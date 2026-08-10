"""Opponent position-specific TD features: TDs allowed to RB/WR/TE/QB."""
import polars as pl
from src.utils.config import get_config


def build_opponent_position_features(pbp: pl.DataFrame, rosters: pl.DataFrame) -> pl.DataFrame:
    """Per-opponent: TDs allowed broken down by scorer position. Shift(1)."""
    cfg = get_config()
    medium = cfg["rolling_windows"]["medium"]

    # Get all TDs with scorer position
    tds = pbp.filter(
        (pl.col("touchdown") == 1)
        & pl.col("td_player_id").is_not_null()
        & pl.col("defteam").is_not_null()
    ).select(["game_id", "season", "week", "defteam", "td_player_id"])

    roster_pos = (
        rosters.select(["season", "player_id", "position"])
        .unique(subset=["season", "player_id"], keep="last")
    )

    tds = tds.join(
        roster_pos,
        left_on=["season", "td_player_id"],
        right_on=["season", "player_id"],
        how="left",
    )

    # Aggregate: per game/defteam, how many TDs allowed to each position
    game_def = (
        tds.group_by(["game_id", "season", "week", "defteam"])
        .agg([
            pl.len().alias("tds_allowed_total"),
            (pl.col("position") == "RB").sum().alias("tds_allowed_to_rb"),
            (pl.col("position") == "WR").sum().alias("tds_allowed_to_wr"),
            (pl.col("position") == "TE").sum().alias("tds_allowed_to_te"),
            (pl.col("position") == "QB").sum().alias("tds_allowed_to_qb"),
        ])
        .rename({"defteam": "opponent"})
        .sort(["opponent", "season", "week"])
    )

    # Rolling features with shift(1)
    stat_cols = ["tds_allowed_to_rb", "tds_allowed_to_wr",
                 "tds_allowed_to_te", "tds_allowed_to_qb"]
    rolling_exprs = []
    for col in stat_cols:
        shifted = pl.col(col).shift(1)
        rolling_exprs.extend([
            shifted.rolling_mean(medium, min_samples=3).over("opponent").alias(f"opp_{col}_avg_{medium}g"),
            (shifted.cum_sum().over("opponent") / shifted.cum_count().over("opponent")).alias(f"opp_{col}_szn_avg"),
        ])

    # Also: proportion of TDs allowed to each position
    for col in stat_cols:
        pos = col.replace("tds_allowed_to_", "")
        total_shifted = pl.col("tds_allowed_total").shift(1)
        col_shifted = pl.col(col).shift(1)
        rolling_exprs.append(
            (col_shifted.cum_sum().over("opponent") / total_shifted.cum_sum().over("opponent").clip(lower_bound=1))
            .alias(f"opp_td_pct_to_{pos}_szn")
        )

    result = (
        game_def
        .with_columns(rolling_exprs)
        .select(["season", "week", "opponent"] + [e.meta.output_name() for e in rolling_exprs])
    )

    return result
