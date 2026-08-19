"""Train the objective we are actually scored on.

Every model in this repo is fitted pointwise on binary log loss: each
player-game is an independent coin, and the loss asks whether its probability
was well calibrated. But nothing on the board is a coin. The number that
matters — Top-1 — is a *within-game argmax*, and for first TD exactly one
player in each game wins. A pointwise loss cannot see that constraint. It will
happily spend capacity separating a 3% player from a 1% player in a game
already decided, and take no credit for putting the right player on top.

The conditional logit is not an approximation of that. It is the likelihood of
the thing that happened: given the candidates in this game, which one scored
first. Within a group the scores go through a softmax, and the loss is the
negative log probability assigned to the player who actually won. For a group
`g` with scores `s` and labels `y`:

    p = softmax(s)
    loss  = -sum_i y_i * log p_i
    grad  = (sum_i y_i) * p - y
    hess  = (sum_i y_i) * p * (1 - p)

`sum_i y_i` is 1 for first TD — one winner per game. It is 0 when the actual
scorer was filtered out of the candidate pool, and the gradient correctly goes
to zero: a group with no winner in it carries no information about who would
have won. It is 2 or more for anytime TD grouped by team-game, where several
players score; that is the multinomial-with-repetition generalisation and it is
what "fit shares directly" means for that market.

The group is the market's own unit of competition:

    first_td     game_id            one winner per game
    anytime_td   game_id x team     the joint model consumes team-level shares,
                                    so the team-game is where players compete

Scores are unbounded, so `predict_proba` squashes them through a sigmoid. That
is monotone, so it changes no ranking, and the isotonic calibrator downstream
maps them to honest probabilities against the serving population — the same
treatment every other model gets. `joint.combine` needs shares only
*proportional* within a team, which a ranker satisfies by construction.
"""
from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import polars as pl
from xgboost import XGBRegressor

from src.models.registry import register

#: Served values. Anything here can be overridden from `model.condlogit` in
#: config; nothing may be hardcoded below this dict. Deliberately the same
#: shape as the xgb block, so the two are comparable — a difference in Top-1
#: between them should be the objective, not the tree.
DEFAULTS = {
    "n_estimators": 2000,
    "learning_rate": 0.02,
    "max_depth": 6,
    "min_child_weight": 20,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "early_stopping_rounds": 50,
}

#: Groups smaller than this cannot teach anything about ranking — a
#: one-candidate game has a softmax of 1.0 whatever the score is — and their
#: zero gradients only dilute the step size.
MIN_GROUP = 2

#: Floor on the diagonal Hessian. Groups whose winner was filtered out of the
#: pool contribute an exactly-zero Hessian, and xgboost divides by it.
HESS_FLOOR = 1e-6


def group_ids(df: pl.DataFrame, target_type: str,
              unit: str = "market") -> np.ndarray:
    """The competition unit for this market, as contiguous integer codes.

    `unit="market"` is the competition the *market* defines: the game for first
    TD, where exactly one player scores first, and the team-game for anytime,
    which is what the joint model consumes as shares.

    `unit="game"` groups by game for both, which is the competition **Top-1**
    defines — the board's top pick is an argmax across every candidate in the
    game, both teams included. For anytime TD these differ, and the difference
    is not cosmetic: `make diagnose` on 2026-08-19 found that 91.9% of
    team-games contain a scorer and 84% of games contain one on BOTH teams, so
    grouping by team-game splits the ranking problem along a line that is
    almost never the discriminator.
    """
    if unit not in ("market", "game"):
        raise ValueError(f"unknown grouping unit {unit!r}")
    if unit == "game" or target_type == "first_td":
        keys = df["game_id"].cast(pl.Utf8)
    else:
        keys = (df["game_id"].cast(pl.Utf8) + "|" + df["team"].cast(pl.Utf8))
    # Factorise to dense codes: the objective indexes arrays by group.
    codes, _ = _factorise(keys.to_list())
    return codes


def _factorise(values: list) -> tuple[np.ndarray, list]:
    seen: dict = {}
    out = np.empty(len(values), dtype=np.int64)
    for i, v in enumerate(values):
        if v not in seen:
            seen[v] = len(seen)
        out[i] = seen[v]
    return out, list(seen)


def _group_softmax(scores: np.ndarray, groups: np.ndarray,
                   n_groups: int) -> np.ndarray:
    """Softmax within each group, computed max-shifted for stability."""
    top = np.full(n_groups, -np.inf)
    np.maximum.at(top, groups, scores)
    shifted = np.exp(scores - top[groups])
    denom = np.zeros(n_groups)
    np.add.at(denom, groups, shifted)
    # A group of one still normalises to 1.0; no division by zero is possible
    # because every group has at least the row that created it.
    return shifted / denom[groups]


def conditional_logit_objective(groups: np.ndarray, n_groups: int):
    """(grad, hess) for the softmax-within-group likelihood."""
    def objective(y_true: np.ndarray, y_pred: np.ndarray):
        p = _group_softmax(y_pred, groups, n_groups)
        wins = np.zeros(n_groups)
        np.add.at(wins, groups, y_true)
        w = wins[groups]
        grad = w * p - y_true
        hess = np.maximum(w * p * (1.0 - p), HESS_FLOOR)
        return grad, hess
    return objective


def conditional_logit_nll(groups: np.ndarray, n_groups: int):
    """Mean negative log likelihood per group — the early-stopping metric.

    Stopping on pointwise log loss would defeat the point of the exercise: the
    model would be selected on the objective it is *not* being trained for.
    Groups with no winner in the pool are excluded rather than scored as zero,
    so the metric does not improve merely by the pool losing scorers.
    """
    def metric(y_true: np.ndarray, y_pred: np.ndarray) -> float:
        p = _group_softmax(y_pred, groups, n_groups)
        wins = np.zeros(n_groups)
        np.add.at(wins, groups, y_true)
        ll = np.zeros(n_groups)
        np.add.at(ll, groups, y_true * np.log(np.clip(p, 1e-12, None)))
        scored = wins > 0
        if not scored.any():
            return 0.0
        return float(-ll[scored].sum() / scored.sum())
    return metric


@register("condlogit")
class ConditionalLogitModel:
    """XGBoost trained on the within-group multinomial likelihood."""

    name = "condlogit"
    #: Tells `trainer.train_all` to hand this model its group arrays. Without
    #: it the model would silently train every row as its own group, which is
    #: exactly the pointwise loss it exists to replace.
    needs_groups = True

    def __init__(self):
        self.model: XGBRegressor | None = None
        self.feature_names: list[str] = []

    def fit(self, X_train: np.ndarray, y_train: np.ndarray,
            X_val: np.ndarray, y_val: np.ndarray, config: dict,
            groups: tuple[np.ndarray, np.ndarray] | None = None) -> None:
        if groups is None:
            raise ValueError(
                "condlogit needs group ids; trainer must pass groups= for any "
                "model declaring needs_groups")
        g_train, g_val = (np.asarray(g, dtype=np.int64) for g in groups)
        g_train, y_train, X_train = _drop_singletons(g_train, y_train, X_train)
        n_train = int(g_train.max()) + 1 if g_train.size else 0
        n_val = int(g_val.max()) + 1 if g_val.size else 0

        params = {k: config.get(k, v) for k, v in DEFAULTS.items()}
        self.model = XGBRegressor(
            **params,
            objective=conditional_logit_objective(g_train, n_train),
            eval_metric=conditional_logit_nll(g_val, n_val),
            # A custom objective works in margin space, where the default
            # probability-space base score of 0.5 is meaningless.
            base_score=0.0,
            random_state=config.get("seed", 42),
            verbosity=0,
        )
        self.model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Sigmoid of the margin: monotone, so ranking is untouched.

        The level is meaningless until the isotonic calibrator has seen it,
        which is true of the raw output of every model here — this one is just
        honest about having no probabilistic reading of its own.
        """
        scores = self.model.predict(X)
        return 1.0 / (1.0 + np.exp(-np.clip(scores, -50, 50)))

    def feature_importances(self) -> dict[str, float] | None:
        if self.model is None or not self.feature_names:
            return None
        return dict(zip(self.feature_names,
                        self.model.feature_importances_.astype(float)))

    def save(self, path: Path) -> None:
        # The objective and metric closures hold group arrays for the fold they
        # were fitted on, and pickling them would both bloat the artifact and
        # restore a model that thinks it is still in training. Neither is used
        # at predict time.
        self.model.set_params(objective="reg:squarederror", eval_metric=None)
        with open(path, "wb") as f:
            pickle.dump({"model": self.model,
                         "feature_names": self.feature_names}, f)

    @classmethod
    def load(cls, path: Path) -> "ConditionalLogitModel":
        with open(path, "rb") as f:
            data = pickle.load(f)
        obj = cls()
        obj.model = data["model"]
        obj.feature_names = data.get("feature_names", [])
        return obj


def _drop_singletons(groups: np.ndarray, y: np.ndarray, X: np.ndarray):
    """Remove groups too small to express a preference between candidates."""
    if groups.size == 0:
        return groups, y, X
    counts = np.bincount(groups)
    keep = counts[groups] >= MIN_GROUP
    if keep.all():
        return groups, y, X
    kept, _ = _factorise(groups[keep].tolist())
    return kept, y[keep], X[keep]
