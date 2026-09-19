"""site/v2 — the same board, as something you can install.

v1 is `src/export/site.py` and is not going anywhere. This is the same data,
the same models and the same behaviour, in a shell that a phone can keep on
its home screen: a web app manifest, a service worker, and the handful of CSS
rules that standalone display needs and a browser tab does not.

**One source of truth for behaviour.** Every page, board, filter and parlay
calculation is `site.JS_*`, imported here rather than copied. A fork of 156KB
of page logic would drift within a week and would take the 635 tests that
cover it out of the picture for v2 — which is exactly the part of this project
that should not be re-earned. What v2 owns is the skin and the shell.

**Three files, and that is a promise rather than an accident.** `index.html`,
`manifest.webmanifest`, `sw.js`. A service worker cannot be inlined — it needs
its own URL to have a scope — and Safari does not reliably accept a data: URI
manifest, so those two are real files. Everything else is inside the page,
icons included: `src/export/appicon.py` draws them at build time and they
travel as data URIs, which is what keeps this from being seven files.

**The token layer is widened and waiting.** v1 has eleven custom properties,
all of them colour, with every spacing, radius and type size typed literally
into 33KB of component rules. Here they are a full scale — space, radius,
type, elevation, layout — so that adopting a design system is a change to
`TOKENS` rather than a search through the components. The colours in it are
still v1's: this is the seam, not the new design.

What standalone display actually changes, and why it is worth the two extra
files: the window has no browser chrome. No address bar to collapse, nothing
to fight over the top of the screen, no viewport that changes height as you
scroll. The problem that took three attempts to work around in v1 does not
exist here.
"""
from __future__ import annotations

import html
import json

from src.export import appicon

#: The design tokens, grouped by what they are rather than where they are
#: used. A design system replaces the values in here; the component rules
#: below reach for the names.
TOKENS: dict[str, dict[str, str]] = {
    "Ground and ink": {
        "bg": "#F5F3EE", "card": "#FFFFFF", "inset": "#F7F5F0", "sunk": "#EEEBE4",
        "line": "#E3DFD6", "line2": "#ECE8E0", "line3": "#F0EDE6",
        "btnline": "#D6D1C6",
        "ink": "#16181D", "mut": "#5E6168", "mut2": "#6B6E75", "mut3": "#8A8D93",
    },
    "Meaning": {
        "ours": "#1F4FA3", "oursbg": "#EEF2FA", "oursfaint": "#B9C8E6",
        "good": "#1C6B42", "goodbg": "#E3F0E8", "goodline": "#BFD9C8",
        "gooddot": "#1C7A4A",
        "bad": "#9E3624", "badbg": "#F6E4E0", "baddot": "#B3402F",
        "warn": "#7A5410", "warnbg": "#FBEFD9",
        "star": "#D9A21B", "starline": "#B8860B",
        "seg": "#E9E5DC", "navon": "#EFECE5", "pend": "#C9C4B8",
    },
    "Type": {
        "sans": ("'Schibsted Grotesk','Helvetica Neue',-apple-system,"
                 "BlinkMacSystemFont,sans-serif"),
        "serif": "'Newsreader',Georgia,'Times New Roman',serif",
        "t-xs": "12px", "t-sm": "13px", "t-md": "14px", "t-base": "15px",
        "t-lg": "18px", "t-xl": "22px", "t-2xl": "28px", "t-3xl": "40px",
    },
    # An eight-step scale on a 4px grid. Named by step rather than by use, so
    # a component asking for `--s4` is asking for a size and not for a meaning
    # it might later stop having.
    "Space": {
        "s1": "4px", "s2": "8px", "s3": "12px", "s4": "16px",
        "s5": "20px", "s6": "24px", "s7": "32px", "s8": "40px",
    },
    "Radius": {
        "r-sm": "8px", "r-md": "10px", "r-lg": "12px", "r-xl": "14px",
        "r-pill": "999px",
    },
    "Elevation": {
        "e1": "0 1px 2px rgba(0,0,0,.08)",
        "e2": "0 6px 20px rgba(22,24,29,.22)",
        "e3": "0 12px 32px rgba(22,24,29,.14)",
    },
    # The frame the artboards were drawn on, so a layout rule can say what it
    # means instead of repeating a number.
    "Layout": {
        "header": "64px", "aside": "360px", "gutter": "40px",
    },
}


def tokens_css() -> str:
    """`TOKENS` as one `:root` block, comments and all."""
    out = ["/* ── Tokens ──────────────────────────────────────────────────",
           "   Named for what they mean rather than what they are, so a design",
           "   change is this block and not a search through the components.",
           "",
           "   There is no dark mode. The design is a single committed look on",
           "   a warm paper ground, and a mechanical inversion is not the same",
           "   design — the greens and reds carry meaning against #F5F3EE that",
           "   they lose against black. `color-scheme` stops the browser",
           "   helping. */",
           ":root{", "  color-scheme: light;"]
    for group, vals in TOKENS.items():
        out.append(f"  /* {group} */")
        for k, v in vals.items():
            out.append(f"  --{k}:{v};")
    out.append("}")
    return "\n".join(out) + "\n"


def component_css() -> str:
    """v1's component rules, with its own token block taken off the front.

    Sliced rather than re-authored. The components are 33KB of decisions that
    were each argued for and tested, and re-typing them to change the palette
    would be throwing that away to achieve nothing — the palette is in the
    tokens. When the design system arrives it will rewrite parts of this; what
    it will not do is rewrite it because v2 exists.
    """
    from src.export.site import CSS

    end = CSS.index("}", CSS.index(":root{")) + 1
    return CSS[end:].lstrip("\n")


#: What a window with no browser chrome needs, and a tab does not.
APP_CSS = """
/* ── Installed ───────────────────────────────────────────────────────────
   `viewport-fit=cover` lets the page use the whole screen, which on a
   notched phone means the whole screen INCLUDING the parts the system draws
   over. `env(safe-area-inset-*)` is how much of each edge that is: zero in a
   browser tab on a flat screen, and 59px of status bar at the top of an
   installed app on an iPhone. Added to the padding that was already there
   rather than replacing it, or the app is flush to the notch on a phone and
   has no gutter at all on a desktop. */
.top{
  padding-top:calc(10px + env(safe-area-inset-top));
  padding-left:calc(40px + env(safe-area-inset-left));
  padding-right:calc(40px + env(safe-area-inset-right));
  height:auto;min-height:calc(64px + env(safe-area-inset-top));
}
main{
  padding-left:calc(40px + env(safe-area-inset-left));
  padding-right:calc(40px + env(safe-area-inset-right));
}
.sliptab{
  right:calc(20px + env(safe-area-inset-right));
  bottom:calc(20px + env(safe-area-inset-bottom));
}
footer{
  padding-left:calc(40px + env(safe-area-inset-left));
  padding-bottom:calc(40px + env(safe-area-inset-bottom));
}
/* The rubber-band. Dragging past the end of the board in an installed app
   pulls the whole app down off the top of the screen and shows the page
   behind it, which in standalone is nothing at all — a white bar where the
   app used to be. It is a browser affordance, and there is no browser. */
html,body{overscroll-behavior:none}
/* And the pane keeps its own, so flinging a 500-row table does not hand the
   leftover momentum to the page underneath it. */
.rows{overscroll-behavior:contain}
@media (max-width:680px){
  .top{
    padding-left:calc(16px + env(safe-area-inset-left));
    padding-right:calc(16px + env(safe-area-inset-right));
  }
  main{
    padding-left:calc(12px + env(safe-area-inset-left));
    padding-right:calc(12px + env(safe-area-inset-right));
  }
  .sliptab{
    right:calc(12px + env(safe-area-inset-right));
    bottom:calc(12px + env(safe-area-inset-bottom));
  }
}
/* Installed, there is no address bar to reach past — so the board gets the
   height a browser was keeping. */
@media (display-mode:standalone){
  .rows{max-height:calc(100dvh - 150px)}
}
"""


#: The service worker.
#:
#: Network-first for the page, which is the opposite of the usual advice and
#: is right here: this page IS the data. A cache-first worker would serve last
#: week's board to someone holding a phone with four bars, and they would have
#: no way to tell — the page looks identical, the numbers are just wrong. So
#: the network wins when there is one, the cache answers when there is not,
#: and being offline is the only way to see a stale board.
#:
#: `__STAMP__` is the build's own timestamp, so every upload is a new cache
#: and the old one is deleted on activate. Without it a worker installed in
#: week 2 keeps answering in week 3.
SW = """// Pick Six — offline shell. Generated; do not edit.
const CACHE = 'picksix-__STAMP__';
const SHELL = ['./', './index.html', './manifest.webmanifest'];

self.addEventListener('install', e => {
  // `skipWaiting`, so a new week's upload takes over on the next load rather
  // than waiting for every tab to close. The page is a document, not a
  // running session; there is no state to lose.
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  // Same origin only. A cross-origin request from this page would be a bug —
  // the page carries its own fonts and reaches for nothing — and caching one
  // would hide it.
  if (new URL(req.url).origin !== self.location.origin) return;

  e.respondWith((async () => {
    try {
      const fresh = await fetch(req);
      // Only a real answer is worth keeping. A 404 cached under the page's
      // own URL is an app that is broken until someone clears their browser.
      if (fresh && fresh.ok) {
        const c = await caches.open(CACHE);
        c.put(req, fresh.clone());
      }
      return fresh;
    } catch (err) {
      const hit = await caches.match(req);
      if (hit) return hit;
      // A navigation with nothing cached: hand back the shell rather than the
      // browser's offline page, which is how an installed app is supposed to
      // behave when it has never been opened online.
      if (req.mode === 'navigate') {
        const shell = await caches.match('./index.html');
        if (shell) return shell;
      }
      throw err;
    }
  })());
});
"""


def manifest(payload: dict) -> str:
    """The web app manifest, icons and all, as JSON."""
    brand = payload.get("brand") or "Pick Six"
    return json.dumps({
        "name": brand,
        # What fits under the icon on a home screen. The full name is used
        # everywhere the room exists.
        "short_name": brand.split()[0] if len(brand) > 12 else brand,
        "description": ("Every player on the slate, with our number beside "
                        "the book's."),
        # Relative, so the app works from a subdirectory — which is how it
        # will be uploaded.
        "start_url": "./index.html",
        "scope": "./",
        # The whole reason for the manifest. No address bar, no tab strip,
        # and no viewport that changes height as you scroll.
        "display": "standalone",
        "orientation": "portrait-primary",
        # The colour behind the app before its first paint, and the tint of
        # the system bars around it. The page's own ground, so launching it
        # is not a flash of white.
        "background_color": TOKENS["Ground and ink"]["bg"],
        "theme_color": TOKENS["Ground and ink"]["bg"],
        "categories": ["sports", "utilities"],
        "icons": [
            {"src": appicon.data_uri(192), "sizes": "192x192",
             "type": "image/png", "purpose": "any"},
            {"src": appicon.data_uri(512), "sizes": "512x512",
             "type": "image/png", "purpose": "any"},
            # Cropped to whatever shape the platform likes, so it needs its
            # own drawing with the margin already in it.
            {"src": appicon.data_uri(512, maskable=True), "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    }, indent=2)


SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<!-- `viewport-fit=cover` is what makes `env(safe-area-inset-*)` mean
     anything. Without it the page is letterboxed inside the safe area and an
     installed app has a white bar where the notch is. -->
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__TITLE__</title>
<meta name="description" content="Every player on the slate, with our number beside the book&#39;s.">
<meta name="theme-color" content="__THEME__">
<link rel="manifest" href="manifest.webmanifest">
<!-- iOS reads these rather than the manifest for the home-screen case. The
     touch icon is a data URI for the same reason every other icon is: three
     files, not seven. -->
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="__SHORT__">
<!-- `default` rather than `black-translucent`: translucent puts the status
     bar ON TOP of the page's first 59 pixels, which is the header. -->
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<link rel="apple-touch-icon" href="__TOUCH__">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ctext y='26' font-size='26'%3E%F0%9F%8F%88%3C/text%3E%3C/svg%3E">
<style>__FONTS____CSS__</style>
</head>
<body>
<!-- The app shell, in the document rather than drawn by the script: these
     five boxes are the layout, and the layout must not wait for 1.4MB of
     payload to arrive before it exists. -->
<header class="appbar" id="appbar"><span class="appbar__mark">__BRAND__</span></header>
<div class="scroll" id="scroll"><div class="inner"><div class="boot" aria-hidden="true">
  <div class="bootbar" style="width:220px;height:34px"></div>
  <div class="bootbar" style="width:min(520px,80%);height:16px"></div>
  <div class="bootcard">
    <div class="bootrow"></div><div class="bootrow"></div><div class="bootrow"></div>
    <div class="bootrow"></div><div class="bootrow"></div><div class="bootrow"></div>
  </div>
</div></div></div>
<div id="slipbarHost"></div>
<nav class="tabbar" id="tabbar"></nav>
<div class="scrim" id="scrim"></div>
<div class="sheet" id="sheet"></div>
<noscript>
  <div style="max-width:640px;margin:48px auto;padding:0 24px;font:16px/1.5 Georgia,serif">
    <h1 style="font-family:Georgia,serif;font-weight:500">This page needs JavaScript</h1>
    <p style="color:#5E6168">Every number here is computed in your browser — the board,
    the parlay maths and the combinations search — so there is nothing to show without it.
    Nothing is sent anywhere; that is the same reason it works with no network.</p>
  </div>
</noscript>
<script id="payload" type="application/json">__DATA__</script>
<script>const DATA = JSON.parse(document.getElementById('payload').textContent);</script>
<script>__JS__</script>
<script>
// The worker, registered after the page is up.
//
// Guarded three ways, because all three happen: no `serviceWorker` at all on
// an old browser, no secure context when the file is opened from disk with a
// double click, and a rejected registration on a host that will not serve
// `sw.js` from this path. None of them is a reason for the page not to work —
// it is self-contained either way, and what the worker adds is a second
// opening rather than a first one.
if ('serviceWorker' in navigator && window.isSecureContext) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  });
}
</script>
</body>
</html>
"""


def render(payload: dict) -> dict[str, str]:
    """The three files, keyed by the name each has to be uploaded under."""
    from src.export.site import _font_faces
    from src.export import site as v1
    from src.export import v2js

    # Every module but JS_SHELL, which owns v1's `render`, `route` and `go`.
    # Those three are what v2 replaces; everything else is the calculation
    # layer — `rowsFor`, `applyFilters`, `slipMath`, `combosOf`, `settle`,
    # `portfolio`, the storage and the icons — and it comes across untouched.
    #
    # v1's own page builders come with it and are never called. That is dead
    # weight, about 100KB before compression, and it is deliberate for now:
    # splitting them out means refactoring v1 while v2's needs are still
    # being learnt, and a refactor of the tested thing to serve the untested
    # one is the wrong way round.
    js = "\n".join([v1.JS_CORE, v1.JS_SHARED, v1.JS_SLIPVIEW, v1.JS_WEEK,
                    v1.JS_COMBOS, v1.JS_SAVED, v1.JS_LADDER, v1.JS_MODEL,
                    v2js.js()])
    # `</` inside the JSON would close the script tag early and render the
    # rest of the payload as text.
    data = (json.dumps(payload, separators=(",", ":"), allow_nan=False)
            .replace("</", "<\\/"))
    brand = payload.get("brand") or "Pick Six"
    short = brand.split()[0] if len(brand) > 12 else brand
    from src.export.v2css import css as v2_css
    css = v2_css()
    stamp = str(payload.get("built", "")).replace(":", "").replace("-", "")

    page = (SHELL
            .replace("__TITLE__", html.escape(
                f"{brand} — {payload.get('season', '')} "
                f"week {payload.get('week', '')}"))
            .replace("__THEME__", TOKENS["Ground and ink"]["bg"])
            .replace("__SHORT__", html.escape(short))
            .replace("__TOUCH__", appicon.data_uri(180))
            .replace("__BRAND__", html.escape(brand))
            .replace("__FONTS__", _font_faces())
            .replace("__CSS__", css)
            .replace("__JS__", js)
            .replace("__DATA__", data))

    return {
        "index.html": page,
        "manifest.webmanifest": manifest(payload),
        "sw.js": SW.replace("__STAMP__", stamp or "dev"),
    }
