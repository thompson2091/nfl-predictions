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

NOT WIRED IN, AND NOT YET TRUSTWORTHY. Nothing imports this: it is not in the
weekly pipeline, not in MARKETS and not on the dashboard, and it must not be
until the following is resolved.

The first board it produced carried +70 point edges, which in this project
means a bug rather than an edge. It is the null-as-zero trap again, landing on
a count model for the first time. Caleb Southampton-style rookies have no usage
history at all — `player_targets_avg_3g` and `player_receptions_avg_3g` are
null — and `prepare_data` fills a missing feature with 0.0. So the model reads
"91% snap share, listed starter, second on the depth chart, zero targets, zero
receptions" and predicts 8.52 receptions, above Amon-Ra St. Brown on 14 targets
and 9.7 receptions a game.

On the yes/no markets the same nulls move a probability by a few points and are
absorbed by densifying and carry-forward. On a count model they move the mean
itself, and the line maths then turns a wrong mean into a confident wrong
probability at every line. Two things to check before this is believed: that
the serving path applies `trainer._filter_low_activity`, which the TD predict
path runs and this does not, and whether the fix belongs in the features rather
than the filter — a player with no history is not a player with zero usage.

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
    from src.models.trainer import prepare_data
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
    if df.height == 0:
        return None

    # `prepare_data` wants a target column and we are predicting, not scoring.
    # Handing it a constant keeps one definition of how a matrix becomes a
    # numpy array — including that a feature the model asks for and the matrix
    # does not have is filled with 0.0, which is the behaviour that scored
    # every tight end as though it were not one when a reference level moved.
    if "target" not in df.columns:
        df = df.with_columns(pl.lit(0).alias("target"))
    X, _ = prepare_data(df, list(art["feature_names"]))
    mu = np.clip(art["model"].predict(X), 1e-6, None)

    return df.select([
        "season", "week", "game_id", "player_id", "player_name", "team",
        _norm_name_expr("player_name").alias("player_name_norm"),
    ]).with_columns(pl.Series("mu", mu))


def board_for_week(season: int, week: int, snapshot: str = "close"
                   ) -> tuple[pl.DataFrame, str]:
    """Every posted receptions line, with what we make it against what it pays.

    Returns `(board, message)`; an empty board always carries a reason.
    """
    from src.ingest.odds_history import HISTORY_PATH, resolve_game_ids
    from src.models.count import fair_two_way, prob_over

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
    lines = resolve_game_ids(pl.read_parquet(HISTORY_PATH)).filter(
        (pl.col("season") == season) & (pl.col("week") == week)
        & (pl.col("market") == "receptions") & (pl.col("snapshot") == snapshot))
    if lines.height == 0:
        return pl.DataFrame(), (
            f"no receptions prices archived for {season} week {week} "
            f"({snapshot}) — the market is captured, so this means the week "
            "has not been snapshotted rather than that books are not posting")

    # Newest capture per player and line. A week holds several snapshots and
    # pooling them prices one line against a number from three days ago.
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
    b = b.with_columns([
        pl.Series("p_over_raw", over),
        pl.Series("p_push", push),
        # The comparable number. A book's Over 5.0 price is a claim about the
        # two outcomes that resolve, not all three, so the push mass has to
        # come out before ours is set beside theirs.
        pl.Series("ours", fair_two_way(over, push)),
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
