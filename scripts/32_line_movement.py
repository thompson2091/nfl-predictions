#!/usr/bin/env python3
"""Is open-to-close line movement worth feeding the model? Measured: no.

The idea was the best one left: 47,750 credits bought open *and* close prices
for three seasons, they are used only to *measure* closing-line value, and
where a line moves is where money went — information nflverse cannot contain.

It does not survive contact with the closing price. Three tests, and they
agree:

  1. Banded by movement, the scoring rate climbs from 14.9% (drifted out more
     than 2pp) to 22.7% (steamed in more than 2pp). That looks like signal.
     It is not: the CLOSE climbs with it, 19.4% -> 27.7%, and the residual is a
     flat -0.04 to -0.05 in every band. That constant is the overround.

  2. Walk-forward logistic regression of the outcome on the closing price, then
     on close + movement. Log loss moves by 0.00000 and AUC by -0.00010. The
     movement coefficient is ~0.01 against a logit-scale close coefficient near
     1. Conditioned on the close, movement is empty.

  3. Within-game ranking, which is what Top-1 actually reads and which a global
     AUC can hide. Re-ranking each game by close + w * movement gives Top-1
     52.8 / 53.0 / 52.3 / 52.9 / 51.5% for w = 0 / 0.25 / 0.5 / 1 / 2. No
     ordering, all inside the standard error.

This is what an efficient closing line looks like. The movement is how the
market reached its number; the number is already the answer.

**And it could not have been used anyway.** `open` is captured 72h before
kickoff and `close` five minutes before. The board is built mid-week, so at the
moment a bet is placed the closing price does not exist. A feature trained on
open->close and served on open->whatever-exists-now is the same train/serve
skew that took out temp, wind, is_cold and is_windy.

    python scripts/32_line_movement.py --market anytime_td
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

from src.evaluation.clv import line_movement  # noqa: E402
from src.ingest.odds_history import _norm_expr  # noqa: E402
from src.utils.paths import get_path  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BANDS = [(-9, -0.02, "drifted out >2pp"), (-0.02, -0.005, "drifted out 0.5-2pp"),
         (-0.005, 0.005, "flat +/-0.5pp"), (0.005, 0.02, "steamed in 0.5-2pp"),
         (0.02, 9, "steamed in >2pp")]
WEIGHTS = (0.0, 0.25, 0.5, 1.0, 2.0)


def _logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def paired(market: str) -> pl.DataFrame:
    """Open/close pairs joined to whether the player actually scored."""
    moves = line_movement(market)
    if moves is None or moves.is_empty():
        raise SystemExit(f"No open/close pairs archived for {market}.")
    feat = pl.read_parquet(
        get_path("processed", market) / "features.parquet",
        columns=["season", "game_id", "player_name", "target"])
    feat = (feat.filter(pl.col("target").is_not_null())
                .with_columns(_norm_expr("player_name").alias("player_name_norm")))
    d = moves.join(feat, on=["game_id", "player_name_norm"], how="inner")
    return d.filter(pl.col("open_prob").is_not_null()
                    & pl.col("close_prob").is_not_null())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", default="anytime_td",
                    choices=["anytime_td", "first_td"])
    a = ap.parse_args()

    d = paired(a.market)
    y = d["target"].to_numpy().astype(float)
    close, openp = d["close_prob"].to_numpy(), d["open_prob"].to_numpy()
    move = close - openp
    out = {"market": a.market, "rows": d.height,
           "seasons": [int(d["season"].min()), int(d["season"].max())],
           "base_rate": float(y.mean()),
           "measured": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    print(f"{a.market}: {d.height:,} player-games, "
          f"{out['seasons'][0]}-{out['seasons'][1]}, base rate {y.mean():.4f}")

    print("\n1. Banded by movement — does the residual vary, or only the level?")
    out["bands"] = []
    for lo, hi, label in BANDS:
        m = (move > lo) & (move <= hi)
        if m.sum() < 50:
            continue
        row = {"band": label, "n": int(m.sum()), "scored": float(y[m].mean()),
               "close": float(close[m].mean()),
               "residual": float(y[m].mean() - close[m].mean())}
        out["bands"].append(row)
        print(f"   {label:22s} n={row['n']:6d}  scored {row['scored']:.4f}  "
              f"close {row['close']:.4f}  residual {row['residual']:+.4f}")
    resid = [b["residual"] for b in out["bands"]]
    print(f"   residual spread across bands: {max(resid) - min(resid):.4f} "
          f"(a flat residual means the close already carries it)")

    print("\n2. Walk-forward: outcome ~ close, versus outcome ~ close + move")
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import log_loss, roc_auc_score

    seasons = d["season"].to_numpy()
    out["folds"] = []
    for test in sorted(set(seasons.tolist()))[1:]:
        tr, te = seasons < test, seasons == test
        if tr.sum() < 2000 or te.sum() < 500:
            continue
        base = LogisticRegression(max_iter=1000).fit(_logit(close[tr, None]), y[tr])
        both = LogisticRegression(max_iter=1000).fit(
            np.column_stack([_logit(close[tr]), move[tr]]), y[tr])
        pa = base.predict_proba(_logit(close[te, None]))[:, 1]
        pb = both.predict_proba(
            np.column_stack([_logit(close[te]), move[te]]))[:, 1]
        row = {"test_season": int(test), "n": int(te.sum()),
               "logloss_close": float(log_loss(y[te], pa)),
               "logloss_both": float(log_loss(y[te], pb)),
               "auc_close": float(roc_auc_score(y[te], pa)),
               "auc_both": float(roc_auc_score(y[te], pb)),
               "move_coef": float(both.coef_[0][1]),
               "close_coef": float(both.coef_[0][0])}
        out["folds"].append(row)
        print(f"   {row['test_season']}  n={row['n']:6d}  log loss "
              f"{row['logloss_close']:.5f} -> {row['logloss_both']:.5f} "
              f"({row['logloss_both'] - row['logloss_close']:+.5f})   AUC "
              f"{row['auc_close']:.5f} -> {row['auc_both']:.5f}   "
              f"move coef {row['move_coef']:+.3f} vs close coef "
              f"{row['close_coef']:+.3f}")

    print("\n3. Within-game ranking — what Top-1 actually reads")
    out["ranking"] = []
    g = d.with_columns([pl.Series("close_p", close), pl.Series("move_v", move)])
    playable = (g.group_by("game_id").agg(pl.col("target").max().alias("any"))
                 .filter(pl.col("any") == 1)["game_id"])
    for w in WEIGHTS:
        top = (g.with_columns((pl.col("close_p") + w * pl.col("move_v")).alias("s"))
                .sort(["game_id", "s"], descending=[False, True])
                .group_by("game_id").head(1)
                .filter(pl.col("game_id").is_in(playable)))
        row = {"weight": w, "top1": float(top["target"].mean()),
               "games": int(len(playable))}
        out["ranking"].append(row)
        print(f"   weight {w:>4.2f}:  Top-1 {row['top1']:.4f}  "
              f"over {row['games']} games")
    se = (0.5 * 0.5 / len(playable)) ** 0.5
    spread = max(r["top1"] for r in out["ranking"]) - min(
        r["top1"] for r in out["ranking"])
    out["ranking_spread"] = spread
    out["ranking_se"] = se
    print(f"   spread {spread:.4f} against a standard error of {se:.4f}")

    mean_dl = float(np.mean([f["logloss_both"] - f["logloss_close"]
                             for f in out["folds"]])) if out["folds"] else None
    out["verdict"] = ("REJECTED" if mean_dl is None or mean_dl > -0.001
                      else "WORTH_BUILDING")
    out["mean_logloss_delta"] = mean_dl
    print(f"\nVERDICT: {out['verdict']} — mean out-of-sample log loss "
          f"{mean_dl:+.5f} (negative would mean movement helps)")
    if out["verdict"] == "REJECTED":
        print("The closing line already contains what the movement carries. "
              "And the close does not exist when the board is built, so even a "
              "real effect here could not have been served.")

    path = ROOT / "diagnostics" / f"line_movement_{a.market}.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nWrote {path}  <- commit this")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
