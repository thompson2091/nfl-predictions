import polars as pl


def build_game_features(schedules: pl.DataFrame) -> pl.DataFrame:
    """Build game-context features from schedule data."""

    feats = schedules.select([
        "game_id", "season", "week", "home_team", "away_team",
        "game_type", "weekday", "div_game",
    ])

    # Primetime flag (Thursday/Monday/Saturday night games)
    feats = feats.with_columns(
        pl.col("weekday").is_in(["Thursday", "Monday", "Saturday"])
        .cast(pl.Int8).alias("is_primetime"),
        pl.col("div_game").cast(pl.Int8).alias("is_divisional"),
    )

    # Expand to one row per team with is_home flag
    home = feats.with_columns(
        pl.col("home_team").alias("team"),
        pl.col("away_team").alias("opponent"),
        pl.lit(1).cast(pl.Int8).alias("is_home"),
    )
    away = feats.with_columns(
        pl.col("away_team").alias("team"),
        pl.col("home_team").alias("opponent"),
        pl.lit(0).cast(pl.Int8).alias("is_home"),
    )

    result = pl.concat([home, away]).select([
        "game_id", "season", "week", "team", "opponent",
        "is_home", "is_primetime", "is_divisional",
    ])

    return result
