"""Append-only archive of sportsbook TD prices, graded against results.

The Odds API only serves *current* markets — once a week kicks off those prices
are gone. Without a local archive there is no way to ever measure whether the
model beats the book, and the model/market blend weight could only ever be
guessed at. So every fetch is snapshotted here, and resolved weeks are graded
against play-by-play outcomes.

This file is the training data for `blend.fit_blend_weight`. It grows week over
week and season over season; nothing in it is ever overwritten.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from src.utils.paths import get_path

#: Deliberately NOT under data/raw. Everything in data/raw can be re-downloaded
#: free from nflverse, so `make clean` wipes it. This archive cannot: historical
#: odds cost real money and the API only sells each snapshot once. It lives in
#: data/archive, which no cleaning target touches.
ARCHIVE_DIR = get_path("raw").parent / "archive"
HISTORY_PATH = ARCHIVE_DIR / "odds_history.parquet"

#: Every individual bookmaker's price, kept alongside the consensus median.
#:
#: The API returns all books in the same response, so this costs nothing extra —
#: we were simply discarding it after taking the median. What it buys, none of
#: which is recoverable later:
#:
#:   * **Line shopping.** The best of seven books beats the median of seven by
#:     more than the entire measured edge on most bets. Every profitability
#:     figure in this project is computed against a median nobody can actually
#:     bet, which makes them all conservative — but only if you take the best
#:     price, and you cannot take it if you never recorded who offered it.
#:   * **Disagreement between books** as a signal in its own right. A player
#:     quoted +250 at one book and +400 at another is a different proposition
#:     from one quoted +300 everywhere.
#:   * **Staleness.** Each book reports when it last moved. A price that has not
#:     updated in six hours is not really an opinion about tonight's game.
BOOKS_PATH = ARCHIVE_DIR / "odds_books.parquet"

BOOK_SCHEMA = {
    "captured_at": pl.Utf8,
    "snapshot": pl.Utf8,
    "season": pl.Int64,
    "week": pl.Int64,
    "game_id": pl.Utf8,
    "bookmaker": pl.Utf8,
    # When that book last moved this market, as the API reports it. The gap
    # between this and captured_at is how stale the quote is.
    "book_last_update": pl.Utf8,
    "player_name_raw": pl.Utf8,
    "player_name_norm": pl.Utf8,
    "market": pl.Utf8,
    "side": pl.Utf8,
    "odds": pl.Int64,
    "implied_prob": pl.Float64,
}


def _ensure_dir() -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

SCHEMA = {
    "captured_at": pl.Utf8,
    # Which point in the market's life this price is from: "open" for a
    # snapshot taken when the week's board first goes up, "close" for one taken
    # just before kickoff. Everything backfilled from the historical endpoint
    # is a closing line by construction (CLOSING_OFFSET), so rows written
    # before this column existed default to "close".
    #
    # The pair is what makes closing-line value measurable: if the players we
    # rate above the opening price are the ones the market then moves toward,
    # the edge survives contact with money. That is the only honest evidence
    # that a backtest ROI means anything, and it needs both ends.
    "snapshot": pl.Utf8,
    "season": pl.Int64,
    "week": pl.Int64,
    "game_id": pl.Utf8,
    # Keep the book's original spelling alongside the normalised key. Name
    # matching across seasons is fiddly and will need more than one attempt —
    # storing the raw string means a second pass costs zero API credits instead
    # of re-fetching the whole archive.
    "player_name_raw": pl.Utf8,
    "player_name_norm": pl.Utf8,
    "market": pl.Utf8,
    "odds": pl.Int64,
    "implied_prob": pl.Float64,
    "fair_prob": pl.Float64,
    "n_books": pl.Int64,
    "overround": pl.Float64,
}


def append_snapshot(odds: pl.DataFrame, season: int, week: int,
                    snapshot: str = "close") -> Path:
    """Archive one fetch. Deduplicates on (game_id, player, market, captured_at)."""
    if odds is None or odds.height == 0:
        print("  Odds history: nothing to archive")
        return HISTORY_PATH

    captured = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snap = odds.with_columns([
        pl.lit(captured).alias("captured_at"),
        pl.lit(season, dtype=pl.Int64).alias("season"),
        pl.lit(week, dtype=pl.Int64).alias("week"),
        pl.lit(snapshot).alias("snapshot"),
    ])
    for col, dtype in SCHEMA.items():
        if col not in snap.columns:
            snap = snap.with_columns(pl.lit(None, dtype=dtype).alias(col))
    snap = snap.select(list(SCHEMA)).cast(SCHEMA)

    if HISTORY_PATH.exists():
        existing = pl.read_parquet(HISTORY_PATH)
        if "snapshot" not in existing.columns:
            existing = existing.with_columns(pl.lit("close").alias("snapshot"))
        existing = existing.select(list(SCHEMA)).cast(SCHEMA)
        snap = pl.concat([existing, snap], how="vertical")

    snap = snap.unique(
        subset=["game_id", "player_name_norm", "market", "captured_at"], keep="last"
    )
    _ensure_dir()
    # Write-then-rename: a crash mid-write must not corrupt an archive that cost
    # money to build and cannot be re-fetched.
    tmp = HISTORY_PATH.with_suffix(".parquet.tmp")
    snap.write_parquet(tmp)
    tmp.replace(HISTORY_PATH)
    print(f"  Odds history: {snap.height:,} rows -> {HISTORY_PATH}")
    return HISTORY_PATH


def load_graded_history(target_type: str = "anytime_td") -> pl.DataFrame | None:
    """Return archived prices joined to actual outcomes, one row per player-game.

    Only weeks that have been played appear — an ungraded snapshot is not
    evidence about anything. Uses the closing (latest) price per player-game.
    """
    if not HISTORY_PATH.exists():
        return None

    hist = pl.read_parquet(HISTORY_PATH)
    market = "anytime_td" if target_type == "anytime_td" else "first_td"
    hist = hist.filter(pl.col("market") == market)
    if hist.height == 0:
        return None

    # Closing line: the "close" snapshot where one exists, else the latest we
    # hold. Grading against an opening line would score a price nobody could
    # still get.
    if "snapshot" in hist.columns and (hist["snapshot"] == "close").any():
        closing = hist.filter(pl.col("snapshot") == "close")
        if closing.height:
            hist = closing
    hist = hist.sort("captured_at").unique(
        subset=["game_id", "player_name_norm"], keep="last"
    )

    tds_path = get_path("processed", target_type) / f"tds_{target_type}.parquet"
    if not Path(tds_path).exists():
        return None
    tds = pl.read_parquet(tds_path)

    # Grade on player_id, never on names. Play-by-play abbreviates the scorer
    # ("D.Kincaid") while sportsbooks spell it out ("Dalton Kincaid"), so a name
    # join silently matches nothing — it graded 0 of 648 rows before this.
    # Rosters carry both the full name and the gsis id, so they bridge the two.
    hist = hist.with_columns(_resolve_player_id(hist))
    matched = hist.filter(pl.col("player_id").is_not_null())
    if matched.height == 0:
        print("  WARNING: no book names resolved to player ids — cannot grade.")
        return None

    rate = matched.height / hist.height
    if rate < 0.7:
        print(f"  WARNING: only {rate:.0%} of priced players resolved to a "
              f"player_id. Grading will be sparse.")

    scorers = (
        tds.select(["game_id", "td_player_id"])
        .drop_nulls()
        .rename({"td_player_id": "player_id"})
        .unique()
        .with_columns(pl.lit(1, dtype=pl.Int8).alias("scored"))
    )

    # Only grade games that actually appear in results.
    played = tds.select("game_id").unique()
    graded = (
        matched.join(played, on="game_id", how="inner")
        .join(scorers, on=["game_id", "player_id"], how="left")
        .with_columns(pl.col("scored").fill_null(0))
    )
    return graded


def append_book_quotes(rows: list[dict], season: int, week: int,
                       snapshot: str = "close") -> Path | None:
    """Archive every bookmaker's individual price for one fetch.

    Append-only and deduplicated on (game, player, market, side, book, capture),
    so re-running a fetch is safe and a crash mid-write cannot corrupt an
    archive that the API will not sell twice.

    Kept separate from `HISTORY_PATH` rather than widening it: the consensus
    archive is one row per player and is joined against everywhere, while this
    is one row per player *per book* and is roughly seven times the size. Fusing
    them would change the grain of a table a dozen callers assume is unique on
    player.
    """
    if not rows:
        return None

    captured = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snap = pl.DataFrame(rows).with_columns([
        pl.lit(captured).alias("captured_at"),
        pl.lit(season, dtype=pl.Int64).alias("season"),
        pl.lit(week, dtype=pl.Int64).alias("week"),
        pl.lit(snapshot).alias("snapshot"),
        _norm_expr("player_name_raw").alias("player_name_norm"),
    ])
    for col, dtype in BOOK_SCHEMA.items():
        if col not in snap.columns:
            snap = snap.with_columns(pl.lit(None, dtype=dtype).alias(col))
    snap = snap.select(list(BOOK_SCHEMA)).cast(BOOK_SCHEMA)

    if BOOKS_PATH.exists():
        existing = pl.read_parquet(BOOKS_PATH).select(list(BOOK_SCHEMA)).cast(BOOK_SCHEMA)
        snap = pl.concat([existing, snap], how="vertical")

    snap = snap.unique(
        subset=["game_id", "player_name_norm", "market", "side", "bookmaker",
                "captured_at"],
        keep="last",
    )
    _ensure_dir()
    tmp = BOOKS_PATH.with_suffix(".parquet.tmp")
    snap.write_parquet(tmp)
    tmp.replace(BOOKS_PATH)
    books = snap["bookmaker"].n_unique()
    print(f"  Book quotes: {snap.height:,} rows across {books} books -> {BOOKS_PATH}")
    return BOOKS_PATH


def best_prices(season: int, week: int, market: str = "anytime_td",
                snapshot: str = "close") -> pl.DataFrame | None:
    """The best available price per player, and who was offering it.

    This is what line shopping actually means, and the reason the per-book
    archive exists. Returns None until `append_book_quotes` has run at least
    once for the week asked for.
    """
    if not BOOKS_PATH.exists():
        return None
    df = pl.read_parquet(BOOKS_PATH).filter(
        (pl.col("season") == season) & (pl.col("week") == week)
        & (pl.col("market") == market) & (pl.col("side") == "yes")
        & (pl.col("snapshot") == snapshot)
    )
    if df.height == 0:
        return None
    # Longest price wins: for a "Yes" bet, higher American odds pay more.
    return (df.sort("odds", descending=True)
              .group_by(["game_id", "player_name_norm"])
              .agg([
                  pl.col("player_name_raw").first(),
                  pl.col("odds").first().alias("best_odds"),
                  pl.col("bookmaker").first().alias("best_book"),
                  pl.col("odds").median().alias("median_odds"),
                  pl.col("odds").count().alias("n_books"),
              ]))


def _resolve_player_id(hist: pl.DataFrame) -> pl.Expr:
    """Map a book's player name to a gsis player_id via the roster.

    Matching is done per season so that two players sharing a name in different
    eras don't collide.
    """
    roster_path = get_path("raw") / "rosters.parquet"
    if not roster_path.exists():
        # Without rosters we cannot map book names to player ids, but that is a
        # reason to return unresolved rows — not to take down every page that
        # touches the odds archive. A missing optional input killed the whole
        # app in the production image with a bare FileNotFoundError.
        return pl.lit(None, dtype=pl.Utf8)
    rosters = pl.read_parquet(roster_path)
    name_col = "player_name" if "player_name" in rosters.columns else "full_name"
    lookup = (
        rosters.select(["season", name_col, "player_id"])
        .drop_nulls()
        .with_columns(_norm_expr(name_col).alias("player_name_norm"))
        .select(["season", "player_name_norm", "player_id"])
        .unique(subset=["season", "player_name_norm"], keep="first")
    )
    joined = hist.select(["season", "player_name_norm"]).join(
        lookup, on=["season", "player_name_norm"], how="left"
    )
    return pl.Series("player_id", joined["player_id"].to_list())


def _norm_expr(col: str) -> pl.Expr:
    """Match src.features.odds_features._normalize_name, as a polars expression."""
    e = pl.col(col).str.to_lowercase().str.strip_chars()
    for suffix in [" jr.", " sr.", " ii", " iii", " iv", " jr", " sr"]:
        e = e.str.replace(rf"{suffix}$", "")
    return e.str.replace_all(r"\.", "").str.strip_chars()
