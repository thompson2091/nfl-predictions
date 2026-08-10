import polars as pl
from src.utils.config import get_config


def build_team_features(pbp: pl.DataFrame) -> pl.DataFrame:
    """Build per-team rolling stats from PBP. Shift(1) to prevent leakage."""
    cfg = get_config()
    short = cfg["rolling_windows"]["short"]
    medium = cfg["rolling_windows"]["medium"]

    # Aggregate PBP to game-team level
    game_team = (
        pbp.filter(pl.col("posteam").is_not_null())
        .group_by(["game_id", "season", "week", "posteam"])
        .agg([
            pl.col("touchdown").sum().alias("tds"),
            pl.col("rush_touchdown").sum().alias("rush_tds"),
            pl.col("pass_touchdown").sum().alias("pass_tds"),
            pl.col("epa").mean().alias("epa_per_play"),
            pl.len().alias("total_plays"),
            pl.col("rush_attempt").sum().alias("rush_attempts"),
            pl.col("pass_attempt").sum().alias("pass_attempts"),
            pl.col("posteam_score_post").max().alias("points_scored"),
        ])
    ).with_columns(
        (pl.col("rush_attempts") / pl.col("total_plays").cast(pl.Float64))
        .alias("run_rate")
    )

    game_team = game_team.sort(["posteam", "season", "week"])

    # Rolling features
    stat_cols = ["tds", "rush_tds", "pass_tds", "epa_per_play",
                 "points_scored", "run_rate"]

    rolling_exprs = []
    for col in stat_cols:
        shifted = pl.col(col).shift(1)
        for window, label in [(short, f"{short}g"), (medium, f"{medium}g")]:
            rolling_exprs.append(
                shifted.rolling_mean(window, min_samples=3)
                .over("posteam").alias(f"team_{col}_avg_{label}")
            )
        rolling_exprs.append(
            (shifted.cum_sum().over("posteam") / shifted.cum_count().over("posteam")).alias(f"team_{col}_szn_avg")
        )

    result = (
        game_team
        .with_columns(rolling_exprs)
        .select(
            ["game_id", "season", "week", "posteam"]
            + [e.meta.output_name() for e in rolling_exprs]
        )
        .rename({"posteam": "team"})
    )

    return result


def build_opponent_features(pbp: pl.DataFrame) -> pl.DataFrame:
    """Build per-team defensive stats (what they allow). Shift(1)."""
    cfg = get_config()
    short = cfg["rolling_windows"]["short"]
    medium = cfg["rolling_windows"]["medium"]

    # Aggregate what the defense allows
    game_def = (
        pbp.filter(pl.col("defteam").is_not_null())
        .group_by(["game_id", "season", "week", "defteam"])
        .agg([
            pl.col("touchdown").sum().alias("tds_allowed"),
            pl.col("rush_touchdown").sum().alias("rush_tds_allowed"),
            pl.col("pass_touchdown").sum().alias("pass_tds_allowed"),
            pl.col("epa").mean().alias("epa_allowed_per_play"),
        ])
    ).sort(["defteam", "season", "week"])

    stat_cols = ["tds_allowed", "rush_tds_allowed", "pass_tds_allowed",
                 "epa_allowed_per_play"]

    rolling_exprs = []
    for col in stat_cols:
        shifted = pl.col(col).shift(1)
        for window, label in [(short, f"{short}g"), (medium, f"{medium}g")]:
            rolling_exprs.append(
                shifted.rolling_mean(window, min_samples=3)
                .over("defteam").alias(f"opp_{col}_avg_{label}")
            )
        rolling_exprs.append(
            (shifted.cum_sum().over("defteam") / shifted.cum_count().over("defteam")).alias(f"opp_{col}_szn_avg")
        )

    result = (
        game_def
        .with_columns(rolling_exprs)
        .select(
            ["game_id", "season", "week", "defteam"]
            + [e.meta.output_name() for e in rolling_exprs]
        )
        .rename({"defteam": "opponent"})
    )

    return result
