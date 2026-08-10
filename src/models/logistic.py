"""Logistic Regression model wrapper."""
from __future__ import annotations
import pickle
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from src.models.registry import register


@register("lr")
class LogisticModel:
    name = "lr"

    def __init__(self):
        self.model: LogisticRegression | None = None
        self.scaler: StandardScaler | None = None
        self.feature_names: list[str] = []

    def fit(self, X_train: np.ndarray, y_train: np.ndarray,
            X_val: np.ndarray, y_val: np.ndarray, config: dict) -> None:
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X_train)

        self.model = LogisticRegression(
            max_iter=config.get("max_iter", 1000),
            C=config.get("C", 0.01),
            random_state=config.get("seed", 42),
        )
        self.model.fit(X_scaled, y_train)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        X_scaled = self.scaler.transform(X)
        return self.model.predict_proba(X_scaled)[:, 1]

    def feature_importances(self) -> dict[str, float] | None:
        if self.model is None or not self.feature_names:
            return None
        return dict(zip(self.feature_names, np.abs(self.model.coef_[0])))

    def save(self, path: Path) -> None:
        with open(path, "wb") as f:
            pickle.dump({
                "model": self.model,
                "scaler": self.scaler,
                "feature_names": self.feature_names,
            }, f)

    @classmethod
    def load(cls, path: Path) -> LogisticModel:
        with open(path, "rb") as f:
            data = pickle.load(f)
        obj = cls()
        obj.model = data["model"]
        obj.scaler = data["scaler"]
        obj.feature_names = data.get("feature_names", [])
        return obj
