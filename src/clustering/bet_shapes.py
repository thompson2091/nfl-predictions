"""Lens B: what kind of bet is this?

Clusters the shape of the wager rather than the shape of the player — our number
against the price, how far down the board it sits, and the game it lives in —
then asks what each kind of bet actually returned on the seasons the clustering
never saw.

Two choices here are inherited from `src/evaluation/rank_economics.py` and are
not free to differ from it:

**Edge is measured pre-blend.** The frame carries an `edge` column, and it is
the wrong one: it is computed from the published probability, which has already
been pulled toward the price by the market blend. Its apparent disagreement is
roughly 60% of the real one and it shrinks exactly where a disagreement would
matter. `model_edge` is recomputed here from `prob_calibrated` against
`market_prob`, the same way `edge_curve` does it and for the same reason.

**Returns get a game-clustered bootstrap.** Two bets in one game share a
defense, a game script and a final score, so they are not independent draws, and
per-bet returns are wildly skewed besides — a +3000 winner pays 30u against a 1u
loss. A naive interval on this data is about half what it should be. `measure`
calls `clustered_roi` rather than computing anything of its own.

One honest limitation, stated here and on screen: real odds history only begins
in 2023, and the training split ends there. So this lens is fitted on a single
season's board and measured on the two after it. That is thin, and the tab says
so rather than reaching across the split to feel better about it.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from src.clustering import core
from src.clustering.archetypes import reporting_window
from src.evaluation.rank_economics import MIN_BETS, clustered_roi, load_bets
from src.utils.config import get_config, production_model
from src.utils.paths import get_path

#: Priority order, same tie-break rule as Lens A. The measured collinearity on
#: this frame is severe — market_prob against log_dec is -0.92, and
#: prob_calibrated against rank_frac is -0.86 — so the correlation gate is doing
#: real work here, and which side of each pair survives is recorded in the
#: artifact rather than decided in advance.
CANDIDATE_FEATURES = [
    "model_edge",       # our disagreement with the de-vigged price, pre-blend
    "prob_calibrated",  # how likely we think it is
    "market_prob",      # how likely they think it is
    "log_dec",          # the price, on a scale where +6600 does not swallow the axis
    "rank_frac",        # how far down our board, normalized by board size
    "implied_team_total",
    "total_line",
    "abs_spread",
    "is_dome",
]

#: Lens B does not stratify: a bet has no position, and the whole point is to
#: find kinds of wager that cut across players. One stratum keeps a single
#: artifact schema and a single assign path shared with Lens A.
STRATUM = "all"

ARTIFACT = "clusters_bet"
REPORT = "clusters_bet_report"


def _split() -> dict:
    return get_config()["splits"]


def population(target_type: str, model: str | None = None) -> pl.DataFrame | None:
    """Every backtested bet with its shape columns derived and its game attached.

    `load_bets` already concatenates the per-season backtests, recovers `season`
    from the filename — the CSVs do not carry one — and adds rank, flat-stake
    profit and the breakeven rate each price implies. None of that is repeated
    here.
    """
    bets = load_bets(target_type, model=model)
    if bets is None or not bets.height:
        return None

    feat_path = get_path("processed", target_type) / "features.parquet"
    if feat_path.exists():
        ctx = (pl.read_parquet(feat_path)
               .select(["game_id", "player_id", "implied_team_total",
                        "total_line", "spread_line", "is_dome"])
               .unique(subset=["game_id", "player_id"]))
        bets = bets.join(ctx, on=["game_id", "player_id"], how="left")

    have = set(bets.columns)
    if not {"prob_calibrated", "market_prob", "dec"} <= have:
        return None

    return bets.with_columns([
        (pl.col("prob_calibrated") - pl.col("market_prob")).alias("model_edge"),
        pl.col("dec").log().alias("log_dec"),
        (pl.col("rank") / pl.len().over("game_id")).alias("rank_frac"),
        pl.col("spread_line").abs().alias("abs_spread")
        if "spread_line" in have else pl.lit(None, dtype=pl.Float64).alias("abs_spread"),
    ])


def fit(target_type: str, model: str | None = None, k_min: int | None = None,
        k_max: int | None = None, seed: int | None = None) -> dict:
    cfg = core.settings()
    k_min = k_min or cfg["k_min"]
    k_max = k_max or cfg["k_max"]
    seed = cfg["seed"] if seed is None else seed
    split = _split()

    pop = population(target_type, model)
    if pop is None:
        raise FileNotFoundError(
            f"no usable backtests for {target_type}; run `make backtest`")
    fit_df = pop.filter(pl.col("season") <= split["train_end"])
    if fit_df.height < 500:
        raise ValueError(
            f"only {fit_df.height} priced rows at or before {split['train_end']}; "
            f"odds history does not reach far enough back to fit bet shapes")

    features, dropped = core.prune_features(
        fit_df, CANDIDATE_FEATURES, None, cfg["max_null_rate"], cfg["max_abs_corr"])
    if len(features) < 3:
        raise ValueError(f"pruning left {len(features)} features: {dropped}")

    transforms = core.fit_transforms(fit_df, features)
    impute = core.fit_impute(fit_df, features)
    X = core.build_matrix(fit_df, features, transforms, impute)
    scaler = core.fit_scaler(X)
    Xz = core.apply_scaler(X, scaler)

    k_values = list(range(k_min, k_max + 1))
    # Counted on every row, not on the gap statistic's subsample — see the same
    # comment in archetypes._fit_one for what that gets wrong.
    sizes_by_k, inertia_by_k = {}, {}
    for k in k_values:
        km = core._kmeans(Xz, k, seed)
        sizes_by_k[k] = [int((km.labels_ == c).sum()) for c in range(k)]
        inertia_by_k[k] = float(km.inertia_)

    gap = core.gap_statistic(Xz, k_values, cfg["gap_reference_draws"],
                             cfg["gap_sample_rows"], seed)
    sil = core.silhouette_curve(Xz, k_values, cfg["silhouette_sample_rows"], seed)
    ari = core.split_half_ari(Xz, k_values, cfg["silhouette_sample_rows"], seed)
    selection = core.merge_selection(
        gap, sil, ari,
        [{"k": k, "inertia": inertia_by_k[k],
          "smallest_cluster": min(sizes_by_k[k])} for k in k_values])

    k, unresolved, reason = core.choose_k(gap, sizes_by_k, cfg["min_cluster_rows"])
    fitted = core.fit_stratum(Xz, k, seed)
    named = core.name_clusters(np.asarray(fitted["centroids"]), features, "bets")

    labels = fitted["labels"]
    dist = np.linalg.norm(Xz - np.asarray(fitted["centroids"])[labels], axis=1)
    for cluster in named:
        own = np.flatnonzero(labels == cluster["id"])
        nearest = own[np.argsort(dist[own])[:3]]
        cluster["examples"] = [
            {"player_name": fit_df["player_name"][int(i)],
             "season": int(fit_df["season"][int(i)]),
             "week": int(fit_df["week"][int(i)]) if "week" in fit_df.columns else 0}
            for i in nearest
        ]

    return {
        "kind": "bet_shapes",
        "version": core.CLUSTER_VERSION,
        "target_type": target_type,
        "lens": "bet",
        "model": model or production_model(target_type),
        "seasons_used": sorted(fit_df["season"].unique().to_list()),
        "split": split,
        "population": "priced rows in the walk-forward backtests",
        "n_rows_fit": fit_df.height,
        "seed": seed,
        "k_range": [k_min, k_max],
        "criterion": "gap_statistic_1se",
        "features": features,
        "transforms": transforms,
        "impute": impute,
        "impute_method": "fit-set median",
        "scaler": scaler,
        "dropped": dropped,
        "pca_display": core.fit_pca_display(Xz, seed),
        "strata_col": None,
        "strata": {STRATUM: {
            "n": fit_df.height,
            "k": k,
            "k_unresolved": unresolved,
            "k_reason": reason,
            "centroids": fitted["centroids"],
            "sizes": fitted["sizes"],
            "inertia": fitted["inertia"],
            "outlier_distance_p95": fitted["outlier_distance_p95"],
            "selection": selection,
            "clusters": named,
        }},
        "fit_date": core.today(),
        "source": f"output/{target_type}/backtest_*.csv",
    }


def assign_frame(bets: pl.DataFrame, artifact: dict) -> pl.DataFrame:
    stratum = artifact["strata"][STRATUM]
    Xz = core.embed(bets, artifact, STRATUM)
    ids, dist = core.assign(Xz, stratum["centroids"])
    by_id = {c["id"]: c["label"] for c in stratum["clusters"]}
    return bets.with_columns([
        pl.Series("cluster_id", ids),
        pl.Series("cluster_label", [by_id.get(int(i), str(i)) for i in ids],
                  dtype=pl.Utf8),
        pl.Series("cluster_distance", dist),
        pl.Series("is_outlier", dist > stratum["outlier_distance_p95"]),
    ])


def measure(target_type: str, artifact: dict, model: str | None = None) -> dict:
    lo, hi = reporting_window()
    pop = population(target_type, model)
    if pop is None:
        raise FileNotFoundError("no usable backtests")
    rep = pop.filter(pl.col("season").is_between(lo, hi))
    if not rep.height:
        raise ValueError(f"no played seasons in {lo}-{hi} to report on")
    rep = assign_frame(rep, artifact)

    rows = []
    for cluster in artifact["strata"][STRATUM]["clusters"]:
        cell = rep.filter(pl.col("cluster_id") == cluster["id"])
        if not cell.height:
            continue
        stats = clustered_roi(cell["pnl"].to_numpy(), cell["game_id"].to_numpy())
        rows.append({
            "stratum": STRATUM,
            "cluster": cluster["id"],
            "label": cluster["label"],
            "label_source": cluster["label_source"],
            "profile": core.profile(cluster["top_features"]),
            "n": cell.height,
            "n_bets": cell.height,
            "share": cell.height / rep.height,
            "hit_pct": float(cell["scored"].mean()) * 100,
            "breakeven_pct": float(cell["breakeven"].mean()) * 100,
            "median_odds": float(cell["odds"].median()),
            "our_mean_prob": float(cell["prob_calibrated"].mean()),
            "market_mean_prob": float(cell["market_prob"].mean()),
            "median_edge_pp": float(cell["model_edge"].median()) * 100,
            "outlier_share": float(cell["is_outlier"].mean()),
            "roi": stats["roi"],
            "lo": stats["lo"],
            "hi": stats["hi"],
            "concentration": stats["concentration"],
            "verdict": stats["verdict"],
            "thin": cell.height < MIN_BETS,
            "per_season": [
                {"season": int(s),
                 **{k: v for k, v in clustered_roi(
                     cell.filter(pl.col("season") == s)["pnl"].to_numpy(),
                     cell.filter(pl.col("season") == s)["game_id"].to_numpy()
                 ).items() if k in ("n", "roi", "lo", "hi")}}
                for s in sorted(cell["season"].unique().to_list())
            ],
        })

    return {
        "kind": "bet_shape_report",
        "version": core.CLUSTER_VERSION,
        "target_type": target_type,
        "model": model or production_model(target_type),
        "fit_seasons": artifact["seasons_used"],
        "report_seasons": sorted(rep["season"].unique().to_list()),
        "n_rows": rep.height,
        "n_priced_rows": rep.height,
        "n_cells": len(rows),
        "rows": sorted(rows, key=lambda r: -r["n"]),
        "fit_date": core.today(),
        "source": f"output/{target_type}/backtest_*.csv",
    }


def artifact_path(target_type: str, model: str | None = None):
    name = f"{ARTIFACT}_{model}.json" if model else f"{ARTIFACT}.json"
    return get_path("models", target_type) / name


def report_path(target_type: str, model: str | None = None):
    name = f"{REPORT}_{model}.json" if model else f"{REPORT}.json"
    return get_path("output", target_type) / name
