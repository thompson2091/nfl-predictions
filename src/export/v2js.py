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
                ['ladder', 'Ladder'], ['model', 'Model']];

//: Which sheet is up, and what it is about. One at a time, by construction:
//: a sheet over a sheet on a phone is a thing you cannot get out of.
let SHEET = null;

const TABICON = {
  week: '<path d="M4 6h16M4 12h16M4 18h10"/>',
  combos: '<circle cx="9" cy="9" r="4.5"/><circle cx="15" cy="15" r="4.5"/>',
  slip: '<path d="M5 4h14v16l-3.5-2-3.5 2-3.5-2L5 20z"/>',
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
  scroll.innerHTML = '<div class="inner">' + screenHTML() + '</div>';
  el('slipbarHost').innerHTML = vSlipbar();
  el('tabbar').innerHTML = V2TABS.map(vTab).join('');
  vSheet();
  scroll.scrollTop = y;
}

function screenHTML() {
  switch (S.route) {
    case 'week': return vBoard();
    case 'slip': return vSlip();
    default: return vSoon(S.route);
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
  if (!m || S.route === 'slip') return '';
  const names = S.slip.legs.map(l => esc(surname(l.label || ''))).join(' · ');
  return '<div class="slipbar"><span class="slipbar__count num">'
    + S.slip.legs.length + '</span>'
    + '<span class="slipbar__main"><span class="slipbar__price num">'
    + (has(m.dec) ? american(decToAm(m.dec)) : '—') + '</span>'
    + '<span class="slipbar__legs">' + names + '</span></span>'
    + '<button class="btn btn--primary btn--sm" data-tab="slip">Open</button></div>';
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
  h += '<div class="sect"><div class="card">' + vSortbar(f)
     + (rows.length ? rows.map(r => vRow(r, kind)).join('') : vEmptyFor(f, view))
     + '</div>'
     + '<div class="count">' + rows.length + ' of ' + all.length + ' shown</div>'
     + '</div>';
  return h;
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
  if (poss.length) h += vChip('pos', f.pos || 'Any position', !!f.pos);
  if (kind === 'td') h += vChip('priced',
    f.priced === 'all' ? 'Priced and not'
      : f.priced === 'priced' ? 'Priced only' : 'No price only', f.priced !== 'all');
  const dupes = kind === 'ou'
    ? extraLines(rowsFor(key, 'all').filter(r => r.priced)) : 0;
  if (dupes > 0) h += '<button class="chip" aria-pressed="'
    + (f.allLines ? 'true' : 'false') + '" data-act="alllines">Every posted line'
    + (f.allLines ? '' : ' <span class="c num">+' + dupes + '</span>') + '</button>';
  if (games.length) h += vChip('game',
    f.game || ('All ' + games.length + ' games'), !!f.game);
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
  const metrics = kind === 'ou'
    ? [met('Proj', has(r.proj) ? num2(r.proj) : '—'),
       met('Book', has(r.book) ? pct(r.book) : '—', has(r.book) ? '' : 'v-none'),
       met('Adj', pct(r.ours), '', true),
       met('Edge', has(r.edge) ? spp(r.edge) : '—',
           has(r.edge) ? (r.edge >= 0 ? 'v-good' : 'v-bad') : 'v-none')]
    : [met('Model', has(r.modelOnly) ? pct(r.modelOnly) : '—'),
       met('Book', has(r.book) ? pct(r.book) : '—', has(r.book) ? '' : 'v-none'),
       met('Adj', pct(r.ours), '', true),
       met('Edge', has(r.edge) ? spp(r.edge) : '—',
           has(r.edge) ? (r.edge >= 0 ? 'v-good' : 'v-bad') : 'v-none')];
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
const met = (l, v, cls, ours) => '<span class="metric'
  + (ours ? ' metric--ours' : '') + '"><span class="metric__l">' + l
  + '</span><span class="metric__v num ' + (cls || '') + '">' + v + '</span></span>';

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
function vSoon(route) {
  const label = (V2TABS.find(t => t[0] === route) || V2TABS[0])[1];
  return '<div class="sect"><div class="card">' + vEmpty(label + ' is not converted yet',
    'This screen still lives in the classic board while its components are '
    + 'built against the new design. Everything it does is there and working.')
    + '</div></div>';
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
const allPriced = legs => legs.every(l => has(l.dec));

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

  h += '<div class="totals">'
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

  h += '<div style="display:flex;gap:12px;margin-top:16px">'
    + '<button class="btn btn--secondary" style="flex:1" data-act="ladderthis">'
    + 'Ladder this</button>'
    + '<button class="btn btn--primary" style="flex:1" data-act="saveslip">'
    + (S.saved[slipSignature()] ? 'Saved' : 'Save slip') + '</button></div>';
  h += '</div></div>';

  // How often each number of legs lands, and what that pays. The reason the
  // slip is worth reading rather than just adding up: a four-leg parlay is
  // mostly the three-of-four branch, and that branch pays nothing.
  if (m.rows && m.rows.length) {
    h += '<div class="sect"><div class="card" style="padding:16px">'
      + '<div class="secthead" style="padding:0 0 8px"><span>If this many land</span>'
      + '<span>Chance · Net</span></div>' + vBrk(m) + '</div></div>';
  }
  const g = gradedNote(S.slip.market);
  if (g) h += '<div class="sect"><div class="prose" style="border:0;padding:0 4px">'
    + '<b>Graded:</b> ' + esc(g) + '</div></div>';
  return h + '<div style="height:24px"></div>';
}
const tot = (l, v, tone) => '<div class="total"><span class="total__l">' + l
  + '</span><span class="total__v num"' + (tone ? ' style="color:var(--' + tone + ')"' : '')
  + '>' + v + '</span></div>';

function vBrk(m) {
  return '<table class="brk"><thead><tr><th>Legs in</th><th>Chance</th>'
    + '<th>Net</th></tr></thead><tbody>'
    + (m.rows || []).map(r => '<tr><td>' + r.hit + ' of ' + m.n
      + (r.slipsWon ? ' · ' + r.slipsWon + '/' + m.slips : '') + '</td>'
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
function wire() {
  document.addEventListener('click', e => {
    const t = e.target.closest && e.target.closest('[data-tab],[data-view],'
      + '[data-sheet],[data-act],[data-fav],[data-fav2],[data-add],[data-add2],'
      + '[data-detail],[data-set],[data-drop]');
    if (!t) {
      // A tap anywhere else closes the sheet, which is the gesture a sheet is
      // expected to answer. Not while a conflict is up — that one is a
      // question and has to be answered.
      if (SHEET && !S.conflict) { SHEET = null; vSheet(); }
      return;
    }
    const d = t.dataset || {};

    if (d.tab) { SHEET = null; go(d.tab); return; }
    if (d.view) { S.fw.view = d.view; S.fw.sort = ''; render(); return; }
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
      case 'ladderthis': go('ladder'); break;
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
  document.addEventListener('input', e => {
    const id = e.target && e.target.id;
    if (id === 'q') {
      S.fw.q = e.target.value;
      render(true);
      const again = document.getElementById('q');
      if (again && again.focus) {
        again.focus();
        try { again.setSelectionRange(again.value.length, again.value.length); }
        catch (err) {}
      }
    } else if (id === 'f-stake') {
      S.slip.stakeRaw = e.target.value;
      const x = parseFloat(String(e.target.value).replace(/[^0-9.]/g, ''));
      if (isFinite(x) && x > 0) { S.slip.stake = x; persistSlip(); }
    }
  });
}

function dropLeg(id) {
  S.slip.legs = S.slip.legs.filter(l => l.id !== id);
  persistSlip();
  render(true);
}

document.addEventListener('DOMContentLoaded', () => { wire(); boot(); });
"""


def js() -> str:
    """The v2 view layer, in the order it has to be declared in."""
    return JS + JS_SLIP + JS_SHEETS + JS_ROUTE + JS_EVENTS
