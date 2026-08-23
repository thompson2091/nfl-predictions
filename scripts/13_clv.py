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
from datetime import datetime, timezone
import sys

sys.path.insert(0, ".")

import polars as pl

from src.evaluation.clv import (by_edge, hit_rows, line_movement,
                                measure, published_predictions)
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
    # Stamped because this is rebuilt by `make evaluate`, alongside the
    # backtests it reads, and the app shows it beside a live board. A figure
    # measured before the last retrain describes a model nobody is serving, and
    # without a date there is no way to tell from looking at it.
    payload["measured"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload["verdict"] = ("positive" if stats["agree_pct"] > stats["null_hi"]
                          else "indistinguishable from zero")
    path = get_path("output", target_type) / "clv.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return path


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

    preds = published_predictions(target_type)
    if preds is None:
        print("No published predictions to compare against yet "
              "(scripts/06_predict.py).")
        return 0

    stats = measure(preds, target_type)  # defaults to the clean column
    if stats is None:
        print("Not enough overlap between predictions and captured lines yet.")
        return 0

    # The headline is one number over every disagreement, which gates a
    # promotion and cannot read a pick. This is the same measurement split by
    # how far we sat from the open and — the part that decides everything —
    # which side of it we were on.
    rows = hit_rows(preds, target_type)
    stats["by_edge"] = by_edge(rows) if rows is not None else []
    if stats["by_edge"]:
        print("\n  by how far we sat from the open, and which side:")
        print(f"    {'side':<7}{'gap':<12}{'n':>7}  {'moved our way':>14}"
              f"  {'mean move':>10}")
        for r in stats["by_edge"]:
            band = (f"{r['lo']:.0f}+" if r["hi"] is None
                    else f"{r['lo']:.0f}-{r['hi']:.0f} pts")
            print(f"    {r['side']:<7}{band:<12}{r['n']:>7,}  "
                  f"{r['moved_our_way']:>13.1%}  {r['mean_move_pp']:>+9.2f}pp")

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
