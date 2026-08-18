"""The combination table's arithmetic, on boards small enough to check by hand.

The point of these is that a parlay row is four multiplications away from the
board, and every one of them is easy to get subtly wrong in a way that still
prints a plausible percentage.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.prediction.bets import american_to_decimal, decimal_to_american
from src.prediction.combos import build, pool


def board(rows: list[dict]) -> pd.DataFrame:
    """A board with the columns `combos` reads, defaults filled in."""
    frame = pd.DataFrame(rows)
    frame["market_prob"] = frame.get("market_prob", frame["probability"])
    return frame


def player(name, game, prob, odds, *, market_prob=None, rank=1, **extra):
    return {"player_name": name, "game_label": game, "probability": prob,
            "odds": odds, "market_prob": prob if market_prob is None else market_prob,
            "game_rank": rank, **extra}


# ── Odds ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("odds", [-250, -150, -110, 100, 120, 250, 900])
def test_american_decimal_round_trip(odds):
    assert decimal_to_american(american_to_decimal(odds)) == pytest.approx(odds)


def test_decimal_to_american_rejects_a_price_that_cannot_lose():
    with pytest.raises(ValueError):
        decimal_to_american(1.0)


# ── The arithmetic ─────────────────────────────────────────────────────────


def test_two_even_money_legs_price_and_probability():
    """Two 50% legs at +100: a quarter of the time, paying 4x. EV is zero."""
    frame = board([player("A", "X @ Y", 0.5, 100),
                   player("B", "P @ Q", 0.5, 100)])
    out = build(frame, legs=2, per_game=1)
    assert len(out) == 1
    row = out.iloc[0]
    assert row["Ours"] == pytest.approx(25.0)
    assert row["Book"] == pytest.approx(25.0)
    assert row["Odds"] == pytest.approx(300.0)
    assert row["EV"] == pytest.approx(0.0)
    assert row["Game"] == "2 games"
    assert not row["SameGame"]


def test_edge_and_ev_use_the_columns_the_board_uses():
    """Difference is published-vs-book; EV is pre-blend at the posted price."""
    frame = board([
        player("A", "X @ Y", 0.60, 100, market_prob=0.50, prob_bet=0.70),
        player("B", "P @ Q", 0.50, 100, market_prob=0.40, prob_bet=0.60),
    ])
    row = build(frame, legs=2, per_game=1).iloc[0]
    assert row["Ours"] == pytest.approx(30.0)                  # .60 * .50
    assert row["Book"] == pytest.approx(20.0)                  # .50 * .40
    assert row["edge_pp"] == pytest.approx(10.0)
    # .70 * .60 = .42 at 4.0 decimal -> 1.68 back per 1 staked.
    assert row["EV"] == pytest.approx(68.0)


def test_ev_falls_back_to_the_published_probability_without_a_preblend_column():
    frame = board([player("A", "X @ Y", 0.5, 100),
                   player("B", "P @ Q", 0.5, 100)])
    assert build(frame, legs=2, per_game=1).iloc[0]["EV"] == pytest.approx(0.0)


# ── Same game ──────────────────────────────────────────────────────────────


def test_anytime_td_keeps_same_game_combinations_and_flags_them():
    frame = board([player("A", "X @ Y", 0.5, 100, rank=1),
                   player("B", "X @ Y", 0.4, 150, rank=2)])
    out = build(frame, legs=2, per_game=2, target_type="anytime_td")
    assert len(out) == 1
    assert out.iloc[0]["SameGame"]
    assert out.iloc[0]["Game"] == "X @ Y"


def test_first_td_drops_same_game_combinations_entirely():
    """Only one player scores first, so the joint probability is zero, not 20%."""
    frame = board([player("A", "X @ Y", 0.5, 100, rank=1),
                   player("B", "X @ Y", 0.4, 150, rank=2)])
    assert build(frame, legs=2, per_game=2, target_type="first_td").empty


def test_first_td_keeps_combinations_across_games():
    frame = board([player("A", "X @ Y", 0.5, 100), player("B", "X @ Y", 0.4, 150, rank=2),
                   player("C", "P @ Q", 0.3, 250), player("D", "P @ Q", 0.2, 400, rank=2)])
    out = build(frame, legs=2, per_game=2, target_type="first_td")
    assert len(out) == 4                                       # 2 x 2, none same-game
    assert not out["SameGame"].any()


# ── The pool ───────────────────────────────────────────────────────────────


def test_pool_takes_each_games_top_n():
    frame = board([player(f"{g}{r}", g, 0.5 - r / 100, 100, rank=r)
                   for g in ("X @ Y", "P @ Q") for r in (1, 2, 3)])
    assert sorted(pool(frame, 2)["player_name"]) == ["P @ Q1", "P @ Q2",
                                                     "X @ Y1", "X @ Y2"]


def test_pool_ranks_the_board_itself_when_it_has_no_ranking():
    frame = board([player("A", "X @ Y", 0.2, 400), player("B", "X @ Y", 0.6, 100)])
    frame = frame.drop(columns=["game_rank"])
    assert pool(frame, 1)["player_name"].tolist() == ["B"]


def test_pool_drops_players_the_injury_report_has_ruled_out():
    frame = board([player("A", "X @ Y", 0.5, 100, is_blocked=True),
                   player("B", "P @ Q", 0.5, 100, is_blocked=False)])
    assert pool(frame, 1)["player_name"].tolist() == ["B"]


def test_pool_drops_players_with_no_price():
    frame = board([player("A", "X @ Y", 0.5, None), player("B", "P @ Q", 0.5, 100)])
    assert pool(frame, 1)["player_name"].tolist() == ["B"]


def test_build_needs_the_board_columns():
    with pytest.raises(KeyError):
        build(pd.DataFrame({"player_name": ["A"]}), legs=2)


# ── Ranking and bounds ─────────────────────────────────────────────────────


def slate(n_games: int = 6, per_game: int = 4) -> pd.DataFrame:
    return board([
        player(f"g{g}p{r}", f"G{g}", 0.55 - 0.05 * r - 0.01 * g,
               100 + 40 * r + 5 * g, market_prob=0.50 - 0.05 * r, rank=r)
        for g in range(n_games) for r in range(1, per_game + 1)
    ])


def test_ranking_by_likelihood_leads_with_the_likeliest_combination():
    out = build(slate(), legs=2, per_game=4, top_k=5, metric="likely")
    assert out["Ours"].is_monotonic_decreasing
    assert out.iloc[0]["Players"] == "g0p1 + g1p1"


def test_ranking_by_ev_leads_with_the_best_expectation():
    out = build(slate(), legs=2, per_game=4, top_k=5, metric="ev")
    assert out["EV"].is_monotonic_decreasing
    assert out["EV"].iloc[0] >= out["EV"].max()


def test_top_k_bounds_the_table():
    assert len(build(slate(), legs=3, per_game=4, top_k=7)) == 7


@pytest.mark.parametrize("metric", ["ev", "likely"])
@pytest.mark.parametrize("legs", [2, 3])
def test_truncating_the_candidate_pool_does_not_change_the_answer(metric, legs):
    """The whole point of the bound: searching fewer legs, same top of table."""
    frame = slate(n_games=8, per_game=4)
    cut = build(frame, legs=legs, per_game=4, top_k=10, metric=metric)
    full = build(frame, legs=legs, per_game=4, top_k=10, metric=metric,
                 max_candidates=32)
    assert cut["Players"].tolist() == full["Players"].tolist()
    assert cut.attrs["n_candidates"] < full.attrs["n_candidates"]


def test_a_pool_smaller_than_the_leg_count_returns_nothing():
    frame = board([player("A", "X @ Y", 0.5, 100)])
    assert build(frame, legs=3, per_game=4).empty


def test_a_single_leg_is_not_a_combination():
    with pytest.raises(ValueError):
        build(slate(), legs=1)


def test_an_unknown_ranking_is_refused_rather_than_guessed():
    with pytest.raises(ValueError):
        build(slate(), legs=2, metric="vibes")
