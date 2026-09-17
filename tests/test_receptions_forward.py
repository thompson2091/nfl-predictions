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
    if "p_model_raw" not in df.columns:
        df = df.with_columns(pl.col("p_model").alias("p_model_raw"))
    if "p_model" not in df.columns:
        df = df.with_columns(pl.col("p_model_raw").alias("p_model"))
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

    The served number is derived from the raw one and the blend weight rather
    than read from the frame, so the weight is pinned here. That derivation is
    the point: what gets graded is what the board would have served, not what a
    caller claimed it served.
    """
    rows = [
        {"week": 1, "point": 3.5, "receptions": 5, "p_model_raw": 0.7, "fair_prob": 0.6},
        {"week": 1, "point": 4.5, "receptions": 2, "p_model_raw": 0.3, "fair_prob": 0.4},
        # The push: a 5.0 line and exactly five catches.
        {"week": 1, "point": 5.0, "receptions": 5, "p_model_raw": 0.9, "fair_prob": 0.2},
    ]
    monkeypatch.setattr(F, "graded", lambda season, snapshot="close": _graded(rows))
    monkeypatch.setattr(F, "_shipped_weight", lambda: 1.0)   # served == raw
    r = F.record(2026)

    assert r["pushes"] == 1
    assert r["pooled"]["n"] == 2, "the push must not be graded"

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


def test_the_blend_keeps_nothing_when_the_model_adds_nothing():
    """A weight near zero is an answer, not a failed fit.

    Fed a model that is pure noise around the book, the right amount of it to
    keep is none. Falsified by flooring the weight or seeding the search away
    from zero — both make a useless model look like a contributor, which is
    exactly the error this market punishes.
    """
    from src.models.count import fit_market_blend

    rng = np.random.default_rng(0)
    book = rng.uniform(0.2, 0.8, 4000)
    noise = np.clip(book + rng.normal(0, 0.15, 4000), 0.01, 0.99)
    y = (rng.uniform(size=4000) < book).astype(float)

    out = fit_market_blend(noise, book, y)
    assert out["weight"] < 0.10, f"kept {out['weight']:.2f} of a noise model"
    assert out["fit_log_loss"] <= out["market_log_loss"] + 1e-9


def test_a_model_that_knows_more_than_the_book_keeps_more_of_itself():
    """The other direction, or the test above passes on a blend stuck at zero."""
    from src.models.count import fit_market_blend

    rng = np.random.default_rng(1)
    truth = rng.uniform(0.15, 0.85, 4000)
    y = (rng.uniform(size=4000) < truth).astype(float)
    sharp = np.clip(truth + rng.normal(0, 0.03, 4000), 0.01, 0.99)
    vague = np.clip(truth + rng.normal(0, 0.25, 4000), 0.01, 0.99)

    assert fit_market_blend(sharp, vague, y)["weight"] > 0.7


def test_a_line_the_book_never_priced_is_left_alone():
    """There is nothing to shrink toward, and 50% is not the market's opinion.

    Most of the receptions board is a projection with no posted line. Treating
    a missing price as an implied coin flip would drag every one of those rows
    to the middle and call it market information.
    """
    from src.models.count import blend_to_market

    model = np.array([0.8, 0.3, 0.55])
    book = np.array([0.5, np.nan, np.nan])
    out = blend_to_market(model, book, 0.2)

    assert out[1] == pytest.approx(0.3)
    assert out[2] == pytest.approx(0.55)
    assert out[0] != pytest.approx(0.8), "a priced row is shrunk"


def test_the_alarm_fires_on_the_raw_model_not_on_what_is_served(monkeypatch):
    """The blend is *supposed* to beat the book, so a flag on that cries wolf.

    Falsified by pointing `raw_beats_market` back at the served number: the
    warning then fires every week the blend does its job, and the one signal
    that has meant a leak every previous time is buried under it.

    The raw model here is confidently wrong on both rows while the book is
    nearly right, which is the real shape of this market.
    """
    rows = [
        {"week": 1, "point": 3.5, "receptions": 5, "p_model_raw": 0.30, "fair_prob": 0.62},
        {"week": 1, "point": 3.5, "receptions": 1, "p_model_raw": 0.70, "fair_prob": 0.38},
    ]
    monkeypatch.setattr(F, "graded", lambda season, snapshot="close": _graded(rows))
    monkeypatch.setattr(F, "_shipped_weight", lambda: 0.0)   # served == the book
    r = F.record(2026)

    assert r["raw_beats_market"] is False, (
        "the raw model is behind, and that is the alarm")
    assert "leak" not in F.report(2026).lower(), (
        "a blend doing its job must not read as a leak")


def test_the_range_brackets_the_mean_and_widens_with_it():
    """A mean alone cannot be read; the interval is what makes it a projection.

    Falsified by returning a fixed window, or by swapping the percentiles: the
    bracket check fails and so does the ordering, because a nine-catch
    projection is genuinely more spread than a two-catch one.
    """
    from src.models.count import count_interval

    mu = np.array([1.0, 4.0, 9.0])
    lo, hi = count_interval(mu, 8.4)

    assert (lo <= np.floor(mu)).all() and (hi >= np.ceil(mu)).all(), (
        f"the interval must contain the mean: {list(zip(lo, hi))}")
    assert (hi - lo)[2] > (hi - lo)[0], "a bigger count is a wider count"
    assert (lo >= 0).all(), "nobody catches a negative number of passes"


def test_the_interval_is_the_stated_share_of_games():
    """70%, and the tails are deliberately not 5/95.

    A 5th percentile on a count this small is 0 for most of the board, which
    says nothing about anyone. Falsified by widening the defaults: the
    coverage below stops matching the interval the column claims.
    """
    from scipy import stats
    from src.models.count import count_interval

    mu, r = 4.0, 8.4
    lo, hi = count_interval(np.array([mu]), r)
    d = stats.nbinom(r, r / (r + mu))
    covered = d.cdf(hi[0]) - d.cdf(lo[0] - 1)

    assert 0.6 < covered < 0.85, f"claims ~70%, covers {covered:.0%}"


def test_a_live_refit_waits_until_the_season_can_carry_it(monkeypatch):
    """One parameter does not need many lines, but two weeks is not enough.

    A weight refitted each week on two weeks of data would swing with each of
    them, and what is served would be chasing noise it had just seen.
    """
    rows = [{"week": 1, "point": 3.5, "receptions": 5,
             "p_model_raw": 0.6, "fair_prob": 0.5}] * 50
    monkeypatch.setattr(F, "graded", lambda season, snapshot="close": _graded(rows))

    assert F.refit_blend(2026, write=False) is None, "50 lines is not a season"
    assert F.refit_blend(2026, min_n=10, write=False) is not None, (
        "and the guard must be a threshold, not a refusal")


def test_grading_never_uses_a_weight_fitted_on_the_week_it_grades():
    """Serving looks back; grading must look further back.

    Refitting on the live season is right for what we serve — fitted on weeks
    already played, applied to the ones after. Grading with that same weight
    would make the record in sample for it, and the headline would improve for
    no reason anyone should believe.

    Falsified by fitting on `week <= wk` and grading week `wk` with it: the
    first week then carries a weight fitted on itself and the assertion below
    fails.
    """
    live = pl.DataFrame({
        "week": [1] * 3000 + [2] * 3000,
        "p_model_raw": [0.6] * 6000,
        "fair_prob": [0.5] * 6000,
        "y_over": ([1.0] * 2000 + [0.0] * 1000) * 2,
    })
    by_week = F.walk_forward_weights(live, fallback=0.17)

    assert by_week[1] == pytest.approx(0.17), (
        "the first week has nothing before it, so it keeps the shipped weight")
    assert by_week[2] != pytest.approx(0.17), (
        "the second week is graded on a weight fitted on the first")


def test_the_shipped_weight_is_the_fallback_not_a_default_of_one(monkeypatch):
    """With no history of its own, serving the raw model is the worst of both.

    A fallback of 1.0 means "keep all of our number", which is the arm that
    loses to the market by 0.028 on this season. The shipped weight is the one
    thing known to work before the live season has any evidence.

    Asserted through `record`, not only on the helper. The first version called
    `walk_forward_weights` directly with an explicit fallback, so changing what
    `record` passes in — the only place it is decided — broke nothing.
    """
    live = pl.DataFrame({"week": [1] * 10, "p_model_raw": [0.6] * 10,
                         "fair_prob": [0.5] * 10, "y_over": [1.0] * 10})
    assert F.walk_forward_weights(live, fallback=0.17)[1] == pytest.approx(0.17)

    rows = [{"week": 1, "point": 3.5, "receptions": 5,
             "p_model_raw": 0.7, "fair_prob": 0.5},
            {"week": 1, "point": 3.5, "receptions": 1,
             "p_model_raw": 0.3, "fair_prob": 0.5}]
    monkeypatch.setattr(F, "graded", lambda season, snapshot="close": _graded(rows))
    monkeypatch.setattr(F, "_shipped_weight", lambda: 0.23)
    r = F.record(2026)
    assert r["weights"]["1"] == pytest.approx(0.23), (
        "an unevidenced week is served the shipped weight, not the raw model")
