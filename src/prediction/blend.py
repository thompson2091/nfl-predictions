"""Anchor model probabilities to the market without surrendering to it.

Three stages, none of which use a hand-set probability:

1. **De-vig** the sportsbook prices. A book's "anytime TD — Yes" price includes
   its margin; taking it at face value overstates every player. Where the book
   posts both sides we remove the vig exactly (p_yes / (p_yes + p_no)). Where it
   only posts "Yes", we scale the game's prices down to the expected scorer
   count from the fitted prior.

2. **Level-calibrate** the model. Solve one shift in log-odds space per game so
   the model's probabilities sum to that game's expected number of scorers. This
   is rank-preserving — it never reorders a game's players, it only fixes how
   confident the model is overall. This is what stops a degraded feature week
   from producing a slate of 70% plays.

3. **Blend** model and market in log-odds space. The weight is *learned* from
   resolved odds history when enough has accumulated; until then it falls back
   to a declared bootstrap prior in config, and every output row records which
   of the two was used.

Edges therefore come from disagreeing with the book about *which* players score,
not from disagreeing about how many touchdowns a football game contains.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

EPS = 1e-6


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


# --------------------------------------------------------------------------
# 1. De-vig
# --------------------------------------------------------------------------

def devig_market(odds: pl.DataFrame, expected: pl.DataFrame) -> pl.DataFrame:
    """Return fair (vig-free) market probabilities per player.

    `odds` needs game_id, player_name_norm, implied_prob and optionally fair_prob
    (already two-sided de-vigged upstream). `expected` supplies the per-game
    scorer count used to normalise one-sided books.
    """
    if odds.height == 0:
        return odds

    df = odds.join(expected, on="game_id", how="left")

    if "fair_prob" not in df.columns:
        df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias("fair_prob"))

    # Per game: how much the one-sided prices overshoot the expected count.
    df = df.with_columns(
        pl.col("implied_prob").sum().over("game_id").alias("_implied_sum")
    )
    df = df.with_columns(
        pl.when(pl.col("fair_prob").is_not_null())
        .then(pl.col("fair_prob"))
        .otherwise(
            pl.col("implied_prob")
            * (pl.col("expected_scorers") / pl.col("_implied_sum")).clip(0.0, 1.0)
        )
        .alias("market_prob")
    )
    return df.drop("_implied_sum")


# --------------------------------------------------------------------------
# 2. Level calibration
# --------------------------------------------------------------------------

def _solve_shift(p: np.ndarray, target: float) -> float:
    """Find delta with sum(sigmoid(logit(p) + delta)) == target.

    The sum is strictly increasing in delta, so bisection converges. Returns 0.0
    when the target is unreachable (degenerate game).
    """
    if len(p) == 0 or target <= 0:
        return 0.0
    z = _logit(p)
    lo, hi = -20.0, 20.0
    if _sigmoid(z + lo).sum() > target or _sigmoid(z + hi).sum() < target:
        return 0.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if _sigmoid(z + mid).sum() < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def calibrate_level(df: pl.DataFrame, prob_col: str, expected: pl.DataFrame,
                    out_col: str = "prob_calibrated") -> pl.DataFrame:
    """Shift each game's log-odds so its probabilities sum to the expected count."""
    exp_map = dict(zip(expected["game_id"].to_list(),
                       expected["expected_scorers"].to_list()))
    out, shifts = [], []
    for (game_id,), g in df.group_by(["game_id"], maintain_order=True):
        p = g[prob_col].to_numpy()
        delta = _solve_shift(p, exp_map.get(game_id, float("nan")))
        if not np.isfinite(delta):
            delta = 0.0
        out.append(g.with_columns([
            pl.Series(out_col, _sigmoid(_logit(p) + delta)),
            pl.lit(delta).alias("level_shift"),
        ]))
        shifts.append(delta)
    return pl.concat(out) if out else df


# --------------------------------------------------------------------------
# 3. Blend
# --------------------------------------------------------------------------

def fit_blend_weight(history: pl.DataFrame, min_rows: int = 500) -> dict | None:
    """Learn how much to trust the model vs the market, from resolved history.

    Fits logit(p_true) ~ a*logit(p_model) + b*logit(p_market) via unregularised
    logistic regression and reports the normalised market share b/(a+b).
    Returns None until enough resolved player-games exist to fit responsibly.
    """
    need = {"model_prob", "market_prob", "scored"}
    if history is None or history.height < min_rows or not need <= set(history.columns):
        return None

    df = history.drop_nulls(list(need))
    if df.height < min_rows:
        return None

    from sklearn.linear_model import LogisticRegression

    X = np.column_stack([
        _logit(df["model_prob"].to_numpy()),
        _logit(df["market_prob"].to_numpy()),
    ])
    y = df["scored"].to_numpy().astype(int)
    if len(np.unique(y)) < 2:
        return None

    lr = LogisticRegression(penalty=None, max_iter=1000).fit(X, y)
    a, b = float(lr.coef_[0][0]), float(lr.coef_[0][1])
    total = abs(a) + abs(b)
    return {
        "kind": "blend_weight",
        "source": "fitted",
        "model_coef": a,
        "market_coef": b,
        "intercept": float(lr.intercept_[0]),
        "market_weight": abs(b) / total if total > 0 else 0.5,
        "n_rows": int(df.height),
        "seasons": sorted(set(df["season"].to_list())) if "season" in df.columns else [],
        "fit_date": date.today().isoformat(),
    }


def blend(df: pl.DataFrame, model_col: str, market_col: str,
          weight: dict, out_col: str = "prob_blended") -> pl.DataFrame:
    """Combine model and market in log-odds space.

    Rows with no market price keep the model probability untouched and are
    flagged, so a missing book never silently reverts to a naked model number.
    """
    w_market = float(weight["market_weight"])
    model_p = df[model_col].to_numpy()
    market_p = df[market_col].to_numpy() if market_col in df.columns else np.full(len(model_p), np.nan)

    has_market = np.isfinite(market_p) & (market_p > 0)
    blended = model_p.copy()
    blended[has_market] = _sigmoid(
        (1 - w_market) * _logit(model_p[has_market])
        + w_market * _logit(market_p[has_market])
    )
    return df.with_columns([
        pl.Series(out_col, blended),
        pl.Series("has_market_price", has_market),
        pl.lit(w_market).alias("market_weight"),
        pl.lit(weight.get("source", "unknown")).alias("blend_source"),
    ])


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------

def save_blend_weight(weight: dict, path: Path) -> None:
    Path(path).write_text(json.dumps(weight, indent=2))


def load_blend_weight(path: Path, bootstrap: float | None = None) -> dict:
    """Load a fitted weight, else fall back to the declared bootstrap prior."""
    p = Path(path)
    if p.exists():
        return json.loads(p.read_text())
    if bootstrap is None:
        raise ValueError(
            "No fitted blend weight and no bootstrap prior configured. Set "
            "blend.bootstrap_market_weight in config/settings.yaml."
        )
    return {
        "kind": "blend_weight",
        "source": "bootstrap",
        "market_weight": float(bootstrap),
        "note": (
            "No resolved odds history yet. This value is a declared starting "
            "point from config, replaced automatically by fit_blend_weight() "
            "once enough graded player-games accumulate in odds_history.parquet."
        ),
    }
