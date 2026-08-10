"""Derive weekly player stats from PBP for seasons missing from nflreadpy."""
import polars as pl
from src.utils.paths import get_path


def derive_weekly_stats_from_pbp(seasons: list[int]) -> pl.DataFrame:
    pbp = pl.read_parquet(get_path("raw") / "pbp.parquet")
    pbp = pbp.filter(pl.col("season").is_in(seasons))

    if pbp.shape[0] == 0:
        return pl.DataFrame()

    is_2pt = pl.col("two_point_conv_result") == "success"

    # --- Rushing stats per player/game ---
    rush = (
        pbp.filter(pl.col("rusher_player_id").is_not_null())
        .group_by(["season", "week", "rusher_player_id", "posteam"])
        .agg([
            pl.len().alias("carries"),
            pl.col("rushing_yards").sum().alias("rushing_yards"),
            pl.col("rush_touchdown").sum().alias("rushing_tds"),
            pl.col("first_down_rush").sum().alias("rushing_first_downs"),
            pl.col("epa").sum().alias("rushing_epa"),
            is_2pt.sum().alias("rushing_2pt_conversions"),
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
            pl.col("first_down_pass").sum().alias("receiving_first_downs"),
            pl.col("epa").sum().alias("receiving_epa"),
            pl.col("yards_after_catch").sum().alias("receiving_yards_after_catch"),
            pl.col("air_yards").sum().alias("receiving_air_yards"),
            is_2pt.sum().alias("receiving_2pt_conversions"),
        ])
        .rename({"receiver_player_id": "player_id", "posteam": "recent_team"})
    )

    # --- Merge rush + recv ---
    zero_fill = [
        "carries", "rushing_yards", "rushing_tds", "rushing_first_downs",
        "rushing_epa", "rushing_2pt_conversions",
        "targets", "receptions", "receiving_yards", "receiving_tds",
        "receiving_first_downs", "receiving_epa", "receiving_yards_after_catch",
        "receiving_air_yards", "receiving_2pt_conversions",
    ]
    merged = rush.join(
        recv,
        on=["season", "week", "player_id", "recent_team"],
        how="full",
        coalesce=True,
    ).with_columns([pl.col(c).fill_null(0) for c in zero_fill])

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

    # Usage shares. nfl_data_py supplies these directly; when we're deriving a
    # season it doesn't cover yet, they have to be rebuilt from PBP or the
    # player_target_share_* / wopr features go null at predict time.
    merged = merged.with_columns([
        pl.col("targets").sum().over(["season", "week", "recent_team"]).alias("_team_targets"),
        pl.col("receiving_air_yards").sum().over(["season", "week", "recent_team"]).alias("_team_air_yards"),
    ])
    merged = merged.with_columns([
        (pl.col("targets") / pl.col("_team_targets").cast(pl.Float64).clip(lower_bound=1))
        .alias("target_share"),
        (pl.col("receiving_air_yards") / pl.col("_team_air_yards").cast(pl.Float64).clip(lower_bound=1))
        .alias("air_yards_share"),
    ])
    # WOPR (Weighted Opportunity Rating), standard formulation.
    merged = merged.with_columns(
        (1.5 * pl.col("target_share") + 0.7 * pl.col("air_yards_share")).alias("wopr")
    ).drop(["_team_targets", "_team_air_yards"])

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

    # Match the existing file's key dtypes so downstream joins line up
    for key in ("season", "week"):
        if key in existing.columns and key in derived.columns:
            derived = derived.with_columns(pl.col(key).cast(existing.schema[key]))

    combined = pl.concat([existing, derived], how="diagonal_relaxed")
    path = get_path("raw") / "weekly_stats.parquet"
    combined.write_parquet(path)
    print(f"  Combined weekly stats: {combined.shape[0]:,} rows -> {path}")
    return combined
