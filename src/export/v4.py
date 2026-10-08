"""site/v4 — the shell, and what goes in it.

Three files and a `data/` folder, uploaded together, exactly as v2 and v3.
What differs from v3 is the look and the navigation: see `v4css` for the token
swap that makes v3's component rules render in Hashmark, and `v4js` for the
four builders v4 redeclares.

**THE PAYLOAD IS UNCHANGED AND UNFORKED.** `scripts/47_export_site.py:build`
is what v2, v3 and v4 all read. That is not laziness — it is the one thing
stopping two apps serving different numbers for the same player, which is a
failure mode this project has already paid for twice (the shortlist mapped
from its own payload entry and disagreed with the board about the same man;
the fit asked the archive while serving asked the cache).

**v1's AND v3's JavaScript BOTH COME ACROSS WHOLE.** v3 carries v1's
calculation layer and never calls v1's page builders; v4 carries both and
calls v3's screen builders for the tabs it has not rebuilt yet. The cost is
bytes before compression. The benefit is that `rowsFor`, `betProb`,
`v3EvModel`, `v3GameOdds`, `v3GameMatchup` and the Record page are the tested
originals rather than a second implementation of each.

Served from `/v4/` while v3 keeps the root, so the two can be read side by
side on the same week's data. `manifest.webmanifest` and `sw.js` are both
relative, so they need no edit to live in a subdirectory — but the service
worker's cache name does, or v3's cached shell answers a v4 request from the
same origin. See `SW_PREFIX`.
"""
from __future__ import annotations

import base64
import html
import json

from src.export import appicon
from src.export.pwa import SW, _split_history, manifest
from src.export.site import FONT_DIR
from src.export.v4css import HASHMARK

#: The cache name's prefix, and the reason it is not v3's.
#:
#: Two apps served from one origin under sibling paths share a service-worker
#: registry and a Cache Storage namespace. An identical cache name would let
#: v3's cached `./index.html` answer v4's request for `/v4/index.html` —
#: which is the same relative URL from each worker's own scope.
SW_PREFIX = "v4"

#: The three faces, as the files on disk.
#:
#: Geist and Geist Mono have variable builds, so one file covers every weight
#: the page uses. Barlow Condensed does not, so it needs a file per weight —
#: which is why this is a list of (family, file, weight-range) rather than
#: `site.FONT_FILES`'s family -> file map, and why it is not a copy of
#: `site._font_faces`.
#:
#: Latin subset only, the same decision `site.FONT_FILES` records: the full
#: faces carry Cyrillic and Vietnamese for rosters that contain neither.
#: 82KB for four files against 270KB for scripts nobody reads here.
#:
#: All three are SIL Open Font License 1.1 — Geist and Geist Mono from Vercel,
#: Barlow Condensed from Jeremy Tribby — so embedding them in the page is
#: within the license. Self-hosted rather than linked, because the app is a
#: PWA that has to render with no network and a `fonts.googleapis.com` link
#: would make the design conditional on being online.
FONT_FACES: tuple[tuple[str, str, str], ...] = (
    ("Geist", "Geist.woff2", "100 900"),
    ("Geist Mono", "GeistMono.woff2", "100 900"),
    ("Barlow Condensed", "BarlowCondensed600.woff2", "600"),
    ("Barlow Condensed", "BarlowCondensed700.woff2", "700"),
)


def font_faces() -> str:
    """The four faces as data URIs. A missing file is skipped, not raised.

    Skipped rather than fatal because the fallback stacks in `v4css` are real
    — Arial Narrow for the display face, `ui-monospace` for the numbers — so a
    checkout without the fonts renders a plainer page rather than no page.
    `test_v4_export` asserts all four are present, which is where a missing
    file should be noticed.
    """
    out = []
    for family, name, weight in FONT_FACES:
        p = FONT_DIR / name
        if not p.exists():
            continue
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        out.append(
            "@font-face{font-family:'%s';font-style:normal;font-weight:%s;"
            "font-display:swap;src:url(data:font/woff2;base64,%s) "
            "format('woff2')}" % (family, weight, b64))
    return "".join(out)


#: The frame. v3's structure, with two deliberate differences.
#:
#: `#appbar` carries NO class: `v4js.v3Header` returns either an `.appbar` or
#: a `.ghead` wrapper, because the game screen's header is a dark surface with
#: its own nav and the element itself cannot be both.
#:
#: And there is no `#slipbarHost`. The bet slip is gone — asked for directly —
#: and `v3js.render` guards every chrome write with an existence check, so its
#: absence removes the slip bar without this file having to stub it out.
SHELL = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="__THEME__">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="__SHORT__">
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="__TOUCH__">
<title>__TITLE__</title>
<style>__FONTS__</style>
<style>__CSS__</style>
</head><body>
<div class="app">
  <header id="appbar"></header>
  <main class="scroll" id="scroll"><div id="app"></div></main>
  <nav class="tabbar" id="tabbar" aria-label="Main"></nav>
</div>
<div class="scrim" id="scrim"></div>
<div class="sheet" id="sheet" role="dialog" aria-modal="true"></div>
<script id="payload" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('payload').textContent);
__JS__
</script>
<script>
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () =>
    navigator.serviceWorker.register('sw.js').catch(() => {}));
}
</script>
</body></html>
"""


def _manifest(payload: dict) -> str:
    """v3's manifest with the Hashmark ground and v4's name.

    Patched rather than rewritten: the icons are PNGs rendered by `appicon`
    and inlined as data URIs, and a second copy of that call is a second
    chance for the two apps' home-screen icons to drift apart.
    """
    m = json.loads(manifest(payload))
    ground = HASHMARK["bg"]
    m["background_color"] = ground
    m["theme_color"] = ground
    return json.dumps(m, indent=2)


def render(payload: dict) -> dict[str, str]:
    """The files, keyed by the name each has to be uploaded under."""
    from src.export import site as v1
    from src.export.v4css import css as v4_css
    from src.export.v4js import js as v4_js

    # Every v1 module but JS_SHELL, then v3's whole app, then v4's overrides.
    # Order is the mechanism and not a convenience: v4's `v3Header`, `v3Nav`
    # and `v3Screen` are duplicate function declarations that have to be
    # instantiated after v3's, and its `v3Load` has to be hoisted before
    # v3's `const V` initializer runs. See `v4js`.
    js = "\n".join([v1.JS_CORE, v1.JS_SHARED, v1.JS_SLIPVIEW, v1.JS_WEEK,
                    v1.JS_COMBOS, v1.JS_SAVED, v1.JS_LADDER, v1.JS_MODEL,
                    v4_js()])

    payload, extra = _split_history(payload)
    from src.export.payload import for_page
    # `sort_keys` for the same reason v3 gives: several dicts in this payload
    # are built by iterating something whose order polars does not promise,
    # so without it every rebuild is a diff that buries the churn that counts.
    data = (json.dumps(for_page(payload), separators=(",", ":"),
                       allow_nan=False, sort_keys=True)
            .replace("</", "<\\/"))
    brand = payload.get("brand") or "Pick Six"
    short = brand.split()[0] if len(brand) > 12 else brand
    stamp = str(payload.get("built", "")).replace(":", "").replace("-", "")

    page = (SHELL
            .replace("__TITLE__", html.escape(
                f"{brand} — {payload.get('season', '')} "
                f"week {payload.get('week', '')}"))
            .replace("__THEME__", HASHMARK["bg"])
            .replace("__SHORT__", html.escape(short))
            .replace("__TOUCH__", appicon.data_uri(180))
            .replace("__FONTS__", font_faces())
            .replace("__CSS__", v4_css())
            .replace("__JS__", js)
            .replace("__DATA__", data))

    return {
        "index.html": page,
        "manifest.webmanifest": _manifest(payload),
        "sw.js": SW.replace("__STAMP__", f"{SW_PREFIX}-{stamp or 'dev'}"),
        **extra,
    }
