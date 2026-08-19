#!/usr/bin/env python3
"""Should the book's price be a feature rather than a post-hoc blend weight?

Today the market is bolted on after the fact: one global weight, fitted once,
applied to every player in every game. `models/<market>/blend_weight.json`
records what that buys — on 2025 anytime TD, log loss 0.3571 blended against
0.3607 model-only and 0.3745 market-only. The book is not uniformly better;
the two are wrong in different places, and a scalar cannot express where.

`make diagnose` says where. Of 586 anytime-TD Top-1 misses, 92.0% are the right
team and the wrong player, and the book's lead over us concentrates in QBs
(43.9% against 47.4%) and in games whose top two candidates are within a point
(21.0% of games, where we hit 43.9% against 50.2% elsewhere). That is precisely
where injury news, beat reporting and sharp money live — information the
feature matrix cannot contain and the price already does.

So the question is whether a *learned* combination beats the scalar. This
trains a second stage on priced rows only:

    outcome ~ f(logit(our probability), logit(the book's price), context)

and scores it against three baselines on held-out seasons — our model alone,
the book alone, and the blend actually being served.

**Why a second stage rather than a column in the main model.** Archived prices
begin in 2023 and the feature matrix begins in 2015. A market column in the
main model is null for eight of eleven seasons, and a tree reads that null as
"this is an old season" — a season proxy, which is exactly why `season_right`
was removed. Restricting the second stage to priced rows makes the nullity
structural rather than informative.

**It is servable, unlike line movement.** The board already carries a live book
price (`has_market_price`), so nothing here depends on a quantity that only
exists after kickoff.

    python scripts/33_market_stage2.py --market anytime_td
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


def _logit(p, lo=1e-6):
    p = np.clip(np.asarray(p, dtype=float), lo, 1 - lo)
    return np.log(p / (1 - p))


def _topk_by_game(df: pl.DataFrame, col: str, k: int = 1) -> float:
    """Share of scored games whose top-k by `col` contains a scorer."""
    played = (df.group_by("game_id").agg(pl.col("target").max().alias("any"))
                .filter(pl.col("any") == 1)["game_id"])
    d = df.filter(pl.col("game_id").is_in(played))
    top = (d.sort(["game_id", col], descending=[False, True])
             .group_by("game_id").head(k)
             .group_by("game_id").agg(pl.col("target").max().alias("hit")))
    return float(top["hit"].mean())


def load(market: str) -> pl.DataFrame:
    df = _load_backtests(market, production_model(market))
    if df is None:
        df = _load_backtests(market)
    if df is None:
        raise SystemExit(
            f"No backtest frames for {market}. Run `make evaluate` first.")
    need = {"game_id", "target", "prob_calibrated", "market_prob", "final"}
    missing = need - set(df.columns)
    if missing:
        raise SystemExit(f"backtest frames are missing {sorted(missing)}")
    # Priced rows only. An unpriced row has nothing for the second stage to
    # read, and imputing the market price would invent the very input under
    # test.
    d = df.filter(pl.col("market_prob").is_not_null()
                  & pl.col("prob_calibrated").is_not_null()
                  & pl.col("target").is_not_null())
    if "season" not in d.columns:
        d = d.with_columns(pl.col("game_id").str.slice(0, 4).cast(pl.Int64)
                             .alias("season"))
    return d


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", default="anytime_td",
                    choices=["anytime_td", "first_td"])
    a = ap.parse_args()

    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import log_loss, roc_auc_score

    d = load(a.market)
    seasons = sorted(d["season"].unique().to_list())
    print(f"{a.market}: {d.height:,} priced rows, "
          f"{d['game_id'].n_unique():,} games, seasons {seasons}")

    out = {"market": a.market, "rows": d.height,
           "games": int(d["game_id"].n_unique()), "seasons": seasons,
           "measured": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "folds": []}

    for test in seasons[1:]:
        tr = d.filter(pl.col("season") < test)
        te = d.filter(pl.col("season") == test)
        if tr.height < 2000 or te.height < 500:
            continue

        def design(f):
            cols = [_logit(f["prob_calibrated"].to_numpy()),
                    _logit(f["market_prob"].to_numpy())]
            # Their disagreement, explicitly. A tree can build it, but naming it
            # is what lets the linear stage express "trust the book where it
            # departs from us" rather than only a fixed mixture.
            cols.append(cols[1] - cols[0])
            return np.column_stack(cols)

        Xtr, ytr = design(tr), tr["target"].to_numpy().astype(float)
        Xte, yte = design(te), te["target"].to_numpy().astype(float)

        fits = {
            "stage2_linear": LogisticRegression(max_iter=2000).fit(Xtr, ytr),
            "stage2_gbm": HistGradientBoostingClassifier(
                max_depth=3, max_iter=200, learning_rate=0.05,
                random_state=42).fit(Xtr, ytr),
        }
        preds = {
            "model_only": te["prob_calibrated"].to_numpy(),
            "market_only": te["market_prob"].to_numpy(),
            "served_blend": te["final"].to_numpy(),
        }
        for name, fit in fits.items():
            preds[name] = fit.predict_proba(Xte)[:, 1]

        row = {"test_season": int(test), "n": te.height,
               "games": int(te["game_id"].n_unique()), "scores": {}}
        for name, p in preds.items():
            scored = te.with_columns(pl.Series("_p", p))
            row["scores"][name] = {
                "log_loss": float(log_loss(yte, np.clip(p, 1e-6, 1 - 1e-6))),
                "auc": float(roc_auc_score(yte, p)),
                "top1": _topk_by_game(scored, "_p", 1),
                "top3": _topk_by_game(scored, "_p", 3),
            }
        out["folds"].append(row)

        print(f"\n  test {test}  ({te.height:,} rows, {row['games']} games)")
        print(f"    {'':16} {'log loss':>9} {'AUC':>8} {'Top-1':>8} {'Top-3':>8}")
        for name, s in row["scores"].items():
            print(f"    {name:16} {s['log_loss']:>9.5f} {s['auc']:>8.5f} "
                  f"{s['top1']:>7.1%} {s['top3']:>7.1%}")

    if out["folds"]:
        names = list(out["folds"][0]["scores"])
        print(f"\n  mean across {len(out['folds'])} held-out season(s)")
        print(f"    {'':16} {'log loss':>9} {'AUC':>8} {'Top-1':>8} {'Top-3':>8}")
        out["mean"] = {}
        for name in names:
            m = {k: float(np.mean([f["scores"][name][k] for f in out["folds"]]))
                 for k in ("log_loss", "auc", "top1", "top3")}
            out["mean"][name] = m
            print(f"    {name:16} {m['log_loss']:>9.5f} {m['auc']:>8.5f} "
                  f"{m['top1']:>7.1%} {m['top3']:>7.1%}")

        base = out["mean"]["served_blend"]
        best = min(("stage2_linear", "stage2_gbm"),
                   key=lambda n: out["mean"][n]["log_loss"])
        d_ll = out["mean"][best]["log_loss"] - base["log_loss"]
        d_t1 = out["mean"][best]["top1"] - base["top1"]
        out["best_stage2"] = best
        out["vs_served_blend"] = {"log_loss": d_ll, "top1": d_t1}
        # A log-loss gain that costs Top-1 is not a gain for this product. The
        # board exists to name the most likely scorer, so a second stage has to
        # clear the blend on Top-1 as well — first TD read log loss -0.00143
        # with Top-1 -1.32pp under the old rule and reported WORTH_GATING for a
        # change that makes the headline number worse.
        helps_ll, helps_t1 = d_ll < -0.001, d_t1 > 0.005
        hurts_t1 = d_t1 < -0.005
        out["verdict"] = ("WORTH_GATING" if (helps_ll or helps_t1) and not hurts_t1
                          else "NO_BETTER_THAN_THE_BLEND")
        print(f"\n  best second stage: {best}   vs the served blend: "
              f"log loss {d_ll:+.5f}, Top-1 {d_t1*100:+.2f}pp")
        print(f"  VERDICT: {out['verdict']}")
        if out["verdict"] == "NO_BETTER_THAN_THE_BLEND":
            print("  A learned combination does not beat one global weight. "
                  "The scalar is already extracting what the pair carries.")
            if hurts_t1:
                print(f"  It also costs {abs(d_t1)*100:.2f}pp of Top-1, which is "
                      f"the number this board is for.")

    path = ROOT / "diagnostics" / f"market_stage2_{a.market}.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nWrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
