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
    assert "weather_available()" in asm, (
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


def test_every_weather_column_has_a_family():
    """The trap that would have let this into the model unmeasured.

    `scripts/26_feature_families.py` records provenance by wrapping every
    `build_*` attribute ON THE ASSEMBLER MODULE. A builder reached through a
    module alias — `wxf.build_weather_features(...)` — is never wrapped, so its
    columns land in `unattributed`; and `trainer.get_feature_cols` keeps
    unattributed columns UNCONDITIONALLY, so the family would have entered the
    locked 24-family set without appearing in any allow-list or any ablation.

    An unmeasured feature in a model whose whole point is a measured feature set
    is worse than no feature.
    """
    import json

    from src.features import assembler

    src = (ROOT / "src" / "features" / "assembler.py").read_text()
    assert "from src.features.weather_features import build_weather_features" in src
    calls = [ln for ln in src.splitlines()
             if "build_weather_features(" in ln and not ln.lstrip().startswith("#")]
    assert calls and all("wxf." not in ln for ln in calls), (
        f"called through an alias the provenance wrapper never sees it: {calls}")
    assert hasattr(assembler, "build_weather_features"), (
        "the name has to exist on the assembler module for wrapping to work")

    path = ROOT / "diagnostics" / "feature_families.json"
    if not path.exists():
        pytest.skip("no family map in this checkout")
    doc = json.loads(path.read_text())
    owned = {c for cols in doc["families"].values() for c in cols}
    wx = {c for c in owned if c.startswith("wx_")}
    if not wx:
        pytest.skip("family map predates the weather family")
    assert wx <= set(doc["families"].get("build_weather_features", [])), (
        "a wx_ column is attributed to some other builder")
    assert not [c for c in doc["unattributed"] if c.startswith("wx_")]


def test_weather_cannot_be_served_until_the_forecast_window_opens():
    """The reason this family is measured but not promoted.

    Open-Meteo forecasts 16 days ahead. In August, every Week 1 fixture is
    further out than that, so every 2026 row takes the outdoor mean — the six
    columns are CONSTANT for the season being served while they vary across
    training. That is the defect commit 3a7e0ef removed three features for, and
    `test_no_feature_takes_one_value_at_predict_time` in tests/test_leakage.py
    already fails on it the moment weather enters the allow-list.

    This test states the dependency explicitly so the failure reads as "wait
    for the forecast" rather than as a mystery. It passes either way: before
    the window opens because the family is not in the served set, and after it
    because the columns vary.
    """
    import polars as pl
    import yaml

    from src.evaluation.harness import _features
    from src.models.trainer import get_feature_cols
    from src.utils.config import config_overlay, get_config

    exp = ROOT / "experiments" / "weather-24-families.yaml"
    if not exp.exists():
        pytest.skip("no weather experiment in this checkout")

    df = _features("anytime_td")
    if not [c for c in df.columns if c.startswith("wx_")]:
        pytest.skip("feature matrix predates the weather family")

    served = get_feature_cols(df, "anytime_td")
    assert not [c for c in served if c.startswith("wx_")], (
        "weather is in the SERVED feature set. That is only safe once the "
        "archive covers the predict season — see the constancy check below "
        "and tests/test_leakage.py::test_no_feature_takes_one_value_at_"
        "predict_time")

    predict_season = get_config()["seasons"]["predict_season"]
    upcoming = df.filter(pl.col("season") == predict_season)
    if upcoming.is_empty():
        pytest.skip("no rows for the predict season")

    overlay = yaml.safe_load(exp.read_text())["overlay"]
    with config_overlay({**overlay, "target": {"type": "anytime_td"}}):
        with_wx = get_feature_cols(df, "anytime_td")
    wx = [c for c in with_wx if c.startswith("wx_")]
    assert wx, "the experiment must actually add the family"

    # COVERAGE IS A QUESTION ABOUT THE MEASUREMENTS, NOT THE FLAGS.
    #
    # This asserted that either every `wx_` column varies or every one is
    # constant, on the reasoning that a mixture means the archive covers some
    # fixtures and not others. That inference held in August, when the window
    # was shut and all six took the fill. It stopped holding on 2026-10-14,
    # when the archive was refreshed and the board came back fully covered:
    # temperature spans 44.8F to 97.5F over 62 distinct values and
    # `wx_is_cold` is STILL constant, because no game this season has been
    # played under 40F. That is October, not a gap.
    #
    # So the coverage question is asked of the three measured columns, which
    # cannot be constant across a real slate. A derived flag is allowed to be
    # constant whenever the column it thresholds varies — the condition
    # simply has not happened yet.
    measured = [c for c in wx if c in ("wx_temp_f", "wx_wind_mph",
                                       "wx_precip_mm")]
    flat = [c for c in measured if upcoming[c].n_unique() <= 1]
    if flat and len(flat) != len(measured):
        raise AssertionError(
            f"the archive covers the predict season only partially: "
            f"{sorted(set(measured) - set(flat))} vary and {sorted(flat)} do "
            f"not. Re-run `python scripts/28_weather.py --fetch --seasons "
            f"{predict_season}`")
    if flat:
        # Every measurement flat is the window-shut state, and then the flags
        # derived from them must be flat too, or something is inventing one.
        assert all(upcoming[c].n_unique() <= 1 for c in wx), (
            "every measured column takes the fill, so no flag derived from "
            "them can vary")


def test_an_interaction_hides_the_constancy_its_inputs_have():
    """`n_unique == 2` is not the same as "this feature varies".

    The main effects are caught by
    `test_no_feature_takes_one_value_at_predict_time` because they take exactly
    one value for the season being served. Their products with a position dummy
    take TWO — zero, and one constant — so the same guard passes them while the
    feature is a scaled dummy carrying no weather at all. A model trained where
    `wxi_wind_x_te` means "how windy, for a tight end" would be served one where
    it means "is a tight end", which is a distinction it already has.

    So the rule is stated on the input rather than the output: no weather
    interaction may be served while the weather it derives from is constant.
    """
    import polars as pl

    from src.evaluation.harness import _features
    from src.models.trainer import get_feature_cols
    from src.utils.config import get_config

    df = _features("anytime_td")
    wxi = [c for c in df.columns if c.startswith("wxi_")]
    if not wxi:
        pytest.skip("feature matrix predates the interaction family")

    predict_season = get_config()["seasons"]["predict_season"]
    upcoming = df.filter(pl.col("season") == predict_season)
    if upcoming.is_empty():
        pytest.skip("no rows for the predict season")

    served = get_feature_cols(df, "anytime_td")
    if not [c for c in served if c.startswith("wxi_")]:
        return                      # not served; nothing to protect against

    inputs = [c for c in df.columns if c.startswith("wx_")]
    degenerate = [c for c in inputs if upcoming[c].n_unique() <= 1]
    assert not degenerate, (
        f"weather interactions are in the served set while {sorted(degenerate)} "
        f"take one value for {predict_season}. Each interaction is then a "
        f"constant multiple of its other factor — a position dummy the model "
        f"already has. Re-run `python scripts/28_weather.py --fetch` once the "
        f"season is inside the 16-day forecast horizon")


def test_the_written_verdict_is_in_the_ledger_and_points_at_runs_that_happened():
    """A row of numbers does not stop anyone retrying an idea blind.

    The ground rule in docs/MODEL_ITERATION.md is that REJECTED "stays in the
    ledger so nobody retries it blind", and the runs log themselves. What they
    do not log is the reading of them — that the main effects cannot reorder a
    within-game ranking however real the weather is, and that the interactions
    move AUC while costing Top-3. Someone will try weather again; this is what
    they should find when they look.
    """
    import json

    ledger = ROOT / "models" / "registry" / "ledger.jsonl"
    if not ledger.exists():
        pytest.skip("no ledger in this checkout")
    rows = [json.loads(x) for x in ledger.read_text().splitlines() if x.strip()]
    notes = [r for r in rows if r.get("kind") == "note"
             and "weather" in r.get("id", "")]
    if not notes:
        pytest.skip("no weather verdict recorded yet")

    note = notes[-1]
    assert note["verdict"] == "REJECTED"
    assert note.get("doc"), "a verdict has to say where it is written up"
    ids = {r["id"] for r in rows}
    assert note["covers"], "a verdict with no runs behind it is an opinion"
    assert set(note["covers"]) <= ids, (
        "the verdict references runs that are not in the ledger")
    # The two things that would otherwise have to be rediscovered.
    assert "within" in note["text"].lower()
    assert "DO NOT RETRY" in note["text"]


# --------------------------------------------------------------------------
# Coverage of the archive itself, against the schedule it has to serve
# --------------------------------------------------------------------------

def test_every_played_outdoor_game_this_season_has_a_reading():
    """The staleness this is written against, and the bug under it.

    `weather.parquet` sat at 2021-2025 from 20 August while the season played
    on, so every 2026 game fell to the outdoor mean with `wx_is_cold`,
    `wx_is_windy` and `wx_is_wet` all zero — a season the model saw as having
    no cold, windy or wet game in it. Nothing failed, because the fill is
    deliberate and silent.

    Underneath it was a real bug. The fetch range was built from LOCAL game
    days while the hourly index is keyed by kickoff in UTC, so a night game —
    Atlanta at 20:20 is 00:20 UTC the next day — fell one hour past the end of
    its own range and was dropped. It bit only the last game of each
    stadium-season, 4 to 8 outdoor games a year from 2016 on.

    A row count would not have caught either. This asks the question that
    matters: is there a game we could have priced and did not?
    """
    import polars as pl

    from src.features.stadium_coords import coordinates
    from src.utils.config import get_config
    from src.utils.paths import get_path

    wx_path = Path(get_path("processed")) / "weather.parquet"
    if not wx_path.exists():
        pytest.skip("no weather archive — run `28_weather.py --fetch`")

    season = int(get_config()["seasons"]["predict_season"])
    sched = pl.read_parquet(Path(get_path("raw")) / "schedules.parquet")
    played = sched.filter(
        (pl.col("season") == season)
        & pl.col("roof").is_in(["outdoors", "open"])
        & pl.col("home_score").is_not_null())
    if not played.height:
        pytest.skip(f"{season} has no completed outdoor games yet")

    have = set(pl.read_parquet(wx_path)["game_id"].to_list())
    missing = [
        (r["game_id"], r["gametime"], r["stadium"])
        for r in played.iter_rows(named=True)
        # A stadium with no asserted coordinate cannot be fetched at all, and
        # that is a different gap — `stadium_coords` is the place it is fixed.
        if coordinates(r["stadium"]) is not None
        and r["game_id"] not in have
    ]
    assert not missing, (
        f"{len(missing)} played outdoor {season} games have no weather row, "
        f"so they are being served the outdoor mean with every flag at zero: "
        f"{missing[:5]}")


def test_the_upcoming_week_is_forecast_rather_than_filled():
    """An archive cannot price a game that has not kicked off.

    Both sources the fetch used hold the past, so a refresh filled in history
    and left the board going up on Wednesday on the fill — which is the half
    that actually prices anything. The live forecast endpoint covers it, and
    this checks the result rather than the intention.
    """
    import polars as pl

    from src.features.stadium_coords import coordinates
    from src.utils.config import get_config
    from src.utils.paths import get_path

    wx_path = Path(get_path("processed")) / "weather.parquet"
    if not wx_path.exists():
        pytest.skip("no weather archive — run `28_weather.py --fetch`")

    season = int(get_config()["seasons"]["predict_season"])
    sched = pl.read_parquet(Path(get_path("raw")) / "schedules.parquet")
    upcoming = sched.filter(
        (pl.col("season") == season)
        & pl.col("roof").is_in(["outdoors", "open"])
        & pl.col("home_score").is_null()
        & pl.col("gameday").is_not_null())
    if not upcoming.height:
        pytest.skip("nothing left to play")

    # Only the games near enough for a forecast to exist. Beyond the
    # endpoint's reach there is nothing to ask for, and the next weekly
    # refresh collects them.
    soon = sorted({str(d)[:10] for d in upcoming["gameday"]})[:1]
    nearest = upcoming.filter(pl.col("gameday").cast(pl.Utf8).str.slice(0, 10)
                              <= (soon[0] if soon else ""))
    have = set(pl.read_parquet(wx_path)["game_id"].to_list())
    missing = [r["game_id"] for r in nearest.iter_rows(named=True)
               if coordinates(r["stadium"]) is not None
               and r["game_id"] not in have]
    assert not missing, (
        "the next outdoor games to kick off carry no forecast and will be "
        f"served the outdoor mean: {missing}")
