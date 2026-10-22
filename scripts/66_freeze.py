#!/usr/bin/env python3
"""Freeze this week's player boards, every market, for every game not yet begun.

    python scripts/66_freeze.py              # the week whose games are next
    python scripts/66_freeze.py --week 5

**THE FREEZE HAD NO CALLER BEFORE KICKOFF.** `prediction_freeze` recorded a
board only as a side effect of `week_history.week_board`, and that only runs
for weeks with play-by-play on disk — so a week was first looked at after its
games had started, and nothing was ever kept. On 2026-10-09 the archive held
one game: week 4's ATL @ NO, touchdown markets only. The four over/under
markets had no freeze at all.

This is the caller. `weekly_odds.sh` runs it after every capture, which puts a
run in front of every kickoff window — Thursday evening, Sunday morning,
Sunday 12:30 and 15:35, Sunday evening and Monday evening. It is idempotent:
a game already frozen is rewritten only while it has not started, and never
after.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from src.export import prediction_freeze as PF                  # noqa: E402

TD_MARKETS = ("anytime_td", "first_td")


def current_week() -> tuple[int, int]:
    """(season, week) of the games nearest ahead — `weekly_odds.sh`'s rule."""
    import polars as pl

    from src.utils.paths import get_path

    s = pl.read_parquet(get_path("raw") / "schedules.parquet")
    s = s.with_columns(pl.col("gameday").cast(pl.Utf8).str.slice(0, 10).alias("_d"))
    season = int(s["season"].max())
    cur = s.filter(pl.col("season") == season)
    today = str(datetime.now(timezone.utc).date())
    ahead = cur.filter(pl.col("_d") >= today).sort("_d")
    row = ahead.head(1) if ahead.height else cur.sort("_d").tail(1)
    return season, int(row["week"][0])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--week", type=int, default=None)
    args = ap.parse_args()

    season, week = current_week()
    season = args.season or season
    week = args.week or week

    from src.evaluation.week_history import freeze_ou, week_board

    print(f"=== freeze {season} week {week}")
    for market in TD_MARKETS:
        try:
            # PREDICTED ON THE NEWEST CAPTURE FIRST. `week_board` reads
            # `predictions_<season>_week<week>.csv`, and the only writer of
            # that file was the Tuesday rollover — so every "kickoff" board
            # was the Wednesday one: week 6 froze 19 players listed Out as
            # priced, and Saquon's week 5 at 1.4% against a 30.8% book.
            # Started games keep their rows (`predict._keep_started`).
            from src.prediction.predict import predict
            predict(season, week, target_type=market)
            # `week_board` records as it reads; the board it returns is not
            # needed here.
            week_board(season, week, market)
        except Exception as e:                                   # noqa: BLE001
            print(f"  {market}: board unavailable ({e})", file=sys.stderr)
    for market in PF.OU_MARKETS:
        try:
            n = freeze_ou(season, week, market)
            print(f"  {market}: {n} games recorded")
        except Exception as e:                                   # noqa: BLE001
            print(f"  {market}: board unavailable ({e})", file=sys.stderr)

    # The 90% floors, on the touchdown board's population, so the forward
    # record grades the floors the page showed. Information, not bets.
    try:
        from src.evaluation import floors as FL

        blk = FL.payload(season, week, FL.eligible_names(season, week))
        n = FL.freeze(blk, season, week)
        PF.flush()
        print(f"  floors: {n} market-games recorded")
    except Exception as e:                                       # noqa: BLE001
        print(f"  floors: unavailable ({e})", file=sys.stderr)

    # What is held now, and what kicked off with nothing held. The second
    # list is the one to read: those games are showing a rebuilt board.
    for market in TD_MARKETS + PF.OU_MARKETS + PF.FLOOR_MARKETS:
        kept = PF.frozen(season, week, market)
        late = PF.missing(season, week, market)
        print(f"  {market:<16} {len(kept):>2} games held"
              + (f", {len(late)} started unfrozen: {', '.join(late)}"
                 if late else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
