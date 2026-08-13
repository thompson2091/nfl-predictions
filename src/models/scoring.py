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


def _break_ties(calibrated: np.ndarray, raw: np.ndarray) -> np.ndarray:
    """Restore ordering that isotonic regression flattened away.

    Isotonic calibration is a monotone *step* function, so every player landing
    on the same step comes out with an identical probability. Downstream that
    identical number becomes an identical share and an identical joint
    probability, and `rank("ordinal")` then resolves the tie by row order — so
    the game's headline pick was chosen by whoever the assembler happened to
    list first. Measured on the walk-forward backtests, the top score was tied
    in 10% of games here and up to 25% through the production artifacts, at
    2.2 players a game.

    The nudge is the pre-calibration score, scaled to be strictly smaller than
    the smallest gap between two distinct calibrated values. Ordering among
    distinct values is therefore untouched and the calibration is preserved:
    across four walk-forward seasons Brier was identical to five decimal places
    (0.09147) and AUC moved by +0.00002.

    This is not sold as an accuracy win — Top-1 rose 0.4987 to 0.5013, which is
    0.18 standard errors on 1,139 games. It removes an arbitrary choice, which
    is worth doing at any effect size. Dropping the calibrator entirely was
    tested at the same time and is worse: Top-3 0.8464 against 0.8551 and AUC
    0.83836 against 0.84189.

    The nudge goes **down** from each step, not up. Nudging up added to a
    calibrated value that can be 1.0 — the anytime-TD xgb calibrator already
    tops out at 0.999999 — and produced probabilities above 1. Nothing rejected
    them: they flowed into `1 - exp(-lambda*s)` and into Brier, where sklearn
    finally refused one at 1.00006 and made the bug visible. Subtracting instead
    is bounded by construction, because a probability can always be made
    slightly smaller and cannot always be made slightly larger.

    Ordering is identical either way: within a step the nudge is monotone in the
    raw score, and across steps it cannot reach a neighbour because it is at
    most half the smallest gap. The floor at zero can still tie the bottom step
    together, which is the one place a tie costs nothing — nobody's headline
    pick comes off the bottom step.
    """
    uniq = np.unique(calibrated)
    if uniq.size < 2:
        return calibrated
    eps = float(np.diff(uniq).min()) / 2.0
    span = float(raw.max() - raw.min())
    if eps <= 0.0 or span <= 0.0:
        return calibrated
    nudged = calibrated - eps * (raw.max() - raw) / span
    return np.clip(nudged, 0.0, 1.0)


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
            probs = _break_ties(IsotonicCalibrator.load(cal_path).calibrate(probs),
                                probs)
    return probs
