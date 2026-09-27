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
        self._smooth_saturated(raw_probs, y_true)
        print(f"  Isotonic calibration fit on {len(raw_probs):,} rows")

    def _smooth_saturated(self, raw_probs: np.ndarray,
                          y_true: np.ndarray) -> None:
        """Replace a 0 or a 1 with what its own bin can support.

        ISOTONIC ENDS IN 0 AND 1 AND MEANS NEITHER. A bin is set to 1.0 when
        every calibration sample that fell in it happened to be a positive —
        on a thin tail that is a handful of games, not a certainty. On
        2026-09-27 the anytime-TD curve stepped from 0.722 straight to 1.000
        and published a player at 100% to score a touchdown, with the edge, the
        EV and a "Good value" tag all computed from it.

        Each saturated knot becomes the Laplace estimate of its OWN bin:
        (k + 1) / (m + 2), the posterior mean under a uniform prior. A bin of
        3 for 3 is 80%, one of 40 for 40 is 97.6% — the correction shrinks as
        the evidence grows, which is the property worth having and the reason
        this is not a fixed cap. Nothing is chosen: `k` and `m` are counted off
        the calibration data the fit already saw.

        Monotonicity is preserved by construction — the top bin can only be
        pulled down toward the bin below it, never past it, and the bottom bin
        can only be pulled up.
        """
        y = np.asarray(self.iso.y_thresholds_, dtype=float)
        x = np.asarray(self.iso.X_thresholds_, dtype=float)
        if y.size < 2:
            return
        raw = np.asarray(raw_probs, dtype=float)
        truth = np.asarray(y_true, dtype=float)

        def laplace(mask: np.ndarray) -> float | None:
            m = int(mask.sum())
            if m == 0:
                return None
            k = float(truth[mask].sum())
            return (k + 1.0) / (m + 2.0)

        # The top: every sample at or above the first knot that reads 1.0.
        if float(y.max()) >= 1.0:
            lo = float(x[y >= 1.0].min())
            est = laplace(raw >= lo)
            if est is not None:
                inner = y[y < 1.0]
                floor = float(inner.max()) if inner.size else 0.0
                y[y >= 1.0] = max(est, floor)
        # And the bottom, the same way.
        if float(y.min()) <= 0.0:
            hi = float(x[y <= 0.0].max())
            est = laplace(raw <= hi)
            if est is not None:
                inner = y[y > 0.0]
                ceil = float(inner.min()) if inner.size else 1.0
                y[y <= 0.0] = min(est, ceil)
        self.iso.y_thresholds_ = y

    def _resolved(self) -> tuple[float, float]:
        """The range this fit actually resolved, read off its own knots.

        ISOTONIC ENDS IN 0 AND 1 AND MEANS NEITHER. Its top bin is set to 1.0
        whenever every calibration sample in it happened to be a positive,
        which on a thin tail is a handful of games rather than a finding; the
        bottom bin is 0.0 the same way. On 2026-09-27 the anytime-TD curve
        stepped from 0.722 straight to 1.000 at a raw score of 0.691, with
        nothing between — so a player landing a thousandth over that line was
        published at 100% to score a touchdown, and the +36pp edge and "Good
        value" tag under it were computed from that.

        The clip that used to be here was `1e-6`, which turns 1.0 into
        0.999999 and displays as 100.0%: cosmetic, not a bound.

        The honest ceiling is the highest value the calibration data resolved
        to — the largest knot that is not saturated. It is read from the fit
        rather than chosen, so it moves with the data and there is no constant
        here to go stale. Ranking is untouched: isotonic is monotone, and this
        only flattens the saturated tail onto the last real value.
        """
        y = np.asarray(self.iso.y_thresholds_, dtype=float)
        inner = y[(y > 0.0) & (y < 1.0)]
        if inner.size == 0:
            return 1e-6, 1 - 1e-6
        return float(inner.min()), float(inner.max())

    def calibrate(self, raw_probs: np.ndarray) -> np.ndarray:
        if self.iso is None:
            return self.fallback.calibrate(raw_probs)
        lo, hi = self._resolved()
        return np.clip(self.iso.predict(raw_probs), lo, hi)

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
