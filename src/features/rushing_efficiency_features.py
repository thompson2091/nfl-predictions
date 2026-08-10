"""Rushing efficiency features from NGS rushing data."""
import polars as pl
from src.utils.config import get_config


def build_rushing_efficiency_features(ngs_rushing: pl.DataFrame) -> pl.DataFrame:
    """Per-player NGS rushing metrics. Shift(1) rolling to prevent leakage."""
    cfg = get_config()
    short = cfg["rolling_windows"]["short"]
    medium = cfg["rolling_windows"]["medium"]

    if ngs_rushing.is_empty():
        return pl.DataFrame(schema={"player_id": pl.Utf8, "season": pl.Int64, "week": pl.Int64})

    stat_cols = [
        "efficiency", "rush_yards_over_expected_per_att",
        "percent_attempts_gte_eight_defenders",
    ]
    available = [c for c in stat_cols if c in ngs_rushing.columns]

    if not available:
        return pl.DataFrame(schema={"player_id": pl.Utf8, "season": pl.Int64, "week": pl.Int64})

    df = ngs_rushing.select(
        [pl.col("player_gsis_id").alias("player_id"), "season", "week"] + available
    ).sort(["player_id", "season", "week"])

    rolling_exprs = []
    for col in available:
        shifted = pl.col(col).cast(pl.Float64).shift(1)
        rolling_exprs.extend([
            shifted.rolling_mean(short, min_samples=3).over("player_id").alias(f"ngs_{col}_avg_{short}g"),
            shifted.rolling_mean(medium, min_samples=3).over("player_id").alias(f"ngs_{col}_avg_{medium}g"),
            (shifted.cum_sum().over("player_id") / shifted.cum_count().over("player_id")).alias(f"ngs_{col}_szn_avg"),
        ])

    result = (
        df.with_columns(rolling_exprs)
        .select(["player_id", "season", "week"] + [e.meta.output_name() for e in rolling_exprs])
    )

    return result
