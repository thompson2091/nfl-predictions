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


def as_of_join(df: pl.DataFrame, sparse: pl.DataFrame,
               feature_cols: list[str] | None = None) -> pl.DataFrame:
    """Attach each player's most recent observation from *before* this week.

    `densify` is the right tool for a sparse frame of counts, where absence
    means zero. It is the wrong tool for a rate: a receiver with no Next Gen
    Stats row did not average zero yards of separation, he was not measured.

    The leak is the same one `player_week_spine` was written for, and it was
    left in a family that spine never covered. NGS publishes a player-week row
    only when that player had qualifying receiving activity that week, so a
    plain left join makes `ngs_avg_separation_szn_avg IS NOT NULL` mean "caught
    a pass in the game we are predicting". Measured on the served matrix:

        P(1+ reception | an NGS row exists that week) = 0.9972
        P(1+ reception | no NGS row)                  = 0.1562

    The *values* were correctly lagged the whole time — sorted, shifted,
    partitioned by player — which is why every shift(1) audit passed. It was
    the row's existence that leaked, and on the touchdown targets that bit
    alone was worth a 5.05x lift on anytime and 4.58x on first before any
    number was read.

    An as-of join fixes it structurally rather than by patching values: every
    candidate row receives the most recent observation strictly *earlier* than
    its own week, so existence stops varying with the outcome. A player who has
    never been measured still gets null — that is a fact about his career, known
    before kickoff, not about the game being predicted.

    `allow_exact_matches=False` is the whole guarantee. With exact matches
    allowed, a player whose current week happens to have an NGS row would get
    fresher inputs than one who does not — and whether this week has a row is
    decided by this week's game. The staleness would carry the same bit the
    null did.
    """
    if sparse.height == 0 or df.height == 0:
        return df

    cols = feature_cols or [c for c in sparse.columns if c not in SPINE_KEYS]
    cols = [c for c in cols if c in sparse.columns]
    if not cols:
        return df

    # Weeks are only orderable inside a season; this makes them orderable
    # across seasons too, so the lookup reaches back into the previous one
    # rather than resetting every September.
    t = (pl.col("season").cast(pl.Int64) * 100 + pl.col("week").cast(pl.Int64)).alias("_t")

    left = df.with_columns(t).sort("_t")
    right = (sparse.with_columns(t)
             .select(["player_id", "_t"] + cols)
             .unique(subset=["player_id", "_t"], keep="last")
             .sort("_t"))

    out = left.join_asof(right, on="_t", by="player_id", strategy="backward",
                         allow_exact_matches=False)
    return out.drop("_t")
