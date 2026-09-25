"""The brief the Ask box answers from.

The endpoint is only as good as what travels with the question. Nothing here
checks wording; it checks that the numbers a reader would ask about are in the
file at all, because the failure mode is the model politely reporting that it
does not have data this repo has ingested and built features from.
"""
from __future__ import annotations

import importlib

import pytest

askctx = importlib.import_module("src.export.askctx")


def _payload():
    """A board with one game, two priced scorers and one longshot."""
    return {
        "season": 2026,
        "week": 3,
        "markets": [{
            "key": "anytime_td",
            "players": [
                # The model's favorite, and a bad price — so an EV sort
                # buries him. This is the row the brief used to drop.
                {"player": "Likely Back", "game_id": "2026_03_CIN_PIT",
                 "priced": True, "odds_num": -200, "model_only": 0.62,
                 "book": 0.66, "ev": -18.0},
                {"player": "Second Back", "game_id": "2026_03_CIN_PIT",
                 "priced": True, "odds_num": 150, "model_only": 0.44,
                 "book": 0.40, "ev": -3.0},
                # A lottery ticket with the best EV on the board.
                {"player": "Longshot Tight End", "game_id": "2026_03_CIN_PIT",
                 "priced": True, "odds_num": 3500, "model_only": 0.03,
                 "book": 0.019, "ev": 26.0},
            ],
        }],
        "yards": {},
        "games": {"cards": [], "public": {}, "lines": {}},
        "notes": {},
    }


def _card():
    return {
        "game_id": "CIN_PIT", "home": "PIT", "away": "CIN",
        "coach_home": "Mike McCarthy", "coach_away": "Zac Taylor",
        "home_coach_games_prior": 143, "home_coach_win_rate_prior": 0.5548,
        "home_coach_ats_rate_prior": 0.5175,
        "home_is_short_week": 1, "home_rest_diff": -3,
        "script": {
            "PIT|RB|rush": {"mult": 0.73, "p": 0.194, "tilt": 0.97},
            # Under the page's own cut: too unlikely to be worth a caveat.
            "CIN|RB|rush": {"mult": 0.73, "p": 0.04, "tilt": 1.02},
        },
        "matchup": {
            "games": {"PIT": 2, "CIN": 2},
            "splits": {
                "full": [{"label": "Early-down success", "sides": [
                    {"offense": "CIN", "defense": "PIT", "off_val": 0.36,
                     "def_val": 0.40, "edge": -0.04}]}],
                "h1": [{"label": "Early-down success", "sides": [
                    {"offense": "CIN", "defense": "PIT", "off_val": 0.41,
                     "def_val": 0.39, "edge": 0.02}]}],
            },
            "missing": [],
        },
    }


def test_the_likeliest_scorer_is_always_in_the_brief():
    """AN EV SORT ANSWERS "best priced", NOT "most likely".

    The board's preloaded question is "Who's most likely to score?" and the
    brief was one EV-ordered cut, so it opened with a longshot and could drop
    the model's own favorite entirely. On the live week it dropped a 39%
    scorer from one game of sixteen — a miss that grows with the number of
    players a book prices.
    """
    b = askctx.for_game(_payload(), _card())
    td = b["players"]["anytime touchdown"]
    assert td["likeliest"][0]["player"] == "Likely Back", td["likeliest"]
    assert [r["player"] for r in td["likeliest"]] == [
        "Likely Back", "Second Back", "Longshot Tight End"]


def test_a_player_is_not_sent_twice():
    """The second list is what the first one leaves out, or it is padding."""
    p = _payload()
    b = askctx.for_game(p, _card())
    td = b["players"]["anytime touchdown"]
    named = [r["player"] for r in td["likeliest"]]
    others = [r["player"] for r in td.get("best_priced_others", [])]
    assert not set(named) & set(others), (named, others)


def test_the_brief_names_the_coordinators_when_the_file_has_them():
    """The coordinators call the plays, and this repo already ingests them.

    Asked about them, the deployed box answered "coordinator information
    isn't included in the game preview data I have access to" while
    `data/raw/coordinators.csv` sat on disk and two feature builders read it.
    """
    askctx._COORD_CACHE.clear()
    askctx._COORD_CACHE[2026] = {"PIT": {"oc": "Brian Angelichio",
                                         "dc": "Patrick Graham"}}
    try:
        b = askctx.for_game(_payload(), _card())
    finally:
        askctx._COORD_CACHE.clear()
    assert b["coaches"]["PIT"]["oc"] == "Brian Angelichio"
    assert b["coaches"]["PIT"]["dc"] == "Patrick Graham"
    assert b["coaches"]["PIT"]["head_coach"] == "Mike McCarthy"


def test_a_missing_coordinator_file_is_not_an_error():
    """The board ships without it; the brief simply carries no coordinators."""
    askctx._COORD_CACHE.clear()
    askctx._COORD_CACHE[2026] = {}
    try:
        b = askctx.for_game(_payload(), _card())
    finally:
        askctx._COORD_CACHE.clear()
    assert "oc" not in b["coaches"]["PIT"]
    assert b["coaches"]["PIT"]["head_coach"] == "Mike McCarthy"


def test_the_coach_record_is_prior_and_says_so():
    b = askctx.for_game(_payload(), _card())
    rec = b["coaches"]["PIT"]["record_before_this_game"]
    assert rec["games"] == 143 and rec["ats_pct"] == 0.517
    assert "BEFORE" in b["coaches"]["note"]
    assert "short week" in b["coaches"]["PIT"]["rest"]


def test_script_dependence_uses_the_same_cut_the_page_does():
    """Below a one-in-eight chance the page drops the flag, so the brief does.

    Two sources disagreeing about whether a caveat applies is how the
    touchdown shortlist once disagreed with its own board.
    """
    b = askctx.for_game(_payload(), _card())
    rows = b["script_dependence"]["rows"]
    assert any(r.startswith("PIT RB rush") for r in rows), rows
    assert not any(r.startswith("CIN RB rush") for r in rows), rows


def test_the_halves_carry_edges_and_point_at_the_full_game_for_rates():
    """A half is a different matchup, not a smaller sample of the same one.

    Sending both sides' rates per half tripled the matchup block for numbers
    already in `full_game`, so a half sends the edge and says where the rest
    is.
    """
    b = askctx.for_game(_payload(), _card())
    me = b["matchup_edges"]
    assert me["first_half"] == ["Early-down success: CIN +0.02"]
    assert "full_game" in me["halves_note"]
    # The full game keeps both sides' rates, which is what the halves drop.
    assert "offense 0.36" in me["full_game"][0]["sides"][0]


def test_nothing_the_reader_types_can_reach_the_brief():
    """The brief is built here and keyed by game id; a question never enters.

    A client that supplies its own context turns the endpoint into a free
    general-purpose model paid for by whoever owns the key.
    """
    import inspect

    src = inspect.getsource(askctx)
    for bad in ("request", "POST", "$_GET", "input("):
        assert bad not in src, f"{bad!r} suggests caller-supplied context"


def test_every_player_row_carries_its_team():
    """PLAYERS CHANGE TEAMS, AND THE MODEL'S MEMORY IS OLDER THAN THE DATA.

    The rows were names and prices, so "what team does he play for" was
    answered from training rather than from this week's roster. Jerry Jeudy
    played for Denver through 2023 and Cleveland from 2024; a model asked
    about him with no team in front of it will answer confidently and be a
    season or two behind.
    """
    p = _payload()
    for r in p["markets"][0]["players"]:
        r["team"] = "CLE"
        r["pos"] = "WR"
    b = askctx.for_game(p, _card())
    rows = b["players"]["anytime touchdown"]["likeliest"]
    assert rows, "no rows to check"
    for r in rows:
        assert r.get("team") == "CLE", r
        assert r.get("pos") == "WR", r


def test_the_brief_says_which_week_the_rosters_are_from():
    """A team with no date on it is a claim the reader cannot age-check."""
    b = askctx.for_game(_payload(), _card())
    note = b["roster_note"]
    assert "week 3" in note and "2026" in note, note
