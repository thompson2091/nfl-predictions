#!/usr/bin/env python3
"""Is the edge still there? Run this after every completed week.

    python scripts/17_decay.py --target anytime_td

A model that stops working does not announce it. The board keeps quoting a
three-season average while the thing it describes has gone, and the first
evidence is usually a bankroll rather than a number. This is the number.

Exits non-zero when the most recent season falls below the pooled interval, or
when the bets you have actually placed are running under what the backtest says
to expect — so it can be wired into a weekly job and be noticed.
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from src.evaluation.decay import by_recent_weeks, by_season, report
from src.utils.config import get_config


def main(target_type: str) -> int:
    print(report(target_type))
    season = by_season(target_type)
    recent = by_recent_weeks(target_type)

    alarms = []
    if season and season.get("latest_below_pooled_interval"):
        alarms.append("the most recent completed season is below the pooled range")
    if recent and recent.get("below_expectation"):
        alarms.append("bets actually placed are running below expectation")

    if alarms:
        print("\n" + "!" * 66)
        for a in alarms:
            print(f"  DECAY WARNING: {a}")
        print("  One season or a few weeks is not proof, but it is the first "
              "thing\n  that would show if this had stopped working. Do not "
              "size up on it.")
        print("!" * 66)
        return 1
    return 0


if __name__ == "__main__":
    cfg = get_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=cfg["target"]["type"])
    a = ap.parse_args()
    sys.exit(main(a.target))
