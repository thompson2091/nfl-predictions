"""A game's roster tab: ESPN's players, ordered by our projection, every slot kept."""
from __future__ import annotations

import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.export import roster  # noqa: E402


def chart(rows):
    return pl.DataFrame([{"team": "SF", "gsis_id": g, "player_name": n,
                          "pos_abb": p, "pos_rank": r} for g, n, p, r in rows])


def test_receivers_are_ordered_by_projection_not_by_espns_rank():
    """ESPN listed Aiyuk at rank 10 and Cooks at 3; the rank is a slot's, not the team's."""
    c = chart([("a", "Aiyuk", "WR", 10), ("b", "Cooks", "WR", 3),
               ("q1", "Purdy", "QB", 1), ("q2", "Jones", "QB", 2)])
    proj = {"a": {"rec_yds": 70.0}, "b": {"rec_yds": 30.0},
            "q2": {"pass_yds": 300.0}, "q1": {"pass_yds": 250.0}}
    got = roster.team_slots(c, "SF", proj, {})
    wr = [s.get("player") for s in got if s["pos"] == "WR"]
    assert wr == ["Aiyuk", "Cooks", None, None, None]
    assert [s.get("player") for s in got if s["pos"] == "QB"] == ["Purdy"], (
        "the quarterback follows the depth chart, not the bigger projection")


def test_a_short_team_keeps_its_empty_slots():
    got = roster.team_slots(chart([("r", "Back", "RB", 1)]), "SF", {}, {})
    assert [s["slot"] for s in got] == (
        ["QB1", "RB1", "RB2", "RB3"] + [f"WR{i}" for i in range(1, 6)]
        + ["TE1", "TE2"])
    assert got[1]["player"] == "Back"
    assert "player" not in got[2], "an empty slot was filled"


def test_an_out_player_falls_below_everyone_expected_to_play():
    """On 2026 week 6 the model still projected an Out back, and he ranked RB1."""
    c = chart([("x", "Hurt", "RB", 1), ("y", "Healthy", "RB", 2)])
    proj = {"x": {"rush_yds": 60.0}, "y": {"rush_yds": 25.0}}
    got = roster.team_slots(c, "SF", proj, {"x": "Out"})
    rb = [s for s in got if s["pos"] == "RB"]
    assert [s.get("player") for s in rb] == ["Healthy", None, None, "Hurt"], (
        "an Out player took a numbered slot or was dropped")
    assert rb[3]["slot"] == "RB" and rb[3]["status"] == "Out"


def test_projections_join_on_id_and_resolve_touchdown_rows_by_team():
    payload = {
        "yards": {"receiving_yards": {"rows": [
            {"player_id": "a", "player_name": "A", "proj": 55.0, "point": 49.5},
            {"player_name": "No Id", "proj": 90.0}]}},
        "receptions": {"rows": [{"player_id": "a", "mu": 4.2}]},
        "markets": [{"key": "anytime_td", "players": [
            {"player": "A", "team": "SF", "ours": 0.31},
            {"player": "A", "team": "LA", "ours": 0.99}]}],
    }
    got = roster.projections(payload, {("SF", "A"): "a"})
    assert got["a"] == {"rec_yds": 55.0, "rec_yds_line": 49.5, "rec": 4.2,
                        "td": 0.31}
    assert len(got) == 1, "a row without an id was matched by name"
