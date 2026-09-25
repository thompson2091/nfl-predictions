"""Counts, not coin flips: one model that prices every line.

Every model in this project so far answers a yes/no question, and
`ModelWrapper.predict_proba` returns one number per row because that is all a
yes/no question needs. Receptions is not that question. A book posts Over 2.5
for one player and Over 6.5 for another, and moves the line between the open
and the close, so "will he beat 3.5" is not a fixed target — it is a family of
targets over the same player-game.

Fitting a classifier per line is the obvious way to handle that and the wrong
one. It throws away the ordering (a model can put P(>2.5) below P(>3.5) and
never notice), it splits the training data by line so the rarest lines get the
least data, and it cannot price a line the book has not posted before.

So the model predicts the *count*, and the line is applied afterwards:

    expected receptions   mu_i          gradient-boosted, Poisson objective
    whose distribution    NB(mu_i, r)   dispersion r fitted once, held out
    any line              P(Y > L)      1 - CDF(floor(L))

**Negative binomial, not Poisson, and this is measured rather than assumed.**
Over 39,682 player-games with at least one target, seasons 2015-2023:

    mean 2.744   variance 5.270   variance/mean 1.920

Poisson asserts that ratio is 1. Fitting both families to the marginal counts:

    k         0       1       2       3       4       5       6       7
    actual  .1049   .2709   .1870   .1403   .1019   .0717   .0486   .0300
    Poisson .0643   .1765   .2421   .2215   .1519   .0834   .0381   .0149
    NegBin  .1429   .2042   .1948   .1551   .1111   .0744   .0474   .0292

    total absolute error   Poisson .3940   NegBin .1454

Poisson is badly wrong in both tails at once — it under-predicts the players
who catch nothing and the ones who catch eight. Some of that is genuine
overdispersion and some is a heterogeneous population: WRs average 3.16
receptions against 2.41 for RBs, and a marginal fit sees only the mixture.
Conditioning on features removes the second part, which is why `r` is fitted on
*model residuals* rather than taken from the 2.98 the marginal moments imply.

**The whole-number line is a real case, not an edge case.** Books post 5.0 as
well as 5.5, and a player landing exactly on it is a push — stake returned,
neither won nor lost. Nothing in this project has ever had to represent a bet
that can end in three ways, and treating a push as a loss would understate
every whole-line price. `prob_over` therefore returns the push mass alongside,
and callers price against `p_over / (p_over + p_under)` with the push removed.
"""
from __future__ import annotations

from datetime import date

import numpy as np
from scipy import stats
from scipy.optimize import minimize_scalar

#: Counts above this are treated as the tail. Receptions above 20 in a game
#: have happened, but not often enough to fit anything to.
MAX_COUNT = 25


def design_matrix(df, feature_names: list[str]) -> np.ndarray:
    """The feature matrix this model is fitted on, and the only one it is scored on.

    Missing stays missing. XGBoost has a native representation for an absent
    value — at every split it learns which way to send a NaN — and that is what
    training hands it, because `polars.to_numpy()` turns a null into a NaN.
    Fill those nulls with 0.0 instead and the row stops being routed by that
    default and starts being routed by where zero actually falls, which on a
    usage feature is the pocket holding players who are measured and not used.

    That is not a rounding difference on a count model. The serving path used
    to route through `trainer.prepare_data`, which ends in
    `np.nan_to_num(X, nan=0.0)` because the touchdown models want it there, and
    the first receptions board it produced led with a rookie at 8.52 expected
    receptions — above the best receiver in the league, from a player with no
    recorded target. His usage features were null, they arrived as zeros, and
    the model read a 91%-snap listed starter who is never thrown to, which is
    not a player who exists. Scored with the nulls intact he makes 4.96 and the
    top of the board is Chase, Nacua and St. Brown. The population mean moved
    by 0.02; only the rows worth betting moved.

    A player with no history is not a player with zero usage, and 0.0 is the
    one value that says he is. So this function exists to be called by the
    trainer, the backtest and the weekly board alike — three call sites that
    previously agreed by coincidence and drifted the moment one of them reached
    for a helper written for a different model.
    """
    import polars as pl

    missing = [c for c in feature_names if c not in df.columns]
    if missing:
        # Null, not zero: a feature the matrix does not carry is unknown, and
        # the model already knows what to do with unknown.
        df = df.with_columns([pl.lit(None, dtype=pl.Float64).alias(c)
                              for c in missing])
    return df.select(feature_names).to_numpy().astype(np.float64)


def fit_dispersion(mu: np.ndarray, y: np.ndarray) -> dict:
    """Fit the negative-binomial dispersion that turns mu into a distribution.

    One free parameter, fitted by log likelihood on games the count model did
    not train on. `r` has a physical reading: large r recovers Poisson (arrivals
    independent), small r means a player's receptions cluster — which they do,
    because targets arrive in bunches when a game script turns pass-heavy.

    Deliberately one number for the whole population rather than one per
    position. A per-position r is the obvious refinement and it is not free:
    it fits four parameters on the same data and the positions differ mostly in
    *mean*, which the count model already predicts per row.
    """
    mu = np.clip(np.asarray(mu, dtype=float), 1e-6, None)
    y = np.asarray(y, dtype=float)

    def nll(log_r: float) -> float:
        r = float(np.exp(log_r))
        p = r / (r + mu)
        return float(-np.sum(stats.nbinom.logpmf(y, r, p)))

    res = minimize_scalar(nll, bounds=(np.log(0.05), np.log(500.0)),
                          method="bounded")
    r = float(np.exp(res.x))

    poisson_nll = float(-np.sum(stats.poisson.logpmf(y, mu)))
    return {
        "kind": "count_dispersion",
        "dispersion": round(r, 4),
        "log_likelihood": -float(res.fun),
        "nll_per_row": float(res.fun) / max(len(y), 1),
        "poisson_nll_per_row": poisson_nll / max(len(y), 1),
        "n": int(len(y)),
        "fit_date": date.today().isoformat(),
    }


def fit_market_blend(p_model: np.ndarray, p_book: np.ndarray,
                     y: np.ndarray, kind: str = "receptions_market_blend") -> dict:
    """How much of our own number to keep, against the book's.

    Shared with `src/models/yards.py`, which is not a count model at all. This
    function and `blend_to_market` never touch the distribution — they take two
    probabilities and a settled outcome — so they are reused rather than
    copied, and `kind` says which market's weight the saved file holds.

    The count model does not beat this market on its own and is not close:
    0.690 against 0.673 on 2025. What it does have is information the price
    does not fully contain, and the way to use that is to predict the residual
    rather than the whole thing — shrink our probability toward the market's
    and fit how far by log likelihood on a season we did not train on.

    Measured on 2025, with the weight fitted on 2024: 0.66982 against the
    market's 0.67274, a gain of 0.0029 with a 95% bootstrap interval over games
    of [+0.0009, +0.0040] and P(gain > 0) = 1.000. That is a real improvement
    in calibration and it is a small one. It is emphatically not a betting
    edge: the same blend betting every over it rates above the posted price
    returned +7.8% on 2025 across 219 bets, with a confidence interval of
    [-5.9%, +21.7%], 99% of the profit in five fixtures, and -1.5% on 2024.

    The blend is done in log-odds space so the result cannot leave [0, 1] and a
    shrink toward the market is a straight line rather than a chord across a
    curve.

    A weight near zero is a real answer and is returned rather than floored: it
    says the best mix of us and the market is all market, which is worth
    knowing and is what every variant richer than this one produced.
    """
    a, b = _logit(p_model), _logit(p_book)
    y = np.asarray(y, dtype=float)
    grid = np.linspace(0.0, 1.0, 101)
    best_w, best_ll = 0.0, None
    for w in grid:
        p = _expit(w * a + (1 - w) * b)
        q = np.clip(p, 1e-9, 1 - 1e-9)
        ll = float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))
        if best_ll is None or ll < best_ll:
            best_ll, best_w = ll, float(w)

    def loss(p):
        q = np.clip(p, 1e-9, 1 - 1e-9)
        return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))

    return {
        "kind": kind,
        "weight": best_w,
        "n": int(len(y)),
        "fit_log_loss": best_ll,
        "model_log_loss": loss(p_model),
        "market_log_loss": loss(p_book),
        "fit_date": date.today().isoformat(),
    }


#: Positions the shrinkage fits a separate prior for. Anything else — and the
#: reference level of the one-hot, which is WR — falls into "OTHER".
_SHRINK_POSITIONS = ("RB", "TE", "QB", "FB")

#: A player at or below this many observed games is "no track record", and the
#: prior is the mean outcome of exactly that population. Not a modeling knob:
#: it selects the rows the prior is *measured on*, and the shrinkage strength
#: `k` is fitted separately against it.
_DEBUT_GAMES = 1


def position_labels(df) -> np.ndarray:
    """One position string per row, from the one-hot columns.

    The encoder drops a named reference level, so a row with every one-hot at
    zero is that level rather than an unknown — see the note in
    `src/features/assembler.py` about never letting an encoder pick its own.
    """
    n = df.height
    out = np.full(n, "OTHER", dtype=object)
    for pos in _SHRINK_POSITIONS:
        col = f"position_{pos}"
        if col in df.columns:
            hit = np.asarray(df[col].fill_null(0).to_numpy(), dtype=float) > 0.5
            out[hit] = pos
    return out


def fit_shrinkage(mu: np.ndarray, y: np.ndarray, games: np.ndarray,
                  positions: np.ndarray, *, seasons_used=None,
                  kind: str = "receptions_shrinkage") -> dict:
    """How far to pull a projection back toward a debutant's base rate.

    The count model reads a rolling mean without knowing how many games it is
    built from, so a player with one good week is indistinguishable from one
    with a season of them. On 2026 week 2 that put Caleb Douglas — 1 career
    game, 7 targets, 5 catches — at 5.33 expected receptions, 12th of 502,
    between Travis Kelce and Sam LaPorta. He drew 3 targets.

    The correction is the standard one and it has a single free parameter:

        mu_shrunk = (n * mu + k * prior) / (n + k)

    where `n` is games observed and `prior` is the mean outcome among players
    who had no track record either. `k` is in units of games — how many games
    of evidence it takes before the model's own number carries half the weight
    — and it is FITTED by Poisson deviance on seasons the count model did not
    train on, not chosen.

    The prior is measured on debutants rather than on the whole population on
    purpose. Shrinking a rookie toward the average *board* player would pull
    him toward men with established roles, which is a different and wrong
    claim.

    `k = 0` is a real answer and is returned rather than floored: it says the
    model needs no shrinking, which is worth knowing.
    """
    mu = np.clip(np.asarray(mu, dtype=float), 1e-6, None)
    y = np.asarray(y, dtype=float)
    games = np.asarray(games, dtype=float)
    positions = np.asarray(positions, dtype=object)

    debut = games <= _DEBUT_GAMES
    global_prior = float(np.mean(y[debut])) if debut.any() else float(np.mean(y))
    prior_by_pos, prior_n = {}, {}
    for pos in set(positions.tolist()):
        m = debut & (positions == pos)
        # Under 30 debut rows is not a prior, it is a rumour; fall back.
        prior_by_pos[str(pos)] = (float(np.mean(y[m])) if m.sum() >= 30
                                  else global_prior)
        prior_n[str(pos)] = int(m.sum())

    prior = np.array([prior_by_pos.get(str(p), global_prior) for p in positions])

    def deviance(shrunk: np.ndarray, actual: np.ndarray) -> float:
        s = np.clip(shrunk, 1e-6, None)
        with np.errstate(divide="ignore", invalid="ignore"):
            term = np.where(actual > 0, actual * np.log(actual / s), 0.0)
        return float(2.0 * np.mean(term - (actual - s)))

    def shrink(k: float) -> np.ndarray:
        return (games * mu + k * prior) / (games + k) if k > 0 else mu

    grid = np.concatenate([np.arange(0.0, 5.0, 0.1), np.arange(5.0, 31.0, 0.5)])
    best_k, best_d = 0.0, None
    for k in grid:
        d = deviance(shrink(float(k)), y)
        if best_d is None or d < best_d:
            best_d, best_k = d, float(k)

    thin = games <= 3
    sh = shrink(best_k)
    return {
        "kind": kind,
        "k_games": round(best_k, 3),
        "prior_by_position": {a: round(b, 4) for a, b in prior_by_pos.items()},
        "prior_debut_rows": prior_n,
        "global_prior": round(global_prior, 4),
        "debut_games_threshold": _DEBUT_GAMES,
        "n": int(len(y)),
        "fit_deviance": best_d,
        "unshrunk_deviance": deviance(mu, y),
        # What it actually changes. The population it is for is small, so a
        # gain averaged over everybody hides whether it worked.
        "thin_rows": int(thin.sum()),
        "thin_deviance_before": deviance(mu[thin], y[thin]) if thin.any() else None,
        "thin_deviance_after": deviance(sh[thin], y[thin]) if thin.any() else None,
        "thin_mean_mu_before": float(np.mean(mu[thin])) if thin.any() else None,
        "thin_mean_mu_after": float(np.mean(sh[thin])) if thin.any() else None,
        "thin_mean_actual": float(np.mean(y[thin])) if thin.any() else None,
        "seasons_used": list(seasons_used or []),
        "source": "weekly_stats.parquet receptions, via the candidate matrix",
        "fit_date": date.today().isoformat(),
    }


def apply_shrinkage(mu: np.ndarray, games: np.ndarray, positions: np.ndarray,
                    art: dict | None) -> np.ndarray:
    """`mu` pulled toward the debutant prior by the fitted `k`.

    A missing or zero-`k` artifact returns `mu` untouched, so a board built
    before the fit exists is the old board rather than a broken one.
    """
    if not art or not art.get("k_games"):
        return np.asarray(mu, dtype=float)
    k = float(art["k_games"])
    by_pos = art.get("prior_by_position") or {}
    gp = float(art.get("global_prior", 0.0))
    prior = np.array([float(by_pos.get(str(p), gp)) for p in positions])
    g = np.asarray(games, dtype=float)
    return (g * np.asarray(mu, dtype=float) + k * prior) / (g + k)


def blend_to_market(p_model: np.ndarray, p_book: np.ndarray,
                    weight: float) -> np.ndarray:
    """Our probability shrunk toward the book's, in log-odds space.

    Where the book has not priced a line there is nothing to shrink toward, so
    the model's own number is returned untouched — a missing price must not be
    read as a market opinion of 50%.
    """
    p_model = np.asarray(p_model, dtype=float)
    p_book = np.asarray(p_book, dtype=float)
    out = _expit(weight * _logit(p_model) + (1 - weight) * _logit(p_book))
    return np.where(np.isfinite(p_book), out, p_model)


def _logit(p):
    q = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(q / (1 - q))


def _expit(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=float)))


def prob_over(mu: np.ndarray, line: np.ndarray, dispersion: float
              ) -> tuple[np.ndarray, np.ndarray]:
    """P(count > line) and P(count == line), given expected count and dispersion.

    The second return value is the push mass, and it is zero for every
    half-point line. It is not zero for a whole-number one, which is why it is
    returned rather than folded away.
    """
    mu = np.clip(np.asarray(mu, dtype=float), 1e-9, None)
    line = np.asarray(line, dtype=float)
    r = float(dispersion)
    p = r / (r + mu)

    # P(Y > L) = 1 - P(Y <= floor(L)). For L = 3.5 that is 1 - CDF(3), and for
    # L = 5.0 it is 1 - CDF(5) — the push mass at exactly 5 belongs to neither
    # side, so it must come out of the over rather than be rounded into it.
    k = np.floor(line)
    over = 1.0 - stats.nbinom.cdf(k, r, p)
    push = np.where(line == k, stats.nbinom.pmf(k, r, p), 0.0)
    return np.clip(over, 0.0, 1.0), np.clip(push, 0.0, 1.0)


def count_interval(mu: np.ndarray, dispersion: float,
                   lo: float = 0.15, hi: float = 0.85
                   ) -> tuple[np.ndarray, np.ndarray]:
    """The range a count actually lands in, from the same fitted distribution.

    A mean on its own is the one number a projection cannot be read from. Two
    players can both project 4.2 and be completely different bets: a target
    hog who catches three to six every week, and a deep threat who catches
    one or nine. The fitted negative binomial already knows the difference —
    it is the whole reason `fit_dispersion` exists — so the floor and ceiling
    are read off it rather than estimated.

    15th and 85th percentiles by default, not 5/95. The tails of a count this
    small are a single catch wide and a 5th percentile is 0 for most of the
    board, which says nothing about anybody. Seven games in ten land inside
    the interval returned here.

    Returned continuously, which needs defending because the thing being
    counted is not. Nobody catches 3.47 passes, and `3.47` is not a claim that
    anybody will: it is the level at which the cumulative probability crosses
    15%, which is a real continuous quantity about the distribution even though
    every realisation of it is a whole number.

    The reason to interpolate rather than round is resolution. The integer
    quantile is a step function, so on a board of five hundred receivers most
    of them floor at 3 and ceiling at 9 and the column stops separating anyone.
    Interpolated, a 2.6 floor and a 3.4 floor are different players, which is
    what the column is for.

    Linear interpolation across the step that contains the quantile: find the
    count `k` where the CDF first reaches `q`, then walk back into the step by
    however much of `k`'s own mass was not needed.
    """
    mu = np.clip(np.asarray(mu, dtype=float), 1e-6, None)
    r = float(dispersion)
    p = r / (r + mu)
    dist = stats.nbinom(r, p)

    def q(level: float) -> np.ndarray:
        k = dist.ppf(level)
        below = dist.cdf(k - 1)          # mass strictly below the step
        mass = dist.pmf(k)
        # A step carrying no mass cannot be walked into; fall back to its edge.
        frac = np.where(mass > 1e-12, (level - below) / np.where(mass > 1e-12, mass, 1.0), 1.0)
        return np.clip(k - 1 + np.clip(frac, 0.0, 1.0), 0.0, None)

    return q(lo), q(hi)


def fair_two_way(over: np.ndarray, push: np.ndarray) -> np.ndarray:
    """Renormalize over/under to exclude the push, for comparison with a price.

    A book's Over 5.0 price is a claim about the two outcomes that resolve, not
    about all three. Comparing our raw P(>5) to it would count the push as a
    loss on our side and a refund on theirs.
    """
    over = np.asarray(over, dtype=float)
    push = np.clip(np.asarray(push, dtype=float), 0.0, 1.0 - 1e-12)
    return np.clip(over / (1.0 - push), 0.0, 1.0)


# ---------------------------------------------------------------------------
# The count regressor itself
# ---------------------------------------------------------------------------

import pickle          # noqa: E402
from pathlib import Path  # noqa: E402

from xgboost import XGBRegressor  # noqa: E402

from src.models.registry import register  # noqa: E402

#: Held identical to `model.xgb` in config on purpose. The classifier and the
#: count model differ in their objective and nothing else, so any difference in
#: what they learn is attributable to the objective rather than to tuning — the
#: same discipline `model.condlogit` is held to.
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


@register("xgb_count")
class XGBCountModel:
    """Expected count per player-game, by Poisson deviance.

    Poisson is the *objective*, not the assumed distribution. It is the right
    loss for a non-negative count with a multiplicative mean — it cannot
    predict a negative number of receptions, and an error on a 9-reception
    player costs proportionally rather than absolutely. The dispersion that
    turns this mean into a distribution is fitted separately by
    `fit_dispersion`, because the objective's own variance assumption is the
    one thing measurement says is wrong.
    """

    name = "xgb_count"

    def __init__(self):
        self.model: XGBRegressor | None = None
        self.feature_names: list[str] = []
        self.dispersion: float | None = None

    def fit(self, X_train, y_train, X_val, y_val, config: dict) -> None:
        params = {k: config.get(k, v) for k, v in DEFAULTS.items()}
        self.model = XGBRegressor(
            **params,
            objective="count:poisson",
            random_state=config.get("seed", 42),
            eval_metric="poisson-nloglik",
            verbosity=0,
        )
        self.model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
        # Dispersion is fitted on validation, never on training: it is a claim
        # about residual spread, and residuals on the rows the trees have
        # already memorised are too small to fit anything honest to.
        self.dispersion = fit_dispersion(self.predict_mu(X_val), y_val)["dispersion"]

    def predict_mu(self, X) -> np.ndarray:
        """Expected count. The natural output of this model."""
        return np.clip(self.model.predict(X), 1e-6, None)

    def predict_over(self, X, line) -> tuple[np.ndarray, np.ndarray]:
        """P(count > line) and the push mass, for any line."""
        if self.dispersion is None:
            raise RuntimeError("dispersion not fitted; call fit() first")
        return prob_over(self.predict_mu(X), line, self.dispersion)

    def predict_proba(self, X) -> np.ndarray:
        """P(count >= 1), so this model satisfies the binary ModelWrapper too.

        Not the point of the model, but it means anything already written
        against `predict_proba` — calibration plots, AUC, the evaluation
        harness — works on it without a special case.
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
                         "dispersion": self.dispersion}, f)

    @classmethod
    def load(cls, path: Path) -> "XGBCountModel":
        with open(path, "rb") as f:
            data = pickle.load(f)
        obj = cls()
        obj.model = data["model"]
        obj.feature_names = data.get("feature_names", [])
        obj.dispersion = data.get("dispersion")
        return obj
