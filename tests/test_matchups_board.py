"""The game card's consensus price: never a quote taken after kickoff."""
from __future__ import annotations

import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation import matchups as M  # noqa: E402


def quote(book, outcome, prob, moved):
    return {"captured_at": moved, "book_last_update": moved,
            "commence_time": "2026-09-21T17:00:00Z", "game_id": "LV_NO",
            "home_team": "NO", "away_team": "LV", "bookmaker": book,
            "market": "h2h", "outcome": outcome, "outcome_raw": outcome,
            "point": None, "odds": -150, "implied_prob": prob,
            "season": 2026, "week": 3, "snapshot": "close"}


def test_an_in_play_quote_does_not_replace_the_pre_kickoff_price(tmp_path, monkeypatch):
    """LV @ NO read NO at 9.5% on a fourth-quarter quote; 64.9% before kickoff."""
    import src.ingest.game_lines as GL

    rows = []
    for book in ("a", "b", "c", "d"):
        rows += [quote(book, "NO", 0.649, "2026-09-21T16:30:00Z"),
                 quote(book, "LV", 0.392, "2026-09-21T16:30:00Z"),
                 quote(book, "NO", 0.095, "2026-09-21T19:40:00Z"),
                 quote(book, "LV", 0.93, "2026-09-21T19:40:00Z")]
    p = tmp_path / "game_lines.parquet"
    pl.DataFrame(rows).write_parquet(p)
    monkeypatch.setattr(GL, "LINES_PATH", p)
    monkeypatch.setattr(M, "_this_week_only", lambda d, s, w: d)
    b = M.board(2026, 3).filter(pl.col("outcome") == "NO")
    assert b["consensus_prob"].to_list() == [0.649]
