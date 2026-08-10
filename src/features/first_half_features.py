"""First-half usage features: carries, targets, touches in Half1 only."""
import polars as pl
from src.utils.config import get_config
from src.features.spine import densify


def build_first_half_features(pbp: pl.DataFrame, spine: pl.DataFrame) -> pl.DataFrame:
    """Per-player first-half usage. Filters out garbage-time inflation. Shift(1)."""
    cfg = get_config()
    medium = cfg["rolling_windows"]["medium"]

    h1 = pbp.filter(
        (pl.col("game_half") == "Half1")
        & pl.col("posteam").is_not_null()
    )

    # Player rushes in first half
    rush_h1 = (
        h1.filter(pl.col("rusher_player_id").is_not_null())
        .group_by(["season", "week", "posteam", "rusher_player_id"])
        .agg(pl.len().alias("h1_carries"))
        .rename({"rusher_player_id": "player_id", "posteam": "team"})
    )

    # Player targets in first half
    recv_h1 = (
        h1.filter(pl.col("receiver_player_id").is_not_null())
        .group_by(["season", "week", "posteam", "receiver_player_id"])
        .agg(pl.len().alias("h1_targets"))
        .rename({"receiver_player_id": "player_id", "posteam": "team"})
    )

    player_h1 = rush_h1.join(
        recv_h1, on=["season", "week", "team", "player_id"],
        how="full", coalesce=True,
    ).with_columns([
        pl.col("h1_carries").fill_null(0),
        pl.col("h1_targets").fill_null(0),
    ]).with_columns(
        (pl.col("h1_carries") + pl.col("h1_targets")).alias("h1_touches"),
    )

    # Team plays in first half for share
    team_h1_plays = (
        h1.group_by(["season", "week", "posteam"])
        .agg(pl.len().alias("team_h1_plays"))
        .rename({"posteam": "team"})
    )

    player_h1 = player_h1.join(
        team_h1_plays, on=["season", "week", "team"], how="left",
    ).with_columns(
        (pl.col("h1_touches") / pl.col("team_h1_plays").cast(pl.Float64).clip(lower_bound=1))
        .alias("h1_touch_share")
    ).drop("team_h1_plays")

    # Densify: absence must mean "available, no first-half touch" rather than
    # silently encoding current-game involvement. See src/features/spine.py.
    player_h1 = densify(
        player_h1, spine,
        zero_cols=["h1_carries", "h1_targets", "h1_touches", "h1_touch_share"],
    )

    # Rolling with shift(1)
    rolling_exprs = []
    for col in ["h1_carries", "h1_targets", "h1_touches", "h1_touch_share"]:
        shifted = pl.col(col).shift(1)
        rolling_exprs.extend([
            shifted.rolling_mean(medium, min_samples=3).over("player_id").alias(f"player_{col}_avg_{medium}g"),
            (shifted.cum_sum().over("player_id") / shifted.cum_count().over("player_id")).alias(f"player_{col}_szn_avg"),
        ])

    result = (
        player_h1.with_columns(rolling_exprs)
        .select(["player_id", "season", "week"]
                + [e.meta.output_name() for e in rolling_exprs])
    )

    return result
