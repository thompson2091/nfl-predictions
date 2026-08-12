"""Shared machinery for both clustering lenses: prune, transform, fit, name.

Two rules govern everything in this module, and both were learned from the way
the rest of this project has gone wrong before.

**The number of groups is fitted, not typed.** `choose_k` picks k from the gap
statistic and persists the whole curve that chose it, so a new season re-selects
instead of inheriting a constant somebody liked once. The obvious alternative,
silhouette, was measured and rejected: on anytime TD it peaks at k=3 and those
three groups are running backs, receivers and everyone with no usage. It
rediscovers the position dummies and presents them as a finding. Silhouette is
still computed here, and still displayed, as a diagnostic next to the gap curve
— a disagreement between the two is information, not something to settle
privately. See the `clustering:` block in config/settings.yaml for the numbers.

**Missing values are never zero-filled.** `src/models/trainer.py:prepare_data`
does `nan_to_num(X, nan=0.0)`, which is harmless for trees — zero is just
another split point — and poisonous here. After standardisation a filled zero
becomes an extreme z, k-means duly isolates those rows, and you get a cluster of
missingness that the naming code below will then give a confident English name
to. So columns too null to trust are dropped and the drop is recorded, and what
survives is imputed with the *fit-set* median, persisted, and replayed from the
artifact at assign time. Recomputing a median on the rows being assigned would
make the transform a function of the data it is applied to, which is the same
class of mistake as fitting a blend weight on the model's own training data.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from src.features.definitions import get_definition
from src.utils.config import get_config

#: Bumped when the artifact schema changes shape. The app refuses an artifact it
#: does not recognise rather than reading fields that have moved.
CLUSTER_VERSION = 1

#: Defaults for every `clustering:` key, so a settings.yaml written before this
#: block existed loads the app instead of raising a KeyError inside a tab.
DEFAULTS = {
    "seed": 42,
    "k_min": 2,
    "k_max": 8,
    "gap_reference_draws": 20,
    "gap_sample_rows": 8000,
    "silhouette_sample_rows": 8000,
    "max_null_rate": 0.05,
    "max_abs_corr": 0.90,
    "min_cluster_rows": 50,
    "explore_max_rows": 40000,
}


def settings() -> dict:
    """The `clustering:` config block, with every missing key defaulted."""
    cfg = get_config().get("clustering") or {}
    return {**DEFAULTS, **cfg}


# ── Feature pruning ──────────────────────────────────────────────────────────

def prune_features(
    df: pl.DataFrame,
    candidates: list[str],
    null_rates: dict[str, float] | None,
    max_null_rate: float,
    max_abs_corr: float,
) -> tuple[list[str], list[dict]]:
    """Survivors in priority order, plus one `{col, reason}` per drop.

    `candidates` is ordered by how much the feature is wanted; the correlation
    pass walks that order and keeps the earlier of any duplicated pair, so the
    priority list is also the tie-break.

    Three gates, in order:

    1. **Null rate**, measured on the training run that produced the model, so
       clustering and the model agree about what is missing. `train_null_rates`
       omits any column the trainer excludes — `snap_pct_filled` among them,
       which is 0% null and very much wanted — so an absent key falls back to
       measuring the fit rows rather than to a pessimistic default that would
       drop exactly the column the fallback exists to save.
    2. **Zero variance** on the fit rows. A constant column contributes nothing
       to a distance and makes the scaler divide by zero.
    3. **Binary flags.** A 0/1 column standardises to two spikes about a
       standard deviation apart with nothing in between, which is a ready-made
       split plane, and k-means will take it in preference to any graded
       structure in the rest of the space. Measured here: with `is_dome` left
       in, three of the eight bet-shape groups came back named after the
       stadium roof, and the roof is not a kind of bet. The information is not
       lost — the flags are still there to describe a group with, and they are
       what `measure` reports on. They just do not get to define one.
    4. **Correlation**, on |Spearman| rather than Pearson. These columns are
       heavy tailed — a handful of thirty-carry games — and Pearson understates
       how duplicated a pair like carries and rushing yards really is.
    """
    null_rates = null_rates or {}
    present = [c for c in candidates if c in df.columns]
    dropped = [{"col": c, "reason": "not in features.parquet"}
               for c in candidates if c not in df.columns]

    kept: list[str] = []
    for col in present:
        rate = null_rates.get(col)
        source = "training run"
        if rate is None:
            rate = float(df[col].null_count() / max(df.height, 1))
            source = "measured on the fit rows (absent from train_null_rates)"
        if rate > max_null_rate:
            dropped.append({
                "col": col,
                "reason": f"null rate {rate:.3f} > {max_null_rate} ({source})",
            })
            continue
        kept.append(col)

    survivors: list[str] = []
    for col in kept:
        s = df[col].drop_nulls()
        if s.len() == 0 or float(s.std() or 0.0) == 0.0:
            dropped.append({"col": col, "reason": "no variance on the fit rows"})
            continue
        distinct = s.n_unique()
        if distinct <= 2:
            dropped.append({
                "col": col,
                "reason": f"binary ({distinct} distinct values); a flag "
                          f"standardises into a split plane and would define "
                          f"groups instead of describing them",
            })
            continue
        survivors.append(col)

    if not survivors:
        return survivors, dropped

    ranked = np.column_stack([
        _rankdata(df[c].fill_null(strategy="mean").to_numpy().astype(np.float64))
        for c in survivors
    ])
    final: list[str] = []
    for i, col in enumerate(survivors):
        clash = None
        for j, keeper in enumerate(final):
            rho = _corr(ranked[:, i], ranked[:, survivors.index(keeper)])
            if abs(rho) > max_abs_corr:
                clash = (keeper, rho)
                break
        if clash:
            dropped.append({
                "col": col,
                "reason": f"|rho| {abs(clash[1]):.2f} with {clash[0]}",
            })
            continue
        final.append(col)
    return final, dropped


def _rankdata(x: np.ndarray) -> np.ndarray:
    """Average ranks, so Spearman handles the many ties in share columns."""
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x), dtype=np.float64)
    ranks[order] = np.arange(1, len(x) + 1, dtype=np.float64)
    sx = x[order]
    i = 0
    while i < len(sx):
        j = i
        while j + 1 < len(sx) and sx[j + 1] == sx[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = ranks[order[i:j + 1]].mean()
        i = j + 1
    return ranks


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    sa, sb = a.std(), b.std()
    if sa == 0 or sb == 0:
        return 0.0
    return float(((a - a.mean()) * (b - b.mean())).mean() / (sa * sb))


# ── Transform, impute, scale ─────────────────────────────────────────────────

def fit_transforms(df: pl.DataFrame, features: list[str]) -> dict[str, str]:
    """Which columns get `log1p` before scaling, decided from the data.

    Counts and yardages are heavily right skewed, and standardising them without
    a variance-stabilising step lets a few thirty-carry games dominate every
    Euclidean distance in the space. Shares and flags already live on 0-1 and are
    left alone. The rule is measured, not listed: reaching past 1 means a count,
    which is why `is_high_usage` and `player_target_share_avg_5g` come out
    untransformed without either being named here.

    Yardage columns need the signed variant. A five-game rushing average can be
    negative, and a plain `log1p` rule quietly skips every column that ever goes
    below zero — which is exactly the set of heavy-tailed yardage columns the
    transform exists for.
    """
    out = {}
    for col in features:
        s = df[col].drop_nulls()
        if not s.len():
            out[col] = "none"
            continue
        lo = float(s.min())
        hi = float(s.quantile(0.99) or 0.0)
        if hi <= 1.0:
            out[col] = "none"
        else:
            out[col] = "log1p" if lo >= 0.0 else "signed_log1p"
    return out


def fit_impute(df: pl.DataFrame, features: list[str]) -> dict[str, float]:
    """Fit-set median per column. Persisted, and replayed at assign time."""
    out = {}
    for col in features:
        s = df[col].drop_nulls()
        out[col] = float(s.median()) if s.len() else 0.0
    return out


def build_matrix(
    df: pl.DataFrame,
    features: list[str],
    transforms: dict[str, str],
    impute: dict[str, float],
) -> np.ndarray:
    """Raw frame to a float64 matrix: impute with stored values, then transform.

    Deliberately does not call `np.nan_to_num`. Anything still missing here was
    missing from `impute` too, which means the artifact and the frame disagree
    about the feature set — a loud failure is the right outcome.
    """
    cols = []
    for col in features:
        filled = df[col].cast(pl.Float64).fill_null(impute.get(col, 0.0))
        x = filled.to_numpy().astype(np.float64)
        how = transforms.get(col)
        if how == "log1p":
            x = np.log1p(np.clip(x, 0.0, None))
        elif how == "signed_log1p":
            x = np.sign(x) * np.log1p(np.abs(x))
        cols.append(x)
    X = np.column_stack(cols) if cols else np.empty((df.height, 0))
    if not np.isfinite(X).all():
        bad = [features[i] for i in np.where(~np.isfinite(X).all(axis=0))[0]]
        raise ValueError(f"non-finite values survived imputation in: {bad}")
    return X


def fit_scaler(X: np.ndarray) -> dict:
    """Mean and scale from the fit rows only, persisted as plain lists."""
    mean = X.mean(axis=0)
    scale = X.std(axis=0)
    scale[scale == 0] = 1.0
    return {"mean": mean.tolist(), "scale": scale.tolist()}


def apply_scaler(X: np.ndarray, scaler: dict) -> np.ndarray:
    return (X - np.asarray(scaler["mean"])) / np.asarray(scaler["scale"])


# ── Selecting k ──────────────────────────────────────────────────────────────

def _kmeans(Xz: np.ndarray, k: int, seed: int):
    from sklearn.cluster import KMeans
    return KMeans(n_clusters=k, n_init=10, random_state=seed).fit(Xz)


def _subsample(Xz: np.ndarray, n: int, seed: int) -> np.ndarray:
    if Xz.shape[0] <= n:
        return Xz
    rng = np.random.default_rng(seed)
    return Xz[rng.choice(Xz.shape[0], n, replace=False)]


def gap_statistic(
    Xz: np.ndarray, k_values: list[int], draws: int, sample_rows: int, seed: int,
) -> list[dict]:
    """Tibshirani's gap: log dispersion against uniform noise of the same shape.

    The reference is drawn over the bounding box of the data, so it carries the
    same ranges and none of the structure. The gap is how much better k-means
    does on the real thing than on noise; where it stops growing is where the
    structure runs out.

    Both this and the data fit run on the same subsample, so the two log
    dispersions are comparable.
    """
    Xs = _subsample(Xz, sample_rows, seed)
    lo, hi = Xs.min(axis=0), Xs.max(axis=0)
    rng = np.random.default_rng(seed)
    out = []
    for k in k_values:
        log_wk = float(np.log(max(_kmeans(Xs, k, seed).inertia_, 1e-12)))
        refs = []
        for b in range(draws):
            R = rng.uniform(lo, hi, size=Xs.shape)
            refs.append(np.log(max(_kmeans(R, k, seed + b).inertia_, 1e-12)))
        refs = np.asarray(refs)
        out.append({
            "k": int(k),
            "log_wk": log_wk,
            "gap": float(refs.mean() - log_wk),
            # The sqrt(1 + 1/B) inflation is Tibshirani's: the reference mean is
            # itself estimated, and the 1-SE rule needs that accounted for.
            "gap_se": float(refs.std(ddof=1) * np.sqrt(1.0 + 1.0 / draws)),
        })
    return out


def silhouette_curve(
    Xz: np.ndarray, k_values: list[int], sample_rows: int, seed: int, repeats: int = 5,
) -> list[dict]:
    """Mean silhouette and its sampling error. A diagnostic, never the chooser.

    Reported so that a disagreement with the gap statistic is visible on screen.
    Silhouette on this data prefers the coarsest possible split — see the module
    docstring — which is exactly the answer that looks rigorous and tells you
    nothing you did not already know from the position column.
    """
    from sklearn.metrics import silhouette_score
    out = []
    for k in k_values:
        scores = []
        for r in range(repeats):
            Xs = _subsample(Xz, sample_rows, seed + r)
            labels = _kmeans(Xs, k, seed).labels_
            if len(np.unique(labels)) < 2:
                continue
            scores.append(silhouette_score(Xs, labels))
        if scores:
            out.append({
                "k": int(k),
                "silhouette": float(np.mean(scores)),
                "silhouette_se": float(np.std(scores, ddof=1) / np.sqrt(len(scores)))
                if len(scores) > 1 else 0.0,
            })
    return out


def split_half_ari(Xz: np.ndarray, k_values: list[int], sample_rows: int,
                   seed: int) -> list[dict]:
    """Do two halves of the data agree about the grouping?

    Low agreement means k is describing the sample rather than the league. On
    the current feature set this sits at .95-.99 everywhere and separates
    nothing, which is itself worth showing — it is the reason stability was not
    used to choose k either.
    """
    from sklearn.metrics import adjusted_rand_score
    rng = np.random.default_rng(seed)
    Xs = _subsample(Xz, sample_rows * 2, seed)
    idx = rng.permutation(Xs.shape[0])
    a, b = Xs[idx[::2]], Xs[idx[1::2]]
    out = []
    for k in k_values:
        ma, mb = _kmeans(a, k, seed), _kmeans(b, k, seed)
        # Score both models on the same rows; agreement is about the partition,
        # not about which arbitrary integer each half assigned to it.
        out.append({
            "k": int(k),
            "split_half_ari": float(adjusted_rand_score(
                ma.predict(Xs), mb.predict(Xs))),
        })
    return out


def choose_k(
    selection: list[dict],
    sizes_by_k: dict[int, list[int]],
    min_cluster_rows: int,
) -> tuple[int, bool, str]:
    """Smallest k whose gap is within one standard error of the next one's.

    Returns `(k, unresolved, reason)`. `unresolved` is true when the rule never
    fires inside the range — the gap is still climbing at `k_max` and the elbow
    is somewhere we do not allow. That case takes the largest gap and says so,
    on screen as well as in the artifact, because a criterion that did not
    resolve is a finding about the data and not a detail to absorb quietly.

    A k whose smallest group falls below `min_cluster_rows` is rejected before
    the rule runs, for the same reason `rank_economics.MIN_BETS` exists: a group
    that small cannot resolve its own sign, and every number this tab reports
    about it would be noise wearing a decimal point.
    """
    viable = sorted([row for row in selection
                     if min(sizes_by_k.get(row["k"], [0])) >= min_cluster_rows],
                    key=lambda r: r["k"])
    rejected = [r["k"] for r in selection if r not in viable]

    if not viable:
        row = max(selection, key=lambda r: r["gap"])
        return (row["k"], True,
                f"every k in range produced a group under {min_cluster_rows} "
                f"rows; took the largest gap")

    if len(viable) == 1:
        # Not the same situation as an unresolved criterion, and saying so
        # matters: the rule did not fail to settle, it never had two candidates
        # to choose between, because every other k split off a group too small
        # to measure anything about.
        only = viable[0]
        return (only["k"], False,
                f"only k={only['k']} kept every group above {min_cluster_rows} "
                f"rows; k={rejected} each split off a group too small to measure")

    for cur, nxt in zip(viable, viable[1:]):
        if cur["gap"] >= nxt["gap"] - nxt["gap_se"]:
            return (cur["k"], False,
                    f"gap 1-SE rule: gap({cur['k']})={cur['gap']:.3f} clears "
                    f"gap({nxt['k']})-se={nxt['gap'] - nxt['gap_se']:.3f}")

    best = max(viable, key=lambda r: r["gap"])
    return (best["k"], True,
            f"gap still rising at k={viable[-1]['k']}, the largest k that keeps "
            f"every group measurable; the elbow is outside the range we allow, "
            f"so this is the biggest gap available and not a settled k")


def merge_selection(*curves: list[dict]) -> list[dict]:
    """Join the gap / silhouette / stability curves on k for the artifact."""
    by_k: dict[int, dict] = {}
    for curve in curves:
        for row in curve:
            by_k.setdefault(row["k"], {"k": row["k"]}).update(row)
    return [by_k[k] for k in sorted(by_k)]


# ── Fitting and assigning ────────────────────────────────────────────────────

def fit_stratum(Xz: np.ndarray, k: int, seed: int) -> dict:
    km = _kmeans(Xz, k, seed)
    labels = km.labels_
    centroids = km.cluster_centers_
    dist = np.linalg.norm(Xz - centroids[labels], axis=1)
    return {
        "centroids": centroids.tolist(),
        "labels": labels,
        "sizes": [int((labels == c).sum()) for c in range(k)],
        "inertia": float(km.inertia_),
        # How far a row normally sits from its own centroid. Reporting seasons
        # beyond this are rows the fitted roles do not describe, and the share of
        # them is how centroid drift becomes visible instead of silent.
        "outlier_distance_p95": float(np.percentile(dist, 95)),
    }


def space(artifact: dict, stratum: str) -> tuple[list[str], dict, dict, dict]:
    """The (features, transforms, impute, scaler) one stratum was fitted in.

    Lens A gives each position its own space — see the fit loop in
    `archetypes.py` — while Lens B has a single stratum and keeps one at the top
    level. Reading through here means the assign path cannot pick a different
    space from the fit path, which is the drift that
    `test_cluster_assignment_reproduces_the_persisted_sizes` exists to catch.
    """
    s = artifact["strata"][stratum]
    return (
        s.get("features", artifact.get("features")),
        s.get("transforms", artifact.get("transforms")),
        s.get("impute", artifact.get("impute")),
        s.get("scaler", artifact.get("scaler")),
    )


def embed(df: pl.DataFrame, artifact: dict, stratum: str) -> np.ndarray:
    """Rows into the standardised space one stratum was fitted in."""
    features, transforms, impute, scaler = space(artifact, stratum)
    return apply_scaler(build_matrix(df, features, transforms, impute), scaler)


def assign(Xz: np.ndarray, centroids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Nearest centroid and the distance to it. Pure numpy, on purpose.

    The app renders without importing sklearn, and the artifact is not tied to
    the sklearn version that produced it. Nineteen thousand rows against eight
    centroids in twenty dimensions is a few milliseconds.
    """
    centroids = np.asarray(centroids, dtype=np.float64)
    if Xz.shape[0] == 0:
        return np.empty(0, dtype=int), np.empty(0)
    d = np.linalg.norm(Xz[:, None, :] - centroids[None, :, :], axis=2)
    ids = d.argmin(axis=1)
    return ids.astype(int), d[np.arange(len(ids)), ids]


# ── Naming ───────────────────────────────────────────────────────────────────

#: The naming vocabulary, keyed on FEATURE rather than on cluster id.
#:
#: You cannot derive the English words "goal-line" from a float, so some human
#: mapping is unavoidable here. What matters is what it hangs off. A table keyed
#: on cluster id ("cluster 2 is the goal-line back") is a lie waiting for the
#: first refit that changes k or adds a season, and it fails silently, because
#: the name still renders. Keyed on the feature that defines the group, it is a
#: glossary of the feature set: it only goes stale when features change, and it
#: survives every refit of k. Anything without an entry still gets named, from
#: `get_definition`, and is marked `generated` so it reads as second-class.
LABEL_WORDS = {
    "player_gl_carries_avg_5g": "goal-line",
    "player_i5_touches_avg_5g": "inside-5",
    "player_i5_touch_share_avg_5g": "inside-5",
    "player_i10_touch_share_avg_5g": "inside-10",
    "player_rz_carries_avg_5g": "red-zone running",
    "player_rz_targets_avg_5g": "red-zone",
    "player_endzone_td_rate_avg_5g": "end-zone finishing",
    "player_td_market_share_avg_5g": "primary scoring",
    "player_carries_avg_5g": "workhorse",
    "player_rush_share_avg_5g": "carry-share",
    "player_targets_avg_5g": "high-target",
    "player_target_share_avg_5g": "volume",
    "player_receptions_avg_5g": "possession",
    "player_air_yards_share_avg_5g": "deep",
    "player_wopr_avg_5g": "focal",
    "player_rushing_yards_avg_5g": "ground-yardage",
    "player_receiving_yards_avg_5g": "yardage",
    "player_receiving_yac_per_rec_avg_5g": "after-catch",
    "player_od_touch_share_avg_5g": "script-opening",
    "player_h1_touch_share_avg_5g": "first-half",
    "snap_pct_filled": "every-down",
    "is_starter": "starting",
    "is_high_usage": "heavily-used",
    # Lens B: the shape of a bet rather than the shape of a player.
    "model_edge": "big-disagreement",
    "log_dec": "long-price",
    "market_prob": "short-price",
    "prob_calibrated": "high-confidence",
    "rank_frac": "top-of-board",
    "implied_team_total": "high-scoring",
    "total_line": "high-total",
    "abs_spread": "lopsided",
    "is_dome": "indoor",
}

POSITION_NOUN = {"RB": "back", "WR": "WR", "TE": "TE", "QB": "QB"}


def name_clusters(centroids: np.ndarray, features: list[str],
                  noun: str, top_n: int = 3) -> list[dict]:
    """Turn each centroid into a name plus the evidence for that name.

    The evidence is not optional decoration. Centroids are already in z-space,
    so the features a group departs furthest from average on *are* what makes it
    a group, and rendering them beside the label is what lets a reader catch a
    name that is wrong. A cluster called "goal-line back" whose receipt reads
    "target share +1.8, goal-line carries -0.2" is caught in a second; the same
    cluster with only a name on it is believed.
    """
    centroids = np.asarray(centroids, dtype=np.float64)
    out, used = [], {}
    for cid, row in enumerate(centroids):
        order = np.argsort(-np.abs(row))[:top_n]
        top = [{"col": features[i], "z": float(row[i]),
                "definition": get_definition(features[i])} for i in order]

        positive = [t for t in top if t["z"] > 0 and t["col"] in LABEL_WORDS]
        if positive:
            word = LABEL_WORDS[positive[0]["col"]]
            label, source = f"{word} {noun}", "vocabulary"
        else:
            lead = top[0]
            direction = "high" if lead["z"] > 0 else "low"
            label = f"{noun} — {lead['definition']} {direction}"
            source = "generated"

        # A collision means the vocabulary is under-specified for this feature
        # set. Say which second feature separates them rather than appending an
        # index, which would hide the fact that two groups look alike.
        if label in used and len(top) > 1:
            extra = LABEL_WORDS.get(top[1]["col"])
            label = f"{label}, {extra}" if extra else f"{label}, {top[1]['definition']}"
        used[label] = True

        out.append({"id": cid, "label": label, "label_source": source,
                    "top_features": top})
    return out


def profile(top_features: list[dict]) -> str:
    """The one-line receipt shown next to every label, in sigma units."""
    return " · ".join(f"{t['definition']} {t['z']:+.1f}σ" for t in top_features)


# ── Display projection ───────────────────────────────────────────────────────

def fit_pca_display(Xz: np.ndarray, seed: int) -> dict:
    """Two components, for drawing only — never for clustering.

    The whole value of this tab is that a centroid maps back to a named feature
    and becomes readable words. A rotation destroys that at exactly the point
    where naming happens, so the model sees the original axes and only the
    picture sees these.
    """
    from sklearn.decomposition import PCA
    p = PCA(n_components=2, random_state=seed).fit(_subsample(Xz, 20000, seed))
    return {
        "components": p.components_.tolist(),
        "explained_variance_ratio": p.explained_variance_ratio_.tolist(),
    }


def project(Xz: np.ndarray, pca: dict) -> np.ndarray:
    return Xz @ np.asarray(pca["components"]).T


# ── Persistence ──────────────────────────────────────────────────────────────

def save(artifact: dict, path: Path) -> None:
    """Atomic write, matching src/ingest/odds_history.py — a half-written
    artifact that still parses is worse than one that is missing."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(artifact, indent=2))
    tmp.replace(path)


def load(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        art = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if art.get("version") != CLUSTER_VERSION:
        return None
    return art


def today() -> str:
    return date.today().isoformat()
