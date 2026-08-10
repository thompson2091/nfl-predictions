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


def _ensure_dir() -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

SCHEMA = {
    "captured_at": pl.Utf8,
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


def append_snapshot(odds: pl.DataFrame, season: int, week: int) -> Path:
    """Archive one fetch. Deduplicates on (game_id, player, market, captured_at)."""
    if odds is None or odds.height == 0:
        print("  Odds history: nothing to archive")
        return HISTORY_PATH

    captured = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snap = odds.with_columns([
        pl.lit(captured).alias("captured_at"),
        pl.lit(season, dtype=pl.Int64).alias("season"),
        pl.lit(week, dtype=pl.Int64).alias("week"),
    ])
    for col, dtype in SCHEMA.items():
        if col not in snap.columns:
            snap = snap.with_columns(pl.lit(None, dtype=dtype).alias(col))
    snap = snap.select(list(SCHEMA)).cast(SCHEMA)

    if HISTORY_PATH.exists():
        existing = pl.read_parquet(HISTORY_PATH).cast(SCHEMA)
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

    # Closing line: last snapshot per player-game.
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


def _resolve_player_id(hist: pl.DataFrame) -> pl.Expr:
    """Map a book's player name to a gsis player_id via the roster.

    Matching is done per season so that two players sharing a name in different
    eras don't collide.
    """
    rosters = pl.read_parquet(get_path("raw") / "rosters.parquet")
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
