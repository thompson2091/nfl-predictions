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
    counts = (
        tds.group_by(["game_id", "season", "week", "defteam"])
        .agg([
            pl.len().alias("tds_allowed_total"),
            (pl.col("position") == "RB").sum().alias("tds_allowed_to_rb"),
            (pl.col("position") == "WR").sum().alias("tds_allowed_to_wr"),
            (pl.col("position") == "TE").sum().alias("tds_allowed_to_te"),
            (pl.col("position") == "QB").sum().alias("tds_allowed_to_qb"),
        ])
    )
    # EVERY GAME THE DEFENSE PLAYED, NOT ONLY THE ONES IT GAVE UP A TOUCHDOWN
    # IN. Built from scoring plays alone, a row existed only when that defense
    # allowed a TD in that game, so a null on the joined feature row meant "no
    # touchdown allowed in THIS game" — a same-game leak: scoring rates 77x
    # apart between null and non-null rows (2024-25), 14% of those teams with
    # a scorer against 92%. Serving never sees a null (carry-forward), so the
    # backtests were flattered as well. And the shutouts are now in the
    # averages, which skipped them and ran high.
    played = (pbp.filter(pl.col("defteam").is_not_null())
              .select(["game_id", "season", "week", "defteam"]).unique())
    zero = [c for c in counts.columns if c.startswith("tds_allowed")]
    game_def = (
        played.join(counts, on=["game_id", "season", "week", "defteam"], how="left")
        .with_columns([pl.col(c).fill_null(0) for c in zero])
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
            # Per SEASON, as the name says: `.over("opponent")` alone made
            # it a career average running back to 2015.
            (shifted.cum_sum().over(["opponent", "season"])
             / shifted.cum_count().over(["opponent", "season"])).alias(f"opp_{col}_szn_avg"),
        ])

    # Also: proportion of TDs allowed to each position
    for col in stat_cols:
        pos = col.replace("tds_allowed_to_", "")
        total_shifted = pl.col("tds_allowed_total").shift(1)
        col_shifted = pl.col(col).shift(1)
        rolling_exprs.append(
            (col_shifted.cum_sum().over(["opponent", "season"])
             / total_shifted.cum_sum().over(["opponent", "season"]).clip(lower_bound=1))
            .alias(f"opp_td_pct_to_{pos}_szn")
        )

    result = (
        game_def
        .with_columns(rolling_exprs)
        .select(["season", "week", "opponent"] + [e.meta.output_name() for e in rolling_exprs])
    )

    return result
