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
    """Fifty observations of a positive drift is not a licence to bet."""
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
        for k in ("name", "market", "min_odds", "max_odds", "min_edge_pp",
                  "status", "found", "control", "out_of_sample"):
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
    """A record that can be inflated by re-running the report is not a record."""
    from src.evaluation.tracked_rules import load, record

    log = tmp_path / "tracked.csv"
    rows = [{"rule": "t", "player": "A", "team": "X", "game": "X @ Y",
             "odds": 400, "ours": 0.25, "book": 0.18, "edge_pp": 7.0}]
    first = record(rows, season=2026, week=1, market="anytime_td",
                   recorded_on="2026-09-10", path=log)
    again = record(rows, season=2026, week=1, market="anytime_td",
                   recorded_on="2026-09-11", path=log)
    assert (first, again) == (1, 0)
    assert load(log).height == 1
    # A different week is a different observation, not a duplicate.
    assert record(rows, season=2026, week=2, market="anytime_td",
                  recorded_on="2026-09-17", path=log) == 1


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
