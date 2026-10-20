import polars as pl

# Franchise relocations / rebrandings
TEAM_NORMALIZE = {
    "OAK": "LV",
    "SD": "LAC",
    "STL": "LA",
    "LAR": "LA",  # sometimes coded as LAR
    # The 2015 roster feed's own codes. Unmapped, the rosters inner join gave
    # ARI, BAL, CLE, HOU and LA no player candidates at all that season.
    "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU", "SL": "LA",
}


def normalize_team_col(df: pl.DataFrame, col: str) -> pl.DataFrame:
    return df.with_columns(
        pl.col(col).replace(TEAM_NORMALIZE).alias(col)
    )


def normalize_teams(df: pl.DataFrame, cols: list[str] | None = None) -> pl.DataFrame:
    if cols is None:
        cols = [c for c in df.columns if "team" in c.lower()]
    for col in cols:
        df = normalize_team_col(df, col)
    return df
