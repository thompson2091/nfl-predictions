"""Regression tests for letting the anytime model inform first TD.

    pytest tests/test_cross_market.py -v
"""
from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.prediction import cross_market as X


def _game(game: str, probs: list[float], any_probs: list[float],
          winner: int) -> list[dict]:
    return [{"game_id": game, "player_id": f"{game}-{i}", "prob": p,
             "any_prob": a, "target": 1 if i == winner else 0}
            for i, (p, a) in enumerate(zip(probs, any_probs))]


def test_blend_is_geometric_so_the_bigger_scale_cannot_dominate():
    """The two markets live on different scales.

    An anytime favorite sits near 0.55 and a first-TD favorite near 0.15. A
    weighted *average* would let the anytime number decide the ordering
    regardless of what either model meant; a geometric blend is an average in
    log space, so it combines the rankings rather than the levels.
    """
    first = np.array([0.15, 0.10])
    anytime = np.array([0.40, 0.60])

    arithmetic = 0.5 * first + 0.5 * anytime
    assert arithmetic[1] > arithmetic[0], "the scale difference flips the order"

    geometric = X.blend(first, anytime, 0.5)
    assert geometric[0] == pytest.approx(np.sqrt(0.15 * 0.40))
    assert geometric[1] == pytest.approx(np.sqrt(0.10 * 0.60))


def test_weight_zero_returns_the_first_td_model_untouched():
    first = np.array([0.2, 0.1, 0.05])
    out = X.blend(first, np.array([0.9, 0.8, 0.7]), 0.0)
    assert np.allclose(out, first)


def test_fit_finds_the_other_market_when_it_carries_the_answer():
    """If the anytime model ranks the winner first and we do not, lean on it."""
    rows = []
    for g in range(40):
        rows += _game(f"g{g}", probs=[0.20, 0.15, 0.10],
                      any_probs=[0.10, 0.20, 0.60], winner=2)
    fitted = X.fit_weight(pl.DataFrame(rows))
    assert fitted["weight"] > 0.5
    assert fitted["nll"] < fitted["nll_first_td_only"]


def test_fit_declines_to_blend_when_the_other_market_only_adds_noise():
    """A weight is only worth serving if it earns its place.

    Returning some small positive weight because the grid had to pick something
    is how a change that does nothing gets shipped and then defended.
    """
    rng = np.random.default_rng(0)
    rows = []
    for g in range(60):
        rows += _game(f"g{g}", probs=[0.30, 0.10, 0.05],
                      any_probs=list(rng.random(3)), winner=0)
    fitted = X.fit_weight(pl.DataFrame(rows))
    assert fitted["weight"] == 0.0
    assert fitted["nll"] == fitted["nll_first_td_only"]


def test_the_objective_is_categorical_not_top_1():
    """Top-1 is a step function of the weight and cannot be optimised.

    Nudging the weight cannot change which player ranks first until it crosses a
    threshold, so a search on Top-1 sees a flat surface and returns its starting
    point — which is precisely how `_optimize_ensemble_weights` spent every
    training run reporting equal weights as "learned".
    """
    rows = []
    for g in range(30):
        # The winner is second on both models, so Top-1 is zero at every weight.
        # But the anytime model gives the winner a larger *share* of its game
        # (0.35/0.80 against 0.20/0.60), so the likelihood still improves.
        rows += _game(f"g{g}", probs=[0.30, 0.20, 0.10],
                      any_probs=[0.40, 0.35, 0.05], winner=1)
    df = pl.DataFrame(rows)

    def top1(w):
        b = X.blend(df["prob"].to_numpy(), df["any_prob"].to_numpy(), w)
        d = df.with_columns(pl.Series("b", b)).with_columns(
            pl.col("b").rank(descending=True, method="ordinal")
            .over("game_id").alias("r"))
        return float(d.filter(pl.col("target") == 1)["r"].eq(1).mean())

    assert top1(0.0) == top1(1.0) == 0.0, "Top-1 is flat across the whole range"
    fitted = X.fit_weight(df)
    assert fitted["weight"] > 0.0, "the likelihood still has a gradient to follow"


def test_categorical_nll_normalises_within_the_game():
    """Exactly one player wins, so the game's scores are a distribution."""
    df = pl.DataFrame(_game("g", probs=[0.5, 0.25, 0.25],
                            any_probs=[0, 0, 0], winner=0))
    # Winner holds half the mass, so the loss is -log(0.5).
    assert X.categorical_nll(df, "prob") == pytest.approx(-np.log(0.5))

    # Scaling a whole game changes nothing: it is the shares that matter.
    scaled = df.with_columns((pl.col("prob") * 7.0).alias("prob"))
    assert X.categorical_nll(scaled, "prob") == pytest.approx(-np.log(0.5))


def test_fit_curve_is_recorded_for_inspection():
    """The shape of the curve is the evidence that the effect is real.

    A smooth plateau is a signal; a spike at one weight is an artefact. The
    ledger should be able to show which one this was.
    """
    rows = []
    for g in range(20):
        rows += _game(f"g{g}", probs=[0.2, 0.1], any_probs=[0.1, 0.5], winner=1)
    fitted = X.fit_weight(pl.DataFrame(rows))
    assert len(fitted["curve"]) == len(X.WEIGHT_GRID)
    assert fitted["curve"][0]["weight"] == 0.0
