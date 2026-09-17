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
                                 "arms": [{"arm": "shortlist", "roi": -19.6, "n": 6345}]}},
        "served": {"version": "2026.01.01-test", "model": "xgb", "dirty": False,
                   "problems": [], "note": "A test version.",
                   "created": "2026-01-01T00:00:00+00:00"},
        "recipe": {"n_features": 5, "n_families": 2, "unattributed": [],
                   "families": [{"name": "usage", "n": 3, "worth_top1": 0.021,
                                 "p_value": 0.01, "cols": []}],
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


def test_narrow_screens_get_labelled_rows_rather_than_a_squeezed_grid():
    """Nine columns on a 360px screen is four characters each.

    The first attempt kept the grid and dropped columns, which leaves a row of
    unlabelled numbers once the header is gone. Each cell now carries its
    column's label and prints it, so a stacked row names its own values.

    Falsified by removing the `data-label` attribute: the CSS then has nothing
    to put in `content: attr(data-label)` and every row is a bare column of
    figures with no way to tell the model's number from the book's.
    """
    from src.export import site as d

    assert "'data-label': c.label || null" in d.JS_SHARED, (
        "every body cell must carry its column label")
    narrow = d.CSS[d.CSS.index("@media (max-width:680px)"):]
    assert "content:attr(data-label)" in narrow.replace(" ", "")
    assert ".hd{display:none}" in narrow.replace(" ", "")
    # The three cells that are furniture keep their places on the first line.
    for cls in ("mob-lead", "mob-title", "mob-act"):
        assert cls in narrow, f"{cls} has no narrow-screen placement"


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
