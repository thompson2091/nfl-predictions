"""Red zone features: carries, targets, and TD rate inside the 20."""
import polars as pl
from src.utils.config import get_config


def build_player_redzone_features(pbp: pl.DataFrame) -> pl.DataFrame:
    """Per-player red zone usage and TD rate. Shift(1)."""
    cfg = get_config()
    short = cfg["rolling_windows"]["short"]
    medium = cfg["rolling_windows"]["medium"]

    rz = pbp.filter(
        (pl.col("yardline_100").is_not_null())
        & (pl.col("yardline_100") <= 20)
    )

    # Red zone rushes per player
    rz_rush = (
        rz.filter(pl.col("rusher_player_id").is_not_null())
        .group_by(["season", "week", "rusher_player_id"])
        .agg([
            pl.len().alias("rz_carries"),
            pl.col("rush_touchdown").sum().alias("rz_rush_tds"),
        ])
        .rename({"rusher_player_id": "player_id"})
    )

    # Red zone targets per player
    rz_recv = (
        rz.filter(pl.col("receiver_player_id").is_not_null())
        .group_by(["season", "week", "receiver_player_id"])
        .agg([
            pl.len().alias("rz_targets"),
            pl.col("pass_touchdown").sum().alias("rz_recv_tds"),
        ])
        .rename({"receiver_player_id": "player_id"})
    )

    # Merge
    rz_player = rz_rush.join(
        rz_recv,
        on=["season", "week", "player_id"],
        how="full",
        coalesce=True,
    ).with_columns([
        pl.col("rz_carries").fill_null(0),
        pl.col("rz_rush_tds").fill_null(0),
        pl.col("rz_targets").fill_null(0),
        pl.col("rz_recv_tds").fill_null(0),
    ]).with_columns(
        (pl.col("rz_carries") + pl.col("rz_targets")).alias("rz_touches"),
        (pl.col("rz_rush_tds") + pl.col("rz_recv_tds")).alias("rz_tds"),
    )

    rz_player = rz_player.sort(["player_id", "season", "week"])

    # Rolling features with shift(1)
    stat_cols = ["rz_carries", "rz_targets", "rz_touches", "rz_tds"]
    rolling_exprs = []
    for col in stat_cols:
        shifted = pl.col(col).shift(1)
        rolling_exprs.extend([
            shifted.rolling_mean(medium, min_samples=3).over("player_id").alias(f"player_{col}_avg_{medium}g"),
            (shifted.cum_sum().over("player_id") / shifted.cum_count().over("player_id")).alias(f"player_{col}_szn_avg"),
        ])

    # Red zone TD rate
    rz_td_shifted = pl.col("rz_tds").shift(1)
    rz_touch_shifted = pl.col("rz_touches").shift(1)
    rolling_exprs.append(
        (rz_td_shifted.cum_sum().over("player_id") / rz_touch_shifted.cum_sum().over("player_id").clip(lower_bound=1))
        .alias("player_rz_td_rate_szn")
    )

    # Goal line (inside 5) - extra signal for short-yardage backs
    gl = pbp.filter(
        (pl.col("yardline_100").is_not_null())
        & (pl.col("yardline_100") <= 5)
    )
    gl_rush = (
        gl.filter(pl.col("rusher_player_id").is_not_null())
        .group_by(["season", "week", "rusher_player_id"])
        .agg([
            pl.len().alias("gl_carries"),
            pl.col("rush_touchdown").sum().alias("gl_rush_tds"),
        ])
        .rename({"rusher_player_id": "player_id"})
    )

    # Merge goal line
    rz_player = rz_player.join(
        gl_rush,
        on=["season", "week", "player_id"],
        how="left",
    ).with_columns([
        pl.col("gl_carries").fill_null(0),
        pl.col("gl_rush_tds").fill_null(0),
    ])

    gl_shifted = pl.col("gl_carries").shift(1)
    rolling_exprs.extend([
        gl_shifted.rolling_mean(medium, min_samples=3).over("player_id").alias(f"player_gl_carries_avg_{medium}g"),
        (gl_shifted.cum_sum().over("player_id") / gl_shifted.cum_count().over("player_id")).alias("player_gl_carries_szn_avg"),
    ])

    result = (
        rz_player
        .with_columns(rolling_exprs)
        .select(["player_id", "season", "week"] + [e.meta.output_name() for e in rolling_exprs])
    )

    return result


def build_team_redzone_features(pbp: pl.DataFrame) -> pl.DataFrame:
    """Per-team red zone efficiency. Shift(1)."""
    cfg = get_config()
    medium = cfg["rolling_windows"]["medium"]

    rz = pbp.filter(
        (pl.col("yardline_100").is_not_null())
        & (pl.col("yardline_100") <= 20)
        & pl.col("posteam").is_not_null()
    )

    team_rz = (
        rz.group_by(["season", "week", "posteam"])
        .agg([
            pl.len().alias("rz_plays"),
            pl.col("touchdown").sum().alias("rz_tds_scored"),
            pl.col("rush_touchdown").sum().alias("rz_rush_tds"),
            pl.col("pass_touchdown").sum().alias("rz_pass_tds"),
        ])
        .rename({"posteam": "team"})
        .with_columns(
            (pl.col("rz_tds_scored") / pl.col("rz_plays").cast(pl.Float64).clip(lower_bound=1))
            .alias("rz_td_pct")
        )
        .sort(["team", "season", "week"])
    )

    rolling_exprs = []
    for col in ["rz_td_pct", "rz_tds_scored", "rz_rush_tds", "rz_pass_tds"]:
        shifted = pl.col(col).shift(1)
        rolling_exprs.extend([
            shifted.rolling_mean(medium, min_samples=3).over("team").alias(f"team_{col}_avg_{medium}g"),
            (shifted.cum_sum().over("team") / shifted.cum_count().over("team")).alias(f"team_{col}_szn_avg"),
        ])

    result = (
        team_rz
        .with_columns(rolling_exprs)
        .select(["season", "week", "team"] + [e.meta.output_name() for e in rolling_exprs])
    )

    return result
