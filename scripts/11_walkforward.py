#!/usr/bin/env python3
"""Walk-forward evaluation: retrain the whole recipe once per season.

A single train/val/test split answers "how good was this model on 2025?" and
nothing else. One season is 283 games, so a Top-1 figure from it carries about
three points of standard error — wide enough that most of the changes made to
this model land inside it. Worse, the split freezes two seasons out of the
training set permanently: production learns nothing from 2024 or 2025 even
though both have finished.

This retrains from scratch for each test season, always predicting forward:

    test 2024  ->  train <=2022, validate 2023
    test 2025  ->  train <=2023, validate 2024

Nothing from the test season, or after it, touches the fit. Averaging the folds
gives an out-of-sample estimate over several times the games, and it is the
evidence for whether rolling the production split forward is safe.

The mechanics now live in `src/evaluation/harness.py`, which the experiment
runner shares, so a model choice and an experiment are measured by the same
code over the same folds. This script is the report over it.

**The denominator changed.** It used to count only games whose scorer survived
`_filter_low_activity`, so a game whose scorer was filtered out vanished from
the measurement instead of counting as a miss — 16 games on first TD, 1 on
anytime, worth about 0.2 points of Top-1. It is now every played game with a
scorer anywhere in the candidate pool, which is also what makes candidate-pool
experiments comparable at all. See `src/evaluation/ranking`.

    python scripts/11_walkforward.py --target anytime_td
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

import polars as pl

from src.evaluation.harness import run, save, summarize
from src.evaluation.ranking import pooled
from src.utils.config import get_config
from src.utils.paths import get_path


def _fold_rows(result: dict, market: str) -> list[dict]:
    """One row per (model, test season), in the shape this file has always had.

    `tests/test_leakage.py` and the app's Model performance strip read this
    artifact, so the schema is kept even though the numbers behind it are now
    measured over the corrected denominator.
    """
    outcomes = result["outcomes"].filter(pl.col("target_type") == market)
    rows = []
    for r in result["row_metrics"]:
        if r["target_type"] != market:
            continue
        sub = outcomes.filter((pl.col("model") == r["model"])
                              & (pl.col("test_season") == r["test_season"]))
        stats = pooled(sub)
        rows.append({
            "test_season": r["test_season"],
            "games": stats["games"],
            "brier": r["brier"],
            "auc": r["auc"],
            "top1": stats["top1"],
            "top3": stats["top3"],
            "top5": stats["top5"],
            "median_rank": stats["median_rank"],
            "sum_per_game": r["sum_per_game"],
            "actual_per_game": r["actual_per_game"],
            "unranked_games": stats["unranked_games"],
            "model": r["model"],
        })
    return sorted(rows, key=lambda r: (r["model"], r["test_season"]))


def main(target_type: str, first_test: int, last_test: int, model_name: str) -> int:
    result = run({}, markets=(target_type,), first_test=first_test,
                 last_test=last_test)
    summary = summarize(result)[target_type]
    rows = _fold_rows(result, target_type)
    save(result, f"walkforward-{target_type}")

    print(f"\n{'=' * 78}")
    print(f"WALK-FORWARD — {target_type}")
    print("=" * 78)
    for name, s in summary.items():
        line = f"  {name:10s}"
        for k in (1, 3, 5):
            line += f"  Top-{k} {s[f'top{k}']:5.1%} +/-{s[f'top{k}_se']:.1%}"
        line += f"  AUC {s['auc']:.4f}"
        print(line)

    print(f"\nPer fold ({model_name}):")
    print(f"{'test':>6} {'games':>6} {'Top-1':>8} {'Top-3':>8} {'Top-5':>8} "
          f"{'AUC':>8} {'Brier':>9} {'sum/game':>10}")
    for r in [x for x in rows if x["model"] == model_name]:
        print(f"{r['test_season']:>6} {r['games']:>6} {r['top1']:>7.1%} "
              f"{r['top3']:>7.1%} {r['top5']:>7.1%} {r['auc']:>8.4f} "
              f"{r['brier']:>9.5f} {r['sum_per_game']:>6.2f}/{r['actual_per_game']:.2f}")

    prod = [r for r in rows if r["model"] == model_name]
    total = sum(r["games"] for r in prod)
    stats = summary[model_name]
    print("-" * 78)
    for k, label in [("top1", "Top-1"), ("top3", "Top-3"), ("top5", "Top-5")]:
        print(f"  pooled {label}: {stats[k]:.1%}  +/- {stats[k + '_se']:.1%} "
              f"(1se over {stats['games']} games)")
    # Row-weighted, matching the table above. These used to be weighted by games
    # up here and by rows there, so the same model printed two different AUCs a
    # dozen lines apart. AUC is not exactly poolable across folds either way —
    # this is the average of per-fold AUCs, not one AUC over concatenated
    # seasons, which would rank players from different years against each other.
    print(f"  pooled AUC:   {stats['auc']:.4f}  (row-weighted mean of per-fold AUCs)")
    print(f"  pooled Brier: {stats['brier']:.5f}")

    unranked = sum(r["unranked_games"] for r in prod)
    if unranked:
        print(f"\n  {unranked} of {total} games had no ranked scorer and count as "
              f"misses (the filter removed every scorer).")
    print(f"  Coin flips (top two within a point): "
          f"{summary[model_name]['coin_flip_share']:.1%} of games.")
    print("\n  These pooled standard errors are unpaired. To compare two "
          "recipes, use\n  `python scripts/23_experiment.py`, which pairs by "
          "game — far more power.")

    out = get_path("output", target_type) / "walkforward.json"
    # Wrapped with provenance rather than written as a bare list. A version
    # manifest reads its accuracy out of this file, and on 2026-08-19 it read
    # anytime TD's full-feature numbers into a lean-feature lock and first TD's
    # leaked-matrix numbers into a clean one — the manifest described a model
    # that was not the one it was recording. `pooled_walkforward` still accepts
    # the bare list for files written before this.
    from src.evaluation.harness import _features, feature_matrix_hash
    from src.models.trainer import get_feature_cols
    n_features = len(get_feature_cols(_features(target_type), target_type))
    out.write_text(json.dumps({
        "measured": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target": target_type,
        "feature_hash": feature_matrix_hash(target_type),
        "n_features": n_features,
        "rows": rows,
    }, indent=2))
    print(f"\nSaved per-fold detail: {out}")
    print(f"Saved per-game rows:   "
          f"{get_path('output') / 'experiments' / f'walkforward-{target_type}'}")
    return 0


if __name__ == "__main__":
    cfg = get_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=cfg["target"]["type"])
    # Four folds by default, not two. This defaulted to `val_season`, which
    # gives two, and two folds put the standard error on Top-1 at +/-2.1% —
    # wider than the gaps between the models it exists to choose between. So a
    # plain `make walkforward` quietly replaced a four-fold artifact with one
    # too thin to answer the question, and
    # tests/test_leakage.py::test_each_market_serves_its_best_walkforward_model
    # reads whatever it finds.
    ap.add_argument("--first-test", type=int,
                    default=cfg["splits"]["test_season"] - 3)
    ap.add_argument("--last-test", type=int, default=cfg["splits"]["test_season"])
    # Resolved after parsing: the right model depends on --target.
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    if a.model is None:
        from src.utils.config import production_model
        a.model = production_model(a.target)
    sys.exit(main(a.target, a.first_test, a.last_test, a.model))
