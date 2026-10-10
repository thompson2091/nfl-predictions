"""The forward log, the started-game guard on the board CSV, and the files
that are now kept rather than overwritten."""
from __future__ import annotations

import csv
import json
from datetime import datetime

import polars as pl
import pytest

from src.evaluation import tracked_rules as TR

KICKS = {"2026_05_A_B": datetime(2026, 10, 8, 20, 15),     # Thursday
         "2026_05_C_D": datetime(2026, 10, 11, 13, 0)}     # Sunday
FRIDAY = datetime(2026, 10, 9, 12, 0)


@pytest.fixture(autouse=True)
def _kicks(monkeypatch):
    monkeypatch.setattr(TR, "kickoffs", lambda season, week: dict(KICKS))


def pick(player, game, rule="model side"):
    return {"rule": rule, "player": player, "team": None, "game": game,
            "odds": -110, "ours": 0.52, "book": 0.50, "edge_pp": 2.0,
            "side": "over", "line": 40.5, "model": 0.57}


def test_an_over_under_pick_is_gated_on_its_own_game_not_the_weeks_first(tmp_path):
    """Thursday's kickoff used to close the book on every Sunday game."""
    p = tmp_path / "picks.csv"
    n = TR.record([pick("Thu Man", "A @ B"), pick("Sun Man", "C @ D")],
                  season=2026, week=5, market="rushing_yards",
                  recorded_on="2026-10-09", path=p, now=FRIDAY)
    assert n == 1
    got = TR.load(p)
    assert got["player"].to_list() == ["Sun Man"]
    assert got["recorded_at"][0] == "2026-10-09T12:00:00"
    assert got["model"][0] == "0.57"


def test_a_touchdown_pick_keeps_the_week_level_gate(tmp_path):
    n = TR.record([pick("Sun Man", "C @ D", rule="mid-price disagreement")],
                  season=2026, week=5, market="anytime_td",
                  recorded_on="2026-10-09", path=tmp_path / "p.csv", now=FRIDAY)
    assert n == 0


def test_model_side_rows_are_recorded_once(tmp_path):
    p = tmp_path / "picks.csv"
    for _ in range(2):
        TR.record([pick("Sun Man", "C @ D")], season=2026, week=5,
                  market="rushing_yards", recorded_on="2026-10-09", path=p,
                  now=FRIDAY)
    assert TR.load(p).height == 1


def test_an_old_file_is_migrated_with_a_copy_left_beside_it(tmp_path):
    p = tmp_path / "tracked_picks.csv"
    old = [c for c in TR.COLUMNS if c not in ("recorded_at", "model")]
    with p.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=old)
        w.writeheader()
        w.writerow({c: "x" for c in old})
    assert TR.migrate(p) is True
    with p.open() as fh:
        rd = csv.DictReader(fh)
        assert rd.fieldnames == list(TR.COLUMNS)
        row = next(rd)
    assert row["player"] == "x" and row["recorded_at"] == ""
    assert list(tmp_path.glob("tracked_picks.pre-migrate-*.csv"))
    assert TR.migrate(p) is False


def test_the_board_csv_keeps_a_started_games_rows(tmp_path, monkeypatch):
    """A rebuild after kickoff lost the prices: week 4 went to 47 priced of 515."""
    from src.prediction import predict as P

    monkeypatch.setattr("src.export.prediction_freeze.started_games",
                        lambda season, week: {"2026_05_A_B"})
    p = tmp_path / "predictions_2026_week5.csv"
    pl.DataFrame({"game_id": ["2026_05_A_B", "2026_05_C_D"],
                  "player_name": ["Thu Man", "Sun Man"],
                  "probability": [0.40, 0.30],
                  "has_market_price": [True, True]}).write_csv(p)
    new = pl.DataFrame({"game_id": ["2026_05_A_B", "2026_05_C_D"],
                        "player_name": ["Thu Man", "Sun Man"],
                        "probability": [0.10, 0.35],
                        "has_market_price": [False, True]})
    out = P._keep_started(new, p, 2026, 5).sort("player_name")
    assert out.filter(pl.col("player_name") == "Thu Man")["probability"][0] == 0.40
    assert out.filter(pl.col("player_name") == "Thu Man")["has_market_price"][0] is True
    assert out.filter(pl.col("player_name") == "Sun Man")["probability"][0] == 0.35


def test_a_refit_file_keeps_its_previous_copy(tmp_path):
    from src.utils.history import write_kept

    p = tmp_path / "blend_weight.json"
    assert write_kept(p, json.dumps({"w": 0.3})) is None
    assert write_kept(p, json.dumps({"w": 0.3})) is None, "no change, no copy"
    kept = write_kept(p, json.dumps({"w": 0.4}))
    assert kept is not None and json.loads(kept.read_text()) == {"w": 0.3}
    assert json.loads(p.read_text()) == {"w": 0.4}


def test_a_run_manifest_line_says_what_produced_the_board(tmp_path, monkeypatch):
    from src.export import run_manifest as RM

    monkeypatch.setattr(RM, "RUNS", tmp_path / "runs")
    p = RM.append("anytime_td", 2026, 5, rows=10)
    line = json.loads(p.read_text().splitlines()[-1])
    for k in ("at", "commit", "dirty", "version", "served", "features",
              "odds_captured_at", "rows"):
        assert k in line, k


def test_the_forward_record_grades_each_pick_at_its_own_price(monkeypatch):
    """Settled the way a book settles, per game, never pooled with the rebuild."""
    from src.evaluation import forward_record as FR

    base = {"season": 2026, "week": 5, "source": None}
    picks = [
        # Over 40.5, had 52: a win at +120.
        dict(base, market="rushing_yards", rule="model side", player="Win Man",
             game="C @ D", odds=120, side="over", line=40.5, model=0.6),
        # Under 3.5 catches, had 5: a loss.
        dict(base, market="receptions", rule="model side", player="Lose Man",
             game="C @ D", odds=-110, side="under", line=3.5, model=0.4),
        # No snap, no stat line: void, not a loss.
        dict(base, market="receptions", rule="model side", player="Scratch Man",
             game="C @ D", odds=-110, side="over", line=2.5, model=0.6),
        # Monday night, no final yet: pending.
        dict(base, market="rushing_yards", rule="model side", player="Late Man",
             game="E @ F", odds=-110, side="over", line=60.5, model=0.6),
        dict(base, market="rushing_yards", rule="prop edge over threshold",
             player="Late Man", game="E @ F", odds=-110, side="over",
             line=60.5, model=0.6),
    ]
    monkeypatch.setattr(FR, "_actuals", lambda season, week, market: {
        "Win Man": 52.0, "Lose Man": 5.0})
    monkeypatch.setattr("src.evaluation.prop_settlement.participation",
                        lambda season: {})
    monkeypatch.setattr("src.evaluation.tracked_rules.unfinished",
                        lambda season, week: ({"2026_05_E_F"}, {"E @ F"}))
    b = FR.block(2026, picks)
    assert b["pending"] == 1 and b["weeks"] == [5]
    model = b["rules"][0]
    assert model["label"] == "Our model"
    assert model["all"]["bets"] == 2, "the scratch was graded as a bet"
    assert model["all"]["roi"] == pytest.approx((1.2 - 1.0) / 2)
    rush = [m for m in model["markets"] if m["key"] == "rushing_yards"][0]
    assert rush["hit"] == 1.0 and rush["candidate"] is False, (
        "one game cannot make a market a candidate")
    assert b["rules"][1]["all"] is None, "a pending pick was graded"


def test_picks_are_read_off_the_frozen_board_one_line_a_player(monkeypatch):
    """The line nearest the player's median, then each rule's side on it."""
    from src.evaluation import forward_record as FR
    from src.export import prediction_freeze as PF

    board = {"2": {"rushing_yards": {"2026_02_C_D": [
        {"player_name": "Alt Man", "point": p, "model_only": 0.6,
         "model_side": "over", "price_over": -110, "price_under": -110,
         "gap_side": "over" if p == 60.5 else None, "source": "x.html"}
        for p in (40.5, 60.5, 80.5)]}}}
    monkeypatch.setattr(PF, "load", lambda season: board)
    got = FR._picks_from_boards(2026)
    assert [(g["rule"], g["line"]) for g in got] == [
        ("model side", 60.5), ("prop edge over threshold", 60.5)]
    assert got[0]["game"] == "C @ D" and got[0]["source"] == "x.html"


def test_the_selection_rules_are_subsets_and_count_from_their_own_week(monkeypatch):
    """`model confident` counts from week 2 (its cut came from 2024-25);
    `model under` from week 6 (it was read off weeks 2-4)."""
    from src.evaluation import forward_record as FR
    from src.export import prediction_freeze as PF

    def board(wk, side, m):
        return {"rushing_yards": {f"2026_{wk:02d}_C_D": [
            {"player_name": "P", "point": 50.5, "model_only": m,
             "model_side": side, "price_over": -110, "price_under": -110,
             "version": "v1"}]}}
    store = {"3": board(3, "under", 0.2), "6": board(6, "under", 0.4)}
    monkeypatch.setattr(PF, "load", lambda season: store)
    got = {(p["rule"], p["week"]) for p in FR._picks_from_boards(2026)}
    assert ("model confident", 3) in got, "0.8 sure on the under is confident"
    assert ("model confident", 6) not in got, "0.6 sure is not"
    assert ("model under", 3) not in got, "week 3 cannot test a week-2-4 finding"
    assert ("model under", 6) in got


def test_clv_takes_the_markets_own_drift_out(monkeypatch):
    """A close that moved only as far as every over/under moves is no skill."""
    from src.evaluation import forward_record as FR

    picks = pl.DataFrame([
        {"season": "2026", "week": "5", "market": "rushing_yards",
         "rule": "model side", "player": "Over Man", "game": "C @ D",
         "book": "0.50", "line": "50.5", "side": "over",
         "recorded_at": "2026-10-07T12:00:00"},
        {"season": "2026", "week": "5", "market": "rushing_yards",
         "rule": "model side", "player": "Under Man", "game": "C @ D",
         "book": "0.50", "line": "40.5", "side": "under",
         "recorded_at": "2026-10-07T12:00:00"},
    ])
    monkeypatch.setattr(FR, "_close_fair", lambda season: {
        ("2026_05_C_D", "over man", "rushing_yards", 50.5): 0.503,
        ("2026_05_C_D", "under man", "rushing_yards", 40.5): 0.503})
    monkeypatch.setattr("src.evaluation.ou_shortlist.pairs", lambda m: None)
    monkeypatch.setattr("src.evaluation.ou_shortlist.drift",
                        lambda pr: 0.3)
    monkeypatch.setattr("src.evaluation.prop_settlement._norm",
                        lambda names: [n.lower() for n in names])
    c = FR.clv(2026, picks)["model side"]
    assert c["n"] == 2
    # Both closes moved +0.3pp on the over, which is exactly the drift: the
    # over gained nothing and the under lost nothing.
    assert c["mean"] == pytest.approx(0.0, abs=1e-9)
