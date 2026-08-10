"""LightGBM model wrapper."""
from __future__ import annotations
import pickle
from pathlib import Path

import numpy as np
import lightgbm
from lightgbm import LGBMClassifier

from src.models.registry import register


@register("lgbm")
class LightGBMModel:
    name = "lgbm"

    def __init__(self):
        self.model: LGBMClassifier | None = None
        self.feature_names: list[str] = []
        self.selected_cols: list[str] | None = None

    def fit(self, X_train: np.ndarray, y_train: np.ndarray,
            X_val: np.ndarray, y_val: np.ndarray, config: dict) -> None:
        self.model = LGBMClassifier(
            n_estimators=2000,
            learning_rate=0.02,
            max_depth=config.get("max_depth", 6),
            num_leaves=config.get("num_leaves", 31),
            min_child_samples=20,
            subsample=config.get("subsample", 0.7),
            colsample_bytree=config.get("colsample_bytree", 0.6),
            reg_alpha=0.1,
            reg_lambda=1.0,
            is_unbalance=True,
            random_state=config.get("seed", 42),
            verbose=-1,
        )
        self.model.fit(
            X_train, y_train,
            eval_X=X_val, eval_y=y_val,
            callbacks=[lightgbm.early_stopping(50, verbose=False)],
        )

        # Feature selection: drop zero-importance, retrain
        importances = self.model.feature_importances_
        keep_mask = importances > 0
        if keep_mask.sum() < len(importances):
            kept_idx = np.where(keep_mask)[0]
            dropped = len(importances) - len(kept_idx)
            print(f"  Feature selection: dropped {dropped} zero-importance features")

            model_sel = LGBMClassifier(
                n_estimators=2000, learning_rate=0.02,
                max_depth=config.get("max_depth", 6),
                num_leaves=config.get("num_leaves", 31),
                min_child_samples=20,
                subsample=config.get("subsample", 0.7),
                colsample_bytree=config.get("colsample_bytree", 0.6),
                reg_alpha=0.1, reg_lambda=1.0,
                is_unbalance=True,
                random_state=config.get("seed", 42), verbose=-1,
            )
            model_sel.fit(
                X_train[:, kept_idx], y_train,
                eval_X=X_val[:, kept_idx], eval_y=y_val,
                callbacks=[lightgbm.early_stopping(50, verbose=False)],
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
