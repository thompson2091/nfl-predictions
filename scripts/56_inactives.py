#!/usr/bin/env python3
"""Re-check availability close to kickoff, and flag picks that are now dead.

    python scripts/56_inactives.py                 # this week, report only
    python scripts/56_inactives.py --refresh       # pull rosters first

Inactives are published about 90 minutes before kickoff. The board is built
long before that: the Sunday closing capture fires at 09:00 for a 13:00 window,
and `predict._filter_unavailable` can only drop what the roster feed already
says. On a week that has been played the feed carries ~200 INA rows; on the
week being played it carries **none**, because the designation does not exist
yet. 2026 weeks 1 and 2 hold 200 and 202 inactives against 1,536 active, and
week 3 holds 0 against 1,695 — the ~160 difference is players who will be
ruled out after the board was built.

So a shortlist can name a player who cannot play, and nothing upstream is wrong
when it does. This is the check that closes that window. It is deliberately
NOT a model input and NOT a filter applied retroactively: it reports, it exits
non-zero when it finds something, and a human decides.

**Whether nflverse publishes in time is an open question this script answers by
running.** The weekly roster is published during the week it is played, and
whether `INA` lands at T-90 or only after the game is not documented anywhere
this project can check. The output records what it saw and when, so one Sunday
settles it. If the feed turns out to be too slow, the answer is a different
source, not a different script.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

import polars as pl

sys.path.insert(0, ".")

from src.prediction.predict import _AVAILABLE_STATUSES          # noqa: E402
from src.utils.paths import get_path                            # noqa: E402


def current_week() -> tuple[int, int]:
    from datetime import date
    s = pl.read_parquet(get_path("raw") / "schedules.parquet")
    season = int(s["season"].max())
    cur = s.filter(pl.col("season") == season).with_columns(
        pl.col("gameday").cast(pl.Utf8).str.slice(0, 10).alias("_d"))
    ahead = cur.filter(pl.col("_d") >= date.today().isoformat()).sort("_d")
    return season, int(ahead["week"][0] if ahead.height else cur["week"].max())


def picks(season: int, week: int) -> pl.DataFrame:
    """This week's tracked picks — the bets that would actually be placed."""
    from src.evaluation.tracked_rules import load

    t = load()
    if t.is_empty():
        return t
    return t.with_columns([pl.col("season").cast(pl.Int64),
                           pl.col("week").cast(pl.Int64)]).filter(
        (pl.col("season") == season) & (pl.col("week") == week))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--refresh", action="store_true",
                    help="Pull rosters from nflverse before checking.")
    a = ap.parse_args()
    season, week = (a.season, a.week) if a.season and a.week else current_week()

    if a.refresh:
        # THE ROSTER A BOARD WAS BUILT FROM, kept before it is replaced.
        # `load_rosters` rewrites the current season whole, and on a Sunday
        # this runs four times; without a copy, which statuses a pre-kickoff
        # board saw cannot be recovered afterwards.
        import shutil

        src = get_path("raw") / "rosters.parquet"
        if src.exists():
            snap = (get_path("raw").parent / "archive" / "snapshots"
                    / datetime.now().strftime("%Y%m%d"))
            snap.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, snap / f"rosters_{datetime.now():%H%M%S}.parquet")
            # 5 MB a copy, four a Sunday: keep a season's worth of days.
            days = sorted(d for d in snap.parent.iterdir() if d.is_dir())
            for old in days[:-120]:
                shutil.rmtree(old, ignore_errors=True)
        from src.ingest.loader import load_rosters
        print("Refreshing rosters from nflverse...")
        load_rosters([season])

    path = get_path("raw") / "rosters.parquet"
    r = pl.read_parquet(path).filter(
        (pl.col("season") == season) & (pl.col("week") == week))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if r.is_empty():
        print(f"{now}  no roster rows for {season} week {week} — cannot check")
        return 0

    counts = (r.group_by("status").agg(pl.len().alias("n"))
              .sort("n", descending=True))
    ina = int(r.filter(pl.col("status") == "INA").height)
    print(f"{now}  {season} week {week}: {r.height:,} roster rows, "
          f"{ina} inactive")
    print("  " + ", ".join(f"{x['status']}={x['n']}" for x in counts.iter_rows(named=True)))
    if ina == 0:
        print("  No inactives published yet. Either the feed has not caught up "
              "or they have not been declared — re-run closer to kickoff.")

    p = picks(season, week)
    if p.is_empty():
        print("  No tracked picks this week — nothing to check.")
        return 0

    out = (r.select([pl.col("player_name").alias("player"), "status"])
             .unique(subset=["player"], keep="last"))
    j = p.join(out, on="player", how="left")
    dead = j.filter(pl.col("status").is_not_null()
                    & ~pl.col("status").is_in(list(_AVAILABLE_STATUSES)))
    print(f"  {p.height} tracked picks checked")
    if dead.is_empty():
        print("  None of them are ruled out.")
        return 0

    print(f"\n  !! {dead.height} tracked pick(s) are no longer available:")
    for row in dead.iter_rows(named=True):
        print(f"       {row['player']:<24} {row.get('team') or '':<4} "
              f"{row['status']}   {row['rule']}  at {row['odds']}")
    print("\n  These are bets that cannot win. Nothing upstream is wrong — the "
          "designation did not exist when the board was built.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
