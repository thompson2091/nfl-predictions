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
             "kick_day": "Thursday", "kick_et": "8:15 PM ET", "prime": True},
            {"game_id": "ARI_SF", "home": "SF", "away": "ARI",
             "total": 47.5, "spread": -8.5, "proj_home": 28.0, "proj_away": 19.5,
             "win_home": 0.78, "win_away": 0.22,
             "kick_day": "Sunday", "kick_et": "4:25 PM ET", "prime": False},
        ],
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
    ]}
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
                 "game tab bets renders"):
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
    assert "data-v3week" in src[i:i + 900], (
        "the picker has to be in the header or it is per-screen again")
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
        assert "." + cls in css, f"{cls} has no rule, so it colours nothing"
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


def test_the_slip_states_its_independence_assumption():
    """Two players in one game are not independent, and the page says so.

    The error runs one way — a same-game parlay is worth more than the product
    for team-mates and less across sides — so a page that prints the product
    without saying it is a page that quietly misprices the most common slip
    anyone builds.
    """
    from src.export import v3js

    src = v3js.js()
    i = src.index("function v3Outcomes")
    assert "independent" in src[i - 900:i].lower(), "unstated in the code"
    assert "independent" in src[i:i + 4000].lower(), "unstated on the page"


def test_the_ask_box_does_not_pretend_to_be_a_chat():
    """A free-text box needs a server the site does not have.

    The site is static files uploaded by hand. A box that accepts any question
    and answers three of them is worse than three buttons that say what they
    are, because only one of the two tells the reader where the edge of the
    feature is.
    """
    from src.export import v3js

    src = v3js.js()
    i = src.index("function v3Ask")
    block = src[i - 400:i + 900]
    assert "data-v3ask" in block
    assert "<input" not in block, "a text input promises an answer to anything"


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
