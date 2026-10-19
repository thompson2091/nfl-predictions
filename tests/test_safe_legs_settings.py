"""The safe-legs threshold is read from its own file and can be overridden per run."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation import safe_legs  # noqa: E402


def test_the_committed_file_loads():
    cfg = safe_legs.settings()
    assert cfg["min_prob"] == 0.90
    assert cfg["min_prob"] in cfg["report_thresholds"]


def test_an_override_wins_and_none_does_not(tmp_path):
    assert safe_legs.settings(min_prob=0.95)["min_prob"] == 0.95
    assert safe_legs.settings(min_prob=None)["min_prob"] == 0.90


def test_a_bad_threshold_is_refused(tmp_path):
    with pytest.raises(ValueError):
        safe_legs.settings(min_prob=90)
    bad = tmp_path / "s.yaml"
    bad.write_text("min_prob: 0.9\n")
    with pytest.raises(KeyError):
        safe_legs.settings(bad)


def test_a_broken_ladder_is_dropped_whole(tmp_path, monkeypatch):
    """A book whose ladder gets MORE likely as the line rises is not quoting it."""
    import polars as pl
    from src.ingest import odds_history

    def q(book, point, odds, imp):
        return {"captured_at": "2025-09-07T16:00:00Z", "snapshot": "close",
                "season": 2025, "week": 1, "game_id": "2025_01_BAL_BUF",
                "bookmaker": book, "book_last_update": "2025-09-07T16:00:00Z",
                "player_name_raw": "Josh Allen", "player_name_norm": "josh allen",
                "market": "passing_yards_alt", "regions": "us", "point": point,
                "side": "yes", "odds": odds, "implied_prob": imp}
    rows = [q("good", 149.5, -1300, 1300 / 1400), q("good", 199.5, -260, 260 / 360),
            q("broken", 99.5, 800, 0.111), q("broken", 199.5, 1600, 0.059),
            q("broken", 124.5, 120, 0.455), q("absurd", 149.5, -999905, 0.9999)]
    path = tmp_path / "books.parquet"
    pl.DataFrame(rows).write_parquet(path)
    monkeypatch.setattr(odds_history, "BOOKS_PATH", path)
    monkeypatch.setattr(odds_history, "drop_in_play", lambda d: d)
    got = safe_legs.book_ladders([2025])
    assert set(got["bookmaker"]) == {"good"}
    r = safe_legs.rungs([2025]).sort("point")
    assert r["n_books"].to_list() == [1, 1]
    assert r["odds"].to_list() == [-1300, -260]
