"""Whether a player practised this week, and how much of it.

Split out of `injury_features` rather than living beside `is_out` and
`is_questionable`, for one reason: this project ablates by FAMILY, never by
column, because columns inside a family are correlated by construction and
dropping one alone measures nothing. Left where it was written, the practice
report could only be tested by removing the game-status features with it, and
the two answer different questions.

`practice_status` is the denser column of the two the injury report carries.
On the raw file it is set on 61,175 of 61,221 rows against `report_status`'s
32,055, so **29,163 player-weeks carry a practice report and no game status at
all** — invisible to the model before this existed. It also discriminates
INSIDE a status: "Questionable" covers 3,195 player-weeks who practised fully
and 2,581 who did not practise at all, and those were the same number.

Joined onto the candidate pool the coverage is far thinner — about 12% of
training rows — because only players who appear on an injury report have a row
at all. That is the same sparsity `is_out` already has, and nullness here means
"not on the report", which is known before kickoff and so is not leakage. It
does mean the three indicators are NOT zero-filled in this builder: 0/0/0 after
`prepare_data` reads as "on no report", which is right, while a zero written
here would erase the difference between that and a report that says nothing.

Three indicators rather than one ordinal: the gap between full and limited is
not the gap between limited and did-not-practise, and a tree should not be told
it is.
"""
from __future__ import annotations

import polars as pl

#: The three values the NFL practice report actually uses. Matched on prefix
#: because the feed appends the reason ("Did Not Participate In Practice") and
#: has carried stray whitespace and a literal "\n" in 213 rows.
_DNP = "Did Not Participate"
_LIMITED = "Limited Participation"
_FULL = "Full Participation"


def build_practice_features(injuries: pl.DataFrame) -> pl.DataFrame:
    """Per player-season-week: did not practise / limited / full.

    Null where the player is on no injury report that week, which is most of
    the pool. Returns an empty frame with the right schema when the feed has no
    `practice_status` column, so an older archive degrades rather than raises.
    """
    schema = {"player_id": pl.Utf8, "season": pl.Int64, "week": pl.Int64,
              "practice_dnp": pl.Float64, "practice_limited": pl.Float64,
              "practice_full": pl.Float64}
    if injuries.is_empty() or "practice_status" not in injuries.columns:
        return pl.DataFrame(schema=schema)

    inj = injuries.select([
        pl.col("gsis_id").alias("player_id"),
        pl.col("season").cast(pl.Int64),
        pl.col("week").cast(pl.Int64),
        pl.col("practice_status").cast(pl.Utf8).str.strip_chars().alias("ps"),
    ]).filter(pl.col("player_id").is_not_null())

    dnp = pl.col("ps").str.starts_with(_DNP)
    lim = pl.col("ps").str.starts_with(_LIMITED)
    full = pl.col("ps").str.starts_with(_FULL)
    known = pl.col("ps").is_not_null() & (dnp | lim | full)

    return (inj.with_columns([
                pl.when(known).then(dnp.cast(pl.Float64)).alias("practice_dnp"),
                pl.when(known).then(lim.cast(pl.Float64)).alias("practice_limited"),
                pl.when(known).then(full.cast(pl.Float64)).alias("practice_full"),
            ])
            .select(["player_id", "season", "week", "practice_dnp",
                     "practice_limited", "practice_full"])
            .unique(subset=["player_id", "season", "week"], keep="last"))
