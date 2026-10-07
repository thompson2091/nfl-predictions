#!/usr/bin/env python3
"""Write down what the prop edge rule says this week, before anyone plays.

    python scripts/64_prop_picks.py --week 5
    python scripts/64_prop_picks.py --week 5 --market receptions

**A RULE CAN ONLY BE TESTED FORWARD.** The two touchdown rules have been
recorded every week since week 1 by `39_shortlist.py`; the prop edge rule is
new and the four over/under markets never had a recording step at all, so
nothing in `tracked_picks.csv` can say what they would have bet. This is
that step. It records at the price available when it runs, and
`tracked_rules.record` refuses once the week has kicked off — a pick found
after the week starts is not a forward test.

**IDEMPOTENT, AND RUN REPEATEDLY ON PURPOSE.** `record` keys on
(season, week, market, rule, player), so the first sighting of a player is
the one kept and later runs only add players the board did not hold before.
That matters here more than on the touchdown markets: the over/under board
is thin early — week 5 held 29 receptions rows on the Tuesday against the
hundreds it will carry by Sunday — because the close captures have not
landed yet. Running on every rollover fills it in without double-counting.

**THE PRICE IS THE SIDE'S OWN.** `prop_edge` takes the under at the under's
price, not the over's, which is the whole subject of `prop_settlement`.

`team` is left empty: the over/under board does not carry one, and nothing
grades on it. `game` is the `"AWAY @ HOME"` label `tracked_rules.unfinished`
returns, so a Monday-night pick is not graded on the Sunday.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date

sys.path.insert(0, ".")

from src.evaluation.prop_edge import qualifying                  # noqa: E402
from src.evaluation.tracked_rules import (PICKS_PATH, record,    # noqa: E402
                                          rules_for)
from src.evaluation.week_history import ou_week                  # noqa: E402

MARKETS = ("receptions", "receiving_yards", "rushing_yards", "passing_yards")


def _label(game_id: str) -> str:
    """`2026_05_SF_SEA` -> `SF @ SEA`, which is what the picks file holds."""
    pair = re.sub(r"^\d{4}_\d{2}_", "", str(game_id or ""))
    bits = pair.split("_")
    return f"{bits[0]} @ {bits[1]}" if len(bits) == 2 else pair


def picks_for(season: int, week: int, market: str) -> list[dict]:
    rules = rules_for(market)
    if not rules:
        return []
    name = rules[0]["name"]
    rows = ou_week(season, week, market) or []
    out = []
    for r in qualifying(season, market, rows):
        if r.get("price") is None or r.get("side") is None:
            continue
        out.append({
            "rule": name, "player": r["player_name"], "team": None,
            "game": _label(r.get("game_id")),
            "odds": int(r["price"]), "ours": float(r["p_blend"]),
            "book": float(r["fair_prob"]), "edge_pp": float(r["edge_pp"]),
            "side": r["side"], "line": float(r["point"]),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--market", default=None, choices=MARKETS)
    ap.add_argument("--allow-late", action="store_true",
                    help="record after kickoff; for a backfill that means it")
    args = ap.parse_args()

    season = args.season
    if season is None:
        from src.utils.config import get_config
        season = int(get_config()["seasons"]["predict_season"])

    total = 0
    for market in ([args.market] if args.market else MARKETS):
        try:
            rows = picks_for(season, args.week, market)
        except Exception as e:                                   # noqa: BLE001
            print(f"  {market}: board unavailable ({e})", file=sys.stderr)
            continue
        rule = (rules_for(market) or [{}])[0]
        if not rows:
            print(f"  {market}: nothing clears "
                  f"{rule.get('threshold_pp')}pp this week.")
            continue
        n = record(rows, season=season, week=args.week, market=market,
                   recorded_on=date.today().isoformat(),
                   allow_late=args.allow_late)
        total += n
        print(f"  {market}: {len(rows)} qualify at "
              f"{rule.get('threshold_pp')}pp, {n} newly recorded")
        for r in rows:
            print(f"      {r['player'][:22]:<23}{r['game']:<11}"
                  f"{r['side']:>6} {r['line']:>6} "
                  f"{r['ours']:>6.1%}{r['book']:>7.1%}{r['edge_pp']:>+7.1f}"
                  f"{r['odds']:>7}")
    print(f"\n  {total} new picks -> {PICKS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
