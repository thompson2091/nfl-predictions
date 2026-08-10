"""Goal line & end zone features: inside-5/10 usage and share metrics."""
import polars as pl
from src.utils.config import get_config
from src.features.spine import densify


def build_goalline_features(pbp: pl.DataFrame, spine: pl.DataFrame) -> pl.DataFrame:
    """Per-player goal-line carry/target share and TD rate. Shift(1) rolling."""
    cfg = get_config()
    medium = cfg["rolling_windows"]["medium"]

    # --- Inside-5 and inside-10 carries per player per week ---
    def _agg_zone(zone_filter, prefix):
        zone = pbp.filter(
            (pl.col("yardline_100").is_not_null())
            & zone_filter
        )

        rush = (
            zone.filter(pl.col("rusher_player_id").is_not_null())
            .group_by(["season", "week", "posteam", "rusher_player_id"])
            .agg([
                pl.len().alias(f"{prefix}_carries"),
                pl.col("rush_touchdown").sum().alias(f"{prefix}_rush_tds"),
            ])
            .rename({"rusher_player_id": "player_id", "posteam": "team"})
        )

        recv = (
            zone.filter(pl.col("receiver_player_id").is_not_null())
            .group_by(["season", "week", "posteam", "receiver_player_id"])
            .agg([
                pl.len().alias(f"{prefix}_targets"),
            ])
            .rename({"receiver_player_id": "player_id", "posteam": "team"})
        )

        merged = rush.join(
            recv, on=["season", "week", "team", "player_id"],
            how="full", coalesce=True,
        ).with_columns([
            pl.col(f"{prefix}_carries").fill_null(0),
            pl.col(f"{prefix}_rush_tds").fill_null(0),
            pl.col(f"{prefix}_targets").fill_null(0),
        ]).with_columns(
            (pl.col(f"{prefix}_carries") + pl.col(f"{prefix}_targets")).alias(f"{prefix}_touches"),
        )

        # Team totals for share calculation
        team_totals = (
            merged.group_by(["season", "week", "team"])
            .agg(pl.col(f"{prefix}_touches").sum().alias(f"team_{prefix}_touches"))
        )
        merged = merged.join(team_totals, on=["season", "week", "team"], how="left")
        merged = merged.with_columns(
            (pl.col(f"{prefix}_touches") / pl.col(f"team_{prefix}_touches").cast(pl.Float64).clip(lower_bound=1))
            .alias(f"{prefix}_touch_share")
        ).drop(f"team_{prefix}_touches")

        return merged

    i5 = _agg_zone(pl.col("yardline_100") <= 5, "i5")
    i10 = _agg_zone(pl.col("yardline_100") <= 10, "i10")

    # Merge i5 and i10
    gl = i5.join(
        i10, on=["season", "week", "team", "player_id"],
        how="full", coalesce=True,
    ).with_columns([
        pl.col(c).fill_null(0)
        for c in ["i5_carries", "i5_rush_tds", "i5_targets", "i5_touches",
                   "i10_carries", "i10_targets", "i10_touches"]
    ]).with_columns([
        pl.col("i5_touch_share").fill_null(0.0),
        pl.col("i10_touch_share").fill_null(0.0),
    ])

    # Endzone TD rate = TDs from inside-5 / inside-5 touches
    gl = gl.with_columns(
        (pl.col("i5_rush_tds") / pl.col("i5_touches").cast(pl.Float64).clip(lower_bound=1))
        .alias("endzone_td_rate")
    )

    # Densify before rolling. A row previously existed only for weeks the player
    # had goal-line usage, so non-nullness leaked current-game involvement —
    # worth a 15.5x lift in P(scored) on its own. See src/features/spine.py.
    gl = densify(
        gl, spine,
        zero_cols=["i5_carries", "i5_rush_tds", "i5_targets", "i5_touches",
                   "i5_touch_share", "i10_carries", "i10_targets",
                   "i10_touches", "i10_touch_share", "endzone_td_rate"],
    )

    # Rolling features with shift(1)
    stat_cols = ["i5_carries", "i5_targets", "i5_touches", "i5_touch_share",
                 "i10_carries", "i10_targets", "i10_touches", "i10_touch_share",
                 "endzone_td_rate"]

    rolling_exprs = []
    for col in stat_cols:
        shifted = pl.col(col).shift(1)
        rolling_exprs.extend([
            shifted.rolling_mean(medium, min_samples=3).over("player_id").alias(f"player_{col}_avg_{medium}g"),
            (shifted.cum_sum().over("player_id") / shifted.cum_count().over("player_id")).alias(f"player_{col}_szn_avg"),
        ])

    result = (
        gl.with_columns(rolling_exprs)
        .select(["player_id", "season", "week"] + [e.meta.output_name() for e in rolling_exprs])
    )

    return result
