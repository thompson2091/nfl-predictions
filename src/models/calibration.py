"""Probability calibration.

Temperature scaling stretches or compresses the logit scale by one number. That
fixes a model that is uniformly over- or under-confident, but it cannot fix a
model whose error changes *shape* across the probability range.

Measured against three seasons of archived sportsbook prices, this model is
exactly the latter case: near-perfect below 0.10, under-predicting by 5-8 points
between 0.20 and 0.45, and over-predicting above 0.45. No single temperature
can correct that — pulling the middle up would push the tails further out.
Isotonic regression can, because it fits a free monotone shape.

`IsotonicCalibrator` is therefore available alongside `TemperatureScaler`. It is
strictly more flexible and strictly more prone to overfitting, so it is fit on
the validation season only and falls back to temperature when there is too
little data to support it.
"""
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


class IsotonicCalibrator:
    """Monotone free-form calibration, fit on held-out validation data.

    Preserves ranking exactly (isotonic is non-decreasing), so it can only change
    *how confident* the model is, never *who it likes*. Use when the calibration
    error varies across the probability range rather than being a uniform
    stretch — see the module docstring for the measured shape here.
    """

    MIN_ROWS = 2000          # below this, a free shape overfits; use temperature

    def __init__(self):
        self.iso = None
        self.fallback = TemperatureScaler()

    def fit(self, raw_probs: np.ndarray, y_true: np.ndarray) -> None:
        self.fallback.fit(raw_probs, y_true)
        if len(raw_probs) < self.MIN_ROWS or len(np.unique(y_true)) < 2:
            print(f"  Isotonic: only {len(raw_probs)} rows — using temperature instead")
            return
        from sklearn.isotonic import IsotonicRegression
        self.iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        self.iso.fit(raw_probs, y_true)
        print(f"  Isotonic calibration fit on {len(raw_probs):,} rows")

    def calibrate(self, raw_probs: np.ndarray) -> np.ndarray:
        if self.iso is None:
            return self.fallback.calibrate(raw_probs)
        return np.clip(self.iso.predict(raw_probs), 1e-6, 1 - 1e-6)

    def save(self, path: Path) -> None:
        with open(path, "wb") as f:
            pickle.dump({"iso": self.iso, "temperature": self.fallback.temperature}, f)

    @classmethod
    def load(cls, path: Path) -> "IsotonicCalibrator":
        with open(path, "rb") as f:
            data = pickle.load(f)
        obj = cls()
        obj.iso = data.get("iso")
        obj.fallback.temperature = data.get("temperature", 1.0)
        return obj
