import json
import pickle
import numpy as np
import polars as pl
from scipy.optimize import minimize
from src.utils.config import get_config
from src.utils.paths import get_path
from src.evaluation.metrics import evaluate_model, print_metrics, top_k_accuracy
from src.evaluation.plots import plot_calibration, plot_feature_importance
from src.models.registry import get_model, ensure_registered
from src.models.calibration import TemperatureScaler


def get_feature_cols(df: pl.DataFrame) -> list[str]:
    """Get feature columns (exclude identifiers and target)."""
    exclude = {
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
        "recent_td_rate", "implied_player_tds",
        "team_team_scored_first_flag_rate_5g",
        "team_team_scored_first_flag_rate_szn",
        # Always null during training (only available for predict season)
        "sbook_first_td_implied", "sbook_anytime_td_implied",
        "sbook_first_td_rank", "sbook_anytime_td_rank",
        "depth_chart_rank",
        # Measured at kickoff, so never known when we actually predict. They were
        # 34% null in training and 100% null at predict time — a guaranteed
        # train/serve skew. The derived is_cold / is_windy / is_dome flags come
        # from the schedule and ARE available ahead of time; use those instead.
        "temp", "wind",
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
      - Is target=1 (for training data integrity)
      - Has recent usage (carries/targets/receptions > 0)
      - Is a starter (is_starter == 1)
      - Has snap share > 0
      - Is on depth chart at rank 1-2 (depth_chart_rank feature)
    """
    is_defst = df.select(
        pl.col("position_DEFST").fill_null(0) == 1
        if "position_DEFST" in df.columns
        else pl.lit(False)
    ).to_series()

    is_target = (
        (df["target"] == 1)
        if "target" in df.columns
        else pl.Series([False] * df.shape[0])
    )

    has_usage = (
        df.select(
            (pl.col("player_carries_avg_5g").fill_null(0) > 0)
            | (pl.col("player_targets_avg_5g").fill_null(0) > 0)
            | (pl.col("player_receptions_avg_5g").fill_null(0) > 0)
        ).to_series()
        if "player_carries_avg_5g" in df.columns
        else pl.Series([True] * df.shape[0])
    )

    is_starter = (
        df.select(pl.col("is_starter").fill_null(0) == 1).to_series()
        if "is_starter" in df.columns
        else pl.Series([False] * df.shape[0])
    )

    has_snaps = (
        df.select(pl.col("snap_pct").fill_null(0) > 0).to_series()
        if "snap_pct" in df.columns
        else pl.Series([False] * df.shape[0])
    )

    on_depth_chart = (
        df.select(pl.col("depth_chart_rank").fill_null(99) <= 2).to_series()
        if "depth_chart_rank" in df.columns
        else pl.Series([False] * df.shape[0])
    )

    keep = is_defst | is_target | has_usage | is_starter | has_snaps | on_depth_chart
    return df.filter(keep)


def _optimize_ensemble_weights(val_probs_dict: dict[str, np.ndarray],
                               val_df: pl.DataFrame) -> dict[str, float]:
    """Find optimal ensemble weights on validation set using top-1 accuracy."""
    names = list(val_probs_dict.keys())
    probs_list = [val_probs_dict[n] for n in names]

    def neg_top1(weights):
        w = np.array(weights)
        w = w / w.sum()
        blended = sum(w_i * p for w_i, p in zip(w, probs_list))
        eval_df = val_df.with_columns(pl.Series("prob", blended))
        return -top_k_accuracy(eval_df, k=1)

    n = len(probs_list)
    bounds = [(0.0, 1.0)] * n
    result = minimize(
        neg_top1,
        x0=[1.0 / n] * n,
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": 500},
    )
    weights = np.array(result.x)
    weights = np.maximum(weights, 0.0)
    weights = weights / weights.sum()
    return dict(zip(names, weights))


def train_all(target_type: str = None):
    ensure_registered()
    cfg = get_config()
    if target_type is None:
        target_type = cfg["target"]["type"]
    seed = cfg["model"]["seed"]
    active_models = cfg["models"]["active"]

    df = pl.read_parquet(get_path("processed", target_type) / "features.parquet")
    df = df.filter(pl.col("target").is_not_null())
    feature_cols = get_feature_cols(df)
    print(f"Features: {len(feature_cols)} columns")

    # Time-series split
    train_df = df.filter(pl.col("season") <= cfg["splits"]["train_end"])
    val_df = df.filter(pl.col("season") == cfg["splits"]["val_season"])
    test_df = df.filter(pl.col("season") == cfg["splits"]["test_season"])

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

    model_dir = get_path("models", target_type)
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
        model.fit(X_train, y_train, X_val, y_val, mcfg)

        # Predict
        val_probs = model.predict_proba(X_val)
        test_probs = model.predict_proba(X_test)
        val_probs_dict[name] = val_probs
        test_probs_dict[name] = test_probs

        # Evaluate raw
        val_eval = val_df.with_columns(pl.Series("prob", val_probs))
        test_eval = test_df.with_columns(pl.Series("prob", test_probs))
        val_m = evaluate_model(val_eval, f"{name} (val)")
        test_m = evaluate_model(test_eval, f"{name} (test)")
        print_metrics(val_m)
        print_metrics(test_m)
        all_metrics.extend([val_m, test_m])

        # Calibrate
        calibrator = TemperatureScaler()
        calibrator.fit(val_probs, y_val)

        cal_val_probs = calibrator.calibrate(val_probs)
        cal_test_probs = calibrator.calibrate(test_probs)
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

    # --- Record the training feature distribution for train/serve skew checks ---
    null_rates = {
        c: float(train_df[c].is_null().mean()) for c in feature_cols
        if c in train_df.columns
    }
    with open(model_dir / "train_null_rates.pkl", "wb") as f:
        pickle.dump(null_rates, f)

    # Save metrics
    output_dir = get_path("output", target_type)
    with open(output_dir / "metrics.json", "w") as f:
        json.dump(all_metrics, f, indent=2)

    print(f"\nModels saved to {model_dir}")
    print(f"Metrics saved to {output_dir / 'metrics.json'}")

    return all_metrics
