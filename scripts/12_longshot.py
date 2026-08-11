#!/usr/bin/env python3
"""Measure how well we sort the longshot band, and publish it for the app.

    python scripts/12_longshot.py --target anytime_td

Requires backtest CSVs (scripts/10_backtest.py) so the measurement describes the
production path rather than raw model output.
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from src.evaluation.longshot import measure, save
from src.utils.config import get_config
from src.utils.paths import get_path


def main(target_type: str) -> int:
    stats = measure(target_type)
    if stats is None:
        print("Not enough backtest data — run scripts/10_backtest.py first.")
        return 1

    out = get_path("output", target_type) / "longshot_skill.json"
    save(stats, out)
    print(f"Longshot band (+{stats['min_odds']} and longer), "
          f"seasons {stats['seasons']}")
    print(f"  {stats['n']:,} player-games, {stats['scorers']} scorers")
    print(f"  our ordering  AUC {stats['auc_ours']:.4f}")
    print(f"  book ordering AUC {stats['auc_book']:.4f}")
    print(f"  gap {stats['auc_gap']:+.4f}  95% CI "
          f"[{stats['auc_gap_lo']:+.4f}, {stats['auc_gap_hi']:+.4f}]")
    print(f"  band is priced {stats['band_price_implied']:.1%} and hits "
          f"{stats['band_actual_rate']:.1%} — blind flat ROI "
          f"{stats['band_flat_roi']*100:+.1f}%")
    print(f"  our top decile: {stats['top_decile_per_week']:.1f}/week, hits "
          f"{stats['top_decile_actual']:.1%} against a price implying "
          f"{stats['top_decile_price_implied']:.1%}")
    print(f"\nSaved: {out}")
    return 0


if __name__ == "__main__":
    cfg = get_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=cfg["target"]["type"])
    a = ap.parse_args()
    sys.exit(main(a.target))
