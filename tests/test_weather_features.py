"""The one feature family that adds information rather than rearranging it.

`temp` and `wind` were removed from this model because they are recorded AT
kickoff — 100% null when a board goes up, so a model trained on them learns
against something it never has. So were `is_cold` and `is_windy`, which derived
from them with `.fill_null(False)` and therefore read "not cold" for every
upcoming game while 11-15% of training rows were cold.

The tests are shaped around those two failures rather than around the
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
        "game_id": ["g_out_cold", "g_dome", "g_out_mild", "g_future"],
        "season": [2025, 2025, 2025, 2026],
        "roof": ["outdoors", "dome", "outdoors", "outdoors"],
    })


@pytest.fixture
def archive(tmp_path) -> Path:
    p = tmp_path / "weather.parquet"
    pl.DataFrame({
        "game_id": ["g_out_cold", "g_out_mild"],
        "wx_temp_f": [20.0, 72.0],
        "wx_wind_mph": [22.0, 4.0],
        "wx_precip_mm": [1.5, 0.0],
    }).write_parquet(p)
    return p


def test_a_dome_is_not_the_coldest_game_on_record(schedules, archive):
    """The failure this family would otherwise walk straight back into.

    `trainer.prepare_data` runs `np.nan_to_num(X, nan=0.0)`, so a null
    temperature does not reach the model as "unknown" — it reaches it as **0F**,
    colder than any game in the data, applied to exactly the fixtures where
    weather cannot matter. Indoor venues take the outdoor mean instead, which
    reads as "unremarkable", and `is_dome` stays a feature so the model can
    still tell them apart.
    """
    from src.features.weather_features import build_weather_features

    out = build_weather_features(schedules, archive)
    row = {r["game_id"]: r for r in out.iter_rows(named=True)}

    assert row["g_dome"]["wx_temp_f"] == pytest.approx(46.0), (
        "a dome should take the outdoor mean of 20F and 72F")
    assert row["g_dome"]["wx_wind_mph"] == pytest.approx(13.0)
    assert row["g_dome"]["wx_precip_mm"] == 0.0, (
        "zero precipitation indoors is not a fill, it is the fact")
    assert row["g_dome"]["wx_is_cold"] == 0.0
    assert row["g_dome"]["wx_is_windy"] == 0.0

    # And the same neutral treatment for a game the fetch has not reached —
    # Open-Meteo runs 16 days ahead, so a Week 1 fixture in August has no
    # forecast yet and must not read as freezing either.
    assert row["g_future"]["wx_temp_f"] == pytest.approx(46.0)
    assert row["g_future"]["wx_is_cold"] == 0.0


def test_the_neutral_value_is_computed_from_the_data_not_written_down():
    """A dome constant nobody can check is a number someone typed once.

    nflverse records `temp` for exactly one dome game in eleven seasons, so
    there is nothing to fit a dome temperature *from* — which is the argument
    for using the outdoor mean of the same archive rather than 70F. It moves
    with the data.
    """
    import inspect

    from src.features import weather_features as wxf

    src = inspect.getsource(wxf.build_weather_features)
    assert 'mean_temp = df.filter(~indoor)["wx_temp_f"].mean()' in src
    assert "70" not in src, "no declared dome temperature"


def test_the_flags_come_from_the_forecast_not_the_observation(schedules,
                                                              archive):
    """`is_cold` was the leak, not just `temp`.

    The removed flags derived from the kickoff observation and filled null to
    False, so every upcoming game read "not cold" while 11-15% of training rows
    were. These derive from the forecast, so they carry the same availability
    guarantee as the columns they come from.
    """
    from src.features.weather_features import (COLD_F, WINDY_MPH,
                                               build_weather_features)

    out = build_weather_features(schedules, archive)
    row = {r["game_id"]: r for r in out.iter_rows(named=True)}

    assert row["g_out_cold"]["wx_is_cold"] == 1.0
    assert row["g_out_cold"]["wx_is_windy"] == 1.0
    assert row["g_out_cold"]["wx_is_wet"] == 1.0
    assert row["g_out_mild"]["wx_is_cold"] == 0.0
    assert row["g_out_mild"]["wx_is_wet"] == 0.0
    assert COLD_F == 40.0 and WINDY_MPH == 15.0, (
        "the thresholds match the flags this replaces so the two are "
        "comparable; changing them silently makes the comparison meaningless")

    src = (ROOT / "src" / "features" / "weather_features.py").read_text()
    assert 'pl.col("temp")' not in src and 'pl.col("wind")' not in src


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


def test_a_checkout_without_the_archive_omits_the_family_rather_than_faking_it(
        schedules, tmp_path):
    """Six constants are invisible; an absent family is not.

    Building the neutral frame with no archive would put the outdoor mean into
    every row of every season — a family that looks present, passes every
    shape check, and carries no information. The builder refuses, and the
    assembler asks `available()` first so the matrix simply lacks the columns.
    """
    from src.features.weather_features import (available,
                                               build_weather_features)

    missing = tmp_path / "nope.parquet"
    assert available(missing) is False
    with pytest.raises(FileNotFoundError, match="28_weather"):
        build_weather_features(schedules, missing)

    asm = (ROOT / "src" / "features" / "assembler.py").read_text()
    assert "wxf.available()" in asm, (
        "the assembler must check before building, or a fetchless checkout "
        "cannot build features at all")
    assert "if weather_feats is not None:" in asm


def test_the_archive_that_ships_is_forecasts_where_forecasts_exist():
    """Not observations. The whole point is the lead time.

    Open-Meteo archives forecasts-as-issued from roughly mid-2021; earlier
    seasons fall back to the reanalysis and are marked `wx_is_forecast = 0`. If
    a season after that is mostly unmarked, something has switched to reading
    what actually happened.
    """
    from src.features.weather_features import WEATHER_PATH

    if not WEATHER_PATH.exists():
        pytest.skip("no weather archive fetched in this checkout")
    wx = pl.read_parquet(WEATHER_PATH)
    recent = wx.filter(pl.col("season") >= 2022)
    if recent.is_empty():
        pytest.skip("archive predates the forecast era")
    share = float(recent["wx_is_forecast"].mean())
    assert share > 0.8, (
        f"only {share:.0%} of post-2021 rows are archived forecasts — the rest "
        f"are reanalysis, which is what happened rather than what was known")
