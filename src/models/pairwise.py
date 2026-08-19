"""Rank the board, rather than price each player and sort the result.

Every model here is fitted pointwise: each player-game is an independent coin,
and the loss rewards getting each probability right on its own. Top-1 is not
that question. It asks whether the player we put *first* is one of the players
who scored, and a pointwise loss takes no credit for that — it spends capacity
separating a 3% player from a 1% player in a game already decided.

`condlogit` was the first attempt at fixing this and it failed twice, on the
leaked matrix (2026-08-13) and again on the clean one (2026-08-19, anytime
-0.27pp p=0.860). The reason is visible in what it assumes. A conditional logit
is a softmax over a group: the likelihood that ONE named candidate won. That is
exactly right for first TD, where exactly one player scores first. It is wrong
for anytime TD, where 4.3 players score in an average game — the model is being
asked to explain a single winner in a competition that has several, so it must
push probability mass away from real scorers to concentrate it on one.

A pairwise ranking loss makes no such assumption. It says only: every player who
scored should outrank every player who did not, within this game. Groups of any
number of winners are fine. That is the Top-1 objective without the
one-winner-per-game fiction, and it is what this model trains.

**Grouped by game, not by team-game.** `make diagnose` found 91.9% of
team-games contain a scorer, and 84% of games contain one on both teams, so the
team is almost never what separates a right pick from a wrong one. The board's
top pick competes against every candidate in the game.

Registered but not active. It enters the same way anything else does — screen,
gate, then the config — and `experiments/pairwise-rank.yaml` is the overlay.
"""
from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
from xgboost import XGBRanker

from src.models.registry import register

#: Mirrors `ranker.DEFAULTS` so a comparison between the two objectives is a
#: comparison between the objectives and not between two hyperparameter sets.
DEFAULTS = {
    "n_estimators": 500,
    "learning_rate": 0.05,
    "max_depth": 6,
    "min_child_weight": 20,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "early_stopping_rounds": 50,
}

#: A group with no scorer, or with nothing but scorers, contains no pair to
#: order and contributes no gradient. Dropping them keeps the step size honest
#: rather than diluting it with zeros.
def _usable(groups: np.ndarray, y: np.ndarray) -> np.ndarray:
    if groups.size == 0:
        return np.zeros(0, dtype=bool)
    n = int(groups.max()) + 1
    pos = np.zeros(n)
    tot = np.zeros(n)
    np.add.at(pos, groups, y)
    np.add.at(tot, groups, 1.0)
    mixed = (pos > 0) & (pos < tot)
    return mixed[groups]


def _sorted_by_group(groups: np.ndarray, y: np.ndarray, X: np.ndarray):
    """XGBRanker needs contiguous groups and their sizes, in row order."""
    order = np.argsort(groups, kind="stable")
    g, y, X = groups[order], y[order], X[order]
    _, sizes = np.unique(g, return_counts=True)
    return X, y, sizes


@register("xgbrank")
class PairwiseRankModel:
    """XGBoost with a pairwise ranking objective, grouped by game."""

    name = "xgbrank"
    #: Hands this model its group arrays; see `trainer.train_all`.
    needs_groups = True
    #: The board's top pick is an argmax over the whole game, so that is the
    #: competition — not the team-game `condlogit` uses for anytime TD.
    group_unit = "game"

    def __init__(self):
        self.model: XGBRanker | None = None
        self.feature_names: list[str] = []

    def fit(self, X_train: np.ndarray, y_train: np.ndarray,
            X_val: np.ndarray, y_val: np.ndarray, config: dict,
            groups: tuple[np.ndarray, np.ndarray] | None = None) -> None:
        if groups is None:
            raise ValueError(
                "xgbrank needs group ids; trainer must pass groups= for any "
                "model declaring needs_groups")
        g_tr, g_va = (np.asarray(g, dtype=np.int64) for g in groups)

        keep_tr, keep_va = _usable(g_tr, y_train), _usable(g_va, y_val)
        Xtr, ytr, size_tr = _sorted_by_group(
            g_tr[keep_tr], y_train[keep_tr], X_train[keep_tr])
        Xva, yva, size_va = _sorted_by_group(
            g_va[keep_va], y_val[keep_va], X_val[keep_va])

        params = {k: config.get(k, v) for k, v in DEFAULTS.items()}
        self.model = XGBRanker(
            **params,
            objective="rank:pairwise",
            eval_metric=["map@1", "ndcg@3"],
            random_state=config.get("seed", 42),
            verbosity=0,
        )
        self.model.fit(Xtr, ytr, group=size_tr,
                       eval_set=[(Xva, yva)], eval_group=[size_va],
                       verbose=False)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Sigmoid of the ranking score: monotone, so the order is untouched.

        A ranking model has no probabilistic reading of its own — the score is
        only meaningful against the other candidates in the same game. The
        isotonic calibrator downstream is what gives it a level, exactly as it
        does for `condlogit`.
        """
        scores = self.model.predict(X)
        return 1.0 / (1.0 + np.exp(-np.clip(scores, -50, 50)))

    def feature_importances(self) -> dict[str, float] | None:
        if self.model is None or not self.feature_names:
            return None
        return dict(zip(self.feature_names,
                        self.model.feature_importances_.astype(float)))

    def save(self, path: Path) -> None:
        with open(path, "wb") as f:
            pickle.dump({"model": self.model,
                         "feature_names": self.feature_names}, f)

    @classmethod
    def load(cls, path: Path) -> "PairwiseRankModel":
        with open(path, "rb") as f:
            data = pickle.load(f)
        obj = cls()
        obj.model = data["model"]
        obj.feature_names = data.get("feature_names", [])
        return obj
