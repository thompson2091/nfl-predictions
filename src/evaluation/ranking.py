"""One definition of "did the ranking get this game right".

Top-K is the metric this project lives on and it had three implementations:
`metrics.top_k_accuracy` (a Python loop over games), `_fold_metrics` inside
`scripts/11_walkforward.py`, and `_top1` inside `scripts/19_tune.py`. They
disagreed about the only thing that is hard here — **which games count**.

That question is not cosmetic. `_fold_metrics` built its game list from the
rows that survived `_filter_low_activity`, so a game whose only scorer was
filtered out vanished from the denominator instead of counting as a miss. Two
consequences:

  * The figure was flattered. Corrected, first TD is measured over 1,131 games
    rather than 1,115 — 16 games that were silently dropped, worth about
    0.2 points of Top-1. Anytime TD loses one game.
  * Worse, and the reason this blocks everything else: any experiment that
    widens or narrows the candidate pool changed its own denominator. Loosening
    the filter adds hard games and *lowers* measured Top-1 while strictly
    improving the product. Pool experiments were not comparable at all.

So the denominator is fixed here, once: **every played game whose scorer exists
in the candidate pool at all**. A scorer the filter removed is a miss, because
that is exactly what it is — the board could not have shown them. The eight
games per season-range with no scorer anywhere in the pool are excluded and
counted separately, since the label is not in the data and no ranking can win
them.

Everything returns per-game rows rather than a percentage. Pooled figures are
derived from those, and so are the paired comparisons in
`src/evaluation/compare.py` — two variants score the same games, and testing
only the games where they disagree is far more powerful than subtracting two
percentages that each carry +/-1.5%.
"""
from __future__ import annotations

import numpy as np
import polars as pl

#: Reported alongside Top-1. Three because the headline strategy backs the top
#: three; five because that is where the board's first screen ends.
TOP_K = (1, 3, 5)


def game_universe(labelled: pl.DataFrame, game_col: str = "game_id",
                  target_col: str = "target") -> pl.DataFrame:
    """Games a ranking could win: played, and with a scorer in the pool.

    Pass the **unfiltered** candidate frame for the seasons being scored — the
    universe must not depend on the filter under test, which is the whole point.
    """
    return (
        labelled.filter(pl.col(target_col) == 1)
        .select(game_col).unique().sort(game_col)
    )


def per_game_outcomes(scored: pl.DataFrame, universe: pl.DataFrame,
                      prob_col: str = "prob", game_col: str = "game_id",
                      target_col: str = "target") -> pl.DataFrame:
    """One row per game in `universe`: where the best actual scorer ranked.

    `scored` holds the rows the model actually ranked, which may be a subset of
    the pool. A game in `universe` with no scorer in `scored` gets a null rank
    and counts as a miss at every K.

    Also returns the top two probabilities and their gap. A game where the top
    two sit within a point is a coin flip, and the share of those is the
    practical ceiling on Top-1 — worth carrying so a diagnosis can read it
    straight off the same artifact the metrics come from.
    """
    ranked = scored.with_columns(
        pl.col(prob_col).rank(descending=True, method="ordinal")
        .over(game_col).alias("_rank")
    )
    best = (
        ranked.filter(pl.col(target_col) == 1)
        .group_by(game_col).agg(pl.col("_rank").min().alias("best_rank"))
    )
    tops = (
        ranked.filter(pl.col("_rank") <= 2)
        .group_by(game_col)
        .agg([
            pl.col(prob_col).filter(pl.col("_rank") == 1).first().alias("p_top1"),
            pl.col(prob_col).filter(pl.col("_rank") == 2).first().alias("p_top2"),
            pl.len().alias("n_candidates"),
        ])
    )
    pool = ranked.group_by(game_col).agg(pl.len().alias("pool_size"))

    out = (
        universe.join(best, on=game_col, how="left")
        .join(tops.drop("n_candidates"), on=game_col, how="left")
        .join(pool, on=game_col, how="left")
        .with_columns([
            (pl.col("p_top1") - pl.col("p_top2")).alias("top_gap"),
            pl.col("pool_size").fill_null(0),
        ])
    )
    for k in TOP_K:
        out = out.with_columns(
            (pl.col("best_rank").is_not_null() & (pl.col("best_rank") <= k))
            .alias(f"hit{k}")
        )
    return out.sort(game_col)


def pooled(outcomes: pl.DataFrame) -> dict:
    """Top-K over the fixed denominator, with binomial standard errors.

    The standard errors are *unpaired* and wide — +/-1.5% on 1,130 anytime-TD
    games. They describe one model; they are not how two models get compared.
    See `src/evaluation/compare.py`.
    """
    n = outcomes.height
    out: dict = {"games": n}
    for k in TOP_K:
        p = float(outcomes[f"hit{k}"].mean()) if n else 0.0
        out[f"top{k}"] = p
        out[f"top{k}_se"] = float(np.sqrt(p * (1 - p) / n)) if n else 0.0
    ranked = outcomes.filter(pl.col("best_rank").is_not_null())
    out["median_rank"] = (float(ranked["best_rank"].median())
                          if ranked.height else float("nan"))
    out["unranked_games"] = int(n - ranked.height)
    gaps = outcomes["top_gap"].drop_nulls()
    # Games where the top two are within a point: coin flips by any reading, and
    # the practical ceiling on how much Top-1 is available to win.
    out["coin_flip_share"] = float((gaps < 0.01).mean()) if gaps.len() else 0.0
    return out


def row_metrics(scored: pl.DataFrame, prob_col: str = "prob",
                target_col: str = "target") -> dict:
    """AUC and Brier over the scored rows.

    Row-level rather than per-game, and unaffected by the denominator question:
    a filtered-out player contributes no row to either path.
    """
    from sklearn.metrics import brier_score_loss, roc_auc_score

    y = scored[target_col].to_numpy().astype(float)
    p = scored[prob_col].to_numpy()
    return {
        "rows": int(len(y)),
        "auc": float(roc_auc_score(y, p)) if len(set(y.tolist())) > 1 else float("nan"),
        "brier": float(brier_score_loss(y, p)),
        "sum_per_game": float(p.sum() / max(scored["game_id"].n_unique(), 1)),
        "actual_per_game": float(y.sum() / max(scored["game_id"].n_unique(), 1)),
    }


def top_k_accuracy(scored: pl.DataFrame, k: int, universe: pl.DataFrame | None = None,
                   prob_col: str = "prob") -> float:
    """Top-K over `universe`, defaulting to the games present in `scored`.

    The default reproduces the old behaviour for callers that have no wider
    frame to hand — in-training validation reporting, where the filtered set is
    all there is. Anything comparing two models must pass an explicit
    `universe`, or the two are free to be measured over different games.
    """
    if universe is None:
        universe = game_universe(scored)
    outcomes = per_game_outcomes(scored, universe, prob_col=prob_col)
    return float(outcomes[f"hit{k}"].mean()) if outcomes.height else 0.0
