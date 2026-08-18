#!/usr/bin/env python3
"""Did the market move toward us? Closing-line value on captured weeks.

    make open-line WEEK=n     # early in the week
    make odds WEEK=n          # near kickoff
    python scripts/13_clv.py

Reports nothing until both snapshots exist for some week — see
src/evaluation/clv.py for why this is the measurement worth waiting for.
"""
from __future__ import annotations

import argparse
import json
import sys

sys.path.insert(0, ".")

import polars as pl

from src.evaluation.clv import measure, line_movement
from src.utils.config import get_config
from src.utils.paths import get_path


def _write(stats: dict, moves: pl.DataFrame, target_type: str):
    """Persist the result, because a number nobody can look up later is not evidence.

    Every other evaluation here leaves an artifact — walkforward.json,
    rank_economics.json, longshot_skill.json — and CLV printed to stdout and
    kept nothing. That gap is not cosmetic: closing-line value is the highest-
    powered measurement this project has, roughly fifteen times the
    observations of the Top-1 walk-forward, and with no file on disk there is
    no way to ask whether a promoted version moved it, or to diff two versions
    on it at all. The verdict vocabulary matches rank_economics.json so the two
    economic readings can be compared without translating between them.
    """
    payload = dict(stats)
    payload["pairs"] = moves.height
    payload["games"] = moves["game_id"].n_unique()
    payload["verdict"] = ("positive" if stats["agree_pct"] > stats["null_hi"]
                          else "indistinguishable from zero")
    path = get_path("output", target_type) / "clv.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return path


def _predictions(target_type: str) -> pl.DataFrame | None:
    """Every published prediction CSV, keyed for joining to the archive."""
    import glob
    import re

    rows = []
    for path in sorted(glob.glob(str(get_path("output", target_type) /
                                     "predictions_*_week*.csv"))):
        m = re.search(r"predictions_(\d+)_week(\d+)\.csv", path)
        if not m:
            continue
        d = pl.read_csv(path)
        if "player_name" not in d.columns:
            continue
        # Prefer the pre-blend column. The published `probability` for anytime
        # TD is blended with the closing price and cannot be scored against it.
        src_col = next((c for c in ("prob_model", "prob_calibrated", "probability")
                        if c in d.columns), None)
        if src_col is None:
            continue
        d = d.with_columns(pl.col(src_col).alias("prob_calibrated"))
        rows.append(d.with_columns([
            pl.lit(int(m.group(1))).alias("season"),
            pl.lit(int(m.group(2))).alias("week"),
            # Loses to the backtest frame where both cover a player-game — see
            # the dedup note in clv.hit_rows.
            pl.lit(1).alias("_src_rank"),
        ]))
    from src.features.odds_features import _normalize_name  # noqa

    # Always add the backtest frames alongside any weekly prediction files.
    # The weekly files only cover weeks actually predicted — right now that is
    # the upcoming season, which has no settled line movement at all — while
    # the backtest holds the same published probability for every historical
    # week. Using both is what makes closing-line value answerable now instead
    # of one week at a time from Week 1.
    if True:
        for path in sorted(glob.glob(str(get_path("output", target_type) /
                                         "backtest_*.csv"))):
            season = int(path.rsplit("_", 1)[-1].split(".")[0])
            d = pl.read_csv(path)
            if "prob_calibrated" not in d.columns:
                continue
            rows.append(
                d.select(["game_id", "player_name", "prob_calibrated"])
                 .with_columns([pl.lit(season).alias("season"),
                                pl.lit(0).alias("_src_rank")])
            )
        if not rows:
            return None

    out = pl.concat(rows, how="diagonal_relaxed")
    return out.with_columns(
        pl.col("player_name").map_elements(_normalize_name, return_dtype=pl.Utf8)
        .alias("player_name_norm")
    )


def main(target_type: str) -> int:
    moves = line_movement(target_type)
    if moves is None or moves.height == 0:
        print("No opening/closing pairs yet.")
        print("  Capture both ends of a week:")
        print("    make open-line WEEK=n     (early in the week)")
        print("    make odds WEEK=n          (near kickoff)")
        return 0

    print(f"Line movement pairs: {moves.height:,} across "
          f"{moves['game_id'].n_unique()} games")

    preds = _predictions(target_type)
    if preds is None:
        print("No published predictions to compare against yet "
              "(scripts/06_predict.py).")
        return 0

    stats = measure(preds, target_type)  # defaults to the clean column
    if stats is None:
        print("Not enough overlap between predictions and captured lines yet.")
        return 0

    print(f"\nClosing-line value — {target_type}, seasons {stats['seasons']}")
    print(f"  {stats['n']:,} player-games where the price actually moved")
    print(f"  we disagree upward with the de-vigged open on "
          f"{stats['we_higher_pct']:.1%} of them")
    print()
    print(f"  market agreed with our direction: {stats['agree_pct']:.1%} "
          f"(+/- {stats['agree_se']:.1%})")
    print(f"  shuffling which players we like: {stats['null_pct']:.1%} "
          f"[{stats['null_lo']:.1%}, {stats['null_hi']:.1%}]")
    print(f"  edge over that null: {stats['edge_pts']:+.1f} points")
    print()
    if stats["move_when_higher"] is not None:
        print(f"  where we were higher ({stats['n_higher']:,}): line moved "
              f"{stats['move_when_higher']*100:+.2f}pp")
    if stats["move_when_lower"] is not None:
        print(f"  where we were lower  ({stats['n_lower']:,}): line moved "
              f"{stats['move_when_lower']*100:+.2f}pp")

    print()
    if stats["agree_pct"] > stats["null_hi"]:
        spread = None
        if stats["move_when_higher"] is not None and stats["move_when_lower"] is not None:
            spread = (stats["move_when_higher"] - stats["move_when_lower"]) * 100
        print("  Beats the null: the players we rate above the opening price are "
              "the ones the market then treats better.")
        if spread:
            print(f"  The market moves about {spread:.2f}pp further our way on the "
                  f"players we like than on the ones we do not.")
        print("  This is line movement, not money. It says our disagreement "
              "anticipates the market; it does not say a book would take the bet.")
    else:
        print("  Inside the null. On this evidence our disagreements do not "
              "anticipate the market.")

    print(f"\nSaved to {_write(stats, moves, target_type)}")
    return 0


if __name__ == "__main__":
    cfg = get_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=cfg["target"]["type"])
    a = ap.parse_args()
    sys.exit(main(a.target))
