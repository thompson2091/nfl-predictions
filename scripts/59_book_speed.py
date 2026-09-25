"""Where a price survives longest, per book.

    python scripts/59_book_speed.py [--seasons 2025 2026]

Reads `data/archive/odds_books.parquet`, which the odds capture has been
writing for three seasons and nothing else reads. Prints one row per book:
how far it prices from the room, how often it holds the longest price, and
how often it moves when the room does.

This is a measurement, not a recommendation. What it supports is an
operational choice — which account to place a rated price at — rather than
any claim about which side to take.
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seasons", type=int, nargs="*", default=None)
    a = ap.parse_args()

    from src.evaluation import book_speed as B

    r = B.report(a.seasons)
    print(B.format_report(r))
    if not r.is_empty() and "mean_dev" in r.columns:
        best = r.row(0, named=True)
        print(f"\n  Longest prices, on this record: {best['bookmaker']} "
              f"({best['mean_dev']:+.4f} against the room, best price "
              f"{best['best_share']:.1%} of the time over "
              f"{best['quotes']:,} quotes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
