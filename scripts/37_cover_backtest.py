#!/usr/bin/env python3
"""Grade the full-cover section against results. It has never been backtested.

    python scripts/37_cover_backtest.py --target anytime_td

`Cover the field` prices a cover from model probabilities and current odds — it
says what should happen. Until this ran, nothing said what did. Every figure in
that section was a projection built from a product of five estimates and five
prices, and a product compounds whatever is wrong with each term: a model two
points overconfident per leg is two points wrong on a single and closer to ten
on a five-fold.

Replays the section's own rule over every graded backtest week — the top N by
the published column, one player per game, every non-empty subset at a flat
stake — with the prices that were actually posted and the players who actually
scored. The app and the exported page read the result; without it both say
plainly that nothing in the section has been graded, which is the honest state
of affairs until this has run.

Requires backtest CSVs (scripts/10_backtest.py) for the model being measured.
Only priced legs are graded: a cover cannot be settled without a payout for
every leg, so the pool is whatever a book had posted that week.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.cover_backtest import load, measure, save  # noqa: E402
from src.utils.config import production_model  # noqa: E402
from src.utils.paths import get_path  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", default="anytime_td")
    ap.add_argument("--model", default=None,
                    help="Grade a specific model. Omit for the production one.")
    ap.add_argument("--stake", type=float, default=1.0)
    ap.add_argument("--show", action="store_true",
                    help="print the saved result without regrading")
    a = ap.parse_args()

    out = get_path("output", a.target) / "cover_backtest.json"
    model = a.model or production_model(a.target)

    stats = load(out) if a.show else measure(a.target, model, a.stake)
    if stats is None:
        print(f"No graded backtest for {model} on {a.target} — run "
              f"scripts/10_backtest.py first.")
        return 1
    if not a.show:
        save(stats, out)

    print(f"{a.target} / {model}: {stats['weeks']} weeks, {stats['span']}, "
          f"${stats['stake']:.2f} a slip\n")
    print(f"{'N':>2} {'weeks':>6} {'slips':>6} {'staked':>11} {'returned':>11} "
          f"{'cover':>8} {'singles':>8} {'profitable':>11} {'top week':>9}")
    for s in stats["sizes"]:
        print(f"{s['n']:>2} {s['weeks']:>6} {s['slips_per_week']:>6} "
              f"${s['staked']:>10,.0f} ${s['returned']:>10,.0f} "
              f"{s['roi']:>+7.1%} {s['singles_roi']:>+7.1%} "
              f"{s['weeks_profitable']:>4}/{s['weeks']:<5} "
              f"{s['top_week_share']:>8.1%}")

    best = max(stats["sizes"], key=lambda s: s["roi"])
    print()
    if best["roi"] > 0:
        print(f"Best measured size is {best['n']} at {best['roi']:+.1%}. Read "
              f"it against {best['weeks_profitable']} profitable weeks of "
              f"{best['weeks']} — a cover's return is carried by its rarest "
              f"outcomes, and the single best week is "
              f"{best['top_week_share']:.1%} of everything returned.")
    else:
        print(f"No pool size returned a profit. The best is {best['n']} at "
              f"{best['roi']:+.1%}.")
        worse = [s for s in stats["sizes"] if s["roi"] < s["singles_roi"]]
        if worse:
            print(f"{len(worse)} of {len(stats['sizes'])} sizes did worse than "
                  f"backing the same money on the singles, which is what a "
                  f"negative per-leg edge does when it is multiplied: a k-fold "
                  f"pays the margin k times.")

    print(f"\nWrote {out}  <- the app reads this")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
