import polars as pl
from src.utils.paths import get_path


def build_snap_features(snap_counts: pl.DataFrame, rosters: pl.DataFrame) -> pl.DataFrame:
    """Snap count percentage from previous week (shifted in assembler).

    Snap counts use player names and pfr_player_id, not GSIS IDs.
    We map via rosters' pfr_id -> player_id (GSIS ID).
    """
    # Build pfr_id -> player_id mapping from rosters
    pfr_mapping = (
        rosters.select(["player_id", "pfr_id"])
        .filter(pl.col("pfr_id").is_not_null() & pl.col("player_id").is_not_null())
        .unique(subset=["pfr_id"], keep="last")
    )

    snaps = snap_counts.select([
        "pfr_player_id", "season", "week", "team", "offense_pct",
    ])

    # Map pfr_player_id -> player_id via rosters
    snaps = snaps.join(
        pfr_mapping, left_on="pfr_player_id", right_on="pfr_id", how="left"
    ).filter(
        pl.col("player_id").is_not_null()
    ).select([
        "player_id", "season", "week", "team",
        pl.col("offense_pct").alias("snap_pct"),
    ])

    return snaps


def build_depth_chart_features(depth_charts: pl.DataFrame) -> pl.DataFrame:
    """Starter flag from depth charts. Handles both old (2015-2024) and new (2025+) formats."""

    # Old format has: season, week, club_code, gsis_id, depth_team, formation
    # New format has: dt, team, gsis_id, pos_abb, pos_rank (no season/week)
    if "depth_team" in depth_charts.columns:
        return _build_dc_old_format(depth_charts)
    elif "pos_rank" in depth_charts.columns:
        return _build_dc_new_format(depth_charts)
    else:
        # Empty fallback
        return pl.DataFrame(schema={
            "player_id": pl.Utf8, "season": pl.Int64,
            "week": pl.Int64, "team": pl.Utf8, "is_starter": pl.Int8,
        })


def _build_dc_old_format(depth_charts: pl.DataFrame) -> pl.DataFrame:
    """Old depth chart format (2015-2024): has season, week, depth_team."""
    dc = depth_charts.select([
        "season", "week", "club_code", "gsis_id",
        "depth_team", "formation",
    ]).rename({"club_code": "team", "gsis_id": "player_id"}).with_columns(
        pl.col("week").cast(pl.Int64),
        pl.col("season").cast(pl.Int64),
    )

    # Starter = depth_team == 1
    dc = dc.with_columns(
        (pl.col("depth_team").cast(pl.Int32, strict=False) == 1).cast(pl.Int8).alias("is_starter")
    ).filter(
        pl.col("player_id").is_not_null()
    )

    # Take most recent depth chart entry per player/season/week
    dc = dc.sort(["player_id", "season", "week"]).unique(
        subset=["player_id", "season", "week"], keep="last"
    )

    return dc.select(["player_id", "season", "week", "team", "is_starter"])


def _build_dc_new_format(depth_charts: pl.DataFrame) -> pl.DataFrame:
    """New depth chart format (2025+): has dt, pos_rank, no season/week."""
    # Parse date to get season and approximate week
    dc = depth_charts.filter(
        pl.col("gsis_id").is_not_null()
    ).with_columns(
        pl.col("dt").str.slice(0, 10).str.to_date("%Y-%m-%d").alias("date"),
    )

    # Derive season from date (NFL season starts in September)
    dc = dc.with_columns(
        pl.when(pl.col("date").dt.month() >= 3)
        .then(pl.col("date").dt.year())
        .otherwise(pl.col("date").dt.year() - 1)
        .cast(pl.Int64)
        .alias("season")
    )

    # Map dates to NFL weeks: use the most recent snapshot per team
    # For prediction, we just need the latest depth chart
    # Group by taking the latest date's snapshot per player per season
    dc = dc.sort("date").unique(
        subset=["gsis_id", "season", "team"], keep="last"
    )

    # Offensive positions only
    off_positions = ["QB", "RB", "WR", "TE", "FB", "LWR", "RWR", "SWR"]
    dc = dc.filter(pl.col("pos_abb").is_in(off_positions))

    # Starter = pos_rank == 1
    dc = dc.with_columns(
        (pl.col("pos_rank") == 1).cast(pl.Int8).alias("is_starter")
    )

    # For predict season, assign week=1 so carry-forward works
    dc = dc.with_columns(pl.lit(1).cast(pl.Int64).alias("week"))

    return dc.select([
        pl.col("gsis_id").alias("player_id"),
        "season", "week",
        pl.col("team"),
        "is_starter",
    ]).unique(subset=["player_id", "season", "week"], keep="last")
