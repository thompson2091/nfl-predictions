"""One way to turn a feature matrix into probabilities.

Four places needed this — prediction, the backtest, the blend stacker and the
dashboard — and each grew its own copy. They drifted, in ways nobody could see
from the output: the backtest applied no calibrator while the app applied one,
so the two disagreed about the same player and each looked internally
consistent. The blend stacker's copy could not handle `"ensemble"` at all and
raised `Unknown model 'ensemble'` the moment a market was configured to use it.

Scoring is one operation. It lives here, and callers ask for it rather than
rebuilding it.
"""
from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np

from src.models.calibration import IsotonicCalibrator
from src.models.registry import get_model, ensure_registered


def ensemble_weights(model_dir: Path, active_models: list[str]) -> dict[str, float]:
    """Fitted ensemble weights, falling back to equal weighting."""
    path = Path(model_dir) / "ensemble_weights.pkl"
    if path.exists():
        return pickle.loads(path.read_bytes())
    return {name: 1.0 / len(active_models) for name in active_models}


def score(model_name: str, X: np.ndarray, feature_cols: list[str],
          model_dir: Path, calibrate: bool = True,
          active_models: list[str] | None = None) -> np.ndarray:
    """Probabilities for `X`, handling single models and `"ensemble"` alike.

    `calibrate` exists only so a caller can deliberately inspect raw model
    output. Production always calibrates, so leaving it True is what keeps the
    backtest measuring the path the app actually serves.
    """
    ensure_registered()
    model_dir = Path(model_dir)

    if model_name == "ensemble":
        if active_models is None:
            from src.utils.config import get_config
            active_models = list(get_config()["models"]["active"])
        weights = ensemble_weights(model_dir, active_models)
        probs = np.zeros(X.shape[0])
        for name, w in weights.items():
            probs += w * score(name, X, feature_cols, model_dir,
                               calibrate=calibrate, active_models=active_models)
        return probs

    model = get_model(model_name).load(model_dir / f"{model_name}.pkl")
    model.feature_names = feature_cols
    probs = model.predict_proba(X)

    if calibrate:
        cal_path = model_dir / f"{model_name}_calibrator.pkl"
        if cal_path.exists():
            probs = IsotonicCalibrator.load(cal_path).calibrate(probs)
    return probs
