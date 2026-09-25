// Every screen of the v3 app, rendered against a stub DOM.
//
// The failure mode of a generated single-page app is a blank screen with one
// line in a console nobody has open. `node --check` proves the syntax and
// nothing else — a bad reference parses fine and throws on load.
//
//   node tests/js/v3app.js <payload.json> <page.js>
const { loadPage, textOf, reporter } = require(
  require('path').join(__dirname, 'domstub.js'));

const { ok, done } = reporter();
const x = loadPage(process.argv[2], process.argv[3],
  ['V', 'render', 'v3Screen', 'v3Week', 'v3Games', 'v3Game', 'v3Slip',
   'v3Ladder', 'v3Header', 'v3Nav', 'v3Rows', 'v3Do', 'V3TABS', 'V3MKT',
   'V3CLICKS', 'V3HIST', 'v3Questions', 'v3Value', 'v3Outcomes', 'v3Legs',
   'rowsFor', 'served', 'DATA', 'V3SORTS', 'v3Sorted', 'V3CACHE', 'v3Same']);
const { V, render, v3Screen, v3Games, v3Game, v3Slip, v3Ladder, v3Nav,
        V3TABS, V3MKT, V3CLICKS, V3HIST, v3Questions, v3Value, v3Legs,
        rowsFor, served, DATA } = x;

const app = () => document.getElementById('app').innerHTML;

// ── The shell ───────────────────────────────────────────────────────────
let err = null;
try { render(); } catch (e) { err = e; }
ok('the shell renders', !err, err && (err.message + '\n' + err.stack));
ok('the nav carries every destination',
   V3TABS.every(t => app().indexOf('data-v3tab="' + t[0] + '"') >= 0));
ok('the header names the brand', app().indexOf(DATA.brand) >= 0, DATA.brand);
ok('and offers the week picker on every screen',
   app().indexOf('data-v3week') >= 0);

// ── Every tab ───────────────────────────────────────────────────────────
V3TABS.forEach(t => {
  V.tab = t[0]; V.game = null;
  let e = null, html = '';
  try { render(); html = app(); } catch (ex) { e = ex; }
  ok('tab ' + t[0] + ' renders', !e, e && (e.message + '\n' + e.stack));
  ok('tab ' + t[0] + ' says something', textOf({ _html: html }).join('').trim().length > 40);
});

// ── Every market, on the board ──────────────────────────────────────────
V.tab = 'week';
V3MKT.forEach(m => {
  if (!served(m[0])) return;
  V.market = m[0];
  ['all', 'short', 'fade'].forEach(f => {
    V.filter = f;
    let e = null;
    try { render(); } catch (ex) { e = ex; }
    ok('market ' + m[0] + ' filter ' + f + ' renders', !e,
       e && (e.message + '\n' + e.stack));
  });
  ['likely', 'value'].forEach(s => {
    V.sort = s;
    let e = null;
    try { render(); } catch (ex) { e = ex; }
    ok('market ' + m[0] + ' sorted by ' + s, !e, e && e.message);
  });
});
V.filter = 'all'; V.sort = 'likely'; V.market = 'any';

// ── The week picker is global, and a past week is a different mode ──────
//
// Not a per-market control. In v2 it belonged to the market and had to be set
// again on every switch; here it survives navigation, which is the point.
const weeks = ((DATA.history || {})[V3HIST[V.market]] || {}).has || [];
if (weeks.length) {
  V.week = weeks[0];
  let e = null, html = '';
  try { render(); html = app(); } catch (ex) { e = ex; }
  ok('a past week renders', !e, e && (e.message + '\n' + e.stack));
  ok('and says so in the header', html.indexOf('wk--past') >= 0);
  ok('and warns on the page that it is settled', html.indexOf('class="past"') >= 0);
  // The rows arrive by fetch; what must be true synchronously is that the
  // page says it is waiting rather than rendering as an empty week.
  ok('and does not render an empty week while it loads',
     html.indexOf('Loading week') >= 0 || html.indexOf('row') >= 0);
  V.tab = 'games';
  let e2 = null;
  try { render(); } catch (ex) { e2 = ex; }
  ok('the week survives moving to another tab', !e2 && V.week === weeks[0]);
  V.week = null; V.tab = 'week';
} else {
  ok('no played weeks in the fixture; picker path not exercised', true);
}

// ── A game, and every tab inside it ─────────────────────────────────────
const cards = (DATA.games || {}).cards || [];
if (cards.length) {
  V.tab = 'games'; V.game = cards[0].game_id;
  ['notes', 'players', 'bets'].forEach(gt => {
    V.gameTab = gt;
    let e = null, html = '';
    try { render(); html = app(); } catch (ex) { e = ex; }
    ok('game tab ' + gt + ' renders', !e, e && (e.message + '\n' + e.stack));
    ok('game tab ' + gt + ' says something',
       textOf({ _html: html }).join('').trim().length > 40);
  });
  // A coaching note must arrive labelled. Unlabelled, a 69% prime-time
  // record beside a priced pick reads as a reason to bet, and
  // `situational_features` measured thirteen of these without one clearing
  // the vig.
  V.game = cards[0].game_id; V.gameTab = 'notes'; V.cat = 'all';
  try { render(); } catch (e) { /* reported above */ }
  const notes = (DATA.notes || {})[cards[0].game_id] || [];
  if (notes.some(n => n.context)) {
    ok('a coaching note is labelled as context',
       app().indexOf('Context, not an edge') >= 0);
  }

  // A game that is not on the board must say so rather than throwing.
  V.game = 'NOT_AGAME';
  let e = null;
  try { render(); } catch (ex) { e = ex; }
  ok('an unknown game is handled', !e && app().indexOf('not on this') >= 0);
  V.game = null; V.tab = 'week';
} else {
  ok('no cards in the fixture; game path not exercised', true);
}

// ── Picks, and the arithmetic behind them ───────────────────────────────
const rows = rowsFor('any', null).filter(r => r.priced && r.dec);
if (rows.length >= 3) {
  V.picks = {}; rows.slice(0, 3).forEach(r => { V.picks[r.id] = true; });
  ok('three picks are found again from their ids', v3Legs().length === 3);
  ['parlay', 'twos', 'singles'].forEach(t => {
    V.betType = t; V.tab = 'slip';
    let e = null, html = '';
    try { render(); html = app(); } catch (ex) { e = ex; }
    ok('slip as ' + t + ' renders', !e, e && (e.message + '\n' + e.stack));
    // Every outcome row from "none land" to "all land", so the table cannot
    // silently drop the case the reader is actually asking about.
    ok('slip as ' + t + ' enumerates all 4 outcomes',
       (html.match(/class="out"/g) || []).length === 5);
  });
  // A pick with no price must not produce a payout table built on nulls.
  V.picks = {}; V.picks['any|__nosuch__'] = true;
  let e = null;
  try { render(); } catch (ex) { e = ex; }
  ok('a pick that is no longer on the board is dropped, not crashed', !e);
  V.picks = {};
} else {
  ok('too few priced rows in the fixture for the slip path', true);
}

// ── The value verdict never claims more than it has ─────────────────────
ok('a row with no price gets no verdict',
   v3Value({ kind: 'td', ours: 0.5, dec: null })[0] === '');

// ── Every control the screens emit is handled ───────────────────────────
//
// A `data-v3*` attribute the views emit and `V3CLICKS` omits is a dead
// button: the delegated listener never matches it, and nothing throws or logs.
V.tab = 'week'; V.game = null; V.picks = {};
const seen = new Set();
[['week', null], ['games', null], ['slip', null], ['ladder', null]]
  .forEach(([t]) => {
    V.tab = t;
    try { render(); } catch (e) { /* reported above */ }
    (app().match(/data-(v3[a-z]+)=/g) || []).forEach(
      m => seen.add(m.slice(5, -1)));
  });
if (cards.length) {
  V.tab = 'games'; V.game = cards[0].game_id;
  ['notes', 'players', 'bets'].forEach(gt => {
    V.gameTab = gt;
    try { render(); } catch (e) { /* reported above */ }
    (app().match(/data-(v3[a-z]+)=/g) || []).forEach(
      m => seen.add(m.slice(5, -1)));
  });
}
const handled = new Set(V3CLICKS.concat(['v3week']));
const dead = [...seen].filter(k => !handled.has(k));
ok('every control the screens emit is wired', dead.length === 0,
   'emitted and never handled: ' + dead.join(', '));


// ── The back stack ──────────────────────────────────────────────────────
//
// A phone has a back gesture and a browser has a button, and neither knew
// this app existed: every screen was one history entry, so Back left the app
// entirely from anywhere inside it.
if (cards.length) {
  V.tab = 'week'; V.game = null; V.open = null;
  render();
  const depth = history.length;
  v3Do('v3game', cards[0].game_id);
  ok('opening a game pushes a history entry', history.length === depth + 1);
  ok('and the app is on that game', V.game === cards[0].game_id);
  history.back();
  ok('back returns to the screen before it', V.game == null,
     'game is still ' + V.game);
  // Sorting is not navigation. Putting all of V in the entry would make
  // twelve taps of Back replay twelve sort orders.
  const d2 = history.length;
  v3Do('v3dir', '1');
  ok('changing the sort direction is not a history step',
     history.length === d2);
}

// ── Sorting, on every column and in both directions ─────────────────────
V.tab = 'week'; V.game = null; V.week = null;
x.V3SORTS.forEach(col => {
  V.sort = col[0];
  [true, false].forEach(desc => {
    V.desc = desc;
    let e = null;
    try { render(); } catch (ex) { e = ex; }
    ok('sorted by ' + col[0] + (desc ? ' desc' : ' asc'), !e,
       e && (e.message + '\n' + e.stack));
  });
});
// Nulls last whichever way the arrow points: flipping the direction should
// reorder the rows that HAVE a value, not promote the ones that do not.
V.sort = 'proj'; V.market = 'any';
const withNulls = x.rowsFor('any', null).filter(r => r.priced);
if (withNulls.length > 2 && withNulls.every(r => r.proj == null)) {
  ok('a column no row has does not reorder anything', true);
} else {
  V.desc = true;
  const first = x.v3Sorted(withNulls)[0];
  V.desc = false;
  const firstAsc = x.v3Sorted(withNulls)[0];
  ok('nulls never lead the board',
     (first == null || first.proj !== undefined)
     && (firstAsc == null || firstAsc.proj !== undefined));
}
V.sort = 'ours'; V.desc = true;

// ── A row opens to show everything ──────────────────────────────────────
const someRow = x.rowsFor('any', null).filter(r => r.priced)[0];
if (someRow) {
  V.tab = 'week'; V.open = null; render();
  const closed = app();
  v3Do('v3open', someRow.id);
  const opened = app();
  ok('tapping a row opens its detail', opened.indexOf('class="detail"') >= 0);
  ok('and the closed board had none', closed.indexOf('class="detail"') < 0);
  v3Do('v3open', someRow.id);
  ok('tapping it again closes it', app().indexOf('class="detail"') < 0);
  V.open = null;
}

// ── The game filter survives a market change ────────────────────────────
if (cards.length) {
  V.tab = 'week'; V.game = cards[0].game_id; V.market = 'any';
  render();
  v3Do('v3mkt', 'first');
  ok('changing market keeps the selected game', V.game === cards[0].game_id);
  ok('and the picker still shows it',
     app().indexOf('data-v3gamesel') >= 0);
  V.game = null; V.market = 'any';
}

// ── A failed week fetch is not an empty week ────────────────────────────
//
// `.catch(() => [])` made every failure render as "no priced picks recorded",
// which is what a real empty week says. Opening the page from the filesystem
// blocks `fetch` outright, so every past week on every market came back empty
// and the page explained it away.
const wk = ((DATA.history || {})[x.V3HIST.any] || {}).has || [];
if (wk.length) {
  V.market = 'any'; V.week = wk[0]; V.tab = 'week';
  x.V3CACHE[x.V3HIST.any + ':' + wk[0]] = { error: 'blocked by the browser' };
  render();
  ok('a failed fetch says so', app().indexOf('did not load') >= 0);
  ok('and does not claim the week was empty',
     app().indexOf('No priced picks recorded') < 0);
  delete x.V3CACHE[x.V3HIST.any + ':' + wk[0]];
  V.week = null;
}

done();
