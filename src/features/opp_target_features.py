"""Opponent target-allowed features: what position scores TDs against this defense."""
import polars as pl
from src.utils.config import get_config
from src.utils.paths import get_path


def build_opp_target_features(target_type: str = None) -> pl.DataFrame:
    """Per-opponent: target-allowed breakdown by position. Shift(1) rolling."""
    cfg = get_config()
    if target_type is None:
        target_type = cfg["target"]["type"]
    medium = cfg["rolling_windows"]["medium"]

    tds = pl.read_parquet(get_path("processed", target_type) / f"tds_{target_type}.parquet")
    schedules = pl.read_parquet(get_path("raw") / "schedules.parquet")

    games = schedules.select([
        "game_id", "season", "week", "home_team", "away_team",
    ]).unique(subset=["game_id"])

    ftd = tds.select([
        "game_id", "td_team", "td_type", "position",
    ])

    # The defense that allowed the TD = the OTHER team
    ftd = ftd.join(games, on="game_id", how="left")
    ftd = ftd.with_columns(
        pl.when(pl.col("td_team") == pl.col("home_team"))
        .then(pl.col("away_team"))
        .otherwise(pl.col("home_team"))
        .alias("defense_team")
    )

    # Position breakdown
    ftd = ftd.with_columns([
        (pl.col("position") == "RB").fill_null(False).cast(pl.Float64).alias("target_allowed_to_rb"),
        (pl.col("position") == "WR").fill_null(False).cast(pl.Float64).alias("target_allowed_to_wr"),
        (pl.col("position") == "TE").fill_null(False).cast(pl.Float64).alias("target_allowed_to_te"),
        (pl.col("position") == "QB").fill_null(False).cast(pl.Float64).alias("target_allowed_to_qb"),
        (pl.col("td_type") == "rush").fill_null(False).cast(pl.Float64).alias("target_allowed_rush"),
    ])

    stat_cols = ["target_allowed_to_rb", "target_allowed_to_wr", "target_allowed_to_te",
                 "target_allowed_to_qb", "target_allowed_rush"]

    # For anytime_td, aggregate per defense per game (sum then clip to max 1 per position)
    ftd_slim = ftd.select(["game_id", pl.col("defense_team").alias("opponent")] + stat_cols)
    ftd_slim = (
        ftd_slim
        .group_by(["game_id", "opponent"])
        .agg([pl.col(c).max().alias(c) for c in stat_cols])
    )

    # Build opponent rows for all games
    home_opp = games.select([
        pl.col("game_id"), pl.col("season"), pl.col("week"),
        pl.col("home_team").alias("opponent"),
    ])
    away_opp = games.select([
        pl.col("game_id"), pl.col("season"), pl.col("week"),
        pl.col("away_team").alias("opponent"),
    ])
    all_opp = pl.concat([home_opp, away_opp], how="diagonal_relaxed")

    opp_df = all_opp.join(ftd_slim, on=["game_id", "opponent"], how="left")

    for col in stat_cols:
        opp_df = opp_df.with_columns(pl.col(col).fill_null(0.0))

    opp_df = opp_df.sort(["opponent", "season", "week"])

    # Rolling features with shift(1)
    rolling_exprs = []
    for col in stat_cols:
        shifted = pl.col(col).shift(1)
        rolling_exprs.extend([
            shifted.rolling_mean(medium, min_samples=3).over("opponent").alias(f"opp_{col}_avg_{medium}g"),
            (shifted.cum_sum().over("opponent") / shifted.cum_count().over("opponent")).alias(f"opp_{col}_szn_avg"),
        ])

    result = (
        opp_df.with_columns(rolling_exprs)
        .select(["season", "week", "opponent"] + [e.meta.output_name() for e in rolling_exprs])
    )

    return result
