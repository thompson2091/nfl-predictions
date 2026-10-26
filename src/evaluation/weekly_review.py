"""Score a week's predictions against what actually happened.

Top-1 accuracy tells you whether the ranking was any good. It says nothing about
whether the *numbers* were right — a model can rank perfectly and still claim 40%
for players who score 25% of the time. For an app whose stated job is producing
the right probability, calibration is the measurement that matters.

So this asks the only question that settles it: **when we said 25%, did roughly
25% of them score?** And where sportsbook prices were archived, it asks the same
of the bookmaker, so our number is graded against the best available benchmark
rather than against nothing.
"""
from __future__ import annotations

import pickle

import numpy as np
import polars as pl

from src.models.registry import ensure_registered, get_model
from src.models.trainer import _filter_low_activity, prepare_data
from src.utils.config import get_config
from src.utils.paths import get_path

#: Buckets to report calibration in. Coarse on purpose — finer slices look
#: rigorous but each one holds too few players for its hit rate to mean anything.
BUCKETS = [(0.0, 0.10), (0.10, 0.20), (0.20, 0.30), (0.30, 0.45), (0.45, 1.01)]


def _brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(((p - y) ** 2).mean())


def score_week(season: int, week: int, target_type: str,
               model_name: str) -> dict | None:
    """Grade one week. Returns None if the week hasn't been played yet."""
    ensure_registered()
    cfg = get_config()

    feats = pl.read_parquet(get_path("processed", target_type) / "features.parquet")
    wdf = feats.filter((pl.col("season") == season) & (pl.col("week") == week))
    if wdf.height == 0 or wdf["target"].is_null().all():
        return None
    # A played week has scorers in it. All-zero means the results aren't in.
    if int(wdf["target"].sum() or 0) == 0:
        return None
    # PART-PLAYED WEEKS. On Sunday night the Monday game is still unplayed and
    # its players have no target yet; grade the games that have one.
    wdf = wdf.filter(pl.col("target").is_not_null())

    wdf = _filter_low_activity(wdf)
    model_dir = get_path("models", target_type)
    fc_path = model_dir / "feature_cols.pkl"
    if not fc_path.exists():
        return None
    feature_cols = pickle.loads(fc_path.read_bytes())

    model = get_model(model_name).load(model_dir / f"{model_name}.pkl")
    model.feature_names = feature_cols
    X, _ = prepare_data(wdf, feature_cols)
    probs = model.predict_proba(X)

    df = wdf.select(["game_id", "player_id", "player_name", "team", "target"]) \
            .with_columns(pl.Series("ours", probs))

    # Grade the bookmaker on the same players, wherever prices were archived.
    market = _market_for(season, week, target_type, df)
    if market is not None:
        df = df.join(market, on=["game_id", "player_id"], how="left")
    else:
        df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias("market_prob"))

    y = df["target"].to_numpy().astype(float)
    p = df["ours"].to_numpy()

    rows = []
    for lo, hi in BUCKETS:
        m = (p >= lo) & (p < hi)
        if m.sum() == 0:
            continue
        rows.append({
            "bucket": f"{lo:.0%}-{hi:.0%}" if hi <= 1 else f"{lo:.0%}+",
            "players": int(m.sum()),
            "we_said": float(p[m].mean()),
            "actually": float(y[m].mean()),
            "gap": float(p[m].mean() - y[m].mean()),
        })

    # Did our top-rated player in each game score?
    ranked = df.with_columns(
        pl.col("ours").rank(descending=True, method="ordinal")
        .over("game_id").alias("rank")
    )
    tops = ranked.filter(pl.col("rank") == 1)

    out = {
        "season": season,
        "week": week,
        "players": df.height,
        "games": df["game_id"].n_unique(),
        "scorers": int(y.sum()),
        "buckets": rows,
        "brier_ours": _brier(p, y),
        "top1_hit": float(tops["target"].mean()) if tops.height else None,
        "predicted_total": float(p.sum()),
        "actual_total": float(y.sum()),
    }

    # Head-to-head, on exactly the players both of us priced.
    both = df.filter(pl.col("market_prob").is_not_null())
    if both.height >= 20:
        yb = both["target"].to_numpy().astype(float)
        out["head_to_head"] = {
            "players": both.height,
            "brier_ours": _brier(both["ours"].to_numpy(), yb),
            "brier_market": _brier(both["market_prob"].to_numpy(), yb),
        }
    return out


def _market_for(season: int, week: int, target_type: str,
                df: pl.DataFrame) -> pl.DataFrame | None:
    """De-vigged closing prices for this week, if the archive has them."""
    try:
        from src.ingest.odds_history import load_graded_history
        from src.models.market_prior import expected_scorers, load_prior
        from src.prediction.blend import devig_market
    except Exception:
        return None

    graded = load_graded_history(target_type)
    if graded is None:
        return None
    mkt = graded.filter((pl.col("season") == season) & (pl.col("week") == week))
    if mkt.height == 0:
        return None

    prior = load_prior(get_path("models", target_type) / "scorer_rate_prior.json")
    if prior is None:
        return None

    feats = pl.read_parquet(get_path("processed", target_type) / "features.parquet")
    wk = feats.filter((pl.col("season") == season) & (pl.col("week") == week))
    games = wk.group_by("game_id").agg(
        [pl.col("total_line").first(), pl.col("spread_line").first()]
    )
    mkt = devig_market(
        mkt.select(["game_id", "player_id", "implied_prob", "fair_prob"]),
        expected_scorers(prior, games),
    )
    return mkt.select(["game_id", "player_id", "market_prob"]).unique(
        subset=["game_id", "player_id"]
    )


def played_weeks(season: int, target_type: str) -> list[int]:
    """Weeks in this season that have results to grade."""
    feats = pl.read_parquet(get_path("processed", target_type) / "features.parquet")
    s = feats.filter(pl.col("season") == season)
    if s.height == 0:
        return []
    played = (
        s.group_by("week").agg(pl.col("target").sum().alias("scorers"))
        .filter(pl.col("scorers") > 0).sort("week")["week"].to_list()
    )
    return [int(w) for w in played]
