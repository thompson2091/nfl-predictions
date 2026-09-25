#!/usr/bin/env python3
"""Capture what share of bets and money is on each side, and archive it.

TWO FEEDS. Sportsbook Review gives the spread and total ticket splits;
Action Network gives the moneyline and, on every market, the share of the
MONEY as well as of the bets. Neither has what the other has, so both are
captured here and archived separately — they are different books with
different customers and averaging them would describe nobody.

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

    from src.ingest.action_public import refresh as act_refresh
    from src.ingest.action_public import week_view as act_view
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
        # TWO FEEDS, ONE HABIT. The second carries the moneyline and the
        # money share, neither of which the first has. Its failure does not
        # take the first one's capture down with it — they are separate
        # sites and either can be having a bad day alone.
        try:
            act = act_refresh(season, week, force=a.force)
            print(f"captured {act.height} ticket/money rows"
                  if act.height else
                  "ticket/money splits already captured within the hour",
                  file=sys.stderr)
        except Exception as e:                                   # noqa: BLE001
            print(f"could not capture ticket/money splits: {e}",
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

    # THE MONEYLINE AND THE MONEY, from the feed that publishes them.
    av = act_view(season, week)
    if av:
        print(f"\n{season} week {week} — moneyline, tickets vs money")
        for gid in sorted(av):
            ml = (av[gid] or {}).get("moneyline")
            if not ml or not ml["sides"]:
                continue
            top = ml["sides"][0]
            if top["tickets"] is None or top["money"] is None:
                continue
            gap = top["gap"]
            flag = "  <- money and tickets disagree" if (
                gap is not None and abs(gap) >= 8) else ""
            print(f"  {gid:<10} {top['side']:<4} "
                  f"{top['tickets']:.0f}% of bets, {top['money']:.0f}% of "
                  f"money ({gap:+.0f}pp){flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
