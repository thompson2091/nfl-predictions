#!/usr/bin/env python3
"""Snapshot moneyline, spread and total for this week's games.

    python scripts/53_game_lines.py --snapshot open
    python scripts/53_game_lines.py --snapshot close

Book-level rows, never aggregated on write. The whole measurable edge found in
the player-prop archive so far is cross-book dispersion — the best anytime-TD
price beats the consensus median by 2.31pp, worth 15.5% of return — and a
consensus written at ingest time throws that away permanently, because The Odds
API sells each snapshot once. The props archive lost 2023-2025 of book history
to exactly that mistake.

Run `open` when the week's lines go up and `close` before kickoff: reverse line
movement needs both ends, and it is the only read on where money went that this
project can derive without a scraped bet-percentage feed.
"""
from __future__ import annotations

import argparse
import sys

import polars as pl

sys.path.insert(0, ".")

from src.ingest.game_lines import (append_snapshot, consensus,  # noqa: E402
                                   fetch_game_lines)
from src.utils.config import get_config                          # noqa: E402
from src.utils.paths import get_path                             # noqa: E402


def current_week() -> tuple[int, int]:
    """The season and week whose games have not all kicked off yet.

    Derived from the schedule rather than the date, for the reason
    `weekly_odds.sh` documents: comparing against today resolves every hour of
    a Monday to the week that is ending, so a capture scheduled then files next
    week's prices under this week's number.
    """
    s = pl.read_parquet(get_path("raw") / "schedules.parquet")
    season = int(s["season"].max())
    cur = s.filter(pl.col("season") == season).with_columns(
        pl.col("gameday").cast(pl.Utf8).str.slice(0, 10).alias("_d"))
    from datetime import date
    ahead = cur.filter(pl.col("_d") >= date.today().isoformat()).sort("_d")
    if ahead.height == 0:
        raise SystemExit("No upcoming games in the schedule — season over?")
    return season, int(ahead["week"][0])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", choices=("open", "close"), required=True)
    ap.add_argument("--regions", default="us,us2")
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--week", type=int, default=None)
    a = ap.parse_args()

    season, week = (a.season, a.week) if a.season and a.week else current_week()
    print(f"Game lines: {season} week {week}, snapshot={a.snapshot}")

    rows = fetch_game_lines(regions=a.regions)
    if not rows:
        print("Nothing fetched — no rows written.")
        return 1

    df = append_snapshot(rows, season=season, week=week, snapshot=a.snapshot)
    this = df.filter((pl.col("season") == season) & (pl.col("week") == week)
                     & (pl.col("snapshot") == a.snapshot))
    c = consensus(this)
    print(f"\n  {this['game_id'].n_unique()} games, "
          f"{this['bookmaker'].n_unique()} books, {this.height:,} quotes")
    for mk in sorted(c["market"].unique().to_list()):
        sub = c.filter(pl.col("market") == mk)
        print(f"    {mk:8s} {sub.height:4d} outcomes, "
              f"median {sub['n_books'].median():.0f} books each")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
