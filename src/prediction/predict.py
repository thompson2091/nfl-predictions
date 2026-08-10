import pickle
import numpy as np
import polars as pl
from src.utils.config import get_config
from src.utils.paths import get_path
from src.models.trainer import get_feature_cols, prepare_data, _filter_low_activity
from src.models.registry import get_model, ensure_registered
from src.models.calibration import TemperatureScaler


def _rank_bucket_lines(target_type: str, model_name: str = None):
    """Return rank bucket accuracy breakdown lines."""
    ensure_registered()
    cfg = get_config()
    if model_name is None:
        model_name = cfg["models"]["production"]
    model_dir = get_path("models", target_type)

    df = pl.read_parquet(get_path("processed", target_type) / "features.parquet")
    df = df.filter(pl.col("target").is_not_null())

    feat_cols_path = model_dir / "feature_cols.pkl"
    if not feat_cols_path.exists():
        return []
    with open(feat_cols_path, "rb") as f:
        feature_cols = pickle.load(f)

    test_season = cfg["splits"]["test_season"]
    test_df = df.filter(pl.col("season") == test_season)

    if test_df.shape[0] == 0:
        return []

    X_test, _ = prepare_data(test_df, feature_cols)

    model_cls = get_model(model_name)
    model = model_cls.load(model_dir / f"{model_name}.pkl")
    model.feature_names = feature_cols
    raw_probs = model.predict_proba(X_test)

    eval_df = test_df.with_columns(pl.Series("prob", raw_probs))
    eval_df = eval_df.with_columns(
        pl.col("prob").rank(descending=True, method="ordinal")
        .over("game_id").alias("pred_rank")
    )
    actual = eval_df.filter(pl.col("target") == 1)
    ranks = actual["pred_rank"].to_list()
    n_games = len(ranks)

    buckets = [(1, 1, "1"), (2, 3, "2-3"), (4, 5, "4-5"),
               (6, 10, "6-10"), (11, 20, "11-20"), (21, 9999, "21+")]

    lines = []
    lines.append(f"Model Accuracy — {model_name} Rank Buckets ({test_season} Test, {n_games} games)")
    lines.append(f"{'=' * 40}")
    lines.append(f"{'Rank':<10} {'Count':>6}  {'Pct':>7}  {'Cumul':>7}")
    lines.append(f"{'-' * 40}")

    cumul = 0
    for lo, hi, label in buckets:
        count = sum(1 for r in ranks if lo <= r <= hi)
        pct = count / n_games * 100
        cumul += pct
        lines.append(f"{label:<10} {count:>4}    {pct:5.1f}%   {cumul:5.1f}%")

    lines.append("")
    return lines


def _game_pick_lines(result: pl.DataFrame, top_n: int = 5):
    """Return formatted top-N picks per game as lines."""
    lines = []
    lines.append(f"Week Predictions — Top {top_n} per Game")
    lines.append(f"{'=' * 52}")

    for game_id in sorted(result.select("game_id").unique()["game_id"].to_list()):
        game = result.filter(pl.col("game_id") == game_id)
        label = game["game_label"][0]
        lines.append("")
        lines.append(f"{label}")
        for row in game.head(top_n).iter_rows(named=True):
            pct = row["probability"] * 100
            lines.append(f"  {row['rank']:>2}. {row['player_name']:25s} {row['team']:3s}  {pct:5.1f}%")

    lines.append("")
    return lines


def predict(season: int, week: int, model_name: str = None,
            target_type: str = None) -> pl.DataFrame | None:
    """Generate predictions for a given season/week."""
    ensure_registered()
    cfg = get_config()
    if target_type is None:
        target_type = cfg["target"]["type"]
    if model_name is None:
        model_name = cfg["models"]["production"]

    model_dir = get_path("models", target_type)
    feat_cols_path = model_dir / "feature_cols.pkl"
    if not feat_cols_path.exists():
        print(f"No trained model for target_type={target_type}")
        return None
    with open(feat_cols_path, "rb") as f:
        feature_cols = pickle.load(f)

    df = pl.read_parquet(get_path("processed", target_type) / "features.parquet")
    week_df = df.filter((pl.col("season") == season) & (pl.col("week") == week))

    if week_df.shape[0] == 0:
        print(f"No data for {season} week {week}")
        return None

    # Filter out low-activity candidates (same filter used in training)
    before = week_df.shape[0]
    week_df = _filter_low_activity(week_df)
    if week_df.shape[0] < before:
        print(f"Filtered {before} -> {week_df.shape[0]} candidates (removed low-activity)")

    X, _ = prepare_data(week_df, feature_cols)

    if model_name == "ensemble":
        weights_path = model_dir / "ensemble_weights.pkl"
        if weights_path.exists():
            with open(weights_path, "rb") as f:
                weights = pickle.load(f)
        else:
            active = cfg["models"]["active"]
            weights = {n: 1.0 / len(active) for n in active}

        probs = np.zeros(X.shape[0])
        for name, w in weights.items():
            m = get_model(name).load(model_dir / f"{name}.pkl")
            m.feature_names = feature_cols
            p = m.predict_proba(X)

            cal_path = model_dir / f"{name}_calibrator.pkl"
            if cal_path.exists():
                cal = TemperatureScaler.load(cal_path)
                p = cal.calibrate(p)

            probs += w * p
    else:
        model = get_model(model_name).load(model_dir / f"{model_name}.pkl")
        model.feature_names = feature_cols
        probs = model.predict_proba(X)

        cal_path = model_dir / f"{model_name}_calibrator.pkl"
        if cal_path.exists():
            cal = TemperatureScaler.load(cal_path)
            probs = cal.calibrate(probs)

    id_cols = ["game_id", "player_id", "player_name", "team"]
    result = week_df.select(id_cols).with_columns(pl.Series("raw_prob", probs))

    # For first_td: normalize within game (exactly one scorer, probs sum to 100%)
    # For anytime_td: use calibrated probs directly (independent per-player probabilities)
    if target_type == "first_td":
        result = result.with_columns(
            (pl.col("raw_prob") / pl.col("raw_prob").sum().over("game_id"))
            .alias("probability")
        )
    else:
        result = result.with_columns(
            pl.col("raw_prob").alias("probability")
        )

    result = result.with_columns(
        pl.col("probability")
        .rank(descending=True, method="ordinal")
        .over("game_id")
        .alias("rank")
    )

    result = result.sort(["game_id", "rank"])

    schedules = pl.read_parquet(get_path("raw") / "schedules.parquet")
    game_labels = schedules.select([
        "game_id",
        (pl.col("away_team") + " @ " + pl.col("home_team")).alias("game_label"),
    ])
    result = result.join(game_labels, on="game_id", how="left")

    result = result.select([
        "game_id", "game_label", "player_name", "team",
        "probability", "rank",
    ])

    output_dir = get_path("output", target_type)
    csv_path = output_dir / f"predictions_{season}_week{week}.csv"
    result.write_csv(csv_path)

    report_lines = []
    report_lines.append(f"NFL TD Predictions ({target_type}) — {season} Week {week} (model: {model_name})")
    report_lines.append(f"{'=' * 60}")
    report_lines.append("")

    report_lines.extend(_rank_bucket_lines(target_type, model_name))
    report_lines.extend(_game_pick_lines(result))

    report = "\n".join(report_lines)

    txt_path = output_dir / f"predictions_{season}_week{week}.txt"
    with open(txt_path, "w") as f:
        f.write(report)

    print(report)
    print(f"Saved: {csv_path}")
    print(f"Saved: {txt_path}")

    return result
