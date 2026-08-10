"""Offensive coordinator tendency features: play-calling style by OC across teams."""
import polars as pl
from src.utils.config import get_config
from src.utils.paths import get_path


def build_oc_features(schedules: pl.DataFrame, pbp: pl.DataFrame,
                      target_type: str = None) -> pl.DataFrame:
    """Per-OC historical tendencies. Shift(1) rolling across seasons."""
    cfg = get_config()
    if target_type is None:
        target_type = cfg["target"]["type"]
    medium = cfg["rolling_windows"]["medium"]

    # --- Load OC mapping ---
    oc_path = get_path("raw") / "oc_mapping.csv"
    oc_map = pl.read_csv(oc_path)

    # --- Build game-level OC assignments ---
    games = schedules.select([
        "game_id", "season", "week", "home_team", "away_team",
    ]).unique(subset=["game_id"])

    home = games.select([
        pl.col("game_id"), pl.col("season"), pl.col("week"),
        pl.col("home_team").alias("team"),
    ])
    away = games.select([
        pl.col("game_id"), pl.col("season"), pl.col("week"),
        pl.col("away_team").alias("team"),
    ])
    oc_games = pl.concat([home, away], how="diagonal_relaxed")

    # Join OC name via season + team
    oc_games = oc_games.join(oc_map, on=["season", "team"], how="left")
    oc_games = oc_games.filter(pl.col("oc_name").is_not_null())

    # --- Compute per-game stats from PBP ---

    # 1. Rush TD rate: fraction of TDs that are rush TDs
    td_plays = pbp.filter(pl.col("touchdown") == 1)
    td_type_agg = (
        td_plays.group_by(["game_id", "posteam"])
        .agg([
            (pl.col("play_type") == "run").sum().alias("rush_tds"),
            (pl.col("play_type") == "pass").sum().alias("pass_tds"),
        ])
        .with_columns(
            (pl.col("rush_tds") / (pl.col("rush_tds") + pl.col("pass_tds")))
            .alias("rush_td_rate")
        )
        .rename({"posteam": "team"})
        .select(["game_id", "team", "rush_td_rate"])
    )

    # 2. Run rate: overall run vs pass rate
    rp_plays = pbp.filter(
        pl.col("play_type").is_in(["run", "pass"])
        & pl.col("posteam").is_not_null()
    )
    run_rate_agg = (
        rp_plays.group_by(["game_id", "posteam"])
        .agg((pl.col("play_type") == "run").mean().alias("run_rate"))
        .rename({"posteam": "team"})
    )

    # 3. Red zone TD conversion rate
    rz_plays = pbp.filter(
        (pl.col("yardline_100") <= 20)
        & pl.col("posteam").is_not_null()
        & pl.col("play_type").is_in(["run", "pass"])
    )
    rz_td_agg = (
        rz_plays.group_by(["game_id", "posteam"])
        .agg(pl.col("touchdown").mean().alias("rz_td_rate"))
        .rename({"posteam": "team"})
    )

    # 4. Pass rate on first 2 drives (scripted plays)
    early_drives = pbp.filter(
        pl.col("fixed_drive").is_in([1, 2])
        & pl.col("posteam").is_not_null()
        & pl.col("play_type").is_in(["run", "pass"])
    )
    early_pass_agg = (
        early_drives.group_by(["game_id", "posteam"])
        .agg((pl.col("play_type") == "pass").mean().alias("pass_rate_early"))
        .rename({"posteam": "team"})
    )

    # --- Join game stats to OC games ---
    oc_games = oc_games.join(td_type_agg, on=["game_id", "team"], how="left")
    oc_games = oc_games.join(run_rate_agg, on=["game_id", "team"], how="left")
    oc_games = oc_games.join(rz_td_agg, on=["game_id", "team"], how="left")
    oc_games = oc_games.join(early_pass_agg, on=["game_id", "team"], how="left")

    # Fill nulls (games with no TDs, no RZ plays, etc.)
    oc_games = oc_games.with_columns([
        pl.col("rush_td_rate").fill_null(0.5),
        pl.col("run_rate").fill_null(0.5),
        pl.col("rz_td_rate").fill_null(0.0),
        pl.col("pass_rate_early").fill_null(0.5),
    ])

    # Sort by OC and time (rolling by OC across seasons/teams)
    oc_games = oc_games.sort(["oc_name", "season", "week"])

    # --- Rolling features by OC (not team) with shift(1) ---
    rolling_exprs = []
    for col, name in [
        ("rush_td_rate", "oc_rush_td_rate"),
        ("run_rate", "oc_run_rate"),
        ("rz_td_rate", "oc_rz_td_rate"),
        ("pass_rate_early", "oc_pass_rate_early"),
    ]:
        shifted = pl.col(col).cast(pl.Float64).shift(1)
        rolling_exprs.extend([
            shifted.rolling_mean(medium, min_samples=3).over("oc_name").alias(f"{name}_avg_{medium}g"),
            (shifted.cum_sum().over("oc_name") / shifted.cum_count().over("oc_name")).alias(f"{name}_szn_avg"),
        ])

    result = (
        oc_games.with_columns(rolling_exprs)
        .select(["season", "week", "team"]
                + [e.meta.output_name() for e in rolling_exprs])
    )

    return result
