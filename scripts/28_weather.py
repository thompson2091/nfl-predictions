#!/usr/bin/env python3
"""Pre-kickoff weather forecasts, and proof they describe the right place.

Phase 3g. `temp` and `wind` sit in `schedules.parquet` and are excluded from the
model, correctly: they are measured *at kickoff*, so a model trained on them
learns against information it will never have on Sunday morning. A forecast
issued before the game restores the signal honestly.

**The archive, not the observations.** Training rows must carry what was
*forecast* before each historical game, not what happened during it. Most
weather APIs serve observations for the past and forecasts only for the future,
which would rebuild the exact train/serve skew the exclusion removed — strong in
backtest, weak live. Open-Meteo's historical-forecast archive stores forecasts
as they were issued, back to 2016, free and keyless, with the same request shape
for past and future. One code path serves training and prediction, which is
itself the guard against the two drifting apart.

**Validation is the point of this script.** Stadium coordinates are asserted by
hand in `src/features/stadium_coords.py`, and an asserted table is only safe if
something independent checks it. `--validate` fetches each site's temperature at
kickoff and correlates it against the `temp` nflverse recorded. A coordinate in
the wrong city cannot survive that, and neither can a timezone mistake. The
column that is useless as a feature is exactly the right instrument for this.

    python scripts/28_weather.py --validate            # check the coordinates
    python scripts/28_weather.py --validate --limit 8  # a quick subset

Nothing here writes a feature yet; that comes once the coordinates are proven.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import polars as pl  # noqa: E402

from src.features.stadium_coords import coordinates  # noqa: E402
from src.utils.paths import get_path  # noqa: E402

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
#: Forecasts as they were issued. `*_previous_day1` is the value this hour was
#: forecast to have, from the model run 24 hours earlier — the lead time a board
#: is actually priced at. Archived from roughly mid-2021; before that the field
#: comes back null and the analysis is used instead. See `fetch` for why that is
#: an acceptable substitution and what it costs.
PREVIOUS_RUNS = "https://previous-runs-api.open-meteo.com/v1/forecast"
#: The live forecast, for games that have not kicked off. Both archives above
#: hold the past only, so without this the upcoming week — the one a board is
#: priced on — carries no weather at all. About 16 days of reach.
LIVE_FORECAST = "https://api.open-meteo.com/v1/forecast"
WEATHER_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "weather.parquet"
OUT = Path(__file__).resolve().parents[1] / "diagnostics" / "weather_validation.json"

#: Open-Meteo returns Celsius; nflverse records Fahrenheit.
def _c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def _get(url: str, params: dict, retries: int = 3) -> dict | None:
    """One request, with a courteous retry. Returns None rather than raising.

    A validation run that dies on the twelfth of thirty-seven stadiums tells
    you less than one that reports thirty-six results and a failure.
    """
    query = urllib.parse.urlencode(params, doseq=True)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(f"{url}?{query}", timeout=60) as r:
                return json.loads(r.read())
        except Exception as e:                                   # noqa: BLE001
            if attempt == retries - 1:
                print(f"    request failed: {type(e).__name__}: {str(e)[:80]}")
                return None
            time.sleep(2 * (attempt + 1))
    return None


def kickoff_utc(gameday: str, gametime: str) -> "datetime":
    """The instant of kickoff, in UTC.

    `gametime` in the nflverse schedule is **US Eastern**, for every game
    including the London and Munich ones. Treating that number as the venue's
    local hour is wrong by the offset between Eastern and the venue, and the
    first validation run showed exactly that: error grew monotonically with
    distance from Eastern — 2.2F median for Eastern stadiums, 5.8F for London —
    and the bias was consistently negative, because an earlier hour is a colder
    hour.

    So the wall-clock number is converted to an instant here, and the archive
    is queried in UTC. A stadium's own timezone never enters the calculation,
    which is what stops it being got wrong twice.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    naive = datetime.fromisoformat(f"{gameday[:10]}T{str(gametime)[:5]}:00")
    return naive.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(
        ZoneInfo("UTC"))


def hourly_temps(lat: float, lon: float, start: str, end: str) -> dict | None:
    """Hourly temperature and wind for a date range, timestamped in UTC."""
    return _get(ARCHIVE, {
        "latitude": lat, "longitude": lon,
        "start_date": start, "end_date": end,
        "hourly": ["temperature_2m", "wind_speed_10m"],
        "timezone": "UTC",
        "wind_speed_unit": "mph",
    })


def _archive_pair(url: str, lat: float, lon: float, start: str, end: str,
                  hourly: list[str]) -> dict:
    """One archive request, already defaulted to an empty dict."""
    return _get(url, {
        "latitude": lat, "longitude": lon,
        "start_date": start, "end_date": end,
        "timezone": "UTC", "wind_speed_unit": "mph",
        "hourly": hourly,
    }) or {}


def fetch(seasons: list[int] | None = None) -> "pl.DataFrame":
    """One row per outdoor game: what was forecast at kickoff, 24 hours out.

    **Forecast, not observation.** Training rows carry what was *forecast*
    before the game. Using what actually happened would train the model against
    a precision it never has when a board goes up. Measured over 34 games, a
    24-hour forecast misses kickoff temperature by 2.2F on average against a
    signal that varies by 17.6F, so the forecast carries essentially all of the
    signal and none of the hindsight.

    **The pre-2021 substitution.** Open-Meteo archives forecasts from around
    mid-2021. Earlier games fall back to the analysis, and the row is marked
    `wx_is_forecast = 0`. That is a real inconsistency and it is bounded: the
    two differ by 2.2F, an eighth of the signal's standard deviation. The
    alternative — nulling six of nine training seasons — would leave the 2022
    and 2023 folds training on a feature that is absent from every row they see,
    which measures nothing at all.

    Note what this does NOT reintroduce. `temp` was excluded because it is 100%
    null at predict time: nobody has recorded a kickoff temperature for a game
    that has not kicked off. That is a total break, not a precision problem, and
    a forecast fixes exactly it.

    Requests are batched per stadium-season rather than per game — 37 sites over
    a dozen seasons is a few hundred calls against a free service, where one
    call per game would be several thousand.
    """
    from src.features.weather_features import with_usual_roof

    # An unplayed game at a retractable roof has a null roof; the stadium's
    # usual state decides whether it needs a forecast. See `with_usual_roof`.
    sched = with_usual_roof(pl.read_parquet(get_path("raw") / "schedules.parquet"))
    games = sched.filter(
        pl.col("roof").is_in(["outdoors", "open"])
        & pl.col("gameday").is_not_null() & pl.col("gametime").is_not_null())
    if seasons:
        games = games.filter(pl.col("season").is_in(seasons))

    rows = []
    pairs = games.select(["stadium", "season"]).unique().sort(["season", "stadium"])
    for i, pr in enumerate(pairs.iter_rows(named=True), 1):
        coords = coordinates(pr["stadium"])
        if coords is None:
            continue
        lat, lon = coords
        sub = games.filter((pl.col("stadium") == pr["stadium"])
                           & (pl.col("season") == pr["season"]))
        days = sorted({str(d)[:10] for d in sub["gameday"]})
        # BOTH SOURCES ARE ARCHIVES, SO A FUTURE DATE IS A 400.
        #
        # The range asked for was min(days) to max(days) over the whole
        # season, which for the season being played runs into next January.
        # Open-Meteo answers that with `400 Bad Request` and the handler
        # reported "no data from either source" — so a mid-season fetch
        # returned almost nothing and looked like a service problem rather
        # than a request this code should not have sent. Clamp to yesterday,
        # which is the last day an archive can be expected to hold.
        #
        # What this does NOT do is price an upcoming game: a board going up on
        # Wednesday wants Sunday's FORECAST, which lives behind the live
        # forecast endpoint rather than either archive. That is a separate
        # addition and the coverage report below says how many games are
        # waiting on it.
        cutoff = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
        # 14, not 15, so that the extra UTC day added below still lands
        # inside the forecast endpoint's own ~16-day reach. Asking past it is
        # a 400, and that dropped Lambeau's Sunday night game — a stadium
        # whose last upcoming fixture happened to sit on the old edge.
        horizon = (datetime.now(timezone.utc).date() + timedelta(days=14)).isoformat()
        api_limit = (datetime.now(timezone.utc).date() + timedelta(days=15)).isoformat()
        ahead = [d for d in days if cutoff < d <= horizon]
        days = [d for d in days if d <= cutoff]
        if not days and not ahead:
            print(f"[{i}/{pairs.height}] {pr['stadium'][:34]:34s} {pr['season']} "
                  f"(nothing within reach of either source yet)")
            continue
        print(f"[{i}/{pairs.height}] {pr['stadium'][:34]:34s} {pr['season']} "
              f"({len(days)} played, {len(ahead)} upcoming)")
        # Two sources, because neither covers the whole span. The previous-runs
        # archive holds forecasts-as-issued but only from 2016-01-01, and its
        # analysis field is empty for the early years — the first version of this
        # relied on that fallback and silently produced nothing before 2017. The
        # reanalysis archive covers everything but holds no forecasts. So: ask
        # both, prefer the forecast, fall back to the reanalysis.
        # A NIGHT GAME KICKS OFF ON THE NEXT UTC DAY, AND THE RANGE ENDED
        # TOO EARLY FOR IT.
        #
        # The hourly index is keyed by kickoff in UTC, but the range was built
        # from LOCAL game days. Atlanta at 20:20 on 11 October is 00:20 UTC on
        # the 12th, so for the last game in a stadium's range the key fell one
        # hour past the end of the data and `t is None` dropped it without a
        # word. It bit only the final game of each stadium-season, which is
        # why it read as an occasional gap rather than a rule: 4 to 8 outdoor
        # games a season from 2016 on, 59% of them kicking off at or after
        # 16:00 local. One more day on the end covers every timezone the
        # league plays in.
        forecast, analysis = {}, {}
        if days:
            last = (date.fromisoformat(max(days))
                    + timedelta(days=1)).isoformat()
            forecast = _archive_pair(PREVIOUS_RUNS, lat, lon, min(days), last,
                                     ["temperature_2m_previous_day1",
                                      "wind_speed_10m_previous_day1",
                                      "precipitation_previous_day1"])
            analysis = _archive_pair(ARCHIVE, lat, lon, min(days), last,
                                     ["temperature_2m", "wind_speed_10m",
                                      "precipitation"])
        # THE UPCOMING WEEK IS THE HALF THAT PRICES A BOARD, and neither
        # archive can serve it: both hold the past. So a game that has not
        # kicked off is read from the live forecast endpoint, which is the
        # same request shape and the same free service. Without this the
        # refresh fills in history and the board going up on Wednesday still
        # sees the outdoor mean with every weather flag at zero — which is
        # the state `weather.parquet` was actually in, for every 2026 game.
        #
        # Marked `wx_is_forecast = 1`, because that is exactly what it is.
        upcoming = {}
        if ahead:
            # The same UTC day boundary as the archive range above: a
            # Thursday 20:15 in Denver is 02:15 UTC on the Friday, so the
            # forecast window needs the extra day too or the week's own night
            # games fall out of it.
            upto = min((date.fromisoformat(max(ahead))
                        + timedelta(days=1)).isoformat(), api_limit)
            upcoming = _get(LIVE_FORECAST, {
                "latitude": lat, "longitude": lon,
                "start_date": min(ahead), "end_date": upto,
                "timezone": "UTC", "wind_speed_unit": "mph",
                "hourly": ["temperature_2m", "wind_speed_10m",
                           "precipitation"],
            }) or {}

        fh, ah = forecast.get("hourly"), analysis.get("hourly")
        uh = upcoming.get("hourly")
        if not fh and not ah and not uh:
            print("    no data from any source")
            continue

        fidx = {t: k for k, t in enumerate(fh["time"])} if fh else {}
        aidx = {t: k for k, t in enumerate(ah["time"])} if ah else {}
        uidx = {t: k for k, t in enumerate(uh["time"])} if uh else {}
        reach = max(days + ahead)
        for g in sub.iter_rows(named=True):
            if str(g["gameday"])[:10] > reach:
                continue
            ko = kickoff_utc(str(g["gameday"])[:10], g["gametime"])
            key = ko.strftime("%Y-%m-%dT%H:00")

            def pick(fc: str, an: str):
                """Archived 24h forecast, else reanalysis, else live forecast."""
                k = fidx.get(key)
                if k is not None and fh.get(fc) and fh[fc][k] is not None:
                    return fh[fc][k], True
                k = aidx.get(key)
                if k is not None and ah.get(an) and ah[an][k] is not None:
                    return ah[an][k], False
                k = uidx.get(key)
                if k is not None and uh.get(an) and uh[an][k] is not None:
                    return uh[an][k], True
                return None, False

            t, is_fc = pick("temperature_2m_previous_day1", "temperature_2m")
            wind, _ = pick("wind_speed_10m_previous_day1", "wind_speed_10m")
            precip, _ = pick("precipitation_previous_day1", "precipitation")
            if t is None:
                continue
            rows.append({
                "game_id": g["game_id"], "season": g["season"],
                "wx_temp_f": _c_to_f(t),
                "wx_wind_mph": float(wind) if wind is not None else None,
                "wx_precip_mm": float(precip) if precip is not None else None,
                "wx_is_forecast": int(is_fc),
            })
        time.sleep(0.5)

    out = pl.DataFrame(rows)
    WEATHER_PATH.parent.mkdir(parents=True, exist_ok=True)

    # MERGE, DO NOT OVERWRITE, AND THAT IS WHY THIS WENT STALE.
    #
    # This wrote `out` wholesale, so the only safe way to run it was over every
    # season — a few hundred calls against a free service. Expensive enough
    # that nobody ran it mid-season, and `weather.parquet` sat at 2021-2025
    # from 20 August while every 2026 game fell to the outdoor mean with
    # `wx_is_cold`, `wx_is_windy` and `wx_is_wet` all zero. The model saw a
    # season with no cold, windy or wet game in it.
    #
    # Now a run replaces only the seasons it actually fetched and leaves the
    # rest untouched, so `--seasons 2026` is a cheap weekly refresh and the
    # historical rows keep the values they were archived with.
    if seasons and WEATHER_PATH.exists():
        prior = pl.read_parquet(WEATHER_PATH)
        kept = prior.filter(~pl.col("season").is_in(list(seasons)))
        out = pl.concat([kept, out.select(prior.columns)], how="vertical") \
                .sort(["season", "game_id"])
        print(f"\n  kept {kept.height:,} rows from seasons this run did not "
              f"fetch")
    out.write_parquet(WEATHER_PATH)
    print(f"\n{out.height:,} games -> {WEATHER_PATH}")
    if out.height:
        fc = out["wx_is_forecast"].mean()
        print(f"  {fc:.1%} from an archived 24h forecast, the rest analysis "
              f"(pre-2021)")
    return out


def validate(limit: int | None = None) -> dict:
    """Do the asserted coordinates agree with recorded kickoff temperatures?"""
    sched = pl.read_parquet(get_path("raw") / "schedules.parquet")
    games = sched.filter(
        pl.col("roof").is_in(["outdoors", "open"])
        & pl.col("temp").is_not_null()
        & pl.col("gameday").is_not_null()
        & pl.col("gametime").is_not_null()
        # The archive starts in 2016; earlier games cannot be checked this way.
        & (pl.col("season") >= 2016)
    )

    by_stadium = (games.group_by("stadium")
                  .agg(pl.len().alias("games"))
                  .sort("games", descending=True))
    names = by_stadium["stadium"].to_list()
    if limit:
        names = names[:limit]

    results, failures = {}, []
    for i, stadium in enumerate(names, 1):
        coords = coordinates(stadium)
        if coords is None:
            failures.append({"stadium": stadium, "why": "not in the table"})
            continue
        lat, lon = coords
        sub = games.filter(pl.col("stadium") == stadium).sort("gameday")
        # Sample across the range so one warm autumn cannot carry the check.
        step = max(1, sub.height // 12)
        sample = sub[::step][:12]

        print(f"[{i}/{len(names)}] {stadium} ({lat:.3f}, {lon:.3f}) "
              f"— {sample.height} games")

        ours, theirs = [], []
        for row in sample.iter_rows(named=True):
            day = str(row["gameday"])[:10]
            ko = kickoff_utc(day, row["gametime"])
            # A UTC kickoff can land on the next calendar day, so ask for both.
            end = (ko.date()).isoformat()
            data = hourly_temps(lat, lon, day, end)
            if not data or "hourly" not in data:
                continue
            times = data["hourly"]["time"]
            temps = data["hourly"]["temperature_2m"]
            want = ko.strftime("%Y-%m-%dT%H:00")
            if want not in times:
                continue
            t = temps[times.index(want)]
            if t is None:
                continue
            ours.append(_c_to_f(t))
            theirs.append(float(row["temp"]))
            time.sleep(0.4)          # be polite to a free service

        if len(ours) < 4:
            failures.append({"stadium": stadium, "why": f"only {len(ours)} usable games"})
            print(f"    too few usable readings ({len(ours)})")
            continue

        a, b = np.array(ours), np.array(theirs)
        r = float(np.corrcoef(a, b)[0, 1])
        mae = float(np.abs(a - b).mean())
        results[stadium] = {"lat": lat, "lon": lon, "n": len(ours),
                            "corr": r, "mae_f": mae,
                            "mean_fetched": float(a.mean()),
                            "mean_recorded": float(b.mean())}
        # Judged on BIAS, not correlation. Correlation collapses when a venue's
        # range is narrow — Jacksonville sits between 70F and 88F, so r=0.78
        # there while the mean error is 0.1F, and Lambeau reaches r=0.997 mostly
        # by spanning 18F of standard deviation. A coordinate in the wrong city
        # shows up as a persistent offset, which is what this now tests.
        bias = float((a - b).mean())
        results[stadium]["bias_f"] = bias
        flag = "" if (abs(bias) < 4 and mae < 8) else "   <-- CHECK"
        print(f"    r={r:+.3f}  MAE={mae:.1f}F  "
              f"(fetched {a.mean():.0f}F vs recorded {b.mean():.0f}F){flag}")

    payload = {"validated": results, "failures": failures}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def report(payload: dict) -> None:
    res = payload["validated"]
    if not res:
        print("\nNothing validated.")
        return
    rs = np.array([v["corr"] for v in res.values()])
    maes = np.array([v["mae_f"] for v in res.values()])
    bad = {k: v for k, v in res.items()
           if abs(v.get("bias_f", 0.0)) >= 4 or v["mae_f"] >= 8}
    print(f"\n{len(res)} stadiums checked against recorded kickoff temperature")
    biases = np.array([abs(v.get("bias_f", 0.0)) for v in res.values()])
    print(f"  mean bias:      median {np.median(biases):.1f}F, worst "
          f"{biases.max():.1f}F   <- the criterion")
    print(f"  absolute error: median {np.median(maes):.1f}F, worst {maes.max():.1f}F")
    print(f"  correlation:    median {np.median(rs):+.3f}, worst {rs.min():+.3f}"
          f"   (reported, not judged on — narrow-range venues score badly "
          f"while being exactly right)")
    if bad:
        print(f"\n  {len(bad)} need checking — a wrong city looks exactly like this:")
        for k, v in sorted(bad.items(),
                           key=lambda kv: -abs(kv[1].get("bias_f", 0.0))):
            print(f"    {k:38s} bias={v.get('bias_f', 0.0):+.1f}F  "
                  f"MAE={v['mae_f']:.1f}F  r={v['corr']:+.3f}")
    else:
        print("\n  Every stadium agrees with the recorded temperature. The "
              "coordinates describe the right places.")
    for f in payload["failures"]:
        print(f"  FAILED {f['stadium']}: {f['why']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--seasons", default=None,
                    help="comma-separated seasons to fetch, e.g. 2026. Only "
                         "these are replaced; every other season already on "
                         "disk is kept. Omit to rebuild the whole archive.")
    ap.add_argument("--fetch", action="store_true",
                    help="build data/processed/weather.parquet")
    ap.add_argument("--current", action="store_true",
                    help="with --fetch: only the season being predicted, for "
                         "the scheduled runs before each feature build")
    ap.add_argument("--limit", type=int, default=None,
                    help="check only the N busiest stadiums")
    a = ap.parse_args()
    if a.fetch:
        if a.current:
            from src.utils.config import get_config
            fetch([int(get_config()["seasons"]["predict_season"])])
        else:
            fetch([int(x) for x in a.seasons.split(",")] if a.seasons else None)
        return 0
    if not a.validate:
        ap.print_help()
        return 0
    report(validate(a.limit))
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
