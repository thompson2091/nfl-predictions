"""Does the model's own certainty sort the prop book? NOT SETTLED.

An over/under bet carries two different numbers that both look like
confidence. The one `ou_shortlist` and the Gaps rule are fitted on is the
model's DISAGREEMENT with the de-vigged price — how much we think the book is
wrong. This module measures the other one: how sure the model is in absolute
terms, `max(p, 1-p)`, regardless of what the book says. A model at 0.95
against a book at 0.93 is nearly certain and disagrees barely.

**MEASURED 2026-10-08, AND IT DOES NOT HOLD UP YET.**

    season                    paired hi-lo       p    games
    2024 backtest, full             +6.51   0.018      284
    2024 ou_rows, weeks 1-9         +6.36   0.089      138
    2025 backtest, full            +10.44   0.00004     285
    2026 ou_rows, weeks 1-4          +0.96   0.878       64

Strong and consistent over 2024-25 — a monotone gradient from -7.31 per $100
in the least certain band to +9.07 in the most, against -2.04 for the whole
book, surviving a within-(market x side x price band) control at +8.38 and a
paired-within-game test at p=0.000005. Flat on 2026: the gradient is
-3.68, -4.38, -6.61, -2.81, +1.18 and over-60% equals under-55% to within a
third of a point.

64 games is about a third of the power needed to see a +8 effect, so 2026
neither confirms nor refutes. Either the effect is real and this is noise, or
it was a two-season artifact and 2026 is the first clean look at it.

**THE INSTRUMENT IS NOT THE EXPLANATION**, which was the thing to rule out.
The 2024-25 figure came from `backtest_*.csv`'s `p_model` and the 2026 one
from `ou_week`'s `model`, so they could have been different quantities. 2024
re-run through the 2026 path gives +6.36 against the backtest's +6.51 on the
same season. The two agree.

**NOTHING HERE IS FITTED AND NOTHING SERVES OFF IT.** `BANDS` and the 0.60 /
0.55 cuts are reporting choices carried from the first measurement so the
seasons stay comparable — a 0.60 cut is tie-break sensitive (+2.48 with the
project's own `-edge` dedupe tie-break, +1.91 with a neutral one) while the
gradient and the paired test are not, which is exactly why the gradient is
the thing reported and no threshold is published. Before anything bets on
this it has to be fitted with provenance the way `ou_shortlist`'s floors are.

See `scripts/65_confidence.py` for the one command, and the memory
`nfl-predictions-model-confidence-sorts-the-prop-book`.
"""
from __future__ import annotations

import math
from collections import defaultdict

#: The reporting bands, carried from the 2024-25 measurement so a later
#: season lands on the same rows. Uneven on purpose: the top of the range is
#: thin — 182 bets above 0.75 on a quarter-season — and splitting it finer
#: would report five intervals nobody can read.
BANDS: tuple[tuple[float, float], ...] = (
    (0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.75), (0.75, 1.01))

#: The two cuts the paired test compares. Not a threshold: see the module
#: docstring on why no cut is published.
HI, LO = 0.60, 0.55


def certainty(p: float) -> float:
    """How sure the model is, either way. 0.5 is a coin flip, 1.0 is certain."""
    return max(p, 1.0 - p)


def legs(season: int, weeks) -> list[dict]:
    """The model's own bets for a season, through the project's own chain.

    `season_scorecard.ou_rows` is `ou_week` -> `_model_only_side` ->
    `settle_rows` -> `_one_per_player`: the side is the unblended model's, the
    under is paid at the under's own archived price, a player with no
    offensive snap is void, and one line per player-game-market counts. Built
    rather than reimplemented so this cannot disagree with the Record page
    about the same bet.
    """
    from src.evaluation import season_scorecard as SC

    weeks = list(weeks)
    cache = SC.ou_rows(season, weeks)
    out = []
    for market, _label in SC.OU_MARKETS:
        for week in weeks:
            for r in cache.get(("model", market, week), []):
                if r.get("won") is None or r.get("odds") is None:
                    continue
                p = r.get("model")
                if p is None:
                    continue
                out.append({
                    "season": season, "week": week, "market": market,
                    "game_id": r["game_id"], "player": r.get("player_name"),
                    "line": r.get("line"), "odds": r["odds"],
                    "model": p, "won": bool(r["won"]),
                    "ret": SC._payout(r["odds"]) if r["won"] else -1.0,
                })
    return out


def _ci(rows: list[dict]) -> tuple[float, float, float]:
    """Mean return and its interval, clustered by game.

    `season_scorecard._cluster_ci` rather than a second estimator: every
    receiver in one game shares a script, so taken as independent 2,145 legs
    claim the precision of 2,145 coin flips and have roughly that of 64 games.
    """
    from src.evaluation import season_scorecard as SC

    by: dict = defaultdict(list)
    for r in rows:
        by[r["game_id"]].append(r["ret"])
    return SC._cluster_ci(dict(by))


def gradient(rows: list[dict], bands=BANDS, min_n: int = 40) -> list[dict]:
    """Return per $100 in each certainty band, with its clustered interval.

    A band under `min_n` is reported as present and unmeasurable rather than
    dropped: a missing row reads as a band nobody looked at.
    """
    out = []
    for lo, hi in bands:
        sub = [r for r in rows if lo <= certainty(r["model"]) < hi]
        row = {"lo": lo, "hi": hi, "n": len(sub),
               "games": len({r["game_id"] for r in sub})}
        if len(sub) >= min_n:
            m, a, b = _ci(sub)
            row.update(roi=m, ci_lo=a, ci_hi=b)
        out.append(row)
    return out


def paired(rows: list[dict], hi: float = HI,
           lo: float = LO) -> dict | None:
    """High minus low certainty, differenced WITHIN each game.

    The strongest form of the question available here, because it removes
    game script entirely rather than controlling for it: a shootout lifts
    both groups in the same game and the difference is blind to it. Only
    games carrying bets in both groups contribute, which is the whole point
    and also why `games` is smaller than the season's.
    """
    g: dict = defaultdict(lambda: [0.0, 0, 0.0, 0])
    for r in rows:
        c = certainty(r["model"])
        if c >= hi:
            g[r["game_id"]][0] += r["ret"]
            g[r["game_id"]][1] += 1
        elif c < lo:
            g[r["game_id"]][2] += r["ret"]
            g[r["game_id"]][3] += 1
    use = [v for v in g.values() if v[1] and v[3]]
    if len(use) < 3:
        return None
    d = [v[0] / v[1] - v[2] / v[3] for v in use]
    mean = sum(d) / len(d)
    var = sum((x - mean) ** 2 for x in d) / (len(d) - 1)
    se = math.sqrt(var / len(d))
    if se == 0:
        return {"diff": mean, "se": 0.0, "p": 1.0, "games": len(use)}
    return {"diff": mean, "se": se, "games": len(use),
            "p": math.erfc(abs(mean / se) / math.sqrt(2))}


def power(rows: list[dict], z_power: float = 0.8416) -> dict:
    """The clustered standard error, and the smallest effect it can see.

    Reported beside every result here because the 2026 null is a null from a
    test that could only have found something large, and a reader handed
    "flat" without the sensitivity has been told the wrong thing.
    `z_power` is 80%; 1.6449 would be 95%.
    """
    if not rows:
        return {"n": 0, "games": 0}
    m, a, b = _ci(rows)
    se = (b - m) / 1.96 if b > m else 0.0
    return {"n": len(rows), "games": len({r["game_id"] for r in rows}),
            "roi": m, "ci_lo": a, "ci_hi": b, "se": se,
            "detects": (1.96 + z_power) * se}
