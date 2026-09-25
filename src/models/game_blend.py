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
            if got.get("n", 0) >= MIN_GAMES:
                return got
        except json.JSONDecodeError:
            pass
    try:
        from src.models.game_model import walk_forward
        d = walk_forward().drop_nulls()
    except Exception:                                            # noqa: BLE001
        return {}
    if d.height < MIN_GAMES:
        return {}

    out: dict = {"n": d.height,
                 "seasons": [int(d["season"].min()), int(d["season"].max())]}
    for kind, mc, kc, ac in (
            ("margin", "margin_model", "margin_market", "margin_actual"),
            ("total", "total_model", "total_market", "total_actual")):
        w, e, base = _sweep(d[mc].to_numpy(), d[kc].to_numpy(),
                            d[ac].to_numpy())
        out[kind] = {"w": round(w, 3), "mae": round(e, 3),
                     "market_mae": round(base, 3),
                     "gain": round(base - e, 4),
                     "oos_gain": round(_oos(d, mc, kc, ac), 4)}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(out, indent=1))
    return out


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
    return out or None
