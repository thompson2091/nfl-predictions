"""Coach tendency features: TD tendencies and play-calling style by coach."""
import polars as pl
from src.utils.config import get_config
from src.utils.paths import get_path


def build_coach_features(schedules: pl.DataFrame, pbp: pl.DataFrame,
                         target_type: str = None) -> pl.DataFrame:
    """Per-coach historical tendencies. Shift(1) rolling across seasons."""
    cfg = get_config()
    if target_type is None:
        target_type = cfg["target"]["type"]
    medium = cfg["rolling_windows"]["medium"]

    tds = pl.read_parquet(get_path("processed", target_type) / f"tds_{target_type}.parquet")

    # Get coach assignments per game
    games = schedules.select([
        "game_id", "season", "week",
        "home_team", "away_team", "home_coach", "away_coach",
    ]).unique(subset=["game_id"])

    # Home coach rows
    home = games.select([
        pl.col("game_id"), pl.col("season"), pl.col("week"),
        pl.col("home_team").alias("team"),
        pl.col("home_coach").alias("coach"),
    ])
    away = games.select([
        pl.col("game_id"), pl.col("season"), pl.col("week"),
        pl.col("away_team").alias("team"),
        pl.col("away_coach").alias("coach"),
    ])
    coach_games = pl.concat([home, away], how="diagonal_relaxed")

    # Join TD info
    ftd = tds.select(["game_id", "td_team", "td_type"])
    # For anytime_td, aggregate to one row per game per team
    ftd = ftd.group_by(["game_id", "td_team"]).agg([
        (pl.col("td_type") == "rush").any().alias("had_rush_td"),
        (pl.col("td_type") == "pass").any().alias("had_pass_td"),
    ])

    coach_games = coach_games.join(ftd, left_on=["game_id", "team"],
                                   right_on=["game_id", "td_team"], how="left")

    # Did this coach's team score a TD?
    coach_games = coach_games.with_columns([
        pl.col("had_rush_td").is_not_null().alias("team_scored"),
    ])

    # TD was rush/pass
    coach_games = coach_games.with_columns([
        pl.col("had_rush_td").fill_null(False)
        .cast(pl.Float64).alias("coach_target_td_rush"),
        pl.col("had_pass_td").fill_null(False)
        .cast(pl.Float64).alias("coach_target_td_pass"),
    ]).drop(["had_rush_td", "had_pass_td"])

    # --- Opening drive TD rate from PBP ---
    d1 = pbp.filter(
        (pl.col("fixed_drive") == 1) & pl.col("posteam").is_not_null()
    )
    od_td = (
        d1.group_by(["game_id", "posteam"])
        .agg(pl.col("touchdown").sum().clip(upper_bound=1).alias("od_td_flag"))
        .rename({"posteam": "team"})
    )

    coach_games = coach_games.join(od_td, on=["game_id", "team"], how="left")
    coach_games = coach_games.with_columns(pl.col("od_td_flag").fill_null(0.0))

    # --- Run rate on first 2 drives (scripted plays) ---
    early_drives = pbp.filter(
        pl.col("fixed_drive").is_in([1, 2])
        & pl.col("posteam").is_not_null()
        & pl.col("play_type").is_in(["run", "pass"])
    )
    early_run = (
        early_drives.group_by(["game_id", "posteam"])
        .agg([
            (pl.col("play_type") == "run").mean().alias("run_rate_early"),
        ])
        .rename({"posteam": "team"})
    )

    coach_games = coach_games.join(early_run, on=["game_id", "team"], how="left")
    coach_games = coach_games.with_columns(pl.col("run_rate_early").fill_null(0.5))

    # Sort by coach and time (rolling by coach across seasons)
    coach_games = coach_games.filter(pl.col("coach").is_not_null())
    coach_games = coach_games.sort(["coach", "season", "week"])

    # Rolling features by COACH (not team) with shift(1)
    rolling_exprs = []
    for col, name in [
        ("coach_target_td_rush", "coach_target_td_rush_rate"),
        ("coach_target_td_pass", "coach_target_td_pass_rate"),
        ("od_td_flag", "coach_opening_drive_td_rate"),
        ("run_rate_early", "coach_run_rate_early"),
    ]:
        shifted = pl.col(col).cast(pl.Float64).shift(1)
        rolling_exprs.extend([
            shifted.rolling_mean(medium, min_samples=3).over("coach").alias(f"{name}_avg_{medium}g"),
            (shifted.cum_sum().over("coach") / shifted.cum_count().over("coach")).alias(f"{name}_szn_avg"),
        ])

    result = (
        coach_games.with_columns(rolling_exprs)
        .select(["season", "week", "team"]
                + [e.meta.output_name() for e in rolling_exprs])
    )

    return result
