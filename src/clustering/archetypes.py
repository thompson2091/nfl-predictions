"""Lens A: what kind of player is this?

Clusters player-games on usage and role — where a player touches the ball, how
often, and how close to the end zone — then measures each group against what
actually happened on seasons the clustering never saw.

**Position is the stratifier, not the answer.** Cluster the league as one pool
and the structure you find is running backs, receivers, and everyone with no
usage: measured on anytime TD, silhouette peaks at k=3 and those are the three
groups. That is the position column with extra steps. The interesting question
is what is left *inside* a position — which backs are goal-line backs, which
receivers are the ones their offense actually throws to near the end zone — so
the fit runs within RB, WR, TE and QB separately and the pooled result is kept
only as the evidence for why (`pooled_evidence` in the artifact, rendered in the
tab so the negative result is shown rather than filed away).

The raw position string only exists in candidates.parquet: features.parquet
carries dummies, and `to_dummies(drop_first=True)` drops a different reference
level per market (RB for anytime TD, TE for first TD), so reconstructing
position from them would silently mean something different in each. Joining the
string back is both simpler and correct in both markets.
"""
from __future__ import annotations

import pickle

import numpy as np
import polars as pl

from src.clustering import core
from src.evaluation.rank_economics import MIN_BETS, clustered_roi, load_bets
from src.models.trainer import _filter_low_activity
from src.utils.config import get_config, production_model
from src.utils.paths import get_path

#: Candidates in priority order. Priority is also the correlation tie-break:
#: when two columns duplicate each other the earlier one survives.
#:
#: Everything here describes the PLAYER. Team, opponent, weather and market
#: columns are left out on purpose — a group that changes when the opponent
#: changes is not an archetype, it is a matchup, and matchups are Lens B's job.
#: Also absent: the 3-game and season-long variants of these same concepts
#: (r > .95 duplicates of the 5-game window), `ngs_*` (92-97% null),
#: `sbook_*` (~100% null before the predict season), `ix_*` (products of columns
#: already listed), and the touchdown-streak features, which describe form
#: rather than role — a player is not a different kind of player because he
#: scored last week.
#:
#: `snap_pct_filled` rather than `snap_pct`: the raw column is 38.7% null in
#: training, and the assembler already writes the filled version that the
#: trainer excludes as a duplicate.
CANDIDATE_FEATURES = [
    # Where he touches it — the part that actually separates scorers.
    "player_gl_carries_avg_5g",
    "player_rz_carries_avg_5g",
    "player_rz_targets_avg_5g",
    "player_i5_touches_avg_5g",
    "player_i10_touch_share_avg_5g",
    "player_i5_touch_share_avg_5g",
    "player_endzone_td_rate_avg_5g",
    "player_td_market_share_avg_5g",
    # How much of it he gets.
    "player_carries_avg_5g",
    "player_targets_avg_5g",
    "player_receptions_avg_5g",
    "player_rush_share_avg_5g",
    "player_target_share_avg_5g",
    "player_air_yards_share_avg_5g",
    "player_wopr_avg_5g",
    # What he does with it.
    "player_rushing_yards_avg_5g",
    "player_receiving_yards_avg_5g",
    "player_receiving_yac_per_rec_avg_5g",
    # When he is on the field.
    "player_od_touch_share_avg_5g",
    "player_h1_touch_share_avg_5g",
    "snap_pct_filled",
    "is_starter",
    "is_high_usage",
]

#: Fullbacks cluster with backs — there are too few of them to fit alone, and
#: the ones who matter here are goal-line bodies, which is a back's role.
#: Defense and special teams have no usage profile at all; they score on
#: turnovers and returns, which none of these columns measure.
POSITION_FOLD = {"FB": "RB"}
STRATA = ("RB", "WR", "TE", "QB")

ARTIFACT = "clusters_player.json"
REPORT = "clusters_player_report"


def _null_rates(target_type: str) -> dict | None:
    path = get_path("models", target_type) / "train_null_rates.pkl"
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


def population(target_type: str) -> pl.DataFrame | None:
    """Every player-game production would score, with its position attached.

    The same `_filter_low_activity` the trainer, the backtest and the app all
    apply. Left in, the 64k rows it removes — no carries, no targets, no snaps —
    form the single largest cluster in the league and drag every centroid toward
    the origin, and they are not part of the population anything is served on.
    """
    feat_path = get_path("processed", target_type) / "features.parquet"
    cand_path = get_path("processed", target_type) / "candidates.parquet"
    if not feat_path.exists() or not cand_path.exists():
        return None

    df = _filter_low_activity(pl.read_parquet(feat_path))
    pos = (pl.read_parquet(cand_path)
           .select(["game_id", "player_id", "position"])
           .unique(subset=["game_id", "player_id"]))
    return (df.join(pos, on=["game_id", "player_id"], how="left")
            .with_columns(
                pl.col("position").replace(POSITION_FOLD).alias("stratum"))
            .filter(pl.col("stratum").is_in(STRATA)))


def _split() -> dict:
    return get_config()["splits"]


def reporting_window() -> tuple[int, int]:
    """Seasons a group may be scored on: after the fit, and already played.

    The upper bound is not decoration. `features.parquet` carries the predict
    season, whose rows have a `target` of 0 because nothing has happened yet,
    not because nobody scored. Left in the reporting set they read as a mass of
    players who all failed to score, which drags every group's touchdown rate
    below the truth and makes the model look systematically over-confident. The
    number is quietly wrong and nothing about it looks wrong.
    """
    cfg = get_config()
    return cfg["splits"]["train_end"] + 1, cfg["seasons"]["end"]


def fit(target_type: str, k_min: int | None = None, k_max: int | None = None,
        seed: int | None = None) -> dict:
    """Fit archetypes on the training seasons and persist everything that chose them."""
    cfg = core.settings()
    k_min = k_min or cfg["k_min"]
    k_max = k_max or cfg["k_max"]
    seed = cfg["seed"] if seed is None else seed
    split = _split()

    pop = population(target_type)
    if pop is None:
        raise FileNotFoundError(
            f"no features.parquet/candidates.parquet for {target_type}; run `make features`")
    fit_df = pop.filter(pl.col("season") <= split["train_end"])
    if fit_df.height < 1000:
        raise ValueError(f"only {fit_df.height} rows at or before "
                         f"{split['train_end']}; refusing to fit archetypes on that")

    null_rates = _null_rates(target_type)
    k_values = list(range(k_min, k_max + 1))

    # Each position gets its own feature set, its own transforms and its own
    # scaler, and that is a correctness requirement rather than a refinement.
    # Standardising across the whole league and then clustering inside a
    # position makes every centroid's z-score a statement about how the position
    # differs from the league: fitted that way, all four quarterback groups were
    # led by "receiving targets -1.2σ", which is not an archetype, it is the
    # word "quarterback". Scaled within the position, a deviation means what the
    # tab claims it means — this back against other backs.
    strata = {}
    for name in STRATA:
        sub = fit_df.filter(pl.col("stratum") == name)
        if sub.height < cfg["min_cluster_rows"] * k_min:
            continue
        features, dropped = core.prune_features(
            sub, CANDIDATE_FEATURES, null_rates,
            cfg["max_null_rate"], cfg["max_abs_corr"])
        if len(features) < 3:
            raise ValueError(
                f"pruning left {len(features)} features for {name}: {dropped}")
        transforms = core.fit_transforms(sub, features)
        impute = core.fit_impute(sub, features)
        X = core.build_matrix(sub, features, transforms, impute)
        scaler = core.fit_scaler(X)
        Xz = core.apply_scaler(X, scaler)
        strata[name] = {
            "features": features,
            "transforms": transforms,
            "impute": impute,
            "impute_method": "fit-set median, within this position",
            "scaler": scaler,
            "dropped": dropped,
            "pca_display": core.fit_pca_display(Xz, seed),
            **_fit_one(Xz, sub, features, k_values, cfg, seed, name),
        }

    return {
        "kind": "player_archetypes",
        "version": core.CLUSTER_VERSION,
        "target_type": target_type,
        "lens": "player",
        "seasons_used": sorted(fit_df["season"].unique().to_list()),
        "split": split,
        "population": "_filter_low_activity",
        "n_rows_fit": fit_df.height,
        "seed": seed,
        "k_range": [k_min, k_max],
        "criterion": "gap_statistic_1se",
        "candidate_features": CANDIDATE_FEATURES,
        # The feature set, transforms and scaler live per position, under
        # `strata` — see the comment above the fit loop for why.
        "features_by_stratum": {n: s["features"] for n, s in strata.items()},
        "strata_col": "position",
        "strata": strata,
        "pooled_evidence": _pooled_evidence(fit_df, null_rates, k_values, cfg, seed),
        "fit_date": core.today(),
        "source": (f"data/processed/{target_type}/features.parquet; "
                   f"position from candidates.parquet"),
    }


def _fit_one(Xz: np.ndarray, rows: pl.DataFrame, features: list[str],
             k_values: list[int], cfg: dict, seed: int, name: str) -> dict:
    """Select k for one position, fit it, and name what comes out."""
    # Cluster sizes are counted on every row, not on the gap statistic's
    # subsample. The `min_cluster_rows` gate asks whether a group is big enough
    # to measure anything about, and a subsample answers a different question:
    # at 8,000 rows drawn from 27,796 receivers, a real group of 163 shows up as
    # 47 and gets rejected as unmeasurable when it is nothing of the sort. Read
    # off the subsample, this gate collapsed both receiver positions to two
    # groups and hid every archetype the tab exists to show.
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
    named = core.name_clusters(np.asarray(fitted["centroids"]), features,
                               core.POSITION_NOUN.get(name, name))

    labels = fitted["labels"]
    dist = np.linalg.norm(Xz - np.asarray(fitted["centroids"])[labels], axis=1)
    for cluster in named:
        # The three fit rows nearest this centroid. If a group called
        # "goal-line back" is exemplified by three slot receivers, the name is
        # wrong and it takes two seconds to see.
        own = np.flatnonzero(labels == cluster["id"])
        nearest = own[np.argsort(dist[own])[:3]]
        cluster["examples"] = [
            {"player_name": rows["player_name"][int(i)],
             "season": int(rows["season"][int(i)]),
             "week": int(rows["week"][int(i)])}
            for i in nearest
        ]

    return {
        "n": int(Xz.shape[0]),
        "k": k,
        "k_unresolved": unresolved,
        "k_reason": reason,
        "centroids": fitted["centroids"],
        "sizes": fitted["sizes"],
        "inertia": fitted["inertia"],
        "outlier_distance_p95": fitted["outlier_distance_p95"],
        "selection": selection,
        "clusters": named,
    }


def _pooled_evidence(fit_df: pl.DataFrame, null_rates: dict | None,
                     k_values: list[int], cfg: dict, seed: int) -> dict:
    """The rejected approach, measured, so the tab can show its own null result.

    Clusters every position together — one league-wide space, which is the
    natural thing to try — and records what silhouette prefers and what those
    groups turn out to be. Kept in the artifact rather than written into prose
    so the claim on screen is re-derived on each refit instead of becoming a
    sentence somebody typed once and stopped checking.
    """
    features, _ = core.prune_features(
        fit_df, CANDIDATE_FEATURES, null_rates,
        cfg["max_null_rate"], cfg["max_abs_corr"])
    if len(features) < 3:
        return {}
    transforms = core.fit_transforms(fit_df, features)
    impute = core.fit_impute(fit_df, features)
    X = core.build_matrix(fit_df, features, transforms, impute)
    Xz = core.apply_scaler(X, core.fit_scaler(X))

    sil = core.silhouette_curve(Xz, k_values, cfg["silhouette_sample_rows"], seed)
    if not sil:
        return {}
    best = max(sil, key=lambda r: r["silhouette"])
    km = core._kmeans(core._subsample(Xz, cfg["silhouette_sample_rows"], seed),
                      best["k"], seed)
    ids, _ = core.assign(Xz, km.cluster_centers_)
    pooled = fit_df.with_columns(pl.Series("pooled_cluster", ids))

    composition = []
    for cid in range(best["k"]):
        sub = pooled.filter(pl.col("pooled_cluster") == cid)
        if not sub.height:
            continue
        shares = (sub.group_by("stratum").len()
                  .with_columns((pl.col("len") / sub.height).alias("share"))
                  .sort("share", descending=True))
        composition.append({
            "cluster": cid,
            "n": sub.height,
            "top_positions": [
                {"position": r["stratum"], "share": float(r["share"])}
                for r in shares.head(3).to_dicts()
            ],
        })
    return {"selection": sil, "silhouette_best_k": best["k"],
            "composition": composition}


def assign_frame(df: pl.DataFrame, artifact: dict) -> pl.DataFrame:
    """Attach cluster id, label and distance to any frame of player-games.

    Uses only what the artifact carries — features, transforms, impute values,
    scaler and centroids, each read through `core.space` for the position being
    assigned — so the fit path and the serve path cannot drift.
    """
    out_ids = np.full(df.height, -1, dtype=int)
    out_dist = np.full(df.height, np.nan)
    labels = np.array([""] * df.height, dtype=object)
    outlier = np.zeros(df.height, dtype=bool)

    for name, stratum in artifact["strata"].items():
        mask = (df["stratum"] == name).to_numpy()
        if not mask.any():
            continue
        sub = df.filter(pl.Series(mask))
        Xz = core.embed(sub, artifact, name)
        ids, dist = core.assign(Xz, stratum["centroids"])
        by_id = {c["id"]: c["label"] for c in stratum["clusters"]}
        idx = np.flatnonzero(mask)
        out_ids[idx] = ids
        out_dist[idx] = dist
        labels[idx] = [by_id.get(int(i), f"{name} {i}") for i in ids]
        outlier[idx] = dist > stratum["outlier_distance_p95"]

    return df.with_columns([
        pl.Series("cluster_id", out_ids),
        pl.Series("cluster_label", labels.tolist(), dtype=pl.Utf8),
        pl.Series("cluster_distance", out_dist),
        pl.Series("is_outlier", outlier),
    ])


def measure(target_type: str, artifact: dict, model: str | None = None) -> dict:
    """Score each archetype on the seasons the clustering never saw.

    Rates and calibration come from every reporting player-game; the money
    columns come from the priced subset, because a return needs a price. Both
    row counts are reported so the difference between them stays visible.
    """
    lo, hi = reporting_window()
    pop = population(target_type)
    if pop is None:
        raise FileNotFoundError("features/candidates missing")
    rep = pop.filter(pl.col("season").is_between(lo, hi))
    if not rep.height:
        raise ValueError(f"no played seasons in {lo}-{hi} to report on")
    rep = assign_frame(rep, artifact)

    bets = load_bets(target_type, model=model)
    if bets is not None:
        # `season` is deliberately not selected: the reporting frame already
        # carries it, and features.parquet also carries a `season_right` from an
        # earlier join, so pulling a second one in collides.
        bets = bets.filter(pl.col("season").is_between(lo, hi)).select([
            "game_id", "player_id", "prob_calibrated", "market_prob",
            "odds", "scored", "pnl", "breakeven",
        ])
        # A backtest holding two rows for one player-game would fan this join
        # out and quietly inflate every count, hit rate and return below it.
        # This project has been bitten by exactly that before; fail instead.
        keys = bets.select(["game_id", "player_id"])
        if keys.unique().height != keys.height:
            raise ValueError(
                f"{target_type} backtests hold duplicate (game_id, player_id) "
                f"rows; joining them would fan out every archetype's counts")
        before = rep.height
        rep = rep.join(bets, on=["game_id", "player_id"], how="left")
        if rep.height != before:
            raise ValueError(
                f"bet join changed the row count {before} -> {rep.height}")
    else:
        rep = rep.with_columns([
            pl.lit(None, dtype=pl.Float64).alias(c)
            for c in ("prob_calibrated", "market_prob", "odds", "scored",
                      "pnl", "breakeven")
        ])

    rows = []
    for name, stratum in artifact["strata"].items():
        sub_all = rep.filter(pl.col("stratum") == name)
        for cluster in stratum["clusters"]:
            cell = sub_all.filter(pl.col("cluster_id") == cluster["id"])
            if not cell.height:
                continue
            rows.append(_cell(cell, rep.height, name, cluster))

    priced = rep.filter(pl.col("pnl").is_not_null())
    return {
        "kind": "player_archetype_report",
        "version": core.CLUSTER_VERSION,
        "target_type": target_type,
        "model": model or production_model(target_type),
        "fit_seasons": artifact["seasons_used"],
        "report_seasons": sorted(rep["season"].unique().to_list()),
        "n_rows": rep.height,
        "n_priced_rows": priced.height,
        "n_cells": len(rows),
        "rows": sorted(rows, key=lambda r: -r["n"]),
        "fit_date": core.today(),
        "source": (f"output/{target_type}/backtest_*.csv; "
                   f"data/processed/{target_type}/features.parquet"),
    }


def _cell(cell: pl.DataFrame, total: int, stratum: str, cluster: dict) -> dict:
    """One archetype's out-of-fit record: how often, how wrong, how much."""
    row = {
        "stratum": stratum,
        "cluster": cluster["id"],
        "label": cluster["label"],
        "label_source": cluster["label_source"],
        "profile": core.profile(cluster["top_features"]),
        "n": cell.height,
        "share": cell.height / max(total, 1),
        "td_rate": float(cell["target"].mean()),
        "outlier_share": float(cell["is_outlier"].mean()),
    }

    priced = cell.filter(pl.col("pnl").is_not_null())
    if not priced.height:
        row.update({"n_bets": 0, "thin": True, "roi": None, "lo": None,
                    "hi": None, "concentration": None,
                    "verdict": "never priced", "per_season": []})
        return row

    actual = float(priced["scored"].mean())
    ours = float(priced["prob_calibrated"].mean())
    theirs = float(priced["market_prob"].mean())
    stats = clustered_roi(priced["pnl"].to_numpy(), priced["game_id"].to_numpy())
    row.update({
        "our_mean_prob": ours,
        "market_mean_prob": theirs,
        # Positive means we were too high on this kind of player.
        "our_gap_pp": (ours - actual) * 100,
        "market_gap_pp": (theirs - actual) * 100,
        "brier_ours": float(
            ((priced["prob_calibrated"] - priced["scored"]) ** 2).mean()),
        "brier_market": float(
            ((priced["market_prob"] - priced["scored"]) ** 2).mean()),
        "n_bets": priced.height,
        "hit_pct": actual * 100,
        "breakeven_pct": float(priced["breakeven"].mean()) * 100,
        "median_odds": float(priced["odds"].median()),
        "roi": stats["roi"],
        "lo": stats["lo"],
        "hi": stats["hi"],
        "concentration": stats["concentration"],
        "verdict": stats["verdict"],
        "thin": priced.height < MIN_BETS,
        # The repo's own standard for believing a return is that it holds in
        # each season separately, so the split is always available.
        "per_season": [
            {"season": int(s),
             **{k: v for k, v in clustered_roi(
                 priced.filter(pl.col("season") == s)["pnl"].to_numpy(),
                 priced.filter(pl.col("season") == s)["game_id"].to_numpy()
             ).items() if k in ("n", "roi", "lo", "hi")}}
            for s in sorted(priced["season"].unique().to_list())
        ],
    })
    return row


def explore(target_type: str, artifact: dict, stratum: str, k: int,
            features: list[str], seed: int, max_rows: int) -> list[dict]:
    """Refit one position with a different k or feature subset, in memory only.

    For the tab's exploratory toggle. It changes k and the feature set and
    nothing else: the fit seasons stay the fit seasons and the reporting seasons
    stay the reporting seasons, so an explored grouping is measured on the same
    honest footing as the served one. Twelve values of k crossed with arbitrary
    feature subsets and a returns column is a lottery with a search button, and
    the only thing keeping it useful is that the split is not one of the dials.

    Returns the same row shape `measure` produces, so the tab can render it
    through the same table and the numbers stay comparable. Writes nothing.
    """
    cfg = core.settings()
    pop = population(target_type)
    if pop is None:
        raise FileNotFoundError("features/candidates missing")

    fit_df = pop.filter((pl.col("season") <= _split()["train_end"])
                        & (pl.col("stratum") == stratum))
    if fit_df.height > max_rows:
        rng = np.random.default_rng(seed)
        keep = rng.choice(fit_df.height, max_rows, replace=False)
        fit_df = fit_df[sorted(keep.tolist())]

    transforms = {c: artifact["strata"][stratum]["transforms"][c] for c in features}
    impute = {c: artifact["strata"][stratum]["impute"][c] for c in features}
    X = core.build_matrix(fit_df, features, transforms, impute)
    scaler = core.fit_scaler(X)  # refit: a feature subset is a different space
    fitted = core.fit_stratum(core.apply_scaler(X, scaler), k, seed)
    named = core.name_clusters(np.asarray(fitted["centroids"]), features,
                               core.POSITION_NOUN.get(stratum, stratum))

    probe = {
        **artifact,
        "strata": {stratum: {**artifact["strata"][stratum],
                             "features": features, "transforms": transforms,
                             "impute": impute, "scaler": scaler,
                             "centroids": fitted["centroids"],
                             "clusters": named,
                             "outlier_distance_p95": fitted["outlier_distance_p95"]}},
    }
    rep = measure(target_type, probe)
    for row, size in zip(sorted(rep["rows"], key=lambda r: r["cluster"]),
                         fitted["sizes"]):
        row["fit_rows"] = size
    return rep["rows"]


def artifact_path(target_type: str):
    return get_path("models", target_type) / ARTIFACT


def report_path(target_type: str, model: str | None = None):
    name = f"{REPORT}_{model}.json" if model else f"{REPORT}.json"
    return get_path("output", target_type) / name
