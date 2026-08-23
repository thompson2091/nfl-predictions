#!/usr/bin/env python3
"""Grade the shortlist rule against results, and publish it for the app.

    python scripts/41_shortlist_backtest.py --target anytime_td

Replays what `make shortlist` would have shown, week by week, over every graded
backtest week, and stakes it flat at the archived closing price. The rule's one
tunable — the disagreement size below which closing-line value has moved
against us — is fitted walk-forward, from seasons strictly earlier than the one
being graded, so the number is not a threshold being marked on its own homework.

Four arms, because the question is never "did it return something" but "did it
return more than the simpler thing above it": every priced player, every player
we rate above the price, the shortlist, and the shortlist with the floor fitted
in hindsight — the ceiling a walk-forward rule cannot reach.

Requires backtest CSVs (scripts/10_backtest.py) and closing-line value
(scripts/13_clv.py) for the model being measured.
"""
from __future__ import annotations

import argparse
import json
import sys

sys.path.insert(0, ".")

from src.evaluation.shortlist_backtest import replay  # noqa: E402
from src.utils.config import get_config, production_model  # noqa: E402
from src.utils.paths import get_path  # noqa: E402


def main(target_type: str, model: str) -> int:
    stats = replay(target_type, model)
    if stats is None:
        print(f"No graded backtest or no line movement for {model} on "
              f"{target_type} — run scripts/10_backtest.py and "
              f"scripts/13_clv.py first.")
        return 1

    out = get_path("output", target_type) / "shortlist_backtest.json"
    out.write_text(json.dumps(stats, indent=2))

    print(f"SHORTLIST REPLAY — {target_type} / {model}")
    if stats["skipped_seasons"]:
        print(f"  {stats['skipped_seasons']} ungraded: no earlier season to "
              f"fit a floor from, so nothing there is screenable")
    graded = ", ".join(str(s) for s in stats["seasons"]) or "nothing"
    print(f"  graded: {graded}")
    for season, f in stats["floors"].items():
        where = ("stood down — no disagreement size had non-negative CLV"
                 if f is None else
                 f"floor {f['lo']:.0f} points (from {f['n']:,} earlier cases, "
                 f"{f['mean_move_pp']:+.2f}pp)")
        print(f"    {season}: {where}")
    if stats.get("hindsight_floor"):
        print(f"    hindsight floor, fitted on every season: "
              f"{stats['hindsight_floor']['lo']:.0f} points")

    print(f"\n  {'arm':<24}{'bets':>7}{'hit':>8}{'breakeven':>11}{'short':>8}"
          f"{'ROI':>9}{'95% interval':>20}")
    for a in stats["arms"]:
        p = a["pooled"]
        if p is None:
            print(f"  {a['arm']:<24}{'—':>7}  {a['note']}")
            continue
        ci = f"[{p['lo']:+.1f}, {p['hi']:+.1f}]"
        print(f"  {a['arm']:<24}{p['n']:>7,}{p['hit_pct']:>7.1f}%"
              f"{p['breakeven_pct']:>10.1f}%{p['breakeven_gap_pp']:>+7.1f}pp"
              f"{p['roi']:>+8.1f}%{ci:>20}")

    print("\n  If every price were better than the consensus close:")
    print(f"  {'arm':<24}" + "".join(f"{r['relative']:>10.1%}"
                                     for r in (stats["arms"][0]["pooled"] or
                                               {"shopped": []})["shopped"]))
    for a in stats["arms"]:
        p = a["pooled"]
        if p is None:
            continue
        print(f"  {a['arm']:<24}" + "".join(f"{r['roi']:>+9.1f}%"
                                            for r in p["shopped"]))
    print("  (a proportion of the implied price, not a flat number of points — "
          "see SHOPPING_REL. Line shopping measured about 5% on a live slate.)")

    print(f"\n  Saved: {out}")
    return 0


if __name__ == "__main__":
    cfg = get_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=cfg["target"]["type"])
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    sys.exit(main(a.target, a.model or production_model(a.target)))
