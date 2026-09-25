"""Back every combination of the top N, and see what it would take to profit.

The `combos` module answers "which slips are worth backing". This answers a
different question: back them ALL — every non-empty subset of the top N — flat
stake on each, and show what has to happen to come out ahead.

    N = 5  ->  2^5 - 1 = 31 slips:  5 singles, 10 doubles, 10 trebles,
                                     5 four-folds, 1 five-fold

**Which slips are staked is a choice, and books only sell some of them.** The
full cover above is one structure among several. A sportsbook's round robin is
sold by leg-count — FanDuel's "By 2's" on six players is the 15 doubles and
nothing else — so a table that only ever prices the full cover is pricing a
wager the reader cannot actually place. `sizes` selects the leg-counts staked;
`None` keeps every one of them, which is the full cover and the default.

    sizes=None    6 players -> 63 slips   the full cover
    sizes=[2]     6 players -> 15 slips   FanDuel "By 2's"
    sizes=[2, 3]  6 players -> 35 slips   "By 2's and 3's"

It restricts *which slips are staked* and nothing else. Every outcome pattern
is still enumerated and priced leg by leg, the correlation term is untouched,
and the per-count rows are still a weighted summary rather than a count. The
temptation a structure creates is to report C(k, s) winning bets and call that
a return, which is the same error the next paragraph exists to forbid.

**Two things this must not get wrong.**

*Which* k score, not just how many. A "3 of 5 returns $15.38" table is only
true if every leg is the same price. Real boards are not: the top pick might be
-120 and the fifth +450, and three cheap legs return a fraction of what three
dear ones do. So nothing here aggregates by count first. Every one of the 2^N
outcome patterns is enumerated — 32 for N=5, trivial — priced exactly, and the
per-count rows are a weighted summary of those, carrying the spread as well as
the average.

Correlation. Teammates are not independent: two backs share goal-line carries,
and `portfolio.fit_correlation` measures the residual correlation at -0.024 on
anytime TD. Small, but the pattern probabilities are products of five terms and
the five-fold is the product of all of them, so it is applied rather than
assumed to be zero. Independence is available as a switch to show what the
assumption is worth.

**What a full cover actually is: leverage on the per-leg edge.** It cannot
manufacture an edge — the portfolio's expected value is the sum of its slips'
expected values, and nothing here creates information. What it does is compound
whatever edge each leg already has. Write a leg's edge as `e`, so that decimal
odds times true probability is `1 + e`. Then per dollar staked:

    a single    returns  e
    a k-fold    returns  (1 + e)^k - 1

For e > 0 the k-fold beats the single and the gap widens with k — parlays
*amplify* a real edge. For e < 0 the same arithmetic runs the other way and the
k-fold is strictly worse, because it pays the bookmaker's margin k times over.

So this section is a magnifying glass held over the one question that matters:
does a leg have edge at the price on offer? It does not answer that question,
it makes the answer louder. `scripts/14_rank_economics.py` currently reports
NEGATIVE on this market's headline strategy, which is why a full cover priced
off the board today comes out worse than backing the singles — but that is a
measurement about these prices, not a property of covering. An earlier draft of
this docstring claimed the dominance was unconditional; the test at
`tests/test_cover.py::test_whether_a_cover_beats_its_singles_turns_on_the_sign_of_the_edge`
disproves it in one line, which is why that test exists.

What the structure always changes is the SHAPE — many small losses against a
rare large win. The tables are built to make both visible rather than argue
either.
"""
from __future__ import annotations

from collections.abc import Iterable
from itertools import combinations
from math import comb

import numpy as np

#: Above this the enumeration is 2^N patterns x 2^N slips and the table stops
#: being readable long before it stops being computable.
MAX_PLAYERS = 12


def sizes_for(n: int, sizes: Iterable[int] | None = None) -> list[int]:
    """The leg-counts a structure actually stakes on `n` players, ascending.

    A size above `n` is dropped rather than refused: C(n, k) is zero there, so
    "By 4's" on three players is an empty stratum, not a mistake, and a reader
    who trims a player from the board should not get an exception for it. Zero
    and negative are refused, because a slip with no legs is not a bet. So is a
    selection that leaves nothing at all — staking no money is not a portfolio,
    and every ratio below it divides by the outlay.
    """
    if sizes is None:
        return list(range(1, n + 1))
    want = sorted({int(s) for s in sizes})
    if not want:
        raise ValueError("a structure must stake at least one slip size")
    if want[0] < 1:
        raise ValueError(f"a slip needs at least one leg, got {want[0]}")
    kept = [s for s in want if s <= n]
    if not kept:
        raise ValueError(
            f"no slip of size {want} exists on {n} player(s) — nothing would "
            f"be staked")
    return kept


def slips(n: int, sizes: Iterable[int] | None = None) -> list[tuple[int, ...]]:
    """The slips a structure stakes, shortest first.

    `sizes` is the leg-counts backed — `[2]` is a book's "By 2's", `[2, 3]` its
    "By 2's and 3's". `None` is every non-empty subset of `range(n)`: the full
    cover, and the default, so a caller that has never heard of the argument
    gets exactly what it always got.
    """
    if not 1 <= n <= MAX_PLAYERS:
        raise ValueError(f"n must be between 1 and {MAX_PLAYERS}, got {n}")
    out: list[tuple[int, ...]] = []
    for size in sizes_for(n, sizes):
        out.extend(combinations(range(n), size))
    return out


def slip_counts(n: int, sizes: Iterable[int] | None = None) -> list[dict]:
    """The bet-count table: how many slips of each size, and what they cost."""
    return [{"legs": k, "combinations": comb(n, k)}
            for k in sizes_for(n, sizes)]


def _pattern_probs(p: np.ndarray, rho: float = 0.0,
                   teams: list | None = None) -> np.ndarray:
    """Probability of each of the 2^n who-scored patterns, index = bitmask.

    With `rho` zero this is the product form. Non-zero up-weights same-direction
    pairs and down-weights opposing ones, renormalized so it stays a proper
    distribution.

    **The adjustment applies only between TEAMMATES.** What
    `portfolio.fit_correlation` measures is residual covariance within a
    team-game — two backs sharing goal-line carries — and there is no reason it
    holds between a Chargers receiver and a Bears one in a different stadium.
    Applying it to every pair inflated the tail of a cross-game cover: on a
    five-game slate it moved P(all five) from 0.0201 to 0.0260 on the strength
    of a number measured about teammates.

    `teams` is None only when the caller genuinely has one team, or does not
    know — in which case every pair is treated as a teammate pair, which is the
    conservative direction for a correlation that is currently positive.
    """
    n = len(p)
    idx = np.arange(1 << n)
    bits = ((idx[:, None] >> np.arange(n)) & 1).astype(float)
    probs = np.prod(np.where(bits == 1, p, 1 - p), axis=1)
    if not rho:
        return probs

    z = (bits - p) / np.sqrt(np.clip(p * (1 - p), 1e-9, None))
    if teams is None:
        same = np.ones((n, n)) - np.eye(n)
    else:
        t = np.array([str(x) for x in teams])
        same = (t[:, None] == t[None, :]).astype(float) - np.eye(n)
    if same.sum() == 0:                      # no teammates: independent
        return probs
    pair = np.einsum("ki,ij,kj->k", z, same, z) / 2.0
    probs = probs * np.exp(rho * pair)
    return probs / probs.sum()


def _decimal(odds) -> float | None:
    """American odds to decimal payout per unit staked, `None` if unpriced."""
    if odds is None or (isinstance(odds, float) and np.isnan(odds)):
        return None
    o = float(odds)
    if o == 0:
        return None
    return 1.0 + (o / 100.0 if o > 0 else 100.0 / abs(o))


#: How many priced players the stand-in is read off. Ten, because the number is
#: acutely sensitive to how deep it looks and a cover is built from the top of
#: the board: on week 1 of 2026 the median posted anytime-TD price is +106 over
#: the ten best-rated priced players, +277 over sixty of them and +360 over all
#: seventy-three, because the tail is full of 5% reserves nobody puts on a
#: slip. Ten is roughly `portfolio`'s own ceiling on cover size, so it is the
#: calibre of player the answer is about to be used for.
ASSUMED_FROM_TOP = 10


def assumed_price(probability, decimal, *, top_n: int = ASSUMED_FROM_TOP
                  ) -> float | None:
    """A stand-in decimal price for a leg no book has quoted.

    The median posted price over the `top_n` best-rated players a book has
    actually quoted on this market. It exists because "assume +100" means
    opposite things on the two markets: the best-rated anytime-TD players are
    odds-on and the best-rated first-TD ones pay seven times the stake, so one
    number carried across a market switch flatters one market and damns the
    other — and the payout table cannot say so, because it is built from prices
    and does not move when the probabilities do.

    Priced players are selected *first* and the top `top_n` taken from those,
    not the other way round. Taking the top of the board and keeping whichever
    of them happen to carry a price makes the answer depend on how many
    unpriced rows the caller's frame holds — which is why the app, whose board
    is priced-only, and the page, whose list is every rated player, read +277
    and +123 off the same slate under the other order.

    A median rather than a mean: the tail is long, and one +2500 reserve drags
    a mean somewhere no reader would recognize.

    `None` when no player on this market carries a price at all — a real state
    three weeks before a season opens, and one the caller has to answer for
    rather than being handed a number with nothing behind it.
    """
    p = np.asarray(list(probability), dtype=float)
    d = np.asarray([np.nan if x is None else x for x in decimal], dtype=float)
    if len(p) == 0 or len(p) != len(d):
        return None
    # A decimal price pays back more than the stake by construction; anything
    # at or below 1.0 is a missing value wearing a number.
    quoted = np.isfinite(d) & (d > 1.0) & np.isfinite(p)
    if not quoted.any():
        return None
    p, d = p[quoted], d[quoted]
    top = np.argsort(-p, kind="stable")[:int(top_n)]
    return float(np.median(d[top]))


#: Fewest priced players a curve may be fitted on. Below this the fit is
#: describing whichever handful a book happened to post rather than the market,
#: and the flat median is the more honest stand-in.
CURVE_MIN_POINTS = 8


def _logit(x: np.ndarray) -> np.ndarray:
    return np.log(x / (1.0 - x))


def price_curve(probability, decimal) -> dict | None:
    """What this market's books pay, as a function of what we rate a player.

    A single stand-in price cannot be right for a cover, because the legs a
    reader picks are the top of the board and the median priced player is not:
    on week 1 of 2026 the median anytime-TD price is +106, while a player we
    rate at 55% — which is what the default five look like — would be posted
    around -141. Assuming +106 for that leg is a 20% overstatement of every
    payout in the table, and the table cannot show it, because a payout column
    is built from prices and does not move when the probabilities do.

    So the stand-in is fitted rather than picked: a straight line through the
    priced players on the logit scale, implied probability against ours, which
    is monotone by construction and carries the market's margin curve with it —
    books hold far more on a 10% player than on a 50% one, and a flat price
    assumes the opposite.

    `lo`/`hi` bound the fitted range. `assumed_decimal` clamps to them rather
    than extrapolating: first TD has no player rated above 15%, and a line
    fitted there says a 55% player would be posted at +266, which is not a
    reading of any market — it is arithmetic run off the end of its evidence.

    `None` when too few players carry a price to fit anything.
    """
    p = np.asarray(list(probability), dtype=float)
    d = np.asarray([np.nan if x is None else x for x in decimal], dtype=float)
    if len(p) == 0 or len(p) != len(d):
        return None
    ok = (np.isfinite(d) & (d > 1.0) & np.isfinite(p) & (p > 0.0) & (p < 1.0))
    if ok.sum() < CURVE_MIN_POINTS:
        return None
    p, q = p[ok], 1.0 / d[ok]
    q = np.clip(q, 1e-6, 1 - 1e-6)
    b, a = np.polyfit(_logit(p), _logit(q), 1)
    return {"a": float(a), "b": float(b), "n": int(ok.sum()),
            "lo": float(p.min()), "hi": float(p.max())}


def assumed_decimal(curve: dict | None, prob: float) -> float | None:
    """The price to stand in for an unpriced leg we rate at `prob`."""
    if not curve or prob is None or not np.isfinite(prob):
        return None
    p = float(np.clip(prob, curve["lo"], curve["hi"]))
    if not 0.0 < p < 1.0:
        return None
    q = 1.0 / (1.0 + np.exp(-(curve["a"] + curve["b"] * _logit(np.array(p)))))
    q = float(np.clip(q, 1e-6, 1 - 1e-6))
    return 1.0 / q


def portfolio(players: list[dict], *, stake: float = 1.0,
              rho: float = 0.0, assumed_decimal: float | None = None,
              sizes: Iterable[int] | None = None) -> dict:
    """Price a cover of `players` and enumerate every outcome.

    `players` need `prob`; `odds` (American) is used when present. Where a
    player has no price, its own `assumed` (decimal) stands in, and failing
    that the flat `assumed_decimal` — that is what makes the table answerable
    on an unpriced board, and every row that used it is flagged so the number
    is never mistaken for a quote.

    `sizes` picks the round-robin structure: the leg-counts staked, `None` for
    every one of them. It changes which slips are bought and therefore the
    outlay; it changes nothing about how any of them is priced. `singles_only`
    stays the null to beat and is re-based on whatever this structure actually
    risks, so the two sides of that comparison are always the same money.

    Per leg rather than one price for all of them, because the legs differ: see
    `price_curve`. `priced` still counts only the legs a book actually quoted,
    so a filled-in price cannot pass itself off as a posted one.
    """
    n = len(players)
    if not 1 <= n <= MAX_PLAYERS:
        raise ValueError(f"need 1 to {MAX_PLAYERS} players, got {n}")

    p = np.array([float(x["prob"]) for x in players], dtype=float)
    dec, priced = [], []
    for x in players:
        d = _decimal(x.get("odds"))
        priced.append(d is not None)
        stand_in = x.get("assumed")
        if d is None and stand_in is not None and float(stand_in) > 1.0:
            d = float(stand_in)
        dec.append(d if d is not None else assumed_decimal)
    if any(d is None for d in dec):
        raise ValueError(
            "some legs have no price and no `assumed_decimal` to stand in for "
            "one; a return cannot be computed without a payout")
    dec = np.array(dec, dtype=float)

    staked_sizes = sizes_for(n, sizes)
    all_slips = slips(n, staked_sizes)
    n_slips = len(all_slips)
    total_staked = stake * n_slips
    pattern = _pattern_probs(p, rho, [x.get("team") for x in players])

    # Payout of the whole book under each pattern: a slip pays when every one
    # of its legs is in the pattern.
    returns = np.zeros(1 << n)
    hits = np.zeros(1 << n, dtype=int)
    for s in all_slips:
        mask = 0
        for i in s:
            mask |= 1 << i
        won = (np.arange(1 << n) & mask) == mask
        returns[won] += stake * float(np.prod(dec[list(s)]))
        hits[won] += 1

    k_of_n = ((np.arange(1 << n)[:, None] >> np.arange(n)) & 1).sum(axis=1)
    net = returns - total_staked

    rows = []
    for k in range(n + 1):
        m = k_of_n == k
        w = pattern[m]
        wsum = float(w.sum())
        r = returns[m]
        rows.append({
            "scored": k,
            "patterns": int(m.sum()),
            "winning_bets": int(hits[m][0]) if m.any() else 0,
            "probability": wsum,
            "returned": float((r * w).sum() / wsum) if wsum > 0 else float(r.mean()),
            "returned_min": float(r.min()), "returned_max": float(r.max()),
            "net": float((net[m] * w).sum() / wsum) if wsum > 0 else float(net[m].mean()),
        })

    ev = float((net * pattern).sum())
    return {
        "n": n, "stake": stake, "bets": n_slips, "staked": total_staked,
        "rho": rho, "all_priced": all(priced),
        "assumed_decimal": None if all(priced) else assumed_decimal,
        "legs": [{"name": x.get("name"), "team": x.get("team"), "prob": float(x["prob"]),
                  "odds": x.get("odds"), "decimal": float(d), "priced": bool(pr)}
                 for x, d, pr in zip(players, dec, priced)],
        "counts": slip_counts(n, staked_sizes),
        # The structure, and whether it is the full cover. Both are read by the
        # headline and by the export, which must not have to re-derive from
        # `counts` what the caller asked for.
        "sizes": staked_sizes,
        "full_cover": staked_sizes == list(range(1, n + 1)),
        "rows": rows,
        "expected_net": ev,
        "expected_roi": ev / total_staked if total_staked else 0.0,
        "breakeven_scored": next((r["scored"] for r in rows if r["net"] > 0), None),
        "p_breakeven": float(sum(r["probability"] for r in rows if r["net"] > 0)),
        # The comparison that matters: the same money on the singles alone.
        "singles_only": _singles(p, dec, total_staked, pattern, k_of_n),
    }


def _singles(p, dec, total, pattern, k_of_n) -> dict:
    """Backing the N singles for the same total outlay, as the null to beat.

    `total` is the structure's own outlay rather than a full cover's, because
    the comparison only means anything at equal money: a By 2's on six players
    risks $15, and the honest null is $15 spread over the six singles, not the
    $63 a full cover would have staked.
    """
    n = len(p)
    per = total / n
    ev = float(sum(per * (d * pi - 1.0) for d, pi in zip(dec, p)))
    return {"bets": n, "stake_each": per, "staked": total,
            "expected_net": ev, "expected_roi": ev / total if total else 0.0}


def ladder(decimal: float, max_n: int = MAX_PLAYERS, stake: float = 1.0,
           probs: list[float] | None = None) -> list[dict]:
    """How a full cover scales with N: risk, breakeven, and the all-score payout.

    At a flat price `decimal` per leg, N players means `2^N - 1` slips and k
    scorers return `(1 + d)^k - 1` per unit staked. The breakeven is the
    smallest k whose return clears the whole outlay.

    **The hit rate needed is not monotone in N, and that is the useful part.**
    At d = 1.667 it runs 100, 100, 100, 75, 80, 83.3, 71.4, 75, 77.8, 80 — N=4
    and N=7 are more forgiving than the sizes either side of them. The reason
    is arithmetic rather than football: the outlay doubles with each player
    while the return multiplies by (1 + d), so N lands sometimes just above and
    sometimes just below the point where one fewer scorer starts paying. Where
    it lands just below, a whole scorer comes off the requirement.

    Which N are forgiving therefore MOVES with the price. At 1.5 the pattern is
    different from at 2.0, so this is computed rather than tabulated, and the
    page recomputes it when the assumed price changes.

    `probs` optionally attaches how likely each row's requirement actually is,
    using the first N of the supplied per-player probabilities. Without it the
    table says what you need, not how often you get it — which is the half of
    the question that flatters a parlay.
    """
    if decimal <= 1:
        raise ValueError("decimal odds must exceed 1.0")
    out = []
    for n in range(1, max_n + 1):
        bets = 2 ** n - 1
        risk = stake * bets
        need = None
        for k in range(1, n + 1):
            if stake * ((1 + decimal) ** k - 1) > risk:
                need = k
                break
        all_score = stake * ((1 + decimal) ** n - 1)
        row = {
            "players": n, "bets": bets, "risk": risk,
            "need": need, "need_rate": (need / n) if need else None,
            "all_return": all_score, "all_profit": all_score - risk,
        }
        if probs and len(probs) >= n and need is not None:
            p = np.array(probs[:n], dtype=float)
            pat = _pattern_probs(p, 0.0)
            k_of_n = ((np.arange(1 << n)[:, None] >> np.arange(n)) & 1).sum(axis=1)
            row["p_need"] = float(pat[k_of_n >= need].sum())
            row["p_all"] = float(pat[k_of_n == n].sum())
        out.append(row)
    return out


def easiest(rows: list[dict]) -> list[int]:
    """Which N need the smallest share of their legs to land.

    A local minimum in `need_rate` — a size that asks less of you than both the
    size below and the size above. These are the structurally forgiving pool
    sizes at this price, and they are not where intuition puts them.
    """
    best = min((r["need_rate"] for r in rows if r["need_rate"] is not None),
               default=None)
    if best is None:
        return []
    return [r["players"] for r in rows if r["need_rate"] == best]
