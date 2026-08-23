"""What survives every measurement this project has, for one week.

The board says who scores. The bet card says where we disagree with a price.
Neither asks the question a bettor is actually asking, which is *given
everything that has been measured about this model, is there anything here
worth money* — and the honest answer is usually nothing, which is precisely why
it needs a surface of its own. A card that lists two plays every week trains a
reader to take two plays every week.

Four filters, each one a measurement rather than a preference:

  **The side.** These markets sell Yes only. A player we rate *below* the price
  is a veto, not a bet, however large the gap — see `board.confidence`.

  **Closing-line value, by disagreement size.** `clv.by_edge` splits the
  agreement rate by how far we sat from the opening price *and which side*. On
  anytime TD the bettable side is negative in every band up to ten points: the
  market moves away from the players we like. Only the ten-plus band is
  non-negative, and barely. First TD has no such band at all. A pick outside
  those bands is one the market has historically moved against.

  **The price band and the rank** are carried as *context*, not as filters, and
  the distinction is the whole reason this module has a docstring.
  `rank_economics` measures every bet in a band over the whole population —
  including the players this screen has just vetoed, which is two thirds of
  them. A band being negative across that population says nothing certain about
  the handful inside it that also cleared the two filters above, and dropping
  rows on it composes two measurements taken over different populations. Every
  anytime-TD price band is negative, so as a filter it would empty every week
  by construction, which is a rule that has stopped reading its input.

What is left is priced at the best number any archived book posted rather than
at the consensus — `line_shopping` — because that is the only edge here that
does not need the model to be right.

Nothing in this module is a claim that the survivors are profitable. Every
measurement it reads says the opposite about the population they come from;
the filters remove the parts that are measurably worse, and what remains is
merely *not yet ruled out*, which is the strongest statement the evidence
supports. The measurement that would say more is a replay of this screen
itself, week by week, graded at closing prices — the same treatment
`combo_backtest` gives the combinations table. Until that exists, the honest
reading of a survivor is "the two filters that are measured on the right
population did not reject it".
"""
from __future__ import annotations

import polars as pl

#: Below this many observations a band's verdict is noise, and a filter built
#: on it removes players for no reason. Matches the floor `rank_economics`
#: itself uses before printing a bucket.
MIN_BAND_N = 100


def clv_floor(clv: dict | None, side: str = "higher") -> dict | None:
    """The smallest disagreement whose band the market has not moved against.

    Returns that band, or `None` when no band on this side is non-negative —
    which is a real answer and the one first TD gives: there is no size of
    disagreement on the side you can bet where the closing line has come our
    way rather than walked off.
    """
    bands = [b for b in (clv or {}).get("by_edge", [])
             if b.get("side") == side and b.get("n", 0) >= MIN_BAND_N]
    if not bands:
        return None
    ok = [b for b in sorted(bands, key=lambda b: b["lo"])
          if b["mean_move_pp"] >= 0.0]
    return ok[0] if ok else None


def clv_band(clv: dict | None, edge_pp: float, side: str = "higher") -> dict | None:
    """The measured band a pick of this size falls in."""
    gap = abs(float(edge_pp))
    for b in (clv or {}).get("by_edge", []):
        if b.get("side") != side:
            continue
        if gap >= b["lo"] and (b["hi"] is None or gap < b["hi"]):
            return b
    return None


def _ruled_out(rows, key: str) -> set:
    """Values whose measured return is entirely below zero.

    `hi < 0` rather than `roi < 0`: a point estimate below zero on forty bets
    is not evidence, and a filter that acts on it throws away players because
    of noise. The interval clearing zero on the wrong side is evidence.
    """
    out = set()
    for r in rows or []:
        if r.get("n", 0) < MIN_BAND_N or r.get("hi") is None:
            continue
        if float(r["hi"]) < 0:
            out.add(r.get("bucket", r.get("rank")))
    return out


def price_bucket(odds: float, econ: dict | None) -> str | None:
    """Which of `rank_economics`' price bands a price falls in.

    The band edges are read off the artifact rather than repeated here, so a
    re-fit that changes them cannot leave this screening on the old ones.
    """
    buckets = [r.get("bucket") for r in (econ or {}).get("by_odds_bucket", [])]
    o = float(odds)
    for b in buckets:
        if b == "<+100":
            if o < 100:
                return b
        elif b.endswith("up"):
            if o >= float(b.split("+")[1].split("up")[0]):
                return b
        elif "-" in b:
            lo, hi = b.replace("+", "").split("-")
            if float(lo) <= o < float(hi):
                return b
    return None


def shortlist(board: pl.DataFrame, *, target_type: str, clv: dict | None,
           econ: dict | None, shopped: pl.DataFrame | None = None) -> dict:
    """Apply every filter to one week's priced board, and say what each removed.

    The `dropped` counts are the point as much as the survivors are: a week
    that ends with nothing has to say which measurement emptied it, or it reads
    as a data problem rather than as the answer.
    """
    reasons: list[dict] = []
    if board is None or board.height == 0:
        return {"rows": [], "dropped": [], "floor": None,
                "note": "No priced players this week."}

    df = board
    start = df.height

    # 1. The side. Everything else is downstream of this one.
    df = df.filter(pl.col("model_edge_pp") > 0)
    reasons.append({"filter": "we rate them below the price (veto)",
                    "dropped": start - df.height, "left": df.height})

    # 2. The disagreement size the market has not moved against.
    floor = clv_floor(clv, "higher")
    if floor is None:
        n = df.height
        df = df.clear()
        reasons.append({
            "filter": ("no disagreement size on this market has non-negative "
                       "closing-line value on the side you can bet"),
            "dropped": n, "left": 0})
    else:
        n = df.height
        df = df.filter(pl.col("model_edge_pp").abs() >= floor["lo"])
        reasons.append({
            "filter": (f"disagreement under {floor['lo']:.0f} points, where the "
                       f"market has moved away from us"),
            "dropped": n - df.height, "left": df.height})

    # Context, not filters: see the docstring. These verdicts were measured
    # over every bet in the band, vetoed players included, so they cannot be
    # applied to what is left of the board without composing two populations.
    by_bucket = {r.get("bucket"): r for r in (econ or {}).get("by_odds_bucket", [])}
    by_rank = {r.get("rank"): r for r in (econ or {}).get("by_rank", [])}
    rank_col = "bet_rank" if "bet_rank" in df.columns else "rank"

    rows = []
    best = {}
    if shopped is not None and shopped.height:
        for r in shopped.iter_rows(named=True):
            best[r.get("player_name_norm") or r.get("player")] = r
    for r in (df.iter_rows(named=True) if df.height else []):
        b = best.get(r.get("player_name_norm")) or best.get(r.get("player_name"))
        band = clv_band(clv, r["model_edge_pp"], "higher")
        bucket = price_bucket(r["odds"], econ)
        rank_row = by_rank.get(r.get(rank_col))
        rows.append({
            "player": r.get("player_name"), "team": r.get("team"),
            "game": r.get("game_label"),
            "ours": float(r["prob_bet"]), "book": float(r["market_prob"]),
            "edge_pp": float(r["model_edge_pp"]),
            "odds": int(r["odds"]),
            "best_odds": (int(b["best_odds"]) if b else None),
            "best_book": (b.get("best_book") if b else None),
            "shopped_pp": (float(b["gap_pp"]) if b else None),
            "clv_moved_our_way": (band or {}).get("moved_our_way"),
            "clv_mean_move_pp": (band or {}).get("mean_move_pp"),
            "clv_n": (band or {}).get("n"),
            # What every bet in this player's price band and at this board rank
            # returned, over a population that includes the vetoes. Context for
            # reading the row, never a reason it is on the list.
            "band": bucket,
            "band_roi": (by_bucket.get(bucket) or {}).get("roi"),
            "band_verdict": (by_bucket.get(bucket) or {}).get("verdict"),
            "rank": r.get(rank_col),
            "rank_roi": (rank_row or {}).get("roi"),
            "rank_verdict": (rank_row or {}).get("verdict"),
        })
    rows.sort(key=lambda x: -x["edge_pp"])
    return {"rows": rows, "dropped": reasons, "floor": floor,
            "note": None if rows else "Nothing this week survives every filter."}
