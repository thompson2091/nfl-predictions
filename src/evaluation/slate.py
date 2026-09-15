"""Which week the board should be showing, defined once.

The Streamlit app and the dashboard exporter both have to answer this, and a
re-implementation in either is the thing this project keeps finding after the
fact — the same reasoning that moved the head-to-head tiles into
`src/evaluation/market_parity.py`.

The answer is: the earliest week of the newest season that still has a game
ahead of it AND has a real candidate pool. Both halves are load-bearing, and
each was learned separately.

Taking the earliest week in the matrix is right exactly once — before a season
starts, the earliest week present is the upcoming one. The matrix carries every
scheduled week, because the DEF/ST rows are built from the schedule rather than
the roster, so that answer stays at week 1 for the rest of the season. On
2026-09-15, with week 1 played and week 2 built and priced, the exporter
published a week-1 page carrying NO PLAYERS: the odds cache had rolled to week
2, so a week-1 board matched no price at all. 1.2MB of board became 150KB of
furniture and the export exited 0.

Taking the next unplayed week alone is the opposite failure. From the final
whistle of one week until nflverse publishes the next week's roster, the
upcoming week holds 32 rows — one DEF/ST per team, from the schedule — and no
players. Pointing the board at that is the same empty page reached the other
way. Requiring a real pool keeps the finished week up until its replacement
genuinely exists.

Across a week that gives: the upcoming week as soon as the rollover builds it,
held through its own games, and held after they finish until the next week's
roster lands.
"""
from __future__ import annotations

from datetime import date

import polars as pl

from src.utils.paths import get_path

#: Below this, a week is DEF/ST alone — one row per team per game, built from
#: the schedule with no roster involved. See scripts/week_rollover.sh.
DEFST_ONLY_ROWS = 200


def weeks_with_games_ahead(season: int, today: str | None = None) -> set[int]:
    """Weeks of `season` still holding a game that has not been played."""
    try:
        sched = pl.read_parquet(get_path("raw") / "schedules.parquet")
    except Exception:
        return set()
    cur = sched.filter(pl.col("season") == season)
    if cur.height == 0 or "gameday" not in cur.columns:
        return set()
    cutoff = today or date.today().isoformat()
    ahead = (cur.with_columns(
                pl.col("gameday").cast(pl.Utf8).str.slice(0, 10).alias("_d"))
             .filter(pl.col("_d") >= cutoff))
    return {int(w) for w in ahead["week"].unique().to_list()}


def pick_week(in_season: pl.DataFrame, season: int,
              today: str | None = None) -> int:
    """The week to show, given one season's slice of the candidate matrix."""
    built = (in_season.group_by("week").agg(pl.len().alias("n"))
             .filter(pl.col("n") > DEFST_ONLY_ROWS)
             .select("week").to_series().sort().to_list())
    if not built:
        # Nothing has a pool yet — pre-season, or mid-rollover.
        return int(in_season.select(pl.col("week").min()).item())

    ahead = weeks_with_games_ahead(season, today)
    live = [w for w in built if int(w) in ahead]
    # No week ahead with a pool: the season is over, or the next week is not
    # built yet. Either way the most recently built week is what to show.
    return int(live[0] if live else built[-1])


def current_slate(target_type: str) -> tuple[int | None, int | None]:
    """(season, week) the board should be showing, on any day of the week."""
    from src.evaluation import harness

    try:
        df = harness._features(target_type)
    except FileNotFoundError:
        return None, None

    season = int(df.select(pl.col("season").max()).item())
    return season, pick_week(df.filter(pl.col("season") == season), season)
