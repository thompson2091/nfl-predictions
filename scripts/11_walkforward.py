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
evidence for whether rolling the production split forward is safe: if a model
trained through 2023 predicts 2025 as well as one trained through 2022 predicts
2024, the recipe travels and the extra season is free accuracy.

Each fold writes its artifacts to a scratch directory, so nothing production
serves is touched.

    python scripts/11_walkforward.py --target anytime_td
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

import numpy as np
import polars as pl

from src.utils.config import get_config
from src.utils.paths import get_path


def _fold_metrics(model_dir: Path, output_dir: Path, target_type: str,
                  test_season: int, model_name: str) -> dict | None:
    """Score the fold's saved model on its held-out season, joint path included."""
    import pickle

    from src.models.joint import apply_joint, load_team_rate, load_conversion
    from src.models.registry import ensure_registered
    from src.models.scoring import score
    from src.models.trainer import prepare_data, _filter_low_activity
    from sklearn.metrics import brier_score_loss, roc_auc_score

    ensure_registered()
    fc = pickle.loads((model_dir / "feature_cols.pkl").read_bytes())
    feats = pl.read_parquet(get_path("processed", target_type) / "features.parquet")
    te = _filter_low_activity(
        feats.filter((pl.col("season") == test_season) & pl.col("target").is_not_null())
    )
    if te.height == 0:
        return None
    X, _ = prepare_data(te, fc)

    # Through src.models.scoring.score, which is the whole point of that module:
    # this function used to load each model and apply its calibrator by hand,
    # making it a fifth private copy of the scoring path alongside the four the
    # module was written to replace. The copy silently skipped the tie-break
    # that resolves players sharing an isotonic step, so the table used to
    # choose which model to serve described a pipeline production does not run.
    probs = score(model_name, X, fc, model_dir)

    ev = te.with_columns(pl.Series("prob", probs))
    team_model = load_team_rate(model_dir / "team_td_rate.json")
    if target_type != "first_td" and team_model is not None:
        # Each fold fits its own conversion, so apply that fold's — otherwise
        # the walk-forward scores a different pipeline than production runs.
        ev = apply_joint(ev, te, team_model, score_col="prob", out_col="prob",
                         conversion=load_conversion(model_dir / "td_conversion.json"))
    probs = ev["prob"].to_numpy()

    ev = ev.with_columns(
        pl.col("prob").rank(descending=True, method="ordinal")
        .over("game_id").alias("r")
    )
    best = (
        ev.filter(pl.col("target") == 1).group_by("game_id")
        .agg(pl.col("r").min().alias("b"))["b"].to_list()
    )
    y = ev["target"].to_numpy().astype(float)
    n, games = len(best), ev["game_id"].n_unique()
    return {
        "test_season": test_season,
        "games": n,
        "brier": float(brier_score_loss(y, probs)),
        "auc": float(roc_auc_score(y, probs)),
        "top1": sum(r == 1 for r in best) / n,
        "top3": sum(r <= 3 for r in best) / n,
        "top5": sum(r <= 5 for r in best) / n,
        "median_rank": float(np.median(best)),
        "sum_per_game": float(probs.sum() / games),
        "actual_per_game": float(y.sum() / games),
    }


def main(target_type: str, first_test: int, last_test: int, model_name: str) -> int:
    from src.models.trainer import train_all

    feats = pl.read_parquet(get_path("processed", target_type) / "features.parquet")
    played = sorted(
        feats.filter(pl.col("target").is_not_null())["season"].unique().to_list()
    )
    tests = [s for s in range(first_test, last_test + 1) if s in played]
    if not tests:
        print("No completed seasons in that range.")
        return 1

    cfg_models = list(get_config()["models"]["active"])
    scored_models = cfg_models + (["ensemble"] if len(cfg_models) > 1 else [])
    print(f"Scoring models per fold: {', '.join(scored_models)}")

    rows = []
    scratch = Path(tempfile.mkdtemp(prefix="walkforward_"))
    try:
        for test_season in tests:
            splits = {
                "train_end": test_season - 2,
                "val_season": test_season - 1,
                "test_season": test_season,
            }
            print(f"\n{'=' * 72}")
            print(f"FOLD: train <={splits['train_end']}  val {splits['val_season']}  "
                  f"test {test_season}")
            print("=" * 72)
            fold_models = scratch / f"{test_season}_models"
            fold_output = scratch / f"{test_season}_output"
            train_all(target_type, splits=splits,
                      model_dir=fold_models, output_dir=fold_output)
            # Score every model from this one fold. Training dominates the
            # cost and it already fits all of them, so scoring each is nearly
            # free — and the app lets you switch model, which needs a
            # walk-forward figure per model or the strip silently keeps showing
            # the production model's numbers whatever you pick.
            for name in scored_models:
                m = _fold_metrics(fold_models, fold_output, target_type,
                                  test_season, name)
                if m:
                    m["model"] = name
                    rows.append(m)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    if not rows:
        print("No folds produced metrics.")
        return 1

    print(f"\n{'=' * 72}")
    print(f"WALK-FORWARD — {target_type}")
    print("=" * 72)
    for name in scored_models:
        sub = [r for r in rows if r["model"] == name]
        if not sub:
            continue
        tot = sum(r["games"] for r in sub)
        line = f"  {name:10s}"
        for k, lab in [("top1", "Top-1"), ("top3", "Top-3"), ("top5", "Top-5")]:
            p = sum(r[k] * r["games"] for r in sub) / tot
            se = np.sqrt(p * (1 - p) / tot)
            line += f"  {lab} {p:5.1%} +/-{se:.1%}"
        line += f"  AUC {sum(r['auc'] * r['games'] for r in sub) / tot:.4f}"
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
    print("-" * 72)
    for k, label in [("top1", "Top-1"), ("top3", "Top-3"), ("top5", "Top-5")]:
        # Weight by games so a short season does not count as much as a full one,
        # and report the binomial standard error on the pooled figure.
        pooled = sum(r[k] * r["games"] for r in prod) / total
        se = np.sqrt(pooled * (1 - pooled) / total)
        print(f"  pooled {label}: {pooled:.1%}  +/- {se:.1%} (1se over {total} games)")
    print(f"  pooled AUC:   {sum(r['auc'] * r['games'] for r in prod) / total:.4f}")
    print(f"  pooled Brier: {sum(r['brier'] * r['games'] for r in prod) / total:.5f}")

    out = get_path("output", target_type) / "walkforward.json"
    out.write_text(json.dumps(rows, indent=2))
    print(f"\nSaved per-fold detail: {out}")
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
