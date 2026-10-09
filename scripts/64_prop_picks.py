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


def _rule(market: str, kind: str) -> dict | None:
    return next((r for r in rules_for(market) if r.get("kind") == kind), None)


def picks_for(season: int, week: int, market: str,
              rows: list[dict] | None = None) -> list[dict]:
    rule = _rule(market, "prop_edge")
    if rule is None:
        return []
    name = rule["name"]
    rows = (ou_week(season, week, market) or []) if rows is None else rows
    # The unblended number each line was read from, which `qualifying` does
    # not carry through. Kept on the pick so the forward record can be cut by
    # the model's own confidence.
    model = {(r.get("game_id"), r.get("player_name"), float(r["line"])):
             r.get("model") for r in rows if r.get("line") is not None}
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
            "model": model.get((r.get("game_id"), r.get("player_name"),
                                float(r["point"]))),
        })
    return out


def model_side_for(season: int, week: int, market: str,
                   rows: list[dict] | None = None) -> list[dict]:
    """The unblended model's side on every priced line, one per player-game.

    The line kept is the one nearest the player's median line, chosen by
    `prop_edge.main_lines` before the side is read — the same rule the Record
    page's "Everyone" view applies — and the price is the side's own.
    """
    import polars as pl

    from src.evaluation.prop_edge import attach_prices, main_lines
    from src.evaluation.prop_settlement import _norm

    rule = _rule(market, "model_side")
    if rule is None:
        return []
    rows = (ou_week(season, week, market) or []) if rows is None else rows
    keep = [r for r in rows if r.get("model") is not None
            and r.get("line") is not None and r.get("game_id")]
    if not keep:
        return []
    names = _norm([r.get("player_name") or "" for r in keep])
    d = pl.DataFrame([{
        "game_id": r["game_id"], "player_name": r.get("player_name"),
        "player_name_norm": n, "player_key": n, "season": season, "week": 0,
        "point": float(r["line"]), "p_model": float(r["model"]),
        "p_blend": r.get("ours"), "fair_prob": r.get("book"),
        "team": r.get("team"),
    } for r, n in zip(keep, names)], infer_schema_length=None)
    d = attach_prices(main_lines(d), season, market)
    out = []
    for r in d.iter_rows(named=True):
        side = "over" if r["p_model"] >= 0.5 else "under"
        price = r["price_over"] if side == "over" else r["price_under"]
        if price is None:
            continue
        book = r.get("fair_prob")
        edge = None
        if book is not None:
            edge = (r["p_model"] - book) * 100 * (1 if side == "over" else -1)
        out.append({
            "rule": rule["name"], "player": r["player_name"],
            "team": r.get("team"), "game": _label(r["game_id"]),
            "odds": int(price),
            "ours": None if r.get("p_blend") is None else float(r["p_blend"]),
            "book": None if book is None else float(book),
            "edge_pp": None if edge is None else round(edge, 3),
            "side": side, "line": float(r["point"]),
            "model": float(r["p_model"]),
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
            board = ou_week(season, args.week, market) or []
            rows = picks_for(season, args.week, market, board)
            base = model_side_for(season, args.week, market, board)
        except Exception as e:                                   # noqa: BLE001
            print(f"  {market}: board unavailable ({e})", file=sys.stderr)
            continue
        if base:
            n = record(base, season=season, week=args.week, market=market,
                       recorded_on=date.today().isoformat(),
                       allow_late=args.allow_late)
            total += n
            print(f"  {market}: model side on {len(base)} lines, "
                  f"{n} newly recorded")
        rule = _rule(market, "prop_edge") or {}
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
