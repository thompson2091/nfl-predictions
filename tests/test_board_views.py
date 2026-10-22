"""The Record's Shortlist and Fades ask the live board's rule about past weeks.

The rule drops any row with no opening price at its line. Past-week rows
carry none of their own, so `shortlist_sides` has to attach the week's open
the way the live board does; when it did not, every past pick was dropped and
both Record filters shipped empty from deploy 20261020.v5 to 20261021.v1.
"""
from __future__ import annotations

from src.evaluation import board_views as BV

ART = {"floors": {"over": None, "under": {"lo": 2.0, "hi": None}},
       "graded": []}

ROWS = [
    # Model 10 points under the open at the same line: a fade.
    {"player_name": "Same Line", "line": 4.5, "model": 0.40, "book": 0.48,
     "n_books": 5},
    # The open sat on another line: no same-line open, so not taken.
    {"player_name": "Moved Line", "line": 5.5, "model": 0.30, "book": 0.48,
     "n_books": 5},
]

OPENS = {"receptions|same line": {"point": 4.5, "fair": 0.50},
         "receptions|moved line": {"point": 4.5, "fair": 0.50}}


def _patch(monkeypatch):
    monkeypatch.setattr("src.evaluation.ou_shortlist.load", lambda market: ART)
    monkeypatch.setattr(BV, "week_opens", lambda season, week: OPENS)


def test_a_past_week_is_measured_against_its_open(monkeypatch):
    _patch(monkeypatch)
    got = BV.shortlist_sides(ROWS, "receptions", 2026, 5)
    assert got == {("Same Line", 4.5): "under"}


def test_without_the_week_nothing_can_be_taken(monkeypatch):
    # The failure this guards: no season and week, no open, no picks.
    _patch(monkeypatch)
    assert BV.shortlist_sides(ROWS, "receptions") == {}
