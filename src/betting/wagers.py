"""What was actually bet, at the price actually available, and what it did.

Every profitability figure in this project comes from a replay: it assumes you
could have had the closing consensus price, in unlimited size, at the moment we
quoted it. None of those assumptions has ever been tested, and each one can only
push realized returns down. A measured +18.3% survives a 3-point haircut; it
does not survive three of them.

This log is the forward test. One row per bet actually placed, recording three
things a backtest cannot know:

  * **The price you got**, against the consensus at the same moment and the
    closing price later. The first gap is line shopping; the second is closing
    line value on money that was genuinely at risk.
  * **When you bet**, because a Tuesday price and a Sunday price are different
    propositions and the backtest only ever measured the latter.
  * **That the bet was accepted at all**, at the size you wanted. Restriction is
    the failure mode nobody backtests, and it arrives precisely when a strategy
    starts working.

Recording a bet is deliberately separate from grading it. Grading reads results
from play-by-play, so a bet placed today gets its answer whenever the week
resolves, without anything being re-entered.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from src.utils.paths import get_path

#: Alongside the odds archive rather than under data/raw: like the odds
#: snapshots, and unlike anything from nflverse, these cannot be regenerated.
WAGERS_PATH = get_path("raw").parent / "archive" / "wagers.parquet"

SCHEMA = {
    "placed_at": pl.Utf8,
    "season": pl.Int64,
    "week": pl.Int64,
    "game_id": pl.Utf8,
    "player_name": pl.Utf8,
    "player_name_norm": pl.Utf8,
    "market": pl.Utf8,
    # The price you were actually given, and where. This is the number that
    # decides whether the money works — not the consensus we modeled against.
    "odds_taken": pl.Int64,
    "book": pl.Utf8,
    "stake": pl.Float64,
    # What we thought at the time, stored so a later re-run of the model cannot
    # quietly rewrite the reason a bet was placed.
    "model_prob": pl.Float64,
    "market_prob": pl.Float64,
    "model_edge": pl.Float64,
    "bet_rank": pl.Int64,
    # Consensus at the moment of betting, for the line-shopping gap.
    "consensus_odds": pl.Int64,
    "note": pl.Utf8,
}

RESULT_SCHEMA = {
    "scored": pl.Int64,
    "pnl": pl.Float64,
    "closing_odds": pl.Int64,
}


def _norm(name: str) -> str:
    from src.ingest.odds_history import _norm_expr
    return (pl.DataFrame({"n": [name]})
            .select(_norm_expr("n"))["n"][0])


def record(season: int, week: int, game_id: str, player_name: str,
           odds_taken: int, stake: float, market: str = "anytime_td",
           book: str | None = None, model_prob: float | None = None,
           market_prob: float | None = None, bet_rank: int | None = None,
           consensus_odds: int | None = None, note: str | None = None,
           placed_at: str | None = None) -> Path:
    """Append one placed bet. Append-only; nothing here is ever rewritten."""
    row = {
        "placed_at": placed_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": season, "week": week, "game_id": game_id,
        "player_name": player_name, "player_name_norm": _norm(player_name),
        "market": market, "odds_taken": int(odds_taken), "book": book,
        "stake": float(stake), "model_prob": model_prob,
        "market_prob": market_prob,
        "model_edge": (None if model_prob is None or market_prob is None
                       else float(model_prob) - float(market_prob)),
        "bet_rank": bet_rank, "consensus_odds": consensus_odds, "note": note,
    }
    df = pl.DataFrame([row])
    for col, dtype in SCHEMA.items():
        if col not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=dtype).alias(col))
    df = df.select(list(SCHEMA)).cast(SCHEMA)

    if WAGERS_PATH.exists():
        existing = pl.read_parquet(WAGERS_PATH).select(list(SCHEMA)).cast(SCHEMA)
        df = pl.concat([existing, df], how="vertical")

    WAGERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = WAGERS_PATH.with_suffix(".parquet.tmp")
    df.write_parquet(tmp)
    tmp.replace(WAGERS_PATH)
    return WAGERS_PATH


def load() -> pl.DataFrame | None:
    if not WAGERS_PATH.exists():
        return None
    return pl.read_parquet(WAGERS_PATH)


def _decimal(american: pl.Expr) -> pl.Expr:
    return (pl.when(american > 0).then(1 + american / 100.0)
            .otherwise(1 + 100.0 / (-american)))


def grade(target_type: str = "anytime_td") -> pl.DataFrame | None:
    """Attach outcomes and closing prices to every settled bet.

    Outcomes come from the same target table the model trains on, so a graded
    wager and a backtest row mean the same thing by construction.
    """
    bets = load()
    if bets is None or bets.height == 0:
        return None
    bets = bets.filter(pl.col("market") == target_type)
    if bets.height == 0:
        return None

    # Outcomes come from the feature table's `target`, the same column the
    # model trains on, so a graded wager and a backtest row mean the same thing
    # by construction rather than by a second definition of "scored".
    targets_path = get_path("processed", target_type) / "features.parquet"
    if not targets_path.exists():
        return None
    tgt = pl.read_parquet(targets_path)
    if "player_name" not in tgt.columns or "target" not in tgt.columns:
        return None
    name_col = "player_name"

    from src.ingest.odds_history import _norm_expr
    tgt = tgt.with_columns(_norm_expr(name_col).alias("player_name_norm"))
    graded = bets.join(
        tgt.select(["game_id", "player_name_norm", "target"]).unique(
            subset=["game_id", "player_name_norm"]),
        on=["game_id", "player_name_norm"], how="left",
    ).rename({"target": "scored"})

    graded = graded.with_columns(
        pl.when(pl.col("scored").is_null()).then(None)
        .when(pl.col("scored") == 1)
        .then(pl.col("stake") * (_decimal(pl.col("odds_taken")) - 1.0))
        .otherwise(-pl.col("stake")).alias("pnl")
    )
    return _attach_closing(graded, target_type)


def _attach_closing(graded: pl.DataFrame, target_type: str) -> pl.DataFrame:
    """Add the closing consensus price, so realized CLV is measurable."""
    from src.ingest.odds_history import HISTORY_PATH
    if not HISTORY_PATH.exists():
        return graded.with_columns(pl.lit(None, dtype=pl.Int64).alias("closing_odds"))
    hist = pl.read_parquet(HISTORY_PATH).filter(
        (pl.col("market") == target_type) & (pl.col("snapshot") == "close")
    )
    if hist.height == 0:
        return graded.with_columns(pl.lit(None, dtype=pl.Int64).alias("closing_odds"))
    # The closing price a bet is graded against must be one that was still on
    # offer at kickoff. See `odds_history.drop_in_play`.
    from src.ingest.odds_history import drop_in_play

    close = (drop_in_play(hist).sort("captured_at")
                 .group_by(["game_id", "player_name_norm"])
                 .agg(pl.col("odds").last().alias("closing_odds")))
    return graded.join(close, on=["game_id", "player_name_norm"], how="left")


def summary(target_type: str = "anytime_td") -> dict | None:
    """What the forward test says so far, and what it cannot say yet.

    `n_settled` is reported prominently because it is the number that decides
    whether any of the rest means anything. Twenty bets tells you nothing about
    a 12% edge; the honest answer for most of a first season is "not yet".
    """
    graded = grade(target_type)
    if graded is None or graded.height == 0:
        return None

    settled = graded.filter(pl.col("scored").is_not_null())
    out = {
        "target_type": target_type,
        "n_placed": int(graded.height),
        "n_settled": int(settled.height),
        "staked": float(settled["stake"].sum()) if settled.height else 0.0,
    }
    if settled.height:
        out["profit"] = float(settled["pnl"].sum())
        out["roi"] = (out["profit"] / out["staked"] * 100
                      if out["staked"] else None)
        out["hit_pct"] = float(settled["scored"].mean() * 100)

    # The two gaps a backtest cannot see. Both are in probability points, and
    # both should be positive if the assumptions behind the replay hold.
    shopped = graded.filter(pl.col("consensus_odds").is_not_null())
    if shopped.height:
        gap = (1 / _decimal(pl.col("consensus_odds"))) - (1 / _decimal(pl.col("odds_taken")))
        out["line_shopping_pp"] = float(
            shopped.select(gap.mean())[0, 0] * 100)
        out["n_shopped"] = int(shopped.height)

    clv = graded.filter(pl.col("closing_odds").is_not_null())
    if clv.height:
        moved = (1 / _decimal(pl.col("closing_odds"))) - (1 / _decimal(pl.col("odds_taken")))
        out["clv_pp"] = float(clv.select(moved.mean())[0, 0] * 100)
        out["clv_beat_close_pct"] = float(
            clv.select((moved > 0).mean())[0, 0] * 100)
        out["n_clv"] = int(clv.height)
    return out
