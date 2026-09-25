"""Which book is slow, and where that is worth money.

This project's measurable claim is closing-line value: the market moves toward
the players it rates above the opening price about 60% of the time against a
54% shuffle null. That is evidence the disagreement anticipates the market. It
has never been turned into an instruction, because knowing the market will
move does not say WHERE to be standing when it does.

`data/archive/odds_books.parquet` answers that and nothing reads it — two
million rows of per-book prices, each stamped with when that book last moved.

Two different questions, measured separately:

  * **Lag.** Measured from the PRICES, not from any timestamp. When the room
    moves between two captures, did this book move with it or only by the
    next one?

    `book_last_update` cannot answer that and is not used. The feed's own
    field is unusable for most books: DraftKings stamps 2024-12-23 on a
    price captured 2026-08-18, FanDuel 2023-10-15. Two books report a
    credible age and eighteen do not, so reading it would have produced a
    confident table of nonsense — a median staleness of 607 days — in a
    project whose failures are all of exactly that shape.

  * **Generosity.** How far a book's implied probability sits below the
    consensus for the same player, market, line and side. Negative is a
    longer price than the room, which is where a bet goes.

**These are not the same thing and a book can be one without the other.** A
slow book that is slow around a price nobody disagrees with pays nothing. The
pair worth acting on is a book that is both, so they are reported together and
never combined into a single score that hides which half is doing the work.

Nothing here is a betting recommendation. It is a measurement of where a price
this project already rates has survived longest.
"""
from __future__ import annotations

import polars as pl

from pathlib import Path

#: The per-book archive. Written by `ingest/odds`, read by nothing until now.
#: `data/archive` is not in `paths` — the odds archive has always been
#: addressed directly, and inventing a config key for one reader would put two
#: answers on disk for where it lives.
BOOKS = Path("data/archive/odds_books.parquet")

#: A book needs this many quotes before it is described at all. Below it the
#: mean is a story about a handful of lines.
MIN_QUOTES = 2000

#: Quotes at least this many books deep, or "consensus" is one other book's
#: opinion and the deviation measures noise.
MIN_BOOKS = 4

#: How the two sides of one line are keyed. `point` is included because a book
#: posting an alternate line is not disagreeing with the room about the main
#: one — comparing across points measures the ladder, not the price.
KEY = ["season", "week", "game_id", "player_name_norm", "market", "point",
       "side", "snapshot"]


def load(seasons: list[int] | None = None) -> pl.DataFrame:
    """Every per-book quote, optionally narrowed to some seasons."""
    if not BOOKS.exists():
        return pl.DataFrame()
    d = pl.read_parquet(BOOKS)
    if seasons:
        d = d.filter(pl.col("season").is_in(seasons))
    return d


#: A consensus move smaller than this is rounding, not news.
MIN_MOVE = 0.01


def lag(d: pl.DataFrame) -> pl.DataFrame:
    """Does a book move WITH the room, or one capture behind it?

    For each line, consecutive captures give the room's move and each book's
    move over the same interval. `keeps_up` is the share of real room moves
    the book matched in direction at the same capture. A book near 1.0 is
    repricing on the same information at the same time; a low share is a book
    whose number is still where it was when the room has already gone.

    Direction rather than size, because a book that moves the right way by
    half as much is still repricing, and scaling two books' step sizes
    against each other measures their margins instead of their speed.
    """
    if d.is_empty():
        return pl.DataFrame()
    line = [c for c in KEY if c != "snapshot"]
    x = d.drop_nulls(["implied_prob", "captured_at"])

    # THE ROOM MOVES ONCE PER CAPTURE, NOT ONCE PER BOOK.
    #
    # Shifting inside the line alone walks across BOOKS at the same capture,
    # so a "move" was one book's price minus a different book's — which is a
    # spread, not a change. The room's path is one row per capture and the
    # book's path is one row per capture per book; they are built separately
    # and joined.
    room = (x.group_by(line + ["snapshot", "captured_at"])
             .agg(pl.col("implied_prob").median().alias("consensus"))
             .sort("captured_at")
             .with_columns((pl.col("consensus")
                            - pl.col("consensus").shift(1).over(line))
                           .alias("room_move")))
    moves = (x.sort("captured_at")
              .with_columns((pl.col("implied_prob")
                             - pl.col("implied_prob").shift(1)
                             .over(line + ["bookmaker"])).alias("book_move")))
    j = (moves.join(room.select(line + ["snapshot", "room_move"]),
                    on=line + ["snapshot"], how="inner")
              .drop_nulls(["room_move", "book_move"])
              .filter(pl.col("room_move").abs() >= MIN_MOVE))
    if j.is_empty():
        return pl.DataFrame()
    j = j.with_columns(
        ((pl.col("room_move") > 0) == (pl.col("book_move") > 0))
        .alias("with_room"))
    return (j.group_by("bookmaker")
             .agg([pl.len().alias("moves"),
                   pl.col("with_room").mean().alias("keeps_up")])
             .filter(pl.col("moves") >= 200)
             .sort("keeps_up"))


def generosity(d: pl.DataFrame) -> pl.DataFrame:
    """How far each book prices below the room, on the same line and side.

    Deviation is the book's implied probability minus the median across books
    quoting that exact line at that capture. Negative means a longer price.
    `best_share` is how often the book held the single longest price in the
    room, which is the number that decides where a bet is placed.
    """
    if d.is_empty():
        return pl.DataFrame()
    x = d.drop_nulls(["implied_prob"])
    x = x.with_columns([
        pl.col("implied_prob").median().over(KEY).alias("consensus"),
        pl.col("bookmaker").n_unique().over(KEY).alias("n_books"),
        pl.col("implied_prob").min().over(KEY).alias("longest"),
    ]).filter(pl.col("n_books") >= MIN_BOOKS)
    if x.is_empty():
        return pl.DataFrame()
    x = x.with_columns([
        (pl.col("implied_prob") - pl.col("consensus")).alias("dev"),
        (pl.col("implied_prob") <= pl.col("longest") + 1e-12).alias("is_best"),
    ])
    return (x.group_by("bookmaker")
             .agg([pl.len().alias("quotes"),
                   pl.col("dev").mean().alias("mean_dev"),
                   pl.col("dev").median().alias("median_dev"),
                   pl.col("is_best").mean().alias("best_share")])
             .filter(pl.col("quotes") >= MIN_QUOTES)
             .sort("mean_dev"))


def report(seasons: list[int] | None = None) -> pl.DataFrame:
    """Staleness and generosity side by side, one row per book.

    Sorted by generosity, because that is the half a bet can act on. The
    staleness column says whether the long price is a book that has not moved
    yet or a book that simply prices that market differently — and those call
    for different behaviour: the first is a clock to beat, the second is a
    standing account to open.
    """
    d = load(seasons)
    if d.is_empty():
        return pl.DataFrame()
    s, g = lag(d), generosity(d)
    if g.is_empty():
        return s
    if s.is_empty():
        return g
    return (g.join(s, on="bookmaker", how="left")
             .select(["bookmaker", "quotes", "mean_dev", "median_dev",
                      "best_share", "moves", "keeps_up"])
             .sort("mean_dev"))


def format_report(r: pl.DataFrame) -> str:
    """The table, with the units spelled out."""
    if r.is_empty():
        return ("No per-book archive to read. `data/archive/odds_books.parquet` "
                "is written by the odds capture; until it has run there is "
                "nothing here.")
    lines = [
        "Where a price survives longest.",
        "",
        "  mean_dev     implied probability minus the room's median.",
        "               NEGATIVE is a longer price than everyone else.",
        "  best_share   how often this book held the single longest price.",
        "  keeps_up     share of real room moves it matched at the same",
        "               capture. LOW is a book still showing the old number.",
        "",
        f"  {'book':18s} {'quotes':>9s} {'mean_dev':>9s} {'best':>6s} "
        f"{'moves':>8s} {'keeps_up':>9s}",
    ]
    for row in r.iter_rows(named=True):
        k = row.get("keeps_up")
        lines.append(
            f"  {row['bookmaker']:18s} {row['quotes']:>9,d} "
            f"{row['mean_dev']:>+9.4f} {row['best_share']:>6.1%} "
            f"{(row.get('moves') or 0):>8,d} "
            + (f"{k:>9.1%}" if k is not None else f"{'—':>9s}"))
    return "\n".join(lines)
