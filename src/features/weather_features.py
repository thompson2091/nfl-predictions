"""What the weather was forecast to be, hours before kickoff.

`temp` and `wind` ship in `schedules.parquet` and are excluded from the model,
correctly: they are recorded **at** kickoff, so a model trained on them learns
against information nobody has when a board goes up. That is not a precision
problem, it is a total break — the column is 100% null at predict time. See
`scripts/28_weather.py`.

A forecast issued the day before restores the signal honestly, and it is the
only remaining idea in this project that adds *information* rather than
rearranging what the model already sees. Measured over 34 games, a 24-hour
forecast misses kickoff temperature by 2.2F against a signal that varies by
17.6F — so it carries essentially all of the signal and none of the hindsight.

**Nulls indoors, not a constant.** A dome has no outdoor temperature, and every
way of supplying one is an invented number. Zero is worse than useless (a tree
splitting on `temp < 32` would catch every dome), and 70F is a guess: nflverse
records `temp` for exactly one dome game in eleven seasons, so there is nothing
to fit a dome constant *from*. So indoor games are null, and `is_dome` — already
a feature — is what tells the model those nulls mean "indoors" rather than
"unknown". XGBoost learns a direction for missing natively; that is the honest
place to leave this.

**One row per game.** Weather is a property of the fixture, not of a side, so
this joins on `game_id` alone rather than being duplicated across both teams.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

#: Where `scripts/28_weather.py --fetch` writes the archive.
WEATHER_PATH = (Path(__file__).resolve().parents[2]
                / "data" / "processed" / "weather.parquet")

COLUMNS = ["wx_temp_f", "wx_wind_mph", "wx_precip_mm", "wx_is_forecast"]


def load_archive(path: Path | None = None) -> pl.DataFrame | None:
    """The fetched forecasts, or None when nobody has fetched them."""
    p = Path(path) if path else WEATHER_PATH
    if not p.exists():
        return None
    return pl.read_parquet(p)


def build_weather_features(schedules: pl.DataFrame,
                           weather: pl.DataFrame | None = None
                           ) -> pl.DataFrame:
    """One row per game: the pre-kickoff forecast, null where there is none.

    Two kinds of null arrive here and they are not the same thing, which is why
    neither is filled:

      * **Indoors.** No outdoor weather exists. `is_dome` marks these.
      * **Not fetched yet.** An upcoming game outside the forecast horizon —
        Open-Meteo runs 16 days ahead, and Week 1 in August is further out than
        that. The column fills in as the week approaches.

    Filling either would make the model learn on a number that means "we do not
    know", and the two would become indistinguishable from each other.
    """
    games = schedules.select(["game_id"]).unique()
    if weather is None:
        weather = load_archive()
    if weather is None or weather.is_empty():
        return games.with_columns([
            pl.lit(None, dtype=pl.Float64).alias(c) for c in COLUMNS
        ])

    wx = (weather.select(["game_id"] + [c for c in COLUMNS
                                        if c in weather.columns])
          .unique(subset=["game_id"], keep="last"))
    out = games.join(wx, on="game_id", how="left")
    for c in COLUMNS:
        if c not in out.columns:
            out = out.with_columns(pl.lit(None, dtype=pl.Float64).alias(c))
    return out.with_columns([pl.col(c).cast(pl.Float64) for c in COLUMNS])


def coverage(schedules: pl.DataFrame,
             weather: pl.DataFrame | None = None) -> dict:
    """How much of the schedule the archive actually covers, per season.

    Reported rather than assumed: a feature that is 100% null for the season
    being served is not a feature, and the difference between "indoors" and
    "not fetched" is the whole reason to look.
    """
    if weather is None:
        weather = load_archive()
    have = set() if weather is None else set(weather["game_id"].to_list())
    rows = []
    for season, chunk in schedules.group_by("season"):
        s = season[0] if isinstance(season, tuple) else season
        roof = chunk["roof"].fill_null("unknown").str.to_lowercase()
        indoor = int((roof.is_in(["dome", "closed"])).sum())
        outdoor = int(chunk.height - indoor)
        covered = sum(1 for g in chunk["game_id"] if g in have)
        rows.append({
            "season": int(s), "games": chunk.height,
            "indoor": indoor, "outdoor": outdoor, "covered": covered,
            "outdoor_covered": covered / outdoor if outdoor else None,
        })
    return {"seasons": sorted(rows, key=lambda r: r["season"]),
            "archive_games": len(have)}
