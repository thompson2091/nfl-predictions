#!/usr/bin/env python3
"""The recon sheet: what a No price has to be, and what to write down.

    python scripts/45_lay_sheet.py --week 1
    python scripts/45_lay_sheet.py --week 1 --commission 0.02

The fade is the one thing in this project that measures positive, and it is on
the side no sportsbook posts. Everything about it is settled by a question no
backtest can reach: is there a venue, and is anyone there. This prints the
players the frozen rule names this week, the price their No side has to beat,
and a CSV with empty columns to fill in at an exchange.

Twenty minutes with an account answers it. See `src/evaluation/lay_sheet.py`
for the arithmetic, and in particular for why the spread turned out not to be
the binding constraint.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys

sys.path.insert(0, ".")

from src.evaluation.lay_sheet import (COMMISSIONS, cost_of_spread,  # noqa: E402
                                      sheet)
from src.prediction.bets import board_for_week  # noqa: E402
from src.presentation import board as bp  # noqa: E402
from src.utils.config import get_config, production_model  # noqa: E402
from src.utils.paths import get_path  # noqa: E402

#: Quotes to price the venue at, as a fraction above the fair Yes price. Wider
#: than anything a real order book should show, on purpose: the point of the
#: table is that even the absurd end of it survives.
SPREADS = (0.02, 0.05, 0.10, 0.20, 0.50, 1.00)

#: What the sheet leaves blank for the person at the screen. Written into the
#: CSV so the recon has somewhere to go that is not a text message to yourself.
OBSERVED = ("venue", "seen_lay_yes_dec", "seen_size", "checked_at", "notes")


def _venue_table(priced_pct: float, commission: float) -> None:
    print(f"\n  WHAT A WIDE QUOTE COSTS  (on the band's {priced_pct:.2f}% player)")
    print(f"  {'Yes lay quote':>14}{'vs fair':>9}{'No-side cost':>14}")
    for s in SPREADS:
        c = cost_of_spread(priced_pct / 100, s)
        if c:
            print(f"  {c['lay_yes_dec']:>14.2f}{s * 100:>8.0f}%"
                  f"{c['cost_pct']:>13.2f}%")
    print("  Capacity is measured on the No decimal and a spread is quoted on "
          "the Yes price;\n  the No side of a 7% player is nearly certain, so a "
          "wide Yes quote is a narrow No one.")


def _write(s: dict, a) -> None:
    """The sheet as a CSV with the observation columns left empty.

    Written for the probe list too, and with a `rule_pick` column, because the
    file has to survive being opened a week later by someone who no longer
    remembers which half of it was a recommendation.
    """
    rows = s["rows"] or s.get("probes") or []
    if not rows:
        return
    path = get_path("output", a.target) / f"lay_sheet_{a.season}_week{a.week}.csv"
    cols = ["player", "team", "game", "odds", "book_pct", "ours", "est_pct",
            "fair_no_dec", "floor_no_dec", "lay_yes_max_dec", "room_pct",
            "rule_pick", *OBSERVED]
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    print(f"\n  Saved: {path}  ({len(rows)} rows, "
          f"{len(OBSERVED)} columns for you to fill in)")


def _probe_rows(s: dict) -> None:
    """Names to check a price on when the rule itself names nobody.

    The rule's cut and the venue question are different questions: any player
    in the band tests whether an exchange quotes this market. Labelled so the
    two never get read as one list.
    """
    rows = s.get("probes") or []
    if not rows:
        return
    print(f"\n  NAMES TO CHECK A PRICE ON — in the band, nearest the "
          f"{s['measured']['priced_pct']:.2f}% the measurement was taken at.")
    print("  Not picks. This tests the venue, not the player.")
    print(f"\n  {'Player':<22}{'Game':<11}{'Book':>7}{'Ours':>7}{'Yes':>8}"
          f"{'Fair lay':>10}{'Worst lay':>11}{'Room':>8}  Rule")
    for r in rows:
        print(f"  {(r['player'] or '')[:21]:<22}{(r['game'] or '')[:10]:<11}"
              f"{r['book_pct']:>6.1f}%{r['ours'] * 100:>6.1f}%"
              f"{bp.american(r['odds']):>8}{1 / (r['book_pct'] / 100):>10.2f}"
              f"{r['lay_yes_max_dec']:>11.1f}{r['room_pct']:>7.2f}%"
              f"  {'pick' if r['rule_pick'] else ''}")


def _footer() -> None:
    print("\n  AT THE EXCHANGE, write down three things per player:")
    print("    1. is the market listed at all — anytime TD, by player")
    print("    2. the best lay price showing, and how much size is behind it")
    print("    3. whether it moves when you put an order in front of it")
    print("  If the answer to (1) is no, or (2) is $20, this edge has no home "
          "and\n  the price tolerance above does not matter. That is the "
          "result, and it is\n  worth having before week 1 rather than after.")


def main(a) -> int:
    model = a.model or production_model(a.target)
    board, status = board_for_week(a.season, a.week, a.target, model)
    if board.height == 0:
        print(status or "no board for that week")
        return 1

    out_dir = get_path("output", a.target)
    rec_path = out_dir / "shortlist_backtest.json"
    rec = json.loads(rec_path.read_text()) if rec_path.exists() else {}
    fade = rec.get("fade_in_band") or rec.get("fade")

    s = sheet(board, fade=fade, commission=a.commission, limit=a.limit)
    print(f"LAY SHEET — {a.target} {a.season} week {a.week} ({model})")
    if not s.get("measured"):
        print(f"  {s['note']}")
        # A measurement that came back empty is an answer and exits clean; only
        # a missing artifact is a failure. first TD hit this path on every run
        # since 2026-09-08 and returned 1 each time, which reads as the sheet
        # being broken rather than as the market having no band.
        return 1 if s.get("gap") else 0

    m = s["measured"]
    print(f"  rule: {s['rule']} — book between {s['band'][0]:.2f}% and "
          f"{s['band'][1]:.2f}%, we rate under {m['ratio']:.0%} of it")
    print(f"  measured on {m['n']:,} bets: scored {m['scored_pct']:.2f}% "
          f"against a {m['priced_pct']:.2f}% de-vigged price")
    print(f"  commission assumed {s['commission']:.0%}")

    _venue_table(m["priced_pct"], s["commission"])

    if not s["rows"]:
        print(f"\n  {s['note']}")
        _probe_rows(s)
        _write(s, a)
        _footer()
        return 0

    print(f"\n  {s['n_all']} named this week; showing {len(s['rows'])}. "
          f"'Worst lay' is break-even — a fill there is worth nothing.")
    print(f"\n  {'Player':<22}{'Game':<11}{'Book':>7}{'Ours':>7}{'Est':>7}"
          f"{'Yes':>8}{'Fair lay':>10}{'Worst lay':>11}{'Room':>8}")
    for r in s["rows"]:
        print(f"  {r['player'][:21]:<22}{(r['game'] or '')[:10]:<11}"
              f"{r['book_pct']:>6.1f}%{r['ours'] * 100:>6.1f}%"
              f"{r['est_pct']:>6.1f}%{bp.american(r['odds']):>8}"
              f"{1 / (r['book_pct'] / 100):>10.2f}"
              f"{r['lay_yes_max_dec']:>11.1f}{r['room_pct']:>7.2f}%")

    _write(s, a)
    _footer()
    return 0


if __name__ == "__main__":
    cfg = get_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=cfg["seasons"]["predict_season"])
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--target", default="anytime_td")
    ap.add_argument("--model", default=None)
    ap.add_argument("--commission", type=float, default=max(COMMISSIONS),
                    help="exchange take on winnings; 5%% is the pessimistic end")
    ap.add_argument("--limit", type=int, default=12)
    sys.exit(main(ap.parse_args()))
