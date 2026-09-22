#!/usr/bin/env python3
"""This week's games: what the market says, and where the books disagree.

    python scripts/54_matchups.py
    python scripts/54_matchups.py --week 3 --movement

Reads the game-line archive. Nothing here is modelled, and the module docstring
explains why there is no model opinion beside a total: the joint model's team
rate is a regression ON the market's total, so printing it there would be
printing the total twice and calling the second one a second opinion.

What it does show is the disagreement, which is the part with money in it.
"""
from __future__ import annotations

import argparse
import sys

import polars as pl

sys.path.insert(0, ".")

from src.evaluation.matchups import board, movement, summary   # noqa: E402
from src.utils.paths import get_path                           # noqa: E402


def _current() -> tuple[int, int]:
    from datetime import date
    s = pl.read_parquet(get_path("raw") / "schedules.parquet")
    season = int(s["season"].max())
    cur = s.filter(pl.col("season") == season).with_columns(
        pl.col("gameday").cast(pl.Utf8).str.slice(0, 10).alias("_d"))
    ahead = cur.filter(pl.col("_d") >= date.today().isoformat()).sort("_d")
    return season, int(ahead["week"][0] if ahead.height else cur["week"].max())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--snapshot", default="close", choices=("open", "close"))
    ap.add_argument("--movement", action="store_true",
                    help="Show open->close movement instead of the board.")
    a = ap.parse_args()
    season, week = (a.season, a.week) if a.season and a.week else _current()

    if not a.movement:
        print(summary(season, week, a.snapshot))
        return 0

    m = movement(season, week)
    if m.is_empty():
        print(f"No open/close pair archived for {season} week {week} yet — "
              f"movement needs both ends.")
        return 0
    moved = m.filter(pl.col("move_pp").abs() >= 0.5)
    print(f"Line movement — {season} week {week}\n"
          f"  {m.height} outcomes with both ends, "
          f"{moved.height} moved by 0.5pp or more\n")
    for r in moved.head(20).iter_rows(named=True):
        pt = "" if r["point"] is None else f" {r['point']:+g}"
        print(f"  {r['game_id']:<9} {r['market']:<8} {str(r['outcome']):<6}{pt:<7}"
              f"{r['open_odds']:>6} -> {r['close_odds']:>6}  {r['move_pp']:+.2f}pp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
