"""TD drought/streak features: weeks since last TD, hot/cold streaks."""
import polars as pl


def build_td_streak_features(weekly_stats: pl.DataFrame) -> pl.DataFrame:
    """Per-player TD streak/drought features. Shift(1) to prevent leakage."""

    df = weekly_stats.sort(["player_id", "season", "week"])

    if "rushing_tds" not in df.columns or "receiving_tds" not in df.columns:
        return pl.DataFrame(schema={"player_id": pl.Utf8, "season": pl.Int64, "week": pl.Int64})

    # Flag: did player score a TD this week
    df = df.with_columns(
        ((pl.col("rushing_tds").fill_null(0) + pl.col("receiving_tds").fill_null(0)) > 0)
        .cast(pl.Int64)
        .alias("scored_td")
    )

    # Shift to prevent leakage
    df = df.with_columns(pl.col("scored_td").shift(1).over("player_id").alias("scored_td_prev"))

    # Weeks since last TD: count games since last scored_td_prev == 1
    # Use cumulative approach: reset counter each time player scores
    df = df.with_columns(
        pl.col("scored_td_prev").fill_null(0).alias("scored_td_prev")
    )

    # Build a group ID that increments each time the player scores
    df = df.with_columns(
        pl.col("scored_td_prev").cum_sum().over("player_id").alias("td_group")
    )

    # Within each group, count rows = weeks since last TD
    df = df.with_columns(
        pl.col("td_group").cum_count().over(["player_id", "td_group"]).alias("weeks_since_last_td")
    )
    # If td_group == 0 (never scored), set to a large number
    df = df.with_columns(
        pl.when(pl.col("td_group") == 0)
        .then(pl.lit(99))
        .otherwise(pl.col("weeks_since_last_td"))
        .alias("weeks_since_last_td")
    )

    # TD streak length: consecutive games with TD (looking backwards from shifted data)
    # For each row, count consecutive 1s in scored_td_prev going backwards
    # Approximate: use rolling sum over last N games
    df = df.with_columns(
        pl.col("scored_td_prev")
        .rolling_sum(10, min_samples=1)
        .over("player_id")
        .alias("_td_last_10")
    )

    # Streak: consecutive games with TD ending at previous game
    # Count backwards from current position while scored_td_prev == 1
    # Use a simpler approach: check last 2 and last 4 games
    df = df.with_columns([
        # Last 2 games both had TDs
        (pl.col("scored_td_prev").rolling_min(2, min_samples=2).over("player_id") == 1)
        .fill_null(False).cast(pl.Float64).alias("is_td_hot"),
        # No TD in last 4 games
        (pl.col("scored_td_prev").rolling_max(4, min_samples=4).over("player_id") == 0)
        .fill_null(False).cast(pl.Float64).alias("is_td_cold"),
        # Streak length approximation: rolling sum of last 5 consecutive
        pl.col("scored_td_prev").rolling_sum(5, min_samples=1).over("player_id")
        .alias("td_streak_approx"),
    ])

    result = df.select([
        "player_id", "season", "week",
        pl.col("weeks_since_last_td").cast(pl.Float64),
        "is_td_hot", "is_td_cold",
        pl.col("td_streak_approx").cast(pl.Float64).alias("td_streak_length"),
    ])

    return result
