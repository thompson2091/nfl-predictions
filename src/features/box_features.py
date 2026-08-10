"""Opponent defensive box count features from PBP data."""
import polars as pl


def build_box_features(pbp: pl.DataFrame) -> pl.DataFrame:
    """Build opponent stacked/light box tendency features.

    defenders_in_box reveals run/pass defense posture:
    - Light box (<=6): favors rushing TDs for RBs
    - Stacked box (>=8): suppresses run, opens passing lanes

    Available ~2016+ (73% non-null).

    Returns one row per (season, week, opponent) with lagged rolling averages.
    Join on opponent (the defense) to get their box tendency.
    """
    plays = pbp.filter(
        pl.col("defenders_in_box").is_not_null()
        & pl.col("defteam").is_not_null()
        & pl.col("play_type").is_in(["run", "pass"])
    ).select([
        pl.col("season").cast(pl.Int64),
        pl.col("week").cast(pl.Int64),
        pl.col("defteam").alias("opponent"),
        pl.col("defenders_in_box").cast(pl.Float64),
    ])

    if plays.is_empty():
        return pl.DataFrame(schema={
            "season": pl.Int64, "week": pl.Int64, "opponent": pl.Utf8,
        })

    # Classify box counts
    plays = plays.with_columns([
        (pl.col("defenders_in_box") >= 8).cast(pl.Float64).alias("is_stacked_box"),
        (pl.col("defenders_in_box") <= 6).cast(pl.Float64).alias("is_light_box"),
    ])

    # Aggregate per opponent-game
    game_stats = (
        plays
        .group_by(["season", "week", "opponent"])
        .agg([
            pl.col("defenders_in_box").mean().alias("avg_box_count"),
            pl.col("is_stacked_box").mean().alias("stacked_box_rate"),
            pl.col("is_light_box").mean().alias("light_box_rate"),
        ])
        .sort(["opponent", "season", "week"])
    )

    # Rolling averages (shifted to avoid leakage)
    output_cols = []
    for col in ["avg_box_count", "stacked_box_rate", "light_box_rate"]:
        # 5-game rolling
        game_stats = game_stats.with_columns(
            pl.col(col)
            .shift(1)
            .rolling_mean(window_size=5, min_periods=1)
            .over(["opponent", "season"])
            .alias(f"opp_{col}_avg_5g")
        )
        output_cols.append(f"opp_{col}_avg_5g")

        # Season average
        game_stats = game_stats.with_columns(
            pl.col(col)
            .shift(1)
            .rolling_mean(window_size=100, min_periods=1)
            .over(["opponent", "season"])
            .alias(f"opp_{col}_szn")
        )
        output_cols.append(f"opp_{col}_szn")

    return game_stats.select(["season", "week", "opponent"] + output_cols)
