#!/usr/bin/env python3
"""Extract TD targets for every market, not just the configured one.

`extract_tds()` with no argument reads `target.type` from config, so running
this script only ever built the market that happened to be selected. The other
market's `tds_*.parquet` then sat at whatever season it was last built for —
which is invisible until a finished week fails to grade. On 2026-09-15 that was
week 1: anytime TD had its 73 scorers extracted and first TD had none, from the
same play-by-play.

The candidate builder reads these frames per market, so both have to be current
before `03_candidates.py` runs.
"""
import sys

sys.path.insert(0, ".")

from src.targets.td_extractor import extract_tds

MARKETS = ("anytime_td", "first_td")

if __name__ == "__main__":
    for market in MARKETS:
        print(f"\n=== targets: {market} ===")
        extract_tds(market)
