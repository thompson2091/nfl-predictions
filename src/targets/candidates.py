import polars as pl
from src.utils.config import get_config
from src.utils.paths import get_path


def build_candidates(target_type: str = None) -> pl.DataFrame:
    cfg = get_config()
    if target_type is None:
        target_type = cfg["target"]["type"]
    positions = cfg["positions"]["offensive"]

    tds = pl.read_parquet(get_path("processed", target_type) / f"tds_{target_type}.parquet")
    rosters = pl.read_parquet(get_path("raw") / "rosters.parquet")
    schedules = pl.read_parquet(get_path("raw") / "schedules.parquet")

    # Get game-level info from schedules
    games = schedules.select([
        "game_id", "season", "week", "home_team", "away_team", "game_type",
    ]).unique(subset=["game_id"])

    # --- Offensive player candidates ---
    roster_slim = rosters.filter(
        pl.col("position").is_in(positions)
    ).select([
        "season", "week", "team", "player_id", "player_name", "position",
    ]).unique(subset=["season", "week", "team", "player_id"])

    # Home team players
    home = games.join(
        roster_slim,
        left_on=["season", "week", "home_team"],
        right_on=["season", "week", "team"],
        how="inner",
    ).with_columns(pl.lit(True).alias("is_home"))

    # Away team players
    away = games.join(
        roster_slim,
        left_on=["season", "week", "away_team"],
        right_on=["season", "week", "team"],
        how="inner",
    ).with_columns(pl.lit(False).alias("is_home"))

    offensive = pl.concat([home, away])
    offensive = offensive.with_columns(
        pl.when(pl.col("is_home"))
        .then(pl.col("home_team"))
        .otherwise(pl.col("away_team"))
        .alias("team")
    )

    # --- DEF/ST candidates: one per team per game ---
    defst_home = games.with_columns(
        pl.col("home_team").alias("team"),
        (pl.col("home_team") + "_DEFST").alias("player_id"),
        pl.lit("DEF/ST").alias("player_name"),
        pl.lit("DEFST").alias("position"),
        pl.lit(True).alias("is_home"),
    )
    defst_away = games.with_columns(
        pl.col("away_team").alias("team"),
        (pl.col("away_team") + "_DEFST").alias("player_id"),
        pl.lit("DEF/ST").alias("player_name"),
        pl.lit("DEFST").alias("position"),
        pl.lit(False).alias("is_home"),
    )
    defst = pl.concat([defst_home, defst_away])

    # Combine offensive + DEF/ST candidates
    candidates = pl.concat([offensive, defst], how="diagonal_relaxed")

    # --- Assign targets ---
    td_info = tds.select([
        "game_id", "td_player_id", "td_team", "is_offensive_td",
    ])

    if target_type == "first_td":
        # One target=1 per game (at most)
        candidates = candidates.join(td_info, on="game_id", how="left")
        candidates = candidates.with_columns(
            pl.when(
                pl.col("is_offensive_td").fill_null(False)
                & (pl.col("player_id") == pl.col("td_player_id"))
            ).then(1)
            .when(
                ~pl.col("is_offensive_td").fill_null(True)
                & (pl.col("position") == "DEFST")
                & (pl.col("team") == pl.col("td_team"))
            ).then(1)
            .otherwise(0)
            .cast(pl.Int8)
            .alias("target")
        ).drop(["td_player_id", "td_team", "is_offensive_td"])

    elif target_type == "anytime_td":
        # Multiple target=1 per game (any scorer)
        # For offensive: match player_id to any td_player_id in that game
        offensive_scorers = td_info.filter(
            pl.col("is_offensive_td")
        ).select(["game_id", "td_player_id"]).unique()

        defst_scorers = td_info.filter(
            ~pl.col("is_offensive_td")
        ).select(["game_id", "td_team"]).unique()

        # Mark offensive scorers
        candidates = candidates.with_columns(
            pl.struct(["game_id", "player_id"]).is_in(
                offensive_scorers.select([
                    pl.col("game_id"),
                    pl.col("td_player_id").alias("player_id"),
                ]).to_struct()
            ).alias("_off_scored")
        )

        # Mark DEF/ST scorers
        candidates = candidates.with_columns(
            (
                (pl.col("position") == "DEFST")
                & pl.struct(["game_id", "team"]).is_in(
                    defst_scorers.select([
                        pl.col("game_id"),
                        pl.col("td_team").alias("team"),
                    ]).to_struct()
                )
            ).alias("_defst_scored")
        )

        candidates = candidates.with_columns(
            (pl.col("_off_scored") | pl.col("_defst_scored"))
            .cast(pl.Int8)
            .alias("target")
        ).drop(["_off_scored", "_defst_scored"])

    # Deduplicate
    candidates = candidates.unique(subset=["game_id", "player_id"])

    path = get_path("processed", target_type) / "candidates.parquet"
    candidates.write_parquet(path)

    # Validation
    n_rows = candidates.shape[0]
    n_positive = candidates.filter(pl.col("target") == 1).shape[0]
    n_games = candidates.select("game_id").n_unique()
    n_defst_positive = candidates.filter(
        (pl.col("target") == 1) & (pl.col("position") == "DEFST")
    ).shape[0]
    pos_rate = n_positive / n_rows * 100 if n_rows > 0 else 0

    print(f"Candidates ({target_type}): {n_rows:,} rows, {n_games:,} games -> {path}")
    print(f"  Positive rate: {n_positive:,} / {n_rows:,} = {pos_rate:.2f}%")
    print(f"  Offensive TDs: {n_positive - n_defst_positive}")
    print(f"  DEF/ST TDs: {n_defst_positive}")

    if target_type == "first_td":
        targets_per_game = (
            candidates.filter(pl.col("target") == 1)
            .group_by("game_id").len()
            .filter(pl.col("len") > 1)
        )
        if targets_per_game.shape[0] > 0:
            print(f"  WARNING: {targets_per_game.shape[0]} games with >1 target=1")
        else:
            print("  Validation passed: at most 1 target=1 per game")

    return candidates
