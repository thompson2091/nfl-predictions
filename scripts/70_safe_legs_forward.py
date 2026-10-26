#!/usr/bin/env python3
"""The safe-legs paper record: the model's near-certain alternate legs, forward.

The 2024-25 backtest (scripts/69_safe_legs.py) found the model's 90%+ legs at
+1.28 per $100 on 2025, interval [-8.3, +10.1] over 88 legs — not an edge, and
too few to rule one out. This keeps the same rule running on games nobody had
seen when the rule was set, without money on it.

Every game is judged ONCE, after it is final, from the close prices captured
before kickoff, the model's as-of features and the calibration fitted on
2024. The legs it picked, or the fact that it picked none, are then frozen:
a later run never reselects a game, so retraining the model or moving the
threshold cannot rewrite what this record says it would have bet.

    python scripts/70_safe_legs_forward.py            # this season, from config
    python scripts/70_safe_legs_forward.py --season 2026
"""
from __future__ import annotations

import argparse
import json
import sys

sys.path.insert(0, ".")

import numpy as np
import polars as pl

from src.evaluation import safe_legs as sl
from src.utils.config import get_config
from src.utils.paths import get_path

#: The rules carried forward: the model alone, and model-and-history.
RULES = {"model": "p_model", "both": "p_both"}


def final_games(season: int) -> set[str]:
    s = pl.read_parquet(get_path("raw") / "schedules.parquet")
    return set(s.filter((pl.col("season") == season)
                        & pl.col("home_score").is_not_null())["game_id"].to_list())


def calibrated(r: pl.DataFrame, fits: dict) -> pl.DataFrame:
    """Apply the 2024 Platt fits the backtest wrote. No refitting here."""
    parts = []
    for market in sl.ALT_STAT:
        g = r.filter(pl.col("market") == market)
        if g.height == 0:
            continue
        for est in ("p_hist", "p_model"):
            f = fits[f"{market}:{est}"]
            raw = g[f"{est}_raw"].to_numpy().astype(float)
            cal = np.where(np.isnan(raw), np.nan,
                           sl.apply_platt(np.nan_to_num(raw, nan=0.5),
                                          (f["slope"], f["intercept"])))
            g = g.with_columns(pl.Series(est, cal).fill_nan(None))
        parts.append(g)
    return pl.concat(parts).with_columns(
        pl.min_horizontal("p_hist", "p_model").alias("p_both"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=None)
    args = ap.parse_args()
    season = args.season or get_config()["seasons"]["predict_season"]
    cfg = sl.settings()

    out_dir = get_path("output", "safe_legs")
    # The calibration is copied once per season and never re-read from the
    # backtest, which rewrites its summary on every run. A record whose
    # calibration moves under it is the rebuilt-from-current-state disease.
    frozen = out_dir / f"forward_{season}_calibration.json"
    if not frozen.exists():
        summary = out_dir / "summary.json"
        if not summary.exists():
            print("no calibration yet — run scripts/69_safe_legs.py first")
            return 1
        frozen.write_text(json.dumps(json.loads(summary.read_text())["fits"], indent=1))
    fits = json.loads(frozen.read_text())

    record_path = out_dir / f"forward_{season}.csv"
    judged_path = out_dir / f"forward_{season}_games.json"
    record = pl.read_csv(record_path) if record_path.exists() else None
    # A night that judged games and found no legs writes a header-only file.
    # Read back, every column of it is a string, and concatenating real legs
    # onto it turns `hit` into text whose mean is None (2026-10-26).
    if record is not None and record.height == 0:
        record = None
    judged = set(json.loads(judged_path.read_text())) if judged_path.exists() else set()

    r = sl.rungs([season])
    logs = sl.game_logs()
    # FINAL AND IN THE BOX SCORE. A game is judged once and never again, so
    # one judged in the hours between the final and the stats landing would
    # settle every rung to nothing and be frozen empty for good.
    stats_in = set(logs.filter(pl.col("season") == season)["game_id"].unique().to_list())
    todo = (final_games(season) & set(r["game_id"].unique().to_list()) & stats_in) - judged
    if todo:
        r = r.filter(pl.col("game_id").is_in(sorted(todo)))
        r = sl.settle(r, logs)
        r = sl.history_rates(r, logs, cfg["history_games"], cfg["history_min_games"])
        r = sl.model_probs(r).with_columns(
            pl.when(pl.col("hist_hits") >= 0)
              .then((pl.col("hist_hits") + 0.5) / (pl.col("hist_games") + 1.0))
              .alias("p_hist_raw"))
        r = calibrated(r, fits)
        new = []
        for rule, est in RULES.items():
            d = r.filter(pl.col(est).is_not_null() & (pl.col(est) >= cfg["min_prob"])
                         & (pl.col(est) - pl.col("implied_prob") >= cfg["min_edge"]))
            d = sl.best_rung(d, est)
            new.append(d.select([
                pl.lit(rule).alias("rule"), "season", "week", "game_id", "player_id",
                "player_name_raw", "market", "point", "odds", "implied_prob",
                "best_odds", "n_books", pl.col(est).alias("estimate"),
                pl.lit(cfg["min_prob"]).alias("min_prob"), "actual", "hit"]))
        new = pl.concat(new)
        record = new if record is None else pl.concat([record, new], how="vertical_relaxed")
        record.sort(["week", "game_id", "rule"]).write_csv(record_path)
        judged_path.write_text(json.dumps(sorted(judged | todo)))
        print(f"judged {len(todo)} new games; {new.height} legs added")
    else:
        print("no newly final games with alternate prices")

    if record is None or record.height == 0:
        print(f"{season}: no legs yet")
        return 0
    for rule in RULES:
        d = record.filter(pl.col("rule") == rule)
        if d.height == 0:
            print(f"  {rule:6s} no legs yet")
            continue
        s = sl.summarize(d)
        print(f"  {rule:6s} {s['n']:4d} legs  hit {s['hit_rate']:.1%}  price "
              f"{s['price_implied']:.1%}  per $100 {s['per_100']:+.2f} "
              f"[{s['ci95'][0]:+.1f}, {s['ci95'][1]:+.1f}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
