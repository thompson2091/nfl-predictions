"""The weekly re-measurement of the count model against the market.

The headline this produces is "the market prices receptions better than we do",
and it is the sentence the dashboard leads with. A measurement that says that
wrongly is worse than no measurement, in both directions: overstate the market
and a usable model stays on the shelf, understate it and a leak gets bet.

The specific things that can go wrong here are not modelling choices, they are
bookkeeping. A push graded as a loss penalises both sides for an outcome
neither called wrong. An in-play price graded as a close credits the market
with knowing a result it could already see. And a pooled figure over a season
hides the week the model fell over.

    pytest tests/test_receptions_forward.py -v
"""
from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.evaluation import receptions_forward as F


def _graded(rows: list[dict]) -> pl.DataFrame:
    """A settled frame in the shape `record` consumes."""
    df = pl.DataFrame(rows)
    return df.with_columns([
        (pl.col("receptions") > pl.col("point")).cast(pl.Float64).alias("y_over"),
        (pl.col("receptions") == pl.col("point")).alias("push"),
    ])


def test_a_push_is_not_a_loss_for_either_side(monkeypatch):
    """A whole-number line landing exactly returns the stake.

    Falsified by dropping the `~pl.col("push")` filter: the pushed row grades
    as a loss against both probabilities, and because the model and the market
    disagree about it the two log losses move by different amounts — so the
    verdict can flip on a bet nobody won or lost.
    """
    rows = [
        {"week": 1, "point": 3.5, "receptions": 5, "p_model": 0.7, "fair_prob": 0.6},
        {"week": 1, "point": 4.5, "receptions": 2, "p_model": 0.3, "fair_prob": 0.4},
        # The push: a 5.0 line and exactly five catches.
        {"week": 1, "point": 5.0, "receptions": 5, "p_model": 0.9, "fair_prob": 0.2},
    ]
    monkeypatch.setattr(F, "graded", lambda season, snapshot="close": _graded(rows))
    r = F.record(2026)

    assert r["pushes"] == 1
    assert r["pooled"]["n"] == 2, "the push must not be graded"

    # The two settled rows alone, computed independently of the module.
    y = np.array([1.0, 0.0])
    expect = float(-np.mean(y * np.log([0.7, 0.3]) + (1 - y) * np.log([0.3, 0.7])))
    assert r["pooled"]["model_log_loss"] == pytest.approx(expect)


def test_beats_market_points_the_way_lower_log_loss_does(monkeypatch):
    """Lower is better, and the flag has to agree with that.

    Both directions are asserted because a sign error here reads as a plain
    English sentence either way — "the market is better calibrated" is exactly
    as believable as its opposite to someone who has not checked.
    """
    losing = [
        {"week": 1, "point": 3.5, "receptions": 5, "p_model": 0.55, "fair_prob": 0.90},
        {"week": 1, "point": 3.5, "receptions": 1, "p_model": 0.45, "fair_prob": 0.10},
    ]
    monkeypatch.setattr(F, "graded", lambda season, snapshot="close": _graded(losing))
    r = F.record(2026)
    assert r["pooled"]["market_log_loss"] < r["pooled"]["model_log_loss"]
    assert r["beats_market"] is False

    winning = [{**d, "p_model": d["fair_prob"], "fair_prob": d["p_model"]}
               for d in losing]
    monkeypatch.setattr(F, "graded", lambda season, snapshot="close": _graded(winning))
    r = F.record(2026)
    assert r["pooled"]["model_log_loss"] < r["pooled"]["market_log_loss"]
    assert r["beats_market"] is True


def test_the_record_is_kept_per_week_because_pooling_hides_a_bad_one(monkeypatch):
    """A season-long average is exactly the wrong resolution for a warning."""
    rows = (
        [{"week": 1, "point": 3.5, "receptions": 5, "p_model": 0.9, "fair_prob": 0.5},
         {"week": 1, "point": 3.5, "receptions": 5, "p_model": 0.9, "fair_prob": 0.5}]
        + [{"week": 2, "point": 3.5, "receptions": 1, "p_model": 0.9, "fair_prob": 0.5},
           {"week": 2, "point": 3.5, "receptions": 1, "p_model": 0.9, "fair_prob": 0.5}]
    )
    monkeypatch.setattr(F, "graded", lambda season, snapshot="close": _graded(rows))
    r = F.record(2026)

    assert [w["week"] for w in r["weeks"]] == [1, 2]
    w1, w2 = r["weeks"]
    assert w1["model_log_loss"] < w1["market_log_loss"], "week 1 the model was right"
    assert w2["model_log_loss"] > w2["market_log_loss"], "week 2 it was confidently wrong"
    # And the pooled number sits between them, saying nothing about either.
    assert (min(w1["model_log_loss"], w2["model_log_loss"])
            < r["pooled"]["model_log_loss"]
            < max(w1["model_log_loss"], w2["model_log_loss"]))


def test_an_in_play_price_never_reaches_the_forward_grade():
    """`graded` filters before it measures, and this is which filter.

    Not a behavioural test of the arithmetic — a source-level one, because the
    ordering is the part that is easy to get wrong and impossible to see in the
    output. Resolving ids must come first (the kickoff is looked up by game
    id), dropping in-play second, and keeping the newest last: an in-play quote
    is the newest by construction, so deduplicating first selects exactly the
    rows the next step exists to remove.
    """
    import inspect

    src = inspect.getsource(F.graded)
    # Nested, so resolution is the inner call and runs first. Asserted as one
    # contiguous string rather than by comparing positions: in `drop_in_play(
    # resolve_game_ids(h))` the outer call appears *earlier* in the text and
    # runs *later*, and a position comparison reads the wrong way round.
    assert "drop_in_play(resolve_game_ids(h))" in src, (
        "drop_in_play looks the kickoff up by game id, so ids resolve first")
    assert src.index("drop_in_play(") < src.index(".unique("), (
        "deduplicating before dropping in-play keeps the fourth-quarter price")


def test_nothing_settled_is_a_state_and_not_a_zero(monkeypatch):
    """Early in a week there is no measurement, which is not a bad one."""
    monkeypatch.setattr(F, "graded", lambda season, snapshot="close": None)
    assert F.record(2026) is None
    assert "nothing settled" in F.report(2026).lower()
