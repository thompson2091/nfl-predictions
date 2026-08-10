"""Opponent defensive coverage tendency features from PBP data."""
import polars as pl


def build_coverage_features(pbp: pl.DataFrame) -> pl.DataFrame:
    """Build opponent man/zone coverage rate features.

    Man coverage yields ~2.5x higher pass TD rate than zone.
    Available 2018+ (92%+ coverage), null for 2015-2017.

    Returns one row per (season, week, opponent) with lagged rolling averages.
    Join on opponent (the defense) to get their coverage tendency.
    """
    # Filter to pass plays with coverage data
    passes = pbp.filter(
        (pl.col("play_type") == "pass")
        & pl.col("defteam").is_not_null()
        & pl.col("defense_man_zone_type").is_in(["MAN_COVERAGE", "ZONE_COVERAGE"])
    ).select([
        pl.col("season").cast(pl.Int64),
        pl.col("week").cast(pl.Int64),
        pl.col("defteam").alias("opponent"),
        (pl.col("defense_man_zone_type") == "MAN_COVERAGE").cast(pl.Float64).alias("is_man"),
        pl.col("pass_touchdown").cast(pl.Float64).fill_null(0.0).alias("pass_td"),
    ])

    if passes.is_empty():
        return pl.DataFrame(schema={
            "season": pl.Int64, "week": pl.Int64, "opponent": pl.Utf8,
        })

    # Aggregate per team-game
    game_stats = (
        passes
        .group_by(["season", "week", "opponent"])
        .agg([
            pl.col("is_man").mean().alias("man_rate"),
            pl.len().alias("_n_plays"),
        ])
        .sort(["opponent", "season", "week"])
    )

    # 5-game rolling average of man coverage rate (shifted to avoid leakage)
    game_stats = game_stats.with_columns(
        pl.col("man_rate")
        .shift(1)
        .rolling_mean(window_size=5, min_periods=1)
        .over(["opponent", "season"])
        .alias("opp_man_coverage_rate_avg_5g")
    )

    # Season cumulative average (shift + expanding mean)
    game_stats = game_stats.with_columns(
        pl.col("man_rate")
        .shift(1)
        .rolling_mean(window_size=100, min_periods=1)
        .over(["opponent", "season"])
        .alias("opp_man_coverage_rate_szn")
    )

    return game_stats.select([
        "season", "week", "opponent",
        "opp_man_coverage_rate_szn",
        "opp_man_coverage_rate_avg_5g",
    ])
