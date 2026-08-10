"""Situational features derived from existing data (rosters, schedules, depth charts, weekly stats)."""
import polars as pl


def build_situational_features(
    rosters: pl.DataFrame,
    schedules: pl.DataFrame,
    depth_charts: pl.DataFrame,
    weekly_stats: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Build player-level and game-level situational features.

    Returns:
        player_feats: per player-season-week (is_new_team, is_role_change,
                      weeks_since_last_game, is_revenge_game, career_seasons)
        game_feats: per game_id-team (rest_advantage, is_post_bye, is_season_opener)
    """
    player_feats = _build_player_situational(rosters, depth_charts, weekly_stats, schedules)
    game_feats = _build_game_situational(schedules)
    return player_feats, game_feats


def _build_player_situational(
    rosters: pl.DataFrame,
    depth_charts: pl.DataFrame,
    weekly_stats: pl.DataFrame,
    schedules: pl.DataFrame,
) -> pl.DataFrame:
    """Player-level situational features."""

    # --- is_new_team: player changed teams since last season ---
    # Get each player's team per season (last roster entry)
    player_teams = (
        rosters
        .filter(pl.col("player_id").is_not_null())
        .select(["player_id", "season", "team"])
        .unique(subset=["player_id", "season"], keep="last")
        .sort(["player_id", "season"])
    )

    player_teams = player_teams.with_columns(
        pl.col("team").shift(1).over("player_id").alias("prev_team"),
        pl.col("season").shift(1).over("player_id").alias("prev_season"),
    )

    # Only flag if prev_season is exactly season-1 (not a gap)
    player_teams = player_teams.with_columns(
        pl.when(
            (pl.col("prev_season") == pl.col("season") - 1)
            & (pl.col("team") != pl.col("prev_team"))
        )
        .then(pl.lit(1))
        .otherwise(pl.lit(0))
        .cast(pl.Int8)
        .alias("is_new_team")
    )

    new_team = player_teams.select(["player_id", "season", "is_new_team"])

    # --- is_revenge_game: facing former team from last season ---
    # Build game-level opponent mapping per player
    # Get schedule with both sides
    home_games = schedules.select([
        "game_id", "season", "week",
        pl.col("home_team").alias("team"),
        pl.col("away_team").alias("opponent"),
    ])
    away_games = schedules.select([
        "game_id", "season", "week",
        pl.col("away_team").alias("team"),
        pl.col("home_team").alias("opponent"),
    ])
    game_teams = pl.concat([home_games, away_games], how="diagonal_relaxed")

    # Join player's current team to get opponent per week
    revenge = (
        player_teams
        .select(["player_id", "season", "team", "prev_team"])
        .join(
            game_teams.select(["season", "week", "team", "opponent"]),
            on=["season", "team"],
            how="inner",
        )
    )

    revenge = revenge.with_columns(
        pl.when(
            pl.col("prev_team").is_not_null()
            & (pl.col("opponent") == pl.col("prev_team"))
        )
        .then(pl.lit(1))
        .otherwise(pl.lit(0))
        .cast(pl.Int8)
        .alias("is_revenge_game")
    ).select(["player_id", "season", "week", "is_revenge_game"])

    # --- career_seasons: number of seasons in rosters ---
    career = (
        rosters
        .filter(pl.col("player_id").is_not_null())
        .select(["player_id", "season"])
        .unique()
        .sort(["player_id", "season"])
    )
    career = career.with_columns(
        pl.col("season")
        .cum_count()
        .over("player_id")
        .cast(pl.Int64)
        .alias("career_seasons")
    )

    # --- weeks_since_last_game: gap since last appearance in weekly_stats ---
    appearances = (
        weekly_stats
        .filter(pl.col("player_id").is_not_null())
        .select(["player_id", "season", "week"])
        .unique()
        .sort(["player_id", "season", "week"])
    )

    # Create a combined ordering key: season * 100 + week
    appearances = appearances.with_columns(
        (pl.col("season") * 100 + pl.col("week")).alias("_ord")
    )
    appearances = appearances.with_columns(
        pl.col("_ord").shift(1).over("player_id").alias("_prev_ord")
    )

    # Compute gap: current_week - prev_week (within season or cross-season)
    # For cross-season: assume ~22 weeks per season
    appearances = appearances.with_columns(
        pl.when(pl.col("_prev_ord").is_not_null())
        .then(
            pl.when(pl.col("_ord") // 100 == pl.col("_prev_ord") // 100)
            .then(pl.col("_ord") % 100 - pl.col("_prev_ord") % 100)
            .otherwise(
                # Cross-season gap: weeks remaining in prev season + current week
                (22 - pl.col("_prev_ord") % 100) + pl.col("_ord") % 100
            )
        )
        .otherwise(pl.lit(None))
        .cast(pl.Int64)
        .alias("weeks_since_last_game")
    )

    weeks_gap = appearances.select(["player_id", "season", "week", "weeks_since_last_game"])

    # --- is_role_change: went from backup to starter or vice versa across seasons ---
    if not depth_charts.is_empty() and "depth_team" in depth_charts.columns:
        dc = (
            depth_charts
            .filter(pl.col("gsis_id").is_not_null())
            .select([
                pl.col("gsis_id").alias("player_id"),
                pl.col("season").cast(pl.Int64),
                pl.col("depth_team").cast(pl.Utf8),
            ])
        )
        # Determine if starter (depth_team == "1") per season
        dc_season = (
            dc.with_columns(
                (pl.col("depth_team").is_in(["1", "1.0"])).cast(pl.Int8).alias("_is_starter")
            )
            .group_by(["player_id", "season"])
            .agg(pl.col("_is_starter").max().alias("was_starter"))
            .sort(["player_id", "season"])
        )
        dc_season = dc_season.with_columns(
            pl.col("was_starter").shift(1).over("player_id").alias("prev_was_starter"),
            pl.col("season").shift(1).over("player_id").alias("_prev_season"),
        )
        dc_season = dc_season.with_columns(
            pl.when(
                (pl.col("_prev_season") == pl.col("season") - 1)
                & pl.col("prev_was_starter").is_not_null()
                & (pl.col("was_starter") != pl.col("prev_was_starter"))
            )
            .then(pl.lit(1))
            .otherwise(pl.lit(0))
            .cast(pl.Int8)
            .alias("is_role_change")
        )
        role_change = dc_season.select(["player_id", "season", "is_role_change"])
    else:
        role_change = pl.DataFrame(schema={
            "player_id": pl.Utf8, "season": pl.Int64, "is_role_change": pl.Int8,
        })

    # --- Assemble player features ---
    # Start from revenge (has player_id, season, week)
    result = revenge.clone()

    # Join is_new_team (season-level → broadcast to all weeks)
    result = result.join(new_team, on=["player_id", "season"], how="left")

    # Join career_seasons (season-level)
    result = result.join(
        career.select(["player_id", "season", "career_seasons"]),
        on=["player_id", "season"],
        how="left",
    )

    # Join weeks_since_last_game
    result = result.join(weeks_gap, on=["player_id", "season", "week"], how="left")

    # Join is_role_change (season-level)
    if not role_change.is_empty():
        result = result.join(role_change, on=["player_id", "season"], how="left")
    else:
        result = result.with_columns(pl.lit(0).cast(pl.Int8).alias("is_role_change"))

    # Fill nulls
    result = result.with_columns([
        pl.col("is_new_team").fill_null(0),
        pl.col("is_revenge_game").fill_null(0),
        pl.col("is_role_change").fill_null(0),
        pl.col("career_seasons").fill_null(1),
    ])

    return result.select([
        "player_id", "season", "week",
        "is_new_team", "is_revenge_game", "is_role_change",
        "weeks_since_last_game", "career_seasons",
    ])


def _build_game_situational(schedules: pl.DataFrame) -> pl.DataFrame:
    """Game-level situational features: rest_advantage, is_post_bye, is_season_opener."""
    # Build home/away rows
    home = schedules.select([
        "game_id", "season", "week",
        pl.col("home_team").alias("team"),
        pl.col("home_rest").alias("team_rest"),
        pl.col("away_rest").alias("opp_rest"),
    ])
    away = schedules.select([
        "game_id", "season", "week",
        pl.col("away_team").alias("team"),
        pl.col("away_rest").alias("team_rest"),
        pl.col("home_rest").alias("opp_rest"),
    ])
    games = pl.concat([home, away], how="diagonal_relaxed")

    games = games.with_columns([
        # rest_advantage: team rest minus opponent rest (positive = more rest)
        (pl.col("team_rest").fill_null(7) - pl.col("opp_rest").fill_null(7))
        .cast(pl.Int64)
        .alias("rest_advantage"),

        # is_post_bye: rest >= 13 days (typical bye = 13-14 day rest)
        (pl.col("team_rest").fill_null(7) >= 13)
        .cast(pl.Int8)
        .alias("is_post_bye"),

        # is_season_opener: week 1
        (pl.col("week") == 1)
        .cast(pl.Int8)
        .alias("is_season_opener"),
    ])

    return games.select([
        "game_id", "team",
        "rest_advantage", "is_post_bye", "is_season_opener",
    ])
