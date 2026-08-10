import polars as pl
from src.utils.config import get_config


def build_player_rolling_features(weekly_stats: pl.DataFrame) -> pl.DataFrame:
    """Build per-player rolling stats. Shift(1) to prevent leakage."""
    cfg = get_config()
    short = cfg["rolling_windows"]["short"]
    medium = cfg["rolling_windows"]["medium"]

    # Ensure sorted by player and time
    df = weekly_stats.sort(["player_id", "season", "week"])

    # Core stats to roll
    stat_cols = [
        "carries", "rushing_yards", "rushing_tds",
        "targets", "receptions", "receiving_yards", "receiving_tds",
        "fantasy_points_ppr",
        "rushing_epa", "receiving_epa",
        "rushing_first_downs", "receiving_first_downs",
        "rushing_2pt_conversions",
    ]

    # Keep only columns that exist
    available = [c for c in stat_cols if c in df.columns]

    # Build rolling features with shift(1) to avoid leakage
    rolling_exprs = []
    for col in available:
        shifted = pl.col(col).shift(1)
        for window, label in [(short, f"{short}g"), (medium, f"{medium}g")]:
            rolling_exprs.append(
                shifted.rolling_mean(window, min_samples=3)
                .over("player_id")
                .alias(f"player_{col}_avg_{label}")
            )
        # Season-to-date mean
        rolling_exprs.append(
            (shifted.cum_sum().over("player_id") / shifted.cum_count().over("player_id")).alias(f"player_{col}_szn_avg")
        )

    # First TD rate (needs first_tds joined later, use rushing+receiving TDs as proxy)
    if "rushing_tds" in df.columns and "receiving_tds" in df.columns:
        df = df.with_columns(
            (pl.col("rushing_tds") + pl.col("receiving_tds")).alias("total_tds")
        )
        shifted_tds = pl.col("total_tds").shift(1)
        rolling_exprs.extend([
            shifted_tds.rolling_mean(short, min_samples=3).over("player_id").alias(f"player_total_tds_avg_{short}g"),
            shifted_tds.rolling_mean(medium, min_samples=3).over("player_id").alias(f"player_total_tds_avg_{medium}g"),
            (shifted_tds.cum_sum().over("player_id") / shifted_tds.cum_count().over("player_id")).alias("player_total_tds_szn_avg"),
        ])

    result = df.with_columns(rolling_exprs).select(
        ["player_id", "season", "week"]
        + [e.meta.output_name() for e in rolling_exprs]
    )

    return result
