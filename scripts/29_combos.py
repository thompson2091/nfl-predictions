#!/usr/bin/env python3
"""Grade the combinations table against results, and publish it for the app.

    python scripts/29_combos.py --target anytime_td --model xgb

Replays the section's own rule over every graded backtest week — each game's
top N, every combination of L legs, the best K by the metric the app offers —
and grades each slip on whether every leg scored. The app reads what comes out;
without it the section says plainly that nothing in it has been backtested,
which is the honest state of affairs until this has run.

Requires backtest CSVs (scripts/10_backtest.py) for the model being measured.
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from src.evaluation.combo_backtest import lookup, measure, save
from src.utils.config import get_config, production_model
from src.utils.paths import get_path


def main(target_type: str, model: str) -> int:
    stats = measure(target_type, model)
    if stats is None:
        print(f"No graded backtest for {model} on {target_type} — "
              f"run scripts/10_backtest.py first.")
        return 1

    out = get_path("output", target_type) / "combo_backtest.json"
    save(stats, out)

    print(f"{target_type} / {model}: {stats['weeks']} weeks, "
          f"{stats['span']}, {len(stats['rows'])} measured settings")
    # The published default, spelled out, so a run says something a person can
    # check rather than only writing a file.
    for legs in (2, 3, 4):
        row = lookup(stats, legs=legs, per_game=4, metric="ev", show=25)
        if row is None:
            continue
        print(f"  {legs} legs, top 4 a game, best 25 by EV: "
              f"{row['slips']:,} slips, landed {row['landed']:.1%} "
              f"against {row['we_said']:.1%} said "
              f"(book {row['book_said']:.1%}), "
              f"${row['return_per_100']:+.2f} per $100")
    print(f"\nSaved: {out}")
    return 0


if __name__ == "__main__":
    cfg = get_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=cfg["target"]["type"])
    ap.add_argument("--model", default=None,
                    help="defaults to the target's production model")
    a = ap.parse_args()
    sys.exit(main(a.target, a.model or production_model(a.target)))
