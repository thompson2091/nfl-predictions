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
                         "splits": {"full": [{"key": "epa_play",
                             "label": "EPA per play", "note": "n",
                             "higher_is_better": True, "proxy": False,
                             "sides": [{"offense": "ATL", "defense": "GB",
                                        "off_val": 0.1, "def_val": 0.0,
                                        "diff": 0.1, "edge": 0.1}]},
                             {"key": "early_down_success",
                              "label": "Early-down success", "note": "n2",
                              "higher_is_better": True, "proxy": False,
                              "sides": [{"offense": "GB", "defense": "ATL",
                                         "off_val": 0.44, "def_val": 0.40,
                                         "diff": 0.04, "edge": 0.04}]}],
                           "h1": [{"key": "epa_play", "label": "EPA per play",
                             "note": "n", "higher_is_better": True,
                             "proxy": False,
                             "sides": [{"offense": "ATL", "defense": "GB",
                                        "off_val": 0.3, "def_val": 0.0,
                                        "diff": 0.3, "edge": 0.3}]}]},
                         "missing": [{"what": "Four-man rush vs blitz",
                                      "why": "field empty for 2026"}],
                         "rows": [{"key": "early_down_success",
                                   "label": "Early-down success",
                                   "note": "Share of 1st and 2nd down plays.",
                                   "higher_is_better": True, "proxy": False,
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
                        "margins": [{"band": "GB by 15+", "n": 106,
                                     "pct": 26.3, "lo": 22.2, "hi": 30.8}]},
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
        "past": {"2": {"cards": [
            {"game_id": "DET_BUF", "home": "BUF", "away": "DET",
             "total": 54.5, "spread": -5.5, "win_home": 0.681,
             "win_away": 0.319, "final_home": 41, "final_away": 31,
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
                 "a coaching note is labeled as context",
                 "the final-score tab renders",
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
                 "the sharp block reads all three markets, not just the moneyline",
                 "and ranks them by ratio, biggest bet first",
                 "a side backed by ordinary-sized bets is left out",
                 "a heavily backed side with the money behind it still surfaces",
                 "the card refuses to call itself a tip",
                 "the sharp block is on the game screen",
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
                 "the metrics can be filtered to one",
                 "All metrics leads the list",
                 "and the rest are alphabetical",
                 "while the sections keep the order the pipeline sent",
                 "and the chooser rides in the pinned bar, not under it",
                 "it is one control, not a pill per metric",
                 "and is absent on the injury view",
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
                 "picking one shows fewer headings than all of them",
                 "an old injuries link still finds it",
                 "and injuries is not one of them, having joined the matchup",
                 "the betting sections come first and are not split by "
                 "commentary",
                 "opening a game from the list lands on the price",
                 "the sections are labeled for their contents",
                 "and the keys behind them are unchanged",
                 "and the filters are inside the tab, under it",
                 "search narrows the board",
                 "the matchup tab renders",
                 "a past week of games renders",
                 "the ask box takes a typed question",
                 "the matchup offers the halves",
                 "tapping Players lands on a market that has players",
                 "a game with nothing quoted says so once",
                 "otherwise it names the markets that do hold players",
                 # The pinned bar carries the switcher and Ask, and a thin
                 # window states itself instead of withholding the tables.
                 "the game switcher is inside the pinned bar",
                 "stepping keeps the section you were reading",
                 "and lands in the same place as the arrows",
                 "a thin game says so",
                 "and still draws the margin bands",
                 "and does not refuse",
                 "a full sample shows no banner"):
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


def test_the_moneyline_move_is_shown_even_though_its_split_is_not():
    """THE PRICE IS THERE; THE TICKET SPLIT IS NOT, AND THEY ARE DIFFERENT.

    `lines[gid].h2h` carries `open_odds` and `now_odds`, but `open`, `now`
    and `move` are null because a moneyline has no point — so the block that
    reads those skipped the market entirely. Sportsbook Review returns 0% on
    every moneyline on every game, which is the feed declining to publish
    rather than a market nobody bet, so no bar is drawn and the page says why.

    Falsified by drawing a 0% moneyline bar, or by dropping the move again.
    """
    from src.export import v3js

    src = v3js.js()
    i = src.index("function v3Moved")
    body = src[i:i + 3000]
    assert "L.h2h" in body, "the moneyline move is not read"
    assert "amToDec" in body, (
        "the move must be read as implied chance; -142 to -130 and +120 to "
        "+110 are different sizes in the same direction")
    assert "to win" in body, "the moneyline rows are not labeled"
    # And the absent split is stated rather than drawn as zero.
    assert "publishes none" in src, "the missing split is unexplained"


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
