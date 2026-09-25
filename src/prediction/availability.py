"""Is the player we are recommending actually going to play?

The board is built from depth charts and usage history, and nothing in it knows
that a player was ruled out on Friday. A recommendation for someone who is
inactive is not a bad bet, it is a guaranteed loss — the one category of error
this project has no defense against, because every other check compares numbers
against numbers and this one needs an outside fact.

The markets know. Player props move hard on the inactive report ~90 minutes
before kickoff, and a book will often pull the market entirely. Our closing
snapshot is taken 45 minutes before the Sunday slate, so an archived price
already reflects it; a Thursday board does not.

Two states worth separating, because they mean different things:

  * **Out / Doubtful** — do not bet. The model's number is meaningless.
  * **Questionable** — the model's number is still roughly right but the
    variance is different, and a book that has not moved may simply be slower
    than the news rather than offering value. Treat a large edge on a
    questionable player as a reason to check, not a reason to bet.

Reports are published during the week, so this returns nothing until they
appear. It says so rather than reporting everyone healthy, which is the failure
mode that would actually cost money.
"""
from __future__ import annotations

import polars as pl

from src.utils.paths import get_path

#: Statuses that should stop a bet outright, in the order nflverse reports them.
BLOCKING = ("Out", "Doubtful")

#: Worth surfacing, not worth blocking.
CAUTION = ("Questionable",)


def status_for(season: int, week: int) -> pl.DataFrame | None:
    """Injury designations for one week, keyed by player_id.

    Returns None when no report has been published for that week — a distinct
    state from "everyone is fit", and the caller must not conflate them.
    """
    path = get_path("raw") / "injuries.parquet"
    if not path.exists():
        return None

    inj = pl.read_parquet(path)
    if "gsis_id" not in inj.columns or "report_status" not in inj.columns:
        return None

    wk = inj.filter(
        (pl.col("season").cast(pl.Int64) == season)
        & (pl.col("week").cast(pl.Int64) == week)
        & pl.col("gsis_id").is_not_null()
    )
    if wk.height == 0:
        return None

    cols = ["gsis_id", "report_status"]
    for extra in ("practice_status", "report_primary_injury", "full_name"):
        if extra in wk.columns:
            cols.append(extra)

    return (wk.select(cols)
              .rename({"gsis_id": "player_id"})
              # A player can appear on consecutive reports; the last one for the
              # week is the one that stands.
              .unique(subset=["player_id"], keep="last")
              .with_columns([
                  pl.col("report_status").is_in(BLOCKING).alias("is_blocked"),
                  pl.col("report_status").is_in(CAUTION).alias("is_questionable"),
              ]))


def annotate(board: pl.DataFrame, season: int, week: int) -> pl.DataFrame:
    """Attach injury status to a board, leaving it untouched when none exists.

    Adds `report_status` (null for players not on the report, which is the
    normal case) plus the two booleans. Never drops rows: a player being ruled
    out is information to show, not a reason to make them disappear from a board
    you are comparing against a bookmaker.
    """
    have_ids = "player_id" in board.columns
    status = status_for(season, week) if have_ids else None
    if status is None:
        return board.with_columns([
            pl.lit(None, dtype=pl.Utf8).alias("report_status"),
            pl.lit(False).alias("is_blocked"),
            pl.lit(False).alias("is_questionable"),
            pl.lit(False).alias("injury_report_available"),
        ])

    keep = ["player_id", "report_status", "is_blocked", "is_questionable"]
    if "practice_status" in status.columns:
        keep.append("practice_status")
    return (board.join(status.select(keep), on="player_id", how="left")
                 .with_columns([
                     pl.col("is_blocked").fill_null(False),
                     pl.col("is_questionable").fill_null(False),
                     pl.lit(True).alias("injury_report_available"),
                 ]))


def check(board: pl.DataFrame, season: int, week: int,
          only_recommended: bool = True) -> dict:
    """Who on this board should not be backed, and is a report even out yet?

    `only_recommended` restricts the answer to rows the board marks, because a
    ruled-out player nobody was going to bet is not news.
    """
    annotated = annotate(board, season, week)
    if not annotated["injury_report_available"][0]:
        return {
            "report_available": False,
            "blocked": [], "questionable": [],
            "note": (f"No injury report published for {season} week {week} yet. "
                     f"This is not a clean bill of health — it is no "
                     f"information. Re-check after Friday."),
        }

    scope = annotated
    if only_recommended and "InRange" in annotated.columns:
        scope = annotated.filter(pl.col("InRange").is_not_null()
                                 & (pl.col("InRange") != ""))

    def names(pred) -> list[str]:
        sub = scope.filter(pred)
        if sub.height == 0 or "player_name" not in sub.columns:
            return []
        return sub["player_name"].to_list()

    blocked = names(pl.col("is_blocked"))
    return {
        "report_available": True,
        "blocked": blocked,
        "questionable": names(pl.col("is_questionable")),
        "note": ("Out or Doubtful means the model's number is meaningless, not "
                 "merely pessimistic." if blocked else
                 "No recommended player is ruled out."),
    }
