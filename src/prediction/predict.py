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

    if model_name == "ensemble":
        weights_path = model_dir / "ensemble_weights.pkl"
        if not weights_path.exists():
            return []
        with open(weights_path, "rb") as f:
            weights = pickle.load(f)
        raw_probs = np.zeros(X_test.shape[0])
        for name, w in weights.items():
            sub = get_model(name).load(model_dir / f"{name}.pkl")
            sub.feature_names = feature_cols
            raw_probs += w * sub.predict_proba(X_test)
    else:
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


def _anchor_to_market(result: pl.DataFrame, week_df: pl.DataFrame,
                      model_dir, cfg: dict, season: int, week: int) -> pl.DataFrame:
    """Level-calibrate anytime-TD probabilities, then blend with the market."""
    from src.models.market_prior import load_prior, expected_scorers
    from src.prediction.blend import (
        calibrate_level, devig_market, blend, fit_blend_weight,
        load_blend_weight, save_blend_weight,
    )

    bcfg = cfg.get("blend", {})
    if not bcfg.get("enabled", True):
        return result.with_columns(pl.col("raw_prob").alias("probability"))

    prior = load_prior(model_dir / "scorer_rate_prior.json")
    if prior is None:
        print("  No scorer-rate prior found — run `make train` to fit one. "
              "Falling back to raw probabilities.")
        return result.with_columns(pl.col("raw_prob").alias("probability"))

    # Expected scorers for each game, from its betting lines.
    games = week_df.group_by("game_id").agg([
        pl.col("total_line").first(), pl.col("spread_line").first(),
    ])
    expected = expected_scorers(prior, games)
    print(f"  Expected scorers/game (fitted prior): "
          f"{expected['expected_scorers'].mean():.2f}")

    result = calibrate_level(result, "raw_prob", expected, out_col="prob_calibrated")

    # De-vigged market prices, if any are cached for this slate.
    market = _load_market(week_df, expected, season, week)
    if market is not None and market.height > 0:
        result = result.with_columns(
            _norm_name_expr("player_name").alias("player_name_norm")
        ).join(
            market.select(["game_id", "player_name_norm", "market_prob"]),
            on=["game_id", "player_name_norm"], how="left",
        )
    else:
        result = result.with_columns(pl.lit(None, dtype=pl.Float64).alias("market_prob"))
        print("  No cached sportsbook prices — publishing model-only probabilities.")

    # Weight: fitted from graded history when we have enough, else the declared
    # bootstrap from config.
    from src.ingest.odds_history import load_graded_history
    weight_path = model_dir / "blend_weight.json"
    graded = load_graded_history("anytime_td")
    fitted = fit_blend_weight(graded, min_rows=bcfg.get("min_history_rows", 500))
    if fitted is not None:
        save_blend_weight(fitted, weight_path)
        print(f"  Blend weight FITTED on {fitted['n_rows']:,} graded player-games: "
              f"market={fitted['market_weight']:.2f}")
    weight = load_blend_weight(weight_path, bcfg.get("bootstrap_market_weight"))
    if weight.get("source") == "bootstrap":
        n = 0 if graded is None else graded.height
        print(f"  Blend weight BOOTSTRAP (market={weight['market_weight']:.2f}) — "
              f"{n:,}/{bcfg.get('min_history_rows', 500)} graded rows archived so far.")

    result = blend(result, "prob_calibrated", "market_prob", weight,
                   out_col="probability")
    return result


def _norm_name_expr(col: str) -> pl.Expr:
    e = pl.col(col).str.to_lowercase().str.strip_chars()
    for suffix in [" jr.", " sr.", " ii", " iii", " iv", " jr", " sr"]:
        e = e.str.replace(rf"{suffix}$", "")
    return e.str.replace_all(r"\.", "").str.strip_chars()


def _load_market(week_df: pl.DataFrame, expected: pl.DataFrame,
                 season: int, week: int) -> pl.DataFrame | None:
    """De-vigged market probabilities for this slate.

    Reads the odds cache directly rather than relying on `sbook_*` columns baked
    into features.parquet — prices move every week, and rebuilding the full
    feature history just to refresh them is both slow and easy to forget.
    """
    from src.prediction.blend import devig_market

    market = _market_from_cache(season, week)
    if market is None and "sbook_anytime_td_implied" in week_df.columns:
        market = (
            week_df.select(["game_id", "player_name", "sbook_anytime_td_implied"])
            .filter(pl.col("sbook_anytime_td_implied") > 0)
            .rename({"sbook_anytime_td_implied": "implied_prob"})
            .with_columns(_norm_name_expr("player_name").alias("player_name_norm"))
        )
    if market is None or market.height == 0:
        return None
    return devig_market(market, expected)


def _market_from_cache(season: int, week: int) -> pl.DataFrame | None:
    """Anytime-TD prices from the odds cache, keyed to this week's game_ids."""
    try:
        from src.ingest.odds_api import load_cached_odds
        from src.features.odds_features import TEAM_ABBREV
    except Exception:
        return None

    odds = load_cached_odds()
    if not odds:
        return None

    schedules = pl.read_parquet(get_path("raw") / "schedules.parquet")
    sched = schedules.filter(
        (pl.col("season") == season) & (pl.col("week") == week)
    ).select(["game_id", "home_team", "away_team"])
    key = {(h, a): g for g, h, a in zip(
        sched["game_id"], sched["home_team"], sched["away_team"])}

    rows = []
    for game in odds.values():
        gid = key.get((TEAM_ABBREV.get(game.get("home_team", "")),
                       TEAM_ABBREV.get(game.get("away_team", ""))))
        if gid is None:
            continue
        for p in game.get("anytime_td", []):
            rows.append({
                "game_id": gid,
                "player_name_norm": p["player"],
                # The American price is what you're actually paid — bets.py needs
                # it for EV and Kelly, so it must survive this hop.
                "odds": p.get("odds"),
                "implied_prob": p["implied_prob"],
                "fair_prob": p.get("fair_prob"),
            })
    if not rows:
        return None
    return pl.DataFrame(rows).with_columns(
        _norm_name_expr("player_name_norm").alias("player_name_norm")
    )


def check_feature_skew(week_df: pl.DataFrame, feature_cols: list[str],
                       model_dir, threshold: float = 0.35) -> list[str]:
    """Warn when predict-time features are far more null than they were in training.

    This is the check that would have caught the 2025 weekly-stats gap: a whole
    block of player_* features silently went 100% null at predict time while the
    model had been trained on populated values, and `prepare_data` turned them
    into 0.0 without complaint. Probabilities inflated ~2.7x with no error raised.
    """
    path = model_dir / "train_null_rates.pkl"
    if not path.exists():
        return []
    with open(path, "rb") as f:
        train_nulls = pickle.load(f)

    degraded = []
    for c in feature_cols:
        if c not in week_df.columns or c not in train_nulls:
            continue
        now = float(week_df[c].is_null().mean())
        if now - train_nulls[c] > threshold:
            degraded.append((c, train_nulls[c], now))

    if degraded:
        print(f"\n  !! FEATURE SKEW: {len(degraded)} feature(s) far more null than in training.")
        print("     These become 0.0 and push probabilities off-distribution:")
        for c, was, now in sorted(degraded, key=lambda r: r[2] - r[1], reverse=True)[:15]:
            print(f"       {c:45s} train={was:.2f} -> now={now:.2f}")
        if len(degraded) > 15:
            print(f"       ... and {len(degraded) - 15} more")
    return [c for c, _, _ in degraded]


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

    check_feature_skew(week_df, feature_cols, model_dir)

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
    # For anytime_td: anchor the level to the fitted scorer-rate prior, then
    # blend with the de-vigged market. See src/prediction/blend.py.
    if target_type == "first_td":
        result = result.with_columns(
            (pl.col("raw_prob") / pl.col("raw_prob").sum().over("game_id"))
            .alias("probability")
        )
    else:
        result = _anchor_to_market(result, week_df, model_dir, cfg,
                                   season=season, week=week)

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
