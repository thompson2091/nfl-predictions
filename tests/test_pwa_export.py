"""site/v2 — the same board, as something a phone can install.

What is asserted here is the part of an installable app that fails silently.
A manifest with a missing field does not error, it just never offers to
install. A service worker uploaded without its page, or with a cache name that
does not change between builds, serves last week's numbers to someone holding
a phone with four bars — and the page looks identical, so there is nothing to
notice.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def v2_js(tmp_path_factory):
    """The v2 bundle, assembled exactly as `pwa.render` assembles it."""
    from src.export import site as v1, v2js

    js = "\n".join([v1.JS_CORE, v1.JS_SHARED, v1.JS_SLIPVIEW, v1.JS_WEEK,
                    v1.JS_COMBOS, v1.JS_SAVED, v1.JS_LADDER, v1.JS_MODEL,
                    v2js.js()])
    p = tmp_path_factory.mktemp("v2") / "app.js"
    p.write_text(js)
    return p


@pytest.fixture(scope="module")
def payload_v2():
    """The site exporter's fixture, which already covers all six markets."""
    import tests.test_site_export as T

    return T.payload.__wrapped__()


@pytest.fixture(scope="module")
def built() -> dict:
    from src.export.pwa import render

    return render({"season": 2026, "week": 2, "brand": "Pick Six",
                   "built": "2026-09-18T01:19:25+00:00", "markets": [],
                   "results": {}})


def test_it_is_three_files_and_they_are_named_what_a_host_expects(built):
    """The names are not decoration.

    `manifest.webmanifest` is what the `<link rel=manifest>` points at, and
    `sw.js` has to sit beside the page because a worker's scope is the
    directory it was served from. Rename either and the app still loads,
    still works, and never installs or goes offline — which is the whole
    reason the extra two files exist.
    """
    assert set(built) == {"index.html", "manifest.webmanifest", "sw.js"}
    assert 'href="manifest.webmanifest"' in built["index.html"]
    assert "register('sw.js')" in built["index.html"]


def test_nothing_else_has_to_be_uploaded(built):
    """Every icon travels inside the files, not beside them.

    A PWA wants icons at several sizes, and an icon file per size is four more
    things to upload and four more ways to upload two of five. They are drawn
    at build time and inlined — see `src/export/appicon.py` for why they are
    geometric rather than typeset.
    """
    m = json.loads(built["manifest.webmanifest"])
    assert m["icons"], "a manifest with no icons does not install"
    for icon in m["icons"]:
        assert icon["src"].startswith("data:image/png;base64,"), (
            f"{icon['sizes']} {icon['purpose']} is a file to upload")
    assert 'rel="apple-touch-icon" href="data:image/png;base64,' \
        in built["index.html"], "iOS reads this one rather than the manifest"

    # And the page still reaches for nothing over the network.
    #
    # The check is on what FETCHES, not on the string "http" — the favicon is
    # an inline SVG and carries `xmlns=\'http://www.w3.org/2000/svg\'`, which
    # is a namespace name that identifies a standard and is never resolved.
    # A blunter assertion fails on it and teaches you to loosen the rule.
    import re
    page = built["index.html"]
    fetches = re.findall(r'(?:src|href)\s*=\s*["\']https?://[^"\']+', page) \
        + re.findall(r'url\(\s*["\']?https?://[^)]*', page)
    assert not fetches, f"a self-contained page fetching: {fetches[:3]}"
    # The two local files are the exception, and they are named.
    assert page.count('href="manifest.webmanifest"') == 1


def test_the_manifest_carries_what_installation_needs(built):
    """A missing field is not an error, it is an app that never offers.

    `display: standalone` is the point of the exercise: a window with no
    address bar to collapse and no viewport that changes height as you
    scroll — which is the problem v1 spent three attempts working around.
    """
    m = json.loads(built["manifest.webmanifest"])
    assert m["display"] == "standalone"
    assert m["name"] and m["short_name"]
    assert len(m["short_name"]) <= 12, "longer than this is truncated under the icon"
    # Relative, because it will be uploaded into a directory rather than to a
    # domain root. An absolute `/index.html` would leave the scope at the
    # server root and the app would never match its own start URL.
    assert m["start_url"].startswith("./") and m["scope"].startswith("./")
    sizes = {(i["sizes"], i["purpose"]) for i in m["icons"]}
    assert ("192x192", "any") in sizes and ("512x512", "any") in sizes
    assert ("512x512", "maskable") in sizes, (
        "without a maskable icon a launcher crops the square one and takes "
        "the corners off the mark")
    from src.export.pwa import TOKENS
    assert m["background_color"] == TOKENS["Ground and ink"]["bg"], (
        "the colour behind the app before its first paint is the page's own "
        "ground, or launching it is a flash of white")


def test_the_worker_prefers_the_network_because_the_page_is_the_data(built):
    """Cache-first is the usual advice and it is wrong here.

    This page is not a shell that fetches numbers; it IS the numbers. A
    cache-first worker serves last week's board to someone on four bars, and
    the page looks identical — the figures are just wrong, with nothing on
    screen to say so. So the network wins when there is one, and being
    offline is the only way to see a stale board.

    Falsified by answering from `caches.match` before trying `fetch`: the
    order below flips.
    """
    sw = built["sw.js"]
    assert sw.index("await fetch(req)") < sw.index("caches.match(req)"), (
        "the cache must be the fallback, not the answer")
    assert "fresh.ok" in sw, (
        "a 404 cached under the page's own URL is an app that stays broken "
        "until someone clears their browser")
    assert "req.mode === 'navigate'" in sw, (
        "a first open with no network should be the app, not the browser's "
        "offline page")


def test_every_build_gets_its_own_cache(built):
    """A worker installed in week 2 must not still be answering in week 3.

    The cache name carries the build's timestamp, so uploading a new week
    makes a new cache and `activate` deletes the old one. Without it the
    worker is a permanent copy of whichever week it first saw.
    """
    from src.export.pwa import render

    assert "picksix-20260918T011925+0000" in built["sw.js"]
    later = render({"season": 2026, "week": 3, "brand": "Pick Six",
                    "built": "2026-09-25T01:00:00+00:00", "markets": []})
    assert later["sw.js"] != built["sw.js"], (
        "two weeks produced the same worker, so the second never invalidates")
    assert "caches.delete" in built["sw.js"] and "keys.filter" in built["sw.js"]


def test_the_page_works_when_the_worker_cannot_be_registered(built):
    """Three ways registration fails, and none is a reason for a blank page.

    No `serviceWorker` on an old browser, no secure context when the file is
    opened from disk with a double click, and a rejected registration on a
    host that will not serve `sw.js` from that path. The page is
    self-contained either way — the worker adds a second opening, not the
    first one.
    """
    page = built["index.html"]
    assert "'serviceWorker' in navigator" in page
    assert "window.isSecureContext" in page, (
        "opened from disk there is no secure context, and registering throws")
    assert ".catch(() => {})" in page, "a rejected registration is not fatal"


def test_the_window_has_no_chrome_so_the_page_takes_the_whole_screen(built):
    """`viewport-fit=cover` is what makes the safe-area insets mean anything.

    Without it the page is letterboxed inside the safe area and an installed
    app has a white bar where the notch is. With it the page owns the whole
    screen, including the parts the system draws over — so every edge that
    had padding needs the inset added to it.
    """
    from src.export.pwa import APP_CSS

    # The meta tag, not the string. The comment above it in the shell
    # explains what `viewport-fit=cover` is for and contains those words, so a
    # search of the whole page passes with the tag deleted.
    assert 'content="width=device-width, initial-scale=1, viewport-fit=cover"' \
        in built["index.html"], "the tag itself, not the note about it"
    for edge in ("safe-area-inset-top", "safe-area-inset-bottom",
                 "safe-area-inset-left", "safe-area-inset-right"):
        assert edge in APP_CSS, f"{edge} is never accounted for"
    # Added to the padding that was there, not replacing it, or the app is
    # flush to the notch on a phone and has no gutter at all on a desktop.
    assert "calc(10px + env(safe-area-inset-top))" in APP_CSS
    assert "overscroll-behavior:none" in APP_CSS.replace(" ", ""), (
        "dragging past the end of an installed app shows the nothing behind it")


def test_v2_is_a_skin_and_a_shell_over_v1s_behaviour(built):
    """156KB of page logic is not forked, it is imported.

    Every board, filter and parlay calculation is `site.JS_*`. A copy would
    drift inside a week and would take the 635 tests that cover it out of the
    picture for v2 — which is the part of this project that should not have to
    be earned twice.
    """
    from src.export import pwa
    from src.export import site as v1

    src = (REPO / "src" / "export" / "pwa.py").read_text()
    assert "from src.export import site as v1" in src
    assert "JS_WEEK" in src and "function pageWeek" not in src, (
        "v2 names v1's modules; it does not carry its own copy of them")
    # The same script, byte for byte.
    assert v1.JS_WEEK in built["index.html"]
    assert v1.JS_COMBOS in built["index.html"]

    # And the tokens are v2's own, exactly once.
    css = pwa.tokens_css() + pwa.component_css() + pwa.APP_CSS
    assert css.count(":root{") == 1, (
        "v1's token block must come off the front, or its colours override "
        "v2's from further down the cascade")
    assert css.count("--bg:#F5F3EE") == 1


def test_the_token_layer_is_wide_enough_to_be_worth_having(built):
    """v1 has eleven custom properties and they are all colour.

    Every spacing, radius and type size is typed literally into 33KB of
    component rules, so a design change is a search rather than an edit. The
    point of this layer is that adopting a design system is a change to
    `TOKENS` — so it has to carry the things a design system actually
    specifies.
    """
    from src.export.pwa import TOKENS

    for group in ("Ground and ink", "Meaning", "Type", "Space", "Radius",
                  "Elevation", "Layout"):
        assert group in TOKENS and TOKENS[group], f"{group} is not tokenised"
    assert len([k for g in TOKENS.values() for k in g]) > 40, (
        "a token layer this thin is a palette with extra steps")
    # A scale, not a handful of numbers that happen to be nearby.
    assert list(TOKENS["Space"]) == [f"s{i}" for i in range(1, 9)]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_apps_script_parses(built, tmp_path):
    """A syntax error here publishes a blank page with one console message."""
    page = built["index.html"]
    start = page.rindex("<script>", 0, page.index("navigator.serviceWorker")) + len("<script>")
    js = page[page.index("<script>", page.index("</script>", page.index("id=\"payload\"")))+8:]
    js = js[:js.index("</script>")]
    p = tmp_path / "app.js"
    p.write_text(js)
    r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_the_build_script_writes_all_three_or_says_which(tmp_path):
    """Two of the three is an app that loads and never works offline."""
    mk = (REPO / "scripts" / "51_export_app.py").read_text()
    assert "--out" in mk and "site/v2" in mk
    assert "upload all three" in mk, (
        "the recipe has to say that the worker travels with its page")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_every_v2_screen_renders(payload_v2, v2_js, tmp_path):
    """The failure mode of a generated app is a blank screen and one console line.

    `node --check` proves the syntax and nothing else — a bad reference parses
    fine and throws on load. So every board, every sheet and every screen is
    actually built, against a payload carrying all six markets.
    """
    p = tmp_path / "payload.json"
    p.write_text(json.dumps(payload_v2))
    r = subprocess.run(["node", str(REPO / "tests" / "js" / "v2app.js"),
                        str(p), str(v2_js)],
                       capture_output=True, text=True, cwd=str(REPO))
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")


def test_v2_replaces_the_views_and_keeps_every_calculation():
    """106KB of views out, 44KB of calculation in — and not one number moved.

    Every probability, parlay, combination and settlement on screen is v1's:
    `rowsFor`, `applyFilters`, `slipMath`, `combosOf`, `portfolio`, `settle`,
    `betProb`, `ev100`, the storage layer. What v2 writes is the DOM.

    Falsified by reimplementing any of them here: the names below would stop
    coming from `site` and the bundle would carry two answers to the same
    question, which is how the touchdown shortlist once disagreed with its own
    board about the same player.
    """
    from src.export import v2js

    src = v2js.js()
    for fn in ("function rowsFor", "function slipMath", "function portfolio",
               "function combosOf", "function settle", "function applyFilters",
               "function ev100", "function betProb"):
        assert fn not in src, f"{fn} is v1's and must not be rewritten here"
    # And the three v1 owns that v2 must take over, declared exactly once.
    for fn in ("function render(", "function route(", "function go("):
        assert src.count(fn) == 1, f"{fn} must be declared once in the v2 layer"


def test_typing_never_replaces_the_field_being_typed_into():
    """iOS scrolls and scales to a newly focused element, and keeps the scale.

    The board re-rendered the whole screen on every keystroke and then put
    focus back on the new input. On a desktop that is invisible; on a phone
    each keystroke is a fresh focus on a fresh node, so the page zoomed in and
    stayed zoomed after the keyboard went away.

    Every text field now patches the part of the screen it changes and leaves
    itself alone. Falsified by calling `render` from the input handler: the
    assertion below fails, and so does the harness's check that the search box
    is outside the patched box.
    """
    from src.export import v2js

    src = v2js.js()
    handler = src[src.index("document.addEventListener('input'"):]
    handler = handler[:handler.index("\n  });")]
    assert "render(" not in handler, (
        "a re-render replaces the focused input, which is the bug")
    for patcher in ("patchBoard()", "patchTotals()", "patchLadder()"):
        assert patcher in handler, f"{patcher} is how that field updates instead"
    # And the fields themselves are large enough not to trigger the other,
    # better-known zoom.
    from src.export.v2css import css
    import re
    for rule in re.finditer(r'([^{}]*\binput\b[^{}]*)\{([^}]*)\}', css()):
        size = re.search(r'font-size:\s*(\d+)px', rule.group(2))
        if size:
            assert int(size.group(1)) >= 16, (
                f"{rule.group(1).strip()} is {size.group(1)}px; iOS zooms into "
                f"anything under 16")


def test_the_slip_bar_can_be_swiped_away_on_a_phone_and_only_there():
    """The way to put a thing down should not be to open it first.

    A touch gesture, by construction: a mouse sends none, and above 900px the
    button is hidden and the transform neutralised, so this is inert on a
    desktop rather than conditional on one.
    """
    from src.export import v2css, v2js

    src, c = v2js.js(), v2css.css()
    assert "addEventListener('touchstart'" in src
    assert "addEventListener('touchmove'" in src
    assert "addEventListener('touchend'" in src
    assert "Math.abs(dy) > Math.abs(dx)" in src, (
        "a vertical drag is the page scrolling, and taking it would make the "
        "board impossible to scroll past the bar")
    assert "SWIPE_TAKE" in src, (
        "past halfway it settles open, short of it it springs back — or a "
        "small accidental drag leaves a delete button showing")
    flat = c.replace(" ", "").replace("\n", "")
    assert ".slipwrap[data-swipe=open].slipbar{transform:translateX(-112px)}" in flat
    assert ".slipwrap[data-swipe=dragging].slipbar{transition:none}" in flat, (
        "with a finger on it there is no transition, or the bar lags the thumb")
    wide = c[c.index("@media (min-width:900px)"):]
    assert ".slipdel{display:none}" in wide.replace(" ", ""), (
        "there is no swiping with a mouse")


def test_the_count_line_is_a_component():
    """"147 of 530 shown" was a bare div inheriting the body's type.

    Which put the one line on the screen that is furniture at the weight of
    the rows it was counting. It is the same 10px uppercase the metric labels
    use, because it is the same kind of thing: a label on a number.
    """
    from src.export import v2css

    flat = v2css.css().replace(" ", "")
    assert ".count{" in flat
    block = flat[flat.index(".count{"):]
    block = block[:block.index("}")]
    for prop in ("text-transform:uppercase", "color:var(--ink-faint)",
                 "text-align:center", "font-variant-numeric:tabular-nums"):
        assert prop in block, f"the count line needs {prop}"


def test_a_wider_screen_gets_more_board_and_not_more_margin():
    """Mobile first, and this is the half that reads as "also works here".

    The column grows in three steps and the row stops hiding two of its six
    metrics once there is room. Rendered at every width and hidden by CSS
    rather than decided in JavaScript: a resize does not re-render, so a
    window someone had just widened would keep a phone's four columns.
    """
    from src.export import v2css, v2js

    c = v2css.css()
    for width, measure in (("700px", "760px"), ("1000px", "940px"),
                           ("1280px", "1100px")):
        block = c[c.index("@media (min-width:" + width + ")"):]
        block = block[:block.index("}\n}") + 1]
        assert "max-width:" + measure in block.replace(" ", ""), (
            f"at {width} the column should reach {measure}")
    assert "metric--wide" in v2js.js(), "the extra metrics have to be drawn"
    assert ".metric--wide{display:none}" in c.replace(" ", ""), (
        "and hidden where there is no room, by the stylesheet")


def test_saved_parlays_are_a_destination_not_a_section():
    """They have a life after you build them.

    A saved slip goes pending, then won or lost, and the record at the top is
    something you come back to rather than glance at on the way somewhere
    else. Folding it into the Slip screen would have put a history under a
    working draft.

    Six tabs is the cost, and it is paid in the stylesheet: `min-width:0` is
    what lets a flex item be narrower than its label, and without it the sixth
    tab is off the edge of a 320px screen.
    """
    from src.export import v2css, v2js

    src, c = v2js.js(), v2css.css()
    assert "['saved', 'Saved']" in src, "Saved is a tab"
    assert src.count("case 'saved': return vSaved()") == 1
    assert "function dropParlay" in src, "and you can get rid of one"
    # Only this week's list is ours to write; last week's is read from its own
    # key and shown for reference.
    drop = src[src.index("function dropParlay"):]
    assert "filter(p => !p.last)" in drop[:drop.index("\n}")], (
        "deleting must not write the key the week rollover owns")
    assert ".tab{min-width:0" in c.replace(" ", ""), (
        "six tabs overflow the bar without it")


def test_a_notice_is_said_once(payload_v2):
    """`loadParlay` sets one when a saved slip has legs the board has dropped.

    That is a fact about the load rather than a state of the page, so it is
    cleared as it is drawn — otherwise it reappears on every render until
    something else happens to replace it.
    """
    from src.export import v2js

    src = v2js.js()
    r = src[src.index("function render("):]
    r = r[:r.index("\nfunction ")]
    assert "S.notice = null;" in r, "drawn, then forgotten"
    assert "banner banner--warn" in r


def test_an_empty_slip_has_no_bar_and_no_infinity():
    """`every` over nothing is true, which made an empty slip fully priced.

    Two bugs on one line. `slipMath` answers an empty slip with a real object
    rather than null — zero legs, an all-hit of 1 — so testing it for
    truthiness kept the bar on screen with nothing in it. Then `allPriced([])`
    said the nothing was priced, `parlayDec([])` handed back a decimal of 1,
    and `decToAm(1)` is -100/0: the bar read "-Infinity".

    Falsified by restoring either half.
    """
    from src.export import v2js

    src = v2js.js()
    assert "if (!m.legs.length || S.route === 'slip') return '';" in src, (
        "the legs are the question, not whether slipMath answered")
    assert "legs.length > 0 && legs.every(l => has(l.dec))" in src, (
        "all of nothing is not priced; it is nothing")


def test_a_saved_slip_shows_what_the_slip_showed():
    """A saved slip you cannot read is a name and a date.

    The same three figures the Slip screen leads with, and the same payout
    curve under them. `dec` is computed from the legs rather than read off the
    record: `saveSlip` never writes one, so v1's own card calls
    `decToAm(undefined)` — and because `has(NaN)` is false, `american` returns
    an empty string. The price is not wrong there, it is absent, which is why
    looking for the word "NaN" would not have found it.
    """
    from src.export import site as v1, v2js

    saved = v1.JS_SLIPVIEW[v1.JS_SLIPVIEW.index("function saveSlip"):]
    saved = saved[:saved.index("\n}")]
    # The parlay's own field, at the object's own indent. Each LEG carries a
    # `dec:` and always has — that is where the price actually survives, and
    # it is what v2 reads.
    assert "\n    dec:" not in saved, (
        "if saveSlip ever starts storing one, read it instead of deriving it")
    assert "dec: l.dec" in saved, "the legs keep theirs, and that is the source"

    src = v2js.js()
    card = src[src.index("function vParlay"):]
    card = card[:card.index("\nfunction ")]
    assert "parlayDec(p.legs)" in card, "derived from the legs that were saved"
    assert "p.dec" not in card, "never from a field that was never written"
    # Net is linear in the stake, so the stored curve can be re-read at any
    # other one — against the stake that produced it, and no other.
    assert "p.rowStake" in card and "scaleRows(p.rows, ratio)" in card


def test_the_breakdown_is_headed_once():
    """The table brings its own headings.

    A `secthead` above them said the same three words again, one line higher
    and in a different typeface.
    """
    from src.export import v2js

    src = v2js.js()
    assert "If this many land" not in src
    assert src.count("<th>Legs in</th>") == 1


def test_a_sheet_that_is_taller_than_the_sheet_scrolls_rather_than_clipping():
    """A flex item will not shrink below its content unless it is told to.

    `.sheet` is a flex column with a max-height, so a body taller than it did
    not scroll — it overflowed, and was clipped. On a player's detail that is
    the two buttons at the bottom, cut in half.

    Falsified by removing `min-height:0`: nothing errors, nothing logs, and
    the buttons are half there.
    """
    from src.export import v2css

    flat = v2css.css().replace(" ", "").replace("\n", "")
    body = flat[flat.rindex(".sheet__body{"):]
    body = body[:body.index("}")]
    assert "min-height:0" in body, "or it overflows instead of scrolling"
    assert "flex:1" in body
    assert "env(safe-area-inset-bottom)" in body, (
        "the home indicator takes the last 34px of an installed app")


def test_ev_is_on_the_board_and_open_is_the_one_held_back():
    """Edge is the disagreement; EV is what the disagreement is worth.

    Which is the question the row is read for, so it earns a place on the
    phone. Five fit a 390px screen once the gap comes down to 10.
    """
    from src.export import v2css, v2js

    row = v2js.js()
    row = row[row.index("function vRow("):]
    row = row[:row.index("\nconst met")]
    assert "met('EV $100', has(ev) ? money(ev) : '—',\n        has(ev) ? (ev >= 0 ? 'v-good' : 'v-bad') : 'v-none')," in row, (
        "EV must not carry the `wide` flag")
    assert row.index("met('Edge'") < row.index("met('EV $100'") < row.index("met('Open'")
    assert "met('Open', has(r.openOdds) ? american(r.openOdds) : '—', '', false, true)" in row

    # Five, and the same five whatever the market. A line board used to put
    # the projection in Model's place, so the number saying what we thought on
    # our own was absent from four of the six markets. Six does not fit: they
    # need 269px of the 254 a 390px screen leaves a row's middle, where five
    # need 218 — so the projection moved up beside the line instead, which is
    # the comparison it was always meant to be read against.
    assert "met('Proj'" not in row, "the projection is a pill, not a metric"
    assert row.count("met('") == 6, "five narrow and one wide"
    assert "kind === 'ou' && (has(r.line) || has(r.proj))" in row, (
        "and the pill appears for either of them")
    narrow = v2css.css()
    narrow = narrow[narrow.index("@media (max-width:480px)"):]
    assert "gap:10px" in narrow[:200]


def test_every_control_the_views_draw_can_actually_be_clicked():
    """Six buttons did nothing at all, and nothing said so.

    The delegated handler starts with `closest` over a list of attributes, and
    that list was a string literal that six controls were added after: the
    Combinations pool switch and its Load, the Saved filters, Delete and Load,
    and the Model page's feature toggle. `closest` returned null, the handler
    bailed on its first line, and the buttons were inert — silently, because a
    button that is never reached throws nothing.

    The list is a constant now and this holds it against what the views emit.
    Falsified by drawing a `data-` control and not listing it, which is
    precisely how the bug arrived.
    """
    import re

    from src.export import v2js

    src = v2js.js()
    listed = set(re.findall(r"'([a-z0-9]+)'", src[src.index("const CLICKS = ["):
                                                 src.index("const CLICK_SEL")]))
    emitted = set(re.findall(r"data-([a-z0-9]+)=", src))
    # An input rather than a button: the input listener reads this one, and a
    # click on it must not be swallowed by the click handler.
    emitted.discard("pstake")
    missing = sorted(emitted - listed)
    assert not missing, f"drawn but unreachable: {['data-' + m for m in missing]}"
    assert "e.target.closest(CLICK_SEL)" in src, (
        "built from the list, or the list is decoration")


def test_the_tab_bar_is_ruled_off_from_what_sits_on_it():
    """Two bars sharing a background read as one tall footer.

    Both carry `--shadow-bar`, a 10%-opacity hairline — enough to lift a
    single bar off a scrolling list, not enough to separate two stacked on
    each other. The tab bar takes the separator the rest of the design uses
    between things that are genuinely different, and it replaces the shadow
    rather than joining it: two lines a pixel apart is a seam.
    """
    from src.export import v2css

    # The exact declaration. `rindex` finds the desktop override, where the
    # bar becomes a row of pills in the header and has no border at all.
    flat = v2css.css().replace(" ", "").replace("\n", "")
    assert ".tabbar{box-shadow:none;border-top:var(--hairline)solidvar(--separator)}" \
        in flat, "the shadow is replaced, not joined — two lines a pixel apart is a seam"


def test_the_ladder_is_headed_in_words_not_sentences():
    """"If every rung wins" is a caption, not a label.

    A keystat label is 10px uppercase with .07em tracking; it holds a word.
    """
    from src.export import v2js

    src = v2js.js()
    assert "keystat('Payout'" in src and "keystat('Chance'" in src
    assert "If every rung wins" not in src and "Chance of the run" not in src


def test_the_stake_moves_everything_it_decides():
    """The totals were patched and the breakdown was not.

    Expected value and every Net in the curve are functions of the stake, so
    changing it left the slip disagreeing with its own table until something
    else forced a render. `slipMath` re-runs the whole portfolio from
    `S.slip.stake`, so both come back correct from one call — what they
    cannot do is come back at all unless each sits somewhere it can be
    replaced without touching the field being typed into.

    Falsified by taking the breakdown out of its box: it stops being
    patchable and the harness catches a curve that does not move.
    """
    from src.export import v2js

    src = v2js.js()
    assert 'id="slipbrk"' in src, "the curve needs a box of its own"
    patch = src[src.index("function patchTotals()"):]
    patch = patch[:patch.index("\nfunction ")]
    assert "getElementById('sliptotals')" in patch
    assert "getElementById('slipbrk')" in patch, (
        "or the Net column keeps the stake it was first drawn at")
    assert "render(" not in patch, (
        "patching is the point; a render would replace the stake field")


def test_a_tab_bar_keeps_the_place_each_tab_was_left_at():
    """Five links you follow once, or five places you keep.

    Coming back to the board a hundred rows down is the whole difference.
    `route` records the outgoing tab's position before it changes screens and
    restores the incoming one's after it renders — `render` starts a screen at
    the top, so the order matters.

    Tapping the tab you are already on is the one time a remembered position
    is not what you want: that is "take me to the top", which is what every
    tab bar does.
    """
    from src.export import v2js

    src = v2js.js()
    r = src[src.index("function route() {"):]
    r = r[:r.index("\nfunction ")]
    assert "SCROLLS[prev] = leaving.scrollTop" in r, "record before leaving"
    assert "s.scrollTop = SCROLLS[S.route] || 0" in r, "restore after rendering"
    assert r.index("SCROLLS[prev]") < r.index("render()") < r.index("SCROLLS[S.route]")
    assert "if (d.tab === S.route)" in src, "the same tab means the top"


def test_clearing_the_slip_goes_back_to_wherever_it_was_opened_from():
    """Right from the board, wrong from Combinations.

    You loaded a slip there to look at it, and emptying it should put you back
    in the list you loaded it from rather than on a board you were not
    reading. One hop is enough: `BACK` is set when the slip is arrived at from
    somewhere else.

    Falsified by sending it to the board again: the harness loads a
    combination, clears it, and finds itself somewhere it did not come from.
    """
    from src.export import v2js

    src = v2js.js()
    assert "case 'clearslip': closeSwipe(); clearSlip(); go(BACK); break;" in src
    assert "if (S.route === 'slip' && prev !== 'slip') BACK = prev;" in src, (
        "and arriving at the slip FROM the slip must not overwrite it")


def test_the_shell_carries_a_box_for_the_receipt():
    """Outside `#scroll`, because a render replaces everything inside it.

    Saving was the only control in the app with nothing to show for it, and a
    receipt the next keystroke erases is worse than none. Falsified by putting
    the box in the screen: `render` rewrites `scroll.innerHTML` on every tab
    change, keystroke and toggle, and the message would go with it.
    """
    from src.export.pwa import render

    built = render({"season": 2026, "week": 2, "brand": "Pick Six",
                    "built": "2026-09-18T01:19:25+00:00", "markets": [],
                    "results": {}})
    page = built["index.html"]
    assert 'id="toast"' in page, "no box to write the receipt into"
    # Announced to a screen reader as a status rather than read as a heading:
    # it is something that just happened, not part of the page's structure.
    assert 'role="status"' in page and 'aria-live="polite"' in page
    # In the shell beside the bars, not in the scrolling screen.
    assert page.index('id="tabbar"') < page.index('id="toast"')
    assert page.index('id="toast"') < page.index('id="scrim"'), (
        "the sheet and its scrim must stack over the toast, not under it")


def test_the_toast_is_written_without_a_render():
    """The same rule every field on the slip follows, for the same reason.

    A render replaces the input being typed into, and iOS answers a fresh
    focus by scrolling and scaling to it. Falsified by calling `render` from
    `toast`: the name would appear between the function and its brace.
    """
    from src.export import v2css, v2js

    src = v2js.js()
    body = src[src.index("function toast(msg) {"):]
    body = body[:body.index("\nfunction ")]
    assert "render(" not in body, "a receipt must not redraw the screen"
    assert "getElementById('toast')" in body
    # Saying a second thing restarts the clock rather than letting the first
    # message's timer cut the second one short.
    assert "clearTimeout(TOASTING)" in body

    css = v2css.css()
    assert ".toast{" in css and ".toast--open{" in css
    # Under the scrim, so an open sheet covers it.
    assert "z-index:19" in css


def test_saving_files_the_slip_once_and_says_which_it_did():
    """`saveSlip` is v1's and appends whatever it is handed.

    So pressing Save twice filed the same parlay twice and the list filled
    with copies of one bet. What makes two slips the same is the market and
    the legs — not the stake, which is a size rather than a selection and is
    editable on the card afterwards.

    Falsified by keying on the whole slip: the same legs at a different stake
    would file a second copy of one opinion.
    """
    from src.export import v2js

    src = v2js.js()
    assert "case 'saveslip': saveSlipOnce(); break;" in src
    body = src[src.index("function saveSlipOnce() {"):]
    body = body[:body.index("\nfunction ")]
    assert "slipKey(S.slip.market, S.slip.legs)" in body
    assert "if (!already) saveSlip();" in body, "a second press must not append"
    # Filed, so the slip is put away and you are taken to where it went.
    assert "clearSlip();" in body and "go('saved');" in body
    assert body.index("clearSlip();") < body.index("go('saved');"), (
        "`clearSlip` renders, so the hop comes last or its render lands on top"
    )
    # The stake is not part of what makes a slip that slip.
    key = src[src.index("function slipKey("):]
    key = key[:key.index("\n}")]
    assert "stake" not in key


def test_clearing_from_the_bar_does_not_move_you():
    """The slip screen's Clear goes back to where the slip was filled.

    The bar is on every tab but the slip's own, so it has nowhere to go back
    from — and clearing a slip while reading Saved moved you to the board,
    which reads as the button having done something else entirely.

    Falsified by giving the bar the screen's action again: the two would share
    `go(BACK)` and the hop would come back.
    """
    from src.export import v2js

    src = v2js.js()
    assert 'data-act="clearbar"' in src, "the bar needs its own action"
    assert "case 'clearbar': closeSwipe(); clearSlip(); break;" in src
    assert "go(BACK)" not in src[src.index("case 'clearbar':"):
                                 src.index("case 'saveslip':")]


def test_saved_cards_start_collapsed_and_say_nothing_about_settling():
    """A saved list is read by name and week.

    Six cards each three screens tall is a list you scroll rather than one you
    read, so a card's legs, totals and payout curve are opened when that card
    is the one being asked about. The running record over the list and the
    Pending/Won/Lost filters under it both reported settling, which is not
    what this tab is for.
    """
    from src.export import v2css, v2js

    src = v2js.js()
    assert "if (!open) return h + '</div></div>';" in src, "nothing collapses"
    assert "if (d.pcard) { S.pcard[d.pcard] = !S.pcard[d.pcard];" in src
    assert "'pcard'" in src[src.index("const CLICKS = "):
                            src.index("const CLICK_SEL")]

    saved = src[src.index("function vSaved() {"):]
    saved = saved[:saved.index("\nfunction ")]
    assert "keystat('Settled'" not in saved, "the scoreboard is back"
    assert "data-sf=" not in saved, "the filters are back"
    assert "savedAt" in saved, "newest first is what saving into here needs"

    card = src[src.index("function vParlay(p) {"):]
    card = card[:card.index("\nfunction ")]
    assert "esc(p.status)" not in card, "the status pill is back on the card"

    assert ".pcard{" in v2css.css()
