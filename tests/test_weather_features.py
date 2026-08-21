"""The one feature family that adds information rather than rearranging it.

`temp` and `wind` were removed from this model because they are recorded AT
kickoff — 100% null when a board goes up, so a model trained on them learns
against something it never has. That is the defect this family must not
reintroduce, and the tests below are shaped around it rather than around the
arithmetic, which is a join.

    pytest tests/test_weather_features.py -v
"""
from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def schedules() -> pl.DataFrame:
    return pl.DataFrame({
        "game_id": ["2025_01_A_B", "2025_01_C_D", "2026_01_E_F"],
        "season": [2025, 2025, 2026],
        "roof": ["outdoors", "dome", "outdoors"],
    })


@pytest.fixture
def archive() -> pl.DataFrame:
    return pl.DataFrame({
        "game_id": ["2025_01_A_B"],
        "wx_temp_f": [41.0], "wx_wind_mph": [12.0],
        "wx_precip_mm": [0.4], "wx_is_forecast": [1.0],
    })


def test_indoor_games_and_unfetched_games_are_both_null_and_stay_that_way(
        schedules, archive):
    """Two different unknowns, neither of them filled in.

    A dome has no outdoor temperature and an upcoming game outside the 16-day
    forecast horizon has one nobody knows yet. Imputing either makes the model
    learn on a number meaning "we do not know", and makes the two
    indistinguishable from each other. `is_dome` is what separates them, and it
    is already a feature.
    """
    from src.features.weather_features import build_weather_features

    out = build_weather_features(schedules, archive).sort("game_id")
    row = {r["game_id"]: r for r in out.iter_rows(named=True)}

    assert row["2025_01_A_B"]["wx_temp_f"] == 41.0
    assert row["2025_01_C_D"]["wx_temp_f"] is None, "a dome is not 70F"
    assert row["2026_01_E_F"]["wx_temp_f"] is None, "not fetched is not 0"
    for col in ("wx_wind_mph", "wx_precip_mm"):
        assert row["2025_01_C_D"][col] is None


def test_weather_is_one_row_per_game_and_never_fans_out(schedules, archive):
    """The join key is the fixture, not the side.

    Joining a game-level frame on (game_id, team) after duplicating it per side
    is how this project has produced fan-out before. One row per game, joined on
    game_id, cannot.
    """
    from src.features.weather_features import build_weather_features

    out = build_weather_features(schedules, archive)
    assert out.height == schedules["game_id"].n_unique()
    assert out["game_id"].n_unique() == out.height


def test_a_missing_archive_is_a_column_of_nulls_not_a_crash(schedules):
    """A fresh checkout has no `weather.parquet`, and must still build."""
    from src.features.weather_features import (COLUMNS,
                                               build_weather_features)

    out = build_weather_features(schedules, pl.DataFrame())
    assert out.height == 3
    for col in COLUMNS:
        assert col in out.columns
        assert out[col].null_count() == out.height


def test_the_recorded_kickoff_columns_do_not_come_back():
    """`temp` and `wind` are the leak this family exists to replace.

    A weather feature named for the recorded column, or built from it, would be
    the original defect with a new label on it. Everything here reads the
    archive of forecasts.
    """
    src = (ROOT / "src" / "features" / "weather_features.py").read_text()
    assert 'pl.col("temp")' not in src and 'pl.col("wind")' not in src
    assert "weather.parquet" in src

    asm = (ROOT / "src" / "features" / "assembler.py").read_text()
    joined = asm[asm.index("build_weather_features(schedules)"):]
    joined = joined[:joined.index("\n\n")]
    assert "schedules" in joined, "the builder takes the schedule, not the board"


def test_the_archive_that_ships_is_forecasts_where_forecasts_exist():
    """Not observations. The whole point is the lead time.

    Open-Meteo archives forecasts-as-issued from roughly mid-2021; earlier
    seasons fall back to the reanalysis and are marked. If a season after that
    is mostly unmarked, something has switched to reading observations.
    """
    from src.features.weather_features import load_archive

    wx = load_archive()
    if wx is None or wx.is_empty():
        pytest.skip("no weather archive fetched in this checkout")

    recent = wx.filter(pl.col("season") >= 2022)
    if recent.is_empty():
        pytest.skip("archive predates the forecast era")
    share = float(recent["wx_is_forecast"].mean())
    assert share > 0.8, (
        f"only {share:.0%} of post-2021 rows are archived forecasts — the rest "
        f"are reanalysis, which is what actually happened rather than what was "
        f"known beforehand")
