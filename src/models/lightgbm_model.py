"""LightGBM model wrapper.

Hyperparameters live in DEFAULTS and are overridable from
`config/settings.yaml -> model.lgbm`. See src/models/xgboost_model.py for why
the half-wired arrangement this replaces was worth removing: some keys were
read from config, others hardcoded, and the config declared values for the
hardcoded ones that had no effect.

`early_stopping_rounds` is separate from DEFAULTS because LightGBM takes it as
a callback rather than a constructor argument.
"""
from __future__ import annotations
import pickle
from pathlib import Path

import numpy as np
import lightgbm
from lightgbm import LGBMClassifier

from src.models.registry import register

#: Served values. Overridable from config; nothing may be hardcoded below.
DEFAULTS = {
    "n_estimators": 2000,
    "learning_rate": 0.02,
    "max_depth": 6,
    "num_leaves": 31,
    "min_child_samples": 20,
    # 0.8/0.8 — config declared these and they were wired, so this is what was
    # served. See the same note in src/models/xgboost_model.py.
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    # LightGBM takes this as a callback rather than a constructor argument, so
    # `_build` filters it out. It stays in DEFAULTS anyway so that config and
    # the wrapper declare the same set of knobs for both tree models.
    "early_stopping_rounds": 50,
}

#: Real knobs minus the one that is not a constructor argument.
_CTOR_KEYS = [k for k in DEFAULTS if k != "early_stopping_rounds"]


@register("lgbm")
class LightGBMModel:
    name = "lgbm"

    def __init__(self):
        self.model: LGBMClassifier | None = None
        self.feature_names: list[str] = []
        self.selected_cols: list[str] | None = None

    def _build(self, config: dict) -> LGBMClassifier:
        params = {k: config.get(k, DEFAULTS[k]) for k in _CTOR_KEYS}
        return LGBMClassifier(**params, is_unbalance=True, verbose=-1,
                              random_state=config.get("seed", 42))

    def fit(self, X_train: np.ndarray, y_train: np.ndarray,
            X_val: np.ndarray, y_val: np.ndarray, config: dict) -> None:
        stop = int(config.get("early_stopping_rounds",
                              DEFAULTS["early_stopping_rounds"]))
        self.model = self._build(config)
        self.model.fit(
            X_train, y_train,
            eval_X=X_val, eval_y=y_val,
            callbacks=[lightgbm.early_stopping(stop, verbose=False)],
        )

        # Feature selection: drop zero-importance, retrain
        importances = self.model.feature_importances_
        keep_mask = importances > 0
        if keep_mask.sum() < len(importances):
            kept_idx = np.where(keep_mask)[0]
            dropped = len(importances) - len(kept_idx)
            print(f"  Feature selection: dropped {dropped} zero-importance features")

            # Rebuilt from the same config, not a second literal copy of it.
            # The two constructions used to be written out separately, so a
            # parameter changed in one and not the other would have produced a
            # served model whose settings matched neither the config nor the
            # first fit.
            model_sel = self._build(config)
            model_sel.fit(
                X_train[:, kept_idx], y_train,
                eval_X=X_val[:, kept_idx], eval_y=y_val,
                callbacks=[lightgbm.early_stopping(stop, verbose=False)],
            )
            self.model = model_sel
            if self.feature_names:
                self.selected_cols = [self.feature_names[i] for i in kept_idx]

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self.selected_cols and self.feature_names:
            idx = [self.feature_names.index(c) for c in self.selected_cols]
            X = X[:, idx]
        return self.model.predict_proba(X)[:, 1]

    def feature_importances(self) -> dict[str, float] | None:
        if self.model is None:
            return None
        names = self.selected_cols or self.feature_names
        if not names:
            return None
        return dict(zip(names, self.model.feature_importances_.astype(float)))

    def save(self, path: Path) -> None:
        with open(path, "wb") as f:
            pickle.dump({
                "model": self.model,
                "feature_names": self.feature_names,
                "selected_cols": self.selected_cols,
            }, f)

    @classmethod
    def load(cls, path: Path) -> LightGBMModel:
        with open(path, "rb") as f:
            data = pickle.load(f)
        obj = cls()
        obj.model = data["model"]
        obj.feature_names = data.get("feature_names", [])
        obj.selected_cols = data.get("selected_cols")
        return obj
