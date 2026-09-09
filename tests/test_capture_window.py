"""The odds-capture guard decides whether a firing spends an API credit.

Two ways to get this wrong, and they are not symmetric. Capturing needlessly
costs one credit. Skipping needlessly loses a price that the API will never
serve again — no closing line, so that game can never testify about edge. Every
test here that involves doubt asserts the guard captures.

    pytest tests/test_capture_window.py -v
"""
from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest

from src.ingest.capture_window import (kickoffs, should_capture, window_for)

CFG = {"open_window_days": 7, "close_window_hours": 4}


def schedule(*rows: tuple[str, str]) -> pl.DataFrame:
    return pl.DataFrame({"gameday": [r[0] for r in rows],
                         "gametime": [r[1] for r in rows]})


def test_captures_when_kickoff_is_inside_the_window():
    s = schedule(("2026-09-13", "13:00"))
    now = datetime(2026, 9, 13, 12, 30)
    capture, why = should_capture("close", now, s, CFG)
    assert capture, why
    assert "capturing" in why


def test_skips_when_the_next_kickoff_is_days_away():
    """The regression that made this worth building: an off-season firing."""
    s = schedule(("2026-09-13", "13:00"))
    now = datetime(2026, 8, 13, 12, 0)
    capture, why = should_capture("close", now, s, CFG)
    assert not capture
    assert "no credits spent" in why


def test_the_open_window_is_days_not_hours():
    """`open` is a weekly slot, so it must tolerate a kickoff days out."""
    s = schedule(("2026-09-13", "13:00"))
    now = datetime(2026, 9, 9, 12, 0)  # four days ahead
    assert should_capture("close", now, s, CFG)[0] is False
    assert should_capture("open", now, s, CFG)[0] is True
    assert window_for("open", CFG) > window_for("close", CFG)


def test_a_started_game_does_not_hold_the_window_open():
    """Kickoffs in the past are gone from the API and must not count.

    Otherwise a Sunday-evening firing would 'capture' on the strength of the
    1pm games it can no longer buy, and skip the games it still can.
    """
    s = schedule(("2026-09-13", "13:00"), ("2026-09-14", "20:15"))
    now = datetime(2026, 9, 13, 16, 0)  # 1pm gone, Monday 20:15 is 28h out
    capture, why = should_capture("close", now, s, CFG)
    assert not capture
    assert "2026-09-14 20:15" in why


def test_the_nearest_kickoff_governs_not_the_first_row():
    """Rows are not ordered by kickoff in the real schedule."""
    s = schedule(("2026-12-25", "13:00"), ("2026-09-13", "13:00"))
    now = datetime(2026, 9, 13, 12, 45)
    assert should_capture("close", now, s, CFG)[0] is True


def test_an_unreadable_schedule_captures_rather_than_skips():
    """Doubt resolves toward spending a credit, never toward losing a price."""
    capture, why = should_capture("close", datetime(2026, 9, 13, 12, 45),
                                  pl.DataFrame({"nonsense": [1]}), CFG)
    assert capture
    assert "capturing anyway" in why


def test_one_malformed_row_does_not_decide_the_week():
    s = schedule(("2026-09-13", "not-a-time"), ("2026-09-13", "13:00"))
    assert kickoffs(s) == [datetime(2026, 9, 13, 13, 0)]
    assert should_capture("close", datetime(2026, 9, 13, 12, 45), s, CFG)[0]


def test_no_kickoffs_ahead_is_a_skip_not_a_crash():
    """The off-season, and the week after the Super Bowl."""
    s = schedule(("2026-09-13", "13:00"))
    capture, why = should_capture("close", datetime(2027, 3, 1, 12, 0), s, CFG)
    assert not capture
    assert "nothing to capture" in why


@pytest.mark.parametrize("lead_minutes", [0, 30, 59])
def test_the_window_covers_the_generated_lead_time(lead_minutes):
    """The slots fire `lead_minutes` before kickoff; the window must reach.

    If the close window were ever configured below the lead time, every
    generated slot would fire and immediately skip — a schedule that looks
    installed and captures nothing.
    """
    s = schedule(("2026-09-13", "13:00"))
    now = datetime(2026, 9, 13, 13, 0) - timedelta(minutes=lead_minutes)
    assert should_capture("close", now, s, CFG)[0] is True


# ── The request itself ────────────────────────────────────────────────────
# The guard above decides whether to call the API. These decide that the call
# comes back. On 2026-09-02 the unattended `open` firing reached the API with
# no timeout set, established two connections and held them for six days —
# which cost far more than the one snapshot, because both odds jobs are single
# launchd jobs carrying many StartCalendarInterval entries and launchd will not
# start a job whose previous instance has not exited. One hung firing silently
# swallows every remaining slot of the week.

def test_every_request_in_the_odds_client_passes_a_timeout():
    """No bare `requests.get` may reach the API.

    An AST check rather than a mock, because the failure is a missing keyword
    argument at a call site — a new call added later is exactly the thing that
    would reintroduce it, and a mock of the existing path would not see it.
    """
    import ast
    import inspect

    from src.ingest import odds_api

    tree = ast.parse(inspect.getsource(odds_api))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr in {"get", "post"}
                and isinstance(f.value, ast.Name) and f.value.id == "requests"):
            continue
        if not any(k.arg == "timeout" for k in node.keywords):
            offenders.append(node.lineno)

    assert not offenders, (
        f"requests call without a timeout at odds_api.py line(s) {offenders}. "
        "`requests` defaults to waiting forever, and a socket that dies without "
        "an RST — a laptop sleeping mid-request — then holds the launchd slot "
        "for every remaining capture of the week. Route it through `_get`."
    )


def test_a_timeout_is_retried_rather_than_dropping_the_game():
    """A transient timeout must not silently cost a game's prices.

    The per-event call carries the actual prices and its caller catches and
    continues, so without a retry one slow response becomes a hole in the
    archive that nothing reports.
    """
    import requests

    from src.ingest.odds_api import HTTP_RETRIES, _get

    calls = {"n": 0}

    class Resp:
        status_code = 200

        def raise_for_status(self):
            return None

    def flaky(url, params=None, timeout=None):
        calls["n"] += 1
        assert timeout is not None, "timeout must be passed through"
        if calls["n"] <= HTTP_RETRIES:
            raise requests.Timeout("stalled")
        return Resp()

    real = requests.get
    requests.get = flaky
    try:
        assert _get("https://example.invalid", {}, "test").status_code == 200
    finally:
        requests.get = real
    assert calls["n"] == HTTP_RETRIES + 1


def test_a_persistent_timeout_raises_rather_than_hanging():
    """When retries are exhausted the capture fails loudly and the job exits."""
    import requests

    from src.ingest.odds_api import HTTP_RETRIES, _get

    calls = {"n": 0}

    def always_timeout(url, params=None, timeout=None):
        calls["n"] += 1
        raise requests.Timeout("stalled")

    real = requests.get
    requests.get = always_timeout
    try:
        with pytest.raises(requests.Timeout):
            _get("https://example.invalid", {}, "test")
    finally:
        requests.get = real
    assert calls["n"] == HTTP_RETRIES + 1
