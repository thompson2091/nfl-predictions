"""site/site.html — the five-page board, and the two joins that settle it.

The page itself is JavaScript inside a generated file, so the rest of this
suite cannot see it: `tests/js/sitepages.js` renders every page against a stub
DOM and is driven from here. What is tested directly is the Python that feeds
it, and both halves of that have the same failure mode — a join that silently
matches nothing and reports a confident wrong answer rather than an error.

    pytest tests/test_site_export.py -v
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import polars as pl
import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def site():
    spec = importlib.util.spec_from_file_location(
        "site_export", REPO / "scripts" / "47_export_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_receiver_is_a_position_and_not_a_gap(site):
    """WR has no one-hot column, because it is the reference level.

    Reading "zero in every position column" as unknown would put the largest
    group on the board behind a position filter that never matches it — and
    the filter would look like it worked, because every other position would
    still narrow correctly.
    """
    assert "position_WR" not in site.POSITION_COLS
    assert site.POSITION_DEFAULT == "WR"


def test_settlement_joins_on_id_because_the_names_are_not_the_same(site, tmp_path,
                                                                  monkeypatch):
    """Play-by-play writes `C.Lamb`; the board carries `CeeDee Lamb`.

    Falsified by joining on the name: every leg then settles as a miss, every
    saved parlay reads Lost, and nothing errors. The two frames below share a
    player id and share no name at all, which is the real shape of the data.
    """
    proc = tmp_path / "processed"
    (proc / "anytime_td").mkdir(parents=True)
    (proc / "first_td").mkdir(parents=True)
    pl.DataFrame({
        "season": [2026, 2026], "week": [1, 1],
        "player_id": ["00-1", "00-2"],
        "player_name": ["CeeDee Lamb", "Nobody Scored"],
    }).write_parquet(proc / "anytime_td" / "features.parquet")
    pl.DataFrame({
        "season": [2026], "week": [1], "td_player_id": ["00-1"],
        "td_player_name": ["C.Lamb"],
    }).write_parquet(proc / "anytime_td" / "tds_anytime_td.parquet")

    monkeypatch.setattr(site, "get_path",
                        lambda kind, target=None: proc / target if target else proc)
    out = site.results(2026, 1)

    assert out["1|any|CeeDee Lamb"] == "hit", "the id joined even though the names differ"
    assert out["1|any|Nobody Scored"] == "miss"
    assert not any("|first|" in k for k in out), (
        "a market with no targets file contributes nothing, rather than "
        "marking everyone a miss")


def test_an_ungraded_week_settles_nothing_at_all(site, tmp_path, monkeypatch):
    """Pending is the honest state before kickoff, and a missing file is not a loss.

    An empty targets file beside a populated feature matrix means the week has
    not been extracted yet. Treating that as "nobody scored" would settle every
    saved parlay in the week as lost, on the strength of a file that had not
    been written.
    """
    proc = tmp_path / "processed"
    (proc / "anytime_td").mkdir(parents=True)
    pl.DataFrame({
        "season": [2026], "week": [2], "player_id": ["00-1"], "player_name": ["A B"],
    }).write_parquet(proc / "anytime_td" / "features.parquet")
    pl.DataFrame({
        "season": [2026], "week": [1], "td_player_id": ["00-1"],
    }).write_parquet(proc / "anytime_td" / "tds_anytime_td.parquet")

    monkeypatch.setattr(site, "get_path",
                        lambda kind, target=None: proc / target if target else proc)
    assert site.results(2026, 2) == {}


@pytest.fixture(scope="module")
def page_js(tmp_path_factory) -> Path:
    """The page's script, assembled exactly as `render` assembles it."""
    from src.export import site as d

    js = "\n".join([d.JS_CORE, d.JS_SHARED, d.JS_SLIPVIEW, d.JS_WEEK,
                    d.JS_COMBOS, d.JS_SAVED, d.JS_LADDER, d.JS_MODEL, d.JS_SHELL])
    p = tmp_path_factory.mktemp("site") / "page.js"
    p.write_text(js)
    return p


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_page_script_parses(page_js):
    """A syntax error here publishes a blank page with one console message."""
    r = subprocess.run(["node", "--check", str(page_js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.fixture(scope="module")
def payload() -> dict:
    """A tiny payload in the shape the exporter produces."""
    def player(name, team, game, ours, book, dec, pos, **kw):
        return dict({
            "player": name, "team": team, "game": game, "game_id": game,
            "ours": ours, "book": book, "priced": dec is not None, "dec": dec,
            "odds_num": None if dec is None else round((dec - 1) * 100),
            # `model_only` is deliberately not `ours`: the board shows both,
            # and a fixture where they coincide cannot catch the bug where the
            # two columns print the same number.
            # An opening price a little away from the close, so the movement
            # the board reports has something to report.
            "open_odds": None if dec is None else round((dec * 1.08 - 1) * 100),
            "open_implied": None if dec is None else 1 / (dec * 1.08),
            "pos": pos, "read": "Strong call", "rank": 1,
            "model_only": min(0.99, ours + 0.07),
            "best": None, "best_book": None, "status": None, "blocked": False,
        }, **kw)

    players = [
        player("Alpha Back", "AAA", "AAA @ BBB", 0.62, 0.45, 2.2, "RB"),
        player("Bravo Wide", "BBB", "AAA @ BBB", 0.41, 0.30, 3.4, "WR"),
        player("Charlie End", "CCC", "CCC @ DDD", 0.33, 0.29, 4.0, "TE"),
        player("Delta Deep", "DDD", "CCC @ DDD", 0.18, None, None, "WR"),
    ]
    # Deep enough that COMBO_POOL_MAX bites, and shaped the way a real board is:
    # the players we rate highest are the ones books have already quoted, so the
    # cap alone hides every unpriced one. A four-player fixture cannot show that
    # — the cap never engages — and the Combinations pool control it justifies
    # would look like a filter with nothing to filter.
    # Every team's defence is on the touchdown board, and every one of them is
    # named "DEF/ST" — which is why the line boards exclude them (a defence
    # catches nothing) and the touchdown board does not (it scores).
    for tm, gm in (("AAA", "AAA @ BBB"), ("BBB", "AAA @ BBB")):
        players.append(player("DEF/ST", tm, gm, 0.09, 0.07, 12.0, "DEFST"))

    _teams = [("AAA", "AAA @ BBB"), ("BBB", "AAA @ BBB"),
              ("CCC", "CCC @ DDD"), ("DDD", "CCC @ DDD")]
    for i in range(30):
        tm, gm = _teams[i % 4]
        ours = 0.60 - i * 0.015
        priced = i < 22          # the top of the board, and only the top
        players.append(player(f"Extra {i:02d}", tm, gm, round(ours, 3),
                              round(ours - 0.06, 3),
                              round(1.0 / max(ours - 0.06, 0.05), 3) if priced else None,
                              ["RB", "WR", "TE", "QB"][i % 4]))
    short = [{"player": "Alpha Back", "team": "AAA", "game": "AAA @ BBB",
              "ours": 0.62, "book": 0.45, "edge_pp": 17.0, "odds": 120,
              "best_odds": 150, "best_book": "Fanatics", "band": "+100 to +200",
              "band_roi": -9.9, "rank": 1, "pos": "RB"}]
    veto = [{"player": "Delta Deep", "team": "DDD", "game": "CCC @ DDD",
             "ours": 0.05, "book": 0.11, "edge_pp": -6.0, "odds": 600,
             "layable": True, "pos": "WR"}]
    market = {
        "key": "anytime_td", "label": "Anytime TD", "season": 2026, "week": 2,
        "players": players, "problems": [],
        "shortlist": {"rows": short, "vetoes": veto,
                      "dropped": [{"filter": "veto", "dropped": 1, "left": 3},
                                  {"filter": "floor", "dropped": 2, "left": 1}],
                      "floor": {"lo": 10.0},
                      "record": {"seasons": [2024, 2025],
                                 # Backing loses and fading wins, which is the
                                 # actual shape of this model's record and the
                                 # reason the Model page leads with the second.
                                 # `exchange` is not a footnote: you cannot lay
                                 # a player at a sportsbook, so +25% becomes
                                 # +2.5% net of commission.
                                 "fade": {"n": 8397, "roi": 24.97, "lo": 20.23,
                                          "hi": 29.69, "concentration": 0.0048,
                                          "verdict": "positive",
                                          "exchange": [{"commission": 0.02, "roi": 3.07},
                                                       {"commission": 0.05, "roi": 2.46}]},
                                 "arms": [{"arm": "shortlist", "roi": -19.6, "n": 6345}]}},
        # The fitted teammate correlation, which the slip's round robin prices
        # with. Negative and small, as measured: one offence stalling takes its
        # players down together, so a same-team parlay is worth slightly less
        # than independence says. Only the touchdown markets carry this — an
        # over/under block has no such number, which is the invariant
        # `sitepages.js` pins.
        "cover": {"rho": -0.0241, "max_players": 12},
        "served": {"version": "2026.01.01-test", "model": "xgb", "dirty": False,
                   "problems": [], "note": "A test version.",
                   "created": "2026-01-01T00:00:00+00:00"},
        "recipe": {"n_features": 5, "n_families": 2, "unattributed": [],
                   # `worth_top1` is ALREADY in percentage points. A fixture
                   # carrying 0.021 cannot catch a page that multiplies by a
                   # hundred, because 2.1 still looks like a plausible number;
                   # 2.83 becoming 283 does not.
                   "families": [{"name": "build_qb_features", "n": 4,
                                 "worth_top1": 2.83, "p_value": 0.002,
                                 "cols": []},
                                {"name": "build_usage_features", "n": 18,
                                 "worth_top1": 1.42, "p_value": 0.03,
                                 "cols": []}],
                   "seasons": [{"season": 2025, "games": 1231, "top1": 0.114,
                                "top3": 0.279, "top5": 0.434}]},
    }
    second = dict(market, key="first_td", label="First TD",
                  shortlist={"rows": [], "vetoes": [], "dropped": [],
                             "floor": {"lo": 10.0}, "record": {"seasons": [], "arms": []}})
    return {
        "built": "2026-09-16T00:00:00+00:00", "brand": "SquaresPro",
        "season": 2026, "week": 2, "results": {},
        "markets": [market, second],
        "receptions": {
            "season": 2026, "week": 2, "problem": "", "model": True,
            # The weight actually fitted, read by the board and the Model page
            # rather than typed into either.
            "blend": 0.17,
            # One quoted line and several projections, which is the real
            # proportion: books post receptions far later than touchdown
            # props, so most of this board has no line against it all week.
            "priced_rows": 1,
            "rows": [{"player_name": "Alpha Back", "team": "AAA", "game_id": "AAA @ BBB",
                      "mu": 5.5, "point": 4.5, "odds": -105, "fair_prob": 0.48,
                      "model_only": 0.66, "ours": 0.59, "edge_pp": 11.3,
                      # Both vigged sides, which is what lets the page price
                      # the UNDER at its own number instead of the over's.
                      # -105 over against a 1.0471 overround is a -115 under,
                      # and a fixture carrying only one side cannot catch a
                      # leg that takes the wrong one.
                      "implied_prob": 0.5122, "overround": 1.0471,
                      "open_point": 4.5, "open_odds": -115, "open_implied": 0.535,
                      "lo": 3, "hi": 9, "n_books": 6, "thin": False}]
                    # Floor and ceiling widen with the mean, which is the
                    # property the column exists to show and the one a fixed
                    # window would hide.
                    + [{"player_name": n, "team": t, "game_id": g, "mu": mu,
                        "lo": max(0, int(mu * 0.55)), "hi": int(mu * 1.7) + 2,
                        "point": None, "odds": None, "fair_prob": None,
                        "model_only": None,
                        # Half of them opened with a line and have no close,
                        # which is the real shape mid-week and the case the
                        # fallback exists for.
                        "open_point": round(mu * 2) / 2 if mu > 2 else None,
                        "open_odds": -110 if mu > 2 else None,
                        "open_implied": 0.524 if mu > 2 else None,
                        # Priced against that opening line by
                        # `47_export_site._price_open_fallback`, because a row
                        # carrying a line and no probability is one the
                        # Combinations page multiplies into a NaN. An
                        # over/under posts both sides at the open, so the
                        # de-vigged book number is real here.
                        "open_fair": 0.501 if mu > 2 else None,
                        "open_books": 7 if mu > 2 else None,
                        "fair_prob": 0.501 if mu > 2 else None,
                        "model_only": 0.55 if mu > 2 else None,
                        "ours": 0.52 if mu > 2 else None,
                        "edge_pp": 1.9 if mu > 2 else None,
                        "n_books": 7 if mu > 2 else 0, "thin": mu <= 2}
                       for n, t, g, mu in [
                           ("Bravo Wide", "BBB", "AAA @ BBB", 4.8),
                           ("Charlie End", "CCC", "CCC @ DDD", 3.9),
                           ("Delta Deep", "DDD", "CCC @ DDD", 2.2),
                           ("Echo Slot", "AAA", "AAA @ BBB", 1.6),
                           ("Foxtrot Back", "BBB", "AAA @ BBB", 1.1),
                           ("Golf Tight", "CCC", "CCC @ DDD", 0.9)]],
            "forward": {"season": 2026, "pushes": 0, "beats_market": False,
                        "note": "Log loss, lower is better.",
                        "pooled": {"n": 283, "over_rate": 0.477,
                                   "model_log_loss": 0.7030, "market_log_loss": 0.6769},
                        "weeks": [{"week": 1, "n": 283, "over_rate": 0.477,
                                   "model_log_loss": 0.7030, "market_log_loss": 0.6769}]},
        },
        # One yardage board, wired the same way and NOT a copy of receptions:
        # a different model family underneath, its own fitted blend weight, and
        # `proj` rather than `mu`. A fixture carrying only receptions cannot
        # catch the page reading the count market's field name on all four.
        "yards": {
            "rushing_yards": {
                "season": 2026, "week": 2, "problem": "", "model": True,
                "market": "rushing_yards", "label": "Rushing yards",
                "blend": 0.06, "priced_rows": 1,
                "graded": {"beats_market": False, "blend_beats_market": False,
                           "seasons": [{"season": 2025, "n": 5728,
                                        "model": 0.71367, "market": 0.69261,
                                        "blend": 0.69103, "in_sample": False,
                                        "vs_market": {"n_games": 282,
                                                      "ci95": [-0.0371, -0.0053]}}]},
                # Alpha Back at four different lines, which is what a yardage
                # board actually looks like: books scatter, most of the lines
                # are one book deep, and only one of them is where the market
                # is. 58.5 is the lowest-priced over and one book drew it;
                # 54.5 is where five of them are. A fixture with one line per
                # player cannot catch a board that leads with the friendliest
                # single quote.
                "rows": [{"player_name": "Alpha Back", "team": "AAA",
                          "game_id": "2026_02_AAA_BBB", "proj": 62.37, "lo": 30.72,
                          "hi": 97.41, "point": 54.5, "odds": -118,
                          "implied_prob": 0.5413, "overround": 1.0476,
                          "fair_prob": 0.5166, "model_only": 0.58,
                          "ours": 0.522, "edge_pp": 0.5, "n_books": 5,
                          "thin": False, "best_line": True, "n_lines": 3},
                         {"player_name": "Alpha Back", "team": "AAA",
                          "game_id": "2026_02_AAA_BBB", "proj": 62.37, "lo": 30.72,
                          "hi": 97.41, "point": 51.5, "odds": -125,
                          "implied_prob": 0.5556, "overround": 1.048,
                          "fair_prob": 0.5301, "model_only": 0.62,
                          "ours": 0.547, "edge_pp": 1.7, "n_books": 2,
                          "thin": True, "best_line": False, "n_lines": 3},
                         {"player_name": "Alpha Back", "team": "AAA",
                          "game_id": "2026_02_AAA_BBB", "proj": 62.37, "lo": 30.72,
                          "hi": 97.41, "point": 58.5, "odds": -108,
                          "implied_prob": 0.5192, "overround": 1.047,
                          "fair_prob": 0.4959, "model_only": 0.54,
                          "ours": 0.509, "edge_pp": 1.3, "n_books": 1,
                          "thin": True, "best_line": False, "n_lines": 3},
                         {"player_name": "Charlie End", "team": "CCC",
                          "game_id": "2026_02_CCC_DDD", "proj": 18.0, "lo": 4.0,
                          "hi": 34.0, "point": 16.5, "odds": -112,
                          "implied_prob": 0.5283, "overround": 1.0472,
                          "fair_prob": 0.5046, "model_only": 0.53,
                          "ours": 0.509, "edge_pp": 0.4, "n_books": 4,
                          "thin": False, "best_line": True, "n_lines": 1},
                         {"player_name": "Bravo Wide", "team": "BBB",
                          "game_id": "2026_02_AAA_BBB", "proj": 4.1, "lo": 0.0,
                          "hi": 12.0, "point": None, "odds": None,
                          "fair_prob": None, "model_only": None, "ours": None,
                          "edge_pp": None, "n_books": 0, "thin": False}],
            },
        },
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_every_page_renders(page_js, payload, tmp_path):
    """The failure mode of a generated single-page file is a blank screen.

    `node --check` proves the syntax and nothing else — a bad reference parses
    fine and throws on load, leaving one line in a console nobody has open. So
    each page is actually rendered, and what must be on it is asserted from the
    payload rather than typed in.
    """
    p = tmp_path / "payload.json"
    p.write_text(json.dumps(payload))
    r = subprocess.run(["node", str(REPO / "tests" / "js" / "sitepages.js"),
                        str(p), str(page_js)],
                       capture_output=True, text=True, cwd=str(REPO))
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")


def test_the_page_carries_its_own_fonts():
    """Self-contained means self-contained, including the type.

    The page has always been a thing you can send to someone who does not have
    the repo. A page that reaches out to a font server is not that, and the
    failure is silent — it renders in a fallback and looks merely slightly
    wrong.
    """
    from src.export import site as d

    faces = d._font_faces()
    assert "Newsreader" in faces and "Schibsted Grotesk" in faces
    assert faces.count("@font-face") == 2, "both faces are variable; one file each"
    assert "data:font/woff2;base64," in faces
    assert "http" not in faces, "no font may be fetched over the network"


def test_the_results_map_covers_last_week_as_well_as_this_one(site, tmp_path,
                                                              monkeypatch):
    """Otherwise a saved parlay can never settle, and the feature is furniture.

    The slate holds a finished week until the next one's roster lands, and the
    rollover that builds the next week is the same run that extracts the
    finished week's touchdowns. So the only export able to settle week 2 is the
    one that has already become week 3. Carrying one week means every saved
    parlay reads Pending until its key stops being read.

    Falsified by narrowing the loop back to `(week,)`: week 1 disappears from
    the map and the assertion below fails while nothing else does.
    """
    proc = tmp_path / "processed"
    (proc / "anytime_td").mkdir(parents=True)
    pl.DataFrame({
        "season": [2026, 2026], "week": [1, 2],
        "player_id": ["00-1", "00-1"], "player_name": ["A B", "A B"],
    }).write_parquet(proc / "anytime_td" / "features.parquet")
    pl.DataFrame({
        "season": [2026], "week": [1], "td_player_id": ["00-1"],
    }).write_parquet(proc / "anytime_td" / "tds_anytime_td.parquet")

    monkeypatch.setattr(site, "get_path",
                        lambda kind, target=None: proc / target if target else proc)
    out = site.results(2026, 2)

    assert out["1|any|A B"] == "hit", "last week settles"
    assert "2|any|A B" not in out, "this week has not been played, so it stays pending"


def test_a_player_is_keyed_per_week_not_across_them(site, tmp_path, monkeypatch):
    """`any|Derrick Henry` is a different bet in week 2 than in week 3.

    Without the week in the key, a live parlay would settle from a result it
    never had — and it would settle as a win as readily as a loss, which is the
    kind of wrong that gets believed.
    """
    proc = tmp_path / "processed"
    (proc / "anytime_td").mkdir(parents=True)
    pl.DataFrame({
        "season": [2026, 2026], "week": [1, 2],
        "player_id": ["00-1", "00-1"], "player_name": ["A B", "A B"],
    }).write_parquet(proc / "anytime_td" / "features.parquet")
    # Scored in week 1, did not in week 2.
    pl.DataFrame({
        "season": [2026], "week": [1], "td_player_id": ["00-1"],
    }).write_parquet(proc / "anytime_td" / "tds_anytime_td.parquet")

    monkeypatch.setattr(site, "get_path",
                        lambda kind, target=None: proc / target if target else proc)
    out = site.results(2026, 1)

    assert out["1|any|A B"] == "hit"
    assert all(k.count("|") == 2 for k in out), "week, market, player — in that order"


def test_launch_builds_one_file_under_a_name_a_server_will_serve():
    """Serving site/ serves the Streamlit recording, not this board.

    `site/` holds index.html from `make site`, and every web server hands out
    index.html by default — so uploading that directory publishes the wrong
    page, and it publishes something that looks plausible rather than erroring.
    """
    mk = (REPO / "Makefile").read_text()
    assert "\nlaunch:" in mk
    block = mk.split("\nlaunch:")[1].split("\n\n")[0]

    # The `--out` flag specifically, not any mention of the path. The first
    # version of this assertion looked for "public/index.html" anywhere in the
    # recipe and was satisfied by the closing `@echo`, so it passed against a
    # target that wrote public/board.html — a test agreeing with the file
    # rather than with the behaviour.
    out = [ln for ln in block.splitlines() if "--out" in ln]
    assert out, "the launch target must name its output"
    assert "--out public/index.html" in out[0], (
        f"a served directory hands out index.html by default; got {out[0].strip()!r}")
    assert "rm -rf public" in block, "the directory is disposable, so it is rebuilt clean"
    assert "public/" in (REPO / ".gitignore").read_text()


def test_narrow_screens_keep_the_table_and_pin_the_name():
    """A board is for comparing players on one number.

    Below 680px every row used to become its own card, with the grid dropped
    and each cell printing its column label from `data-label`. That reads well
    for one row and badly for forty: comparing two players on a single figure
    meant scrolling past every other figure they had.

    So the columns stay at their real widths and the table scrolls sideways
    inside its own card, with the star and the player pinned to the left edge
    so the name stays put while the numbers move under it.

    Falsified three ways, each of which breaks it differently: drop the
    `overflow-x` and the columns squash instead of scrolling; drop the sticky
    and the name scrolls away, leaving a row of figures belonging to nobody;
    drop the background on the pinned cells and the columns sliding underneath
    show through the name.
    """
    from src.export import site as d

    # The `.hd` rule itself, not "everything before the first @media" — the
    # first one in this sheet is the dark-mode block near the top, so that
    # slice never contained the table header and the assertion below could not
    # fail however the rule was broken.
    i = d.CSS.index("\n.hd{")
    base = d.CSS[i:d.CSS.index("}", i)].replace(" ", "")
    mid = d.CSS[d.CSS.index("@media (max-width:900px)"):
                d.CSS.index("@media (max-width:680px)")].replace(" ", "")
    narrow = d.CSS[d.CSS.index("@media (max-width:680px)"):]
    flat = narrow.replace(" ", "")

    # Pinned under the site header on a wide screen, where that bar is exactly
    # 64px; pinned to its own scroll pane below 900, where the nav wraps and
    # the bar's height stops being a number anyone can write down.
    assert "position:sticky;top:64px" in base, (
        "a long board must not leave a column of figures with nothing naming "
        "them")
    assert ".rows{overflow:auto" in mid and "max-height:76vh" in mid, (
        "below 900 the table becomes its own pane, so the header pins to that "
        "rather than to a site header of unpredictable height")
    assert ".hd{top:0}" in mid

    assert ".hd{display:none}" not in flat, (
        "a table that scrolls needs its header; it is the only thing naming "
        "the columns once the labels are gone")
    assert "width:max-content" in flat, (
        "without it the grid compresses to the viewport and the scroll never "
        "engages")

    # The name pins, and so does its header, or the headings slide out from
    # over the column they name.
    pin = flat[flat.index(".hd>.mob-lead"):]
    assert "position:sticky" in pin and "left:0" in pin
    assert "background:var(--card)" in pin, (
        "the columns sliding underneath show through an unpainted cell")
    assert ".hd>.mob-lead+.mob-title,.row>.mob-lead+.mob-title{left:44px}" in flat, (
        "the player sits beside the star, not on top of it")
    assert ".hd>.mob-lead,.hd>.mob-title{z-index:6}" in flat, (
        "where the two pins cross, the header must outrank the column it "
        "names or the first column scrolls up over its own heading")

    # And the marker reaches the header cell, not only the body cell.
    assert "c.mob ? 'mob-' + c.mob + ' ' : ''" in d.JS_SHARED, (
        "the header cell must carry the same mob- marker as its column")


def test_the_slip_is_a_sheet_on_narrow_screens_not_a_block_below_the_board():
    """Stacked in the flow it lands under five hundred rows.

    That is not "below the board", it is unreachable — and the handle that
    opens it would scroll you there rather than show it. Falsified by putting
    the panel back in the document flow: the assertions below fail and the
    control becomes a link to the bottom of a very long page.
    """
    from src.export import site as d

    block = d.CSS[d.CSS.index("@media (max-width:1100px)"):
                  d.CSS.index("@media (max-width:900px)")]
    flat = block.replace(" ", "").replace("\n", "")
    assert "position:fixed" in flat, "the sheet is fixed to the viewport"
    assert "bottom:0" in flat
    assert "max-height:82vh" in flat, "it must not cover the whole screen"
    assert "padding-bottom:180px" in flat, (
        "the board needs room to scroll clear of the sheet, or its last rows "
        "sit underneath it with no way to reach them")


def test_no_layout_property_is_written_inline_where_a_breakpoint_overrides_it():
    """An inline declaration beats every rule in the stylesheet, media queries included.

    The column track was written inline as `grid-template-columns`, so the
    narrow layout was present, correct, and unreachable — the board kept its
    nine-column grid at 360px and no amount of CSS could take it back. The
    track is a custom property now, which carries the same value while leaving
    the property to the cascade.

    Falsified by writing the track inline again: `--cols` disappears from the
    output and the assertion below fails, which is the only signal this bug
    gives — it does not throw, it just quietly ignores the breakpoint.
    """
    from src.export import site as d

    assert "'--cols:' + tpl" in d.JS_SHARED, (
        "the track must be a custom property, not the property itself")
    assert "grid-template-columns:' + tpl" not in d.JS_SHARED
    assert "grid-template-columns:var(--cols)" in d.CSS.replace(" ", "")

    # And nothing else writes a property inline that the narrow rules restyle.
    narrow = d.CSS[d.CSS.index("@media (max-width:1100px)"):]
    overridden = {p.split(":")[0].strip()
                  for p in ("grid-template-columns:", "position:", "max-height:")}
    for prop in overridden:
        assert f"style: '{prop}" not in d.JS_SHARED, (
            f"{prop} is set inline and restyled at a breakpoint")
    assert "!important" not in narrow.split("@media (max-width:680px)")[0], (
        "a breakpoint needing !important is a breakpoint fighting an inline style")


def test_the_opening_line_is_the_consensus_not_the_friendliest():
    """One opening line per player, and which one is not arbitrary.

    `opening_prices` collapses a player's opening quotes to a single row. It
    used to keep the LOWEST line, which is correct for a yes/no market (there
    is only one) and nearly harmless for receptions, where books agree.

    On a yardage market books scatter: a quarterback carries a median of four
    distinct opening lines across the board, 89% of player-weeks have more than
    one, and the lowest sits 4.9 yards below the median. Keeping the lowest
    hands the over a five-yard head start, and everything downstream inherits
    it — the Open column reports dispersion as movement, and a row with no
    close is priced against the most over-friendly number available.

    So the pick is the line the most books drew, ties to the one nearest the
    median. Asserted on a frame where those two answers differ.
    """
    import importlib.util

    import polars as pl

    spec = importlib.util.spec_from_file_location(
        "es_open", REPO / "scripts" / "47_export_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # One quarterback, four opening lines. 248.5 is the lowest and one book
    # drew it; 254.5 is where six of them are.
    rows = []
    for point, books, odds in ((248.5, 1, -110), (250.5, 2, -112),
                               (254.5, 6, -115), (258.5, 2, -118)):
        rows.append({
            "season": 2026, "week": 1, "market": "passing_yards",
            "snapshot": "open", "player_name_norm": "test qb",
            "player_name_raw": "Test QB", "game_id": "2026_01_AAA_BBB",
            "point": point, "odds": odds, "implied_prob": 0.52,
            "fair_prob": 0.50, "n_books": books, "overround": 1.05,
            "captured_at": "2026-09-01T12:00:00+00:00",
            "book_last_update": "2026-09-01T11:59:00+00:00",
            "regions": "us,us2", "home_team": "AAA", "away_team": "BBB",
        })
    frame = pl.DataFrame(rows)

    def fake_read(_path):
        return frame

    import src.ingest.odds_history as OH
    orig = (pl.read_parquet, OH.drop_in_play, OH.resolve_game_ids)
    pl.read_parquet = fake_read
    OH.drop_in_play = lambda df: df
    OH.resolve_game_ids = lambda df: df
    try:
        out = mod.opening_prices(2026, 1)
    finally:
        pl.read_parquet = orig[0]
        OH.drop_in_play, OH.resolve_game_ids = orig[1], orig[2]

    got = out.get("passing_yards|test qb")
    assert got is not None, list(out)
    assert got["point"] == 254.5, (
        f"kept the {got['point']} line; the consensus is 254.5, where six "
        f"books are. 248.5 is the lowest and one book drew it.")
    assert got["n_books"] == 6, got


def test_the_consensus_line_is_the_one_the_most_books_drew():
    """Which of a player's posted lines the board leads with.

    A yardage board carries one row per (player, line) and books scatter: 4.4
    rows per quarterback on passing yards against 1.0 on receptions. They are
    not duplicates — each is a real bet — but most are one book deep, and a
    board that shows a player six times leads with whichever of his lines
    sorted highest, which is usually the friendliest single quote.

    The rule matters more than it looks. Measured on 2026 week 2, picking each
    player's BEST-EV line instead of the consensus raises the share of
    one-book rows from 0% to 39% on passing yards and invents +2.3 of mean EV
    — and the graded record says exactly that band is where the model's
    apparent edge is fake (2024 passing: +0.0057 against one book, -0.0143
    against two, -0.0245 against three or more).
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "es_cons", REPO / "scripts" / "47_export_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def row(point, books):
        return {"player_name": "Test Man", "point": point, "n_books": books}

    # 58.5 is the friendliest over and one book drew it; 54.5 is where five are.
    rows = [row(58.5, 1), row(51.5, 2), row(54.5, 5), row(56.5, 1)]
    other = {"player_name": "Only One", "point": 20.5, "n_books": 3}
    payload = {"yards": {"rushing_yards": {"rows": rows + [other]}},
               "receptions": {"rows": []}}
    mod._mark_consensus_lines(payload)

    best = [r for r in rows if r["best_line"]]
    assert len(best) == 1, best
    assert best[0]["point"] == 54.5, (
        f"led with {best[0]['point']}; five books are on 54.5 and one drew "
        f"58.5")
    assert all(r["n_lines"] == 4 for r in rows), rows
    assert other["best_line"] and other["n_lines"] == 1

    # A tie on book count goes to the line nearest that player's median, not
    # to whichever happened to be first.
    tied = [row(40.5, 3), row(60.5, 3), row(50.5, 1)]
    mod._mark_consensus_lines({"yards": {"rushing_yards": {"rows": tied}}})
    picked = [r for r in tied if r["best_line"]]
    assert len(picked) == 1 and picked[0]["point"] in (40.5, 60.5), picked
    assert abs(picked[0]["point"] - 50.5) == 10.0, picked


def test_a_row_showing_only_an_opening_line_still_counts_as_a_line():
    """The collapse runs after the open-line fallback, so it sees those rows.

    Mid-week most of a count board has an opening line and no close. If the
    consensus pass ignored them they would every one be flagged `best_line`
    by default and the narrowing would do nothing on the week it matters most.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "es_cons2", REPO / "scripts" / "47_export_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    rows = [{"player_name": "Open Only", "point": None, "open_point": 4.5,
             "n_books": 7},
            {"player_name": "Open Only", "point": None, "open_point": 5.5,
             "n_books": 2},
            {"player_name": "No Line", "point": None, "open_point": None}]
    mod._mark_consensus_lines({"receptions": {"rows": rows}})
    assert rows[0]["best_line"] is True and rows[0]["n_lines"] == 2
    assert rows[1]["best_line"] is False
    # A projection with no line anywhere is not part of the count.
    assert "best_line" not in rows[2]
