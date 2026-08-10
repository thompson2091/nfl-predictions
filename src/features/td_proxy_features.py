"""TD proxy features: moneyline-implied win prob crossed with player usage."""
import polars as pl


def build_td_proxy_features(schedules: pl.DataFrame) -> pl.DataFrame:
    """Per-team-per-game moneyline-derived features. No rolling needed."""

    games = schedules.select([
        "game_id", "season", "week", "home_team", "away_team",
        "home_moneyline", "away_moneyline",
    ]).filter(pl.col("home_moneyline").is_not_null())

    def _ml_to_prob(col: str) -> pl.Expr:
        """Convert American moneyline to implied probability."""
        return (
            pl.when(pl.col(col) < 0)
            .then(-pl.col(col) / (-pl.col(col) + 100))
            .otherwise(100 / (pl.col(col) + 100))
        )

    # Home rows
    home = games.select([
        pl.col("game_id"), pl.col("season"), pl.col("week"),
        pl.col("home_team").alias("team"),
        _ml_to_prob("home_moneyline").alias("moneyline_implied_prob"),
    ])

    # Away rows
    away = games.select([
        pl.col("game_id"), pl.col("season"), pl.col("week"),
        pl.col("away_team").alias("team"),
        _ml_to_prob("away_moneyline").alias("moneyline_implied_prob"),
    ])

    result = pl.concat([home, away], how="diagonal_relaxed")

    return result
