#!/usr/bin/env python3
"""Refit the Gaps rule's threshold per over/under market, with provenance.

The rule (src/evaluation/prop_edge.py) bets where our blended number beats
the book's fair price by more than a fitted margin. The stored margins were
fitted once, by hand, against backtests from before the 2026-10-19 retrains,
and no script could reproduce them. This is that script; run it after any
retrain of the four over/under models.

Two numbers per market:
  - out of sample: the margin fitted on 2024 alone, scored on 2025;
  - served: the margin refitted on 2024 and 2025 together, which is what
    `models/<market>/edge_threshold.json` holds and the board uses.

    python scripts/73_gaps_thresholds.py
    python scripts/73_gaps_thresholds.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys

sys.path.insert(0, ".")

from src.evaluation import prop_edge as PE                      # noqa: E402
from src.utils.paths import get_path                            # noqa: E402


def served_weight(market: str) -> float | None:
    p = get_path("models", market) / "market_blend_served.json"
    if not p.exists():
        return None
    w = json.loads(p.read_text())
    return float(w.get("weight", w.get("model_weight")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    for market in PE.MARKETS:
        w = served_weight(market)
        if w is None:
            print(f"{market}: no served blend weight; skipped")
            continue
        fit = PE.backtest_frame(market, 2024, w)
        test = PE.backtest_frame(market, 2025, w)
        if fit is None or test is None:
            print(f"{market}: backtests missing; skipped")
            continue
        oos = PE.fit_threshold([fit])
        t = oos["threshold_pp"]
        n, roi = PE._score(test, t) if t is not None else (0, float("nan"))
        print(f"{market:16s} weight {w:.2f}  fit-2024 margin {t}  "
              f"-> 2025: {n} bets, {100 * roi:+.1f} per $100")
        # NOT SERVED WHEN IT FAILS OUT OF SAMPLE. The in-sample fit always
        # finds a margin that paid; a margin chosen on 2024 that loses on 2025
        # is that fit and nothing more. The rule then takes no bets on this
        # market until a refit passes, and the file says why.
        got = PE.refit(market, [2024, 2025], w, write=False)
        if got and not (roi == roi and roi > 0):
            got["threshold_pp"] = None
            got["withheld"] = (f"fitted on 2024 at {t}, scored on 2025: "
                               f"{n} bets, {100 * roi:+.1f} per $100")
        if got and not args.dry_run:
            from src.utils.history import write_kept
            write_kept(get_path("models", market) / PE.FILE, json.dumps(got, indent=1))
        if got:
            print(f"{'':16s} served margin {got['threshold_pp']} on 2024-25 "
                  f"({got['fit_n']} bets, in-sample {100 * got['fit_roi']:+.1f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
