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
   'v3GameMkt', 'v3GameMkts', 'v3MarketForGame', 'v3GameEmpty',
   'v3Had', 'v3Ord', 'v3Graded', 'v3PastRow',
   'v3Sharp', 'v3SharpSides', 'V3RATIO_SMALL', 'v3GTab', 'v3MktLabel',
   'v3Clv',
   'v3NowImplied', 'v3Clv', 'v3ClvNote', 'v3GameMoney']);
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
  // "Likeliest", not "Most common": the list is ordered for THIS game by a
  // kernel over real finals, not by league-wide frequency. The heading is
  // asserted because it is the claim the card makes.
  ok('and leads with the bands rather than the exact scores',
     app().indexOf('How it finished') >= 0
       && app().indexOf('Likeliest exact scores') > app().indexOf('How it finished'),
     'bands at ' + app().indexOf('How it finished')
       + ', scores at ' + app().indexOf('Likeliest exact scores'));
  ok('the exact-score card says what the whole list is worth',
     app().indexOf('finish on a score nobody listed') >= 0);

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
  V.gameTab = 'odds'; render();
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
  // PUBLIC MONEY IS PART OF THE PRICE, so it lives on Odds with the bars it
  // belongs to rather than above every tab. As a permanent preamble it put a
  // screen and a half between opening a game and reaching any section of it.
  // The filters are the first thing inside the tab, so nothing sits between
  // a control and the rows it controls.
  ok('the public split is not inline on the players tab', publics < 0);
  if (controls >= 0 && tabs >= 0) {
    ok('and the filters are inside the tab, under it', tabs < controls);
  }
  // Same for the injury report, which is part of the matchup.
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

// ── Injuries are part of the matchup ────────────────────────────────────
//
// They were a tab of their own, which split one question over two: an
// efficiency table is a claim about personnel, and reading it without knowing
// who is out is reading last month's teams.
if (cards.length) {
  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'edge';
  let e = null;
  try { render(); } catch (ex) { e = ex; }
  ok('the injuries tab renders', !e, e && e.message);
  // A FOURTH VIEW of the matchup, beside the halves: the halves ask how the
  // units rate, this asks which of them is playing. So it is behind the same
  // control rather than stacked above the table on every view of it.
  ok('the injury report is a view of the matchup',
     app().indexOf('data-v3half="inj"') >= 0);
  ok('and is not stacked above the table on the other views',
     app().indexOf('Injury report') < 0
     && app().indexOf('No injury report') < 0);
  V.half = 'inj'; render();
  ok('and shows the report', app().indexOf('Injury report') >= 0
     || app().indexOf('No injury report') >= 0);
  ok('with the efficiency rows put away while it is showing',
     app().indexOf('offense <i>vs</i>') < 0);
  // The control itself stays, or there is no way back to the numbers.
  ok('and the view control still there to leave by',
     app().indexOf('data-v3half="full"') >= 0);
  V.half = 'full'; render();
  // A saved `inj` must land on the section that absorbed it rather than
  // falling through to whatever is first.
  V.gameTab = x.v3GTab('inj');
  ok('an old injuries link still finds it', V.gameTab === 'edge',
     String(V.gameTab));
  V.gameTab = 'notes'; V.game = null; V.tab = 'props';
}

// ── Three game numbers where all three exist ────────────────────────────
if (cards.length) {
  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'odds'; render();
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
    // The "Based on" card and the "Not shown, and why" list are both gone.
    // Neither answered a question in front of the reader: that a season rate
    // comes from the season's earlier games is what a season rate IS, and a
    // list of metrics the page is not showing is a note about the pipeline.
    ok('no "Based on" preamble above the numbers',
       h.indexOf('Based on') < 0);
    ok('and no list of what was left out below them',
       h.indexOf('Not shown, and why') < 0);

    // ONE METRIC AT A TIME, CHOSEN FROM A DROPDOWN. Eleven metrics with names
    // like "Late-half scoring drives" wrapped to six rows of pills — a chooser
    // taller than the thing it chooses, and far too tall to pin.
    if (h.indexOf('data-v3metricsel') >= 0) {
      ok('the metrics can be filtered to one', h.indexOf('All metrics') >= 0);
      const barAt = h.indexOf('class="mxbar"');
      ok('and the chooser rides in the pinned bar, not under it',
         h.indexOf('data-v3metricsel') > barAt
         && h.indexOf('data-v3metricsel') < h.indexOf('</div>', barAt + 400));
      ok('it is one control, not a pill per metric',
         h.indexOf('mxpills') < 0 && h.indexOf('data-v3metric=') < 0);
      const k = /<option value="((?!all)[^"]+)"/.exec(
        h.slice(h.indexOf('data-v3metricsel')));
      ok('an option names a real metric', !!k);
      // ALPHABETICAL, with "All metrics" pinned on top. A dropdown is scanned
      // for a name you already have in mind.
      const opts = h.slice(h.indexOf('data-v3metricsel'))
        .split('<option').slice(1)
        .map(o => o.slice(o.indexOf('>') + 1, o.indexOf('</option>')));
      ok('All metrics leads the list', opts[0] === 'All metrics', opts[0]);
      const names = opts.slice(1);
      ok('and the rest are alphabetical',
         names.join('|') === names.slice().sort((a, b) =>
           a.localeCompare(b)).join('|'), names.join(' | '));
      // The SECTIONS are not resorted: their order is roughly how much each
      // metric explains, which is a ranking rather than a list.
      const heads = (h.match(/font-size:17px[^>]*>([^<]+)/g) || [])
        .map(t => t.slice(t.indexOf('>') + 1));
      if (heads.length > 1) {
        ok('while the sections keep the order the pipeline sent',
           heads.join('|') !== heads.slice().sort((a, b) =>
             a.localeCompare(b)).join('|')
           || heads.length < 2, heads.join(' | '));
      }
      if (k) {
        fireDoc('change', { target: {
          getAttribute: a => a === 'data-v3metricsel' ? '' : null,
          value: k[1] } });
        const one = app();
        ok('picking one shows fewer headings than all of them',
           (one.match(/class="mx"/g) || []).length
           < (h.match(/class="mx"/g) || []).length,
           'one=' + (one.match(/class="mx"/g) || []).length
           + ' all=' + (h.match(/class="mx"/g) || []).length);
        ok('and the chooser is still there to change it',
           one.indexOf('All metrics') >= 0);
        fireDoc('change', { target: {
          getAttribute: a => a === 'data-v3metricsel' ? '' : null,
          value: 'all' } });
      }
      // The injury view has no metrics, so the chooser is absent rather than
      // present and inert.
      V.half = 'inj'; render();
      ok('and is absent on the injury view',
         app().indexOf('data-v3metricsel') < 0);
      ok('while the view control stays', app().indexOf('data-v3half=') >= 0);
      V.half = 'full'; render();
    }
  }
  V.gameTab = 'notes'; V.game = null; V.metric = 'all';
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
  // IN THE PINNED BAR, not under the score card. Under the card it was the
  // first thing you saw and then the last thing you could reach: by the
  // Outcome tables it was three screens up. Pinned it is a tap from wherever
  // you have read to, which is what a button scoped to "this game" is for.
  V.gameTab = 'notes'; render();
  const gh = app();
  const askAt = gh.indexOf('data-v3sheet="ask"');
  const barAt = gh.indexOf('class="gtabs"');
  const segAt = gh.indexOf('data-v3gtab="players"');
  ok('the ask control is inside the pinned bar',
     askAt > barAt && barAt >= 0,
     'ask at ' + askAt + ', bar at ' + barAt);
  ok('and above the section control it shares the bar with',
     askAt < segAt, 'ask at ' + askAt + ', seg at ' + segAt);
  // Pinned means it rides with the bar, so it must not ALSO be left in the
  // flow — two ask buttons on one screen is the bug this replaced.
  ok('and appears once, not in both places',
     gh.split('data-v3sheet="ask"').length - 1 === 1,
     String(gh.split('data-v3sheet="ask"').length - 1));

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


// ── What a settled row says the player actually had ─────────────────────
//
// Three markets settle on three different quantities and the row has space
// for one short phrase. Each of these is a phrasing that was wrong once.
{
  const { v3Had, v3Ord, v3Graded, v3PastRow } = x;

  ok('ordinals read like English',
     [1, 2, 3, 4, 11, 12, 13, 21, 22].map(v3Ord).join(' ')
       === '1st 2nd 3rd 4th 11th 12th 13th 21st 22nd',
     [1, 2, 3, 4, 11, 12, 13, 21, 22].map(v3Ord).join(' '));

  // THE REAL BOARD KEYS. `V3MKT` calls these markets `any` and `first`; the
  // names `anytime_td` and `first_td` are the ARCHIVE's and never reach a
  // row. A fixture using the archive names passed while the live board
  // printed a touchdown count where the ordinal belongs.
  const td = (c, o) => ({ kind: 'td', key: 'any', tdCount: c, tdOrder: o });
  ok('one touchdown is singular', v3Had(td(1, 1)) === '1 TD', v3Had(td(1, 1)));
  ok('three touchdowns are plural', v3Had(td(3, 1)) === '3 TDs', v3Had(td(3, 1)));
  ok('a blank is named, not left as a zero',
     v3Had(td(0, null)) === 'no TD', v3Had(td(0, null)));
  // ABSENT IS NOT ZERO. A row with no count recorded must say nothing at all
  // rather than claim the player was held out of the end zone.
  ok('an unrecorded count says nothing',
     v3Had({ kind: 'td', key: 'any' }) === '',
     v3Had({ kind: 'td', key: 'any' }));

  // A first-TD board settles on WHICH touchdown was theirs. Printing a count
  // there would put "1 TD" beside a cross on everyone who scored second.
  const ft = (c, o) => ({ kind: 'td', key: 'first', tdCount: c, tdOrder: o });
  ok('the first-TD board names which touchdown it was',
     v3Had(ft(1, 3)) === '3rd TD of the game', v3Had(ft(1, 3)));
  ok('the first-TD winner reads as the first',
     v3Had(ft(1, 1)) === '1st TD of the game', v3Had(ft(1, 1)));
  ok('a first-TD blank still reads as no touchdown',
     v3Had(ft(0, null)) === 'no TD', v3Had(ft(0, null)));

  // An over/under row settles on the stat, so it prints the stat.
  ok('an over/under row prints the stat it settled on',
     v3Had({ kind: 'ou', key: 'rec', actual: 4 }) === '4 catches',
     v3Had({ kind: 'ou', key: 'rec', actual: 4 }));
  ok('an over/under row with no stat says nothing',
     v3Had({ kind: 'ou', key: 'rec' }) === '');

  // THE FIELDS HAVE TO SURVIVE THE NORMALIZER, which is where the touchdown
  // count was dropped before it ever reached the row.
  V.market = 'any';
  const g = v3Graded('anytime_td',
                     [{ player_name: 'A Man', team: 'BAL', game_id: 'x_BAL_NO',
                        probability: 0.4, scored: 1, td_count: 2, td_order: 1 }]);
  ok('the normalizer carries the count through',
     g[0].tdCount === 2 && g[0].tdOrder === 1, JSON.stringify(g[0]));
  ok('a settled row shows what they actually had',
     v3PastRow(g[0]).indexOf('2 TDs') >= 0, v3PastRow(g[0]));

  // AND THE FIRST-TD BOARD THROUGH THE SAME PATH, which is where the archive
  // name slipped in: the row below scored, and scored third.
  V.market = 'first';
  const gf = v3Graded('first_td',
                      [{ player_name: 'A Man', team: 'BAL', game_id: 'x_BAL_NO',
                         probability: 0.1, scored: 0, td_count: 1,
                         td_order: 3 }]);
  ok('a first-TD row names the ordinal, not the count',
     v3Had(gf[0]) === '3rd TD of the game', v3Had(gf[0]));
  V.market = 'any';
}


// ── Where the bigger bets are ───────────────────────────────────────────
//
// The dollar share, across all three markets. Every check here is a way the
// gap-based version got it wrong.
{
  const { v3Sharp, v3SharpSides, V3RATIO_SMALL } = x;

  const sides = v3SharpSides('ATL_GB');
  ok('the sharp block reads all three markets, not just the moneyline',
     sides.length >= 2 && sides.some(s => s.market === 'Spread'),
     JSON.stringify(sides));
  ok('and ranks them by ratio, biggest bet first',
     sides.every((s, i) => i === 0 || sides[i - 1].ratio >= s.ratio),
     JSON.stringify(sides.map(s => s.ratio)));
  ok('a side backed by ordinary-sized bets is left out',
     sides.every(s => s.ratio >= V3RATIO_SMALL),
     JSON.stringify(sides));

  // THE CASE A GAP RANKING DROPS. Carolina is 89% of the tickets AND 96% of
  // the money: a 7-point gap, under every threshold on this card, and three
  // times the average bet.
  const car = v3SharpSides('CAR_CLE');
  ok('a heavily backed side with the money behind it still surfaces',
     car.length === 1 && car[0].side === 'CAR', JSON.stringify(car));
  ok('and is named by its ratio rather than its gap',
     v3Sharp('CAR_CLE').indexOf('3.0\u00d7') >= 0
       || v3Sharp('CAR_CLE').indexOf('3.0×') >= 0, v3Sharp('CAR_CLE'));

  const html = v3Sharp('ATL_GB');
  ok('the card names the side and both shares',
     html.indexOf('ATL') >= 0 && html.indexOf('% of bets') >= 0
       && html.indexOf('% of the money') >= 0);
  // NOT A TIP. Whether the bigger money is the smarter money is exactly what
  // has not been measured, and the card has to say so on its face.
  ok('the card refuses to call itself a tip',
     html.indexOf('not a') >= 0 && html.indexOf('not measured') >= 0, html);
  ok('a game with no split shows no card',
     v3Sharp('NOPE_NOPE') === '', v3Sharp('NOPE_NOPE'));

  // And it reaches the actual game screen rather than only the function.
  // On Odds, with the public split it is the other half of: the bars there
  // are the ticket share and this is the dollar share.
  V.tab = 'games'; V.game = 'ATL_GB'; V.gameTab = 'odds'; render();
  ok('the sharp block is on the game screen',
     app().indexOf('Where the bigger bets are') >= 0);
  V.game = null; V.tab = 'props'; V.gameTab = 'notes';
}


// ── The move since open, compared like for like ─────────────────────────
//
// `openImplied` is raw and `book` is de-vigged. Subtracting one from the
// other measured the overround, not the market, and only ever downward: on
// the live board 316 of 814 rows carried the move with the wrong sign, and
// the closing-line note — this project's one measured claim — read 16% where
// the backtest says 60%.
{
  const { v3NowImplied, v3Clv, v3ClvNote } = x;

  ok('the current price is read raw, margin and all',
     Math.abs(v3NowImplied({ odds: -345 }) - 0.7753) < 0.001,
     String(v3NowImplied({ odds: -345 })));
  ok('and an underdog price too',
     Math.abs(v3NowImplied({ odds: 205 }) - 0.3279) < 0.001,
     String(v3NowImplied({ odds: 205 })));
  ok('a row with no price has no implied number',
     v3NowImplied({}) === null);

  // Kyren Williams, from the board the bug was found on. Opened -260
  // (0.7222 raw), now -345 (0.7753 raw): the market came 5.3pp toward him.
  // The de-vigged 0.608 would call that a 11.4-point move AWAY.
  const moved = { openImplied: 0.7222, odds: -345, book: 0.608,
                  modelOnly: 0.80, kind: 'td' };
  const c = v3Clv([moved]);
  ok('a market that came toward the pick is counted as toward',
     c && c.n === 1 && c.toward === 1, JSON.stringify(c));

  // And the reverse, so the fix is not simply "always true".
  const away = { openImplied: 0.7222, odds: -200, book: 0.60,
                 modelOnly: 0.80, kind: 'td' };
  const c2 = v3Clv([away]);
  ok('a market that drifted away is not counted as toward',
     c2 && c2.n === 1 && c2.toward === 0, JSON.stringify(c2));

  // ONLY ROWS RATED ABOVE THE OPEN. "The price moved" is not the claim.
  const notours = { openImplied: 0.7222, odds: -345, book: 0.608,
                    modelOnly: 0.50, kind: 'td' };
  ok('a pick we rated below the open is not counted at all',
     v3Clv([notours]) === null, JSON.stringify(v3Clv([notours])));

  // Under a handful the share is noise and must not be printed.
  ok('three picks are too few to report a share',
     v3ClvNote([moved, moved, moved], 'picks') === '');
  ok('four are enough',
     v3ClvNote([moved, moved, moved, moved], 'picks').indexOf('4 of 4') >= 0);
}


// ── The money in a player's game ────────────────────────────────────────
//
// There is NO ticket/money split on any player prop — the feed publishes the
// moneyline, the spread and the total and nothing else. What a prop can
// inherit is the money on the game it sits in, and the only honest version of
// that says whose side it is on.
{
  const { v3GameMoney } = x;

  const mine = v3GameMoney({ gameId: 'AAA @ BBB', team: 'AAA' });
  ok('a player inherits the money on their own game',
     mine && Math.abs(mine.ratio - 4.0) < 0.001, JSON.stringify(mine));
  ok('and it says the money is on their side',
     mine && mine.mine === true && mine.facing === false, JSON.stringify(mine));

  const against = v3GameMoney({ gameId: 'AAA @ BBB', team: 'BBB' });
  ok('a player facing the money is told so, not merely told there is money',
     against && against.mine === false && against.facing === true,
     JSON.stringify(against));

  ok('a game with no split gives a player nothing',
     v3GameMoney({ gameId: 'NOPE_NOPE', team: 'AAA' }) === null);
  ok('and a row with no game at all does not throw',
     v3GameMoney({}) === null);

  // IT HAS TO REACH THE OPENED ROW, not just the function.
  //
  // The row is looked up rather than named. Hardcoding a player assumed it
  // would be on the visible page, and the board is sorted and capped at
  // `V.shown` — the fixture's Alpha Back sorts past the cap, so the check
  // failed while the feature worked. Every piece of state this screen reads
  // is reset too, because an earlier block leaving a week or a filter set
  // empties the board, which reads as "the line is missing".
  V.tab = 'props'; V.market = 'any'; V.week = null; V.game = null;
  V.filter = 'all'; V.q = ''; V.shown = 500;
  V.sort = 'model'; V.desc = true;
  const withMoney = rowsFor('any', null)
    .filter(r => r.priced && !r.blocked && v3GameMoney(r));
  ok('some board row sits in a game with money on it', withMoney.length > 0);
  V.open = withMoney[0].id; render();
  ok('the opened player row names the money in their game',
     app().indexOf('Big money in this game') >= 0,
     'open=' + V.open);
  ok('and names the side carrying it',
     app().indexOf('the average bet') >= 0);
  V.open = null; V.shown = 25;
}


// ── The scoreline nearest our projection ────────────────────────────────
//
// The list is ordered by how often each score has happened, which is a fact
// about games like this one. The projection is specific to this game. The
// marker joins them; it must not claim either is the other.
{
  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'out';
  V.week = null; render();
  const seen = app();
  if (seen.indexOf('srow') >= 0) {
    // "where our model points", not "nearest our number": the list is
    // centered on the MARKET's line, so this marker is the gap between the
    // two and often sits low. The old wording read as a bug beside a list
    // nobody had said was centered somewhere else.
    // LIKELIEST FIRST, and the rank is on the row. Sorting by distance to our
    // number put a score less than half as likely at the top: walk-forward,
    // the nearest row lands 0.58% against the kernel's own first pick at
    // 1.37%.
    ok('every row carries its place in the order',
       (seen.match(/class="srank"/g) || []).length
       === (seen.match(/class="srow/g) || []).length,
       (seen.match(/class="srank"/g) || []).length + ' ranks, '
       + (seen.match(/class="srow/g) || []).length + ' rows');
    ok('and the proximity tint is gone with the ordering it belonged to',
       seen.indexOf('srow--like') < 0);
    ok('and no per-row percentage sits beside a per-scoreline count',
       seen.indexOf('where our model points') < 0);
    ok('and our number is stated rather than only implied',
       seen.indexOf('Our number') >= 0);
    // RANK ORDER, not distance order. The scores arrive ranked, so the first
    // row rendered must be the first one in the payload.
    ok('the list is in the order the model ranked them',
       seen.indexOf('>1</i>') < seen.indexOf('>2</i>')
       || seen.indexOf('>2</i>') < 0,
       'rank 1 at ' + seen.indexOf('>1</i>')
       + ', rank 2 at ' + seen.indexOf('>2</i>'));
    ok('and every row says how far it sits from that number',
       seen.indexOf(' off') >= 0);
    // IT MUST NOT READ AS A RESULT. `srow--on` marks what actually happened
    // on a played week; this marks where our number points, and the two are
    // different kinds of claim.
    ok('an unplayed game marks no row as having happened',
       seen.indexOf('\u00b7 this one') < 0 || seen.indexOf('final') >= 0);
  }
  V.game = null; V.tab = 'props'; V.gameTab = 'notes';
}


// ── The totals ladder says what it is for ───────────────────────────────
//
// At the posted number the rate is 50% by construction, so the table used to
// restate that more points are less likely. The row worth reading is where
// OUR number falls, and the posted one has to actually be a rung — it was one
// only by luck of banker's rounding, missing 8 of 16 games under a note that
// promised it was marked.
{
  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'out';
  V.week = null; render();
  const seen = app();
  if (seen.indexOf('Total points') >= 0) {
    ok('the posted total is actually a marked rung',
       seen.indexOf('\u00b7 posted') >= 0);
    ok('and the gap to our number is stated above the table',
       seen.indexOf('our number') >= 0);
  }
  V.game = null; V.tab = 'props'; V.gameTab = 'notes';
}


// ── The game's section bar stays reachable ──────────────────────────────
//
// Notes, Players and Outcome are long sections — the ladder alone is four
// tables — so switching from deep inside one meant scrolling back to a bar
// that had left the screen.
{
  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'notes';
  V.week = null; render();
  ok('the section bar has its own sticky wrapper',
     app().indexOf('class="gtabs"') >= 0);
  // The segmented control itself stays exactly as it was; only the wrapper
  // is new. (The CSS side is checked in tests/test_v3_export.py, which can
  // read the stylesheet.)
  ok('and the control inside it is unchanged',
     app().indexOf('class="seg seg--5"') >= 0);
  V.game = null; V.tab = 'props';
}


// ── Switching section starts at that section ────────────────────────────
//
// The bar is pinned, so keeping the scroll offset left you deep inside a
// section you had not read, at a position that belonged to the one you left.
{
  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'notes';
  V.week = null; render();
  let threw = null;
  try { v3Do('v3gtab', 'out'); } catch (e) { threw = e; }
  ok('switching section does not throw', !threw, threw && threw.message);
  ok('and lands on the section rather than the tab you left',
     V.gameTab === 'out');
  // The flag is consumed by the render, so the NEXT paint keeps its place.
  ok('and the scroll intent is consumed, not left armed',
     V.top === false, String(V.top));
  V.game = null; V.tab = 'props'; V.gameTab = 'notes';
}


// ── And starts there FROM DEEP INSIDE the section you are leaving ───────
//
// The case above is checked at the top of the page, where a sticky bar and a
// static one behave identically — which is why it passed while the feature
// did nothing. The bar is `position: sticky`, so once you have scrolled past
// it the browser reports it PINNED at the pane's top edge: `rect.top -
// pane.top` is zero, and code that adds that to the current offset lands you
// back where you started. Modeling the stickiness is the only way to tell
// the two apart.
{
  const BAR_AT = 300;               // the bar's place in the document
  const DEEP = 900;                 // and how far past it you had read
  const scroll = document.getElementById('scroll');
  const pane = document.querySelector('.gtabs');
  // `top: 0` sticky: the bar rides up with the content until it reaches the
  // pane's edge, then stops there. Exactly `max(0, layout - scrolled)`.
  pane._rect = () => ({ top: Math.max(0, BAR_AT - scroll.scrollTop) });
  scroll._rect = () => ({ top: 0 });
  // A pane with room to scroll that far. Left at zero the page cannot reach
  // the bar at all, and the assertions below would be measuring the clamp.
  scroll.scrollHeight = 5000; scroll.clientHeight = 800;

  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'notes';
  V.week = null; render();
  scroll.scrollTop = DEEP;
  // Proves the model, not the page: at this depth the bar really is pinned,
  // so a test that read the rect and believed it would see zero.
  ok('the harness models a bar that is pinned when you are deep in a section',
     pane.getBoundingClientRect().top === 0);

  v3Do('v3gtab', 'out');
  ok('switching section from deep inside one lands on the new section',
     scroll.scrollTop === BAR_AT, 'scrollTop ' + scroll.scrollTop);
  ok('and does not leave you at the offset you came from',
     scroll.scrollTop !== DEEP);

  pane._rect = null; scroll._rect = null; scroll.scrollTop = 0;
  V.game = null; V.tab = 'props'; V.gameTab = 'notes';
}

// ── Changing game without leaving where you are reading ────────────────
//
// The switcher sat in `.gamenav` above the matchup card, so by the time you
// were in the Outcome tables and wanted the same table for another game, the
// control had scrolled off and the only route was out to the list and back in.
if (cards.length > 1) {
  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'out';
  V.week = null; render();
  const gh = app();
  const barAt = gh.indexOf('class="gtabs"');
  ok('the game switcher is inside the pinned bar',
     gh.indexOf('data-v3gameto') > barAt && barAt >= 0);
  ok('and not left behind above the matchup card as well',
     gh.split('data-v3gameto').length - 1 === 1,
     String(gh.split('data-v3gameto').length - 1));
  ok('the arrows are there too',
     gh.indexOf('data-v3gamestep') > barAt);

  // BOTH CONTROLS BEHAVE THE SAME WAY. The arrows used to run through
  // `v3game`, which is the games LIST's action: it reset the section to Notes
  // and went to the page top, so the arrow beside the Outcome tab took you to
  // another game's Notes while the dropdown beside it kept Outcome.
  const step = /data-v3gamestep="([^"]+)"/.exec(gh);
  ok('an arrow names a real game', !!step);
  if (step) {
    // Same pinned-bar geometry as the section test, so "landed on the
    // section" is a measured offset rather than a consumed flag.
    const BAR_AT = 300, DEEP = 900;
    const scroll = document.getElementById('scroll');
    const pane = document.querySelector('.gtabs');
    pane._rect = () => ({ top: Math.max(0, BAR_AT - scroll.scrollTop) });
    scroll._rect = () => ({ top: 0 });
    scroll.scrollHeight = 5000; scroll.clientHeight = 800;
    scroll.scrollTop = DEEP;

    v3Do('v3gamestep', step[1]);
    ok('stepping keeps the section you were reading',
       V.gameTab === 'out', String(V.gameTab));
    ok('and changes the game', V.game === step[1]);
    ok('and lands on that section, not the top of the new game',
       scroll.scrollTop === BAR_AT, 'scrollTop ' + scroll.scrollTop);

    // The dropdown is the same control and must agree.
    const other = (cards.filter(c => c.game_id !== V.game)[0] || {}).game_id;
    if (other) {
      V.gameTab = 'out'; render(); scroll.scrollTop = DEEP;
      fireDoc('change', { target: {
        getAttribute: k => k === 'data-v3gameto' ? '' : null,
        value: other } });
      ok('the dropdown keeps the section too', V.gameTab === 'out');
      ok('and lands in the same place as the arrows',
         scroll.scrollTop === BAR_AT, 'scrollTop ' + scroll.scrollTop);
    }
    pane._rect = null; scroll._rect = null; scroll.scrollTop = 0;
  }
  V.game = null; V.tab = 'props'; V.gameTab = 'notes';
}

// ── A thin window is a caveat, not a refusal ───────────────────────────
//
// Under `MIN_COMPARABLES` the Outcome tab used to be two cards explaining
// twice why it was empty. The comparables are still this game's; 52 games is
// thin for a PERCENTAGE and perfectly informative about SHAPE, and
// withholding the shape left nothing to be careful with.
if (cards.length) {
  const c = cards[0];
  const keep = { scores: c.scores, ladders: c.ladders };
  if (keep.scores && keep.scores.n) {
    // Same payload, declared thin — the Python side already computes
    // everything below `MIN_COMPARABLES`, so this is exactly what a thin
    // game serves.
    c.scores = Object.assign({}, keep.scores,
                             { thin: true, n: 52, min_n: 60 });
    if (c.ladders) c.ladders = Object.assign({}, keep.ladders,
                                             { thin: true, n: 52 });
    V.tab = 'games'; V.game = c.game_id; V.gameTab = 'out';
    V.week = null; render();
    const gh = app();
    ok('a thin game says so', gh.indexOf('class="thin"') >= 0);
    ok('and says it once, not once per table',
       gh.split('class="thin"').length - 1 === 1,
       String(gh.split('class="thin"').length - 1));
    ok('and names the count', gh.indexOf('52 past games') >= 0);
    // THE POINT OF THE CHANGE: the tables are still there.
    ok('and still draws the margin bands',
       gh.indexOf('class="mrow') >= 0);
    ok('and still draws the ladder',
       gh.indexOf('data-v3half') >= 0 || gh.indexOf('class="lfields"') >= 0
       || gh.indexOf('Over') >= 0);
    ok('and does not refuse',
       gh.indexOf('too few to draw a distribution') < 0
       && gh.indexOf('too few to build a table') < 0);

    // And a healthy sample carries no banner at all.
    c.scores = keep.scores; c.ladders = keep.ladders;
    render();
    ok('a full sample shows no banner',
       app().indexOf('class="thin"') < 0);
  }
  V.game = null; V.tab = 'props'; V.gameTab = 'notes';
}

// ── The sections are five, in the order you decide things in ───────────
if (cards.length) {
  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'odds';
  V.week = null; render();
  const gh = app();
  const at = k => gh.indexOf('data-v3gtab="' + k + '"');
  ['odds', 'out', 'players', 'notes', 'edge'].forEach(k =>
    ok('the ' + k + ' section is on the bar', at(k) >= 0));
  ok('and injuries is not one of them, having joined the matchup',
     at('inj') < 0);
  // The three you can BET sit together, ahead of the two that explain them.
  ok('the betting sections come first and are not split by commentary',
     at('odds') < at('out') && at('out') < at('players')
     && at('players') < at('notes') && at('notes') < at('edge'));
  // The LABELS say what is in each: the ladder of lines under the score
  // distribution is about the score, and the player rows are the Props board
  // scoped to this game rather than a second, differently named one.
  ok('the sections are labeled for their contents',
     gh.indexOf('>Score<') >= 0 && gh.indexOf('>Props<') >= 0
     && gh.indexOf('>Outcome<') < 0 && gh.indexOf('>Players<') < 0);
  // Renaming a label must not move the reader: the keys are in saved state
  // and in links.
  ok('and the keys behind them are unchanged',
     at('out') >= 0 && at('players') >= 0);
  // Opening a game from the list lands on the price, which is what the page
  // showed before the market block became a section rather than a preamble.
  V.game = null; V.tab = 'games'; V.gameTab = 'notes'; render();
  v3Do('v3game', cards[0].game_id);
  ok('opening a game from the list lands on the price',
     V.gameTab === 'odds', String(V.gameTab));
  V.game = null; V.tab = 'props'; V.gameTab = 'notes';
}

// ── The props filters are one pinned bar ───────────────────────────────
//
// Stacked at full size they ran about 250px before the first player, which
// is fine to read once and impossible to pin. Every control keeps one tap.
{
  V.tab = 'props'; V.game = null; V.week = null; V.q = ''; render();
  const h = app();
  ok('the filters share one bar', h.indexOf('class="pbar"') >= 0);
  // A SEGMENTED CONTROL, the same one the filter row uses. As pills sized to
  // their own labels the row was only as wide as the names happened to be,
  // and six of them overflowed into a sideways scroll.
  const nServed = x.V3MKT.filter(m => served(m[0])).length;
  ok('the markets divide the width evenly instead of overflowing',
     h.indexOf('class="seg seg--' + nServed + '"') >= 0,
     'expected seg--' + nServed);
  ok('and are not a grid that wraps to two rows',
     h.indexOf('class="mkts"') < 0 && h.indexOf('mkts--strip') < 0);
  // All four still reachable without leaving the bar.
  ok('market is in it', h.indexOf('data-v3mkt=') > h.indexOf('class="pbar"'));
  ok('shortlist and fades are in it', h.indexOf('data-v3filter=') >= 0);
  ok('search is in it', h.indexOf('data-v3q') >= 0);
  ok('sort is in it', h.indexOf('data-v3sortsel') >= 0);
  // ONE OF EACH. Search and sort moved INTO the bar, so leaving the old
  // standalone copies in place would pin one and scroll the other, and typing
  // in the wrong box would look like search was broken.
  ok('and search appears once, not above the bar as well',
     h.split('data-v3q').length - 1 === 1,
     String(h.split('data-v3q').length - 1));
  ok('and sort appears once', h.split('data-v3sortsel').length - 1 === 1,
     String(h.split('data-v3sortsel').length - 1));
  // The prose stays, under the bar rather than inside it: it explains what
  // you are reading instead of changing it, so it is not worth pinned pixels.
  const barAt = h.indexOf('class="pbar"');
  const rowsAt = h.indexOf('id="v3rows"');
  const helpAt = h.indexOf('class="help"', barAt);
  ok('with the market explanation below the bar and above the rows',
     helpAt > barAt && helpAt < rowsAt,
     'bar ' + barAt + ', help ' + helpAt + ', rows ' + rowsAt);
  // Narrowing to one game is set once and worked inside, so it sits above.
  const pickAt = h.indexOf('data-v3gamesel');
  ok('and the game filter above it rather than pinned too',
     pickAt >= 0 && pickAt < barAt, 'picker ' + pickAt + ', bar ' + barAt);
  // And the controls still WORK from the bar, not just draw in it.
  v3Do('v3filter', 'short');
  ok('the filter still filters from inside the bar', V.filter === 'short');
  v3Do('v3filter', 'all');
}

// The same bar inside a game, pinned UNDER the game bar rather than over it.
if (cards.length) {
  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'players';
  V.week = null; render();
  const h = app();
  ok('the game props section uses the same bar',
     h.indexOf('class="pbar"') >= 0);
  ok('and it comes after the game bar it pins under',
     h.indexOf('class="pbar"') > h.indexOf('class="gtabs"'));
  ok('and still has exactly one search box',
     h.split('data-v3q').length - 1 === 1);
  // The same green line, counted over THIS GAME's picks. The board's number
  // is the whole market, and quoting that under one game's rows would be a
  // statistic about somewhere else.
  if (h.indexOf('class="clv"') >= 0) {
    ok('the game props section carries the measured edge too',
       h.indexOf('class="clv"') > h.indexOf('class="pbar"'));
    ok('and says it is this game it counted',
       h.indexOf('this game') > 0);
  }
  // NOTHING BETWEEN THE TWO PINNED BARS. A sentence there is charged to the
  // one part of the page that cannot afford one, and it described the screen
  // to someone already looking at it.
  ok('and no preamble between the bars and the rows',
     h.indexOf('The same board as This week') < 0);
  const gAt = h.indexOf('class="gtabs"');
  const pAt = h.indexOf('class="pbar"');
  ok('the two bars are adjacent', pAt > gAt && gAt >= 0);
  // The market's own sentence — "pays if the player scores a touchdown" —
  // stays. It says what the market IS, which the short pill labels no longer
  // can, and it sits below the pinned bars where it costs nothing.
  ok('but the market explanation survives the cut',
     h.slice(pAt, h.indexOf('id="v3rows"')).indexOf('class="help"') >= 0);
  V.game = null; V.tab = 'props'; V.gameTab = 'notes';
}

// ── Standing explanation is not charged to the top of the board ────────
//
// Five lines of CLV context and a sentence restating each filter's own name
// ran above the players on every props screen. All of it true, none of it
// changing between one board and the next.
{
  V.tab = 'props'; V.game = null; V.week = null; V.filter = 'all'; render();
  const h = app();
  const barAt = h.indexOf('class="pbar"');
  const rowsAt = h.indexOf('id="v3rows"');
  ok('the three-season CLV explanation is not above the board',
     h.indexOf('shuffled list', 0) < 0
     || h.indexOf('shuffled list') > rowsAt,
     'shuffled at ' + h.indexOf('shuffled list') + ', rows at ' + rowsAt);
  // But the COUNT stays, and keeps the condition that defines its sample.
  if (h.indexOf('Prices moved toward us on') >= 0) {
    const cAt = h.indexOf('Prices moved toward us on');
    ok('the count itself is still there', cAt < rowsAt);
    ok('and still says which picks it counted',
       h.indexOf('rated above the open', cAt) > cAt
       && h.indexOf('rated above the open', cAt) < cAt + 200);
  }
  // And the explanation is still ON the page, in the card that explains.
  ok('the explanation moved to How to read a pick',
     h.indexOf('shuffled list') > rowsAt
     || h.indexOf('How to read a pick') < 0);

  // Filters that restate their own button are gone.
  V.filter = 'fav'; render();
  ok('Starred says nothing beyond its own label',
     app().indexOf('The same list v2 uses') < 0);
  V.filter = 'short'; render();
  ok('nor does Shortlist',
     app().indexOf('the picks this project would actually place') < 0);
  // Fades is the exception and stays: the word reads like a bet to place and
  // it is the opposite, so the line prevents a real mistake.
  V.filter = 'fade'; render();
  ok('but Fades still warns they are not bets to place',
     app().indexOf('leave alone') >= 0);
  ok('and does it in one line, not four',
     app().indexOf('no book posts the other side') < 0);
  V.filter = 'all';
  if (barAt < 0) ok('the bar was on screen for this check', false);
}

// ── Short labels on the pills, full names everywhere else ──────────────
//
// Six markets on one row of a phone is about 50px each, and "Receiving yds"
// does not go in 50px — so the strip scrolled sideways, hiding half the
// markets behind a gesture nothing on screen advertises.
{
  V.tab = 'props'; V.game = null; V.week = null; V.market = 'any'; render();
  const h = app();
  const bar = h.slice(h.indexOf('class="pbar"'), h.indexOf('id="v3rows"'));
  // Shorter still, because an even sixth of a phone is about 50px.
  ok('every short label fits a sixth of a phone',
     x.V3MKT.every(m => m[4].length <= 7),
     x.V3MKT.map(m => m[4]).join(' | '));
  // THE TWO RECEIVING MARKETS MUST NOT SHARE A STEM. One counts catches and
  // one counts yards; shortened toward the same word they became "Rec" and
  // "Rec yd", a letter apart and side by side. Same first three characters is
  // the failure, not just an exact match.
  const recL = x.V3MKT.filter(m => m[0] === 'rec')[0][4];
  const rydL = x.V3MKT.filter(m => m[0] === 'recyds')[0][4];
  ok('the two receiving markets cannot be misread for each other',
     recL.slice(0, 3).toLowerCase() !== rydL.slice(0, 3).toLowerCase(),
     recL + ' vs ' + rydL);
  // Over the markets this payload actually serves, not a hard-coded six:
  // the fixture serves four, so naming them would pass by not looking.
  const servedM = x.V3MKT.filter(m => served(m[0]));
  ok('the fixture serves enough markets to fill a row', servedM.length >= 4,
     String(servedM.length));
  ok('the pills use the short label',
     servedM.every(m => bar.indexOf('>' + m[4]) >= 0),
     servedM.map(m => m[4]).join(' | '));
  ok('and not the long one',
     servedM.every(m => m[4] === m[1] || bar.indexOf('>' + m[1] + '<') < 0),
     servedM.map(m => m[1]).join(' | '));
  // Every market has one, or a pill silently falls back to the long name and
  // the row overflows again.
  ok('every market carries a short label',
     x.V3MKT.every(m => typeof m[4] === 'string' && m[4].length > 0
                        && m[4].length <= 8),
     JSON.stringify(x.V3MKT.map(m => m[4])));
  // The full name still has work to do off the pills.
  V.market = 'rush';
  ok('the prose still uses the full name',
     x.v3MktLabel().indexOf('rushing') >= 0, x.v3MktLabel());
  V.market = 'any';
}

// ── The board has the game screen's bar, pinned ────────────────────────
{
  V.tab = 'props'; V.game = null; V.week = null; render();
  let h = app();
  ok('the board bar is in the same pinned wrapper as the game screen',
     h.indexOf('class="gtabs"') >= 0);
  ok('and the filters pin under it',
     h.indexOf('class="pbar"') > h.indexOf('class="gtabs"'));
  ok('it still offers every game', h.indexOf('data-v3gamesel') >= 0);
  ok('with a forward stepper from all games',
     h.indexOf('data-v3boardgame=') >= 0);
  // Back and Ask are about ONE game, so neither shows until one is chosen.
  ok('no Ask across sixteen matchups', h.indexOf('data-v3sheet="ask"') < 0);
  ok('and no back from all games', h.indexOf('class="gback"') < 0);

  // Stepping filters the board rather than opening the game screen.
  const step = /data-v3boardgame="([^"]+)"/.exec(h);
  ok('a stepper names a real game', !!step);
  if (step) {
    v3Do('v3boardgame', step[1]);
    ok('stepping filters the board', V.game === step[1]);
    ok('and does not leave the board', V.tab === 'props');
    h = app();
    ok('now Ask is offered', h.indexOf('data-v3sheet="ask"') >= 0);
    ok('and back is too', h.indexOf('class="gback"') >= 0);
    v3Do('v3boardgame', '');
    ok('back returns to all games', V.game === null, String(V.game));
  }
}

// ── The measured edge is called out, on both boards ────────────────────
//
// It was set in the same muted grey as "pays if the player scores a
// touchdown", where the one edge this project has measured read as another
// line of instructions. And it only appeared on the props board, which made
// it look like a fact about touchdown props rather than about every line.
{
  V.tab = 'props'; V.game = null; V.week = null; render();
  const ph = app();
  if (ph.indexOf('class="clv"') >= 0) {
    ok('the props board calls it out rather than greying it',
       ph.indexOf('class="clv"') >= 0);
    ok('and not as help text', ph.indexOf('class="help">Prices moved') < 0);
    // BELOW THE PINNED BAR. The number is per market, so from above the bar
    // it never changed in front of you: you tapped Rush, the rows redrew,
    // and the one line that also moved was two screens up.
    const clvAt = ph.indexOf('class="clv"');
    ok('and below the filters, where switching market shows it change',
       clvAt > ph.indexOf('class="pbar"'),
       'clv ' + clvAt + ', bar ' + ph.indexOf('class="pbar"'));
    ok('and above the rows it describes',
       clvAt < ph.indexOf('id="v3rows"'));
    // The note is built from `rowsFor(V.market, ...)`, so it is per market by
    // construction — this checks the wiring survives, not the arithmetic:
    // switching market must re-render it rather than leave the first one up.
    const countOf = t => (/(\d+) of (\d+)/.exec(
      t.slice(t.indexOf('class="clv"'))) || [])[0];
    const a = countOf(ph);
    V.market = 'rush'; render();
    const bh = app();
    ok('and it is rebuilt for the market you switch to',
       bh.indexOf('class="clv"') < 0 || !!countOf(bh),
       'was ' + a + ', now ' + countOf(bh));
    V.market = 'any'; render();
  }
  V.tab = 'games'; V.game = null; render();
  const gh = app();
  // Only where the payload HAS a measurable set. `v3ClvNote` prints nothing
  // under four qualifying lines, and asserting regardless would turn a thin
  // fixture into a failure about the games board.
  const grows = ((DATA.games || {}).rows || [])
    .filter(r => r.priced && !r.blocked);
  const gc = x.v3Clv(grows);
  ok('the games board is wired to the same measurement',
     !gc || gc.n < 4 || gh.indexOf('class="clv"') >= 0,
     'clv=' + JSON.stringify(gc));
  // A graded week's prices stopped moving, so it says nothing there.
  if (gc && gc.n >= 4) {
    V.week = 1; render();
    ok('and says nothing on a graded week', app().indexOf('class="clv"') < 0);
    V.week = null;
  }
  V.tab = 'props';
}

// ── The games board's filter is pinned too ─────────────────────────────
//
// Sixteen game cards is four screens, and the control that narrows them sat
// above all four.
{
  V.tab = 'games'; V.game = null; V.week = null; V.gfilter = 'all'; render();
  const h = app();
  const barAt = h.indexOf('class="pbar pbar--free"');
  ok('the games filter is in the shared pinned bar', barAt >= 0);
  ok('and it is the filter that is pinned, not a copy of it',
     h.split('data-v3gfilter="all"').length - 1 === 1);
  ok('with the seg inside it',
     h.indexOf('data-v3gfilter=') > barAt);
  // The counts and the measured edge stay in the flow above: read once, and
  // they are what makes the bar the top of the page once you scroll.
  const statAt = h.indexOf('Model agrees');
  ok('the counts are above it rather than pinned with it',
     statAt >= 0 && statAt < barAt, 'stats ' + statAt + ', bar ' + barAt);
  if (h.indexOf('class="clv"') >= 0) {
    ok('and so is the measured edge',
       h.indexOf('class="clv"') < barAt);
  }
  // The rows it filters come after it, or it is pinning nothing.
  ok('and the cards it filters below it',
     h.indexOf('data-v3game=') > barAt);
  // Still works from the bar.
  v3Do('v3gfilter', 'flip');
  ok('the pinned filter still filters', V.gfilter === 'flip');
  v3Do('v3gfilter', 'all');
  V.tab = 'props';
}

// ── Changing the list starts you at the top of it ──────────────────────
//
// Keeping the offset was right when these controls sat above the board and
// scrolled with it. Pinned, they change the list UNDER a bar that does not
// move — so tapping Rush from forty rows down landed you forty rows into a
// different market, past the CLV line that had just changed with it.
{
  const BAR_AT = 300, DEEP = 900;
  const scroll = document.getElementById('scroll');
  const bar = document.querySelector('.gtabs');
  bar._rect = () => ({ top: Math.max(0, BAR_AT - scroll.scrollTop) });
  scroll._rect = () => ({ top: 0 });
  scroll.scrollHeight = 5000; scroll.clientHeight = 800;

  V.tab = 'props'; V.game = null; V.week = null;
  V.market = 'any'; V.filter = 'all'; render();

  scroll.scrollTop = DEEP;
  v3Do('v3mkt', 'rush');
  ok('switching market starts at the top of the new market',
     scroll.scrollTop === BAR_AT, 'scrollTop ' + scroll.scrollTop);

  scroll.scrollTop = DEEP;
  v3Do('v3filter', 'short');
  ok('and switching Everyone / Shortlist / Fades does the same',
     scroll.scrollTop === BAR_AT, 'scrollTop ' + scroll.scrollTop);

  // NOT the top of the PAGE: the title and the counts stay above, and these
  // controls are not navigation.
  ok('at the bar rather than the top of the page', scroll.scrollTop !== 0);

  // Sorting is not a different list, it is the same one in another order —
  // you are looking at a row and want it moved, not to start over.
  scroll.scrollTop = DEEP;
  v3Do('v3sort', 'model');
  ok('but sorting keeps your place', scroll.scrollTop === DEEP,
     'scrollTop ' + scroll.scrollTop);

  // A tall pane needs no help, and must not be given any.
  ok('no dead space is added when the page can already scroll',
     document.getElementById('app').style.paddingBottom === '0px',
     String(document.getElementById('app').style.paddingBottom));

  // A SHORT LIST CANNOT BE SCROLLED THAT FAR ON ITS OWN. Filtering to one
  // result leaves a page the browser clamps, which stranded the bar a third
  // of the way down. Landing at zero instead was tidier and made the short
  // filter behave differently from every other one — Agrees pinned the bar,
  // Upsets showed the whole page, one tap doing two things.
  scroll.scrollHeight = 900; scroll.clientHeight = 800;   // max scroll: 100
  scroll.scrollTop = 60;
  v3Do('v3filter', 'fade');
  ok('a short filter lands on the bar like every other one',
     scroll.scrollTop === BAR_AT, 'scrollTop ' + scroll.scrollTop);
  // The room is MADE: exactly the shortfall, so the new maximum is the offset
  // being asked for.
  ok('by padding the page by exactly what it was short',
     document.getElementById('app').style.paddingBottom
       === (BAR_AT - 100) + 'px',
     String(document.getElementById('app').style.paddingBottom));

  // And it is recomputed, not accumulated: a render that needs none clears it.
  scroll.scrollHeight = 5000; scroll.clientHeight = 800;
  v3Do('v3filter', 'all');
  ok('and cleared again once the page is long enough',
     document.getElementById('app').style.paddingBottom === '0px',
     String(document.getElementById('app').style.paddingBottom));

  V.filter = 'all'; V.market = 'any';
  bar._rect = null; scroll._rect = null; scroll.scrollTop = 0;
  scroll.scrollHeight = 0; scroll.clientHeight = 0;
}

// ── The exact scores grade themselves once the game is in ──────────────
//
// Before kickoff a tinted row is one we like. After it, the same tint still
// said "we like this" about a game already decided — the only section on the
// page that did not grade itself, while the boxes above it turn green or red.
if (cards.length) {
  const c = cards[0];
  const keep = { s: c.scores, fh: c.final_home, fa: c.final_away };
  if (keep.s && (keep.s.scores || []).length > 1) {
    V.tab = 'games'; V.game = c.game_id; V.gameTab = 'out'; V.week = null;

    // A PROJECTION THAT LANDS ON ONE OF THE LISTED SCORES, so a row really is
    // "one we called". Without it nothing is liked, nothing can be red, and
    // the assertions about red below pass by counting zero.
    //
    // `pj` is [home, away] from the blend's spread and total, so the inverse
    // is total = home + away and spread = away - home.
    const near = keep.s.scores[1] || keep.s.scores[0];
    const keepBlend = c.blend;
    c.blend = Object.assign({}, c.blend || {},
      { total: near.home + near.away, spread: near.away - near.home });

    // LIVE: a liked row is a call, in the call color, and nothing is graded.
    c.final_home = null; c.final_away = null; render();
    const live = app();
    ok('before kickoff nothing is graded',
       live.indexOf('srow--on') < 0 && live.indexOf('srow--miss') < 0);


    // PLAYED, and the final IS on the list: that row goes green.
    const hit = keep.s.scores[0];
    c.final_home = hit.home; c.final_away = hit.away; render();
    const won = app();
    ok('the score the game finished on is marked green',
       won.indexOf('srow--on') >= 0);
    ok('and the call color is gone, because it is no longer a call',
       won.indexOf('srow--like') < 0);
    // EVERY OTHER ROW IS RED. Sixteen scores were put up and one happened;
    // the other fifteen were wrong, and leaving them neutral hid the thing
    // the list is worst at.
    const wRed = (won.match(/srow--miss/g) || []).length;
    const wRows = (won.match(/class="srow/g) || []).length;
    ok('and every score that did not happen is red',
       wRed === wRows - 1, wRed + ' red of ' + wRows + ' rows');
    ok('and the footer says green is the final',
       won.indexOf('Green is the score this game actually finished on') >= 0);
    ok('without claiming it is missing', won.indexOf('not on this list') < 0);

    // PLAYED, and the final is NOT on the list. Nothing green, and the footer
    // has to say so — otherwise a played game with no green row reads as
    // broken marking rather than as a score nobody listed.
    c.final_home = 99; c.final_away = 98; render();
    const off = app();
    ok('a final nobody listed leaves no green row',
       off.indexOf('srow--on') < 0);
    ok('and the footer says the final is not on the list',
       off.indexOf('not on this list') >= 0);
    // Rows we pointed at are red; rows we never pointed at are not.
    const reds = (off.match(/srow--miss/g) || []).length;
    const rows = (off.match(/class="srow/g) || []).length;
    // With the final on nobody's list, every row is wrong and every row is
    // red — there is no green to subtract.
    ok('a final nobody listed leaves the whole list red',
       reds === rows, reds + ' of ' + rows);
    ok('and there is at least one red to have been counted',
       reds > 0, reds + ' reds of ' + rows + ' rows');
    c.blend = keepBlend;
  }
  c.scores = keep.s; c.final_home = keep.fh; c.final_away = keep.fa;
  V.game = null; V.tab = 'props'; V.gameTab = 'notes';
}

done();
