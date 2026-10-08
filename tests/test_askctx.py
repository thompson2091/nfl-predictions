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
    import re

    # CODE, NOT PROSE. The first version scanned the whole source for the
    # substring "POST", which a comment reading "how many books POSTED this
    # line" trips — and a guard that fires on its own documentation gets
    # weakened or deleted rather than fixed. Comments and docstrings are
    # stripped and the patterns are code-shaped.
    src = inspect.getsource(askctx)
    src = re.sub(r'"""(?:.|\n)*?"""', "", src)
    src = re.sub(r"^\s*#.*$", "", src, flags=re.M)
    for bad in (r"\brequests?\.", r"\$_(?:GET|POST|REQUEST)\b",
                r"\binput\s*\(", r"\bsys\.argv\b",
                r"\bos\.environ\b", r"\burlopen\b"):
        assert not re.search(bad, src), (
            f"{bad!r} in askctx suggests caller-supplied context")
    # And the one positive statement: every public entry point takes the
    # payload and a card or an id, never a question.
    for fn in ("for_game", "core", "slice_players", "slice_angles",
               "slice_record", "slice_team", "build", "build_slices"):
        sig = inspect.signature(getattr(askctx, fn))
        assert "q" not in sig.parameters and "question" not in sig.parameters, (
            f"{fn} takes something that could be a reader's question")


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


# ──────────────────────────────────────────────────────────────────────────
# SLICES — the model asks for what a question needs
# ──────────────────────────────────────────────────────────────────────────
#
# The brief above is a fixed guess, and measured against what the app draws
# it was wrong in six places at once: sixteen of about forty priced players
# traveled, and the best price, the books quoting, the second per-$100 basis
# and the Pass/Leans/Strong verdict were on every board row and in no brief.
# Two more could never have fitted — the whole angles table is 1.2 MB and the
# whole season record is 254 KB.
#
# These check that each slice carries what the screen carries, and that the
# one slice derived rather than copied agrees with the figure the page prints.


def _slice_payload():
    """The brief fixture, plus the things only the slices reach."""
    p = _payload()
    p["markets"][0]["players"][0].update({
        "ours": 0.60, "ev_adj": -14.0, "best": "-190",
        "best_book": "fanatics", "n_best": 2, "read": "Pass", "pos": "RB",
        "team": "PIT",
    })
    p["markets"][0]["players"][1].update({
        "ours": 0.43, "ev_adj": -2.0, "best": "+160",
        "best_book": "ballybet", "n_best": 1, "read": "Leans", "pos": "RB",
        "team": "CIN",
    })
    p["markets"][0]["players"][2].update({
        "ours": 0.03, "ev_adj": 26.0, "best": "+3600",
        "best_book": "bovada", "n_best": 1, "read": "Strong call",
        "pos": "TE", "team": "PIT",
    })
    p["yards"] = {"receptions": {"rows": [
        {"player_name": "Slot Man", "team": "CIN",
         "game_id": "2026_03_CIN_PIT", "point": 4.5, "odds": -115,
         "proj": 5.2, "lo": 2.0, "hi": 8.0, "model_only": 0.71,
         "fair_prob": 0.52, "ours": 0.55, "ev": 4.9, "n_books": 1},
    ]}}
    p["angles"] = {
        "break_even": 0.5238,
        "week": {"CIN_PIT": [["CIN", "road_dog"], ["PIT", "home_fav"],
                             ["CIN", "made_up"]]},
        "rows": [
            {"id": "road_dog", "label": "Road underdog", "cat": "The line",
             "blurb": "{team} is an underdog away from home.",
             "all": {"w": 924, "l": 847, "n": 1771, "pct": 0.5217,
                     "lo": 0.498, "hi": 0.545, "clears": False}},
            {"id": "home_fav", "label": "Home favorite", "cat": "The line",
             "blurb": "{team} is favored at home.",
             "all": {"w": 847, "l": 924, "n": 1771, "pct": 0.4783,
                     "lo": 0.455, "hi": 0.502, "clears": False}},
        ],
    }
    p["scorecard"] = {
        "season": 2026, "break_even": 0.5238, "played": [1, 2, 3],
        "default": "2-3",
        "ranges": {
            "1-1": {"games": {"n": 16}, "players": {"all": {"bets": 1}}},
            "2-3": {"games": {"n": 32}, "players": {"all": {"bets": 500}}},
        },
        "bets": {
            "teams": ["PIT", "CIN"],
            "markets": ["Catches", "Receiving yards"],
            "players": ["A Man", "B Man"],
            "market_keys": ["receptions", "receiving_yards"],
            "weeks": {
                # [playerIdx, game_id, legs, teamIdx]; a leg is
                # [market, line, actual, adj_side, adj_ret, model_side,
                #  model_ret, edge_ret, streak, adj_price, model_price,
                #  edge_price]
                "1": [
                    [0, "2026_01_CIN_PIT",
                     [[0, 4.5, 6, 0, 0.91, 0, 0.91, None, None, -110, -110, None],
                      [1, 55.5, 40, 1, -1.0, 1, -1.0, None, None, -110, -110, None]],
                     0],
                    [1, "2026_01_CIN_PIT",
                     [[0, 3.5, 2, 0, -1.0, 0, -1.0, None, None, -115, -115, None]],
                     1],
                ],
            },
        },
    }
    return p


def test_the_core_is_small_and_says_what_can_be_fetched():
    """A core that does not advertise the slices is a core the model answers
    from, which is the old failure wearing a new file name."""
    import json

    out = askctx.core(_slice_payload(), _card())
    assert len(json.dumps(out)) < 3000, "the core is meant to be ~1.3 KB"
    menu = out["you_can_fetch"]
    assert set(menu) == set(askctx.SLICES), (
        f"the menu and SLICES disagree: {sorted(menu)} vs "
        f"{sorted(askctx.SLICES)}")
    for k, v in menu.items():
        assert isinstance(v, str) and len(v) > 30, f"{k} is not described"
    # The two teams, so the proxy can check a `team` argument against the
    # data rather than against the game id's spelling.
    assert out["away"] == "CIN" and out["home"] == "PIT"
    # And the three numbers a question usually opens with.
    assert out["market"]["spread"] is None or "spread" in out["market"]
    assert "our_model" in out and "adjusted" in out


def test_the_player_slice_carries_every_priced_player_not_a_cut():
    """THE MISS THAT MATTERED MOST. `for_game` sends eight per market per
    ordering; the ninth name is on the screen the reader is looking at."""
    out = askctx.slice_players(_slice_payload(), "CIN_PIT")
    td = out["markets"]["anytime touchdown"]
    assert {r["player"] for r in td} == {"Likely Back", "Second Back",
                                         "Longshot Tight End"}
    # Ordered by our own number, so the likeliest scorer leads.
    assert td[0]["player"] == "Likely Back"


def test_the_player_slice_carries_what_the_board_carries():
    """A brief that disagrees with the page a reader is looking at is worse
    than one that is merely thin."""
    out = askctx.slice_players(_slice_payload(), "CIN_PIT")
    row = [r for r in out["markets"]["anytime touchdown"]
           if r["player"] == "Likely Back"][0]
    assert row["per_100_model"] == -18.0
    assert row["per_100_adjusted"] == -14.0, "the second basis shipped 2026-10-07"
    assert row["best_price"] == "-190" and row["best_book"] == "fanatics"
    assert row["books_level_at_best"] == 2
    assert row["our_read"] == "Pass"
    assert row["team"] == "PIT"
    # And a line market carries the books quoting, which is the gate the
    # shortlist floors were fitted under.
    ou = out["markets"]["receptions"][0]
    assert ou["books_quoting"] == 1
    assert ou["line"] == 4.5 and ou["we_project"] == 5.2
    assert ou["likely_range"] == [2.0, 8.0]
    # The note has to say what the three percentages are, because a positive
    # edge that loses money is the single thing here most often misread.
    assert "per_100" in out["note"]


def test_the_angle_slice_joins_this_fixture_to_the_records():
    """The whole table is 1.2 MB and twelve rows of it are about one game."""
    out = askctx.slice_angles(_slice_payload(), _card())
    got = {(a["team"], a["angle"]) for a in out["angles"]}
    assert got == {("CIN", "Road underdog"), ("PIT", "Home favorite")}, (
        "an angle with no definition must drop rather than ship a blank")
    road = [a for a in out["angles"] if a["angle"] == "Road underdog"][0]
    assert road["record"] == "924-847" and road["games"] == 1771
    assert road["cover_pct"] == 0.522
    assert road["clears_break_even"] is False
    # `{team}` is filled, or the sentence reads "{team} is an underdog".
    assert road["what_it_means"].startswith("CIN ")
    assert out["break_even_pct"] == 0.5238


def test_the_record_slice_is_the_range_the_page_opens_on():
    """A reader asking "how has your model done" is looking at one range."""
    out = askctx.slice_record(_slice_payload())
    assert out["weeks"] == "2-3", "not the default range"
    assert out["games"]["n"] == 32
    assert out["player_bets"]["all"]["bets"] == 500
    assert out["break_even_pct"] == 0.5238
    assert out["weeks_played"] == [1, 2, 3]


def test_the_record_slice_falls_back_rather_than_shipping_nothing():
    p = _slice_payload()
    p["scorecard"]["default"] = "9-9"
    out = askctx.slice_record(p)
    assert out["games"] is not None, "an unknown default must not blank it"


def test_the_per_team_record_sums_to_the_pooled_one():
    """THE ANTI-DRIFT CHECK, and the only slice that is derived rather than
    copied.

    The payload carries no per-team record: the page sums it in the browser
    from 182 KB of leg detail. This does the same arithmetic in Python, so
    the two can disagree — and a per-team figure that does not add up to the
    season figure printed two screens away is worse than no per-team figure.
    """
    p = _slice_payload()
    b = p["scorecard"]["bets"]
    legs = [leg for wk in b["weeks"].values() for e in wk for leg in e[2]]
    pooled_n = len(legs)
    pooled_model = sum(leg[6] for leg in legs if leg[6] is not None)

    n = 0
    model = 0.0
    for team in b["teams"]:
        s = askctx.slice_team(p, team)
        n += s["bets"]
        if s["bets"]:
            model += s["model_per_100"] / 100 * s["bets"]
    assert n == pooled_n, f"{n} bets per team against {pooled_n} legs"
    assert abs(model - pooled_model) < 0.05, (
        f"{model:.3f} summed against {pooled_model:.3f} pooled")


def test_the_per_team_record_splits_by_market():
    out = askctx.slice_team(_slice_payload(), "PIT")
    assert out["bets"] == 2
    assert set(out["by_market"]) == {"Catches", "Receiving yards"}
    assert out["by_market"]["Catches"]["bets"] == 1
    # One won at -110 and one lost, so the model's return is 0.91 - 1.0.
    assert out["model_per_100"] == pytest.approx((0.91 - 1.0) / 2 * 100, abs=0.1)


def test_a_team_with_no_graded_bets_says_so_rather_than_erroring():
    out = askctx.slice_team(_slice_payload(), "ZZZ")
    assert out["bets"] == 0 and "no graded prop bets" in out["note"]


def test_every_slice_the_menu_offers_is_a_file_that_gets_built():
    """A menu entry with no file is a tool call that always fails."""
    p = _slice_payload()
    p["games"] = {"cards": [_card()], "public": {}, "lines": {}}
    built = askctx.build_slices(p)
    assert "core/CIN_PIT" in built
    assert "record/season" in built
    for name in askctx.SLICES:
        if name == "record":
            assert "record/season" in built
        elif name == "team":
            assert "team/PIT" in built and "team/CIN" in built
        else:
            assert f"{name}/CIN_PIT" in built, f"no file for slice {name!r}"


def test_no_slice_path_can_escape_the_ask_directory():
    """Every path is a literal plus a validated id. Asserted anyway: a slice
    keyed on something a reader influences would be a traversal."""
    p = _slice_payload()
    p["games"] = {"cards": [_card()], "public": {}, "lines": {}}
    for rel in askctx.build_slices(p):
        assert ".." not in rel and not rel.startswith("/")
        assert rel.count("/") == 1, rel
