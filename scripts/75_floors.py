#!/usr/bin/env python3
"""Fit the 90% floors' tail calibration on 2024 and grade the floor on 2025.

    python scripts/75_floors.py

Writes `output/floors/calibration.json` (what the export serves) and
`output/floors/backtest.json` (what the page quotes). See
`src/evaluation/floors.py` for what a floor is and why it gets its own
calibration.

Three calibrations are graded side by side on the same player-games, so the
choice is visible rather than asserted:

  - raw:     the model's distribution as it stands,
  - median:  `ou_calibration`'s validation fit (2024 only), the one the board
             serves at each player's median line,
  - tail:    two numbers fitted on 2024 at the lines a floor is read from.

The tail fit is the one written for serving. It was chosen on what the median
fit does in the tail by construction (see the module docstring), not on the
2025 numbers this prints; 2025 is the season it is judged on.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

sys.path.insert(0, ".")

import numpy as np
import polars as pl

from src.evaluation import floors as F
from src.utils.config import get_config


def money(test: int, rows: dict[str, tuple]) -> dict:
    """Floors that had an alternate rung at exactly that line, at the median
    closing price across books: hit rate, implied, per $100 (clustered)."""
    from src.evaluation import safe_legs as sl

    r = sl.rungs([test], snapshot="close")
    r = r.with_columns(pl.col("market").replace_strict(sl.ALT_STAT).alias("stat"))
    parts = []
    for m, (ids, line) in rows.items():
        d = ids.with_columns(pl.Series("point", line), pl.lit(m).alias("stat"))
        parts.append(d.filter(pl.col("point").is_not_nan()).select(
            ["game_id", "player_id", "stat", "point", "actual"]))
    if not parts:
        return {}
    d = pl.concat(parts).join(
        r.select(["game_id", "player_id", "stat", "point", "odds", "implied_prob"]),
        on=["game_id", "player_id", "stat", "point"], how="inner")
    if d.height == 0:
        return {"n": 0}
    d = d.with_columns((pl.col("actual") > pl.col("point")).cast(pl.Int8).alias("hit"))
    s = sl.summarize(d)
    out = {"season": test, "n": s["n"], "games": s["games"],
           "hit": s["hit_rate"], "implied": s["price_implied"],
           "per_100": s["per_100"], "ci95": s["ci95"], "markets": {}}
    for m in rows:
        dm = d.filter(pl.col("stat") == m)
        if dm.height:
            sm = sl.summarize(dm)
            out["markets"][m] = {"n": sm["n"], "hit": sm["hit_rate"],
                                 "implied": sm["price_implied"],
                                 "per_100": sm["per_100"], "ci95": sm["ci95"]}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-write", action="store_true",
                    help="print the tables and write nothing")
    args = ap.parse_args()

    from src.evaluation.safe_legs import game_logs
    from src.models import ou_calibration as OC

    s = get_config()["splits"]
    fit_s, test_s = int(s["val_season"]), int(s["test_season"])
    tgt = F.target()
    logs = game_logs()
    arts: dict = {}
    cal_out, bt_out = {}, {}
    test_floor_rows: dict = {}

    print(f"target {tgt:.2f}; tail calibration fitted on {fit_s}, judged on {test_s}")
    for m in F.MARKETS:
        print(f"\n=== {m}")
        lines = F.grid(m)
        data = {}
        for season in (fit_s, test_s):
            ids, dist, meta = F.settled_dists(m, season, logs, arts)
            raw = F.raw_over_grid(m, dist, lines, meta.get("levels"),
                                  meta.get("dispersion"))
            data[season] = (ids, dist, meta, raw)
            print(f"  {season}: {ids.height:,} non-void player-games priced")

        ids, dist, meta, raw = data[fit_s]
        x, y = F.fit_rows(raw, lines, ids["actual"].to_numpy())
        tail = F.fit_tail(x, y)
        tail.update({"fitted_on": [fit_s], "fit_rows": int(len(y)),
                     "fit_levels": list(F.FIT_LEVELS),
                     "fit_date": date.today().isoformat()})
        cal_out[m] = tail
        median_fit = None
        try:
            from src.utils.paths import get_path
            p = get_path("models", m) / OC.REPORT_FILE
            median_fit = json.loads(p.read_text())
            if median_fit.get("fitted_on") != [fit_s]:
                print(f"  !! {p.name} is fitted on {median_fit.get('fitted_on')}, "
                      f"not {fit_s} alone")
        except Exception:                                        # noqa: BLE001
            median_fit = None
        print(f"  tail fit: slope {tail['b']:.3f}, offset {tail['a']:+.3f} "
              f"on {len(y):,} rows; median-line fit slope "
              f"{(median_fit or {}).get('b', float('nan')):.3f}")

        res_m: dict = {"tail_fit": {k: tail[k] for k in ("a", "b", "n")},
                       "median_fit": ({k: median_fit[k] for k in ("a", "b")}
                                      if median_fit else None)}
        for name, cal in (("raw", None), ("median", median_fit), ("tail", tail)):
            for season in (fit_s, test_s):
                ids, dist, meta, raw = data[season]
                line, chance = F.floors(F.calibrate(raw, cal), lines, tgt)
                ok = ~np.isnan(line)
                act = ids["actual"].to_numpy()
                hit = F.grade(line[ok], act[ok])
                r = F.cluster_rate(hit, ids["game_id"].to_numpy()[ok])
                med = F.median_of(m, dist, meta)
                r.update({
                    "candidates": int(ids.height),
                    "coverage": float(ok.mean()) if len(ok) else 0.0,
                    "claimed": float(np.mean(chance[ok])) if ok.any() else None,
                    "floor_median": float(np.median(line[ok])) if ok.any() else None,
                    "proj_median": float(np.median(med[ok])) if ok.any() else None,
                    "gap_median": float(np.median(med[ok] - line[ok])) if ok.any() else None,
                    "in_sample": season == fit_s and name == "tail",
                })
                res_m[f"{name}|{season}"] = r
                tag = " (fit season)" if r["in_sample"] else ""
                print(f"  {name:6s} {season}: {F.fmt_rate(r)}  claimed "
                      f"{(r['claimed'] or 0):.3f}  coverage {r['coverage']:.0%}  "
                      f"floor {r['floor_median']} vs median "
                      f"{(r['proj_median'] or 0):.1f}{tag}")
                if name == "tail" and season == test_s:
                    test_floor_rows[m] = (ids, line)
        # BY HOW MUCH THE PLAYER IS PROJECTED FOR. A market can hold 90% on
        # average and miss it at one end: a low projection is a thin role,
        # and a thin role is where the distribution is least sure of itself.
        # Cut points from the fit season, so 2025 only grades them.
        strata = []
        fids, fdist, fmeta, fraw = data[fit_s]
        fline, _ = F.floors(F.calibrate(fraw, tail), lines, tgt)
        fmed = F.median_of(m, fdist, fmeta)[~np.isnan(fline)]
        cuts = [float(c) for c in np.percentile(fmed, [100 / 3, 200 / 3])] \
            if len(fmed) else []
        ids, dist, meta, raw = data[test_s]
        line, _ = F.floors(F.calibrate(raw, tail), lines, tgt)
        med = F.median_of(m, dist, meta)
        ok = ~np.isnan(line)
        edges = [-np.inf] + cuts + [np.inf]
        for i in range(len(edges) - 1):
            sel = ok & (med >= edges[i]) & (med < edges[i + 1])
            r = F.cluster_rate(F.grade(line[sel], ids["actual"].to_numpy()[sel]),
                               ids["game_id"].to_numpy()[sel])
            r.update({"from": None if i == 0 else edges[i],
                      "to": None if i == len(edges) - 2 else edges[i + 1]})
            strata.append(r)
            print(f"    median {edges[i]:7.1f} to {edges[i + 1]:7.1f}: {F.fmt_rate(r)}")
        test = res_m[f"tail|{test_s}"]
        bt_out[m] = {"strata": strata,
                     "test": {k: test[k] for k in
                              ("n", "games", "hit", "lo", "hi", "coverage",
                               "candidates", "claimed", "floor_median",
                               "proj_median", "gap_median")},
                     "fit": {k: res_m[f"tail|{fit_s}"][k] for k in
                             ("n", "games", "hit", "lo", "hi")},
                     "median_gap": test["gap_median"],
                     "passes": F.passes(test, tgt),
                     "compare": res_m}
        print(f"  ships: {'yes' if F.passes(test, tgt) else 'NO — shown with a warning'}")

    print("\n=== at the book's price, where an alternate rung sat on the floor")
    mon = money(test_s, test_floor_rows)
    if mon.get("n"):
        print(f"  {mon['n']:,} floors over {mon['games']} games: hit {mon['hit']:.3f}, "
              f"implied {mon['implied']:.3f}, per $100 {mon['per_100']:+.2f} "
              f"[{mon['ci95'][0]:+.2f}, {mon['ci95'][1]:+.2f}]")
        for m, x in mon["markets"].items():
            print(f"    {m:16s} n={x['n']:5,d} hit {x['hit']:.3f} implied "
                  f"{x['implied']:.3f} per $100 {x['per_100']:+.2f} "
                  f"[{x['ci95'][0]:+.1f}, {x['ci95'][1]:+.1f}]")

    if args.no_write:
        return 0
    F.OUT_DIR.mkdir(parents=True, exist_ok=True)
    (F.OUT_DIR / F.CAL_FILE).write_text(json.dumps(
        {"kind": "floors_tail_calibration", "target": tgt,
         "fitted_on": [fit_s], "markets": cal_out}, indent=1))
    (F.OUT_DIR / F.BACKTEST_FILE).write_text(json.dumps(
        {"kind": "floors_backtest", "target": tgt, "fit_season": fit_s,
         "test_season": test_s, "markets": bt_out, "money": mon,
         "run_date": date.today().isoformat()}, indent=1))
    print(f"\n-> {F.OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
