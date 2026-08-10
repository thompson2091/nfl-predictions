"""Pace/volume features: plays per game, seconds per play, drives per game."""
import polars as pl
from src.utils.config import get_config


def build_pace_features(pbp: pl.DataFrame) -> pl.DataFrame:
    """Per-team pace metrics. Shift(1) rolling to prevent leakage."""
    cfg = get_config()
    medium = cfg["rolling_windows"]["medium"]

    plays = pbp.filter(pl.col("posteam").is_not_null())

    # Per-game team stats
    team_game = (
        plays.group_by(["game_id", "season", "week", "posteam"])
        .agg([
            pl.len().alias("plays_per_game"),
            pl.col("fixed_drive").n_unique().alias("drives_per_game"),
        ])
        .rename({"posteam": "team"})
    )

    # Seconds per play from drive time of possession
    if "drive_time_of_possession" in pbp.columns:
        # Parse MM:SS format to seconds
        drive_top = (
            plays.select(["game_id", "season", "week", "posteam", "fixed_drive", "drive_time_of_possession"])
            .unique(subset=["game_id", "posteam", "fixed_drive"], keep="last")
            .filter(pl.col("drive_time_of_possession").is_not_null())
        )

        # Count plays per drive
        plays_per_drive = (
            plays.group_by(["game_id", "posteam", "fixed_drive"])
            .agg(pl.len().alias("drive_plays"))
        )

        drive_info = drive_top.join(
            plays_per_drive, on=["game_id", "posteam", "fixed_drive"], how="left"
        )

        # Parse TOP string to seconds
        drive_info = drive_info.with_columns(
            pl.col("drive_time_of_possession")
            .str.split(":")
            .list.get(0).cast(pl.Float64, strict=False).fill_null(0) * 60
            + pl.col("drive_time_of_possession")
            .str.split(":")
            .list.get(1).cast(pl.Float64, strict=False).fill_null(0)
        ).with_columns(
            pl.col("drive_time_of_possession").alias("drive_seconds")
        )

        # Total seconds / total plays per game
        game_spp = (
            drive_info.group_by(["game_id", "season", "week", "posteam"])
            .agg([
                pl.col("drive_seconds").sum().alias("total_top_seconds"),
                pl.col("drive_plays").sum().alias("total_drive_plays"),
            ])
            .with_columns(
                (pl.col("total_top_seconds") / pl.col("total_drive_plays").cast(pl.Float64).clip(lower_bound=1))
                .alias("seconds_per_play")
            )
            .rename({"posteam": "team"})
            .select(["game_id", "season", "week", "team", "seconds_per_play"])
        )

        team_game = team_game.join(game_spp, on=["game_id", "season", "week", "team"], how="left")
    else:
        team_game = team_game.with_columns(pl.lit(None).cast(pl.Float64).alias("seconds_per_play"))

    team_game = team_game.sort(["team", "season", "week"])

    # Rolling features with shift(1)
    stat_cols = ["plays_per_game", "drives_per_game", "seconds_per_play"]
    rolling_exprs = []
    for col in stat_cols:
        shifted = pl.col(col).cast(pl.Float64).shift(1)
        rolling_exprs.extend([
            shifted.rolling_mean(medium, min_samples=3).over("team").alias(f"team_{col}_avg_{medium}g"),
            (shifted.cum_sum().over("team") / shifted.cum_count().over("team")).alias(f"team_{col}_szn_avg"),
        ])

    result = (
        team_game.with_columns(rolling_exprs)
        .select(["season", "week", "team"] + [e.meta.output_name() for e in rolling_exprs])
    )

    return result
