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
    scorer count used to normalize one-sided books.

    **Pass only the players you are going to score.** The one-sided branch
    divides every price by `sum(implied) / expected`, so the result for a
    favorite depends on how many *other* players the book happened to quote.
    Archive coverage fell from 52 priced players a game in 2023 to 26.8 in
    2025, and that alone moved a -100 favorite's "fair" probability from 41%
    to 49% while its real rate sat near 52% throughout. The market number was
    partly an artifact of how deep the book's longshot list ran that season,
    which then flowed into every edge, the blend weight, and the head-to-head
    claims in the app. Restricting the input to the scored population holds the
    denominator steady (scale 0.836 / 0.844 / 0.894 across the same seasons).
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
                    out_col: str = "prob_calibrated",
                    mask_col: str | None = None) -> pl.DataFrame:
    """Shift each game's log-odds so its probabilities sum to the expected count.

    With `mask_col` — the name of a boolean column — the sum is matched over
    only those rows, while the shift is still applied to every row in the game.
    Production scores priced players, and roughly five candidates a game are
    never priced. Making the total come out right across *all* candidates
    therefore hands about a tenth of the probability mass to players who
    account for well under 1% of actual scorers, which leaves every priced
    player systematically short. Pass the priced mask and an expectation
    already scaled by the prior's `priced_share` to normalize where it counts.

    The shift is monotone in log-odds, so ranking is untouched either way.
    """
    exp_map = dict(zip(expected["game_id"].to_list(),
                       expected["expected_scorers"].to_list()))
    out = []
    for (game_id,), g in df.group_by(["game_id"], maintain_order=True):
        p = g[prob_col].to_numpy()
        if mask_col is not None and mask_col in g.columns:
            m = g[mask_col].fill_null(False).to_numpy().astype(bool)
        else:
            m = np.ones(len(p), dtype=bool)
        # Nothing priced in this game: fall back to normalizing over everyone,
        # which is the pre-existing behavior rather than a silent no-op.
        target_rows = p[m] if m.any() else p
        delta = _solve_shift(target_rows, exp_map.get(game_id, float("nan")))
        if not np.isfinite(delta):
            delta = 0.0
        out.append(g.with_columns([
            pl.Series(out_col, _sigmoid(_logit(p) + delta)),
            pl.lit(delta).alias("level_shift"),
        ]))
    return pl.concat(out) if out else df


# --------------------------------------------------------------------------
# 3. Blend
# --------------------------------------------------------------------------

def build_blend_training_frame(target_type: str, model_name: str,
                               before: tuple[int, int] | None = None,
                               model_dir=None,
                               min_season: int | None = None) -> pl.DataFrame | None:
    """Assemble (model_prob, market_prob, scored) rows to fit the stacker on.

    `load_graded_history` returns prices and outcomes but no model predictions,
    so passing it straight to `fit_blend_weight` always returned None and the
    blend silently stayed on its bootstrap weight forever. This runs the archive
    back through the production path — model, then level calibration, then
    de-vig — so the two estimates being combined are on the same footing.

    Args:
        before: optional (season, week). Only games strictly before this are
            included, which is what makes a walk-forward backtest honest.
        model_dir: which trained model to score the archive with. Defaults to
            production, which is right when serving and **wrong inside a
            walk-forward backtest** — see below.
        min_season: drop archive seasons before this. Serving passes
            `val_season + 1`, because a model cannot tell you how much help it
            needs by being asked about years it trained on — see below.

    `model_dir` and `min_season` are the whole reason this is not a two-line
    helper. Both exist to stop the stacker learning from a model's own training
    data, which biases the weight one specific way: in-sample predictions look
    sharper than honest ones, so the stacker concludes the model needs no help
    and suppresses the market.

    `model_dir` used to read production unconditionally, so a walk-forward
    backtest that had carefully retrained into a scratch directory still fitted
    its weight against a model that had trained on the archive's seasons. That
    drove the market weight to 0.010-0.015 across anytime-TD 2024 and
    0.003-0.005 on first-TD 2025, against an honest 0.23-0.33.

    `min_season` is the same disease in the serving path. Production's model
    trains through `splits.train_end` and early-stops on `splits.val_season`,
    but the weight was fitted over the whole archive — so two of three seasons
    were the model's own homework. Measured on anytime TD, the weight rises
    monotonically as that contamination is removed:

        2023-2025 (two seasons contaminated)   w = 0.214
        2024-2025 (val season + one clean)     w = 0.432
        2025 only (clean)                      w = 0.600

    Production had been serving roughly 0.29 where the honest answer is near
    0.60 — it was trusting the model about twice as much as the evidence
    supports. The season guard in scripts/10_backtest.py catches neither case:
    it checks which season is being *scored*, not which model produced the
    stacker's training rows.
    """
    import pickle

    from src.ingest.odds_history import load_graded_history
    from src.models.market_prior import load_prior, expected_scorers
    from src.models.registry import get_model, ensure_registered
    from src.models.scoring import score
    from src.models.trainer import prepare_data, _filter_low_activity
    from src.utils.paths import get_path

    graded = load_graded_history(target_type)
    if graded is None or graded.height == 0:
        return None

    if before is not None:
        s, w = before
        graded = graded.filter(
            (pl.col("season") < s) | ((pl.col("season") == s) & (pl.col("week") < w))
        )
    if min_season is not None:
        graded = graded.filter(pl.col("season") >= min_season)
    if graded.height == 0:
        return None

    model_dir = Path(model_dir) if model_dir is not None else get_path("models", target_type)
    prior = load_prior(model_dir / "scorer_rate_prior.json")
    fc_path = model_dir / "feature_cols.pkl"
    if prior is None or not fc_path.exists():
        return None

    ensure_registered()
    feature_cols = pickle.loads(fc_path.read_bytes())

    # The stacker has to see the number production actually publishes. When a
    # team rate has been fitted, predict.py sends the model through the joint
    # structure -- P = 1 - exp(-lambda * share) -- and only falls back to the
    # log-odds shift `calibrate_level` when it has not. This function used to
    # call calibrate_level unconditionally, so the weight was fitted against a
    # quantity nobody serves: two different transforms of the same raw score,
    # combined with the market as though they were interchangeable.
    from src.models.joint import apply_joint, load_team_rate, load_conversion
    team_model = load_team_rate(model_dir / "team_td_rate.json")
    conversion = load_conversion(model_dir / "td_conversion.json")

    feats = pl.read_parquet(get_path("processed", target_type) / "features.parquet")
    out = []
    for (season, week), _ in graded.group_by(["season", "week"], maintain_order=True):
        wdf = _filter_low_activity(
            feats.filter((pl.col("season") == season) & (pl.col("week") == week))
        )
        if wdf.height == 0:
            continue
        X, _ = prepare_data(wdf, feature_cols)
        # `team` rides along because the joint model forms shares within a
        # team-game; without it apply_joint has nothing to normalize over.
        res = wdf.select(["game_id", "player_id", "team"]).with_columns(
            pl.Series("raw_prob", score(model_name, X, feature_cols, model_dir))
        )
        games = wdf.group_by("game_id").agg(
            [pl.col("total_line").first(), pl.col("spread_line").first()]
        )
        exp = expected_scorers(prior, games)
        if team_model is not None:
            res = apply_joint(res, wdf, team_model, score_col="raw_prob",
                              out_col="model_prob", conversion=conversion)
        else:
            res = calibrate_level(res, "raw_prob", exp, out_col="model_prob")

        mkt = graded.filter((pl.col("season") == season) & (pl.col("week") == week))
        mkt = devig_market(
            mkt.select(["game_id", "player_id", "implied_prob", "fair_prob", "scored"]), exp
        )
        merged = res.join(
            mkt.select(["game_id", "player_id", "market_prob", "scored"]),
            on=["game_id", "player_id"], how="inner",
        )
        if merged.height:
            out.append(merged.with_columns([
                pl.lit(season).alias("season"), pl.lit(week).alias("week"),
            ]))

    return pl.concat(out) if out else None


def fit_blend_weight(history: pl.DataFrame, min_rows: int = 500) -> dict | None:
    """Learn how much to trust the model vs the market, from resolved history.

    Fits the one number `blend` actually applies: the w minimising the log loss
    of sigmoid((1-w)*logit(model) + w*logit(market)), searched directly on
    [0, 1]. Returns None until enough resolved player-games exist to fit
    responsibly.

    This used to fit a different model than it served. The estimator was an
    unregularised logistic regression of the outcome on both logits,

        logit(p) = c + a*logit(model) + b*logit(market)

    reporting |b|/(|a|+|b|). But `blend` applies no intercept and forces the
    coefficients to sum to one, and the fit does not: measured on three seasons
    it wanted a+b = 1.11 and c = 0.21 for anytime TD, and a+b = 1.25, c = 0.71
    for first TD. The regression is free to spend signal on sharpening and on a
    level shift, then the ratio handed to `blend` silently drops both. Fitting
    the served parameter directly costs one line and removes the question.

    The out-of-sample difference between the two is small — under 0.001 of log
    loss either way across 2024 and 2025 — so this is a coherence fix rather
    than an accuracy win, and it should not be sold as one. The accuracy
    problem in this area was `build_blend_training_frame` scoring the archive
    with a contaminated model; see its docstring.
    """
    need = {"model_prob", "market_prob", "scored"}
    if history is None or history.height < min_rows or not need <= set(history.columns):
        return None

    df = history.drop_nulls(list(need))
    if df.height < min_rows:
        return None

    y = df["scored"].to_numpy().astype(int)
    if len(np.unique(y)) < 2:
        return None

    lm = _logit(df["model_prob"].to_numpy())
    lk = _logit(df["market_prob"].to_numpy())

    def nll(w: float) -> float:
        p = np.clip(_sigmoid((1 - w) * lm + w * lk), 1e-9, 1 - 1e-9)
        return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))

    # Bounded scalar minimisation: the objective is smooth and one-dimensional,
    # so this is exact to tolerance and cannot suffer the collinearity that made
    # the two-coefficient split unstable.
    from scipy.optimize import minimize_scalar
    res = minimize_scalar(nll, bounds=(0.0, 1.0), method="bounded")
    w = float(np.clip(res.x, 0.0, 1.0))

    return {
        "kind": "blend_weight",
        "source": "fitted",
        "market_weight": w,
        "log_loss": nll(w),
        "log_loss_model_only": nll(0.0),
        "log_loss_market_only": nll(1.0),
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
    from src.utils.history import write_kept

    write_kept(path, json.dumps(weight, indent=2))


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


# --------------------------------------------------------------------------
# First TD: a blend WITHIN the game
# --------------------------------------------------------------------------
#
# Anytime TD blends each player on his own, in log-odds, because each player's
# question has its own yes and no. First TD has one answer per game, so a
# per-player blend has to be renormalised afterwards and the thing actually
# being scored is a categorical distribution over the game's players. The
# blend is therefore GEOMETRIC over the priced players' shares,
#
#     p_i  ∝  m_i^(1-w) * k_i^w
#
# renormalised to the probability mass the MODEL gave those same players. The
# mass the model gave the unpriced players is left exactly where it was: the
# book has no opinion about them, and moving them would let a thin price list
# deflate or inflate everyone else — the failure the anytime priced-share
# guard exists for, which this construction cannot reach. A game with fewer
# than two priced players keeps the model's numbers untouched.
#
# Geometric, logit-then-renormalise and linear were all gated out of sample
# on 2026-10-06 (walk-forward backtests, fit on earlier seasons, scored on
# the next). Geometric and logit were indistinguishable; linear trailed both
# on every fold. Geometric is the one whose fitted parameter is the parameter
# served, since it renormalises by construction.

FIRST_TD_MIN_PRICED = 2


def first_td_blend_frame(seasons, model_name: str = "xgb",
                         output_dir=None) -> pl.DataFrame | None:
    """Walk-forward first-TD rows (model share, market share, scored) to fit on.

    Read from `output/first_td/backtest_<model>_<season>.csv`, which are
    produced by models that never trained on the season they score — the same
    honesty `build_blend_training_frame` buys for anytime by replaying only
    clean seasons. Kept to games whose first scorer was priced, because the
    categorical likelihood is the probability placed on the actual winner.
    """
    from src.utils.paths import get_path

    out_dir = Path(output_dir) if output_dir else get_path("output", "first_td")
    parts = []
    for s in seasons:
        path = out_dir / f"backtest_{model_name}_{s}.csv"
        if not path.exists():
            continue
        d = (pl.read_csv(path)
             .select(["game_id", "scored", "prob_calibrated", "market_prob"])
             .rename({"prob_calibrated": "model_prob"})
             .filter((pl.col("model_prob") > 0) & (pl.col("market_prob") > 0))
             .with_columns(pl.lit(int(s)).alias("season")))
        parts.append(d)
    if not parts:
        return None
    d = pl.concat(parts)
    return d.filter(pl.col("scored").sum().over("game_id") == 1)


def _first_td_shares(model_p: np.ndarray, market_p: np.ndarray,
                     game: np.ndarray, w: float) -> np.ndarray:
    """Geometric blend of within-game shares, normalised per game."""
    _, inv = np.unique(game, return_inverse=True)
    m = model_p / np.bincount(inv, model_p)[inv]
    k = market_p / np.bincount(inv, market_p)[inv]
    raw = np.exp((1 - w) * np.log(np.clip(m, EPS, 1))
                 + w * np.log(np.clip(k, EPS, 1)))
    return raw / np.bincount(inv, raw)[inv]


def fit_first_td_blend(history: pl.DataFrame | None,
                       min_games: int = 200) -> dict | None:
    """The market weight minimising -log p(first scorer), over priced games."""
    if history is None or history.height == 0:
        return None
    n_games = history["game_id"].n_unique()
    if n_games < min_games:
        return None
    m = history["model_prob"].to_numpy().astype(float)
    k = history["market_prob"].to_numpy().astype(float)
    g = history["game_id"].to_numpy()
    y = history["scored"].to_numpy().astype(int) == 1

    def nll(w: float) -> float:
        p = _first_td_shares(m, k, g, w)
        return float(-np.log(np.clip(p[y], EPS, 1)).mean())

    from scipy.optimize import minimize_scalar
    res = minimize_scalar(nll, bounds=(0.0, 1.0), method="bounded")
    w = float(np.clip(res.x, 0.0, 1.0))
    return {
        "kind": "first_td_blend",
        "method": "geometric_within_game",
        "source": "fitted",
        "market_weight": w,
        "nll_winner": nll(w),
        "nll_winner_model_only": nll(0.0),
        "nll_winner_market_only": nll(1.0),
        "n_games": int(n_games),
        "n_rows": int(history.height),
        "seasons": sorted(set(history["season"].to_list())),
        "fit_date": date.today().isoformat(),
    }


def blend_first_td(df: pl.DataFrame, model_col: str, market_col: str,
                   weight: dict, out_col: str = "probability") -> pl.DataFrame:
    """Serve the within-game blend; unpriced players keep the model's number.

    `model_col` must already sum to one per game. The priced players' total is
    held at the model's own total for them, so the game still sums to one and
    the unpriced players are untouched.
    """
    w = float(weight["market_weight"])
    model_p = df[model_col].to_numpy().astype(float)
    market_p = (df[market_col].to_numpy().astype(float)
                if market_col in df.columns else np.full(len(model_p), np.nan))
    priced = np.isfinite(market_p) & (market_p > 0)
    game = df["game_id"].to_numpy()

    out = model_p.copy()
    gids, inv = np.unique(game, return_inverse=True)
    n_priced = np.bincount(inv, priced.astype(float))
    use = priced & (n_priced[inv] >= FIRST_TD_MIN_PRICED)
    if use.any():
        idx = np.where(use)[0]
        shares = _first_td_shares(model_p[idx], market_p[idx], game[idx], w)
        _, sub_inv = np.unique(game[idx], return_inverse=True)
        mass = np.bincount(sub_inv, model_p[idx])[sub_inv]
        out[idx] = shares * mass
    return df.with_columns([
        pl.Series(out_col, out),
        pl.Series("has_market_price", priced),
        pl.lit(w).alias("market_weight"),
        pl.lit(weight.get("source", "unknown")).alias("blend_source"),
    ])
