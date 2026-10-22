"""Two rebuilds of identical inputs give identical features.

Measured 2026-10-21: two `04_features` runs on the same raw files differed on
`starter_out_at_position` (134 rows, all 2025) and on `mkt_move_*` nulls
(6 rows). Both came from a deduplication that read row order, and row order
out of a polars join is not fixed. Each test feeds one builder the same rows
in different orders and asks for one answer.
"""
from __future__ import annotations

import polars as pl

from src.features import context_features as CF


def _weekly(order):
    rows = [
        {"player_id": "wr_b", "season": 2025, "week": 3, "team": "KC",
         "position": "WR", "depth_rank": 2},
        {"player_id": "wr_a", "season": 2025, "week": 3, "team": "KC",
         "position": "WR", "depth_rank": 1},
        {"player_id": "wr_c", "season": 2025, "week": 3, "team": "KC",
         "position": "WR", "depth_rank": 1},
    ]
    return pl.DataFrame([rows[i] for i in order]).with_columns(
        pl.col("depth_rank").cast(pl.Int32))


def test_the_starter_is_the_same_whatever_the_row_order(monkeypatch):
    got = set()
    for order in ([0, 1, 2], [2, 1, 0], [1, 0, 2], [2, 0, 1]):
        monkeypatch.setattr(CF, "dc_new_weekly",
                            lambda dc, sched, o=order: _weekly(o))
        s = CF.starter_lookup(None, pl.DataFrame({"pos_rank": [1]}),
                              pl.DataFrame({"season": [2025]}), {"WR": 2})
        got.add(tuple(s["starter_id"].to_list()))
    # Top of the chart, ties to the lower id, every time.
    assert got == {("wr_a",)}


def test_two_players_sharing_a_name_keep_their_own_games(monkeypatch):
    from src.features import market_movement_features as MM

    mv = pl.DataFrame({
        "season": [2026] * 2, "week": [7] * 2,
        "game_id": ["2026_07_MIN_PHI", "2026_07_LV_KC"],
        "player_name_norm": ["justin jefferson"] * 2,
        "move": [0.02, -0.01],
    })
    for frame in (mv, mv.reverse()):
        monkeypatch.setattr("src.evaluation.clv.line_movement",
                            lambda target_type="anytime_td", f=frame: f)
        out = MM.build_market_movement_features().sort("game_id")
        assert out["game_id"].to_list() == ["2026_07_LV_KC", "2026_07_MIN_PHI"]
        assert out["mkt_move_pp"].to_list() == [-1.0, 2.0]
