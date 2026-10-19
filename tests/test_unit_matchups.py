"""Position group against position group, from the games before this one."""
from __future__ import annotations

import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import unit_matchups as U  # noqa: E402


def plays(rows):
    base = {"season": 2026, "game_id": "g", "play_id": 1, "pass": 0, "sack": 0,
            "qb_hit": 0, "qb_scramble": 0, "receiver_player_id": None,
            "rusher_player_id": None, "rec_pos": None, "rush_pos": None,
            "n_pass_rushers": None, "n_blitzers": None, "yards_gained": 0}
    return pl.DataFrame([base | r for r in rows])


def test_throws_are_grouped_by_the_targets_position_and_only_earlier_weeks_count():
    d = plays([
        # Week 1: one WR target (success) and one TE target, A on offense.
        dict(week=1, posteam="A", defteam="B", play_type="pass",
             receiver_player_id="w", rec_pos="WR", epa=0.5, success=1),
        dict(week=1, posteam="A", defteam="B", play_type="pass",
             receiver_player_id="t", rec_pos="TE", epa=-0.2, success=0),
        # Week 2 is the week being shown: it must not count.
        dict(week=2, posteam="A", defteam="B", play_type="pass",
             receiver_player_id="w", rec_pos="WR", epa=9.0, success=0),
    ])
    g = U._per_game(d, "posteam")
    t = U._totals_through(g, 2)
    r = t.row(0, named=True)
    assert (r["c_wr_n"], r["c_wr_s"], r["c_wr_epa"]) == (1, 1, 0.5)
    assert (r["c_te_n"], r["c_te_epa"]) == (1, -0.2)


def test_a_four_man_sack_needs_the_charting_and_a_blitz_does_not_count():
    d = plays([
        dict(week=1, posteam="A", defteam="B", play_type="pass", sack=1,
             n_pass_rushers=4, epa=-1.0, success=0),
        dict(week=1, posteam="A", defteam="B", play_type="pass", sack=1,
             n_pass_rushers=6, epa=-1.0, success=0),
        dict(week=1, posteam="A", defteam="B", play_type="pass", **{"pass": 1},
             n_pass_rushers=None, epa=0.1, success=1),
    ])
    r = U._per_game(d, "defteam").row(0, named=True)
    assert (r["drop_n"], r["sack_k"]) == (3, 2)
    assert (r["drop4_n"], r["sack4_k"]) == (1, 1), (
        "the blitz sack or the uncharted play reached the four-man split")


def test_a_matchup_pairs_each_unit_with_the_other_sides_defense():
    stats = {"A": {"games": 3, "off": {"wr_epa": (0.3, 50)}, "def": {"wr_epa": (0.0, 40)}},
             "B": {"games": 3, "off": {"wr_epa": (0.1, 45)}, "def": {"wr_epa": (0.2, 60)}}}
    u = U.matchup({"away": "A", "home": "B"}, stats)
    wr = u[0]["rows"][0]["sides"]
    assert [(p["offense"], p["edge"]) for p in wr] == [("A", 0.1), ("B", 0.1)]
    assert wr[0]["off_n"] == 50 and wr[0]["def_n"] == 60
