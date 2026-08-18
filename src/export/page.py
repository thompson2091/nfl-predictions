"""The HTML shell: design tokens, layout, and the browser-side behaviour.

Kept apart from render.py so the node-to-markup mapping stays readable next to
the capture it consumes, and so the whole of the page's look is one file you can
edit without touching the tree walk.
"""
from __future__ import annotations

from .render import Renderer, esc, plain
from .simplify import expander_labels, simplify

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
    --ramp-1: #256abf; --ramp-2: #3987e5; --ramp-3: #b7d3f6;
    --shadow: 0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.35);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --plane: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7;
  --muted: #898781; --grid: #2c2c2a; --rule: #383835;
  --border: rgba(255,255,255,0.10); --accent: #3987e5;
  --good: #0ca30c; --good-ink: #0ca30c; --warn: #fab219; --bad: #d03b3b;
  --ramp-1: #256abf; --ramp-2: #3987e5; --ramp-3: #b7d3f6;
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
blockquote {
  margin: 0 0 14px; padding: 2px 0 2px 16px;
  border-left: 3px solid var(--accent); color: var(--ink-2); max-width: 72ch;
}
.cols { display: flex; flex-wrap: wrap; gap: 28px; align-items: flex-start; }
.cols > .col { flex: 1 1 280px; min-width: 0; }
.panel { border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; background: var(--surface); margin: 0 0 18px; }

/* ── Stat tiles ───────────────────────────────────────────────────────── */

.tiles {
  display: grid; background: var(--surface);
  grid-template-columns: repeat(var(--cols, 4), minmax(0, 1fr));
  border: 1px solid var(--border); border-radius: 12px; overflow: hidden;
  margin: 0 0 22px;
}
/* Rules drawn outside each tile and clipped by the container, so a part-full
   last row has no orphan cell and the outer edge never doubles up. */
.tile {
  padding: 14px 16px 16px;
  box-shadow: 1px 0 0 var(--border), 0 1px 0 var(--border);
}
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
.tablewrap.tall { max-height: 68vh; overflow-y: auto; }
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

@media (max-width: 720px) {
  .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ctl input, .ctl select { min-width: 0; width: 100%; }
  .ctl { flex: 1 1 160px; }
}

footer { border-top: 1px solid var(--border); margin-top: 56px; padding-top: 20px; font-size: 13px; color: var(--muted); }
footer p { max-width: 78ch; }

[hidden] { display: none !important; }
@media print { .switch, .tabsnav, .iconbtn, .controls { display: none !important; } }
"""


JS = r"""
(function () {
  'use strict';

  var root = document.documentElement;
  /* Declared up here because syncPanes() runs during setup and closes it. */
  var pop = document.getElementById('popover');
  var openBtn = null;

  function hidePopover() {
    if (!pop) return;
    pop.hidden = true;
    if (openBtn) openBtn.setAttribute('aria-expanded', 'false');
    openBtn = null;
  }

  /* ── Theme ───────────────────────────────────────────────────────────── */
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

  function showMarket(btn, btns) {
    btns.forEach(function (b) { b.setAttribute('aria-pressed', String(b === btn)); });
    /* Scoped to the panels: the switch's own buttons also carry data-market,
       and a bare [data-market] hid the button you had just pressed. */
    document.querySelectorAll('.marketpane').forEach(function (el) {
      el.hidden = el.getAttribute('data-market') !== btn.dataset.market;
    });
  }

  group('.switch button', function (btn, btns) {
    showMarket(btn, btns);
    syncPanes();
    writeHash();
  });

  group('.tabsnav button', function (btn, btns) {
    btns.forEach(function (b) { b.setAttribute('aria-selected', String(b === btn)); });
    syncPanes();
    writeHash();
  });

  /* Market and section in the URL, so a particular view can be linked to. */
  function writeHash() {
    var m = document.querySelector('.switch button[aria-pressed="true"]');
    var t = document.querySelector('.tabsnav button[aria-selected="true"]');
    if (m && t) history.replaceState(null, '', '#' + m.dataset.market + '/' + t.dataset.pane);
  }

  function readHash() {
    var parts = (location.hash || '').replace(/^#/, '').split('/');
    var m = parts[0] && document.querySelector('.switch button[data-market="' + CSS.escape(parts[0]) + '"]');
    var t = parts[1] && document.querySelector('.tabsnav button[data-pane="' + CSS.escape(parts[1]) + '"]');
    if (m) showMarket(m, Array.prototype.slice.call(document.querySelectorAll('.switch button')));
    if (t) document.querySelectorAll('.tabsnav button').forEach(function (b) {
      b.setAttribute('aria-selected', String(b === t));
    });
  }
  readHash();
  addEventListener('hashchange', function () { readHash(); syncPanes(); });

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


  /* ── Combinations ────────────────────────────────────────────────────────
     The section's controls, made to work on a page with no server.

     A slip's numbers are products of its legs', and every leg is a row of the
     board table above with its exact value in `data-v` — so the same table a
     reader is looking at is the input. The arithmetic here mirrors
     src/prediction/combos.py deliberately, including the candidate cut and the
     tie-break, because a published page that ranks slips differently from the
     app is worse than one that cannot rank them at all. */

  var READ_ORDER = ['Matches book', 'Leans', 'Strong call'];
  var BLOCKING = ['Out', 'Doubtful'];

  function american(dec) {
    /* Truncated, not rounded: `bets.decimal_to_american` returns a float and
       `board.american` prints it through int(), so rounding here published a
       price one point away from the app's on about a third of rows. */
    var profit = dec - 1;
    return profit >= 1 ? Math.trunc(profit * 100) : -Math.trunc(100 / profit);
  }

  function toDecimal(odds) {
    var n = parseFloat(String(odds).replace('+', ''));
    if (!isFinite(n) || n === 0) return null;
    return 1 + (n > 0 ? n / 100 : 100 / -n);
  }

  function headings(table) {
    return Array.prototype.map.call(table.tHead.rows[0].cells, function (th) {
      var span = th.querySelector('span');
      var node = span ? span.childNodes[0] : th.firstChild;
      return (node ? node.textContent : th.textContent).trim();
    });
  }

  function readLegs(board, spec) {
    var heads = headings(board);
    var at = {};
    Object.keys(spec.columns).forEach(function (k) {
      at[k] = heads.indexOf(spec.columns[k]);
    });
    if (at.player < 0 || at.game < 0 || at.odds < 0 || at.rank < 0 ||
        at.ours < 0 || at.book < 0) return null;
    var injury = heads.indexOf('Injury');

    /* The board's own game filter, mirrored: in the app the combinations
       follow it, and its search and depth filters deliberately do not. */
    var pick = null;
    var sel = document.querySelector(
      'select.filter[data-table="' + spec.board + '"][data-mode="equals"]');
    if (sel && sel.value && sel.value !== sel.dataset.all) pick = sel.value;

    var legs = [];
    Array.prototype.forEach.call(board.tBodies[0].rows, function (row) {
      var raw = function (i) { return i < 0 ? null : row.cells[i].dataset.v; };
      var dec = toDecimal(raw(at.odds));
      var ours = parseFloat(raw(at.ours)), book = parseFloat(raw(at.book));
      if (dec === null || !isFinite(ours) || !isFinite(book)) return;
      if (injury >= 0 && BLOCKING.indexOf(raw(injury)) >= 0) return;
      var game = raw(at.game);
      if (pick !== null && game !== pick) return;
      var edge = at.betEdge >= 0 ? parseFloat(raw(at.betEdge)) : NaN;
      legs.push({
        player: raw(at.player), game: game, rank: parseInt(raw(at.rank), 10),
        dec: dec, ours: ours / 100, book: book / 100,
        bet: isFinite(edge) ? (book + edge) / 100 : ours / 100,
        read: at.read >= 0 ? raw(at.read) : '',
        tier: at.tier >= 0 ? (raw(at.tier) || '') : '',
      });
    });
    return legs;
  }

  function chooseCandidates(legs, cfg) {
    var factor = cfg.metric === 'ev'
      ? function (l) { return l.bet * l.dec; }
      : function (l) { return l.ours; };
    var pool = legs.filter(function (l) { return l.rank <= cfg.perGame; });
    pool.sort(function (a, b) {
      var d = factor(b) - factor(a);
      return d || a.player.localeCompare(b.player);
    });
    return pool.slice(0, Math.max(24, cfg.show + cfg.legs));
  }

  function combinations(n, k) {
    var out = [], idx = [];
    (function walk(start) {
      if (idx.length === k) { out.push(idx.slice()); return; }
      for (var i = start; i < n; i++) { idx.push(i); walk(i + 1); idx.pop(); }
    })(0);
    return out;
  }

  function buildSlips(legs, cfg, singleWinner) {
    var cand = chooseCandidates(legs, cfg);
    if (cand.length < cfg.legs) return [];
    var slips = [];
    combinations(cand.length, cfg.legs).forEach(function (pick) {
      var games = {}, n = 0;
      pick.forEach(function (i) {
        if (!games[cand[i].game]) { games[cand[i].game] = 1; n++; }
      });
      var same = n < cfg.legs;
      if (singleWinner && same) return;
      var dec = 1, ours = 1, book = 1, bet = 1;
      pick.forEach(function (i) {
        dec *= cand[i].dec; ours *= cand[i].ours;
        book *= cand[i].book; bet *= cand[i].bet;
      });
      slips.push({
        players: pick.map(function (i) { return cand[i].player; }).join(' + '),
        game: n === 1 ? cand[pick[0]].game : n + ' games',
        dec: dec, ours: ours * 100, book: book * 100,
        edge: (ours - book) * 100, ev: (bet * dec - 1) * 100,
        read: readOf(pick.map(function (i) { return cand[i].read; })),
        tier: tierOf(pick.map(function (i) { return cand[i].tier; })),
      });
    });
    var key = cfg.metric === 'ev' ? 'ev' : 'ours';
    slips.sort(function (a, b) {
      return (b[key] - a[key]) || a.players.localeCompare(b.players);
    });
    return slips.slice(0, cfg.show);
  }

  function readOf(reads) {
    var ranks = reads.map(function (r) { return READ_ORDER.indexOf(r); })
                     .filter(function (i) { return i >= 0; });
    return ranks.length ? READ_ORDER[Math.min.apply(null, ranks)] : '';
  }

  function tierOf(tiers) {
    if (!tiers.some(function (t) { return t; })) return '';
    return tiers.map(function (t) { return t || '—'; }).join(' + ');
  }

  function signed(x, places, unit) {
    return (x >= 0 ? '+' : '-') + Math.abs(x).toFixed(places) + (unit || '');
  }

  function drawSlips(table, slips) {
    var heads = headings(table);
    /* First TD doubles land under 1% and anytime ones around a fifth of the
       time; one decimal prints the first as "0.5%" for every row. */
    var dp = slips.length && Math.max.apply(null, slips.map(function (s) {
      return s.ours; })) < 5 ? 2 : 1;
    var cell = function (value, sort, num) {
      return '<td class="' + (num ? 'num' : '') + '" data-v="' + sort + '">' +
             value + '</td>';
    };
    var body = slips.map(function (s) {
      var by = {
        'Players': cell(s.players, s.players),
        'Game': cell(s.game, s.game),
        'Odds': cell(signed(american(s.dec), 0), american(s.dec), true),
        'Our estimate': cell(s.ours.toFixed(dp) + '%', s.ours, true),
        'Bookmaker says': cell(s.book.toFixed(dp) + '%', s.book, true),
        'Difference': cell(signed(s.edge, dp, ' pts'), s.edge, true),
        'Our read': cell(s.read, s.read),
        'Expected on $100': cell('$' + signed(s.ev, 2), s.ev, true),
        'Worth backing': cell(s.tier, s.tier),
      };
      return '<tr>' + heads.map(function (h) {
        return by[h] !== undefined ? by[h] : cell('', '');
      }).join('') + '</tr>';
    }).join('');
    table.tBodies[0].innerHTML = body;
  }

  function drawStrip(strip, row, span) {
    if (!strip) return;
    if (!row) { strip.hidden = true; return; }
    strip.hidden = false;
    var money = function (x) { return '$' + signed(x, 0); };
    var values = {
      'Slips graded': [row.slips.toLocaleString(),
                       row.weeks + ' weeks, ' + span],
      'Landed': [(row.landed * 100).toFixed(1) + '%', null],
      'We said': [(row.we_said * 100).toFixed(1) + '%',
                  signed((row.landed - row.we_said) * 100, 1, '% vs landed')],
      'Book said': [(row.book_said * 100).toFixed(1) + '%', null],
      'Return per $100': [money(row.return_per_100),
                          row.return_ex_top10 === null ? null :
                          money(row.return_ex_top10) + ' without the 10 biggest wins'],
      'As singles': [money(row.as_singles_per_100), null],
    };
    Array.prototype.forEach.call(strip.querySelectorAll('.tile'), function (tile) {
      var label = tile.querySelector('.tile-label').textContent.trim();
      var found = values[label];
      if (!found) return;
      tile.querySelector('.tile-value').textContent = found[0];
      var delta = tile.querySelector('.tile-delta');
      if (delta) delta.textContent = found[1] || '';
      else if (found[1]) {
        var el = document.createElement('div');
        el.className = 'tile-delta';
        el.textContent = found[1];
        tile.appendChild(el);
      }
    });
  }

  document.querySelectorAll('.combo-controls').forEach(function (bar) {
    var spec;
    try { spec = JSON.parse(bar.dataset.combo); } catch (e) { return; }
    var board = document.getElementById(spec.board);
    var table = document.getElementById(spec.table);
    var strip = spec.strip ? document.getElementById(spec.strip) : null;
    if (!board || !table || !readLegs(board, spec)) { bar.remove(); return; }

    var inputs = Array.prototype.slice.call(bar.querySelectorAll('.combo-input'));
    var published = settings();
    /* The prose under the table describes the setting that was published. It
       is hidden while the controls say something else rather than rewritten:
       those sentences are the app's, and a page that paraphrases them would be
       a second copy to keep in step. */
    var notes = [], sib = table.parentNode.nextElementSibling;
    while (sib && sib.classList.contains('caption')) {
      notes.push(sib);
      sib = sib.nextElementSibling;
    }
    var note = document.createElement('p');
    note.className = 'caption';
    note.hidden = true;
    if (notes.length) notes[notes.length - 1].after(note);

    function settings() {
      var cfg = {};
      Array.prototype.forEach.call(bar.querySelectorAll('.combo-input'),
        function (el) { cfg[el.dataset.param] = el.value; });
      return cfg;
    }

    function config() {
      var raw = settings();
      return {
        legs: parseInt(raw.legs, 10),
        perGame: parseInt(raw.perGame, 10),
        show: parseInt(raw.show, 10),
        metric: raw.metric === 'Most likely' ? 'likely' : 'ev',
      };
    }

    var record = {rows: [], span: ''};
    if (spec.recordId) {
      var blob = document.getElementById(spec.recordId);
      if (blob) { try { record = JSON.parse(blob.textContent); } catch (e) {} }
    }

    function measured(cfg) {
      for (var i = 0; i < (record.rows || []).length; i++) {
        var r = record.rows[i];
        if (r.legs === cfg.legs && r.per_game === cfg.perGame &&
            r.metric === cfg.metric && r.show === cfg.show) return r;
      }
      return null;
    }

    function render() {
      var cfg = config();
      var slips = buildSlips(readLegs(board, spec), cfg, spec.singleWinner);
      drawSlips(table, slips);
      var row = measured(cfg);
      drawStrip(strip, row, record.span);

      var raw = settings();
      var changed = Object.keys(published).some(function (k) {
        return published[k] !== raw[k];
      });
      notes.forEach(function (n) { n.hidden = changed; });
      note.hidden = !changed;
      if (changed) {
        var words = {2: 'two', 3: 'three', 4: 'four'}[cfg.legs] || cfg.legs;
        note.textContent =
          'The ' + slips.length + ' best ' + words + '-leg combinations of the top ' +
          cfg.perGame + ', ranked by ' +
          (cfg.metric === 'ev' ? 'expected value' : 'how likely the slip is to land') +
          '. ' + (row
            ? 'Replayed over ' + record.span + ', this setting graded ' +
              row.slips.toLocaleString() + ' slips, of which ' +
              (row.landed * 100).toFixed(1) + '% landed against the ' +
              (row.we_said * 100).toFixed(1) + '% we said.'
            : 'This setting has not been graded.');
      }
    }

    inputs.forEach(function (el) { el.addEventListener('change', render); });
    /* The board's game filter feeds the legs, so it has to redraw them too. */
    var gameSel = document.querySelector(
      'select.filter[data-table="' + spec.board + '"][data-mode="equals"]');
    if (gameSel) gameSel.addEventListener('change', render);
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


def _pane(capture, tab_label: str, pane_id: str, prefix: str,
          simple: bool = True, published: set[str] | None = None,
          market: str = "", record: dict | None = None) -> str:
    tabs = next(c for c in capture.root["children"]
                if c["t"] == "group" and c["kind"] == "tabs")
    tab = next(t for t in tabs["children"] if t["label"] == tab_label)
    children = tab["children"]
    if simple:
        # The app's own tabs that this page does not publish are pointed at in
        # its prose ("see Betting reality") exactly the way a dropped expander
        # is, and read the same way on a page that has neither.
        absent = {t["label"] for t in tabs["children"]
                  if t["label"] not in (published or {tab_label})}
        children = simplify(children, expander_labels(children) | absent)
    body = Renderer(prefix, market=market, record=record).nodes(children)
    return f'<section class="pane" data-pane="{pane_id}">{body}</section>'


def build_page(markets: list[dict], *, panes: list[tuple[str, str]],
               built: str, title: str, dek: str, simple: bool = True) -> str:
    """markets: [{key, label, capture, meta}] in the order they should appear.

    `simple` publishes the trimmed page: see simplify.py for what comes out.
    """
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
        published = {label for _, label in panes}
        body = "".join(_pane(m["capture"], label, pid, f'{m["key"]}-{pid}', simple,
                             published, m["key"], m.get("record"))
                       for pid, label in panes)
        blocks.append(
            f'<div class="marketpane" data-market="{esc(m["key"])}"'
            f'{"" if i == 0 else " hidden"}>'
            f'<div class="wrap"><p class="meta submeta">{meta}</p>{body}</div></div>')

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(dek)}">
<meta name="robots" content="index, follow">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ctext y='26' font-size='26'%3E%F0%9F%8F%88%3C/text%3E%3C/svg%3E">
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
