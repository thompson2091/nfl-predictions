#!/usr/bin/env python3
"""Score one week for a market — or for every market.

    python scripts/06_predict.py --season 2026 --week 1
    python scripts/06_predict.py --season 2026 --week 1 --target first_td

`--target` exists for the same reason it does in `04_features.py`: without it
this scores whichever market `config.target.type` names and says nothing about
the other, which is how first TD's served predictions came to describe a model
two promotions old while anytime TD's were current.
"""
import argparse
import sys

sys.path.insert(0, ".")

from src.evaluation.harness import MARKETS
from src.prediction.predict import predict
from src.utils.config import config_overlay

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--model", default=None,
                        help="Model name (default: from config)")
    parser.add_argument("--target", choices=MARKETS,
                        help="score one market; omit to score every one")
    args = parser.parse_args()

    targets = [args.target] if args.target else list(MARKETS)
    for target in targets:
        with config_overlay({"target": {"type": target}}):
            predict(args.season, args.week, args.model)
