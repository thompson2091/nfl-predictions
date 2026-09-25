#!/usr/bin/env python3
"""What each position scores, what it is charged, and what we say.

    python scripts/42_position_rates.py --target anytime_td

Three numbers the board makes a reader derive by eye — the realized rate for a
position, the de-vigged price it carries, and our own estimate — measured over
the priced population, which is the only one anybody can bet.

The gap between the last two is a calibration check the pooled figures cannot
give: a model two points hot on tight ends and two cold on backs looks perfect
in aggregate and is wrong on every row.
"""
from __future__ import annotations

import argparse
import json
import sys

sys.path.insert(0, ".")

from src.evaluation.position_rates import measure  # noqa: E402
from src.presentation import board as bp  # noqa: E402
from src.utils.config import get_config, production_model  # noqa: E402
from src.utils.paths import get_path  # noqa: E402


def main(target_type: str, model: str) -> int:
    d = measure(target_type, model)
    if d is None:
        print(f"No priced backtest joined to a feature matrix for {model} on "
              f"{target_type} — run scripts/10_backtest.py first.")
        return 1

    out = get_path("output", target_type) / "position_rates.json"
    out.write_text(json.dumps(d, indent=2))

    print(f"BY POSITION — {target_type} / {model}, {d['span']}, priced players")
    print(f"  {'pos':<6}{'player-weeks':>14}{'scored':>9}{'book says':>11}"
          f"{'we say':>9}{'median price':>14}{'all rated':>11}")
    for r in d["rows"]:
        ours = "—" if r["ours_pct"] is None else f"{r['ours_pct']:.1f}%"
        print(f"  {r['position']:<6}{r['priced_weeks']:>14,}"
              f"{r['scored_pct']:>8.1f}%{r['book_pct']:>10.1f}%{ours:>9}"
              f"{bp.american(r['median_odds']):>14}{r['all_rated_pct']:>10.1f}%")
    print("\n  `all rated` is the same rate over everyone the model rates, "
          "priced or not — far lower, because it counts deep reserves no book "
          "has ever posted a price for. It is context, not a bet.")
    print(f"\n  Saved: {out}")
    return 0


if __name__ == "__main__":
    cfg = get_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=cfg["target"]["type"])
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    sys.exit(main(a.target, a.model or production_model(a.target)))
