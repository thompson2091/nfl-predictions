#!/usr/bin/env python3
"""Print the forward record: the over/under picks written down before kickoff.

    python scripts/67_forward_report.py
    python scripts/67_forward_report.py --season 2026

**THE TUESDAY READ.** The weekly improvement loop is: grade last week's
forward picks, read the record per market, and treat a market as a candidate
for emphasis only once its 95% range clears break-even. This prints that read
at the end of `week_rollover.sh`. It changes nothing — the model moves only
at the season-end refit, and nothing reads this to move a threshold.
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=None)
    a = ap.parse_args()
    season = a.season
    if season is None:
        from src.utils.config import get_config
        season = int(get_config()["seasons"]["predict_season"])

    from src.evaluation.forward_record import block

    b = block(season)
    if not b["weeks"]:
        print(f"  forward record {season}: nothing recorded yet")
        return 0
    print(f"=== forward record {season}, from week {b['weeks'][0]} "
          f"({b['pending']} picks still pending)")
    for r in b["rules"]:
        if not r["all"]:
            print(f"  {r['label']:<22} nothing graded yet")
            continue
        x = r["all"]
        print(f"  {r['label']:<22} {x['bets']:>5} bets  {x['hit']:>6.1%} "
              f"correct, {x['be']:>6.1%} needed  {x['roi'] * 100:>+7.2f} per $100 "
              f"[{x['lo'] * 100:+.2f}, {x['hi'] * 100:+.2f}]")
        for m in r["markets"]:
            flag = "candidate" if m["candidate"] else "not yet"
            print(f"    {m['label']:<20} {m['bets']:>5} bets  {m['hit']:>6.1%} "
                  f"correct, {m['be']:>6.1%} needed  {m['roi'] * 100:>+7.2f} "
                  f"[{m['lo'] * 100:+.2f}, {m['hi'] * 100:+.2f}]  {flag}")
        if len(r.get("by_version") or {}) > 1:
            for v, x in r["by_version"].items():
                print(f"    version {v:<34} {x['bets']:>5} bets  "
                      f"{x['roi'] * 100:>+7.2f} per $100")
    c = b.get("clv") or {}
    for rule, x in c.items():
        print(f"  CLV {x['label']:<36} {x['mean']:+.2f}pp over {x['n']} picks "
              f"[{x['lo']:+.2f}, {x['hi']:+.2f}]  "
              + ", ".join(f"{m} {v:+.2f}" for m, v in x["markets"].items()))
    print("  A candidate is a market whose range clears break-even. Changes "
          "ship only at a promotion point, on evidence from past seasons. See "
          "docs/RECORD_LOOP.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
