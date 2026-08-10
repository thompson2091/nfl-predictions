"""Model wrapper protocol for pluggable prediction algorithms."""
from __future__ import annotations
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class ModelWrapper(Protocol):
    """Interface every model must implement."""

    name: str

    def fit(self, X_train: np.ndarray, y_train: np.ndarray,
            X_val: np.ndarray, y_val: np.ndarray, config: dict) -> None:
        ...

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Return 1-D array of positive-class probabilities."""
        ...

    def feature_importances(self) -> dict[str, float] | None:
        """Return {feature_name: importance} or None if not supported."""
        ...

    def save(self, path: Path) -> None:
        ...

    @classmethod
    def load(cls, path: Path) -> ModelWrapper:
        ...
