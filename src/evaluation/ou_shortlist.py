"""A shortlist for the over/under markets, and what it is actually worth.

Anytime and first TD have had one for a long time: a rule with a floor fitted
on the disagreement sizes the market has historically moved toward, and its
graded return printed beside it. Receptions and the three yardage markets had
nothing, and `src/export/site.py` said so in a comment rather than in code —
"a control called Shortlist would imply a bet list that has not been
measured". This is the measurement.

It is not a port of `src/evaluation/shortlist.py`, because the market is a
different shape in three ways that each change the rule.

**Both sides are bettable.** A touchdown prop sells Yes only, so a player we
rate below the price is a veto — an opinion you cannot act on. An over/under
sells both, so there is no veto here at all: rating a player below the line is
a bet on the under. The rule therefore picks a *side* per row instead of
throwing half the board away, and the "Leave these out" view that the
touchdown boards carry has no meaning on these.

**The line is part of the bet.** A player carries several of them — 4.4 per
quarterback on passing yards — so everything below is keyed on
(player, game, point) and an open is only ever compared with a close at the
same number. A book moving a receptions line from 4.5 to 3.5 is a different
bet, not a price move.

**The market drifts, and the drift is not ours.** This is the one that would
have produced a wrong answer silently. De-vigged, the over's probability rises
from the open to the close across the whole archive — +0.24pp on rushing
yards, +0.34 on receiving, +0.16 on receptions, -0.04 on passing — whatever
anyone thinks about any player. Measured raw, that hands every over we like a
free +0.3pp of apparent closing-line value and charges every under the same
amount, so an uncentered fit concludes that our overs anticipate the market on
all four markets and our unders are wrong on all four. They do not and they
are not: that is the market's own drift wearing our name. Every move below is
centered on `drift`, which is that number computed over the whole market with
no reference to the model at all.

What the floor is fitted on, and what it is graded on, are deliberately two
different things. The floor is chosen on closing-line value — did the market
come toward us — because CLV has an observation for every priced row and
therefore has the statistical power to choose a band. The graded return is
then computed over the band that choice produced and reported beside it,
never used to make the choice. Scanning eight bands per market for the best
return would find one at 5% about once per market by construction, and the
band that scan returns IS the finding rather than a fact about the market.

Nothing here claims these are profitable. On the four markets as they stand,
no band's return clears zero on its own interval, which is the answer and is
why the artifact carries the interval rather than the point estimate.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from src.utils.paths import get_path

#: How far from the de-vigged opening price a row sat, in probability points,
#: as bucket edges. The last is open-ended. Deliberately the same edges as
#: `clv.EDGE_BUCKETS`, so a reader who knows the touchdown table can read this
#: one: 2 points is the threshold the board calls a bet, 5 is a "Leans", past
#: 10 is where "Strong call" lives.
GAP_BANDS = (0.0, 2.0, 5.0, 10.0)

#: Below this many rows a band's verdict is noise and a floor built on it
#: removes bets for no reason. Matches `shortlist.MIN_BAND_N`.
MIN_BAND_N = 100

#: A line one book drew is not a consensus, and this project has measured what
#: happens when you treat it as one: on the yardage markets the model's
#: apparent gain over the book is +0.0057 at one book, -0.0143 at two and
#: -0.0245 at three or more. The edge is an artifact of thin quotes, so a rule
#: that does not say how deep the book was is a rule that will find it again.
MIN_BOOKS = 2

#: Seasons the fit may look at, and the season it may not. The floor is fitted
#: on the validation season for the same reason the market blend is — it is
#: the first season the model did not train on — and everything after it is
#: reported as held out.
def _splits() -> tuple[int, int]:
    from src.utils.config import get_config
    s = get_config()["splits"]
    return int(s["val_season"]), int(s["train_end"])


def pairs(market: str) -> pl.DataFrame | None:
    """Every archived line holding both an open and a close at the same number.

    Both ends de-vigged two-way. `fair_prob` is the archive's own column and is
    null wherever a book posted only one side, which is about 9% of rows — a
    one-sided quote has no de-vigged probability and cannot be compared with
    anything, so those rows are absent rather than guessed at.
    """
    from src.ingest.odds_history import (HISTORY_PATH, SCHEMA, _conform,
                                         drop_in_play, resolve_game_ids)

    if not HISTORY_PATH.exists():
        return None
    h = _conform(pl.read_parquet(HISTORY_PATH), SCHEMA)
    h = resolve_game_ids(h).filter(
        (pl.col("market") == market) & pl.col("point").is_not_null()
        & pl.col("fair_prob").is_not_null() & pl.col("overround").is_not_null())
    if h.height == 0:
        return None

    # `point` is in the key so an open and a close are only ever compared at
    # the same line; see the module docstring.
    keys = ["season", "week", "game_id", "player_name_norm", "point"]
    opens = (h.filter(pl.col("snapshot") == "open").sort("captured_at")
             .unique(subset=keys, keep="first")
             .select(keys + [pl.col("fair_prob").alias("open_fair")]))
    # An in-play close is not a close. Every dedupe in this project keeps the
    # newest capture, so without this the fourth quarter wins.
    closes = (drop_in_play(h.filter(pl.col("snapshot") == "close"))
              .sort("captured_at").unique(subset=keys, keep="last")
              .select(keys + [pl.col("fair_prob").alias("close_fair"),
                              pl.col("implied_prob").alias("over_imp"),
                              pl.col("overround").alias("overround"),
                              pl.col("odds").alias("over_odds"),
                              pl.col("n_books").alias("n_books")]))
    if opens.height == 0 or closes.height == 0:
        return None
    both = opens.join(closes, on=keys, how="inner")
    if both.height == 0:
        return None
    # The under's price, recovered rather than invented. `overround` is
    # `p_over + p_under` as the book posted them, so the subtraction returns
    # the under's own implied probability exactly. See `odds_api`.
    return both.with_columns(
        (pl.col("overround") - pl.col("over_imp")).alias("under_imp"))


def drift(pr: pl.DataFrame | None) -> float:
    """How far the de-vigged over moves from open to close, market-wide.

    The number every band below is centered on. Computed over every pair with
    no reference to the model, which is what makes it a property of the market
    rather than of our opinion — see the module docstring for what happens
    when it is left in.
    """
    if pr is None or pr.height == 0:
        return 0.0
    return float(((pl.col("close_fair") - pl.col("open_fair")) * 100).alias("d")
                 .pipe(lambda e: pr.select(e))["d"].mean())


def model_probs(market: str, pr: pl.DataFrame) -> pl.DataFrame | None:
    """Our probability of the over at each archived line, and what happened.

    The model differs by market — a fitted quantile curve for the three
    yardage boards, a count mean and a dispersion for receptions — and the
    difference stops here: what comes back is one frame with `p_model` on it
    either way.

    `p_model` is the RAW model, before the market blend. That is deliberate
    and matches the touchdown shortlist, whose floor is fitted on `prob_bet`
    for the same reason: a number already shrunk 94% of the way to the book's
    cannot be asked whether it disagrees with the book.
    """
    from src.ingest.odds_history import _resolve_player_id
    from src.models.count import design_matrix

    feats_path = get_path("processed", "anytime_td") / "features.parquet"
    if not feats_path.exists() or pr is None or pr.height == 0:
        return None
    feats = pl.read_parquet(feats_path)
    # A defense does not catch passes, carry the ball or throw, and all 32 of
    # them are named "DEF/ST". Off the matrix here for the same reason the
    # boards exclude them.
    if "position_DEFST" in feats.columns:
        feats = feats.filter(pl.col("position_DEFST") != 1)

    rows = pr.with_columns(_resolve_player_id(pr)).filter(
        pl.col("player_id").is_not_null())
    if rows.height == 0:
        return None

    if market == "receptions":
        from src.models.count import fair_two_way, prob_over
        from src.prediction.receptions import load_model
        art = load_model()
        if art is None:
            return None
        mu = np.clip(art["model"].predict(
            design_matrix(feats, list(art["feature_names"]))), 1e-6, None)
        te = feats.select(["season", "week", "player_id"]).with_columns(
            pl.Series("mu", mu))
        rows = rows.join(te, on=["season", "week", "player_id"], how="inner")
        if rows.height == 0:
            return None
        over, push = prob_over(rows["mu"].to_numpy(), rows["point"].to_numpy(),
                               float(art["dispersion"]))
        # The push mass comes out before our number is set beside the book's:
        # a book's Over 5.0 price is a claim about the two outcomes that
        # resolve, not all three.
        p = fair_two_way(over, push)
    else:
        from src.models.yards import prob_over, rearrange
        from src.prediction.yards import MARKETS, load_model
        if market not in MARKETS:
            return None
        art = load_model(market)
        if art is None:
            return None
        gate = MARKETS[market]["gate"]
        f = feats.filter(pl.col(gate) == 1) if gate and gate in feats.columns else feats
        q = rearrange(np.asarray(art["model"].predict(
            design_matrix(f, list(art["feature_names"]))), dtype=float))
        te = f.select(["season", "week", "player_id"]).with_columns(
            [pl.Series(f"_q{i}", q[:, i]) for i in range(q.shape[1])])
        rows = rows.join(te, on=["season", "week", "player_id"], how="inner")
        if rows.height == 0:
            return None
        qq = np.stack([rows[f"_q{i}"].to_numpy() for i in range(q.shape[1])], axis=1)
        over, push = prob_over(qq, rows["point"].to_numpy(),
                               np.asarray(art["levels"], dtype=float))
        p = np.clip(over / np.clip(1.0 - push, 1e-9, None), 0.0, 1.0)
        rows = rows.drop([f"_q{i}" for i in range(q.shape[1])])

    ws = (pl.scan_parquet(get_path("raw") / "weekly_stats.parquet")
          .select(["season", "week", "player_id", market]).collect())
    rows = rows.with_columns(pl.Series("p_model", p)).join(
        ws, on=["season", "week", "player_id"], how="left")
    # A push settles neither side and is not a bet. A row with no weekly stat
    # is a player who did not play, and the outcome is unknowable rather than
    # zero — nflverse writes 0 for a player who played and did none of it.
    return rows.with_columns(
        pl.when(pl.col(market) > pl.col("point")).then(1)
          .when(pl.col(market) < pl.col("point")).then(0)
          .otherwise(None).alias("won_over")).filter(
        pl.col("won_over").is_not_null())


def _returns(rows: pl.DataFrame, over: bool) -> np.ndarray:
    """A flat unit on one side of every row, settled at the closing price."""
    imp = (rows["over_imp"] if over else rows["under_imp"]).to_numpy()
    dec = 1.0 / np.clip(imp, 1e-6, 0.999)
    won = rows["won_over"].to_numpy() == (1 if over else 0)
    return np.where(won, dec - 1.0, -1.0)


def roi_interval(ret: np.ndarray, games, n_boot: int = 4000,
                 seed: int = 0) -> tuple[float, float, float]:
    """Mean return with a 95% interval, resampled by GAME rather than by row.

    A book posts five passing lines on one quarterback and every one of them
    settles on the same afternoon against the same defense. Treating those as
    five independent observations is what turns a coin flip into a finding,
    and is the same correction `scripts/49_yards.py:compare` makes.
    """
    ret = np.asarray(ret, dtype=float)
    if ret.size == 0:
        return (float("nan"),) * 3
    gs = np.asarray(games)
    uniq = np.unique(gs)
    where = {g: np.where(gs == g)[0] for g in uniq}
    rng = np.random.default_rng(seed)
    boot = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        take = np.concatenate([where[g] for g in rng.choice(uniq, uniq.size, True)])
        boot[i] = ret[take].mean()
    return (float(ret.mean()), float(np.percentile(boot, 2.5)),
            float(np.percentile(boot, 97.5)))


def bands(rows: pl.DataFrame, market_drift: float, seasons=None) -> list[dict]:
    """Closing-line value and graded return, by side and disagreement size.

    One entry per (side, band). `move_pp` is signed toward the side we took
    and centered on the market's own drift, so a positive number means the
    close came toward us by more than it came toward everybody. `roi` is a
    flat unit on that side at the closing price, with the interval that says
    whether it means anything.
    """
    if rows is None or rows.height == 0:
        return []
    if seasons is not None:
        rows = rows.filter(pl.col("season").is_in(list(seasons)))
    if rows.height == 0:
        return []

    rows = rows.with_columns([
        ((pl.col("p_model") - pl.col("open_fair")).abs() * 100).alias("_gap"),
        (pl.col("p_model") > pl.col("open_fair")).alias("_over"),
    ]).with_columns(
        # Signed toward the side we took, then centered. Uncentered, the
        # market's drift pays every over and charges every under — see the
        # module docstring.
        (pl.when(pl.col("_over"))
           .then((pl.col("close_fair") - pl.col("open_fair")) * 100 - market_drift)
           .otherwise((pl.col("open_fair") - pl.col("close_fair")) * 100 + market_drift)
         ).alias("_toward"))

    out: list[dict] = []
    edges = list(GAP_BANDS)
    for side, over in (("over", True), ("under", False)):
        part = rows.filter(pl.col("_over") == over)
        for i, lo in enumerate(edges):
            hi = edges[i + 1] if i + 1 < len(edges) else None
            b = part.filter(pl.col("_gap") >= lo)
            if hi is not None:
                b = b.filter(pl.col("_gap") < hi)
            if b.height == 0:
                continue
            deep = b.filter(pl.col("n_books") >= MIN_BOOKS)
            ret = _returns(b, over)
            roi, rlo, rhi = roi_interval(ret, b["game_id"].to_list())
            out.append({
                "side": side, "lo": float(lo),
                "hi": None if hi is None else float(hi),
                "n": int(b.height),
                "n_deep": int(deep.height),
                "moved_our_way": float((b["_toward"] > 0).mean()),
                "mean_move_pp": float(b["_toward"].mean()),
                "roi": roi * 100, "roi_lo": rlo * 100, "roi_hi": rhi * 100,
                "roi_deep": (float(_returns(deep, over).mean()) * 100
                             if deep.height else None),
                "fixtures": int(b["game_id"].n_unique()),
            })
    return out


def floor_for(bs: list[dict], side: str) -> dict | None:
    """The smallest disagreement whose band the market has not moved against.

    Chosen on closing-line value and never on the graded return. There are
    eight bands per market, and picking the one that paid best would find a
    payer on a coin-flip market roughly once per market by construction: the
    scan would BE the finding. CLV has an observation for every priced row
    rather than only the settled ones, which is what gives it the power to
    choose a band at all.

    `None` is a real answer, and the one first TD gives on the touchdown side:
    there is no size of disagreement where the close has come our way.
    """
    ok = [b for b in bs
          if b.get("side") == side and b.get("n", 0) >= MIN_BAND_N
          and b.get("mean_move_pp", 0.0) >= 0.0]
    return min(ok, key=lambda b: b["lo"]) if ok else None


def fit(market: str) -> dict:
    """Fit the floor on the validation season and grade it on everything after.

    The validation season is the first the model did not train on, and is the
    season the market blend is fitted on for the same reason. Every season
    after it is held out — the floor was chosen before those games were
    played, so what the rule returned there is the only figure here that is
    not in some sense fitted.
    """
    val, _train_end = _splits()
    pr = pairs(market)
    if pr is None or pr.height == 0:
        return {"market": market, "problem": "no open/close pairs archived",
                "drift_pp": 0.0, "bands": [], "floors": {}, "graded": []}
    d = drift(pr)
    rows = model_probs(market, pr)
    if rows is None or rows.height == 0:
        return {"market": market, "problem": "no archived line joins a candidate",
                "drift_pp": d, "bands": [], "floors": {}, "graded": []}

    fitted = bands(rows, d, seasons=[val])
    floors = {s: floor_for(fitted, s) for s in ("over", "under")}
    held = sorted(s for s in rows["season"].unique().to_list() if s > val)
    return {
        "market": market, "problem": "",
        "drift_pp": d,
        "val_season": val, "held_out": held,
        "n_pairs": int(rows.height),
        "bands": fitted,
        "floors": floors,
        # What the fitted rule returned on seasons it was not fitted on. One
        # entry per held-out season, plus the pooled one, because a rule that
        # only worked in the year after the fit is a rule that decayed.
        "graded": _grade(rows, d, floors, held),
    }


def _grade(rows: pl.DataFrame, market_drift: float, floors: dict,
           held: list[int]) -> list[dict]:
    """What the fitted floors returned, per held-out season and pooled."""
    out = []
    for label, seasons in ([(str(s), [s]) for s in held]
                           + ([("held out", held)] if len(held) > 1 else [])):
        picks = _apply(rows, floors, seasons)
        if picks is None or picks.height == 0:
            out.append({"season": label, "n": 0, "roi": None,
                        "roi_lo": None, "roi_hi": None})
            continue
        ret = np.concatenate([
            _returns(picks.filter(pl.col("_side") == s), s == "over")
            for s in ("over", "under")
            if picks.filter(pl.col("_side") == s).height])
        games = (picks.filter(pl.col("_side") == "over")["game_id"].to_list()
                 + picks.filter(pl.col("_side") == "under")["game_id"].to_list())
        roi, lo, hi = roi_interval(ret, games)
        out.append({"season": label, "n": int(picks.height),
                    "fixtures": int(picks["game_id"].n_unique()),
                    "roi": roi * 100, "roi_lo": lo * 100, "roi_hi": hi * 100})
    return out


def _apply(rows: pl.DataFrame, floors: dict, seasons) -> pl.DataFrame | None:
    """The rows a set of floors would have picked, with the side it took."""
    if rows is None or rows.height == 0:
        return None
    r = rows.filter(pl.col("season").is_in(list(seasons))) if seasons else rows
    r = r.with_columns([
        ((pl.col("p_model") - pl.col("open_fair")).abs() * 100).alias("_gap"),
        pl.when(pl.col("p_model") > pl.col("open_fair")).then(pl.lit("over"))
          .otherwise(pl.lit("under")).alias("_side"),
    ]).filter(pl.col("n_books") >= MIN_BOOKS)
    keep = []
    for side in ("over", "under"):
        f = floors.get(side)
        if not f:
            continue
        part = r.filter((pl.col("_side") == side) & (pl.col("_gap") >= f["lo"]))
        if f.get("hi") is not None:
            part = part.filter(pl.col("_gap") < f["hi"])
        if part.height:
            keep.append(part)
    return pl.concat(keep) if keep else r.clear()


def load(market: str) -> dict | None:
    """The fitted artifact for one market, or None where it has not been run."""
    import json

    path = get_path("output", market) / "shortlist.json"
    if not path.exists():
        return None
    try:
        art = json.loads(path.read_text())
    except Exception:                                            # noqa: BLE001
        return None
    return art if isinstance(art, dict) and "floors" in art else None


def apply_to_board(rows: list[dict], art: dict | None) -> dict:
    """This week's board, narrowed to what the fitted rule would take.

    `rows` are the payload rows for one over/under board and carry the board's
    own names: `model_only` is the model before the blend, `fair_prob` is the
    book de-vigged. The gap is measured between those two for the reason given
    in `model_probs` — a number already shrunk most of the way to the book's
    cannot be asked whether it disagrees with the book.

    The `dropped` counts are as much the point as the picks. A week that ends
    with nothing has to say which measurement emptied it, or it reads as a
    data problem rather than as the answer.
    """
    out = {"rows": [], "dropped": [], "floors": (art or {}).get("floors") or {},
           "graded": (art or {}).get("graded") or [], "note": ""}
    if art is None:
        out["note"] = ("no fitted rule for this market — run "
                       "`python scripts/50_ou_shortlist.py`")
        return out

    # `point` or `open_point`: a row showing only an opening line is a line
    # like any other, and `_price_open_fallback` has already given it the same
    # three probabilities the closing rows get.
    priced = [r for r in rows
              if (r.get("point") is not None or r.get("open_point") is not None)
              and r.get("fair_prob") is not None
              and r.get("model_only") is not None]
    out["dropped"].append({"filter": "no posted line to bet into",
                           "dropped": len(rows) - len(priced), "left": len(priced)})

    # A line one book drew is not a consensus. This is the gate the fit was
    # made under, so serving without it would serve a different rule.
    deep = [r for r in priced if (r.get("n_books") or 0) >= MIN_BOOKS]
    out["dropped"].append({
        "filter": f"fewer than {MIN_BOOKS} books behind the line",
        "dropped": len(priced) - len(deep), "left": len(deep)})

    floors = out["floors"]
    if not any(floors.get(s) for s in ("over", "under")):
        out["dropped"].append({
            "filter": ("no disagreement size on this market has non-negative "
                       "closing-line value on either side"),
            "dropped": len(deep), "left": 0})
        return out

    kept = []
    dropped_side = 0
    for r in deep:
        # AGAINST THE OPEN, as fitted. The floors were chosen on the gap
        # between the model and the OPENING fair price, judged on how the
        # close then moved; measured against the close here the board was
        # serving a different population from the one the rule describes. The
        # open at this row's own line where it exists, else the current price.
        same = (r.get("open_point") is None or r.get("point") is None
                or r.get("open_point") == r.get("point"))
        base = (r.get("open_fair") if same and r.get("open_fair") is not None
                else r["fair_prob"])
        gap = (float(r["model_only"]) - float(base)) * 100.0
        side = "over" if gap > 0 else "under"
        f = floors.get(side)
        if not f or abs(gap) < f["lo"] or (f.get("hi") is not None
                                           and abs(gap) >= f["hi"]):
            dropped_side += 1
            continue
        # The key and the verdict, not the row. The page takes every figure
        # from the board itself, so the shortlist cannot disagree with the
        # table it filters about the same bet — the touchdown shortlist is
        # carried the same way and for the same reason.
        kept.append({
            "player_name": r.get("player_name"),
            "point": r.get("point") if r.get("point") is not None
                     else r.get("open_point"),
            "side": side, "gap_pp": abs(gap),
            "band_lo": f["lo"], "band_hi": f.get("hi")})
    out["dropped"].append({
        "filter": "disagreement outside the band the market has come our way in",
        "dropped": dropped_side, "left": len(kept)})
    kept.sort(key=lambda r: -r["gap_pp"])
    out["rows"] = kept
    return out
