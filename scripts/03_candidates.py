#!/usr/bin/env python3
"""Build the candidate pool for a market — or for every market.

    python scripts/03_candidates.py                    # every market
    python scripts/03_candidates.py --target first_td  # just one

Takes an argument for the same reason `04_features.py` does. `build_candidates`
defaults to whatever `config.target.type` names, so `make candidates` rebuilt
one market and left the other's pool on disk from a previous run — the failure
that script's docstring describes, one stage earlier. It matters most after an
ingest: the pool is built from `rosters.parquet`, so a market that skips the
rebuild keeps scoring players who have since been cut.
"""
import argparse
import sys

sys.path.insert(0, ".")

from src.evaluation.harness import MARKETS
from src.targets.candidates import build_candidates
from src.utils.config import config_overlay

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", choices=MARKETS,
                    help="build one market; omit to build every one")
    a = ap.parse_args()

    targets = [a.target] if a.target else list(MARKETS)
    for i, target in enumerate(targets, 1):
        print(f"\n=== candidates: {target} ({i} of {len(targets)}) ===", flush=True)
        with config_overlay({"target": {"type": target}}):
            build_candidates(target)
