"""Correct the model's positional bias. DISABLED, AND THE BIAS IS NOT REAL.

Kept and documented rather than deleted, because the idea is reasonable and
keeps recurring. It was tried twice and failed twice, for two different reasons.

FIRST FAILURE — it broke the ranking. Additive per-rank deltas were not monotone
in rank, so a lower-rated player could overtake a higher-rated one. Stacked on
the joint model's output it collapsed the top ranks into ties and took 2025 AUC
from 0.862 to 0.497. That is why it is skipped whenever the joint model is
active.

SECOND FAILURE — the bias does not generalise. A monotone-by-construction
version was built specifically to fix the first failure (non-increasing deltas
cannot reorder a game), fitted on 2023-24 and tested on 2025. It moved nothing:
Brier 0.11291 -> 0.11300, AUC 0.8141 -> 0.8144, Top-1 unchanged, and rank-1
calibration got *worse* (-8.8pp -> -12.2pp).

The reason is visible once the pooled figure is split by season:

    calibration gap    2023     2024     2025    pooled
    rank 1           +12.0pp   +3.2pp   -8.8pp   +2.1pp
    rank 2            +6.5pp   -2.2pp   -3.2pp   +0.4pp
    rank 6           +10.2pp   +5.4pp   -0.1pp   +5.2pp

Roughly 283 observations per rank per season. The gaps disagree in sign, so the
pooled "systematic bias" is an average of seasons that contradict each other.
Fitting it forward is fitting last year's noise.

The headline in the paragraph below — "#2 runs 6 points hot, #4 down runs cold" —
is one season's shape read as a law. Across all 20,957 priced players the model
sits +0.5pp off, which is close to calibrated, and the team-rate lambda is
accurate across the whole spread. There is no positional bias left worth
correcting.


Measured on held-out data, this model's error depends on *where a player sits in
its own ranking*, not just on the probability it assigned. For anytime-TD the #1
pick is accurate, the #2 runs about 6 points hot, and everything from #4 down
runs several points cold. That is a systematic bias the model cannot see, because
nothing in its features encodes "you are this game's fourth-favorite".

The per-game level calibration already in the pipeline can't fix it: that applies
one shift to a whole game, so it moves every rank together. This applies a shift
per rank instead.

Two properties make it safe:

- **Fit on the validation season only.** Fitting on test would tune the model to
  the data used to judge it, and the improvement would be an illusion.
- **Ranking is preserved.** Corrected probabilities are clipped so a lower-ranked
  player can never overtake a higher-ranked one. The correction adjusts how
  confident we are at each slot; it never claims the #4 is better than the #3,
  because the empirical rates that drive it are noisy enough to invert
  neighbouring ranks by chance.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path


def would_be_applied(target_type: str, model_dir) -> bool:
    """Will any serving path actually consume a correction fitted here?

    Both answers are currently False, and the reasons differ:

      * `first_td` never reaches the correction at all. `predict()` normalizes
        raw probabilities within the game and returns; only the anytime branch
        calls `_anchor_to_market`, which is where the correction lives.
        `scripts/10_backtest.py` branches the same way.
      * `anytime_td` reaches it and is then disabled by the joint-model guard —
        see FIRST FAILURE above — and `team_td_rate.json` is written on every
        training run, so the guard is always taken.

    This exists so `train_all` can stop fitting an artifact nothing reads, and
    say which of those two reasons applies. Fitting it anyway was not harmful,
    but it wrote a `rank_calibration.json` into both model directories and
    announced "N of 12 ranks kept a meaningful correction" on every retrain,
    which reads exactly like a component that is doing something.

    Kept as a live check rather than a hardcoded False so the capability still
    works for a model directory with no team rate — the legacy fallback the
    guard was written for.
    """
    if target_type == "first_td":
        return False
    from src.models.joint import load_team_rate
    return load_team_rate(Path(model_dir) / "team_td_rate.json") is None

import numpy as np
import polars as pl

EPS = 1e-6
#: Ranks with fewer games than this are pooled into the tail — a hit rate from a
#: handful of games is noise, and noise here would reorder real players.
MIN_GAMES_PER_RANK = 30
#: Beyond this depth the probabilities are small and the players interchangeable.
MAX_RANK = 12


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=float)))


def fit_rank_calibration(df: pl.DataFrame, prob_col: str = "prob",
                         season_col: str | None = None) -> dict:
    """Learn a per-rank logit shift from labeled data.

    Pass VALIDATION seasons; fitting on test produces a flattering, meaningless
    result.

    If `season_col` is given and spans several seasons, each rank's shift is
    shrunk toward zero by how consistent it is across them. This matters: fit on
    a single season, the top ranks appeared badly biased, but the sign of that
    bias *flipped* the following year — it was sampling noise, and correcting it
    made those ranks worse. Only ranks whose bias repeats survive the shrinkage.
    """
    if season_col and df[season_col].n_unique() > 1:
        return _fit_shrunk(df, prob_col, season_col)

    ranked = df.with_columns(
        pl.col(prob_col).rank(descending=True, method="ordinal")
        .over("game_id").alias("_rank")
    )
    agg = (
        ranked.group_by("_rank")
        .agg([
            pl.col("target").mean().alias("actual"),
            pl.col(prob_col).mean().alias("predicted"),
            pl.len().alias("n"),
        ])
        .filter((pl.col("_rank") <= MAX_RANK) & (pl.col("n") >= MIN_GAMES_PER_RANK))
        .sort("_rank")
    )
    if agg.height < 3:
        raise ValueError("not enough ranks with data to fit a rank calibration")

    ranks = agg["_rank"].to_numpy().astype(int)
    actual = agg["actual"].to_numpy()
    predicted = agg["predicted"].to_numpy()

    # Empirical rates wobble between neighbouring ranks (rank 4 outscoring rank 3
    # by a point is sampling noise, not signal). Force them monotone decreasing
    # so the correction can't encode that wobble.
    from sklearn.isotonic import IsotonicRegression
    smooth = IsotonicRegression(increasing=False, out_of_bounds="clip").fit_transform(
        ranks, actual
    )

    deltas = _logit(smooth) - _logit(predicted)
    return {
        "kind": "rank_calibration",
        "deltas": {int(r): float(d) for r, d in zip(ranks, deltas)},
        "diagnostics": [
            {"rank": int(r), "n": int(n), "predicted": float(p),
             "actual": float(a), "smoothed": float(s), "delta": float(d)}
            for r, n, p, a, s, d in zip(
                ranks, agg["n"].to_numpy(), predicted, actual, smooth, deltas)
        ],
        "max_rank": MAX_RANK,
        "fit_date": date.today().isoformat(),
    }


def _fit_shrunk(df: pl.DataFrame, prob_col: str, season_col: str) -> dict:
    """Per-rank shifts, shrunk toward zero by cross-season consistency.

    A rank whose bias points the same way every season keeps most of its
    correction. A rank that flips sign gets shrunk to nearly nothing, because a
    correction fitted to noise is worse than no correction at all.
    """
    seasons = sorted(df[season_col].unique().to_list())
    per_season: dict[int, list[float]] = {}

    for s in seasons:
        sub = df.filter(pl.col(season_col) == s)
        ranked = sub.with_columns(
            pl.col(prob_col).rank(descending=True, method="ordinal")
            .over("game_id").alias("_rank")
        )
        agg = (
            ranked.group_by("_rank")
            .agg([
                pl.col("target").mean().alias("actual"),
                pl.col(prob_col).mean().alias("predicted"),
                pl.len().alias("n"),
            ])
            .filter((pl.col("_rank") <= MAX_RANK) & (pl.col("n") >= MIN_GAMES_PER_RANK))
        )
        for r, a, p in zip(agg["_rank"], agg["actual"], agg["predicted"]):
            per_season.setdefault(int(r), []).append(
                float(_logit(a) - _logit(p))
            )

    deltas, diags = {}, []
    for rank in sorted(per_season):
        vals = np.array(per_season[rank])
        if len(vals) < 2:
            continue
        mean = vals.mean()
        se = vals.std(ddof=1) / np.sqrt(len(vals))
        # Shrink by signal-to-noise: mean^2 / (mean^2 + se^2). A shift much
        # larger than its own standard error is kept; one comparable to it is
        # damped toward zero.
        weight = float(mean ** 2 / (mean ** 2 + se ** 2)) if se > 0 else 1.0
        shrunk = float(mean * weight)
        deltas[rank] = shrunk
        diags.append({
            "rank": rank, "seasons": len(vals), "raw_delta": float(mean),
            "std_error": float(se), "kept": round(weight, 3),
            "delta": shrunk,
            "consistent_sign": bool(np.all(vals > 0) or np.all(vals < 0)),
        })

    if not deltas:
        raise ValueError("no ranks had enough data across seasons")
    return {
        "kind": "rank_calibration",
        "method": "cross-season shrinkage",
        "seasons_used": [int(s) for s in seasons],
        "deltas": deltas,
        "diagnostics": diags,
        "max_rank": MAX_RANK,
        "fit_date": date.today().isoformat(),
    }


def apply_rank_calibration(df: pl.DataFrame, calib: dict, prob_col: str,
                           out_col: str = "prob_rank_calibrated") -> pl.DataFrame:
    """Apply per-rank shifts, never letting a player overtake the one above."""
    if not calib or not calib.get("deltas"):
        return df.with_columns(pl.col(prob_col).alias(out_col))

    deltas = {int(k): float(v) for k, v in calib["deltas"].items()}
    fallback = deltas[max(deltas)]          # deepest fitted rank covers the tail

    out = []
    for _, g in df.group_by(["game_id"], maintain_order=True):
        g = g.sort(prob_col, descending=True)
        p = g[prob_col].to_numpy()
        shifts = np.array([deltas.get(i + 1, fallback) for i in range(len(p))])
        corrected = _sigmoid(_logit(p) + shifts)
        # Order-preserving: each value capped by the one above it.
        corrected = np.minimum.accumulate(corrected)
        out.append(g.with_columns(pl.Series(out_col, corrected)))
    return pl.concat(out) if out else df.with_columns(pl.col(prob_col).alias(out_col))


def save(calib: dict, path: Path) -> None:
    Path(path).write_text(json.dumps(calib, indent=2))


def load(path: Path) -> dict | None:
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else None
