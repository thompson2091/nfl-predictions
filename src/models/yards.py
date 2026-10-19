"""Yardage, where the shape of the distribution is itself a prediction.

The fourth target type, and the first where the receptions answer does not
transfer. `src/models/count.py` predicts a mean and hands it to a negative
binomial whose single dispersion parameter is fitted once for the whole
population. That works for receptions because a count's spread really is
governed by its level. Yardage is not like that, and this is measured rather
than argued. Banding 2015-2023 player-games by volume:

    receiving yards      mean     sd   sd/mean   skew   P(y<=0)
      1 target           6.54   9.09     1.39    2.54    37.6%
      7+ targets        70.51  36.42     0.52    1.01     0.1%

    rushing yards
      1 carry            4.39   7.26     1.65    2.68    26.4%
      13+ carries       78.10  34.43     0.44    1.02     0.0%

    passing yards
      14-26 attempts   165.49  60.02     0.36    0.31     0.0%
      41+ attempts     311.13  65.16     0.21    0.36     0.0%

Read the columns rather than the rows. The *shape* moves, not just the scale:
skew falls by a factor of 2.5 across the receiving board, and the zero mass
goes from better than a third of rows to one in a thousand. And passing yards
moves the other way entirely — its standard deviation is nearly CONSTANT near
60 while its mean almost doubles, so spread there is not proportional to level
at all.

Three families are ruled out by that table, each for a different reason:

  * **One fitted dispersion** (the receptions model) asserts a fixed
    relationship between level and spread. Two different ones appear above.
  * **Location-scale with sigma proportional to mu** is the same assertion in
    a different coat, and passing yards contradicts it directly.
  * **A pooled standardised-residual ECDF** assumes the residual has one shape
    once the level is divided out. Its skew ranges over 2.5x.

Gamma, Tweedie and the negative binomial are ruled out before any of that, on
support alone: 7.5% of rushing player-games and 1.3% of receiving ones are
NEGATIVE, and every one of those families lives on [0, inf).

So the model predicts the **quantile function** directly, and the line is
applied to it afterwards:

    expected quantiles   q_i(a)     gradient-boosted, pinball loss at each a
    the CDF              F_i        linear interpolation between them
    any line             P(Y > L)   1 - F_i(L)

Quantile regression is the only one of the candidates that lets the shape be a
function of the features. It is not a cleverer distribution; it is the absence
of one. A 1-target tight end and a 12-target WR1 get different skews because
their fitted quantiles are spaced differently, not because anything was told
they should be.

**Floor and ceiling stop being a derived extra.** The receptions board reads
them off the fitted negative binomial in `count.count_interval`. Here they are
two of the columns the model was fitted on, which is the same reason this
family was chosen.

**Crossing is repaired by sorting, and that is a theorem rather than a
shrug.** Nothing constrains the fitted 60th percentile to exceed the fitted
55th, and on thin rows it sometimes does not. Sorting each row's quantiles
(Chernozhukov, Fernandez-Val and Galichon's rearrangement) is guaranteed not
to increase the estimation error in any L^p norm: the sorted curve is at least
as close to the true monotone quantile function as the unsorted one. So it is
free to apply and there is no case for leaving a crossed row alone.

**The training pool is gated pre-game or not at all.** Filtering to rows where
the player actually threw, carried or was targeted would select on the
outcome, which is the same shape of mistake as the NGS existence leak: the
model would be fitted on a population it cannot identify before kickoff. So
the label is zero where a player played and did none of it, and the only gate
is `position_QB`, which comes off a roster rather than a box score.
"""
from __future__ import annotations

import pickle
from datetime import date
from pathlib import Path

import numpy as np
from xgboost import XGBRegressor

from src.models.registry import register

#: The levels the quantile function is fitted at.
#:
#: Dense through the middle and sparse in the tails, because that is where the
#: lines are. A book sets a yardage line close to a coin flip by construction —
#: that is what makes it sellable — so the interpolation that prices it almost
#: always lands between two of the 5-point steps from 0.10 to 0.90. The 0.02
#: and 0.98 ends exist to bound the extrapolation rather than to be read.
#:
#: Twenty-one levels rather than five: the gap between adjacent quantiles is
#: the resolution of the whole CDF, and on a 250-yard passing line a 0.10 step
#: is about 25 yards of line movement priced as one straight segment.
QUANTILE_LEVELS: tuple[float, ...] = (
    0.02, 0.05,
    0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50,
    0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90,
    0.95, 0.98,
)

#: Held identical to `model.xgb` and `count.DEFAULTS` on purpose, so any
#: difference in what this learns is attributable to the objective rather than
#: to tuning. See count.DEFAULTS for the same discipline.
DEFAULTS = {
    "n_estimators": 2000,
    "learning_rate": 0.02,
    "max_depth": 6,
    "min_child_weight": 20,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "early_stopping_rounds": 50,
}


def rearrange(q: np.ndarray) -> np.ndarray:
    """Repair quantile crossing by sorting each row.

    See the module docstring: sorting is the rearrangement estimator, and it
    cannot increase the L^p error against the true monotone quantile curve. A
    row that did not cross is returned unchanged, so this is safe to apply
    unconditionally rather than only to rows that look wrong.
    """
    return np.sort(np.asarray(q, dtype=float), axis=1)


def cdf(q: np.ndarray, x: np.ndarray,
        levels: tuple[float, ...] = QUANTILE_LEVELS) -> np.ndarray:
    """F(x) for each row, read off that row's fitted quantile curve.

    Linear between adjacent fitted quantiles, exponential outside the outermost
    ones. The tails need *some* rule and a flat one is the wrong rule: clamping
    F to 0.02 below the lowest fitted quantile would price every line down
    there identically, and books do post a rushing line at 0.5 yards for a
    quarterback. An exponential tail is continuous at the join, respects the
    bound, and its scale is taken from the outermost fitted gap rather than
    invented — so a row whose distribution is wide gets a wide tail.

    `q` is (n, k) and already sorted; `x` is (n,).
    """
    q = np.asarray(q, dtype=float)
    x = np.asarray(x, dtype=float)
    a = np.asarray(levels, dtype=float)
    n, k = q.shape
    if x.shape != (n,):
        raise ValueError(f"line vector is {x.shape}, expected {(n,)}")
    if k != len(a):
        raise ValueError(f"{k} fitted quantiles against {len(a)} levels")

    rows = np.arange(n)
    # Index of the last fitted quantile at or below x, in [-1, k-1].
    j = np.sum(q <= x[:, None], axis=1) - 1

    out = np.empty(n, dtype=float)

    # Interior: between two fitted quantiles.
    mid = (j >= 0) & (j <= k - 2)
    if mid.any():
        jm = j[mid]
        lo_q, hi_q = q[rows[mid], jm], q[rows[mid], jm + 1]
        span = hi_q - lo_q
        # A flat step carries no width to interpolate across; take its top.
        frac = np.where(span > 1e-12, (x[mid] - lo_q) / np.where(span > 1e-12, span, 1.0), 1.0)
        out[mid] = a[jm] + (a[jm + 1] - a[jm]) * np.clip(frac, 0.0, 1.0)

    # Below the lowest fitted quantile.
    lo = j < 0
    if lo.any():
        scale = np.maximum(q[lo, 1] - q[lo, 0], 1e-6)
        out[lo] = a[0] * np.exp((x[lo] - q[lo, 0]) / scale)

    # At or above the highest.
    hi = j >= k - 1
    if hi.any():
        scale = np.maximum(q[hi, k - 1] - q[hi, k - 2], 1e-6)
        out[hi] = 1.0 - (1.0 - a[-1]) * np.exp(-(x[hi] - q[hi, k - 1]) / scale)

    return np.clip(out, 0.0, 1.0)


def prob_over(q: np.ndarray, line: np.ndarray,
              levels: tuple[float, ...] = QUANTILE_LEVELS
              ) -> tuple[np.ndarray, np.ndarray]:
    """P(Y > line) and the push mass, for any line.

    Mirrors `count.prob_over` so the two markets can be served by one caller.

    Yardage lines are half-points essentially always — every one of the 264
    rows in the first archived sample was — so the push return is usually a
    vector of zeros. It is returned anyway because a whole-number line settles
    in three ways and treating a push as a loss would understate one side of
    every one of them, which is the same reason `count.prob_over` returns it.

    Yards are whole numbers, so a whole line L takes the continuity correction:
    over is the mass above L + 0.5 and the push is the mass across [L-0.5,
    L+0.5]. A half-point line has no such band and reads straight off the CDF.
    """
    q = rearrange(q)
    line = np.asarray(line, dtype=float)
    whole = line == np.floor(line)

    over = 1.0 - cdf(q, np.where(whole, line + 0.5, line), levels)
    push = np.where(whole,
                    cdf(q, line + 0.5, levels) - cdf(q, line - 0.5, levels),
                    0.0)
    return np.clip(over, 0.0, 1.0), np.clip(push, 0.0, 1.0)


def quantile_at(q: np.ndarray, level: float,
                levels: tuple[float, ...] = QUANTILE_LEVELS) -> np.ndarray:
    """One percentile of each row's fitted distribution, interpolated.

    The median is the number a yardage board leads with, and it is `level=0.5`
    here rather than a separately fitted mean. A book sets its line where the
    two sides are even money, which IS the median — so the median is the
    directly comparable quantity, and on a distribution this skewed the mean
    is not the same number.
    """
    q = rearrange(q)
    a = np.asarray(levels, dtype=float)
    if level <= a[0]:
        return q[:, 0].copy()
    if level >= a[-1]:
        return q[:, -1].copy()
    j = int(np.searchsorted(a, level, side="right") - 1)
    if a[j + 1] - a[j] < 1e-12:
        return q[:, j].copy()
    w = (level - a[j]) / (a[j + 1] - a[j])
    return q[:, j] + w * (q[:, j + 1] - q[:, j])


def mean_of(q: np.ndarray,
            levels: tuple[float, ...] = QUANTILE_LEVELS) -> np.ndarray:
    """Each row's mean, integrated over its fitted quantile curve.

    The tails past the outer levels are held flat, so this slightly
    understates a long right tail. It exists for totals: medians of skewed
    yardage add to far less than the team's total (196 against 224 receiving
    yards a team-game on 2025), and means are what add.
    """
    q = rearrange(q)
    a = np.asarray(levels, dtype=float)
    x = np.concatenate([[0.0], a, [1.0]])
    y = np.concatenate([q[:, :1], q, q[:, -1:]], axis=1)
    return np.trapezoid(y, x, axis=1)


def interval(q: np.ndarray, lo: float = 0.15, hi: float = 0.85,
             levels: tuple[float, ...] = QUANTILE_LEVELS
             ) -> tuple[np.ndarray, np.ndarray]:
    """The range the yardage actually lands in — floor and ceiling.

    15th and 85th by default, matching `count.count_interval` so the two boards
    mean the same thing by the same words. Unlike that function this needs no
    interpolation trick across a discrete step, because both levels are fitted
    quantiles in their own right: floor and ceiling are outputs of this model
    rather than quantities derived from a mean.
    """
    return quantile_at(q, lo, levels), quantile_at(q, hi, levels)


@register("xgb_quantile")
class XGBQuantileModel:
    """The conditional quantile function of a yardage total, per player-game.

    Fitted by pinball loss at every level in `QUANTILE_LEVELS` at once. The
    objective is the whole point of the model rather than a detail of it — see
    the module docstring for the measurements that rule out predicting a mean
    and attaching a distribution to it afterwards.
    """

    name = "xgb_quantile"

    def __init__(self):
        self.model: XGBRegressor | None = None
        self.feature_names: list[str] = []
        self.levels: tuple[float, ...] = QUANTILE_LEVELS
        self.market: str | None = None

    def fit(self, X_train, y_train, X_val, y_val, config: dict) -> None:
        params = {k: config.get(k, v) for k, v in DEFAULTS.items()}
        self.levels = tuple(config.get("quantile_levels", QUANTILE_LEVELS))
        self.model = XGBRegressor(
            **params,
            objective="reg:quantileerror",
            quantile_alpha=np.asarray(self.levels, dtype=float),
            random_state=config.get("seed", 42),
            verbosity=0,
        )
        self.model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

    def predict_quantiles(self, X) -> np.ndarray:
        """(n, k) fitted quantiles per row, sorted.

        Sorted here rather than at the call sites, so no caller can forget. See
        `rearrange`.
        """
        p = np.asarray(self.model.predict(X), dtype=float)
        if p.ndim == 1:                      # a single fitted level
            p = p[:, None]
        return rearrange(p)

    def predict_median(self, X) -> np.ndarray:
        return quantile_at(self.predict_quantiles(X), 0.5, self.levels)

    def predict_over(self, X, line) -> tuple[np.ndarray, np.ndarray]:
        return prob_over(self.predict_quantiles(X), line, self.levels)

    def predict_proba(self, X) -> np.ndarray:
        """P(Y > 0.5), so this satisfies the binary ModelWrapper too.

        Not the point of the model — the same courtesy `XGBCountModel` extends,
        so calibration plots and the evaluation harness work without a special
        case.
        """
        over, _ = self.predict_over(X, np.full(len(X), 0.5))
        return over

    def feature_importances(self) -> dict[str, float] | None:
        if self.model is None or not self.feature_names:
            return None
        return dict(zip(self.feature_names,
                        self.model.feature_importances_.astype(float)))

    def save(self, path: Path) -> None:
        with open(path, "wb") as f:
            pickle.dump({"model": self.model, "feature_names": self.feature_names,
                         "levels": tuple(self.levels), "market": self.market,
                         "fit_date": date.today().isoformat()}, f)

    @classmethod
    def load(cls, path: Path) -> "XGBQuantileModel":
        with open(path, "rb") as f:
            data = pickle.load(f)
        obj = cls()
        obj.model = data["model"]
        obj.feature_names = data.get("feature_names", [])
        obj.levels = tuple(data.get("levels", QUANTILE_LEVELS))
        obj.market = data.get("market")
        return obj
