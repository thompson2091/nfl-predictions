import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.calibration import calibration_curve
from src.utils.paths import get_path


def plot_calibration(y_true, y_prob, model_name: str):
    fig, ax = plt.subplots(figsize=(8, 6))
    prob_true, prob_pred = calibration_curve(y_true, y_prob, n_bins=10, strategy="quantile")
    ax.plot(prob_pred, prob_true, marker="o", label=model_name)
    ax.plot([0, 1], [0, 1], "--", color="gray", label="Perfect calibration")
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Fraction of positives")
    ax.set_title(f"Calibration Curve - {model_name}")
    ax.legend()
    fig.savefig(get_path("plots") / f"calibration_{model_name}.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_feature_importance(importances: dict, model_name: str, top_n: int = 20):
    sorted_feats = sorted(importances.items(), key=lambda x: abs(x[1]), reverse=True)[:top_n]
    names, vals = zip(*sorted_feats)

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.barh(range(len(names)), vals, align="center")
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names)
    ax.invert_yaxis()
    ax.set_title(f"Top {top_n} Feature Importances - {model_name}")
    ax.set_xlabel("Importance")
    fig.savefig(get_path("plots") / f"importance_{model_name}.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
