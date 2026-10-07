"""The weekly shortlist, and the log that scores real bets against the close.

Both exist because every other measurement in this project is a replay. These
are the two surfaces that touch a decision — what to consider this week, and
whether the price you got was any good — so the failure modes are different
from the rest of the suite:

  * A filter built on a measurement taken over a *different population*. Price
    bands are measured over every bet including the ones the screen vetoes, so
    using them to drop rows composes two answers that were never about the same
    players — and on anytime TD it would empty every week by construction.
  * A CLV sign that is backwards. Positive has to mean *you* got the better of
    it, or a log of good bets reads as a log of bad ones and the number that is
    supposed to detect an edge points at the floor.

    pytest tests/test_shortlist_and_betlog.py -v
"""
from __future__ import annotations

import polars as pl
import pytest

from src.evaluation import betlog
from src.evaluation.shortlist import (clv_band, clv_floor,
                                      price_bucket, shortlist)


def clv(*bands) -> dict:
    return {"by_edge": list(bands)}


def band(side, lo, hi, move, n=500, hit=0.5) -> dict:
    return {"side": side, "lo": lo, "hi": hi, "n": n,
            "moved_our_way": hit, "mean_move_pp": move}


def board(rows: list[dict]) -> pl.DataFrame:
    base = {"player_name": "A", "team": "X", "game_label": "X @ Y",
            "prob_bet": 0.4, "market_prob": 0.3, "model_edge_pp": 10.0,
            "odds": 200.0, "bet_rank": 1, "player_name_norm": "a"}
    return pl.DataFrame([{**base, **r} for r in rows])


# ── The floor ──────────────────────────────────────────────────────────────


def test_the_floor_is_the_smallest_band_the_market_has_not_moved_against():
    c = clv(band("higher", 0, 2, -0.05), band("higher", 2, 5, -0.08),
            band("higher", 5, 10, -0.04), band("higher", 10, None, +0.24))
    assert clv_floor(c)["lo"] == 10


def test_no_band_on_the_bettable_side_is_a_real_answer():
    """First TD gives exactly this, and it has to survive as `None`.

    Every band on the side these markets sell is negative there: the closing
    line walks away from the players we like, whatever the size of the
    disagreement. A screen that quietly fell back to "no filter" would turn
    that into a full card.
    """
    c = clv(band("higher", 0, 2, -0.19), band("higher", 2, None, -0.28),
            band("lower", 0, None, +0.67))
    assert clv_floor(c) is None
    out = shortlist(board([{}]), target_type="first_td", clv=c, econ=None)
    assert out["rows"] == []
    assert "closing-line value" in out["dropped"][-1]["filter"]


def test_a_thin_band_cannot_set_the_floor():
    """Fifty observations of a positive drift is not a license to bet."""
    c = clv(band("higher", 0, 2, -0.20, n=5000),
            band("higher", 2, None, +0.30, n=40))
    assert clv_floor(c) is None


def test_a_pick_is_read_against_the_band_it_falls_in():
    c = clv(band("higher", 0, 2, -0.05), band("higher", 2, 10, -0.08),
            band("higher", 10, None, +0.24))
    assert clv_band(c, 1.0)["lo"] == 0
    assert clv_band(c, 9.9)["lo"] == 2
    assert clv_band(c, 10.0)["lo"] == 10
    assert clv_band(c, 40.0)["hi"] is None


# ── The screen ─────────────────────────────────────────────────────────────


def test_a_player_we_rate_under_the_price_is_never_on_the_card():
    """These markets sell Yes only, so the other side is not a bet at all."""
    c = clv(band("higher", 0, None, +0.1))
    out = shortlist(board([{"model_edge_pp": -12.0}, {"model_edge_pp": +12.0}]),
                 target_type="anytime_td", clv=c, econ=None)
    assert len(out["rows"]) == 1
    assert out["dropped"][0]["dropped"] == 1
    assert "veto" in out["dropped"][0]["filter"]


def test_the_price_band_is_context_and_never_removes_a_row():
    """The measurement it comes from covers a different population.

    `rank_economics` measures every bet in a band, vetoed players included —
    two thirds of the board. Dropping rows on it composes two answers about
    different populations, and since every anytime-TD band is negative it would
    empty the card every week by construction, which is a rule that has stopped
    reading its input.
    """
    econ = {"by_odds_bucket": [
        {"bucket": "+100-300", "n": 5370, "roi": -12.7, "lo": -16.2,
         "hi": -9.2, "verdict": "negative"}]}
    c = clv(band("higher", 0, None, +0.1))
    out = shortlist(board([{"odds": 200.0}]), target_type="anytime_td",
                 clv=c, econ=econ)
    assert len(out["rows"]) == 1, "a negative band must not drop the row"
    row = out["rows"][0]
    assert row["band"] == "+100-300" and row["band_roi"] == -12.7
    assert all("price band" not in d["filter"] for d in out["dropped"])


def test_the_screen_says_which_measurement_emptied_it():
    """An empty card is the answer; an empty card with no reason is a bug."""
    c = clv(band("higher", 0, 10, -0.05), band("higher", 10, None, +0.24))
    out = shortlist(board([{"model_edge_pp": 3.0}]), target_type="anytime_td",
                 clv=c, econ=None)
    assert out["rows"] == []
    assert out["note"]
    assert out["dropped"][-1]["dropped"] == 1


def test_the_best_available_price_rides_along_when_it_exists():
    c = clv(band("higher", 0, None, +0.1))
    shopped = pl.DataFrame([{"player_name_norm": "a", "best_odds": 280,
                             "best_book": "draftkings", "gap_pp": 1.33}])
    out = shortlist(board([{}]), target_type="anytime_td", clv=c, econ=None,
                 shopped=shopped)
    r = out["rows"][0]
    assert (r["best_odds"], r["best_book"]) == (280, "draftkings")
    assert r["shopped_pp"] == pytest.approx(1.33)


def test_price_bucket_reads_its_edges_off_the_artifact():
    econ = {"by_odds_bucket": [{"bucket": "<+100"}, {"bucket": "+100-300"},
                               {"bucket": "+300-700"}, {"bucket": "+1500up"}]}
    assert price_bucket(-130, econ) == "<+100"
    assert price_bucket(200, econ) == "+100-300"
    assert price_bucket(650, econ) == "+300-700"
    assert price_bucket(2000, econ) == "+1500up"


# ── The bet log ────────────────────────────────────────────────────────────


def test_implied_probability_both_ways_round():
    assert betlog._implied(100) == pytest.approx(0.5)
    assert betlog._implied(-200) == pytest.approx(2 / 3)
    assert betlog._implied(300) == pytest.approx(0.25)
    assert betlog._implied(None) is None


def test_positive_clv_means_you_got_the_better_of_the_close(tmp_path, monkeypatch):
    """The sign that matters. Backwards, it points a good log at the floor."""
    log = tmp_path / "bets.csv"
    betlog.record({"placed_on": "2026-09-13", "season": 2026, "week": 1,
                   "market": "anytime_td", "player": "Saquon Barkley",
                   "book": "draftkings", "odds": -120, "stake": 25.0,
                   "note": ""}, path=log)
    monkeypatch.setattr(betlog, "_closes", lambda market: pl.DataFrame(
        [{"season": 2026, "week": 1, "player_name_norm": "saquon barkley",
          "close_odds": -210.0}]))
    s = betlog.score(path=log)
    assert s["scored"] == 1
    # Took 54.5%, closed 67.7%: the market came 13pp our way after we bet.
    assert s["mean_clv_pp"] == pytest.approx(13.2, abs=0.1)
    assert s["beat_close_pct"] == 1.0


def test_a_bet_with_no_archived_close_is_reported_not_dropped(tmp_path, monkeypatch):
    """Otherwise the average quietly describes whatever happened to join."""
    log = tmp_path / "bets.csv"
    betlog.record({"placed_on": "2026-09-13", "season": 2026, "week": 1,
                   "market": "anytime_td", "player": "Nobody At All",
                   "book": "fanduel", "odds": 450, "stake": 10.0,
                   "note": ""}, path=log)
    monkeypatch.setattr(betlog, "_closes", lambda market: pl.DataFrame(
        [{"season": 2026, "week": 1, "player_name_norm": "someone else",
          "close_odds": -110.0}]))
    s = betlog.score(path=log)
    assert (s["n"], s["scored"], s["unmatched"]) == (1, 0, 1)
    assert s["mean_clv_pp"] is None and s["note"]


def test_two_bets_on_one_player_are_two_bets(tmp_path):
    """Same player at two books is a normal thing to have done."""
    log = tmp_path / "bets.csv"
    row = {"placed_on": "2026-09-13", "season": 2026, "week": 1,
           "market": "anytime_td", "player": "Kyren Williams",
           "book": "draftkings", "odds": -120, "stake": 25.0, "note": ""}
    betlog.record(row, path=log)
    betlog.record({**row, "book": "williamhill_us", "odds": -115}, path=log)
    assert betlog.load(log).height == 2


def test_a_bet_needs_the_fields_that_make_it_measurable(tmp_path):
    with pytest.raises(ValueError):
        betlog.record({"season": 2026, "week": 1, "market": "anytime_td",
                       "player": "A", "stake": 10.0}, path=tmp_path / "b.csv")


# ── The replay ─────────────────────────────────────────────────────────────


def _clv_rows(*specs) -> pl.DataFrame:
    """Rows shaped like `clv.hit_rows`, for fitting a floor from."""
    rows = []
    for season, moved, n in specs:
        rows += [{"season": season, "prob_calibrated": 0.30, "open_fair": 0.20,
                  "we_are_higher": True, "hit": moved,
                  "move": 0.02 if moved else -0.02} for _ in range(n)]
    return pl.DataFrame(rows)


def test_the_floor_is_fitted_on_earlier_seasons_only(monkeypatch):
    """A threshold graded on the data that chose it is not evidence.

    The first season on record has nothing before it and must be absent from
    the mapping entirely — screening it with its own answer is exactly the
    hindsight this replay exists to avoid.
    """
    from src.evaluation import shortlist_backtest as sb

    rows = _clv_rows((2023, True, 600), (2024, False, 600))
    monkeypatch.setattr(sb, "published_predictions", lambda tt: rows)
    monkeypatch.setattr(sb, "hit_rows", lambda preds, tt: rows)

    floors = sb.floors_by_season("anytime_td")
    assert 2023 not in floors, "the first season cannot screen itself"
    assert floors[2024] is not None, "2024 is screened by 2023, which was positive"


def test_a_season_whose_history_says_no_is_a_stand_down_not_a_gap(monkeypatch):
    """First TD gives this: no band on the bettable side ever qualifies.

    Keyed with a `None` floor rather than dropped, so the replay can say the
    rule bet nothing that year. Dropping the season instead would hide a rule
    declining to play behind a rule with no data.
    """
    from src.evaluation import shortlist_backtest as sb

    rows = _clv_rows((2023, False, 600), (2024, False, 600))
    monkeypatch.setattr(sb, "published_predictions", lambda tt: rows)
    monkeypatch.setattr(sb, "hit_rows", lambda preds, tt: rows)
    floors = sb.floors_by_season("first_td")
    assert 2024 in floors and floors[2024] is None


def test_each_arm_is_the_one_above_it_plus_a_filter():
    """Otherwise the difference between two rows is not what a filter bought."""
    import numpy as np
    import pandas as pd

    from src.evaluation.shortlist_backtest import _bets

    board = pd.DataFrame({"prob_bet": [0.40, 0.30, 0.10],
                          "market_prob": [0.20, 0.29, 0.30]})
    masks = _bets(board, {"lo": 5.0}, {"lo": 15.0})
    assert list(masks["all priced"]) == [True, True, True]
    assert list(masks["we rate higher"]) == [True, True, False]
    assert list(masks["shortlist"]) == [True, False, False]
    assert list(masks["shortlist (hindsight)"]) == [True, False, False]
    for arm in ("we rate higher", "shortlist"):
        assert np.all(masks[arm] <= masks["all priced"])


def test_a_price_improvement_is_a_proportion_and_not_a_flat_point():
    """Flat points break at long odds, and they broke loudly.

    Taking 1.5 points of implied probability off a 2% first-TD longshot leaves
    0.5% — a price four times longer, which is an arithmetic accident rather
    than a shopped quote, and it printed a +554% return before this was fixed.
    """
    import numpy as np

    from src.evaluation.shortlist_backtest import SHOPPING_REL, shopped_returns

    assert all(0 < r < 1 for r in SHOPPING_REL), "relative, not points"
    dec = np.full(50, 50.0)              # a 2% shot at +4900...
    won = np.array([1.0] + [0.0] * 49)   # ...that came in once in fifty
    for r in shopped_returns(dec, won):
        assert -1.0 < r["roi"] / 100 < 0.3, r
        assert r["mean_pp"] < 1.0, "2% of a 2% price is a fifth of a point"


# ── Rules under observation ────────────────────────────────────────────────


def test_a_tracked_rule_carries_where_it_came_from():
    """A band with no provenance reads as a recommendation.

    Every field here is printed beside the picks on both surfaces: what the
    rule is, the search that found it, the control that says the search is not
    the whole story, and the out-of-sample record that says it is not settled.
    """
    from src.evaluation.tracked_rules import RULES

    assert RULES, "the module exists to hold at least one"
    for r in RULES:
        # The shape depends on the side: a lay is bounded by the book's own
        # number and a ratio, a back by the posted price and a points gap.
        shape = (("min_book_pct", "max_book_pct", "max_ratio")
                 if r.get("kind") == "lay"
                 else ("threshold_pp",) if r.get("kind") == "prop_edge"
                 else ("min_odds", "max_odds", "min_edge_pp"))
        for k in ("name", "market", "status", "found", "control",
                  "out_of_sample") + shape:
            assert r.get(k), f"{r.get('name')} is missing {k}"
        assert "unproven" in r["status"], (
            "a tracked rule must say so on its own row, not only in a docstring")


def test_a_tracked_rule_picks_on_the_pre_blend_edge():
    """The blend pulls our number toward the price it is compared against.

    The replay that found this rule measured the pre-blend edge, so a live pick
    on the blended one would be a different rule wearing the same name.
    """
    from src.evaluation.tracked_rules import picks

    rule = {"name": "t", "min_odds": 300, "max_odds": 700, "min_edge_pp": 5.0}
    board = pl.DataFrame([
        # In band, big enough edge: a pick.
        {"player_name": "In", "team": "A", "game_label": "A @ B",
         "odds": 400.0, "prob_bet": 0.25, "market_prob": 0.18,
         "model_edge_pp": 7.0},
        # Same edge, price outside the band.
        {"player_name": "Long", "team": "A", "game_label": "A @ B",
         "odds": 900.0, "prob_bet": 0.17, "market_prob": 0.10,
         "model_edge_pp": 7.0},
        # In band, edge under the floor.
        {"player_name": "Thin", "team": "A", "game_label": "A @ B",
         "odds": 400.0, "prob_bet": 0.21, "market_prob": 0.18,
         "model_edge_pp": 3.0},
    ])
    got = picks(board, rule)
    assert [p["player"] for p in got] == ["In"]
    assert got[0]["edge_pp"] == pytest.approx(7.0)


def test_recording_a_week_twice_does_not_double_the_record(tmp_path):
    """A record that can be inflated by re-running the report is not a record.

    `allow_late` because these are weeks that have long since been played and
    this is a test about DEDUPLICATION. The timing guard is a separate
    concern with its own tests below, and saying so here keeps one from
    quietly standing in for the other.
    """
    from src.evaluation.tracked_rules import load, record

    log = tmp_path / "tracked.csv"
    rows = [{"rule": "t", "player": "A", "team": "X", "game": "X @ Y",
             "odds": 400, "ours": 0.25, "book": 0.18, "edge_pp": 7.0}]
    first = record(rows, season=2026, week=1, market="anytime_td",
                   recorded_on="2026-09-10", path=log, allow_late=True)
    again = record(rows, season=2026, week=1, market="anytime_td",
                   recorded_on="2026-09-11", path=log, allow_late=True)
    assert (first, again) == (1, 0)
    assert load(log).height == 1
    # A different week is a different observation, not a duplicate.
    assert record(rows, season=2026, week=2, market="anytime_td",
                  recorded_on="2026-09-17", path=log, allow_late=True) == 1


def test_a_week_with_no_picks_is_part_of_the_record():
    """Silence has to be visible, or the rule looks like it never misses."""
    from src.evaluation.shortlist import shortlist

    board = pl.DataFrame([{"player_name": "A", "team": "X", "game_label": "X @ Y",
                           "odds": 400.0, "prob_bet": 0.20, "market_prob": 0.19,
                           "model_edge_pp": 1.0, "player_name_norm": "a",
                           "bet_rank": 1}])
    out = shortlist(board, target_type="anytime_td",
                    clv={"by_edge": [band("higher", 0, None, +0.1)]}, econ=None)
    assert out["tracked"], "the rule must appear even when it names nobody"
    assert out["tracked"][0]["picks"] == []


def test_a_lay_is_scored_the_other_way_up(tmp_path, monkeypatch):
    """Backing and laying want opposite movement, and one sign cannot serve both.

    The archive holds the Yes price only. Backing a player, a shorter close is
    good; laying him, a drifting close is good — it is the market coming round
    to his being overrated. Scored with one sign, the fade rule's best weeks
    read as its worst.
    """
    from src.evaluation import betlog

    log = tmp_path / "bets.csv"
    row = {"placed_on": "2026-09-13", "season": 2026, "week": 1,
           "market": "anytime_td", "player": "Some Guy", "book": "novig",
           "odds": 600, "stake": 10.0, "note": ""}
    betlog.record({**row, "side": "yes"}, path=log)
    betlog.record({**row, "player": "Other Guy", "side": "no"}, path=log)
    monkeypatch.setattr(betlog, "_closes", lambda market: pl.DataFrame([
        # Both drifted from +600 to +900: worse for the backer, better for the layer.
        {"season": 2026, "week": 1, "player_name_norm": "some guy",
         "close_odds": 900.0},
        {"season": 2026, "week": 1, "player_name_norm": "other guy",
         "close_odds": 900.0},
    ]))
    got = {r["player"]: r["clv_pp"] for r in betlog.score(path=log)["rows"]}
    assert got["Some Guy"] < 0, "a drifting price is bad for a back"
    assert got["Other Guy"] > 0, "the same drift is good for a lay"
    assert got["Some Guy"] == pytest.approx(-got["Other Guy"])


def test_an_unknown_side_is_refused(tmp_path):
    from src.evaluation import betlog

    with pytest.raises(ValueError):
        betlog.record({"season": 2026, "week": 1, "market": "anytime_td",
                       "player": "A", "odds": 100, "stake": 1.0,
                       "side": "maybe"}, path=tmp_path / "b.csv")


def test_the_fade_rule_is_scored_as_a_lay():
    """The rule that most needs the flip is the one that has it."""
    from src.evaluation.tracked_rules import RULES

    fade = [r for r in RULES if r.get("kind") == "lay"]
    assert fade, "the fade rule is a lay and has to say so"
    assert all(r["market"] == "anytime_td" for r in fade), (
        "first TD failed its own permutation control (p = 0.105) and must not "
        "be tracked as though it had passed")


def test_the_records_can_be_moved_out_of_the_way(monkeypatch, tmp_path):
    """`NFL_RECORDS_DIR` relocates both irreplaceable files.

    The rehearsal has to drive the real scripts to prove the chain runs, and a
    rehearsal that appended August prices as week 1's tracked picks would
    corrupt the one record the forward test is being built to hold. Pinned
    because the override is read once at import, which is the kind of thing a
    later refactor silently loses.
    """
    import importlib

    monkeypatch.setenv("NFL_RECORDS_DIR", str(tmp_path / "scratch"))
    for name in ("src.utils.paths", "src.evaluation.betlog",
                 "src.evaluation.tracked_rules"):
        importlib.reload(importlib.import_module(name))
    from src.evaluation.betlog import LOG_PATH
    from src.evaluation.tracked_rules import PICKS_PATH

    assert LOG_PATH.parent == tmp_path / "scratch"
    assert PICKS_PATH.parent == tmp_path / "scratch"

    monkeypatch.delenv("NFL_RECORDS_DIR")
    for name in ("src.utils.paths", "src.evaluation.betlog",
                 "src.evaluation.tracked_rules"):
        importlib.reload(importlib.import_module(name))
    from src.evaluation.betlog import LOG_PATH as back
    assert back.parent.name == "data"


# ── Grading the tracked rules on results ──────────────────────────────────
#
# `score` measured closing-line value and nothing else for as long as it
# existed, while its own docstring promised "closing-line value first, then
# results" and described a `graded` block that was never written. An empty
# result therefore read as "the week has not finished yet" when it meant "this
# never grades anything" — the same shape as the first-TD unpriced view, an
# absence wearing the clothes of a pending state.

def test_an_unplayed_week_is_not_graded_as_a_week_everyone_lost():
    """The gate the whole thing rests on.

    A week with no play-by-play carries `target = 0` on every candidate, so
    grading it scores every back pick as a loss and every lay as a win. That is
    not a bad week and not a good one; it is no week, and the only thing that
    separates the two is whether the games were played.
    """
    from src.evaluation import tracked_rules

    played = tracked_rules._played_weeks(2026)
    assert played, "2026 has play-by-play on disk; the gate should see it"

    import polars as pl
    from src.utils.paths import get_path

    feats = get_path("processed", "anytime_td") / "features.parquet"
    if not feats.exists():
        pytest.skip("no feature matrix on disk")
    built = set((pl.scan_parquet(feats)
                 .filter(pl.col("season") == 2026)
                 .select("week").unique().collect())["week"].to_list())
    unplayed = built - played
    assert unplayed, "expected at least one built-but-unplayed week to guard"

    res = tracked_rules.score("anytime_td")
    if res is None:
        pytest.skip("no tracked picks recorded")
    for rule, r in res["rules"].items():
        g = r.get("graded")
        if g:
            assert g["weeks"] <= len(played), (
                f"{rule} graded {g['weeks']} weeks against {len(played)} played")


def test_a_lay_is_scored_the_other_way_up():
    """Right means the player did NOT score, and the return says so."""
    from src.evaluation.tracked_rules import _pnl

    # Laying a 10% player: he stays out and it pays 1, he scores and it costs
    # nine — the de-vigged price, which is the only price a No side has.
    assert _pnl("lay", took_prob=0.05, fair_prob=0.10, scored=0) == 1.0
    assert _pnl("lay", 0.05, 0.10, 1) == pytest.approx(-9.0)
    # Backing the same price is the ordinary way round.
    assert _pnl("back", 0.10, 0.10, 1) == pytest.approx(9.0)
    assert _pnl("back", 0.10, 0.10, 0) == -1.0


def test_the_lay_return_is_the_one_the_fade_measurement_already_uses():
    """Two formulas for this would be two claims wearing one name."""
    import numpy as np

    from src.evaluation.tracked_rules import _pnl

    for p in (0.04, 0.07, 0.11, 0.25):
        for scored in (0, 1):
            theirs = float(np.where(scored == 1, -(1.0 - p) / p, 1.0))
            assert _pnl("lay", None, p, scored) == pytest.approx(theirs), p


def test_a_pick_with_no_outcome_is_left_out_rather_than_counted_as_a_loss():
    from src.evaluation.tracked_rules import _pnl

    assert _pnl("back", 0.10, 0.10, None) is None
    assert _pnl("lay", 0.10, None, 0) is None, (
        "a lay with no de-vigged price has no price to lay at")


# ── A tracked pick is a forward test, and the clock starts at the open ──

def test_nothing_is_recorded_once_the_week_has_kicked_off(tmp_path,
                                                          monkeypatch):
    """`week_rollover.sh` runs the shortlist unconditionally, which is right
    while it only ever runs Tuesday to Thursday.

    A forced rebuild on a Sunday morning breaks that assumption: on
    2026-10-04 one wrote thirteen week-4 picks at game-day prices into a set
    whose premise is the price you could have acted on days earlier. Every row
    was honest — before its own kickoff, none on the game already played — and
    still the wrong kind of row, with hours of lead time where the rest of the
    set has days.
    """
    from src.evaluation import tracked_rules as T

    monkeypatch.setattr(T, "week_has_started", lambda s, w, now=None: True)
    p = tmp_path / "picks.csv"
    rows = [{"rule": "r", "player": "A Player", "game": "A @ B", "team": "A",
             "odds": 300, "ours": 0.3, "book": 0.25, "edge_pp": 5.0}]
    assert T.record(rows, season=2026, week=4, market="anytime_td",
                    recorded_on="2026-10-04", path=p) == 0
    assert not p.exists(), "it wrote a file for a week already under way"


def test_a_backfill_can_say_it_means_it(tmp_path, monkeypatch):
    from src.evaluation import tracked_rules as T

    monkeypatch.setattr(T, "week_has_started", lambda s, w, now=None: True)
    p = tmp_path / "picks.csv"
    rows = [{"rule": "r", "player": "A Player", "game": "A @ B", "team": "A",
             "odds": 300, "ours": 0.3, "book": 0.25, "edge_pp": 5.0}]
    assert T.record(rows, season=2026, week=4, market="anytime_td",
                    recorded_on="2026-10-04", path=p, allow_late=True) == 1


def test_the_clock_is_the_weeks_first_kickoff():
    """Week 4 of 2026 opens on Thursday night, so Friday is already late."""
    from datetime import datetime

    from src.evaluation import tracked_rules as T

    kick = T.first_kickoff(2026, 4)
    assert kick == datetime(2026, 10, 1, 20, 15), kick
    assert not T.week_has_started(2026, 4, now=datetime(2026, 9, 30, 12, 0))
    assert T.week_has_started(2026, 4, now=datetime(2026, 10, 4, 9, 0))


def test_an_unreadable_schedule_records_rather_than_going_quiet(monkeypatch):
    """A guard that silently stops recording is worse than one that never
    fires: the week would pass with an empty record and nothing said."""
    from src.evaluation import tracked_rules as T

    monkeypatch.setattr(T, "first_kickoff", lambda s, w: None)
    assert T.week_has_started(2026, 4) is False


#: Every number that defines a tracked rule, pinned by the name it was
#: recorded under. `tracked_picks.csv` keys its history on `name` and nothing
#: else, so changing a threshold without changing the name files two
#: different rules under one label and grades them as one record.
#: Keyed on (name, market), because the prop edge rule carries ONE name
#: across four markets — `tracked_picks.csv` keys on the market too, so the
#: pair is what identifies a rule's record.
TRACKED_RULE_DEFINITIONS = {
    ("fade the overpriced", "anytime_td"): {
        "kind": "lay",
        "min_book_pct": 4.26, "max_book_pct": 11.20, "max_ratio": 1 / 3,
    },
    ("mid-price disagreement", "anytime_td"): {
        "kind": "back",
        "min_odds": 300, "max_odds": 700, "min_edge_pp": 5.0,
    },
    ("prop edge over threshold", "receptions"): {
        "kind": "prop_edge", "threshold_pp": 5.5},
    ("prop edge over threshold", "receiving_yards"): {
        "kind": "prop_edge", "threshold_pp": 6.0},
    ("prop edge over threshold", "rushing_yards"): {
        "kind": "prop_edge", "threshold_pp": 2.5},
    ("prop edge over threshold", "passing_yards"): {
        "kind": "prop_edge", "threshold_pp": 9.0},
}


def test_a_tracked_rule_cannot_be_retuned_without_being_renamed():
    """THE FAILURE A FORWARD TEST CANNOT SURVIVE, and it leaves no trace.

    This module's own docstring is explicit: "A rule that keeps being
    re-tuned can never fail that way, because every failure is absorbed into
    the next tuning." The record in `tracked_picks.csv` is keyed on `name`
    alone, so moving `min_edge_pp` from 5.0 to 4.0 does not start a new
    experiment — it silently merges the new rule's picks into the old one's
    record and reports the pair as one number.

    Nothing about that is visible afterwards. The CSV keeps its rows, the
    percentages keep updating, and the only evidence that two different
    rules are being averaged together is a diff nobody kept.

    So the numbers live here as well as in the module, and they are pinned to
    the name. Re-tuning is allowed; re-tuning quietly is not. To change a
    threshold: give the rule a new name carrying it, add the new entry here,
    and leave the old one so its forward record stays readable on its own.
    """
    from src.evaluation.tracked_rules import RULES

    by_name = {(r["name"], r["market"]): r for r in RULES}
    assert set(by_name) == set(TRACKED_RULE_DEFINITIONS), (
        f"tracked rules changed name: module has {sorted(by_name)}, this "
        f"test pins {sorted(TRACKED_RULE_DEFINITIONS)}")
    for name, want in TRACKED_RULE_DEFINITIONS.items():
        got = by_name[name]
        for k, v in want.items():
            have = got.get(k, "back" if k == "kind" else None)
            assert have == pytest.approx(v) if isinstance(v, float) \
                else have == v, (
                f"{name!r} changed {k} from {v} to {have} without changing "
                f"its name — its forward record now mixes two rules")


def test_a_rules_record_is_read_under_one_definition_only():
    """And the picks on disk agree. A name in the log with no rule behind it
    is a rule that was renamed or removed after it had recorded picks, which
    is the same merge seen from the other side."""
    import polars as pl

    from src.evaluation.tracked_rules import RULES, load

    picks = load()
    if picks.is_empty():
        pytest.skip("nothing recorded yet")
    known = {r["name"] for r in RULES}
    seen = set(picks["rule"].drop_nulls().to_list())
    # The threshold a prop pick was taken under has to be recoverable from
    # the rule that took it, or its record cannot be reproduced.
    assert all(r.get("threshold_pp") is not None
               for r in RULES if r.get("kind") == "prop_edge")
    assert seen <= known, (
        f"{sorted(seen - known)} appear in tracked_picks.csv with no rule "
        f"defining them — their record cannot be reproduced")


def test_the_picks_file_header_matches_the_columns_that_write_it():
    """`record` appends with a FIXED fieldname list and writes the header
    only when the file does not exist. So a column added to `COLUMNS`
    without migrating the file produces rows wider than the header already
    on disk, and every reader silently misaligns from that row on.

    `side` and `line` were added on 2026-10-06 for the prop edge rule, which
    bets a two-sided market and so has to say which side at what number. The
    284 existing rows were padded with empty values and no other cell was
    touched.
    """
    import csv
    from pathlib import Path

    from src.evaluation.tracked_rules import COLUMNS, PICKS_PATH

    p = Path(PICKS_PATH)
    if not p.exists():
        pytest.skip("nothing recorded yet")
    header = next(csv.reader(p.open()))
    assert header == list(COLUMNS), (
        f"the file's header is {header} but `record` writes {list(COLUMNS)} "
        f"— migrate the file before changing COLUMNS")
