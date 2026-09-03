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


#: The region set every row written before 2026-08-17 was fetched with, back
#: when `regions="us"` was hardcoded in both fetch paths.
LEGACY_REGIONS = "us"


class UnknownMarket(KeyError):
    """A target type with no archived market. Raised rather than guessed at."""


#: Target type -> the `market` value its prices are archived under.
#:
#: The two are deliberately the same string, and this map exists so that being
#: the same string is an assertion rather than a coincidence. What it replaces,
#: in this module and again in `src/evaluation/clv.py`:
#:
#:     market = "anytime_td" if target_type == "anytime_td" else "first_td"
#:
#: Every target that was not anytime resolved to first TD. With two markets
#: that is merely redundant. With a third it silently fits the blend weight
#: against the wrong prices, measures closing-line value against the wrong
#: prices, and grades a rushing-touchdown model on first-touchdown odds — none
#: of which raises, and none of which looks wrong on screen. That is the same
#: failure shape as the weekly-stats lag in docs/DATA_SOURCES.md: a plausible
#: number, silently wrong.
#:
#: A new target belongs here once its prices are being archived. Until then it
#: gets an exception instead of another market's numbers.
MARKET_BY_TARGET: dict[str, str] = {
    "first_td": "first_td",
    "anytime_td": "anytime_td",
    # A count target, not a yes/no one: graded per (player, line) rather than
    # per player, and its archive rows carry `point`. Registered 2026-08-18,
    # once its prices were actually in the archive — 21,129 closing lines
    # across 2023-2025.
    "receptions": "receptions",
}


def market_for_target(target_type: str) -> str:
    """The archive market for a target type. Raises on anything unregistered."""
    try:
        return MARKET_BY_TARGET[target_type]
    except KeyError:
        raise UnknownMarket(
            f"no archived market for target type {target_type!r}; known targets "
            f"are {sorted(MARKET_BY_TARGET)}. Add it to MARKET_BY_TARGET once "
            f"its prices are in the archive — do not let it fall back to "
            f"another market's prices."
        ) from None


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
    # Which bookmaker regions this price was a consensus of. Provenance, and
    # the only thing that can tell a 7-book `us` median from an 11-book
    # `us,us2` one after the fact — they are different numbers for the same
    # player and nothing else in the row distinguishes them.
    #
    # It also decides what a backfill considers done. Without it,
    # `_already_archived` reports every game covered and a top-up for a newly
    # added region silently fetches nothing.
    #
    # Rows written before this column existed were all fetched with "us",
    # which is why the migration stamps that rather than null.
    "regions": pl.Utf8,
    # See SCHEMA["point"]. Per book, because two books can post different lines
    # for the same player — which is precisely what line shopping on an
    # over/under market means, and is invisible if only the median is kept.
    "point": pl.Float64,
    # "yes"/"no". Over/under markets are normalised onto the same two words:
    # "over" is stored as "yes", "under" as "no". The semantics are identical —
    # the side that wins when the player does more — and one vocabulary means
    # `best_prices` and `line_shopping` need no per-market branch. Which line
    # the side refers to is in `point`, not in this column.
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
    # Which bookmaker regions this price was a consensus of. Provenance, and
    # the only thing that can tell a 7-book `us` median from an 11-book
    # `us,us2` one after the fact — they are different numbers for the same
    # player and nothing else in the row distinguishes them.
    #
    # It also decides what a backfill considers done. Without it,
    # `_already_archived` reports every game covered and a top-up for a newly
    # added region silently fetches nothing.
    #
    # Rows written before this column existed were all fetched with "us",
    # which is why the migration stamps that rather than null.
    "regions": pl.Utf8,
    # The line this price is for, as the API reports it. Null for yes/no
    # markets, which have no line — anytime and first TD only ask whether it
    # happened. Over/under markets always carry one: 0.5 for rush and reception
    # touchdowns, though books do post 1.5 on a heavy favourite, and receptions
    # lines routinely differ between books for the same player.
    #
    # It is part of the archive's grain, not decoration. A consensus median
    # taken across books quoting different lines is not a price for anything,
    # so `point` sits in the dedup key beside player and market. Added before
    # the first over/under backfill rather than after: this archive is
    # append-only, cost real money, and cannot be re-fetched.
    "point": pl.Float64,
    "odds": pl.Int64,
    "implied_prob": pl.Float64,
    "fair_prob": pl.Float64,
    "n_books": pl.Int64,
    "overround": pl.Float64,
}


def _conform(df: pl.DataFrame, schema: dict) -> pl.DataFrame:
    """Fill in any column the schema has gained since a file was written.

    Everything missing becomes null, with one exception: rows predating the
    `snapshot` column all came from the historical endpoint at CLOSING_OFFSET,
    so they are closing lines by construction rather than unknown ones.
    """
    if "snapshot" in schema and "snapshot" not in df.columns:
        df = df.with_columns(pl.lit("close").alias("snapshot"))
    if "regions" in schema and "regions" not in df.columns:
        # Every fetch before 2026-08-17 hardcoded regions=us.
        df = df.with_columns(pl.lit(LEGACY_REGIONS).alias("regions"))
    missing = [c for c in schema if c not in df.columns]
    if missing:
        df = df.with_columns(
            [pl.lit(None, dtype=schema[c]).alias(c) for c in missing])
    return df.select(list(schema)).cast(schema)


def append_snapshot(odds: pl.DataFrame, season: int, week: int,
                    snapshot: str = "close",
                    regions: str | None = None) -> Path:
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
    if regions is not None:
        snap = snap.with_columns(pl.lit(regions).alias("regions"))
    snap = _conform(snap, SCHEMA)

    if HISTORY_PATH.exists():
        existing = _conform(pl.read_parquet(HISTORY_PATH), SCHEMA)
        snap = pl.concat([existing, snap], how="vertical")

    # `point` is in the key because it is part of the grain: a player can be
    # quoted at two lines in the same market, and collapsing them would keep
    # whichever happened to sort last. Null compares equal to null in polars,
    # so yes/no markets — where every point is null — dedup exactly as before.
    snap = snap.unique(
        subset=["game_id", "player_name_norm", "market", "point", "regions",
                "captured_at"],
        keep="last",
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

    hist = _conform(pl.read_parquet(HISTORY_PATH), SCHEMA)
    market = market_for_target(target_type)
    hist = hist.filter(pl.col("market") == market)
    if hist.height == 0:
        return None

    # Grading below keeps one price per player-game, which is only meaningful
    # while the market has one line. Say so rather than quietly averaging a
    # player quoted at 0.5 with the same player quoted at 1.5.
    n_lines = hist["point"].drop_nulls().n_unique()
    if n_lines > 1:
        print(f"  WARNING: {market} holds {n_lines} distinct lines; grading "
              f"keeps one price per player-game and will mix them. Grade a "
              f"multi-line market per point instead.")

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
                       snapshot: str = "close",
                       regions: str | None = None) -> Path | None:
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
    # infer_schema_length=None: scan every row, not the first 100. `point` is
    # null for the TD markets and only carries a number on lines that have one,
    # so a fetch whose first 100 rows are all anytime/first TD types the column
    # Null and then fails on the first 6.5 that arrives — losing the whole
    # book-level archive for that week while the consensus snapshot succeeds.
    snap = pl.DataFrame(rows, infer_schema_length=None).with_columns([
        pl.lit(captured).alias("captured_at"),
        pl.lit(season, dtype=pl.Int64).alias("season"),
        pl.lit(week, dtype=pl.Int64).alias("week"),
        pl.lit(snapshot).alias("snapshot"),
        _norm_expr("player_name_raw").alias("player_name_norm"),
    ])
    if regions is not None:
        snap = snap.with_columns(pl.lit(regions).alias("regions"))
    snap = _conform(snap, BOOK_SCHEMA)

    if BOOKS_PATH.exists():
        existing = _conform(pl.read_parquet(BOOKS_PATH), BOOK_SCHEMA)
        snap = pl.concat([existing, snap], how="vertical")

    snap = snap.unique(
        subset=["game_id", "player_name_norm", "market", "point", "regions",
                "side", "bookmaker", "captured_at"],
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
