"""Pre-kickoff weather, as it was forecast rather than as it turned out.

Phase 3g. `temp` and `wind` are excluded from the model because they are
measured at kickoff and are 100% null for a game that has not been played — a
total train/serve break, not a precision problem. So were `is_cold` and
`is_windy`, which derived from them with `.fill_null(False)` and therefore read
"not cold" for every upcoming game while 11-15% of training rows were cold.

This replaces all four with a 24-hour-ahead forecast, which is available when a
board goes up and misses kickoff temperature by 2.2F on average against a signal
that varies by 17.6F. `scripts/28_weather.py` fetches it and verifies the
stadium coordinates against the recorded kickoff temperatures.

Two decisions worth stating, because both are silent failure modes:

**Domes get the average, not zero.** `trainer.prepare_data` runs
`np.nan_to_num(x, nan=0.0)`, so a null temperature would reach the model as 0F —
the coldest reading in the data by a wide margin, and applied to exactly the
games where weather cannot matter. Indoor games and unmapped venues are filled
with the outdoor mean instead, which reads as "weather is not a factor", and
`is_dome` remains a feature so the model can still tell them apart. The mean is
computed from the data rather than written down, so it tracks the league's
scoring environment instead of a number someone typed once.

**The derived flags are computed from the forecast**, not from the observation,
so they carry the same availability guarantee as the columns they come from.
Indoors they are zero, which is the truthful answer: it is not cold on the field
of a closed stadium.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

WEATHER_PATH = (Path(__file__).resolve().parents[2]
                / "data" / "processed" / "weather.parquet")

#: Thresholds match the flags this replaces, so the two are comparable.
COLD_F = 40.0
WINDY_MPH = 15.0

#: Roofs where outdoor weather does not reach the field.
INDOOR = ("dome", "closed")


def available(weather_path: Path | None = None) -> bool:
    """Has anybody fetched the archive on this machine?

    The assembler asks before joining. A checkout without the archive builds a
    matrix WITHOUT these columns rather than one full of neutral values: an
    absent family is visible in `feature_matrix_hash` and in the family map,
    where a family of six constants is not visible anywhere at all.
    """
    return (Path(weather_path) if weather_path else WEATHER_PATH).exists()


def build_weather_features(schedules: pl.DataFrame,
                           weather_path: Path | None = None) -> pl.DataFrame:
    """One row per game: forecast conditions, neutralised for indoor venues."""
    path = Path(weather_path) if weather_path else WEATHER_PATH
    if not path.exists():
        # A missing fetch must not silently produce a column of zeros that the
        # model reads as "freezing everywhere". Better to have no feature.
        raise FileNotFoundError(
            f"{path} does not exist — run `python scripts/28_weather.py "
            "--fetch` before building features.")

    wx = pl.read_parquet(path).select(
        ["game_id", "wx_temp_f", "wx_wind_mph", "wx_precip_mm"])

    games = schedules.select(["game_id", "roof"]).unique(subset=["game_id"])
    df = games.join(wx, on="game_id", how="left")

    indoor = pl.col("roof").is_in(INDOOR).fill_null(False)

    # The neutral value is the outdoor mean, computed here rather than declared.
    mean_temp = df.filter(~indoor)["wx_temp_f"].mean()
    mean_wind = df.filter(~indoor)["wx_wind_mph"].mean()

    return df.with_columns([
        # Indoors, and anywhere the fetch has no reading, take the average so
        # the model sees "unremarkable" rather than "coldest game on record".
        pl.when(indoor).then(pl.lit(mean_temp))
          .otherwise(pl.col("wx_temp_f").fill_null(mean_temp))
          .alias("wx_temp_f"),
        pl.when(indoor).then(pl.lit(mean_wind))
          .otherwise(pl.col("wx_wind_mph").fill_null(mean_wind))
          .alias("wx_wind_mph"),
        # Zero precipitation indoors is not a fill, it is the fact.
        pl.when(indoor).then(pl.lit(0.0))
          .otherwise(pl.col("wx_precip_mm").fill_null(0.0))
          .alias("wx_precip_mm"),
    ]).with_columns([
        # Flags from the forecast, so they are known when the board goes up.
        (pl.when(indoor).then(pl.lit(0.0))
           .otherwise((pl.col("wx_temp_f") < COLD_F).cast(pl.Float64))
         ).alias("wx_is_cold"),
        (pl.when(indoor).then(pl.lit(0.0))
           .otherwise((pl.col("wx_wind_mph") >= WINDY_MPH).cast(pl.Float64))
         ).alias("wx_is_windy"),
        (pl.when(indoor).then(pl.lit(0.0))
           .otherwise((pl.col("wx_precip_mm") > 0.1).cast(pl.Float64))
         ).alias("wx_is_wet"),
    ]).select(["game_id", "wx_temp_f", "wx_wind_mph", "wx_precip_mm",
               "wx_is_cold", "wx_is_windy", "wx_is_wet"])


def coverage(schedules: pl.DataFrame,
             weather_path: Path | None = None) -> dict:
    """How much of the schedule the archive actually reaches, per season.

    Reported rather than assumed. Two gaps look identical in the built matrix
    once indoor games are neutralised, and they are not the same thing: a dome
    has no outdoor weather, while an upcoming game simply sits beyond
    Open-Meteo's 16-day horizon and fills in as the week approaches. If the
    season being served is 0% covered, the family is six constants and the
    model is learning nothing from it.
    """
    path = Path(weather_path) if weather_path else WEATHER_PATH
    have = (set(pl.read_parquet(path)["game_id"].to_list())
            if path.exists() else set())
    rows = []
    for season, chunk in schedules.group_by("season"):
        s = season[0] if isinstance(season, tuple) else season
        roof = chunk["roof"].fill_null("unknown").str.to_lowercase()
        indoor = int(roof.is_in(INDOOR).sum())
        outdoor = chunk.height - indoor
        covered = sum(1 for g in chunk["game_id"] if g in have)
        rows.append({
            "season": int(s), "games": chunk.height,
            "indoor": indoor, "outdoor": outdoor, "covered": covered,
            "outdoor_covered": covered / outdoor if outdoor else None,
        })
    return {"archive_games": len(have),
            "seasons": sorted(rows, key=lambda r: r["season"])}
