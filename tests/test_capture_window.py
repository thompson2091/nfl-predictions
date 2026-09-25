"""The odds-capture guard decides whether a firing spends an API credit.

Two ways to get this wrong, and they are not symmetric. Capturing needlessly
costs one credit. Skipping needlessly loses a price that the API will never
serve again — no closing line, so that game can never testify about edge. Every
test here that involves doubt asserts the guard captures.

    pytest tests/test_capture_window.py -v
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

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


# A 502 from the gateway killed the 2026-09-09 open capture outright, because
# the first cut of `_get` retried timeouts but not HTTP statuses — "an HTTP
# status is an answer". A 5xx is the opposite of an answer, and the same code
# runs the close capture, where the price cannot be re-bought.

def _fake_get(codes, key="SECRET"):
    """A requests.get that returns `codes` in order, last one repeating."""
    import requests
    calls = {"n": 0}

    class R:
        def __init__(self, code):
            self.status_code = code
            self.reason = "Bad Gateway"

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.HTTPError(
                    f"{self.status_code} Error for url: "
                    f"https://api/x?apiKey={key}", response=self)

    def fake(url, params=None, timeout=None):
        i = calls["n"]
        calls["n"] += 1
        return R(codes[min(i, len(codes) - 1)])

    return fake, calls


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_a_transient_server_status_is_retried(status, monkeypatch):
    import requests

    from src.ingest import odds_api

    monkeypatch.setattr(odds_api, "RETRY_BACKOFF", (0.0, 0.0, 0.0))
    fake, calls = _fake_get([status, status, 200])
    monkeypatch.setattr(requests, "get", fake)
    assert odds_api._get("https://api/x", {}, "t").status_code == 200
    assert calls["n"] == 3


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_a_client_error_is_a_real_answer_and_is_not_retried(status, monkeypatch):
    """401 means the key is wrong. Retrying it burns clock before a kickoff."""
    import requests

    from src.ingest import odds_api

    monkeypatch.setattr(odds_api, "RETRY_BACKOFF", (0.0, 0.0, 0.0))
    fake, calls = _fake_get([status])
    monkeypatch.setattr(requests, "get", fake)
    with pytest.raises(requests.HTTPError):
        odds_api._get("https://api/x", {}, "t")
    assert calls["n"] == 1, "a 4xx must not be retried"


def test_the_api_key_never_reaches_a_log_or_an_exception(monkeypatch):
    """`raise_for_status` puts the query string in the message, key included."""
    import requests

    from src.ingest import odds_api

    monkeypatch.setattr(odds_api, "RETRY_BACKOFF", (0.0, 0.0, 0.0))
    monkeypatch.setattr(odds_api, "_get_api_key", lambda: "SUPERSECRETKEY")
    fake, _ = _fake_get([502], key="SUPERSECRETKEY")
    monkeypatch.setattr(requests, "get", fake)
    with pytest.raises(requests.HTTPError) as e:
        odds_api._get("https://api/x", {}, "t")
    assert "SUPERSECRETKEY" not in str(e.value)
    assert "***" in str(e.value)


# The close capture's other silent failure: not a crash, a cache hit.
#
# The TTL was a flat 6 hours for every snapshot, keyed only on the UTC date, so
# Sunday 2026-09-13 would have run 9:00 fresh -> 12:30 HIT -> 15:35 fresh ->
# 19:50 HIT. The close for the 1pm wave would have been the 9:00 price and the
# close for SNF the 15:35 price, each stamped with the time it was asked for and
# each taken before inactives. The archive would look complete either way, which
# is why this needs a test rather than an eye on a log.

def _seed_cache(odds_api, tmp_path, monkeypatch, age_hours: float):
    """A cache file for 2026-09-13, aged `age_hours` by its mtime."""
    import json
    import os
    import time

    monkeypatch.setattr(odds_api, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(odds_api, "_get_api_key", lambda: "TESTKEY")
    path = odds_api._cache_path("2026-09-13")
    path.write_text(json.dumps({"cached": {"home_team": "Seattle Seahawks"}}))
    stamp = time.time() - age_hours * 3600
    os.utime(path, (stamp, stamp))
    return path


def _count_fetches(odds_api, monkeypatch):
    """Stop at the first API call and say whether one was made."""
    calls = {"n": 0}

    def counted(*a, **k):
        calls["n"] += 1
        raise RuntimeError("reached the API")

    monkeypatch.setattr(odds_api, "_get", counted)
    return calls


def test_an_open_capture_may_be_served_from_a_fresh_cache(tmp_path, monkeypatch):
    """The TTL still does its job where it was right: a re-run of the open."""
    from src.ingest import odds_api

    _seed_cache(odds_api, tmp_path, monkeypatch, age_hours=3.5)
    calls = _count_fetches(odds_api, monkeypatch)
    got = odds_api.fetch_week_td_props(week_start="2026-09-13", snapshot="open")
    assert got == {"cached": {"home_team": "Seattle Seahawks"}}
    assert calls["n"] == 0, "a fresh open should not spend a credit"


def test_an_open_capture_past_the_ttl_goes_to_the_api(tmp_path, monkeypatch):
    from src.ingest import odds_api

    _seed_cache(odds_api, tmp_path, monkeypatch, age_hours=6.5)
    calls = _count_fetches(odds_api, monkeypatch)
    with pytest.raises(RuntimeError):
        odds_api.fetch_week_td_props(week_start="2026-09-13", snapshot="open")
    assert calls["n"] == 1


@pytest.mark.parametrize("age_hours", [0.1, 3.5, 4.25, 5.9])
def test_a_close_capture_never_reads_the_cache(age_hours, tmp_path, monkeypatch):
    """3.5h is Sunday's 12:30 slot; 4.25h is the 19:50 one. Both must fetch."""
    from src.ingest import odds_api

    _seed_cache(odds_api, tmp_path, monkeypatch, age_hours)
    calls = _count_fetches(odds_api, monkeypatch)
    with pytest.raises(RuntimeError):
        odds_api.fetch_week_td_props(week_start="2026-09-13", snapshot="close")
    assert calls["n"] == 1, (
        f"a close {age_hours}h after the last fetch was served from cache — "
        "that archives the older price under a fresh captured_at")


def test_a_caller_that_forgets_the_snapshot_spends_a_credit(tmp_path, monkeypatch):
    """The default leans the safe way: a wasted credit, not a falsified close."""
    from src.ingest import odds_api

    _seed_cache(odds_api, tmp_path, monkeypatch, age_hours=1.0)
    calls = _count_fetches(odds_api, monkeypatch)
    with pytest.raises(RuntimeError):
        odds_api.fetch_week_td_props(week_start="2026-09-13")
    assert calls["n"] == 1


def test_a_close_still_writes_the_cache_it_will_not_read():
    """`load_cached_book_quotes` reads that file; the open path reads it too."""
    import inspect

    from src.ingest import odds_api

    src = inspect.getsource(odds_api.fetch_week_td_props)
    body = src.split("ttl = CACHE_TTL_HOURS", 1)[1]
    assert "json.dump" in body or "write_text" in body, \
        "a close that neither reads nor writes the cache strands the book quotes"


def test_the_odds_script_passes_the_snapshot_to_the_fetch():
    """Recording the snapshot is not enough — it has to govern the cache."""
    src = Path("scripts/07_odds.py").read_text()
    call = src.split("fetch_week_td_props(", 1)[1].split(")", 1)[0]
    assert "snapshot=args.snapshot" in call, \
        "07_odds.py archives a snapshot label it did not fetch under"


# The opening capture decides what closing-line value is measured *from*.
# `clv.line_movement` keeps the first captured_at per player-game, so the
# earliest open slot is the one every CLV figure is built on. A single
# Wednesday-noon slot made that a price taken 32 hours before Thursday's
# kickoff.

def _schedule_module():
    """`scripts/25_odds_schedule.py` is a script, not a package module."""
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "25_odds_schedule.py"
    spec = importlib.util.spec_from_file_location("odds_schedule", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_open_is_captured_before_the_backstop():
    mod = _schedule_module()
    slots = mod.open_slots()
    assert len(slots) >= 2, (
        "one open slot means one gateway 502 loses the week's opening line — "
        "which is what happened on 2026-09-09")
    assert slots == sorted(
        slots, key=lambda pr: (mod.WEEKDAYS[pr[0]], mod._minutes(pr[1]))), \
        "open slots must be earliest-first; the first one is the measured open"


def test_no_open_slot_falls_on_a_day_that_still_resolves_to_the_old_week():
    """Monday is unusable, and not because of when books post.

    `weekly_odds.sh` derives the week from the nearest kickoff ahead *by date*,
    so every hour of Monday — 23:30, after Monday night's game has finished,
    included — still returns the week that is ending. A Monday open would file
    next week's prices under this week's number and leave next week with none.
    """
    mod = _schedule_module()
    bad = [s for s in mod.open_slots() if mod.WEEKDAYS[s[0]] in (0, 1, 6)]
    assert not bad, (
        f"open slots {bad} fall on a day carrying live games or resolving to "
        "the outgoing week")


def test_open_slots_falls_back_to_the_single_slot_config():
    """An older settings.yaml must still generate a schedule."""
    mod = _schedule_module()
    got = mod.open_slots({"open_weekday": "Wednesday", "open_time": "12:00"})
    assert got == [("Wednesday", "12:00")]


def test_every_open_slot_precedes_the_season_s_earliest_kickoff_weekday():
    """An open taken after a week's first game has started is not an open."""
    mod = _schedule_module()
    waves = mod.kickoff_waves()
    earliest_game_day = min(mod.WEEKDAYS[d] for d in waves
                            if mod.WEEKDAYS[d] not in (0, 1))
    for day, _t in mod.open_slots():
        assert mod.WEEKDAYS[day] <= earliest_game_day, (
            f"open slot on {day} lands after the week's first kickoff wave")


# ── the public-split capture runs itself ────────────────────────────────

def test_the_public_split_job_is_scheduled_every_day_not_only_on_game_days():
    """THE DRIFT IS THE PART THAT CANNOT BE BOUGHT BACK.

    Anyone can read Sunday's percentage off a website. A side that opened at
    50% and sat at 71% by kickoff is a different fact from one that was at
    71% all week, and neither feed publishes history — so the only copy of
    the path is the one this job makes while it happens.

    A schedule that woke only for kickoffs would capture the destination and
    none of the journey, so the entries carry no Weekday key at all.
    """
    import plistlib
    from pathlib import Path

    p = Path("config/launchd/com.mthompson.nfl-public-money.plist")
    assert p.exists(), "the capture is not scheduled"
    d = plistlib.loads(p.read_bytes())
    slots = d["StartCalendarInterval"]
    assert len(slots) >= 3, f"a few times a day, not {len(slots)}"
    assert not any("Weekday" in s for s in slots), (
        "restricted to certain days; the line opens Tuesday and the money "
        "arrives all week")
    hours = sorted(s["Hour"] for s in slots)
    assert max(hours) - min(hours) >= 8, (
        f"clustered into {max(hours) - min(hours)}h; four reads an hour "
        "apart describe an hour, not a day")


def test_the_public_split_job_runs_the_script_that_captures_both_feeds():
    """One habit, not two. Sportsbook Review has no moneyline and no money
    share; Action Network has both. A job that captured only one would leave
    the other's week unrecoverable."""
    import plistlib
    from pathlib import Path

    d = plistlib.loads(
        Path("config/launchd/com.mthompson.nfl-public-money.plist").read_bytes())
    wrapper = Path(d["ProgramArguments"][0])
    assert wrapper.name == "public_money.sh"
    src = Path("scripts/public_money.sh").read_text()
    assert "57_public_money.py" in src
    runner = Path("scripts/57_public_money.py").read_text()
    assert "action_public" in runner and "public_money import" in runner, (
        "the runner must capture both feeds")


def test_the_wrapper_cannot_rely_on_a_login_shell():
    """launchd hands a job a near-empty environment.

    A wrapper that assumes a profile has run works by hand and silently never
    runs unattended, which is the failure mode that leaves a season with no
    archive and no error.
    """
    from pathlib import Path

    src = Path("scripts/public_money.sh").read_text()
    assert ".venv/bin/python" in src, "the interpreter must be found explicitly"
    assert 'cd "$(dirname "$0")/.."' in src, (
        "the job must set its own working directory")
    assert "mtime" in src, (
        "four runs a day for a season leaves hundreds of logs; prune them")
