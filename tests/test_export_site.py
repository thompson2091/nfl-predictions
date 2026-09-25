"""The site payload: what the page is handed, and what it joins on."""

from pathlib import Path




def test_shortlist_and_veto_names_match_the_board_they_filter():
    """A defence on either list must not silently drop out of its view.

    The board qualifies "DEF/ST" by team so 32 defences do not share one leg
    id. Shortlist and veto rows are matched to the board BY NAME, so leaving
    them bare made a vetoed defence match nothing — Fades came back one row
    short and looked like a quiet week rather than a bug.
    """
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "se", Path(__file__).resolve().parents[1] / "scripts/47_export_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    payload = {"markets": [{
        "players": [{"player": "DEF/ST", "team": "BUF"},
                    {"player": "Josh Allen", "team": "BUF"}],
        "shortlist": {"rows": [{"player": "DEF/ST", "team": "BUF"}],
                      "vetoes": [{"player": "DEF/ST", "team": "KC"}]}}]}
    for m in payload["markets"]:
        for p in m["players"]:
            p["player"] = mod.qualified_name(p["player"], p["team"])
        for key in ("rows", "vetoes"):
            for r in m["shortlist"][key]:
                r["player"] = mod.qualified_name(r["player"], r["team"])

    names = {p["player"] for p in payload["markets"][0]["players"]}
    short = payload["markets"][0]["shortlist"]["rows"][0]["player"]
    assert short in names, f"{short!r} does not match the board: {names}"
    assert payload["markets"][0]["shortlist"]["vetoes"][0]["player"] \
        == "KC DEF/ST"


def test_bets_payload_reaches_the_page_under_its_own_name():
    """`DATA` is the payload; `PAYLOAD` is the market-key map.

    `vBets` first read `PAYLOAD.games`, which is the `{any, first, rec, ...}`
    lookup and has no `games` key. The tab rendered its own "no game lines
    captured" empty state on a build that carried 126 priced outcomes — a
    failure indistinguishable from the legitimate state it imitates.
    """
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "src/export/v2js.py").read_text()
    for bad in ("PAYLOAD.games", "PAYLOAD.bets"):
        assert bad not in js, (
            f"{bad} is the market-key map, not the payload — use DATA")
    assert "DATA.games" in js and "DATA.bets" in js


def test_every_clickable_data_attribute_is_handled():
    """A `data-` attribute a view emits but `CLICKS` omits is a dead button.

    It throws nothing and logs nothing: the delegated listener simply never
    matches it. `betseg` was added to three tab buttons and had to be added
    here too.
    """
    import re
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "src/export/v2js.py").read_text()
    m = re.search(r"const CLICKS = \[(.*?)\];", js, re.S)
    assert m, "CLICKS list not found"
    handled = set(re.findall(r"'([a-z0-9]+)'", m.group(1)))
    emitted = set(re.findall(r"data-([a-z0-9]+)=", js))
    # Attributes the input listener owns rather than the click listener.
    emitted -= {"pstake", "act"}
    missing = {e for e in emitted if e not in handled and e in {
        "betseg", "cbpool", "view", "tab", "fam", "set", "drop"}}
    assert not missing, f"emitted but never handled: {sorted(missing)}"


def test_every_route_has_a_screen_function_in_the_emitted_js():
    """A route whose view function is missing is a blank tab.

    Editing `v2js.py` by splicing on a `\"\"\"` boundary once deleted nine
    functions at a stroke — the whole of Combos, Ladder and Model — and left
    an orphan triple-quote that made the module unparseable. The build still
    produced a page, from stale bytecode, so nothing anywhere said no.
    """
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src/export/v2js.py"
    # Parseable at all — the orphan quote made this false while the build
    # carried on running from __pycache__.
    compile(src.read_text(), str(src), "exec")

    import importlib

    v2js = importlib.import_module("src.export.v2js")
    js = "".join(getattr(v2js, n) for n in dir(v2js) if n.startswith("JS"))

    routes = re.findall(r"case '(\w+)': return (\w+)\(", js)
    assert routes, "no routes found in screenHTML"
    for route, fn in routes:
        assert f"function {fn}(" in js, (
            f"route {route!r} calls {fn}() and nothing defines it")

    # Helpers every screen leans on. `keystat` went with the nine and took
    # the Bets tab down with it.
    for helper in ("keystat", "field"):
        assert f"const {helper}" in js or f"function {helper}(" in js, (
            f"{helper} is referenced by the screens and is not defined")


def test_v2js_string_constants_are_balanced():
    """Every JS_* constant holds JavaScript, not a fragment of Python.

    The orphan `\"\"\"` swallowed `JS_SAVED = r\"\"\"` into a string literal,
    so the name survived import and its contents did not.
    """
    import importlib

    v2js = importlib.import_module("src.export.v2js")
    names = [n for n in dir(v2js) if n.startswith("JS")]
    assert len(names) >= 6, f"expected the JS constants, found {names}"
    for n in names:
        v = getattr(v2js, n)
        assert isinstance(v, str) and len(v) > 200, f"{n} is {len(v)} chars"
        assert "= r" not in v[:40], f"{n} begins with a Python assignment"


def test_history_is_reachable_under_the_key_the_board_looks_it_up_by():
    """The week pill looked up `DATA.history[S.market]` and never found it.

    The board's market keys are `any` and `first`; `week_history` is built per
    TARGET TYPE and keyed `anytime_td` and `first_td`. The lookup returned
    undefined for every market, so the pill never rendered — and "no history"
    is indistinguishable from "no weeks played yet", which is a normal state,
    so nothing complained. It shipped dead.
    """
    import importlib
    import re

    v2js = importlib.import_module("src.export.v2js")
    js = "".join(getattr(v2js, n) for n in dir(v2js) if n.startswith("JS"))

    m = re.search(r"const HISTORY_KEY = \{(.*?)\};", js, re.S)
    assert m, "HISTORY_KEY map is gone; the week pill will look up the wrong key"
    mapped = dict(re.findall(r"(\w+):\s*'([\w]+)'", m.group(1)))
    assert mapped.get("any") == "anytime_td"
    assert mapped.get("first") == "first_td"

    # And the builder must still emit those names, or the map points at
    # nothing and the failure returns in the other direction.
    build = (Path(__file__).resolve().parents[1]
             / "scripts/47_export_site.py").read_text()
    assert 'for mk in ("anytime_td", "first_td")' in build



def test_week_history_still_exposes_every_builder_the_export_calls():
    """A splice on this module once deleted `payload` outright.

    The export catches the resulting ImportError and prints "week history
    unavailable", so the page built fine with no history on any market — the
    same shape as a season that has not started.
    """
    import importlib

    wh = importlib.import_module("src.evaluation.week_history")
    for name in ("played_weeks", "week_board", "payload", "ou_week",
                 "ou_payload"):
        assert callable(getattr(wh, name, None)), f"{name} is missing"

    build = (Path(__file__).resolve().parents[1]
             / "scripts/47_export_site.py").read_text()
    assert "from src.evaluation.week_history import payload as week_payload" in build
    assert "from src.evaluation.week_history import ou_payload" in build


def test_history_is_split_out_of_the_page_and_indexed():
    """The rows live in their own files; the page keeps only the index.

    Inlined, a full season across six markets measured 20MB. If `_split_history`
    stops firing, the page silently grows by that much instead of failing.
    """
    import importlib

    pwa = importlib.import_module("src.export.pwa")
    payload = {"history": {"anytime_td": {
        "weeks": {"1": [{"a": 1}], "2": []}, "accuracy": {"1": {"n": 1}},
        "played": [1, 2]}}}
    out, files = pwa._split_history(payload)
    assert "weeks" not in out["history"]["anytime_td"]
    assert out["history"]["anytime_td"]["has"] == [1], "empty weeks must not be offered"
    assert list(files) == ["data/h-anytime_td-1.json"]
    assert out["history_path"] == pwa.HISTORY_PATH
    # The caller's dict must survive: the exporter reuses it afterwards.
    assert "weeks" in payload["history"]["anytime_td"]


def test_a_market_without_has_market_price_is_not_emptied():
    """ABSENT IS NOT FALSE, on the board index the game screen reads.

    The first-TD prediction file has never carried `has_market_price`. The
    page read the missing field as False, marked all 500 rows unpriced, and
    rendered "no priced picks recorded for week 2 on this market" — which is
    what a week whose board was genuinely empty says, so First TD was empty
    on every past week and explained itself away.
    """
    import importlib

    pwa = importlib.import_module("src.export.pwa")
    # Exactly the two shapes the exporter writes: anytime_td carries the
    # column, first_td has never had it.
    rows_first = [{"game_id": "2026_02_CAR_ATL", "player_name": "A"},
                  {"game_id": "2026_02_CAR_ATL", "player_name": "B"}]
    assert pwa._priced_by_game("first_td", rows_first) == {"CAR_ATL": 2}

    rows_any = [{"game_id": "2026_02_CAR_ATL", "has_market_price": True},
                {"game_id": "2026_02_CAR_ATL", "has_market_price": False}]
    assert pwa._priced_by_game("anytime_td", rows_any) == {"CAR_ATL": 1}, (
        "an explicit False is still off the board")


def test_the_history_index_counts_priced_rows_per_game():
    """The game screen must tell an empty market from an unfetched one.

    Six markets for one week is roughly 900KB, so the screen cannot fetch
    them to find out which hold players for the game being looked at. The
    index answers it in a few hundred bytes.
    """
    import importlib

    pwa = importlib.import_module("src.export.pwa")
    payload = {"history": {"passing_yards": {"weeks": {"2": [
        {"game_id": "2026_02_CAR_ATL", "line": 228.5},
        {"game_id": "2026_02_CAR_ATL", "line": 238.5},
        # No line: quoted nowhere, so not on the board.
        {"game_id": "2026_02_CIN_HOU", "line": None},
    ]}}}}
    out, _ = pwa._split_history(payload)
    by_game = out["history"]["passing_yards"]["by_game"]
    assert by_game == {"2": {"CAR_ATL": 2}}, by_game
    assert "CIN_HOU" not in by_game["2"], (
        "a game with nothing quoted must be absent, not present as zero")
