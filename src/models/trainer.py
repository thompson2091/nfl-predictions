import json
import pickle
from pathlib import Path
import numpy as np
import polars as pl
from scipy.optimize import minimize
from src.utils.config import get_config, production_model
from src.utils.paths import get_path
from src.evaluation.metrics import evaluate_model, print_metrics, top_k_accuracy
from src.evaluation.plots import plot_calibration, plot_feature_importance
from src.models.registry import get_model, ensure_registered
from src.models.calibration import IsotonicCalibrator



def inject_noise_features(df: "pl.DataFrame") -> "pl.DataFrame":
    """Add N columns of pure noise, if config asks for them. A CONTROL ONLY.

    Phase 3e concluded "every family carries something" from the fact that
    removing any one of 33 families made Top-3 worse, 33 times out of 33. The
    control for that was seed-only reruns, which are symmetric in sign — so the
    asymmetry looked like information loss.

    Then adding families made Top-3 worse too: 42 defensive columns cost 1.24pp,
    12 giveaway columns cost 1.50pp, against ~1.30pp for removing an arbitrary
    family. Adding and removing cannot both destroy information. Something about
    changing the feature set at all is worth roughly a point of Top-3, and 3e
    cannot tell that apart from what it claimed to measure.

    These columns are deterministic in the row index and independent of the
    target, so they carry exactly nothing. If Top-3 falls by about the same
    point when they are added, 3e's conclusion is an artifact of retraining
    rather than a fact about the features.

    Deterministic and applied wherever features are loaded, so training and
    scoring see identical values — noise that differs between them would
    measure train/serve skew instead.
    """
    import numpy as np
    import polars as pl

    n = int((get_config().get("models") or {}).get("inject_noise_features") or 0)
    if n <= 0:
        return df
    rng = np.random.default_rng(20260813)
    return df.with_columns([
        pl.Series(f"_noise_{i}", rng.standard_normal(df.height))
        for i in range(n)
    ])


def excluded_families(cfg: dict | None = None) -> set[str]:
    """Columns dropped because their builder family is switched off.

    Ablation is by family, not by column, because columns within a family are
    correlated by construction — `player_carries_avg_3g` and `_5g` cover for
    each other, so dropping either alone measures nothing while dropping the
    family measures something. The map from column to builder is
    `diagnostics/feature_families.json`, recorded by
    `scripts/26_feature_families.py`.

    Driven from config so an ablation is an ordinary overlay and goes through
    the same screen, gate and ledger as any other change.
    """
    cfg = cfg if cfg is not None else get_config()
    families = list((cfg.get("models") or {}).get("exclude_feature_families") or [])
    if not families:
        return set()

    path = Path(__file__).resolve().parents[2] / "diagnostics" / "feature_families.json"
    if not path.exists():
        raise FileNotFoundError(
            f"exclude_feature_families is set to {families} but {path} does not "
            "exist. Run `python scripts/26_feature_families.py` to record which "
            "builder produced each column. Guessing from column names would "
            "drop the wrong ones silently.")
    mapping = json.loads(path.read_text())["families"]
    unknown = [f for f in families if f not in mapping]
    if unknown:
        raise ValueError(
            f"unknown feature families {unknown}; known families are "
            f"{sorted(mapping)}. A typo here would ablate nothing and report "
            "the result as 'this family does not matter'.")
    return {c for f in families for c in mapping[f]}


def get_feature_cols(df: pl.DataFrame) -> list[str]:
    """Get feature columns (exclude identifiers and target)."""
    exclude = set(excluded_families()) | {
        "game_id", "season", "week", "player_id", "player_name",
        "team", "opponent", "home_team", "away_team",
        "target", "game_type", "prob",
        # Situational features: kept in features.parquet for AI display,
        # excluded from model training (context-only, not predictive signals)
        "is_new_team", "is_revenge_game", "is_role_change",
        "weeks_since_last_game", "career_seasons",
        "rest_advantage", "is_post_bye", "is_season_opener",
        # Exact duplicates of other features
        "week_right", "is_divisional_gf", "snap_pct_filled", "is_dome_right",
        # `season_right` is a join artifact identical to `season` in 100% of
        # rows, and `season` is excluded above precisely because the calendar
        # year is not a predictor. Worse than a redundant column: every predict
        # row carries a value no training row ever held (2026 against a 2025
        # maximum), and a tree cannot extrapolate — it drops the whole season
        # into whichever leaf the previous one occupied. `week_right` was
        # caught; its sibling was not.
        "season_right",
        "recent_td_rate", "implied_player_tds",
        "team_team_scored_first_flag_rate_5g",
        "team_team_scored_first_flag_rate_szn",
        # Always null during training (only available for predict season)
        "sbook_first_td_implied", "sbook_anytime_td_implied",
        "sbook_first_td_rank", "sbook_anytime_td_rank",
        "depth_chart_rank",
        # Measured at kickoff, so never known when we actually predict. They were
        # 34% null in training and 100% null at predict time — a guaranteed
        # train/serve skew.
        "temp", "wind",
        # And so are these two, which this comment used to recommend as the
        # safe alternative. `is_cold` is `(temp < 40).fill_null(False)` and
        # `is_windy` the same on `wind` — derived from the very columns above,
        # with the nulls silently reading as "not cold". Measured: 11-15% of
        # training rows are cold, and 0.0% of 2026 rows are, because every 2026
        # temperature is null. Even in played seasons they are wrong for the
        # 33-62% of games with no recorded temperature.
        #
        # `is_dome` is genuinely from the schedule's `roof` and stays.
        # Pre-kickoff forecasts are the honest replacement — see
        # scripts/28_weather.py and src/features/weather_features.py.
        "is_cold", "is_windy",
    }
    return [c for c in df.columns
            if c not in exclude
            and df[c].dtype in (pl.Float64, pl.Float32, pl.Int8, pl.Int16,
                                pl.Int32, pl.Int64, pl.UInt8, pl.UInt16,
                                pl.UInt32, pl.UInt64)]


def prepare_data(df: pl.DataFrame, feature_cols: list[str]):
    """Convert to numpy, fill NaN."""
    for col in feature_cols:
        if col not in df.columns:
            df = df.with_columns(pl.lit(0.0).alias(col))
    X = df.select(feature_cols).to_numpy().astype(np.float64)
    X = np.nan_to_num(X, nan=0.0)
    y = df["target"].to_numpy().astype(np.float64)
    return X, y


def _filter_low_activity(df: pl.DataFrame) -> pl.DataFrame:
    """Remove candidates unlikely to score: no usage, not on depth chart.

    Keep a player if ANY of these are true:
      - Is DEF/ST
      - Has recent usage (carries/targets/receptions > 0)
      - Is a starter (is_starter == 1)
      - Has snap share > 0
      - Is on depth chart at rank 1-2 (depth_chart_rank feature)

    Every criterion above is knowable before kickoff. That is not optional.
    This function once also kept any row with `target == 1` — "for training
    data integrity" — which made the surviving population a function of the
    outcome. The damage was not subtle: it left 863 training rows with zero
    carries, zero targets, zero receptions, no snaps and no starter role, of
    which 100% scored, because the only way into that corner of the data was
    to score. The model duly learned that no usage at all predicts a
    touchdown, and priced backup tight ends at 6-13% against a true rate near
    2%. It also silently skewed train against serve: a future week has no
    `target` column, so the clause could only ever fire in training and
    backtests, never in production.

    The thresholds come from `candidate_filter` in config so Phase 3f can sweep
    them. The defaults reproduce the hardcoded behaviour exactly — a strictly
    positive usage/snap threshold and depth-chart rank 1-2 — because the trade
    this filter makes is not obviously tuned: every candidate removed is one
    fewer distractor above the true scorer, and every *scorer* removed is a
    guaranteed miss under the fixed denominator. Both directions have a cost and
    neither has been measured.
    """
    cfg = get_config().get("candidate_filter") or {}
    min_usage = float(cfg.get("min_usage", 0.0))
    min_snap_pct = float(cfg.get("min_snap_pct", 0.0))
    max_depth_rank = int(cfg.get("max_depth_chart_rank", 2))

    is_defst = df.select(
        pl.col("position_DEFST").fill_null(0) == 1
        if "position_DEFST" in df.columns and cfg.get("keep_defst", True)
        else pl.lit(False)
    ).to_series()

    has_usage = (
        df.select(
            (pl.col("player_carries_avg_5g").fill_null(0) > min_usage)
            | (pl.col("player_targets_avg_5g").fill_null(0) > min_usage)
            | (pl.col("player_receptions_avg_5g").fill_null(0) > min_usage)
        ).to_series()
        if "player_carries_avg_5g" in df.columns
        else pl.Series([True] * df.shape[0])
    )

    is_starter = (
        df.select(pl.col("is_starter").fill_null(0) == 1).to_series()
        if "is_starter" in df.columns and cfg.get("keep_starters", True)
        else pl.Series([False] * df.shape[0])
    )

    has_snaps = (
        df.select(pl.col("snap_pct").fill_null(0) > min_snap_pct).to_series()
        if "snap_pct" in df.columns
        else pl.Series([False] * df.shape[0])
    )

    on_depth_chart = (
        df.select(pl.col("depth_chart_rank").fill_null(99) <= max_depth_rank).to_series()
        if "depth_chart_rank" in df.columns and max_depth_rank > 0
        else pl.Series([False] * df.shape[0])
    )

    keep = is_defst | has_usage | is_starter | has_snaps | on_depth_chart
    return df.filter(keep)


def _priced_only(df: pl.DataFrame, target_type: str) -> pl.DataFrame:
    """Rows a sportsbook priced — the population production actually shows.

    Falls back to the full frame when no archive covers it, since a fit on the
    wrong population still beats no fit.
    """
    try:
        from src.ingest.odds_history import load_graded_history
        graded = load_graded_history(target_type)
    except Exception:
        graded = None
    if graded is None or graded.height == 0:
        return df
    priced = graded.select(["game_id", "player_id"]).unique()
    out = df.join(priced, on=["game_id", "player_id"], how="inner")
    return out if out.height >= 1000 else df


def _serving_population(val_df: pl.DataFrame, probs: np.ndarray,
                        y: np.ndarray, target_type: str):
    """Restrict a calibration fit to the players a sportsbook actually priced.

    Production only ever scores priced players. They are a far stronger group
    than the full candidate pool, so a calibrator fit over every candidate is
    tuned for rows the app never shows. Falls back to the whole pool when the
    odds archive cannot cover the validation season, since a calibrator fit on
    the wrong population still beats no calibrator at all.
    """
    try:
        from src.ingest.odds_history import load_graded_history
        graded = load_graded_history(target_type)
    except Exception:
        graded = None
    if graded is None or graded.height == 0:
        print("  Calibration: no odds archive — fitting on all candidates")
        return probs, y

    priced = graded.select(["game_id", "player_id"]).unique().with_columns(
        pl.lit(True).alias("_priced")
    )
    mask = (
        val_df.select(["game_id", "player_id"])
        .join(priced, on=["game_id", "player_id"], how="left")["_priced"]
        .fill_null(False)
        .to_numpy()
    )
    if mask.sum() < IsotonicCalibrator.MIN_ROWS:
        print(f"  Calibration: only {int(mask.sum())} priced validation rows — "
              "fitting on all candidates")
        return probs, y
    print(f"  Calibration: fitting on {int(mask.sum()):,} priced validation rows "
          f"of {len(mask):,} candidates")
    return probs[mask], y[mask]


def _optimize_ensemble_weights(val_probs_dict: dict[str, np.ndarray],
                               val_df: pl.DataFrame) -> dict[str, float]:
    """Weight the ensemble by validation log loss.

    This used to minimise negative top-1 accuracy with L-BFGS-B, which never
    ran. Top-1 is a step function of the weights — nudging a weight by 1e-8
    cannot change which player ranks first in a game — so the numerical
    gradient was exactly zero, the optimiser returned at iteration 0, and the
    "learned weights" printed at every training run were the equal-weight
    starting point echoed back unchanged.

    Log loss is smooth in the weights, is a proper scoring rule, and is
    measured over every candidate rather than one row per game, so it is far
    less noisy than top-1 (~9,700 rows against 283 games). Fitting a
    three-weight simplex to 283 coarse outcomes is how you overfit a
    validation season; fitting it to the full likelihood is not.

    The result is kept only if it genuinely beats equal weighting.
    """
    names = list(val_probs_dict.keys())
    P = np.column_stack([val_probs_dict[n] for n in names])
    y = val_df["target"].to_numpy().astype(float)

    def nll(w: np.ndarray) -> float:
        w = np.maximum(np.asarray(w, dtype=float), 0.0)
        total = w.sum()
        if total <= 0:
            return 1e9
        p = np.clip(P @ (w / total), 1e-7, 1 - 1e-7)
        return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))

    n = len(names)
    equal = np.full(n, 1.0 / n)
    result = minimize(
        nll, x0=equal, method="L-BFGS-B",
        bounds=[(0.0, 1.0)] * n, options={"maxiter": 500},
    )
    weights = np.maximum(np.asarray(result.x, dtype=float), 0.0)

    if weights.sum() <= 0 or nll(weights) >= nll(equal):
        print("  Ensemble: fitted weights did not beat equal weighting — keeping equal")
        weights = equal
    weights = weights / weights.sum()

    # Shrink toward equal weighting by how much of the improvement is signal.
    #
    # Three free weights fitted to one validation season will happily collapse
    # onto whichever model won that season — a corner solution that stops being
    # an ensemble at all and throws away the variance reduction that motivated
    # it. Same signal-to-noise weighting the rank calibration uses: compare the
    # per-row log-loss gain against its own standard error, so a gain that is
    # large relative to its noise is kept almost whole and a marginal one is
    # pulled back toward equal.
    def row_loss(w: np.ndarray) -> np.ndarray:
        p = np.clip(P @ (w / w.sum()), 1e-7, 1 - 1e-7)
        return -(y * np.log(p) + (1 - y) * np.log(1 - p))

    diff = row_loss(equal) - row_loss(weights)
    se = diff.std(ddof=1) / np.sqrt(len(diff)) if len(diff) > 1 else 0.0
    d = float(diff.mean())
    lam = (d ** 2) / (d ** 2 + se ** 2) if (d > 0 and se > 0) else (1.0 if d > 0 else 0.0)
    weights = lam * weights + (1.0 - lam) * equal
    weights = weights / weights.sum()
    print(f"  Ensemble: gain {d:.5f} +/- {se:.5f} per row -> shrunk {lam:.0%} "
          f"toward the fit")

    def top1(w: np.ndarray) -> float:
        return top_k_accuracy(val_df.with_columns(pl.Series("prob", P @ w)), k=1)

    print(f"  Ensemble: log loss {nll(equal):.5f} (equal) -> {nll(weights):.5f} (fitted), "
          f"val top-1 {top1(equal):.1%} -> {top1(weights):.1%}")
    return dict(zip(names, weights))


def _fit_rank_correction(df, train_seasons, splits, feature_cols, model_dir,
                         target_type: str, active_models: list[str]) -> None:
    """Fit the per-rank correction, but only if a serving path would read it.

    The model's error depends on where a player sits in its own ranking, which
    no feature encodes and the per-game level shift cannot fix — that moves a
    whole game together. Fitted across several seasons and shrunk by how
    consistent each rank's bias is, because a single season taught the top ranks
    a bias that reversed the next year.

    It is disabled in both markets today, for two different reasons documented
    on `rank_calibration.would_be_applied`. Fitting it regardless was not
    harmful, but it wrote a `rank_calibration.json` into both model directories
    and announced "N of 12 ranks kept a meaningful correction" on every retrain,
    which reads exactly like a component that is doing something.
    """
    from src.models.rank_calibration import would_be_applied

    if not would_be_applied(target_type, model_dir):
        stale = model_dir / "rank_calibration.json"
        note = ""
        if stale.exists():
            stale.unlink()
            note = "  (removed the artifact a previous run left behind)"
        reason = ("first_td never reaches it — predict() normalises within the "
                  "game and returns" if target_type == "first_td" else
                  "the joint model is active, which disables it")
        print(f"\nRank calibration not fitted: {reason}. "
              f"See src/models/rank_calibration.py.{note}")
        return

    try:
        from src.models.rank_calibration import fit_rank_calibration, save as save_rank
        prod = production_model(target_type)
        rank_src = df.filter(
            pl.col("season").is_in(train_seasons + [splits["val_season"]])
            & pl.col("target").is_not_null()
        )
        rank_src = _filter_low_activity(rank_src)
        Xr, _ = prepare_data(rank_src, feature_cols)

        # Fit on the same quantity this correction is applied to. It used to be
        # fitted on raw `predict_proba` and applied downstream of both the
        # calibrator and the level step, so it corrected a rank-conditional bias
        # measured on numbers nobody publishes.
        #
        # Scored through `scoring.score`, the entry point production uses,
        # rather than by loading one pickle — a pickle cannot express
        # `prod == "ensemble"`, and `get_model("ensemble")` raising was turned
        # by the bare except below into a one-line "skipped" that left the
        # previous model's correction on disk.
        from src.models.scoring import score as score_probs
        rank_probs = score_probs(prod, Xr, feature_cols, model_dir,
                                 calibrate=True, active_models=active_models)
        rank_src = rank_src.with_columns(pl.Series("prob", rank_probs))

        from src.models.joint import apply_joint, load_team_rate
        _tm = load_team_rate(model_dir / "team_td_rate.json")
        if _tm is not None:
            rank_src = apply_joint(rank_src, rank_src, _tm,
                                   score_col="prob", out_col="prob")

        rank_calib = fit_rank_calibration(rank_src, "prob", season_col="season")
        save_rank(rank_calib, model_dir / "rank_calibration.json")
        kept = [d for d in rank_calib["diagnostics"] if abs(d["delta"]) > 0.02]
        print(f"\nRank calibration: fitted over {len(rank_calib['seasons_used'])} "
              f"seasons, {len(kept)} of {len(rank_calib['diagnostics'])} ranks kept "
              f"a meaningful correction -> {model_dir / 'rank_calibration.json'}")
    except Exception as e:
        # A failed fit must not leave the previous model's correction behind.
        # Applying a stale per-rank shift is measurably worse than applying
        # none: on 2025 it dropped the bet card from 19.4% to 14.0%.
        stale = model_dir / "rank_calibration.json"
        removed = ""
        if stale.exists():
            stale.unlink()
            removed = (f"  REMOVED the previous {stale.name}: applying a stale "
                       "rank correction is worse than applying none")
        print(f"\nRank calibration skipped: {e}{removed}")


def train_all(target_type: str = None, splits: dict | None = None,
              model_dir=None, output_dir=None):
    """Train, calibrate and fit every artifact for one market.

    `splits`, `model_dir` and `output_dir` exist so a walk-forward evaluation
    can run the whole recipe on an earlier slice of history without touching
    the artifacts production is serving. Default to the config and the standard
    paths, so ordinary training is unchanged.
    """
    ensure_registered()
    cfg = get_config()
    if target_type is None:
        target_type = cfg["target"]["type"]
    splits = dict(cfg["splits"]) if splits is None else dict(splits)
    seed = cfg["model"]["seed"]
    active_models = cfg["models"]["active"]

    df = pl.read_parquet(get_path("processed", target_type) / "features.parquet")
    df = inject_noise_features(df)
    df = df.filter(pl.col("target").is_not_null())
    feature_cols = get_feature_cols(df)
    print(f"Features: {len(feature_cols)} columns")

    # Time-series split
    train_df = df.filter(pl.col("season") <= splits["train_end"])
    val_df = df.filter(pl.col("season") == splits["val_season"])
    test_df = df.filter(pl.col("season") == splits["test_season"])

    # Filter low-activity candidates consistently across all splits
    train_before = train_df.shape[0]
    train_df = _filter_low_activity(train_df)
    val_before = val_df.shape[0]
    val_df = _filter_low_activity(val_df)
    test_before = test_df.shape[0]
    test_df = _filter_low_activity(test_df)
    print(f"Train: {train_before:,} -> {train_df.shape[0]:,} after filtering")
    print(f"Val: {val_before:,} -> {val_df.shape[0]:,}  Test: {test_before:,} -> {test_df.shape[0]:,}")

    X_train, y_train = prepare_data(train_df, feature_cols)
    X_val, y_val = prepare_data(val_df, feature_cols)
    X_test, y_test = prepare_data(test_df, feature_cols)

    model_dir = Path(model_dir) if model_dir else get_path("models", target_type)
    model_dir.mkdir(parents=True, exist_ok=True)
    all_metrics = []
    val_probs_dict = {}
    test_probs_dict = {}

    # Merge seed into each model's config
    def model_config(name: str) -> dict:
        base = cfg["model"].get(name, cfg["model"].get(
            {"lr": "logistic", "lgbm": "lgbm", "xgb": "xgb"}.get(name, name), {}
        ))
        if isinstance(base, dict):
            return {**base, "seed": seed}
        return {"seed": seed}

    # --- Train each registered model ---
    for name in active_models:
        print(f"\nTraining {name}...")
        model_cls = get_model(name)
        model = model_cls()
        model.feature_names = feature_cols

        mcfg = model_config(name)
        # Most models treat every row as independent. A model that declares
        # `needs_groups` is trained on a within-group likelihood instead and
        # cannot be fitted without knowing which rows compete with which — so
        # this is a hard requirement, not an optional extra. Passing the groups
        # to everything would mean changing every wrapper's signature to accept
        # an argument it ignores.
        if getattr(model_cls, "needs_groups", False):
            from src.models.ranker import group_ids
            model.fit(X_train, y_train, X_val, y_val, mcfg,
                      groups=(group_ids(train_df, target_type),
                              group_ids(val_df, target_type)))
        else:
            model.fit(X_train, y_train, X_val, y_val, mcfg)

        # Predict
        val_probs = model.predict_proba(X_val)
        test_probs = model.predict_proba(X_test)

        # Evaluate raw
        val_eval = val_df.with_columns(pl.Series("prob", val_probs))
        test_eval = test_df.with_columns(pl.Series("prob", test_probs))
        val_m = evaluate_model(val_eval, f"{name} (val)")
        test_m = evaluate_model(test_eval, f"{name} (test)")
        print_metrics(val_m)
        print_metrics(test_m)
        all_metrics.extend([val_m, test_m])

        # Calibrate, on the population we actually serve.
        #
        # Two changes from the old single-temperature fit over every candidate.
        # First, isotonic: the measured error is not a uniform stretch but a
        # shape — near-perfect below 0.10, 5-8 points under between 0.20 and
        # 0.45, over above 0.45 — and no single temperature can pull the middle
        # up without pushing the tails further out. Second, the fit population:
        # the app only ever scores players a sportsbook priced, a narrower and
        # much stronger group than the full candidate pool, so calibrating
        # against every candidate tunes for rows production never sees.
        calibrator = IsotonicCalibrator()
        fit_p, fit_y = _serving_population(val_df, val_probs, y_val, target_type)
        calibrator.fit(fit_p, fit_y)

        cal_val_probs = calibrator.calibrate(val_probs)
        cal_test_probs = calibrator.calibrate(test_probs)

        # Weight the ensemble on calibrated probabilities, because that is what
        # production combines: predict.py loads each model's calibrator, applies
        # it, and only then takes the weighted average. Fitting the weights on
        # raw probabilities optimises a blend nobody serves, and it penalises
        # whichever model happens to be worst calibrated rather than whichever
        # is least informative.
        val_probs_dict[name] = cal_val_probs
        test_probs_dict[name] = cal_test_probs
        cal_val_eval = val_df.with_columns(pl.Series("prob", cal_val_probs))
        cal_test_eval = test_df.with_columns(pl.Series("prob", cal_test_probs))
        cal_val_m = evaluate_model(cal_val_eval, f"{name}-calibrated (val)")
        cal_test_m = evaluate_model(cal_test_eval, f"{name}-calibrated (test)")
        print_metrics(cal_val_m)
        print_metrics(cal_test_m)
        all_metrics.extend([cal_val_m, cal_test_m])

        # Plots
        plot_calibration(y_test, test_probs, name)
        importances = model.feature_importances()
        if importances:
            plot_feature_importance(importances, name)

        # Save model + calibrator
        model.save(model_dir / f"{name}.pkl")
        calibrator.save(model_dir / f"{name}_calibrator.pkl")

    # --- Ensemble ---
    if len(active_models) > 1:
        print("\nOptimizing ensemble weights on validation set...")
        weights = _optimize_ensemble_weights(val_probs_dict, val_df)
        print(f"  Learned weights: {weights}")

        val_probs_ens = sum(w * val_probs_dict[n] for n, w in weights.items())
        test_probs_ens = sum(w * test_probs_dict[n] for n, w in weights.items())

        val_eval_ens = val_df.with_columns(pl.Series("prob", val_probs_ens))
        test_eval_ens = test_df.with_columns(pl.Series("prob", test_probs_ens))
        val_m = evaluate_model(val_eval_ens, "Ensemble (val)")
        test_m = evaluate_model(test_eval_ens, "Ensemble (test)")
        print_metrics(val_m)
        print_metrics(test_m)
        all_metrics.extend([val_m, test_m])

        with open(model_dir / "ensemble_weights.pkl", "wb") as f:
            pickle.dump(weights, f)

    # Save feature cols
    with open(model_dir / "feature_cols.pkl", "wb") as f:
        pickle.dump(feature_cols, f)

    # --- Fit the empirical scorer-rate prior on the training seasons ---
    from src.models.market_prior import fit_scorer_rate_prior, save_prior
    train_seasons = sorted(train_df["season"].unique().to_list())
    prior = fit_scorer_rate_prior(df, train_seasons)
    save_prior(prior, model_dir / "scorer_rate_prior.json")
    print(f"\nScorer-rate prior: {prior['mean_scorers_per_game']:.2f} scorers/game "
          f"over {prior['n_games']:,} games (RMSE {prior['rmse']:.2f}) "
          f"-> {model_dir / 'scorer_rate_prior.json'}")

    # --- Fit the team touchdown rate that sets the level in the joint model ---
    # Predictions are published as 1 - exp(-lambda * share): this supplies the
    # lambda, the model above supplies the share. The scorer-rate prior is kept
    # because the market de-vig still normalises against it.
    from src.models.joint import fit_team_rate, save_team_rate
    try:
        team_model = fit_team_rate(df, train_seasons)
        save_team_rate(team_model, model_dir / "team_td_rate.json")
        print(f"Team TD rate: {team_model['mean_team_tds']:.2f} TDs/team-game over "
              f"{team_model['n_team_games']:,} team-games (RMSE "
              f"{team_model['rmse']:.2f}) -> {model_dir / 'team_td_rate.json'}")
    except ValueError as e:
        team_model = None
        print(f"Team TD rate NOT fitted ({e}) — prediction falls back to the "
              "per-player level calibration.")

    # --- Fit the count -> probability conversion the joint model publishes ---
    # Poisson thinning understated the top of the board by 5-7 points because a
    # lead back's goal-line carries are not independent arrivals. Fit the
    # dispersion, and a level term that absorbs the scoring environment drifting
    # away from the seasons the team rate was fitted on. Fitted on train+val
    # only, like the calibrator, so the held-out season stays held out.
    if team_model is not None:
        try:
            from src.models.joint import (apply_joint, fit_conversion,
                                          save_conversion)
            conv_src = _filter_low_activity(df.filter(
                pl.col("season").is_in(train_seasons + [splits["val_season"]])
                & pl.col("target").is_not_null()
            ))
            Xc, _ = prepare_data(conv_src, feature_cols)
            prod_name = production_model(target_type)
            from src.models.scoring import score as _score
            conv_src = conv_src.with_columns(
                pl.Series("_s", _score(prod_name, Xc, feature_cols, model_dir))
            )
            conv_src = apply_joint(conv_src, conv_src, team_model,
                                   score_col="_s", out_col="_p")
            conv_src = conv_src.with_columns(
                (pl.col("team_lambda") * pl.col("share")).alias("_mu")
            )
            # Fit on the players we publish for. Over the full candidate pool
            # thousands of near-zero rows, where every conversion agrees,
            # swamp the top of the board where they differ by 5-7 points: the
            # dispersion came out 3.05 on all candidates against 1.15 on the
            # priced ones, i.e. almost back to the Poisson it was correcting.
            conv_src = _priced_only(conv_src, target_type)
            conv = fit_conversion(conv_src, "_mu")
            save_conversion(conv, model_dir / "td_conversion.json")
            print(f"TD conversion: level {conv['level']}, dispersion "
                  f"{conv['dispersion']} (log loss {conv['poisson_log_loss']:.5f} "
                  f"Poisson -> {conv['log_loss']:.5f}) -> "
                  f"{model_dir / 'td_conversion.json'}")
        except Exception as e:
            print(f"TD conversion NOT fitted ({e}) — falling back to Poisson.")

    # --- Fit the positional (per-rank) correction ---
    _fit_rank_correction(df, train_seasons, splits, feature_cols, model_dir,
                         target_type, active_models)


    # --- Record the training feature distribution for train/serve skew checks ---
    null_rates = {
        c: float(train_df[c].is_null().mean()) for c in feature_cols
        if c in train_df.columns
    }
    with open(model_dir / "train_null_rates.pkl", "wb") as f:
        pickle.dump(null_rates, f)

    # Save metrics
    output_dir = Path(output_dir) if output_dir else get_path("output", target_type)
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_dir / "metrics.json", "w") as f:
        json.dump(all_metrics, f, indent=2)

    print(f"\nModels saved to {model_dir}")
    print(f"Metrics saved to {output_dir / 'metrics.json'}")

    return all_metrics
