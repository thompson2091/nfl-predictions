"""Regression tests for the measurement layer.

These test the thing that decides whether every future change is real. A bug
here does not produce a wrong prediction; it produces a wrong *decision*, which
is worse, because the wrong decision then gets locked, committed and defended.

    pytest tests/test_evaluation_harness.py -v
"""
from __future__ import annotations

import polars as pl
import pytest

from src.evaluation import compare as C
from src.evaluation.ranking import (game_universe, per_game_outcomes, pooled,
                                    top_k_accuracy)
from src.utils.config import config_diff, config_overlay, deep_merge, get_config


# --------------------------------------------------------------------------
# The denominator
# --------------------------------------------------------------------------

def _scored(hits: dict[str, int | None]) -> pl.DataFrame:
    """A frame where game g's scorer is ranked at `hits[g]` (None = absent)."""
    rows = []
    for game, rank in hits.items():
        for i in range(5):
            rows.append({
                "game_id": game, "player_id": f"{game}-{i}",
                "prob": 1.0 - i * 0.1,
                "target": 1 if rank is not None and i == rank - 1 else 0,
            })
    return pl.DataFrame(rows)


def test_a_filtered_out_scorer_counts_as_a_miss_not_a_missing_game():
    """The bug this whole layer exists to fix.

    `_fold_metrics` built its game list from the rows that survived
    `_filter_low_activity`, so a game whose only scorer was filtered out
    disappeared from the denominator instead of counting against the model. On
    first TD that hid 16 of 1,131 games, worth about 0.2 points of Top-1.
    """
    scored = _scored({"g1": 1, "g2": 4})
    universe = pl.DataFrame({"game_id": ["g1", "g2", "g3"]})

    outcomes = per_game_outcomes(scored, universe)
    assert outcomes.height == 3, "every game in the universe must be scored"
    assert outcomes.filter(pl.col("game_id") == "g3")["hit5"].item() is False
    assert pooled(outcomes)["top1"] == pytest.approx(1 / 3)
    assert pooled(outcomes)["unranked_games"] == 1


def test_the_denominator_does_not_move_when_the_pool_does():
    """Two candidate filters must be scored over the same games.

    Otherwise loosening the filter adds hard games, lowers measured Top-1, and
    reads as a regression while strictly improving the product — which made
    pool experiments impossible to compare at all.
    """
    universe = pl.DataFrame({"game_id": ["g1", "g2", "g3"]})
    tight = _scored({"g1": 1, "g2": 1})              # g3's scorer filtered away
    loose = _scored({"g1": 1, "g2": 1, "g3": 4})     # ... and now retained

    tight_stats, loose_stats = pooled(per_game_outcomes(tight, universe)), \
        pooled(per_game_outcomes(loose, universe))
    assert tight_stats["games"] == loose_stats["games"] == 3
    assert tight_stats["top1"] == loose_stats["top1"], (
        "keeping a player the model ranks 4th must not change Top-1")
    assert loose_stats["top5"] > tight_stats["top5"], (
        "but it must show up where it helps")


def test_games_with_no_scorer_anywhere_are_excluded_and_counted():
    """No ranking can win a game whose label is not in the pool at all.

    Eight games per four-season window have no scorer among the candidates.
    Counting them as misses would penalise the model for a data gap; hiding
    them entirely is how the old denominator got its flattering number. They
    are excluded from the universe and reported.
    """
    labelled = pl.DataFrame({
        "game_id": ["g1", "g1", "g2", "g2"],
        "target": [1, 0, 0, 0],       # g2: nobody in the pool scored
    })
    universe = game_universe(labelled)
    assert universe["game_id"].to_list() == ["g1"]


def test_top_k_accuracy_still_answers_its_old_question():
    """Callers with no wider frame — in-training reporting — keep working."""
    scored = _scored({"g1": 1, "g2": 4})
    assert top_k_accuracy(scored, k=1) == pytest.approx(0.5)
    assert top_k_accuracy(scored, k=5) == pytest.approx(1.0)


def test_coin_flip_share_reads_the_gap_between_the_top_two():
    close = pl.DataFrame({
        "game_id": ["g1", "g1", "g2", "g2"],
        "prob": [0.300, 0.299, 0.30, 0.10],
        "target": [1, 0, 1, 0],
    })
    stats = pooled(per_game_outcomes(close, game_universe(close)))
    assert stats["coin_flip_share"] == pytest.approx(0.5)


# --------------------------------------------------------------------------
# Paired comparison
# --------------------------------------------------------------------------

def _outcomes(hits: list[int], market="anytime_td", model="xgb") -> pl.DataFrame:
    return pl.DataFrame({
        "game_id": [f"g{i}" for i in range(len(hits))],
        "hit1": [bool(h) for h in hits],
        "hit3": [bool(h) for h in hits],
        "hit5": [True] * len(hits),
        "target_type": [market] * len(hits),
        "model": [model] * len(hits),
    })


def test_pairing_finds_a_difference_the_pooled_error_bar_hides():
    """The reason this layer exists.

    Two variants that agree on 900 of 1,000 games differ by a hair in pooled
    terms, and both pooled figures carry +/-1.5%. Paired, the same data resolves
    the difference easily, because only the games where they disagree carry any
    information about which is better.
    """
    n = 1000
    a = [1] * 500 + [0] * 500
    b = list(a)
    for i in range(500, 540):        # candidate wins 40 games the champion lost
        b[i] = 1
    for i in range(10):              # and loses 10 it had won
        b[i] = 0

    result = C.paired_top_k(_outcomes(a), _outcomes(b), k=1)
    assert result["wins"] == 40 and result["losses"] == 10
    assert result["delta"] == pytest.approx(0.03)
    assert result["p_value"] < 0.001
    assert result["se_multiple"] > 3

    # The unpaired view of the same numbers: 50.0% vs 53.0%, each +/-1.6%.
    unpaired_se = (0.5 * 0.5 / n) ** 0.5
    assert result["se"] < unpaired_se, (
        "pairing must be tighter than the pooled binomial error, or it buys "
        "nothing")


def test_identical_runs_compare_as_no_difference():
    a = _outcomes([1, 0] * 100)
    result = C.paired_top_k(a, a, k=1)
    assert result["delta"] == 0.0 and result["discordant"] == 0
    assert result["p_value"] == 1.0


def test_comparison_joins_on_game_so_unmatched_games_are_dropped():
    """A game only one side scored must not count as a win for whoever has it."""
    a = _outcomes([1, 1, 1])
    b = _outcomes([1, 1, 1, 1])
    assert C.paired_top_k(a, b, k=1)["n_compared"] == 3


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------

def _comparison(delta_top1: float, se: float = 0.005, **row) -> dict:
    base = {
        "market": "anytime_td", "model": "xgb",
        "top_k": {
            k: {"k": k, "n_compared": 1000, "champion": 0.5,
                "candidate": 0.5 + (delta_top1 if k == 1 else 0.0),
                "delta": delta_top1 if k == 1 else 0.0, "se": se,
                "se_multiple": delta_top1 / se if se else 0.0,
                "wins": 0, "losses": 0, "discordant": 0, "p_value": 0.01,
                "noise_band": None}
            for k in (1, 3, 5)
        },
        "row": {"auc": {"champion": 0.84, "candidate": 0.84, "delta": 0.0,
                        "noise_band": 0.001},
                "brier": {"champion": 0.09, "candidate": 0.09, "delta": 0.0,
                          "noise_band": 0.0005}},
    }
    for key, value in row.items():
        base["row"][key].update(value)
    return base


def test_a_gain_inside_the_error_is_rejected():
    verdict = C.gate(_comparison(delta_top1=0.002, se=0.005))
    assert verdict["verdict"] == "REJECTED"


def test_a_clear_gain_with_clean_guards_is_promoted():
    verdict = C.gate(_comparison(delta_top1=0.012, se=0.005))
    assert verdict["verdict"] == "PROMOTED"
    assert verdict["guards_tripped"] == []


def test_a_gain_that_costs_a_guard_is_flagged_not_silently_taken():
    """Top-1 up, Brier materially worse: promotable only with a justification."""
    verdict = C.gate(_comparison(
        delta_top1=0.012, se=0.005,
        brier={"delta": +0.004, "noise_band": 0.0005}))
    assert verdict["verdict"] == "GUARD_TRIPPED"
    assert [g["metric"] for g in verdict["guards_tripped"]] == ["brier"]


def test_a_guard_regression_inside_the_seed_noise_is_not_a_trip():
    """A difference smaller than what the seed alone produces is not one."""
    verdict = C.gate(_comparison(
        delta_top1=0.012, se=0.005,
        brier={"delta": +0.0003, "noise_band": 0.0005}))
    assert verdict["verdict"] == "PROMOTED"


# --------------------------------------------------------------------------
# Config overlays
# --------------------------------------------------------------------------

def test_overlay_merges_deeply_but_replaces_lists():
    base = {"model": {"xgb": {"max_depth": 6, "subsample": 0.8}},
            "models": {"active": ["lr", "lgbm", "xgb"]}}
    merged = deep_merge(base, {"model": {"xgb": {"max_depth": 4}},
                               "models": {"active": ["xgb"]}})
    assert merged["model"]["xgb"] == {"max_depth": 4, "subsample": 0.8}
    assert merged["models"]["active"] == ["xgb"], (
        "a screen restricting the model set must not train everything")
    assert base["model"]["xgb"]["max_depth"] == 6, "the base must not be mutated"


def test_overlay_is_restored_even_when_the_block_raises():
    """`run_all.py` already mutates the config singleton in place.

    If an experiment does the same by hand, a run that raises leaves the
    mutation behind and the *next* experiment silently measures a recipe nobody
    asked for.
    """
    before = get_config()["model"]["seed"]
    with pytest.raises(RuntimeError):
        with config_overlay({"model": {"seed": 999}}):
            assert get_config()["model"]["seed"] == 999
            raise RuntimeError("boom")
    assert get_config()["model"]["seed"] == before


def test_config_diff_reports_what_an_experiment_changed():
    diff = config_diff({"model": {"seed": 42, "xgb": {"max_depth": 6}}},
                       {"model": {"seed": 42, "xgb": {"max_depth": 4}}})
    assert diff == {"model.xgb.max_depth": (6, 4)}
