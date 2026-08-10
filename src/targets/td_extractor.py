"""Parameterized TD extraction: first_td, anytime_td."""
import polars as pl
from src.utils.config import get_config
from src.utils.paths import get_path


def extract_tds(target_type: str = None) -> pl.DataFrame:
    """Extract TDs by type.

    Args:
        target_type: 'first_td' or 'anytime_td'. Reads from config if None.

    Returns:
        DataFrame with: game_id, season, week, td_player_id, td_player_name,
        td_team, td_type, position, is_offensive_td
    """
    cfg = get_config()
    if target_type is None:
        target_type = cfg["target"]["type"]
    offensive_positions = cfg["positions"]["offensive"]

    pbp = pl.read_parquet(get_path("raw") / "pbp.parquet")
    rosters = pl.read_parquet(get_path("raw") / "rosters.parquet")

    # Filter to touchdown plays with a scorer
    tds = pbp.filter(
        (pl.col("touchdown") == 1)
        & pl.col("td_player_id").is_not_null()
        & (pl.col("td_player_id") != "")
    ).select([
        "game_id", "season", "week", "play_id",
        "game_seconds_remaining",
        "td_player_id", "td_player_name", "td_team",
        "posteam", "defteam",
        "rush_touchdown", "pass_touchdown",
        "return_touchdown",
    ])

    if target_type == "first_td":
        result = _extract_first_td(tds)
    elif target_type == "anytime_td":
        result = _extract_anytime_td(tds)
    else:
        raise ValueError(f"Unknown target_type: {target_type}")

    # Classify TD type
    result = result.with_columns(
        pl.when(pl.col("rush_touchdown") == 1).then(pl.lit("rush"))
        .when(pl.col("pass_touchdown") == 1).then(pl.lit("pass"))
        .when(pl.col("return_touchdown") == 1).then(pl.lit("return"))
        .otherwise(pl.lit("other"))
        .alias("td_type")
    )

    # Look up scorer's position from roster
    roster_positions = (
        rosters.select(["season", "player_id", "position"])
        .unique(subset=["season", "player_id"], keep="last")
    )

    result = result.join(
        roster_positions,
        left_on=["season", "td_player_id"],
        right_on=["season", "player_id"],
        how="left",
    )

    result = result.with_columns(
        pl.col("position").is_in(offensive_positions)
        .fill_null(False)
        .alias("is_offensive_td")
    )

    path = get_path("processed", target_type) / f"tds_{target_type}.parquet"
    result.write_parquet(path)

    # Also write to unscoped processed dir for backward compat (score_first_features)
    if target_type == "first_td":
        result.write_parquet(get_path("processed") / "first_tds.parquet")

    n_games = pbp.select("game_id").n_unique()
    n_offensive = result.filter(pl.col("is_offensive_td")).shape[0]
    n_defst = result.filter(~pl.col("is_offensive_td")).shape[0]
    print(f"TDs ({target_type}): {result.shape[0]:,} rows -> {path}")
    print(f"  Games in PBP: {n_games}")
    print(f"  Offensive: {n_offensive}, DEF/ST: {n_defst}")
    print(f"  TD type breakdown: {result.group_by('td_type').len().sort('len', descending=True)}")

    return result


def _extract_first_td(tds: pl.DataFrame) -> pl.DataFrame:
    """First TD per game: max game_seconds_remaining, tiebreaker min play_id."""
    return (
        tds
        .sort(["game_id", "game_seconds_remaining", "play_id"],
              descending=[False, True, False])
        .group_by("game_id")
        .first()
    )


def _extract_anytime_td(tds: pl.DataFrame) -> pl.DataFrame:
    """All unique TD scorers per game (one row per player per game)."""
    return (
        tds
        .sort(["game_id", "game_seconds_remaining", "play_id"],
              descending=[False, True, False])
        .unique(subset=["game_id", "td_player_id"], keep="first")
    )
