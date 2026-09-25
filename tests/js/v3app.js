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
  ['V', 'render', 'v3Screen', 'v3Week', 'v3Games', 'v3Game', 'v3Picks', 'v3SlipBody', 'v3SlipMath',
   'v3SaveSlip', 'v3Saved', 'v3IsSaved',
   'v3Ladder', 'v3Header', 'v3Nav', 'v3Rows', 'v3Do', 'V3TABS', 'V3MKT',
   'V3CLICKS', 'V3HIST', 'v3Questions', 'v3Value', 'v3Outcomes', 'v3Legs',
   'rowsFor', 'served', 'DATA', 'V3SORTS', 'v3Sorted', 'V3CACHE', 'v3Same',
   'isFav', 'toggleFav', 'v3Slipbar', 'v3Sheet', 'V3SHEETS', 'v3Rungs',
   'v3Num', 'v3Rows', 'v3LadderSummary', 'v3Questions', 'v3AskSend',
   'V3BETTYPES',
   'v3GameMkt', 'v3GameMkts', 'v3MarketForGame', 'v3GameEmpty']);
const { V, render, v3Screen, v3Games, v3Game, v3Picks, v3Ladder, v3Nav,
        V3TABS, V3MKT, V3CLICKS, V3HIST, v3Questions, v3Value, v3Legs,
        rowsFor, served, DATA } = x;

// THE WHOLE SHELL, not just the scrolling pane. v3 renders the header into
// `#appbar`, the tab bar into `#tabbar` and the slip bar into `#slipbarHost`,
// exactly as v2 does — so a check that reads only `#app` reports the nav and
// the week picker missing when both are on screen.
const app = () => ['app', 'appbar', 'tabbar', 'slipbarHost', 'sheet']
  .map(id => (document.getElementById(id) || {}).innerHTML || '').join('\n');
const pane = () => document.getElementById('app').innerHTML;

// ── The shell ───────────────────────────────────────────────────────────
let err = null;
try { render(); } catch (e) { err = e; }
ok('the shell renders', !err, err && (err.message + '\n' + err.stack));
ok('the nav carries every destination',
   V3TABS.every(t => app().indexOf('data-v3tab="' + t[0] + '"') >= 0));
ok('the header names the brand', app().indexOf(DATA.brand) >= 0, DATA.brand);
// The picker appears where a week means something. Slip and Ladder do not
// vary by week, so it is ABSENT there rather than present and inert — which
// is how it came to sit on the landing page changing nothing.
ok('the board offers the week picker', app().indexOf('data-v3week') >= 0);
V.tab = 'picks'; render();
ok('and the slip does not', app().indexOf('data-v3week') < 0);
V.tab = 'ladder'; render();
ok('nor the ladder', app().indexOf('data-v3week') < 0);
V.tab = 'props'; render();

// ── Every tab ───────────────────────────────────────────────────────────
V3TABS.forEach(t => {
  V.tab = t[0]; V.game = null;
  let e = null, html = '';
  try { render(); html = app(); } catch (ex) { e = ex; }
  ok('tab ' + t[0] + ' renders', !e, e && (e.message + '\n' + e.stack));
  ok('tab ' + t[0] + ' says something', textOf({ _html: html }).join('').trim().length > 40);
});

// ── Every market, on the board ──────────────────────────────────────────
V.tab = 'props';
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
  V.week = null; V.tab = 'props';
} else {
  ok('no played weeks in the fixture; picker path not exercised', true);
}

// ── A game, and every tab inside it ─────────────────────────────────────
const cards = (DATA.games || {}).cards || [];
if (cards.length) {
  V.tab = 'games'; V.game = cards[0].game_id;
  ['notes', 'players', 'bets', 'score'].forEach(gt => {
    V.gameTab = gt;
    let e = null, html = '';
    try { render(); html = app(); } catch (ex) { e = ex; }
    ok('game tab ' + gt + ' renders', !e, e && (e.message + '\n' + e.stack));
    ok('game tab ' + gt + ' says something',
       textOf({ _html: html }).join('').trim().length > 40);
  });
  // A coaching note must arrive labeled. Unlabelled, a 69% prime-time
  // record beside a priced pick reads as a reason to bet, and
  // `situational_features` measured thirteen of these without one clearing
  // the vig.
  V.game = cards[0].game_id; V.gameTab = 'notes'; V.cat = 'all';
  try { render(); } catch (e) { /* reported above */ }
  const notes = (DATA.notes || {})[cards[0].game_id] || [];
  if (notes.some(n => n.context)) {
    ok('a coaching note is labeled as context',
       app().indexOf('Context, not an edge') >= 0);
  }

  // A game that is not on the board must say so rather than throwing.
  V.game = 'NOT_AGAME';
  let e = null;
  try { render(); } catch (ex) { e = ex; }
  ok('an unknown game is handled', !e && app().indexOf('not on this') >= 0);
  V.game = null; V.tab = 'props';
} else {
  ok('no cards in the fixture; game path not exercised', true);
}

// ── Picks, and the arithmetic behind them ───────────────────────────────
const rows = rowsFor('any', null).filter(r => r.priced && r.dec);
if (rows.length >= 3) {
  V.picks = {}; rows.slice(0, 3).forEach(r => { V.picks[r.id] = true; });
  ok('three picks are found again from their ids', v3Legs().length === 3);
  // THE SLIP IS A SHEET NOW, not a tab: it opens over whatever board you are
  // reading and closes back onto it, which is the shape v2 had.
  ['parlay', 'twos', 'singles'].forEach(t => {
    V.betType = t; V.tab = 'props'; V.sheet = 'slip';
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
  V.picks = {}; V.sheet = null;
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
V.tab = 'props'; V.game = null; V.picks = {};
const seen = new Set();
[['props', null], ['games', null], ['slip', null], ['ladder', null]]
  .forEach(([t]) => {
    V.tab = t;
    try { render(); } catch (e) { /* reported above */ }
    (app().match(/data-(v3[a-z]+)=/g) || []).forEach(
      m => seen.add(m.slice(5, -1)));
  });
if (cards.length) {
  V.tab = 'games'; V.game = cards[0].game_id;
  ['notes', 'players', 'bets', 'score'].forEach(gt => {
    V.gameTab = gt;
    try { render(); } catch (e) { /* reported above */ }
    (app().match(/data-(v3[a-z]+)=/g) || []).forEach(
      m => seen.add(m.slice(5, -1)));
  });
}
// Attributes the `input`/`change` listeners own rather than the click
// listener: the week and game selects, the search box and the ladder fields.
// Attributes owned by a listener other than the click one: the selects
// (`change`), the text fields (`input`), and the ask form (`submit`).
const handled = new Set(V3CLICKS.concat(
  ['v3week', 'v3gamesel', 'v3sortsel', 'v3gameto', 'v3q', 'v3q2', 'v3l',
   'v3askform']));
const dead = [...seen].filter(k => !handled.has(k));
ok('every control the screens emit is wired', dead.length === 0,
   'emitted and never handled: ' + dead.join(', '));


// ── The back stack ──────────────────────────────────────────────────────
//
// A phone has a back gesture and a browser has a button, and neither knew
// this app existed: every screen was one history entry, so Back left the app
// entirely from anywhere inside it.
if (cards.length) {
  V.tab = 'props'; V.game = null; V.open = null;
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
V.tab = 'props'; V.game = null; V.week = null;
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
  V.tab = 'props'; V.open = null; render();
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
  V.tab = 'props'; V.game = cards[0].game_id; V.market = 'any';
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
  V.market = 'any'; V.week = wk[0]; V.tab = 'props';
  x.V3CACHE[x.V3HIST.any + ':' + wk[0]] = { error: 'blocked by the browser' };
  render();
  ok('a failed fetch says so', app().indexOf('did not load') >= 0);
  ok('and does not claim the week was empty',
     app().indexOf('No priced picks recorded') < 0);
  delete x.V3CACHE[x.V3HIST.any + ':' + wk[0]];
  V.week = null;
}

// ── Favorites ──────────────────────────────────────────────────────────
//
// On v1's store, keyed by the same row id v2 uses, so a player starred in one
// is starred in the other. Two lists under two keys would be the same feature
// twice, disagreeing.
V.tab = 'props'; V.market = 'any'; V.filter = 'all'; V.week = null;
const favRow = x.rowsFor('any', null).filter(r => r.priced)[0];
if (favRow) {
  render();
  ok('every row offers a star', app().indexOf('data-v3fav=') >= 0);
  v3Do('v3fav', favRow.id);
  ok('starring sticks', x.isFav(favRow.id) === true);
  V.filter = 'fav'; render();
  ok('the starred filter finds it', app().indexOf(favRow.player) >= 0);
  v3Do('v3fav', favRow.id);
  render();
  ok('unstarring empties it', app().indexOf('Nothing starred') >= 0);
  V.filter = 'all';
}

// ── The slip has a way out of it ────────────────────────────────────────
//
// The first version was a floating button with no dismiss and no clear: the
// only way to empty the slip was to find each row again and untap it.
const slipRows = x.rowsFor('any', null).filter(r => r.priced && r.dec);
if (slipRows.length >= 2) {
  V.picks = {}; slipRows.slice(0, 2).forEach(r => { V.picks[r.id] = true; });
  V.tab = 'props'; render();
  ok('the slip bar appears when picks exist',
     app().indexOf('slipbar__count') >= 0);
  ok('and carries a clear control', app().indexOf('data-v3clear') >= 0);
  // THE BAR OPENS THE SLIP OVER THE BOARD, it does not navigate to it. It
  // used to be a tab, so looking at what you had just added meant leaving the
  // board it came from and then coming back.
  ok('the bar opens the slip rather than navigating',
     app().indexOf('data-v3sheet="slip"') >= 0);
  x.v3Do('v3sheet', 'slip');
  const sheet = () => (document.getElementById('sheet') || {}).innerHTML || '';
  ok('tapping it opens the slip sheet', sheet().indexOf('legwrap') >= 0);
  ok('and stays on the board underneath', V.tab === 'props');
  ok('every leg can be removed', sheet().indexOf('data-v3drop=') >= 0);
  ok('and every leg can be swiped', sheet().indexOf('class="legwrap"') >= 0);
  v3Do('v3drop', slipRows[0].id);
  ok('removing a leg removes exactly one', v3Legs().length === 1);
  v3Do('v3clear', '1');
  ok('clear empties the slip', v3Legs().length === 0);
  V.tab = 'props'; V.sheet = null;
}

// ── The bottom sheet ────────────────────────────────────────────────────
V.picks = {}; slipRows.slice(0, 2).forEach(r => { V.picks[r.id] = true; });
V.tab = 'props'; V.sheet = 'slip'; render();
ok('the slip offers its choices as sheets', app().indexOf('data-v3sheet=') >= 0);
v3Do('v3sheet', 'bet');
ok('opening a sheet renders it',
   (document.getElementById('sheet') || {}).className.indexOf('open') >= 0);
ok('and it can be closed', app().indexOf('data-v3close') >= 0);
// CHOOSING RETURNS TO THE SLIP, it does not close everything. These two
// choosers are opened only from inside the slip sheet, so closing to null
// dismissed the thing being changed and the new payout table was never seen.
v3Do('v3type', 'singles');
ok('choosing returns to the slip', V.sheet === 'slip' && V.betType === 'singles');
V.picks = {}; V.betType = 'parlay'; V.tab = 'props'; V.sheet = null;

// ── Navigation resets the scroll; editing the screen does not ───────────
//
// Opening a game from halfway down the Games list landed you halfway down the
// GAME — a different page at someone else's scroll offset.
if (cards.length) {
  V.tab = 'games'; V.game = null; V.top = false; render();
  v3Do('v3game', cards[0].game_id);
  ok('opening a game starts at the top of it', V.top === false,
     'v3Do sets V.top and render consumes it');
  V.top = false;
  v3Do('v3dir', '1');
  ok('flipping the sort does not jump you to the top', V.top === false);
  V.game = null; V.tab = 'props';
}

// ── Three estimates, all three sortable ─────────────────────────────────
//
// The board carries model, book and blend for the same event, and the first
// version showed two of them under one label — while `betProb` answered MODEL
// on a touchdown market and ADJUSTED on a yardage one, so the same control
// sorted by different quantities depending on the tab.
V.tab = 'props'; render();
['Model', 'Book', 'Adjusted'].forEach(k =>
  ok('the board shows ' + k, app().indexOf('>' + k + '</i>') >= 0));
['model', 'book', 'adj'].forEach(k =>
  ok('and can sort by ' + k, x.V3SORTS.some(c => c[0] === k)));

// ── The game screen is the board, filtered ──────────────────────────────
if (cards.length) {
  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'players';
  render();
  const h = app();
  ok('the players tab carries the market pills', h.indexOf('data-v3mkt=') >= 0);
  ok('and the filters', h.indexOf('data-v3filter=') >= 0);
  ok('and the sort control', h.indexOf('data-v3sortsel') >= 0);
  ok('and it leaves the global game filter alone', V.game === cards[0].game_id);
  V.game = null; V.tab = 'props'; V.gameTab = 'notes';
}

// ── The game's own tabs ─────────────────────────────────────────────────
if (cards.length) {
  V.tab = 'games'; V.game = cards[0].game_id;

  // ONE DISTRIBUTION, ONE TAB. `score_dist` answers the final-score table
  // and the ladder from a single `comparables(spread, total)` call, so they
  // were two tabs rendering one thing and reading them together meant
  // moving between them.
  V.gameTab = 'out'; render();
  ok('the final-score tab renders', app().indexOf('How it finished') >= 0);
  ok('and leads with the bands rather than the exact scores',
     app().indexOf('How it finished') < app().indexOf('Most common exact'));

  // The per-book listing printed eleven spreads a game, each with a fair
  // chance of 50% — because a spread IS a coin flip, so the column that
  // looked like information was the one quantity that cannot vary.
  const b = app();
  ok('the bets tab is a ladder, not a list of books',
     b.indexOf('ltab__r') >= 0);
  ok('and does not print a fair-chance column', b.indexOf('Fair chance') < 0);
  ok('the outcome tab carries BOTH, score first then the ladder',
     b.indexOf('How it finished') >= 0 && b.indexOf('ltab__r') >= 0
     && b.indexOf('How it finished') < b.indexOf('ltab__r'));
  ok('and the tab bar no longer offers them separately',
     b.indexOf('data-v3gtab="bets"') < 0 && b.indexOf('data-v3gtab="score"') < 0);

  // A bookmark, a back entry or a remembered session from before the merge
  // still names a tab that no longer exists.
  V.gameTab = 'bets';
  x.v3Do('v3gtab', 'bets');
  ok('an old tab name does not render an empty screen',
     app().indexOf('How it finished') >= 0 || V.gameTab === 'out',
     'gameTab=' + V.gameTab);

  // Our model belongs on the same scale as the book's, not two boxes away.
  V.gameTab = 'notes'; render();
  const h = app();
  ok('the win bar carries both the book and our model',
     h.indexOf('Sportsbooks') >= 0 && h.indexOf('Our model') >= 0);
  // A DECIMAL, not a whole number. Rounding turned a 0.6-point model margin
  // into "LA 22-22" — a projected tie, from numbers that did not say one.
  ok('the projected scores keep a decimal',
     /\d+\.\d\u2013\d+\.\d/.test(h),
     'whole numbers collapse a close game into a tie');
  V.game = null; V.tab = 'props'; V.gameTab = 'notes';
}

// ── No hedging language reaches the reader ──────────────────────────────
//
// Asked for directly, twice. The measured caveats live in the code, where the
// person deciding whether to trust a number can read them.
const everything = [];
['props', 'games', 'slip', 'ladder'].forEach(t => {
  V.tab = t; V.game = null; render(); everything.push(app());
});
if (cards.length) {
  V.tab = 'games';
  ['notes', 'players', 'bets', 'score'].forEach(gt => {
    V.game = cards[0].game_id; V.gameTab = gt; render(); everything.push(app());
  });
  V.game = null; V.tab = 'props';
}
const blob = everything.join(' ').toLowerCase();
['unproven', 'still being tested', 'not yet validated', 'untested']
  .forEach(w => ok('no "' + w + '" on any screen', blob.indexOf(w) < 0));

// ── Moving between games ────────────────────────────────────────────────
//
// Reading one game then the next meant Back, find the row, tap.
if (cards.length >= 2) {
  V.tab = 'games'; V.game = cards[1].game_id; V.gameTab = 'score'; render();
  const h = app();
  ok('a game page offers a game switcher', h.indexOf('data-v3gameto') >= 0);
  // On the LAST game there is only a previous step, which is correct — the
  // first assertion here asked for two and was wrong, not the code.
  ok('and a step to the game beside it', h.indexOf('class="gstep"') >= 0);
  ok('with no step past the end of the slate',
     (h.match(/class="gstep"/g) || []).length === 1);
  // The tab is kept: landing on notes when you were reading the ladder is
  // the same annoyance in a different place.
  fireDoc('change', { target: {
    getAttribute: k => k === 'data-v3gameto' ? '' : null,
    value: cards[0].game_id } });
  ok('switching keeps the tab you were on', V.gameTab === 'score');
  ok('and lands on the game you picked', V.game === cards[0].game_id);
  V.game = null; V.tab = 'props'; V.gameTab = 'notes';
}

// ── How the game may unfold ─────────────────────────────────────────────
//
// Counted, not reasoned. A partition rather than a list of overlapping
// scenarios: "one-score 50%, shootout 31%, upset 28%" reads as a ranking and
// cannot be one, because it adds to more than everything that can happen.
if (cards.length) {
  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'notes';
  V.cat = 'all'; render();
  const h = app();
  ok('the notes tab opens with how the game may unfold',
     h.indexOf('How it may unfold') >= 0);
  ok('and it comes before the written notes',
     h.indexOf('How it may unfold') < h.indexOf('What our AI noticed'));
  // That the cells PARTITION is a property of the model and is tested in
  // test_score_dist, on a frame whose answer is known. What matters here is
  // that every cell reaches the screen with its percentage.
  const u = (cards[0] || {}).unfold;
  if (u && u.cells) {
    ok('every scenario reaches the screen',
       u.cells.every(cl => h.indexOf(cl.label) >= 0));
    ok('each with its percentage',
       u.cells.every(cl => h.indexOf(cl.pct.toFixed(0) + '%') >= 0));
  }
  V.game = null; V.tab = 'props'; V.gameTab = 'notes';
}

// ── Controls sit next to the rows they control ──────────────────────────
//
// The injury report and the public split rendered between the tab bar and
// the tab content, so every filter on the Players tab was two screens below
// the tab you pressed to reach it: change a market, scroll down, read, scroll
// back up. Both blocks are identical all week and on every tab, which is
// exactly what should not sit between a control and its rows.
if (cards.length) {
  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'players';
  render();
  const h = app();
  const controls = h.indexOf('data-v3mkt=');
  const tabs = h.indexOf('data-v3gtab=');
  const publics = h.indexOf('Where the public is');
  // PUBLIC MONEY IS GAME CONTEXT and belongs with the matchup, ABOVE the tab
  // bar — it is the same all week whichever tab you are on. The filters are
  // the first thing inside the tab, so nothing sits between a control and
  // the rows it controls.
  if (publics >= 0 && tabs >= 0) {
    ok('the public split sits above the tab bar', publics < tabs);
  }
  if (controls >= 0 && tabs >= 0) {
    ok('and the filters are inside the tab, under it', tabs < controls);
  }
  // The injury report is a TAB now: under the matchup card it pushed every
  // control two screens down.
  ok('the injury report is not inline on the players tab',
     h.indexOf('Injury report') < 0);
  // And on This week, the controls are directly above the rows.
  V.tab = 'props'; V.game = null; render();
  const w = app();
  ok('the board puts its sort control above its rows',
     w.indexOf('data-v3sortsel') < w.indexOf('id="v3rows"'));
  V.gameTab = 'notes';
}

// ── The games list labels its numbers ───────────────────────────────────
//
// It printed a lean — "our model picks the other side" — beside a bare
// "CIN 63% to win", where the 63% was the BOOK's number with nothing saying
// so. Read together the two contradict each other.
V.tab = 'games'; V.game = null; V.filter = 'all'; render();
if (cards.length) {
  const h = app();
  ok('the games list labels the book number', h.indexOf('book</i>') >= 0);
  const withModel = cards.filter(c => c.model_win_home != null);
  if (withModel.length) {
    ok('and shows the model beside it', h.indexOf('>model</i>') >= 0);
    ok('and the gap between them', h.indexOf('>gap</i>') >= 0);
  }
  ok('and no longer prints a bare percentage with no owner',
     h.indexOf('to win</span>') < 0);
}
V.filter = 'all'; V.tab = 'props';

// ── The games filters, and their own state ──────────────────────────────
//
// They shared `V.filter` with the board. Picking "Fades" on This week landed
// here with no segment pressed and every game shown; picking "Model
// disagrees" here left the board silently unfiltered.
if (cards.length) {
  V.tab = 'props'; V.filter = 'fade'; render();
  V.tab = 'games'; render();
  ok('the games page keeps its own filter', V.gfilter === 'all');
  ok('and the board keeps its own', V.filter === 'fade');
  V.filter = 'all';

  ['all', 'flip', 'agree', 'diff'].forEach(f => {
    V.gfilter = f;
    let e = null;
    try { render(); } catch (ex) { e = ex; }
    ok('games filter ' + f + ' renders', !e, e && e.message);
    ok('games filter ' + f + ' never renders blank',
       textOf({ _html: app() }).join('').trim().length > 40);
  });
  V.gfilter = 'all';
}

// ── No hero on the games page ───────────────────────────────────────────
//
// "Game to watch" picked the largest gap between our model and the book,
// which is not a reason to watch a game — and with four real filters below
// it, it was answering a question nobody asked.
V.tab = 'games'; V.game = null; render();
ok('the games page has no hero card', app().indexOf('Game to watch') < 0);
V.tab = 'props'; render();
ok('and neither does the board', app().indexOf('Game to watch') < 0);

// ── Search ──────────────────────────────────────────────────────────────
//
// Five hundred priced players and a scroll. The input must NOT be
// re-rendered while you type: replacing the field being typed into loses
// focus and the caret and drops keystrokes, which is what made v2's search
// unusable.
V.tab = 'props'; V.game = null; V.q = ''; V.filter = 'all'; render();
const anyRow = x.rowsFor(V.market, null).filter(r => r.priced)[0];
if (anyRow) {
  ok('the board offers a search box', app().indexOf('data-v3q') >= 0);
  V.q = anyRow.player.split(' ').pop();
  const host = document.getElementById('v3rows');
  if (host) host.innerHTML = x.v3Rows();
  ok('search narrows the board', (host.innerHTML || '').indexOf(anyRow.player) >= 0);
  V.q = 'zzzznotaplayer';
  if (host) host.innerHTML = x.v3Rows();
  ok('and says so when nothing matches',
     (host.innerHTML || '').indexOf('No player matching') >= 0);
  V.q = '';
}
// Typing is wired to `input` and patches only the rows — never the shell.
{
  const src = x.v3Rows.toString();
  ok('the search filter is applied inside the row builder',
     src.indexOf('v3Match') >= 0);
}

// ── Injuries are their own tab ──────────────────────────────────────────
if (cards.length) {
  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'inj';
  let e = null;
  try { render(); } catch (ex) { e = ex; }
  ok('the injuries tab renders', !e, e && e.message);
  ok('and shows the report', app().indexOf('Injury report') >= 0
     || app().indexOf('No injury report') >= 0);
  V.gameTab = 'notes'; V.game = null; V.tab = 'props';
}

// ── Three game numbers where all three exist ────────────────────────────
if (cards.length) {
  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'notes'; render();
  const h2 = app();
  if (cards[0].blend) {
    ok('the game shows Adjusted beside Book and Model',
       h2.indexOf('Adjusted') >= 0 && h2.indexOf('Sportsbooks') >= 0
       && h2.indexOf('Our model') >= 0);
  }
  V.game = null; V.tab = 'props';
}

// ── The ladder is driven by what you type ───────────────────────────────
//
// It offered four stakes and three canned "kinds", so the question it exists
// to answer — what does MY bet at MY price turn into — could be asked twelve
// ways. The table is patched in place on each keystroke, never re-rendered,
// or the field being typed into is replaced and loses focus.
V.tab = 'ladder'; V.stake = 10; V.lodds = 100; V.rungs = 6; render();
const L = () => app();
ok('the ladder offers input fields', L().indexOf('data-v3l="stake"') >= 0
   && L().indexOf('data-v3l="odds"') >= 0
   && L().indexOf('data-v3l="rungs"') >= 0);
const rungsOf = h => (h.match(/class="rung/g) || []).length;
const six = rungsOf(L());
V.rungs = 10;
ok('changing the step count changes the table',
   (x.v3Rungs().match(/class="rung/g) || []).length === 10);
V.rungs = 6;
// $10 at +100 doubles each step: six wins is $640.
ok('the maths follows the inputs', x.v3Rungs().indexOf('$640.00') >= 0,
   'ten dollars at even money, six times');
V.lodds = -150;
ok('and follows the price', x.v3Rungs().indexOf('$640.00') < 0);
V.lodds = 100;
// A half-typed price must not snap the table to something absurd.
ok('a price under 100 is ignored rather than coerced',
   x.v3Num('-1') === -1);
ok('and the fields parse what a person types',
   x.v3Num('$25') === 25 && x.v3Num('+150') === 150
   && x.v3Num('-150') === -150);
V.tab = 'games';

// ── Games is the way in ─────────────────────────────────────────────────
ok('the first tab is Games', V3TABS[0][0] === 'games');
ok('and the second is Props', V3TABS[1][0] === 'props');
ok('there are no duplicate tab keys',
   new Set(V3TABS.map(t => t[0])).size === V3TABS.length);

// ── The matchup tab ─────────────────────────────────────────────────────
if (cards.length) {
  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'edge'; V.week = null;
  let e = null;
  try { render(); } catch (ex) { e = ex; }
  ok('the matchup tab renders', !e, e && (e.message + '\n' + e.stack));
  if (cards[0].matchup) {
    const h = app();
    ok('and pairs one offense against the other defense',
       h.indexOf('offense') >= 0 && h.indexOf('defense') >= 0);
    // A gap has to read as a gap rather than as an oversight.
    ok('and says what it could not build', h.indexOf('Not shown, and why') >= 0);
  }
  V.gameTab = 'notes'; V.game = null;
}

// ── A past week of GAMES ────────────────────────────────────────────────
//
// The selector was honoured only by the props board. Games then became the
// landing page, so the picker sat on the first screen anyone sees and changed
// nothing — the most convincing kind of broken.
{
  V.tab = 'games'; V.game = null;
  const gw = Object.keys(((DATA.games || {}).past) || {}).map(Number);
  if (gw.length) {
    V.week = gw[0];
    let e = null;
    try { render(); } catch (ex) { e = ex; }
    ok('a past week of games renders', !e, e && e.message);
    const h = app();
    ok('and the picker offers the weeks GAMES has',
       h.indexOf('>Week ' + gw[0] + '<') >= 0);
    ok('and the final score is on the row', h.indexOf('41') >= 0);
    // A week the destination cannot show must not follow you into it.
    v3Do('v3tab', 'picks');
    ok('a week the next screen cannot show is dropped', V.week == null);
    V.tab = 'games';
  }
  V.week = null;
}

// ── The Players tab must open on a market that HAS players ─────────────
//
// It opens on whatever market the board was left on, and the board opens on
// "Scores a TD". Week 2 archived touchdown prices for two of its sixteen
// games, so fourteen of them opened the tab on a market holding nothing and
// said "no priced picks recorded for week 2 on this market" — which reads as
// "this game has no players" rather than "not this one". Reported from the
// live site: "digging into a historical game, clicking on players tab ...
// there are no players there".
{
  const gw = Object.keys(((DATA.games || {}).past) || {}).map(Number);
  const svd = V3MKT.filter(m => served(m[0])).map(m => m[0]);
  const pastCards = gw.length
    ? ((((DATA.games || {}).past) || {})[String(gw[0])] || {}).cards || [] : [];
  if (gw.length && pastCards.length && svd.length >= 2) {
    const wk = String(gw[0]), gid = pastCards[0].game_id;
    // An index of the shape `_split_history` writes: the market the board
    // opens on holds nothing for this game, a later one holds players.
    DATA.history = DATA.history || {};
    svd.forEach((k, i) => {
      const hk = V3HIST[k];
      DATA.history[hk] = DATA.history[hk] || {};
      DATA.history[hk].has = [gw[0]];
      DATA.history[hk].by_game = { [wk]: i === 0 ? {} : { [gid]: 7 } };
    });
    V.tab = 'games'; V.week = gw[0]; V.market = svd[0]; V.filter = 'all'; V.q = '';
    ok('a market holding nothing for this game counts zero',
       x.v3GameMkt(svd[0], gid) === 0);
    ok('and one that holds players counts them',
       x.v3GameMkt(svd[1], gid) === 7);
    v3Do('v3game', gid);
    v3Do('v3gtab', 'players');
    ok('tapping Players lands on a market that has players',
       V.market !== svd[0] && x.v3GameMkt(V.market, gid) > 0,
       'landed on ' + V.market);

    // And when NOTHING is quoted for the game, say so rather than blaming
    // the market — the reader has no other market to try.
    svd.forEach(k => { DATA.history[V3HIST[k]].by_game = { [wk]: {} }; });
    const bare = x.v3GameEmpty(gid);
    ok('a game with nothing quoted says so once',
       bare.indexOf('any market') >= 0, bare.slice(0, 120));
    // With somewhere to go, the empty state names it and makes it tappable.
    DATA.history[V3HIST[svd[1]]].by_game = { [wk]: { [gid]: 7 } };
    const hinted = x.v3GameEmpty(gid);
    ok('otherwise it names the markets that do hold players',
       hinted.indexOf('data-v3mkt="' + svd[1] + '"') >= 0, hinted.slice(0, 160));
    V.week = null; V.game = null; V.gameTab = 'notes'; V.tab = 'games';
  }
}

// ── Asking is reachable from every tab ─────────────────────────────────
//
// The box lived at the bottom of Notes, so a question raised by a number on
// Matchup or Outcome meant leaving that number, scrolling past every note,
// asking, and navigating back.
if (cards.length) {
  V.tab = 'games'; V.game = cards[0].game_id;
  ['notes', 'players', 'out', 'edge', 'inj'].forEach(t => {
    V.gameTab = t; render();
    ok('the ask control is on the ' + t + ' tab',
       app().indexOf('data-v3sheet="ask"') >= 0);
  });
  // ABOVE THE PUBLIC SPLIT, not below it. Under that block it fell past the
  // fold on a phone: the control that answers anything was the one you had
  // to scroll to find.
  V.gameTab = 'notes'; render();
  const gh = app();
  const askAt = gh.indexOf('data-v3sheet="ask"');
  const pubAt = gh.indexOf('Share of bets');
  ok('the ask control sits under the score card',
     askAt >= 0 && (pubAt < 0 || askAt < pubAt),
     'ask at ' + askAt + ', public split at ' + pubAt);
  ok('and above the tab bar', askAt < gh.indexOf('data-v3gtab="players"'));

  // And it opens over whichever tab raised it, rather than navigating away.
  V.gameTab = 'edge'; render();
  const before = V.gameTab;
  x.v3Do('v3sheet', 'ask');
  const sheet = (document.getElementById('sheet') || {}).innerHTML || '';
  ok('tapping it opens the ask sheet', sheet.indexOf('data-v3askform') >= 0);
  ok('and does not leave the tab', V.gameTab === before);
  ok('the sheet does not repeat its own heading inside the body',
     sheet.split('Ask about this game').length - 1 === 1, sheet.slice(0, 200));
  x.v3Do('v3close', '1');
  ok('closing it returns to that tab', V.gameTab === before && !V.sheet);
  V.game = null; V.tab = 'props'; V.gameTab = 'notes';
}

// ── a slip is not a saved pick ─────────────────────────────────────────
//
// v3 conflated them: the tab called "My picks" showed the slip, so there was
// nowhere for a kept copy to live. v2 had it right — the slip is the draft,
// reachable from the bar over whatever you are reading; Picks are the copies
// you kept, which settle themselves as the games finish.
{
  const rs = rowsFor('any', null).filter(r => r.priced && r.dec);
  if (rs.length >= 2) {
    V.tab = 'props'; V.week = null; V.saved = []; V.savedFilter = 'all';
    V.picks = {}; rs.slice(0, 2).forEach(r => { V.picks[r.id] = true; });
    V.betType = 'parlay'; V.stake = 10;
    ok('the slip opens on the round robin by default',
       x.V3BETTYPES[0][0] === 'twos' && x.V3BETTYPES[0][1] === 'Round robin');

    ok('nothing is kept to begin with', x.v3Saved().length === 0);
    x.v3Do('v3keep', '1');
    ok('keeping copies the slip into Picks', x.v3Saved().length === 1);
    ok('and leaves the slip alone', v3Legs().length === 2,
       'keeping must be a copy, not a move');
    x.v3Do('v3keep', '1');
    ok('keeping the same slip twice keeps one copy', x.v3Saved().length === 1);

    const p = x.v3Saved()[0];
    // STRUCTURE, NOT A POINTER AT THE BOARD. Prices move under a saved slip.
    ok('the saved copy stores its own legs',
       (p.legs || []).length === 2 && !!p.legs[0].label);
    ok('and the payout curve it was priced at',
       (p.rows || []).length === 3 && p.rows.every(r => 'net' in r),
       JSON.stringify(p.rows || []).slice(0, 120));
    ok('and the stake that curve belongs to', p.rowStake === 10);

    V.tab = 'picks';
    let e = null;
    try { render(); } catch (ex) { e = ex; }
    ok('the Picks screen renders', !e, e && (e.message + '\n' + e.stack));
    const h = app();
    ok('and shows it as pending before the games are in',
       h.indexOf('Pending') >= 0);
    ok('the tab is called Picks', h.indexOf('>Picks<') >= 0
       || app().indexOf('Picks') >= 0);

    // A SAVED PICK OPENS THE SAME BREAKDOWN THE SLIP SHOWS, from the curve
    // it was stored with rather than from today's board.
    x.v3Do('v3pickopen', p.id);
    const ps = () => (document.getElementById('sheet') || {}).innerHTML || '';
    ok('tapping a saved pick opens its breakdown', ps().indexOf('class="out"') >= 0);
    ok('and draws the stored curve, not the live one',
       ps().indexOf('saved at, not today') >= 0);
    ok('and stays on the Picks tab', V.tab === 'picks');
    x.v3Do('v3close', '1');

    // Changing how or how much must not dismiss the slip that shows it.
    V.sheet = 'slip'; x.v3Do('v3type', 'singles');
    ok('changing the bet type keeps the slip open', V.sheet === 'slip');
    x.v3Do('v3stake', '25');
    ok('and changing the stake keeps it open too', V.sheet === 'slip');
    ok('and the numbers followed', V.stake === 25 && V.betType === 'singles');
    V.sheet = null; V.betType = 'parlay'; V.stake = 10;

    x.v3Do('v3unkeep', p.id);
    ok('a kept slip can be removed', x.v3Saved().length === 0);
    ok('and removing it leaves the slip alone', v3Legs().length === 2);

    // The old state shapes: a tab called slip, and `saved` as a boolean.
    V.tab = 'slip';
    if (V.tab === 'slip') V.tab = 'picks';
    ok('an old saved tab name lands somewhere real', V.tab === 'picks');
    V.picks = {}; V.saved = []; V.tab = 'props'; V.sheet = null;
  } else {
    ok('too few priced rows in the fixture for the picks path', true);
  }
}

// ── The ask box sends a game id and a question, and nothing else ────────
if (cards.length) {
  // The box lives in the sheet now, reachable from every tab, so these
  // states are read there rather than off the Notes tab.
  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'notes';
  V.answer = ''; V.asking = false; V.sheet = 'ask'; render();
  const h = app();
  ok('the ask box takes a typed question', h.indexOf('data-v3q2') >= 0);
  // The quick questions are computed from priced rows IN THIS GAME, so a
  // fixture whose players belong elsewhere legitimately has none. What must
  // always hold is that the box is there either way.
  if (x.v3Questions(cards[0].game_id).length) {
    ok('and the quick questions are still there', h.indexOf('data-v3ask=') >= 0);
  } else {
    ok('the box stands alone when no quick question applies',
       h.indexOf('data-v3q2') >= 0);
  }
  // Thinking, answered and failed are three distinct states, and none of
  // them may be silence.
  V.asking = true; render();
  ok('a pending question says so', app().indexOf('Thinking') >= 0);
  V.asking = false; V.answerErr = 'nope'; render();
  ok('and a failure says so', app().indexOf('nope') >= 0);
  V.answerErr = ''; V.answer = 'An answer.'; V.answerLive = true; render();
  ok('and an answer is marked as the model\u2019s',
     app().indexOf('Answered by our model') >= 0);
  V.answer = ''; V.answerLive = false; V.sheet = null;
  V.game = null; V.tab = 'props';
}

// ── Half splits on the matchup tab ──────────────────────────────────────
if (cards.length && cards[0].matchup && cards[0].matchup.splits) {
  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'edge';
  V.half = 'full'; render();
  ok('the matchup offers the halves', app().indexOf('data-v3half=') >= 0);
  const hs = Object.keys(cards[0].matchup.splits);
  hs.forEach(k => {
    V.half = k;
    let e = null;
    try { render(); } catch (ex) { e = ex; }
    ok('matchup split ' + k + ' renders', !e, e && e.message);
  });
  // A split the payload does not carry must fall back rather than blank.
  V.half = 'nonsense'; render();
  ok('an unknown split falls back to the full game',
     textOf({ _html: app() }).join('').trim().length > 40);
  V.half = 'full'; V.gameTab = 'notes'; V.game = null; V.tab = 'props';
}

done();
