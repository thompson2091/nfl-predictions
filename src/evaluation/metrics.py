import numpy as np
import polars as pl
from sklearn.metrics import log_loss, roc_auc_score, brier_score_loss


def top_k_accuracy(df: pl.DataFrame, k: int) -> float:
    """Per game, check if any actual scorer is in top-K predicted players.

    For first_td (one scorer per game): equivalent to checking if THE scorer is in top K.
    For anytime_td (multiple scorers): checks if at least one scorer is in top K.
    """
    games_with_target = df.filter(pl.col("target") == 1).select("game_id").unique()

    correct = 0
    total = 0
    for game_id in games_with_target["game_id"].to_list():
        game_df = df.filter(pl.col("game_id") == game_id).sort("prob", descending=True)
        top_k_ids = set(game_df.head(k)["player_id"].to_list())
        actual_ids = set(game_df.filter(pl.col("target") == 1)["player_id"].to_list())
        if top_k_ids & actual_ids:
            correct += 1
        total += 1

    return correct / total if total > 0 else 0.0


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
