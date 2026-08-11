"""A second model whose job is deciding which bets to make.

The first model answers "will this player score". It is good at that and its
errors are not random: measured on 6,792 backtested bets, it under-predicts
quarterbacks by 9.2 points, underdogs by up to 3.9 points scaling with the
spread, and everything by about 1.5 points overall. Those are the same misses
every week, in the same places, and no amount of extra features inside the first
model has found them because they are structural rather than informational.

This model takes the first model's probability as an *input*, alongside the
price and the context the first model never sees in this form, and predicts the
outcome again. What it learns is the correction: "when the first model says 24%
about a quarterback, the truth is nearer 33%". A corrected probability gives a
corrected edge, and a corrected edge is a better answer to *should I back this*
than the raw one.

Three things make it honest rather than a second chance to overfit:

  * **It is walk-forward.** Stage two for season S is fitted only on seasons
    before S. A stacked model fitted on the same rows it scores will always look
    brilliant and always be worthless.
  * **Its inputs are all known before kickoff.** Price, rank, position, spread,
    total, week. Nothing about how the game went.
  * **It is judged on money, not on likelihood.** Brier improvement is necessary
    but not sufficient — a model that sharpens probabilities in the middle of
    the distribution and nowhere near a price has improved nothing you can bet.
    `evaluate` reports both, and the profitability comparison is the one that
    decides whether this is worth serving.

Logistic regression by default. With roughly 7,000 usable rows per fold and
eleven inputs, a gradient booster has enough freedom to memorise the fold; the
linear model cannot, and the corrections we are looking for (a level shift for
quarterbacks, a slope against the spread) are exactly what it represents well.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from src.utils.paths import get_path

#: Inputs available at bet time. `prob_calibrated` is the first model's answer;
#: everything else is the context in which that answer tends to be wrong.
FEATURES = [
    "prob_calibrated",     # what the first model said
    "market_prob",         # the vig-free price
    "edge",                # their disagreement, the thing a bet is made of
    "log_odds_price",      # price level, where the book's premium lives
    "rank",                # position within the game's list
    "is_qb", "is_rb", "is_te",   # the position-specific misses (WR is baseline)
    "spread_line",         # the underdog gradient
    "total_line",
    "is_home",
]

#: Below this a fold is skipped rather than fitted. Eleven coefficients on a few
#: hundred rows is a story, not an estimate.
MIN_TRAIN_ROWS = 2000


def build_frame(target_type: str = "anytime_td",
                model: str | None = None) -> pl.DataFrame | None:
    """Backtested bets joined to the context stage two reasons about.

    Rows come from the walk-forward backtest frames, so `prob_calibrated` was
    itself produced by a model that never saw the season it is scoring. That
    property is what makes stacking on top of it legitimate.
    """
    from src.evaluation.rank_economics import backtest_files

    frames = []
    for path in backtest_files(target_type, model):
        season = int(path.stem.rsplit("_", 1)[-1])
        frames.append(pl.read_csv(path).with_columns(pl.lit(season).alias("season")))
    if not frames:
        return None
    df = pl.concat(frames, how="diagonal_relaxed")

    need = {"prob_calibrated", "market_prob", "scored", "game_id", "player_id",
            "odds", "dec"}
    if not need <= set(df.columns):
        return None

    feats = pl.read_parquet(get_path("processed", target_type) / "features.parquet")
    ctx = [c for c in ("spread_line", "total_line", "is_home", "position_QB",
                       "position_RB", "position_TE") if c in feats.columns]
    df = df.join(feats.select(["game_id", "player_id"] + ctx),
                 on=["game_id", "player_id"], how="left")

    df = df.with_columns([
        (pl.col("prob_calibrated") - pl.col("market_prob")).alias("edge"),
        # Price on a scale where equal steps mean equal odds ratios, so the
        # model can express "the book's premium grows with the price" as a slope
        # rather than needing a curve.
        (pl.col("dec") - 1.0).log().alias("log_odds_price"),
        pl.col("prob_calibrated").rank(descending=True, method="ordinal")
        .over("game_id").alias("rank"),
        (pl.col("scored") * (pl.col("dec") - 1) - (1 - pl.col("scored"))).alias("pnl"),
        # The hit rate a bet must clear at its own price. rank_economics
        # computes this too; stage two needs it here because `fit_edge_rule`
        # runs against this frame rather than that one.
        (1.0 / pl.col("dec")).alias("breakeven"),
    ])
    for src, dst in (("position_QB", "is_qb"), ("position_RB", "is_rb"),
                     ("position_TE", "is_te")):
        df = df.with_columns(
            (pl.col(src).fill_null(0) if src in df.columns
             else pl.lit(0.0)).cast(pl.Float64).alias(dst)
        )
    for c in ("spread_line", "total_line", "is_home"):
        if c not in df.columns:
            df = df.with_columns(pl.lit(0.0).alias(c))
    return df.with_columns([pl.col(c).cast(pl.Float64).fill_null(0.0)
                            for c in FEATURES])


#: Context the first model is known to get wrong, used as a *correction* to its
#: probability rather than as inputs to a fresh one. Deliberately short: these
#: are the residuals measured in the audit, not everything available.
CORRECTIONS = ["is_qb", "is_rb", "is_te", "spread_line", "log_odds_price",
               "rank", "is_home"]


def _fit_offset(train: pl.DataFrame):
    """Fit only a correction, holding the first model's probability fixed.

    The free-form version of stage two — re-predicting the outcome from
    everything at once — came out *worse* than stage one: Brier -2.8%, AUC
    0.8184 -> 0.8112. It spent its capacity re-learning rank and price, which
    the first model already encodes, and had nothing left for the residual.

    This form cannot do that. The first model's log-odds enter with a
    coefficient fixed at 1, so the only thing being estimated is the offset:
    how far, and in what direction, the answer is wrong for quarterbacks, for
    underdogs, at long prices. Seven parameters instead of eleven plus a
    refitted base, on the same rows.
    """
    from scipy.optimize import minimize
    from sklearn.preprocessing import StandardScaler

    base = _logit(train["prob_calibrated"].to_numpy())
    Z = train.select(CORRECTIONS).to_numpy()
    y = train["scored"].to_numpy().astype(float)
    scaler = StandardScaler().fit(Z)
    Zs = scaler.transform(Z)
    Zs = np.column_stack([np.ones(len(Zs)), Zs])          # intercept

    def nll(w):
        z = base + Zs @ w
        # log(1+exp(z)) computed stably, so a confident row cannot overflow.
        return float(np.mean(np.logaddexp(0.0, z) - y * z) + 1e-4 * np.sum(w * w))

    w0 = np.zeros(Zs.shape[1])
    res = minimize(nll, w0, method="L-BFGS-B")
    return scaler, res.x


def _apply_offset(scaler, w, frame: pl.DataFrame) -> np.ndarray:
    base = _logit(frame["prob_calibrated"].to_numpy())
    Zs = scaler.transform(frame.select(CORRECTIONS).to_numpy())
    Zs = np.column_stack([np.ones(len(Zs)), Zs])
    return 1.0 / (1.0 + np.exp(-(base + Zs @ w)))


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _fit(train: pl.DataFrame):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    X = train.select(FEATURES).to_numpy()
    y = train["scored"].to_numpy().astype(int)
    scaler = StandardScaler().fit(X)
    lr = LogisticRegression(max_iter=2000, C=1.0).fit(scaler.transform(X), y)
    return scaler, lr


def _apply(scaler, lr, frame: pl.DataFrame) -> np.ndarray:
    return lr.predict_proba(scaler.transform(frame.select(FEATURES).to_numpy()))[:, 1]


def walk_forward(df: pl.DataFrame) -> pl.DataFrame | None:
    """Score each season with a stage two fitted only on earlier seasons."""
    seasons = sorted(df["season"].unique().to_list())
    out = []
    for s in seasons:
        train = df.filter(pl.col("season") < s)
        test = df.filter(pl.col("season") == s)
        if train.height < MIN_TRAIN_ROWS or test.height == 0:
            continue
        scaler, lr = _fit(train)
        out.append(test.with_columns(pl.Series("prob_stage2", _apply(scaler, lr, test))))
    return pl.concat(out) if out else None


def evaluate(target_type: str = "anytime_td",
             model: str | None = None) -> dict | None:
    """Does stage two beat stage one — on likelihood, and on money?

    Both are reported because they can disagree, and only the second decides
    whether this gets served. Bet selection uses the same fitted edge rule the
    board applies, so the comparison is like-for-like: the only thing that
    changes between the two columns is which probability computed the edge.
    """
    from sklearn.metrics import brier_score_loss, roc_auc_score
    from src.evaluation.rank_economics import clustered_roi, fit_edge_rule

    df = build_frame(target_type, model)
    if df is None:
        return None
    scored = walk_forward(df)
    if scored is None or scored.height == 0:
        return None

    y = scored["scored"].to_numpy().astype(float)
    p1 = scored["prob_calibrated"].to_numpy()
    p2 = scored["prob_stage2"].to_numpy()

    rule = fit_edge_rule(df.with_columns(
        pl.col("prob_calibrated").rank(descending=True, method="ordinal")
        .over("game_id").alias("rank")))
    cut = rule["edge_cut"] if rule else 0.01
    max_rank = rule["max_rank"] if rule else 5

    scored = scored.with_columns(
        (pl.col("prob_stage2") - pl.col("market_prob")).alias("edge_stage2"))

    def money(edge_col: str) -> dict:
        sel = scored.filter((pl.col(edge_col) >= cut) & (pl.col("rank") <= max_rank))
        if sel.height == 0:
            return {"n": 0, "roi": None}
        r = clustered_roi(sel["pnl"].to_numpy(), sel["game_id"].to_numpy())
        r["per_season"] = {
            int(s): round(float(sel.filter(pl.col("season") == s)["pnl"].mean() * 100), 1)
            for s in sorted(sel["season"].unique().to_list())
        }
        return r

    return {
        "target_type": target_type,
        "model": model,
        "n": int(scored.height),
        "seasons": sorted(int(s) for s in scored["season"].unique().to_list()),
        "edge_cut": cut,
        "max_rank": max_rank,
        "brier_stage1": float(brier_score_loss(y, p1)),
        "brier_stage2": float(brier_score_loss(y, p2)),
        "auc_stage1": float(roc_auc_score(y, p1)),
        "auc_stage2": float(roc_auc_score(y, p2)),
        "money_stage1": money("edge"),
        "money_stage2": money("edge_stage2"),
        "coefficients": coefficients(df),
    }


def coefficients(df: pl.DataFrame) -> dict:
    """What the correction actually learned, in plain coefficients.

    Worth reading rather than trusting: if this says quarterbacks get a positive
    bump and underdogs get a positive slope, it has rediscovered the residuals
    that motivated it, which is the cheapest available check that it is
    modelling something real.
    """
    scaler, lr = _fit(df)
    return {f: round(float(c), 4) for f, c in zip(FEATURES, lr.coef_[0])}


def fit_and_save(target_type: str = "anytime_td", model: str | None = None,
                 path: Path | None = None) -> Path | None:
    """Fit on everything available and persist, for serving."""
    import pickle

    df = build_frame(target_type, model)
    if df is None or df.height < MIN_TRAIN_ROWS:
        return None
    scaler, lr = _fit(df)
    path = path or (get_path("models", target_type) / "stage2.pkl")
    path.write_bytes(pickle.dumps(
        {"scaler": scaler, "model": lr, "features": FEATURES,
         "n_rows": int(df.height),
         "seasons": sorted(int(s) for s in df["season"].unique().to_list())}))
    return path


def save(stats: dict, path: Path) -> None:
    Path(path).write_text(json.dumps(stats, indent=2))


def load(path: Path) -> dict | None:
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else None
