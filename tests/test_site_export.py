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
        "season": [2026, 2026, 2026], "week": [1, 1, 1],
        "player_id": ["00-1", "00-2", "00-3"],
        "player_name": ["CeeDee Lamb", "Nobody Scored", "DEF/ST"],
        "team": ["DAL", "NYG", "DAL"],
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
        players.append(player(f"{tm} DEF/ST", tm, gm, 0.09, 0.07, 12.0, "DEFST"))

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
            # What the fitted rule took this week, carried as (name, line,
            # side) and nothing else — every figure on screen still comes off
            # the board, so the two cannot disagree about the same bet.
            "shortlist": {
                "floors": {"over": {"lo": 0.0, "hi": 2.0, "n": 139,
                                    "mean_move_pp": 0.861},
                           "under": {"lo": 2.0, "hi": 5.0, "n": 198,
                                     "mean_move_pp": 0.283}},
                "rows": [{"player_name": "Alpha Back", "point": 4.5,
                          "side": "over", "gap_pp": 18.0,
                          "band_lo": 0.0, "band_hi": 2.0}],
                "dropped": [{"filter": "no posted line to bet into",
                             "dropped": 6, "left": 1},
                            {"filter": "fewer than 2 books behind the line",
                             "dropped": 0, "left": 1},
                            {"filter": "disagreement outside the band the "
                                       "market has come our way in",
                             "dropped": 0, "left": 1}],
                # Every held-out interval on all four of these markets spans
                # zero, and the page has to say so rather than print the point
                # estimate on its own.
                "graded": [{"season": "2025", "n": 349, "fixtures": 177,
                            "roi": 0.54, "roi_lo": -7.71, "roi_hi": 8.85},
                           {"season": "held out", "n": 380, "fixtures": 190,
                            "roi": -1.19, "roi_lo": -9.52, "roi_hi": 6.82}],
            },
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
                # Neither of these is the consensus line — 54.5 is, and the
                # rule did not take it. A view narrowed with `oneLine` keeps
                # the consensus row and drops both of these, so Alpha Back
                # disappears from a shortlist that is still counting him.
                # That is the bug `oneTake` exists for, and this fixture is
                # the only thing that can catch it.
                "shortlist": {
                    "floors": {"over": {"lo": 2.0, "hi": 5.0, "n": 118,
                                        "mean_move_pp": 0.090},
                               "under": None},
                    "rows": [{"player_name": "Alpha Back", "point": 51.5,
                              "side": "over", "gap_pp": 8.9,
                              "band_lo": 2.0, "band_hi": 5.0},
                             {"player_name": "Alpha Back", "point": 58.5,
                              "side": "over", "gap_pp": 4.4,
                              "band_lo": 2.0, "band_hi": 5.0}],
                    "dropped": [{"filter": "no posted line to bet into",
                                 "dropped": 1, "left": 4},
                                {"filter": "fewer than 2 books behind the line",
                                 "dropped": 1, "left": 3},
                                {"filter": "disagreement outside the band the "
                                           "market has come our way in",
                                 "dropped": 1, "left": 2}],
                    "graded": [{"season": "held out", "n": 409, "fixtures": 191,
                                "roi": -0.58, "roi_lo": -12.51, "roi_hi": 10.70}],
                },
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


def test_one_table_layout_at_every_width():
    """A phone scrolls further because it is smaller, not because it is different.

    Four attempts: label/value cards (destroyed the alignment that makes a
    table scannable), sideways scroll with a frozen name (right pattern, wrong
    table — three screens wide), four chosen columns with the rest behind a tap
    (put a chevron on every row, hid the bet buttons a gesture deep, and leaked
    the chevron onto the desktop as a stray grid child).

    It is one table now. A bounded pane that scrolls inside its own card, with
    the headings pinned to the pane and the name pinned to its left edge, and
    `hide` dropping the least useful columns on a small screen to shorten the
    journey.
    """
    from src.export import site as d

    base = d.CSS[:d.CSS.index("@media")].replace(" ", "")
    mid = d.CSS[d.CSS.index("@media (max-width:900px)"):
                d.CSS.index("@media (max-width:680px)")].replace(" ", "")
    narrow = d.CSS[d.CSS.index("@media (max-width:680px)"):].replace(" ", "")

    # The pane, declared once. Without it the overflow is not clipped, not
    # scrolled and not warned about — it is RENDERED, underneath the slip.
    assert "overflow:auto" in base and "max-height:calc(100vh-230px)" in base, (
        "a table that does not fit must say so by scrolling, not by hiding "
        "under the panel beside it")
    assert "position:sticky;top:0;z-index:15" in base, (
        "the pane is what scrolls, so the headings pin to it and need no "
        "constant for a site header whose height changes")
    assert "position:sticky;left:0" in base, "the name pins while numbers move"

    # The breakpoints only resize it. Nothing invents a second layout.
    assert "max-height:calc(100vh-280px)" in mid
    # 176, not 300: the page head is gone from a phone and the market menu
    # went to the site header, so the chrome above the board is the 64px
    # header and one pinned bar.
    assert "max-height:calc(100vh-176px)" in narrow
    for gone in ("display:flex", "display:none;padding:0", "flex:0060px",
                 ".rowmore{", "mobshow"):
        assert gone not in narrow.replace(".sortbar{display:flex}", ""), (
            f"{gone!r} is from the four-column phone layout, which is gone")
    assert ".sortbar{display:flex}" in narrow, (
        "the far headings need scrolling to reach, so the sort stays somewhere "
        "findable")


def test_the_board_never_makes_the_page_wider_than_the_screen():
    """`align-items` governs the cross axis, and the cross axis moves.

    Side by side, `.wrap` is a row and `align-items:flex-start` means "do not
    stretch the slip to the board's height". Stacked — which is what it becomes
    below 1100px — it is a column, the cross axis is now HORIZONTAL, and the
    same declaration means "size the board to its content". So `main` took the
    table's 1,150px, the page grew wider than the phone, and the scroll pane
    inside it never had a narrower width to scroll against.

    The table was never too wide. Its container was.
    """
    from src.export import site as d

    block = d.CSS[d.CSS.index("@media (max-width:1100px)"):
                  d.CSS.index("@media (max-width:900px)")].replace(" ", "")
    assert ".wrap{flex-direction:column;align-items:stretch}" in block, (
        "stacked, `flex-start` sizes the board to the widest thing in it")


def test_the_page_links_go_behind_a_button_on_a_narrow_screen():
    """Five tabs are a row on a desktop and a third line of header on a phone.

    That third line costs 44px of every screen to offer a jump most readers
    make once. Behind a button it costs nothing, and the button names the page
    you are on.
    """
    from src.export import site as d

    block = d.CSS[d.CSS.index("@media (max-width:900px)"):
                  d.CSS.index("@media (max-width:680px)")].replace(" ", "")
    assert ".nav{display:none}" in block, "the links come out of the flow"
    assert ".burger{display:inline-flex" in block, "and the button takes over"
    assert ".nav.open{" in block and "position:absolute" in block, (
        "opened, the menu lays over the board rather than pushing it down — "
        "or the header costs its height again the moment it is used")
    assert "flex-wrap:nowrap" in block, (
        "the header must not wrap; that is the row this removes")
    assert "const BARS" in d.JS_CORE and "S.navOpen" in d.JS_SHELL


def test_no_cell_is_rendered_without_a_column_to_put_it_in():
    """The chevron was appended to every row and styled only below 680px.

    Above it the grid has tracks for the real columns and nothing else, so the
    extra child wrapped onto an implicit row: an ellipsis on its own line under
    all 531 players, on the desktop, where it was never meant to appear at all.
    """
    from src.export import site as d

    for dead in ("mobmore", "rowmore", "mobshow", "MOB_COLS", "mobKey"):
        assert dead not in d.JS_SHARED and dead not in d.JS_WEEK, (
            f"{dead!r} belonged to the removed layout")
        assert dead not in d.CSS, f"{dead!r} still has styling with nothing to style"


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

    assert "'--cols:' + tracks" in d.JS_SHARED, (
        "the track must be a custom property, not the property itself")
    assert "grid-template-columns:" not in d.JS_SHARED, (
        "nothing may write the property itself into a style attribute")
    assert "grid-template-columns:var(--cols)" in d.CSS.replace(" ", "")
    # The name pins to the far edge of the lead cell, and that width is now
    # the lead column's own rather than a constant — so it travels the same
    # way, as a property the cascade can still reach.
    assert "';--lead:' + lead.w" in d.JS_SHARED
    assert "left:var(--lead,44px)" in d.CSS.replace(" ", "")

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


def test_the_board_and_the_results_map_name_a_player_the_same_way():
    """A leg id and a settlement key are the same string or nothing settles.

    Every team's defence is called "DEF/ST", so all 32 shared the id
    `any|DEF/ST`: starring one starred them all, and the results map resolved
    32 rows to a single outcome.

    Qualifying by team fixes it only if BOTH sides are qualified. Doing one and
    not the other is strictly worse than doing neither — the leg looks correct,
    matches no key, and reads Pending for ever, which is the failure this
    project treats as the expensive one because nothing errors.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "es_names", REPO / "scripts" / "47_export_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.qualified_name("DEF/ST", "BUF") == "BUF DEF/ST"
    assert mod.qualified_name("CeeDee Lamb", "DAL") == "CeeDee Lamb", (
        "only the ambiguous name is qualified; a real one is left alone")
    assert mod.qualified_name("DEF/ST", None) == "DEF/ST", (
        "with no team there is nothing to qualify it with")
    assert mod.qualified_name(None, "BUF") == ""

    # And it is the same function on both sides, not two spellings of one rule.
    src = (REPO / "scripts" / "47_export_site.py").read_text()
    board = src.index('pl_["player"] = qualified_name(')
    settle = src.index('out[f"{week}|{key}|{qualified_name(')
    assert board > 0 and settle > 0, (
        "the board and the results map must call the same helper")


def test_the_market_is_named_once_and_in_the_header():
    """It was drawn twice, and both copies were over the board.

    The market changes what every page is about, so it belongs with the page
    links rather than above one table — and on a phone it was the reason the
    chrome needed two pinned rows instead of one: the page head existed to
    carry it, and its own title and lede were hidden there anyway.

    Falsified by putting `marketMenu()` back into either page head: the count
    below goes to two and the head stops being an empty box that can be
    dropped.
    """
    from src.export import site as d

    # `marketMenu` is DEFINED in JS_WEEK, so counting the name there counts
    # its own declaration. What must be gone is the call — the page head used
    # to end with one on both of these pages.
    assert "marketMenu()," not in d.JS_WEEK, "not over the board"
    assert "marketMenu()," not in d.JS_COMBOS
    assert d.JS_SHELL.count("marketMenu()") == 1, "called once, in the header"
    assert "MARKET_ROUTES[S.route]" in d.JS_SHELL, (
        "Saved names its own market, the ladder prices the slip and the Model "
        "page describes all of them — a picker there changes nothing visible")

    # The season and the week it displaced. They are a fact about the build,
    # not something anyone acts on, so they read as one in the footer.
    assert "class: 'when'" not in d.JS_SHELL and ".when{" not in d.CSS
    assert "__SEASON__ week __WEEK__" in d.FOOTER
    page = d.render({"season": 2026, "week": 2, "built": "x", "markets": {},
                     "brand": "T"})
    assert "2026 week 2" in page, "the week must survive the substitution"
    assert "__SEASON__" not in page and "__WEEK__" not in page


def test_the_phone_pins_one_bar_and_knows_how_tall_it_is():
    """Two stacked sticky boxes, the top one pinning nothing.

    The page head pinned at 64 and the filters at 110, which wrote the head's
    height into a constant — and the head's title and lede are hidden at this
    width, so once the market menu moved to the site header it was an empty
    band holding the bar below it away from the header. iOS jitters exactly
    that arrangement while the address bar animates.

    Falsified by restoring `.pagehead{position:sticky;top:64px}` and the
    110px offset: the two assertions below fail together, which is the point
    — one offset cannot be wrong on its own.
    """
    from src.export import site as d

    narrow = d.CSS[d.CSS.index("@media (max-width:680px)"):].replace(" ", "")
    assert ".pagehead.titleonly{display:none}" in narrow, (
        "its title and its lede are hidden here and its only control has "
        "left; what remains is a band")
    # Not every head is only a title. Saved parlays keeps settled/won/staked
    # up there, and those are numbers rather than a heading.
    assert "'pagehead titleonly'" not in d.JS_SAVED, (
        "the counts on Saved are the point of visiting the page")
    assert d.JS_WEEK.count("'pagehead titleonly'") == 1
    assert "top:110px" not in narrow, "there is no head left to sit under"
    bar = narrow[narrow.index(".stickybar{"):]
    bar = bar[:bar.index("}")]
    # Measured, not declared. 64 is the first-paint fallback; the real number
    # comes off the header, because a constant here is a bar that slides under
    # the nav the moment the header grows a line — taking the market switcher
    # with it, which is the one control that must stay reachable.
    assert "top:var(--top,64px)" in bar, (
        "the filters pin under whatever height the header actually is")
    from src.export import site as e
    assert "root.style.setProperty('--top'" in e.JS_SHELL, (
        "and something has to measure it")
    assert "window.addEventListener('resize', measureTop)" in e.JS_SHELL, (
        "a rotation changes that height")


def test_the_pane_is_measured_against_the_viewport_the_phone_actually_has():
    """`100vh` on iOS is the window with the address bar hidden.

    So a pane sized in `vh` is taller than the screen it is on, the page
    scrolls to make up the difference, and the headings — which pin to the
    PANE, not to the window — ride up out of sight while rows keep coming.
    The row is not drawn over the header; the header has left.

    Falsified by deleting the `dvh` line at any one of the three widths: the
    pairing below fails there. The `vh` line stays as the fallback and must
    come first, or a browser that understands both takes the wrong one.
    """
    from src.export import site as d

    flat = d.CSS.replace(" ", "").replace("\n", "")
    vh = flat.count("max-height:calc(100vh-")
    assert vh == 3, f"three widths declare a pane height; found {vh}"
    assert flat.count("max-height:calc(100dvh-") == vh, (
        "every one of them needs its dynamic-viewport twin")
    for px in ("230px", "280px", "176px"):
        i = flat.index(f"max-height:calc(100vh-{px})")
        assert flat[i:].startswith(f"max-height:calc(100vh-{px});"
                                   f"max-height:calc(100dvh-{px})"), (
            f"at {px} the fallback must come first and the dvh twin second")

    # Comments out. The reason this is gone is written in the stylesheet and
    # names the property, so a search over the raw text finds the explanation
    # and calls it the bug.
    import re
    declared = re.sub(r"/\*.*?\*/", "", d.CSS, flags=re.S)
    assert "-webkit-overflow-scrolling" not in declared, (
        "a no-op since iOS 13, and the documented cause of sticky children "
        "painting in the wrong order inside the scroller they belong to")


def test_no_row_can_be_drawn_over_the_heading_that_names_it():
    """A cell that pins in both directions is two stickies on one element.

    The heading row pins to the top of the pane; the star and the name pin to
    its left edge. Where those meet, the browser has to resolve an order, and
    the only thing that settles it is the z-index — which was 5 against 6 with
    a 2 underneath, three numbers close enough that a body cell reached the
    top tier on iOS.

    Falsified by giving the body cells the heading's z-index: the assertion
    below fails and the star column scrolls up over its own heading.
    """
    from src.export import site as d

    import re
    flat = d.CSS.replace(" ", "")

    def zof(anchor):
        """The z-index of the rule that starts at `anchor`, as a number.

        Read as a number and not a character: the first version of this took a
        one-character slice, so a body cell raised to 15 read as 1 and the test
        agreed that 1 was under 15. It passed against the bug it names.
        """
        rule = flat[flat.index(anchor):]
        return int(re.search(r"z-index:(\d+)", rule).group(1))

    hd_z = zof(".hd{")
    body_z = zof(".hd>.mob-lead,.row>.mob-lead,")
    assert hd_z >= 15, f"the heading row needs a tier of its own; got {hd_z}"
    assert body_z < hd_z, (
        f"a body cell at {body_z} must sit under the heading row at {hd_z}")
    assert ".hd>.mob-lead,.hd>.mob-title{z-index:16}" in flat, (
        "and the heading's own pinned cells sit above the heading row")


def test_a_verdict_cannot_be_drawn_over_the_button_beside_it():
    """A grid item is `min-width:auto` — never smaller than its content.

    So a cell whose content is wider than its track does not clip and does not
    shrink: it overflows, and draws on top of the column next to it. "Strong
    call" measures wider in iOS Safari's system font than in the desktop one,
    which is why the pill sat over the + button on a phone and looked correct
    everywhere it was being checked.

    Falsified by removing either half: the track alone is not a guarantee,
    because the fonts are not ours to measure.
    """
    from src.export import site as d

    flat = d.CSS.replace(" ", "")
    assert ".hd>*,.row>*{min-width:0}" in flat, (
        "without this a cell is sized by its content, not by its track")
    pill = flat[flat.index(".row.pill{"):]
    pill = pill[:pill.index("}")]
    assert "max-width:100%" in pill and "overflow:hidden" in pill, (
        "bounded to its cell, the longest verdict can only be trimmed")
    assert "{ w: '100px', label: 'Read'" in d.JS_WEEK, (
        "and wide enough that the ordinary case is not trimmed at all")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_adding_a_leg_never_opens_the_slip_at_any_width(page_js, payload, tmp_path):
    """Six players, or one player six times.

    On a phone the slip is a sheet covering the board it was picked from. On a
    desktop it is a panel that TAKES 360px from that board, so every add
    reflows the table under the hand picking from it — columns move and the row
    being aimed at shifts. Neither is what "add another one" should do.

    The handle in the corner carries the count, so the feedback is there
    either way. A market conflict is the exception, and it is the one case
    where a prompt has to be seen to be answered.

    Falsified by restoring `S.slipOpen = true` in `toggleLeg`: both halves of
    `tests/js/slipopen.js` fail on the first add.
    """
    p = tmp_path / "payload.json"
    p.write_text(json.dumps(payload))
    r = subprocess.run(["node", str(REPO / "tests" / "js" / "slipopen.js"),
                        str(p), str(page_js)],
                       capture_output=True, text=True, cwd=str(REPO))
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_pressing_add_does_not_send_you_back_to_the_top(page_js, payload, tmp_path):
    """The page rebuilds its tree on every state change, and the pane went with it.

    So starring or adding the two hundredth player scrolled the board back to
    the first — the act of acknowledging a tap threw away what the tap was part
    of. Two things have to survive the rebuild and neither is enough alone:
    where the pane had got to, and how many rows had been drawn to get there.
    Restoring a position onto a table redrawn with only its first screenful
    scrolls to somewhere that does not exist.

    Changing a filter still starts at the top, on purpose: those are different
    rows, and a position in them is not a place.
    """
    p = tmp_path / "payload.json"
    p.write_text(json.dumps(payload))
    r = subprocess.run(["node", str(REPO / "tests" / "js" / "panescroll.js"),
                        str(p), str(page_js)],
                       capture_output=True, text=True, cwd=str(REPO))
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")
