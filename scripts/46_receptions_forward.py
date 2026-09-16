#!/usr/bin/env python3
"""Re-measure the receptions model against the market, on the season being played.

`scripts/30_receptions.py` grades on held-out history and answers "was this
ever any good". This answers "is it any good now", which is a different
question and the one that matters after August: the backtest reads a backfilled
archive with exactly one closing price per line, while the live season is built
from captures that overlap, repeat, and keep quoting after kickoff.

    python scripts/46_receptions_forward.py            # the predict season
    python scripts/46_receptions_forward.py --season 2025

Exit codes are the point of running this on a schedule:

    0   the market is better calibrated than the model, as expected
    2   THE MODEL IS AHEAD OF THE MARKET
    3   nothing settled yet, which is the normal state early in a week

2 is not success. Every previous time this model has beaten this market it was
a leak — the first version returned +17-22% ROI and that was the NGS existence
leak, where the model could see whether a player had a tracking record, which
only exists for players who played. So the loud exit is on the good-looking
result, because that is the one nobody investigates.
"""
from __future__ import annotations

import argparse
import json
import sys

sys.path.insert(0, ".")

from src.evaluation.receptions_forward import record, report
from src.utils.config import get_config
from src.utils.paths import get_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--json", action="store_true",
                    help="print the record as JSON instead of a report")
    args = ap.parse_args()

    season = args.season or int(get_config()["seasons"]["predict_season"])
    r = record(season)
    if r is None:
        print(f"RECEPTIONS FORWARD — nothing settled yet for {season}.")
        return 3

    print(json.dumps(r, indent=1) if args.json else report(season))

    # Written beside the backtest summary so both live in one place, and so the
    # dashboard has something to read if the measurement ever gets expensive
    # enough to be worth caching.
    path = get_path("output", "receptions") / f"forward_{season}.json"
    path.write_text(json.dumps(r, indent=1))
    print(f"\nWrote {path}")
    return 2 if r["beats_market"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
