"""This week's yardage boards: a distribution per player, priced against every line.

The fourth, fifth and sixth markets, and the weekly serving path for
`src/models/yards.py`. One module for all three because they differ in their
label column and their training gate and in nothing else — see
`scripts/49_yards.py`, which trains them the same way for the same reason.

The shape is the receptions board's and the model underneath is not. A count
model predicts a mean and hands it to a negative binomial whose one dispersion
parameter is fitted for the whole population; that assumes a fixed
relationship between level and spread, and yardage has two different ones at
once. Receiving yards go from sd/mean 1.39 at one target to 0.52 at seven-plus
while their skew falls by a factor of 2.5; passing yards hold their standard
deviation near 60 while the mean almost doubles. So these predict the quantile
function directly and read the line off it. `src/models/yards.py` carries the
measurements.

**Not an edge, and said in numbers rather than left to be inferred.** The
first grading of passing yards reported `beats_market: True` on 53 fixtures,
and every part of that was an artefact: resampled by game the 95% interval was
[-0.033, +0.038] with P(gain > 0) = 0.58, the top five fixtures held 640% of
the gain, and the gain lived entirely on lines quoted by a single book — we
lost to the market on every line two or more books had drawn. With 129
fixtures the sign flipped. Books scatter on a yardage line, so `fair_prob` on
a thin row is a de-vig of one quote, and beating a noisy reading of a price is
not beating the price. `scripts/49_yards.py:compare` is the guard that now
stands between that number and the word "better".
"""
from __future__ import annotations

import json
import pickle

import numpy as np
import polars as pl

from src.utils.paths import get_path

#: Below this many books at a line, a "consensus" is one or two opinions
#: wearing the word. Kept as a column rather than a filter, as on receptions —
#: but it bites far harder here. Books agree on a receptions line and scatter
#: on a yardage one: a player carries a median of 3 distinct lines across the
#: board and each (player, line) cell is quoted by a median of 2 books, so
#: about half this board is thin by this definition and that is the honest
#: reading rather than a data problem.
THIN_BOOKS = 3

#: The three markets and the pre-game gate each is served on.
#:
#: The gate mirrors `scripts/49_yards.py:MARKETS` exactly and must keep doing
#: so: serving a population the model was not fitted on is the same mistake as
#: fitting one you cannot identify before kickoff, taken from the other end.
MARKETS: dict[str, dict] = {
    "rushing_yards": {"gate": None, "label": "Rushing yards"},
    "receiving_yards": {"gate": None, "label": "Receiving yards"},
    "passing_yards": {"gate": "position_QB", "label": "Passing yards"},
}


def load_blend(market: str, model_dir=None) -> float | None:
    """How far to shrink our number toward the book's, or None if unfitted.

    Fitted by `scripts/49_yards.py` on the validation season and saved beside
    the model. Absent, the board serves the raw model — which is worse, so its
    absence is reported by `board_for_week` rather than passed over.

    The season being played first, then the fit on every out-of-tree season
    (`evaluation.prop_blend`), then the validation-only fit.
    """
    root = model_dir or get_path("models", market)
    for name in ("market_blend_live.json", "market_blend_served.json",
                 "market_blend.json"):
        path = root / name
        if not path.exists():
            continue
        try:
            w = float(json.loads(path.read_text())["weight"])
        except Exception:                                        # noqa: BLE001
            continue
        if 0.0 <= w <= 1.0:
            return w
    return None


def load_model(market: str, model_dir=None) -> dict | None:
    """The fitted quantile model, its feature list and its levels.

    Read as a dict rather than through `XGBQuantileModel.load`, so serving does
    not depend on that class staying importable at the same path — the three
    things needed to price are the booster, the column order and the levels,
    and none of them are behavior.
    """
    if market not in MARKETS:
        raise KeyError(f"unknown yardage market {market!r}; known are "
                       f"{sorted(MARKETS)}")
    path = (model_dir or get_path("models", market)) / "xgb_quantile.pkl"
    if not path.exists():
        return None
    with open(path, "rb") as fh:
        art = pickle.load(fh)
    if not all(k in art for k in ("model", "feature_names", "levels")):
        return None
    return art


def expected_quantiles(market: str, season: int, week: int,
                       art: dict | None = None) -> tuple[pl.DataFrame, np.ndarray] | None:
    """The fitted distribution for every candidate in a week.

    Returns `(ids, quantiles)` — one row per player, before any line is
    applied. Separate from the board because it is the honest half: the
    quantile curve is what the model actually says, and everything downstream
    is that curve with a line put through it.
    """
    from src.models.count import design_matrix
    from src.models.yards import rearrange
    from src.prediction.predict import _norm_name_expr

    art = art or load_model(market)
    if art is None:
        return None

    feats_path = get_path("processed", "anytime_td") / "features.parquet"
    if not feats_path.exists():
        return None
    df = (pl.scan_parquet(feats_path)
          .filter((pl.col("season") == season) & (pl.col("week") == week))
          .collect())
    gate = MARKETS[market]["gate"]
    if gate and gate in df.columns:
        df = df.filter(pl.col(gate) == 1)
    # A defense does not catch passes, carry the ball or throw. It is on the
    # shared matrix because it scores touchdowns, which is a real market and
    # not this one — and it arrived here carrying a projection of 2.34
    # receiving yards for Buffalo, 1.72 for Cleveland, one row per team.
    #
    # Worse than the number being meaningless: all 32 of them are NAMED
    # "DEF/ST", so anything keyed on a player's name collapses them into one
    # row belonging to no team.
    if "position_DEFST" in df.columns:
        df = df.filter(pl.col("position_DEFST") != 1)
    if df.height == 0:
        return None

    # `design_matrix`, not `trainer.prepare_data`: missing stays missing. See
    # src/models/count.py for the rookie who arrived as a 91%-snap starter who
    # is never thrown to, because a null usage feature was zero-filled.
    q = rearrange(np.asarray(
        art["model"].predict(design_matrix(df, list(art["feature_names"]))),
        dtype=float))
    ids = df.select([
        "season", "week", "game_id", "player_id", "player_name", "team",
        _norm_name_expr("player_name").alias("player_name_norm"),
    ])
    return ids, q


def board_for_week(market: str, season: int, week: int,
                   snapshot: str = "close",
                   allow_open: bool = False) -> tuple[pl.DataFrame, str]:
    """Every posted line, with what we make it against what it pays.

    Returns `(board, message)`; an empty board always carries a reason.

    `allow_open` lets a week with no closing capture yet be priced off its
    open, every row stamped `price_snapshot="open"`. For the site only: the
    record is graded at the close, so nothing that freezes or records a pick
    may pass it. See `src.evaluation.week_history.ou_board`.
    """
    from src.ingest.odds_history import (HISTORY_PATH, drop_in_play,
                                         resolve_game_ids)
    from src.models.count import blend_to_market
    from src.models.yards import interval, prob_over, quantile_at

    art = load_model(market)
    if art is None:
        return pl.DataFrame(), (f"no {market} model on disk — run "
                                f"`python scripts/49_yards.py --market {market}`")

    got = expected_quantiles(market, season, week, art)
    if got is None:
        return pl.DataFrame(), (f"no candidates for {season} week {week} — "
                                "the feature matrix does not cover it")
    ids, q = got
    levels = tuple(art["levels"])

    if not HISTORY_PATH.exists():
        return pl.DataFrame(), "no odds archive on disk"
    week_lines = drop_in_play(resolve_game_ids(pl.read_parquet(HISTORY_PATH))).filter(
        (pl.col("season") == season) & (pl.col("week") == week)
        & (pl.col("market") == market))
    lines = week_lines.filter(pl.col("snapshot") == snapshot)
    if lines.height == 0 and allow_open and snapshot != "open":
        lines = week_lines.filter(pl.col("snapshot") == "open")
        if lines.height:
            snapshot = "open"
    if lines.height == 0:
        return pl.DataFrame(), (
            f"no {market} prices archived for {season} week {week} "
            f"({snapshot}) — the market is captured, so this means the week "
            "has not been snapshotted rather than that books are not posting")

    # Newest pre-kickoff capture per player and line. `drop_in_play` above is
    # what makes "newest" mean "the last one you could have bet" rather than
    # "furthest into the fourth quarter" — Sunday's capture slots cannot all be
    # pre-kickoff at once, so the archive holds genuinely in-play prices filed
    # under `close`.
    lines = (lines.sort("captured_at")
             .unique(subset=["player_name_norm", "point"], keep="last")
             .select(["player_name_norm", "point", "odds", "implied_prob",
                      "fair_prob", "n_books", "overround", "captured_at"]))

    lo, hi = interval(q, levels=levels)
    mus = ids.with_columns([
        pl.Series("proj", quantile_at(q, 0.5, levels)),
        pl.Series("lo", lo), pl.Series("hi", hi),
        # The row index, so the quantile matrix can be reordered with the join
        # rather than assumed to survive it.
        pl.Series("_ix", np.arange(q.shape[0])),
    ])

    b = mus.join(lines, on="player_name_norm", how="inner")
    if b.height == 0:
        return pl.DataFrame(), ("no posted line matches a candidate — the "
                                "names are not joining")

    over, push = prob_over(q[b["_ix"].to_numpy()], b["point"].to_numpy(), levels)
    # Ours, before the market is consulted. A book's Over 40.0 price is a claim
    # about the two outcomes that resolve, not all three, so the push mass
    # comes out before ours is set beside theirs. On this market that is almost
    # always a no-op: every line in the first archived sample was a half-point.
    raw = np.clip(over / np.clip(1.0 - push, 1e-9, None), 0.0, 1.0)

    w = load_blend(market)
    blended = raw if w is None else blend_to_market(raw, b["fair_prob"].to_numpy(), w)

    b = b.drop("_ix").with_columns([
        pl.Series("p_over_raw", over),
        pl.Series("p_push", push),
        pl.Series("model_only", raw),
        pl.Series("ours", blended),
        pl.lit(w).alias("blend_weight"),
        pl.lit(snapshot).alias("price_snapshot"),
    ])

    return b.with_columns([
        ((pl.col("ours") - pl.col("fair_prob")) * 100).alias("edge_pp"),
        # What a flat $100 on the over returns if we are right, at the posted
        # price. Negative is the usual answer on a market with a 7% hold.
        (pl.when(pl.col("odds") > 0)
           .then(pl.col("ours") * pl.col("odds") - (1 - pl.col("ours")) * 100)
           .otherwise(pl.col("ours") * (10000.0 / -pl.col("odds"))
                      - (1 - pl.col("ours")) * 100)).alias("ev"),
        (pl.col("n_books") < THIN_BOOKS).alias("thin"),
    ]).sort("edge_pp", descending=True), ""
