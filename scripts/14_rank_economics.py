#!/usr/bin/env python3
"""Does being right pay? Profitability by model rank and by price.

    python scripts/14_rank_economics.py --target first_td

Top-N accuracy answers "is the scorer in our shortlist". This answers "would
backing that shortlist have made money at the prices the book actually offered",
which is a different question and the only one worth betting on. Needs backtest
frames (scripts/10_backtest.py) for the seasons you hold prices for.
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from src.evaluation.rank_economics import measure, save
from src.utils.config import get_config
from src.utils.paths import get_path


def _fmt(r: dict) -> str:
    if r.get("roi") is None:
        return f"{r['n']:>5} bets   —"
    flag = "  THIN" if r.get("thin") else ""
    conc = ""
    if r.get("concentration") and r["concentration"] > 0.5:
        conc = f"   top-10 winners = {r['concentration']:.0%} of profit"
    return (f"{r['n']:>5} {r['hit_pct']:>6.1f}% {r['breakeven_pct']:>8.1f}% "
            f"{r['median_odds']:>+8.0f} {r['roi']:>+7.1f}% "
            f"[{r['lo']:>+6.1f}, {r['hi']:>+6.1f}]{flag}{conc}")


def main(target_type: str, headline_n: int, model: str | None) -> int:
    stats = measure(target_type, headline_n=headline_n, model=model)
    if stats is None:
        print(f"No backtest frames for {target_type} — run scripts/10_backtest.py "
              f"for each season first.")
        return 1

    hdr = f"{'bets':>5} {'hit':>6} {'breakeven':>9} {'odds':>8} {'ROI':>8} {'95% interval':>17}"
    print(f"\n{'=' * 78}")
    print(f"RANK ECONOMICS — {target_type} — seasons {stats['seasons']}, "
          f"{stats['games']} games")
    print(f"{'=' * 78}")

    print(f"\nBY MODEL RANK\n rank {hdr}")
    for r in stats["by_rank"]:
        print(f" {r['rank']:>4} {_fmt(r)}")

    print(f"\nBY PRICE\n {'band':>12} {hdr}")
    for r in stats["by_odds_bucket"]:
        print(f" {r['bucket']:>12} {_fmt(r)}")

    print(f"\nBACK EVERY PLAYER RANKED N OR BETTER\n  N   {hdr}")
    for r in stats["top_n"]:
        star = " <- headline" if r["top_n"] == stats["headline_n"] else ""
        print(f" {r['top_n']:>4} {_fmt(r)}{star}")

    print(f"\nHEADLINE STRATEGY (top {stats['headline_n']}) BY SEASON\n"
          f" season {hdr}")
    for r in stats["by_season"]:
        print(f" {r['season']:>6} {_fmt(r)}")

    if stats.get("blend_comparison"):
        print(f"\nWHAT TO RANK BY  (a bet is a disagreement with the price;\n"
              f"                  blending toward the price gives it up)")
        print(f" {'ranked by':<24} {'N':>2} {'bets':>5} {'ROI':>8} {'95% interval':>17}")
        for r in stats["blend_comparison"]:
            print(f" {r['ranked_by']:<24} {r['top_n']:>2} {r['n']:>5} "
                  f"{r['roi']:>+7.1f}% [{r['lo']:>+6.1f}, {r['hi']:>+6.1f}]")

    h = stats["headline"]
    print(f"\n{'-' * 78}")
    if h and h["verdict"] == "positive":
        print(f"VERDICT: backing the top {stats['headline_n']} returned "
              f"{h['roi']:+.1f}% [{h['lo']:+.1f}, {h['hi']:+.1f}] — the interval "
              f"excludes zero.")
        if h.get("concentration") and h["concentration"] > 0.5:
            print("         But the ten biggest winners carry "
                  f"{h['concentration']:.0%} of the profit. Treat this as a "
                  "description of those results, not a rate.")
    else:
        print(f"VERDICT: NO EDGE DEMONSTRATED. Backing the top "
              f"{stats['headline_n']} returned {h['roi']:+.1f}% "
              f"[{h['lo']:+.1f}, {h['hi']:+.1f}], which includes zero.")
        print("         High Top-N accuracy has not translated into money here. "
              "No staking scheme fixes that — sizing changes how fast you find "
              "out, not the sign.")

    # Tagged per model so switching models in the app switches the evidence
    # with it. The untagged file stays the production model's, which is what
    # the board falls back to.
    out_dir = get_path("output", target_type)
    out = (out_dir / f"rank_economics_{model}.json") if model else (
        out_dir / "rank_economics.json")
    save(stats, out)
    print(f"\nSaved: {out}")
    return 0


if __name__ == "__main__":
    cfg = get_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=cfg["target"]["type"])
    ap.add_argument("--model", default=None,
                    help="Score a specific model. Omit for the production one.")
    ap.add_argument("--headline-n", type=int, default=3,
                    help="Strategy the verdict is based on. Declared up front so "
                         "it cannot be picked after seeing which N won.")
    a = ap.parse_args()
    sys.exit(main(a.target, a.headline_n, a.model))
