"""Regression tests for the diagnosis.

A diagnosis that is wrong sends Phase 3 at the half of the problem that was
already fine, which is the most expensive kind of wrong available here — it
costs weeks and looks like progress the whole time.

    pytest tests/test_diagnose.py -v
"""
from __future__ import annotations

import polars as pl
import pytest

from src.evaluation import diagnose as D


def _players(rows: list[dict]) -> pl.DataFrame:
    """game_id, team, prob, target -> ranked player rows."""
    df = pl.DataFrame(rows)
    return df.with_columns(
        pl.col("prob").rank(descending=True, method="ordinal")
        .over("game_id").alias("rank"))


# --------------------------------------------------------------------------
# Team vs player
# --------------------------------------------------------------------------

def test_right_team_wrong_player_is_not_counted_as_a_wrong_team():
    """The split that decides which half of the model to work on.

    Anytime TD is team_lambda x share. A miss where a teammate scored says the
    rate was right and the share was wrong; a miss where nobody on that team
    scored says the opposite. Conflating them points the work at the wrong
    factor.
    """
    players = _players([
        # g1: our pick scored.
        {"game_id": "g1", "player_id": "a", "team": "KC", "prob": .9, "target": 1},
        {"game_id": "g1", "player_id": "b", "team": "KC", "prob": .5, "target": 0},
        # g2: teammate of our pick scored.
        {"game_id": "g2", "player_id": "c", "team": "KC", "prob": .9, "target": 0},
        {"game_id": "g2", "player_id": "d", "team": "KC", "prob": .5, "target": 1},
        # g3: the other team scored.
        {"game_id": "g3", "player_id": "e", "team": "KC", "prob": .9, "target": 0},
        {"game_id": "g3", "player_id": "f", "team": "BUF", "prob": .5, "target": 1},
    ])
    r = D.team_vs_player(players)
    assert (r["hit"], r["right_team_wrong_player"], r["wrong_team"]) == (1, 1, 1)
    assert r["of_misses_right_team"] == pytest.approx(0.5)
    assert r["of_misses_wrong_team"] == pytest.approx(0.5)


def test_a_game_with_no_scorer_on_either_team_counts_as_wrong_team():
    players = _players([
        {"game_id": "g1", "player_id": "a", "team": "KC", "prob": .9, "target": 0},
        {"game_id": "g1", "player_id": "b", "team": "BUF", "prob": .5, "target": 0},
    ])
    assert D.team_vs_player(players)["wrong_team"] == 1


# --------------------------------------------------------------------------
# Market benchmark
# --------------------------------------------------------------------------

def _priced_game(game: str, n: int, scorer_at_model_rank: int,
                 scorer_at_market_rank: int) -> tuple[list, list]:
    """One game where model and book rank the same n players differently."""
    players, graded = [], []
    for i in range(n):
        pid = f"{game}-p{i}"
        players.append({"game_id": game, "player_id": pid, "team": "KC",
                        "prob": 1.0 - i * 0.01,
                        "target": 1 if i == scorer_at_model_rank - 1 else 0})
        graded.append({"game_id": game, "player_id": pid,
                       "implied_prob": None, "fair_prob": None})
    # The book's ordering: put the scorer at the requested rank.
    order = [p["player_id"] for p in players]
    scorer = players[scorer_at_model_rank - 1]["player_id"]
    order.remove(scorer)
    order.insert(scorer_at_market_rank - 1, scorer)
    for rank, pid in enumerate(order):
        for g in graded:
            if g["player_id"] == pid:
                g["implied_prob"] = 1.0 - rank * 0.01
    return players, graded


def test_market_benchmark_ranks_both_sides_over_the_same_player_set():
    """Comparing a ranking over 33 candidates with one over 27 is not a
    comparison. Both sides rank the priced players only."""
    players, graded = [], []
    for i in range(6):                       # model right, book wrong
        p, g = _priced_game(f"win{i}", 10, 1, 4)
        players += p
        graded += g
    for i in range(2):                       # book right, model wrong
        p, g = _priced_game(f"lose{i}", 10, 4, 1)
        players += p
        graded += g

    r = D.market_benchmark(pl.DataFrame(players), pl.DataFrame(graded))
    assert r["available"] and r["games"] == 8
    assert r["top1"]["model"] == pytest.approx(6 / 8)
    assert r["top1"]["market"] == pytest.approx(2 / 8)
    assert r["top1"]["model_wins"] == 6 and r["top1"]["market_wins"] == 2


def test_thinly_priced_games_are_excluded_and_reported():
    """A book that priced four players is offering a shortlist, not a ranking."""
    players, graded = _priced_game("thin", 4, 1, 1)
    deep_p, deep_g = _priced_game("deep", 10, 1, 1)
    r = D.market_benchmark(pl.DataFrame(players + deep_p),
                           pl.DataFrame(graded + deep_g))
    assert r["games"] == 1 and r["games_dropped_thin"] == 1


def test_market_benchmark_prefers_the_two_sided_fair_price():
    """One-sided de-vig is a per-game scalar and cannot reorder a game; the
    two-sided fair price can, so it wins where it exists."""
    players = _players([
        {"game_id": "g", "player_id": "a", "team": "KC", "prob": .9, "target": 0},
        {"game_id": "g", "player_id": "b", "team": "KC", "prob": .1, "target": 1},
    ])
    graded = pl.DataFrame([
        {"game_id": "g", "player_id": "a", "implied_prob": 0.9, "fair_prob": 0.1},
        {"game_id": "g", "player_id": "b", "implied_prob": 0.1, "fair_prob": 0.9},
    ])
    r = D.market_benchmark(players, graded)
    # Only two priced players, so the game is dropped as thin — but the
    # ordering logic is what is under test, so check it directly.
    assert r["available"] is False or r["games"] == 0

    wide = pl.concat([graded] + [pl.DataFrame([
        {"game_id": "g", "player_id": f"x{i}", "implied_prob": 0.05,
         "fair_prob": 0.05}]) for i in range(8)])
    wide_players = pl.concat([players.drop("rank"), pl.DataFrame([
        {"game_id": "g", "player_id": f"x{i}", "team": "KC", "prob": 0.05,
         "target": 0} for i in range(8)])], how="diagonal_relaxed")
    r = D.market_benchmark(wide_players, wide)
    assert r["top1"]["market"] == 1.0, "the book ranked the scorer first on fair_prob"
    assert r["top1"]["model"] == 0.0


# --------------------------------------------------------------------------
# Winnability and the pool
# --------------------------------------------------------------------------

def test_coin_flips_are_reported_separately_from_decided_games():
    outcomes = pl.DataFrame({
        "game_id": ["a", "b", "c", "d"],
        "best_rank": [1, 2, 1, 3],
        "top_gap": [0.001, 0.002, 0.20, 0.30],
        "hit1": [True, False, True, False],
    })
    w = D.winnability(outcomes)
    assert w["coin_flip_games"] == 2
    assert w["top1_in_coin_flips"] == pytest.approx(0.5)
    assert w["top1_in_decided"] == pytest.approx(0.5)


def test_pool_ceiling_separates_a_data_gap_from_a_filter_loss():
    """Two different problems that used to be one number.

    A game with no scorer anywhere in the pool is a labelling gap no ranking
    can win. A game whose scorer the filter removed is a miss we chose.
    """
    labelled = pl.DataFrame({
        "game_id": ["g1", "g1", "g2", "g2", "g3", "g3"],
        "target": [1, 0, 1, 0, 0, 0],        # g3: nobody in the pool scored
    })
    filtered = labelled.filter(pl.col("game_id") != "g2")   # g2's scorer removed
    p = D.pool_ceiling(labelled, filtered)
    assert p["played_games"] == 3
    assert p["games_with_no_scorer_anywhere"] == 1
    assert p["games_whose_scorer_the_filter_removed"] == 1
    assert p["ceiling"] == pytest.approx(0.5)


def test_favourite_and_underdog_slices_are_not_inverted():
    """`spread_line` is team-relative and POSITIVE when that team is favoured.

    `vegas_features` defines `is_favorite` as `spread_line > 0`, and this
    project has already shipped the opposite reading once — teams marked
    favourite were winning 34.9% of their games. An inverted slice here would
    not crash; it would quietly claim the model is bad at backing favourites
    when it is bad at backing underdogs, and Phase 3 would chase the wrong
    thing.
    """
    players = _players([
        {"game_id": "fav", "player_id": "a", "team": "KC", "prob": .9,
         "target": 1, "spread_line": 7.0, "total_line": 45.0},
        {"game_id": "fav", "player_id": "b", "team": "KC", "prob": .1,
         "target": 0, "spread_line": 7.0, "total_line": 45.0},
        {"game_id": "dog", "player_id": "c", "team": "NYJ", "prob": .9,
         "target": 0, "spread_line": -7.0, "total_line": 45.0},
        {"game_id": "dog", "player_id": "d", "team": "NYJ", "prob": .1,
         "target": 1, "spread_line": -7.0, "total_line": 45.0},
    ])
    outcomes = pl.DataFrame({"game_id": ["fav", "dog"], "hit1": [True, False]})
    by_side = {d["side"]: d["top1"] for d in D.slices(players, outcomes)["by_side"]}
    assert by_side["pick on favourite"] == 1.0
    assert by_side["pick on underdog"] == 0.0


def test_position_falls_back_to_rb_as_the_baseline():
    df = pl.DataFrame({
        "position_QB": [1, 0, 0], "position_WR": [0, 1, 0],
        "position_TE": [0, 0, 0], "position_FB": [0, 0, 0],
        "position_DEFST": [0, 0, 0],
    })
    assert D._position(df).to_list() == ["QB", "WR", "RB"]
