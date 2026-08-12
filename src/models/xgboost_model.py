"""XGBoost model wrapper.

Every hyperparameter is declared in DEFAULTS and overridable from
`config/settings.yaml -> model.xgb`. That uniformity is the point: this class
used to read `max_depth`, `subsample` and `colsample_bytree` from config while
hardcoding `n_estimators` and `learning_rate`, and the config declared 500 and
0.05 against a served 2000 and 0.02. Anyone tuning those two through config
changed nothing and got no error. tests/test_leakage.py asserts the config
block and DEFAULTS cover the same keys, so a half-wired parameter fails rather
than silently doing nothing.

The values themselves were hand-picked, then checked: a 60-configuration
walk-forward random search over depth, learning rate, both sampling fractions,
min_child_weight and both regularisers did not beat them by more than noise.
See `models.xgb` in config for the measured comparison.
"""
from __future__ import annotations
import pickle
from pathlib import Path

import numpy as np
from xgboost import XGBClassifier

from src.models.registry import register

#: Served values. Anything here can be overridden from config; nothing may be
#: hardcoded below this dict.
DEFAULTS = {
    "n_estimators": 2000,
    "learning_rate": 0.02,
    "max_depth": 6,
    "min_child_weight": 20,
    # 0.8/0.8, not the 0.7/0.6 that used to sit here as a fallback: config
    # already declared 0.8 for both and those two keys *were* wired, so 0.8 is
    # what every trained model has actually used.
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "early_stopping_rounds": 50,
}


@register("xgb")
class XGBoostModel:
    name = "xgb"

    def __init__(self):
        self.model: XGBClassifier | None = None
        self.feature_names: list[str] = []

    def fit(self, X_train: np.ndarray, y_train: np.ndarray,
            X_val: np.ndarray, y_val: np.ndarray, config: dict) -> None:
        params = {k: config.get(k, v) for k, v in DEFAULTS.items()}
        self.model = XGBClassifier(
            **params,
            random_state=config.get("seed", 42),
            eval_metric="logloss",
            verbosity=0,
        )
        self.model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return self.model.predict_proba(X)[:, 1]

    def feature_importances(self) -> dict[str, float] | None:
        if self.model is None or not self.feature_names:
            return None
        return dict(zip(self.feature_names, self.model.feature_importances_.astype(float)))

    def save(self, path: Path) -> None:
        with open(path, "wb") as f:
            pickle.dump({
                "model": self.model,
                "feature_names": self.feature_names,
            }, f)

    @classmethod
    def load(cls, path: Path) -> XGBoostModel:
        with open(path, "rb") as f:
            data = pickle.load(f)
        obj = cls()
        obj.model = data["model"]
        obj.feature_names = data.get("feature_names", [])
        return obj
