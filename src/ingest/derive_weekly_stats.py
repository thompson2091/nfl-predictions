"""Derive weekly player stats from PBP for seasons missing from nflreadpy."""
import polars as pl
from src.utils.paths import get_path


def derive_weekly_stats_from_pbp(seasons: list[int]) -> pl.DataFrame:
    pbp = pl.read_parquet(get_path("raw") / "pbp.parquet")
    pbp = pbp.filter(pl.col("season").is_in(seasons))

    if pbp.shape[0] == 0:
        return pl.DataFrame()

    # --- Rushing stats per player/game ---
    rush = (
        pbp.filter(pl.col("rusher_player_id").is_not_null())
        .group_by(["season", "week", "rusher_player_id", "posteam"])
        .agg([
            pl.len().alias("carries"),
            pl.col("rushing_yards").sum().alias("rushing_yards"),
            pl.col("rush_touchdown").sum().alias("rushing_tds"),
        ])
        .rename({"rusher_player_id": "player_id", "posteam": "recent_team"})
    )

    # --- Receiving stats per player/game ---
    recv = (
        pbp.filter(pl.col("receiver_player_id").is_not_null())
        .group_by(["season", "week", "receiver_player_id", "posteam"])
        .agg([
            pl.len().alias("targets"),
            pl.col("complete_pass").sum().alias("receptions"),
            pl.col("receiving_yards").sum().alias("receiving_yards"),
            pl.col("pass_touchdown").sum().alias("receiving_tds"),
        ])
        .rename({"receiver_player_id": "player_id", "posteam": "recent_team"})
    )

    # --- Merge rush + recv ---
    merged = rush.join(
        recv,
        on=["season", "week", "player_id", "recent_team"],
        how="full",
        coalesce=True,
    ).with_columns([
        pl.col("carries").fill_null(0),
        pl.col("rushing_yards").fill_null(0),
        pl.col("rushing_tds").fill_null(0),
        pl.col("targets").fill_null(0),
        pl.col("receptions").fill_null(0),
        pl.col("receiving_yards").fill_null(0),
        pl.col("receiving_tds").fill_null(0),
    ])

    # Fantasy points PPR approximation
    merged = merged.with_columns(
        (
            pl.col("rushing_yards") * 0.1
            + pl.col("rushing_tds") * 6
            + pl.col("receptions") * 1.0
            + pl.col("receiving_yards") * 0.1
            + pl.col("receiving_tds") * 6
        ).alias("fantasy_points_ppr")
    )

    return merged


def backfill_weekly_stats():
    """Add derived stats for seasons missing from the weekly_stats file."""
    existing = pl.read_parquet(get_path("raw") / "weekly_stats.parquet")
    existing_seasons = set(existing["season"].unique().to_list())

    pbp = pl.read_parquet(get_path("raw") / "pbp.parquet")
    pbp_seasons = set(pbp["season"].unique().to_list())

    missing = sorted(pbp_seasons - existing_seasons)
    if not missing:
        print("No missing seasons to backfill.")
        return existing

    print(f"Deriving weekly stats from PBP for: {missing}")
    derived = derive_weekly_stats_from_pbp(missing)
    print(f"  Derived: {derived.shape[0]:,} rows")

    combined = pl.concat([existing, derived], how="diagonal_relaxed")
    path = get_path("raw") / "weekly_stats.parquet"
    combined.write_parquet(path)
    print(f"  Combined weekly stats: {combined.shape[0]:,} rows -> {path}")
    return combined
