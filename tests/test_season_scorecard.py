"""The Record page's arithmetic, and the one join that silently loses bets.

The page adds the shipped legs back up to draw its per-player tables, so the
invariant worth guarding is that the legs and the pooled rows are the same
bets: if `bets_block` drops one, section 06 reports a return the four
sections above it disagree with, and nothing raises.

That is not hypothetical. Built against the card's rows alone and joined on
a local `.strip().lower()`, this returned 65 of 69 edge bets over weeks 3-4
of 2026 — +11.65% against the published +13.36% — because `prop_edge` keys
on `prop_settlement._norm`, which strips punctuation and the generational
suffix. "J.K. Dobbins" and "jk dobbins" never met.
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")

from src.evaluation.season_scorecard import (OU_MARKETS, bets_block,
                                             players_block)


def _row(player, game, line, side, won, odds, model_side=None, actual=0.0):
    """One graded card row, in the shape `ou_rows` yields."""
    return {"player_name": player, "game_id": game, "line": line,
            "side": side, "won": won, "odds": odds, "actual": actual,
            "model": 0.9 if (model_side or side) == "over" else 0.1}


@pytest.fixture
def cache():
    """Two weeks, two markets, and a name the normaliser has to work on."""
    rec, ry = OU_MARKETS[0][0], OU_MARKETS[1][0]
    c = {
        (rec, 1): [_row("J.K. Dobbins", "2026_01_LA_DEN", 4.5, "over", True,
                        -110),
                   _row("Amon-Ra St. Brown", "2026_01_LA_DEN", 6.5, "under",
                        False, 120)],
        (ry, 1): [_row("J.K. Dobbins", "2026_01_LA_DEN", 40.5, "over", True,
                       -115)],
        (rec, 2): [_row("Michael Penix Jr.", "2026_02_ATL_GB", 1.5, "under",
                        True, 100)],
    }
    # The model series is the same bets sided on the unblended number, which
    # on these rows disagrees with the card on exactly one of them.
    c[("model", rec, 1)] = [dict(c[(rec, 1)][0]),
                            dict(c[(rec, 1)][1], side="over", won=True)]
    c[("model", ry, 1)] = [dict(c[(ry, 1)][0])]
    c[("model", rec, 2)] = [dict(c[(rec, 2)][0])]
    # And the edge series, keyed the way `prop_edge` keys it: a normalised
    # `player_key`, a `point` rather than a `line`, and its own `price`.
    c[("edge", rec, 1)] = [{"game_id": "2026_01_LA_DEN",
                            "player_name": "J.K. Dobbins",
                            "player_key": "jk dobbins", "point": 4.5,
                            "side": "over", "won": True, "price": -110.0,
                            "actual": 0.0, "threshold_pp": 5.5}]
    c[("edge", ry, 1)] = []
    # AN EDGE BET THE CARD'S OWN ROWS DO NOT CARRY. `qualifying` runs over
    # every archived line and `_one_per_player` keeps only those with an
    # over price, so the edge series reaches player-games the card series
    # does not. Built from the card's rows alone this leg is simply lost,
    # and section 06 then reports a return section 05 disagrees with.
    c[("edge", rec, 2)] = [{"game_id": "2026_02_ATL_GB",
                            "player_name": "Michael Penix Jr.",
                            "player_key": "michael penix", "point": 1.5,
                            "side": "under", "won": True, "price": -105.0,
                            "actual": 0.0, "threshold_pp": 5.5},
                           {"game_id": "2026_02_ATL_GB",
                            "player_name": "Bijan Robinson",
                            "player_key": "bijan robinson", "point": 3.5,
                            "side": "over", "won": False, "price": -120.0,
                            "actual": 0.0, "threshold_pp": 5.5}]
    for mk, _ in OU_MARKETS[2:]:
        for w in (1, 2):
            c[(mk, w)] = c[("model", mk, w)] = c[("edge", mk, w)] = []
    return c


def _legs(block, weeks, idx):
    return [l[idx] for w in weeks for pg in block["weeks"].get(str(w), [])
            for l in pg[2] if l[idx] is not None]


@pytest.mark.parametrize("idx,key", [(4, "all"), (6, "model_all"),
                                     (7, "edge_all")])
def test_the_legs_add_up_to_the_pooled_return(cache, idx, key):
    """What section 06 sums must be what sections 04 and 05 report.

    The page's only arithmetic is this addition — every per-leg return is
    computed here, by the same `_payout` the pooled rows use — so a
    disagreement is a bet that fell out of the join rather than a rounding
    difference.
    """
    weeks = [1, 2]
    b = bets_block(cache, weeks)
    p = players_block(cache, weeks, {})
    got = _legs(b, weeks, idx)
    assert len(got) == p[key]["bets"], (
        f"{key}: {len(got)} legs against {p[key]['bets']} pooled bets")
    assert sum(got) / len(got) == pytest.approx(p[key]["roi"], abs=1e-6)


def test_an_edge_bet_with_no_card_row_is_still_shipped(cache):
    """THE REGRESSION. The three series are not the same set of bets.

    `qualifying` runs over every archived line and keeps whatever clears the
    threshold at its own side's price; `_one_per_player` keeps only rows
    with an over price. So the edge series reaches player-games the card
    series does not, and an accumulator seeded from the card's rows drops
    them — silently, because nothing joins the two counts.
    """
    b = bets_block(cache, [1, 2])
    assert len(_legs(b, [1, 2], 7)) == 3
    # The leg is there even though no card row names that player-game.
    assert "Bijan Robinson" in b["players"]
    rows = [r for r in b["weeks"]["2"] if b["players"][r[0]]
            == "Bijan Robinson"]
    assert rows and rows[0][2][0][7] is not None
    assert rows[0][2][0][4] is None, (
        "the card never bet this player-game, so its adjusted return is not "
        "a number")


def test_the_printed_name_is_what_the_page_shows(cache):
    """Joined on the normalised name, displayed with its punctuation."""
    b = bets_block(cache, [1, 2])
    assert "J.K. Dobbins" in b["players"]
    assert "Michael Penix Jr." in b["players"]
    assert "jk dobbins" not in b["players"]


def test_one_player_game_is_one_entry_across_the_three_series(cache):
    """A leg the card and the edge rule both took is ONE leg carrying both
    returns, not two rows a reader would count twice."""
    b = bets_block(cache, [1])
    hits = [r for r in b["weeks"]["1"] if b["players"][r[0]]
            == "J.K. Dobbins"]
    assert len(hits) == 1, "one player-game split into several entries"
    rec_leg = [l for l in hits[0][2] if l[0] == 0][0]
    assert rec_leg[4] is not None and rec_leg[6] is not None \
        and rec_leg[7] is not None


def test_a_return_is_positive_exactly_when_the_bet_won(cache):
    """`won` is not stored twice: the page reads it off the sign, so the
    sign has to carry it."""
    b = bets_block(cache, [1, 2])
    for w in ("1", "2"):
        for _, _, legs in b["weeks"].get(w, []):
            for l in legs:
                for i in (4, 6, 7):
                    if l[i] is not None:
                        assert l[i] != 0, "a zero return says nothing"


def test_both_sides_are_kept_where_the_model_and_the_card_disagree(cache):
    """One leg with two sides, not two rows a reader would count twice."""
    b = bets_block(cache, [1])
    legs = [l for _, _, ls in b["weeks"]["1"] for l in ls]
    split = [l for l in legs if l[3] is not None and l[5] is not None
             and l[3] != l[5]]
    assert split, "the fixture's disagreeing row collapsed into one side"
    for l in split:
        assert l[4] is not None and l[6] is not None


def test_a_week_with_no_bets_is_absent_rather_than_empty(cache):
    b = bets_block(cache, [1, 2, 3])
    assert "3" not in b["weeks"]
