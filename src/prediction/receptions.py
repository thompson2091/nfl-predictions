"""This week's receptions board: an expected count, priced against every line.

The third market, and the first that is not a yes/no question. A book posts
Over 2.5 for one player and Over 6.5 for another and moves the line between the
open and the close, so there is no single target to model. `src/models/count.py`
explains why the answer is to predict the count and apply the line afterwards;
this is the weekly serving path for that model.

What it does NOT do is claim an edge. Graded on 2025 the model's log loss is
0.689 against the market's 0.644 — the market is better calibrated than we are,
which is what a 7% hold market looks like when you bring a model to it. The
first version of this model beat receptions by +17-22% ROI and that was the NGS
existence leak; the edge was the bug. So this exists to be measured against the
close and to be wrong in public, not to be bet.

WIRED IN since 2026-08. It is a market in the menu, a board on This week, a
pool on Combinations and a card on the Model page — and the three yardage
markets that followed it are served by `src/prediction/yards.py`, which is this
module's shape with a different distribution underneath.

Two bugs held it out of the pipeline for a while, and both are worth knowing
about because neither failed loudly.

The first board this produced carried +70 point edges into a 7% hold market,
which in this project means a bug rather than an edge, and it was two bugs.

One was representation. Serving went through `trainer.prepare_data`, which
zero-fills nulls because the touchdown models want it there; training builds
its matrix with a bare `to_numpy()`, which leaves them NaN. A rookie with no
recorded target therefore reached the model as a 91%-snap listed starter who is
never thrown to, and scored 8.52 expected receptions — above Amon-Ra St. Brown
on 14 targets a game. Read with the nulls intact he makes 4.96 and the top of
the board is Chase, Nacua and St. Brown. `src/models/count.py:design_matrix` is
now the single definition all three call sites use.

The other was time. Sunday's capture slots cannot all be pre-kickoff at once,
so the archive holds genuinely in-play prices filed under `close`, and every
dedupe in this project keeps the newest capture. Elic Ayomanor's Over 0.5 came
back at +235 from one book in the fourth quarter, displacing a four-book -205
from three hours earlier. `odds_history.drop_in_play` removes them, here and in
grading, line shopping, CLV and the wager log, all of which had the same hole.

Graded on 2026 week 1 with both fixed: 283 priced rows, model log loss 0.7030
against the market's 0.6769, mean mu 3.03 against 2.82 actual. The market is
better calibrated than we are, out of sample, which is the same answer 2025
gave (0.689 against 0.644) and is what a 7% hold market looks like when you
bring a model to it. The largest remaining disagreements are the model being
overconfident at the tails, not the pipeline lying: on the rows where it
claimed the market was 20 points too high, it said 23.0% and the market said
49.5% against an outcome of 47.8%.

So this is honest now, and it is still not an edge. It exists to be measured
against the close and to be wrong in public, not to be bet.

Features are the anytime-TD matrix. The candidate pool (who is on a roster this
week) and the usage history are the same question whatever is being predicted;
only the label differs, which is why `scripts/30_receptions.py` trains off that
matrix rather than building a fourth one.
"""
from __future__ import annotations

import pickle

import numpy as np
import polars as pl

from src.utils.paths import get_path

#: Below this many books, a consensus is one or two opinions wearing the word.
#: Kept as a column rather than a filter — a thin line is still the only price
#: there is, and the board says how thin instead of dropping the row.
THIN_BOOKS = 3


def load_blend(model_dir=None) -> float | None:
    """How far to shrink our number toward the book's, or None if unfitted.

    Fitted by `scripts/30_receptions.py` on the validation season and saved
    beside the model. Absent, the board serves the raw model — which is the
    behaviour before this existed and is worse, so its absence is reported by
    `board_for_week` rather than passed over.
    """
    import json

    root = model_dir or get_path("models", "receptions")
    # The live season's own weight where one has been fitted, the shipped one
    # otherwise. The live file only appears once enough of this season has
    # settled to carry it (`receptions_forward.MIN_BLEND_LINES`), and it is
    # fitted on weeks already played, so it is out of sample for the week it
    # is about to serve.
    for name in ("market_blend_live.json", "market_blend.json"):
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


def load_model(model_dir=None) -> dict | None:
    """The fitted count model, its feature list and its dispersion.

    Saved as a dict rather than the `XGBCountModel` instance, so loading it
    does not depend on that class staying importable at the same path — the
    three things needed to score are the booster, the column order and the
    dispersion, and none of them are behaviour.
    """
    path = (model_dir or get_path("models", "receptions")) / "xgb_count.pkl"
    if not path.exists():
        return None
    with open(path, "rb") as fh:
        art = pickle.load(fh)
    if not all(k in art for k in ("model", "feature_names", "dispersion")):
        return None
    return art


def expected_counts(season: int, week: int, art: dict | None = None
                    ) -> pl.DataFrame | None:
    """Expected receptions for every candidate in a week.

    One row per player, before any line is applied. Separate from the board
    because it is the honest half: `mu` is what the model actually says, and
    everything downstream is that number pushed through a distribution.
    """
    from src.models.count import design_matrix
    from src.prediction.predict import _norm_name_expr

    art = art or load_model()
    if art is None:
        return None

    feats_path = get_path("processed", "anytime_td") / "features.parquet"
    if not feats_path.exists():
        return None
    df = (pl.scan_parquet(feats_path)
          .filter((pl.col("season") == season) & (pl.col("week") == week))
          .collect())
    # No defence has ever caught a pass. It is on this matrix because it scores
    # touchdowns; it reached this board with a projected reception count, and
    # all 32 of them share the name "DEF/ST", so any key built from a player's
    # name folds them into a single row belonging to no team.
    if "position_DEFST" in df.columns:
        df = df.filter(pl.col("position_DEFST") != 1)
    if df.height == 0:
        return None

    # The same matrix builder the model was fitted through. It used to be
    # `trainer.prepare_data`, which zero-fills nulls for the touchdown models
    # and thereby told this one that a rookie with no recorded target is a
    # starter who is never thrown to. See `design_matrix`.
    mu = np.clip(art["model"].predict(design_matrix(df, list(art["feature_names"]))),
                 1e-6, None)

    # How many games that projection is built from, carried to the board.
    #
    # `mu` reads a rolling mean without saying how many observations are behind
    # it, so one good week and a full season look identical on screen. On 2026
    # week 2 that put a player with a single career game at 5.33 receptions,
    # 12th of 502. Measured over 2024-2026 the model turns out to be RIGHT
    # about such players more often than not (bias +0.16 on 49 cases, and
    # `fit_shrinkage` fits its correction to zero) — so this is published as
    # context, not as a warning. It is the number that lets the question be
    # asked.
    games = (pl.col("player_games_observed").fill_null(0).cast(pl.Int32)
             if "player_games_observed" in df.columns
             else pl.lit(None, dtype=pl.Int32))

    return df.select([
        "season", "week", "game_id", "player_id", "player_name", "team",
        _norm_name_expr("player_name").alias("player_name_norm"),
        games.alias("games_observed"),
    ]).with_columns(pl.Series("mu", mu))


def board_for_week(season: int, week: int, snapshot: str = "close"
                   ) -> tuple[pl.DataFrame, str]:
    """Every posted receptions line, with what we make it against what it pays.

    Returns `(board, message)`; an empty board always carries a reason.
    """
    from src.ingest.odds_history import (HISTORY_PATH, drop_in_play,
                                        resolve_game_ids)
    from src.models.count import blend_to_market, fair_two_way, prob_over

    art = load_model()
    if art is None:
        return pl.DataFrame(), ("no receptions model on disk — run "
                                "`python scripts/30_receptions.py`")

    mus = expected_counts(season, week, art)
    if mus is None or mus.height == 0:
        return pl.DataFrame(), (f"no candidates for {season} week {week} — "
                                "the feature matrix does not cover it")

    if not HISTORY_PATH.exists():
        return pl.DataFrame(), "no odds archive on disk"
    lines = drop_in_play(resolve_game_ids(pl.read_parquet(HISTORY_PATH))).filter(
        (pl.col("season") == season) & (pl.col("week") == week)
        & (pl.col("market") == "receptions") & (pl.col("snapshot") == snapshot))
    if lines.height == 0:
        return pl.DataFrame(), (
            f"no receptions prices archived for {season} week {week} "
            f"({snapshot}) — the market is captured, so this means the week "
            "has not been snapshotted rather than that books are not posting")

    # Newest pre-kickoff capture per player and line. A week holds several
    # snapshots and pooling them prices one line against a number from three
    # days ago; `drop_in_play` above is what makes "newest" mean "last one you
    # could have bet" rather than "furthest into the fourth quarter".
    lines = (lines.sort("captured_at")
             .unique(subset=["player_name_norm", "point"], keep="last")
             .select(["player_name_norm", "point", "odds", "implied_prob",
                      "fair_prob", "n_books", "overround", "captured_at"]))

    b = mus.join(lines, on="player_name_norm", how="inner")
    if b.height == 0:
        return pl.DataFrame(), ("no posted line matches a candidate — the "
                                "names are not joining")

    over, push = prob_over(b["mu"].to_numpy(), b["point"].to_numpy(),
                           float(art["dispersion"]))
    # Ours, before the market is consulted. The comparable number: a book's
    # Over 5.0 price is a claim about the two outcomes that resolve, not all
    # three, so the push mass comes out before ours is set beside theirs.
    raw = fair_two_way(over, push)

    # And ours after. The count model loses to this market on its own — 0.690
    # against 0.673 on 2025 — and wins by a little once shrunk toward it, at a
    # weight fitted on a season it did not train on. So what the board serves
    # is the blend, with the raw number kept beside it because a row where we
    # agree with the book because we were pulled there is not the same as one
    # where we agreed on our own. See `count.fit_market_blend`.
    w = load_blend()
    blended = raw if w is None else blend_to_market(raw, b["fair_prob"].to_numpy(), w)

    b = b.with_columns([
        pl.Series("p_over_raw", over),
        pl.Series("p_push", push),
        pl.Series("model_only", raw),
        pl.Series("ours", blended),
        pl.lit(w).alias("blend_weight"),
    ])

    return b.with_columns([
        ((pl.col("ours") - pl.col("fair_prob")) * 100).alias("edge_pp"),
        # What a flat $100 on the over returns if we are right, at the posted
        # price. Negative edge is a row to fade if anything sold that side.
        (pl.when(pl.col("odds") > 0)
           .then(pl.col("ours") * pl.col("odds") - (1 - pl.col("ours")) * 100)
           .otherwise(pl.col("ours") * (10000.0 / -pl.col("odds"))
                      - (1 - pl.col("ours")) * 100)).alias("ev"),
        (pl.col("n_books") < THIN_BOOKS).alias("thin"),
    ]).sort("edge_pp", descending=True), ""
