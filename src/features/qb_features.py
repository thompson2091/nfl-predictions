"""QB scoring features: rush TD rate, scramble rate — attached to all team candidates."""
import polars as pl
from src.utils.config import get_config


def build_qb_features(pbp: pl.DataFrame) -> pl.DataFrame:
    """Per-team QB usage features (contextual for all candidates). Shift(1)."""
    cfg = get_config()
    medium = cfg["rolling_windows"]["medium"]

    plays = pbp.filter(pl.col("posteam").is_not_null())

    # Per-game team stats
    team_game = (
        plays.group_by(["game_id", "season", "week", "posteam"])
        .agg([
            pl.col("touchdown").sum().alias("team_tds"),
            pl.col("rush_attempt").sum().alias("team_rush_att"),
            pl.len().alias("team_plays"),
        ])
        .rename({"posteam": "team"})
    )

    # QB rushing TDs per game
    qb_rush_tds = (
        plays.filter(
            (pl.col("rusher_player_id").is_not_null())
            & (pl.col("rush_touchdown") == 1)
            & (pl.col("qb_scramble") == 1)
        )
        .group_by(["game_id", "season", "week", "posteam"])
        .agg(pl.len().alias("qb_rush_tds"))
        .rename({"posteam": "team"})
    )

    # QB scrambles and designed runs
    qb_runs = (
        plays.filter(
            (pl.col("rush_attempt") == 1)
            & (pl.col("qb_scramble") == 1)
        )
        .group_by(["game_id", "season", "week", "posteam"])
        .agg(pl.len().alias("qb_scrambles"))
        .rename({"posteam": "team"})
    )

    # Merge
    qb = team_game.join(qb_rush_tds, on=["game_id", "season", "week", "team"], how="left")
    qb = qb.join(qb_runs, on=["game_id", "season", "week", "team"], how="left")
    qb = qb.with_columns([
        pl.col("qb_rush_tds").fill_null(0),
        pl.col("qb_scrambles").fill_null(0),
    ]).with_columns([
        (pl.col("qb_rush_tds") / pl.col("team_tds").cast(pl.Float64).clip(lower_bound=1))
        .alias("qb_rush_td_rate"),
        (pl.col("qb_scrambles") / pl.col("team_rush_att").cast(pl.Float64).clip(lower_bound=1))
        .alias("qb_scramble_rate"),
    ])

    qb = qb.sort(["team", "season", "week"])

    # Rolling with shift(1)
    rolling_exprs = []
    for col in ["qb_rush_td_rate", "qb_scramble_rate"]:
        shifted = pl.col(col).shift(1)
        rolling_exprs.extend([
            shifted.rolling_mean(medium, min_samples=3).over("team").alias(f"team_{col}_avg_{medium}g"),
            (shifted.cum_sum().over("team") / shifted.cum_count().over("team")).alias(f"team_{col}_szn_avg"),
        ])

    result = (
        qb.with_columns(rolling_exprs)
        .select(["game_id", "season", "week", "team"]
                + [e.meta.output_name() for e in rolling_exprs])
    )

    return result
