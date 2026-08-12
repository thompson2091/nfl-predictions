import numpy as np
import polars as pl
from sklearn.metrics import log_loss, roc_auc_score, brier_score_loss


def top_k_accuracy(df: pl.DataFrame, k: int) -> float:
    """Per game, check if any actual scorer is in the top-K predicted players.

    Delegates to `src.evaluation.ranking`, which is the one definition of this
    metric. There used to be three, and they disagreed about which games count —
    the question that decides whether a filtered-out scorer is a miss or is
    simply not measured. Two of them are gone; this is the third, kept as a
    name because the trainer and the app both call it.

    The old body scored one game per Python-level loop iteration, filtering the
    whole frame each time. On a walk-forward that is four models by four folds
    by ~1,100 games of quadratic-ish filtering, for a number a single grouped
    rank computes at once.

    Behaviour is unchanged: with no wider frame to hand, the games that count
    are those with a scorer in `df` — exactly what the loop did.
    """
    from src.evaluation.ranking import top_k_accuracy as _top_k

    return _top_k(df, k)


def evaluate_model(df: pl.DataFrame, label: str) -> dict:
    """Compute all metrics for a model's predictions."""
    y_true = df["target"].to_numpy()
    y_prob = df["prob"].to_numpy()

    metrics = {
        "model": label,
        "log_loss": float(log_loss(y_true, y_prob)),
        "roc_auc": float(roc_auc_score(y_true, y_prob)),
        "brier_score": float(brier_score_loss(y_true, y_prob)),
        "top_1_accuracy": top_k_accuracy(df, 1),
        "top_3_accuracy": top_k_accuracy(df, 3),
        "top_5_accuracy": top_k_accuracy(df, 5),
    }

    return metrics


def print_metrics(metrics: dict):
    print(f"\n  === {metrics['model']} ===")
    print(f"  Log Loss:       {metrics['log_loss']:.4f}")
    print(f"  ROC AUC:        {metrics['roc_auc']:.4f}")
    print(f"  Brier Score:    {metrics['brier_score']:.4f}")
    print(f"  Top-1 Accuracy: {metrics['top_1_accuracy']:.1%}")
    print(f"  Top-3 Accuracy: {metrics['top_3_accuracy']:.1%}")
    print(f"  Top-5 Accuracy: {metrics['top_5_accuracy']:.1%}")
