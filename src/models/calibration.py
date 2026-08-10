"""Temperature scaling for probability calibration."""
from __future__ import annotations
import pickle
from pathlib import Path

import numpy as np
from scipy.optimize import minimize_scalar


class TemperatureScaler:
    """Learn temperature T on validation set, divide logits by T.

    Single parameter — minimal overfitting risk vs isotonic regression.
    """

    def __init__(self):
        self.temperature: float = 1.0

    def fit(self, raw_probs: np.ndarray, y_true: np.ndarray) -> None:
        """Find optimal temperature on validation data."""
        # Clip to avoid log(0)
        probs = np.clip(raw_probs, 1e-7, 1 - 1e-7)
        logits = np.log(probs / (1 - probs))

        def nll(T):
            scaled = logits / T
            p = 1 / (1 + np.exp(-scaled))
            p = np.clip(p, 1e-7, 1 - 1e-7)
            return -np.mean(y_true * np.log(p) + (1 - y_true) * np.log(1 - p))

        result = minimize_scalar(nll, bounds=(0.1, 10.0), method="bounded")
        self.temperature = result.x
        print(f"  Temperature scaling: T={self.temperature:.4f}")

    def calibrate(self, raw_probs: np.ndarray) -> np.ndarray:
        """Apply temperature scaling to raw probabilities."""
        probs = np.clip(raw_probs, 1e-7, 1 - 1e-7)
        logits = np.log(probs / (1 - probs))
        scaled = logits / self.temperature
        return 1 / (1 + np.exp(-scaled))

    def save(self, path: Path) -> None:
        with open(path, "wb") as f:
            pickle.dump({"temperature": self.temperature}, f)

    @classmethod
    def load(cls, path: Path) -> TemperatureScaler:
        with open(path, "rb") as f:
            data = pickle.load(f)
        obj = cls()
        obj.temperature = data["temperature"]
        return obj
