"""Regression tests for the measurement layer.

These test the thing that decides whether every future change is real. A bug
here does not produce a wrong prediction; it produces a wrong *decision*, which
is worse, because the wrong decision then gets locked, committed and defended.

    pytest tests/test_evaluation_harness.py -v
"""
from __future__ import annotations

import json

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


# --------------------------------------------------------------------------
# A model the champion does not have
# --------------------------------------------------------------------------

def _result(frames: list[pl.DataFrame]) -> dict:
    """A harness result carrying just what compare/gate read."""
    outcomes = pl.concat(frames, how="vertical")
    rows = []
    for (market, model), part in outcomes.group_by(["target_type", "model"]):
        rows.append({"target_type": market, "model": model,
                     "rows": part.height, "auc": 0.83, "brier": 0.09})
    return {"outcomes": outcomes, "row_metrics": rows}


def test_a_new_model_is_gated_against_what_the_market_serves():
    """Phase 3a introduces `condlogit`, which the champion has no version of.

    `compare_all` used to intersect model names, so a brand-new model produced
    no comparison at all — and a gate that prints nothing reads exactly like a
    gate that found nothing wrong. The honest pairing is against whatever the
    market actually serves, since that is the choice being made.
    """
    champion = _result([_outcomes([1, 0, 1, 0] * 25, model="xgb")])
    # The newcomer wins 25 games the served model lost, and loses none.
    better = [1, 0, 1, 0] * 25
    for i in range(1, 100, 4):
        better[i] = 1
    candidate = _result([_outcomes([1, 0, 1, 0] * 25, model="xgb"),
                         _outcomes(better, model="condlogit")])

    rows = C.compare_all(champion, candidate)
    by_model = {r["model"]: r for r in rows}
    assert "condlogit" in by_model, "the new model must not be silently dropped"

    new = by_model["condlogit"]
    assert new["against"] == "xgb", "paired against the served model"
    assert new["top1"]["wins"] == 25 and new["top1"]["losses"] == 0
    assert new["verdict"] == "PROMOTED"

    # The same-named comparison is still there and still finds no difference.
    assert by_model["xgb"]["top1"]["delta"] == pytest.approx(0.0)


def test_the_gate_table_names_both_sides_when_they_differ():
    """'REJECTED' against an unserved model is a different claim."""
    champion = _result([_outcomes([1, 0] * 50, model="xgb")])
    candidate = _result([_outcomes([1, 0] * 50, model="xgb"),
                         _outcomes([0, 0] * 50, model="condlogit")])
    text = C.format_gate(C.compare_all(champion, candidate))
    assert "condlogit vs served xgb" in text
    # ...and stays quiet about it when they are the same model.
    assert "xgb vs served xgb" not in text


def test_a_new_model_in_a_market_the_champion_never_scored_is_skipped():
    """No champion rows for that market means nothing to pair against.

    Dropping it is right — there is no comparison to make — but it must drop
    rather than raise, because a partial champion is normal when an experiment
    is screened on one market.
    """
    champion = _result([_outcomes([1, 0] * 50, market="anytime_td", model="xgb")])
    candidate = _result([_outcomes([1, 0] * 50, market="first_td",
                                   model="condlogit")])
    assert C.compare_all(champion, candidate) == []


# --------------------------------------------------------------------------
# What a screen trains
# --------------------------------------------------------------------------

def test_a_screen_trains_the_model_the_overlay_introduces():
    """Otherwise the screen reports the served model under the experiment's name.

    The conditional-logit screen did exactly that on its first run: the overlay
    added `condlogit` to models.active, `screen_models` returned only the served
    `xgb`, and the run printed a full result table in which the experiment's
    entire content never appeared. A screen that silently omits the thing being
    screened is worse than no screen, because it looks like a result.
    """
    from src.evaluation.harness import screen_models

    served = screen_models("anytime_td")
    assert "condlogit" not in served, "no overlay, no newcomer"

    overlay = {"models": {"active": ["lr", "lgbm", "xgb", "condlogit"]}}
    with_new = screen_models("anytime_td", overlay)
    assert "condlogit" in with_new, "the overlay's new model must be trained"
    assert with_new[0] == served[0], "still screened against what is served"
    # Models already active are not duplicated — the screen stays cheap.
    assert with_new.count("xgb") == 1
    assert "lgbm" not in with_new


def test_an_overlay_that_adds_no_model_screens_exactly_as_before():
    from src.evaluation.harness import screen_models

    overlay = {"joint": {"exclude_defst_from_shares": True}}
    assert screen_models("anytime_td", overlay) == screen_models("anytime_td")


# --------------------------------------------------------------------------
# The champion must describe what is being served
# --------------------------------------------------------------------------

def _experiment_module():
    """Load scripts/23_experiment.py without running its CLI."""
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "23_experiment.py"
    spec = importlib.util.spec_from_file_location("_exp_under_test", path)
    module = importlib.util.module_from_spec(spec)
    saved = sys.argv
    sys.argv = ["23_experiment.py"]
    try:
        spec.loader.exec_module(module)
    finally:
        sys.argv = saved
    return module


def test_a_champion_recorded_before_a_promotion_is_called_out(tmp_path):
    """The defect that made a no-op experiment report +2.56pp.

    The champion's per-game rows came from before the DEF/ST share fix was
    promoted. Every experiment measured afterwards was therefore credited with
    that fix. Nothing failed — the numbers just got better for free, which is
    the hardest kind of wrong to notice.
    """
    module = _experiment_module()
    current = tmp_path / "CURRENT.json"
    current.write_text(json.dumps({
        "anytime_td": {"version": "2026.08.12-first-td-xgb"},
        "first_td": {"version": "2026.08.12-first-td-xgb"},
    }))
    module.current_path = lambda: current

    stale = module.champion_drift({"run": "r", "version": "2026.08.12-baseline"})
    assert stale, "a champion older than the served version must be reported"
    text = "\n".join(stale)
    assert "STALE CHAMPION" in text
    assert "2026.08.12-baseline" in text and "2026.08.12-first-td-xgb" in text
    assert "make champion" in text, "the warning must say how to fix it"

    fresh = module.champion_drift({"run": "r",
                                   "version": "2026.08.12-first-td-xgb"})
    assert fresh == [], "a current champion must warn about nothing"


def test_champion_drift_is_quiet_when_it_cannot_know(tmp_path):
    """No champion, no recorded version, no CURRENT.json — all silent.

    A warning that fires on a fresh checkout is a warning that gets ignored,
    and this one has to survive being read on the day it matters.
    """
    module = _experiment_module()
    module.current_path = lambda: tmp_path / "missing.json"
    assert module.champion_drift(None) == []
    assert module.champion_drift({"run": "r"}) == []
    assert module.champion_drift({"run": "r", "version": "x"}) == []


def test_two_runs_can_mean_different_things_by_ensemble():
    """A screen's ensemble averages only the screened models.

    `harness.run` restricts `models.active` to whatever is being trained, so a
    screen of {xgb, condlogit} produces an `ensemble` row that is those two
    averaged. Compared against a champion's {lr, lgbm, xgb} ensemble, the delta
    is mostly composition — which is exactly how "+2.21pp" got read as "adding
    condlogit helps the ensemble".
    """
    champion = _result([_outcomes([1, 0] * 50, model="ensemble")])
    champion["meta"] = {"active_models": ["lr", "lgbm", "xgb"]}
    candidate = _result([_outcomes([1, 1] * 50, model="ensemble")])
    candidate["meta"] = {"active_models": ["xgb", "condlogit"]}

    rows = C.compare_all(champion, candidate)
    assert rows[0].get("incomparable"), (
        "an ensemble of different models must not be compared silently")
    text = C.format_gate(rows)
    assert "NOT COMPARABLE" in text
    assert "lgbm" in text and "condlogit" in text, "name both compositions"


def test_matching_compositions_compare_without_complaint():
    champion = _result([_outcomes([1, 0] * 50, model="ensemble")])
    champion["meta"] = {"active_models": ["lr", "lgbm", "xgb"]}
    candidate = _result([_outcomes([1, 0] * 50, model="ensemble")])
    candidate["meta"] = {"active_models": ["xgb", "lgbm", "lr"]}   # order differs
    rows = C.compare_all(champion, candidate)
    assert not rows[0].get("incomparable")
    assert "NOT COMPARABLE" not in C.format_gate(rows)


def test_only_the_ensemble_row_is_flagged():
    """A named model means the same thing in both runs regardless."""
    champion = _result([_outcomes([1, 0] * 50, model="xgb"),
                        _outcomes([1, 0] * 50, model="ensemble")])
    champion["meta"] = {"active_models": ["lr", "xgb"]}
    candidate = _result([_outcomes([1, 0] * 50, model="xgb"),
                         _outcomes([1, 0] * 50, model="ensemble")])
    candidate["meta"] = {"active_models": ["xgb", "condlogit"]}
    by_model = {r["model"]: r for r in C.compare_all(champion, candidate)}
    assert by_model["ensemble"].get("incomparable")
    assert not by_model["xgb"].get("incomparable")


def test_missing_metadata_does_not_invent_a_mismatch():
    """Runs saved before this was recorded must still compare."""
    champion = _result([_outcomes([1, 0] * 50, model="ensemble")])
    candidate = _result([_outcomes([1, 0] * 50, model="ensemble")])
    assert C.ensemble_mismatch(champion, candidate) is None
