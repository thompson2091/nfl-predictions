"""XGBoost model wrapper."""
from __future__ import annotations
import pickle
from pathlib import Path

import numpy as np
from xgboost import XGBClassifier

from src.models.registry import register


@register("xgb")
class XGBoostModel:
    name = "xgb"

    def __init__(self):
        self.model: XGBClassifier | None = None
        self.feature_names: list[str] = []

    def fit(self, X_train: np.ndarray, y_train: np.ndarray,
            X_val: np.ndarray, y_val: np.ndarray, config: dict) -> None:
        self.model = XGBClassifier(
            n_estimators=2000,
            learning_rate=0.02,
            max_depth=config.get("max_depth", 6),
            min_child_weight=20,
            subsample=config.get("subsample", 0.7),
            colsample_bytree=config.get("colsample_bytree", 0.6),
            reg_alpha=0.1,
            reg_lambda=1.0,
            random_state=config.get("seed", 42),
            eval_metric="logloss",
            verbosity=0,
            early_stopping_rounds=50,
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
