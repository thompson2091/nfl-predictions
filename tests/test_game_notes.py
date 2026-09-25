"""The notes on a game page: what code decides, and what Claude is allowed to.

The split is the design. Code chooses the notes and computes the figures;
Claude writes the prose. These tests hold that line, because every way it can
slip produces a page that looks right.
"""
import json
from pathlib import Path

import pytest

from src.analysis import game_notes as gn


def _payload():
    """A minimal payload shaped like the real one, including the id mismatch.

    The boards key games as `2026_03_ATL_GB` and the cards as `ATL_GB`. That
    is not a quirk to normalise away in the fixture — it is the bug that made
    every touchdown note silently vanish, so the fixture keeps it.
    """
    return {
        "games": {
            "cards": [{"game_id": "ATL_GB", "home": "GB", "away": "ATL",
                       "total": 44.5, "spread": -6.5,
                       "model_total": 47.6, "model_spread": -0.9}],
            "rows": [{"game_id": "2026_03_ATL_GB", "market": "h2h",
                      "outcome": "GB", "consensus": -245, "open_odds": -283,
                      "move_pp": -2.9, "best": -225, "best_book": "lowvig",
                      "gap_pp": 2.9}],
        },
        "markets": [{
            "key": "anytime_td",
            "players": [
                {"player": "Tucker Kraft", "game_id": "2026_03_ATL_GB",
                 "priced": True, "odds_num": 195, "ours": 0.35, "book": 0.27,
                 "ev": 12.0, "diff": 8.0},
                {"player": "Deep Reserve", "game_id": "2026_03_ATL_GB",
                 "priced": True, "odds_num": 2827, "ours": 0.04, "book": 0.03,
                 "ev": 48.0, "diff": 1.0},
                {"player": "Michael Penix Jr.", "game_id": "2026_03_ATL_GB",
                 "priced": True, "odds_num": 700, "ours": 0.03, "book": 0.17,
                 "ev": -40.0, "diff": -14.0},
            ],
            "shortlist": {"rows": [{"player": "Tucker Kraft"}]},
        }],
        "yards": {"receiving_yards": {"rows": [
            {"player_name": "Michael Penix Jr.", "game_id": "2026_03_ATL_GB",
             "point": None, "proj": 3.6, "ev": 1.0, "ours": 0.5, "odds": -110},
            {"player_name": "Austin Hooper", "game_id": "2026_03_ATL_GB",
             "point": 7.5, "proj": 15.8, "ev": 9.0, "ours": 0.5, "odds": 108},
        ]}},
    }


def test_notes_find_the_game_despite_two_id_schemes():
    """Matching nothing looks exactly like a game with no priced players."""
    p = _payload()
    kinds = {n["kind"] for n in gn.select(p, p["games"]["cards"][0])}
    assert "td_value" in kinds, (
        "the boards key games as 2026_03_ATL_GB and the cards as ATL_GB")
    assert "move" in kinds and "shop" in kinds


def test_the_value_pick_is_never_drawn_from_the_longshot_tail():
    """`longshot`: the tail is priced at 4.8% against a true 2.4%.

    Ranking a game's players by expected value puts the longest price on top
    almost every time. The first build led with a +2827 player at "4% ours
    against 3% theirs" and claimed 48 dollars per 100 — arithmetic on two
    estimates that are both inside their own noise.
    """
    p = _payload()
    notes = gn.select(p, p["games"]["cards"][0])
    value = next(n for n in notes if n["kind"] == "td_value")
    assert "Deep Reserve" not in value["pick"]
    assert "Tucker Kraft" in value["pick"]


def test_no_note_puts_a_missing_number_in_front_of_a_reader():
    """A row with no posted line still carries a projection.

    That rendered as "under None" in the headline, the stat chip and the pick
    — three places at once, and nothing raised.
    """
    p = _payload()
    for n in gn.select(p, p["games"]["cards"][0]):
        blob = json.dumps(n["stats"]) + n["pick"] + n["brief"] + n["fallback"]
        assert "None" not in blob, f"{n['kind']} leaked a null: {n['pick']}"


def test_every_note_reads_correctly_with_no_api_key():
    """No key, no network and a refused response are the same page, plainer."""
    p = _payload()
    notes = gn.phrase(gn.select(p, p["games"]["cards"][0]),
                      p["games"]["cards"][0], use_cache=False)
    for n in notes:
        assert n["why"], f"{n['kind']} has no explanation"
        assert n["title"], f"{n['kind']} has no headline"


def test_generated_prose_may_not_introduce_a_number():
    """The guard that makes generated text safe beside real money."""
    assert gn._numbers_are_sourced("GB by 6.5", "The book has GB by 6.5.")
    assert gn._numbers_are_sourced("a close game", "The book has GB by 6.5.")
    assert not gn._numbers_are_sourced(
        "GB by 9.5", "The book has GB by 6.5."), "invented a line"
    # Rounding counts as inventing. A note that rounds is replaced by one
    # that does not, because the chip beside it will not be rounded.
    assert not gn._numbers_are_sourced(
        "GB by 7", "The book has GB by 6.5.")
    # But notation is not invention. Rejecting "a 3-point spread" because the
    # brief said "3.0" threw away a correct sentence over a trailing zero.
    assert gn._numbers_are_sourced("a 3-point spread", "The book has BAL by 3.0.")
    assert gn._numbers_are_sourced("35%", "We make him 35.0%.")


def test_an_unsourced_answer_falls_back_rather_than_printing():
    p = _payload()
    notes = gn.select(p, p["games"]["cards"][0])
    n = notes[0]
    before = n["why"]
    gn._apply([n], {n["id"]: {"title": "Now 99.9 points", "why": "Made up 12345"}})
    assert n.get("unsourced") is True
    assert n["why"] == before, "unsourced prose must not reach the page"


def test_title_and_why_move_together():
    """A generated headline over a template explanation reads as a mismatch."""
    p = _payload()
    n = gn.select(p, p["games"]["cards"][0])[0]
    before = (n["title"], n["why"])
    gn._apply([n], {n["id"]: {"title": "A fine headline"}})
    assert (n["title"], n["why"]) == before


def test_thresholds_leave_a_quiet_game_quiet():
    """Selection is thresholded, not top-k.

    Padding every game to seven cards means showing the seventh-most
    interesting thing about a game that had two.
    """
    p = _payload()
    p["games"]["cards"][0]["model_spread"] = -6.5     # agrees with the book
    p["games"]["cards"][0]["model_total"] = 44.5
    kinds = {n["kind"] for n in gn.select(p, p["games"]["cards"][0])}
    assert "line_gap" not in kinds and "total_gap" not in kinds
