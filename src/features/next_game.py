"""A placeholder play for each team's next game, so team features reach it.

Every team and opponent builder works the same way: aggregate the play-by-play
to one row per team-game, `shift(1)` so a game never sees itself, then roll.
A game's row therefore holds everything BEFORE it — and a game not yet played
has no plays, so it has no row. `_carry_within_season` then projects the last
real row forward, and that row was already shifted: the week-7 board read the
week-6 row, which holds weeks 1-5. Measured 2026-10-19, the week-7 value
equalled the week-6 value for 100% of teams on seven team features; every live
board this season was scored on team form one game stale. The player side has
no such gap because `carry_forward._project` projects UNshifted values.

So each builder is handed one placeholder play per team for its next game,
and its own shift produces that game's row from every game before it — the
same arithmetic a real row gets, through the same code.

**The placeholder's own values are never read.** A game's stats reach only
the rows after it, and nothing comes after the next game until it is played,
when real plays replace the placeholder. Its fields are set only so the
builders' row filters (a play type, a personnel string, a box count) keep it;
what they say is irrelevant. `scripts/74_next_game_check.py` proves both
halves on a past season: the next-game rows equal the rows the real plays
give, and no played row moves.
"""
from __future__ import annotations

import polars as pl

#: The opponent every placeholder plays. Not a team code, so it matches no
#: candidate and no schedule row.
NOBODY = "~next"

#: Fields a builder filters on before it aggregates, given a value that passes.
_PASS = {
    "season_type": "REG",
    "play_type": "pass",
    "pass_attempt": 0.0,
    "rush_attempt": 0.0,
    "touchdown": 0.0,
    "fixed_drive": 1.0,
    "drive_time_of_possession": "0:00",
    "offense_personnel": "1 RB, 1 TE, 3 WR",
    "defenders_in_box": 6.0,
    "defense_man_zone_type": "ZONE_COVERAGE",
}


def stubs(pbp: pl.DataFrame, schedules: pl.DataFrame, season: int) -> pl.DataFrame:
    """One placeholder play per side of each team's next unplayed game."""
    played = (pbp.filter((pl.col("season") == season)
                         & pl.col("posteam").is_not_null())
              .group_by("posteam").agg(pl.col("week").max().alias("last"))
              .rename({"posteam": "team"}))
    games = schedules.filter(pl.col("season") == season).select(
        "game_id", "season", "week", "home_team", "away_team")
    sides = pl.concat([
        games.with_columns(pl.col("home_team").alias("team"),
                           pl.col("away_team").alias("opp")),
        games.with_columns(pl.col("away_team").alias("team"),
                           pl.col("home_team").alias("opp")),
    ])
    nxt = (sides.join(played, on="team", how="left")
           .filter(pl.col("week") > pl.col("last").fill_null(0))
           .sort("week").group_by("team", maintain_order=True).first())
    if nxt.height == 0:
        return pbp.clear()
    # TWO PLAYS PER TEAM, EACH AGAINST A TEAM THAT DOES NOT EXIST. One play
    # against the real opponent would also give the OPPONENT a row at this
    # game — and when this is not the opponent's next game (it has a bye
    # between, or plays first) that row sits after the opponent's own
    # placeholder and reads it: CHI 2025 week 8 came out 2.0 touchdowns
    # allowed where the real plays say 2.67. The dummy's rows join nothing.
    base = nxt.select(
        "game_id", "home_team", "away_team",
        pl.col("season").cast(pbp.schema["season"]),
        pl.col("week").cast(pbp.schema["week"]), "team")
    out = pl.concat([
        base.select(pl.exclude("team"), pl.col("team").alias("posteam"),
                    pl.lit(NOBODY).alias("defteam")),
        base.select(pl.exclude("team"), pl.lit(NOBODY).alias("posteam"),
                    pl.col("team").alias("defteam")),
    ]).with_columns([pl.lit(v).cast(pbp.schema[k]).alias(k)
                    for k, v in _PASS.items() if k in pbp.schema])
    return out.select([c for c in out.columns if c in pbp.schema])


def with_stubs(pbp: pl.DataFrame, schedules: pl.DataFrame,
               season: int | None) -> pl.DataFrame:
    """`pbp` with the placeholders appended, for the team builders only."""
    if season is None:
        return pbp
    s = stubs(pbp, schedules, season)
    if s.height == 0:
        return pbp
    return pl.concat([pbp, s], how="diagonal_relaxed")
