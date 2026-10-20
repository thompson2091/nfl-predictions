"""The player board a game kicked off with, and that it stays that one."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from src.export import prediction_freeze as PF

KICKS = {"2026_05_A_B": datetime(2026, 10, 11, 13, 0),
         "2026_05_C_D": datetime(2026, 10, 12, 20, 15)}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Never touch the real archive. It is the only copy of what it holds."""
    monkeypatch.setattr(PF, "ROOT", tmp_path / "predictions")
    monkeypatch.setattr("src.evaluation.tracked_rules.kickoffs",
                        lambda season, week: dict(KICKS))
    PF._CACHE.clear()
    PF._DIRTY.clear()
    yield
    PF._CACHE.clear()
    PF._DIRTY.clear()


def rows(priced=True, p=0.51):
    return [
        {"game_id": "2026_05_A_B", "player_name": "Early Man", "team": "A",
         "probability": p, "prob_model": 0.50, "rank": 1,
         "has_market_price": priced, "book": 0.48},
        {"game_id": "2026_05_C_D", "player_name": "Monday Man", "team": "C",
         "probability": 0.40, "prob_model": 0.39, "rank": 2,
         "has_market_price": priced, "book": 0.37},
    ]


BEFORE = datetime(2026, 10, 11, 9, 0)      # both still to come
BETWEEN = datetime(2026, 10, 11, 18, 0)    # Sunday done, Monday to come
AFTER = datetime(2026, 10, 13, 9, 0)       # both finished


def test_a_board_still_to_kick_off_is_recorded_and_keeps_moving():
    out, served, recorded = PF.settle(rows(), 2026, 5, "anytime_td", BEFORE)
    assert (served, recorded) == (0, 2)
    assert [r["probability"] for r in out] == [0.51, 0.40]

    out, served, recorded = PF.settle(rows(p=0.62), 2026, 5, "anytime_td",
                                      BEFORE)
    assert (served, recorded) == (0, 1)
    assert out[0]["probability"] == 0.62


def test_each_game_freezes_alone_rather_than_the_whole_week():
    """PER GAME, NOT PER WEEK. A week-level freeze would lock Sunday's games
    when Thursday's kicked off, and leave Monday's frozen two days early."""
    PF.settle(rows(), 2026, 5, "anytime_td", BEFORE)

    # Sunday has kicked off; Monday has not. The Sunday row is served from
    # the archive and the Monday one is still being written.
    out, served, recorded = PF.settle(rows(priced=False, p=0.99), 2026, 5,
                                      "anytime_td", BETWEEN)
    assert (served, recorded) == (1, 1)
    by = {r["game_id"]: r for r in out}
    assert by["2026_05_A_B"]["probability"] == 0.51
    assert by["2026_05_A_B"]["has_market_price"] is True
    # Monday's row is the fresh one, not the archive's: it still carries the
    # flag this rebuild gave it.
    assert by["2026_05_C_D"]["has_market_price"] is False


def test_the_price_flag_survives_a_rebuild_after_the_games():
    """THE WHOLE POINT. `has_market_price` is a predict-time flag and the
    live odds cache holds nothing for a finished week, so a board rebuilt
    afterwards reports almost nobody priced — weeks 3 and 4 of 2026 are on
    disk showing 24 of 498 and 47 of 515 because of exactly this."""
    PF.settle(rows(priced=True), 2026, 5, "anytime_td", BEFORE)
    out, served, _ = PF.settle(rows(priced=False), 2026, 5, "anytime_td",
                               AFTER)
    assert served == 2
    assert all(r["has_market_price"] is True for r in out)
    assert all(r["book"] is not None for r in out)


def test_a_started_game_with_nothing_frozen_keeps_the_late_board():
    """A late board beats no board — and the count is reported, because the
    fallback is invisible on the page."""
    out, served, recorded = PF.settle(rows(), 2026, 5, "anytime_td", AFTER)
    assert (served, recorded) == (0, 0)
    assert len(out) == 2
    assert PF.missing(2026, 5, "anytime_td", AFTER) == sorted(KICKS)


def test_a_served_row_cannot_write_back_into_the_archive():
    """`projection_freeze` learned this one: assigning the stored object by
    reference lets an edit downstream mutate the archive in memory."""
    PF.settle(rows(), 2026, 5, "anytime_td", BEFORE)
    PF.flush()
    out, _, _ = PF.settle(rows(), 2026, 5, "anytime_td", AFTER)
    out[0]["probability"] = 404.0
    kept = PF.frozen(2026, 5, "anytime_td")["2026_05_A_B"]
    assert kept[0]["probability"] == 0.51
    assert not PF._DIRTY


def test_it_survives_a_round_trip_to_disk():
    PF.settle(rows(), 2026, 5, "anytime_td", BEFORE)
    written = PF.flush()
    assert written and written[0].exists()
    PF._CACHE.clear()
    kept = PF.frozen(2026, 5, "anytime_td")
    assert set(kept) == set(KICKS)
    assert kept["2026_05_A_B"][0]["player_name"] == "Early Man"


def test_the_two_markets_do_not_overwrite_each_other():
    PF.settle(rows(), 2026, 5, "anytime_td", BEFORE)
    PF.settle(rows(p=0.11), 2026, 5, "first_td", BEFORE)
    assert PF.frozen(2026, 5, "anytime_td")["2026_05_A_B"][0]["probability"] \
        == 0.51
    assert PF.frozen(2026, 5, "first_td")["2026_05_A_B"][0]["probability"] \
        == 0.11


def test_a_corrupt_archive_does_not_take_the_export_down():
    PF.ROOT.mkdir(parents=True, exist_ok=True)
    PF.path(2026).write_text("{not json")
    assert PF.load(2026) == {}


def test_kickoff_is_the_gate_and_an_unreadable_schedule_freezes_nothing(
        monkeypatch):
    """A guard that invents kickoff times is worse than one that never
    fires: it would freeze a board on a game nobody has played."""
    monkeypatch.setattr("src.evaluation.tracked_rules.kickoffs",
                        lambda season, week: {})
    assert PF.started_games(2026, 5, AFTER) == set()
    out, served, recorded = PF.settle(rows(), 2026, 5, "anytime_td", AFTER)
    assert (served, recorded) == (0, 2)


def test_the_archive_is_in_git():
    """What is not regenerable stays in the repository — a Sunday morning's
    board cannot be rebuilt, because what is gone is what a bookmaker was
    offering at the time."""
    import subprocess
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    r = subprocess.run(["git", "check-ignore", "-q", "archive/predictions"],
                       cwd=repo)
    assert r.returncode != 0, "the prediction archive is gitignored"


def test_the_export_cannot_republish_the_week_it_is_reading():
    """Looking at the board is not publishing it. The HTML export runs the
    app against a fake Streamlit, so every export used to be a write."""
    import inspect
    import os

    import app as A
    from src.export import capture

    assert "READ_ONLY_ENV" in dir(capture)
    assert capture.READ_ONLY_ENV in inspect.getsource(A.selected_model_dir)

    was = os.environ.get(capture.READ_ONLY_ENV)
    os.environ[capture.READ_ONLY_ENV] = "1"
    try:
        assert A.selected_model_dir("anytime_td", None) == (None, False)
    finally:
        if was is None:
            os.environ.pop(capture.READ_ONLY_ENV, None)
        else:
            os.environ[capture.READ_ONLY_ENV] = was
    assert A.selected_model_dir("anytime_td", None) == (None, True)



# ── The over/under markets, frozen from 2026-10-09 ─────────────────────────

def ou_rows(model=0.58):
    return [
        {"game_id": "2026_05_A_B", "player_name": "Early Man", "team": "A",
         "point": 55.5, "model_only": model, "ours": 0.53, "fair_prob": 0.50,
         "price_over": -110.0, "price_under": -110.0, "model_side": "over",
         "gap_side": "over", "gap_edge_pp": 3.0, "gap_threshold_pp": 2.5,
         "odds": -110, "ev": 1.2},
        {"game_id": "2026_05_C_D", "player_name": "Monday Man", "team": "C",
         "point": 40.5, "model_only": 0.41, "ours": 0.47, "fair_prob": 0.49,
         "price_over": -105.0, "price_under": -115.0, "model_side": "under",
         "gap_side": None},
    ]


def test_an_over_under_board_keeps_both_prices_and_every_rules_side():
    assert PF.record(ou_rows(), 2026, 5, "rushing_yards", BEFORE) == 2
    kept = PF.frozen(2026, 5, "rushing_yards")["2026_05_A_B"][0]
    for f in ("point", "model_only", "ours", "fair_prob", "price_over",
              "price_under", "model_side", "gap_side", "gap_edge_pp"):
        assert f in kept, f"{f} was not frozen"
    # Display-only fields stay out: the freeze is a record, not a cache.
    assert "ev" not in kept and "odds" not in kept


def test_an_over_under_game_stops_moving_at_its_own_kickoff():
    PF.record(ou_rows(), 2026, 5, "rushing_yards", BEFORE)
    PF.record(ou_rows(model=0.70), 2026, 5, "rushing_yards", BETWEEN)
    kept = PF.frozen(2026, 5, "rushing_yards")
    assert kept["2026_05_A_B"][0]["model_only"] == 0.58, (
        "Sunday's game kicked off and was rewritten after it")
    assert PF.missing(2026, 5, "rushing_yards", BETWEEN) == []


def test_the_touchdown_fields_are_unchanged_by_the_over_under_ones():
    assert PF.fields_for("anytime_td") == PF.FIELDS
    assert PF.fields_for("receptions") == PF.OU_FIELDS


def test_serve_started_swaps_in_the_frozen_board_and_records_nothing(monkeypatch):
    import polars as pl
    from src.export import prediction_freeze as PF

    monkeypatch.setattr(PF, "frozen", lambda s, w, m: {
        "g1": [{"player_name": "A", "team": "X", "probability": 0.862}]})
    monkeypatch.setattr(PF, "started_games", lambda s, w, now=None: {"g1"})
    monkeypatch.setattr(PF, "record", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("serve_started must not record")))
    df = pl.DataFrame({"game_id": ["g1", "g2"], "player_name": ["A", "B"],
                       "team": ["X", "Y"], "probability": [0.968, 0.4],
                       "extra": [1.0, 2.0]})
    out = PF.serve_started(df, 2026, 6, "anytime_td").sort("game_id")
    assert out["probability"].to_list() == [0.862, 0.4]
    assert out["extra"].to_list() == [None, 2.0]
