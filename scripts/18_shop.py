#!/usr/bin/env python3
"""What the best available price is worth this week.

    python scripts/18_shop.py --season 2026 --week 1

Every profitability figure in this project is measured at a consensus median
across books, and nobody can bet a median. This measures the gap to the price
you could actually take — riskless edge that needs no model to be right, only
an account at more than one book.
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from src.evaluation.line_shopping import best_vs_consensus, report
from src.utils.config import get_config


def main(season: int, week: int, target: str, top: int) -> int:
    print(report(season, week, target))
    d = best_vs_consensus(season, week, target)
    if d is None:
        return 1
    shoppable = d.filter(d["n_books"] > 1).head(top)
    if shoppable.height:
        print(f"\n  Biggest gaps this week:")
        for r in shoppable.iter_rows(named=True):
            print(f"    {r['player'][:24]:24s} {r['consensus_odds']:>+6d} -> "
                  f"{r['best_odds']:>+6d} at {r['best_book']:<16s} "
                  f"{r['gap_pp']:+.2f}pp")
    return 0


if __name__ == "__main__":
    cfg = get_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=cfg["seasons"]["predict_season"])
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--target", default=cfg["target"]["type"])
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args()
    sys.exit(main(a.season, a.week, a.target, a.top))
