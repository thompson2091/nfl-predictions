"""The dashboard's shell: design tokens, layout, and the browser-side behaviour.

Kept apart from `scripts/34_export_dashboard.py` for the same reason `page.py`
is kept apart from `render.py` — the whole of the page's look and all of its
interactivity is one file you can edit without touching the measurement that
feeds it, and the measurement can be dumped as JSON and checked without
rendering anything.

**Why the interactivity lives in the page rather than in the export.** The app
answers one filter setting per run; a frozen capture of it can only publish the
setting that happened to be captured. Everything a reader would reach for here —
a different game, a deeper board, a longer slip, a higher threshold — is a
different slice of numbers already in the payload, so the page recomputes rather
than the exporter enumerating. The one thing that genuinely cannot be
precomputed is the combination search: 128 eligible players is 10.7 million
four-leg slips, which is a JSON file nobody can download and a loop the browser
finishes in under a second.

**What it opens on.** Every player, then Combinations, Cover the field, By
team — a slate first, and the things you can do with it after. The two panes
that used to come first, `Model vs book` and `How often it is right`, scored
the model instead of the week; they were the first thing a reader saw and the
last thing they wanted. The measurements themselves are not gone, they are in
`walkforward.json`, `market_parity` and `hit_rates` where the evaluation
harness can gate on them, which is where a number that describes the model
rather than the slate belongs.
"""
from __future__ import annotations

import html
import json

CSS = """
*, *::before, *::after { box-sizing: border-box; }

:root {
  color-scheme: light;
  --plane: #f9f9f7;
  --surface: #fcfcfb;
  --sunken: #f2f1ed;
  --ink: #0b0b0b;
  --ink-2: #52514e;
  --muted: #898781;
  --grid: #e1e0d9;
  --rule: #c3c2b7;
  --border: rgba(11,11,11,0.10);
  --accent: #2a78d6;
  --good: #008300;
  --warn: #eda100;
  --bad: #e34948;
  --s1: #2a78d6;   /* us — blended, the published number */
  --s2: #eb6834;   /* model only — our number before the blend */
  --s3: #1baf7a;   /* the bookmaker */
  --accent-soft: rgba(42,120,214,0.10);
  --s1-soft: rgba(42,120,214,0.16);
  --s3-soft: rgba(27,175,122,0.16);
  --shadow: 0 1px 2px rgba(11,11,11,.05), 0 8px 24px rgba(11,11,11,.06);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --plane: #0d0d0d; --surface: #1a1a19; --sunken: #232322; --ink: #ffffff;
    --ink-2: #c3c2b7; --muted: #898781; --grid: #2c2c2a; --rule: #383835;
    --border: rgba(255,255,255,0.10); --accent: #3987e5;
    --good: #0ca30c; --warn: #c98500; --bad: #e66767;
    --s1: #3987e5; --s2: #d95926; --s3: #199e70;
    --accent-soft: rgba(57,135,229,0.18);
    --s1-soft: rgba(57,135,229,0.20); --s3-soft: rgba(25,158,112,0.20);
    --shadow: 0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.35);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --plane: #0d0d0d; --surface: #1a1a19; --sunken: #232322; --ink: #ffffff;
  --ink-2: #c3c2b7; --muted: #898781; --grid: #2c2c2a; --rule: #383835;
  --border: rgba(255,255,255,0.10); --accent: #3987e5;
  --good: #0ca30c; --warn: #c98500; --bad: #e66767;
  --s1: #3987e5; --s2: #d95926; --s3: #199e70;
  --accent-soft: rgba(57,135,229,0.18);
    --s1-soft: rgba(57,135,229,0.20); --s3-soft: rgba(25,158,112,0.20);
  --shadow: 0 1px 2px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.35);
}

html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0; background: var(--plane); color: var(--ink);
  font-family: ui-sans-serif, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 15px; line-height: 1.5;
}
a { color: var(--accent); }

/* ── Chrome ────────────────────────────────────────────────────────── */
.top {
  position: sticky; top: 0; z-index: 30;
  background: var(--surface); border-bottom: 1px solid var(--border);
  padding: 10px 20px; display: flex; gap: 16px; align-items: center;
  flex-wrap: wrap;
}
.brand { font-weight: 640; letter-spacing: -0.01em; margin-right: auto; }
.brand small { display: block; font-weight: 400; color: var(--muted); font-size: 12px; }
.seg { display: inline-flex; background: var(--sunken); border-radius: 8px; padding: 2px; }
.seg button {
  border: 0; background: none; color: var(--ink-2); cursor: pointer;
  font: inherit; font-size: 13px; padding: 5px 12px; border-radius: 6px;
}
.seg button[aria-pressed="true"] { background: var(--surface); color: var(--ink); font-weight: 600; box-shadow: var(--shadow); }
.iconbtn {
  border: 1px solid var(--border); background: var(--surface); color: var(--ink-2);
  border-radius: 8px; cursor: pointer; font: inherit; font-size: 13px; padding: 5px 10px;
}

.tabs { display: flex; gap: 2px; padding: 0 20px; background: var(--surface);
        border-bottom: 1px solid var(--border); overflow-x: auto;
        position: sticky; top: 53px; z-index: 29; }
.tabs button {
  border: 0; background: none; font: inherit; font-size: 14px; cursor: pointer;
  color: var(--ink-2); padding: 10px 14px; border-bottom: 2px solid transparent;
  white-space: nowrap;
}
.tabs button[aria-selected="true"] { color: var(--ink); font-weight: 620; border-bottom-color: var(--accent); }

main { padding: 20px; max-width: 1500px; margin: 0 auto; }

/* ── Blocks ────────────────────────────────────────────────────────── */
.card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 16px 18px; margin-bottom: 16px;
}
h2 { font-size: 17px; margin: 0 0 4px; letter-spacing: -0.01em; }
h3 { font-size: 14px; margin: 18px 0 6px; letter-spacing: -0.005em; }
.note { color: var(--ink-2); font-size: 13px; margin: 4px 0 0; max-width: 78ch; }
.note b, .note strong { color: var(--ink); }
.fine { color: var(--muted); font-size: 12px; margin: 8px 0 0; max-width: 90ch; }
.warn-box {
  border-left: 3px solid var(--warn); background: var(--sunken);
  padding: 10px 12px; border-radius: 0 8px 8px 0; font-size: 13px; margin: 10px 0;
}
.bad-box { border-left-color: var(--bad); }
.good-box { border-left-color: var(--good); }
/* The player picker. Two surfaces, not one: chips for what is already in the
   cover, so the answer to "who is in?" is one line rather than a re-scan of
   forty checkboxes, and a grid for everyone who could be. The grid is a wall
   of names read by eye, so each cell puts the name and the probability on the
   same baseline and the team and price beneath in a quieter colour. */
.picker { margin-bottom: 16px; }
.picked { margin: 10px 0 12px; }
.picked-h { font-size: 12px; color: var(--muted); text-transform: uppercase;
            letter-spacing: .06em; margin-bottom: 6px; }
.picked-h b { color: var(--ink); font-size: 13px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.pchip {
  display: inline-flex; align-items: center; gap: 6px; font: inherit;
  font-size: 13px; cursor: pointer; padding: 4px 8px 4px 10px;
  border-radius: 99px; border: 1px solid var(--accent);
  background: var(--accent-soft); color: var(--ink);
}
.pchip i { font-style: normal; color: var(--ink-2); font-variant-numeric: tabular-nums; }
.pchip span { color: var(--ink-2); font-size: 15px; line-height: 1; }
.pchip:hover span { color: var(--bad); }
.pchip.ghost { border-color: var(--rule); background: var(--surface); color: var(--ink-2); }
.pchip.ghost:hover { color: var(--ink); border-color: var(--border); }

/* Three rows deep and it scrolls. The section sits above the table it feeds,
   so every row of picker is a row of answer pushed off the screen; the list is
   for finding a name, not for reading the board, and the board has its own tab. */
.ppick {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(216px, 1fr));
  gap: 6px; margin: 4px 0 6px;
  max-height: 222px; overflow-y: auto; padding-right: 4px;
}
.ppick-i {
  display: grid; grid-template-columns: 1fr auto; gap: 0 8px; text-align: left;
  font: inherit; cursor: pointer; padding: 7px 10px; border-radius: 9px;
  border: 1px solid var(--rule); background: var(--surface); color: var(--ink);
}
.ppick-i:hover { border-color: var(--border); background: var(--sunken); }
.ppick-i.on { border-color: var(--accent); background: var(--accent-soft); }
.ppick-i .n { font-size: 13px; font-weight: 560; overflow: hidden;
              text-overflow: ellipsis; white-space: nowrap; }
.ppick-i .v { font-size: 13px; font-weight: 620; font-variant-numeric: tabular-nums; }
.ppick-i .d {
  grid-column: 1 / -1; display: flex; justify-content: space-between; gap: 10px;
  font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums;
}
.ppick-i .d span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ppick-i.on .d { color: var(--ink-2); }
.ppick-i.on .v { color: var(--accent); }

/* ── Tiles ─────────────────────────────────────────────────────────── */
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(148px, 1fr)); gap: 10px; }
.tile { background: var(--sunken); border-radius: 10px; padding: 10px 12px; }
.tile .k { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
.tile .v { font-size: 26px; font-weight: 600; letter-spacing: -0.02em; margin-top: 2px; }
.tile .d { font-size: 12px; color: var(--ink-2); }

/* ── Controls ──────────────────────────────────────────────────────── */
.bar { display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end; margin-bottom: 12px; }
.field { display: flex; flex-direction: column; gap: 3px; }
.field label { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
.field select, .field input[type=text] {
  font: inherit; font-size: 13px; padding: 5px 8px; border-radius: 7px;
  border: 1px solid var(--rule); background: var(--surface); color: var(--ink);
  min-width: 120px;
}
/* A range input is a drag target, so it gets drag-target dimensions: full
   width of its cell, a 44px-tall hit area on touch, and a thumb big enough to
   land on. The default 190px track with a 16px thumb is a 4% margin for error
   on a phone. */
.field.wide { flex: 1 1 280px; min-width: 220px; max-width: 460px; }
.field input[type=range] {
  width: 100%; accent-color: var(--accent);
  height: 28px; margin: 0; background: transparent; touch-action: pan-y;
}
.field input[type=range]::-webkit-slider-runnable-track {
  height: 6px; border-radius: 99px; background: var(--grid);
}
.field input[type=range]::-webkit-slider-thumb {
  -webkit-appearance: none; appearance: none;
  width: 22px; height: 22px; border-radius: 50%; margin-top: -8px;
  background: var(--accent); border: 2px solid var(--surface);
  box-shadow: var(--shadow); cursor: grab;
}
.field input[type=range]:active::-webkit-slider-thumb { cursor: grabbing; }
.field input[type=range]::-moz-range-track { height: 6px; border-radius: 99px; background: var(--grid); }
.field input[type=range]::-moz-range-thumb {
  width: 20px; height: 20px; border-radius: 50%; background: var(--accent);
  border: 2px solid var(--surface); box-shadow: var(--shadow);
}
.field input[type=range]:focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; }
.check { display: inline-flex; gap: 6px; align-items: center; font-size: 13px; color: var(--ink-2);
         padding-bottom: 6px; cursor: pointer; }
.check input { accent-color: var(--accent); }
.check.off { opacity: .45; cursor: not-allowed; }

/* ── Tables ────────────────────────────────────────────────────────── */
/* These tables are wider than any screen — the master board carries eighteen
   columns — so horizontal scrolling is the normal way to read them, not an
   edge case. Two things make that workable and both were missing: macOS hides
   overlay scrollbars until you already know to scroll, and scrolling right
   used to carry the player's name off the screen, leaving a row of numbers
   belonging to nobody. */
.scroll {
  overflow-x: auto; overflow-y: hidden;
  border: 1px solid var(--border); border-radius: 10px;
  scrollbar-width: thin; scrollbar-color: var(--rule) transparent;
  -webkit-overflow-scrolling: touch;
}
.scroll::-webkit-scrollbar { height: 11px; }
.scroll::-webkit-scrollbar-track { background: var(--sunken); border-radius: 99px; }
.scroll::-webkit-scrollbar-thumb {
  background: var(--rule); border-radius: 99px; border: 3px solid var(--sunken);
}
.scroll::-webkit-scrollbar-thumb:hover { background: var(--muted); }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { padding: 6px 10px; text-align: right; white-space: nowrap;
         border-bottom: 1px solid var(--grid); }
th { position: sticky; top: 0; background: var(--surface); z-index: 2;
     font-weight: 600; color: var(--ink-2); font-size: 11px;
     text-transform: uppercase; letter-spacing: .05em; cursor: pointer; user-select: none; }
th.nosort { cursor: default; }
th[aria-sort] { color: var(--ink); }
th[aria-sort]::after { content: " \\2193"; }
th[aria-sort="ascending"]::after { content: " \\2191"; }
td.t, th.t { text-align: left; }
tbody tr:hover { background: var(--sunken); }
/* The first column stays put, so a row scrolled sideways still says whose it
   is. Its background has to be opaque and has to follow the hover state, or
   the columns underneath show through it. */
tbody td:first-child, thead th:first-child {
  position: sticky; left: 0; z-index: 1; background: var(--surface);
}
thead th:first-child { z-index: 3; }
tbody tr:hover td:first-child { background: var(--sunken); }
tbody td:first-child::after, thead th:first-child::after {
  content: ""; position: absolute; top: 0; right: -6px; bottom: -1px; width: 6px;
  background: linear-gradient(to right, var(--border), rgba(0,0,0,0));
  pointer-events: none;
}
td.num { font-variant-numeric: tabular-nums; }
.wrap td { white-space: normal; }
.wrap td:first-child { white-space: nowrap; color: var(--ink-2); width: 1%; }
.dim { color: var(--muted); }
.pos { color: var(--good); }
.neg { color: var(--bad); }
.chip { display: inline-block; font-size: 11px; padding: 1px 7px; border-radius: 99px;
        background: var(--sunken); color: var(--ink-2); border: 1px solid var(--border); }
.chip.strong { border-color: var(--good); color: var(--good); }
.chip.warn { border-color: var(--warn); color: var(--warn); }
.chip.fade { border-color: var(--bad); color: var(--bad); }
.chip.un { border-color: var(--rule); }
.rowcount { font-size: 12px; color: var(--muted); margin-top: 8px; }

/* A cell that carries a bar behind its number: the same value twice, so the
   figure stays readable and the shape is only there to be scanned. */
.barcell { position: relative; }
.barcell i {
  position: absolute; top: 3px; bottom: 3px; display: block; border-radius: 2px;
  background: var(--s1-soft);
}

@media (max-width: 700px) {
  main { padding: 12px; }
  .bar { gap: 10px; }
  .field, .field.wide { flex: 1 1 100%; max-width: none; }
  .field select, .field input[type=text] { width: 100%; }
  /* 44px of vertical hit area for the thumb, per the touch-target minimum. */
  .field input[type=range] { height: 44px; }
  .field input[type=range]::-webkit-slider-thumb { margin-top: -16px; }
  /* The header wraps to two or three rows on a phone, so a sticky tab strip
     pinned to a fixed offset lands on top of it. It scrolls away instead. */
  .tabs { position: static; }
}
"""

JS = r"""
// ── Formatting ──────────────────────────────────────────────────────────
const $ = (s, r) => (r || document).querySelector(s);
const el = (t, a, kids) => {
  const n = document.createElement(t);
  for (const k in (a || {})) {
    if (k === 'class') n.className = a[k];
    else if (k === 'html') n.innerHTML = a[k];
    else if (k === 'text') n.textContent = a[k];
    else if (a[k] != null) n.setAttribute(k, a[k]);
  }
  (kids || []).forEach(c => n.appendChild(c));
  return n;
};
const esc = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const has = v => v != null && !Number.isNaN(v);
const pct = (v, d) => has(v) ? (v * 100).toFixed(d == null ? 1 : d) + '%' : '';
const pp = (v, d) => has(v) ? (v >= 0 ? '+' : '') + v.toFixed(d == null ? 1 : d) : '';
const money = v => has(v) ? (v >= 0 ? '+$' : '-$') + Math.abs(v).toFixed(2) : '';
const american = o => {
  if (!has(o)) return '';
  const n = Math.round(o);
  return (n > 0 ? '+' : '') + n;
};
// Mirrors src/prediction/bets.decimal_to_american — a slip's price is the
// product of its legs' decimal odds, and readers want it back in American.
const decToAm = d => {
  const profit = d - 1;
  return profit >= 1 ? profit * 100 : -100 / profit;
};
// The inverse, over whatever a reader actually types. Every price on this page
// is displayed American, so a box that only accepted decimals was asking them
// to convert the one number they have in front of them.
//
// A sign always means American. Unsigned, the two notations cannot collide:
// American odds are never inside ±100 and a decimal price never reaches it, so
// 100 is the boundary rather than a guess. Below it, a decimal has to beat 1 —
// at evens or shorter there is no stake to win back.
const parsePrice = v => {
  const t = String(v == null ? '' : v).trim().replace(/[,\s$]/g, '');
  if (!t) return null;
  const x = parseFloat(t);
  if (!isFinite(x)) return null;
  if (/^[+-]/.test(t) || Math.abs(x) >= 100) {
    if (Math.abs(x) < 100) return null;
    return x > 0 ? 1 + x / 100 : 1 + 100 / Math.abs(x);
  }
  return x > 1 ? x : null;
};
// Both notations, so nothing on the page is only readable in the one the
// reader did not type.
const bothPrices = d => american(decToAm(d)) + ' (' + d.toFixed(2) + ')';
const cls = v => !has(v) ? '' : (v > 0 ? 'pos' : (v < 0 ? 'neg' : ''));

// ── State ───────────────────────────────────────────────────────────────
const S = {
  market: 0,
  tab: 'players',
  p: { game: '', q: '', depth: 0, priced: 'all', longshot: false, differ: false },
  // Five players, one per game. Five because 31 slips is the size the question
  // is usually asked at, and one-per-game because taking the top five from a
  // single fixture is usually five teammates — which correlates the legs and
  // guts the all-score tail.
  // `picked` fills from the top five on first render; after that it is
  // whatever the reader chose.
  // `dec` is the price the table uses; `decRaw` is what was typed to get it,
  // in either notation. They part company only while a price is half-entered.
  cover: { picked: null, stake: 1, dec: 2.0, decRaw: '+100', q: '', game: '',
           pricedOnly: false, open: true },
  // `priced` mirrors the master table's control and defaults the same way:
  // the whole slate. A priced-only default answered "what can I bet on"
  // while being read as "which players go together".
  // `likely` rather than `ev`, because expected value can only rank a slip
  // that carries a price and most of a slate does not: at 25 rows an
  // EV-ranked table is entirely priced, which is a priced-only table wearing a
  // different label. Likelihood is the one ranking every player has a number
  // for, so it is the one that opens.
  c: { legs: 2, per: 4, metric: 'likely', show: 25, game: '', priced: 'all' },
  t: { game: '' },
  sort: {},
};
const M = () => DATA.markets[S.market];

// ── Tables ──────────────────────────────────────────────────────────────
// `cols` is [{k, label, t?: 'text', fmt, cls, title, bar}]. Sorting is by the
// raw value, never the formatted string: "9.0%" sorts after "10.0%" as text.
function table(id, cols, rows, opts) {
  opts = opts || {};
  const st = S.sort[id];
  let data = rows.slice();
  if (st) {
    const c = cols.find(c => c.k === st.k);
    if (c) data.sort((a, b) => {
      let x = c.sortVal ? c.sortVal(a) : a[c.k], y = c.sortVal ? c.sortVal(b) : b[c.k];
      if (x == null) return 1; if (y == null) return -1;
      if (typeof x === 'string') return st.dir * String(x).localeCompare(String(y));
      return st.dir * (x - y);
    });
  }
  const thead = el('tr');
  cols.forEach(c => {
    const th = el('th', {
      class: (c.t ? 't ' : '') + (opts.nosort ? 'nosort' : ''),
      title: c.title || null, text: c.label,
    });
    if (st && st.k === c.k) th.setAttribute('aria-sort', st.dir > 0 ? 'ascending' : 'descending');
    if (!opts.nosort) th.onclick = () => {
      S.sort[id] = (st && st.k === c.k) ? { k: c.k, dir: -st.dir } : { k: c.k, dir: -1 };
      render();
    };
    thead.appendChild(th);
  });
  const tb = el('tbody');
  data.forEach(r => {
    const tr = el('tr');
    cols.forEach(c => {
      const v = r[c.k];
      const td = el('td', { class: (c.t ? 't' : 'num') + (c.cls ? ' ' + c.cls(v, r) : '') });
      if (c.bar && has(v)) {
        td.classList.add('barcell');
        const w = Math.max(0, Math.min(1, c.bar(v, r)));
        td.innerHTML = `<i style="left:2px;width:${(w * 100).toFixed(1)}%"></i>` +
          `<span style="position:relative">${c.fmt ? c.fmt(v, r) : esc(v)}</span>`;
      } else {
        td.innerHTML = c.fmt ? (c.fmt(v, r) || '') : esc(v);
      }
      tr.appendChild(td);
    });
    tb.appendChild(tr);
  });
  const wrap = el('div', { class: 'scroll' });
  const t = el('table', { class: opts.wrap ? 'wrap' : null });
  t.appendChild(el('thead', {}, [thead]));
  t.appendChild(tb);
  wrap.appendChild(t);
  return wrap;
}

function tiles(items) {
  return el('div', { class: 'tiles' }, items.filter(Boolean).map(i =>
    el('div', { class: 'tile', title: i.help || null }, [
      el('div', { class: 'k', text: i.k }),
      el('div', { class: 'v', text: i.v }),
      i.d ? el('div', { class: 'd', text: i.d }) : el('div', { class: 'd', text: ' ' }),
    ])));
}

function card(title, note, kids) {
  const c = el('div', { class: 'card' });
  if (title) c.appendChild(el('h2', { text: title }));
  if (note) c.appendChild(el('p', { class: 'note', html: note }));
  (kids || []).forEach(k => k && c.appendChild(k));
  return c;
}

function bar(fields) {
  return el('div', { class: 'bar' }, fields.filter(Boolean));
}
function select(label, value, options, onchange, title) {
  const s = el('select', { title: title || null });
  options.forEach(o => {
    const v = Array.isArray(o) ? o[0] : o, t = Array.isArray(o) ? o[1] : o;
    const opt = el('option', { value: v, text: t });
    if (String(v) === String(value)) opt.selected = true;
    s.appendChild(opt);
  });
  s.onchange = () => { onchange(s.value); render(); };
  return el('div', { class: 'field' }, [el('label', { text: label }), s]);
}
function text(label, value, onchange, placeholder) {
  // The label doubles as the field's identity across a re-render. Without it
  // the focus restore below grabs the first text input on the pane, so typing
  // into the third one throws the caret back into the first — which the cover
  // pane now has three of.
  const i = el('input', { type: 'text', value: value,
    placeholder: placeholder || '', 'data-k': label });
  let tmr;
  i.oninput = () => { clearTimeout(tmr); tmr = setTimeout(() => { onchange(i.value); render(true); }, 120); };
  const f = el('div', { class: 'field' }, [el('label', { text: label }), i]);
  f.dataset.focus = 'search';
  return f;
}
function check(label, value, onchange, disabled, title) {
  const i = el('input', { type: 'checkbox' });
  i.checked = !!value; i.disabled = !!disabled;
  i.onchange = () => { onchange(i.checked); render(); };
  const l = el('label', { class: 'check' + (disabled ? ' off' : ''), title: title || null }, [i]);
  l.appendChild(document.createTextNode(' ' + label));
  return l;
}
"""

JS_PLAYERS = r"""
// ── Pane: every player ──────────────────────────────────────────────────
function filteredPlayers() {
  const m = M(), f = S.p;
  let rows = m.players.slice();
  if (f.game) rows = rows.filter(p => p.game === f.game);
  if (f.q) {
    const q = f.q.toLowerCase();
    rows = rows.filter(p => (p.player || '').toLowerCase().includes(q));
  }
  if (f.priced === 'yes') rows = rows.filter(p => p.priced);
  if (f.priced === 'no') rows = rows.filter(p => !p.priced);
  if (f.depth) rows = rows.filter(p => p.rank <= f.depth);
  if (f.differ) rows = rows.filter(p => has(p.bet_edge) && Math.abs(p.bet_edge) >= m.min_edge);
  if (f.longshot && m.longshot) rows = rows.filter(p => has(p.odds_num) && p.odds_num >= m.longshot.min_odds);
  return rows;
}

function panePlayers() {
  const m = M(), f = S.p, out = el('div');
  const games = Array.from(new Set(m.players.map(p => p.game).filter(Boolean))).sort();
  const anyBest = m.players.some(p => p.best);
  const anyStatus = m.players.some(p => p.status);
  const anyBacking = m.players.some(p => p.backing);
  const blended = m.topk && m.topk.blended;

  out.appendChild(bar([
    select('Game', f.game, [['', 'All games']].concat(games.map(g => [g, g])), v => f.game = v),
    text('Search player', f.q, v => f.q = v, 'e.g. Barkley'),
    select('Show per game', f.depth, [[0, 'Everyone'], [10, 'Top 10'], [5, 'Top 5'], [3, 'Top 3'], [1, 'Top 1']],
      v => f.depth = +v, 'Ranked by # — our estimate within the game, over everyone listed.'),
    select('Prices', f.priced, [['all', 'Priced and unpriced'], ['yes', 'Priced only'], ['no', 'Unpriced only']],
      v => f.priced = v),
    check('Only where we differ', f.differ, v => f.differ = v, false,
      'Hide players we price within ' + m.min_edge + ' points of the bookmaker, measured on Bet edge — our own number, before the blend.'),
    // The gap is measured and moves, so the copy branches on it rather than
    // asserting an edge. On the 24-family model it fell to +0.019 with a 95%
    // interval of (-0.011, +0.049) — it no longer clears zero, and a filter
    // that still promised an edge would be the app's own retired claim
    // reappearing on a second surface.
    check('Longshot standouts', f.longshot, v => f.longshot = v, !m.longshot,
      !m.longshot ? 'Needs the longshot measurement — run scripts/12_longshot.py.'
      : ('Players priced at +' + m.longshot.min_odds + ' or longer, ours-highest first. ' +
         (has(m.longshot.auc_gap_lo) && m.longshot.auc_gap_lo <= 0
           ? 'Our ordering of that band (AUC ' + m.longshot.auc_ours.toFixed(2) +
             ') is not distinguishable from the price’s (' + m.longshot.auc_book.toFixed(2) +
             ') — the interval on the gap includes zero. Read this as a way to see the band, not as an edge in it.'
           : 'Inside that band our ordering sorts scorers better than the price does (AUC ' +
             m.longshot.auc_ours.toFixed(2) + ' against ' + m.longshot.auc_book.toFixed(2) +
             '). It says which longshots are live, not which are cheap.'))),
  ]));

  const rows = filteredPlayers();
  const cols = [
    { k: 'player', label: 'Player', t: 1, fmt: (v, r) => esc(v) + (r.blocked ? ' <span class="chip fade">out</span>' : '') },
    { k: 'team', label: 'Team', t: 1 },
    { k: 'game', label: 'Game', t: 1 },
    { k: 'odds', label: 'Odds', t: 1, sortVal: r => r.odds_num,
      fmt: v => v || '<span class="dim">—</span>',
      title: 'The bookmaker’s posted price. Blank where no book has quoted this player.' },
    anyBest ? { k: 'best', label: 'Best price', t: 1,
      fmt: (v, r) => v ? esc(v) + ' <span class="dim">' + esc(r.best_book || '') + '</span>' : '',
      title: 'The longest price across the books we archived this week. Nobody can bet a consensus.' } : null,
    { k: 'rank', label: '#', title: 'Where this player sits on our list for their game, over everyone shown — priced and unpriced alike.' },
    { k: 'priced_rank', label: 'Priced #', fmt: v => has(v) ? v : '<span class="dim">—</span>',
      title: 'The board’s own ladder, over priced players only. It is the one the historical column beside it is keyed on.' },
    { k: 'at_rank', label: 'Typical at #', fmt: v => has(v) ? pct(v, 0) : '<span class="dim">—</span>',
      title: 'What actually happened to players in that priced slot across the backtested seasons. A second opinion on the row: if our estimate sits well above or below it, the model may be running hot or cold at this rank rather than knowing something about this player. Blank for unpriced rows — it was never measured on them.' },
    { k: 'ours', label: 'Our estimate',
      fmt: (v, r) => pct(v, 0) + (r.priced ? '' : '<sup class="dim" title="Unblended — no book has priced this player, so there is nothing to blend toward">\u2020</sup>'),
      title: 'Our estimated chance this player scores. On priced rows it is blended with the bookmaker, which is what makes it better calibrated; on unpriced rows there is no price to blend toward, so it is the model’s raw number.' },
    blended ? { k: 'model_only', label: 'Model only', fmt: v => pct(v, 0),
      title: 'Our number before the blend. The right column for judging a bet, where the disagreement with the price is the whole point — and the wrong one for judging who is likely to score.' } : null,
    { k: 'book', label: 'Bookmaker says', fmt: v => has(v) ? pct(v, 0) : '<span class="dim">—</span>',
      title: 'The bookmaker’s own estimate with their margin removed, so both columns measure the same thing.' },
    { k: 'diff', label: 'Difference', fmt: v => has(v) ? pp(v) + ' pts' : '', cls: v => cls(v),
      title: 'How far our estimate sits above (+) or below (−) the bookmaker’s. A big number is where the value would be — and also where we are least reliable.' },
    { k: 'read', label: 'Our read', t: 1, fmt: v => v ? '<span class="chip">' + esc(v) + '</span>' : '',
      title: 'Matches book / Leans / Strong call, cut at the 33rd and 66th percentile of how far this model typically sits from the price.' },
    blended ? { k: 'bet_rank', label: 'Bet #', fmt: v => has(v) ? v : '<span class="dim">—</span>',
      title: 'Our ranking before the bookmaker’s price is mixed in. # is the one to read for who scores; this is the one the money was measured on.' } : null,
    blended ? { k: 'bet_edge', label: 'Bet edge', fmt: v => has(v) ? pp(v) + ' pts' : '', cls: v => cls(v),
      title: 'The same comparison as Difference on our pre-blend number. The blend pulls our estimate toward the price it is being compared against, so Difference comes out smaller — this is the column every profitability figure was measured on.' } : null,
    { k: 'ev', label: 'Expected on $100', fmt: v => has(v) ? money(v) : '', cls: v => cls(v),
      title: 'What a flat $100 returns on average if our number is right, at the price in Odds. A +3 point edge at −185 still loses; the same +3 at +170 makes money.' },
    anyBacking ? { k: 'backing', label: 'Worth backing', t: 1,
      fmt: v => v ? '<span class="chip ' + (v === 'Fade' ? 'fade' : 'strong') + '">' + esc(v) + '</span>' : '' } : null,
    anyStatus ? { k: 'status', label: 'Injury', t: 1, fmt: v => v ? '<span class="chip fade">' + esc(v) + '</span>' : '' } : null,
  ].filter(Boolean);

  const priced = rows.filter(p => p.priced).length;
  out.appendChild(card(null, null, [
    table('players', cols, rows.length ? rows : [], {}),
    el('p', { class: 'rowcount', text:
      rows.length + ' of ' + m.players.length + ' players — ' + priced + ' priced, ' +
      (rows.length - priced) + ' with no price posted. Click a heading to sort.' }),
  ]));

  if (rows.some(p => !p.priced)) out.appendChild(el('div', { class: 'warn-box', html:
    '<b>Rows with no odds are not on the same footing as the rest.</b> Their estimate is marked \u2020 and is <i>unblended</i> — there is no price to pull it toward, and every priced row has been — so the two are not comparable at face value. ' +
    '<b>Priced #</b>, <b>Typical at #</b> and every accuracy figure on this page were measured on priced players only; extending them here would be an extrapolation, so they are blank rather than filled in.' }));
  return out;
}
"""

JS_COMBOS = r"""
// ── Pane: combinations ──────────────────────────────────────────────────
// The board prices one player. This answers the question it provokes: what if
// two or three of them go on one slip. Nothing is refitted — every number is
// the players' own columns multiplied out.
//
// Built here rather than in the export because the answer depends on five
// controls at once: 128 eligible players is 10.7 million four-leg slips, which
// is not a file anyone can download and is a loop the browser finishes in well
// under a second.
//
// **Every rated player is eligible, priced or not.** Three weeks before a
// season opens four games of sixteen carry a price, so a priced-only search
// answers "what can I bet on" while being read as "which players go together".
// A slip touching an unpriced leg has no odds, no bookmaker number and no
// expected value — those cells are blank, because there is no price to compute
// them from, and blank is the honest answer rather than a reason to hide the
// row.
const READ_ORDER = ['Matches book', 'Leans', 'Strong call'];

//: How many candidate legs the search keeps, by slip length. Combinations grow
//: as C(n, legs), so the pool is cut to its strongest legs first. That cut
//: cannot change the answer while `keep >= show + legs`: every metric here is a
//: product of positive per-leg factors, so a slip using a leg ranked below the
//: cut is beaten by at least `show` slips built from the legs above it. Where
//: it does bind, the caption says so rather than letting a bounded search read
//: as an exhaustive one.
const LEG_CAP = { 2: 400, 3: 140, 4: 64 };

//: Each game's top `per` by the board's own #, over whichever population is
//: asked for. Ranked within the game before the cut, so widening `per` reaches
//: further down every game rather than deeper into one.
function comboPool(players, per, game, pricedOnly) {
  let pool = players.filter(p => has(p.ours) && !p.blocked);
  if (game) pool = pool.filter(p => p.game === game);
  if (pricedOnly) pool = pool.filter(p => p.priced);
  const byGame = {};
  pool.forEach(p => { (byGame[p.game] = byGame[p.game] || []).push(p); });
  let picked = [];
  Object.keys(byGame).forEach(g => {
    byGame[g].sort((a, b) => b.ours - a.ours);
    picked = picked.concat(byGame[g].slice(0, per));
  });
  return picked;
}

//: The pool cut to its strongest legs under `factor`, which is the ordering the
//: truncation argument above is stated in. Tie-broken by name: two legs can
//: price to exactly the same factor, and an unstable sort would then reorder
//: them on every rebuild.
function comboCandidates(picked, legs, factor) {
  const sorted = picked.slice().sort(
    (a, b) => (factor(b) - factor(a)) || a.player.localeCompare(b.player));
  return sorted.slice(0, Math.min(sorted.length, LEG_CAP[legs] || 64));
}

//: Every slip of `legs` from `cand`, with its five quantities multiplied out.
//: `priced` is false the moment one leg has no quote, and everything that needs
//: a price is null from there — the product of a number and a blank is a blank,
//: not a smaller number.
function comboSearch(cand, legs, singleWinner) {
  const n = cand.length, out = [];
  if (n < legs) return out;
  const idx = new Array(legs);
  const gameOf = cand.map(p => p.game);
  (function walk(start, depth) {
    if (depth === legs) {
      let same = false;
      for (let a = 0; a < legs && !same; a++)
        for (let b = a + 1; b < legs; b++)
          if (gameOf[idx[a]] === gameOf[idx[b]]) { same = true; break; }
      if (singleWinner && same) return;
      let ours = 1, mo = 1, book = 1, dec = 1, priced = true;
      for (let i = 0; i < legs; i++) {
        const p = cand[idx[i]];
        ours *= p.ours;
        mo *= has(p.model_only) ? p.model_only : p.ours;
        if (p.priced && has(p.book) && has(p.dec)) { book *= p.book; dec *= p.dec; }
        else priced = false;
      }
      out.push({ ps: idx.map(i => cand[i]), ours: ours, mo: mo,
                 book: priced ? book : null, dec: priced ? dec : null,
                 ev: priced ? (mo * dec - 1) * 100 : null,
                 same: same, priced: priced });
      return;
    }
    for (let i = start; i <= n - (legs - depth); i++) { idx[depth] = i; walk(i + 1, depth + 1); }
  })(0, 0);
  return out;
}

function buildCombos() {
  const m = M(), c = S.c;
  const legs = +c.legs, per = +c.per, showN = +c.show, ev = c.metric === 'ev';
  const singleWinner = m.key === 'first_td';
  const pricedOnly = c.priced === 'yes';

  // Expected value and likelihood are ranked over different candidate
  // orderings, and the truncation above is only safe within one of them: the
  // best-value slip can be built from long-priced legs that rank nowhere on
  // likelihood. So an EV table with unpriced players in it is two searches, not
  // one weakened search — the priced pool ordered by value, then the whole
  // slate ordered by likelihood for the slips value cannot score. Each half is
  // exact under its own metric, which a single blended ordering would not be.
  let scored = [], unscored = [], nPool = 0, nCand = 0, searched = 0, bounded = false;

  const rank = (pool, factor) => {
    const cand = comboCandidates(pool, legs, factor);
    nPool = Math.max(nPool, pool.length);
    nCand = Math.max(nCand, cand.length);
    if (cand.length < pool.length && cand.length < showN + legs) bounded = true;
    return cand;
  };

  if (ev) {
    const priced = comboPool(m.players, per, c.game, true);
    const found = comboSearch(rank(priced, p => p.model_only * p.dec), legs, singleWinner);
    searched += found.length;
    scored = found.filter(r => r.priced).sort((a, b) => b.ev - a.ev);
  }
  if (!ev || !pricedOnly) {
    const all = comboPool(m.players, per, c.game, pricedOnly);
    const found = comboSearch(rank(all, p => p.ours), legs, singleWinner);
    searched += found.length;
    // Under EV this pass exists only to reach the slips the first pass could
    // not price; its priced rows are already above, ranked properly.
    unscored = (ev ? found.filter(r => !r.priced) : found)
      .sort((a, b) => b.ours - a.ours);
  }

  const rows = scored.concat(unscored).slice(0, showN).map(r => {
    // A slip inherits the weakest read its legs carry, and a leg nobody priced
    // is weaker than "Matches book" — we have not disagreed with the market
    // about that player, we have no market to disagree with. Filtering the
    // blanks out and reducing what was left let one priced leg's "Strong call"
    // become the verdict for a slip whose other leg we had said nothing about.
    const reads = r.ps.map(p => p.read);
    const readable = r.ps.every(p => READ_ORDER.indexOf(p.read) >= 0);
    const tiers = r.ps.map(p => p.backing || '');
    const gs = Array.from(new Set(r.ps.map(p => p.game)));
    return {
      players: r.ps.map(p => p.player).join(' + '),
      game: gs.length === 1 ? gs[0] : gs.length + ' games',
      odds: r.dec ? american(decToAm(r.dec)) : null,
      ours: r.ours, mo: r.mo, book: r.book,
      diff: r.book != null ? (r.ours - r.book) * 100 : null,
      read: readable ? READ_ORDER[Math.min.apply(null, reads.map(x => READ_ORDER.indexOf(x)))] : '',
      backing: tiers.some(t => t) ? tiers.map(t => t || '—').join(' + ') : '',
      ev: r.ev, same: r.same, priced: r.priced,
    };
  });
  return { rows: rows, nPool: nPool, nCand: nCand, total: searched,
           bounded: bounded, legs: legs,
           nScored: Math.min(scored.length, showN),
           nUnpriced: rows.filter(r => !r.priced).length };
}

// The graded replay is a priced-only measurement — `scripts/29_combos.py`
// replays slips that had closing prices to settle against. It is only quoted
// where the table on screen is that same population, because a strip describing
// 1,593 priced slips sitting above a table that is mostly unpriced ones is a
// number attached to the wrong rows.
function comboRecord() {
  const m = M(), c = S.c;
  if (!m.combo_record || !m.combo_record.rows) return null;
  if (c.priced !== 'yes') return null;
  return m.combo_record.rows.find(r =>
    r.legs === +c.legs && r.per_game === +c.per &&
    r.metric === (c.metric === 'ev' ? 'ev' : 'likely') && r.show === +c.show) || null;
}

function paneCombos() {
  const m = M(), c = S.c, out = el('div');
  const games = Array.from(new Set(m.players.map(p => p.game).filter(Boolean))).sort();
  const ev = c.metric === 'ev';

  out.appendChild(bar([
    select('Legs', c.legs, [[2, '2'], [3, '3'], [4, '4']], v => c.legs = +v,
      'How many players on the slip. Each one lengthens the price and shortens the chance, and both move faster than they look: three 40% legs is a 6% shot.'),
    select('From each game’s top', c.per, [2, 3, 4, 5, 6, 7, 8], v => c.per = +v,
      'Which players are eligible: each game’s top N by #. Widening this reaches further down every game rather than deeper into one.'),
    select('Rank by', c.metric, [['likely', 'Most likely'], ['ev', 'Expected value']], v => c.metric = v,
      'Most likely ranks on the chance the slip lands, which every player has a number for. Expected value ranks on what $100 expects to return — it needs a price, so it can only order the slips that carry one, and the rest follow it by likelihood. Different questions and usually different tables: the likeliest slips are short-priced and the best value ones are not.'),
    select('Show', c.show, [25, 50, 100, 250, 500], v => c.show = +v),
    select('Game', c.game, [['', 'All games']].concat(games.map(g => [g, g])), v => c.game = v),
    select('Players', c.priced, [['all', 'Priced and unpriced'], ['yes', 'Priced only']],
      v => c.priced = v,
      'The whole slate by default. A slip touching a player no book has quoted carries no odds, no bookmaker number and no expected value — there is nothing to compute them from — so those cells are blank. Priced only narrows it to the games a book has posted, which is also the population the graded replay covers.'),
  ]));

  const rec = comboRecord();
  if (rec) {
    out.appendChild(card('This exact setting, replayed and graded',
      'Every slip these controls would have shown, replayed week by week over ' +
      esc(m.combo_record.span) + ' and graded on results. It sits above the table because it is the context for reading any row: a table of expected values built on a probability that runs hot is a table of fiction, and <b>Landed</b> against <b>We said</b> is the only thing that says which.',
      [tiles([
        { k: 'Slips graded', v: rec.slips.toLocaleString(), d: rec.weeks + ' weeks' },
        { k: 'Landed', v: pct(rec.landed), d: 'every leg scored' },
        { k: 'We said', v: pct(rec.we_said), d: pp((rec.landed - rec.we_said) * 100) + ' pts vs landed' },
        { k: 'Book said', v: pct(rec.book_said), d: 'their de-vigged prices' },
        { k: 'Return per $100', v: money(rec.return_per_100),
          d: has(rec.return_ex_top10) ? money(rec.return_ex_top10) + ' without the 10 biggest wins' : '' },
        { k: 'As singles', v: money(rec.as_singles_per_100), d: 'same money, staked separately' },
      ])]));
  } else if (m.combo_record && c.priced !== 'yes') {
    out.appendChild(el('div', { class: 'warn-box', html:
      '<b>The graded replay covers priced slips only</b> — it settles against closing prices, and most of this table has none. Set <b>Players</b> to <i>Priced only</i> to see what these settings actually returned over ' +
      esc(m.combo_record.span) + '.' }));
  } else if (m.combo_record) {
    // Not a stale file: the replay is a fixed grid and these controls reach
    // outside it on purpose, because "show me more than fifty" is a reasonable
    // thing to ask and a graded number for it does not exist. Say which grid,
    // so the way back to a measured setting is on screen.
    const g = m.combo_record.rows;
    const uniq = k => Array.from(new Set(g.map(r => r[k]))).sort((a, b) => a - b);
    const rng = k => { const u = uniq(k); return u[0] + '–' + u[u.length - 1]; };
    out.appendChild(el('div', { class: 'warn-box', html:
      '<b>This setting has not been graded.</b> The replay covers legs ' + rng('legs') +
      ', top ' + rng('per_game') + ' from each game and ' + rng('show') +
      ' rows — the controls deliberately reach past it, and a measured number for a ' +
      'setting nobody replayed does not exist. Move back inside that grid to see one, ' +
      'or extend the sweep in <code>scripts/29_combos.py</code>.' }));
  }

  const r = buildCombos();
  const blended = m.topk && m.topk.blended;
  const anyBacking = r.rows.some(x => x.backing);
  const cols = [
    { k: 'players', label: 'Players', t: 1,
      title: 'Every one of these has to score for the slip to pay. That is the whole difference between this table and the board.' },
    { k: 'game', label: 'Game', t: 1, fmt: (v, x) => esc(v) + (x.same ? ' <span class="chip warn">same game</span>' : '') },
    { k: 'odds', label: 'Odds', t: 1, fmt: v => v || '<span class="dim">—</span>' },
    { k: 'ours', label: 'Our estimate', fmt: v => pct(v, v < 0.05 ? 2 : 1) },
    blended ? { k: 'mo', label: 'Model only', fmt: v => pct(v, v < 0.05 ? 2 : 1) } : null,
    { k: 'book', label: 'Bookmaker says', fmt: v => has(v) ? pct(v, v < 0.05 ? 2 : 1) : '<span class="dim">—</span>' },
    { k: 'diff', label: 'Difference', fmt: v => has(v) ? pp(v) + ' pts' : '', cls: v => cls(v) },
    { k: 'read', label: 'Our read', t: 1, fmt: v => v ? '<span class="chip">' + esc(v) + '</span>' : '',
      title: 'The weakest read its legs carry. Not the average and not the strongest: a slip needs all of them, so the leg we have least to say about is the one that decides what it is. Blank where no leg carries a read, which is any slip with an unpriced player on it.' },
    { k: 'ev', label: 'Expected on $100', fmt: v => has(v) ? money(v) : '<span class="dim">—</span>', cls: v => cls(v) },
    anyBacking ? { k: 'backing', label: 'Worth backing', t: 1,
      title: 'Each leg’s own tier, in the order the slip names its players. Never one tier for the slip: the tiers were fitted on single bets.' } : null,
  ].filter(Boolean);

  const legWord = { 2: 'two', 3: 'three', 4: 'four' }[r.legs];
  const where = c.game || 'every game on the slate';
  out.appendChild(card(null, null, [
    r.rows.length ? table('combos', cols, r.rows, {}) : el('p', { class: 'note', html:
      (m.key === 'first_td' && c.game)
        ? '<b>One game has no combinations on this market.</b> Exactly one player scores a game’s first touchdown, so two legs from the same game cannot both land. Choose <b>All games</b> to combine across the slate.'
        : 'Not enough eligible players here to build a combination.' }),
    el('p', { class: 'rowcount', html:
      r.rows.length
        ? 'The ' + r.rows.length + ' best ' + legWord + '-leg combinations of the top ' + c.per +
          ' in ' + esc(where) + ', out of ' + (r.total || 0).toLocaleString() +
          ' searched from ' + r.nCand + ' of the ' + r.nPool + ' eligible players. ' +
          (ev && r.nUnpriced
            ? '<b>' + r.nScored + '</b> carry a price and are ranked by expected value; the ' +
              'remaining <b>' + r.nUnpriced + '</b> have an unpriced leg, so there is no expected ' +
              'value to rank them on and they follow, ordered by how likely they are to land.'
            : 'Ranked by ' + (ev ? 'expected value' : 'how likely the slip is to land') + '.') +
          (r.bounded ? ' <b>The search was bounded here</b>: at ' + r.legs +
            ' legs the pool is cut to its ' + r.nCand + ' strongest, which is fewer than the ' +
            (+c.show + r.legs) + ' that would guarantee this is the exact top ' + c.show +
            '. Lower <b>Show</b> or narrow <b>From each game’s top</b> for an exact answer.' : '')
        : '' }),
  ]));

  const notes = [];
  if (m.key === 'first_td') {
    notes.push('Legs on this market always come from different games — one player scores a game’s first touchdown, so two legs from one game cannot both land — which means multiplying them assumes only that separate games are independent of each other.');
  } else {
    notes.push('Legs are multiplied as if independent. Teammates share a scoring game and compete for the same touchdowns, and in the backtest those very nearly cancel; same-game rows are flagged above because a book prices its own correlation into them and will come back shorter than this arithmetic.');
  }
  if (r.nUnpriced) notes.push(
    '<b>' + r.nUnpriced + ' of these rows touch a player no book has quoted.</b> Their odds, bookmaker number, difference and expected value are blank because there is no price to compute them from — the absence of a quote, not of an opinion. Their <b>Our estimate</b> is also a product of unblended legs, so it is not on the same footing as a fully priced row’s.');
  notes.push(rec
    ? 'The strip above is this exact setting replayed over ' + esc(m.combo_record.span) +
      '. The <b>Expected on $100</b> column is still a forecast rather than that measurement.'
    : 'Nothing in this table has been backtested at this setting: every profitability figure in this project was measured on single bets at closing prices, and multiplying legs multiplies the model’s calibration error along with them.');
  out.appendChild(el('div', { class: 'warn-box', html: notes.join(' ') }));
  return out;
}
"""

JS_TEAMS = r"""
// ── Pane: by team ───────────────────────────────────────────────────────
// ── Cover the field ─────────────────────────────────────────────────────
// Pick players, back every combination of them, and see what each number of
// scorers returns. The legs are chosen here rather than precomputed, so the
// arithmetic runs in the page: 2^n patterns for n up to 12 is at most 4,096
// rows of a dot product, which is nothing.
//
// The closed forms this must satisfy are the same ones `tests/test_cover.py`
// holds the Python to — k scorers win 2^k - 1 slips and, at a flat price d,
// return (1+d)^k - 1 — so the two implementations are pinned to a third thing
// rather than to each other.
function coverPortfolio(legs, stake, rho, assumedDec) {
  const n = legs.length, N = 1 << n;
  const p = legs.map(l => l.prob);
  const dec = legs.map(l => has(l.dec) ? l.dec : assumedDec);

  // Pattern probabilities. Teammate pairs only: the measured correlation is a
  // team-game effect and applying it across fixtures inflates the tail.
  const bits = [], prob = new Array(N);
  for (let m = 0; m < N; m++) {
    const b = [];
    let q = 1;
    for (let i = 0; i < n; i++) { const on = (m >> i) & 1; b.push(on); q *= on ? p[i] : 1 - p[i]; }
    bits.push(b); prob[m] = q;
  }
  if (rho) {
    let tot = 0;
    for (let m = 0; m < N; m++) {
      const z = bits[m].map((on, i) => (on - p[i]) / Math.sqrt(Math.max(p[i] * (1 - p[i]), 1e-9)));
      let pair = 0;
      for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++)
        if (legs[i].team && legs[i].team === legs[j].team) pair += z[i] * z[j];
      prob[m] *= Math.exp(rho * pair); tot += prob[m];
    }
    for (let m = 0; m < N; m++) prob[m] /= tot;
  }

  // Every non-empty subset is a slip; it pays when all its legs are in the
  // pattern.
  const ret = new Array(N).fill(0), wins = new Array(N).fill(0);
  let slips = 0;
  for (let mask = 1; mask < N; mask++) {
    slips++;
    let payout = stake;
    for (let i = 0; i < n; i++) if ((mask >> i) & 1) payout *= dec[i];
    for (let m = 0; m < N; m++) if ((m & mask) === mask) { ret[m] += payout; wins[m]++; }
  }
  const staked = stake * slips;

  const kOf = m => bits[m].reduce((a, b) => a + b, 0);
  const rows = [];
  for (let k = 0; k <= n; k++) {
    let w = 0, r = 0, lo = Infinity, hi = -Infinity, nb = 0;
    for (let m = 0; m < N; m++) if (kOf(m) === k) {
      w += prob[m]; r += ret[m] * prob[m];
      lo = Math.min(lo, ret[m]); hi = Math.max(hi, ret[m]); nb = wins[m];
    }
    const avg = w > 0 ? r / w : lo;
    rows.push({ scored: k, winning_bets: nb, probability: w,
                returned: avg, returned_min: lo, returned_max: hi,
                net: avg - staked });
  }
  let ev = 0;
  for (let m = 0; m < N; m++) ev += (ret[m] - staked) * prob[m];
  const perSingle = staked / n;
  let evSingles = 0;
  for (let i = 0; i < n; i++) evSingles += perSingle * (dec[i] * p[i] - 1);

  const be = rows.find(r => r.net > 0);
  return {
    n: n, stake: stake, bets: slips, staked: staked, rho: rho, rows: rows,
    all_priced: legs.every(l => has(l.dec)), assumed_decimal: assumedDec,
    priced: legs.filter(l => has(l.dec)).length,
    expected_net: ev, expected_roi: staked ? ev / staked : 0,
    breakeven_scored: be ? be.scored : null,
    p_breakeven: rows.filter(r => r.net > 0).reduce((a, r) => a + r.probability, 0),
    singles_net: evSingles, singles_roi: staked ? evSingles / staked : 0,
  };
}

// The opening five: the best player in each of five different games. The state
// comment has said "one per game" since this pane shipped while the code took
// the top five overall, which on a busy slate is often five men in one fixture
// — legs that correlate, and a joint tail the independence in the table below
// would badly overstate. This is the comment made true.
function coverDefault(pool, n) {
  const seen = {}, out = [];
  for (const r of pool) {
    const g = r.game || r.player;
    if (seen[g]) continue;
    seen[g] = 1;
    out.push(r.player);
    if (out.length >= n) break;
  }
  return out;
}

function coverToggle(name) {
  const at = S.cover.picked.indexOf(name);
  if (at >= 0) S.cover.picked.splice(at, 1);
  else S.cover.picked.push(name);
  render(true);
}

// The picker: what is chosen, then how to change it, then everyone who could
// be chosen. Forty checkboxes in a wrapped row made those three things one
// thing — the reader had to re-scan the whole list to answer "who is in?",
// and anyone outside the top forty could not be picked at all.
function coverPicker(pool, blended, extra) {
  const f = S.cover;
  const inSet = {};
  f.picked.forEach(n => { inSet[n] = 1; });

  const chips = f.picked.map(name => {
    const r = pool.find(p => p.player === name);
    const b = el('button', { class: 'pchip', type: 'button',
      title: 'Remove ' + name });
    b.innerHTML = esc(name) +
      (r ? ' <i>' + pct(r.ours, 0) + '</i>' : '') + ' <span>×</span>';
    b.onclick = () => coverToggle(name);
    return b;
  });
  const clear = el('button', { class: 'pchip ghost', type: 'button',
    text: 'Clear all' });
  clear.onclick = () => { f.picked = []; render(true); };
  const five = el('button', { class: 'pchip ghost', type: 'button',
    text: 'Top 5, one per game',
    title: 'The best player in each of five different games.' });
  five.onclick = () => { f.picked = coverDefault(pool, 5); render(true); };
  const fold = el('button', { class: 'pchip ghost', type: 'button',
    text: f.open ? 'Hide the list' : 'Choose players',
    title: 'The list of everyone who could go in. Collapsing it puts the '
         + 'table below on screen without scrolling.' });
  fold.onclick = () => { f.open = !f.open; render(true); };

  const picked = el('div', { class: 'picked' }, [
    el('div', { class: 'picked-h', html:
      '<b>' + f.picked.length + '</b> selected' +
      (f.picked.length >= 2
        ? ' — <b>' + (Math.pow(2, f.picked.length) - 1).toLocaleString() +
          '</b> slips'
        : '') }),
    el('div', { class: 'chips' },
      chips.concat(f.picked.length ? [clear, five, fold] : [five, fold])),
  ]);

  // Collapsed, the filters go with the list they filter — but the stake and
  // the assumed price drive the table below, so they stay either way.
  if (!f.open) {
    return el('div', { class: 'picker' }, [picked, bar(extra)]);
  }

  const games = Array.from(new Set(pool.map(r => r.game).filter(Boolean))).sort();
  const controls = bar([
    text('Search', f.q, v => { f.q = v; }, 'name'),
    select('Game', f.game, [['', 'All games']].concat(games.map(g => [g, g])),
      v => { f.game = v; }),
    check('Priced only', f.pricedOnly, v => { f.pricedOnly = v; }, false,
      'Hide players no book has posted a price for.'),
  ].concat(extra));

  let rows = pool;
  if (f.q) {
    const q = f.q.toLowerCase();
    rows = rows.filter(r => (r.player || '').toLowerCase().includes(q));
  }
  if (f.game) rows = rows.filter(r => r.game === f.game);
  if (f.pricedOnly) rows = rows.filter(r => r.priced);
  const total = rows.length;
  rows = rows.slice(0, 60);

  const grid = el('div', { class: 'ppick' }, rows.map(r => {
    const on = !!inSet[r.player];
    // The second line is where a priced player earns the extra ink: the three
    // numbers that disagree. `ours` is what the card leads with because it is
    // what the table below computes from; `model` is that number before the
    // blend and `book` is the price de-vigged, and the gap between those two
    // is the only thing on this card that is an argument for a bet rather
    // than a description of a player.
    //
    // An unpriced player has neither, and `ours` is then the model's own
    // number — so repeating it as `model` would dress a single estimate up as
    // two agreeing ones. It says `no price` instead, which is the fact.
    const det = [];
    if (blended && r.priced && has(r.model_only)) {
      det.push('model ' + pct(r.model_only, 0));
    }
    if (has(r.book)) det.push('book ' + pct(r.book, 0));
    const b = el('button', {
      class: 'ppick-i' + (on ? ' on' : ''), type: 'button',
      'aria-pressed': on ? 'true' : 'false',
      title: [r.player, r.game, r.priced ? 'priced ' + r.odds : 'no price',
              'ours ' + pct(r.ours, 1),
              blended && has(r.model_only) ? 'model only ' + pct(r.model_only, 1) : null,
              has(r.book) ? 'bookmaker ' + pct(r.book, 1) : null,
             ].filter(Boolean).join(' · '),
    });
    // The detail line spans both columns rather than sitting in the right one.
    // In a two-column cell it set the column width for the whole card, and
    // `model 59% · book 48%` is wider than a name — so every player on a
    // priced card lost their surname to an ellipsis.
    b.innerHTML =
      '<span class="n">' + esc(r.player) + '</span>' +
      '<span class="v">' + pct(r.ours, 0) + '</span>' +
      '<span class="d"><span>' + esc(r.team || '') +
        (r.priced ? ' · ' + esc(r.odds) : '') + '</span><span>' +
        (det.length ? det.join(' · ') : 'no price') + '</span></span>';
    b.onclick = () => coverToggle(r.player);
    return b;
  }));

  const out = el('div', { class: 'picker' }, [picked, controls, grid]);
  if (!total) {
    out.appendChild(el('div', { class: 'warn-box',
      text: 'No player matches that filter.' }));
  } else if (total > rows.length) {
    out.appendChild(el('p', { class: 'fine', text:
      'Showing the ' + rows.length + ' likeliest of ' + total +
      ' — search or pick a game to reach the rest.' }));
  }
  return out;
}

function paneCover() {
  const m = M();
  const cov = m.cover || {};
  const pool = (m.players || [])
    .filter(r => has(r.ours))
    .slice()
    .sort((a, b) => b.ours - a.ours);

  if (!S.cover.picked) S.cover.picked = coverDefault(pool, 5);
  const chosen = pool.filter(r => S.cover.picked.indexOf(r.player) >= 0);

  // No `render()` in these callbacks: `text` re-renders for itself, with the
  // focus restore, and a second render nested inside the change handler tore
  // the field out from under the caret first — so a stake typed one digit at a
  // time lost focus on the first keystroke.
  const money2 = [
    text('Stake per slip', String(S.cover.stake),
      v => { const x = parseFloat(v); if (x > 0) S.cover.stake = x; }),
    // What was typed is held as typed, and the parsed price beside it. Parsing
    // into the field's own value would rewrite `-2` to something else on the
    // keystroke before `-200`, which is a box that fights the person using it.
    text('Assumed price if unpriced', S.cover.decRaw,
      v => { S.cover.decRaw = v;
             const d = parsePrice(v);
             if (d) S.cover.dec = d; },
      '+120 or 2.20'),
  ];
  const boxes = coverPicker(pool, m.topk && m.topk.blended, money2);

  const kids = [
    el('p', { class: 'muted', html:
      'Pick players and back every combination of them \u2014 <b>n</b> players ' +
      'is <b>2\u207f \u2212 1</b> slips, so five is 31. The table is what each ' +
      'number of scorers returns.' }),
    boxes,
  ];

  // Half-typed prices are normal and silent; a finished one that means nothing
  // has to say so, or the table quietly answers a different question from the
  // one on screen.
  if (S.cover.decRaw && !parsePrice(S.cover.decRaw)) {
    kids.push(el('div', { class: 'warn-box', html:
      '<b>' + esc(S.cover.decRaw) + '</b> is not a price. Type American \u2014 ' +
      '<b>+120</b>, <b>-200</b> \u2014 or decimal, <b>2.20</b>. Still using ' +
      bothPrices(S.cover.dec) + '.' }));
  }

  if (chosen.length < 2) {
    kids.push(el('div', { class: 'warn-box', text: 'Pick at least two players.' }));
    return card('Cover the field', '', kids);
  }
  if (chosen.length > (cov.max_players || 12)) {
    kids.push(el('div', { class: 'warn-box bad-box', html:
      '<b>' + chosen.length + ' players is ' +
      (Math.pow(2, chosen.length) - 1).toLocaleString() + ' slips.</b> ' +
      (cov.max_players || 12) + ' is the most this will enumerate.' }));
    return card('Cover the field', '', kids);
  }

  const legs = chosen.map(r => ({
    name: r.player, team: r.team, prob: r.ours,
    dec: r.priced && has(r.dec) ? r.dec : null,
  }));
  const v = coverPortfolio(legs, S.cover.stake, cov.rho || 0, S.cover.dec);

  kids.push(el('p', { class: 'muted', html:
    '<b>' + v.bets + ' slips</b> on ' + v.n + ' players at $' +
    v.stake.toFixed(2) + ' each, <b>$' + v.staked.toFixed(2) + '</b> staked. ' +
    (v.all_priced ? 'All ' + v.n + ' legs priced by the book.'
      : v.priced + ' of ' + v.n + ' legs priced; the rest at an assumed ' +
        bothPrices(v.assumed_decimal) + '.') }));

  const cols = [
    { k: 'who', label: 'Players who score', t: 1 },
    { k: 'chance', label: 'Chance of this', fmt: x => pct(x, 1) },
    { k: 'wins', label: 'Winning bets' },
    { k: 'ret', label: 'Total returned', fmt: x => '$' + x.toFixed(2) },
    { k: 'net', label: 'Net on $' + v.staked.toFixed(2),
      fmt: x => money(x), cls: x => cls(x) },
  ];
  kids.push(table('cover-rows', cols, v.rows.map(r => ({
    who: r.scored + ' of ' + v.n, chance: r.probability,
    wins: r.winning_bets, ret: r.returned, net: r.net,
  })), {}));

  const be = v.breakeven_scored;
  kids.push(el('div', { class: 'warn-box' + (be == null ? ' bad-box' : ' good-box'),
    html: be == null
      ? '<b>No number of scorers turns a profit.</b> Even all ' + v.n +
        ' landing returns $' + v.rows[v.n].returned.toFixed(2) + ' against $' +
        v.staked.toFixed(2) + ' staked.'
      : '<b>Breakeven is ' + be + ' of ' + v.n + '</b> \u2014 and that happens <b>' +
        pct(v.p_breakeven, 1) + '</b> of the time' +
        (v.rho ? ', with the measured teammate correlation of ' +
          v.rho.toFixed(3) + ' applied' : ', treating the legs as independent') +
        '.' }));

  if (!v.all_priced) {
    kids.push(el('div', { class: 'warn-box', html:
      '<b>The expected result below is not a measured edge.</b> Some legs have ' +
      'no market price, so it weighs the model\u2019s own probabilities against ' +
      'the ' + bothPrices(v.assumed_decimal) + ' you assumed. A book that agreed ' +
      'with these numbers would not offer that price.' }));
  }
  kids.push(el('p', { class: 'muted', html:
    'Expected result <b>' + money(v.expected_net) + '</b> (' +
    pct(v.expected_roi, 1) + ') against <b>' + money(v.singles_net) + '</b> (' +
    pct(v.singles_roi, 1) + ') for the same $' + v.staked.toFixed(2) +
    ' on the ' + v.n + ' singles alone. A cover is leverage on the edge in each ' +
    'leg: per dollar a single returns <i>e</i> and a k-fold returns ' +
    '<i>(1+e)<sup>k</sup> \u2212 1</i>. ' +
    (v.expected_roi > v.singles_roi
      ? 'These prices leave a positive edge, so multiplying them compounds it ' +
        '\u2014 at far higher variance, and on the model\u2019s probabilities ' +
        'rather than a measured result.'
      : 'These prices leave a negative edge, so multiplying them pays the ' +
        'margin once per leg and the cover loses harder than the singles do.') }));

  // What the rule actually returned. Everything above is a product of
  // estimates and prices; this is the only part nothing can argue with.
  const rec = cov.record;
  if (!rec) {
    kids.push(el('div', { class: 'warn-box', html:
      '<b>Nothing in this section has been graded.</b> Every figure above is a ' +
      'projection. `make cover-backtest` replays the rule over the backtested ' +
      'weeks.' }));
  } else {
    const recCols = [
      { k: 'n', label: 'Players' },
      { k: 'weeks', label: 'Weeks' },
      { k: 'slips', label: 'Slips a week' },
      { k: 'staked', label: 'Staked', fmt: x => '$' + x.toFixed(0) },
      { k: 'returned', label: 'Returned', fmt: x => '$' + x.toFixed(0) },
      { k: 'roi', label: 'Cover', fmt: x => pct(x, 1), cls: x => cls(x) },
      { k: 'ci', label: '90% CI', t: 1 },
      { k: 'singles', label: 'Singles', fmt: x => pct(x, 1), cls: x => cls(x),
        title: 'The same money spread over the N singles instead.' },
      { k: 'ahead', label: 'Weeks ahead', t: 1 },
      { k: 'top', label: 'Best week\u2019s share', fmt: x => pct(x, 1),
        title: 'How much of everything returned came from one week. High means ' +
               'the headline is an anecdote rather than a rate.' },
    ];
    kids.push(el('h4', { text: 'What this rule actually returned' }));
    kids.push(table('cover-record', recCols, rec.sizes.map(s => ({
      n: s.n, weeks: s.weeks, slips: s.slips_per_week, staked: s.staked,
      returned: s.returned, roi: s.roi,
      ci: pct(s.roi_lo, 0) + ' to ' + pct(s.roi_hi, 0),
      singles: s.singles_roi, ahead: s.weeks_profitable + '/' + s.weeks,
      top: s.top_week_share,
    })), {}));
    const worse = rec.sizes.filter(s => s.roi < s.singles_roi).length;
    kids.push(el('p', { class: 'muted', html:
      'Replayed over ' + rec.weeks + ' graded weeks (' + rec.span + ') at $' +
      rec.stake.toFixed(2) + ' a slip, on the prices actually posted. ' +
      '<b>No pool size has an interval clearing zero.</b> ' +
      (worse ? worse + ' of ' + rec.sizes.length + ' sizes returned less than ' +
        'backing the same money on the singles \u2014 which is what a negative ' +
        'edge per leg does when it is multiplied: a k-fold pays the margin k ' +
        'times.' : '') }));
  }

  return card('Cover the field', '', kids);
}

function paneTeams() {
  const m = M(), out = el('div');
  // The named scorers follow the market — see `teams()` in the exporter.
  const first = m.key === 'first_td';
  let rows = m.teams.slice();
  const games = Array.from(new Set(m.teams.map(t => t.game).filter(Boolean))).sort();
  if (S.t.game) rows = rows.filter(t => t.game === S.t.game);
  const anyBook = rows.some(t => has(t.book_first_td));
  rows = rows.map(t => Object.assign({}, t, {
    gap: has(t.first_td) && has(t.book_first_td) ? (t.first_td - t.book_first_td) * 100 : null,
  }));

  out.appendChild(bar([
    select('Game', S.t.game, [['', 'All games']].concat(games.map(g => [g, g])), v => S.t.game = v,
      'One game is two rows that answer each other: the two sides’ chances of striking first add to 100%, so reading them together is the point.'),
  ]));

  const cols = [
    { k: 'game', label: 'Game', t: 1 },
    { k: 'team', label: 'Team', t: 1 },
    { k: 'first_td', label: 'Scores first', fmt: v => has(v) ? pct(v, 0) : '<span class="dim">—</span>',
      bar: v => v, title: 'Chance this team scores the game’s first touchdown. The two teams add to 100%.' },
    anyBook ? { k: 'book_first_td', label: 'Bookmaker says', fmt: v => has(v) ? pct(v, 0) : '<span class="dim">—</span>',
      title: 'The same arithmetic on the bookmaker’s own first-TD prices, margin removed: their players’ chances summed by team and normalised within the game. Blank where too few of a game’s players carry a price to split it.' } : null,
    anyBook ? { k: 'gap', label: 'Difference', fmt: v => has(v) ? pp(v, 0) + ' pts' : '', cls: v => cls(v),
      title: 'The same number with opposite signs on the two sides of a game, because both columns add to 100%.' } : null,
    { k: 'expected_tds', label: 'Expected TDs', fmt: v => has(v) ? v.toFixed(2) : '',
      title: 'The fitted team touchdown rate, driven by the betting lines.' },
    { k: 'expected_scorers', label: 'Expected scorers', fmt: v => has(v) ? v.toFixed(2) : '',
      title: 'How many different players are expected to score. Lower than expected touchdowns because one player can score twice.' },
    { k: 'shutout', label: 'Shut-out risk', fmt: v => has(v) ? pct(v, 0) : '',
      title: 'Chance of no offensive touchdown. Rare — teams score in about 92% of games — so this column is only interesting when it is high.' },
    { k: 'top1_player', label: first ? 'Likeliest to score first' : 'Likeliest scorer', t: 1,
      fmt: (v, r) => v ? esc(v) + ' <span class="dim">' + pct(r.top1_pct, first ? 1 : 0) + '</span>' : '',
      title: first
        ? 'This market’s own number: the player most likely to score the game’s FIRST touchdown, and his chance of doing it. Only one player in the game can, so these percentages are several times smaller than an anytime one and the two are not comparable.'
        : 'This market’s own number: the player most likely to score at some point, and his chance of doing it.' },
    { k: 'top2_player', label: 'Second likeliest', t: 1,
      fmt: (v, r) => v ? esc(v) + ' <span class="dim">' + pct(r.top2_pct, first ? 1 : 0) + '</span>' : '',
      title: 'The second name, because one on its own reads as "the bet". Two say where a team’s touchdowns are concentrated and how far ahead the first name actually is.' },
  ].filter(Boolean);

  out.appendChild(card('By team',
    'The board answers "which player". This is the question underneath it. ' +
    'Which side scores first is a coin-flip question and the model beats the coin — <b>AUC 0.674</b> over 2,278 walk-forward team-games, calibrated from 6% to 94%. ' +
    'Every game on the slate is here, not only the ones a book has priced. ' +
    'The two named players are <b>' + esc(m.label) + '</b> — this market’s own numbers, so they change with the switch above.',
    [table('teams', cols, rows, {}),
     el('p', { class: 'fine', html:
       'Not shown: the chance a team scores <i>any</i> touchdown. It is around 92% for nearly every team in nearly every game, and a column that always reads the same teaches you to skip it.' })]));

  const thin = rows.filter(t => has(t.candidates) && t.candidates < 5);
  if (thin.length) out.appendChild(el('div', { class: 'warn-box', html:
    '<b>No first-TD split for some games.</b> ' +
    Array.from(new Set(thin.map(t => t.team))).sort().join(', ') +
    ' have almost no players in this week’s candidate pool, so the split would describe the roster feed rather than the football. Their opponents are withheld too — one number is just one minus the other. This clears once rosters are published.' }));
  return out;
}
"""

JS_SHELL = r"""
// ── Shell ───────────────────────────────────────────────────────────────
const TABS = [
  ['players', 'Every player', paneMPlayers],
  ['combos', 'Combinations', paneCombos],
  ['cover', 'Cover the field', paneCover],
  ['teams', 'By team', paneTeams],
];
function paneMPlayers() { return panePlayers(); }

function render(keepFocus) {
  const active = keepFocus ? document.activeElement : null;
  const sel = active && active.selectionStart;
  const key = active && active.dataset ? active.dataset.k : null;
  const m = M();

  $('#meta').innerHTML =
    '<b>' + esc(m.label) + '</b> · ' + m.season + ' week ' + m.week +
    ' · model <b>' + esc(m.model) + '</b>' +
    (m.served.version ? ' · version <b>' + esc(m.served.version) + '</b>' : '');

  document.querySelectorAll('#markets button').forEach((b, i) =>
    b.setAttribute('aria-pressed', i === S.market));
  document.querySelectorAll('#tabs button').forEach(b =>
    b.setAttribute('aria-selected', b.dataset.id === S.tab));

  const main = $('#main');
  main.innerHTML = '';
  if ((m.problems || []).length) {
    main.appendChild(el('div', { class: 'warn-box bad-box', html:
      '<b>Something failed to load, so a column here is missing because it broke rather than because the data does not exist:</b><br>' +
      m.problems.map(esc).join('<br>') }));
  }
  const t = TABS.find(t => t[0] === S.tab) || TABS[0];
  main.appendChild(t[2]());

  if (active && active.tagName === 'INPUT' && active.type === 'text') {
    const again = (key && main.querySelector('input[data-k="' + key + '"]')) ||
                  main.querySelector('input[type=text]') ||
                  document.querySelector('input[type=text]');
    if (again) { again.focus(); if (sel != null) again.setSelectionRange(sel, sel); }
  }
  window.scrollTo(window.scrollX, window.scrollY);
}

function boot() {
  const mk = $('#markets');
  DATA.markets.forEach((m, i) => {
    const b = el('button', { text: m.label, type: 'button' });
    b.onclick = () => { S.market = i; S.sort = {}; S.p.game = ''; S.c.game = ''; S.t.game = ''; render(); };
    mk.appendChild(b);
  });
  const tb = $('#tabs');
  TABS.forEach(([id, label]) => {
    const b = el('button', { text: label, type: 'button', 'data-id': id, role: 'tab' });
    b.onclick = () => { S.tab = id; render(); };
    tb.appendChild(b);
  });
  const th = $('#theme');
  th.onclick = () => {
    const cur = document.documentElement.getAttribute('data-theme');
    const next = cur === 'dark' ? 'light' : (cur === 'light' ? '' : 'dark');
    if (next) document.documentElement.setAttribute('data-theme', next);
    else document.documentElement.removeAttribute('data-theme');
    th.textContent = next === 'dark' ? 'Dark' : (next === 'light' ? 'Light' : 'Auto');
  };
  render();
}
document.addEventListener('DOMContentLoaded', boot);
"""

SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ctext y='26' font-size='26'%3E%F0%9F%8F%88%3C/text%3E%3C/svg%3E">
<style>__CSS__</style>
</head>
<body>
<header class="top">
  <div class="brand">NFL scorer dashboard<small id="meta"></small></div>
  <div class="seg" id="markets" role="group" aria-label="Market"></div>
  <button class="iconbtn" id="theme" type="button" title="Light, dark, or follow the system">Auto</button>
</header>
<nav class="tabs" id="tabs" role="tablist"></nav>
<main id="main"></main>
<footer style="padding:0 20px 32px;max-width:1500px;margin:0 auto">
  <p class="fine">__FOOTER__</p>
</footer>
<script id="payload" type="application/json">__DATA__</script>
<script>const DATA = JSON.parse(document.getElementById('payload').textContent);</script>
<script>__JS__</script>
</body>
</html>
"""

FOOTER = (
    "Built by <code>scripts/34_export_dashboard.py</code> at __BUILT__ UTC. "
    "The model on each market is whichever version <code>models/registry/CURRENT.json</code> "
    "says is promoted, and the model that version's own config resolves to — so this "
    "page cannot disagree with what the app serves. "
    "Accuracy is measured on seasons the model never trained on. "
    "Nothing here is betting advice: the ranking is measured and real, and backing it "
    "against these prices has been measured as unprofitable."
)


def render(payload: dict) -> str:
    """One self-contained file: the payload, the shell, and nothing fetched."""
    # `</script>` inside a JSON string would close the tag it sits in, and the
    # rest of the payload would render as text. Escaping the sequence is
    # cheaper and more reliable than trusting no player is ever named in a way
    # that produces one.
    data = (json.dumps(payload, separators=(",", ":"), allow_nan=False)
            .replace("</", "<\\/"))
    js = "\n".join([JS, JS_PLAYERS, JS_COMBOS, JS_TEAMS, JS_SHELL])
    labels = " and ".join(m["label"] for m in payload["markets"]) or "NFL"
    return (SHELL
            .replace("__TITLE__", html.escape(f"{labels} — model dashboard"))
            .replace("__CSS__", CSS)
            .replace("__FOOTER__", FOOTER.replace("__BUILT__", html.escape(payload["built"])))
            .replace("__JS__", js)
            .replace("__DATA__", data))
