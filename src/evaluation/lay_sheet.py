"""What a No price has to be, player by player, for the fade to be worth taking.

Every other surface here reports the Yes price, because that is the only side a
sportsbook posts. The one thing in this project that measures positive is the
other side: inside the band where the book's own longshot bias pays, players we
rate under a third of its number scored 2.61% against a 6.92% de-vigged price.
That is an edge you can only collect by laying, and laying happens at an
exchange, at whatever two-sided price the order book is showing.

So the question that decides whether any of it is real is not another backtest.
It is: **can you get filled inside the room the measurement leaves?** This turns
that into something checkable at a screen in twenty minutes — for each player
the rule names this week, the fair No price, the worst No price still worth
taking, and a blank column to write down what the exchange was actually
offering.

**How the floor is derived.** The measured claim is a ratio: as a group, these
players score about 37.7% of their de-vigged price. Each player's estimate is
that same shrink applied to his own number — `q = book x scored/priced` — which
is a group mean worn by an individual, not a per-player forecast. It is what
the measurement supports and no more, and it is why the sheet reports the whole
band's `n` beside every row.

From `q`, backing No at decimal `D` breaks even when `(1 - q)(D - 1)(1 - c) = q`
for commission `c`. Above that price the fade pays; below it you are paying the
exchange for the privilege of being right. The gap between fair and the floor is
the same `margin_capacity` `shortlist_backtest.fade_side` reports, seen one
player at a time.

**The spread is not the constraint, and the earlier framing had it wrong.**
`fade_side` reports 4.63% of margin capacity and the note beside it compared
that to the 1-4% of spread a thin prop market embeds. Those are not the same
unit. Capacity is measured on the *No* decimal; a quoted spread is on the *Yes*
price, and the No side of a 7% player is nearly certain, so a wide Yes quote is
a narrow No one. `cost_of_spread` does the conversion: a lay price 10% worse
than fair costs 0.67% of the edge, and one at *double* fair still leaves room.
Break-even on a 6.9% player is laying his Yes side out at 36.5.

What that leaves is a different question, and the only one the recon can answer:
whether the venue lists these markets at all, and whether anyone is there to
take the other side. An edge with four points of price tolerance and no
counterparty is worth exactly as much as one with no tolerance.

**A fill at the floor is worth nothing.** The floor is break-even, so the number
to read is not "is the quote above it" but "how far above" — and, given the
above, mostly "was there any size at all".

Nothing here can be scored later: the archive holds Yes prices only, so a lay
gets its closing-line value by the sign flip in `betlog.SIDES` rather than from
a No close that was never captured.
"""
from __future__ import annotations

import math

from src.prediction.bets import decimal_to_american

#: What the exchanges take out of winnings. Not margin on the price — the price
#: is whatever another user will take — which is why a lay can be worth doing at
#: all where a book's No side never is.
COMMISSIONS = (0.02, 0.05)

#: The one to plan against. The US exchanges advertise between 1% and 5%; 5% is
#: the pessimistic end, and a recon that only clears at 2% has not cleared.
DEFAULT_COMMISSION = 0.05


def shrink_from(fade: dict | None, max_ratio: float) -> dict | None:
    """How far under its price this group actually landed, as a ratio.

    Read off the cut in `fade_side`'s ladder that matches the frozen rule's
    ratio rather than the band as a whole: the rule names players we rate under
    a third of the book, and the whole band includes ones we rate at nine
    tenths of it. Averaging those together would price the sheet off a
    population the rule does not pick.
    """
    if not fade:
        return None
    cuts = fade.get("cuts") or []
    best = min(cuts, key=lambda c: abs(float(c["ratio"]) - float(max_ratio)),
               default=None)
    if best is None or not best.get("priced_pct"):
        return None
    return {
        "shrink": float(best["scored_pct"]) / float(best["priced_pct"]),
        "n": int(best["n"]),
        "scored_pct": float(best["scored_pct"]),
        "priced_pct": float(best["priced_pct"]),
        "carries_pct": float(best["carries_pct"]),
        "ratio": float(best["ratio"]),
    }


def price_no(book_prob: float, shrink: float,
             commission: float = DEFAULT_COMMISSION) -> dict | None:
    """Fair, break-even and the room between, for one player's No side.

    `lay_yes_max` is the same floor expressed the way an exchange usually shows
    it — laying Yes at decimal `L` is backing No at `L / (L - 1)`, and a screen
    that quotes one will not quote the other.
    """
    p = float(book_prob)
    if not (0.0 < p < 1.0) or not math.isfinite(p):
        return None
    q = p * float(shrink)
    if not (0.0 <= q < 1.0):
        return None
    fair = 1.0 / (1.0 - p)
    floor = 1.0 + q / ((1.0 - q) * (1.0 - float(commission)))
    if floor <= 1.0:
        return None
    return {
        "book_pct": p * 100,
        "est_pct": q * 100,
        "fair_no_dec": fair,
        "fair_no_american": decimal_to_american(fair) if fair > 1.0 else None,
        "floor_no_dec": floor,
        "floor_no_american": decimal_to_american(floor),
        # Laying the Yes side instead: the highest Yes price still worth it.
        "lay_yes_max_dec": floor / (floor - 1.0),
        "commission": float(commission),
        # How much worse than fair a fill can be before the edge is gone. The
        # number to hold the exchange's spread against.
        "room_pct": (fair / floor - 1.0) * 100,
    }


def cost_of_spread(book_prob: float, spread: float) -> dict | None:
    """What a Yes lay quote `spread` above fair costs on the No side.

    The conversion the venue question turns on. Laying Yes at decimal `L` is
    backing No at `L / (L - 1)`, and that map is violently compressive at the
    long end: a 7% player's Yes price can be quoted half again too high and his
    No-equivalent barely moves, because the No side wins almost always and the
    whole quarrel is over a sliver of return.
    """
    p = float(book_prob)
    if not (0.0 < p < 1.0):
        return None
    lay = (1.0 + float(spread)) / p
    if lay <= 1.0:
        return None
    no_dec = lay / (lay - 1.0)
    fair = 1.0 / (1.0 - p)
    return {"spread": float(spread), "lay_yes_dec": lay, "no_dec": no_dec,
            "cost_pct": (1.0 - no_dec / fair) * 100}


def probes(board, rule: dict, measured: dict,
           commission: float = DEFAULT_COMMISSION, limit: int = 8) -> list[dict]:
    """In-band players to check a *price* on, whether or not the rule picks them.

    Two different questions get confused here. Whether a player is worth laying
    is the rule's question and it answers no most weeks. Whether the venue
    quotes a lay price on a 7% touchdown scorer at all is a question about the
    exchange, and any player in the band tests it equally well.

    So this returns the band's population sorted by how close each one sits to
    the price the measurement was taken at, and it is explicitly not a list of
    bets. On a four-game August board it is the only thing here with names on
    it, which is exactly when the recon wants doing.
    """
    if board is None or getattr(board, "height", 0) == 0:
        return []
    import polars as pl

    lo, hi = rule["min_book_pct"] / 100.0, rule["max_book_pct"] / 100.0
    at = measured["priced_pct"] / 100.0
    sel = board.filter((pl.col("market_prob") >= lo)
                       & (pl.col("market_prob") <= hi))
    out = []
    for r in sel.iter_rows(named=True):
        priced = price_no(r["market_prob"], measured["shrink"], commission)
        if priced is None:
            continue
        out.append({"player": r.get("player_name"), "team": r.get("team"),
                    "game": r.get("game_label"), "odds": int(r["odds"]),
                    "ours": float(r["prob_bet"]),
                    "book": float(r["market_prob"]),
                    "edge_pp": float(r["model_edge_pp"]),
                    "rule_pick": bool(r["prob_bet"]
                                      <= r["market_prob"] * float(rule["max_ratio"])),
                    **priced})
    out.sort(key=lambda r: abs(r["book"] - at))
    return out[:limit]


def sheet(board, *, fade: dict | None, rule: dict | None = None,
          commission: float = DEFAULT_COMMISSION, limit: int = 12) -> dict:
    """This week's fade picks, priced for the side you would have to take.

    Returns `rows` empty with a `note` rather than raising when the board holds
    nothing in the band — most weeks in August that is the true answer, and a
    sheet that invented rows would send you to an exchange to check a price for
    a player no rule named.
    """
    from src.evaluation.tracked_rules import RULES, picks

    if rule is None:
        rule = next((r for r in RULES if r.get("kind") == "lay"), None)
    if rule is None:
        return {"rows": [], "note": "no lay rule is defined"}
    sh = shrink_from(fade, rule.get("max_ratio", 1.0))
    if sh is None:
        return {"rows": [], "rule": rule["name"],
                "note": "no measured fade band on disk — run "
                        "`make shortlist-backtest` first"}

    rows = []
    for r in (picks(board, rule) if board is not None else []):
        priced = price_no(r["book"], sh["shrink"], commission)
        if priced is None:
            continue
        rows.append({**r, **priced})
    # Longest No price first: the widest room is where a thin book is likeliest
    # to still be inside the floor, so it is where the recon should start.
    rows.sort(key=lambda r: -r["room_pct"])
    return {
        "kind": "lay_sheet",
        "probes": probes(board, rule, sh, commission, limit),
        "rule": rule["name"],
        "band": [rule.get("min_book_pct"), rule.get("max_book_pct")],
        "max_ratio": rule.get("max_ratio"),
        "commission": float(commission),
        "measured": sh,
        "rows": rows[:limit],
        "n_all": len(rows),
        "note": (None if rows else
                 "nothing on this board is inside the band and rated far "
                 "enough under its price — normal on a short slate"),
    }
