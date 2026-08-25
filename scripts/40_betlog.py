#!/usr/bin/env python3
"""Log a bet, and score every logged bet against the closing line.

    python scripts/40_betlog.py --add --week 1 --player "Kyren Williams" \\
        --odds -120 --stake 25 --book williamhill_us
    python scripts/40_betlog.py                      # score what is logged

Beating the close is the only measurement that says whether an edge exists
before the bankroll does: a 20% hit rate at +450 needs hundreds of bets before
profit means anything, while closing-line value is readable in dozens. See
`src/evaluation/betlog.py` for the sign convention and why the vig is left in.

The log is `data/bets_placed.csv`, and it is a plain CSV on purpose — it is the
one file here that cannot be regenerated, so it stays editable by hand.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

sys.path.insert(0, ".")

from src.evaluation.betlog import LOG_PATH, record, score  # noqa: E402
from src.presentation import board as bp  # noqa: E402
from src.utils.config import get_config  # noqa: E402


def main(a) -> int:
    if a.add:
        for need in ("week", "player", "odds", "stake"):
            if getattr(a, need) in (None, ""):
                print(f"--add needs --{need}")
                return 1
        record({"placed_on": a.on or date.today().isoformat(),
                "season": a.season, "week": a.week, "market": a.target,
                "player": a.player, "book": a.book, "side": a.side,
                "odds": a.odds, "stake": a.stake, "note": a.note})
        print(f"Logged: {'LAY ' if a.side == 'no' else ''}{a.player} "
              f"{bp.american(a.odds)} for ${a.stake:.2f}"
              + (f" at {a.book}" if a.book else "")
              + f" — {a.target} {a.season} week {a.week}")

    s = score()
    if not s["n"]:
        print(s["note"])
        print(f"  Add one with --add, or edit {LOG_PATH} directly.")
        return 0

    print(f"\nBET LOG — {s['n']} bets, ${s['staked']:,.2f} staked")
    if s["scored"]:
        print(f"  {s['scored']} scored against a closing price: "
              f"mean CLV {s['mean_clv_pp']:+.2f}pp, "
              f"beat the close {s['beat_close_pct']:.0%} of the time")
    if s["unmatched"]:
        print(f"  {s['unmatched']} with no archived close yet — the capture "
              f"has not run for those weeks, or the name did not match")

    print(f"\n  {'Week':<6}{'Player':<24}{'Book':<16}{'Side':<5}{'Took':>7}"
          f"{'Closed':>8}{'CLV':>9}")
    for r in s["rows"]:
        closed = bp.american(r["close_odds"]) if r["close_odds"] else "—"
        clv = f"{r['clv_pp']:+.2f}pp" if r["clv_pp"] is not None else "—"
        print(f"  {str(r['week']):<6}{(r['player'] or '')[:23]:<24}"
              f"{(r['book'] or '')[:15]:<16}{(r.get('side') or 'yes'):<5}"
              f"{bp.american(r['odds']):>7}{closed:>8}{clv:>9}")

    if s["scored"]:
        print("\n  Positive CLV means the market moved toward your number after "
              "you took it. It is not profit and does not wait for one — which "
              "is exactly why it is the number to watch first.")
    return 0


if __name__ == "__main__":
    cfg = get_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--add", action="store_true", help="log a bet")
    ap.add_argument("--season", type=int, default=cfg["seasons"]["predict_season"])
    ap.add_argument("--week", type=int)
    ap.add_argument("--target", default=cfg["target"]["type"])
    ap.add_argument("--player")
    ap.add_argument("--book")
    ap.add_argument("--odds", type=float)
    ap.add_argument("--stake", type=float)
    ap.add_argument("--on", help="date placed, default today")
    ap.add_argument("--side", default="yes", choices=("yes", "no"),
                    help="'no' if you laid the player on an exchange — it "
                         "flips which way closing-line value counts")
    ap.add_argument("--note")
    sys.exit(main(ap.parse_args()))
