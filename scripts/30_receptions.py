#!/usr/bin/env python3
"""Train and honestly grade the receptions count model.

The third target type, and a different shape from the two before it: a count,
graded per (player, line) rather than per player, in the lowest-hold market on
the board (~7% overround against anytime TD's ~23%, measured on our own
archive). One model prices every line — see src/models/count.py for why a
classifier per line is the wrong tool.

What this script deliberately is NOT: a claim of betting edge. The first
version of this model beat the receptions market by +17-22% ROI, which is how
the NGS existence leak was found — the edge was the leak. On clean features it
does not beat the market, and the summary this writes says so in numbers
rather than leaving the reader to infer it.

    python scripts/30_receptions.py            # train + backtest + artifacts
    python scripts/30_receptions.py --skip-train   # re-grade existing model
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

sys.path.insert(0, ".")

import numpy as np
import polars as pl

from src.models.count import (XGBCountModel, design_matrix, fair_two_way,
                             prob_over)
from src.utils.config import get_config
from src.utils.paths import get_path

#: Identifier columns of the shared feature matrix; everything else numeric is
#: a feature. The matrix is REUSED from anytime_td rather than rebuilt — the
#: candidate pool (who is on a roster this week) and the features (usage,
#: matchup, pace) answer the receptions question as directly as the touchdown
#: one, and a second copy of an 80MB matrix would only drift from the first.
ID_COLS = {"game_id", "season", "week", "home_team", "away_team", "game_type",
           "player_id", "player_name", "team", "target", "receptions"}


def _frame() -> tuple[pl.DataFrame, list[str]]:
    feats = pl.read_parquet(get_path("processed", "anytime_td") / "features.parquet")
    ws = (pl.scan_parquet(get_path("raw") / "weekly_stats.parquet")
          .select(["season", "week", "player_id", "receptions"]).collect())
    df = feats.join(ws, on=["season", "week", "player_id"], how="left")
    # A row with no weekly stat is a player who did not play. For a TD target
    # those rows train as zeros; for a count label they are simply unknowable
    # before kickoff WHETHER he plays — but the label itself requires he did.
    df = df.filter(pl.col("receptions").is_not_null())
    fcols = [c for c in df.columns if c not in ID_COLS and df[c].dtype.is_numeric()]
    return df, fcols


def train(df: pl.DataFrame, fcols: list[str]) -> XGBCountModel:
    cfg = get_config()
    tr = df.filter(pl.col("season") <= cfg["splits"]["train_end"])
    va = df.filter(pl.col("season") == cfg["splits"]["val_season"])

    def XY(d):
        # `design_matrix`, not a bare `to_numpy`, so training and the weekly
        # board build the matrix from one definition. See src/models/count.py.
        return design_matrix(d, fcols), d["receptions"].to_numpy().astype(float)

    Xtr, ytr = XY(tr)
    Xva, yva = XY(va)
    m = XGBCountModel()
    m.feature_names = fcols
    m.fit(Xtr, ytr, Xva, yva,
          get_config().get("model", {}).get("xgb_count", {}) | {"seed": get_config()["model"]["seed"]})
    print(f"Trained on {tr.height:,} rows (<= {cfg['splits']['train_end']}), "
          f"dispersion fitted on {va.height:,} ({cfg['splits']['val_season']}): "
          f"r = {m.dispersion}")
    return m


def graded_lines(season: int) -> pl.DataFrame | None:
    """Archived closing lines joined to what the player actually caught."""
    from src.ingest.odds_history import HISTORY_PATH, SCHEMA, _conform, _resolve_player_id

    if not HISTORY_PATH.exists():
        return None
    h = _conform(pl.read_parquet(HISTORY_PATH), SCHEMA).filter(
        (pl.col("market") == "receptions") & (pl.col("snapshot") == "close")
        & (pl.col("season") == season) & pl.col("point").is_not_null())
    if h.height == 0:
        return None
    h = h.with_columns(_resolve_player_id(h)).filter(pl.col("player_id").is_not_null())
    ws = (pl.scan_parquet(get_path("raw") / "weekly_stats.parquet")
          .select(["season", "week", "player_id", "receptions"]).collect())
    # fair_prob is null where only one side was posted; a market comparison
    # over rows where the market has no de-vigged number would be NaN, which
    # is how the 2025 column first printed as `nan` and read as a broken model
    # rather than a thin book.
    return h.join(ws, on=["season", "week", "player_id"], how="inner").filter(
        pl.col("receptions").is_not_null() & pl.col("fair_prob").is_not_null())


def backtest(m: XGBCountModel, df: pl.DataFrame, fcols: list[str], season: int) -> dict | None:
    lines = graded_lines(season)
    if lines is None or lines.height == 0:
        print(f"  {season}: no graded lines in the archive")
        return None
    te = df.filter(pl.col("season") == season)
    mu = m.predict_mu(design_matrix(te, fcols))
    te = te.select(["season", "week", "player_id", "game_id"]).with_columns(
        pl.Series("mu", mu))
    j = lines.join(te, on=["season", "week", "player_id"], how="inner")

    over, push = prob_over(j["mu"].to_numpy(), j["point"].to_numpy(), m.dispersion)
    p_model = fair_two_way(over, push)
    y_raw = j["receptions"].to_numpy()
    line = j["point"].to_numpy()
    gradeable = y_raw != line                      # whole-number pushes drop out
    y = (y_raw > line).astype(float)[gradeable]
    pm = p_model[gradeable]
    pk = j["fair_prob"].to_numpy()[gradeable]

    def ll(p):
        q = np.clip(p, 1e-9, 1 - 1e-9)
        return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))

    out_dir = get_path("output", "receptions")
    bt = j.filter(pl.Series(gradeable)).with_columns([
        pl.Series("p_model", pm), pl.Series("y_over", y)])
    bt.select(["season", "week", "game_id", "player_name_raw", "player_id",
               "point", "odds", "implied_prob", "fair_prob", "p_model",
               "receptions", "y_over"]).write_csv(out_dir / f"backtest_{season}.csv")

    res = {
        "season": season, "n": int(len(y)), "pushes": int((~gradeable).sum()),
        "over_rate": float(y.mean()),
        "model": {"log_loss": ll(pm), "brier": float(np.mean((pm - y) ** 2)),
                  "mean_p": float(pm.mean())},
        "market": {"log_loss": ll(pk), "brier": float(np.mean((pk - y) ** 2)),
                   "mean_p": float(pk.mean())},
    }
    tag = "model better" if res["model"]["log_loss"] < res["market"]["log_loss"] \
        else "MARKET better"
    print(f"  {season}: n={len(y):,}  log loss model {res['model']['log_loss']:.5f} "
          f"vs market {res['market']['log_loss']:.5f}  ({tag})")
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-train", action="store_true",
                    help="Reuse models/receptions/xgb_count.pkl instead of refitting.")
    args = ap.parse_args()

    cfg = get_config()
    df, fcols = _frame()
    print(f"Receptions frame: {df.height:,} labelled rows, {len(fcols)} features")

    model_dir = get_path("models", "receptions")
    model_path = model_dir / "xgb_count.pkl"
    if args.skip_train and model_path.exists():
        m = XGBCountModel.load(model_path)
        print(f"Loaded {model_path} (dispersion r = {m.dispersion})")
    else:
        m = train(df, fcols)
        m.save(model_path)
        print(f"Saved -> {model_path}")

    results = []
    for season in (cfg["splits"]["val_season"], cfg["splits"]["test_season"]):
        r = backtest(m, df, fcols, season)
        if r:
            results.append(r)

    summary = {
        "kind": "receptions_summary",
        "fit_date": date.today().isoformat(),
        "dispersion": m.dispersion,
        "n_features": len(fcols),
        "splits": {k: cfg["splits"][k] for k in ("train_end", "val_season", "test_season")},
        "seasons": results,
        # Stated here so no screen has to infer it: this model does not beat
        # this market. The first version that appeared to (+17-22% ROI) is how
        # the NGS existence leak was found.
        "beats_market": bool(results) and all(
            r["model"]["log_loss"] < r["market"]["log_loss"] for r in results),
    }
    path = get_path("output", "receptions") / "summary.json"
    path.write_text(json.dumps(summary, indent=1))
    print(f"\nSummary -> {path}")
    print(f"beats_market: {summary['beats_market']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
