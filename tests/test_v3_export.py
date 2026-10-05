"""site/v3 — the casual app: does every screen render, and is it the same data.

v3 is a second front end over one payload. The risk is not that a number is
wrong — the numbers are v1's, and tested there — but that a screen throws on
load, which shows as a blank page and one line in a console nobody has open.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def v3_js(tmp_path_factory):
    """The v3 bundle, assembled exactly as `v3.render` assembles it."""
    from src.export import site as v1
    from src.export import v3js

    js = "\n".join([v1.JS_CORE, v1.JS_SHARED, v1.JS_SLIPVIEW, v1.JS_WEEK,
                    v1.JS_COMBOS, v1.JS_SAVED, v1.JS_LADDER, v1.JS_MODEL,
                    v3js.js()])
    p = tmp_path_factory.mktemp("v3") / "app.js"
    p.write_text(js)
    return p


@pytest.fixture(scope="module")
def payload_v3():
    """The site fixture, PLUS the two things v3 adds and it does not carry.

    The shared fixture has no played weeks and no game cards, so on it the
    week picker and the whole game-detail screen are skipped — which are
    exactly the two features v3 exists to add. A harness that reports "not
    exercised" and exits zero is the failure this file is here to prevent.
    """
    import tests.test_site_export as T

    p = T.payload.__wrapped__()
    p["games"] = {
        "season": 2026, "week": 3, "games": 2,
        "cards": [
            {"game_id": "ATL_GB", "home": "GB", "away": "ATL",
             "total": 44.5, "spread": -6.5, "proj_home": 25.5, "proj_away": 19.0,
             "win_home": 0.684, "win_away": 0.316,
             "model_total": 47.6, "model_spread": -0.9,
             "model_home": 24.3, "model_away": 23.4,
             "kick_day": "Thursday", "kick_et": "8:15 PM ET", "prime": True,
             "model_win_home": 0.55, "model_win_n": 380,
             "blend": {"spread": -5.7, "total": 45.4},
             "matchup": {"thin": False, "games": {"GB": 2, "ATL": 2},
                         "halves": [["full", "Full game"], ["h1", "1st half"],
                                    ["h2", "2nd half"]],
                         # TWO metrics on a split, not one. With a single row
                         # the pills that filter to one metric render as
                         # nothing and every assertion about them is skipped
                         # while the file still reports all passed.
                         # TWO GROUPS, not two metrics from one. With every
                         # metric in the same group the chooser has one
                         # button, correctly renders nothing, and every
                         # assertion about filtering is skipped silently.
                         "splits": {"full": [{"key": "epa_play",
                             "label": "EPA per play", "note": "n",
                             "higher_is_better": True, "proxy": False,
                             "group": "move",
                             "sides": [{"offense": "ATL", "defense": "GB",
                                        "off_val": 0.1, "def_val": 0.0,
                                        "diff": 0.1, "edge": 0.1}]},
                             {"key": "early_down_success",
                              "label": "Early-down success", "note": "n2",
                              "higher_is_better": True, "proxy": False,
                              "group": "move",
                              "sides": [{"offense": "GB", "defense": "ATL",
                                         "off_val": 0.44, "def_val": 0.40,
                                         "diff": 0.04, "edge": 0.04}]},
                             {"key": "sack_rate", "label": "Sack rate",
                              "note": "PROXY for pressure.",
                              "higher_is_better": False, "proxy": True,
                              "group": "rush",
                              "sides": [{"offense": "ATL", "defense": "GB",
                                         "off_val": 0.06, "def_val": 0.08,
                                         "diff": -0.02, "edge": 0.02}]}],
                           "h1": [{"key": "epa_play", "label": "EPA per play",
                             "note": "n", "higher_is_better": True,
                             "proxy": False, "group": "move",
                             "sides": [{"offense": "ATL", "defense": "GB",
                                        "off_val": 0.3, "def_val": 0.0,
                                        "diff": 0.3, "edge": 0.3}]}]},
                         "missing": [{"what": "Four-man rush vs blitz",
                                      "why": "field empty for 2026"}],
                         "rows": [{"key": "early_down_success",
                                   "label": "Early-down success",
                                   "note": "Share of 1st and 2nd down plays.",
                                   "higher_is_better": True, "proxy": False,
                                   "group": "move",
                                   "sides": [{"offense": "ATL", "defense": "GB",
                                              "off_val": 0.42, "def_val": 0.39,
                                              "diff": 0.03, "edge": 0.03}]}]},
             "scores": {"n": 403, "thin": False, "min_n": 60, "home": "GB",
                        "away": "ATL", "total": 44.5, "mean_total": 46.4,
                        "mean_margin": 6.3,
                        "home_win": {"n": 287, "pct": 71.2, "lo": 66.6,
                                     "hi": 75.4},
                        "over": {"n": 207, "pct": 51.4, "lo": 46.5,
                                 "hi": 56.2},
                        # Shaped as `score_dist.summary` now leaves it: `p` is
                        # the MEASURED rate at that rank, not the scoreline's
                        # share, and ranks two and below share one number
                        # because the record cannot separate them.
                        "scores_n": 2418,
                        "scores_covered": 5.5,
                        "scores_flat_from": 2,
                        "scores": [{"home": 27, "away": 20, "n": 22, "p": 1.37},
                                   {"home": 20, "away": 17, "n": 23, "p": 0.59},
                                   {"home": 23, "away": 20, "n": 23, "p": 0.59}],
                        "margins": [
                            {"band": "GB by 15+", "mlo": 15, "mhi": None,
                             "n": 106, "pct": 26.3, "lo": 22.2, "hi": 30.8},
                            {"band": "GB by 8-14", "mlo": 8, "mhi": 14,
                             "n": 70, "pct": 17.4, "lo": 14.0, "hi": 21.3},
                            # THE BAND THE LINE FALLS INSIDE. The spread is
                            # -6.5, so this is the one the rule cuts, and it
                            # is neither covering nor not.
                            {"band": "GB by 4-7", "mlo": 4, "mhi": 7,
                             "n": 60, "pct": 14.9, "lo": 11.7, "hi": 18.7},
                            {"band": "GB by 1-3", "mlo": 1, "mhi": 3,
                             "n": 48, "pct": 11.9, "lo": 9.1, "hi": 15.4},
                            {"band": "Tie", "mlo": 0, "mhi": 0, "n": 6,
                             "pct": 1.5, "lo": 0.7, "hi": 3.2},
                            {"band": "ATL by 1-3", "mlo": -3, "mhi": -1,
                             "n": 45, "pct": 11.2, "lo": 8.5, "hi": 14.6},
                            {"band": "ATL by 4-7", "mlo": -7, "mhi": -4,
                             "n": 30, "pct": 7.4, "lo": 5.2, "hi": 10.4},
                            {"band": "ATL by 8-14", "mlo": -14, "mhi": -8,
                             "n": 24, "pct": 6.0, "lo": 4.0, "hi": 8.7},
                            {"band": "ATL by 15+", "mlo": None, "mhi": -15,
                             "n": 14, "pct": 3.5, "lo": 2.1, "hi": 5.8}]},
             "injuries": {"GB": [{"player": "Jayden Reed", "pos": "WR",
                                  "status": "Out", "injury": "Neck",
                                  "practice": "Did not practice",
                                  "rest": False}],
                          "ATL": [{"player": "A.J. Terrell", "pos": "CB",
                                   "status": None, "injury": "Groin",
                                   "practice": "Did not practice",
                                   "rest": False}]},
             "injury_key": 1,
             "unfold": {"n": 403, "thin": False, "home": "GB", "away": "ATL",
                        "fav": "GB", "dog": "ATL", "total": 44.5,
                        "bands": [{"key": "upset", "short": "ATL wins"},
                                  {"key": "tie", "short": "Level"},
                                  {"key": "narrow", "short": "GB by 1-7"},
                                  {"key": "comfortable",
                                   "short": "GB by 8-14"},
                                  {"key": "pulls away",
                                   "short": "GB by 15+"}],
                        "cells": [
                            {"key": "narrow_over", "band": "narrow",
                             "side": "over", "label": "GB edges it, high scoring",
                             "n": 66, "pct": 16.4, "lo": 13.1, "hi": 20.3},
                            {"key": "upset_under", "band": "upset",
                             "side": "under",
                             "label": "ATL wins outright, low scoring",
                             "n": 61, "pct": 15.1, "lo": 12.0, "hi": 18.9}],
                        "headline": {
                            "one_score": {"n": 202, "pct": 50.1, "lo": 45.3,
                                          "hi": 55.0},
                            "blowout": {"n": 107, "pct": 26.6, "lo": 22.5,
                                        "hi": 31.1},
                            "upset": {"n": 115, "pct": 28.5, "lo": 24.3,
                                      "hi": 33.1},
                            "shootout": {"n": 126, "pct": 31.3, "lo": 26.9,
                                         "hi": 36.0},
                            "grind": {"n": 108, "pct": 26.8, "lo": 22.7,
                                      "hi": 31.3}}},
             "ladders": {"n": 403, "thin": False, "home": "GB", "away": "ATL",
                         "teams": [{"team": "GB", "rows": [
                             {"line": 20.5, "n": 286, "pct": 71.0,
                              "lo": 66.0, "hi": 75.0}]}],
                         # `ours` sits on a DIFFERENT rung from `posted` on
                         # purpose: when the two coincide the card says there
                         # is nothing to disagree about, which would not
                         # exercise the gap line.
                         "total": {"posted": 44.5, "ours": 46.4, "rows": [
                             {"line": 44.5, "n": 207, "pct": 51.4,
                              "lo": 46.5, "hi": 56.2},
                             {"line": 46.5, "n": 181, "pct": 44.9,
                              "lo": 40.1, "hi": 49.8}]},
                         "spread": {"posted": 6.5, "ours": 5.7, "rows": [
                             {"line": 5.5, "n": 194, "pct": 48.1,
                              "lo": 43.2, "hi": 53.0},
                             {"line": 6.5, "n": 180, "pct": 44.7,
                              "lo": 39.9, "hi": 49.6}]}}},
            {"game_id": "ARI_SF", "home": "SF", "away": "ARI",
             "total": 47.5, "spread": -8.5, "proj_home": 28.0, "proj_away": 19.5,
             "win_home": 0.78, "win_away": 0.22,
             "kick_day": "Sunday", "kick_et": "4:25 PM ET", "prime": False},
        ],
        # A past week of game lines, so the selector has somewhere to go on
        # the screen that is now the landing page.
        # THE THREE BASES DISAGREE ON THIS GAME, on purpose. The book and
        # the blend favor BUF, who won; the model favors DET, who lost. A
        # fixture where all three pick the same side cannot tell whether the
        # board grades the one it says it grades.
        "past": {"2": {"cards": [
            {"game_id": "DET_BUF", "home": "BUF", "away": "DET",
             "total": 54.5, "spread": -5.5, "win_home": 0.681,
             "win_away": 0.319, "final_home": 41, "final_away": 31,
             "model_spread": 1.5, "model_total": 50.0,
             "model_win_home": 0.42, "model_win_n": 300,
             "blend": {"spread": -2.0, "total": 52.0},
             "kick_day": "Sunday", "kick_et": "1:00 PM ET"}],
            "rows": []}},
        "public": {"ATL_GB": {
            "spreads": {"captures": 2, "sides": [
                {"side": "GB", "pct": 62.4, "open_pct": 55.0, "drift": 7.4},
                {"side": "ATL", "pct": 37.6, "open_pct": 45.0, "drift": -7.4}]},
            "totals": {"captures": 2, "sides": [
                {"side": "Over", "pct": 55.4, "open_pct": 55.4, "drift": None},
                {"side": "Under", "pct": 44.6, "open_pct": 44.6,
                 "drift": None}]}}},
        "rows": [
            {"game_id": "ATL_GB", "home": "GB", "away": "ATL", "market": "h2h",
             "outcome": "GB", "point": None, "consensus": -245, "best": -225,
             "best_book": "lowvig", "fair": 0.684, "ev100": 1.2, "gap_pp": 2.9,
             "n_books": 21, "move_pp": -2.9, "open_odds": -283},
            {"game_id": "ATL_GB", "home": "GB", "away": "ATL",
             "market": "spreads", "outcome": "ATL", "point": 6.5,
             "consensus": -110, "best": -105, "best_book": "fanduel",
             "fair": 0.5, "ev100": -1.0, "gap_pp": 1.1, "n_books": 20,
             "move_pp": 0.4, "open_odds": -112},
            {"game_id": "ATL_GB", "home": "GB", "away": "ATL",
             "market": "totals", "outcome": "Over", "point": 44.5,
             "consensus": -110, "best": -108, "best_book": "draftkings",
             "fair": 0.5, "ev100": -0.5, "gap_pp": 0.4, "n_books": 20,
             "move_pp": 0.0, "open_odds": -110},
        ],
    }
    p["notes"] = {"ATL_GB": [
        {"id": "ATL_GB:line_gap", "kind": "line_gap", "cat": "The line",
         "title": "Our model sees a closer game", "unproven": True,
         "stats": [{"v": "GB by 6.5", "l": "sportsbooks"},
                   {"v": "GB by 0.9", "l": "our model"}],
         "why": "The book has Green Bay comfortable; our model has it tight.",
         "pick": "ATL on the spread"},
        {"id": "ATL_GB:td_value", "kind": "td_value", "cat": "Players",
         "title": "The best-priced touchdown bet here", "measured": False,
         "stats": [{"v": "35%", "l": "our chance"}, {"v": "27%", "l": "books'"}],
         "why": "We make him likelier than the price implies.",
         "pick": "Tucker Kraft to score"},
        {"id": "ATL_GB:coach_prime", "kind": "coach_prime", "cat": "Coaching",
         "title": "LaFleur has covered 25 of 36 prime-time games",
         "context": True,
         "stats": [{"v": "25-11", "l": "Matt LaFleur, prime time"}],
         "why": "Covering means beating the line, not merely winning.",
         "pick": "ATL at GB on the spread"},
    ]}
    # TICKET AND MONEY SPLITS, shaped as `action_public.week_view` leaves
    # them. Carolina is here on purpose: a 7-point gap, under every threshold
    # that earns a sentence, and three times the average bet — the case a gap
    # ranking silently drops.
    p.setdefault("games", {})["splits"] = {
        "ATL_GB": {
            "moneyline": {"captures": 3, "sides": [
                {"side": "GB", "odds": -250, "tickets": 89.0, "money": 54.0,
                 "gap": -35.0, "ratio": 0.15},
                {"side": "ATL", "odds": 205, "tickets": 11.0, "money": 46.0,
                 "gap": 35.0, "ratio": 6.89}]},
            "spread": {"captures": 3, "sides": [
                {"side": "GB", "odds": -110, "tickets": 53.0, "money": 40.0,
                 "gap": -13.0, "ratio": 0.59},
                {"side": "ATL", "odds": -110, "tickets": 47.0, "money": 60.0,
                 "gap": 13.0, "ratio": 1.69}]},
            "total": {"captures": 3, "sides": [
                {"side": "Over", "odds": -110, "tickets": 50.0, "money": 55.0,
                 "gap": 5.0, "ratio": 1.22},
                {"side": "Under", "odds": -110, "tickets": 50.0, "money": 45.0,
                 "gap": -5.0, "ratio": 0.82}]},
        },
        # Keyed to match a BOARD row's game, so the player detail has a game
        # to inherit money from. The board's players live in "AAA @ BBB".
        "AAA @ BBB": {
            "moneyline": {"captures": 3, "sides": [
                {"side": "BBB", "odds": -250, "tickets": 80.0, "money": 50.0,
                 "gap": -30.0, "ratio": 0.25},
                {"side": "AAA", "odds": 205, "tickets": 20.0, "money": 50.0,
                 "gap": 30.0, "ratio": 4.0}]},
        },
        "CAR_CLE": {
            "moneyline": {"captures": 3, "sides": [
                {"side": "CAR", "odds": -146, "tickets": 89.0, "money": 96.0,
                 "gap": 7.0, "ratio": 2.97},
                {"side": "CLE", "odds": 120, "tickets": 11.0, "money": 4.0,
                 "gap": -7.0, "ratio": 0.34}]},
        },
    }
    # An index shaped exactly as `_split_history` leaves it: weeks lifted out
    # into files, `has` naming which of them exist.
    p["history"] = {"anytime_td": {"has": [1, 2],
                                   "accuracy": {"1": {"n": 120}, "2": {"n": 118}}}}
    p["history_path"] = "data/h-{market}-{week}.json"
    # THE ANGLES BOARD, with a winner, a loser and one added later — the three
    # shapes the page has to draw. Without a losing row the "nothing is
    # dropped for going cold" assertion passes by having nothing to drop.
    # A PLAYER'S PAST LINES. Two markets on purpose -- one with a line and one
    # without -- because the two are drawn differently and a fixture carrying
    # only one leaves the other's renderer untested while the file reports all
    # passed. `Alpha Back` is on the anytime board above; `Bravo Wide` carries
    # a week he recorded nothing, which is the row this table exists to show.
    p["pastlines"] = {
        "markets": [
            {"key": "anytime_td", "label": "Anytime touchdown",
             "kind": "yesno", "unit": ""},
            {"key": "receptions", "label": "Receptions", "kind": "line",
             "unit": "catches"},
        ],
        "inline": 3,
        "players": {
            "Alpha Back": {
                # TEN WEEKS, so the window control has something to narrow —
                # it is only drawn where it would, and a three-week fixture
                # left every assertion about it unexercised while the run
                # still reported passing.
                #
                # One week he did not play (played=0): a book voids that bet
                # and hands the stake back, and counting it as a losing $100
                # is the error the flag exists to prevent. One week with no
                # archived price, which is not a bet at all. And two rows in
                # the OLD seven-field shape, because a cached payload written
                # before `played` existed must keep its answer rather than
                # have every week of it voided.
                "anytime_td": [[2026, 3, "GB", 0, None, 140, 1, 1],
                               [2026, 2, "CHI", 1, None, 175, 0, 1],
                               [2026, 1, "MIN", 0, None, 120, 1, 1],
                               [2025, 18, "DET", 1, None, 240, 0, 0],
                               [2025, 17, "SEA", 0, None, -110, 1, 1],
                               [2025, 16, "LA", 1, None, 160, 0, 1],
                               [2025, 15, "SF", 0, None, None, 0, 1],
                               [2025, 14, "ARI", 1, None, 130, 1, 1],
                               [2025, 13, "NO", 0, None, 210, 0],
                               [2025, 12, "TB", 1, None, 115, 1]],
                # A WINDOW THAT RAN UNDER, with the under's price on it.
                #
                # Seven of ten under at -130 and three over: 7 x $76.92 won
                # against $300 lost is +$238, and the panel has to price the
                # UNDER to get there. Backing the over on the same ten weeks
                # is the opposite question and a different number, which is
                # the bug this fixture exists to catch.
                #
                # The ninth field is the under's price, recovered from the
                # two-sided quote in `player_history`, not assumed.
                "receptions": [
                    [2026, 3, "GB", 0, 3.5, 100, 2.0, 1, -130],
                    [2026, 2, "CHI", 1, 4.5, 100, 2.0, 1, -130],
                    [2026, 1, "MIN", 0, 3.5, 100, 1.0, 1, -130],
                    [2025, 18, "DET", 1, 4.5, 100, 6.0, 1, -130],
                    [2025, 17, "SEA", 0, 3.5, 100, 2.0, 1, -130],
                    [2025, 16, "LA", 1, 4.5, 100, 1.0, 1, -130],
                    [2025, 15, "SF", 0, 3.5, 100, 5.0, 1, -130],
                    [2025, 14, "ARI", 1, 4.5, 100, 3.0, 1, -130],
                    [2025, 13, "NO", 0, 3.5, 100, 7.0, 1, -130],
                    [2025, 12, "TB", 1, 4.5, 100, 0.0, 1, -130]],
            },
            "Bravo Wide": {
                "receptions": [[2026, 3, "GB", 0, 5.5, -110, 0.0],
                               [2026, 2, "CHI", 1, 5.5, -110, 7.0]],
            },
        },
    }
    p["angles"] = {
        "break_even": 0.5238,
        # A row is tinted only when it clears AND has the games to mean it.
        # The fixture's floor is low so a fixture row can still go green;
        # production uses 300.
        "tint_min": 200,
        # THE KINDS, IN THE ORDER BOTH FILTERS OFFER THEM, and deliberately
        # longer than the two the rows below use: the surfaces are supposed to
        # drop a kind nothing carries rather than draw an option that filters
        # to an empty screen. Reversed against the rows' own order too, so a
        # page that quietly sorted them itself would show it.
        "cats": ["The line", "Form", "Setting", "Spot", "Rest", "Opponent"],
        "rows": [
            {"id": "blowout_loss", "label": "Off a 20+ loss",
             "blurb": "{team} lost by {detail} last week.",
             "added": "2026-09-28", "mined": False,
             "plain": "Beaten by three touchdowns or more last week.",
             "cat": "Form",
             "all": {"n": 504, "w": 265, "l": 239, "pct": 0.526,
                     "lo": 0.482, "hi": 0.569, "clears": False},
             "since": None,
             "season": {"n": 8, "w": 7, "l": 1, "pct": 0.875,
                        "lo": 0.529, "hi": 0.978, "clears": True}},
            {"id": "div_dog", "label": "Divisional underdog",
             "blurb": "{team} is a divisional underdog.",
             "added": "2026-10-05", "mined": True,
             "plain": "An underdog against a divisional rival.",
             "cat": "The line", "mirror": "div_fav",
             "all": {"n": 1046, "w": 548, "l": 498, "pct": 0.524,
                     "lo": 0.494, "hi": 0.554, "clears": False},
             "since": {"n": 30, "w": 14, "l": 16, "pct": 0.467,
                       "lo": 0.298, "hi": 0.643, "clears": False},
             "season": {"n": 13, "w": 8, "l": 5, "pct": 0.615,
                        "lo": 0.355, "hi": 0.823, "clears": False}},
            # THE OTHER HALF OF `div_dog`, same games and the cover on the
            # other side, so the flip-side tag and the sentence that shows both
            # records have something to find. Slotted here because the board
            # arrives sorted by the long run and a test below asserts it.
            {"id": "div_fav", "label": "Divisional favorite",
             "blurb": "{team} is a divisional favorite.",
             "added": "2026-10-05", "mined": True, "mirror": "div_dog",
             "plain": "Favoured against a divisional rival.",
             "cat": "The line",
             "all": {"n": 1046, "w": 498, "l": 548, "pct": 0.476,
                     "lo": 0.446, "hi": 0.506, "clears": False},
             "since": None,
             "season": {"n": 13, "w": 5, "l": 8, "pct": 0.385,
                        "lo": 0.177, "hi": 0.645, "clears": False}},
            {"id": "off_ot", "label": "Off an overtime game",
             "blurb": "{team} went to overtime last week.",
             "added": "2026-09-28", "mined": False, "whole_game": True,
             "plain": "Played overtime last week.",
             "cat": "Form",
             "all": {"n": 301, "w": 141, "l": 160, "pct": 0.468,
                     "lo": 0.413, "hi": 0.525, "clears": False},
             "since": None,
             # DELIBERATELY THE BEST SEASON AND THE WORST LONG RUN. With
             # three rows whose season order, long-run order and alphabetical
             # order all coincided, every sort assertion passed without the
             # sort doing anything.
             "season": {"n": 5, "w": 5, "l": 0, "pct": 1.0,
                        "lo": 0.566, "hi": 1.0, "clears": True}},
        ],
        # KEYED BY GAME, not by team. Keyed by team, a week-3 answer was
        # printed under a week-4 fixture, because the board carries whatever
        # the books have posted and that is regularly more than one week.
        # `DET_BUF` is a DIFFERENT game and its entries must not reach the
        # ATL at GB card.
        # KEYED BY GAME, not by team. Keyed by team, a week-3 answer was
        # printed under a week-4 fixture, because the board carries whatever
        # the books have posted and that is regularly more than one week.
        #
        # ATL APPEARS IN TWO GAMES ON PURPOSE. That is the shape of the bug:
        # a team-keyed lookup pulls `CAR_ATL`'s entry onto the `ATL_GB` card,
        # and a fixture where each team appears once cannot tell the two
        # lookups apart.
        "week": {"ATL_GB": [["ATL", "blowout_loss"], ["GB", "div_dog"],
                            ["ATL", "div_fav"], ["GB", "off_ot"]],
                 "CAR_ATL": [["ATL", "off_ot"], ["CAR", "div_dog"]]},
        # WHAT THE SPLIT'S OWN COMPOSITION PREDICTS. `blowout_loss` is put
        # entirely in the road-underdog cell, which covers 60% here against
        # 40% for home favorites, so its expectation is 60% and its long run
        # of 52.6% is a FADE, not an edge. A fixture whose cells all cover at
        # the same rate cannot tell whether the page used the mix at all.
        "baseline": {
            "cells": {
                "2015": {"AD": [60, 100], "AF": [50, 100],
                         "HD": [50, 100], "HF": [40, 100]},
                "2026": {"AD": [6, 10], "AF": [5, 10],
                         "HD": [5, 10], "HF": [4, 10]},
            },
            "mix": {"blowout_loss": {"2015": [100, 0, 0, 0],
                                     "2026": [10, 0, 0, 0]},
                    "div_dog": {"2015": [0, 0, 50, 50]},
                    "off_ot": {"2015": [0, 0, 0, 40]}},
            "team_mix": {
                "ATL": {"blowout_loss": {"2015": [0, 0, 0, 4]},
                        "off_ot": {"2015": [5, 0, 0, 0]}},
                "GB": {"div_dog": {"2015": [0, 0, 7, 0]},
                       "off_ot": {"2015": [0, 0, 0, 5]}},
            },
        },
        # PER TEAM PER SEASON, which is the only reading under which a
        # whole-game condition says anything: `off_ot` is flagged
        # `whole_game`, so league-wide it is 50.00% by arithmetic, and ATL's
        # own record in it is 1-4. The two must not be the same number, or
        # the test cannot tell which one the page drew.
        "team_splits": {
            "ATL": {"blowout_loss": {"2015": [3, 1], "2026": [1, 0]},
                    "off_ot": {"2015": [1, 4], "2026": [0, 1]},
                    "div_dog": {"2015": [2, 2]}},
            "GB": {"div_dog": {"2015": [6, 1], "2026": [1, 1]},
                   "off_ot": {"2015": [4, 1], "2026": [1, 0]}},
        },
        # Per-season records, which is what lets the page answer "since 2020"
        # without another measurement. Without these the slider has no range
        # and silently clamps to a single year.
        "splits": {
            "blowout_loss": {"2015": [20, 21], "2020": [24, 18],
                             "2023": [22, 26], "2026": [7, 1]},
            "div_dog": {"2015": [48, 44], "2020": [50, 46],
                        "2023": [45, 47], "2026": [8, 5]},
            "div_fav": {"2015": [44, 48], "2020": [46, 50],
                        "2023": [47, 45], "2026": [5, 8]},
            "off_ot": {"2015": [11, 14], "2020": [12, 13],
                       "2023": [10, 15], "2026": [3, 2]},
        },
        # ONE FIXTURE PER BOARD, so the link out is exercised on each.
        # `DET_BUF` is in the archive for week 2; `ATL_GB` is on the live
        # board for week 3, which is the Monday case — played, but its week
        # is still open, so it is NOT in `past`; `MIA_NYJ` is week 4, on the
        # schedule and on no board at all.
        "games": {"blowout_loss": [
            {"week": 2, "team": "DET", "opp": "BUF", "home": False,
             "game_id": "2026_02_DET_BUF", "gid": "DET_BUF",
             "spread": -3.5, "pf": 31, "pa": 41, "covered": False,
             "by": -17.5, "played": True},
            {"week": 3, "team": "ATL", "opp": "GB", "home": False,
             "game_id": "2026_03_ATL_GB", "gid": "ATL_GB",
             "spread": -6.5, "pf": 20, "pa": 24, "covered": True,
             "by": 2.5, "played": True},
            # A PUSH: played, landed exactly on the number, graded as
            # neither. It reaches the page as `covered: None`, the same as a
            # fixture that has not kicked off, and the two must not render
            # the same way.
            {"week": 1, "team": "SEA", "opp": "NE", "home": True,
             "game_id": "2026_01_NE_SEA", "gid": "NE_SEA",
             "spread": 3.0, "pf": 13, "pa": 10, "covered": None,
             "by": 0.0, "played": True},
            {"week": 4, "team": "MIA", "opp": "NYJ", "home": False,
             "game_id": "2026_04_MIA_NYJ", "gid": "MIA_NYJ",
             "spread": 2.5, "pf": None, "pa": None, "covered": None,
             "by": None, "played": False}]},
    }
    # RECENT FORM, CROSSING A SEASON ON PURPOSE. Ten games in week 3 is
    # mostly last year, which is the case the divider and the muted bars
    # exist for — a fixture that stayed inside one season would render
    # neither and report passing.
    #
    # GB's week-1 row carries no expectation, because a game the archive has
    # no line for must draw a bar and no tick rather than a tick at zero.
    def _form(team, base):
        rows = []
        for i in range(10):
            szn, wk = (2026, 3 - i) if i < 2 else (2025, 20 - i)
            pf = base + (i % 4) * 3
            pa = base - 2 + (i % 3) * 4
            rows.append([szn, wk, "OPP", i % 2, pf, pa,
                         None if (team == "GB" and i == 1) else 22.5,
                         None if (team == "GB" and i == 1) else 21.0])
        return rows
    p["teamform"] = {"last": 10,
                     "teams": {"GB": _form("GB", 24), "ATL": _form("ATL", 19)}}

    # AGAINST THE NUMBER, with every branch the panel can take in it.
    #
    # A fixture of ten clean covers would render the common row and report
    # passing on a panel that crashes on any of the four cases that actually
    # occur: a push, an ungraded week with no posted line, a week the feed has
    # no price for, and a record that ran the other way so the money question
    # is about fading rather than backing.
    def _lines(team, flip):
        rows = []
        # Exactly the inline count, because that is what the real payload
        # carries: `_team_lines_block` slices to `TEAMLINES_INLINE` and the
        # rest goes to the fetched file.
        for i in range(10):
            szn, wk = (2026, 3 - i) if i < 2 else (2025, 20 - i)
            # GB's spread record runs the team's way and ATL's runs against
            # it, so one panel prices backing the team and the other prices
            # FADING it — the branch with its own wording, and the one the
            # player panel cannot offer because that archive holds one side.
            res = 1 if (i % 4) else -1
            if flip:
                res = -res
            push = i == 4
            bare = i == 6      # no line posted: null results
            noprice = i == 7   # graded, and no price to bet it at
            rows.append([
                szn, wk, "OPP", i % 2, 24 - (i % 5), 17 + (i % 4),
                None if bare else (-3.5 if flip else 2.5),
                None if bare else 44.5,
                None if bare else (0 if push else res),
                None if bare else (0 if push else -res),
                None if bare else res,
                None if noprice else -110, None if noprice else -108,
                None if noprice else -105, None if noprice else -115,
                None if noprice else (145 if flip else -165),
                None if noprice else (-175 if flip else 140),
            ])
        return rows
    p["teamlines"] = {
        "markets": [{"key": "ats", "label": "Against the spread",
                     "won": "covered", "lost": "did not cover"},
                    {"key": "ou", "label": "Over/under",
                     "won": "over", "lost": "under"},
                    {"key": "ml", "label": "Moneyline",
                     "won": "won", "lost": "lost"}],
        "inline": 10,
        "teams": {"GB": _lines("GB", False), "ATL": _lines("ATL", True)},
    }

    # HOW THIS ONE GOES, both ways it can arrive: one written and one on the
    # template, because the template is a different render path and the label
    # that distinguishes them only appears on one of them.
    cards = (p.get("games") or {}).get("cards") or []
    if cards:
        p["stories"] = {
            cards[0]["game_id"]: {
                "paras": ["Atlanta arrives on a short week.",
                          "Green Bay has scored above expectation.",
                          "The matchup turns on third down.",
                          "This sets up close and low-scoring."],
                "scoreline": {"away": cards[0].get("away", "ATL"),
                              "home": cards[0].get("home", "GB"),
                              "away_pts": 19.4, "home_pts": 23.1,
                              "spread": -3.7, "total": 42.5,
                              "lead": cards[0].get("home", "GB")},
                "written": True},
        }
        if len(cards) > 1:
            p["stories"][cards[1]["game_id"]] = {
                "paras": ["The book makes this one close."],
                "scoreline": None, "written": False,
                "rejected": "it names somebody the facts do not"}
    # THE SCORECARD, with both the cases the page branches on: a market
    # level with the book and one behind it, a thin calibration band, and a
    # week whose board was rebuilt rather than frozen. A fixture of one
    # healthy market would render the page and exercise none of it.
    p["scorecard"] = {
        "season": 2026, "bucket_min": 25,
        "markets": {
            "anytime_td": {
                "sources": ["mixed", "rebuilt"],
                "weeks": [
                    {"week": 1, "source": "rebuilt", "n": 362,
                     "brier": 0.1228, "book_brier": 0.1325,
                     "brier_edge": 0.0098, "log_loss": 0.38,
                     "book_log_loss": 0.40, "log_loss_edge": 0.02,
                     "said": 0.182, "book_said": 0.180, "actual": 0.188,
                     "per_game": {"games": 16, "said": 4.1, "actual": 4.2}},
                    {"week": 2, "source": "mixed", "n": 389,
                     "brier": 0.1011, "book_brier": 0.0989,
                     "brier_edge": -0.0021, "log_loss": 0.33,
                     "book_log_loss": 0.32, "log_loss_edge": -0.01,
                     "said": 0.174, "book_said": 0.170, "actual": 0.131,
                     "per_game": {"games": 16, "said": 4.2, "actual": 3.2}},
                ],
                "pooled": {"n": 751, "brier": 0.1115, "book_brier": 0.1152,
                           "brier_edge": 0.0037, "log_loss": 0.355,
                           "book_log_loss": 0.360, "log_loss_edge": 0.005,
                           "said": 0.178, "book_said": 0.175,
                           "actual": 0.158},
                "buckets": [
                    {"lo": 0, "hi": 5, "n": 329, "said": 0.030,
                     "actual": 0.043, "thin": False},
                    {"lo": 5, "hi": 10, "n": 292, "said": 0.068,
                     "actual": 0.072, "thin": False},
                    {"lo": 45, "hi": 100, "n": 7, "said": 0.564,
                     "actual": 0.540, "thin": True},
                ],
                "per_game": {"games": 32, "said": 4.17, "actual": 3.70},
            },
            "first_td": {
                "sources": ["frozen"],
                "weeks": [
                    {"week": 1, "source": "frozen", "n": 360,
                     "brier": 0.0384, "book_brier": 0.0375,
                     "brier_edge": -0.0009, "log_loss": 0.16,
                     "book_log_loss": 0.159, "log_loss_edge": -0.001,
                     "said": 0.040, "book_said": 0.041, "actual": 0.042,
                     "per_game": {"games": 16, "said": 0.9, "actual": 0.95}},
                ],
                "pooled": {"n": 360, "brier": 0.0384, "book_brier": 0.0375,
                           "brier_edge": -0.0009, "log_loss": 0.16,
                           "book_log_loss": 0.159, "log_loss_edge": -0.001,
                           "said": 0.040, "book_said": 0.041,
                           "actual": 0.042},
                "buckets": [{"lo": 0, "hi": 5, "n": 300, "said": 0.017,
                             "actual": 0.022, "thin": False}],
                "per_game": {"games": 16, "said": 0.92, "actual": 0.97},
            },
        },
        "omitted": ["Weekly return on investment \u2014 at these sample "
                    "sizes one Sunday moves it more than the model does."],
    }
    return p


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_every_v3_screen_renders(payload_v3, v3_js, tmp_path):
    """Every tab, every market, every filter, and inside a game.

    Includes the two paths the shared fixture cannot reach: a past week, and
    the game-detail screen with its notes, players and bets tabs.
    """
    p = tmp_path / "payload.json"
    p.write_text(json.dumps(payload_v3))
    r = subprocess.run(["node", str(REPO / "tests" / "js" / "v3app.js"),
                        str(p), str(v3_js)],
                       capture_output=True, text=True, cwd=str(REPO))
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    # And that the enriched fixture actually reached them, rather than
    # reporting "not exercised" and passing.
    for path in ("a past week renders", "game tab notes renders",
                 "game tab bets renders",
                 # The season record: that it rendered at all, that the sign
                 # of the edge is the right way round, and that the two
                 # sentences a thin sample most needs were reached.
                 "the record screen names both markets",
                 "an edge in our favor is positive and marked good",
                 "and an edge against us is negative and marked bad",
                 "a sub-threshold edge is reported as level, not as ahead",
                 "a market with rebuilt weeks says so",
                 "and one frozen before kickoff says that instead",
                 "a thin calibration band is marked thin rather than read",
                 "an empty scorecard says so rather than rendering nothing",
                 # Against the number: the panel, and the four branches a
                 # fixture of ten clean covers would never reach.
                 "the odds tab carries each side’s record "
                 "against the number",
                 "a push is marked as a push rather than a loss",
                 "a game with no posted line has no result against it",
                 "a game with no price is named rather than counted",
                 "and fades the team whose record ran the other way",
                 "no result mark is colored as a verdict",
                 "narrowing the window narrows both tables",
                 "a fetch that failed says so rather than "
                 "redrawing the same ten",
                 "the fetched record replaces the inlined ten",
                 # Difference: the sort, both ends of it, and the two markets
                 # where it does and does not apply.
                 "the board can be sorted by the difference",
                 "descending leads with the projection furthest above the line",
                 "ascending reaches the strongest unders instead",
                 "and the two ends are different rows",
                 "an opened row states the difference it was sorted by",
                 "a touchdown board does not offer the difference sort",
                 "a difference sort carried onto a touchdown board falls back",
                 "and the sort is offered again on a market with lines",
                 # The story, and that it sits under its evidence.
                 "the Read tab carries the story",
                 "and it comes after the notes it reads from",
                 "the number is stated by code beneath the words",
                 "a story that fell back to the template says so",
                 "a played game says what we said beforehand",
                 "and does not call it a preview",
                 "the number is labeled as the one we had",
                 "and an unplayed game is still a preview",
                 "a coaching note is labeled as context",
                 "and score is not a section of its own",
                 "the bets tab is a ladder, not a list of books",
                 "the outcome tab carries BOTH, score first then the ladder",
                 "and the tab bar no longer offers them separately",
                 "an old tab name does not render an empty screen",
                 "the ask control is on the edge tab",
                 "tapping it opens the ask sheet",
                 "the slip opens on the round robin by default",
                 "keeping copies the slip into Picks",
                 "and leaves the slip alone",
                 "keeping the same slip twice keeps one copy",
                 "the saved copy stores its own legs",
                 "and the payout curve it was priced at",
                 "the Picks screen renders",
                 "a kept slip can be removed",
                 "tapping a saved pick opens its breakdown",
                 "and draws the stored curve, not the live one",
                 "choosing returns to the slip",
                 "changing the bet type keeps the slip open",
                 "ordinals read like English",
                 "one touchdown is singular",
                 "three touchdowns are plural",
                 "a blank is named, not left as a zero",
                 "an unrecorded count says nothing",
                 "the first-TD board names which touchdown it was",
                 "an over/under row prints the stat it settled on",
                 "the normalizer carries the count through",
                 "a settled row shows what they actually had",
                 "the panel offers a default question",
                 "and it names all three markets",
                 "it is not one of the canned chips",
                 "and it is marked as the one that thinks",
                 "the handler is registered",
                 "the split feed carries all three markets, not just the moneyline",
                 "every market is drawn with a bets bar and a money bar",
                 "and all three are named",
                 "no percentage-point jargon anywhere on the card",
                 "the card explains what a line move means",
                 "with no second card repeating it",
                 "and ranks them by ratio, biggest bet first",
                 "a side backed by ordinary-sized bets is left out",
                 "a heavily backed side with the money behind it still surfaces",
                 "the card refuses to call itself a tip",
                 "the current price is read raw, margin and all",
                 "a market that came toward the pick is counted as toward",
                 "a market that drifted away is not counted as toward",
                 "a pick we rated below the open is not counted at all",
                 "three picks are too few to report a share",
                 "a first-TD row names the ordinal, not the count",
                 "a player inherits the money on their own game",
                 "a player facing the money is told so, not merely told there is money",
                 "some board row sits in a game with money on it",
                 "every row carries its place in the order",
                 "the box names the side we lean, not always the home team",
                 "leaning away and the away team winning is green",
                 "and the home team winning after we leaned away is red",
                 "which is the case that used to be colored backwards",
                 "a tie is neither color",
                 "and a push says so",
                 "the list is in the order the model ranked them",
                 "and the proximity tint is gone with the ordering it "
                 "belonged to",
                 "and no per-row percentage sits beside a per-scoreline count",
                 "and our number is stated rather than only implied",
                 "and every row says how far it sits from that number",
                 "the posted total is actually a marked rung",
                 "the section bar has its own sticky wrapper",
                 "and the control inside it is unchanged",
                 "switching section does not throw",
                 "and lands on the section rather than the tab you left",
                 "and the scroll intent is consumed, not left armed",
                 "and the gap to our number is stated above the table",
                 "the exact-score card says what the whole list is worth",
                 "the opened player row names the money in their game",
                 "and changing the stake keeps it open too",
                 "the bar opens the slip rather than navigating",
                 "tapping it opens the slip sheet",
                 "and stays on the board underneath",
                 "the ask control is inside the pinned bar",
                 "and above the section control it shares the bar with",
                 "and appears once, not in both places",
                 "and does not leave the tab",
                 "the notes tab opens with how the game may unfold",
                 "the public split is not inline on the players tab",
                 "the injury report is a view of the matchup",
                 "and is not stacked above the table on the other views",
                 "with the efficiency rows put away while it is showing",
                 "no \"Based on\" preamble above the numbers",
                 "and no list of what was left out below them",
                 "the metrics can be filtered by what they measure",
                 "picking a group shows fewer rows than all of them",
                 "with that group pressed",
                 "while the sections keep the order the pipeline sent",
                 "and the chooser rides in the pinned bar, not under it",
                 "it is a handful of groups, not one control per metric",
                 "and is absent on the injury view",
                 # The angle kinds, on both surfaces. Pinned for the same
                 # reason as the metric groups: an assertion that stops
                 # running reports nothing and the file still says passed.
                 "and the kind chooser rides in the bar, not under it",
                 "a game\u2019s angles can be narrowed by kind",
                 "and only the kinds it carries are offered",
                 "in the order the payload names them",
                 "picking a kind shows fewer rows than all of them",
                 "and a kind this game has none of still leaves the bar",
                 "a club chosen, the board offers league or that club",
                 "and the league reading comes back with the club still "
                 "picked",
                 "with no club chosen there is nothing to compare, so no "
                 "control",
                 "and the sweep reaches the angle controls",
                 # The mirror pair, named on the row and explained in the
                 # panel. Pinned so the block cannot stop running quietly.
                 "the board has a mirror pair to talk about",
                 "the two records really are each other reversed",
                 "a paired row is tagged as one side of two",
                 "and the tag names the row it pairs with",
                 "opening it shows both records side by side",
                 "with the arithmetic said plainly",
                 "but the club reading drops the arithmetic it cannot claim",
                 # The two visuals: the margin strip on the Score tab and
                 # the unfold grid in Notes. Pinned like the rest, so a block
                 # that stops running fails instead of reporting nothing.
                 "the bands are drawn as a shape, not only as a list",
                 "with a column per band",
                 "and the line drawn over them",
                 "the band the line cuts is marked as neither side",
                 "our own number is drawn where it differs",
                 "and the picture is explained in words",
                 "a home team getting points covers by losing narrowly",
                 "and at half a point it only has to avoid losing",
                 "a whole-number line says where the push is",
                 "and no strip at all when there is no line to place",
                 "the scenarios are drawn as a grid",
                 "one row per band that has cells",
                 "and no row for a band nothing reached",
                 "with row and column totals, which a list cannot have",
                 # A player's past lines: a fact, not a finding.
                 "the payload carries a player\u2019s past lines",
                 "opening a player shows what his line has done before",
                 "a bar for every week",
                 "with nothing colored to mean good",
                 "a yes-or-no market draws no center line",
                 "while a market with a line draws one",
                 "a week he recorded nothing is marked on the chart",
                 "the rest is offered behind a link",
                 "the filters share one bar",
                 "before kickoff nothing is graded",
                 "and the call color is gone, because it is no longer a call",
                 "the score the game finished on is marked green",
                 "a final nobody listed leaves no green row",
                 "and there is at least one red to have been counted",
                 "and the footer says the final is not on the list",
                 "a final nobody listed leaves the whole list red",
                 "and every score that did not happen is red",
                 "the props board calls it out rather than greying it",
                 "and below the filters, where switching market shows it "
                 "change",
                 "and above the rows it describes",
                 "switching market starts at the top of the new market",
                 "and switching Everyone / Shortlist / Fades does the same",
                 "but sorting keeps your place",
                 "a short filter lands on the bar like every other one",
                 "by padding the page by exactly what it was short",
                 "and cleared again once the page is long enough",
                 "no dead space is added when the page can already scroll",
                 "the games filter is in the shared pinned bar",
                 "the counts are above it rather than pinned with it",
                 "and the cards it filters below it",
                 "the pinned filter still filters",
                 # The green and red grade OUR pick, not the book's.
                 "the board grades our model by default",
                 "and a game our model called wrong is marked lost",
                 "the book can still be graded instead",
                 "and the two disagree, which is why the control exists",
                 "and so can the blend of the two",
                 "the graded number is marked on the card",
                 "and the mark follows the control",
                 "with exactly one number marked per card",
                 "the pills use the short label",
                 "and not the long one",
                 "every market carries a short label",
                 "the board bar is in the same pinned wrapper as the game "
                 "screen",
                 "stepping filters the board",
                 "no Ask across sixteen matchups",
                 "now Ask is offered",
                 "back returns to all games",
                 "the games board is wired to the same measurement",
                 "the three-season CLV explanation is not above the board",
                 "Starred says nothing beyond its own label",
                 "but Fades still warns they are not bets to place",
                 "and does it in one line, not four",
                 "the markets divide the width evenly instead of "
                 "overflowing",
                 "and are not a grid that wraps to two rows",
                 "every short label fits a sixth of a phone",
                 "the two receiving markets cannot be misread for each other",
                 "and search appears once, not above the bar as well",
                 "with the market explanation below the bar and above the rows",
                 "the game props section uses the same bar",
                 "and no preamble between the bars and the rows",
                 "the two bars are adjacent",
                 "but the market explanation survives the cut",
                 "and it comes after the game bar it pins under",
                 "and the chooser rides in the pinned bar, not under it",
                 "an old injuries link still finds it",
                 "and injuries is not one of them, having joined the matchup",
                 "the betting sections come first and are not split by "
                 "commentary",
                 "opening a game from the list lands on the price",
                 "the sections are labeled for their contents",
                 "and the names this app dropped still resolve",
                 "and the filters are inside the tab, under it",
                 "search narrows the board",
                 "the matchup tab renders",
                 "a past week of games renders",
                 "the ask box takes a typed question",
                 "the matchup offers the halves",
                 "tapping Players lands on a market that has players",
                 "a game with nothing quoted says so once",
                 "otherwise it names the markets that do hold players",
                 # The angles board: sortable, filterable, and openable.
                 "nor the angles board",
                 "the angles board lists every angle tracked",
                 "and says how many patterns were measured",
                 "and that some of them look good on luck alone",
                 "and what clearing means",
                 "and says it without jargon",
                 "and explains why half is not enough",
                 "opening one shows its games",
                 "with a plain-language description above them",
                 "and only one is open",
                 "tapping it again closes it",
                 "the board can be sorted",
                 "every angle carries a category",
                 "and the board offers them as a filter",
                 "filtering to one kind shows fewer rows",
                 "and only that kind",
                 "and clears back to all",
                 "the columns are the sort control",
                 "and tapping the same column flips it",
                 "percentages carry two decimals",
                 "there is a control for how far back to count",
                 "moving it recounts the long run",
                 "a whole-game condition is tagged on the board",
                 "and exactly the flagged ones are",
                 "and the row is kept rather than hidden",
                 "a clearing interval on a thin sample is not green",
                 "the same interval with the games behind it is",
                 "and a big sample that does not clear is not",
                 "the card counts the rows it colors",
                 "and the card says the rule has two halves",
                 "seven-and-one on eight games is not unusual",
                 "the same rate over eighty games is",
                 "and a season that matches the long run is not",
                 "and it reads cold seasons too",
                 "and a long run of all wins says nothing rather than dividing by zero",
                 "the board marks exactly the unusual ones",
                 "and the mark is a tag, not a tint on the number",
                 "and the card says what it means",
                 "the board explains what the composition costs",
                 "the board is back to three columns",
                 "and it is read off the cells the split actually sits in",
                 "mixing two cells averages them by how many games are in each",
                 "and the start year applies to the baseline too",
                 "and a team is measured against its own mix, not the league\u2019s",
                 "an angle with no baseline shows none",
                 "and the expected rate is in the panel that opens",
                 "the board offers a team picker",
                 "picking one narrows the numbers to that team",
                 "and the record shown is that team\u2019s",
                 "not the league\u2019s",
                 "the both-sides tag is gone once a team is chosen",
                 "and the fixtures under it are that team\u2019s",
                 "and clearing it restores the league board",
                 "the card can switch to the team\u2019s own record",
                 "to that team\u2019s record",
                 "and the both-sides tag comes off with it",
                 "the long-run column carries its record",
                 "and the games column is gone",
                 "and each game links to its own page",
                 "the team the pattern is about is marked",
                 "and an unplayed game names its side",
                 "and a played one still says how it went",
                 "and a push is marked as one",
                 "and is not counted as still to play",
                 "and the season line separates the three",
                 "every linked fixture names a game the board holds",
                 "and a fixture with no board is not a link",
                 "a closed week opens the archive",
                 "and a game in the current week opens the live board",
                 "tapping one opens that game",
                 "on the week it was played",
                 "and that game is actually on the board it was sent to",
                 "and Back returns to the angles board",
                 "with the angle still open",
                 "the board can be searched",
                 "the search box keeps focus while you type",
                 "and the caret with it",
                 "but a redraw with nothing focused focuses nothing",
                 "typing narrows the board",
                 "and clearing it restores the board",
                 "sorted by the long run rather than by this season",
                 "losing angles are on the board too",
                 # The pinned bar carries the switcher and Ask, and a thin
                 # window states itself instead of withholding the tables.
                 "the game switcher is inside the pinned bar",
                 "stepping keeps the section you were reading",
                 "and lands in the same place as the arrows",
                 "a thin game says so",
                 "and still draws the margin bands",
                 "and does not refuse",
                 "a full sample shows no banner",
                 # The angles on one game: its own, sortable, filterable.
                 "the game card lists its angles",
                 "one row per angle this game carries",
                 "and no other game\u2019s angles leak in",
                 "the card carries the year slider",
                 "and moving it moves the long-run column",
                 "on the team reading as well as the league one",
                 "dragging updates the year as it moves",
                 "and writes it into the label",
                 "without redrawing the board under the finger",
                 "and letting go redraws it",
                 "the angle filters are in a pinned bar",
                 "inside a section that also holds the table",
                 "and no search box, which the team control already does",
                 "with both segments and the year slider in it",
                 "the columns sort it",
                 "sorting the card reorders it",
                 "and tapping the same column flips it",
                 "without touching the board\u2019s own sort",
                 "the card can be narrowed to one side",
                 "and narrowing leaves only that side",
                 "tapping a row opens its games",
                 "and only one at a time"):
        assert path in r.stdout, f"{path!r} never ran:\n{r.stdout}"


def test_v3_keeps_every_calculation_and_rewrites_none():
    """The numbers are v1's. What v3 owns is the shell and the wording.

    Falsified by reimplementing any of them here: the bundle would then carry
    two answers to the same question, which is how the touchdown shortlist
    once disagreed with its own board about the same player.
    """
    from src.export import v3js

    src = v3js.js()
    for fn in ("function rowsFor", "function betProb", "function ev100",
               "function slipMath", "function settle", "function served",
               "function fixtureOf", "const amToDec"):
        assert fn not in src, f"{fn} is v1's and must not be rewritten here"
    assert src.count("function render(") == 1, (
        "v3 takes over v1's render and must declare it exactly once")


def test_the_week_picker_is_global_rather_than_per_market():
    """In v2 the picker belonged to a market and reset on every switch.

    Asked for directly: "I'd love that if a specific game was selected, that
    selection continued across markets". The same is true of the week, and it
    is the reason the picker lives in the header.
    """
    from src.export import v3js

    src = v3js.js()
    # Drawn by the header, which every screen renders.
    assert "data-v3week" in src
    i = src.index("function v3Header")
    assert "data-v3week" in src[i:i + 2600], (
        "the picker has to be in the header or it is per-screen again")
    # And the weeks it offers must follow the SCREEN, because the two
    # archives differ: the props board needs play-by-play, the games board
    # needs archived lines, and a week can have one without the other.
    assert "function v3Weeks" in src
    w = src[src.index("function v3Weeks"):]
    w = w[:w.index("\n}") + 2]
    assert "V.tab === 'games'" in w and "past" in w
    # And switching market must not clear it. The market case is annotated;
    # what matters is that neither it nor the game filter touches V.week.
    case = src[src.index("case 'v3mkt':"):src.index("case 'v3sort':")]
    assert "V.week" not in case and "V.game" not in case, (
        "switching market must not reset the week or the game filter")


def test_a_past_week_is_graded_rather_than_merely_shown():
    """Asked for: "a color coded way to see winners and losers".

    A past week that renders the same as this week is a week you cannot read.
    """
    from src.export import v3css, v3js

    js, css = v3js.js(), v3css.css()
    for cls in ("row--won", "row--lost", "mark--won", "mark--lost"):
        assert cls in js, f"{cls} is never applied"
        assert "." + cls in css, f"{cls} has no rule, so it colors nothing"
    # Three-valued, not two. A pick that never settled is not a pick that lost.
    assert "mark--void" in js and ".mark--void" in css


def test_history_is_looked_up_under_the_key_the_files_are_named_by():
    """`any` and `first` on the board; `anytime_td` and `first_td` on disk.

    Looking one up under the other returns undefined, and "no history" renders
    identically to "no weeks played yet" — a normal state, so nothing
    complains. This is the map that stops the picker shipping dead.
    """
    import re

    from src.export import v3js

    m = re.search(r"const V3HIST = \{(.*?)\};", v3js.js(), re.S)
    assert m, "V3HIST is gone; the picker will look up the wrong key"
    mapped = dict(re.findall(r"(\w+):\s*'([\w]+)'", m.group(1)))
    assert mapped.get("any") == "anytime_td"
    assert mapped.get("first") == "first_td"
    assert mapped.get("recyds") == "receiving_yards"


def test_fades_are_offered_beside_the_other_filters():
    """The project's best-measured player result is a list to leave alone.

    v2 buried it behind a market-specific control. It is a filter here, and
    the wording has to say it is not a bet, because "Fades" beside "Shortlist"
    otherwise reads as a second list of things to back.
    """
    from src.export import v3js

    src = v3js.js()
    assert "'fade', 'Fades'" in src
    assert "LEAVE ALONE" in src or "leave alone" in src.lower()


def test_the_slip_prices_two_picks_in_one_game_together():
    """It used to STATE the assumption; it corrects it now.

    The error runs one way — a same-game parlay is worth more than the product
    for team-mates and less across sides — and the slip printed the product
    with a sentence underneath admitting it. The sentence is a number now:
    legs sharing a game are taken across the margin bands rather than through
    them, at a strength fitted on 341,044 measured pairs.

    Falsified by dropping the correction back to a caveat: `v3CorrNote` would
    stop calling `v3Correlation`, or the fitted exponent would stop being
    read from the payload.
    """
    from src.export import v3js

    src = v3js.js()
    assert "function v3Correlation" in src, "no same-game correction at all"
    assert "v3CorrNote(legs)" in src, "the slip does not call it"
    # The strength is fitted, not written in the page.
    i = src.index("function v3JointOne")
    body = src[i:i + 2500]
    assert "correlation || {}).k" in body, (
        "the exponent must come from the fitted payload, not from a literal")
    # And the flip is what makes opposite sides anti-correlate.
    assert "V3FLIP" in body, "a leg on the away bench must read the game flipped"


def test_the_ask_box_never_sends_its_own_context():
    """An endpoint that forwards whatever it is given is a free
    general-purpose model billed to whoever owns the key.

    The browser sends a GAME ID and a QUESTION. The brief that answers it
    lives on the server and is chosen by that id, so the endpoint can only
    ever answer questions about this week's games however the box is abused.
    """
    import re

    from src.export import v3js

    src = v3js.js()
    i = src.index("function v3AskSend")
    body = src[i:i + 1600]
    m = re.search(r"JSON\.stringify\(\{([^}]*)\}\)", body)
    assert m, "the request body is not a literal; check what it sends"
    sent = {k.strip() for k in re.findall(r"(\w+)\s*:", m.group(1))}
    assert sent == {"game", "q"}, f"it also sends {sorted(sent - {'game', 'q'})}"


def test_the_proxy_holds_the_key_and_the_page_never_does():
    from pathlib import Path

    php = (Path(__file__).resolve().parents[1] / "deploy/ask.php").read_text()
    js = (Path(__file__).resolve().parents[1] / "src/export/v3js.py").read_text()
    # The key is read from outside the web root and never echoed.
    assert "/etc/picksix/anthropic.key" in php
    assert "echo $key" not in php and "echo json_encode($key" not in php
    # And nothing resembling a key is in the page.
    for bad in ("sk-ant", "x-api-key", "anthropic.com"):
        assert bad not in js, f"{bad} must not appear in the page"


def test_the_proxy_validates_the_game_id_by_shape_before_building_a_path():
    """Validated by shape, so a traversal cannot even be attempted."""
    from pathlib import Path

    php = (Path(__file__).resolve().parents[1] / "deploy/ask.php").read_text()
    assert "preg_match('/^[A-Z]{2,4}_[A-Z]{2,4}$/'" in php
    assert php.index("preg_match('/^[A-Z]") < php.index("$ctx_file ="), (
        "the id must be checked before it is used to build a path")


def test_the_proxy_is_rate_limited_per_address_and_in_total():
    """A per-IP limit alone is a limit per proxy. The daily cap is the one
    that protects the bill."""
    from pathlib import Path

    php = (Path(__file__).resolve().parents[1] / "deploy/ask.php").read_text()
    assert "$PER_IP_HR" in php and "$PER_DAY" in php
    assert "bump($STATE_DIR, 'all.json'" in php
    assert "bump($STATE_DIR, 'ip-'" in php
    # And the limiter runs before the key is even read.
    assert php.index("bump($STATE_DIR, 'all.json'") < php.index("$KEY_FILE)")


def test_the_upstream_error_body_is_not_returned_to_the_browser():
    """It can echo request details, and this endpoint is public."""
    from pathlib import Path

    php = (Path(__file__).resolve().parents[1] / "deploy/ask.php").read_text()
    assert "fail(502, 'the model returned ' . $code)" in php
    assert "fail(502, $resp" not in php


def test_the_build_recipe_names_every_file_that_has_to_travel():
    """Uploading three of the four is an app that loads and lies about a week."""
    mk = (REPO / "scripts" / "52_export_v3.py").read_text()
    for needed in ("index.html", "manifest.webmanifest", "sw.js", "data/"):
        assert needed in mk, f"the recipe has to name {needed}"


def test_v3_does_not_share_a_service_worker_cache_with_v2():
    """Two apps under one origin share a worker registry.

    An identical cache stamp lets v2's cached shell answer a v3 request, which
    shows as v3 rendering v2's page after an upload — intermittently, and only
    for people who had visited v2 before.
    """
    from src.export.v3 import render

    out = render({"season": 2026, "week": 2, "brand": "Pick Six",
                  "built": "2026-09-18T01:19:25+00:00", "markets": [],
                  "results": {}})
    assert "v3-" in out["sw.js"]


def test_no_focusable_control_is_small_enough_to_zoom_ios():
    """iOS SAFARI ZOOMS THE PAGE AND DOES NOT ZOOM BACK OUT.

    Focus a form control whose computed font-size is under 16px and mobile
    Safari magnifies the whole document, leaving it that way until the reader
    pinches back. The board is read on a phone, so every control you can
    focus — the search box, the ask box, the week picker, the game switcher,
    the ladder fields — has to clear the floor.

    Falsified by lowering any of them, including by deleting the base rule
    and letting a control inherit the 15px body size.
    """
    import importlib as _il
    import re

    css = _il.import_module("src.export.v3css").css()
    # The base rule has to exist, or every control inherits `body`.
    assert re.search(r"input\s*,\s*select\s*,\s*textarea\s*\{[^}]*"
                     r"font-size:\s*16px", css), (
        "the 16px floor on input/select/textarea is gone; controls now "
        "inherit the body size")
    bad = []
    for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        sel = sel.strip()
        if "::" in sel or not re.search(r"\b(input|select|textarea)\b", sel):
            continue
        m = re.search(r"font-size:\s*(\d+(?:\.\d+)?)px", body)
        if m and float(m.group(1)) < 16:
            bad.append((sel.splitlines()[-1].strip(), m.group(1) + "px"))
    assert not bad, f"controls below the 16px floor: {bad}"


def test_the_app_bar_is_not_shorter_than_the_header_inside_it():
    """TWO BOXES CANNOT BOTH OWN THE HEADER'S HEIGHT.

    `.appbar` was a fixed 52px and `v3Header` rendered `.hd` inside it asking
    for 52px plus a 12px margin plus the safe-area inset. The overflow was
    centered, so it bled downward and the brand row sat almost on top of the
    game switcher beneath it on a phone.

    Falsified by giving either one a fixed height again.
    """
    import importlib as _il
    import re

    css = _il.import_module("src.export.v3css").css()

    def rule(sel):
        m = re.search(re.escape(sel) + r"\s*\{([^}]*)\}", css)
        assert m, f"{sel} is gone"
        return m.group(1)

    bar, hd = rule(".appbar"), rule(".hd")
    assert not re.search(r"(^|;)\s*height:", bar), (
        ".appbar sets a fixed height again; it must size to its content")
    assert not re.search(r"(^|;)\s*height:", hd), (
        ".hd sets a height inside a bar that already sizes to it")
    assert "margin-top" not in hd, (
        ".hd adds a margin inside the bar that already pads itself")
    # The inset belongs to whichever box actually touches the top of the
    # screen, and that is the bar.
    assert "safe-area-inset-top" in bar, (
        ".appbar must carry the notch inset; nothing above it does")


def test_the_moneyline_move_is_read_as_a_price_not_a_point():
    """A MONEYLINE HAS NO NUMBER TO MOVE, ONLY A PRICE.

    `lines[gid].h2h` carries `open_odds` and `now_odds`, but `open`, `now`
    and `move` are null because a moneyline has no point — so a block that
    reads those skips the market entirely, which is how it was left out once
    already.

    Falsified by reading the raw odds instead of the chance they imply, or by
    dropping the market again.
    """
    from src.export import v3js

    src = v3js.js()
    i = src.index("function v3PublicMoney")
    body = src[i:src.index("\nfunction ", i + 1)]
    assert "L.h2h" in body, "the moneyline move is not read"
    assert "amToDec" in body, (
        "the move must be read as implied chance; -142 to -130 and +120 to "
        "+110 are different sizes in the same direction")
    # ALL THREE MARKETS CARRY BOTH SHARES. The moneyline had bets and money
    # side by side and the other two had bets only, from a different feed.
    for mkt in ("sp.moneyline", "sp.spread", "sp.total"):
        assert mkt in body, f"{mkt} is not drawn"
    assert body.count("v3MoneyBlock(") == 3, (
        "the three markets are not drawn by one block renderer")
    block = src[src.index("function v3MoneyBlock"):]
    block = block[:block.index("\nfunction ")]
    assert "bar('Bets'" in block and "bar('Money'" in block, (
        "a market is drawn without one of its two bars")

def test_a_played_week_marks_which_lines_cleared():
    """ONCE THE GAME IS IN, EVERY LADDER ROW HAS AN ANSWER.

    Each row asks whether the game went over a number. On a historical week
    that is no longer a chance, so the rows the result settled are tinted:
    green where the number was cleared, red where it was not. A live week
    passes no final and nothing is colored — a table of green rows on a game
    nobody has played would read a forecast as a result.
    """
    from src.export import v3css, v3js

    src = v3js.js()
    i = src.index("function v3GameBets")
    # To the NEXT top-level function, not a fixed 4,000 characters. The window
    # was a magic number and the function outgrew it: adding the our-number
    # rung pushed `final_home` past the cut and the test failed on code it was
    # not looking at.
    j = src.index("\nfunction ", i + 1)
    body = src[i:j]
    assert "final_home" in body and "final_away" in body, (
        "the ladder never reads the final score")
    assert "ltab__r--hit" in body and "ltab__r--miss" in body
    assert "actual == null ? null" in body, (
        "a live week must pass no result rather than a default")
    css = v3css.css()
    assert ".ltab__r--hit{" in css and ".ltab__r--miss{" in css


def test_the_margin_band_is_matched_on_margins_not_on_a_confidence_interval():
    """`lo` AND `hi` ON A BAND ARE THE WILSON INTERVAL ON ITS PERCENTAGE.

    They are not margin bounds, and reading them as such marks whichever band
    happens to have an interval straddling the final score — the first cut of
    this did exactly that. `mlo`/`mhi` are the inclusive margin bounds,
    home-positive, and `score_dist` emits them so the page never has to parse
    "SEA by 8-14" back out of a label built for reading.
    """
    import importlib

    sd = importlib.import_module("src.models.score_dist")
    import inspect

    py = inspect.getsource(sd.summary)
    assert '"mlo"' in py and '"mhi"' in py, "the bounds are not emitted"

    from src.export import v3js

    src = v3js.js()
    i = src.index("function v3GameScores")
    body = src[i:i + 3000]
    assert "m.mlo" in body and "m.mhi" in body, (
        "the page is matching on something other than the margin bounds")


def test_the_band_bounds_actually_bracket_their_own_label():
    """Falsified by a bound that disagrees with the words beside it."""
    import importlib

    sd = importlib.import_module("src.models.score_dist")
    hist = sd.history()
    if hist.is_empty():
        pytest.skip("no score history on disk")
    d = sd.summary(-3.0, 44.5, "PIT", "CIN", hist=hist)
    by = {m["band"]: m for m in d["margins"]}
    assert by["PIT by 8-14"]["mlo"] == 8 and by["PIT by 8-14"]["mhi"] == 14
    assert by["CIN by 8-14"]["mlo"] == -14 and by["CIN by 8-14"]["mhi"] == -8
    assert by["Tie"]["mlo"] == 0 and by["Tie"]["mhi"] == 0
    # The open ends are open, not clamped to a number that would exclude a
    # blowout from the band named for blowouts.
    assert by["PIT by 15+"]["mhi"] is None
    assert by["CIN by 15+"]["mlo"] is None
    # And every band is reachable: the bounds must partition the line.
    for m in d["margins"]:
        assert m["mlo"] is None or m["mhi"] is None or m["mlo"] <= m["mhi"], m


def test_the_slip_opens_on_round_robin_and_calls_it_that():
    """"Any two" DESCRIBES THE MECHANIC AND HIDES THE NAME.

    It is a round robin, which is what a reader will have heard it called,
    and it sat second behind all-or-nothing — the hardest bet on the list to
    win, and a poor thing to open on for someone who does not bet much.
    """
    from src.export import v3js

    src = v3js.js()
    i = src.index("const V3BETTYPES")
    block = src[i:i + 900]
    assert "'Round robin'" in block, "the round robin is not named"
    assert "'Any two'" not in block
    # First in the list, so it is what the chooser shows first.
    assert block.index("'twos'") < block.index("'parlay'"), (
        "all-or-nothing still leads the list")
    # And the state opens on it.
    j = src.index("betType:")
    assert "betType: 'twos'" in src[j - 40:j + 40], src[j - 40:j + 40]


def test_the_slip_has_a_save_button_that_names_where_it_goes():
    """The tab is Picks, so the verb is save and the destination is named.

    A button called "Keep" beside a tab called "Picks" leaves the reader to
    infer they are the same thing.
    """
    from src.export import v3js

    src = v3js.js()
    i = src.index("function v3SlipBody")
    body = src[i:i + 4000]
    assert "data-v3keep=" in body, "the slip has no save control"
    assert "Save to Picks" in body
    assert "Saved to Picks" in body, "a saved slip must say so"


def test_only_the_game_section_bar_is_pinned():
    """It sticks to the top of the scrolling pane, and nothing else does.

    `#scroll` is the scroll container and the app header sits outside it, so
    `top:0` is the top of the readable area and needs no header offset. Making
    `.seg` itself sticky would have pinned the market pills and the halves
    too, which belong in the flow.
    """
    from src.export import v3css

    css = v3css.css()
    assert ".gtabs{position:sticky" in css, "the section bar is not pinned"
    assert ".seg{position:sticky" not in css, "every segmented control is pinned"
    i = css.index(".gtabs{")
    rule = css[i:css.index("}", i)]
    # Without a background the rounded control lets content slide behind it.
    assert "background" in rule, "the pinned bar is transparent"
    # `.wrap` pads 16px a side; the bar cancels that so its background reaches
    # the edge of the column rather than stopping short of it.
    assert "-16px" in rule and "16px" in rule, rule
    assert "z-index" in rule, "the pinned bar can be drawn under the content"


def test_switching_game_section_scrolls_to_the_bar_not_the_page_top():
    """Three scroll cases, not two.

    Restoring the offset is right when you star a row. Zero is right when you
    open a game. Neither is right for switching section INSIDE a game: the
    offset leaves you deep in a section you have not read, and zero puts the
    matchup card back above the thing you tapped for. The pinned bar is where
    the pane comes to rest anyway.
    """
    from src.export import v3js

    src = v3js.js()
    i = src.index("function v3Do")
    # `v3Do` is the last top-level function in the bundle, so "the next one"
    # may not exist. `find` returning -1 would slice backwards and silently
    # check the wrong region.
    j = src.find("\nfunction ", i + 1)
    j = len(src) if j < 0 else j
    assert "V.top = 'section'" in src[i:j], (
        "switching section no longer asks to scroll")
    # And the render honors it by measuring the bar rather than assuming 0.
    #
    # Bounded by the BRANCH, not by a character count. A fixed window made the
    # test fail on a comment getting longer, which says nothing about the code.
    assert "V.top === 'section'" in src
    k = src.index("if (V.top === 'section')")
    branch = src[k:src.index("scroll.scrollTop = V.top ?", k)]
    assert ".gtabs" in branch, (
        "the section scroll does not look for the pinned bar")
    # Measured against the PANE: the app header sits outside the scroller.
    assert "scroll.getBoundingClientRect" in branch, (
        "the offset is measured against the window, which counts the header")
    # AND THE PANE IS RESTED AT ZERO FIRST. A sticky bar you have scrolled
    # past reports itself pinned at the pane's edge, so measuring it where you
    # stand gives back the offset you already had — the scroll did nothing in
    # the one case the pinned bar is for. `tests/js/v3app.js` proves the
    # behavior against a stub that models the pinning; this pins the cause,
    # because the two lines read as a redundant write and invite deletion.
    assert "scroll.scrollTop = 0;" in branch, (
        "the bar is measured while stuck, so the offset is whatever you had")
    assert branch.index("scroll.scrollTop = 0;") < branch.index(".gtabs"), (
        "the bar is measured before the pane is rested, so it reads as pinned")


def test_the_ask_prompt_answers_rather_than_declines():
    """Asked to read the spread, the moneyline and the total, the model spent
    its first paragraph announcing that it does not give betting advice and
    then answered anyway.

    Describing the site's own numbers is the product: every figure the
    question touches is printed on the card above the box. The rule that
    produced the refusal was a bare "no betting advice", which the model read
    as covering its own data.

    Falsified by putting the blanket rule back, or by dropping the guardrails
    that replaced it.
    """
    php = (REPO / "deploy" / "ask.php").read_text()
    i = php.index("$system =")
    # THE PROMPT, NOT THE COMMENTARY AROUND IT. The comment explaining why
    # the blanket rule went away quotes the blanket rule, and a naive slice
    # reads that quotation as the rule still being in force.
    body = "\n".join(ln for ln in php[i:php.index("$body =", i)].split("\n")
                     if not ln.lstrip().startswith("//"))

    # THE INSTRUCTION TO ANSWER, and the ban on leading with a disclaimer.
    assert "Never open with a disclaimer" in body, (
        "nothing stops the answer opening with what it will not do")
    assert "Do not refuse a question the data can answer" in body
    for market in ("spread", "moneyline", "total"):
        assert market in body, f"the prompt never names the {market}"

    # AND THE GUARDRAILS THAT REPLACED THE BLANKET RULE. Describing the model
    # is not recommending a bet, and the difference has to be written down.
    assert "what to bet" in body, "nothing rules out telling the reader to bet"
    for word in ("lock", "guarantee", "sure thing"):
        assert word in body, f"{word!r} is no longer ruled out"
    assert "small sample" in body and "wide interval" in body, (
        "the prompt no longer requires the caveat to travel with the number")
    # The blanket rule is what caused it; it must not come back.
    assert "no betting advice" not in body, (
        "the bare rule is back, and it is what produced the refusal")


def test_a_games_angle_filters_pin_under_the_section_bar():
    """Pinned to the tab they would ride over the cards below the table.

    A sticky element stays stuck for as long as its PARENT is on screen, so
    the bar and the table it filters share a wrapper: the bar lets go where
    the list ends. And it pins at `--gtabs-h`, which `render` writes from the
    measured height of the section bar, rather than at the top of the pane
    where it would sit on top of it.

    Falsified by unwrapping them, or by pinning the bar at zero.
    """
    from src.export import v3css, v3js

    src, css = v3js.js(), v3css.css()
    i = src.index("function v3Angles(c) {")
    body = src[i:src.index("\nfunction ", i + 1)]
    assert "'<div class=\"gasec\">'" in body, (
        "the filters and their table are no longer wrapped together")
    bar = body.index("class=\\\"pbar\\\"") if "class=\\\"pbar\\\"" in body \
        else body.index("'<div class=\"pbar\">'")
    sec = body.index("'<div class=\"gasec\">'")
    assert sec < bar, "the wrapper opens after the bar it is meant to scope"
    # The wrapper has to close AFTER the table, or it scopes nothing.
    rows = body.index("data-v3gangle=")
    close = body.index("'</div></div>';")
    assert bar < rows < close, (
        "the section does not close around the table it is meant to scope "
        f"(bar={bar}, rows={rows}, close={close})")
    # PINNED UNDER THE SECTION BAR. `.pbar` is the shared pinned-filter bar
    # and is offset by the height the game's own bar publishes.
    assert ".pbar{position:sticky;top:var(--gtabs-h,0px)" in css, (
        "the pinned bar no longer offsets itself by the section bar")
    assert ".gasec" in css, "the wrapper has no rule, so it scopes nothing"


def _v3js() -> str:
    from pathlib import Path
    return (Path(__file__).resolve().parents[1]
            / "src/export/v3js.py").read_text()


def test_a_last_ten_bar_cannot_be_taller_than_the_half_it_grows_into():
    """The bars grow from the midline, so their room is half the box.

    `.pl__b--up` is pinned to the top of a 72px box and pushed down by half
    its own height; `--dn` is the mirror. Scaling the biggest week to 100% of
    the box drew it at twice its room, so it overflowed and landed across the
    sentence underneath — the caption had a bar drawn through it.
    """
    src = _v3js()
    assert "Math.abs(v) / top * 50" in src, \
        "the last-10 bars are scaled to the whole box again"
    assert "Math.abs(v) / top * 100" not in src, "the old full-box scale is back"

    from pathlib import Path
    css = (Path(__file__).resolve().parents[1]
           / "src/export/v3css.py").read_text()
    i = css.index(".pl__c{")
    assert "overflow:hidden" in css[i:i + 200], \
        "the chart no longer clips, so an overflowing bar reaches the text"


def test_the_last_ten_chart_says_what_its_colors_mean():
    """A chart of bars around an unlabeled line explains itself to nobody.

    Hovering a bar carried the answer and is not available on a phone at all.
    """
    src = _v3js()
    assert "pl__lg" in src and "over his line that week" in src, \
        "the last-10 chart lost its legend"
    assert src.index("'<p class=\"pl__s\">'") < src.index("'<div class=\"pl__c\">'"), \
        "the count is printed under the chart again rather than above it"


def test_a_streak_is_counted_against_the_line_he_was_quoted_that_week():
    """Not against this week's line, which he never played against.

    A player's number moves week to week — three catches against 1.5 and three
    against 3.5 are not the same week — so counting past games against today's
    line reports a run the player never had. The row's tag and the chart above
    it have to be answering one question.
    """
    src = _v3js()
    i = src.index("function v3Streak(row)")
    body = src[i:i + 1800]
    assert "recent[i][4]" in body and "recent[i][6]" in body, \
        "the streak no longer reads the archived line and result per week"
    assert "did > line" in body, "the streak is not compared to that week's line"
    assert "row.line" not in body and "row.book" not in body, \
        "the streak reached for this week's line"


def test_a_short_or_ragged_record_is_silent_rather_than_flagged():
    """Five weeks with a line AND a result, or no tag at all.

    A flag built on three weeks would appear most often on exactly the players
    with the least behind them.
    """
    src = _v3js()
    i = src.index("function v3Streak(row)")
    body = src[i:i + 1800]
    assert "rows.length < V3STREAK_OF" in body, "a short record is now flagged"
    assert "known < V3STREAK_OF" in body, \
        "weeks with no line or no result are counted toward the streak"


def test_the_streak_tag_is_not_colored_like_a_recommendation():
    """Recent form is not an edge this project has measured.

    `player_history` makes the argument: a rate over five games carries an
    interval wide enough to cover almost anything. The tag is drawn beside the
    facts, not painted as one of the good/bad marks the board uses to grade.
    """
    src = _v3js()
    i = src.index("function v3StreakTag(row)")
    body = src[i:i + 700]
    assert "tag--good" not in body and "tag--bad" not in body \
        and "tag--warn" not in body, "the streak tag grades the player"


def test_the_streak_filter_is_reachable_and_has_an_empty_state():
    src = _v3js()
    assert "['streak', 'Streaks']" in src, "the Streaks segment is gone"
    assert "seg--5" in src, "the filter bar still claims four segments"
    assert "V.filter === 'streak'" in src, "the Streaks segment filters nothing"
    assert "Nobody on this market went one way in" in src, \
        "the Streaks filter has no empty state"


def test_a_streak_that_describes_the_whole_market_is_not_drawn():
    """A tag on 97% of the board is a label for the market, not the player.

    Measured on the week this was written: "did not score in 4 of his last 5"
    was true of 385 of the 398 players eligible on first TD and 325 of 398 on
    anytime TD — most players do not score most weeks. The other direction on
    those markets is 0 and 8 players, and that is the fact worth seeing.

    The cut is read off the board rather than written per market, so a season
    where unders stop being the norm on receptions starts showing them with no
    edit here.
    """
    src = _v3js()
    i = src.index("function v3Streak(row)")
    body = src[i:i + 2600]
    assert "v3StreakBase(mk)" in body, "the base-rate gate is gone"
    assert "> 0.5) return null" in body, \
        "a direction covering most of the board is drawn again"
    j = src.index("function v3StreakBase(mk)")
    base = src[j:j + 1400]
    assert "V3STREAKBASE[mk]" in base, "the base rate is recomputed per row"
    assert "{ over: 1, under: 1 }" in base, \
        "a market with nothing to measure now flags everything"


def test_the_player_detail_pairs_are_sized_by_fit_not_by_handset():
    """A width breakpoint has to be re-guessed every time a phone gets wider.

    The detail list was two equal columns with a `max-width:420px` override to
    collapse them. Every iPhone from the 14 Pro Max on is 428 to 440 CSS
    pixels, so the override missed and each value got about 60px — "PIT to
    win, 1.5x the average bet" came down the screen one character per line.
    """
    from pathlib import Path
    css = (Path(__file__).resolve().parents[1]
           / "src/export/v3css.py").read_text()
    i = css.index(".detail dl{")
    rule = css[i:i + 200]
    assert "auto-fit" in rule and "minmax(260px" in rule, \
        "the detail pairs are back on fixed columns"
    assert "max-width:420px){.detail dl" not in css, \
        "the handset breakpoint is back"


def test_a_detail_value_wraps_at_its_spaces_before_it_breaks_a_word():
    """`overflow-wrap:anywhere` cut "average" into "av/era/ge".

    It only earns its keep on an unbroken string longer than its box, and
    every value in this list is a phrase.
    """
    from pathlib import Path
    css = (Path(__file__).resolve().parents[1]
           / "src/export/v3css.py").read_text()
    i = css.index(".detail dd{")
    rule = css[i:i + 200]
    assert "overflow-wrap:break-word" in rule, "the detail values break anywhere again"


def test_the_game_money_note_is_last_and_spans_the_panel():
    """It is a clause, not a field, and it is about the game not the player.

    Sat between "Books quoting" and "Board rank" in half a row, it wrapped
    into a column of fragments — "1.5x the av/era/ge bet".
    """
    src = _v3js()
    i = src.index("function v3Detail(row)")
    body = src[i:src.index("</dl></div>", i)]
    assert body.index("add('Our read'") < body.index("Big money in this game"), \
        "the game-money note is back in the middle of the list"
    assert "), true);" in body.split("Big money in this game")[1][:400], \
        "the game-money note is no longer marked as a full-width fact"
    assert "x[2] ? ' class=\"detail__w\"' : ''" in src, \
        "the renderer ignores the full-width flag"

    from pathlib import Path
    css = (Path(__file__).resolve().parents[1]
           / "src/export/v3css.py").read_text()
    assert ".detail__w{grid-column:1/-1}" in css, \
        "the full-width fact no longer spans the panel"


def test_no_layout_rule_decides_a_phone_by_a_width_that_phones_outgrew():
    """420px stopped meaning "a phone" in 2022.

    Every iPhone from the 14 Pro Max on is 428 to 440 CSS pixels, so a
    `max-width:420px` rule fires on none of them. Both rules that used it —
    the player detail pairs and the game comparison — asked about the handset
    when the question was whether a column had room, and both now ask that
    instead.
    """
    import re
    from pathlib import Path
    css = (Path(__file__).resolve().parents[1]
           / "src/export/v3css.py").read_text()
    # Comments quote the rule they replaced, which is the point of them.
    rules = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert "max-width:420px" not in rules, \
        "a 420px breakpoint is back; use auto-fit with a content minimum"
    i = rules.index(".three{")
    assert "auto-fit" in rules[i:i + 200], \
        "the comparison block is back on three fixed columns"


def test_every_data_file_the_build_writes_is_one_the_deploy_uploads():
    """The build and the deploy disagreed about a filename for months.

    `52_export_v3.py` writes `data/hist-<market>.json`; `58_deploy.py`
    collected `data/h-*.json`, which is a literal `h`, a literal `-`, then
    anything. `hist-` has an `i` in that second position, so six files
    totalling 1.6 MB were built on every deploy and uploaded on none. Nothing
    failed anywhere: the page fetched one, got a 404, fell back to the ten
    weeks it already had, and redrew the button that had asked for more.

    So the globs are a named contract, and this reads it against the paths the
    exporter actually writes. A new data file now fails here rather than going
    missing in production.
    """
    import fnmatch
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    dep = (root / "scripts/58_deploy.py").read_text()
    m = re.search(r"DATA_GLOBS = \(([^)]*)\)", dep)
    assert m, "58_deploy.py no longer declares DATA_GLOBS"
    globs = re.findall(r'"([^"]+)"', m.group(1))
    assert globs, "DATA_GLOBS is empty"

    written = set()
    for rel in ("scripts/52_export_v3.py", "src/export/pwa.py"):
        for hit in re.finditer(r'"data/([A-Za-z0-9_\-{}/.]+\.json)"',
                               (root / rel).read_text()):
            written.add(hit.group(1))
    assert written, "found no data file paths in the exporter"

    for name in sorted(written):
        # `{market}` and friends stand for whatever the week holds.
        sample = re.sub(r"\{[^}]*\}", "X", name)
        assert any(fnmatch.fnmatch(sample, g) for g in globs), \
            f"the build writes data/{name} and no DATA_GLOBS entry carries it"


def test_the_history_files_are_actually_uploaded_not_just_declared():
    """A contract nothing reads would pass the test above and ship nothing."""
    from pathlib import Path

    dep = (Path(__file__).resolve().parents[1]
           / "scripts/58_deploy.py").read_text()
    assert 'data.glob("hist-*.json")' in dep, \
        "the deploy no longer collects the history files"
    assert "for f in hist_files:" in dep, \
        "the history files are collected and never copied"


def test_the_upload_globs_what_this_tuple_names():
    """`DATA_GLOBS` must be what the upload actually collects, not a label.

    The test above is the right idea written for one file. `tlines.json` was
    added to `DATA_GLOBS`, the declaration test passed, and the uploader —
    which hardcodes its own glob per group and never reads the tuple — shipped
    nothing. The build wrote the file, the test was green, and the live page
    404'd on it on 2026-10-03: the same silent shape as the bug the constant
    was introduced to prevent, one level further out.

    The groups stay separate on purpose — week files are pruned, ask briefs go
    to a subdirectory — so this holds the two in step rather than merging them.
    """
    import re
    from pathlib import Path

    dep = (Path(__file__).resolve().parents[1]
           / "scripts/58_deploy.py").read_text()
    globs = re.search(r"DATA_GLOBS = \(([^)]*)\)", dep).group(1)
    names = re.findall(r'"([^"]+)"', globs)
    assert names, "DATA_GLOBS is empty"
    # What the upload actually reaches for, wherever it looks.
    collected = set(re.findall(r'\.glob\("([^"]+)"\)', dep))
    for name in names:
        # `ask/*.json` is globbed as `*.json` inside `data / "ask"`.
        bare = name.rsplit("/", 1)[-1]
        assert name in collected or bare in collected, \
            (f"DATA_GLOBS names {name} and the upload never globs it — "
             f"it will be built, pass every test, and 404 in production")
    assert "tline_files" in dep and "for f in tline_files:" in dep, \
        "the team line record is collected and never copied"


def test_a_history_fetch_that_failed_says_so():
    """Falling back to ten weeks is right; doing it silently is not.

    The panel redrew identically on a 404 and the button read as broken.
    """
    src = _v3js()
    assert "pl__e" in src, "the past-lines failure line is gone"
    assert "Every week did not load" in src, \
        "a failed history fetch is silent again"
    i = src.index("const err = (V.pastAll === row.player")
    assert "ck.error" in src[i:i + 300], \
        "the failure line is not reading the cached error"


def _v3css() -> str:
    from pathlib import Path
    return (Path(__file__).resolve().parents[1]
            / "src/export/v3css.py").read_text()


def test_the_desktop_width_is_spent_rather_than_stretched():
    """560px on a 1700px screen is a phone column with a field beside it.

    Widening that alone is the stretch: a board row 900px wide puts a player's
    name and his price at opposite ends of the screen. So the width goes to
    things with more to show, and prose keeps a line length.
    """
    css = _v3css()
    assert "@media (min-width:900px)" in css, "there is no desktop layout"
    i = css.index("@media (min-width:900px)")
    block = css[i:i + 1800]
    assert ".wrap{max-width:880px}" in block, "the shell never widens"
    assert "68ch" in block, "prose runs the full width of the window"
    assert "max-width:880px" in block, "the shell never widens"


def test_a_player_opens_under_himself_at_every_width():
    """One column, and the panel opens where it did on the phone.

    Two rows abreast with a docked drawer worked and read as two different
    apps: the phone expanded the row you tapped and the desktop answered
    somewhere else on the screen. What a reader learns on one has to be what
    happens on the other.
    """
    css = _v3css()
    i = css.index("@media (min-width:900px)")
    block = css[i:i + 2600]
    assert "#v3rows{display:grid" not in block, \
        "the board is two columns again"
    assert "position:fixed" not in block, "the drawer is back"

    src = _v3js()
    assert "detail__h" not in src and "detail__x" not in src, \
        "the panel carries a drawer's title and close button with no drawer"


def test_no_list_on_the_site_is_made_two_columns():
    """`.list` is five lists — the board, the games list, the angles table
    and a ladder — and none of them is a grid of equal cards."""
    css = _v3css()
    i = css.index("@media (min-width:900px)")
    block = css[i:i + 2600]
    assert ".list{display:grid" not in block, \
        "every list on the site was made two columns"


def test_the_shell_bars_stop_at_the_content_width():
    """A header with its two ends 1700px apart reads as two headers."""
    css = _v3css()
    i = css.index("@media (min-width:900px)")
    block = css[i:i + 1800]
    assert ".appbar,.tabbar{max-width:912px" in block, \
        "the top and bottom bars still run the full width of the glass"


def test_the_form_table_aligns_its_four_numbers():
    """"30-27 · expected 19.5-23" is four numbers in two en-dashed pairs
    whose dashes mean different things, right-aligned as one string."""
    src = _v3js()
    assert "tf__hd" in src and "tf__row" in src, "the form list is a string again"
    assert '"tf__n">scored</span>' in src \
        and '"tf__n">allowed</span>' in src, \
        "the form table lost its column headers"
    css = _v3css()
    i = css.index(".tf__hd,.tf__row{")
    assert "tabular-nums" in css[i:i + 600], \
        "the form numbers no longer line up down the page"


def test_a_control_is_clickable_across_its_whole_pill():
    """A select sized to its text inside a pill that stretches.

    `.pbar .picker select` sizes to content so several controls share a pinned
    row. Alone in a row on a desktop that is a 950px pill with a 96px select
    at the left: "All kinds" opened on the words and did nothing on the nine
    tenths of the pill that look exactly as clickable.
    """
    css = _v3css()
    i = css.index(".pbar__row--two .picker select{")
    rule = css[i:i + 120]
    assert "flex:1" in rule, "the lone picker's select sizes to its text again"
    assert "max-width:none" in rule, "and it is capped at 96px"


def test_every_projection_row_sits_on_the_same_columns():
    """Each row is its own grid, so `auto` sized the label column per row.

    "SPORTSBOOKS", "OUR MODEL / from 2943 past games" and "ADJUSTED" are three
    different widths, so the percentages started at three different places and
    the thing meant to be compared down a column could not be.
    """
    css = _v3css()
    i = css.index(".proj__r{")
    rule = css[i:i + 240]
    assert "var(--proj-l)" in rule, "the label column sizes to its own row again"
    assert "minmax(0,auto) 52px" not in rule, "the old auto track is back"
    assert "--proj-l:" in css, "the label width is not declared anywhere"
