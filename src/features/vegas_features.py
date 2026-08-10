"""Vegas lines, implied totals, and environment features from schedules + PBP."""
import polars as pl


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
    ]).with_columns([
        # spread_line is from home perspective (negative = home favored)
        ((pl.col("total_line") - pl.col("spread_line")) / 2).alias("implied_team_total"),
        (pl.col("spread_line") < 0).cast(pl.Float64).alias("is_favorite"),
        (pl.col("spread_line") <= -7).cast(pl.Float64).alias("is_big_favorite"),
    ])

    away = games.select([
        pl.col("game_id"), pl.col("season"), pl.col("week"),
        pl.col("away_team").alias("team"),
        (-pl.col("spread_line")).alias("spread_line"),
        pl.col("total_line"),
        pl.col("away_rest").alias("rest_days"),
        pl.col("roof"),
    ]).with_columns([
        ((pl.col("total_line") + pl.col("spread_line")) / 2).alias("implied_team_total"),
        (pl.col("spread_line") < 0).cast(pl.Float64).alias("is_favorite"),
        (pl.col("spread_line") <= -7).cast(pl.Float64).alias("is_big_favorite"),
    ])

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
