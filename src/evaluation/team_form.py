"""What each team scored and allowed, against what was expected of them.

**A ROW OF SCORES CANNOT BE READ, WHICH IS WHY THE EXPECTATION IS IN HERE.**
27, 14, 31, 20 invites an average — "this offense scores 23" — and the four
games were played against four defenses the market priced differently. 27
against a team expected to concede 23 and 27 against one expected to concede
31 are opposite weeks and the raw number says they are the same. So every row
carries the implied team total alongside the score, and the chart is drawn
against it. `player_history` makes the identical argument about a prop line
that moves week to week; this is that argument at the team level.

The expectation comes from `features.vegas_features.implied_team_total`, the
same function the feature matrix trains on, rather than from the formula
written out a second time. Two copies drift and both answers look like points.

**EVERYTHING HERE IS THE SCOREBOARD**, defensive and special-teams touchdowns
included. A pick-six is seven points the offense did not score and seven
points the total settled on, and this panel sits beside a total. The page says
so rather than quietly subtracting them, which would leave a number that
matches neither the scoreboard nor the offense.

Postseason games count as games. A team's last ten is its last ten.
"""
from __future__ import annotations

import polars as pl

from src.features.vegas_features import implied_team_total
from src.utils.paths import get_path

#: How many games a team's form is read over. Ten rather than a season: in
#: week 4 a season is three games, and it is three games every September.
#: Crossing into the previous season is a real cost — rosters and coordinators
#: turn over — so the boundary is drawn on the chart rather than hidden, and
#: by week 11 it has scrolled off on its own.
LAST = 10


def rows_for(season: int, week: int, last: int = LAST,
             schedule: pl.DataFrame | None = None) -> dict[str, list]:
    """Per team, its last `last` completed games BEFORE (season, week).

    Each row is `[season, week, opponent, home, pf, pa, exp_for, exp_against]`,
    newest first. Season and week lead so the page's existing `v3PastWhen` can
    label them without a second formatter.

    Strictly before: a game in the week being previewed has not been played,
    and one that has — an early kickoff on a slate still to come — is not
    something the preview of its own week should be reporting as form.
    """
    if schedule is None:
        schedule = pl.read_parquet(get_path("raw") / "schedules.parquet")
    need = {"season", "week", "home_team", "away_team", "home_score",
            "away_score", "spread_line", "total_line"}
    if not need.issubset(set(schedule.columns)):
        return {}
    d = schedule.filter(
        pl.col("home_score").is_not_null() & pl.col("away_score").is_not_null()
        # Played, and played before the week being previewed. `_ord` sorts
        # seasons and weeks as one line rather than two.
        & ((pl.col("season") * 100 + pl.col("week"))
           < (int(season) * 100 + int(week))))
    if d.is_empty():
        return {}

    # One row per TEAM per game, home and away, so the two sides of a game can
    # be read the same way. `spread_line` is flipped into each team's own
    # perspective first — positive means that team is favored — which is the
    # convention `implied_team_total` documents and the one the project got
    # backwards once already.
    home = d.select([
        pl.col("season"), pl.col("week"),
        pl.col("home_team").alias("team"),
        pl.col("away_team").alias("opp"),
        pl.lit(1, dtype=pl.Int8).alias("home"),
        pl.col("home_score").alias("pf"),
        pl.col("away_score").alias("pa"),
        pl.col("spread_line").alias("_sp"), pl.col("total_line").alias("_tot"),
    ])
    away = d.select([
        pl.col("season"), pl.col("week"),
        pl.col("away_team").alias("team"),
        pl.col("home_team").alias("opp"),
        pl.lit(0, dtype=pl.Int8).alias("home"),
        pl.col("away_score").alias("pf"),
        pl.col("home_score").alias("pa"),
        (-pl.col("spread_line")).alias("_sp"),
        pl.col("total_line").alias("_tot"),
    ])
    both = pl.concat([home, away]).with_columns([
        implied_team_total(pl.col("_tot"), pl.col("_sp")).alias("exp_for"),
        # What the market expected of the OPPONENT, which is the number the
        # points-allowed row is drawn against. The two implied totals sum to
        # the posted total by construction.
        implied_team_total(pl.col("_tot"), -pl.col("_sp")).alias("exp_against"),
    ]).drop(["_sp", "_tot"])

    both = (both.with_columns(
                (pl.col("season") * 100 + pl.col("week")).alias("_ord"))
                .sort("_ord", descending=True))
    out: dict[str, list] = {}
    for team, grp in both.group_by("team"):
        name = team[0] if isinstance(team, tuple) else team
        rows = []
        for r in grp.sort("_ord", descending=True).head(last).iter_rows(named=True):
            rows.append([
                int(r["season"]), int(r["week"]), r["opp"], int(r["home"]),
                int(r["pf"]), int(r["pa"]),
                None if r["exp_for"] is None else round(float(r["exp_for"]), 1),
                None if r["exp_against"] is None
                else round(float(r["exp_against"]), 1),
            ])
        out[name] = rows
    return out
