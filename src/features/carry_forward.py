"""Project player form onto games that have not been played yet.

`weekly_stats` only contains rows for completed games, so every player-keyed
rolling feature joins to null for an upcoming week. `prepare_data` then turns
those nulls into 0.0 and the model scores rows that look nothing like its
training data — which is exactly how Week 1 2026 ended up implying 7.6 touchdown
scorers per game against a true rate of ~4.3.

The fix is to carry each player's most recent rolling state forward. Real rows
always win, so the projection dissolves week by week as games are played.
"""
from __future__ import annotations

import polars as pl

from src.utils.config import get_config

# Full slate incl. postseason; extra weeks are harmless (they anti-join away).
_PREDICT_WEEKS = list(range(1, 23))


def build_with_carry_forward(
    df: pl.DataFrame,
    exprs_for_lag,
    key_cols: tuple[str, ...] = ("player_id", "season", "week"),
    spine: pl.DataFrame | None = None,
    zero_cols: list[str] | None = None,
) -> pl.DataFrame:
    """Build shifted rolling features, then project them into the predict season.

    Args:
        df: weekly stats, one row per player-week, already sorted by player/time.
        exprs_for_lag: callable(lag:int) -> list[pl.Expr]. lag=1 excludes the
            current game (correct for training rows, no leakage); lag=0 includes
            it (the state a player carries into their *next*, unplayed game).
    """
    if spine is not None and zero_cols:
        # weekly_stats only has a row for a week the player actually played, so
        # non-nullness downstream encodes "was active this week". Densifying
        # against the candidate pool makes absence mean a real zero instead.
        from src.features.spine import densify
        df = densify(df, spine, zero_cols=zero_cols)

    shifted = exprs_for_lag(1)
    if not shifted:
        return pl.DataFrame(
            schema={"player_id": pl.Utf8, "season": pl.Int64, "week": pl.Int64}
        )
    feat_names = [e.meta.output_name() for e in shifted]

    real = df.with_columns(shifted).select(list(key_cols) + feat_names)

    projected = _project(df, exprs_for_lag(0), feat_names, real, key_cols)
    if projected is None:
        return real
    return pl.concat([real, projected], how="vertical_relaxed")


def _project(df, unshifted_exprs, feat_names, real, key_cols) -> pl.DataFrame | None:
    cfg = get_config()
    predict_season = cfg["seasons"].get("predict_season")
    if predict_season is None:
        return None

    latest = (
        df.with_columns(unshifted_exprs)
        .sort(["player_id", "season", "week"])
        .group_by("player_id")
        .last()
        .select(["player_id"] + feat_names)
    )
    if latest.height == 0:
        return None

    weeks = pl.DataFrame({"week": _PREDICT_WEEKS}).with_columns(
        pl.col("week").cast(df.schema["week"])
    )
    stubs = (
        latest.join(weeks, how="cross")
        .with_columns(pl.lit(predict_season).cast(df.schema["season"]).alias("season"))
        .select(list(key_cols) + feat_names)
        .join(real.select(list(key_cols)), on=list(key_cols), how="anti")
    )
    print(f"    carried {stubs.height:,} player-weeks forward into {predict_season}")
    return stubs
