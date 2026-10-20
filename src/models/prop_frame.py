"""What the receptions and yardage models train on: labels and columns.

Shared by scripts/30_receptions.py and scripts/49_yards.py, so the two cannot
drift on either question.
"""
from __future__ import annotations

import polars as pl

#: Market-movement features: null before 2023 and on any board built before
#: the late capture, so in these models they were one season of signal and a
#: train/serve difference. The touchdown models' own lists are separate.
PROP_EXCLUDE = {"mkt_move_pp", "mkt_move_z", "mkt_move_abs_z"}


def labeled(feats: pl.DataFrame, stat: str) -> pl.DataFrame:
    """`feats` with the stat attached, for every player-game he PLAYED.

    A player with a snap and no stat line is a real zero; one with neither
    did not play and has no label. The label used to require a weekly-stats
    row, which dropped the zeros: 12-14% of receiver and back snap-games
    (24% of tight ends), every one an under, so the target ran high. Same
    rule as settlement (`safe_legs.game_logs`, keyed by player id).
    """
    from src.evaluation.safe_legs import game_logs

    logs = (game_logs().select(["season", "week", "player_id", stat])
            .with_columns(pl.col("season").cast(feats["season"].dtype),
                          pl.col("week").cast(feats["week"].dtype)))
    return (feats.join(logs, on=["season", "week", "player_id"], how="inner")
                 .filter(pl.col(stat).is_not_null()))


def feature_cols(df: pl.DataFrame, id_cols: set[str]) -> list[str]:
    """Numeric columns, less identifiers and every excluded column."""
    from src.models.trainer import excluded_columns

    drop = set(id_cols) | excluded_columns() | PROP_EXCLUDE
    return [c for c in df.columns if c not in drop and df[c].dtype.is_numeric()]


def outcomes(stat: str) -> pl.DataFrame:
    """(season, week, player_id, stat) for every player-game played, zeros
    included — what a graded line settles against, as a book settles it."""
    from src.evaluation.safe_legs import game_logs

    return game_logs().select(["season", "week", "player_id", stat])
