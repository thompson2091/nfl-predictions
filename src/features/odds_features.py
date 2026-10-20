"""Build player-level sportsbook odds features from cached TD prop data."""
import re
import polars as pl
from src.utils.paths import get_path


# Map full team names to NFL abbreviations used in our data
TEAM_ABBREV = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN",
    "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Los Angeles Rams": "LA", "Los Angeles Chargers": "LAC",
    "Las Vegas Raiders": "LV", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE",
    "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT", "Seattle Seahawks": "SEA",
    "San Francisco 49ers": "SF", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}


def _normalize_name(name: str) -> str:
    """Normalize for matching: lowercase, strip suffixes."""
    name = name.lower().strip()
    # "Michael Thomas (NO)": a team in brackets. See odds_history._norm_expr.
    name = re.sub(r"\s+", " ", re.sub(r"\s*\([a-z]{2,10}\)", "", name))
    for suffix in [" jr.", " sr.", " ii", " iii", " iv", " jr", " sr"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    # Also strip periods from initials (A.J. -> aj)
    name = name.replace(".", "")
    return name


def build_odds_features(schedules: pl.DataFrame) -> pl.DataFrame:
    """Build player-level odds features by matching cached odds to games.

    Returns DataFrame with columns:
        game_id, player_name_norm, sbook_first_td_implied, sbook_anytime_td_implied,
        sbook_first_td_rank, sbook_anytime_td_rank
    """
    odds_path = get_path("raw") / "player_td_odds.parquet"
    if not odds_path.exists():
        return pl.DataFrame()

    odds = pl.read_parquet(odds_path)
    if odds.shape[0] == 0:
        return pl.DataFrame()

    # Map full team names to abbreviations
    odds = odds.with_columns([
        pl.col("odds_home_team").replace_strict(TEAM_ABBREV, default=None).alias("home_abbr"),
        pl.col("odds_away_team").replace_strict(TEAM_ABBREV, default=None).alias("away_abbr"),
    ])

    # Parse commence_time to get approximate season/week for matching
    odds = odds.with_columns(
        pl.col("commence_time").str.to_datetime("%Y-%m-%dT%H:%M:%SZ", time_zone="UTC")
        .alias("commence_dt")
    )

    # Join odds to schedule games via (home_team, away_team, commence_time proximity)
    # Schedules have game_id, home_team, away_team, gameday
    sched = schedules.select([
        "game_id", "home_team", "away_team", "gameday", "season", "week",
    ]).with_columns(
        pl.col("gameday").cast(pl.Date).alias("gameday_dt")
    )

    # Join on team abbreviations
    merged = odds.join(
        sched,
        left_on=["home_abbr", "away_abbr"],
        right_on=["home_team", "away_team"],
        how="inner",
    )

    # Filter to games where commence_time is close to gameday (within 2 days)
    merged = merged.with_columns(
        pl.col("commence_dt").dt.date().alias("odds_date")
    )
    merged = merged.filter(
        (pl.col("odds_date").cast(pl.Date) - pl.col("gameday_dt")).dt.total_days().abs() <= 2
    )

    if merged.shape[0] == 0:
        return pl.DataFrame()

    # Normalize player names for matching
    merged = merged.with_columns(
        pl.col("odds_player_name").map_elements(_normalize_name, return_dtype=pl.Utf8)
        .alias("player_name_norm")
    )

    # Compute within-game rank for each market
    result = merged.select([
        "game_id", "player_name_norm",
        "first_td_implied", "anytime_td_implied",
    ]).with_columns([
        pl.col("first_td_implied").fill_null(0.0).alias("sbook_first_td_implied"),
        pl.col("anytime_td_implied").fill_null(0.0).alias("sbook_anytime_td_implied"),
    ]).with_columns([
        pl.col("sbook_first_td_implied")
        .rank(descending=True, method="ordinal")
        .over("game_id").alias("sbook_first_td_rank"),
        pl.col("sbook_anytime_td_implied")
        .rank(descending=True, method="ordinal")
        .over("game_id").alias("sbook_anytime_td_rank"),
    ]).select([
        "game_id", "player_name_norm",
        "sbook_first_td_implied", "sbook_anytime_td_implied",
        "sbook_first_td_rank", "sbook_anytime_td_rank",
    ]).unique(subset=["game_id", "player_name_norm"])

    return result
