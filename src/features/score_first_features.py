"""Score-first tendency features: who scores first (home/favorite/team)."""
import polars as pl
from src.utils.config import get_config
from src.utils.paths import get_path


def build_score_first_features(schedules: pl.DataFrame) -> pl.DataFrame:
    """Per-team: rate of scoring first as home/favorite. Shift(1) rolling."""
    cfg = get_config()
    medium = cfg["rolling_windows"]["medium"]

    first_tds = pl.read_parquet(get_path("processed") / "first_tds.parquet")

    # Get game info
    games = schedules.select([
        "game_id", "season", "week", "home_team", "away_team", "spread_line",
    ]).unique(subset=["game_id"])

    # Which team scored first per game
    first_scorer = first_tds.select(["game_id", "td_team"]).unique(subset=["game_id"])

    games = games.join(first_scorer, on="game_id", how="left")

    # nflverse spread_line is POSITIVE when the home team is favored — its
    # correlation with home margin of victory is +0.44. This had the test the
    # wrong way round and so named the underdog as the favorite in every game
    # with a line, which inverted `team_fav_scored_first_rate_*`.
    games = games.with_columns([
        pl.when(pl.col("spread_line") > 0)
        .then(pl.col("home_team"))
        .when(pl.col("spread_line") < 0)
        .then(pl.col("away_team"))
        .otherwise(None)
        .alias("favorite_team"),
    ])

    # --- Home rows ---
    home = games.select([
        pl.col("game_id"), pl.col("season"), pl.col("week"),
        pl.col("home_team").alias("team"),
        (pl.col("td_team") == pl.col("home_team")).fill_null(False).cast(pl.Float64).alias("team_scored_first_flag"),
        (pl.col("td_team") == pl.col("home_team")).fill_null(False).cast(pl.Float64).alias("home_scored_first"),
        (pl.col("td_team") == pl.col("favorite_team")).fill_null(False).cast(pl.Float64).alias("fav_scored_first"),
    ])

    # --- Away rows ---
    away = games.select([
        pl.col("game_id"), pl.col("season"), pl.col("week"),
        pl.col("away_team").alias("team"),
        (pl.col("td_team") == pl.col("away_team")).fill_null(False).cast(pl.Float64).alias("team_scored_first_flag"),
        (pl.col("td_team") == pl.col("home_team")).fill_null(False).cast(pl.Float64).alias("home_scored_first"),
        (pl.col("td_team") == pl.col("favorite_team")).fill_null(False).cast(pl.Float64).alias("fav_scored_first"),
    ])

    team_df = pl.concat([home, away], how="diagonal_relaxed").sort(["team", "season", "week"])

    rolling_exprs = []
    for col in ["team_scored_first_flag", "home_scored_first", "fav_scored_first"]:
        shifted = pl.col(col).shift(1)
        rolling_exprs.extend([
            shifted.rolling_mean(medium, min_samples=3).over("team").alias(f"team_{col}_rate_{medium}g"),
            (shifted.cum_sum().over("team") / shifted.cum_count().over("team")).alias(f"team_{col}_rate_szn"),
        ])

    result = (
        team_df.with_columns(rolling_exprs)
        .select(["season", "week", "team"] + [e.meta.output_name() for e in rolling_exprs])
    )

    return result
