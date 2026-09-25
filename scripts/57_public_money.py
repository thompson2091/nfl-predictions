#!/usr/bin/env python3
"""Capture what share of bets is on each side, and archive it.

    python scripts/57_public_money.py              # this week
    python scripts/57_public_money.py --week 4
    python scripts/57_public_money.py --show       # read the archive, fetch nothing

Run it SEVERAL TIMES across the week. One capture gives you the split; the
drift from Tuesday to Sunday is the part that is hard to get anywhere else,
and it only exists if something was there to record it. A sensible cadence is
the same one `weekly_odds.sh` uses — an opening read early in the week and a
closing one before the first kickoff.

Fetching twice inside an hour is a no-op rather than a duplicate row, so
running this by hand whenever you think of it is safe.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

import polars as pl

sys.path.insert(0, ".")


def current_week() -> tuple[int, int]:
    from src.utils.paths import get_path

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
    ap.add_argument("--force", action="store_true",
                    help="capture even if one was taken in the last hour")
    ap.add_argument("--show", action="store_true",
                    help="print the archive for the week and fetch nothing")
    a = ap.parse_args()
    season, week = (a.season, a.week) if a.season and a.week else current_week()

    from src.ingest.public_money import refresh, week_view

    if not a.show:
        try:
            got = refresh(season, week, force=a.force)
        except Exception as e:                                   # noqa: BLE001
            # Named, not swallowed. A feed that has changed shape is the one
            # failure that must not read as a quiet week.
            print(f"could not capture: {e}", file=sys.stderr)
            return 1
        if got.is_empty():
            print("already captured within the hour; nothing written "
                  "(--force to override)", file=sys.stderr)
        else:
            print(f"captured {got.height} rows for {season} week {week}",
                  file=sys.stderr)

    v = week_view(season, week)
    if not v:
        print("nothing archived for this week yet", file=sys.stderr)
        return 0
    print(f"\n{season} week {week} — share of bets, "
          f"{list(v.values())[0]['spreads']['captures']} capture(s)")
    for gid in sorted(v):
        blk = v[gid]
        bits = []
        for mk in ("spreads", "totals"):
            m = blk.get(mk)
            if not m:
                continue
            top = m["sides"][0]
            drift = (f" ({top['drift']:+.1f} since first look)"
                     if top.get("drift") else "")
            bits.append(f"{mk[:6]}: {top['side']} {top['pct']:.0f}%{drift}")
        print(f"  {gid:<10} " + "   ".join(bits))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
