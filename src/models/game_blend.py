"""The adjusted game number: how far our model should move the market's.

Every player market on this board carries three numbers — what the model
says, what the book says, and a blend. The game markets carried two, so
"Adjusted" had no meaning at the game level and the page could only offer a
model that disagrees with a market and no answer about what to believe.

**THE WEIGHT IS FITTED, NOT CHOSEN.** A blend needs a number saying how much
of the model to use, and picking one because it looks reasonable is how a
project ends up with a constant nobody can defend. This sweeps the weight
against 1,904 walk-forward games and takes the one that minimises absolute
error, then checks that the weight itself survives being chosen out of
sample — fitted on seasons before each one, applied to it.

**AND THE GAIN IS SMALL. STATED, NOT BURIED.** Measured 2026-09-25:

    margin   market alone MAE 9.864   best w 0.15   MAE 9.835   gain 0.029
    total    market alone MAE 10.369  best w 0.30   MAE 10.279  gain 0.091

    walk-forward on the weight: margin +0.030, total +0.020

On a margin whose average error is ten points, three hundredths of a point is
not an edge and is not presented as one. What it IS good for is the question
a reader actually has when two numbers disagree: the blend says how far the
model has earned the right to move the book, and the honest answer is "about
a seventh of the way on the margin, a third on the total". Seeing that is
more useful than seeing a model number with no sense of how much to trust it.

The weights are cached, because fitting them means a walk-forward refit per
season and that is half a minute the export should not spend every build.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl

CACHE = Path("data/processed/game_blend.json")

#: How fine the sweep is. Twentieths: finer pretends to a precision the
#: sample does not support, coarser misses the optimum.
STEPS = 20

#: Below this many walk-forward games the weight is noise and the blend is
#: not offered at all.
MIN_GAMES = 500


def _sweep(model, market, actual) -> tuple[float, float, float]:
    """The weight minimising mean absolute error, and what it buys."""
    base = float(abs(market - actual).mean())
    best_w, best_e = 0.0, base
    for i in range(STEPS + 1):
        w = i / STEPS
        e = float(abs(w * model + (1 - w) * market - actual).mean())
        if e < best_e:
            best_w, best_e = w, e
    return best_w, best_e, base


def fit(refit: bool = False) -> dict:
    """Fitted weights for margin and total, cached.

    Returns `{}` rather than a default when the walk-forward cannot be built.
    An unfitted blend is a made-up number wearing a fitted number's label.
    """
    if not refit and CACHE.exists():
        try:
            got = json.loads(CACHE.read_text())
            # A cache from before the centering fit existed is refitted
            # rather than served without it, or the centered total would be
            # silently absent on every card until somebody passed `refit`.
            if (got.get("n", 0) >= MIN_GAMES and "center" in got
                    and "win" in got):
                return got
        except json.JSONDecodeError:
            pass
    try:
        from src.models.game_model import walk_forward
        d = walk_forward().drop_nulls()
    except Exception:                                            # noqa: BLE001
        return {}
    # COMPLETED SEASONS ONLY. The weights were fitted on 2019-2026, the
    # season being bet included, which the record loop forbids: a weight
    # tuned on this season absorbs the failure it was meant to detect.
    try:
        from src.utils.config import get_config
        cur = get_config()["seasons"].get("predict_season")
        if cur:
            d = d.filter(pl.col("season") < int(cur))
    except Exception:                                            # noqa: BLE001
        pass
    if d.height < MIN_GAMES:
        return {}

    out: dict = {"n": d.height,
                 "seasons": [int(d["season"].min()), int(d["season"].max())]}
    for kind, mc, kc, ac in (
            ("margin", "margin_model", "margin_market", "margin_actual"),
            ("total", "total_model", "total_market", "total_actual")):
        w, e, base = _sweep(d[mc].to_numpy(), d[kc].to_numpy(),
                            d[ac].to_numpy())
        oos = _oos(d, mc, kc, ac)
        # A WEIGHT THAT FAILS ITS OWN OUT-OF-SAMPLE CHECK IS ZERO. The total's
        # did (-0.0023 on 2026-10-06) and was served at 0.25 anyway; the sweep
        # always finds an in-sample gain, which is why `_oos` exists.
        served_w = w if oos > 0 else 0.0
        out[kind] = {"w": round(served_w, 3), "w_in_sample": round(w, 3),
                     "mae": round(e, 3),
                     "market_mae": round(base, 3),
                     "gain": round(base - e, 4),
                     "oos_gain": round(oos, 4)}
    center = fit_center(d)
    if center:
        out["center"] = center
    out["win"] = fit_model_win(d)
    out["fit_date"] = date.today().isoformat()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(out, indent=1))
    return out


def _logistic(x, y):
    """Two-parameter logistic fit by Newton-Raphson: (a, b)."""
    import numpy as np

    b = np.zeros(2)
    X = np.column_stack([np.ones_like(x), x])
    for _ in range(50):
        p = 1.0 / (1.0 + np.exp(-(X @ b)))
        w = np.clip(p * (1 - p), 1e-9, None)
        step = np.linalg.solve((X * w[:, None]).T @ X, X.T @ (y - p))
        b = b + step
        if np.max(np.abs(step)) < 1e-9:
            break
    return float(b[0]), float(b[1])


def fit_model_win(d: pl.DataFrame) -> dict:
    """P(home wins) from OUR model's margin, fitted on our model's margins.

    The page applied the curve fitted on the market's closing spread to the
    model's spread. The model's margin is noisier than the market's, so the
    same number means less: out of sample the slope on the model margin is
    about 0.09 against the market's 0.146, and games served at 29% were won
    41% of the time. Fitted here on walk-forward model margins, completed
    seasons only, with its own out-of-sample Brier score beside the market's.
    """
    import numpy as np

    d = d.filter(pl.col("margin_actual") != 0)
    x = d["margin_model"].to_numpy().astype(float)
    y = (d["margin_actual"].to_numpy() > 0).astype(float)
    a, b = _logistic(x, y)
    # Walk-forward: each season scored by a curve fitted on the ones before.
    sq_m, sq_k = [], []
    for s in sorted(d["season"].unique())[1:]:
        tr, te = d.filter(pl.col("season") < s), d.filter(pl.col("season") == s)
        ya = (tr["margin_actual"].to_numpy() > 0).astype(float)
        yt = (te["margin_actual"].to_numpy() > 0).astype(float)
        am, bm = _logistic(tr["margin_model"].to_numpy().astype(float), ya)
        ak, bk = _logistic(tr["margin_market"].to_numpy().astype(float), ya)
        pm = 1 / (1 + np.exp(-(am + bm * te["margin_model"].to_numpy())))
        pk = 1 / (1 + np.exp(-(ak + bk * te["margin_market"].to_numpy())))
        sq_m += list((pm - yt) ** 2)
        sq_k += list((pk - yt) ** 2)
    return {"a": round(a, 5), "b": round(b, 5), "n": int(d.height),
            "oos_brier": round(float(np.mean(sq_m)), 4) if sq_m else None,
            "market_oos_brier": round(float(np.mean(sq_k)), 4) if sq_k else None}


def model_win_home(model_spread: float, win: dict) -> float | None:
    """The card signs its spread negative when HOME is favored."""
    import math

    if not win or model_spread is None:
        return None
    m = -float(model_spread)
    return 1.0 / (1.0 + math.exp(-(win["a"] + win["b"] * m)))


# ── the total's level, removed and nothing else ──────────────────────────
#
# **THE MODEL'S TOTAL IS RIGHT ABOUT ORDER AND WRONG ABOUT LEVEL.** Walk-forward
# by season, the vegas-blind total sits anywhere from 1.2 points under the
# closing line (2020) to 2.7 over it (2022), and in a season that runs high it
# calls the over on two games in three. That is not an opinion about any one
# game; it is the league scoring a different amount from the seasons the model
# learned on. Game to game it still orders well — 52.9 to 54.3% against the
# close in six of seven seasons.
#
# So the week's average gap between our totals and the book's is taken out and
# the disagreement about each game is kept. The slate is the right unit: every
# total on it is posted before the first kickoff, and nothing about a result
# reaches it. How much of the gap to take out is FITTED — `c` swept like the
# blend weight, chosen on earlier seasons and scored on the next. Measured
# 2026-10-06 over 1,679 walk-forward games, 2020-2026:
#
#     raw       MAE 10.848   over/under 52.44%   over picked 59.4%
#     centered  MAE 10.734   over/under 53.70%   over picked 51.6%
#     paired MAE -0.114 +/- 0.039, paired hit +1.26pp +/- 0.74
#
# The season-to-date gap was the other candidate and lost to the slate on
# every line of that table. **The raw total stays the model's number** — this
# is an extra figure beside it, never a replacement.


def _slate_gap(d: pl.DataFrame) -> pl.DataFrame:
    return d.with_columns(
        (pl.col("total_model") - pl.col("total_market"))
        .mean().over(["season", "week"]).alias("_gap"))


def _sweep_c(model, gap, actual) -> tuple[float, float]:
    """The share of the slate gap to remove that minimises absolute error."""
    best_c, best_e = 0.0, float(abs(model - actual).mean())
    for i in range(STEPS + 1):
        c = i / STEPS
        e = float(abs(model - c * gap - actual).mean())
        if e < best_e:
            best_c, best_e = c, e
    return best_c, best_e


def fit_center(d: pl.DataFrame) -> dict:
    """`c`, the blend weight on the centered total, and what both buy.

    Every figure is out of sample except `c` and `w` themselves, which are
    fitted on everything because they are what gets served.
    """
    if d.height < MIN_GAMES:
        return {}
    d = _slate_gap(d)
    m, g, k, a = (d[x].to_numpy() for x in
                  ("total_model", "_gap", "total_market", "total_actual"))
    c, _ = _sweep_c(m, g, a)
    cen = m - c * g
    w, e, base = _sweep(cen, k, a)

    # Out of sample: c chosen on earlier seasons, scored on the next.
    raw_e = cen_e = 0.0
    hits_raw = hits_cen = n_ou = n = 0
    for s in sorted(d["season"].unique())[1:]:
        tr = d.filter(pl.col("season") < s)
        te = d.filter(pl.col("season") == s)
        if tr.height < 200 or te.is_empty():
            continue
        cs, _ = _sweep_c(tr["total_model"].to_numpy(), tr["_gap"].to_numpy(),
                         tr["total_actual"].to_numpy())
        tm, tg = te["total_model"].to_numpy(), te["_gap"].to_numpy()
        tk, ta = te["total_market"].to_numpy(), te["total_actual"].to_numpy()
        tc = tm - cs * tg
        raw_e += float(abs(tm - ta).sum())
        cen_e += float(abs(tc - ta).sum())
        n += te.height
        res = ta - tk
        for p_raw, p_cen, r, kk in zip(tm, tc, res, tk):
            if r == 0 or p_raw == kk or p_cen == kk:
                continue
            n_ou += 1
            hits_raw += (p_raw > kk) == (r > 0)
            hits_cen += (p_cen > kk) == (r > 0)
    if not n:
        return {}
    return {
        "c": round(c, 3), "w": round(w, 3), "mae": round(e, 3),
        "market_mae": round(base, 3), "gain": round(base - e, 4),
        "oos": {"n": n, "raw_mae": round(raw_e / n, 3),
                "centered_mae": round(cen_e / n, 3),
                "n_ou": n_ou,
                "raw_ou_hit": round(hits_raw / n_ou, 4) if n_ou else None,
                "centered_ou_hit": round(hits_cen / n_ou, 4) if n_ou else None},
        "seasons_used": sorted(int(x) for x in d["season"].unique()),
        "n_rows": d.height,
    }


def center_cards(cards: dict, weights: dict) -> None:
    """`model_total_centered` on every card of one week, from that week's gap.

    `cards` must be ONE slate: the gap is the mean over it, so mixing weeks
    would center each on the other's level. Cards missing either total are
    left alone and do not enter the mean.
    """
    cen = (weights or {}).get("center") or {}
    if "c" not in cen:
        return
    both = [c for c in cards.values()
            if c.get("model_total") is not None and c.get("total") is not None]
    if not both:
        return
    # THE GAP FROM GAMES STILL TO COME. A started card here carries a model
    # total recomputed after kickoff (the freeze swaps its own back in later),
    # and those fed the Monday-night game's centering: WAS @ SF was served
    # 48.0 on a gap of +0.14 where the frozen totals gave -0.47. A started
    # card's own centered number is served from the freeze.
    try:
        from src.export.projection_freeze import started
        ahead = [c for c in both if not started(c)]
    except Exception:                                            # noqa: BLE001
        ahead = both
    basis = ahead or both
    gap = sum(float(c["model_total"]) - float(c["total"]) for c in basis) / len(basis)
    for c in both:
        c["model_total_centered"] = round(float(c["model_total"])
                                          - cen["c"] * gap, 1)


def _oos(d: pl.DataFrame, mc: str, kc: str, ac: str) -> float:
    """The weight chosen on earlier seasons, scored on the next one.

    Without this the sweep is guaranteed to find SOME improvement — it is
    choosing a parameter on the same data it is scored on — and a weight that
    only helps in sample is a weight of zero wearing a disguise.
    """
    tot_b = tot_m = n = 0.0
    for s in sorted(d["season"].unique())[1:]:
        tr = d.filter(pl.col("season") < s)
        te = d.filter(pl.col("season") == s)
        if tr.height < 100 or te.height < 20:
            continue
        w, _, _ = _sweep(tr[mc].to_numpy(), tr[kc].to_numpy(),
                         tr[ac].to_numpy())
        m, k, a = te[mc].to_numpy(), te[kc].to_numpy(), te[ac].to_numpy()
        tot_b += float(abs(w * m + (1 - w) * k - a).sum())
        tot_m += float(abs(k - a).sum())
        n += te.height
    return (tot_m - tot_b) / n if n else 0.0


def blend_card(card: dict, weights: dict) -> dict | None:
    """The adjusted spread and total for one game.

    Signed the way the CARD signs them — negative when the home side is
    favored — because that is what every other number on the card does and a
    blend that flips convention halfway is worse than no blend.
    """
    if not weights:
        return None
    sp, tot = card.get("spread"), card.get("total")
    msp, mtot = card.get("model_spread"), card.get("model_total")
    out = {}
    if sp is not None and msp is not None and "margin" in weights:
        w = weights["margin"]["w"]
        out["spread"] = round(w * float(msp) + (1 - w) * float(sp), 1)
    if tot is not None and mtot is not None and "total" in weights:
        w = weights["total"]["w"]
        out["total"] = round(w * float(mtot) + (1 - w) * float(tot), 1)
    ctot, cen = card.get("model_total_centered"), weights.get("center") or {}
    if tot is not None and ctot is not None and "w" in cen:
        out["total_centered"] = round(cen["w"] * float(ctot)
                                      + (1 - cen["w"]) * float(tot), 1)
    return out or None


def blend_win(blend: dict | None, curve: dict | None) -> float | None:
    """P(home wins) at the blended spread — ONE definition, computed here.

    The page used to interpolate this itself, between the book's win
    probability and ours by the fraction the spread moved. Measured 2026-10-06
    on 1,674 walk-forward games the two agree to the third decimal (Brier
    0.2109 here, 0.2114 interpolated, the de-vigged moneyline 0.2109, the raw
    model 0.2414), so the choice is about having one number, not a better
    one. The curve is the same `score_dist.win_curve` the raw model's win
    probability comes from, so the two are on one scale.

    Signed the card's way: a negative spread means HOME is favored, and the
    curve takes the schedule's opposite convention.
    """
    from src.models.score_dist import win_prob

    if not blend or blend.get("spread") is None or not curve:
        return None
    got = win_prob(-float(blend["spread"]), curve)
    return None if got is None else round(got, 4)
