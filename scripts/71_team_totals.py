#!/usr/bin/env python3
"""Does tying receivers to their team's passing total make them more accurate?

The roster tab showed Purdy at 263 passing yards and his receivers' medians
adding to about 210. Measured on players who played, the receiving models'
MEANS add to 249 a team-game on 2025 against 224 actual (251 against 237 on
2024): a real overstatement, separate from the larger and harmless fact that
medians of skewed variables add to less than the median of the sum. The
starting quarterback's model, by contrast, averages 225 against 225.

So: scale each receiver's whole projected distribution by

    s = c * (QB mean / sum of the team's receiver means) ** alpha

`c` alone is a global correction for the bias; `alpha` is how far the team's
own passing projection should pull its receivers. Both are fitted on 2024 and
judged on 2025, which the served models never saw (trained through 2023,
early-stopped on 2024).

Judged three ways, on players who played:
  - pinball loss averaged over the fitted quantiles, the proper score for a
    quantile model;
  - calibration: mean PIT, and how often the result lands under the 10th or
    over the 90th percentile;
  - log loss at the book's closing lines, the use the board puts it to,
    with the interval clustered by game.

    python scripts/71_team_totals.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

import numpy as np
import polars as pl
from scipy.optimize import minimize

from src.evaluation import safe_legs as sl
from src.models.yards import QUANTILE_LEVELS, cdf, mean_of, prob_over, rearrange
from src.prediction.yards import expected_quantiles
from src.utils.paths import get_path

FIT, TEST = 2024, 2025
WEEKS = range(3, 19)
LV = np.asarray(QUANTILE_LEVELS)


def season_frame(season: int, logs: pl.DataFrame) -> tuple[pl.DataFrame, np.ndarray]:
    """Every candidate receiver with his quantiles and his team's QB mean.

    The team ratio is computed over ALL candidates, because who plays is not
    known before kickoff; the scoring is on those who played.
    """
    frames, qs, off = [], [], 0
    for w in WEEKS:
        rec = expected_quantiles("receiving_yards", season, w)
        pas = expected_quantiles("passing_yards", season, w)
        if rec is None or pas is None:
            continue
        rid, rq = rec
        pid, pq = pas
        rq, pq = rearrange(np.asarray(rq)), rearrange(np.asarray(pq))
        qb = (pid.with_columns(pl.Series("qb_mean", mean_of(pq)))
              .sort("qb_mean", descending=True)
              .group_by(["game_id", "team"]).agg(pl.col("qb_mean").first()))
        d = rid.with_columns(pl.Series("row", np.arange(rid.height) + off),
                             pl.Series("mean", mean_of(rq)))
        d = d.join(d.group_by(["game_id", "team"]).agg(pl.col("mean").sum()
                                                       .alias("team_mean")),
                   on=["game_id", "team"]).join(qb, on=["game_id", "team"])
        frames.append(d)
        qs.append(rq)
        off += rid.height
    d = pl.concat(frames).with_columns(
        (pl.col("qb_mean") / pl.col("team_mean")).alias("ratio"))
    q = np.concatenate(qs)
    # Played: a snap or a stat line. No snap and no stat is void.
    d = d.join(logs.select(["season", "week", "player_id", "receiving_yards"]),
               on=["season", "week", "player_id"], how="inner")
    return d, q[d["row"].to_numpy()]


def scale(d: pl.DataFrame, c: float, alpha: float) -> np.ndarray:
    return c * d["ratio"].to_numpy() ** alpha


def pinball(q: np.ndarray, y: np.ndarray) -> np.ndarray:
    e = y[:, None] - q
    return np.mean(np.maximum(LV * e, (LV - 1) * e), axis=1)


def pit(q: np.ndarray, y: np.ndarray, seed: int = 0) -> np.ndarray:
    lo, hi = cdf(q, y - 0.5, QUANTILE_LEVELS), cdf(q, y + 0.5, QUANTILE_LEVELS)
    return lo + np.random.default_rng(seed).random(len(y)) * (hi - lo)


def fit(d: pl.DataFrame, q: np.ndarray, free_alpha: bool) -> tuple[float, float]:
    y = d["receiving_yards"].to_numpy()

    def loss(p):
        c, a = (p[0], p[1]) if free_alpha else (p[0], 0.0)
        return pinball(q * scale(d, c, a)[:, None], y).mean()

    x0 = [1.0, 0.0] if free_alpha else [1.0]
    r = minimize(loss, x0, method="Nelder-Mead", options={"xatol": 1e-4, "fatol": 1e-7})
    return (float(r.x[0]), float(r.x[1]) if free_alpha else 0.0)


def lines(season: int) -> pl.DataFrame | None:
    spec = importlib.util.spec_from_file_location(
        "yards49", Path(__file__).with_name("49_yards.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.graded_lines(season, "receiving_yards")


def line_loss(d: pl.DataFrame, q: np.ndarray, s: np.ndarray,
              gl: pl.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per graded line: log loss of the scaled model's over, and its game."""
    k = d.select(["season", "week", "player_id"]).with_columns(
        pl.Series("_i", np.arange(d.height)))
    j = gl.join(k, on=["season", "week", "player_id"], how="inner")
    i = j["_i"].to_numpy()
    y_raw, pt = j["receiving_yards"].to_numpy(), j["point"].to_numpy()
    keep = y_raw != pt
    over, push = prob_over(q[i] * s[i][:, None], pt)
    p = np.clip(over / np.clip(1 - push, 1e-9, None), 1e-6, 1 - 1e-6)
    y = (y_raw > pt).astype(float)
    ll = -(y * np.log(p) + (1 - y) * np.log(1 - p))
    return ll[keep], j["game_id"].to_numpy()[keep], i[keep]


def clustered_diff(a: np.ndarray, b: np.ndarray, games: np.ndarray,
                   n_boot: int = 2000, seed: int = 0) -> dict:
    """Mean of (a - b) with a 95% interval resampled by game. Negative favors a."""
    diff = a - b
    g, inv = np.unique(games, return_inverse=True)
    sums = np.bincount(inv, weights=diff)
    ns = np.bincount(inv)
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(g), len(g))
        boots.append(sums[pick].sum() / ns[pick].sum())
    return {"mean": float(diff.mean()), "ci95": [float(np.percentile(boots, 2.5)),
                                                 float(np.percentile(boots, 97.5))],
            "n": int(len(diff)), "games": int(len(g))}


def report(d: pl.DataFrame, q: np.ndarray, s: np.ndarray) -> dict:
    y = d["receiving_yards"].to_numpy()
    qs = q * s[:, None]
    u = pit(qs, y)
    t = (d.with_columns(pl.Series("m", mean_of(qs)))
         .group_by(["game_id", "team"])
         .agg(pl.col("m").sum(), pl.col("receiving_yards").sum()))
    return {"pinball": float(pinball(qs, y).mean()),
            "mean_pit": float(u.mean()),
            "below_q10": float((u < 0.1).mean()), "above_q90": float((u > 0.9).mean()),
            "team_sum_of_means": float(t["m"].mean()),
            "team_actual": float(t["receiving_yards"].mean())}


def main() -> int:
    logs = sl.game_logs()
    print("building 2024 and 2025 frames")
    dfit, qfit = season_frame(FIT, logs)
    dtest, qtest = season_frame(TEST, logs)
    variants = {"raw": (1.0, 0.0),
                "global": fit(dfit, qfit, free_alpha=False),
                "team": fit(dfit, qfit, free_alpha=True)}
    gl = lines(TEST)
    out = {"fit": FIT, "test": TEST, "variants": {}}
    base_ll = None
    for name, (c, a) in variants.items():
        s = scale(dtest, c, a)
        r = report(dtest, qtest, s) | {"c": c, "alpha": a}
        yraw = dtest["receiving_yards"].to_numpy()
        r["pinball_rows"] = pinball(qtest * s[:, None], yraw)
        if gl is not None and gl.height:
            ll, games, _ = line_loss(dtest, qtest, s, gl)
            r["line_log_loss"] = float(ll.mean())
            r["_ll"], r["_games"] = ll, games
        out["variants"][name] = r
    raw = out["variants"]["raw"]
    for name in ("global", "team"):
        v = out["variants"][name]
        games = dtest["game_id"].to_numpy()
        v["pinball_vs_raw"] = clustered_diff(v["pinball_rows"], raw["pinball_rows"], games)
        if "_ll" in v:
            v["line_vs_raw"] = clustered_diff(v["_ll"], raw["_ll"], v["_games"])
    print(f"\nfit on {FIT}, judged on {TEST}; players who played; negative = better than raw\n")
    for name, v in out["variants"].items():
        print(f"  {name:7s} c={v['c']:.3f} alpha={v['alpha']:+.3f}  pinball {v['pinball']:.3f}  "
              f"PIT {v['mean_pit']:.3f}  <q10 {v['below_q10']:.3f}  >q90 {v['above_q90']:.3f}  "
              f"team means {v['team_sum_of_means']:.0f} vs {v['team_actual']:.0f}"
              + (f"  line LL {v['line_log_loss']:.4f}" if "line_log_loss" in v else ""))
        for k in ("pinball_vs_raw", "line_vs_raw"):
            if k in v:
                x = v[k]
                print(f"          {k:15s} {x['mean']:+.5f}  [{x['ci95'][0]:+.5f}, "
                      f"{x['ci95'][1]:+.5f}]  n={x['n']:,} over {x['games']} games")
    for v in out["variants"].values():
        for k in ("pinball_rows", "_ll", "_games"):
            v.pop(k, None)
    d = get_path("output", "team_totals")
    d.mkdir(parents=True, exist_ok=True)
    (d / "summary.json").write_text(json.dumps(out, indent=1))
    print(f"\n-> {d / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
