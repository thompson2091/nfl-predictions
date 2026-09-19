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
