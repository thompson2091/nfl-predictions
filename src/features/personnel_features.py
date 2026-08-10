"""Team offensive personnel grouping features from PBP data."""
import polars as pl


def build_personnel_features(pbp: pl.DataFrame) -> pl.DataFrame:
    """Build team personnel grouping rate features.

    Personnel groupings (e.g. 11, 12, 21, 22) reveal run/pass tendency
    and goal-line package usage. Heavy sets (21/22/13) correlate with
    rushing TDs. Available ~2016+ (74% non-null).

    Returns one row per (season, week, team) with lagged rolling averages.
    """
    if "offense_personnel" not in pbp.columns:
        # Participation data is unavailable for these seasons. Return empty
        # rather than raising — the assembler skips empty feature frames,
        # and a missing optional feed should degrade, not halt the run.
        print("  build_personnel_features: no 'offense_personnel' column, skipping")
        return pl.DataFrame()
    plays = pbp.filter(
        pl.col("offense_personnel").is_not_null()
        & pl.col("posteam").is_not_null()
        & pl.col("play_type").is_in(["run", "pass"])
    ).select([
        pl.col("season").cast(pl.Int64),
        pl.col("week").cast(pl.Int64),
        pl.col("posteam").alias("team"),
        pl.col("offense_personnel"),
    ])

    if plays.is_empty():
        return pl.DataFrame(schema={
            "season": pl.Int64, "week": pl.Int64, "team": pl.Utf8,
        })

    # Parse personnel string: "1 RB, 1 TE, 3 WR" -> extract RB and TE counts
    plays = plays.with_columns([
        pl.col("offense_personnel")
        .str.extract(r"(\d+)\s*RB", 1)
        .cast(pl.Int64)
        .fill_null(0)
        .alias("_n_rb"),
        pl.col("offense_personnel")
        .str.extract(r"(\d+)\s*TE", 1)
        .cast(pl.Int64)
        .fill_null(0)
        .alias("_n_te"),
    ])

    # Classify personnel groupings
    plays = plays.with_columns([
        # 11 personnel (1 RB, 1 TE) — most common passing set
        ((pl.col("_n_rb") == 1) & (pl.col("_n_te") == 1)).cast(pl.Float64).alias("is_11"),
        # 12 personnel (1 RB, 2 TE) — balanced run/pass
        ((pl.col("_n_rb") == 1) & (pl.col("_n_te") == 2)).cast(pl.Float64).alias("is_12"),
        # 21 personnel (2 RB, 1 TE) — run-heavy
        ((pl.col("_n_rb") == 2) & (pl.col("_n_te") == 1)).cast(pl.Float64).alias("is_21"),
        # Heavy sets: 22, 13, or 3+ RB (goal line / short yardage)
        (
            ((pl.col("_n_rb") >= 2) & (pl.col("_n_te") >= 2))
            | ((pl.col("_n_rb") == 1) & (pl.col("_n_te") >= 3))
            | (pl.col("_n_rb") >= 3)
        ).cast(pl.Float64).alias("is_heavy"),
    ])

    # Aggregate per team-game
    game_stats = (
        plays
        .group_by(["season", "week", "team"])
        .agg([
            pl.col("is_11").mean().alias("personnel_11_rate"),
            pl.col("is_12").mean().alias("personnel_12_rate"),
            pl.col("is_21").mean().alias("personnel_21_rate"),
            pl.col("is_heavy").mean().alias("personnel_heavy_rate"),
        ])
        .sort(["team", "season", "week"])
    )

    # Rolling averages (shifted to avoid leakage)
    output_cols = []
    for col in ["personnel_11_rate", "personnel_12_rate",
                "personnel_21_rate", "personnel_heavy_rate"]:
        # 5-game rolling
        game_stats = game_stats.with_columns(
            pl.col(col)
            .shift(1)
            .rolling_mean(window_size=5, min_periods=1)
            .over(["team", "season"])
            .alias(f"team_{col}_avg_5g")
        )
        output_cols.append(f"team_{col}_avg_5g")

        # Season average
        game_stats = game_stats.with_columns(
            pl.col(col)
            .shift(1)
            .rolling_mean(window_size=100, min_periods=1)
            .over(["team", "season"])
            .alias(f"team_{col}_szn")
        )
        output_cols.append(f"team_{col}_szn")

    return game_stats.select(["season", "week", "team"] + output_cols)
