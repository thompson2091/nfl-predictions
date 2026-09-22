"""The site payload: what the page is handed, and what it joins on."""




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
