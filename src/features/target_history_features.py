"""Target-specific features: player TD rate, team TD tendencies (parameterized by target type)."""
import polars as pl
from src.utils.config import get_config
from src.utils.paths import get_path


def build_player_target_history(target_type: str = None) -> pl.DataFrame:
    """Per-player historical target rate. Shift(1) to prevent leakage."""
    cfg = get_config()
    if target_type is None:
        target_type = cfg["target"]["type"]
    short = cfg["rolling_windows"]["short"]
    medium = cfg["rolling_windows"]["medium"]

    candidates = pl.read_parquet(get_path("processed", target_type) / "candidates.parquet")

    # For each player-game, did they achieve the target?
    player_games = (
        candidates
        .select(["game_id", "season", "week", "player_id", "target"])
        .sort(["player_id", "season", "week"])
    )

    # Rolling target rate with shift(1)
    shifted = pl.col("target").shift(1)
    rolling_exprs = [
        shifted.rolling_mean(short, min_samples=3).over("player_id").alias(f"player_target_rate_{short}g"),
        shifted.rolling_mean(medium, min_samples=3).over("player_id").alias(f"player_target_rate_{medium}g"),
        (shifted.cum_sum().over("player_id") / shifted.cum_count().over("player_id")).alias("player_target_rate_szn"),
        shifted.cum_sum().over("player_id").alias("player_target_count"),
    ]

    result = (
        player_games
        .with_columns(rolling_exprs)
        .select(["player_id", "season", "week"] + [e.meta.output_name() for e in rolling_exprs])
    )

    return result


def build_team_target_tendency(target_type: str = None) -> pl.DataFrame:
    """Per-team: what position tends to achieve the target? Shift(1)."""
    cfg = get_config()
    if target_type is None:
        target_type = cfg["target"]["type"]
    short = cfg["rolling_windows"]["short"]
    medium = cfg["rolling_windows"]["medium"]

    tds = pl.read_parquet(get_path("processed", target_type) / f"tds_{target_type}.parquet")

    # tds already has position from td_extractor join with rosters
    ftd = tds.with_columns([
        (pl.col("td_type") == "rush").cast(pl.Int8).alias("target_was_rush"),
        (pl.col("td_type") == "pass").cast(pl.Int8).alias("target_was_pass"),
        (~pl.col("is_offensive_td")).cast(pl.Int8).alias("target_was_defst"),
        (pl.col("position") == "RB").fill_null(False).cast(pl.Int8).alias("target_by_rb"),
        (pl.col("position") == "WR").fill_null(False).cast(pl.Int8).alias("target_by_wr"),
        (pl.col("position") == "TE").fill_null(False).cast(pl.Int8).alias("target_by_te"),
        (pl.col("position") == "QB").fill_null(False).cast(pl.Int8).alias("target_by_qb"),
    ])

    schedules = pl.read_parquet(get_path("raw") / "schedules.parquet")
    games = schedules.select(["game_id", "season", "week", "home_team", "away_team"]).unique(subset=["game_id"])

    td_cols = ["target_was_rush", "target_was_pass", "target_was_defst",
               "target_by_rb", "target_by_wr", "target_by_te", "target_by_qb"]

    # Exactly one row per (game_id, scoring team). Without this collapse the
    # joins below fan out and shift(1) lands on another row of the SAME game,
    # leaking the current game's result into its own "historical" rate.
    ftd_slim = (
        ftd.select(["game_id", "td_team"] + td_cols)
        .group_by(["game_id", "td_team"])
        .agg([pl.col(c).max().alias(c) for c in td_cols])
    )

    # One row per (game_id, team) for both participants...
    team_games = pl.concat([
        games.select(["game_id", "season", "week",
                      pl.col("home_team").alias("team")]),
        games.select(["game_id", "season", "week",
                      pl.col("away_team").alias("team")]),
    ])

    # ...joined to that team's OWN scoring row for the game (keyed on team, not
    # just game_id). A team that scored nothing simply has no match.
    team_ftd = team_games.join(
        ftd_slim, left_on=["game_id", "team"], right_on=["game_id", "td_team"],
        how="left",
    )
    team_ftd = team_ftd.with_columns(
        [pl.col(c).fill_null(0).cast(pl.Int8) for c in td_cols]
        + [pl.max_horizontal([pl.col(c) for c in td_cols])
           .fill_null(0).cast(pl.Int8).alias("team_scored_target")]
    ).sort(["team", "season", "week"])

    n_rows, n_keys = team_ftd.height, team_ftd.select(["game_id", "team"]).unique().height
    if n_rows != n_keys:
        raise ValueError(
            f"team_target_tendency fanned out: {n_rows} rows for {n_keys} "
            f"(game_id, team) pairs. shift(1) would leak the current game."
        )

    # Rolling features with shift(1)
    rolling_exprs = []
    for col in td_cols + ["team_scored_target"]:
        shifted = pl.col(col).shift(1)
        rolling_exprs.extend([
            shifted.rolling_mean(medium, min_samples=3).over("team").alias(f"team_{col}_rate_{medium}g"),
            (shifted.cum_sum().over("team") / shifted.cum_count().over("team")).alias(f"team_{col}_rate_szn"),
        ])

    result = (
        team_ftd
        .with_columns(rolling_exprs)
        .select(["game_id", "season", "week", "team"] + [e.meta.output_name() for e in rolling_exprs])
    )

    return result
