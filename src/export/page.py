"""The HTML shell: design tokens, layout, and the browser-side behaviour.

Kept apart from render.py so the node-to-markup mapping stays readable next to
the capture it consumes, and so the whole of the page's look is one file you can
edit without touching the tree walk.
"""
from __future__ import annotations

from .render import Renderer, esc, plain

CSS = """
*, *::before, *::after { box-sizing: border-box; }

:root {
  color-scheme: light;
  --plane: #f9f9f7;
  --surface: #fcfcfb;
  --ink: #0b0b0b;
  --ink-2: #52514e;
  --muted: #898781;
  --grid: #e1e0d9;
  --rule: #c3c2b7;
  --border: rgba(11,11,11,0.10);
  --accent: #2a78d6;
  --good: #0ca30c;
  --good-ink: #006300;
  --warn: #fab219;
  --bad: #d03b3b;
  --ramp-1: #1c5cab;
  --ramp-2: #2a78d6;
  --ramp-3: #86b6ef;
  --shadow: 0 1px 2px rgba(11,11,11,.05), 0 8px 24px rgba(11,11,11,.06);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --plane: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7;
    --muted: #898781; --grid: #2c2c2a; --rule: #383835;
    --border: rgba(255,255,255,0.10); --accent: #3987e5;
    --good: #0ca30c; --good-ink: #0ca30c; --warn: #fab219; --bad: #d03b3b;
    --ramp-1: #b7d3f6; --ramp-2: #3987e5; --ramp-3: #1c5cab;
    --shadow: 0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.35);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --plane: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7;
  --muted: #898781; --grid: #2c2c2a; --rule: #383835;
  --border: rgba(255,255,255,0.10); --accent: #3987e5;
  --good: #0ca30c; --good-ink: #0ca30c; --warn: #fab219; --bad: #d03b3b;
  --ramp-1: #b7d3f6; --ramp-2: #3987e5; --ramp-3: #1c5cab;
  --shadow: 0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.35);
}

html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--plane);
  color: var(--ink);
  font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif;
}
.wrap { max-width: 1180px; margin: 0 auto; padding: 0 20px 96px; }

/* ── Masthead ─────────────────────────────────────────────────────────── */

.masthead { border-bottom: 1px solid var(--border); background: var(--surface); }
.masthead .wrap { padding-top: 26px; padding-bottom: 0; }
.eyebrow {
  font-size: 12px; letter-spacing: .09em; text-transform: uppercase;
  color: var(--muted); margin: 0 0 6px;
}
h1 { font-size: clamp(26px, 4vw, 38px); line-height: 1.15; margin: 0 0 8px; letter-spacing: -.02em; }
.dek { color: var(--ink-2); margin: 0 0 20px; max-width: 62ch; }
.bar { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-end; justify-content: space-between; }

.switch { display: inline-flex; gap: 4px; padding: 4px; border: 1px solid var(--border); border-radius: 10px; background: var(--plane); }
.switch button {
  font: inherit; font-size: 14px; font-weight: 550; color: var(--ink-2);
  background: none; border: 0; border-radius: 7px; padding: 7px 14px; cursor: pointer;
}
.switch button[aria-pressed="true"] { background: var(--surface); color: var(--ink); box-shadow: var(--shadow); }
.switch button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

.tabsnav { display: flex; gap: 24px; margin: 22px 0 0; }
.tabsnav button {
  font: inherit; font-size: 15px; font-weight: 550; color: var(--muted);
  background: none; border: 0; border-bottom: 2px solid transparent;
  padding: 0 0 12px; cursor: pointer;
}
.tabsnav button[aria-selected="true"] { color: var(--ink); border-bottom-color: var(--accent); }
.tabsnav button:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }

.meta { font-size: 13px; color: var(--muted); display: flex; flex-wrap: wrap; gap: 6px 14px; }
.meta b { color: var(--ink-2); font-weight: 550; }

.iconbtn {
  font: inherit; font-size: 13px; color: var(--ink-2); background: var(--plane);
  border: 1px solid var(--border); border-radius: 8px; padding: 6px 11px; cursor: pointer;
}
.iconbtn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

/* ── Flow ─────────────────────────────────────────────────────────────── */

section.pane { padding-top: 34px; }
h2 { font-size: 22px; letter-spacing: -.01em; margin: 34px 0 10px; }
h3 { font-size: 18px; margin: 30px 0 8px; }
h4 { font-size: 15px; margin: 22px 0 6px; }
h5, h6 { font-size: 14px; margin: 18px 0 6px; }
p { margin: 0 0 14px; max-width: 74ch; }
li { max-width: 72ch; }
.caption { font-size: 14px; color: var(--ink-2); }
hr { border: 0; border-top: 1px solid var(--border); margin: 30px 0; }
code { font: 500 .88em ui-monospace, SFMono-Regular, Menlo, monospace; background: var(--plane); border: 1px solid var(--border); border-radius: 4px; padding: .1em .35em; }
a { color: var(--accent); }
.cols { display: flex; flex-wrap: wrap; gap: 28px; align-items: flex-start; }
.cols > .col { flex: 1 1 280px; min-width: 0; }
.panel { border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; background: var(--surface); margin: 0 0 18px; }

/* ── Stat tiles ───────────────────────────────────────────────────────── */

.tiles {
  display: grid; gap: 1px; background: var(--border);
  grid-template-columns: repeat(auto-fit, minmax(148px, 1fr));
  border: 1px solid var(--border); border-radius: 12px; overflow: hidden;
  margin: 0 0 22px;
}
.tile { background: var(--surface); padding: 14px 16px 16px; }
.tile-label { font-size: 12.5px; color: var(--muted); display: flex; align-items: center; gap: 4px; margin-bottom: 4px; }
.tile-value { font-size: 25px; font-weight: 600; letter-spacing: -.02em; line-height: 1.1; }
.tile-delta { font-size: 12px; color: var(--muted); margin-top: 3px; }

/* ── Callouts ─────────────────────────────────────────────────────────── */

.callout {
  border: 1px solid var(--border); border-left: 3px solid var(--rule);
  border-radius: 10px; background: var(--surface);
  padding: 16px 18px; margin: 0 0 20px;
}
.callout > :last-child { margin-bottom: 0; }
.callout.good { border-left-color: var(--good); }
.callout.warn { border-left-color: var(--warn); }
.callout.bad  { border-left-color: var(--bad); }
.callout.info { border-left-color: var(--accent); }

/* ── Disclosure ───────────────────────────────────────────────────────── */

.disclosure { border: 1px solid var(--border); border-radius: 10px; background: var(--surface); margin: 0 0 20px; }
.disclosure > summary {
  cursor: pointer; padding: 13px 18px; font-weight: 550; font-size: 15px;
  list-style: none; display: flex; align-items: center; gap: 9px;
}
.disclosure > summary::-webkit-details-marker { display: none; }
.disclosure > summary::before {
  content: ""; width: 7px; height: 7px; flex: none;
  border-right: 1.5px solid var(--muted); border-bottom: 1.5px solid var(--muted);
  transform: rotate(-45deg); transition: transform .15s;
}
.disclosure[open] > summary::before { transform: rotate(45deg); }
.disclosure > summary:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; border-radius: 10px; }
.disclosure-body { padding: 2px 18px 8px; border-top: 1px solid var(--border); }
.disclosure-body > :first-child { margin-top: 14px; }

/* ── Tables ───────────────────────────────────────────────────────────── */

.controls { display: flex; flex-wrap: wrap; gap: 14px; margin: 0 0 14px; align-items: flex-end; }
.ctl { display: flex; flex-direction: column; gap: 5px; font-size: 12.5px; color: var(--muted); }
.ctl > span { display: flex; align-items: center; gap: 4px; }
.ctl input, .ctl select {
  font: inherit; font-size: 14px; color: var(--ink); background: var(--surface);
  border: 1px solid var(--border); border-radius: 8px; padding: 7px 10px; min-width: 170px;
}
.ctl input:focus-visible, .ctl select:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }

.tablewrap {
  overflow-x: auto; border: 1px solid var(--border); border-radius: 12px;
  background: var(--surface); margin: 0 0 8px;
}
table.grid { border-collapse: collapse; width: 100%; font-size: 14px; }
table.grid th, table.grid td { padding: 9px 13px; text-align: left; white-space: nowrap; }
table.grid th {
  position: sticky; top: 0; z-index: 2; background: var(--surface);
  font-size: 12px; font-weight: 600; color: var(--ink-2); cursor: pointer;
  border-bottom: 1px solid var(--rule); user-select: none;
}
table.grid th > span { display: inline-flex; align-items: center; gap: 4px; }
table.grid th[aria-sort="ascending"] > span::after { content: "\\2191"; color: var(--accent); }
table.grid th[aria-sort="descending"] > span::after { content: "\\2193"; color: var(--accent); }
table.grid th:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
table.grid td { border-bottom: 1px solid var(--grid); font-variant-numeric: tabular-nums; }
table.grid tbody tr:last-child td { border-bottom: 0; }
table.grid tbody tr:hover td { background: var(--plane); }
table.grid .num { text-align: right; }
.rowcount { font-size: 13px; color: var(--muted); margin: 0 0 20px; }

/* ── Help popovers ────────────────────────────────────────────────────── */

button.help {
  width: 15px; height: 15px; flex: none; padding: 0; cursor: pointer;
  border: 1px solid var(--rule); border-radius: 50%; background: transparent;
  color: var(--muted); font-size: 10px; line-height: 1; position: relative;
}
button.help::before { content: "i"; font-style: italic; font-weight: 700; }
button.help:hover, button.help[aria-expanded="true"] { border-color: var(--accent); color: var(--accent); }
button.help:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
button.help .tip { display: none; }

#popover {
  position: fixed; z-index: 50; max-width: 340px; padding: 14px 16px;
  background: var(--surface); color: var(--ink);
  border: 1px solid var(--border); border-radius: 10px; box-shadow: var(--shadow);
  font-size: 13.5px; line-height: 1.5;
}
#popover[hidden] { display: none; }
#popover p { margin: 0 0 9px; max-width: none; }
#popover > :last-child { margin-bottom: 0; }
#popover ul { margin: 0 0 9px; padding-left: 18px; }

/* ── Chart ────────────────────────────────────────────────────────────── */

.figure { margin: 0 0 22px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); padding: 16px 18px 12px; position: relative; }
.figure figcaption { font-size: 15px; font-weight: 550; margin-bottom: 2px; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12.5px; color: var(--ink-2); margin: 6px 0 8px; }
.key { display: inline-flex; align-items: center; gap: 6px; }
.key i { width: 14px; height: 3px; border-radius: 2px; }
svg.chart { display: block; width: 100%; height: auto; overflow: visible; }
svg.chart .grid { stroke: var(--grid); stroke-width: 1; }
svg.chart .tick { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
svg.chart .line { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
svg.chart .end { stroke: var(--surface); stroke-width: 2; }
svg.chart .endlabel { fill: var(--ink-2); font-size: 11.5px; font-weight: 550; }
svg.chart .crosshair { stroke: var(--rule); stroke-width: 1; }
.chart-tip {
  position: absolute; pointer-events: none; z-index: 5; padding: 8px 11px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  box-shadow: var(--shadow); font-size: 12.5px; white-space: nowrap;
}
.chart-tip[hidden] { display: none; }
.chart-tip b { display: block; margin-bottom: 4px; font-size: 11px; color: var(--muted); font-weight: 550; }
.chart-tip span { display: flex; align-items: center; gap: 7px; font-variant-numeric: tabular-nums; }
.chart-tip i { width: 9px; height: 3px; border-radius: 2px; flex: none; }
.axis-note { font-size: 11px; color: var(--muted); text-align: center; margin: 2px 0 0; }

footer { border-top: 1px solid var(--border); margin-top: 56px; padding-top: 20px; font-size: 13px; color: var(--muted); }
footer p { max-width: 78ch; }

[hidden] { display: none !important; }
@media print { .switch, .tabsnav, .iconbtn, .controls { display: none !important; } }
"""


JS = r"""
(function () {
  'use strict';

  /* ── Theme ───────────────────────────────────────────────────────────── */
  var root = document.documentElement;
  var saved = null;
  try { saved = localStorage.getItem('td-theme'); } catch (e) {}
  if (saved) root.setAttribute('data-theme', saved);
  var themeBtn = document.getElementById('theme');
  if (themeBtn) themeBtn.addEventListener('click', function () {
    var dark = matchMedia('(prefers-color-scheme: dark)').matches;
    var now = root.getAttribute('data-theme') || (dark ? 'dark' : 'light');
    var next = now === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('td-theme', next); } catch (e) {}
  });

  /* ── Market + section switching ──────────────────────────────────────── */
  function group(selector, onPick) {
    var btns = Array.prototype.slice.call(document.querySelectorAll(selector));
    btns.forEach(function (b) {
      b.addEventListener('click', function () { onPick(b, btns); });
    });
  }

  group('.switch button', function (btn, btns) {
    btns.forEach(function (b) { b.setAttribute('aria-pressed', String(b === btn)); });
    document.querySelectorAll('[data-market]').forEach(function (el) {
      el.hidden = el.getAttribute('data-market') !== btn.dataset.market;
    });
    syncPanes();
  });

  group('.tabsnav button', function (btn, btns) {
    btns.forEach(function (b) { b.setAttribute('aria-selected', String(b === btn)); });
    syncPanes();
  });

  function syncPanes() {
    var tab = document.querySelector('.tabsnav button[aria-selected="true"]');
    var want = tab ? tab.dataset.pane : null;
    document.querySelectorAll('section.pane').forEach(function (p) {
      p.hidden = want !== null && p.dataset.pane !== want;
    });
    hidePopover();
  }
  syncPanes();

  /* ── Help popovers ───────────────────────────────────────────────────── */
  var pop = document.getElementById('popover');
  var openBtn = null;

  function hidePopover() {
    pop.hidden = true;
    if (openBtn) openBtn.setAttribute('aria-expanded', 'false');
    openBtn = null;
  }

  document.addEventListener('click', function (ev) {
    var btn = ev.target.closest ? ev.target.closest('button.help') : null;
    if (!btn) { if (!ev.target.closest('#popover')) hidePopover(); return; }
    ev.preventDefault();
    ev.stopPropagation();
    if (openBtn === btn) { hidePopover(); return; }
    hidePopover();
    openBtn = btn;
    btn.setAttribute('aria-expanded', 'true');
    var tip = btn.querySelector('.tip');
    pop.innerHTML = tip ? tip.innerHTML : '';
    pop.hidden = false;
    var r = btn.getBoundingClientRect();
    var w = pop.offsetWidth, h = pop.offsetHeight;
    var left = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), innerWidth - w - 8);
    var top = r.bottom + 8;
    if (top + h > innerHeight - 8) top = Math.max(8, r.top - h - 8);
    pop.style.left = left + 'px';
    pop.style.top = top + 'px';
  });
  addEventListener('keydown', function (e) { if (e.key === 'Escape') hidePopover(); });
  addEventListener('resize', hidePopover);
  addEventListener('scroll', hidePopover, true);

  /* ── Table sorting ───────────────────────────────────────────────────── */
  document.querySelectorAll('table.grid').forEach(function (table) {
    var body = table.tBodies[0];
    var heads = Array.prototype.slice.call(table.tHead.rows[0].cells);
    heads.forEach(function (th, i) {
      function sort() {
        var dir = th.getAttribute('aria-sort') === 'ascending' ? -1 : 1;
        heads.forEach(function (h) { h.setAttribute('aria-sort', 'none'); });
        th.setAttribute('aria-sort', dir === 1 ? 'ascending' : 'descending');
        var numeric = th.dataset.type === 'number';
        var rows = Array.prototype.slice.call(body.rows);
        rows.sort(function (a, b) {
          var x = a.cells[i].dataset.v, y = b.cells[i].dataset.v;
          if (numeric) {
            var nx = x === '' ? null : parseFloat(x), ny = y === '' ? null : parseFloat(y);
            if (nx === null && ny === null) return 0;
            if (nx === null) return 1;          /* blanks last, either direction */
            if (ny === null) return -1;
            return (nx - ny) * dir;
          }
          if (x === y) return 0;
          if (x === '') return 1;
          if (y === '') return -1;
          return x.localeCompare(y, undefined, {numeric: true}) * dir;
        });
        rows.forEach(function (r) { body.appendChild(r); });
      }
      th.addEventListener('click', sort);
      th.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); sort(); }
      });
    });
  });

  /* ── Table filtering ─────────────────────────────────────────────────── */
  var filters = Array.prototype.slice.call(document.querySelectorAll('.filter'));

  function applyFilters(tableId) {
    var table = document.getElementById(tableId);
    if (!table) return;
    var mine = filters.filter(function (f) { return f.dataset.table === tableId; });
    var rows = Array.prototype.slice.call(table.tBodies[0].rows);
    var shown = 0;
    rows.forEach(function (row) {
      var ok = mine.every(function (f) {
        var v = (f.value || '').trim();
        if (!v || v === f.dataset.all) return true;
        var cell = row.cells[+f.dataset.col];
        if (!cell) return true;
        var raw = cell.dataset.v || '';
        if (f.dataset.mode === 'equals') return raw === v;
        if (f.dataset.mode === 'contains') return raw.toLowerCase().indexOf(v.toLowerCase()) >= 0;
        if (f.dataset.mode === 'top_n') {
          var n = parseInt(v.replace(/[^0-9]/g, ''), 10);
          return isNaN(n) || parseFloat(raw) <= n;
        }
        return true;
      });
      row.hidden = !ok;
      if (ok) shown++;
    });
    var note = document.querySelector('.rowcount[data-for="' + tableId + '"]');
    if (note) {
      note.textContent = shown === rows.length ? ''
        : 'Showing ' + shown + ' of ' + rows.length + ' rows.';
    }
  }

  filters.forEach(function (f) {
    var run = function () { applyFilters(f.dataset.table); };
    f.addEventListener('input', run);
    f.addEventListener('change', run);
  });

  /* ── Chart hover ─────────────────────────────────────────────────────── */
  var RAMP = ['--ramp-1', '--ramp-2', '--ramp-3'];
  document.querySelectorAll('.figure[data-chart]').forEach(function (fig) {
    var spec;
    try { spec = JSON.parse(fig.dataset.chart); } catch (e) { return; }
    var svg = fig.querySelector('svg');
    var cross = fig.querySelector('.crosshair');
    var tip = fig.querySelector('.chart-tip');
    var span = (spec.xs.length - 1) || 1;
    var plotW = spec.w - spec.pad.l - spec.pad.r;

    function px(i) { return spec.pad.l + (i / span) * plotW; }

    svg.addEventListener('pointermove', function (ev) {
      var box = svg.getBoundingClientRect();
      var x = (ev.clientX - box.left) / box.width * spec.w;
      var i = Math.round((x - spec.pad.l) / plotW * span);
      if (i < 0 || i > span) { hide(); return; }
      cross.setAttribute('x1', px(i));
      cross.setAttribute('x2', px(i));
      cross.style.opacity = 1;
      var xv = spec.xs[i];
      var html = '<b>Week ' + xv + '</b>';
      spec.series.forEach(function (s, k) {
        var at = s.x.indexOf(xv);
        if (at < 0) return;
        html += '<span><i style="background:var(' + RAMP[k % RAMP.length] + ')"></i>' +
                s.name + ' &nbsp;' + s.y[at].toFixed(1) + '%</span>';
      });
      tip.innerHTML = html;
      tip.hidden = false;
      var left = px(i) / spec.w * box.width + 14;
      if (left + tip.offsetWidth > box.width) left -= tip.offsetWidth + 28;
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = (ev.clientY - box.top) + 'px';
    });

    function hide() { cross.style.opacity = 0; tip.hidden = true; }
    svg.addEventListener('pointerleave', hide);
  });
})();
"""


def _pane(capture, tab_label: str, pane_id: str) -> str:
    tabs = next(c for c in capture.root["children"]
                if c["t"] == "group" and c["kind"] == "tabs")
    tab = next(t for t in tabs["children"] if t["label"] == tab_label)
    body = Renderer().nodes(tab["children"])
    return f'<section class="pane" data-pane="{pane_id}">{body}</section>'


def build_page(markets: list[dict], *, panes: list[tuple[str, str]],
               built: str, title: str, dek: str) -> str:
    """markets: [{key, label, capture, meta}] in the order they should appear."""
    switch = "".join(
        f'<button type="button" data-market="{esc(m["key"])}" '
        f'aria-pressed="{"true" if i == 0 else "false"}">{esc(m["label"])}</button>'
        for i, m in enumerate(markets))

    nav = "".join(
        f'<button type="button" role="tab" data-pane="{esc(pid)}" '
        f'aria-selected="{"true" if i == 0 else "false"}">{esc(label)}</button>'
        for i, (pid, label) in enumerate(panes))

    blocks = []
    for i, m in enumerate(markets):
        meta = " ".join(f"<span>{v}</span>" for v in m["meta"])
        body = "".join(_pane(m["capture"], label, pid) for pid, label in panes)
        blocks.append(
            f'<div data-market="{esc(m["key"])}"{"" if i == 0 else " hidden"}>'
            f'<div class="wrap"><p class="meta submeta">{meta}</p>{body}</div></div>')

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(dek)}">
<meta name="robots" content="index, follow">
<style>{CSS}</style>
</head>
<body>
<header class="masthead">
  <div class="wrap">
    <p class="eyebrow">NFL touchdown props</p>
    <h1>{esc(title)}</h1>
    <p class="dek">{plain(dek)}</p>
    <div class="bar">
      <div class="switch" role="group" aria-label="Market">{switch}</div>
      <button class="iconbtn" id="theme" type="button">Light / dark</button>
    </div>
    <nav class="tabsnav" role="tablist">{nav}</nav>
  </div>
</header>

{"".join(blocks)}

<div class="wrap">
  <footer>
    <p>Built {esc(built)} from the project's own dashboard — every figure on this
    page is computed by the same code that serves the live app, then frozen into
    this file. Nothing here updates on its own; rebuild to refresh it.</p>
    <p>Probabilities are estimates, and the profitability figures describe a
    replay at closing prices in past seasons. No bet in them was ever struck.
    Nothing here is advice.</p>
  </footer>
</div>

<div id="popover" role="tooltip" hidden></div>
<script>{JS}</script>
</body>
</html>
"""
