"""Let the anytime-TD model inform the first-TD ranking.

Whoever scores the game's first touchdown scored a touchdown. The two markets
are not independent problems, and the first-TD model has been solving its half
without ever seeing the other's answer.

Measured on four walk-forward folds, ranking first-TD candidates by a geometric
blend of the two models' probabilities:

    weight on anytime   0.0     0.3     0.4     0.5     0.7     1.0
    Top-1              16.2%   16.8%   17.0%   16.9%   16.1%   14.9%
    Top-3              37.1%   38.2%   38.6%   39.4%   38.6%   37.7%

A smooth plateau rather than a spike, which is what a real effect looks like.
The anytime model *alone* ranks first TD worse at Top-1 and better at Top-3 and
Top-5 than the dedicated model — the two carry different information, which is
why combining them beats either.

**Geometric, not arithmetic.** These are probabilities on very different scales
— an anytime favorite sits near 0.55, a first-TD favorite near 0.15 — and a
weighted average would let the larger number dominate the ordering regardless of
what either model meant. A geometric blend is a weighted average in log space,
so it combines the two rankings rather than their levels, and the level is
restored by normalizing within the game afterwards.

**The weight is fitted, never chosen.** The curve above was measured on the same
seasons it would be applied to, which makes its peak optimistic; the weight this
module serves is fitted on each fold's validation season and applied to the
held-out one. It is fitted by the *categorical* likelihood — the chance the
model assigns to the player who actually scored first, among that game's
candidates — because that is the question this market asks. Top-1 would not
work: it is a step function of the weight, so its gradient is zero almost
everywhere, which is exactly how `_optimize_ensemble_weights` once spent every
training run returning its own starting point.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

EPS = 1e-12

#: Searched rather than optimised. One bounded parameter on a smooth curve does
#: not need a solver, and a grid cannot wander into a corner the way L-BFGS-B
#: did when it was pointed at a step function.
WEIGHT_GRID = np.round(np.arange(0.0, 1.001, 0.05), 3)


def blend(first: np.ndarray, anytime: np.ndarray, weight: float) -> np.ndarray:
    """Geometric mean of two probability vectors, weighted toward `anytime`.

    Not normalized — callers rank within a game, and `predict` renormalises so
    a game's first-TD probabilities sum to one.
    """
    w = float(np.clip(weight, 0.0, 1.0))
    if w <= 0.0:
        return np.asarray(first, dtype=float)
    a = np.clip(np.asarray(first, dtype=float), EPS, None)
    b = np.clip(np.asarray(anytime, dtype=float), EPS, None)
    return np.exp((1.0 - w) * np.log(a) + w * np.log(b))


def categorical_nll(df: pl.DataFrame, prob_col: str, game_col: str = "game_id",
                    target_col: str = "target") -> float:
    """Negative log likelihood of the player who actually scored first.

    Within each game the scores are normalized to sum to one — exactly one
    player wins — and this returns the mean negative log probability the model
    placed on the winner. Lower is better, and unlike Top-1 it moves smoothly
    with the weight.
    """
    d = df.with_columns(
        (pl.col(prob_col).clip(EPS, None)
         / pl.col(prob_col).clip(EPS, None).sum().over(game_col)).alias("_p")
    ).filter(pl.col(target_col) == 1)
    if d.height == 0:
        return float("inf")
    return float(-np.log(np.clip(d["_p"].to_numpy(), EPS, 1.0)).mean())


def fit_weight(df: pl.DataFrame, first_col: str = "prob",
               anytime_col: str = "any_prob") -> dict:
    """Fit how far to lean on the anytime model, on data the fold may see.

    Returns 0.0 — no blend at all — when leaning on the other market does not
    beat the first-TD model alone. A weight is only worth serving if it earns
    its place on the season it was fitted to.
    """
    first = df[first_col].to_numpy()
    anytime = df[anytime_col].to_numpy()
    scores = []
    for w in WEIGHT_GRID:
        scored = df.with_columns(pl.Series("_b", blend(first, anytime, w)))
        scores.append((float(w), categorical_nll(scored, "_b")))

    baseline = scores[0][1]
    best_w, best = min(scores, key=lambda s: s[1])
    if not np.isfinite(best) or best >= baseline:
        best_w, best = 0.0, baseline

    return {
        "kind": "first_td_anytime_weight",
        "weight": best_w,
        "nll": best,
        "nll_first_td_only": baseline,
        "n_games": int(df.filter(pl.col("target") == 1).height),
        "curve": [{"weight": w, "nll": s} for w, s in scores],
        "fit_date": date.today().isoformat(),
    }


def anytime_probs(rows: pl.DataFrame, anytime_model_dir: Path,
                  model_name: str, active_models: list[str] | None = None,
                  features: pl.DataFrame | None = None) -> np.ndarray:
    """Score the same players through the anytime-TD model.

    The two markets share a candidate pool — same games, same players, one row
    each — but they are built into separate feature matrices with their own
    column sets, so the anytime rows are looked up by (game_id, player_id)
    rather than assumed to be in the same order.

    Players with no anytime row score 0, which the geometric blend floors to
    EPS: unknown is not evidence of anything, and a missing companion should
    not promote a player up the board.
    """
    import pickle

    from src.models.scoring import score
    from src.models.trainer import prepare_data
    from src.utils.paths import get_path

    anytime_model_dir = Path(anytime_model_dir)
    feature_cols = pickle.loads(
        (anytime_model_dir / "feature_cols.pkl").read_bytes())
    if features is None:
        features = pl.read_parquet(
            get_path("processed", "anytime_td") / "features.parquet")

    keys = rows.select(["game_id", "player_id"]).with_row_index("_order")
    matched = keys.join(features, on=["game_id", "player_id"], how="left")
    matched = matched.sort("_order")

    have = matched.filter(pl.col(feature_cols[0]).is_not_null()
                          if feature_cols[0] in matched.columns
                          else pl.lit(True))
    if have.height == 0:
        return np.zeros(rows.height)

    X, _ = prepare_data(
        matched.with_columns(pl.lit(0.0).alias("target")), feature_cols)
    probs = score(model_name, X, feature_cols, anytime_model_dir,
                  active_models=active_models)
    return np.asarray(probs, dtype=float)


def save(weight: dict, path) -> None:
    import json
    Path(path).write_text(json.dumps(weight, indent=2) + "\n")


def load(path) -> dict | None:
    import json
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else None
