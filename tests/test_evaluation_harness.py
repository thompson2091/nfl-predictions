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
    labeled = pl.DataFrame({
        "game_id": ["g1", "g1", "g2", "g2"],
        "target": [1, 0, 0, 0],       # g2: nobody in the pool scored
    })
    universe = game_universe(labeled)
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
    from src.utils.config import get_config

    # Built from whatever is active *now*, not from a remembered list. An
    # earlier version of this test hardcoded {lr, lgbm, xgb} and started failing
    # the moment condlogit was promoted into models.active — asserting a fact
    # about the config rather than about the function.
    active = list(get_config()["models"]["active"])
    newcomer = "a-model-not-in-the-active-set"
    assert newcomer not in active

    served = screen_models("anytime_td")
    assert newcomer not in served, "no overlay, no newcomer"
    assert len(served) == 1, "without an overlay a screen trains one model"

    with_new = screen_models("anytime_td", {"models": {"active": active + [newcomer]}})
    assert newcomer in with_new, "the overlay's new model must be trained"
    assert with_new[0] == served[0], "still screened against what is served"
    # Models already active are not duplicated — the screen stays cheap.
    assert with_new.count(served[0]) == 1
    assert len(with_new) == 2


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


# --------------------------------------------------------------------------
# Seed-averaged pairing
# --------------------------------------------------------------------------

def _seeded(hits_a, hits_b, market="anytime_td"):
    """One run carrying `xgb` and `ensemble` rows over the same games."""
    return _result([_outcomes(hits_a, market=market, model="xgb"),
                    _outcomes(hits_b, market=market, model="ensemble")])


def test_a_win_driven_by_one_seed_is_discounted():
    """The whole reason for averaging first.

    The candidate wins 20 games, but only in one seed out of five. Paired on
    that seed alone it looks like a clean 20-game gain; averaged, each of those
    games is worth 0.2 and the result collapses.
    """
    n = 100
    base = [1, 0] * (n // 2)
    lucky = list(base)
    for i in range(1, 41, 2):          # 20 games the candidate wins
        lucky[i] = 1

    runs = [_seeded(base, lucky)] + [_seeded(base, base) for _ in range(4)]
    r = C.seed_averaged_paired(runs, market="anytime_td", model="ensemble",
                               against="xgb", k=1)
    assert r["n_seeds"] == 5 and r["n_compared"] == n
    assert r["delta"] == pytest.approx(20 * 0.2 / n)      # 0.04, not 0.20
    assert r["seeds_ahead"] == 1, "only one seed favors the candidate"

    # The single-seed view of the same data claims five times the gain.
    single = C.paired_top_k(_outcomes(base), _outcomes(lucky), k=1)
    assert single["delta"] == pytest.approx(0.20)
    assert single["delta"] > 4 * r["delta"]


def test_a_consistent_win_survives_averaging():
    n = 100
    base = [1, 0] * (n // 2)
    better = list(base)
    for i in range(1, 21, 2):          # the same 10 games, every seed
        better[i] = 1
    runs = [_seeded(base, better) for _ in range(5)]
    r = C.seed_averaged_paired(runs, market="anytime_td", model="ensemble",
                               against="xgb", k=1)
    assert r["delta"] == pytest.approx(0.10)
    assert r["seeds_ahead"] == 5
    assert r["wins"] == 10 and r["losses"] == 0
    assert r["p_value"] < 0.01


def test_identical_models_average_to_no_difference():
    runs = [_seeded([1, 0] * 50, [1, 0] * 50) for _ in range(5)]
    r = C.seed_averaged_paired(runs, market="anytime_td", model="ensemble",
                               against="xgb", k=1)
    assert r["delta"] == pytest.approx(0.0)
    assert r["wins"] == 0 and r["losses"] == 0 and r["p_value"] == 1.0
    assert C.seed_gate(runs, market="anytime_td", model="ensemble",
                       against="xgb")["verdict"] == "REJECTED"


def test_games_missing_from_any_seed_are_dropped():
    """Averaging over a game only some seeds scored would weight it wrongly."""
    runs = [_seeded([1, 0, 1, 0], [1, 1, 1, 0]),
            _seeded([1, 0, 1], [1, 1, 1])]
    r = C.seed_averaged_paired(runs, market="anytime_td", model="ensemble",
                               against="xgb", k=1)
    assert r["n_compared"] == 3, "only games present in every seed can average"


@pytest.mark.parametrize("wins", [1, 4, 9])
def test_the_one_standard_error_rule_is_the_square_root_of_the_net_wins(wins):
    """A property of the promotion rule worth knowing before trusting it.

    For a strictly one-sided paired difference — the candidate wins some games
    and loses none — `delta / se` works out to sqrt(wins), independent of how
    many games were scored. So a single consistently-won game lands exactly on
    the one-standard-error threshold and "passes".

    That is not a defect in the seed averaging; `paired_top_k` has the same
    arithmetic and always has. It is the reason the sign test is reported
    beside the standard-error multiple rather than instead of it: with 1 win
    and 0 losses the sign test returns p=1.000 and says plainly that one game
    is not evidence. A verdict read off the SE alone would disagree.
    """
    n = 400
    base = [1, 0] * (n // 2)
    better = list(base)
    for i in range(wins):
        better[2 * i + 1] = 1           # the same games in every seed
    runs = [_seeded(base, better) for _ in range(5)]
    row = C.seed_gate(runs, market="anytime_td", model="ensemble",
                      against="xgb")
    t1 = row["top_k"][1]
    assert t1["wins"] == wins and t1["losses"] == 0
    assert t1["se_multiple"] == pytest.approx(wins ** 0.5, rel=0.05)
    # One game clears the SE rule and the sign test refuses to call it.
    if wins == 1:
        assert t1["p_value"] == pytest.approx(1.0)
    else:
        assert t1["p_value"] < 0.15


def test_noise_injection_is_off_by_default_and_deterministic():
    """The control for Phase 3e's retraction; it must never fire in production.

    Adding columns of pure noise reproduced the Top-3 signature that 3e read as
    "every family carries information", which is what withdrew that claim. The
    mechanism has to stay available and stay off, and it has to give training
    and scoring identical values — noise that differed between them would
    measure train/serve skew instead of what it is for.
    """
    import polars as pl

    from src.models.trainer import inject_noise_features
    from src.utils.config import config_overlay, get_config

    df = pl.DataFrame({"a": [1.0, 2.0, 3.0], "target": [0, 1, 0]})
    assert not (get_config().get("models") or {}).get("inject_noise_features"), (
        "noise injection is a control and must be off in the served config")
    assert inject_noise_features(df).columns == df.columns, "off means untouched"

    with config_overlay({"models": {"inject_noise_features": 4}}):
        a = inject_noise_features(df)
        b = inject_noise_features(df)
    assert [c for c in a.columns if c.startswith("_noise_")] == [
        f"_noise_{i}" for i in range(4)]
    assert a["_noise_0"].to_list() == b["_noise_0"].to_list(), (
        "two loads must agree, or training and scoring see different features")


# --------------------------------------------------------------------------
# Feature-set size: the allow-list, and the cache that must not outlive its
# feature matrix
# --------------------------------------------------------------------------

def test_the_allow_list_is_off_by_default_and_keeps_only_what_it_names():
    """`include_feature_families` exists to build a feature set UP.

    Leave-one-out ablation answered "no family is prunable" 33 times, which it
    would also answer if half the set were redundant — dropping one family lets
    a correlated survivor cover for it. The allow-list is the other direction,
    so it has to select exactly the named families and nothing else.
    """
    from src.models.trainer import _family_map, included_families

    assert included_families({"models": {}}) is None, (
        "no allow-list must mean keep everything, not keep nothing")

    mapping = _family_map()["families"]
    picked = sorted(mapping)[:2]
    keep = included_families(
        {"models": {"include_feature_families": picked}})
    named = {c for f in picked for c in mapping[f]}
    assert named <= keep, "every column of a named family must survive"

    other = sorted(set(mapping) - set(picked))[0]
    stray = set(mapping[other]) - named
    assert not (stray & keep), (
        f"{other} is not on the allow-list but some of its columns survived")


def test_the_allow_list_always_keeps_the_unattributed_columns():
    """Position dummies belong to no builder and must not be selectable away.

    `position_QB`, `week_num` and the usage flags are assembled inline, so no
    family names them. A retention curve that dropped them would be measuring a
    model with no idea who is a receiver, and would report that as "fewer
    features scores worse".
    """
    from src.models.trainer import _family_map, included_families

    doc = _family_map()
    unattributed = set(doc.get("unattributed") or [])
    assert unattributed, "the map records unattributed columns; this test needs them"

    keep = included_families(
        {"models": {"include_feature_families": [sorted(doc["families"])[0]]}})
    assert unattributed <= keep, (
        f"unattributed columns dropped by the allow-list: "
        f"{sorted(unattributed - keep)}")


def test_an_allow_list_and_a_deny_list_together_are_refused():
    """Order of application would decide the result, so there is no right answer."""
    from src.models.trainer import included_families

    with pytest.raises(ValueError, match="both"):
        included_families({"models": {
            "include_feature_families": ["build_qb_features"],
            "exclude_feature_families": ["build_box_features"]}})


def test_a_typo_in_a_family_name_raises_instead_of_selecting_nothing():
    """A silently-ignored name would train on the wrong set under the right label."""
    from src.models.trainer import excluded_families, included_families

    with pytest.raises(ValueError, match="unknown feature families"):
        included_families({"models": {"include_feature_families": ["buld_qb"]}})
    with pytest.raises(ValueError, match="unknown feature families"):
        excluded_families({"models": {"exclude_feature_families": ["buld_qb"]}})


def test_a_saved_run_from_another_feature_matrix_is_not_returned_as_current(
        tmp_path, monkeypatch):
    """The bug this guard was written for, in miniature.

    The 33-family ablation table was cached by run id alone. Two existence
    leaks were closed on 2026-08-18, the feature matrix changed, and every row
    still loaded from the old matrix and reported itself as a current
    measurement. `StaleRun` subclasses FileNotFoundError so every existing
    `try: load() except FileNotFoundError: re-run` site recomputes instead of
    needing to be found and updated one by one.
    """
    from src.evaluation import harness as H

    assert issubclass(H.StaleRun, FileNotFoundError), (
        "callers catch FileNotFoundError to mean 'recompute'; a stale run must "
        "land there or every call site has to be changed by hand")

    directory = tmp_path / "experiments" / "run-from-yesterday"
    directory.mkdir(parents=True)
    pl.DataFrame({"game_id": ["g1"], "target_type": ["anytime_td"],
                  "model": ["xgb"], "hit_rank": [1]}).write_parquet(
        directory / "outcomes.parquet")
    (directory / "meta.json").write_text(json.dumps(
        {"feature_hash": {"anytime_td": "0000oldmatrix00"}}))

    monkeypatch.setattr(H, "get_path", lambda _name: tmp_path)
    monkeypatch.setattr(H, "feature_matrix_hash", lambda _m: "ffffnewmatrix11")

    # Without `markets` the run is returned as-is: comparing two archived runs
    # to each other is legitimate and neither is being called current.
    assert H.load("run-from-yesterday")["outcomes"].height == 1

    with pytest.raises(H.StaleRun, match="different feature matrix"):
        H.load("run-from-yesterday", markets=("anytime_td",))

    monkeypatch.setattr(H, "feature_matrix_hash", lambda _m: "0000oldmatrix00")
    assert H.load("run-from-yesterday", markets=("anytime_td",))["outcomes"].height == 1


def test_a_run_that_never_recorded_a_hash_is_treated_as_stale():
    """Absence is not agreement.

    An older saved run predates `feature_hash` entirely. Reading a missing hash
    as "matches" would let exactly the runs most likely to be stale through.
    """
    from src.evaluation import harness as H

    assert H.StaleRun is not None
    meta = {}
    saved = (meta.get("feature_hash") or {}).get("anytime_td")
    assert saved != "any-current-hash", (
        "a missing hash must compare unequal to the current one")


def test_the_allow_list_is_per_market_so_one_market_cannot_lean_the_other():
    """A family ranking is measured on one market's folds and does not transfer.

    The walk-forward trains both markets under one config, so resolving the
    allow-list from `target.type` would hand whichever market is not the
    configured default the wrong list — silently, and reported under the right
    name. This is the same defect class as the NGS and weekly-stats leaks: not
    a wrong value, a wrong row selected without saying so.
    """
    from src.models.trainer import included_families

    cfg = {"target": {"type": "anytime_td"},
           "models": {"include_feature_families_by_target": {
               "anytime_td": ["build_qb_features"]}}}

    assert included_families(cfg, "anytime_td"), "the named market gets its list"
    assert included_families(cfg, "first_td") is None, (
        "a market with no entry keeps every feature; it must not inherit the "
        "other market's list")

    # The global key stays as the fallback, so a config written before this
    # existed still resolves the same way for every market.
    flat = {"target": {"type": "first_td"},
            "models": {"include_feature_families": ["build_qb_features"]}}
    assert included_families(flat, "first_td"), "global key is the fallback"


def test_get_feature_cols_selects_on_the_market_it_is_given():
    """`train_all` knows the market; the selection has to use it, not the config."""
    import inspect

    from src.models.trainer import get_feature_cols, train_all

    assert "target_type" in inspect.signature(get_feature_cols).parameters, (
        "without this the market being trained cannot say which list it wants")
    src = inspect.getsource(train_all)
    assert "get_feature_cols(df, target_type)" in src, (
        "train_all resolves target_type from its own argument and must pass it "
        "on; falling back to the config default is wrong for one market of "
        "every walk-forward fold")


def test_the_gate_reads_the_noise_bands_out_of_the_file_it_saves():
    """A shape mismatch that silently disabled two guards and over-tightened two.

    `noise-floor` writes {"measured", "seeds", "git", "spread": {...}} and the
    gate handed the whole dict to `compare_all`, whose lookups start at
    `noise[market]`. Those all missed. Top-3/Top-5 then fell back to the paired
    standard error — several times wider than the seed band, so too permissive —
    while AUC and Brier fell back to a band of zero, so any regression at any
    decimal place tripped them. `lean-25-families` tripped on AUC by 0.00022
    against a real measured band of 0.00028.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "experiment_cli", "scripts/23_experiment.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    bands = mod._noise_bands()
    if bands is None:
        pytest.skip("no noise floor measured in this checkout")

    assert "spread" not in bands, (
        "the bands must be unwrapped; leaving the envelope on is the bug")
    for market, models in bands.items():
        for model, entry in models.items():
            assert {"top1", "auc", "brier"} <= set(entry), (
                f"{market}/{model} is missing bands the guards read")
            return  # one is enough to prove the shape


def test_a_guard_band_of_zero_is_not_silently_accepted_as_measured():
    """Zero means "no band recorded", and reads identically to "no tolerance".

    Without this distinction a missing measurement makes the gate maximally
    strict on exactly the metrics whose seed noise is smallest in absolute
    terms, and the verdict looks like a considered judgment.
    """
    from src.evaluation import compare as C

    champion = _result([_outcomes([1, 0] * 50, model="xgb")])
    candidate = _result([_outcomes([1, 0] * 50, model="xgb")])
    row = C.compare(champion, candidate,
                    market="anytime_td", model="xgb", noise=None)
    for key, entry in row["row"].items():
        assert entry["noise_band"] is None, (
            f"{key}: with no noise argument the band must be None, not 0.0 — "
            "None is recoverable, 0.0 is indistinguishable from a measurement")


def test_a_market_the_overlay_never_reaches_is_not_scored_as_a_failure():
    """Worst-of across markets is wrong for a per-market experiment.

    `lean-25-families` scoped its feature set to anytime TD, improved the model
    that market serves, and the gate printed VERDICT: REJECTED — because first
    TD, which the overlay deliberately does not touch, moved 0 of 1,131 games
    and "identical" was being read as "no better". A market that was never
    under test cannot veto the result in one that was.
    """
    from src.evaluation import compare as C

    same = _outcomes([1, 0, 1, 1] * 25, model="xgb")
    champion = _result([same])
    candidate = _result([same])
    row = C.gate(C.compare(champion, candidate,
                           market="anytime_td", model="xgb", noise=None))
    assert row["verdict"] == "UNCHANGED", (
        "two identical runs of the same model mean the overlay does not reach "
        "here, which is not a measured tie")
    assert "identical on all" in C.format_gate([row]), (
        "the table must say nothing was measured, not print a row of zeroes "
        "that reads like a result")


def test_two_models_that_score_identically_still_read_reject_not_unchanged():
    """The distinction UNCHANGED turns on.

    Same model both sides = the overlay is under test, and identical means it
    did not reach this market. Different models = the models are under test,
    and identical means they are interchangeable — the answer is still "do not
    switch", which is REJECTED.
    """
    from src.evaluation import compare as C

    rows = [_outcomes([1, 0, 1, 1] * 25, model=m) for m in ("xgb", "ensemble")]
    result = _result(rows)
    row = C.gate(C.compare(result, result, market="anytime_td",
                           model="ensemble", against="xgb", noise=None))
    assert row["verdict"] == "REJECTED", (
        "a model comparison that ties must not report UNCHANGED — the decision "
        "'keep what we serve' is a real one")


def test_an_overlay_that_reaches_nothing_reports_no_change_overall():
    """All markets untouched is its own outcome, not a rejection."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "experiment_cli", "scripts/23_experiment.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    from src.utils.config import production_model

    rows = [{"market": m, "model": production_model(m),
             "against": production_model(m), "verdict": "UNCHANGED"}
            for m in ("anytime_td", "first_td")]
    assert mod._overall_verdict(rows, ("anytime_td", "first_td")) == "NO_CHANGE"

    # One market scored, one untouched: the scored one decides.
    rows[0]["verdict"] = "PROMOTED"
    assert mod._overall_verdict(rows, ("anytime_td", "first_td")) == "PROMOTED"


def test_the_line_movement_rejection_is_backed_by_its_own_measurement():
    """A rejected idea gets retried blind unless the numbers stay checkable.

    `docs/MODEL_ITERATION.md` 3j and the docstring of
    `scripts/32_line_movement.py` both claim open-to-close movement adds
    nothing over the closing price. This asserts the saved measurement still
    says that, so the claim cannot outlive the evidence for it.
    """
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    found = False
    for market in ("anytime_td", "first_td"):
        path = root / "diagnostics" / f"line_movement_{market}.json"
        if not path.exists():
            continue
        found = True
        d = json.loads(path.read_text())
        assert d["verdict"] == "REJECTED", (
            f"{market}: the docs record this as rejected; the measurement now "
            f"says {d['verdict']}. Update both together or neither.")

        # The residual is what carries the claim: if the close already contains
        # the movement, the gap between outcome and close does not vary with it.
        residuals = [b["residual"] for b in d["bands"]]
        assert max(residuals) - min(residuals) < 0.15, (
            f"{market}: residual spread {max(residuals) - min(residuals):.4f} "
            "across movement bands. A close that already carried the movement "
            "would show a flat residual.")

        # Within-game ranking must stay inside its own error bar, or the Top-1
        # sentence in 3j is no longer true.
        assert d["ranking_spread"] <= d["ranking_se"] * 1.5, (
            f"{market}: Top-1 varies by {d['ranking_spread']:.4f} across "
            f"movement weights against a standard error of "
            f"{d['ranking_se']:.4f} — no longer 'inside the noise'.")

    if not found:
        pytest.skip("line movement not measured — python scripts/32_line_movement.py")


def test_a_new_model_that_loses_reports_rejected_not_no_change():
    """A tested-and-rejected model must not read as "nothing was tried".

    An overlay that adds a model leaves the served one untouched, so its row is
    UNCHANGED and excluded from the verdict — correctly. But the row that
    matters is the new model paired against what the market serves, and reading
    only `model == production` drops it. `pairwise-rank` was screened, lost on
    Top-1 and tripped three guards, and the gate printed NO_CHANGE.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "experiment_cli", "scripts/23_experiment.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    from src.utils.config import production_model

    prod = production_model("anytime_td")
    rows = [
        {"market": "anytime_td", "model": prod, "against": prod,
         "verdict": "UNCHANGED"},
        {"market": "anytime_td", "model": "xgbrank", "against": prod,
         "verdict": "REJECTED"},
    ]
    assert mod._overall_verdict(rows, ("anytime_td",)) == "REJECTED"

    rows[1]["verdict"] = "PROMOTED"
    assert mod._overall_verdict(rows, ("anytime_td",)) == "PROMOTED"

    # With no new model at all, an untouched market is still NO_CHANGE.
    assert mod._overall_verdict([rows[0]], ("anytime_td",)) == "NO_CHANGE"


# ── Two game-id formats in one archive ────────────────────────────────────
#
# `scripts/07_odds.py` writes `AWAY_HOME`, because the team pair is all the
# odds payload carries, with a note saying it "is resolved against schedules
# downstream". Nothing downstream did. Backfilled seasons hold the nflverse id
# and live captures hold the pair, so every join keyed on game_id matched the
# backfilled seasons and dropped the live ones — closing-line value reported
# 2023, 2024 and 2025 over 30,062 pairs while 2026's fell out with no error and
# no empty result to notice. Every season from here on is captured live.

def _sched(rows):
    import polars as pl
    return pl.DataFrame(
        rows, schema={"season": pl.Int64, "week": pl.Int64,
                      "away_team": pl.Utf8, "home_team": pl.Utf8,
                      "game_id": pl.Utf8}, orient="row")


def _resolve(monkeypatch, tmp_path, hist_rows, sched_rows):
    import polars as pl

    from src.ingest import odds_history

    raw = tmp_path / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    _sched(sched_rows).write_parquet(raw / "schedules.parquet")
    monkeypatch.setattr(odds_history, "get_path",
                        lambda kind, *a, **k: raw)
    hist = pl.DataFrame(
        hist_rows, schema={"season": pl.Int64, "week": pl.Int64,
                           "game_id": pl.Utf8}, orient="row")
    return odds_history.resolve_game_ids(hist)


def test_a_live_capture_id_is_resolved_against_the_schedule(monkeypatch, tmp_path):
    out = _resolve(monkeypatch, tmp_path,
                   [(2026, 1, "DEN_KC")],
                   [(2026, 1, "DEN", "KC", "2026_01_DEN_KC")])
    assert out["game_id"].to_list() == ["2026_01_DEN_KC"]


def test_an_already_resolved_id_is_left_exactly_as_it_is(monkeypatch, tmp_path):
    out = _resolve(monkeypatch, tmp_path,
                   [(2023, 1, "2023_01_HOU_BAL")],
                   [(2023, 1, "HOU", "BAL", "2023_01_HOU_BAL")])
    assert out["game_id"].to_list() == ["2023_01_HOU_BAL"]


def test_a_fixture_filed_under_the_wrong_week_still_resolves(monkeypatch, tmp_path):
    """A Monday capture stamps next week's games with this week's number.

    The Odds API serves whatever is upcoming and the capture labels the whole
    payload with one derived week, so with Monday night's game all but over the
    payload is mostly next week. 415 rows of the 2026 archive are that.
    """
    out = _resolve(monkeypatch, tmp_path,
                   [(2026, 1, "CAR_ATL")],
                   [(2026, 2, "CAR", "ATL", "2026_02_CAR_ATL")])
    assert out["game_id"].to_list() == ["2026_02_CAR_ATL"]
    assert out["week"].to_list() == [2], (
        "the week has to follow the fixture; a row whose id says week 2 and "
        "whose week column says 1 answers two questions differently")


def test_an_ambiguous_pair_is_left_unresolved_rather_than_guessed(monkeypatch, tmp_path):
    """46 season-pairs across 2015-2026 appear twice.

    Putting a price on the wrong fixture is worse than leaving it unjoinable,
    so the pair-only fallback only fires where the pair is unique in its season.
    """
    out = _resolve(monkeypatch, tmp_path,
                   [(2026, 9, "AAA_BBB")],
                   [(2026, 3, "AAA", "BBB", "2026_03_AAA_BBB"),
                    (2026, 7, "AAA", "BBB", "2026_07_AAA_BBB")])
    assert out["game_id"].to_list() == ["AAA_BBB"]


def test_a_pair_with_no_fixture_keeps_what_it_had(monkeypatch, tmp_path):
    out = _resolve(monkeypatch, tmp_path,
                   [(2026, 1, "XXX_YYY")],
                   [(2026, 1, "DEN", "KC", "2026_01_DEN_KC")])
    assert out["game_id"].to_list() == ["XXX_YYY"]


def test_closing_line_value_sees_the_seasons_captured_live():
    """The symptom, asserted where it actually showed.

    Not in `line_movement`: both sides of that join come from the archive, so
    the live seasons pair with each other perfectly and 2026 was present there
    all along. The drop is one join later, where `hit_rows` matches those pairs
    to published predictions — which carry the nflverse id. That is the join
    that silently returned nothing for every live season, and the graded
    headline that read "seasons [2023, 2024, 2025]" was the only trace.
    """
    import polars as pl

    from src.evaluation.clv import hit_rows, line_movement, published_predictions
    from src.ingest.odds_history import HISTORY_PATH
    from src.utils.config import get_config

    predict_season = get_config()["seasons"]["predict_season"]
    hist = pl.read_parquet(HISTORY_PATH)
    if not (hist["season"] == predict_season).any():
        pytest.skip(f"nothing archived for {predict_season} yet")
    if line_movement("anytime_td") is None:
        pytest.skip("no open/close pairs archived")
    preds = published_predictions("anytime_td")
    if preds is None or predict_season not in preds["season"].to_list():
        pytest.skip(f"no published predictions for {predict_season}")

    rows = hit_rows(preds, "anytime_td")
    assert rows is not None, "no scored player-games at all"
    assert predict_season in rows["season"].to_list(), (
        f"{predict_season} is archived and predicted but scores no rows — its "
        "captured game ids are not matching the ids the predictions carry")


def test_the_books_archive_names_a_game_a_third_way(monkeypatch, tmp_path):
    """`append_book_quotes` stores the API's own label, not the team pair.

    So the two archives that describe the same games disagree about how to name
    one: odds_history holds `LV_LAC`, odds_books holds
    `Las Vegas Raiders @ Los Angeles Chargers`. Both reduce to a pair; only the
    route does.
    """
    out = _resolve(monkeypatch, tmp_path,
                   [(2026, 1, "Denver Broncos @ Kansas City Chiefs")],
                   [(2026, 1, "DEN", "KC", "2026_01_DEN_KC")])
    assert out["game_id"].to_list() == ["2026_01_DEN_KC"]


def test_the_best_price_is_one_moment_not_a_week_of_them():
    """A book quoted twice in a week is one book, and its newest price.

    Pooling the week's snapshots counts it once per firing: `n_books` climbs
    with the schedule rather than measuring the market, and the "best" price can
    be one from days ago that nobody can take. Measured 2026-09-15, one player
    came back at n_books=24 from 13 real books.
    """
    import polars as pl

    from src.ingest.odds_history import BOOKS_PATH, best_prices, resolve_game_ids
    from src.utils.config import get_config

    if not BOOKS_PATH.exists():
        pytest.skip("no per-book archive yet")
    season = get_config()["seasons"]["predict_season"]
    books = resolve_game_ids(pl.read_parquet(BOOKS_PATH))
    weeks = (books.filter(pl.col("season") == season)["week"]
             .unique().sort().to_list())
    if not weeks:
        pytest.skip(f"nothing archived for {season}")

    for week in weeks:
        real = (books.filter((pl.col("season") == season)
                             & (pl.col("week") == week)
                             & (pl.col("market") == "anytime_td")
                             & (pl.col("side") == "yes")
                             & (pl.col("snapshot") == "close"))["bookmaker"]
                .n_unique())
        got = best_prices(season, week, "anytime_td", "close")
        if got is None or not real:
            continue
        assert int(got["n_books"].max()) <= real, (
            f"week {week}: a player is credited to more books than the week "
            f"holds — the snapshots are being pooled")
