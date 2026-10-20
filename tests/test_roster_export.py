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
    assert got["a"]["rec_yds"] == 55.0 and got["a"]["rec_yds_line"] == 49.5
    assert got["a"]["rec"] == 4.2 and got["a"]["td"] == 0.31
    assert len(got) == 1, "a row without an id was matched by name"


def test_each_market_carries_model_book_and_adjusted_off_the_consensus_line():
    """A player can have six yardage rows; the tab quotes the one Props leads with."""
    row = {"player_id": "a", "proj": 60.0, "model_only": 0.7, "ours": 0.55}
    payload = {"yards": {"rushing_yards": {"rows": [
        dict(row, point=52.5, odds=-110, fair_prob=0.5, best_line=True),
        dict(row, point=58.5, odds=120, fair_prob=0.44, best_line=False)]}},
        "markets": [{"key": "anytime_td", "players": [
            {"player_id": "a", "ours": 0.4, "model_only": 0.45, "book": 0.38,
             "odds_num": 140.0}]}]}
    got = roster.projections(payload)["a"]
    assert (got["rush_yds_line"], got["rush_yds_odds"]) == (52.5, -110)
    assert (got["rush_yds_model"], got["rush_yds_book"], got["rush_yds_adj"]) == (
        0.7, 0.5, 0.55)
    assert (got["td_model"], got["td_book"], got["td_adj"], got["td_odds"]) == (
        0.45, 0.38, 0.4, 140.0)


def test_the_team_line_adds_averages_of_the_numbered_slots_only():
    """Medians of the shown receivers read 50 yards under Purdy; averages add."""
    slots = [{"slot": "QB1", "pos": "QB", "player": "Q", "player_id": "q"},
             {"slot": "WR1", "pos": "WR", "player": "A", "player_id": "a"},
             {"slot": "WR2", "pos": "WR"},
             {"slot": "WR", "pos": "WR", "player": "Hurt", "player_id": "h"}]
    avg = {"q": {"pass_avg": 254.0}, "a": {"rec_avg": 80.0},
           "h": {"rec_avg": 40.0}}
    got = roster.team_line(slots, avg)
    assert got == {"rec_avg": 80.0, "pass_avg": 254.0, "n": 1, "qb": "Q"}, (
        "an Out player or an empty slot was counted")


def test_an_unfinished_game_is_pending_not_did_not_play(monkeypatch):
    """With no box score yet, all 36 WAS @ SF players read "Did not play"."""
    from src.evaluation import tracked_rules

    cards = [{"game_id": "WAS_SF", "away": "WAS", "home": "SF"}]
    monkeypatch.setattr(tracked_rules, "unfinished",
                        lambda s, w: ({"2026_06_WAS_SF"}, {"WAS @ SF"}))
    out = roster.build_past(2026, 6, cards)
    if not out:
        import pytest
        pytest.skip("no 2026 week 6 chart or freeze on disk")
    slots = [s for t in out["WAS_SF"].values()
             for s in (t if isinstance(t, list) else t.get("slots", []))
             if isinstance(s, dict) and s.get("player_id")]
    # Every player with a frozen projection is pending; one without (a backup
    # nobody projected) carries nothing to grade either way.
    assert any(s.get("pending") for s in slots)
    assert not any(s.get("void") for s in slots)
