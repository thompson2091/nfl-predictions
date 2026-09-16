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

**What it opens on.** Parlay, then Players, Combinations, Teams — the thing
being built first, and the board it is built from after. The two panes that
used to come first, `Model vs book` and `How often it is right`, scored the
model instead of the week; they were the first thing a reader saw and the last
thing they wanted. The measurements themselves are not gone, they are in
`walkforward.json`, `market_parity` and `hit_rates` where the evaluation
harness can gate on them, which is where a number that describes the model
rather than the slate belongs.

The pane keys did not change with the labels — `cover`, `players`, `combos`,
`teams` are what the state and every test refer to, and renaming them to match
the tab strip would break saved links for a cosmetic gain.
"""
from __future__ import annotations

import html
import json

from src.prediction.combos import LEG_CAPS, MAX_LEGS

#: The `Show` stops this page offers. The app's own control is a 5-50 slider in
#: fives and the graded replay measures every one of those stops, but the page
#: asks for deeper tables than the app does and can only ever look up these —
#: so `scripts/34_export_dashboard.py` carries the measured rows for these
#: stops and drops the rest. At eleven leg counts the full grid is 1,100 rows a
#: market, four fifths of which nothing on the page can reach.
PAGE_SHOW_STOPS = (25, 50, 100, 250, 500)

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
.tiles.narrow { grid-template-columns: repeat(auto-fit, minmax(160px, 250px)); justify-content: start; }
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
/* A field that takes several answers. It gets its own line: sixteen fixtures
   wrap to two or three rows, and squeezed in beside the selects it would push
   them off the bar. */
.field.chipset { flex: 1 1 100%; }
.tog { display: flex; flex-wrap: wrap; gap: 6px; }
.tog button {
  font: inherit; font-size: 12px; padding: 4px 10px; border-radius: 99px;
  border: 1px solid var(--rule); background: var(--surface); color: var(--ink-2);
  cursor: pointer; white-space: nowrap;
}
.tog button:hover { color: var(--ink); border-color: var(--border); }
.tog button[aria-pressed="true"] {
  border-color: var(--accent); background: var(--accent-soft); color: var(--ink);
  font-weight: 560;
}
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
/* Twelve names joined by plus signs is a 600px cell that pushes every number
   off the screen. Only the slip column, and only where a slip is long enough
   to need it. */
td.wrapcell { white-space: normal; max-width: 46ch; }
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
/* A control that lives inside a table cell. Distinct from `.iconbtn`, which is
   a toolbar-sized button: at that padding every row here grows taller than its
   own text. */
.cellbtn { font: inherit; font-size: 13px; line-height: 1; cursor: pointer;
  border: 1px solid var(--border); background: var(--surface); color: var(--ink-2);
  border-radius: 5px; padding: 2px 6px; min-width: 24px; }
.cellbtn:hover { border-color: var(--accent); color: var(--ink); }
.cellbtn.on { border-color: var(--accent); color: var(--accent); font-weight: 700; }
.cellbtn.star.on { color: var(--warn); border-color: var(--warn); }
/* A saved player the current board no longer carries. Dimmed rather than
   dropped: a row vanishing is indistinguishable from never having added it. */
tr.stale td { opacity: 0.55; }
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
// Grouped, because the stake is a free-text dollar amount now and $31000.00
// is a number you have to count the digits of. Two decimals always: a money
// column that drops them is a money column that stops lining up.
const cents = v => Math.abs(v).toLocaleString('en-US',
  { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const usd = v => has(v) ? '$' + cents(v) : '';
const money = v => has(v) ? (v >= 0 ? '+$' : '-$') + cents(v) : '';
const american = o => {
  if (!has(o)) return '';
  const n = Math.round(o);
  return (n > 0 ? '+' : '') + n;
};
// The same price, grouped. A single player's odds are three or four digits and
// read fine unbroken; a twelve-leg slip's are +3237144, which is a number you
// have to count the digits of — the same reason the money columns group.
const americanLong = o => {
  if (!has(o)) return '';
  const n = Math.round(o);
  return (n > 0 ? '+' : '-') + Math.abs(n).toLocaleString('en-US');
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
  // Shape first, then value. `parseFloat` reads `1.2.3` as 1.2 and Python's
  // `float` refuses it; neither string is a price, and a box that disagrees
  // with itself across two languages is how the page and the app come to stake
  // different money on the same input.
  if (!/^[+-]?[0-9]*\.?[0-9]+$/.test(t)) return null;
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
// A stake as anyone would write one: `2.50`, `$2.50`, `1,000`. `parseFloat`
// alone reads `$2.50` as nothing and `1,000` as one, and the second of those
// is the dangerous one — it is not an error, it is a thousandfold understatement
// of what the table below says is at risk.
const parseMoney = v => {
  const t = String(v == null ? '' : v).trim().replace(/[$,\s]/g, '');
  if (!t || !/^[0-9]*\.?[0-9]+$/.test(t)) return null;
  const x = parseFloat(t);
  return isFinite(x) && x > 0 ? x : null;
};
const cls = v => !has(v) ? '' : (v > 0 ? 'pos' : (v < 0 ? 'neg' : ''));
// A return needs its sign even when it is positive: `19.0%` beside `-12.9%`
// reads as a magnitude, and the whole comparison is directional.
const spct = (v, d) => has(v) ? (v > 0 ? '+' : '') + pct(v, d) : '';

// ── State ───────────────────────────────────────────────────────────────
const S = {
  market: 0,
  tab: 'shortlist',
  p: { game: '', q: '', depth: 0, priced: 'all', longshot: false, differ: false },
  // Five players, one per game. Five because 31 slips is the size the question
  // is usually asked at, and one-per-game because taking the top five from a
  // single fixture is usually five teammates — which correlates the legs and
  // guts the all-score tail.
  // `picked` fills from the top five on first render; after that it is
  // whatever the reader chose.
  // `dec` is the price the table uses; `decRaw` is what was typed to get it,
  // in either notation. They part company only while a price is half-entered.
  // `dec`/`decRaw` are seeded per market from what books have actually posted
  // there — see `assumed_price` — and `decMarket` is which market they were
  // seeded for. Carrying one price across a market switch was a trap: the
  // payout table is built from prices and does not move when the
  // probabilities do, so +100 assumed on both markets makes an anytime cover
  // look ordinary and a first-TD cover look catastrophic for no reason a
  // reader can see.
  // `sizes` is the round robin: the slip sizes actually backed. Empty is
  // every combination, which is the full cover and what this pane did before
  // the control existed -- so an empty default changes nothing for a reader
  // who never touches it.
  cover: { picked: null, stake: 1, stakeRaw: '1.00', dec: 2.0, decRaw: '+100',
           decMarket: null, q: '', game: '', sizes: [],
           pricedOnly: false, open: true },
  // `priced` mirrors the master table's control and defaults the same way:
  // the whole slate. A priced-only default answered "what can I bet on"
  // while being read as "which players go together".
  // `likely` rather than `ev`, because expected value can only rank a slip
  // that carries a price and most of a slate does not: at 25 rows an
  // EV-ranked table is entirely priced, which is a priced-only table wearing a
  // different label. Likelihood is the one ranking every player has a number
  // for, so it is the one that opens.
  // `games` is a list because a slip is the one thing on this page that
  // deliberately spans fixtures: "these three games and nothing else" is
  // the question it provokes, and a single-game dropdown could only ask it
  // one game at a time. Empty is the whole slate.
  c: { legs: 2, per: 4, metric: 'likely', show: 25, games: [], priced: 'all' },
  // "Guys I like": a list built by clicking players on the Players and
  // Shortlist tables. Scoped to one season/week/market and held in
  // localStorage, so it survives this page being rebuilt — which happens
  // several times a week and would otherwise discard it every time.
  //
  // `liked` and `likedFav` are caches keyed the same way as storage; reading
  // localStorage on every render would be a synchronous disk hit per row.
  // `likedFav` is a starred subset that sorts to the top and is marked. It
  // deliberately does NOT narrow what the parlay or the combinations table
  // draw from — a star is a note to yourself, not a filter, and a star that
  // silently changed the pool would make two tools disagree with the list
  // above them.
  // The ladder is arithmetic on four numbers and touches no payload at all, so
  // it keeps raw text beside parsed values for the same reason every other
  // field here does: `-1` and `2.` are the middle of a price, and rewriting
  // them mid-keystroke makes a box that fights the person using it.
  ladder: { start: 100, startRaw: '100', goal: 10000, goalRaw: '10000',
            bets: 10, betsRaw: '10', dec: 1 + 100 / 170, oddsRaw: '-170' },
  liked: {}, likedFav: {}, likedBroken: false,
  likedCover: { picked: null, stake: 1, stakeRaw: '1.00', dec: 2.0, decRaw: '+100',
                decMarket: null, q: '', game: '', sizes: [],
                pricedOnly: false, open: true },
  t: { game: '' },
  sort: {},
};
const M = () => DATA.markets[S.market];

//: Rungs the ladder will draw. Past this the table is longer than the idea it
//: illustrates, and the payout has long since stopped meaning anything.
const LADDER_MAX = 50;

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
    const nosort = opts.nosort || c.nosort;
    const th = el('th', {
      class: (c.t ? 't ' : '') + (nosort ? 'nosort' : ''),
      title: c.title || null, text: c.label,
    });
    if (st && st.k === c.k) th.setAttribute('aria-sort', st.dir > 0 ? 'ascending' : 'descending');
    if (!nosort) th.onclick = () => {
      S.sort[id] = (st && st.k === c.k) ? { k: c.k, dir: -st.dir } : { k: c.k, dir: -1 };
      render();
    };
    thead.appendChild(th);
  });
  const tb = el('tbody');
  data.forEach(r => {
    const rc = opts.rowClass ? opts.rowClass(r) : null;
    const tr = el('tr', rc ? { class: rc } : {});
    cols.forEach(c => {
      const v = r[c.k];
      const td = el('td', { class: (c.t ? 't' : 'num') + (c.cls ? ' ' + c.cls(v, r) : '') });
      if (c.cell) {
        // The column owns the cell. `fmt` writes a string into innerHTML,
        // which cannot carry a listener without an inline onclick and a global
        // to hang it on; a control column needs a real node.
        c.cell(td, v, r);
      } else if (c.bar && has(v)) {
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
// Several answers to one question. Toggle chips rather than a native
// `<select multiple>`: that control asks for ctrl-click, which nobody
// discovers, and hides everything past its first few rows — and seeing what is
// selected without opening anything is the whole point of the field. The
// leading chip clears the selection rather than naming a value, so "all of
// them" is one click from any state.
function multi(label, values, options, onchange, allLabel, title) {
  const on = {};
  values.forEach(v => { on[v] = 1; });
  const chip = (t, pressed, click) => {
    const b = el('button', { type: 'button', text: t });
    b.setAttribute('aria-pressed', pressed ? 'true' : 'false');
    b.onclick = () => { click(); render(); };
    return b;
  };
  const wrap = el('div', { class: 'tog' }, [
    chip(allLabel || 'All', !values.length, () => onchange([])),
  ]);
  options.forEach(o => {
    const v = Array.isArray(o) ? o[0] : o, t = Array.isArray(o) ? o[1] : o;
    wrap.appendChild(chip(t, !!on[v], () => onchange(
      on[v] ? values.filter(x => x !== v) : values.concat([v]))));
  });
  return el('div', { class: 'field chipset', title: title || null },
            [el('label', { text: label }), wrap]);
}
function text(label, value, onchange, placeholder, title) {
  // The label doubles as the field's identity across a re-render. Without it
  // the focus restore below grabs the first text input on the pane, so typing
  // into the third one throws the caret back into the first — which the cover
  // pane now has three of.
  const i = el('input', { type: 'text', value: value,
    placeholder: placeholder || '', 'data-k': label });
  let tmr;
  i.oninput = () => { clearTimeout(tmr); tmr = setTimeout(() => { onchange(i.value); render(true); }, 120); };
  const f = el('div', { class: 'field', title: title || null },
               [el('label', { text: label }), i]);
  f.dataset.focus = 'search';
  return f;
}
// A read as a chip. `Veto` is the one that has to look different: it is not a
// weaker call, it is the opposite instruction — we rate the player under the
// price, which is the side of this model that measures sharpest and the side
// no book will sell you.
function readChip(v) {
  if (!v) return '';
  return '<span class="chip' + (v === 'Veto' ? ' fade' : '') + '">' + esc(v) + '</span>';
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

// The Players table's columns, defined once. "Guys I like" is the same table
// over a chosen subset, and a second copy of this list would drift from it the
// first time a column was added to either — the failure this file has already
// had twice, with the head-to-head tiles and with the slate predicate.
function playerCols(m) {
  const anyBest = m.players.some(p => p.best);
  const anyStatus = m.players.some(p => p.status);
  const anyBacking = m.players.some(p => p.backing);
  const blended = m.topk && m.topk.blended;
  return [
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
    { k: 'read', label: 'Our read', t: 1, fmt: readChip,
      title: 'Matches book / Leans / Strong call where we rate a player above the price, cut at the 33rd and 66th percentile of how far this model typically sits from it — and Veto where we rate one below it. Veto is not a weaker call, it is the opposite instruction: the closing line moves our way when we are lower and stands still when we are higher, so that is the sharpest thing here, and these markets only sell the Yes side.' },
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
}

function panePlayers() {
  const m = M(), f = S.p, out = el('div');
  const games = Array.from(new Set(m.players.map(p => p.game).filter(Boolean))).sort();

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
  const cols = [likeCol()].concat(playerCols(m));

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
const READ_ORDER = ['Veto', 'Matches book', 'Leans', 'Strong call'];

//: How many candidate legs the search keeps, by slip length. Combinations grow
//: as C(n, legs), so the pool is cut to its strongest legs first. That cut
//: cannot change the answer while `keep >= show + legs`: every metric here is a
//: product of positive per-leg factors, so a slip using a leg ranked below the
//: cut is beaten by at least `show` slips built from the legs above it. Where
//: it does bind, the caption says so rather than letting a bounded search read
//: as an exhaustive one — and past four legs it always binds, because the pool
//: that would carry the proof is more combinations than any machine will
//: enumerate.
//:
//: Written out of `src/prediction/combos.LEG_CAPS` at export time rather than
//: typed here: the page and the app search the same slips, and two hand-kept
//: tables of caps are two searches that quietly disagree about what "the
//: strongest 20" means.
const LEG_CAP = __LEG_CAP__;
//: Every slip length the control offers, and the same lengths the app offers.
const LEG_CHOICES = Object.keys(LEG_CAP).map(k => [+k, k]);
//: A slip length as a word, for a line that reads like a sentence.
const LEG_WORDS = ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven',
                   'eight', 'nine', 'ten', 'eleven', 'twelve'];

//: Each game's top `per` by the board's own #, over whichever population is
//: asked for. Ranked within the game before the cut, so widening `per` reaches
//: further down every game rather than deeper into one.
function comboPool(players, per, games, pricedOnly) {
  let pool = players.filter(p => has(p.ours) && !p.blocked);
  if (games && games.length) pool = pool.filter(p => games.indexOf(p.game) >= 0);
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
    const priced = comboPool(m.players, per, c.games, true);
    const found = comboSearch(rank(priced, p => p.model_only * p.dec), legs, singleWinner);
    searched += found.length;
    scored = found.filter(r => r.priced).sort((a, b) => b.ev - a.ev);
  }
  if (!ev || !pricedOnly) {
    const all = comboPool(m.players, per, c.games, pricedOnly);
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
      games: gs.length,
      odds: r.dec ? americanLong(decToAm(r.dec)) : null,
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
    select('Legs', c.legs, LEG_CHOICES, v => c.legs = +v,
      'How many players on the slip. Each one lengthens the price and shortens the chance, and both move faster than they look: three 40% legs is a 6% shot, six of them is 1 in 244, and twelve is 1 in 59,605. Past four legs the table is the best the search found rather than a proven best — the line under it says which.'),
    select('From each game’s top', c.per, [2, 3, 4, 5, 6, 7, 8], v => c.per = +v,
      'Which players are eligible: each game’s top N by #. Widening this reaches further down every game rather than deeper into one.'),
    select('Rank by', c.metric, [['likely', 'Most likely'], ['ev', 'Expected value']], v => c.metric = v,
      'Most likely ranks on the chance the slip lands, which every player has a number for. Expected value ranks on what $100 expects to return — it needs a price, so it can only order the slips that carry one, and the rest follow it by likelihood. Different questions and usually different tables: the likeliest slips are short-priced and the best value ones are not.'),
    select('Show', c.show, __SHOW_STOPS__, v => c.show = +v),
    select('Players', c.priced, [['all', 'Priced and unpriced'], ['yes', 'Priced only']],
      v => c.priced = v,
      'The whole slate by default. A slip touching a player no book has quoted carries no odds, no bookmaker number and no expected value — there is nothing to compute them from — so those cells are blank. Priced only narrows it to the games a book has posted, which is also the population the graded replay covers.'),
    multi('Games', c.games, games, v => c.games = v, 'All games',
      'Which fixtures the legs may come from — as many as you like, or none for the whole slate.'),
  ]));

  const rec = comboRecord();
  if (rec) {
    // Enough places that the three chances stay comparable. At twelve legs the
    // replay says we predicted 1 in 55,000 and none of 1,500 slips landed,
    // which one place prints as 0.0% against 0.0% — the reading a perfectly
    // calibrated strip gets, from the setting that says least.
    const hi = Math.max(rec.landed || 0, rec.we_said || 0, rec.book_said || 0) * 100;
    const rp = hi > 0 ? Math.min(4, Math.max(1, 2 - Math.floor(Math.log10(hi)))) : 1;
    out.appendChild(card('This exact setting, replayed and graded',
      'Every slip these controls would have shown, replayed week by week over ' +
      esc(m.combo_record.span) + ' and graded on results. It sits above the table because it is the context for reading any row: a table of expected values built on a probability that runs hot is a table of fiction, and <b>Landed</b> against <b>We said</b> is the only thing that says which.',
      [tiles([
        { k: 'Slips graded', v: rec.slips.toLocaleString(), d: rec.weeks + ' weeks' },
        { k: 'Landed', v: pct(rec.landed, rp), d: 'every leg scored' },
        { k: 'We said', v: pct(rec.we_said, rp), d: pp((rec.landed - rec.we_said) * 100, rp) + ' pts vs landed' },
        { k: 'Book said', v: pct(rec.book_said, rp), d: 'their de-vigged prices' },
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
  // A twelve-leg slip lands about once in a hundred thousand, and one decimal
  // place prints every row of that table as 0.0%. Enough places to keep two
  // significant figures on the likeliest row — chosen once for the whole
  // column rather than per cell, so the numbers still line up under each other.
  const top = r.rows.reduce((mx, x) => Math.max(mx, x.ours || 0), 0) * 100;
  const dp = top >= 5 ? 1
    : top > 0 ? Math.min(9, Math.max(2, 2 - Math.floor(Math.log10(top)))) : 2;
  const cols = [
    { k: 'players', label: 'Players', t: 1, cls: () => r.legs >= 5 ? 'wrapcell' : '',
      title: 'Every one of these has to score for the slip to pay. That is the whole difference between this table and the board.' },
    { k: 'game', label: 'Game', t: 1,
      fmt: (v, x) => esc(v) + (x.same
        ? ' <span class="chip warn">' + (x.games === 1 ? 'same game' : 'shares a game') + '</span>'
        : '') },
    { k: 'odds', label: 'Odds', t: 1, fmt: v => v || '<span class="dim">—</span>' },
    { k: 'ours', label: 'Our estimate', fmt: v => pct(v, dp) },
    blended ? { k: 'mo', label: 'Model only', fmt: v => pct(v, dp) } : null,
    { k: 'book', label: 'Bookmaker says', fmt: v => has(v) ? pct(v, dp) : '<span class="dim">—</span>' },
    { k: 'diff', label: 'Difference', fmt: v => has(v) ? pp(v, dp) + ' pts' : '', cls: v => cls(v) },
    { k: 'read', label: 'Our read', t: 1, fmt: readChip,
      title: 'The weakest read its legs carry. Not the average and not the strongest: a slip needs all of them, so the leg we have least to say about is the one that decides what it is — and a Veto leg, one we rate under its own price, ends the slip whatever the others say. Blank where no leg carries a read, which is any slip with an unpriced player on it.' },
    { k: 'ev', label: 'Expected on $100', fmt: v => has(v) ? money(v) : '<span class="dim">—</span>', cls: v => cls(v) },
    anyBacking ? { k: 'backing', label: 'Worth backing', t: 1,
      title: 'Each leg’s own tier, in the order the slip names its players. Never one tier for the slip: the tiers were fitted on single bets.' } : null,
  ].filter(Boolean);

  const legWord = LEG_WORDS[r.legs];
  // Named while the list is short enough to read, counted after that: eight
  // fixture labels inside a sentence is not a sentence.
  const where = !c.games.length ? 'every game on the slate'
    : c.games.length > 3 ? 'the ' + c.games.length + ' games selected'
    : c.games.length === 1 ? c.games[0]
    : c.games.slice(0, -1).join(', ') + ' and ' + c.games[c.games.length - 1];
  // Why the table is empty, counted over what the search actually had rather
  // than over what the filters selected. A slip can now be longer than the
  // slate, and "not enough players" is the wrong thing to go looking for when
  // the shortage is games.
  const emptyPool = comboPool(m.players, +c.per, c.games, c.priced === 'yes');
  const emptyGames = new Set(emptyPool.map(p => p.game)).size;
  const short = m.key === 'first_td' && emptyGames < r.legs;
  out.appendChild(card(null, null, [
    r.rows.length ? table('combos', cols, r.rows, {}) : el('p', { class: 'note', html:
      short
        ? '<b>A ' + legWord + '-leg slip needs ' + r.legs + ' different games on this market.</b> ' +
          'Exactly one player scores a game’s first touchdown, so no two legs can come from the same game, and there ' +
          (emptyGames === 1 ? 'is 1 game' : 'are ' + emptyGames + ' games') + ' to choose from here. ' +
          'Add games above, or shorten the slip.'
        : '<b>Not enough eligible players here.</b> A ' + legWord + '-leg slip needs ' + r.legs +
          ' of them and the top ' + c.per + ' of ' + esc(where) + ' leaves ' + emptyPool.length +
          '. Widen <b>From each game’s top</b>, add games, or shorten the slip.' }),
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
""".replace("__LEG_CAP__", json.dumps({str(k): v for k, v in LEG_CAPS.items()})
   ).replace("__SHOW_STOPS__", json.dumps(list(PAGE_SHOW_STOPS)))

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
// What this market's books pay for a player we rate at `p`, from the line
// `cover.price_curve` fitted over the priced ones — the JS half of
// `src.prediction.cover.assumed_decimal`, pinned to it by test. Clamped to the
// fitted range rather than extrapolated: first TD has nobody rated above 15%,
// and a line run past that says a 55% player would be posted at +266, which is
// arithmetic off the end of its evidence rather than a reading of any market.
function curveDecimal(curve, p) {
  if (!curve || !has(p) || p <= 0 || p >= 1) return null;
  const x = Math.min(Math.max(p, curve.lo), curve.hi);
  if (!(x > 0 && x < 1)) return null;
  const q = 1 / (1 + Math.exp(-(curve.a + curve.b * Math.log(x / (1 - x)))));
  return 1 / Math.min(Math.max(q, 1e-6), 1 - 1e-6);
}

// The prices the unpriced legs were charged, as a range a reader can check.
// Naming them beats naming one number: five legs off a curve are five prices,
// and "an assumed +106" for all of them is what made this table lie.
function standInRange(ds) {
  const xs = (ds || []).filter(has).slice().sort((a, b) => a - b);
  if (!xs.length) return 'no stand-in needed';
  const lo = american(decToAm(xs[0])), hi = american(decToAm(xs[xs.length - 1]));
  return lo === hi ? lo : lo + ' to ' + hi;
}

// The leg-counts a structure stakes, ascending. Mirrors `cover.sizes_for`:
// a size above n is an empty stratum rather than an error, because trimming a
// player is ordinary; a size below 1 is not a bet, and a selection leaving
// nothing staked has no outlay to divide by.
function coverSizes(n, sizes) {
  if (!sizes) return Array.from({ length: n }, (_, i) => i + 1);
  const want = Array.from(new Set(sizes.map(Number))).sort((a, b) => a - b);
  const kept = want.filter(k => k >= 1 && k <= n);
  return kept.length ? kept : Array.from({ length: n }, (_, i) => i + 1);
}

function nCk(n, k) {
  if (k < 0 || k > n) return 0;
  let r = 1;
  for (let i = 1; i <= k; i++) r = r * (n - k + i) / i;
  return Math.round(r);
}

// How many slips a structure buys on n players. Mirrors the sum the pane's
// headline and the picker's running count both need.
function coverBets(n, sizes) {
  return coverSizes(n, sizes).reduce((a, k) => a + nCk(n, k), 0);
}

// What to call the structure, in a reader's words -- a book says "By 2's",
// never "by 2s and by 3s", so the "by" is said once over the whole list.
// Mirrors `board.cover_structure`.
function coverStructure(n, sizes) {
  const want = coverSizes(n, sizes);
  if (want.length === n) return 'every combination';
  if (want.length === 1 && want[0] === 1) return 'singles only';
  if (want.length === 1 && want[0] === n && n > 1) return 'the ' + n + '-leg only';
  const series = xs => xs.length === 1 ? xs[0]
    : xs.slice(0, -1).join(', ') + ' and ' + xs[xs.length - 1];
  const parts = want.indexOf(1) >= 0 ? ['singles'] : [];
  const rest = want.filter(k => k > 1);
  if (rest.length) parts.push('by ' + series(rest.map(k => k + 's')));
  return parts.join(' and ');
}

function coverPortfolio(legs, stake, rho, assumedDec, sizes) {
  const n = legs.length, N = 1 << n;
  const p = legs.map(l => l.prob);
  // A leg's own stand-in first, then the flat override. `priced` below still
  // counts only what a book quoted, so a filled-in price cannot pass itself
  // off as a posted one.
  const dec = legs.map(l => has(l.dec) ? l.dec
    : (has(l.assumed) ? l.assumed : assumedDec));

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

  // The slips the round robin buys; each pays when all its legs are in the
  // pattern. Restricting which sizes are staked changes what is bought and
  // nothing about how it is priced -- the payout below is still the product of
  // that slip's own legs, at each leg's own price.
  const want = coverSizes(n, sizes);
  const staked_sizes = new Set(want);
  const ret = new Array(N).fill(0), wins = new Array(N).fill(0);
  const counts = {};
  let slips = 0;
  for (let mask = 1; mask < N; mask++) {
    let legsOn = 0;
    for (let i = 0; i < n; i++) if ((mask >> i) & 1) legsOn++;
    if (!staked_sizes.has(legsOn)) continue;
    slips++;
    counts[legsOn] = (counts[legsOn] || 0) + 1;
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
    sizes: want, full_cover: want.length === n,
    counts: want.map(k => ({ legs: k, combinations: counts[k] || 0 })),
    all_priced: legs.every(l => has(l.dec)), assumed_decimal: assumedDec,
    // What each unpriced leg was actually charged, so the note under the table
    // can name the prices the answer rests on rather than one that may not
    // have been used.
    stand_ins: legs.map((l, i) => has(l.dec) ? null : dec[i]).filter(has),
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

function coverToggle(name, st) {
  // `st` is the state slot the picker belongs to. Two builders share this
  // code — the Parlay tab and the one on "Guys I like" — and a hardcoded
  // S.cover here meant clicking a chip on one moved the other's legs.
  st = st || S.cover;
  if (!st.picked) st.picked = [];
  const at = st.picked.indexOf(name);
  if (at >= 0) st.picked.splice(at, 1);
  else st.picked.push(name);
  render(true);
}

// The picker: what is chosen, then how to change it, then everyone who could
// be chosen. Forty checkboxes in a wrapped row made those three things one
// thing — the reader had to re-scan the whole list to answer "who is in?",
// and anyone outside the top forty could not be picked at all.
function coverPicker(pool, blended, extra, st) {
  const f = st || S.cover;
  const inSet = {};
  f.picked.forEach(n => { inSet[n] = 1; });

  const chips = f.picked.map(name => {
    const r = pool.find(p => p.player === name);
    const b = el('button', { class: 'pchip', type: 'button',
      title: 'Remove ' + name });
    b.innerHTML = esc(name) +
      (r ? ' <i>' + pct(r.ours, 0) + '</i>' : '') + ' <span>×</span>';
    b.onclick = () => coverToggle(name, f);
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
        ? ' — <b>' +
          coverBets(f.picked.length,
                    (f.sizes && f.sizes.length) ? f.sizes : null).toLocaleString() +
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
        (det.length ? det.join(' · ')
          : (has(r.estDec) ? 'no price · est ' + american(decToAm(r.estDec))
                           : 'no price')) + '</span></span>';
    b.onclick = () => coverToggle(r.player, f);
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

function paneCover(opts) {
  // Called bare by the Parlay tab, and with a state slot plus a pool filter by
  // "Guys I like", which is this same builder over a chosen subset.
  // Parameterised rather than copied: a second implementation of this pricing
  // would drift from the first the week either was touched, which is the
  // failure this file keeps having — the head-to-head tiles and the slate
  // predicate both got here the same way.
  opts = opts || {};
  const st = opts.state || S.cover;
  const inPool = opts.pool || (() => true);
  const m = M();
  const cov = m.cover || {};
  if (st.decMarket !== m.key) {
    // The flat median is the last resort for a leg the curve cannot price, and
    // the box itself opens blank: blank means "charge each leg what this
    // market charges players like it", which is the answer, and a number in
    // the box means the reader is asking a what-if instead.
    st.dec = has(cov.assumed_dec) ? cov.assumed_dec : 2.0;
    st.decRaw = '';
    st.decMarket = m.key;
  }
  // `estDec` is what this market would plausibly post for a player nobody has
  // quoted, so the picker can say it on the card rather than leaving a reader
  // to discover the number only in the payout table.
  const pool = (m.players || [])
    .filter(r => has(r.ours))
    .filter(inPool)
    .map(r => (r.priced && has(r.dec)) ? r
              : Object.assign({}, r, { estDec: curveDecimal(cov.price_curve, r.ours) }))
    .sort((a, b) => b.ours - a.ours);

  if (!st.picked) st.picked = coverDefault(pool, 5);
  const chosen = pool.filter(r => st.picked.indexOf(r.player) >= 0);

  // No `render()` in these callbacks: `text` re-renders for itself, with the
  // focus restore, and a second render nested inside the change handler tore
  // the field out from under the caret first — so a stake typed one digit at a
  // time lost focus on the first keystroke.
  const money2 = [
    // Raw text and parsed value kept apart, for the same reason the price
    // field does it: `2.` is a normal thing to be in the middle of typing and
    // rewriting it mid-keystroke makes a box that fights the person using it.
    text('Stake per slip', st.stakeRaw,
      v => { st.stakeRaw = v;
             const x = parseMoney(v);
             if (x) st.stake = x; },
      '$2.50'),
    // What was typed is held as typed, and the parsed price beside it. Parsing
    // into the field's own value would rewrite `-2` to something else on the
    // keystroke before `-200`, which is a box that fights the person using it.
    text('Price unpriced legs at', st.decRaw,
      v => { st.decRaw = v;
             const d = parsePrice(v);
             if (d) st.dec = d; },
      has(cov.price_curve) ? 'this market\u2019s curve' : '+120 or 2.20',
      has(cov.assumed_dec)
        ? 'Leave it blank and each unpriced leg is charged what this market posts for a '
          + 'player we rate that highly, read off a line fitted over its '
          + ((cov.price_curve || {}).n || 0) + ' priced players. Type a price to override '
          + 'that for every unpriced leg \u2014 a what-if, and one worth checking against '
          + american(decToAm(cov.assumed_dec)) + ', the median this market actually posts.'
        : 'No player on this market carries a price, so there is nothing to derive a '
          + 'stand-in from and this opens at +100. Every payout below rests on that number '
          + 'rather than on a market.'),
  ];
  // A book sells a round robin by leg-count -- "By 2's" is the doubles and
  // nothing else -- so the full cover is one structure among several rather
  // than the only thing this pane can price. Below two players there is only
  // one structure and the control would be a field with one answer.
  //
  // Sizes the pool no longer has are dropped rather than kept pressed: trim a
  // player and a chip for a size that cannot exist would still read as chosen.
  st.sizes = (st.sizes || []).filter(k => k <= chosen.length);
  if (chosen.length > 1) {
    money2.push(multi('Round robin', st.sizes,
      Array.from({ length: chosen.length }, (_, i) => i + 1).map(k =>
        [k, k === 1 ? 'Singles' : k === chosen.length ? k + '-leg' : 'By ' + k + 's']),
      v => { st.sizes = v.slice().sort((a, b) => a - b); },
      'Every combination',
      'Which slip sizes to back. Every combination is the full cover; By 2s ' +
      'on six players is the 15 doubles for $15 rather than 63 slips for ' +
      '$63. It changes what is bought, never how a slip is priced.'));
  }
  const boxes = coverPicker(pool, m.topk && m.topk.blended, money2, st);

  const kids = [
    el('p', { class: 'muted', html:
      'Pick players, then choose the <b>round robin</b> \u2014 which slip ' +
      'sizes to back. Every combination is the full cover, <b>2\u207f \u2212 1</b> ' +
      'slips; <b>By 2s</b> on six is the 15 doubles, the way a book sells it. ' +
      'The table is what each number of scorers returns.' }),
  ];

  // Whether there is any basis for preferring these numbers to the price, put
  // where the question is being asked. Both halves, never their average: most
  // of the model's accuracy on big disagreements comes from rating players
  // DOWN, and these markets only sell the Yes side — so the blend sells fade
  // skill as though it were a bet. Reported apart, the fade tile is a veto.
  const par = cov.parity;
  if (par && (has(par.disagree_higher_pct) || has(par.disagree_lower_pct))) {
    const par_t = tiles([
      has(par.disagree_higher_pct) ? {
        k: 'Closer \u2014 backable', v: pp(par.disagree_higher_pct, 0) + '%',
        d: (par.disagree_higher_n || 0).toLocaleString() + ' players',
        help: 'On the tenth of players we differ from the book on most, taking ' +
              'only those we rate HIGHER \u2014 the direction these markets let ' +
              'you bet. The percentage by which our average squared miss is ' +
              'smaller than the book\u2019s, over ' + (par.span || '') + '. 0% ' +
              'would mean we match the book, so this is a win. It is not a win ' +
              'rate and there is no 50% baseline.' } : null,
      has(par.disagree_lower_pct) ? {
        k: 'Closer \u2014 fade', v: pp(par.disagree_lower_pct, 0) + '%',
        d: (par.disagree_lower_n || 0).toLocaleString() + ' players',
        help: 'The same comparison for players we rate LOWER than the book. ' +
              'This is the model\u2019s sharpest skill by a wide margin and ' +
              'there is no way to bet it \u2014 these markets only sell the Yes ' +
              'side. Read it as a veto: a big disagreement downward is a player ' +
              'to leave out of a cover.' } : null,
    ]);
    // Two tiles in a full-width auto-fit grid are two very empty boxes. The
    // strip stops at its content instead.
    par_t.className = 'tiles narrow';
    kids.push(par_t);
    kids.push(el('p', { class: 'fine', html:
      'Only the backable half is a bet. A cover multiplies whatever edge each ' +
      'leg carries, so it multiplies that half \u2014 not the average of the ' +
      'two, which is higher because the fade side is sharper.' }));
  }

  kids.push(boxes);

  // A finished entry that means nothing has to say so, or the table quietly
  // answers a different question from the one on screen. But `2.` and `-` are
  // not mistakes, they are the middle of `2.50` and `-200` — and a warning box
  // that appears on those shoves the picker down the page mid-keystroke. Only
  // the two shapes that can only ever be incomplete are silent; `+50` is a
  // finished thought that happens to be wrong, so it still gets told.
  const midStake = /^\$?[0-9,]*\.?$/.test(st.stakeRaw || '');
  const midPrice = /^[+-]?[0-9]*\.?$/.test(st.decRaw || '');
  if (st.stakeRaw && !midStake && !parseMoney(st.stakeRaw)) {
    kids.push(el('div', { class: 'warn-box', html:
      '<b>' + esc(st.stakeRaw) + '</b> is not an amount. Type dollars ' +
      '\u2014 <b>2.50</b>, <b>$2.50</b>, <b>1,000</b>. Still staking <b>' +
      usd(st.stake) + '</b> a slip.' }));
  }
  if (st.decRaw && !midPrice && !parsePrice(st.decRaw)) {
    kids.push(el('div', { class: 'warn-box', html:
      '<b>' + esc(st.decRaw) + '</b> is not a price. Type American \u2014 ' +
      '<b>+120</b>, <b>-200</b> \u2014 or decimal, <b>2.20</b>. Still using ' +
      bothPrices(st.dec) + '.' }));
  }

  // One player is allowed. A cover of one is a single bet — 2^1 - 1 is one
  // slip — and the table still says what it returns and what it costs, which
  // is the question someone with one name in mind is asking. Refusing it made
  // the reader pick a second player they did not want in order to see the
  // first one's numbers.
  if (chosen.length < 1) {
    kids.push(el('div', { class: 'warn-box', text: opts.empty || 'Pick at least one player.' }));
    return card(opts.title || 'Parlay', '', kids);
  }
  if (chosen.length > (cov.max_players || 12)) {
    kids.push(el('div', { class: 'warn-box bad-box', html:
      '<b>' + chosen.length + ' players is ' +
      Math.pow(2, chosen.length).toLocaleString() + ' outcome patterns.</b> ' +
      (cov.max_players || 12) + ' is the most this will enumerate, and that ' +
      'ceiling does not move with the round robin \u2014 every pattern is ' +
      'priced whichever slips you back.' }));
    return card(opts.title || 'Parlay', '', kids);
  }

  const flat = parsePrice(st.decRaw);
  const legs = chosen.map(r => ({
    name: r.player, team: r.team, prob: r.ours,
    dec: r.priced && has(r.dec) ? r.dec : null,
    // Blank box means every unpriced leg is priced off the curve at its own
    // probability, which is the only way this table stops flattering the top
    // of the board: the default five are rated around 55% while the median
    // posted price is +106, so one flat stand-in handed every one of them a
    // 20% overlay that the payout column cannot show — it is built from
    // prices and does not move when the probabilities do. A typed price is an
    // override and beats the curve, because someone who types one is asking a
    // what-if and should get the what-if they asked for.
    assumed: flat ? null : curveDecimal(cov.price_curve, r.ours),
  }));
  const v = coverPortfolio(legs, st.stake, cov.rho || 0,
                           flat || st.dec,
                           st.sizes.length ? st.sizes : null);

  const plural = (k, one, many) => k + ' ' + (k === 1 ? one : many);
  kids.push(el('p', { class: 'muted', html:
    '<b>' + plural(v.bets, 'slip', 'slips') + '</b> on ' +
    plural(v.n, 'player', 'players') +
    (v.n > 1 ? ' \u2014 ' + coverStructure(v.n, v.sizes) + ': ' +
       v.counts.map(c => c.combinations + '\u00d7' + c.legs + '-leg').join(' \u00b7 ')
     : '') +
    ' at $' + cents(v.stake) +
    ' each, <b>' + usd(v.staked) + '</b> staked. ' +
    (v.all_priced
      ? (v.n === 1 ? 'Priced by the book.'
                   : 'All ' + v.n + ' legs priced by the book.')
      : v.priced + ' of ' + plural(v.n, 'leg', 'legs') + ' priced; the rest ' +
        (flat
          ? 'at the ' + bothPrices(v.assumed_decimal) + ' you typed.'
          : 'at what this market posts for players we rate that highly \u2014 ' +
            standInRange(v.stand_ins) + ', fitted over ' +
            ((cov.price_curve || {}).n || 0) + ' priced players.')) }));

  const cols = [
    { k: 'who', label: 'Players who score', t: 1 },
    { k: 'chance', label: 'Chance of this', fmt: x => pct(x, 1) },
    { k: 'wins', label: 'Winning bets' },
    { k: 'ret', label: 'Total returned', fmt: x => usd(x) },
    { k: 'net', label: 'Net on ' + usd(v.staked),
      fmt: x => money(x), cls: x => cls(x) },
  ];
  kids.push(table('cover-rows', cols, v.rows.map(r => ({
    who: r.scored + ' of ' + v.n, chance: r.probability,
    wins: r.winning_bets, ret: r.returned, net: r.net,
  })), {}));

  // With one leg the k-of-n framing says nothing a bettor wants: the whole
  // question is the price against the probability. So it gets the numbers that
  // do answer it — what the price demands, what we make it, and the gap.
  if (v.n === 1) {
    const leg = legs[0];
    const d = has(leg.dec) ? leg.dec
      : (has(leg.assumed) ? leg.assumed : v.assumed_decimal);
    const need = 1 / d;
    const gap = (leg.prob - need) * 100;
    kids.push(el('div', {
      class: 'warn-box ' + (gap > 0 ? 'good-box' : 'bad-box'), html:
        '<b>This is a single bet.</b> At ' + bothPrices(d) + ' the price needs '
        + '<b>' + pct(need, 1) + '</b> to break even and we make it <b>' +
        pct(leg.prob, 1) + '</b> \u2014 ' +
        (gap > 0 ? 'an edge of <b>' + pp(gap, 1)
                 : 'a shortfall of <b>' + Math.abs(gap).toFixed(1)) +
        ' points</b>' +
        (has(leg.dec) ? '.' : ', against a price you assumed rather than one ' +
         'a book has posted \u2014 so the edge is an artefact of that ' +
         'assumption, not a measurement.') }));
  }

  const be = v.breakeven_scored;
  if (v.n > 1) kids.push(el('div', { class: 'warn-box' + (be == null ? ' bad-box' : ' good-box'),
    html: be == null
      ? '<b>No number of scorers turns a profit.</b> Even all ' + v.n +
        ' landing returns ' + usd(v.rows[v.n].returned) + ' against ' +
        usd(v.staked) + ' staked.'
      : '<b>Breakeven is ' + be + ' of ' + v.n + '</b> \u2014 and that happens <b>' +
        pct(v.p_breakeven, 1) + '</b> of the time' +
        (v.rho ? ', with the measured teammate correlation of ' +
          v.rho.toFixed(3) + ' applied' : ', treating the legs as independent') +
        '.' }));

  if (!v.all_priced) {
    kids.push(el('div', { class: 'warn-box', html:
      '<b>The expected result below is not a measured edge.</b> ' +
      (flat
        ? 'Some legs have no market price, so it weighs the model\u2019s own ' +
          'probabilities against the ' + bothPrices(v.assumed_decimal) + ' you ' +
          'typed. Type a price a book would not offer and the table will show ' +
          'you the profit in the assumption: a player we rate at 55% posted at ' +
          '+106 is a 14% overlay a leg, before anyone has been right about ' +
          'anything.'
        : 'Some legs have no market price, so they are charged what this ' +
          'market posts for players we rate that highly (' +
          standInRange(v.stand_ins) + '). That is a reading of a margin curve, ' +
          'not a quote for these players \u2014 it says what a book would ' +
          'plausibly ask, and being close to right about that is the whole ' +
          'difference between a payout table and a wish.') }));
  }
  kids.push(el('p', { class: 'muted', html: v.n === 1
    ? 'Expected result <b>' + money(v.expected_net) + '</b> (' +
      pct(v.expected_roi, 1) + ') on ' + usd(v.staked) + '. With one leg ' +
      'there is nothing to multiply, so this is the edge itself rather than ' +
      'leverage on it \u2014 add a second player and the same edge is ' +
      'compounded, in both directions.'
    : 'Expected result <b>' + money(v.expected_net) + '</b> (' +
      pct(v.expected_roi, 1) + ') against <b>' + money(v.singles_net) + '</b> (' +
      pct(v.singles_roi, 1) + ') for the same ' + usd(v.staked) +
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
    // One line, not the ten-column table this used to be. That table was the
    // whole grading, and it earned its place while nothing in this section had
    // been measured at all. Now that the answer is in, the answer is short —
    // and it was ten columns of it sitting directly under the projection it
    // qualifies. The per-size figures live on in the tooltip, in
    // `cover_backtest.json`, and in `make cover-backtest`.
    const rois = rec.sizes.map(z => z.roi);
    const worse = rec.sizes.filter(z => z.roi < z.singles_roi).length;
    // `roi_beats_zero` is the artifact's own verdict rather than this page
    // re-deciding it from two numbers: profitable means the interval clears
    // zero, not that the point estimate happened to land positive.
    const clears = rec.sizes.filter(z => z.roi_beats_zero).length;
    kids.push(el('p', { class: 'fine',
      title: rec.sizes.map(z => z.n + ' players: ' + pct(z.roi, 1) + ' [' +
        pct(z.roi_lo, 0) + ' to ' + pct(z.roi_hi, 0) + '] over ' + z.weeks +
        ' weeks \u00b7 singles ' + pct(z.singles_roi, 1) +
        ' \u00b7 best week ' + pct(z.top_week_share, 0) +
        ' of everything returned').join('\n'),
      html:
        '<b>Graded.</b> Replayed over ' + rec.weeks + ' weeks (' + rec.span +
        ') at ' + usd(rec.stake) + ' a slip on the prices actually ' +
        'posted, this rule returned between ' +
        pct(Math.min.apply(null, rois), 1) + ' and ' +
        pct(Math.max.apply(null, rois), 1) + ' depending on pool size, and ' +
        (clears
          ? '<b>' + clears + ' of ' + rec.sizes.length + ' sizes had an ' +
            'interval clearing zero.</b>'
          : '<b>no pool size had an interval clearing zero.</b>') +
        (worse ? ' ' + worse + ' of ' + rec.sizes.length + ' returned less ' +
          'than the same money on the singles \u2014 which is what a negative ' +
          'edge per leg does when it is multiplied: a k-fold pays the margin ' +
          'k times.' : '') +
        ' Hover for each size.' }));
  }

  // What `make cover-selection` found, in one line. That measurement is 44
  // variants, a hindsight ceiling, a walk-forward chooser and a random control
  // redrawn five times; none of that belongs under a bet slip, and the single
  // pattern in it that is not one lucky cell does.
  const sel = cov.selection;
  if (sel && !sel.identical && sel.best_pair) {
    const bp = sel.best_pair;
    kids.push(el('p', { class: 'fine', html:
      '<b>Would a different rule have helped?</b> Over the same ' + sel.weeks +
      ' weeks, ranking by the model\u2019s own number instead of the blended ' +
      'one returned <b>' + spct(bp.model_roi, 1) + '</b> at ' + bp.n +
      ' players against <b>' + spct(bp.published_roi, 1) + '</b> \u2014 ahead ' +
      'at ' + sel.model_wins + ' of ' + sel.n_sizes + ' sizes. ' +
      (sel.any_beats_zero ? '' : 'No interval clears zero, ') +
      'and the best of ' + sel.n_variants + ' <i>random</i> orderings reached ' +
      spct(sel.control_best_roi, 0) + ' on the same weeks \u2014 so read this ' +
      'as a direction, not a result. Blending pulls our number toward the ' +
      'price, which is what makes it better calibrated and also what deletes ' +
      'the disagreement a bet lives on.' }));
  } else if (sel && sel.identical) {
    kids.push(el('p', { class: 'fine', html:
      '<b>Would a different rule have helped?</b> Not by re-ranking: this ' +
      'market\u2019s blend does not move the number, so the model\u2019s own ' +
      'ordering and the published one pick the same players at every size. ' +
      'Of ' + sel.n_variants + ' rules tried over ' + sel.weeks + ' weeks, ' +
      'none has an interval clearing zero.' }));
  }

  return card(opts.title || 'Parlay', '', kids);
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

JS_SHORTLIST = r"""
// ── Pane: shortlist ─────────────────────────────────────────────────────
// The board says who scores and the combinations table says what they pay
// together. This is the only pane that asks whether either is worth money, so
// it leads with the graded verdict and puts the week's list underneath it — a
// card of three plays every week trains a reader to take three plays every
// week, and the verdict is the part that says not to.
function paneShortlist() {
  const m = M(), out = el('div');
  const sl = m.shortlist;
  if (!sl) {
    out.appendChild(card('Shortlist',
      'Not built for this market. It needs closing-line value by disagreement ' +
      'size (<code>scripts/13_clv.py</code>) and a priced board for the week.', []));
    return out;
  }

  const rec = sl.record;
  if (rec && rec.arms && rec.arms.length) {
    // Every arm is negative, so the level is not the news. What each filter is
    // worth against the arm above it, and how far the best of them still is
    // from paying for itself, is — and four red numbers in a row said neither.
    const armOf = k => (rec.arms.find(a => a.arm === k) || {});
    const base = armOf('all priced'), best = armOf('we rate higher');
    const lede = (has(base.roi) && has(best.roi))
      ? '<b>Backing every priced player returned ' + pp(base.roi, 1) + '% a bet. ' +
        'Taking only the ones we rate above the price returns ' + pp(best.roi, 1) +
        '% \u2014 the model\u2019s ordering is worth ' +
        (best.roi - base.roi).toFixed(1) + ' points, and still ' +
        best.breakeven_gap_pp.toFixed(1) + ' points of implied probability short ' +
        'of breaking even.</b><br><br>'
      : '';
    out.appendChild(card('This rule, replayed and graded', lede +
      'Every arm is the one above it plus a filter, so the difference between ' +
      'two rows is what that filter bought. Flat stakes at the ' +
      esc(rec.priced_at || 'closing price') + ' over ' +
      (rec.seasons || []).join(', ') +
      ((rec.skipped || []).length
        ? ' (' + rec.skipped.join(', ') + ' has no earlier season to fit the ' +
          'floor from, so it cannot be screened)'
        : '') +
      '. <b>With hindsight</b> is not a rule anyone could have followed \u2014 its ' +
      'floor is fitted on the seasons it is being graded on, so the gap to the ' +
      'row above it is how much of this screen is knowing the answer first.',
      [tiles(rec.arms.map(a => (a.roi == null
        ? { k: a.arm, v: 'stood down', d: a.note || 'bet nothing' }
        : { k: a.arm, v: pp(a.roi, 1) + '%',
            d: (a.arm === 'all priced' || !has(base.roi)
                ? a.n.toLocaleString() + ' bets \u00b7 ' + pp(a.lo, 0) + ' to ' + pp(a.hi, 0)
                : pp(a.roi - base.roi, 1) + ' pts vs backing everything'),
            help: 'Hit ' + pct(a.hit_pct / 100, 1) + ' where the price needed ' +
                  pct(a.breakeven_pct / 100, 1) + ' \u2014 short by ' +
                  a.breakeven_gap_pp.toFixed(1) + ' points of implied probability.' })))]));
  }

  const kids = [];
  (sl.dropped || []).forEach(d => {
    kids.push(el('p', { class: 'fine', html:
      '\u2212' + d.dropped + ' ' + esc(d.filter) + ' \u2192 <b>' + d.left + '</b> left' }));
  });

  if (!sl.rows || !sl.rows.length) {
    kids.push(el('div', { class: 'warn-box', html:
      '<b>' + esc(sl.note || 'Nothing survives every filter this week.') + '</b> ' +
      'That is the answer rather than a gap: every filter above is a ' +
      'measurement, and this week they leave nothing.' }));
    out.appendChild(card(null, null, kids));
    return out;
  }

  const cols = [
    { k: 'player', label: 'Player', t: 1 },
    { k: 'game', label: 'Game', t: 1 },
    { k: 'ours', label: 'Our estimate', fmt: v => pct(v, 1) },
    { k: 'book', label: 'Bookmaker says', fmt: v => pct(v, 1) },
    { k: 'edge_pp', label: 'Difference', fmt: v => pp(v) + ' pts', cls: v => cls(v) },
    { k: 'odds', label: 'Price', t: 1, fmt: v => american(v) },
    { k: 'best_odds', label: 'Best posted', t: 1,
      fmt: (v, r) => has(v) ? american(v) + ' <span class="dim">' +
        esc(r.best_book || '') + '</span>' : '<span class="dim">\u2014</span>',
      title: 'The best price any archived book posted this week. Every backtested return here is measured at the consensus, so it understates a shopped price.' },
    { k: 'shopped_pp', label: 'Shop', fmt: v => has(v) ? pp(v, 2) + ' pts' : '',
      cls: v => cls(v),
      title: 'What the best price is worth against the consensus, in points of implied probability \u2014 the one edge here that does not need the model to be right.' },
    { k: 'band_roi', label: 'Band returned', fmt: (v, r) => has(v)
        ? pp(v, 0) + '% <span class="dim">' + esc(r.band || '') + '</span>' : '',
      cls: v => cls(v),
      title: 'What every bet at this price returned across the whole population, vetoed players included. Context for reading a row, never the reason it is on the list.' },
  ];
  kids.push(table('shortlist', [likeCol()].concat(cols), sl.rows, {}));
  kids.push(el('p', { class: 'note', html:
    'Nothing here is a claim that these are profitable. The strip above says ' +
    'the population they come from loses money; these are the rows the two ' +
    'filters measured on the right population did not reject.' }));
  out.appendChild(card(null, null, kids));
  out.appendChild(fadeCard(sl, rec));
  (sl.tracked || []).forEach(r => out.appendChild(trackedCard(r, sl.tracked_record)));
  out.appendChild(marketShapeCard(m.market_shape));
  out.appendChild(positionCard(m.positions));
  return out;
}

// The table that explains every negative return on this page without reference
// to the model: the book's own error is real and small, its margin is larger,
// and the two together are what you pay above the truth on every bet.
function marketShapeCard(shape) {
  const out = el('div');
  if (!shape || !shape.rows || !shape.rows.length) return out;
  const cols = [
    { k: 'decile', label: 'Decile', t: 1,
      title: 'Tenths of the priced population, ordered by the bookmaker\u2019s own de-vigged number \u2014 its opinion, not its price.' },
    { k: 'n', label: 'Bets', fmt: v => v.toLocaleString() },
    { k: 'book_pct', label: 'Book says', fmt: v => pct(v / 100, 2) },
    { k: 'actual_pct', label: 'Actual', fmt: v => pct(v / 100, 2) },
    { k: 'book_error_pp', label: 'Book error', fmt: v => pp(v, 2) + ' pts',
      cls: v => cls(-v),
      title: 'What the bookmaker\u2019s opinion gets wrong before it charges anything. Positive at the bottom and negative at the top is the favourite-longshot bias: longshots overpriced, favourites underpriced.' },
    { k: 'posted_pct', label: 'Posted implies', fmt: v => pct(v / 100, 2) },
    { k: 'margin_pp', label: 'Margin', fmt: v => pp(v, 2) + ' pts',
      title: 'What it charges for that opinion.' },
    { k: 'overpay_pp', label: 'You overpay', fmt: v => pp(v, 2) + ' pts',
      title: 'The two together \u2014 what you pay above the truth. Nearly constant across the board, which is the whole story: the same four or five points is half the stake on a 5% shot and a tenth of it on a 50% one.' },
    { k: 'roi', label: 'Returned', fmt: v => pp(v, 1) + '%', cls: v => cls(v) },
  ];
  out.appendChild(card('What the market gets wrong, and what it charges',
    esc(shape.span || '') + '. The bookmaker\u2019s own number is genuinely ' +
    'wrong \u2014 too high on longshots, too low on favourites \u2014 and the ' +
    'margin is bigger than the error at every decile. A model would have to ' +
    'beat the de-vigged number by more than the <b>overpay</b> column to ' +
    'profit; on the bets we select we beat it by about two points. That is the ' +
    'entire arithmetic of this project on one screen.',
    [table('market-shape', cols, shape.rows, { nosort: true })]));
  return out;
}

// A rule that looked good in a slice of three seasons, with one good season
// and one bad one out of sample. Kept out of the list above and labelled on
// every line: writing down what it says each week is the only way it can ever
// be settled, and a rule that is re-tuned instead can never fail — every
// failure is absorbed into the next tuning.
function trackedCard(rule, record) {
  const kids = [];
  kids.push(el('div', { class: 'warn-box', html:
    '<b>' + esc(rule.status[0].toUpperCase() + rule.status.slice(1)) + '.</b> ' +
    esc(rule.found) + '. The control: ' + esc(rule.control) + '. Out of sample: ' +
    esc(rule.out_of_sample) }));

  const r = record && record[rule.name];
  if (r && r.picks) {
    kids.push(tiles([
      { k: 'Picks recorded', v: r.picks.toLocaleString(), d: r.weeks + ' weeks' },
      { k: 'Mean CLV', v: has(r.mean_clv_pp) ? pp(r.mean_clv_pp, 2) + ' pts' : '\u2014',
        d: 'price taken vs close',
        help: 'Positive means the market moved toward these picks after they ' +
              'were recorded. Readable in dozens, where profit needs hundreds.' },
      { k: 'Beat the close',
        v: has(r.beat_close_pct) ? pct(r.beat_close_pct, 0) : '\u2014', d: ' ' },
      // Results only appear once a week has actually been played. A rule with
      // picks and no grades is the normal state for a live week, so the two
      // tiles are absent rather than dashed — an empty verdict reads as a
      // verdict.
      r.graded ? { k: 'Landed', v: pct(r.graded.landed_pct, 0),
        d: r.graded.picks + ' graded, ' + r.graded.weeks +
           (r.graded.weeks === 1 ? ' week' : ' weeks'),
        help: rule.kind === 'lay'
          ? 'How often the player did not score, which is what a lay needs.'
          : 'How often the player scored.' } : null,
      r.graded ? { k: 'Returned', v: spct(r.graded.return_pct / 100, 1),
        d: 'flat, at the recorded price',
        help: rule.kind === 'lay'
          ? 'Laying at the de-vigged price — win one unit, lose p/(1-p) — the same convention the fade measurement quotes, and a price no book posts. Capped at +100% by that convention, so a clean week reads as exactly that.'
          : 'Flat stakes at the price recorded when the pick was made, not at the close.' } : null,
    ]));
  }

  if (rule.picks && rule.picks.length) {
    kids.push(table('tracked-' + rule.name.replace(/\W+/g, '-'), [
      { k: 'player', label: 'Player', t: 1 },
      { k: 'game', label: 'Game', t: 1 },
      { k: 'ours', label: 'Our estimate', fmt: v => pct(v, 1) },
      { k: 'book', label: 'Bookmaker says', fmt: v => pct(v, 1) },
      { k: 'edge_pp', label: 'Difference', fmt: v => pp(v) + ' pts', cls: v => cls(v) },
      { k: 'odds', label: 'Price', t: 1, fmt: v => american(v) },
    ], rule.picks, {}));
    kids.push(el('p', { class: 'fine', html:
      'Recorded to <code>data/tracked_picks.csv</code> every time this page is ' +
      'built, whether or not anyone backs them. Not a recommendation \u2014 the ' +
      'point is the record, not the picks.' }));
  } else {
    const needs = rule.kind === 'lay'
      ? 'a player the book prices between ' + rule.min_book_pct.toFixed(1) + '% and ' +
        rule.max_book_pct.toFixed(1) + ' that we rate under ' +
        (rule.max_ratio * 100).toFixed(0) + '% of their number'
      : rule.min_edge_pp + '+ points between ' + american(rule.min_odds) + ' and ' +
        american(rule.max_odds);
    kids.push(el('p', { class: 'fine', html:
      'Nothing on this board matches it this week: it needs ' + needs +
      '. A week with no picks is part of the record.' }));
  }
  return card('Tracked \u2014 ' + esc(rule.name) +
              (rule.kind === 'lay' ? ' (a lay, not a bet at a book)' : ''),
              null, kids);
}

// Reference rather than verdict: the numbers a reader keeps deriving by eye
// while reading any table on this page. "Is 12% good?" is a question you have
// while looking at a board, not while auditing one, so it sits with the board
// rather than in a report card.
function positionCard(pos) {
  const out = el('div');
  if (!pos || !pos.rows || !pos.rows.length) return out;
  const cols = [
    { k: 'position', label: 'Position', t: 1 },
    { k: 'priced_weeks', label: 'Player-weeks', fmt: v => v.toLocaleString() },
    { k: 'scored_pct', label: 'Scored', fmt: v => pct(v / 100, 1),
      title: 'How often a priced player at this position actually scored.' },
    { k: 'book_pct', label: 'Book says', fmt: v => pct(v / 100, 1),
      title: 'The de-vigged price they carried, averaged. Beside the realised rate this is the market\u2019s own accuracy, position by position.' },
    { k: 'ours_pct', label: 'We say', fmt: v => has(v) ? pct(v / 100, 1) : '',
      title: 'Our own average estimate for the same rows. A model two points hot on one position and two cold on another looks perfect in aggregate and is wrong on every row.' },
    { k: 'median_odds', label: 'Median price', t: 1, fmt: v => american(v) },
    { k: 'all_rated_pct', label: 'All rated', fmt: v => pct(v / 100, 1),
      title: 'The same rate over everyone the model rates, priced or not. Far lower, because it counts deep reserves nobody has ever posted a price for \u2014 context, not a bet.' },
  ];
  out.appendChild(card('What each position typically does',
    'Priced players, ' + esc(pos.span || '') + '. Read <b>Scored</b> against ' +
    '<b>Book says</b> for what the market gets right, and against <b>We say</b> ' +
    'for what we do \u2014 the gap between the last two is where a position the ' +
    'model misreads would show up.',
    [table('positions', cols, pos.rows, { nosort: true })]));
  return out;
}

// The half the filters above throw away in their first step, and the only
// group in this project whose measured return clears zero. Counted was not
// enough: a reader told two thirds of the board is a veto and never shown
// which two thirds cannot act on it.
// The margin tile in the units an order book quotes. Backing No at decimal D
// breaks even when (1 - q)(D - 1)(1 - c) = q; laying Yes at L is backing No at
// L / (L - 1). Pinned against the Python in `lay_sheet.price_no`.
function layCeiling(f, c) {
  const q = f.scored_pct / 100;
  const floor = 1 + q / ((1 - q) * (1 - c));
  return floor / (floor - 1);
}

function fadeCard(sl, rec) {
  const out = el('div');
  if (!sl.vetoes || !sl.vetoes.length) return out;
  // The banded measurement, because it describes the list actually shown.
  // Outside that band a veto is still a player to leave out and laying him
  // loses, so mixing the two makes a list nobody can act on.
  const f = rec && (rec.fade_in_band || rec.fade);
  const layable = sl.vetoes.filter(v => v.layable);
  const outside = sl.vetoes.filter(v => !v.layable);
  const kids = [];
  if (f) {
    kids.push(tiles([
      { k: 'They scored', v: pct(f.scored_pct / 100, 2),
        d: 'priced at ' + pct(f.priced_pct / 100, 2),
        help: 'Every player we rated ' + f.min_edge_pp + '+ points below the ' +
              'de-vigged price' +
              (f.band ? ', priced between ' + f.band[0].toFixed(1) + '% and ' +
                        f.band[1].toFixed(1) + '% \u2014 the deciles where the ' +
                        'market\u2019s own bias pays for itself' : '') +
              ', over ' + f.n.toLocaleString() + ' bets, graded on whether they ' +
              'actually scored.' },
      { k: 'Laying at fair', v: pp(f.roi, 1) + '%',
        d: pp(f.lo, 0) + ' to ' + pp(f.hi, 0),
        help: 'What backing the No side at the de-vigged price would have ' +
              'returned. The interval clears zero, which nothing else here ' +
              'does \u2014 and that price does not exist: a live slate carried ' +
              '0 of 142 quotes with a No side.' },
      { k: 'Margin it can carry', v: f.margin_capacity_pct.toFixed(2) + '%',
        d: 'before the edge is gone',
        help: 'How much a No price could hold back and still leave this worth ' +
              'taking. Measured on the No decimal \u2014 which is why it is ' +
              'not comparable to a spread quoted on the Yes price, and why ' +
              'the tile beside it converts one into the other.' },
      { k: 'Worst lay still worth it', v: layCeiling(f, 0.05).toFixed(1),
        d: 'fair is ' + (100 / f.priced_pct).toFixed(1),
        help: 'The highest Yes price you could lay this group at, after 5% ' +
              'commission, and still break even. The gap to fair is the ' +
              'margin tile in a number an exchange actually shows \u2014 and ' +
              'it is wide, which means the spread was never the constraint. ' +
              'Whether a venue lists the market at all is.' },
      { k: 'Exchange, 5% commission',
        v: pp(f.exchange[f.exchange.length - 1].roi, 1) + '%',
        d: 'per unit at risk',
        help: 'An exchange takes commission on winnings rather than margin on ' +
              'the price, which is the only venue where laying a player is ' +
              'possible. Assumes a fill at the de-vigged price, which is ' +
              'optimistic where the book is thin.' },
    ]));
  }
  const cols = [
    { k: 'player', label: 'Player', t: 1 },
    { k: 'game', label: 'Game', t: 1 },
    { k: 'ours', label: 'Our estimate', fmt: v => pct(v, 1) },
    { k: 'book', label: 'Bookmaker says', fmt: v => pct(v, 1) },
    { k: 'edge_pp', label: 'Difference', fmt: v => pp(v) + ' pts', cls: v => cls(v),
      title: 'How far below their price we sit. This is the direction the model is measurably good at, and the direction you cannot buy.' },
    { k: 'odds', label: 'Price', t: 1, fmt: v => american(v) },
  ];
  if (layable.length) {
    kids.push(el('h3', { text: 'In the band where laying pays' }));
    kids.push(table('fades', cols, layable, {}));
  }
  if (outside.length) {
    kids.push(el('h3', { text: 'Below the price, outside that band' }));
    kids.push(table('fades-out', cols, outside, {}));
  }
  kids.push(el('div', { class: 'warn-box', html:
    '<b>These are not bets you can place at a book.</b> The second list is ' +
    'still players to leave out \u2014 of a single, of a parlay, of a cover \u2014 ' +
    'but laying them has measured <i>negative</i>: past the band the book ' +
    'under-prices rather than over-prices, and the same lay returns \u22123% to ' +
    '\u22125%. Only the first list is a bet anybody could place, and only ' +
    'somewhere that lets you lay.' }));
  out.appendChild(card('Fade \u2014 the half no book sells',
    'The filters above spend their first step throwing these away. They are ' +
    'also the only group here whose measured return clears zero, which is the ' +
    'whole shape of this model: it is better at naming who will not score ' +
    'than who will, and only one of those is for sale.', kids));
  return out;
}
"""

JS_LIKED = r"""
// ── Pane: guys I like ───────────────────────────────────────────────────
//
// A list the reader builds by clicking players on the Players and Shortlist
// tables, then works over here. Three things live on it: the same table those
// players came from, a parlay built from them, and every combination of them
// priced out.
//
// Scoped to one season, week and market. "Guys I like this week" is the
// question, and a list that carried across a rollover would answer a different
// one — most of it would be players whose games have been played.
//
// Held in localStorage because this page is rebuilt several times a week and
// has no server to keep anything in. That has one consequence worth being
// honest about: the list lives in the browser that made it. It does not follow
// the file if it is copied elsewhere, and a browser told to block site data
// will refuse the write — `S.likedBroken` catches that and the pane says so
// rather than letting a list quietly fail to save.
const LIKED_NS = 'gil', LIKED_FAV_NS = 'gilfav';

function likedKey(ns, m) {
  return ns + ':' + m.season + ':' + m.week + ':' + m.key;
}

function likedRead(ns, m) {
  try {
    const raw = localStorage.getItem(likedKey(ns, m));
    const v = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? v : [];
  } catch (e) {
    // Private windows, file:// under some settings, and "block site data" all
    // land here. In-memory still works for the session.
    S.likedBroken = true;
    return [];
  }
}

function likedWrite(ns, m, names) {
  try {
    localStorage.setItem(likedKey(ns, m), JSON.stringify(names));
  } catch (e) {
    S.likedBroken = true;
  }
}

function likedCache(slot, ns, m) {
  m = m || M();
  const k = likedKey(ns, m);
  if (!S[slot][k]) S[slot][k] = likedRead(ns, m);
  return S[slot][k];
}

const likedList = m => likedCache('liked', LIKED_NS, m);
const favList = m => likedCache('likedFav', LIKED_FAV_NS, m);
const isLiked = (name, m) => likedList(m).indexOf(name) >= 0;
const isFav = (name, m) => favList(m).indexOf(name) >= 0;

function likedToggle(name) {
  const m = M(), l = likedList(m), at = l.indexOf(name);
  if (at >= 0) {
    l.splice(at, 1);
    // A player off the list cannot stay starred on it. Leaving the star behind
    // makes re-adding them later arrive pre-starred for no reason the reader
    // can trace.
    const f = favList(m), fa = f.indexOf(name);
    if (fa >= 0) { f.splice(fa, 1); likedWrite(LIKED_FAV_NS, m, f); }
  } else {
    l.push(name);
  }
  likedWrite(LIKED_NS, m, l);
  render(true);
}

function favToggle(name) {
  const m = M(), f = favList(m), at = f.indexOf(name);
  if (at >= 0) f.splice(at, 1); else f.push(name);
  likedWrite(LIKED_FAV_NS, m, f);
  render(true);
}

function cellButton(label, on, title, cls, onclick) {
  const b = el('button', {
    class: 'cellbtn' + (cls ? ' ' + cls : '') + (on ? ' on' : ''),
    title: title, type: 'button', 'aria-pressed': on ? 'true' : 'false',
  });
  b.textContent = label;
  b.onclick = ev => { ev.stopPropagation(); onclick(); };
  return b;
}

// The add/remove control, for the tables a player is picked FROM.
function likeCol() {
  return {
    k: '_like', label: '', t: 1, nosort: true,
    title: 'Add a player to "Guys I like" — your own list for this week, kept in this browser.',
    cell: (td, v, r) => td.appendChild(cellButton(
      isLiked(r.player) ? '✓' : '+', isLiked(r.player),
      isLiked(r.player) ? 'On your list — click to remove'
                        : 'Add to "Guys I like"',
      null, () => likedToggle(r.player))),
  };
}

// Every subset of the saved players, priced. The pool is small by
// construction, so this enumerates rather than searching: 2^n - n - 1 slips of
// two legs or more, which at the ceiling below is 4,083.
//
// The per-leg maths is the same as the Combinations tab's — probabilities and
// decimal prices multiplied out, nothing refitted — and `singleWinner` carries
// the same rule: on first TD two players in one game cannot both score first,
// so those slips are impossible rather than merely correlated and are dropped.
function likedSubsets(cand, singleWinner) {
  const n = cand.length, out = [];
  for (let mask = 1; mask < (1 << n); mask++) {
    const idx = [];
    for (let i = 0; i < n; i++) if (mask & (1 << i)) idx.push(i);
    if (idx.length < 2) continue;

    let same = false;
    for (let a = 0; a < idx.length && !same; a++)
      for (let b = a + 1; b < idx.length; b++)
        if (cand[idx[a]].game && cand[idx[a]].game === cand[idx[b]].game) { same = true; break; }
    if (singleWinner && same) continue;

    let ours = 1, mo = 1, book = 1, dec = 1, priced = true;
    for (const i of idx) {
      const p = cand[i];
      ours *= p.ours;
      mo *= has(p.model_only) ? p.model_only : p.ours;
      if (p.priced && has(p.book) && has(p.dec)) { book *= p.book; dec *= p.dec; }
      else priced = false;
    }
    out.push({
      ps: idx.map(i => cand[i]), legs: idx.length, ours: ours, mo: mo,
      book: priced ? book : null, dec: priced ? dec : null,
      ev: priced ? (mo * dec - 1) * 100 : null,
      same: same, priced: priced,
      names: idx.map(i => cand[i].player).join(' + '),
    });
  }
  return out;
}

function paneLiked() {
  const m = M(), out = el('div');
  const names = likedList(m);
  const byName = {};
  (m.players || []).forEach(p => { byName[p.player] = p; });

  if (S.likedBroken) out.appendChild(el('div', { class: 'warn-box', html:
    '<b>This browser will not let the page save your list.</b> It still works ' +
    'for as long as this tab is open, and it will be empty again on reload. ' +
    'Private windows and "block site data" both do this; so does opening the ' +
    'file directly in some browsers.' }));

  if (!names.length) {
    out.appendChild(card('Guys I like', null, [el('p', { class: 'muted', html:
      'Nothing saved for <b>' + esc(m.label) + ', week ' + m.week + '</b> yet. ' +
      'Add players with the <b>+</b> button on the <b>Players</b> or ' +
      '<b>Shortlist</b> tab and they will appear here. ' +
      'The list is per week and per market, and it is kept in this browser.' })]));
    return out;
  }

  // Saved players the board no longer carries keep their row. A row that
  // vanished would be indistinguishable from one never added, and the reason
  // it went is usually the thing worth seeing.
  const rows = names.map(n => byName[n]
    ? Object.assign({}, byName[n], { _fav: isFav(n) })
    : { player: n, stale: true, _fav: isFav(n) });
  const live = rows.filter(r => !r.stale);
  const stale = rows.length - live.length;

  // Favourites first by default; a click on any heading takes over from there.
  rows.sort((a, b) => (b._fav ? 1 : 0) - (a._fav ? 1 : 0)
                   || (b.ours || 0) - (a.ours || 0));

  const favCol = {
    k: '_fav', label: '', t: 1, nosort: true,
    title: 'Star a player. Stars sort to the top and mark the row — they do not change what the parlay or the combinations below draw from, which is the whole list.',
    cell: (td, v, r) => td.appendChild(cellButton(
      r._fav ? '★' : '☆', r._fav,
      r._fav ? 'Starred' : 'Star this player', 'star',
      () => favToggle(r.player))),
  };
  const dropCol = {
    k: '_drop', label: '', t: 1, nosort: true,
    cell: (td, v, r) => td.appendChild(cellButton(
      '×', false, 'Remove from your list', null,
      () => likedToggle(r.player))),
  };
  // The same columns the Players tab draws, so this is that table over a
  // chosen subset rather than a second table that resembles it.
  const cols = [favCol].concat(playerCols(m).map(c => c.k !== 'player' ? c
    : Object.assign({}, c, {
        fmt: (v, r) => r.stale
          ? esc(v) + ' <span class="chip un">not on this week’s board</span>'
          : c.fmt(v, r),
      }))).concat([dropCol]);

  out.appendChild(card('Guys I like', null, [
    table('liked', cols, rows, { rowClass: r => r.stale ? 'stale' : null }),
    el('p', { class: 'rowcount', text:
      names.length + ' saved for ' + m.label + ', week ' + m.week +
      (stale ? ' — ' + stale + ' no longer on this week’s board' : '') +
      '. Stars sort to the top. Click a heading to sort by anything else.' }),
  ]));

  if (stale) out.appendChild(el('div', { class: 'warn-box', html:
    '<b>' + stale + ' saved ' + (stale === 1 ? 'player is' : 'players are') +
    ' not on this week’s board.</b> They are kept here, dimmed and with ' +
    'their numbers blank, because a row disappearing looks exactly like one ' +
    'that was never added. Nothing below uses them — there is no price to ' +
    'use. Remove them with ×.' }));

  // ── Parlay, from this list ─────────────────────────────────────────────
  // The Parlay tab's own builder, pooled to the saved players. Same pricing,
  // same round-robin structures, same ceiling on how many outcome patterns it
  // will enumerate.
  out.appendChild(paneCover({
    state: S.likedCover,
    pool: r => isLiked(r.player),
    title: 'Parlay from your list',
    empty: 'Pick at least one of your saved players.',
  }));

  // ── Every combination of them ──────────────────────────────────────────
  const cap = (m.cover && m.cover.max_players) || 12;
  const cand = live.filter(r => has(r.ours));
  if (cand.length >= 2) {
    const kids = [];
    if (cand.length > cap) {
      kids.push(el('div', { class: 'warn-box bad-box', html:
        '<b>' + cand.length + ' players is ' +
        Math.pow(2, cand.length).toLocaleString() + ' combinations.</b> ' +
        cap + ' is the most this will enumerate. Star the ones you are ' +
        'actually weighing and remove the rest, or read the parlay above, ' +
        'which prices a structure rather than every subset.' }));
      out.appendChild(card('Every combination', null, kids));
      return out;
    }
    const singleWinner = m.key === 'first_td';
    const subs = likedSubsets(cand, singleWinner);
    subs.sort((a, b) => (b.ours || 0) - (a.ours || 0));

    const ccols = [
      { k: 'legs', label: 'Legs' },
      { k: 'names', label: 'Players', t: 1 },
      { k: 'ours', label: 'All score', fmt: v => pct(v, 1),
        title: 'Our chance that every leg on the slip scores — the per-leg numbers multiplied. It assumes the legs are independent, which two players in one game are not.' },
      { k: 'book', label: 'Bookmaker says', fmt: v => has(v) ? pct(v, 1) : '<span class="dim">—</span>',
        title: 'The same product taken on the bookmaker’s own de-vigged numbers. Blank when any leg is unpriced.' },
      { k: 'dec', label: 'Pays', t: 1, sortVal: r => r.dec,
        fmt: v => has(v) ? american(decToAm(v)) : '<span class="dim">—</span>',
        title: 'The combined price, decimal odds multiplied and shown American. Blank when any leg is unpriced — there is no price to multiply.' },
      { k: 'ev', label: 'Expected on $100', fmt: v => has(v) ? money(v) : '', cls: v => cls(v),
        title: 'On our pre-blend number at that combined price. The blend pulls our estimate toward the price it is being judged against, so the blended number cannot judge it.' },
      { k: 'same', label: '', t: 1, nosort: true,
        fmt: v => v ? '<span class="chip warn">same game</span>' : '' },
    ];
    kids.push(table('likedsubs', ccols, subs, {}));
    kids.push(el('p', { class: 'rowcount', text:
      subs.length.toLocaleString() + ' combinations of ' + cand.length +
      ' players, two legs and up. Every one of them, not a ranked selection.' }));
    out.appendChild(card('Every combination', null, kids));

    if (singleWinner) out.appendChild(el('div', { class: 'warn-box', html:
      '<b>Same-game slips are missing on purpose.</b> Only one player scores ' +
      'first in a game, so a slip naming two from the same fixture cannot ' +
      'land — it is impossible rather than merely correlated, and pricing ' +
      'it would put a number on something that has no chance at all.' }));
    else if (subs.some(x => x.same)) out.appendChild(el('div', { class: 'warn-box', html:
      '<b>Slips marked "same game" are not independent.</b> <b>All score</b> ' +
      'multiplies the legs as though they were, which overstates the tail on ' +
      'players who share a fixture — they rise and fall with the same ' +
      'game script. Read those rows as an upper bound.' }));
  }

  return out;
}
"""

JS_LADDER = r"""
// ── Pane: ladder ────────────────────────────────────────────────────────
//
// Roll the whole balance into the next bet and see the path. Four inputs, one
// row per rung, and the arithmetic is not in question: at decimal price d the
// balance is start × d^n if every bet wins.
//
// The thing worth saying is what that sentence carries. "If every bet wins" is
// doing all the work, and a ladder table shows only the branch where it holds
// — the other branch is one row tall and says zero. So the chance of the whole
// run is on the strip beside the payout, at the same size, because a payout
// without it is a number with no scale.
//
// That chance is read off the posted price and is therefore generous. A price
// implies 1/d, which includes the bookmaker's margin, so it sits above what
// the book itself thinks will happen; the true figure is lower by however much
// margin is in the line, which one price cannot reveal. Taken at face value
// the whole ladder is worth exactly its stake — p × d = 1 at every rung, so
// every dollar of upside is paid for by the chance of losing the lot — and the
// margin is what pushes it below that.
function paneLadder() {
  const L = S.ladder, out = el('div');

  out.appendChild(bar([
    text('Starting bankroll', L.startRaw,
      v => { L.startRaw = v; const x = parseMoney(v); if (x) L.start = x; }, '$100'),
    text('Target', L.goalRaw,
      v => { L.goalRaw = v; const x = parseMoney(v); if (x) L.goal = x; }, '$10,000'),
    text('Bets', L.betsRaw,
      v => { L.betsRaw = v; const n = parseInt(String(v).replace(/[^0-9]/g, ''), 10);
             if (n >= 1 && n <= LADDER_MAX) L.bets = n; },
      '10', 'How many rungs to show. ' + LADDER_MAX + ' at most — past that the ' +
      'table is longer than the idea it illustrates.'),
    text('Price each bet', L.oddsRaw,
      v => { L.oddsRaw = v; const d = parsePrice(v); if (d) L.dec = d; },
      '-170 or 1.59',
      'American or decimal, the same as everywhere else on this page. Every ' +
      'rung is priced the same, which is the assumption the table is built on.'),
  ]));

  // `-1` and `2.` are the middle of a price, not a mistake, and a warning that
  // appears on them shoves the table down the page mid-keystroke. Anything
  // that could still become a price is therefore silent — which includes `+50`,
  // a finished thought that happens to be wrong, because `+50` is also the
  // first three characters of `+500`. Only a string no price starts with gets
  // told. Same rule, and the same regex, as the parlay.
  const midPrice = /^[+-]?[0-9]*\.?$/.test(L.oddsRaw || '');
  if (L.oddsRaw && !midPrice && !parsePrice(L.oddsRaw)) {
    out.appendChild(el('div', { class: 'warn-box', html:
      '<b>' + esc(L.oddsRaw) + '</b> is not a price. Type American — ' +
      '<b>+150</b>, <b>-170</b> — or decimal, <b>1.59</b>. Still using ' +
      bothPrices(L.dec) + '.' }));
  }

  const d = L.dec, n = L.bets, start = L.start, goal = L.goal;
  const perLeg = 1 / d;
  const final = start * Math.pow(d, n);
  const runAll = Math.pow(perLeg, n);
  // The inverse question, which is usually the one being asked: how many rungs
  // does this price actually need.
  const need = (goal > start && d > 1)
    ? Math.ceil(Math.log(goal / start) / Math.log(d)) : 0;

  out.appendChild(card(null, null, [tiles([
    { k: 'Final payout', v: usd(final),
      d: n + (n === 1 ? ' bet at ' : ' bets at ') + bothPrices(d),
      help: 'The balance after every one of them wins, rolling the full payout in each time.' },
    { k: 'Net profit', v: money(final - start),
      d: 'on ' + usd(start) + ' staked once',
      help: 'The whole run risks the starting bankroll and nothing more — but it risks all of it, at every rung.' },
    { k: 'Chance of running it', v: pct(runAll, runAll < 0.01 ? 3 : 1),
      d: pct(perLeg, 1) + ' a leg, margin included',
      help: 'Read off the posted price, so it includes the bookmaker’s margin and sits above what the book itself expects. The true figure is lower.' },
    { k: 'Bets to the target', v: need ? String(need) : '—',
      d: need ? 'at ' + bothPrices(d) : (goal <= start ? 'already there' : ''),
      help: 'How many rungs this price needs to clear the target, rounded up.' },
  ])]));

  const hit = final >= goal;
  out.appendChild(el('div', { class: 'warn-box' + (hit ? '' : ' bad-box'), html:
    hit
      ? '<b>Clears ' + usd(goal) + ' by ' + usd(final - goal) + '</b> after ' +
        n + ' winning ' + (n === 1 ? 'bet' : 'bets') + ' — about ' +
        pct(runAll, runAll < 0.01 ? 3 : 1) + ' of the time, at this price and ' +
        'taking it at face value.'
      : '<b>Finishes ' + usd(goal - final) + ' short of ' + usd(goal) + '.</b> ' +
        (need ? need + ' bets at ' + bothPrices(d) + ' would get there, which lands at ' +
           pct(Math.pow(perLeg, need), Math.pow(perLeg, need) < 0.01 ? 3 : 1) + '.'
              : 'A longer price or a lower target.') }));

  const rows = [];
  let bal = start;
  for (let i = 1; i <= n; i++) {
    const open = bal, payout = open * d;
    rows.push({ i: i, open: open, profit: payout - open, payout: payout,
                progress: payout / goal, alive: Math.pow(perLeg, i) });
    bal = payout;
  }
  const cols = [
    { k: 'i', label: 'Bet', nosort: true },
    { k: 'open', label: 'Starting bankroll', fmt: v => usd(v) },
    { k: 'profit', label: 'Profit if it wins', fmt: v => money(v), cls: v => cls(v) },
    { k: 'payout', label: 'Payout, and the next stake', fmt: v => usd(v),
      title: 'The whole balance goes back on. Nothing is ever taken off the table, which is what makes the run compound and what makes it total.' },
    { k: 'alive', label: 'Still alive here',
      fmt: v => pct(v, v < 0.01 ? 3 : 1),
      title: 'The chance of having got this far — every rung to this point won. At the posted price, so generous for the same reason.' },
    { k: 'progress', label: 'Of target', fmt: v => pct(v, 1),
      bar: v => Math.min(1, v) },
  ];
  out.appendChild(card(null, null, [
    table('ladder', cols, rows, { nosort: true }),
    el('p', { class: 'rowcount', text:
      'Every rung assumes the one before it won. The row where one does not is ' +
      'not in this table, and it is the row that ends the run.' }),
  ]));

  out.appendChild(el('div', { class: 'warn-box', html:
    '<b>This is arithmetic, not a plan.</b> It assumes every leg wins, the ' +
    'whole balance rolls over with no stake limit, the same price is there ' +
    'every week, and nothing is voided or cashed out. The first of those is ' +
    'the one that matters: at ' + bothPrices(d) + ' the run lands about ' +
    pct(runAll, runAll < 0.01 ? 3 : 1) + ' of the time — and that figure is ' +
    'generous, because it is read off the posted price and a posted price ' +
    'carries the bookmaker’s margin, so it sits above what the book itself ' +
    'expects. Taken at face value the whole ladder is worth exactly its ' +
    'stake: every dollar of upside is paid for by the chance of losing the ' +
    'lot, and the margin is what pushes it below that. ' +
    'Nothing here draws on the model — no board, no edge, no player. It ' +
    'prices a shape, and the shape is the same whoever is on the ticket.' }));

  return out;
}
"""

JS_SERVED = r"""
// ── Pane: the model being served ────────────────────────────────────────
//
// What is actually scoring this week's board: which model, which promoted
// version, what it was fitted on, and how it did on seasons it never saw.
//
// Two panes that answered "how good is the model" were deleted from this page
// once, and deliberately — they opened it on the model's report card when a
// reader arriving here wants this week. This is not those. It is provenance:
// the recipe behind the numbers on every other tab, which is a different
// question from whether the recipe is any good. It sits last for the same
// reason they were removed, and the page still opens on the shortlist.
//
// Everything here is read off artifacts — the registry's CURRENT.json, the
// market's own feature_cols.pkl, its walk-forward file. Nothing is recomputed
// for display, because a page that recomputes its own provenance can agree
// with itself while disagreeing with what is being served.
function paneServed() {
  const m = M(), w = m.served || {}, r = m.recipe, out = el('div');

  out.appendChild(card(null, null, [tiles([
    { k: 'Market', v: m.label, d: 'season ' + m.season + ', week ' + m.week },
    { k: 'Model', v: (w.model || '—').toUpperCase(),
      d: 'chosen per market, not globally',
      help: 'Set by production_by_target in config/settings.yaml, with the walk-forward numbers behind the choice written beside it.' },
    { k: 'Version', v: w.version || '—',
      d: w.created ? w.created.slice(0, 10) + ' promoted' : ' ',
      help: 'The promoted version from the registry — what `make promote` wrote and what the app serves.' },
    { k: 'Features', v: r ? r.n_features.toLocaleString() : '—',
      d: r ? r.n_families + ' families' + (r.unattributed.length
             ? ' + ' + r.unattributed.length + ' loose' : '') : ' ',
      help: r ? 'Read from ' + r.source + ' — the list the scorer asks the matrix for, so it is what the model is fitted on by definition rather than by description.' : '' },
  ])]));

  if (w.dirty) out.appendChild(el('div', { class: 'warn-box', html:
    '<b>The working tree has moved since this version was promoted.</b> ' +
    'What is scoring the board is still the promoted artifacts, but the code ' +
    'around them is not what was measured. Re-promote to make the two agree.' }));

  (w.problems || []).forEach(p => out.appendChild(
    el('div', { class: 'warn-box bad-box', text: String(p) })));

  if (w.note) out.appendChild(card('Why this version', null, [
    el('p', { class: 'muted', text: w.note }),
    w.verdict ? el('p', { class: 'fine', html:
      'Verdict: <b>' + esc(w.verdict) + '</b>' +
      (w.git ? ' · commit <code>' + esc(String(w.git).slice(0, 10)) + '</code>' : '') })
      : null,
  ]));

  // ── How it scored, season by season ────────────────────────────────────
  if (r && r.seasons && r.seasons.length) {
    const rec = w.recorded || {};
    const cols = [
      { k: 'season', label: 'Test season', t: 1 },
      { k: 'games', label: 'Games' },
      { k: 'top1', label: 'Top 1', fmt: v => pct(v, 1), bar: v => v,
        title: 'How often the player we rank first in a game scored.' },
      { k: 'top3', label: 'Top 3', fmt: v => pct(v, 1),
        title: 'How often at least one of our top three scored.' },
      { k: 'top5', label: 'Top 5', fmt: v => pct(v, 1) },
      { k: 'auc', label: 'AUC', fmt: v => has(v) ? v.toFixed(4) : '',
        title: 'How well the ordering separates scorers from non-scorers across the whole board, not just at the top.' },
      { k: 'brier', label: 'Brier', fmt: v => has(v) ? v.toFixed(4) : '',
        title: 'Squared error on the probabilities themselves. Lower is better, and it punishes confident misses.' },
    ];
    out.appendChild(card('Measured on seasons it never trained on', null, [
      table('wf', cols, r.seasons, { nosort: true }),
      has(rec.top1) ? el('p', { class: 'rowcount', html:
        'Pooled over ' + (rec.games || 0).toLocaleString() + ' games: <b>' +
        pct(rec.top1, 1) + '</b> Top 1, ' + pct(rec.top3, 1) + ' Top 3, ' +
        pct(rec.top5, 1) + ' Top 5' +
        (has(rec.top1_se) ? ' — the standard error on Top 1 is ' +
           pp(rec.top1_se * 100, 1) + ' points, so a difference smaller than ' +
           'that is not a difference.' : '.') }) : null,
    ]));
  }

  // ── What it was fitted on ──────────────────────────────────────────────
  if (r) {
    const fcols = [
      { k: 'name', label: 'Family', t: 1,
        fmt: v => '<code>' + esc(v) + '</code>' },
      { k: 'n', label: 'Columns', bar: (v, row) => v / r.n_features * 4 },
      { k: 'cols', label: 'What they are', t: 1,
        fmt: v => '<span class="dim">' + esc(v.join(', ')) + '</span>' },
    ];
    out.appendChild(card('The ' + r.n_features + ' features it was fitted on', null, [
      table('fams', fcols, r.families, { wrap: true }),
      el('p', { class: 'rowcount', text:
        r.n_families + ' families, grouped by the builder that produced each ' +
        'column. Dropping one column tells you nothing when its neighbours ' +
        'carry the same signal — the family is the unit that gets measured.' }),
    ]));

    if (r.unattributed.length) out.appendChild(el('div', { class: 'warn-box', html:
      '<b>' + r.unattributed.length + ' columns reach the model with no ' +
      'recorded builder.</b> They are real features and they are being used; ' +
      'what is missing is their provenance, because the family map is written ' +
      'from one run of the assembler and does not cover everything derived ' +
      'afterwards. Listed rather than folded into a family, because a feature ' +
      'nobody can attribute is the one worth knowing about: ' +
      '<span class="dim">' + esc(r.unattributed.join(', ')) + '</span>' }));
  } else {
    out.appendChild(el('div', { class: 'warn-box', text:
      'No feature list on disk for this market — models/' + m.key +
      '/feature_cols.pkl is missing, which means nothing here has been trained.' }));
  }

  return out;
}
"""

JS_SHELL = r"""
// ── Shell ───────────────────────────────────────────────────────────────
const TABS = [
  ['shortlist', 'Shortlist', paneShortlist],
  ['cover', 'Parlay', paneCover],
  ['liked', 'Guys I like', paneLiked],
  ['players', 'Players', paneMPlayers],
  ['combos', 'Combinations', paneCombos],
  ['teams', 'Teams', paneTeams],
  ['served', 'Model', paneServed],
  ['ladder', 'Ladder', paneLadder],
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
    b.onclick = () => { S.market = i; S.sort = {}; S.p.game = ''; S.c.games = []; S.t.game = ''; render(); };
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
    js = "\n".join([JS, JS_PLAYERS, JS_COMBOS, JS_TEAMS, JS_SHORTLIST,
                    JS_LIKED, JS_LADDER, JS_SERVED, JS_SHELL])
    labels = " and ".join(m["label"] for m in payload["markets"]) or "NFL"
    return (SHELL
            .replace("__TITLE__", html.escape(f"{labels} — model dashboard"))
            .replace("__CSS__", CSS)
            .replace("__FOOTER__", FOOTER.replace("__BUILT__", html.escape(payload["built"])))
            .replace("__JS__", js)
            .replace("__DATA__", data))
