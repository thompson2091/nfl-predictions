"""Player share features: target_share, air_yards_share, wopr, rush_share, td_market_share."""
import polars as pl
from src.utils.config import get_config
from src.features.carry_forward import build_with_carry_forward


def build_player_share_features(weekly_stats: pl.DataFrame,
                                spine: pl.DataFrame = None) -> pl.DataFrame:
    """Per-player share/efficiency metrics. Shift(1) rolling."""
    cfg = get_config()
    short = cfg["rolling_windows"]["short"]
    medium = cfg["rolling_windows"]["medium"]

    df = weekly_stats.sort(["player_id", "season", "week"])

    # Columns already in weekly_stats
    share_cols = []
    for col in ["target_share", "air_yards_share", "wopr"]:
        if col in df.columns:
            share_cols.append(col)

    # Build rush_share: player carries / team carries per week
    # Need team-level carries first
    if "carries" in df.columns and "recent_team" in df.columns:
        team_carries = (
            df.group_by(["season", "week", "recent_team"])
            .agg(pl.col("carries").sum().alias("team_carries"))
        )
        df = df.join(
            team_carries,
            on=["season", "week", "recent_team"],
            how="left",
        )
        df = df.with_columns(
            (pl.col("carries") / pl.col("team_carries").cast(pl.Float64).clip(lower_bound=1))
            .alias("rush_share")
        ).drop("team_carries")
        share_cols.append("rush_share")

    # TD market share: player TDs / team TDs
    if "rushing_tds" in df.columns and "receiving_tds" in df.columns:
        df = df.with_columns(
            (pl.col("rushing_tds") + pl.col("receiving_tds")).alias("player_tds_for_share")
        )
        team_tds = (
            df.group_by(["season", "week", "recent_team"])
            .agg(pl.col("player_tds_for_share").sum().alias("team_tds_total"))
        )
        df = df.join(team_tds, on=["season", "week", "recent_team"], how="left")
        df = df.with_columns(
            (pl.col("player_tds_for_share") / pl.col("team_tds_total").cast(pl.Float64).clip(lower_bound=1))
            .alias("td_market_share")
        ).drop(["player_tds_for_share", "team_tds_total"])
        share_cols.append("td_market_share")

    # Receiving YAC per reception
    if "receiving_yards_after_catch" in df.columns and "receptions" in df.columns:
        df = df.with_columns(
            (pl.col("receiving_yards_after_catch") / pl.col("receptions").cast(pl.Float64).clip(lower_bound=1))
            .alias("receiving_yac_per_rec")
        )
        share_cols.append("receiving_yac_per_rec")
    elif "racr" in df.columns:
        share_cols.append("racr")

    # Rolling features. lag=1 for real rows (no leakage); lag=0 supplies the
    # state carried into an unplayed week — see src/features/carry_forward.py.
    def _exprs(lag: int) -> list[pl.Expr]:
        out = []
        for col in share_cols:
            if col not in df.columns:
                continue
            base = pl.col(col).shift(lag) if lag else pl.col(col)
            out.extend([
                base.rolling_mean(short, min_samples=3).over("player_id").alias(f"player_{col}_avg_{short}g"),
                base.rolling_mean(medium, min_samples=3).over("player_id").alias(f"player_{col}_avg_{medium}g"),
                (base.cum_sum().over("player_id") / base.cum_count().over("player_id")).alias(f"player_{col}_szn_avg"),
            ])
        return out

    return build_with_carry_forward(df, _exprs, spine=spine, zero_cols=share_cols)
