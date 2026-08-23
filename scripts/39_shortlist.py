#!/usr/bin/env python3
"""What survives every measurement, this week.

    python scripts/39_shortlist.py --week 1
    python scripts/39_shortlist.py --week 1 --target first_td

The bet card asks "where do we disagree with a price". This asks the harder
question: given closing-line value by disagreement size, the measured return of
every price band and every board rank, and the best number any archived book
posted — is there anything here worth money. Most weeks the answer is nothing,
and the script says which measurement emptied it rather than printing an empty
table.

Read `src/evaluation/shortlist.py` for what each filter is and why. Nothing here
claims the survivors are profitable: the filters remove what has been measured
worst, and what is left is not yet ruled out.
"""
from __future__ import annotations

import argparse
import json
import sys

sys.path.insert(0, ".")

from src.evaluation.line_shopping import best_vs_consensus  # noqa: E402
from src.evaluation.shortlist import shortlist  # noqa: E402
from src.prediction.bets import board_for_week  # noqa: E402
from src.presentation import board as bp  # noqa: E402
from src.utils.config import get_config, production_model  # noqa: E402
from src.utils.paths import get_path  # noqa: E402


def _load(path):
    return json.loads(path.read_text()) if path.exists() else None


def _fades(res: dict, out_dir) -> None:
    """The players we rate furthest below their price, and what that is worth.

    Printed even when the shortlist is empty, because on most weeks it is the
    only thing here with a measurement behind it: laying this group at the
    de-vigged price returned +25% on anytime TD across 2023-2025, on an
    interval clearing zero. No book sells that side — the number that decides
    whether it is reachable is how much margin a No price could carry, which
    the replay reports.
    """
    if not res.get("vetoes"):
        return
    rec = _load(out_dir / "shortlist_backtest.json") or {}
    f = rec.get("fade")
    print(f"\n  FADE \u2014 furthest below the price, the half no book sells")
    if f:
        print(f"    this group scored {f['scored_pct']:.1f}% against a "
              f"{f['priced_pct']:.1f}% de-vigged price over {f['n']:,} bets; "
              f"laying at fair returned {f['roi']:+.1f}% "
              f"[{f['lo']:+.1f}, {f['hi']:+.1f}]")
        print(f"    a No price could carry {f['margin_capacity_pct']:.2f}% of "
              f"margin before that is gone \u2014 on an exchange at 5% "
              f"commission it is {f['exchange'][-1]['roi']:+.1f}% per unit at risk")
    print(f"\n  {'Player':<24}{'Game':<12}{'Ours':>6}{'Book':>7}{'Gap':>7}{'Price':>8}")
    for r in res["vetoes"][:10]:
        print(f"  {r['player'][:23]:<24}{(r['game'] or '')[:11]:<12}"
              f"{r['ours']:>6.1%}{r['book']:>7.1%}{r['edge_pp']:>+7.1f}"
              f"{bp.american(r['odds']):>8}")


def main(season: int, week: int, target: str, model: str) -> int:
    board, status = board_for_week(season, week, target, model)
    if board.height == 0:
        print(status)
        return 1

    out_dir = get_path("output", target)
    clv = _load(out_dir / "clv.json")
    econ = _load(out_dir / "rank_economics.json")
    if clv is None or not clv.get("by_edge"):
        print("No closing-line value by disagreement size — run "
              "`python scripts/13_clv.py --target %s` first." % target)
        return 1

    shopped = best_vs_consensus(season, week, target)
    res = shortlist(board, target_type=target, clv=clv, econ=econ, shopped=shopped)

    print(f"SHORTLIST — {target} {season} week {week} ({model})")
    print(f"  {board.height} priced players on the board")
    for d in res["dropped"]:
        print(f"    -{d['dropped']:>4}  {d['filter']}   ({d['left']} left)")

    if not res["rows"]:
        print(f"\n  {res['note']}")
        print("  That is the answer, not a gap: every filter above is a "
              "measurement that says this population loses money.")
        _fades(res, out_dir)
        return 0

    f = res["floor"]
    print(f"\n  {len(res['rows'])} survive. Closing-line value in that band: "
          f"the market moved our way {f['moved_our_way']:.1%} of the time, "
          f"{f['mean_move_pp']:+.2f}pp on average, over {f['n']:,} cases.")
    print(f"\n  {'Player':<24}{'Game':<12}{'Ours':>6}{'Book':>7}{'Edge':>7}"
          f"{'Price':>8}{'Best':>8}  {'Shop':>7}  {'Band':>10}  Book")
    for r in res["rows"]:
        best = bp.american(r["best_odds"]) if r["best_odds"] else "\u2014"
        shop = f"{r['shopped_pp']:+.2f}pp" if r["shopped_pp"] is not None else "\u2014"
        band = (f"{r['band']} {r['band_roi']:+.0f}%" if r.get("band_roi") is not None
                else (r.get("band") or "\u2014"))
        print(f"  {r['player'][:23]:<24}{(r['game'] or '')[:11]:<12}"
              f"{r['ours']:>6.1%}{r['book']:>7.1%}{r['edge_pp']:>+7.1f}"
              f"{bp.american(r['odds']):>8}{best:>8}  {shop:>7}  {band:>10}  "
              f"{r['best_book'] or ''}")
    print("\n  Band is what every bet at that price returned over the whole "
          "population, vetoed players included — context for reading a row, "
          "never the reason it is on the list.")

    _fades(res, out_dir)
    path = out_dir / f"shortlist_{season}_week{week}.json"
    path.write_text(json.dumps(res, indent=2))
    print(f"\n  Saved: {path}")
    print("  Not a claim that these are profitable — see the module docstring.")
    return 0


if __name__ == "__main__":
    cfg = get_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=cfg["seasons"]["predict_season"])
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--target", default=cfg["target"]["type"])
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    sys.exit(main(a.season, a.week, a.target,
                  a.model or production_model(a.target)))
