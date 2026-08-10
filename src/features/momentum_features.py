"""Player usage momentum/trend features from weekly stats."""
import polars as pl


def build_momentum_features(weekly_stats: pl.DataFrame) -> pl.DataFrame:
    """Build player touch share trend and momentum features.

    Captures whether a player's usage is increasing or decreasing,
    which is a leading indicator for TD scoring beyond the rolling average level.

    Returns one row per (player_id, season, week).
    """
    ws = (
        weekly_stats
        .filter(pl.col("player_id").is_not_null())
        .select([
            "player_id",
            pl.col("season").cast(pl.Int64),
            pl.col("week").cast(pl.Int64),
            pl.col("recent_team").alias("team"),
            pl.col("carries").cast(pl.Float64).fill_null(0.0),
            pl.col("targets").cast(pl.Float64).fill_null(0.0),
        ])
        .sort(["player_id", "season", "week"])
    )

    # Total touches
    ws = ws.with_columns(
        (pl.col("carries") + pl.col("targets")).alias("touches")
    )

    # Team total touches per game (for share calculation)
    team_touches = (
        ws.group_by(["team", "season", "week"])
        .agg(pl.col("touches").sum().alias("team_touches"))
    )

    ws = ws.join(team_touches, on=["team", "season", "week"], how="left")

    ws = ws.with_columns(
        pl.when(pl.col("team_touches") > 0)
        .then(pl.col("touches") / pl.col("team_touches"))
        .otherwise(0.0)
        .alias("touch_share")
    )

    # --- Touch share trend (slope over last 3 games) ---
    # Approximate slope: (latest - earliest) / 2 over a 3-game window
    # Using the difference between current and 2-game-ago value
    ws = ws.with_columns([
        pl.col("touch_share")
        .shift(1)
        .over(["player_id", "season"])
        .alias("_ts_lag1"),
        pl.col("touch_share")
        .shift(2)
        .over(["player_id", "season"])
        .alias("_ts_lag2"),
        pl.col("touch_share")
        .shift(3)
        .over(["player_id", "season"])
        .alias("_ts_lag3"),
    ])

    # Trend: slope approximation using lagged values (no current-week leakage)
    # (lag1 - lag3) / 2 = average change per game over last 3
    ws = ws.with_columns(
        pl.when(pl.col("_ts_lag3").is_not_null())
        .then((pl.col("_ts_lag1") - pl.col("_ts_lag3")) / 2.0)
        .when(pl.col("_ts_lag2").is_not_null())
        .then(pl.col("_ts_lag1") - pl.col("_ts_lag2"))
        .otherwise(pl.lit(None))
        .alias("player_touch_share_trend_3g")
    )

    # --- Touch share delta: last game vs rolling 5g average ---
    ws = ws.with_columns(
        pl.col("touch_share")
        .shift(1)
        .rolling_mean(window_size=5, min_periods=2)
        .over(["player_id", "season"])
        .alias("_ts_avg_5g")
    )

    ws = ws.with_columns(
        pl.when(pl.col("_ts_avg_5g").is_not_null() & pl.col("_ts_lag1").is_not_null())
        .then(pl.col("_ts_lag1") - pl.col("_ts_avg_5g"))
        .otherwise(pl.lit(None))
        .alias("player_touch_share_delta")
    )

    # --- Carries trend (for RBs specifically) ---
    ws = ws.with_columns([
        pl.col("carries")
        .shift(1)
        .over(["player_id", "season"])
        .alias("_car_lag1"),
        pl.col("carries")
        .shift(3)
        .over(["player_id", "season"])
        .alias("_car_lag3"),
    ])

    ws = ws.with_columns(
        pl.when(pl.col("_car_lag3").is_not_null())
        .then((pl.col("_car_lag1") - pl.col("_car_lag3")) / 2.0)
        .otherwise(pl.lit(None))
        .alias("player_carries_trend_3g")
    )

    # --- Targets trend (for pass catchers) ---
    ws = ws.with_columns([
        pl.col("targets")
        .shift(1)
        .over(["player_id", "season"])
        .alias("_tgt_lag1"),
        pl.col("targets")
        .shift(3)
        .over(["player_id", "season"])
        .alias("_tgt_lag3"),
    ])

    ws = ws.with_columns(
        pl.when(pl.col("_tgt_lag3").is_not_null())
        .then((pl.col("_tgt_lag1") - pl.col("_tgt_lag3")) / 2.0)
        .otherwise(pl.lit(None))
        .alias("player_targets_trend_3g")
    )

    return ws.select([
        "player_id", "season", "week",
        "player_touch_share_trend_3g",
        "player_touch_share_delta",
        "player_carries_trend_3g",
        "player_targets_trend_3g",
    ])
