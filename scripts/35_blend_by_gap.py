#!/usr/bin/env python3
"""Should the market's weight depend on how close the top two candidates are?

The blend is one number applied everywhere: `blend_weight.json` records
market_weight 0.439 for anytime TD, fitted once on graded odds history. Today's
diagnosis says its value is not spread evenly.

Ranked on the model alone, 16.0% of games have their top two within a point and
we hit 44.9% in those against 52.7% elsewhere — and 82% of those near-ties are
TEAMMATES. Ranked on the blended number the board actually publishes, near-ties
fall to 10.7%, teammates to 59%, and the penalty disappears entirely: 52.7%
against 51.5%. The market is doing its work in a specific place — separating
two players on one team when our features cannot — which is exactly where
injury news and beat reporting live and exactly what a scalar cannot express.

So: does a weight that varies with the top-two gap beat the flat one? A learned
function of both probabilities did not (`scripts/33_market_stage2.py`,
NO_BETTER_THAN_THE_BLEND on both markets), but that asked a much broader
question — this one is narrow and pointed at a measured effect.

Walk-forward: fit on earlier seasons, score the next. Reported on log loss and
on within-game Top-1, because the two disagreed the last time the blend was
examined and Top-1 is what the board is for.

    python scripts/35_blend_by_gap.py --market anytime_td
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.hit_rates import _load_backtests  # noqa: E402
from src.utils.config import production_model  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

#: Gap bands on the model's own top-two spread, in probability points. The
#: first is the near-tie the diagnosis identified; the rest are context.
BANDS = (0.0, 0.01, 0.03, 0.08, 1.01)


def _logit(p, lo=1e-6):
    p = np.clip(np.asarray(p, float), lo, 1 - lo)
    return np.log(p / (1 - p))


def _blend(model_p, market_p, w):
    """Logit-space mixture, the form `predict._anchor_to_market` already uses."""
    z = (1 - w) * _logit(model_p) + w * _logit(market_p)
    return 1.0 / (1.0 + np.exp(-np.clip(z, -50, 50)))


def _top1(df: pl.DataFrame, col: str) -> float:
    played = (df.group_by("game_id").agg(pl.col("target").max().alias("a"))
                .filter(pl.col("a") == 1)["game_id"].to_list())
    d = df.filter(pl.col("game_id").is_in(played))
    top = (d.sort(["game_id", col], descending=[False, True])
             .group_by("game_id").head(1))
    return float(top["target"].mean())


def load(market: str) -> pl.DataFrame:
    # `or` on a DataFrame raises: polars refuses a truth value. This is the
    # same trap `_load_backtests` callers keep hitting.
    df = _load_backtests(market, production_model(market))
    if df is None:
        df = _load_backtests(market)
    if df is None:
        raise SystemExit(f"No backtest frames for {market}. Run `make evaluate`.")
    d = df.filter(pl.col("market_prob").is_not_null()
                  & pl.col("prob_calibrated").is_not_null()
                  & pl.col("target").is_not_null())
    if "season" not in d.columns:
        d = d.with_columns(pl.col("game_id").str.slice(0, 4).cast(pl.Int64)
                             .alias("season"))
    # The gap is a property of the GAME, measured on the model's own ranking —
    # it must not depend on the market, or the thing being conditioned on would
    # already contain the answer.
    ranked = d.sort(["game_id", "prob_calibrated"], descending=[False, True])
    tops = (ranked.group_by("game_id", maintain_order=True)
                  .head(2)
                  .group_by("game_id")
                  .agg([(pl.col("prob_calibrated").max()
                         - pl.col("prob_calibrated").min()).alias("gap"),
                        pl.col("team").n_unique().alias("top2_teams")]))
    return d.join(tops, on="game_id", how="inner")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", default="anytime_td",
                    choices=["anytime_td", "first_td"])
    a = ap.parse_args()
    from sklearn.metrics import log_loss

    d = load(a.market)
    seasons = sorted(d["season"].unique().to_list())
    print(f"{a.market}: {d.height:,} priced rows, {d['game_id'].n_unique():,} "
          f"games, seasons {seasons}")

    out = {"market": a.market, "rows": d.height, "seasons": seasons,
           "measured": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "bands": [], "folds": []}

    print("\nWhere the market earns its weight — best in-sample w per gap band")
    grid = np.round(np.arange(0.0, 1.01, 0.05), 2)
    for lo, hi in zip(BANDS, BANDS[1:]):
        band = d.filter((pl.col("gap") >= lo) & (pl.col("gap") < hi))
        if band["game_id"].n_unique() < 40:
            continue
        y = band["target"].to_numpy().astype(float)
        mp, kp = band["prob_calibrated"].to_numpy(), band["market_prob"].to_numpy()
        losses = [log_loss(y, np.clip(_blend(mp, kp, w), 1e-6, 1 - 1e-6))
                  for w in grid]
        best = float(grid[int(np.argmin(losses))])
        # `.to_series()` returns the FIRST column, which is game_id — comparing
        # game ids to 1 reported 0% teammates in every band.
        mates = float((band.group_by("game_id")
                           .agg(pl.col("top2_teams").first())
                           .get_column("top2_teams") == 1).mean())
        row = {"lo": lo, "hi": min(hi, 1.0), "games": int(band["game_id"].n_unique()),
               "rows": band.height, "best_w": best,
               "teammate_share": mates,
               "loss_at_best": float(min(losses)),
               "loss_at_flat": float(log_loss(
                   y, np.clip(_blend(mp, kp, 0.439), 1e-6, 1 - 1e-6)))}
        out["bands"].append(row)
        print(f"  gap {lo:.2f}-{min(hi,1.0):.2f}  games {row['games']:4d}  "
              f"teammates {mates:4.0%}  best w {best:.2f}  "
              f"log loss {row['loss_at_best']:.5f} vs {row['loss_at_flat']:.5f} flat")

    print("\nWalk-forward: fit the per-band weights on earlier seasons, apply to the next")
    for test in seasons[1:]:
        tr, te = d.filter(pl.col("season") < test), d.filter(pl.col("season") == test)
        if tr.height < 2000 or te.height < 500:
            continue
        ytr = tr["target"].to_numpy().astype(float)
        flat_w = float(grid[int(np.argmin([
            log_loss(ytr, np.clip(_blend(tr["prob_calibrated"].to_numpy(),
                                         tr["market_prob"].to_numpy(), w),
                                  1e-6, 1 - 1e-6)) for w in grid]))])
        weights = {}
        for lo, hi in zip(BANDS, BANDS[1:]):
            b = tr.filter((pl.col("gap") >= lo) & (pl.col("gap") < hi))
            if b.height < 500:
                weights[(lo, hi)] = flat_w
                continue
            yb = b["target"].to_numpy().astype(float)
            weights[(lo, hi)] = float(grid[int(np.argmin([
                log_loss(yb, np.clip(_blend(b["prob_calibrated"].to_numpy(),
                                            b["market_prob"].to_numpy(), w),
                                     1e-6, 1 - 1e-6)) for w in grid]))])

        w_col = np.full(te.height, flat_w)
        gaps = te["gap"].to_numpy()
        for (lo, hi), w in weights.items():
            w_col[(gaps >= lo) & (gaps < hi)] = w
        scored = te.with_columns([
            pl.Series("_flat", _blend(te["prob_calibrated"].to_numpy(),
                                      te["market_prob"].to_numpy(), flat_w)),
            pl.Series("_gap", _blend(te["prob_calibrated"].to_numpy(),
                                     te["market_prob"].to_numpy(), w_col)),
        ])
        yte = te["target"].to_numpy().astype(float)
        row = {"test_season": int(test), "flat_w": flat_w,
               "band_w": {f"{lo:.2f}-{hi:.2f}": w for (lo, hi), w in weights.items()},
               "logloss_flat": float(log_loss(yte, np.clip(scored["_flat"].to_numpy(), 1e-6, 1-1e-6))),
               "logloss_gap": float(log_loss(yte, np.clip(scored["_gap"].to_numpy(), 1e-6, 1-1e-6))),
               "top1_flat": _top1(scored, "_flat"), "top1_gap": _top1(scored, "_gap")}
        out["folds"].append(row)
        print(f"  {test}: flat w={flat_w:.2f}  per-band "
              f"{ {k: round(v,2) for k,v in row['band_w'].items()} }")
        print(f"       log loss {row['logloss_flat']:.5f} -> {row['logloss_gap']:.5f} "
              f"({row['logloss_gap']-row['logloss_flat']:+.5f})   "
              f"Top-1 {row['top1_flat']:.1%} -> {row['top1_gap']:.1%} "
              f"({(row['top1_gap']-row['top1_flat'])*100:+.2f}pp)")

    if out["folds"]:
        dl = float(np.mean([f["logloss_gap"] - f["logloss_flat"] for f in out["folds"]]))
        dt = float(np.mean([f["top1_gap"] - f["top1_flat"] for f in out["folds"]]))
        out["mean_logloss_delta"], out["mean_top1_delta"] = dl, dt
        out["verdict"] = ("WORTH_GATING" if (dl < -0.001 or dt > 0.005)
                          and dt > -0.005 else "NO_BETTER_THAN_FLAT")
        print(f"\n  mean out-of-sample: log loss {dl:+.5f}, Top-1 {dt*100:+.2f}pp")
        print(f"  VERDICT: {out['verdict']}")

    path = ROOT / "diagnostics" / f"blend_by_gap_{a.market}.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nWrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
