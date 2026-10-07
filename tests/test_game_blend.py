"""The game blend's extra numbers: the centered total and the blended win."""
from __future__ import annotations

import numpy as np
import polars as pl

from src.models import game_blend as GB


def _weights(c=1.0, w=0.25):
    return {"margin": {"w": 0.1}, "total": {"w": 0.25},
            "center": {"c": c, "w": w}}


def test_centering_removes_the_slate_level_and_keeps_the_order():
    cards = {"A": {"model_total": 50.0, "total": 45.0},
             "B": {"model_total": 44.0, "total": 41.0},
             "C": {"model_total": 47.0, "total": 46.0}}
    raw = {k: v["model_total"] for k, v in cards.items()}
    GB.center_cards(cards, _weights())
    cen = {k: v["model_total_centered"] for k, v in cards.items()}
    # The slate's mean centered total equals the book's mean total...
    assert abs(np.mean(list(cen.values()))
               - np.mean([c["total"] for c in cards.values()])) < 0.11
    # ...the game-to-game disagreement is unchanged...
    assert sorted(cen, key=cen.get) == sorted(raw, key=raw.get)
    # ...and the raw total, the model's own number, is untouched.
    assert {k: v["model_total"] for k, v in cards.items()} == raw


def test_a_card_missing_a_total_neither_moves_the_gap_nor_gets_one():
    cards = {"A": {"model_total": 50.0, "total": 45.0},
             "B": {"model_total": 60.0, "total": None}}
    GB.center_cards(cards, _weights())
    assert cards["A"]["model_total_centered"] == 45.0
    assert "model_total_centered" not in cards["B"]


def test_no_fit_means_no_centered_total():
    cards = {"A": {"model_total": 50.0, "total": 45.0}}
    GB.center_cards(cards, {"total": {"w": 0.3}})
    assert "model_total_centered" not in cards["A"]


def test_the_centered_blend_sits_beside_the_raw_blend():
    card = {"spread": -3.0, "total": 45.0, "model_spread": -6.0,
            "model_total": 50.0, "model_total_centered": 47.0}
    got = GB.blend_card(card, _weights())
    assert got["total"] == round(0.25 * 50 + 0.75 * 45, 1)
    assert got["total_centered"] == round(0.25 * 47 + 0.75 * 45, 1)


def test_blended_win_reads_the_card_sign():
    """The card signs a spread negative when HOME is favored; the curve takes
    the schedule's opposite. Getting it backwards would hand the favorite's
    chance to the underdog on every card."""
    curve = {"a": 0.0, "b": 0.15, "n": 1}
    home_fav = GB.blend_win({"spread": -7.0}, curve)
    away_fav = GB.blend_win({"spread": 7.0}, curve)
    assert home_fav > 0.5 > away_fav
    assert abs(home_fav + away_fav - 1) < 1e-3
    assert GB.blend_win({"total": 44.0}, curve) is None
    assert GB.blend_win({"spread": -3.0}, {}) is None


def test_the_centering_fit_reports_out_of_sample_and_provenance():
    rng = np.random.default_rng(0)
    rows = []
    for s in range(2015, 2023):
        lvl = rng.normal(0, 3)
        for wk in range(1, 18):
            for g in range(8):
                k = rng.normal(45, 4)
                a = k + rng.normal(0, 10)
                rows.append({"season": s, "week": wk, "total_market": k,
                             "total_actual": a,
                             "total_model": a * 0.2 + k * 0.8 + lvl
                                            + rng.normal(0, 4)})
    got = GB.fit_center(pl.DataFrame(rows))
    assert got["c"] > 0.5
    assert got["oos"]["centered_mae"] < got["oos"]["raw_mae"]
    assert got["seasons_used"][0] == 2015 and got["n_rows"] == len(rows)
