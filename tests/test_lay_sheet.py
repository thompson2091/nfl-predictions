"""The arithmetic that decides whether the fade has a venue.

Three things can be quietly wrong here and none of them would look wrong.

  * The **floor** could be the wrong side of break-even, which would send you
    to an exchange with a threshold that accepts losing fills.
  * The **units** could be mixed. Capacity is measured on the No decimal and a
    quoted spread is on the Yes price; comparing them directly is the error
    this module was written to correct, and a test that does not pin the
    conversion would let it back in.
  * The **shrink** could be read off the whole band rather than the cut the
    frozen rule actually picks, pricing the sheet for a population the rule
    does not name.

    pytest tests/test_lay_sheet.py -v
"""
from __future__ import annotations

import polars as pl
import pytest

from src.evaluation.lay_sheet import (cost_of_spread, price_no, probes, sheet,
                                      shrink_from)

#: The band as `shortlist_backtest.fade_side` currently measures it.
FADE = {
    "band": [4.26, 11.20],
    "cuts": [
        {"ratio": 1.0, "n": 2205, "scored_pct": 4.17, "priced_pct": 7.47,
         "carries_pct": 3.57},
        {"ratio": 1 / 3, "n": 690, "scored_pct": 2.61, "priced_pct": 6.92,
         "carries_pct": 4.63},
    ],
}

RULE = {"name": "fade the overpriced", "kind": "lay", "market": "anytime_td",
        "min_book_pct": 4.26, "max_book_pct": 11.20, "max_ratio": 1 / 3}


def _ev(no_decimal: float, true_prob: float, commission: float) -> float:
    """What backing No at this price is worth, per unit staked."""
    return (1 - true_prob) * (no_decimal - 1) * (1 - commission) - true_prob


def test_the_floor_is_exactly_break_even():
    """A fill at the floor is worth nothing — and a hair above it, something."""
    for commission in (0.0, 0.02, 0.05):
        p = price_no(0.0692, 0.377, commission)
        q = p["est_pct"] / 100
        assert _ev(p["floor_no_dec"], q, commission) == pytest.approx(0, abs=1e-12)
        assert _ev(p["floor_no_dec"] * 1.01, q, commission) > 0
        assert _ev(p["floor_no_dec"] * 0.99, q, commission) < 0


def test_the_room_is_the_measured_capacity():
    """With no commission, room per player is the band's margin capacity.

    `fade_side` reports capacity as `(1 - hit) / (1 - priced) - 1`. Applying
    the group's own shrink to the group's own price has to reproduce it, or the
    sheet and the measurement behind it are describing different bets.
    """
    priced, hit = 0.0692, 0.0261
    capacity = ((1 - hit) / (1 - priced) - 1) * 100
    p = price_no(priced, hit / priced, commission=0.0)
    assert p["room_pct"] == pytest.approx(capacity, abs=1e-9)


def test_commission_only_eats_a_sliver_of_it():
    """Five percent of winnings on a near-certain side is not five percent."""
    free = price_no(0.0692, 0.377, 0.0)["room_pct"]
    charged = price_no(0.0692, 0.377, 0.05)["room_pct"]
    assert charged < free
    assert free - charged < 0.25          # tenths of a point, not points


def test_a_wide_yes_quote_is_a_narrow_no_one():
    """The unit conversion the venue question turns on.

    This is the error the module exists to correct: a lay price a tenth above
    fair costs well under a point of the No-side edge, so a 1-4% spread was
    never the thing standing between this and a bet.
    """
    tenth = cost_of_spread(0.0692, 0.10)
    assert tenth["cost_pct"] == pytest.approx(0.67, abs=0.05)
    assert tenth["cost_pct"] < price_no(0.0692, 0.377, 0.05)["room_pct"]
    # Monotone, and still survivable at a quote of double fair.
    costs = [cost_of_spread(0.0692, s)["cost_pct"] for s in (0.02, 0.1, 0.5, 1.0)]
    assert costs == sorted(costs)
    assert costs[-1] < price_no(0.0692, 0.377, 0.05)["room_pct"]


def test_the_lay_ceiling_is_the_floor_seen_from_the_other_side():
    """Laying Yes at L is backing No at L/(L-1); the sheet quotes both."""
    p = price_no(0.0692, 0.377, 0.05)
    L = p["lay_yes_max_dec"]
    assert L / (L - 1) == pytest.approx(p["floor_no_dec"], rel=1e-12)


def test_the_shrink_comes_from_the_cut_the_rule_picks():
    """Not the whole band: the rule names a third, and the third scored less."""
    got = shrink_from(FADE, RULE["max_ratio"])
    assert got["n"] == 690
    assert got["shrink"] == pytest.approx(2.61 / 6.92)
    assert shrink_from(FADE, 1.0)["n"] == 2205
    assert shrink_from(None, 1 / 3) is None


def _board() -> pl.DataFrame:
    return pl.DataFrame({
        "player_name": ["In Band Pick", "In Band Only", "Too Short", "Too Long"],
        "team": ["AAA"] * 4,
        "game_label": ["AAA @ BBB"] * 4,
        "odds": [700.0, 700.0, -200.0, 5000.0],
        "market_prob": [0.07, 0.07, 0.60, 0.02],
        "prob_bet": [0.01, 0.06, 0.20, 0.001],
        "model_edge_pp": [-6.0, -1.0, -40.0, -1.9],
    })


def test_the_sheet_prices_only_what_the_rule_names():
    s = sheet(_board(), fade=FADE, rule=RULE)
    assert [r["player"] for r in s["rows"]] == ["In Band Pick"]
    assert s["rows"][0]["floor_no_dec"] < s["rows"][0]["fair_no_dec"]


def test_probes_are_the_band_and_say_which_are_picks():
    """The venue question does not care whether a player is a pick.

    Any in-band name tests whether the exchange quotes the market at all, which
    is what makes a probe list useful on a board where the rule fires nobody —
    and why it has to be labelled so it is never read as one.
    """
    got = probes(_board(), RULE, shrink_from(FADE, RULE["max_ratio"]))
    assert [r["player"] for r in got] == ["In Band Pick", "In Band Only"]
    assert [r["rule_pick"] for r in got] == [True, False]


def test_an_empty_board_says_so_rather_than_inventing_rows():
    empty = _board().head(0)
    s = sheet(empty, fade=FADE, rule=RULE)
    assert s["rows"] == [] and s["note"]
    assert sheet(_board(), fade=None, rule=RULE)["rows"] == []
