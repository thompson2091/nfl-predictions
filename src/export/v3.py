"""site/v3 — the shell, and what goes in it.

Three files and a `data/` folder, uploaded together, exactly as v2. What
differs is what the page is for: see `v3js`.

**v1's calculation layer comes across unforked.** `rowsFor`, `betProb`,
`ev100`, `amToDec`, `esc`, `served` and `fixtureOf` are imported from
`src.export.site` and are the arithmetic under every figure v3 renders. v1's
own page builders travel with them and are never called — about 100KB before
compression — which is the same trade `pwa.render` documents and makes for the
same reason: splitting them out means refactoring the tested thing to serve the
untested one.
"""
from __future__ import annotations

import html
import json

from src.export import appicon
from src.export.pwa import SW, TOKENS, _split_history, manifest

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
  <header class="appbar" id="appbar"></header>
  <main class="scroll" id="scroll"><div id="app"></div></main>
  <div id="slipbarHost"></div>
  <nav class="tabbar" id="tabbar" aria-label="Main"></nav>
</div>
<div class="scrim" id="scrim"></div>
<div class="sheet" id="sheet" role="dialog" aria-modal="true" aria-labelledby="sheet-title" aria-label="Details"></div>
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


def render(payload: dict) -> dict[str, str]:
    """The files, keyed by the name each has to be uploaded under."""
    from src.export import site as v1
    from src.export.site import _font_faces
    from src.export.v3css import css as v3_css
    from src.export.v3js import js as v3_js

    # Every v1 module but JS_SHELL, whose `render`, `route` and `go` are what
    # v3 replaces. Order matters: v3's shell is last and shadows them.
    js = "\n".join([v1.JS_CORE, v1.JS_SHARED, v1.JS_SLIPVIEW, v1.JS_WEEK,
                    v1.JS_COMBOS, v1.JS_SAVED, v1.JS_LADDER, v1.JS_MODEL,
                    v3_js()])

    payload, extra = _split_history(payload)
    # `sort_keys` KILLS A WHOLE CLASS OF CHURN IN ONE LINE.
    #
    # Several dicts in this payload are built by iterating something whose
    # order polars does not promise — `unique`, `group_by` — so their keys
    # came out in a different order on every build. The keys and the values
    # were identical; only the order moved. That changes nothing a reader
    # sees, and it made every rebuild a diff, which is worse than cosmetic:
    # it buries the churn that DOES matter under noise nobody can read past.
    # Sorting here fixes every such dict at once instead of one at a time.
    from src.export.payload import for_page
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
            .replace("__THEME__", TOKENS["Ground and ink"]["bg"])
            .replace("__SHORT__", html.escape(short))
            .replace("__TOUCH__", appicon.data_uri(180))
            .replace("__FONTS__", _font_faces())
            .replace("__CSS__", v3_css())
            .replace("__JS__", js)
            .replace("__DATA__", data))

    return {
        "index.html": page,
        "manifest.webmanifest": manifest(payload),
        # A DIFFERENT cache name from v2's, via the stamp. Two apps served from
        # one origin under sibling paths share a worker registry; an identical
        # stamp would let v2's cached shell answer a v3 request.
        "sw.js": SW.replace("__STAMP__", f"v3-{stamp or 'dev'}"),
        **extra,
    }
