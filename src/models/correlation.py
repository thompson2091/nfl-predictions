"""Two legs in the same game are not independent, and the page says so.

The slip multiplies leg probabilities together and prints a caveat under the
answer: *"Chances assume each pick is independent. Two players in the same
game are not."* That caveat has been true and unpriced since it was written.

**Conditionally independent given the game script, not independent.** The
dependence between two players in one game runs almost entirely through how
the game goes. A back on the side that pulls away gets the fourth quarter; the
back on the other side is watching his team throw. Two receivers in a shootout
both eat. Condition on the margin band and most of the correlation is gone —
what is left is the bit two teammates compete for, which this does not claim
to capture.

So:

    P(A and B) = SUM over bands  P(band) * P(A | band) * P(B | band)

Both halves are already measured and neither is invented here:

  * `P(band)` is `script_risk.band_probabilities`, counted over the games the
    market priced like this one — the same partition the game page prints.
  * `P(leg | band)` is the leg's own number moved by `script_risk.fit`, whose
    multipliers are fitted per position and market over thousands of
    player-games. An RB's rushing line swings 0.51 across the bands; a
    receiver's receptions swing 0.12.

**The marginals are preserved.** Each conditional is divided by the leg's own
expected multiplier, so `SUM P(band) P(A|band)` comes back to exactly the
number the board shows for A. Without that the joint would be a different
claim about A as well as about A-and-B, and the slip would stop agreeing with
the board about a single leg.

**A band is one game seen from two sides.** `band_probabilities` reports from
one team's point of view, so a leg on the other team reads the same game
through `FLIP`. This is what makes two backs on opposite sides anti-correlate
rather than correlate: the same "won big" that helps one is the "lost big"
that hurts the other. Multiplying their probabilities OVERSTATES the parlay;
conditioning corrects it downward, and the slip should say so.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

from src.models.script_risk import BANDS, band_probabilities

#: One game, read from the other bench. `close` is its own mirror.
FLIP = {"won big": "lost big", "won": "lost", "close": "close",
        "lost": "won", "lost big": "won big"}

#: Below this the joint is reported as unavailable rather than estimated. A
#: band carrying no comparable games cannot condition anything.
MIN_BANDS = 3

#: A lift this far from 1.0 is worth telling the reader about. Under it the
#: correction is smaller than the rounding on the price they are shown.
MATERIAL_LIFT = 0.02


def _conditional(p: float, mult: dict, probs: dict) -> dict | None:
    """One leg's chance in each band, rescaled to keep its own marginal.

    `tilt` is what the leg's probability would average to under these band
    odds if the multipliers were applied raw. Dividing by it puts the marginal
    back exactly where the board has it, so conditioning changes the JOINT and
    never the single-leg number the reader already saw.
    """
    tilt = sum(probs.get(b, 0.0) * mult[b] for b in BANDS)
    if tilt <= 0:
        return None
    out = {}
    for b in BANDS:
        if probs.get(b, 0.0) <= 0:
            continue
        # A probability cannot leave [0, 1]; a heavy multiplier on a leg that
        # is already 90% would otherwise produce 1.2 and a joint above one.
        out[b] = min(1.0, max(0.0, p * mult[b] / tilt))
    return out


def joint(legs: list[dict], card: dict, fits: dict,
          hist: pl.DataFrame | None = None,
          strength: float | None = None) -> dict | None:
    """The chance every leg lands, with the game script shared between them.

    `legs` are dicts of `team`, `pos`, `market` and `p` — the board's own
    probability for that leg. `market` names a `script_risk` market, e.g.
    `rushing_yards`; a leg whose position and market were never fitted is
    carried at its marginal in every band, which makes it independent of the
    others rather than silently dropped.

    Returns None when the game has no usable band partition. A joint that
    cannot be conditioned is not a joint worth printing beside one that can.
    """
    if not legs or len(legs) < 2:
        return None
    home = card.get("home")
    probs = band_probabilities(card, home, hist=hist)
    if not probs or len(probs) < MIN_BANDS:
        return None

    conds, unfitted = [], 0
    for leg in legs:
        p = leg.get("p")
        if p is None:
            return None
        f = fits.get(f"{leg.get('pos')}|{leg.get('market')}")
        # A leg read from the away bench sees the flipped band.
        at_home = leg.get("team") == home
        if not f:
            unfitted += 1
            conds.append({b: float(p) for b in probs})
            continue
        mult = {b: f["mult"][FLIP[b] if not at_home else b] for b in BANDS}
        c = _conditional(float(p), mult, probs)
        if c is None:
            return None
        conds.append(c)

    independent = 1.0
    for leg in legs:
        independent *= float(leg["p"])
    together = sum(probs[b] * _prod(c.get(b, 0.0) for c in conds)
                   for b in probs)
    raw = (together / independent) if independent > 0 else None
    # THE CONDITIONING IS THE RIGHT SHAPE AND THE WRONG SIZE, so its strength
    # is fitted rather than trusted: five margin bands are a coarse summary of
    # a game script, and two players share more of it than five buckets carry.
    # See `fit_strength`.
    k = _strength() if strength is None else strength
    lift = None if raw is None else raw ** k
    return {
        "independent": independent,
        "joint": independent * lift if lift is not None else together,
        "lift": lift,
        "lift_unfitted": raw,
        "strength": k,
        "bands": probs,
        "legs_unfitted": unfitted,
        "n_legs": len(legs),
    }


_K: list = []


def _strength() -> float:
    """The fitted exponent, read once per process."""
    if not _K:
        try:
            _K.append(float(fit_strength().get("k") or 1.0))
        except Exception:
            _K.append(1.0)
    return _K[0]


def _prod(xs) -> float:
    out = 1.0
    for x in xs:
        out *= x
    return out


def explain(result: dict, legs: list[dict]) -> str | None:
    """One sentence a reader can act on, or None when it does not matter.

    Says which way the correction goes and why, never how big the multiplier
    is: "these two need the same game" is the fact, and 1.14 is not.
    """
    if not result or result.get("lift") is None:
        return None
    lift = result["lift"]
    if abs(lift - 1.0) < MATERIAL_LIFT:
        return None
    teams = {leg.get("team") for leg in legs}
    same = len(teams) == 1
    if lift > 1:
        return ("These picks rise and fall together — they want the same kind "
                "of game, so this pays off more often than multiplying the "
                "chances suggests."
                if same else
                "These picks want the same kind of game, so this lands more "
                "often than multiplying the chances suggests.")
    return ("These picks pull against each other: the game that helps one "
            "tends to hurt the other, so this lands LESS often than "
            "multiplying the chances suggests.")


#: Where the fitted strength lives, with its provenance.
CACHE = Path("data/processed/correlation.json")

#: Pair types used to fit the strength: both legs have a measured multiplier,
#: so the model has an opinion about them and can be scored on it.
FIT_PAIRS = [("RB", "rushing_yards"), ("RB", "carries"),
             ("QB", "passing_yards")]


def measure_pairs(seasons: tuple[int, int] | None = None) -> dict:
    """What same-game pairs ACTUALLY do, against multiplying them.

    A leg is "the player beat his own season median in that stat", which is a
    stand-in for a line defined without any book — so this measures
    CORRELATION and never pricing. Every ordered pair of legs inside one game
    is counted, split by whether the two players share a sideline.

    Measured over 2015-2026: 930,346 pairs. Same team lifts the joint 1.6%
    above the product (+5.3 se); opposite teams cut it 1.7% (-6.2 se); two
    running backs on opposite sides rushing is the strongest at 0.945
    (-5.1 se), which is the game script showing through — one team runs the
    clock out while the other abandons the run.
    """
    from src.models.script_risk import _band, _team_margins
    from src.utils.paths import get_path

    w = pl.read_parquet(get_path("raw") / "weekly_stats.parquet")
    tc = "recent_team" if "recent_team" in w.columns else "team"
    d = w.join(_team_margins(), left_on=["season", "week", tc],
               right_on=["season", "week", "team"], how="inner")
    if seasons:
        d = d.filter(pl.col("season").is_between(*seasons))
    if d.is_empty():
        return {"n": 0}
    d = d.with_columns(_band().alias("script"))

    def legs(pos, stat):
        x = (d.filter((pl.col("position") == pos) & pl.col(stat).is_not_null()
                      & (pl.col(stat) > 0))
              .select(["season", "week", tc, "opponent_team", "player_id",
                       "script", pl.col(stat).alias("v")]))
        med = (x.group_by(["season", "player_id"])
                .agg(pl.col("v").median().alias("med")))
        return (x.join(med, on=["season", "player_id"])
                 .with_columns([(pl.col("v") > pl.col("med")).alias("hit"),
                                pl.lit(f"{pos}|{stat}").alias("leg")])
                 .drop(["v", "med"]))

    parts = [legs(p, s) for p, s in FIT_PAIRS if s in d.columns]
    if not parts:
        return {"n": 0}
    a = pl.concat(parts).with_columns(
        pl.when(pl.col(tc) < pl.col("opponent_team"))
          .then(pl.col(tc) + "_" + pl.col("opponent_team"))
          .otherwise(pl.col("opponent_team") + "_" + pl.col(tc)).alias("gkey"))
    L = a.select(["season", "week", "gkey", pl.col(tc).alias("team"),
                  "player_id", "leg", "hit"])
    pairs = (L.join(L, on=["season", "week", "gkey"], suffix="_b")
              .filter(pl.col("player_id") != pl.col("player_id_b"))
              .with_columns((pl.col("team") == pl.col("team_b"))
                            .alias("same_team")))
    out = {"n": pairs.height,
           "seasons_used": [int(a["season"].min()), int(a["season"].max())]}
    for same in (True, False):
        x = pairs.filter(pl.col("same_team") == same)
        if not x.height:
            continue
        both = float((x["hit"] & x["hit_b"]).mean())
        prod = float(x["hit"].mean()) * float(x["hit_b"].mean())
        out["same_team" if same else "opposite"] = {
            "n": x.height, "observed": both, "product": prod,
            "lift": both / prod if prod else None}
    return out


def band_marginals() -> dict:
    """How often each band happens at all, over every game on disk.

    The strength is fitted against the league's own band mix rather than
    against one card's, so it is a property of the model and not of whichever
    game it was fitted beside.
    """
    from src.models.script_risk import _band, _team_margins

    m = _team_margins().with_columns(_band().alias("script"))
    g = m.group_by("script").agg(pl.len().alias("n"))
    total = m.height
    return {r["script"]: r["n"] / total for r in g.iter_rows(named=True)}


def fit_strength(refit: bool = False) -> dict:
    """How hard to apply the conditioning, fitted rather than assumed.

    Conditioning on the band gets the DIRECTION right and the SIZE short: on
    the league's own band mix the model puts two opposing backs at a lift of
    about 0.974, where the record says 0.945. Rather than invent a fudge, the
    correction is raised to a power `k` chosen so the model reproduces the
    measured lift:

        lift_applied = lift_model ** k,    k = ln(measured) / ln(model)

    `k` near 1 would mean the conditioning was already the right size. It is
    not, because a margin band is a coarse summary of a game script and two
    players share more of the script than five buckets can carry.

    Returns the fit with its provenance. A fit that cannot be measured returns
    `k = 1.0` and says so, which leaves the model exactly as conditioning
    alone makes it — understated, never invented.
    """
    import json
    from datetime import date

    if not refit and CACHE.exists():
        try:
            got = json.loads(CACHE.read_text())
            if got.get("k"):
                return got
        except (ValueError, OSError):
            pass
    measured = measure_pairs()
    probs = band_marginals()
    out = {"k": 1.0, "measured": measured, "bands": probs,
           "fit_date": date.today().isoformat(),
           "note": "not measurable; conditioning applied as-is"}
    opp = (measured or {}).get("opposite") or {}
    if opp.get("lift") and probs:
        from src.models.script_risk import fit as fit_script

        fits = fit_script()
        f = fits.get("RB|rushing_yards")
        if f:
            model = _lift_two_sided(f, probs)
            if model and model < 1.0:
                import math
                k = math.log(opp["lift"]) / math.log(model)
                out = {"k": round(max(1.0, min(4.0, k)), 4),
                       "model_lift": round(model, 4),
                       "measured_lift": round(opp["lift"], 4),
                       "n": measured.get("n"),
                       "seasons_used": measured.get("seasons_used"),
                       "bands": probs,
                       "fit_date": date.today().isoformat(),
                       "note": "raises the conditioned lift to this power so "
                               "it matches the measured pair record"}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(out, indent=1))
    return out


def _lift_two_sided(f: dict, probs: dict) -> float | None:
    """The model's lift for two mirrored legs at even money, under `probs`."""
    home = _conditional(0.5, {b: f["mult"][b] for b in BANDS}, probs)
    away = _conditional(0.5, {b: f["mult"][FLIP[b]] for b in BANDS}, probs)
    if not home or not away:
        return None
    together = sum(probs[b] * home.get(b, 0.0) * away.get(b, 0.0)
                   for b in probs)
    return together / 0.25


def validate(pairs: pl.DataFrame) -> dict:
    """Does conditioning beat multiplying, on games that have been played?

    `pairs` carries one row per (game, leg A, leg B) with both marginals, both
    outcomes and the model's joint. Scored by Brier against the observed
    both-landed indicator, because the claim is about a probability and not
    about a direction.

    A result where the product wins is a real answer and is reported as one.
    """
    if pairs.is_empty():
        return {"n": 0}
    both = pl.col("hit_a") & pl.col("hit_b")
    out = pairs.select([
        pl.len().alias("n"),
        both.mean().alias("observed"),
        pl.col("independent").mean().alias("mean_independent"),
        pl.col("joint").mean().alias("mean_joint"),
        ((pl.col("independent") - both.cast(pl.Float64)) ** 2)
        .mean().alias("brier_independent"),
        ((pl.col("joint") - both.cast(pl.Float64)) ** 2)
        .mean().alias("brier_joint"),
    ]).to_dicts()[0]
    out["brier_gain"] = out["brier_independent"] - out["brier_joint"]
    out["better"] = "conditional" if out["brier_gain"] > 0 else "independent"
    return out
