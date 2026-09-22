#!/usr/bin/env python3
"""Reverse line movement, scored against the price it would be taken at.

    python scripts/58_rlm.py
    python scripts/58_rlm.py --seasons 2023 2024 --min-move 2

Every row carries its sample size and its interval. A pattern measured on six
games looks like a system and is a coin flip — P(1 or fewer of 6 | fair coin)
is 10.9% — and a page that prints a hit rate without an n manufactures exactly
that belief at scale.

And every row is scored against the CLOSING price of the sides it selects, not
against a flat 52.38%. A rule that picks favourites beats a coin flip by
construction; beating the coin is not beating the book.
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from src.evaluation.rlm import MIN_MOVE_PP, evaluate                # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seasons", type=int, nargs="+", default=None)
    ap.add_argument("--min-move", type=float, default=MIN_MOVE_PP,
                    help="Probability points a line must move to count.")
    a = ap.parse_args()

    rows = evaluate(a.seasons, a.min_move)
    if not rows:
        print("No graded movement yet. The archive needs an open and a close "
              "for the same line: `python scripts/55_backfill_game_lines.py`.")
        return 0

    print(f"Reverse line movement — moves of {a.min_move:g}pp or more"
          f"{'' if not a.seasons else ', seasons ' + ' '.join(map(str, a.seasons))}\n")
    print(f"  {'definition':38s} {'n':>5} {'hit':>7} {'priced':>7} "
          f"{'ROI':>7}  {'95% interval':>16}")
    for r in rows:
        if not r["n"]:
            print(f"  {r['definition']:38s} {'—':>5}  no games matched")
            continue
        band = f"[{100*r['lo']:.1f}, {100*r['hi']:.1f}]"
        print(f"  {r['definition']:38s} {r['n']:5d} {100*r['hit_rate']:6.1f}% "
              f"{100*r['implied']:6.1f}% {r['roi_pct']:+6.1f}%  {band:>16}"
              f"  {'BEATS ITS PRICE' if r['clears'] else ''}")
    print("\n  ROI is flat stake at the MEDIAN closing price. Nobody can bet a "
          "median — the best book beats it by about 1.2pp on a moneyline — so "
          "these are conservative by roughly that much.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
