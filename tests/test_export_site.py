"""The site payload: what the page is handed, and what it joins on."""

from pathlib import Path




def test_shortlist_and_veto_names_match_the_board_they_filter():
    """A defense on either list must not silently drop out of its view.

    The board qualifies "DEF/ST" by team so 32 defenses do not share one leg
    id. Shortlist and veto rows are matched to the board BY NAME, so leaving
    them bare made a vetoed defense match nothing — Fades came back one row
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


def test_one_capture_cannot_be_filed_as_both_ends_of_a_week():
    """Writing the same fetch under both labels invents a close that is not one.

    2026 week 4 archived a 7-book capture twice — identical in every field but
    the label — nine days before kickoff. Nothing errored. `matchups.board`
    defaults to the close, so it priced the week off that instead of off the
    21-book open captured a week later, dropped every outcome quoted by fewer
    than MIN_BOOKS, and left the moneyline standing on one game of sixteen.
    """
    import polars as pl

    from src.ingest.game_lines import append_snapshot

    import tempfile
    rows = [{"captured_at": "2026-09-22T20:45:36Z", "game_id": "PIT_CLE",
             "home_team": "CLE", "away_team": "PIT", "bookmaker": "fanduel",
             "market": "h2h", "outcome": "PIT", "outcome_raw": "Pittsburgh",
             "point": None, "odds": -110, "implied_prob": 0.5238}]
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "game_lines.parquet"
        append_snapshot(rows, season=2026, week=4, snapshot="open", path=p)
        append_snapshot(rows, season=2026, week=4, snapshot="close", path=p)
        d = pl.read_parquet(p)

    assert d.height == 1, "the second label was written anyway"
    assert d["snapshot"].to_list() == ["open"], "the first label did not stand"


def test_a_repeat_capture_under_its_own_label_still_appends():
    """The guard is about the OTHER end, not about de-duplicating the archive.

    A price standing for three hours across three captures is three
    observations, and how long a price stood is only answerable because they
    are all on disk.
    """
    import polars as pl

    from src.ingest.game_lines import append_snapshot

    import tempfile
    def _row(at):
        return [{"captured_at": at, "game_id": "PIT_CLE", "home_team": "CLE",
                 "away_team": "PIT", "bookmaker": "fanduel", "market": "h2h",
                 "outcome": "PIT", "outcome_raw": "Pittsburgh", "point": None,
                 "odds": -110, "implied_prob": 0.5238}]

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "game_lines.parquet"
        append_snapshot(_row("2026-09-29T16:00:10Z"), season=2026, week=4,
                        snapshot="open", path=p)
        append_snapshot(_row("2026-09-30T16:00:12Z"), season=2026, week=4,
                        snapshot="open", path=p)
        d = pl.read_parquet(p)

    assert d.height == 2, "a genuine second open capture was refused"


def test_a_week_with_no_usable_close_is_priced_off_its_open():
    """A stale close must not decide which prices the games page shows.

    `board` defaults to the close and drops outcomes below MIN_BOOKS, and
    `v3Games` hides its whole book/model/adjusted/gap strip when the book
    number is null — so a thin close showed fifteen of sixteen games with no
    numbers at all while the model had an opinion on every one of them.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "se", Path(__file__).resolve().parents[1] / "scripts/47_export_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    src = Path(__file__).resolve().parents[1] / "scripts/47_export_site.py"
    text = src.read_text()
    assert "stale_close, gap_h = _line_ends(season, week)" in text, \
        "the ends are read after the board is built again"
    assert 'board(season, week, snapshot=priced_from)' in text, \
        "the board no longer takes the end it was told to use"
    i_ends = text.index("stale_close, gap_h = _line_ends(season, week)")
    i_board = text.index("b = board(season, week, snapshot=priced_from)")
    assert i_ends < i_board, "which end to price off is decided too late"


def _se():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "se", Path(__file__).resolve().parents[1] / "scripts/47_export_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_streak_flags_refuse_to_be_empty_for_the_wrong_reason():
    """An empty map and "nobody is on a streak" are the same answer.

    They are not the same thing, and that is how this shipped broken.
    `_history_block` ran BEFORE `payload["season"]` and `payload["week"]`
    were written, so reading them back off the payload gave None, the flags
    came back `{}`, and 20261007.v3 went live with the board's Streaks
    filter silently showing nobody. Nothing failed, because an empty answer
    is a legal one.

    There is no case where this runs without a week to be as-of, so it
    raises.
    """
    import pytest

    se = _se()
    for season, week in ((None, 5), (2026, None), (None, None)):
        with pytest.raises(ValueError):
            se._streak_flags({}, season, week)


def test_the_history_block_is_given_the_week_it_is_as_of():
    """The call site, because that is where the bug was.

    Every other block on that list already takes `s` and `w` as arguments;
    this one read them off a payload they had not been written to yet.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "scripts/47_export_site.py").read_text()
    assert "_history_block(payload, s, w)" in src, (
        "the history block must be handed the season and week, not left to "
        "read them off a payload they are written to later")


def test_saved_legs_settle_per_game_and_skip_players_who_did_not_play(tmp_path, monkeypatch):
    """106 WAS @ SF legs read "miss" while the game was being played, and a
    player with no snap read "miss" where a book voids."""
    import importlib.util
    from pathlib import Path as _P

    import polars as pl

    spec = importlib.util.spec_from_file_location(
        "e47", _P(__file__).resolve().parents[1] / "scripts" / "47_export_site.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    proc = tmp_path / "anytime_td"
    proc.mkdir()
    (tmp_path / "first_td").mkdir()
    pl.DataFrame({"season": [2026] * 4, "week": [6] * 4,
                  "game_id": ["2026_06_A_B", "2026_06_A_B", "2026_06_A_B", "2026_06_C_D"],
                  "player_id": ["scorer", "blank", "scratch", "monday"],
                  "player_name": ["Scorer", "Blank", "Scratch", "Monday"],
                  "team": ["A", "A", "A", "C"]}).write_parquet(proc / "features.parquet")
    pl.DataFrame({"season": [2026], "week": [6], "td_player_id": ["scorer"]}
                 ).write_parquet(proc / "tds_anytime_td.parquet")
    monkeypatch.setattr(m, "get_path", lambda *a: tmp_path / a[1] if len(a) > 1 else tmp_path)
    monkeypatch.setattr("src.evaluation.tracked_rules.unfinished",
                        lambda season, week: ({"2026_06_C_D"}, {"C @ D"}))
    monkeypatch.setattr("src.evaluation.safe_legs.game_logs", lambda: pl.DataFrame(
        {"season": [2026, 2026, 2026], "week": [6, 6, 6],
         "player_id": ["scorer", "blank", "monday"]}))
    monkeypatch.setattr(m, "_ou_results", lambda season, week: {})
    got = {k: v for k, v in m.results(2026, 6).items() if k.startswith("6|any|")}
    assert got == {"6|any|Scorer (A)": "hit", "6|any|Blank (A)": "miss"} or got == {
        "6|any|Scorer": "hit", "6|any|Blank": "miss"}, got


def test_a_started_game_shows_the_touchdown_board_it_kicked_off_with(monkeypatch):
    """Kyren Williams read 100% after kickoff; frozen before it, 86%."""
    import importlib.util
    from pathlib import Path as _P

    spec = importlib.util.spec_from_file_location(
        "e47b", _P(__file__).resolve().parents[1] / "scripts" / "47_export_site.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    from src.export import prediction_freeze as PF

    monkeypatch.setattr(PF, "started_games", lambda s, w: {"2026_06_ARI_LA"})
    monkeypatch.setattr(PF, "missing", lambda s, w, k: [])
    monkeypatch.setattr(PF, "frozen", lambda s, w, k: {"2026_06_ARI_LA": [
        {"player_name": "Kyren Williams", "team": "LA", "probability": 0.86,
         "prob_model": 0.97, "book": 0.51, "odds": -188.0, "has_market_price": True}]})
    rows = [{"player": "Kyren Williams", "team": "LA", "game_id": "2026_06_ARI_LA",
             "ours": 1.0, "model_only": 1.0, "book": None, "priced": False, "read": "x",
             "best": "+260", "best_book": "betmgm", "n_best": 1},
            {"player": "Later Man", "team": "SF", "game_id": "2026_06_WAS_SF",
             "ours": 0.3, "model_only": 0.3, "book": 0.25}]
    m._serve_frozen_td([{"key": "anytime_td", "players": rows}], 2026, 6)
    k = rows[0]
    assert (k["ours"], k["model_only"], k["book"], k["priced"]) == (0.86, 0.97, 0.51, True)
    assert k["odds"] == "-188" and k["diff"] == 35.0 and k["read"] is None
    assert rows[1]["ours"] == 0.3, "a game still to come was touched"
    # A best price is today's quote; beside a frozen price it can sit shorter
    # than "posted", and after kickoff it cannot be taken anyway.
    assert (k["best"], k["best_book"], k["n_best"]) == (None, None, None)


def test_a_started_games_defense_matches_its_frozen_row(monkeypatch):
    """The board names it "LA DEF/ST", the freeze "DEF/ST": 28 of 28 missed."""
    import importlib.util
    from pathlib import Path as _P

    spec = importlib.util.spec_from_file_location(
        "e47c", _P(__file__).resolve().parents[1] / "scripts" / "47_export_site.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    from src.export import prediction_freeze as PF

    monkeypatch.setattr(PF, "started_games", lambda s, w: {"2026_06_ARI_LA"})
    monkeypatch.setattr(PF, "missing", lambda s, w, k: [])
    monkeypatch.setattr(PF, "frozen", lambda s, w, k: {"2026_06_ARI_LA": [
        {"player_name": "DEF/ST", "team": "LA", "probability": 0.1137,
         "prob_model": 0.1137, "has_market_price": False}]})
    rows = [{"player": m.qualified_name("DEF/ST", "LA"), "team": "LA",
             "game_id": "2026_06_ARI_LA", "ours": 0.1485, "model_only": 0.1485}]
    m._serve_frozen_td([{"key": "anytime_td", "players": rows}], 2026, 6)
    assert rows[0]["ours"] == 0.1137 and rows[0].get("frozen") is True


def test_a_cards_main_line_is_where_the_books_stand_not_where_they_stood():
    """KC @ MIA 2026 week 3 carded 11.5, Tuesday's line, against a 9.5 close."""
    import polars as pl
    from src.evaluation import matchups as M

    b = M.board(2026, 3)
    if b.is_empty():
        import pytest
        pytest.skip("no 2026 week 3 odds archive")
    s = b.filter(pl.col("game_id").str.contains("KC") & pl.col("game_id").str.contains("MIA")
                 & (pl.col("market") == "spreads") & (pl.col("outcome") == "MIA"))
    by_books = s.sort("n_books", descending=True)["point"][0]
    by_now = s.sort(["n_current", "n_books"], descending=True)["point"][0]
    assert by_books == 11.5, "the archive changed; re-measure this case"
    assert by_now == 9.5
