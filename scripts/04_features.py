#!/usr/bin/env python3
"""Build the feature matrix for a market — or for every market.

    python scripts/04_features.py                    # every market
    python scripts/04_features.py --target first_td  # just one

**Why this takes an argument now.** It used to build only the market named by
`config.target.type`, silently. When the NGS and weekly-stats existence leaks
were closed on 2026-08-18 that key read `anytime_td`, so anytime TD's matrix was
rebuilt through `spine.as_of_join` and first TD's was not — it kept its
same-week join for five days, and every first-TD number measured in that window
was read off a matrix that still leaked, including a walk-forward that was
reported as showing the market unaffected.

Nothing failed. The script did exactly what it was written to do, for one
market, and said nothing about the other.
"""
import argparse
import sys

sys.path.insert(0, ".")

from src.evaluation.harness import MARKETS
from src.features.assembler import assemble_features
from src.utils.config import config_overlay

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", choices=MARKETS,
                    help="build one market; omit to build every one")
    a = ap.parse_args()

    targets = [a.target] if a.target else list(MARKETS)
    for i, target in enumerate(targets, 1):
        print(f"\n=== features: {target} ({i} of {len(targets)}) ===", flush=True)
        with config_overlay({"target": {"type": target}}):
            assemble_features()
