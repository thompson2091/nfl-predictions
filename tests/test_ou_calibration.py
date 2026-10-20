"""The over/under calibration layer: recovers a known slope, never reorders."""
from __future__ import annotations

import numpy as np

from src.models import ou_calibration as C


def test_fit_recovers_an_overconfident_slope():
    rng = np.random.default_rng(0)
    truth = rng.uniform(0.25, 0.75, 40_000)
    y = (rng.uniform(size=truth.size) < truth).astype(float)
    # A model five times too extreme in log-odds, as measured 2026-10-09.
    raw = C._expit(5.0 * C._logit(truth))
    cal = C.fit(raw, y)
    assert abs(cal["b"] - 0.2) < 0.02
    assert abs(cal["a"]) < 0.03
    assert cal["log_loss_calibrated"] < cal["log_loss_raw"]


def test_apply_is_monotone_and_passes_through_when_unfitted():
    p = np.linspace(0.01, 0.99, 99)
    out = C.apply(p, {"a": 0.1, "b": 0.3})
    assert np.all(np.diff(out) > 0)
    assert np.array_equal(C.apply(p, None), p)
