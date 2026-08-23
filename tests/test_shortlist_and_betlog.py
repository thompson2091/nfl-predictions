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
