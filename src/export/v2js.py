"""The v2 view layer: the design system's components, over v1's numbers.

v1 builds its DOM through `el()` — one function call per node, 106KB of them.
This is written the way the prototype is, as HTML strings with one delegated
click handler, because that is what the design source looks like and because a
row here is eleven nodes rather than fourteen cells: the machinery v1 needed
to keep a grid honest has nothing to keep.

Every number on screen still comes from v1. `rowsFor`, `applyFilters`,
`slipMath`, `combosOf`, `settle`, `betProb`, `ev100`, the storage layer and
the routing are imported and called, not reimplemented — see `src/export/
pwa.py` for why that is the one rule this version does not bend.

`render` is declared here and nowhere else in the v2 bundle: v1's JS_SHELL,
which owns the other one, is the single module left out. Everything v1's logic
calls — `render(true)` from `toggleLeg`, from `toggleFav`, from `go` — lands
here instead, which is what lets the calculations come across untouched.
"""
from __future__ import annotations

#: Screens, in tab order. The ids are v1's routes, so `go()` and the hash
#: still work and a link into the app still lands where it says.
JS = r"""
// ── The shell ───────────────────────────────────────────────────────────
const V2TABS = [['week', 'Board'], ['combos', 'Combos'], ['slip', 'Slip'],
                ['saved', 'Saved'], ['ladder', 'Ladder'], ['model', 'Model']];

//: Which sheet is up, and what it is about. One at a time, by construction:
//: a sheet over a sheet on a phone is a thing you cannot get out of.
let SHEET = null;

const TABICON = {
  week: '<path d="M4 6h16M4 12h16M4 18h10"/>',
  combos: '<circle cx="9" cy="9" r="4.5"/><circle cx="15" cy="15" r="4.5"/>',
  slip: '<path d="M5 4h14v16l-3.5-2-3.5 2-3.5-2L5 20z"/>',
  saved: '<path d="M4 7.5A2.5 2.5 0 016.5 5H12l2 2h4a2 2 0 012 2v8a2 2 0 01-2 2H6a2 2 0 01-2-2z"/>',
  ladder: '<path d="M5 19h4V9H5zM10 19h4V5h-4zM15 19h4v-6h-4z"/>',
  model: '<path d="M4 16l5-6 4 3 6-8"/>',
};
const I = {
  star: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"><path d="M12 3.5l2.6 5.5 5.9.8-4.3 4.2 1 6-5.2-2.8-5.2 2.8 1-6L3.5 9.8l5.9-.8z"/></svg>',
  starOn: '<svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M12 3.5l2.6 5.5 5.9.8-4.3 4.2 1 6-5.2-2.8-5.2 2.8 1-6L3.5 9.8l5.9-.8z"/></svg>',
  plus: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  check: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7"/></svg>',
  x: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M7 7l10 10M17 7L7 17"/></svg>',
  chev: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>',
  bin: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13"/></svg>',
  mag: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4 4"/></svg>',
};
const tabIcon = k => '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
  + 'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
  + 'stroke-linejoin="round">' + TABICON[k] + '</svg>';

// The four bars the shell is made of, rebuilt together. A partial update
// would be faster and would let the tab bar disagree with the screen it is
// marking as current, which is the one thing it exists to say.
function render(keep) {
  const el = document.getElementById.bind(document);
  const scroll = el('scroll');
  const y = keep && scroll ? scroll.scrollTop : 0;

  el('appbar').innerHTML = vAppbar();
  // A notice is said once and then gone: `loadParlay` sets one when a saved
  // slip has legs this week's board no longer carries, and that is a fact
  // about the load rather than a state of the page.
  const notice = S.notice
    ? '<div class="sect"><div class="banner banner--warn">' + esc(S.notice)
      + '</div></div>' : '';
  S.notice = null;
  scroll.innerHTML = '<div class="inner">' + notice + screenHTML() + '</div>';
  el('slipbarHost').innerHTML = vSlipbar();
  el('tabbar').innerHTML = V2TABS.map(vTab).join('');
  vSheet();
  scroll.scrollTop = y;
}

function screenHTML() {
  switch (S.route) {
    case 'week': return vBoard();
    case 'slip': return vSlip();
    case 'combos': return vCombos();
    case 'ladder': return vLadder();
    case 'saved': return vSaved();
    case 'model': return vModel();
    default: return vBoard();
  }
}

function vAppbar() {
  const label = (V2TABS.find(t => t[0] === S.route) || V2TABS[0])[1];
  // The market names what every screen is about, so it rides in the bar
  // rather than over one board. A pill, and it opens a sheet — the design
  // system has no dropdown, on purpose: a 280px menu anchored to a control
  // is a desktop object.
  const market = MARKET_ROUTES[S.route]
    ? '<button class="market" data-sheet="market">' + esc(marketLabel(S.market))
      + ' ' + I.chev + '</button>'
    : '';
  return '<span class="appbar__mark">' + esc(DATA.brand || 'Pick Six') + '</span>'
    + '<span class="appbar__screen">' + esc(S.route === 'week' ? '' : label) + '</span>'
    + market;
}

function vTab(t) {
  const n = S.slip.legs.length;
  const badge = t[0] === 'slip' && n ? '<span class="bdg">' + n + '</span>' : '';
  return '<button class="tab" data-tab="' + t[0] + '"'
    + (S.route === t[0] ? ' aria-current="page"' : '')
    + '><span class="wrap">' + tabIcon(t[0]) + badge + '</span>' + t[1] + '</button>';
}

// The slip, as a bar above the tabs. It is the only thing on screen that
// follows you between screens, which is what a slip is for — and it is not
// shown on the slip's own screen, where it would be a summary of what is
// already there.
function vSlipbar() {
  const m = slipMath();
  // `slipMath` answers an empty slip with a real object rather than null —
  // zero legs, zero outlay, an all-hit of 1 — so truthiness is not the
  // question. The legs are.
  if (!m.legs.length || S.route === 'slip') return '';
  const names = S.slip.legs.map(l => esc(surname(l.label || ''))).join(' · ');
  const dec = parlayDec(m.legs);
  // The button is behind the bar rather than revealed by it, so the movement
  // can follow a thumb instead of playing an animation after one.
  return '<div class="slipwrap" id="slipwrap">'
    + '<button class="slipdel" data-act="clearslip" aria-label="Clear the slip">'
    + I.bin + ' Clear</button>'
    + '<div class="slipbar"><span class="slipbar__count num">'
    + S.slip.legs.length + '</span>'
    + '<span class="slipbar__main"><span class="slipbar__price num">'
    + (allPriced(m.legs) ? american(decToAm(dec)) : '—') + '</span>'
    + '<span class="slipbar__legs">' + names + '</span></span>'
    + '<button class="btn btn--primary btn--sm" data-tab="slip">Open</button></div>'
    + '</div>';
}
const surname = n => {
  const b = String(n).split(' ');
  return b.length > 1 ? b.slice(1).join(' ').replace(/ (Sr\.|Jr\.|III|II|IV)$/, '') : n;
};

// ── The board ───────────────────────────────────────────────────────────
function vBoard() {
  const f = S.fw, key = S.market, kind = KIND[key] || 'td';
  const m = marketOf(key);
  if (!served(key)) return vEmpty('Not served yet',
    marketLabel(key) + ' has no model behind it in this build.');

  const view = kind === 'ou'
    ? (['priced', 'short'].indexOf(f.view) >= 0 ? f.view : 'all')
    : f.view;
  let rows = rowsFor(key, view === 'priced' ? 'all' : view);
  if (view === 'priced') rows = rows.filter(r => r.priced);
  rows = view === 'short' && kind === 'ou' ? oneTake(rows) : oneLine(rows, f);
  const all = rows;
  rows = applyFilters(rows, f);
  rows = v2sort(rows, f);

  let h = '<div class="sect">' + vSeg(key, kind, m) + vSearch(f) + '</div>'
        + vChips(f, key, kind, all);
  (m.problems || []).forEach(p => {
    h += '<div class="sect"><div class="banner banner--bad">' + esc(String(p)) + '</div></div>';
  });
  if (view === 'short') h += vFunnel(m, key, kind, rows.length);
  // The list is in a box of its own so that typing can replace it without
  // replacing the search input above it. See `patchBoard`.
  h += '<div class="sect" id="boardlist">' + boardList(rows, all, f, view, kind)
     + '</div>';
  return h;
}

// The rows, the sort bar above them and the count under them — everything
// that changes when you type, and nothing that does not.
function boardList(rows, all, f, view, kind) {
  return '<div class="card">' + vSortbar(f)
    + (rows.length ? rows.map(r => vRow(r, kind)).join('') : vEmptyFor(f, view))
    + '</div><div class="count">' + rows.length + ' of ' + all.length
    + ' shown</div>';
}

// Typing replaces the list and leaves the input alone.
//
// It used to re-render the screen and put focus back on the new input, once
// per keystroke. On a desktop that is invisible. On iOS every one of those is
// a fresh focus on a fresh node, and the system answers a fresh focus by
// scrolling and scaling to bring it into view — so the page ended up zoomed,
// and stayed zoomed after the keyboard went away. The input is never replaced
// now, so there is nothing to focus and nothing to zoom to.
function patchBoard() {
  const host = document.getElementById('boardlist');
  if (!host) return render(true);
  const f = S.fw, key = S.market, kind = KIND[key] || 'td';
  const m = marketOf(key);
  const view = kind === 'ou'
    ? (['priced', 'short'].indexOf(f.view) >= 0 ? f.view : 'all')
    : f.view;
  let rows = rowsFor(key, view === 'priced' ? 'all' : view);
  if (view === 'priced') rows = rows.filter(r => r.priced);
  rows = view === 'short' && kind === 'ou' ? oneTake(rows) : oneLine(rows, f);
  const all = rows;
  host.innerHTML = boardList(v2sort(applyFilters(rows, f), f), all, f, view, kind);
}

function v2sort(rows, f) {
  if (!f.sort) return rows;
  const dir = f.dir > 0 ? 1 : -1;
  return rows.slice().sort((a, b) => {
    const x = f.sort === 'player' ? a.player : a[f.sort];
    const y = f.sort === 'player' ? b.player : b[f.sort];
    if (!has(x) && !has(y)) return 0;
    if (!has(x)) return 1;
    if (!has(y)) return -1;
    return typeof x === 'string' ? dir * String(x).localeCompare(String(y))
                                 : dir * (x - y);
  });
}

function vSeg(key, kind, m) {
  const f = S.fw, allRows = rowsFor(key, 'all');
  const shown = oneLine(allRows, f);
  const opts = kind === 'ou'
    ? [['all', 'Everyone', shown.length],
       ['priced', 'Priced', shown.filter(r => r.priced).length],
       ['short', 'Shortlist', ouShortKeys(m).size]]
    : [['all', 'Everyone', (m.players || []).length],
       ['short', 'Shortlist', ((m.shortlist || {}).rows || []).length],
       ['fade', 'Fades', ((m.shortlist || {}).vetoes || []).length]];
  const cur = opts.some(o => o[0] === f.view) ? f.view : 'all';
  return '<div class="seg" role="tablist">' + opts.map(o =>
    '<button role="tab" aria-selected="' + (cur === o[0] ? 'true' : 'false')
    + '" data-view="' + o[0] + '">' + o[1] + ' <span class="c">' + o[2]
    + '</span></button>').join('') + '</div>';
}

function vSearch(f) {
  return '<label class="search">' + I.mag
    + '<input id="q" type="search" placeholder="Player, team or game" value="'
    + esc(f.q) + '" aria-label="Search players, teams and games">'
    + (f.q ? '<button class="ib" style="width:32px;height:32px" data-act="clearq"'
           + ' aria-label="Clear search">' + I.x + '</button>' : '')
    + '</label>';
}

function vChips(f, key, kind, rows) {
  const games = Array.from(new Set(rows.map(r => r.game).filter(Boolean))).sort();
  const poss = Array.from(new Set(rows.map(r => r.pos).filter(Boolean))).sort();
  const nFav = S.favs.length;
  const dirty = f.q || f.game || f.pos || f.favOnly || f.priced !== 'all' || f.allLines;
  let h = '<div class="chiprow">'
    + '<button class="chip" aria-pressed="' + (f.favOnly ? 'true' : 'false')
    + '" data-act="favonly">' + (f.favOnly ? I.starOn : I.star)
      .replace('width="22" height="22"', 'width="15" height="15"')
    + ' Favourites <span class="c num">' + nFav + '</span></button>';
  // Game first, because it is the filter anyone actually reaches for — you
  // watch a fixture, you do not watch a position. It used to sit last, after
  // three chips that are narrowings of a board you have already got.
  if (games.length) h += vChip('game',
    f.game || ('All ' + games.length + ' games'), !!f.game);
  if (poss.length) h += vChip('pos', f.pos || 'Any position', !!f.pos);
  if (kind === 'td') h += vChip('priced',
    f.priced === 'all' ? 'Priced and not'
      : f.priced === 'priced' ? 'Priced only' : 'No price only', f.priced !== 'all');
  const dupes = kind === 'ou'
    ? extraLines(rowsFor(key, 'all').filter(r => r.priced)) : 0;
  if (dupes > 0) h += '<button class="chip" aria-pressed="'
    + (f.allLines ? 'true' : 'false') + '" data-act="alllines">Every posted line'
    + (f.allLines ? '' : ' <span class="c num">+' + dupes + '</span>') + '</button>';
  if (dirty) h += '<button class="chip chip--clear" data-act="clearfilters">Clear</button>';
  return h + '</div>';
}
const vChip = (k, label, on) => '<button class="chip" aria-pressed="'
  + (on ? 'true' : 'false') + '" data-sheet="' + k + '">' + esc(label) + ' '
  + I.chev + '</button>';

const SORTS = [['', 'Default'], ['player', 'Player'], ['ours', 'Adj'],
               ['modelOnly', 'Model'], ['book', 'Book'], ['edge', 'Edge'],
               ['odds', 'Odds'], ['proj', 'Projection'], ['line', 'Line']];
function vSortbar(f) {
  const cur = (SORTS.find(s => s[0] === f.sort) || SORTS[0])[1];
  return '<div class="sortbar"><span class="sortbar__label">Sorted by</span>'
    + '<button class="sortbar__value" data-sheet="sort">' + cur + ' ' + I.chev + '</button>'
    + '<button class="sortbar__dir num" data-act="dir"' + (f.sort ? '' : ' disabled')
    + ' title="' + (f.sort ? '' : 'Pick a column first — there is nothing to reverse')
    + '">' + (f.dir > 0 ? '↑ Low first' : '↓ High first') + '</button></div>';
}

// A player, as a row. Four numbers always visible and the rest a tap away —
// which is the design's answer to the thing v1 spent four attempts on.
function vRow(r, kind) {
  const fav = isFav(r.id), inSlip = legIn(r.id) || legIn(r.id + '|over');
  const priced = r.priced;
  const line = kind === 'ou' && has(r.line)
    ? '<span class="odds num">' + num2(r.line) + '</span>' : '';
  const odds = priced && has(r.odds)
    ? '<span class="odds num">' + american(r.odds) + '</span>'
    : '<span class="odds odds--none">No price</span>';
  const ev = ev100(r);
  const metrics = [
    kind === 'ou' ? met('Proj', has(r.proj) ? num2(r.proj) : '—')
                  : met('Model', has(r.modelOnly) ? pct(r.modelOnly) : '—'),
    met('Book', has(r.book) ? pct(r.book) : '—', has(r.book) ? '' : 'v-none'),
    met('Adj', pct(r.ours), '', true),
    met('Edge', has(r.edge) ? spp(r.edge) : '—',
        has(r.edge) ? (r.edge >= 0 ? 'v-good' : 'v-bad') : 'v-none'),
    // EV earns a place on the phone. Edge is the disagreement and this is
    // what the disagreement is worth at the posted price, which is the
    // question the row is actually being read for — and five of these fit a
    // 390px screen once the gap comes down to 10.
    met('EV $100', has(ev) ? money(ev) : '—',
        has(ev) ? (ev >= 0 ? 'v-good' : 'v-bad') : 'v-none'),
    // Drawn on every row and shown only where there is room for it. A resize
    // does not re-render, so deciding this in JavaScript would leave a window
    // someone had just widened showing a phone's columns.
    met('Open', has(r.openOdds) ? american(r.openOdds) : '—', '', false, true),
  ];
  return '<div class="row">'
    + '<button class="ib' + (fav ? ' ib--on' : '') + '" data-fav="' + esc(r.id)
      + '" aria-label="' + (fav ? 'Remove' : 'Add') + ' favourite ' + esc(r.player)
      + '">' + (fav ? I.starOn : I.star) + '</button>'
    + '<button class="row__main" data-detail="' + esc(r.id) + '">'
      + '<span class="row__top"><span class="row__name">' + esc(r.player) + '</span>'
      + line + odds + '</span>'
      + '<span class="row__meta">' + esc(r.team || '') + ' · ' + esc(r.game || '')
        + (r.status ? ' · ' + esc(r.status) : '') + '</span>'
      + '<span class="metrics">' + metrics.join('') + '</span>'
    + '</button>'
    + '<button class="ib ' + (inSlip ? 'ib--in' : 'ib--add') + '" data-add="'
      + esc(r.id) + '" aria-label="' + (inSlip ? 'Remove ' : 'Add ') + esc(r.player)
      + (inSlip ? ' from slip' : ' to slip') + '">'
      + (inSlip ? I.check : I.plus) + '</button>'
    + '</div>';
}
const met = (l, v, cls, ours, wide) => '<span class="metric'
  + (ours ? ' metric--ours' : '') + (wide ? ' metric--wide' : '')
  + '"><span class="metric__l">' + l + '</span>'
  + '<span class="metric__v num ' + (cls || '') + '">' + v + '</span></span>';

// The rule's funnel, and its record. Both belong to the shortlist view and
// to nothing else: "27 shortlisted" means nothing without the 530 it came
// from, and neither means anything without what backing them returned.
function vFunnel(m, key, kind, shown) {
  const sl = (kind === 'ou' ? m.shortlist : m.shortlist) || {};
  const dropped = sl.dropped || [];
  const first = kind === 'ou' ? (m.rows || []).length
                              : (m.players || []).filter(p => p.priced).length;
  let h = '<div class="funnel"><span class="step num">' + first
        + (kind === 'ou' ? ' on the board' : ' priced') + '</span>';
  dropped.forEach((d, i) => {
    h += '<span class="sep">' + I.chev.replace('d="M6 9l6 6 6-6"', 'd="M9 6l6 6-6 6"') + '</span>'
      + '<span class="step num' + (i === dropped.length - 1 ? ' step--last' : '') + '">'
      + d.left + (i === dropped.length - 1 ? ' shortlisted' : ' left') + '</span>';
  });
  h += '</div>';
  const g = (sl.graded || []).filter(x => x.season === 'held out')[0]
         || (sl.graded || [])[0];
  if (g && has(g.roi)) {
    const spans = g.roi_lo < 0 && g.roi_hi > 0;
    h += '<div class="graded">Graded on seasons it was not fitted on: <b class="'
      + (g.roi >= 0 ? 'pos' : 'neg') + '">' + roiTxt(g.roi) + '</b> a bet over '
      + g.n + ', with a 95% interval of ' + roiTxt(g.roi_lo) + ' to '
      + roiTxt(g.roi_hi)
      + (spans ? ' — which spans zero, so the honest reading is that this rule '
               + 'has not been shown to make or lose money.' : '.') + '</div>';
  } else {
    const arm = armOf(sl.record || {}, 'shortlist');
    if (arm && has(arm.roi)) h += '<div class="graded">Graded '
      + esc((sl.record.seasons || []).join('–')) + ': <b class="'
      + (arm.roi >= 0 ? 'pos' : 'neg') + '">' + roiTxt(arm.roi)
      + '</b> a bet on this rule.</div>';
  }
  return h;
}

function vEmptyFor(f, view) {
  if (f.q) return vEmpty('No one matches ‘' + esc(f.q) + '’',
    'Check the spelling, or clear a filter.', 'Clear filters', 'clearfilters');
  if (view === 'short') return vEmpty('Nothing survives every filter this week',
    'That is an answer, not a gap: no disagreement here has held up against '
    + 'the closing line.');
  if (view === 'fade') return vEmpty('No fades',
    'Players we rate below their price show up here once the board is priced.');
  return vEmpty('Nothing to show', 'Loosen a filter and the board fills back up.',
    'Clear filters', 'clearfilters');
}
function vEmpty(t, b, action, act) {
  return '<div class="empty"><span class="empty__t">' + t + '</span>'
    + '<span class="empty__b">' + b + '</span>'
    + (action ? '<div style="height:4px"></div><button class="btn btn--secondary '
      + 'btn--sm" data-act="' + act + '">' + action + '</button>' : '') + '</div>';
}
"""


JS_SLIP = r"""
// ── The slip ────────────────────────────────────────────────────────────
//
// v1's slip is a 360px panel beside the board and a sheet below 1100px. Here
// it is a screen, which is what a tab bar makes it — and the difference is
// not cosmetic: a screen can be as long as it needs to be, so the breakdown
// and the round robin stop being things you scroll a panel to find.
const parlayDec = legs => legs.reduce((d, l) => has(l.dec) ? d * l.dec : d, 1);
// `every` over nothing is true, so an empty slip read as fully priced and was
// handed to `decToAm` at a decimal of 1 — which is `-100 / 0`, and the bar
// said "-Infinity". All of nothing is not priced; it is nothing.
const allPriced = legs => legs.length > 0 && legs.every(l => has(l.dec));

function vSlip() {
  const m = slipMath();
  if (!m.legs.length) return '<div class="sect"><div class="card">'
    + vEmpty('Your slip is empty', 'Add players with the + on any row.',
             'Go to the board', 'goboard') + '</div></div>';

  const priced = allPriced(m.legs);
  const dec = parlayDec(m.legs);
  let h = '';
  if (S.conflict) h += vConflict();

  h += '<div class="sect"><div class="card" style="padding:4px 16px 16px">';
  h += m.legs.map(l =>
    '<div class="leg"><div class="leg__m"><div class="leg__n">' + esc(l.label)
    + '</div><div class="leg__s">' + esc(l.team || '') + ' · '
    + esc(l.game || '') + '</div></div>'
    + '<span class="odds num">' + (has(l.odds) ? american(l.odds) : 'No price')
    + '</span>'
    + '<button class="ib" data-drop="' + esc(l.id) + '" aria-label="Remove '
    + esc(l.label) + '">' + I.x + '</button></div>').join('');

  h += '<div class="totals" id="sliptotals">'
    + tot('All hit', chanceTxt(m.all))
    + tot('Pays', priced ? american(decToAm(dec)) : '—')
    + tot('EV on $' + (S.slip.stake || 0),
          has(m.ev) ? (m.ev >= 0 ? '+' : '') + money(m.ev) : '—',
          has(m.ev) ? (m.ev >= 0 ? 'good' : 'bad') : null)
    + '</div>';

  h += '<label class="field" style="margin-top:16px"><span class="field__l">'
    + 'Stake per slip</span><span class="field__b"><span class="field__p">$</span>'
    + '<input class="num" id="f-stake" inputmode="decimal" value="'
    + esc(S.slip.stakeRaw) + '"></span></label>';

  // Clear, not Ladder. The ladder is a tab of its own and prices a repeated
  // bet rather than this one, so sending the slip there was an answer to a
  // question nobody had asked. Emptying it is the thing you actually want
  // next to Save, and it goes back to the board because an empty slip is not
  // a screen worth standing on.
  h += '<div style="display:flex;gap:12px;margin-top:16px">'
    + '<button class="btn btn--secondary" style="flex:1" data-act="clearslip">'
    + 'Clear slip</button>'
    + '<button class="btn btn--primary" style="flex:1" data-act="saveslip">'
    + (S.saved[slipSignature()] ? 'Saved' : 'Save slip') + '</button></div>';
  h += '</div></div>';

  // How often each number of legs lands, and what that pays. The reason the
  // slip is worth reading rather than just adding up: a four-leg parlay is
  // mostly the three-of-four branch, and that branch pays nothing.
  if (m.rows && m.rows.length) {
    // The table brings its own headings. A `secthead` over them said the
    // same three words again, one line higher and in a different typeface.
    h += '<div class="sect"><div class="card" style="padding:16px">'
      + vBrk(m.rows, m.n, m.slips) + '</div></div>';
  }
  const g = gradedNote(S.slip.market);
  if (g) h += '<div class="sect"><div class="prose" style="border:0;padding:0 4px">'
    + '<b>Graded:</b> ' + esc(g) + '</div></div>';
  return h + '<div style="height:24px"></div>';
}
const tot = (l, v, tone) => '<div class="total"><span class="total__l">' + l
  + '</span><span class="total__v num"' + (tone ? ' style="color:var(--' + tone + ')"' : '')
  + '>' + v + '</span></div>';

function vBrk(rows, n, slips) {
  return '<table class="brk"><thead><tr><th>Legs in</th><th>Chance</th>'
    + '<th>Net</th></tr></thead><tbody>'
    + (rows || []).map(r => '<tr><td>' + r.hit + ' of ' + n
      + (r.slipsWon ? ' · ' + r.slipsWon + '/' + slips : '') + '</td>'
      + '<td class="num">' + (has(r.chance) ? chanceTxt(r.chance) : '—') + '</td>'
      + '<td class="num ' + (r.net >= 0 ? 'pos' : 'neg') + '">' + money(r.net)
      + '</td></tr>').join('') + '</tbody></table>';
}

// One market per slip, and the prompt that has to be answered. A banner
// rather than a sheet: a sheet over the slip you are being asked about hides
// the thing the question is about.
function vConflict() {
  const c = S.conflict;
  return '<div class="sect"><div class="banner banner--warn"><div>'
    + 'Your slip is <b>' + esc(marketLabel(S.slip.market)) + '</b>. '
    + esc(c.row.player) + ' is <b>' + esc(marketLabel(c.row.key))
    + '</b>, and a book will not price the two together.'
    + '<div style="display:flex;gap:8px;margin-top:12px">'
    + '<button class="btn btn--sm btn--secondary" data-act="conflictkeep">Keep this slip</button>'
    + '<button class="btn btn--sm btn--primary" data-act="conflictswap">Start a new one</button>'
    + '</div></div></div></div>';
}
"""


JS_SHEETS = r"""
// ── Sheets ──────────────────────────────────────────────────────────────
//
// Every choice this app offers is a sheet: the market, each filter, the sort,
// and a player's detail. One pattern, one place to look, and a 44px row for
// every option — where v1 had a 280px anchored menu for the market, native
// `<select>`s for the filters and a fourteenth column for the detail.
function vSheet() {
  const scrim = document.getElementById('scrim');
  const sheet = document.getElementById('sheet');
  if (!SHEET) {
    scrim.className = 'scrim';
    sheet.className = 'sheet';
    sheet.innerHTML = '';
    return;
  }
  sheet.innerHTML = SHEETS[SHEET.kind](SHEET.arg);
  scrim.className = 'scrim open';
  sheet.className = 'sheet open';
}

const SHEETS = {
  market: () => sheetHTML('Market', MENU.map(g =>
    '<div class="secthead" style="padding:12px 0 4px">' + esc(g.title) + '</div>'
    + g.items.map(it => opt(it[1], it[0] === S.market, '', 'market', it[0],
                            !!it[2] || !served(it[0]))).join('')).join('')),

  sort: () => sheetHTML('Sort by', SORTS.map(s =>
    opt(s[1], S.fw.sort === s[0], '', 'sort', s[0])).join('')),

  pos: () => {
    const rows = oneLine(rowsFor(S.market, 'all'), S.fw);
    const poss = Array.from(new Set(rows.map(r => r.pos).filter(Boolean))).sort();
    return sheetHTML('Position', opt('Any position', !S.fw.pos, rows.length, 'pos', '')
      + poss.map(p => opt(p, S.fw.pos === p,
          rows.filter(r => r.pos === p).length, 'pos', p)).join(''));
  },

  priced: () => sheetHTML('Pricing', [['all', 'Priced and not'],
    ['priced', 'Priced only'], ['unpriced', 'No price only']]
    .map(o => opt(o[1], S.fw.priced === o[0], '', 'priced', o[0])).join('')),

  game: () => {
    const rows = oneLine(rowsFor(S.market, 'all'), S.fw);
    const games = Array.from(new Set(rows.map(r => r.game).filter(Boolean))).sort();
    return sheetHTML('Game', opt('All ' + games.length + ' games', !S.fw.game,
        rows.length, 'game', '')
      + games.map(g => opt(g, S.fw.game === g,
          rows.filter(r => r.game === g).length, 'game', g)).join(''));
  },

  cblegs: () => sheetHTML('Legs per slip', [2, 3, 4, 5, 6].map(n =>
    opt(n + ' legs', S.cb.legs === n, '', 'cblegs', n)).join('')),

  cbrank: () => sheetHTML('Rank by', [['likely', 'Most likely'],
    ['price', 'Longest price'], ['ev', 'Expected value']]
    .map(o => opt(o[1], S.cb.rank === o[0], '', 'cbrank', o[0])).join('')),

  cbshow: () => sheetHTML('How many to show', [10, 25, 50, 100].map(n =>
    opt('Top ' + n, S.cb.show === n, '', 'cbshow', n)).join('')),

  // The row, opened. Everything the four visible metrics left out, plus a
  // sentence saying what the row means — which is the thing a column of
  // figures cannot do and the reason this sheet is worth a tap.
  detail: (id) => {
    const r = (rowsFor(S.market, 'all').filter(x => x.id === id))[0];
    if (!r) return sheetHTML('Gone', '<div class="prose" style="border:0">'
      + 'That player is no longer on this board.</div>');
    const kind = KIND[S.market] || 'td';
    const inSlip = legIn(r.id) || legIn(r.id + '|over');
    const metrics = [
      met('Odds', r.priced && has(r.odds) ? american(r.odds) : '—'),
      met('Open', has(r.openOdds) ? american(r.openOdds) : '—'),
      met('Model', has(r.modelOnly) ? pct(r.modelOnly) : '—'),
      met('Book', has(r.book) ? pct(r.book) : '—'),
      met('Adj', pct(r.ours), '', true),
      met('Edge', has(r.edge) ? spp(r.edge) : '—',
          has(r.edge) ? (r.edge >= 0 ? 'v-good' : 'v-bad') : 'v-none'),
      met('EV $100', has(ev100(r)) ? money(ev100(r)) : '—',
          has(ev100(r)) ? (ev100(r) >= 0 ? 'v-good' : 'v-bad') : 'v-none'),
    ];
    if (kind === 'ou') metrics.unshift(
      met('Line', has(r.line) ? num2(r.line) : '—'),
      met('Proj', has(r.proj) ? num2(r.proj) : '—'),
      met('Floor', has(r.lo) ? num2(r.lo) : '—'),
      met('Ceiling', has(r.hi) ? num2(r.hi) : '—'));

    const badges = (r.read ? '<span class="badge badge--'
        + readTone(r.read) + '"><span class="dot"></span>' + esc(r.read)
        + '</span>' : '')
      + (r.pos ? '<span class="badge badge--neutral">' + esc(r.pos) + '</span>' : '')
      + (r.thin ? '<span class="badge badge--warn">' + (r.nBooks || 0)
        + ' book' + (r.nBooks === 1 ? '' : 's') + '</span>' : '');

    const buttons = kind === 'ou'
      ? '<button class="btn btn--secondary" style="flex:1" data-add2="' + esc(r.id)
        + '|under">Under</button><button class="btn btn--primary" style="flex:1"'
        + ' data-add2="' + esc(r.id) + '|over">Over</button>'
      : '<button class="btn btn--secondary" style="flex:1" data-fav2="' + esc(r.id)
        + '">' + (isFav(r.id) ? 'Unfavourite' : 'Favourite') + '</button>'
        + '<button class="btn btn--primary" style="flex:1" data-add2="' + esc(r.id)
        + '">' + (inSlip ? 'Remove from slip' : 'Add to slip') + '</button>';

    return sheetHTML(r.player, '<div style="display:flex;gap:8px;flex-wrap:wrap;'
      + 'padding-bottom:12px">' + badges + '</div>'
      + '<div class="metrics" style="flex-wrap:wrap;gap:16px;padding-bottom:16px">'
      + metrics.join('') + '</div>'
      + '<div class="prose" style="border:0;padding:0">' + explain(r) + '</div>'
      + '<div style="display:flex;gap:12px;margin-top:20px">' + buttons + '</div>',
      (r.team || '') + ' · ' + (r.game || ''));
  },
};

const READ_TONE = { 'strong call': 'good', 'leans': 'neutral',
                    'matches book': 'neutral', 'veto': 'bad' };
const readTone = r => READ_TONE[String(r).toLowerCase()] || 'neutral';

// What the row means, in a sentence. The numbers are already above it; this
// says which way to read them, and says "nothing here" when that is the
// honest answer rather than dressing a one-point gap as a finding.
function explain(r) {
  if (!r.priced) return 'Nobody has quoted him yet. We make it ' + pct(r.ours)
    + ', so he is worth watching when a price appears.';
  if (!has(r.edge)) return 'There is a price but no de-vigged number to compare '
    + 'it with — a book posted one side only.';
  if (r.edge < -2) return 'The book is asking more than we think he is worth. At '
    + pct(r.book) + ' implied against our ' + pct(r.ours)
    + ', the price is the problem rather than the player.';
  if (r.edge < 2) return 'We and the market agree within two points. There is '
    + 'nothing here to act on either way.';
  return 'We have him ' + spp(r.edge) + ' above the de-vigged price. That gap is '
    + 'where the value would be, if the price holds — and the graded record on '
    + 'this market says to weigh it against a negative return.';
}

function sheetHTML(title, body, sub) {
  return '<div class="sheet__grab"></div><div class="sheet__head"><div>'
    + '<div class="sheet__title">' + esc(title) + '</div>'
    + (sub ? '<div style="font-size:13px;color:var(--ink-muted)">' + esc(sub)
           + '</div>' : '')
    + '</div><button class="btn btn--sm" data-act="closesheet">Done</button></div>'
    + '<div class="sheet__body">' + body + '</div>';
}
function opt(label, sel, count, key, val, disabled) {
  return '<button class="opt" aria-selected="' + (sel ? 'true' : 'false')
    + '" data-set="' + esc(key) + ':' + esc(val) + '"'
    + (disabled ? ' disabled style="opacity:.4"' : '') + '>'
    + '<span>' + esc(label) + '</span>'
    + (sel ? '<span class="check">✓</span>'
           : (count !== '' && count !== undefined
              ? '<span class="c num">' + count + '</span>' : '')) + '</button>';
}
"""


JS_ROUTE = r"""
// ── Routing ─────────────────────────────────────────────────────────────
//
// v1's `route` validates the hash against `PAGES`, which lists its five
// pages — and Slip is not one of them, because in v1 the slip is a panel
// beside the board rather than somewhere you go. A tab bar makes it a
// destination, so the valid set is `V2TABS`.
//
// Declared rather than assigned: these are function declarations in the same
// script scope as v1's, and the later one wins. Everything that calls
// `route()` or `go()` — `boot`, the hashchange listener, the cross-links in
// v1's own copy — lands here without knowing.
//
// `MARKET_ROUTES` is a `const` and cannot be redeclared, so it is named for
// v2 and read by `vAppbar`: Saved names its own market, the ladder prices
// whatever the slip holds, and the Model page describes every market at once.
const MARKET_ROUTES = { week: 1, combos: 1 };

function route() {
  const h = (location.hash || '').replace(/^#\/?/, '').split('?')[0];
  S.route = V2TABS.some(t => t[0] === h) ? h : 'week';
  render();
  const s = document.getElementById('scroll');
  if (s) s.scrollTop = 0;
}
function go(page) {
  // Setting the hash fires `hashchange`, which routes and renders. Setting it
  // to what it already is fires nothing, so the render has to be asked for —
  // otherwise tapping the tab you are already on does nothing at all, which
  // reads as a dead control rather than as "you are here".
  const next = '#' + page;
  if (location.hash === next) { render(); return; }
  location.hash = next;
}
"""


JS_EVENTS = r"""
// ── Events ──────────────────────────────────────────────────────────────
//
// One delegated listener for the whole app, rather than a closure per button.
// The shell rebuilds four bars on every render, so handlers attached to nodes
// would be attached to nodes that no longer exist — and the ones that do get
// re-created are re-created for a reason. A `data-` attribute survives that
// because it is data rather than a binding.
//: Every `data-` attribute a click has to reach, in one list.
//:
//: It was a string literal inside `closest`, and six controls were added
//: after it without being added to it: the Combinations pool switch and its
//: Load, the Saved filters, Delete and Load, and the Model page's feature
//: toggle. `closest` returned null, the handler bailed on the first line, and
//: every one of those buttons did nothing at all — silently, because a
//: button that is never reached throws nothing.
//:
//: `pstake` is deliberately absent: it is an input, and the input listener
//: has it. A test holds this list against what the views actually emit.
const CLICKS = ['tab', 'view', 'cbpool', 'sf', 'del', 'open', 'fam', 'load',
                'sheet', 'act', 'fav', 'fav2', 'add', 'add2', 'detail',
                'set', 'drop'];
const CLICK_SEL = CLICKS.map(k => '[data-' + k + ']').join(',');

function wire() {
  document.addEventListener('click', e => {
    const t = e.target.closest && e.target.closest(CLICK_SEL);
    if (!t) {
      // A tap anywhere else closes the sheet, which is the gesture a sheet is
      // expected to answer. Not while a conflict is up — that one is a
      // question and has to be answered.
      if (SHEET && !S.conflict) { SHEET = null; vSheet(); }
      closeSwipe();
      return;
    }
    if (SWIPE.open && !(t.dataset || {}).act) closeSwipe();
    const d = t.dataset || {};

    if (d.tab) { SHEET = null; go(d.tab); return; }
    if (d.view) { S.fw.view = d.view; S.fw.sort = ''; render(); return; }
    if (d.cbpool) { S.cb.pool = d.cbpool; render(); return; }
    if (d.sf) { S.savedFilter = d.sf; render(true); return; }
    if (d.del) { dropParlay(d.del); return; }
    if (d.open) {
      const p2 = S.parlays.map(settle).filter(x => x.id === d.open)[0];
      if (p2) loadParlay(p2);
      return;
    }
    if (d.fam) { S.fam[d.fam] = !S.fam[d.fam]; render(true); return; }
    if (d.load !== undefined) { loadCombo(+d.load); return; }
    if (d.sheet) { SHEET = { kind: d.sheet }; vSheet(); return; }
    if (d.detail) { SHEET = { kind: 'detail', arg: d.detail }; vSheet(); return; }
    if (d.fav) { toggleFav(d.fav); return; }
    if (d.fav2) { toggleFav(d.fav2); vSheet(); return; }
    if (d.drop) { dropLeg(d.drop); return; }
    if (d.add || d.add2) {
      const raw = d.add || d.add2;
      const i = raw.lastIndexOf('|');
      const side = /\|(over|under)$/.test(raw) ? raw.slice(i + 1) : null;
      const id = side ? raw.slice(0, i) : raw;
      const row = rowsFor(S.market, 'all').filter(r => r.id === id)[0];
      if (row) toggleLeg(row, side || (row.kind === 'ou' ? 'over' : null));
      if (d.add2) vSheet();
      return;
    }
    if (d.set) {
      const i = d.set.indexOf(':');
      const k = d.set.slice(0, i), v = d.set.slice(i + 1);
      if (k.slice(0, 2) === 'cb') {
        const key = k.slice(2);
        S.cb[key] = (key === 'rank') ? v : +v;
        SHEET = null; render(); return;
      }
      if (k === 'market') { S.market = v; S.fw.game = ''; }
      else if (k === 'sort') {
        // Tapping the column you are already sorted by reverses it, which is
        // what the arrow on a table heading does and what a sheet cannot say.
        if (S.fw.sort === v) S.fw.dir = -S.fw.dir; else S.fw.dir = -1;
        S.fw.sort = v;
      } else S.fw[k] = v;
      SHEET = null;
      render();
      return;
    }

    switch (d.act) {
      case 'closesheet': SHEET = null; vSheet(); break;
      case 'clearq': S.fw.q = ''; render(); break;
      case 'favonly': S.fw.favOnly = !S.fw.favOnly; render(true); break;
      case 'alllines': S.fw.allLines = !S.fw.allLines; render(true); break;
      case 'dir': S.fw.dir = -S.fw.dir; render(true); break;
      case 'clearfilters':
        S.fw = Object.assign(S.fw, { q: '', game: '', pos: '', priced: 'all',
                                     favOnly: false, allLines: false });
        render();
        break;
      case 'goboard': go('week'); break;
      case 'samegame': S.cb.sameGame = !S.cb.sameGame; render(true); break;
      // Emptied, and back to where you fill it. An empty slip is not a screen
      // worth standing on.
      case 'clearslip': closeSwipe(); clearSlip(); go('week'); break;
      case 'saveslip': saveSlip(); render(true); break;
      case 'conflictkeep': S.conflict = null; render(true); break;
      case 'conflictswap': {
        const c = S.conflict;
        S.conflict = null;
        S.slip.market = c.row.key;
        S.slip.legs = [legOf(c.row, c.side)];
        S.market = c.row.key;
        persistSlip();
        render();
        break;
      }
    }
  });

  // Typing must not cost the caret. A re-render replaces the input, so the
  // value and the selection are put back by hand — v1 does the same thing
  // through `data-fk`, and this is the one input on the board.
  // Every text field patches the part of the screen it changes and leaves
  // itself where it is. Nothing here calls `render`, and that is the whole
  // point: a re-render replaces the input, and replacing a focused input on
  // iOS makes the system scroll and scale to the new one.
  document.addEventListener('input', e => {
    const t = e.target;
    if (!t) return;
    // A saved slip's own stake box, which is keyed by the slip rather than by
    // a document id — there is one per card.
    const ps = t.getAttribute && t.getAttribute('data-pstake');
    if (ps) {
      const x = num(t.value);
      const p2 = S.parlays.filter(q => q.id === ps)[0];
      if (p2 && isFinite(x) && x > 0) {
        p2.stake = x;
        saveParlays(S.parlays.filter(q => !q.last));
        patchParlay(ps);
      }
      return;
    }
    const id = t && t.id;
    if (!id) return;
    if (id === 'q') {
      S.fw.q = t.value;
      patchBoard();
    } else if (id === 'f-stake') {
      S.slip.stakeRaw = t.value;
      const x = num(t.value);
      if (isFinite(x) && x > 0) { S.slip.stake = x; persistSlip(); patchTotals(); }
    } else if (id === 'f-start') {
      S.ladder.startRaw = t.value;
      const x = num(t.value);
      if (isFinite(x) && x > 0) { S.ladder.start = x; patchLadder(); }
    } else if (id === 'f-odds') {
      S.ladder.oddsRaw = t.value;
      const a = parseFloat(String(t.value).replace(/[−–]/g, '-').trim());
      if (isFinite(a) && Math.abs(a) >= 100) { S.ladder.dec = amToDec(a); patchLadder(); }
      else if (isFinite(a) && a > 1 && a < 100) { S.ladder.dec = a; patchLadder(); }
    } else if (id === 'f-bets') {
      S.ladder.betsRaw = t.value;
      const n2 = parseInt(String(t.value).replace(/[^0-9]/g, ''), 10);
      if (isFinite(n2) && n2 > 0) { S.ladder.bets = Math.min(LADDER_MAX, n2); patchLadder(); }
    }
  });
}

const num = v => parseFloat(String(v).replace(/[^0-9.]/g, ''));

// The slip's three totals, and the ladder's whole answer. Same rule as the
// board: replace what changed, never the field being typed into.
function patchTotals() {
  const host = document.getElementById('sliptotals');
  if (!host) return;
  const m = slipMath();
  const dec = parlayDec(m.legs);
  host.innerHTML = tot('All hit', chanceTxt(m.all))
    + tot('Pays', allPriced(m.legs) ? american(decToAm(dec)) : '—')
    + tot('EV on $' + (S.slip.stake || 0),
          has(m.ev) ? (m.ev >= 0 ? '+' : '') + money(m.ev) : '—',
          has(m.ev) ? (m.ev >= 0 ? 'good' : 'bad') : null);
}
function patchLadder() {
  const host = document.getElementById('ladderout');
  if (!host) return;
  host.innerHTML = ladderOut();
}

// A combination, into the slip. Rebuilt rather than remembered: the list is
// re-derived on every render, so the index only means anything right now.
function loadCombo(i) {
  const c = S.cb, key = S.market, kind = KIND[key] || 'td';
  const eligible = r => kind === 'ou' ? r.priced : true;
  const board = oneLine(rowsFor(key, 'all'), null).filter(eligible);
  const pools = kind === 'ou'
    ? { all: board, fav: board.filter(r => isFav(r.id)) }
    : { short: rowsFor(key, 'short').filter(eligible),
        fav: board.filter(r => isFav(r.id)), all: board };
  const pool = (pools[c.pool] || board).slice()
    .sort((a, b) => b.ours - a.ours).slice(0, COMBO_POOL_MAX);
  const k = Math.min(c.legs, pool.length);
  let sets = pool.length >= 2 && choose(pool.length, k) <= COMBO_SETS_MAX
    ? combosOf(pool.length, k) : [];
  let slips = sets.map(ix => {
    let p = 1, d = 1, priced = true;
    const gs = {};
    ix.forEach(j => {
      p *= betProb(pool[j]);
      if (has(pool[j].dec)) d *= pool[j].dec; else priced = false;
      gs[pool[j].game] = 1;
    });
    return { ix: ix, p: p, dec: priced ? d : null,
             ev: priced ? p * ((S.slip.stake || 10) * d - (S.slip.stake || 10))
                        - (1 - p) * (S.slip.stake || 10) : null,
             sameGame: Object.keys(gs).length < ix.length };
  });
  if (!c.sameGame) slips = slips.filter(x => !x.sameGame);
  const rank = { likely: (a, b) => b.p - a.p,
                 price: (a, b) => (b.dec || 0) - (a.dec || 0),
                 ev: (a, b) => (b.ev === null ? -Infinity : b.ev)
                             - (a.ev === null ? -Infinity : a.ev) };
  const s = slips.sort(rank[c.rank] || rank.likely)[i];
  if (!s) return;
  S.slip.market = key;
  S.slip.legs = s.ix.map(j => legOf(pool[j], kind === 'ou' ? 'over' : null));
  persistSlip();
  go('slip');
}

function dropLeg(id) {
  S.slip.legs = S.slip.legs.filter(l => l.id !== id);
  persistSlip();
  render(true);
}

// ── Swipe the slip bar away ─────────────────────────────────────────────
//
// Drag it left and a Clear button comes out from under it. The pattern every
// phone list uses for "get rid of this", and it belongs to the slip bar for
// the same reason it belongs to a mail row: the bar is a thing you are
// carrying around, and the way to put a thing down should not be to open it
// first.
//
// Touch only, by construction. A mouse sends no touch events, and above 900px
// the button is hidden and the transform is neutralised — so this is inert on
// a desktop rather than conditional on one.
const SWIPE = { x: 0, y: 0, dx: 0, live: false, open: false };
//: How far before it counts as a swipe rather than a tap that moved, and how
//: far the bar travels when it is open.
const SWIPE_MIN = 8, SWIPE_OPEN = 112, SWIPE_TAKE = 45;

function wireSwipe() {
  const wrap = () => document.getElementById('slipwrap');

  document.addEventListener('touchstart', e => {
    const w = wrap();
    if (!w || !e.target.closest || !e.target.closest('#slipwrap')) return;
    // A tap on the Clear button is not a drag of the bar over it.
    if (e.target.closest('.slipdel')) return;
    const t = e.touches[0];
    SWIPE.x = t.clientX; SWIPE.y = t.clientY; SWIPE.dx = 0; SWIPE.live = true;
  }, { passive: true });

  document.addEventListener('touchmove', e => {
    if (!SWIPE.live) return;
    const w = wrap();
    if (!w) return;
    const t = e.touches[0];
    const dx = t.clientX - SWIPE.x, dy = t.clientY - SWIPE.y;
    // A vertical drag is the page being scrolled, and taking it would make
    // the board impossible to scroll past the bar.
    if (Math.abs(dy) > Math.abs(dx)) { SWIPE.live = false; return; }
    if (Math.abs(dx) < SWIPE_MIN) return;
    SWIPE.dx = dx;
    w.setAttribute('data-swipe', 'dragging');
    // Follows the thumb, and does not follow it past either end.
    const base = SWIPE.open ? -SWIPE_OPEN : 0;
    const at = Math.max(-SWIPE_OPEN, Math.min(0, base + dx));
    const bar = w.querySelector('.slipbar');
    if (bar) bar.style.transform = 'translateX(' + at + 'px)';
  }, { passive: true });

  document.addEventListener('touchend', () => {
    const w = wrap();
    if (!SWIPE.live || !w) { SWIPE.live = false; return; }
    SWIPE.live = false;
    const bar = w.querySelector('.slipbar');
    if (bar) bar.style.transform = '';
    // Past the halfway mark it settles open, short of it it springs back —
    // so a small accidental drag never leaves a delete button showing.
    if (SWIPE.dx < -SWIPE_TAKE) SWIPE.open = true;
    else if (SWIPE.dx > SWIPE_TAKE) SWIPE.open = false;
    w.setAttribute('data-swipe', SWIPE.open ? 'open' : 'shut');
    SWIPE.dx = 0;
  }, { passive: true });
}

// Opened, then left alone: any other tap closes it. A delete button that
// stays out is one you eventually hit by accident.
function closeSwipe() {
  SWIPE.open = false;
  const w = document.getElementById('slipwrap');
  if (w) w.setAttribute('data-swipe', 'shut');
}

document.addEventListener('DOMContentLoaded', () => { wire(); wireSwipe(); boot(); });
"""


def js() -> str:
    """The v2 view layer, in the order it has to be declared in."""
    return JS + JS_SLIP + JS_SCREENS + JS_SAVED + JS_SHEETS + JS_ROUTE + JS_EVENTS


JS_SCREENS = r"""
// ── Combinations ────────────────────────────────────────────────────────
//
// Every slip you could build from a pool you choose, ranked. The pool control
// is a segmented control because the pools are readings of the same board;
// legs, ranking and how many to show are sheets, because they are lists.
function vCombos() {
  const c = S.cb, key = S.market, kind = KIND[key] || 'td';
  if (!served(key)) return vEmpty('Not served yet',
    marketLabel(key) + ' has no model behind it in this build.');

  // Only a row that can actually be backed belongs in a pool, and on a line
  // market only one line per player — a pool holding all six of a
  // quarterback's passing lines builds slips pairing him with himself.
  const eligible = r => kind === 'ou' ? r.priced : true;
  const board = oneLine(rowsFor(key, 'all'), null).filter(eligible);
  const pools = kind === 'ou'
    ? { all: { label: 'Priced', rows: board },
        fav: { label: 'Favourites', rows: board.filter(r => isFav(r.id)) } }
    : { short: { label: 'Shortlist', rows: rowsFor(key, 'short').filter(eligible) },
        fav: { label: 'Favourites', rows: board.filter(r => isFav(r.id)) },
        all: { label: 'Everyone', rows: board } };
  if (!pools[c.pool]) c.pool = kind === 'ou' ? 'all' : 'short';

  let h = '<div class="sect"><div class="seg" role="tablist">'
    + Object.keys(pools).map(k => '<button role="tab" aria-selected="'
      + (c.pool === k ? 'true' : 'false') + '" data-cbpool="' + k + '">'
      + pools[k].label + ' <span class="c">' + pools[k].rows.length
      + '</span></button>').join('') + '</div></div>';

  h += '<div class="chiprow">'
    + vChip('cblegs', c.legs + ' legs', false)
    + vChip('cbrank', c.rank === 'likely' ? 'Most likely'
        : c.rank === 'price' ? 'Longest price' : 'Expected value', false)
    + vChip('cbshow', 'Top ' + c.show, false)
    + '<button class="chip" aria-pressed="' + (c.sameGame ? 'true' : 'false')
    + '" data-act="samegame">Allow same game</button></div>';

  // Capped, and the cap is stated. Every subset of 24 players taken 6 at a
  // time is 134,596 slips, which the browser will enumerate and no one will
  // read.
  let pool = pools[c.pool].rows.slice().sort((a, b) => b.ours - a.ours);
  const poolFull = pool.length;
  pool = pool.slice(0, COMBO_POOL_MAX);

  const k = Math.min(c.legs, pool.length);
  const sets = pool.length >= 2 && choose(pool.length, k) <= COMBO_SETS_MAX
    ? combosOf(pool.length, k) : [];
  const stake = S.slip.stake || 10;
  let slips = sets.map(ix => {
    let p = 1, d = 1, priced = true;
    const gs = {};
    ix.forEach(i => {
      // `betProb`, not the published number, so a slip's EV here is measured
      // on the same quantity as the EV beside each player on the board.
      p *= betProb(pool[i]);
      if (has(pool[i].dec)) d *= pool[i].dec; else priced = false;
      gs[pool[i].game] = 1;
    });
    return { ix: ix, p: p, dec: priced ? d : null,
             ev: priced ? p * (stake * d - stake) - (1 - p) * stake : null,
             sameGame: Object.keys(gs).length < ix.length };
  });
  if (!c.sameGame) slips = slips.filter(s => !s.sameGame);
  const rank = { likely: (a, b) => b.p - a.p,
                 price: (a, b) => (b.dec || 0) - (a.dec || 0),
                 ev: (a, b) => (b.ev === null ? -Infinity : b.ev)
                             - (a.ev === null ? -Infinity : a.ev) };
  const total = slips.length;
  slips = slips.sort(rank[c.rank] || rank.likely).slice(0, c.show);

  h += '<div class="sect"><div class="card">';
  if (!slips.length) {
    h += vEmpty('No combinations',
      pool.length < 2 ? 'The pool needs at least two players in it.'
                      : 'Allow same-game slips, or widen the pool.');
  } else {
    h += slips.map((s, i) => vCombo(s, i, pool)).join('');
  }
  h += '</div><div class="count">'
    + total.toLocaleString() + ' slips of ' + c.legs + ' from the '
    + pool.length + ' we rate highest'
    + (poolFull > pool.length ? ' (of ' + poolFull + ' eligible)' : '')
    + ' · showing ' + slips.length + '</div></div>';
  return h + '<div style="height:24px"></div>';
}

function vCombo(s, i, pool) {
  const names = s.ix.map(j => esc(comboLeg(pool[j]))).join(' · ');
  const teams = s.ix.map(j => esc(pool[j].team || '')).join(', ');
  return '<div class="combo"><div class="combo__l">' + names + '</div>'
    + '<div class="combo__t">' + teams
    + (s.sameGame ? ' <span class="badge badge--warn" style="height:18px">'
        + 'Same game</span>' : '') + '</div>'
    + '<div class="combo__f">'
    + met('All hit', chanceTxt(s.p))
    + met('Pays', has(s.dec) ? american(decToAm(s.dec)) : '—')
    + met('EV $' + (S.slip.stake || 10), has(s.ev)
        ? (s.ev >= 0 ? '+' : '') + money(s.ev) : '—',
        has(s.ev) ? (s.ev >= 0 ? 'v-good' : 'v-bad') : 'v-none')
    + '<span style="flex:1"></span>'
    + '<button class="btn btn--secondary btn--sm" data-load="' + i + '">Load</button>'
    + '</div></div>';
}

// ── Ladder ──────────────────────────────────────────────────────────────
function vLadder() {
  const L = S.ladder;
  let h = '<div class="sect"><div class="card" style="padding:16px;display:flex;'
    + 'flex-direction:column;gap:16px">'
    + field('Starting bankroll', 'f-start', L.startRaw, 'Dollars', '$')
    + field('Price each rung', 'f-odds', L.oddsRaw, 'American (−170) or decimal (1.59)')
    + field('Rungs', 'f-bets', L.betsRaw, 'Up to ' + LADDER_MAX)
    + '</div></div><div id="ladderout">' + ladderOut() + '</div>';
  return h + '<div style="height:24px"></div>';
}

// Everything the three fields decide, in a box the fields are not inside.
function ladderOut() {
  const L = S.ladder;
  const rows = [];
  let bal = L.start, p = 1;
  for (let i = 1; i <= Math.min(L.bets, LADDER_MAX); i++) {
    bal *= L.dec; p /= L.dec;
    rows.push({ rung: i, bal: bal, p: p, won: bal - L.start });
  }
  const last = rows[rows.length - 1];
  const max = rows.length ? rows[0].p : 1;
  let h = '<div class="sect"><div class="card"><div class="keystats">'
    + keystat('Payout', last ? money(last.bal) : '—', 'good')
    + keystat('Chance', last ? chanceTxt(last.p) : '—', null, true)
    + keystat('At risk', money(L.start), 'bad', true)
    + '</div></div></div>';

  h += '<div class="sect"><div class="card">'
    + '<div class="secthead"><span>Rung · Balance</span><span>Chance</span></div>'
    + rows.map(r => '<div class="rung"><span class="rung__n num">' + r.rung + '</span>'
      + '<span class="rung__b num">' + money(r.bal) + '</span>'
      + '<span class="rung__p num">+' + money(r.won) + '</span>'
      + '<span class="rung__r"><span class="rung__c num">' + chanceTxt(r.p) + '</span>'
      + '<span class="rung__track"><span class="rung__bar" style="width:'
      + Math.max(2, (r.p / max) * 100).toFixed(1) + '%"></span></span></span></div>').join('')
    + '<div class="prose">Every row assumes the one above it won. The branch '
    + 'where it did not is a single row saying zero, and it is the likelier '
    + 'branch from about the third rung on. The chance column is read off the '
    + 'price, so it carries the book’s margin and is kinder than the truth.</div>'
    + '</div></div>';
  return h + '<div style="height:24px"></div>';
}
const field = (label, id, raw, hint, prefix) =>
  '<label class="field"><span class="field__l">' + label + '</span>'
  + '<span class="field__b">' + (prefix ? '<span class="field__p">' + prefix
    + '</span>' : '') + '<input class="num" id="' + id + '" inputmode="decimal" '
  + 'value="' + esc(raw) + '" aria-label="' + label + '"></span>'
  + (hint ? '<span class="field__h">' + esc(hint) + '</span>' : '') + '</label>';
const keystat = (l, v, tone, small) => '<div class="keystat">'
  + '<span class="keystat__l">' + l + '</span>'
  + '<span class="keystat__v num' + (small ? ' keystat__v--sm' : '') + '"'
  + (tone ? ' style="color:var(--' + tone + ')"' : '') + '>' + v + '</span></div>';

// ── Model ───────────────────────────────────────────────────────────────
//
// Top-level numbers for every market that is served, and the features behind
// each one a tap away. No alert boxes and no red: what this page reports is
// measured, and a market that loses to its book says so in a sentence rather
// than in a colour.
function vModel() {
  let h = '';
  const rec = ((marketOf('any').shortlist || {}).record) || {};
  const f = rec.fade;
  if (f && has(f.roi)) {
    h += '<div class="sect"><div class="card" style="padding:16px">'
      + '<div class="secthead" style="padding:0 0 8px"><span>What it is best at</span></div>'
      + '<div class="keystats" style="padding:0">'
      + keystat('Fading a player', roiTxt(f.roi), f.roi >= 0 ? 'good' : 'bad')
      + keystat('Interval', roiTxt(f.lo) + ' to ' + roiTxt(f.hi), null, true)
      + '</div>'
      + '<div class="prose" style="padding:12px 0 0">The model is better at '
      + 'naming who will NOT score than who will. You cannot lay a player at a '
      + 'sportsbook, so this is a reason to keep those players off a parlay '
      + 'rather than a bet you can place.</div></div></div>';
  }
  MENU.forEach(g => g.items.forEach(it => {
    const k = it[0];
    if (!served(k)) return;
    h += (KIND[k] === 'ou' ? vOuModel(k) : vTdModel(k));
  }));
  return h + '<div style="height:24px"></div>';
}

function vTdModel(key) {
  const m = marketOf(key), r = m.recipe;
  if (!r || !r.seasons || !r.seasons.length) return '';
  const ss = r.seasons.slice().sort((a, b) => a.season - b.season);
  const games = ss.reduce((a, s) => a + s.games, 0);
  const span = lo => lo.length < 2 ? pct(lo[0])
    : pct(Math.min.apply(null, lo)) + '–' + pct(Math.max.apply(null, lo));
  return '<div class="sect"><div class="card" style="padding:16px">'
    + '<div class="secthead" style="padding:0 0 8px"><span>'
    + esc(marketLabel(key)) + '</span><span>' + games.toLocaleString()
    + ' games</span></div>'
    + '<div class="keystats" style="padding:0">'
    + keystat('Top pick scored', span(ss.map(s => s.top1)))
    + keystat('One of the top three', span(ss.map(s => s.top3)), null, true)
    + '</div>' + vFamilies(key, r) + '</div></div>';
}

function vOuModel(key) {
  const m = marketOf(key);
  let n = null, ours = null, book = null, span = '';
  const f = m.forward;
  if (f && f.pooled) {
    n = f.pooled.n; ours = f.pooled.model_log_loss;
    book = f.pooled.market_log_loss; span = 'this season so far';
  } else if (m.graded && (m.graded.seasons || []).length) {
    const oos = m.graded.seasons.filter(s => !s.in_sample);
    const s0 = oos[oos.length - 1] || m.graded.seasons[0];
    n = s0.n; ours = has(s0.blend) ? s0.blend : s0.model;
    book = s0.market; span = String(s0.season);
  }
  const mix = has(m.blend)
    ? Math.round(m.blend * 100) + '% / ' + Math.round((1 - m.blend) * 100) + '%'
    : '—';
  const cal = has(ours) && has(book) ? book - ours : null;
  return '<div class="sect"><div class="card" style="padding:16px">'
    + '<div class="secthead" style="padding:0 0 8px"><span>'
    + esc(marketLabel(key)) + '</span><span>' + span + '</span></div>'
    + '<div class="keystats" style="padding:0">'
    + keystat('Served as', mix, null, true)
    + keystat('Lines graded', has(n) ? n.toLocaleString() : '—', null, true)
    + keystat('Calibration', has(cal) ? (cal >= 0 ? '+' : '') + cal.toFixed(4) : '—',
              has(cal) ? (cal >= 0 ? 'good' : 'bad') : null, true)
    + '</div>'
    + '<div class="prose" style="padding:12px 0 0">' + esc(ouModelNote(m, cal))
    + '</div></div></div>';
}
function ouModelNote(m, cal) {
  const w = has(m.blend) ? Math.round(m.blend * 100) : null;
  const mix = w === null ? 'the model'
    : w + '% of our number and ' + (100 - w) + '% of the book’s';
  if (!has(cal)) return 'Served as ' + mix + '. Not yet graded out of sample.';
  return 'Served as ' + mix + '. Calibration is the book’s log loss minus ours, '
    + 'so a negative number means the market is better calibrated than we are — '
    + 'which is what a 7% hold market looks like when you bring a model to it.';
}

// The features, behind a tap. They are worth showing and they are not the
// headline: what a model leans on is not what causes a touchdown.
function vFamilies(key, r) {
  if (!r.families || !r.families.length) return '';
  const open = !!S.fam[key];
  if (!open) return '<button class="btn btn--secondary btn--sm" '
    + 'style="margin-top:12px" data-fam="' + esc(key) + '">Show '
    + r.families.length + ' feature families</button>';
  const fam = r.families.slice().sort((a, b) =>
    (has(b.worth_top1) ? Math.abs(b.worth_top1) : -1)
    - (has(a.worth_top1) ? Math.abs(a.worth_top1) : -1));
  const max = fam.reduce((a, x) => Math.max(a, has(x.worth_top1)
    ? Math.abs(x.worth_top1) : 0), 0) || 1;
  return '<div style="margin-top:12px">' + fam.map(x =>
    '<div class="feat" style="padding-left:0;padding-right:0">'
    + '<div class="feat__h"><span class="feat__n">' + esc(x.name) + '</span>'
    + '<span class="feat__v num">' + (has(x.worth_top1)
        ? spp(x.worth_top1) + ' pp' : 'not measured') + '</span></div>'
    + '<div class="feat__t"><span class="feat__f" style="width:'
    + (has(x.worth_top1) ? (Math.abs(x.worth_top1) / max * 100).toFixed(1) : 0)
    + '%"></span></div>'
    + '<div class="feat__d">' + x.n + ' columns'
    + (has(x.p_value) ? ' · p ' + x.p_value.toFixed(3) : '') + '</div></div>').join('')
    + '<button class="btn btn--secondary btn--sm" style="margin-top:12px" '
    + 'data-fam="' + esc(key) + '">Hide</button>'
    + '<div class="prose" style="padding:12px 0 0">Worth is the drop in '
    + 'out-of-sample top-1 accuracy when the family is shuffled. It says which '
    + 'inputs the model leans on, not which ones cause a touchdown.</div></div>';
}
"""


JS_SAVED = r"""
// ── Saved ───────────────────────────────────────────────────────────────
//
// The slips you kept, settling on their own as results land. A destination
// rather than a section of the Slip screen: these have a life after you build
// them — they go pending, then won or lost, and the summary at the top is a
// record you come back to rather than something you glance at on the way
// somewhere else.
//
// `settle` is v1's and keys results by week as well as by player, because
// `any|Derrick Henry` is a different bet in week 3 than in week 2 and a
// shared key would settle a live parlay from a result it never had.
function vSaved() {
  const all = S.parlays.map(settle);
  if (!all.length) return '<div class="sect"><div class="card">'
    + vEmpty('Nothing saved yet',
             'Build a slip and press Save, and it lands here to settle itself.',
             'Go to the board', 'goboard') + '</div></div>';

  const settled = all.filter(p => p.status !== 'Pending');
  const won = settled.filter(p => p.status === 'Won');
  const net = settled.reduce((a, p) => a + p.net, 0);
  const staked = settled.reduce((a, p) => a + (p.outlay || 0), 0);

  let h = '<div class="sect"><div class="card"><div class="keystats">'
    + keystat('Settled', String(settled.length), null, true)
    + keystat('Won', String(won.length), null, true)
    + keystat('Net', settled.length ? money(net) : '—',
              settled.length ? (net >= 0 ? 'good' : 'bad') : null, true)
    + '</div>'
    + (staked ? '<div class="prose">' + money(staked) + ' staked across '
        + settled.length + ' settled slip' + (settled.length === 1 ? '' : 's')
        + ', for ' + money(net) + '. Saved slips are held in this browser only.'
        + '</div>' : '')
    + '</div></div>';

  const counts = { all: all.length, pending: all.length - settled.length,
                   won: won.length, lost: settled.length - won.length };
  h += '<div class="chiprow">' + [['all', 'All'], ['pending', 'Pending'],
    ['won', 'Won'], ['lost', 'Lost']].map(o =>
    '<button class="chip" aria-pressed="'
    + (S.savedFilter === o[0] ? 'true' : 'false') + '" data-sf="' + o[0] + '">'
    + o[1] + ' <span class="c num">' + counts[o[0]] + '</span></button>').join('')
    + '</div>';

  const keep = p => S.savedFilter === 'all'
    || (S.savedFilter === 'pending' && p.status === 'Pending')
    || (S.savedFilter === 'won' && p.status === 'Won')
    || (S.savedFilter === 'lost' && p.status === 'Lost');
  const shown = all.filter(keep);
  if (!shown.length) return h + '<div class="sect"><div class="card">'
    + vEmpty('Nothing is ' + S.savedFilter,
             'Every saved slip is under one of the other filters.') + '</div></div>';

  h += shown.map(vParlay).join('');
  return h + '<div style="height:24px"></div>';
}

const STATE_TONE = { hit: 'good', miss: 'bad', pending: 'neutral' };

// A saved slip says what the slip said, and then what happened to it.
//
// The same three figures the Slip screen leads with — All hit, Pays, EV — and
// the same payout curve underneath, because a saved slip you cannot read is a
// name and a date. `dec` is computed from the legs rather than read off the
// record: `saveSlip` never wrote one, so v1's own card renders
// `decToAm(undefined)` and prints NaN where the price should be.
//
// Net is linear in the stake, so the stored curve can be re-read at any other
// one — but only against the stake that produced it, which is why `rowStake`
// is saved beside it and never moves.
function vParlay(p) {
  const pend = p.status === 'Pending';
  const tone = pend ? 'neutral' : (p.status === 'Won' ? 'good' : 'bad');
  const dec = parlayDec(p.legs);
  const ratio = p.rowStake > 0 ? (p.stake || 0) / p.rowStake : 1;
  const rows = scaleRows(p.rows, ratio);
  const ev = has(p.ev) ? p.ev * ratio : null;

  let h = '<div class="sect"><div class="card" style="padding:16px">'
    + '<div style="display:flex;justify-content:space-between;align-items:flex-start;'
    + 'gap:12px"><div style="min-width:0">'
    + '<div class="leg__n">' + esc(p.name) + '</div>'
    + '<div class="row__meta">' + esc(p.marketLabel || '') + ' · Week ' + p.week
    + (p.last ? ' · last week' : '') + '</div></div>'
    + '<span class="badge badge--' + tone + '"><span class="dot"></span>'
    + esc(p.status) + '</span></div>';

  // Each leg with the state the results map gave it. A dot rather than a
  // word, because the status above already says the answer and these are how
  // it was arrived at.
  h += '<div style="margin-top:12px">' + p.legs.map(l =>
    '<div class="leg"><div class="leg__m"><div class="leg__s">'
    + '<span class="badge badge--' + (STATE_TONE[l.state] || 'neutral')
    + '" style="height:18px;padding:0 6px"><span class="dot"></span></span> '
    + esc(l.label) + '</div></div>'
    + '<span class="odds num">' + (has(l.odds) ? american(l.odds) : '—')
    + '</span></div>').join('') + '</div>';

  h += '<div class="totals" id="ptot-' + esc(p.id) + '">'
    + tot('All hit', has(p.chance) ? chanceTxt(p.chance) : '—')
    + tot('Pays', allPriced(p.legs) ? american(decToAm(dec)) : '—')
    + tot('EV on $' + (p.stake || 0), has(ev) ? (ev >= 0 ? '+' : '') + money(ev) : '—',
          has(ev) ? (ev >= 0 ? 'good' : 'bad') : null)
    + '</div>';

  if (!pend) h += '<div class="keystats" style="padding:16px 0 0">'
    + keystat('Legs in', p.hits + ' of ' + p.legs.length, null, true)
    + keystat('Result', money(p.net * ratio), p.net >= 0 ? 'good' : 'bad', true)
    + '</div>';

  // Only while it can still be changed. A settled slip's stake is what was
  // staked, and an input on it would invite editing history.
  if (pend) h += '<label class="field" style="margin-top:16px">'
    + '<span class="field__l">Stake per slip</span><span class="field__b">'
    + '<span class="field__p">$</span><input class="num" inputmode="decimal" '
    + 'data-pstake="' + esc(p.id) + '" value="' + esc(String(p.stake))
    + '" aria-label="Stake per slip"></span></label>';

  h += '<div id="pbrk-' + esc(p.id) + '" style="margin-top:16px">'
    + (rows && rows.length ? vBrk(rows, p.legs.length, p.slips || 1) : '')
    + '</div>';

  h += '<div style="display:flex;gap:12px;margin-top:16px">'
    + '<button class="btn btn--secondary" style="flex:1" data-del="' + esc(p.id)
    + '">Delete</button>'
    + '<button class="btn btn--primary" style="flex:1" data-open="' + esc(p.id)
    + '">' + (pend ? 'Load into slip' : 'Rebuild for this week') + '</button>'
    + '</div>';
  return h + '</div></div>';
}

// A saved slip's stake, changed on its own card. The figures it decides are
// patched where they sit — the same rule the board and the ladder follow, and
// for the same reason: re-rendering would replace the field being typed into,
// and iOS answers a fresh focus by scaling to it.
function patchParlay(id) {
  const p = S.parlays.map(settle).filter(x => x.id === id)[0];
  if (!p) return;
  const ratio = p.rowStake > 0 ? (p.stake || 0) / p.rowStake : 1;
  const ev = has(p.ev) ? p.ev * ratio : null;
  const dec = parlayDec(p.legs);
  const tots = document.getElementById('ptot-' + id);
  if (tots) tots.innerHTML =
    tot('All hit', has(p.chance) ? chanceTxt(p.chance) : '—')
    + tot('Pays', allPriced(p.legs) ? american(decToAm(dec)) : '—')
    + tot('EV on $' + (p.stake || 0), has(ev) ? (ev >= 0 ? '+' : '') + money(ev) : '—',
          has(ev) ? (ev >= 0 ? 'good' : 'bad') : null);
  const brk = document.getElementById('pbrk-' + id);
  const rows = scaleRows(p.rows, ratio);
  if (brk) brk.innerHTML = rows && rows.length
    ? vBrk(rows, p.legs.length, p.slips || 1) : '';
}

function dropParlay(id) {
  S.parlays = S.parlays.filter(p => p.id !== id);
  // Only this week's list is ours to write. Last week's is read from its own
  // key and shown for reference, so deleting from it would write a key the
  // rollover owns.
  saveParlays(S.parlays.filter(p => !p.last));
  render(true);
}
"""
