#!/usr/bin/env python3
"""Where the money is, as opposed to where the tickets are.

    python scripts/60_sharp.py
    python scripts/60_sharp.py --seasons 2026
    python scripts/60_sharp.py --week          # this week's sides, ungraded

Tickets count bets and money counts dollars. A side taking 11% of the bets and
46% of the dollars is a small number of large ones, and the ratio between the
two sides' dollars-per-ticket is what this ranks on — not the raw gap, which is
capped by the ticket share and so just ranks by unpopularity.

Graded against the CLOSING LINE rather than the result. Whether a side wins is
a question about a few hundred games a season; whether the price moved toward
it is answerable in weeks. It will refuse to report until a split capture sits
before a close on enough games — see `src/evaluation/sharp.py`.
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

import polars as pl                                                # noqa: E402

from src.evaluation import sharp                                   # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seasons", type=int, nargs="+", default=None)
    ap.add_argument("--week", action="store_true",
                    help="List this week's sides by ratio instead of grading.")
    a = ap.parse_args()

    if a.week:
        d = sharp.splits(a.seasons)
        if d.is_empty():
            print("No split capture archived yet. "
                  "`./scripts/public_money.sh` writes one.")
            return 0
        # The latest capture only. Older ones are the week's drift and belong
        # to the graded view, not to a list of what to look at now.
        latest = d["captured_at"].max()
        d = (d.filter(pl.col("captured_at") == latest)
             .sort("ratio", descending=True))
        print(f"Dollars per ticket, capture of {latest}\n")
        print(f"  {'game':10s} {'market':10s} {'side':6s} {'tickets':>8s} "
              f"{'money':>7s} {'$/ticket':>9s}")
        for r in d.head(20).iter_rows(named=True):
            print(f"  {r['game_id']:10s} {r['market']:10s} {r['side']:6s} "
                  f"{r['tickets_pct']:7.0f}% {r['money_pct']:6.0f}% "
                  f"{r['ratio']:8.2f}x")
        print("\n  A ratio near 1 means both sides are backed by the same "
              "average bet.\n  Nothing here is graded — see the no-argument "
              "form for that.")
        return 0

    print(sharp.report(a.seasons))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
