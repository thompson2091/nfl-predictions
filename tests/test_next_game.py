"""The next-game placeholders: team form reaches the game about to be played."""
from __future__ import annotations

import sys
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.features.next_game import NOBODY, stubs, with_stubs  # noqa: E402


def _pbp():
    return pl.DataFrame({
        "game_id": ["g1", "g1", "g2", "g2"], "season": [2030] * 4,
        "week": [1, 1, 2, 2], "posteam": ["A", "B", "A", "C"],
        "defteam": ["B", "A", "C", "A"], "touchdown": [1.0, 0.0, 2.0, 1.0],
    }).with_columns(pl.col("season").cast(pl.Int32), pl.col("week").cast(pl.Int32))


def _sched():
    return pl.DataFrame({
        "game_id": ["g1", "g2", "g3", "g4", "g5"], "season": [2030] * 5,
        "week": [1, 2, 3, 3, 4], "home_team": ["A", "A", "A", "D", "B"],
        "away_team": ["B", "C", "B", "E", "C"],
    })


def test_each_team_gets_one_placeholder_for_its_next_game_only():
    s = stubs(_pbp(), _sched(), 2030)
    real = s.filter(pl.col("posteam") != NOBODY)
    nxt = dict(zip(real["posteam"], real["game_id"]))
    # A and B meet in week 3; C has a bye in week 3 and plays in week 4.
    assert nxt == {"A": "g3", "B": "g3", "C": "g5", "D": "g4", "E": "g4"}


def test_a_placeholder_never_plays_a_real_team():
    """Against the real opponent, a team whose next game comes later read the
    opponent's own placeholder: CHI 2025 week 8 allowed 2.0 TDs, not 2.67."""
    s = stubs(_pbp(), _sched(), 2030)
    assert (s.filter(pl.col("posteam") != NOBODY)["defteam"] == NOBODY).all()
    assert (s.filter(pl.col("defteam") != NOBODY)["posteam"] == NOBODY).all()


def test_no_season_means_no_placeholders():
    p = _pbp()
    assert with_stubs(p, _sched(), None).equals(p)


def test_on_a_real_season_the_next_game_row_is_the_one_its_plays_give():
    """`scripts/74_next_game_check.py`: next-game rows equal the real rows,
    and no played row moves, for every team builder."""
    import subprocess
    r = subprocess.run([sys.executable, "scripts/74_next_game_check.py"],
                       cwd=Path(__file__).resolve().parents[1],
                       capture_output=True, text=True)
    if "No such file" in r.stderr or "pbp.parquet" in r.stderr:
        pytest.skip("no play-by-play on disk")
    assert r.returncode == 0, r.stdout + r.stderr
