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
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import polars as pl  # noqa: E402

from src.features.stadium_coords import coordinates  # noqa: E402
from src.utils.paths import get_path  # noqa: E402

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
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
    ap.add_argument("--limit", type=int, default=None,
                    help="check only the N busiest stadiums")
    a = ap.parse_args()
    if not a.validate:
        ap.print_help()
        return 0
    report(validate(a.limit))
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
