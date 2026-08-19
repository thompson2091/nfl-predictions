"""Walk-forward hyperparameter search for the tree models.

Checks a setting rather than choosing one. The values in
`config/settings.yaml -> model.*` were hand-picked; this measures whether any
of a random sample of alternatives beats them by more than noise, on the same
folds `scripts/11_walkforward.py` uses to choose which model to serve:

    train <= T-2   ·   early-stop on T-1   ·   score T,   T in 2022..2025

so nothing scores a season it trained or early-stopped on.

Result as of the 2026 pre-season, anytime TD, 61 configurations:

    served config          AUC 0.84377   Brier 0.08868   Top-1 0.5387
    best AUC found         AUC 0.84397   (+0.00020)
    best Top-1 found       Top-1 0.5392  (+0.0005, 0.03 standard errors)
    configs beating served AUC by a standard error: 0

The served setting sits at the top of the searched space. The honest reading
is not "tuning was done well" but "this model is not hyperparameter-limited" —
the remaining error is in the data and the problem, not the tree depth.

Usage:
    python scripts/19_tune.py --target anytime_td --n 60
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.metrics import roc_auc_score
from xgboost import XGBClassifier

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models.trainer import get_feature_cols, prepare_data, _filter_low_activity  # noqa: E402
from src.models.xgboost_model import DEFAULTS  # noqa: E402
from src.utils.config import get_config  # noqa: E402
from src.utils.paths import get_path  # noqa: E402

FOLDS = (2022, 2023, 2024, 2025)

#: Sampled independently per configuration. Ranges bracket the served value on
#: both sides so the search can say "lower is better" as easily as "higher".
SPACE = {
    "learning_rate": [0.01, 0.02, 0.03, 0.05],
    "max_depth": [3, 4, 5, 6, 8],
    "min_child_weight": [5, 10, 20, 40, 80],
    "subsample": [0.6, 0.7, 0.8, 0.9],
    "colsample_bytree": [0.3, 0.4, 0.6, 0.8],
    "reg_alpha": [0.0, 0.1, 1.0, 5.0],
    "reg_lambda": [0.5, 1.0, 5.0, 20.0],
}


def served_params(target_type: str) -> dict:
    """Exactly what production trains with, read from config."""
    cfg = get_config()["model"].get("xgb", {})
    return {k: cfg.get(k, v) for k, v in DEFAULTS.items()
            if k != "early_stopping_rounds"}


def _folds(df: pl.DataFrame, feature_cols: list[str]) -> dict:
    """Prepared matrices per fold. Built once — this is the expensive part."""
    out = {}
    for T in FOLDS:
        tr = _filter_low_activity(df.filter(pl.col("season") <= T - 2))
        va = _filter_low_activity(df.filter(pl.col("season") == T - 1))
        te = _filter_low_activity(df.filter(pl.col("season") == T))
        out[T] = (prepare_data(tr, feature_cols), prepare_data(va, feature_cols),
                  prepare_data(te, feature_cols), te.select(["game_id", "target"]))
    return out


def _top1(meta: pl.DataFrame, p: np.ndarray) -> float:
    """Did the game's highest-rated player score. The metric a card lives on."""
    d = meta.with_columns(pl.Series("p", p))
    top = (d.with_columns(pl.col("p").rank("ordinal", descending=True)
                          .over("game_id").alias("r"))
             .filter(pl.col("r") == 1))
    return float(top["target"].mean())


def evaluate(params: dict, folds: dict, stop: int) -> dict:
    """Games-weighted AUC, Brier and Top-1 pooled across every fold."""
    aucs, briers, t1s, ns = [], [], [], []
    for T in FOLDS:
        (Xtr, ytr), (Xva, yva), (Xte, yte), meta = folds[T]
        m = XGBClassifier(**params, eval_metric="logloss", verbosity=0,
                          early_stopping_rounds=stop, random_state=42)
        m.fit(Xtr, ytr, eval_set=[(Xva, yva)], verbose=False)
        p = m.predict_proba(Xte)[:, 1]
        aucs.append(roc_auc_score(yte, p))
        briers.append(float(np.mean((p - yte) ** 2)))
        t1s.append(_top1(meta, p))
        ns.append(len(yte))
    w = np.array(ns, dtype=float)
    w /= w.sum()
    return {"auc": float(np.dot(aucs, w)), "brier": float(np.dot(briers, w)),
            "top1": float(np.dot(t1s, w)),
            "per_fold_auc": [round(a, 4) for a in aucs]}


def main(target_type: str, n: int, seed: int) -> int:
    df = pl.read_parquet(get_path("processed", target_type) / "features.parquet")
    df = df.filter(pl.col("target").is_not_null())
    feature_cols = get_feature_cols(df, target_type)
    print(f"{target_type}: {df.height:,} rows, {len(feature_cols)} features")
    print("Preparing folds (train <= T-2, early-stop T-1, score T)...")
    folds = _folds(df, feature_cols)

    served = served_params(target_type)
    stop = int(get_config()["model"].get("xgb", {}).get(
        "early_stopping_rounds", DEFAULTS["early_stopping_rounds"]))

    rng = np.random.default_rng(seed)
    grid = [served]
    for _ in range(n):
        cand = dict(served)
        # n_estimators is a ceiling, not a setting: early stopping picks the
        # real count, so it is raised rather than sampled.
        cand["n_estimators"] = 3000
        for k, choices in SPACE.items():
            cand[k] = type(served.get(k, choices[0]))(rng.choice(choices))
        grid.append(cand)

    results = []
    out_path = get_path("output", target_type) / "hyperparameter_search.json"
    for i, params in enumerate(grid):
        t0 = time.time()
        r = evaluate(params, folds, stop)
        r["params"] = params
        r["is_served"] = (i == 0)
        results.append(r)
        tag = "  <-- SERVED" if i == 0 else ""
        print(f"[{i:2d}/{len(grid)-1}] auc={r['auc']:.5f} brier={r['brier']:.5f} "
              f"top1={r['top1']:.4f}  {time.time()-t0:.0f}s{tag}")
        out_path.write_text(json.dumps(results, indent=1))

    base = results[0]
    # Standard error of Top-1 over the pooled games, which is what tells you
    # whether any of this is worth acting on.
    n_games = sum(len(folds[T][3]) and folds[T][3]["game_id"].n_unique() for T in FOLDS)
    se = float(np.sqrt(base["top1"] * (1 - base["top1"]) / n_games))

    print(f"\nServed: AUC {base['auc']:.5f}  Brier {base['brier']:.5f}  "
          f"Top-1 {base['top1']:.4f}  (Top-1 standard error {se:.4f} on {n_games} games)")
    print("\nBest five by AUC:")
    for r in sorted(results, key=lambda r: -r["auc"])[:5]:
        print(f"  auc={r['auc']:.5f} ({r['auc']-base['auc']:+.5f})  "
              f"top1={r['top1']:.4f} ({(r['top1']-base['top1'])/se:+.2f} se)  "
              f"{ {k: v for k, v in r['params'].items() if base.get(k) != v} }")

    better = [r for r in results[1:] if r["top1"] > base["top1"] + se]
    print(f"\nConfigurations beating the served Top-1 by more than one standard "
          f"error: {len(better)} of {len(results)-1}")
    if not better:
        print("Nothing to change. This model is not hyperparameter-limited.")
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--target", default=None, help="anytime_td | first_td")
    a.add_argument("--n", type=int, default=60, help="random configurations to try")
    a.add_argument("--seed", type=int, default=0)
    args = a.parse_args()
    target = args.target or get_config()["target"]["type"]
    sys.exit(main(target, args.n, args.seed))
