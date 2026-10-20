#!/usr/bin/env python3
"""Fit how much of an Out player's projected work moves to his teammates.

See src/models/vacated.py. Per market, `beta` is fitted on 2024 and judged
on 2025, on players who played:

  - the model's own score: pinball loss for yards, squared error for catches;
  - log loss at the book's closing lines, the use the board makes of it;
  - the Out case itself: the active teammates' projection against what they
    gained, in team-games where a teammate projected for real work was Out.

A market's fit is written only when 2025 is no worse at the lines (the 95%
interval, clustered by game, does not sit above zero) and the Out gap
narrows. Otherwise any existing file is removed and the market is left as
the model says.

    python scripts/72_vacated.py
    python scripts/72_vacated.py --dry-run     # report, write nothing
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, ".")

import numpy as np
import polars as pl
from scipy.optimize import minimize_scalar

from src.evaluation import safe_legs as sl
from src.models import vacated as vac
from src.models.count import prob_over as count_over
from src.models.yards import QUANTILE_LEVELS, mean_of, prob_over
from src.prediction import receptions as rp
from src.prediction import yards as yp
from src.utils.paths import get_path

FIT, TEST = 2024, 2025
WEEKS = range(3, 19)
LV = np.asarray(QUANTILE_LEVELS)
#: An Out teammate counts as "real work" from this projected mean. Only the
#: report uses it; the fit uses every Out player.
REAL_WORK = {"rushing_yards": 30.0, "receiving_yards": 40.0, "receptions": 3.0}


def _feats(market: str, season: int, week: int) -> pl.DataFrame:
    df = (pl.scan_parquet(get_path("processed", "anytime_td") / "features.parquet")
          .filter((pl.col("season") == season) & (pl.col("week") == week)).collect())
    gate = yp.MARKETS.get(market, {}).get("gate")
    if gate and gate in df.columns:
        df = df.filter(pl.col(gate) == 1)
    if "position_DEFST" in df.columns:
        df = df.filter(pl.col("position_DEFST") != 1)
    return df


def frame(market: str, season: int, logs: pl.DataFrame):
    """Every played player-week: id, game, raw projection, slice, Out flag."""
    rows, qs, ns = [], [], 0
    art = rp.load_model() if market == "receptions" else yp.load_model(market)
    for w in WEEKS:
        df = _feats(market, season, w)
        if market == "receptions":
            got = rp.expected_counts(season, w, art, vacated=False)
            if got is None:
                continue
            mean, q = got["mu"].to_numpy(), None
            ids = got
        else:
            got = yp.expected_quantiles(market, season, w, art, vacated=False)
            if got is None:
                continue
            ids, q = got
            mean = mean_of(q)
        assert ids["player_id"].to_list() == df["player_id"].to_list(), "row order drifted"
        sl_ = vac.allocation(df, mean, market)
        out_mass = (df.with_columns(pl.Series("_m", mean))
                    .filter(pl.col("is_out").fill_null(0) == 1)
                    .group_by(["game_id", "team"]).agg(pl.col("_m").max().alias("_top")))
        d = ids.select(["season", "week", "game_id", "player_id", "team"]).with_columns(
            pl.Series("i", np.arange(ids.height) + ns), pl.Series("mean", mean),
            pl.Series("slice", sl_),
            pl.Series("out", (df["is_out"].fill_null(0) == 1).to_numpy()))
        d = d.join(out_mass, on=["game_id", "team"], how="left")
        rows.append(d)
        if q is not None:
            qs.append(q)
        ns += ids.height
    d = pl.concat(rows)
    q = np.concatenate(qs) if qs else None
    stat = "receptions" if market == "receptions" else market
    y = logs.select(["season", "week", "player_id", stat]).rename({stat: "y"})
    d = d.with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)).join(
        y, on=["season", "week", "player_id"], how="inner").filter(~pl.col("out"))
    return d, (q[d["i"].to_numpy()] if q is not None else None)


def adjusted(market, d, q, beta):
    m, s = d["mean"].to_numpy(), d["slice"].to_numpy()
    if market == "receptions":
        return m + beta * s, None
    qq = vac.scale_quantiles(q, m, s, beta)
    return mean_of(qq), qq


def score_rows(market, d, q, beta):
    y = d["y"].to_numpy()
    m, qq = adjusted(market, d, q, beta)
    if market == "receptions":
        return (y - m) ** 2
    e = y[:, None] - qq
    return np.mean(np.maximum(LV * e, (LV - 1) * e), axis=1)


def lines(season, market):
    spec = importlib.util.spec_from_file_location(
        "y49", Path(__file__).with_name("49_yards.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.graded_lines(season, market)


def line_ll(market, d, q, beta, gl, disp):
    k = d.select(["season", "week", "player_id"]).with_columns(
        pl.Series("_k", np.arange(d.height)))
    j = gl.with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)).join(
        k, on=["season", "week", "player_id"], how="inner")
    idx, pt = j["_k"].to_numpy(), j["point"].to_numpy()
    stat = "receptions" if market == "receptions" else market
    yr = j[stat].to_numpy()
    keep = yr != pt
    m, qq = adjusted(market, d, q, beta)
    if market == "receptions":
        over, push = count_over(m[idx], pt, disp)
    else:
        over, push = prob_over(qq[idx], pt)
    p = np.clip(over / np.clip(1 - push, 1e-9, None), 1e-6, 1 - 1e-6)
    y = (yr > pt).astype(float)
    ll = -(y * np.log(p) + (1 - y) * np.log(1 - p))
    return ll[keep], j["game_id"].to_numpy()[keep]


def clustered(diff, games, n_boot=2000, seed=0):
    g, inv = np.unique(games, return_inverse=True)
    s, n = np.bincount(inv, weights=diff), np.bincount(inv)
    rng = np.random.default_rng(seed)
    b = [s[p].sum() / n[p].sum() for p in (rng.integers(0, len(g), len(g)) for _ in range(n_boot))]
    return {"mean": float(diff.mean()), "ci95": [float(np.percentile(b, 2.5)),
                                                 float(np.percentile(b, 97.5))],
            "n": int(len(diff)), "games": int(len(g))}


def out_gap(market, d, q, beta):
    m, _ = adjusted(market, d, q, beta)
    x = d.with_columns(pl.Series("m", m)).filter(
        pl.col("_top").fill_null(0) >= REAL_WORK[market])
    t = x.group_by(["season", "week", "team"]).agg(pl.col("m").sum(), pl.col("y").sum())
    return {"team_games": t.height, "projected": float(t["m"].mean()),
            "actual": float(t["y"].mean())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logs = sl.game_logs()
    ws = (pl.scan_parquet(get_path("raw") / "weekly_stats.parquet")
          .select(["season", "week", "player_id", "receptions"]).collect()
          .with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)))
    logs = (logs.with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64))
            .join(ws, on=["season", "week", "player_id"], how="left")
            .with_columns(pl.col("receptions").fill_null(0)))
    disp = (rp.load_model() or {}).get("dispersion")
    report = {}
    for market in vac.RULES:
        print(f"\n=== {market} ===")
        dfit, qfit = frame(market, FIT, logs)
        dte, qte = frame(market, TEST, logs)
        r = minimize_scalar(lambda b: score_rows(market, dfit, qfit, b).mean(),
                            bounds=(0.0, 1.5), method="bounded")
        beta = float(r.x)
        games = dte["game_id"].to_numpy()
        own = clustered(score_rows(market, dte, qte, beta) - score_rows(market, dte, qte, 0.0), games)
        gl = lines(TEST, market)
        at_lines = None
        if gl is not None and gl.height:
            a, g = line_ll(market, dte, qte, beta, gl, disp)
            b0, _ = line_ll(market, dte, qte, 0.0, gl, disp)
            at_lines = clustered(a - b0, g)
        before, after = out_gap(market, dte, qte, 0.0), out_gap(market, dte, qte, beta)
        ok = (at_lines is None or at_lines["ci95"][1] <= 0 or at_lines["ci95"][0] < 0 < at_lines["ci95"][1]) \
            and abs(after["actual"] - after["projected"]) < abs(before["actual"] - before["projected"]) \
            and own["mean"] <= 0
        report[market] = {"beta": beta, "fitted_on": FIT, "judged_on": TEST,
                          "own_score_vs_raw": own, "line_log_loss_vs_raw": at_lines,
                          "out_case_before": before, "out_case_after": after, "kept": ok}
        print(f"  beta {beta:.3f} (fitted {FIT})")
        print(f"  {TEST} own score vs raw {own['mean']:+.5f} [{own['ci95'][0]:+.5f}, {own['ci95'][1]:+.5f}]")
        if at_lines:
            print(f"  {TEST} line log loss vs raw {at_lines['mean']:+.5f} "
                  f"[{at_lines['ci95'][0]:+.5f}, {at_lines['ci95'][1]:+.5f}] n={at_lines['n']:,}")
        print(f"  {TEST} Out case: projected {before['projected']:.1f} -> {after['projected']:.1f}"
              f" against {after['actual']:.1f} over {after['team_games']} team-games")
        print(f"  -> {'KEEP' if ok else 'leave as the model says'}")
        if not args.dry_run:
            p = vac.path(market)
            if ok:
                p.write_text(json.dumps(report[market] | {"fit_date": date.today().isoformat()},
                                        indent=1))
            elif p.exists():
                p.unlink()
    d = get_path("output", "vacated")
    d.mkdir(parents=True, exist_ok=True)
    (d / "summary.json").write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
