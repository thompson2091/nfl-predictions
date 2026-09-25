"""Vegas lines, implied totals, and environment features from schedules + PBP."""
import polars as pl


def _line_features() -> list[pl.Expr]:
    """Line-derived features, once, for a `spread_line` already in team perspective.

    nflverse `spread_line` is **positive when the home team is favored**
    (correlation with home margin of victory is +0.44). The previous code
    asserted the opposite in a comment and built three features on it, all
    wrong:

    - `is_favorite` and `is_big_favorite` were inverted. Teams flagged as
      favorites won 34.9% of their games; teams flagged as underdogs won
      66.7%.
    - `implied_team_total` came out identical for both sides of all 3,300
      games. The home rows subtracted the spread when they should have added
      it, and the away rows negated the spread into team perspective and then
      negated it again inside the formula, so the two canceled and both teams
      received the away team's number.

    Every caller flips `spread_line` into that team's own perspective first, so
    a positive value here always means "this team is favored" and one set of
    expressions serves both.
    """
    return [
        ((pl.col("total_line") + pl.col("spread_line")) / 2).alias("implied_team_total"),
        (pl.col("spread_line") > 0).cast(pl.Float64).alias("is_favorite"),
        (pl.col("spread_line") >= 7).cast(pl.Float64).alias("is_big_favorite"),
    ]


def build_vegas_features(schedules: pl.DataFrame, pbp: pl.DataFrame) -> pl.DataFrame:
    """Per-team-per-game Vegas and environment features. No rolling needed."""

    # --- Vegas from schedules ---
    games = schedules.select([
        "game_id", "season", "week", "home_team", "away_team",
        "spread_line", "total_line", "roof", "home_rest", "away_rest",
    ])

    # Home rows
    home = games.select([
        pl.col("game_id"), pl.col("season"), pl.col("week"),
        pl.col("home_team").alias("team"),
        pl.col("spread_line"),
        pl.col("total_line"),
        pl.col("home_rest").alias("rest_days"),
        pl.col("roof"),
    ]).with_columns(_line_features())

    away = games.select([
        pl.col("game_id"), pl.col("season"), pl.col("week"),
        pl.col("away_team").alias("team"),
        (-pl.col("spread_line")).alias("spread_line"),
        pl.col("total_line"),
        pl.col("away_rest").alias("rest_days"),
        pl.col("roof"),
    ]).with_columns(_line_features())

    vegas = pl.concat([home, away], how="diagonal_relaxed")

    # Dome indicator
    vegas = vegas.with_columns(
        pl.col("roof").is_in(["dome", "closed"]).cast(pl.Float64).alias("is_dome"),
    ).drop("roof")

    # --- Weather from PBP (first play per game) ---
    weather = (
        pbp.filter(pl.col("play_id").is_not_null())
        .sort(["game_id", "play_id"])
        .group_by("game_id")
        .first()
        .select([
            "game_id",
            pl.col("temp").cast(pl.Float64),
            pl.col("wind").cast(pl.Float64),
        ])
    )

    vegas = vegas.join(weather, on="game_id", how="left")

    # Weather indicators
    vegas = vegas.with_columns([
        (pl.col("temp") < 40).fill_null(False).cast(pl.Float64).alias("is_cold"),
        (pl.col("wind") >= 15).fill_null(False).cast(pl.Float64).alias("is_windy"),
    ])

    result = vegas.select([
        "game_id", "season", "week", "team",
        "spread_line", "total_line", "implied_team_total",
        "is_favorite", "is_big_favorite", "rest_days",
        "is_dome", "temp", "wind", "is_cold", "is_windy",
    ])

    return result
