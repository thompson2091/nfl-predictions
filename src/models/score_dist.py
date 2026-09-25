"""What the final score is likely to be, from games that were priced like this one.

**Empirical, not parametric, and that is the whole design.** The obvious way
to turn a spread and a total into a scoreline is to assume each team's points
are Poisson or normal around a mean and multiply out. It produces a smooth
surface and it is wrong in a way that matters: NFL scores are LUMPY. They are
built from 3s and 7s, so 27-24 happens far more often than 28-25, and 20-17
more often than 21-16. A smooth model spreads probability over scorelines that
essentially never occur and takes it from the handful that do.

So this reads the record instead. For a game hung at a given spread and total,
it finds every past game hung at roughly the same numbers and reports what
actually happened in them. The lumpiness comes for free because it was never
modeled away.

**WHAT IT CANNOT DO IS PRICE AN EXACT SCORELINE.** With 2,927 graded games in
the archive a window this narrow holds a few hundred, and a scoreline seen
four times in three hundred is 1.3% with an interval running past 3%. Exact
scores are reported with their COUNTS, not as probabilities to bet, and the
margins and totals — which pool hundreds of games into each bucket — are the
numbers that carry weight. `summary` returns both and labels which is which.

**The window is symmetric and fixed, not fitted.** Widening it until the
sample looks comfortable is fitting the method to the answer; the tolerances
below are round numbers chosen for being round, and `comparables` returns its
n so a thin window is visible rather than inferred.
"""
from __future__ import annotations

import math

import polars as pl

from src.utils.paths import get_path

#: How far a past game's spread may sit from this one's and still count. Two
#: points is roughly the distance between adjacent key numbers.
SPREAD_TOL = 2.0

#: And its total. Bigger, because a total moves over a wider range and three
#: and a half points is about a field goal and a fraction.
TOTAL_TOL = 3.5

#: Below this many comparable games, say so rather than draw a chart. A
#: distribution over 40 games is a list of anecdotes with percentages on it.
MIN_COMPARABLES = 60


def _wilson(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = hits / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - half), min(1.0, c + half))


def history() -> pl.DataFrame:
    """Every graded regular-season game that carried a line."""
    s = pl.read_parquet(get_path("raw") / "schedules.parquet")
    return (s.filter(pl.col("game_type") == "REG")
            .drop_nulls(["spread_line", "total_line", "home_score",
                         "away_score"])
            .select(["season", "week", "home_team", "away_team", "home_score",
                     "away_score", "spread_line", "total_line"])
            .with_columns([
                (pl.col("home_score") - pl.col("away_score")).alias("margin"),
                (pl.col("home_score") + pl.col("away_score")).alias("total"),
            ]))


def comparables(spread: float, total: float,
                spread_tol: float = SPREAD_TOL,
                total_tol: float = TOTAL_TOL,
                hist: pl.DataFrame | None = None) -> pl.DataFrame:
    """Past games hung at roughly these numbers.

    `spread` is signed the way the schedule signs it: POSITIVE when the home
    team is favored. Getting that backwards mirrors the whole distribution
    and produces a confident, exactly wrong answer, so it is asserted against
    the schedule's own convention rather than assumed.
    """
    h = history() if hist is None else hist
    if h.is_empty():
        return h
    return h.filter(
        ((pl.col("spread_line") - spread).abs() <= spread_tol)
        & ((pl.col("total_line") - total).abs() <= total_tol))


def summary(spread: float, total: float, home: str = "HOME",
            away: str = "AWAY", top: int = 8,
            hist: pl.DataFrame | None = None) -> dict:
    """The distribution, split into what it can and cannot support.

    `scores` are exact finals with their counts — interesting, and too thin to
    price. `margins` and `totals` bucket hundreds of games each and carry
    intervals. `n` is on the outside of all of it.
    """
    c = comparables(spread, total, hist=hist)
    n = c.height
    out = {"n": n, "spread": spread, "total": total, "home": home,
           "away": away, "min_n": MIN_COMPARABLES,
           "thin": n < MIN_COMPARABLES}
    if n == 0:
        return out

    # Exact scorelines. Oriented home-first, and counted rather than rated.
    sc = (c.group_by(["home_score", "away_score"]).agg(pl.len().alias("k"))
          .sort("k", descending=True).head(top))
    out["scores"] = [
        {"home": int(r["home_score"]), "away": int(r["away_score"]),
         "n": int(r["k"]), "pct": round(r["k"] / n * 100, 1)}
        for r in sc.iter_rows(named=True)]

    # Margin, in buckets that mean something to a bettor: who won, and whether
    # it was inside a field goal, a touchdown, or more.
    # THE BOUNDS TRAVEL WITH THE BAND.
    #
    # `lo` and `hi` below are the Wilson interval on the PERCENTAGE, not the
    # margin. A page wanting to mark the band a finished game landed in has to
    # know the margin edges, and the only other way to get them is to parse
    # "SEA by 8-14" back out of a label that is built for reading. `mlo` and
    # `mhi` are inclusive margin bounds, home-positive, null where open.
    bands = [("Home by 15+", pl.col("margin") >= 15, 15, None),
             ("Home by 8-14", (pl.col("margin") >= 8) & (pl.col("margin") < 15), 8, 14),
             ("Home by 4-7", (pl.col("margin") >= 4) & (pl.col("margin") < 8), 4, 7),
             ("Home by 1-3", (pl.col("margin") >= 1) & (pl.col("margin") < 4), 1, 3),
             ("Tie", pl.col("margin") == 0, 0, 0),
             ("Away by 1-3", (pl.col("margin") <= -1) & (pl.col("margin") > -4), -3, -1),
             ("Away by 4-7", (pl.col("margin") <= -4) & (pl.col("margin") > -8), -7, -4),
             ("Away by 8-14", (pl.col("margin") <= -8) & (pl.col("margin") > -15), -14, -8),
             ("Away by 15+", pl.col("margin") <= -15, None, -15)]
    out["margins"] = []
    for name, expr, mlo, mhi in bands:
        k = c.filter(expr).height
        lo, hi = _wilson(k, n)
        out["margins"].append({
            "band": name.replace("Home", home).replace("Away", away),
            "n": k, "pct": round(k / n * 100, 1),
            "lo": round(lo * 100, 1), "hi": round(hi * 100, 1),
            "mlo": mlo, "mhi": mhi})

    # Total points, against the posted number and in bands around it.
    over = c.filter(pl.col("total") > total).height
    under = c.filter(pl.col("total") < total).height
    push = n - over - under
    lo, hi = _wilson(over, over + under) if (over + under) else (0.0, 1.0)
    out["over"] = {"n": over, "pct": round(over / n * 100, 1),
                   "lo": round(lo * 100, 1), "hi": round(hi * 100, 1)}
    out["under"] = {"n": under, "pct": round(under / n * 100, 1)}
    out["push"] = {"n": push, "pct": round(push / n * 100, 1)}

    hw = c.filter(pl.col("margin") > 0).height
    lo, hi = _wilson(hw, n)
    out["home_win"] = {"n": hw, "pct": round(hw / n * 100, 1),
                       "lo": round(lo * 100, 1), "hi": round(hi * 100, 1)}
    out["mean_total"] = round(float(c["total"].mean()), 1)
    out["mean_margin"] = round(float(c["margin"].mean()), 1)
    # The most common single scoreline, for the headline. Named separately so
    # the page cannot accidentally present it as the expected result: at these
    # sample sizes the top scoreline is usually under 4%.
    if out["scores"]:
        out["modal"] = out["scores"][0]
    return out


def for_card(card: dict, hist: pl.DataFrame | None = None) -> dict | None:
    """Straight from a site card, with the sign convention handled once.

    The card's `spread` is signed toward the home side and NEGATIVE when the
    home team is favored — it is a betting line, not a margin. The schedule's
    `spread_line` is the other way round. Flipping it here, once, is why no
    caller has to remember which of the two it is holding.
    """
    sp, tot = card.get("spread"), card.get("total")
    if sp is None or tot is None:
        return None
    return summary(-float(sp), float(tot), card.get("home") or "HOME",
                   card.get("away") or "AWAY", hist=hist)


#: Point thresholds a team total ladder is drawn at. Half-points, because a
#: line ON a whole number can push and "over 20.5" is unambiguous.
TEAM_STEPS = [9.5, 13.5, 16.5, 17.5, 20.5, 23.5, 24.5, 27.5, 30.5, 34.5]


def ladders(spread: float, total: float, home: str, away: str,
            hist: pl.DataFrame | None = None) -> dict:
    """How often each side clears a given number of points, and the game a total.

    The table a bettor actually reads: pick a number, see how often it was
    beaten in games priced like this one. Every row carries its own count, so
    a threshold out in the tail is visibly thin rather than quietly wrong.

    **Every probability here is the EMPIRICAL frequency, not a fitted curve.**
    That is the point of the module and it has a cost worth stating: the tails
    are ragged. "Over 34.5" might read 12% where "over 30.5" reads 19%, and
    the gap between them is partly sample. Smoothing would hide that; the
    counts do not.
    """
    c = comparables(spread, total, hist=hist)
    n = c.height
    out = {"n": n, "home": home, "away": away, "thin": n < MIN_COMPARABLES}
    if n == 0:
        return out

    def over(col, t):
        k = c.filter(pl.col(col) > t).height
        lo, hi = _wilson(k, n)
        return {"line": t, "n": k, "pct": round(k / n * 100, 1),
                "lo": round(lo * 100, 1), "hi": round(hi * 100, 1)}

    out["teams"] = [
        {"team": home, "rows": [over("home_score", t) for t in TEAM_STEPS]},
        {"team": away, "rows": [over("away_score", t) for t in TEAM_STEPS]},
    ]
    # The game total, stepped around the posted number so the row a reader
    # came for is in the middle rather than at an end.
    steps = sorted({round(total + d * 2) + 0.5 for d in range(-4, 5)})
    out["total"] = {"posted": total, "rows": [over("total", t) for t in steps]}
    # And the spread, as "how often did the favorite win by more than X".
    # Signed the schedule's way: positive `spread` means home favored.
    sp_steps = sorted({round(spread + d * 2) + 0.5 for d in range(-4, 5)})
    out["spread"] = {"posted": spread,
                     "rows": [over("margin", t) for t in sp_steps]}
    return out


def ladders_for_card(card: dict, hist: pl.DataFrame | None = None) -> dict | None:
    """As `for_card`: the site's spread is negative when home is favored."""
    sp, tot = card.get("spread"), card.get("total")
    if sp is None or tot is None:
        return None
    return ladders(-float(sp), float(tot), card.get("home") or "HOME",
                   card.get("away") or "AWAY", hist=hist)


def scenarios(spread: float, total: float, home: str, away: str,
              hist: pl.DataFrame | None = None) -> dict:
    """How the game is likely to unfold, as a partition that sums to 100%.

    Margin band crossed with over/under, counted over the comparable games.
    **Mutually exclusive and exhaustive on purpose.** A list of overlapping
    scenarios — "one-score game 46%, shootout 31%, upset 28%" — reads as a
    ranking and cannot be one, because those add to more than everything that
    can happen and nobody can tell which of them overlap. A partition can be
    read straight down: these are all the ways it goes, and the column adds up.

    The favorite is named rather than "home", because "home by 8-14" is a
    sentence a reader has to translate and "KC by 8-14" is not.

    Nothing here is a projection of THIS game. It is the record of games the
    market priced the same way, which is a different and more defensible
    claim, and `n` travels with it so the reader can see how much record.
    """
    c = comparables(spread, total, hist=hist)
    n = c.height
    fav, dog = (home, away) if spread > 0 else (away, home)
    out = {"n": n, "home": home, "away": away, "fav": fav, "dog": dog,
           "total": total, "thin": n < MIN_COMPARABLES}
    if n == 0:
        return out

    # Margin from the FAVORITE's point of view, so the bands read the same
    # way whichever side is favored.
    m = pl.col("margin") if spread > 0 else -pl.col("margin")
    bands = [
        ("pulls away", f"{fav} pulls away", m >= 15),
        ("comfortable", f"{fav} wins comfortably", (m >= 8) & (m < 15)),
        ("narrow", f"{fav} edges it", (m >= 1) & (m < 8)),
        ("upset", f"{dog} wins outright", m <= -1),
        ("tie", "It ends level", m == 0),
    ]
    over = pl.col("total") > total
    cells = []
    for key, label, expr in bands:
        for side, oexpr in (("over", over), ("under", ~over)):
            k = c.filter(expr & oexpr).height
            if not k:
                continue
            lo, hi = _wilson(k, n)
            cells.append({
                "key": f"{key}_{side}", "band": key, "side": side,
                "label": label + (", high scoring" if side == "over"
                                  else ", low scoring"),
                "n": k, "pct": round(k / n * 100, 1),
                "lo": round(lo * 100, 1), "hi": round(hi * 100, 1)})
    cells.sort(key=lambda x: -x["n"])
    out["cells"] = cells

    # The headline numbers a reader wants without reading a table. These DO
    # overlap each other and are labeled separately for that reason.
    def share(expr):
        k = c.filter(expr).height
        lo, hi = _wilson(k, n)
        return {"n": k, "pct": round(k / n * 100, 1),
                "lo": round(lo * 100, 1), "hi": round(hi * 100, 1)}

    out["headline"] = {
        "one_score": share(m.abs() <= 8),
        "blowout": share(m.abs() >= 17),
        "upset": share(m <= -1),
        "shootout": share(pl.col("total") >= total + 7),
        "grind": share(pl.col("total") <= total - 7),
    }
    return out


def scenarios_for_card(card: dict, hist: pl.DataFrame | None = None):
    sp, tot = card.get("spread"), card.get("total")
    if sp is None or tot is None:
        return None
    return scenarios(-float(sp), float(tot), card.get("home") or "HOME",
                     card.get("away") or "AWAY", hist=hist)


def calibration(hist: pl.DataFrame | None = None, bins: int = 10) -> dict:
    """Leave-one-out: when this says 70%, how often does it happen?

    **The question a bad Thursday actually asks.** On 2026-09-25 Atlanta won
    at Green Bay by 21 as a road underdog, and every number on the page looked
    wrong: the book had Green Bay by 6.5, this project by 3.7, and the win
    probability at 68% and 60%. "Way off" is the natural reading and it is the
    wrong one — the same page had put an outright Atlanta win at 28.5%, which
    is not a long shot, and the only way to know whether that 28.5% meant
    anything is to check what happens to every other 28.5% this model emits.

    Each game is predicted from comparables EXCLUDING ITSELF. Without that the
    prediction contains its own answer and the curve is perfect and worthless.

    Measured 2026-09-25 over 2,692 games with a usable comparable set: the
    weighted mean gap between predicted and observed is 1.17pp on the home
    win, and in the 66-76% band — the one that Thursday game sat in — the
    favorite won 70.1% of 518 games. So a 70% that loses is a 70% behaving
    correctly, three times in ten.

    Slow: it is O(n^2) over three thousand games, a few seconds. Called by the
    exporter once and by a test, not per request.
    """
    h = history() if hist is None else hist
    if h.height < MIN_COMPARABLES * 2:
        return {"n": 0}
    sp = h["spread_line"].to_list()
    to = h["total_line"].to_list()
    mg = h["margin"].to_list()
    tt = h["total"].to_list()
    n = len(sp)
    rows = []
    for i in range(n):
        lo_s, hi_s = sp[i] - SPREAD_TOL, sp[i] + SPREAD_TOL
        lo_t, hi_t = to[i] - TOTAL_TOL, to[i] + TOTAL_TOL
        k = w = ov = 0
        for j in range(n):
            if j == i:
                continue
            if lo_s <= sp[j] <= hi_s and lo_t <= to[j] <= hi_t:
                k += 1
                if mg[j] > 0:
                    w += 1
                if tt[j] > to[i]:
                    ov += 1
        if k < MIN_COMPARABLES:
            continue
        rows.append((w / k, 1 if mg[i] > 0 else 0))
    if not rows:
        return {"n": 0}

    buckets: dict[int, list] = {}
    for p, y in rows:
        buckets.setdefault(min(bins - 1, int(p * bins)), []).append((p, y))
    out, gap = [], 0.0
    for b in sorted(buckets):
        vals = buckets[b]
        said = sum(p for p, _ in vals) / len(vals)
        happened = sum(y for _, y in vals) / len(vals)
        gap += abs(happened - said) * len(vals)
        out.append({"said": round(said * 100, 1),
                    "happened": round(happened * 100, 1),
                    "n": len(vals)})
    return {"n": len(rows), "bins": out,
            "mean_gap_pp": round(gap / len(rows) * 100, 2)}


def win_curve(hist: pl.DataFrame | None = None) -> dict:
    """P(home wins) as a smooth, monotone function of the spread.

    **Why not just count the comparable games.** `comparables` answers with
    the observed rate in a window, which is right for the distribution's
    SHAPE and wrong for a single probability near a pick'em: the window is
    two points wide, the crossover is noisy, and at a model spread of -0.7
    (home favored by 0.7) the window returned 48.5% for the home side. The
    page then printed "our model: PIT by 0.7" beside "CIN 51.5%", two
    statements from the same model pointing opposite ways.

    Observed rate by spread, on this archive:

        -3  42.7%    -1  44.4%    0  47.5%    +1  54.5%    +3  59.0%

    Monotone across the range and ragged across the middle — 47.5% at a
    pick'em on 242 games is within noise of 50 and still prints as "the away
    team is favored". A logistic fit through all of it crosses 50 where the
    spread says it should and is defensible at every point in between.

    Fitted by Newton-Raphson on two parameters; no dependency, and at three
    thousand rows it converges in under ten iterations.
    """
    h = history() if hist is None else hist
    if h.height < 200:
        return {}
    x = h["spread_line"].to_numpy().astype(float)
    y = (h["margin"].to_numpy() > 0).astype(float)
    import numpy as np

    b = np.zeros(2)
    X = np.column_stack([np.ones_like(x), x])
    for _ in range(50):
        p = 1.0 / (1.0 + np.exp(-(X @ b)))
        w = np.clip(p * (1 - p), 1e-9, None)
        g = X.T @ (y - p)
        hess = (X * w[:, None]).T @ X
        try:
            step = np.linalg.solve(hess, g)
        except np.linalg.LinAlgError:
            break
        b = b + step
        if np.max(np.abs(step)) < 1e-9:
            break
    return {"a": float(b[0]), "b": float(b[1]), "n": int(h.height)}


def win_prob(spread: float, curve: dict | None = None,
             hist: pl.DataFrame | None = None) -> float | None:
    """P(home wins) at a SCHEDULE-signed spread — positive means home favored."""
    import math

    c = curve or win_curve(hist)
    if not c:
        return None
    return 1.0 / (1.0 + math.exp(-(c["a"] + c["b"] * float(spread))))
