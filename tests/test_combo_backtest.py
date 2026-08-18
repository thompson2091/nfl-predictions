"""Grading a slip against results, on outcomes small enough to check by hand.

The replay is the only thing standing between the combinations table and a set
of confident numbers nobody has ever checked, so its arithmetic gets the same
treatment as the table's.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.evaluation import combo_backtest as cb


def board(scored, dec=None):
    """A graded week: one row per player, in the order slips index into."""
    n = len(scored)
    return pd.DataFrame({
        "player_name": [f"p{i}" for i in range(n)],
        "game_label": [f"G{i}" for i in range(n)],
        "scored": scored,
        "decimal_odds": dec if dec is not None else [2.0] * n,
    })


def slips(legs, odds):
    """Slips as `build` returns them: legs by position, price in American."""
    return pd.DataFrame({"_legs": legs, "Odds": odds,
                         "Ours": [10.0] * len(legs),
                         "Book": [5.0] * len(legs)})


# ── Grading ────────────────────────────────────────────────────────────────


def test_a_slip_lands_only_when_every_leg_scores():
    out = cb.grade(board([1, 1, 0]), slips([(0, 1), (0, 2), (1, 2)], [300] * 3))
    assert out["landed"].tolist() == [True, False, False]


def test_a_losing_slip_loses_the_whole_stake():
    out = cb.grade(board([1, 0]), slips([(0, 1)], [300]))
    assert out["paid"].tolist() == [-1.0]


def test_a_winning_slip_pays_the_price():
    """+300 is 4.0 decimal: $100 comes back as $400, so profit is 3x stake."""
    out = cb.grade(board([1, 1]), slips([(0, 1)], [300]))
    assert out["paid"].tolist() == pytest.approx([3.0])


def test_the_same_money_as_singles_is_the_average_of_the_legs():
    """One leg at 2.0 wins (+1), one loses (-1): staked separately, that is 0."""
    out = cb.grade(board([1, 0], dec=[2.0, 2.0]), slips([(0, 1)], [300]))
    assert out["split_paid"].tolist() == pytest.approx([0.0])
    assert out["paid"].tolist() == [-1.0]                  # as a slip, nothing


def test_singles_and_slips_disagree_on_purpose():
    """Two 3.0 legs: as singles +$200 a leg, as a slip +$800 or nothing."""
    won = cb.grade(board([1, 1], dec=[3.0, 3.0]), slips([(0, 1)], [800]))
    assert won["split_paid"].tolist() == pytest.approx([2.0])
    assert won["paid"].tolist() == pytest.approx([8.0])


def test_grading_nothing_returns_the_columns_anyway():
    out = cb.grade(board([1, 1]), pd.DataFrame(columns=["_legs", "Odds"]))
    assert {"landed", "paid", "split_paid"} <= set(out.columns)


# ── The summary ────────────────────────────────────────────────────────────


def graded(n_win, n_lose, dec=4.0):
    rows = []
    for i in range(n_win + n_lose):
        won = i < n_win
        rows.append({"landed": won, "paid": (dec - 1.0) if won else -1.0,
                     "split_paid": 0.5 if won else -0.5,
                     "Ours": 20.0, "Book": 10.0, "_week": f"2025-{i % 4 + 1:02d}"})
    return pd.DataFrame(rows)


def test_summary_reports_the_rate_the_count_and_the_money():
    out = cb.summarise(graded(25, 75))
    assert out["slips"] == 100
    assert out["landed"] == pytest.approx(0.25)
    assert out["we_said"] == pytest.approx(0.20)
    assert out["book_said"] == pytest.approx(0.10)
    # 25 wins at +3 units, 75 losses at -1: (75 - 75) / 100 = break even.
    assert out["return_per_100"] == pytest.approx(0.0)
    assert out["weeks"] == 4


def test_an_empty_replay_summarises_to_no_slips_rather_than_zeroes():
    """A rate of 0% and no slips at all are different claims."""
    assert cb.summarise(pd.DataFrame()) == {"slips": 0}


def test_return_without_the_biggest_wins_drops_exactly_ten():
    pnl = np.array([9.0] * 10 + [-1.0] * 10)
    assert cb._ex_top10(pnl) == pytest.approx(-100.0)


def test_no_return_without_the_biggest_wins_when_that_is_everything():
    assert cb._ex_top10(np.array([3.0] * 10)) is None


def test_concentrated_profit_shows_up_as_the_gap_between_the_two():
    """The whole point: one afternoon carrying a headline return."""
    slips_ = graded(1, 99, dec=400.0)
    whole = cb.summarise(slips_)["return_per_100"]
    rest = cb.summarise(slips_)["return_ex_top10"]
    assert whole > 200 and rest == pytest.approx(-100.0)


# ── Lookup ─────────────────────────────────────────────────────────────────


ARTIFACT = {"rows": [{"legs": 2, "per_game": 4, "metric": "ev", "show": 25,
                      "slips": 10}]}


def test_lookup_finds_the_measured_setting():
    assert cb.lookup(ARTIFACT, legs=2, per_game=4, metric="ev", show=25)["slips"] == 10


@pytest.mark.parametrize("change", [{"legs": 3}, {"per_game": 5},
                                    {"metric": "likely"}, {"show": 50}])
def test_lookup_refuses_to_answer_for_a_setting_it_did_not_measure(change):
    """A nearby answer would describe a different table than the one shown."""
    ask = {"legs": 2, "per_game": 4, "metric": "ev", "show": 25, **change}
    assert cb.lookup(ARTIFACT, **ask) is None


def test_lookup_without_an_artifact_is_not_an_error():
    assert cb.lookup(None, legs=2, per_game=4, metric="ev", show=25) is None


# ── Reading the backtest files ─────────────────────────────────────────────


def write_backtest(tmp_path, name="backtest_xgb_2025.csv", **overrides):
    frame = pd.DataFrame({
        "player_name": ["a", "b"], "game_id": ["G1", "G1"], "week": [1, 1],
        "odds": [100, 150], "dec": [2.0, 2.5], "final": [0.5, 0.4],
        "prob_calibrated": [0.55, 0.45], "market_prob": [0.45, 0.35],
        "scored": [1, 0], "has_market_price": [True, True], **overrides,
    })
    frame.to_csv(tmp_path / name, index=False)
    return tmp_path


def test_load_weeks_renames_backtest_columns_into_a_board(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "get_path", lambda *a, **k: write_backtest(tmp_path))
    weeks = cb.load_weeks("anytime_td", "xgb")
    assert len(weeks) == 1
    wk = weeks[0]
    assert (wk["season"], wk["week"]) == (2025, 1)
    assert {"player_name", "game_label", "probability", "prob_bet",
            "market_prob", "decimal_odds", "scored"} <= set(wk["board"].columns)
    # The published number, not the pre-blend one, is what the board shows.
    assert wk["board"]["probability"].tolist() == [0.5, 0.4]
    assert wk["board"]["prob_bet"].tolist() == [0.55, 0.45]


def test_load_weeks_drops_players_no_book_priced(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "get_path", lambda *a, **k: write_backtest(
        tmp_path, has_market_price=[True, False]))
    assert len(cb.load_weeks("anytime_td", "xgb")[0]["board"]) == 1


def test_load_weeks_ignores_another_models_files(tmp_path, monkeypatch):
    write_backtest(tmp_path, name="backtest_lgbm_2025.csv")
    monkeypatch.setattr(cb, "get_path", lambda *a, **k: tmp_path)
    assert cb.load_weeks("anytime_td", "xgb") == []


def test_no_backtest_measures_to_nothing_rather_than_an_empty_record(
        tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "get_path", lambda *a, **k: tmp_path)
    assert cb.measure("anytime_td", "xgb") is None
