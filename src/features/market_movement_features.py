"""What the market did between its opening price and its last pre-kickoff one.

Every other feature family in this project is a summary of on-field events.
This one is not: it is the only input that carries what *other people's money*
did after the week's prices went up, which is information no amount of
play-by-play contains. `docs/DATA_SOURCES.md` has listed it as the top
unexploited input since the odds backfill landed.

Three things make it harder than differencing two numbers.

**The archive's second quote sits about an hour before kickoff.** Measured on
`odds_books.book_last_update` — the API's own market clock, and the only clock
that means the same thing live and backfilled — the two quote times per
player-game cluster at ~72h before kickoff and ~0.3-1.2h before. There is
nothing in between. So a board built on Saturday has the open and nothing else,
and this family is null on it. It is populated only on a board rebuilt after a
late capture, which is why `weekly_odds.sh` now rebuilds after the closing
snapshot. A null here is honest: it says the market has not moved yet, because
it has not.

**The move's level drifts by season**, and a tree cannot extrapolate to a level
it never saw — the same failure that made `season_right` a trap. Mean move on
anytime TD: -0.18pp in 2023, -0.44pp in 2024, -0.83pp in 2025, -0.47pp so far
in 2026. So the feature served is a **within-week z-score**, which is free of
the level by construction, with the raw move kept beside it for readability.

**The de-vigged columns are not usable here.** `fair_prob` and `overround` in
`odds_history.parquet` are 100% null for 2025 and 2026 and 50-72% null before
that, so a de-vigged move would be absent in exactly the seasons being served.
The vigged price is differenced instead, and `line_movement` already keys the
join on `regions` so a change in *which books are quoting* cannot masquerade as
the market moving.

Built on `src.evaluation.clv.line_movement` rather than re-deriving the pair:
that function already resolves live-vs-backfilled game ids, drops in-play
closes (`odds_history.drop_in_play`), and joins open to close at the same line
and the same book set. A second definition of "the open and the close" is
exactly the kind of copy that drifts.
"""
from __future__ import annotations

import polars as pl

#: A week needs at least this many priced players before a cross-sectional
#: z-score means anything. Below it the week's own mean and spread are noise,
#: and dividing by them manufactures large values out of nothing.
MIN_WEEK_ROWS = 20


def build_market_movement_features(target_type: str = "anytime_td"
                                   ) -> pl.DataFrame:
    """Per player-week: how far the market moved, against how far it usually does.

    Returns a frame keyed on (season, week, player_name_norm) carrying:

        mkt_move_pp    the raw open->close change in vigged implied probability
        mkt_move_z     that move, centered and scaled within its own week
        mkt_move_abs_z the same magnitude without direction

    Rows are absent, not zero, for a player-week with no closing price. The
    distinction matters on a board built before the closing capture, where
    every row is legitimately unmoved.
    """
    from src.evaluation.clv import line_movement

    mv = line_movement(target_type)
    if mv is None or mv.height == 0:
        return pl.DataFrame(schema={
            "season": pl.Int64, "week": pl.Int64, "game_id": pl.Utf8,
            "player_name_norm": pl.Utf8,
            "mkt_move_pp": pl.Float64, "mkt_move_z": pl.Float64,
            "mkt_move_abs_z": pl.Float64,
        })

    mv = mv.select(["season", "week", "game_id", "player_name_norm",
                    (pl.col("move") * 100).alias("mkt_move_pp")])

    # Center and scale within the week. `std` over one row is null and over a
    # constant week is zero; both are guarded, because a zero denominator is
    # how a feature family arrives full of infinities that `prepare_data`
    # quietly turns into something finite and wrong.
    n = pl.len().over(["season", "week"])
    mu = pl.col("mkt_move_pp").mean().over(["season", "week"])
    sd = pl.col("mkt_move_pp").std().over(["season", "week"])
    z = pl.when((n >= MIN_WEEK_ROWS) & sd.is_not_null() & (sd > 1e-9)) \
          .then((pl.col("mkt_move_pp") - mu) / sd)

    return (mv.with_columns(z.alias("mkt_move_z"))
              .with_columns(pl.col("mkt_move_z").abs().alias("mkt_move_abs_z"))
              .unique(subset=["season", "week", "player_name_norm"], keep="last"))
