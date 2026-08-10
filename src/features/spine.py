"""A dense player-week spine, so feature *absence* stops carrying information.

The usage frames built from play-by-play (red zone, goal line, opening drive,
first half) only contain a row for a player-week when that player actually had
that kind of usage. Left-joined onto candidates, the result is that
`player_i10_touches_szn_avg IS NOT NULL` means "this player touched the ball
inside the 10 **in the game we are predicting**".

Measured on 2023-2025, that single bit was worth a 15.5x lift in P(scored)
(0.513 non-null vs 0.033 null) before any value was read. The rolling *values*
were correctly lagged the whole time — it was the row's existence that leaked,
which is why it survived every shift(1) audit.

Densifying against the candidate pool fixes it. Candidates come from rosters and
the schedule, so membership is known before kickoff: a player-week appearing in
the spine reveals nothing about what happened in that game. Usage columns fill
to 0, meaning "was available and did not get a goal-line touch" — which is
exactly what the model should learn from.
"""
from __future__ import annotations

import polars as pl

SPINE_KEYS = ["player_id", "season", "week"]


def player_week_spine(candidates: pl.DataFrame) -> pl.DataFrame:
    """Every player-week we ever score, one row each."""
    return (
        candidates.select(SPINE_KEYS)
        .unique()
        .sort(SPINE_KEYS)
    )


def densify(sparse: pl.DataFrame, spine: pl.DataFrame, zero_cols: list[str],
            keep_cols: list[str] | None = None) -> pl.DataFrame:
    """Expand a sparse usage frame onto the spine, filling absence with 0.

    Must be called BEFORE any shift/rolling: the point is that the rolling
    window sees a continuous series of real zeros rather than skipping the weeks
    a player was available but unused.
    """
    cols = SPINE_KEYS + [c for c in (keep_cols or []) if c in sparse.columns] + \
           [c for c in zero_cols if c in sparse.columns]
    sparse = sparse.select([c for c in dict.fromkeys(cols)])

    out = spine.join(sparse, on=SPINE_KEYS, how="left")
    present = [c for c in zero_cols if c in out.columns]
    out = out.with_columns([pl.col(c).fill_null(0) for c in present])
    return out.sort(SPINE_KEYS)
