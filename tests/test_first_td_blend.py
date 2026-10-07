"""The first-TD market blend: one first scorer a game, before and after.

Anytime TD blends each player on his own. First TD cannot, because a game has
exactly one first scorer and moving one player's number has to move everyone
else's. These pin the properties the served blend promises.
"""
import numpy as np
import polars as pl

from src.prediction.blend import (blend_first_td, fit_first_td_blend,
                                  FIRST_TD_MIN_PRICED)


def _board():
    return pl.DataFrame({
        "game_id": ["g1"] * 4 + ["g2"] * 3,
        "player_name": list("abcdefg"),
        "prob_calibrated": [0.5, 0.3, 0.15, 0.05, 0.6, 0.3, 0.1],
        "market_prob": [0.2, 0.5, 0.2, None, 0.7, None, None],
    })


def test_every_game_still_sums_to_one():
    out = blend_first_td(_board(), "prob_calibrated", "market_prob",
                         {"market_weight": 0.5})
    sums = out.group_by("game_id").agg(pl.col("probability").sum())
    assert np.allclose(sums["probability"].to_numpy(), 1.0)


def test_unpriced_players_keep_the_models_number():
    out = blend_first_td(_board(), "prob_calibrated", "market_prob",
                         {"market_weight": 0.5})
    un = out.filter(pl.col("market_prob").is_null())
    assert np.allclose(un["probability"].to_numpy(),
                       un["prob_calibrated"].to_numpy())


def test_a_game_with_one_priced_player_is_left_alone():
    assert FIRST_TD_MIN_PRICED == 2
    out = blend_first_td(_board(), "prob_calibrated", "market_prob",
                         {"market_weight": 0.9}).filter(pl.col("game_id") == "g2")
    assert np.allclose(out["probability"].to_numpy(),
                       out["prob_calibrated"].to_numpy())


def test_weight_zero_is_the_model_and_one_is_the_book_within_the_priced_mass():
    b = _board().filter(pl.col("game_id") == "g1")
    zero = blend_first_td(b, "prob_calibrated", "market_prob", {"market_weight": 0.0})
    assert np.allclose(zero["probability"].to_numpy(), b["prob_calibrated"].to_numpy())
    one = blend_first_td(b, "prob_calibrated", "market_prob", {"market_weight": 1.0})
    priced = one.filter(pl.col("market_prob").is_not_null())
    mass = 0.95
    assert np.allclose(priced["probability"].to_numpy(),
                       np.array([0.2, 0.5, 0.2]) / 0.9 * mass)


def test_the_fit_finds_the_book_when_the_book_is_the_truth():
    rng = np.random.default_rng(0)
    rows = []
    for g in range(300):
        k = rng.dirichlet(np.ones(8) * 2)
        m = rng.dirichlet(np.ones(8) * 2)
        win = rng.choice(8, p=k)
        for i in range(8):
            rows.append({"game_id": f"g{g}", "season": 2025,
                         "model_prob": m[i], "market_prob": k[i],
                         "scored": int(i == win)})
    fit = fit_first_td_blend(pl.DataFrame(rows))
    assert fit["market_weight"] > 0.8
    assert fit["nll_winner"] <= fit["nll_winner_model_only"]
