#!/usr/bin/env python3
"""Backtest near-certain alternate-ladder legs on 2024-2025.

Fits each estimate's calibration on 2024 and judges it on 2025. See
src/evaluation/safe_legs.py for what is tested and why.

    python scripts/69_safe_legs.py                  # threshold from config/safe_legs.yaml
    python scripts/69_safe_legs.py --min-prob 0.95  # one-run override
"""
from __future__ import annotations

import argparse
import json
import sys

sys.path.insert(0, ".")

import numpy as np
import polars as pl

from src.evaluation import safe_legs as sl
from src.utils.paths import get_path

FIT, TEST = 2024, 2025
PRICE_BANDS = [(0.0, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.01)]


def build(cfg: dict) -> pl.DataFrame:
    r = sl.rungs([FIT, TEST])
    print(f"  {r.height:,} archived rungs")
    logs = sl.game_logs()
    r = sl.settle(r, logs)
    print(f"  {r.height:,} settled (void and push removed)")
    r = sl.history_rates(r, logs, cfg["history_games"], cfg["history_min_games"])
    r = sl.model_probs(r)
    print(f"  history on {(r['hist_hits'] >= 0).mean():.0%}, "
          f"model on {r['p_model_raw'].is_not_null().mean():.0%}")
    return r.with_columns(
        pl.when(pl.col("hist_hits") >= 0)
          .then((pl.col("hist_hits") + 0.5) / (pl.col("hist_games") + 1.0))
          .alias("p_hist_raw"))


def calibrate(r: pl.DataFrame) -> tuple[pl.DataFrame, dict]:
    """Per market and estimate, a Platt layer fitted on FIT only."""
    fits, cols = {}, {"p_hist": [], "p_model": []}
    parts = []
    for market in sl.ALT_STAT:
        g = r.filter(pl.col("market") == market)
        for est in ("p_hist", "p_model"):
            tr = g.filter((pl.col("season") == FIT) & pl.col(f"{est}_raw").is_not_null())
            ab = sl.fit_platt(tr[f"{est}_raw"].to_numpy(), tr["hit"].to_numpy())
            fits[f"{market}:{est}"] = {"slope": ab[0], "intercept": ab[1], "n": tr.height}
            raw = g[f"{est}_raw"].to_numpy().astype(float)
            cal = np.where(np.isnan(raw), np.nan, sl.apply_platt(np.nan_to_num(raw, nan=0.5), ab))
            g = g.with_columns(pl.Series(est, cal).fill_nan(None))
        parts.append(g)
    r = pl.concat(parts).with_columns(
        pl.min_horizontal("p_hist", "p_model").alias("p_both"))
    return r, fits


def select(r: pl.DataFrame, est: str, t: float, edge: float) -> pl.DataFrame:
    return r.filter(pl.col(est).is_not_null() & (pl.col(est) >= t)
                    & (pl.col(est) - pl.col("implied_prob") >= edge))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-prob", type=float, default=None)
    ap.add_argument("--min-edge", type=float, default=None)
    args = ap.parse_args()
    cfg = sl.settings(min_prob=args.min_prob, min_edge=args.min_edge)
    thresholds = sorted(set(cfg["report_thresholds"]) | {cfg["min_prob"]})

    print("Building rungs")
    r = build(cfg)
    r, fits = calibrate(r)
    out_dir = get_path("output", "safe_legs")
    out_dir.mkdir(parents=True, exist_ok=True)
    r.write_parquet(out_dir / "rungs.parquet")

    res = {"settings": cfg, "fits": fits, "rules": {}}
    rules = {
        # The baseline: every leg the BOOK prices at t or better. If these
        # already pay, no estimate is needed; if not, an estimate must beat it.
        "book": lambda d, t: d.filter(pl.col("implied_prob") >= t),
        "history_raw": lambda d, t: select(d, "p_hist_raw", t, cfg["min_edge"]),
        "history": lambda d, t: select(d, "p_hist", t, cfg["min_edge"]),
        "model": lambda d, t: select(d, "p_model", t, cfg["min_edge"]),
        "both": lambda d, t: select(d, "p_both", t, cfg["min_edge"]),
    }
    est_of = {"book": "implied_prob", "history_raw": "p_hist_raw",
              "history": "p_hist", "model": "p_model", "both": "p_both"}
    print(f"\nmin_edge {cfg['min_edge']:.2f}; per $100 at the median book's price; "
          f"95% interval clustered by game")
    for t in thresholds:
        print(f"\n=== estimate >= {t:.0%} ===")
        print(f"  {'rule':12s} {'season':6s} {'legs':>6s} {'games':>5s} "
              f"{'hit':>6s} {'price':>6s} {'per $100':>9s}  95% interval")
        for name, rule in rules.items():
            for season in (FIT, TEST):
                for scope in ("all", "best"):
                    d = rule(r.filter(pl.col("season") == season), t)
                    if scope == "best":
                        d = sl.best_rung(d, est_of[name])
                    s = sl.summarize(d)
                    # The same legs at the best clean price any book offered:
                    # what shopping across your books would have paid.
                    sb = sl.summarize(d.with_columns(
                        pl.col("best_odds").alias("odds"),
                        pl.col("best_implied").alias("implied_prob")))
                    res["rules"][f"{name}|{t}|{season}|{scope}"] = s
                    res["rules"][f"{name}|{t}|{season}|{scope}|best_price"] = sb
                    if scope == "best" and s["n"]:
                        print(f"  {name:12s} {season:<6d} {s['n']:6,d} {s['games']:5d} "
                              f"{s['hit_rate']:6.1%} {s['price_implied']:6.1%} "
                              f"{s['per_100']:+9.2f}  [{s['ci95'][0]:+.1f}, {s['ci95'][1]:+.1f}]"
                              f"   best price {sb['price_implied']:5.1%} {sb['per_100']:+7.2f}"
                              f" [{sb['ci95'][0]:+.1f}, {sb['ci95'][1]:+.1f}]")

    # Is the book itself right about its near-certain legs? Calibration of
    # the price, 2024-25 pooled, by implied band.
    print("\n=== the price's own calibration, all rungs ===")
    for lo, hi in PRICE_BANDS:
        d = r.filter((pl.col("implied_prob") >= lo) & (pl.col("implied_prob") < hi))
        s = sl.summarize(d)
        res["rules"][f"price_band|{lo}-{hi}"] = s
        print(f"  implied {lo:.0%}-{min(hi, 1):.0%}: n={s['n']:7,d}  hit {s['hit_rate']:.1%}  "
              f"price {s['price_implied']:.1%}  per $100 {s['per_100']:+.2f} "
              f"[{s['ci95'][0]:+.1f}, {s['ci95'][1]:+.1f}]")

    (out_dir / "summary.json").write_text(json.dumps(res, indent=1))
    print(f"\n-> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
