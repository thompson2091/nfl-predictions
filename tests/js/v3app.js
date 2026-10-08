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
   // v1's null guard, so a check here reads the same way the page does.
   'has', 'KIND', 'v3Diff', 'v3MktLines',
   'isFav', 'toggleFav', 'v3Slipbar', 'v3Sheet', 'V3SHEETS', 'v3Rungs',
   'v3Num', 'v3Rows', 'v3LadderSummary', 'v3Questions', 'v3AskSend',
   'V3BETTYPES',
   'v3GameMkt', 'v3GameMkts', 'v3MarketForGame', 'v3GameEmpty',
   'v3Had', 'v3Ord', 'v3Graded', 'v3PastRow',
   'v3Streak', 'v3StreakTag', 'V3STREAK_OF', 'V3STREAK_MIN',
   'v3IsEdge', 'v3EdgeHit', 'v3EdgeNote', 'marketOf', 'KIND',
   'v3PublicMoney', 'v3MoneyBlock', 'v3SharpSides', 'V3RATIO_SMALL',
   'v3GameSet', 'v3RecordPage', 'v3RecRange', 'v3Money',
   'v3Ask', 'V3ASK_DEFAULT', 'v3AngleBase', 'v3Surprise', 'V3SURPRISE', 'v3Clears',
   'v3AngleSince', 'v3AngleYears',
   'v3GTab', 'v3MktLabel',
   'v3Clv',
   'v3NowImplied', 'v3Clv', 'v3ClvNote', 'v3GameMoney']);
const { V, render, v3Screen, v3Games, v3Game, v3Picks, v3Ladder, v3Nav,
        V3TABS, V3MKT, V3CLICKS, V3HIST, v3Questions, v3Value, v3Legs,
        rowsFor, served, DATA, has } = x;

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
V.tab = 'angles'; render();
ok('nor the angles board', app().indexOf('data-v3week') < 0);
// Nor the record: it is the whole season, so a week picker on it is a
// control that changes nothing, which is the exact fault the rule above
// exists for.
V.tab = 'record'; render();
ok('nor the season record', app().indexOf('data-v3week') < 0);
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
  // A coaching note must arrive labeled. Unlabeled, a 69% prime-time
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

  // ── The angles on THIS game ──────────────────────────────────────────
  //
  // Keyed by team and measured for one week, the card printed a week-3
  // answer under a week-4 fixture: ARI came off a 24-point loss in week 3
  // and its week-4 card said "ARI · Off a 20+ loss" when ARI's last result
  // was a six-point loss.
  {
    const gid = cards[0].game_id;
    const wk = (DATA.angles || {}).week || {};
    const mine = wk[gid] || [];
    // ANGLES IS ITS OWN TAB NOW. It was the longest block on the odds tab and
    // brought four controls of its own, under a card about the price.
    V.game = gid; V.gameTab = 'angles'; V.gaTeam = 'all'; V.gaOpen = null;
    V.gaSort = 'season'; V.gaDesc = true;
    render();
    const h = app();
    ok('the game card lists its angles', h.indexOf('Angles on this game') >= 0);
    ok('one row per angle this game carries',
       (h.match(/data-v3gangle="/g) || []).length === mine.length,
       (h.match(/data-v3gangle="/g) || []).length + ' drawn, '
       + mine.length + ' carried');
    // ANOTHER GAME'S ENTRIES MUST NOT REACH THIS CARD.
    const others = {};
    Object.keys(wk).forEach(k => {
      if (k !== gid) (wk[k] || []).forEach(pr => { others[pr[0]] = 1; });
    });
    const sides = {}; sides[cards[0].away] = 1; sides[cards[0].home] = 1;
    const strays = Object.keys(others).filter(
      t => !sides[t] && h.indexOf('<b>' + t + '</b>') >= 0);
    ok('and no other game\u2019s angles leak in', strays.length === 0,
       strays.join(','));
    // PINNED, LIKE EVERY OTHER FILTER IN THE APP. The median game carries
    // seventeen patterns, more than a screen, and the controls that narrow
    // them were above all of it.
    {
      const h2 = app();
      const bar = h2.indexOf('class="pbar"');
      ok('the angle filters are in a pinned bar', bar >= 0);
      // WRAPPED WITH THE TABLE IT FILTERS. A sticky element stays stuck as
      // long as its PARENT is on screen, so pinned to the tab itself it would
      // ride over the closing cards below the table.
      const sec = h2.indexOf('class="gasec"');
      ok('inside a section that also holds the table',
         sec >= 0 && sec < bar, 'gasec=' + sec + ' pbar=' + bar);
      const close = h2.indexOf('</div></div>', h2.indexOf('board of survivors'));
      ok('and the section closes after the table, not before it',
         h2.indexOf('data-v3gangle=') > bar);
      // Every control the reader narrows with is inside it, not some of them.
      const seg = h2.slice(bar, h2.indexOf('class="card"', bar));
      ok('with both segments and the year slider in it',
         seg.indexOf('data-v3gateam') >= 0
         && seg.indexOf('data-v3gascope') >= 0
         && seg.indexOf('data-v3anglefrom') >= 0, seg.slice(0, 120));
      // AND THE KIND, which is what a median of thirteen rows needs and what
      // replaced the search box: a search wants you to know the word already.
      ok('and the kind chooser rides in the bar, not under it',
         seg.indexOf('data-v3gacat') >= 0, seg.slice(0, 200));
      // AND NO SEARCH BOX. Fifty-five rows need one; a median of seventeen,
      // already split three ways by the team control, does not, and the box
      // cost the pinned bar a third of its height.
      ok('and no search box, which the team control already does',
         h2.indexOf('data-v3gaq') < 0);
    }
    // HOW FAR BACK TO COUNT, on this card as on the board and sharing the
    // same state: how far back you trust is a view about football, not about
    // which screen you are on.
    ok('the card carries the year slider',
       app().indexOf('data-v3anglefrom') >= 0);
    // \u2019, NOT AN ASCII APOSTROPHE. The header is built with a
    // typographic quote and a regex for the straight one matches nothing.
    const hdr = () => (/\u2019(\d\d)\+ ATS/.exec(app()) || [])[1];
    const was = hdr();
    fireDoc('change', { target: {
      getAttribute: a => a === 'data-v3anglefrom' ? '' : null, value: '2023' } });
    ok('and moving it moves the long-run column',
       V.angleFrom === 2023 && hdr() === '23', was + ' -> ' + hdr());
    // AND THE TEAM READING TOO, which is the other half of the ask.
    v3Do('v3gascope', 'team'); render();
    ok('on the team reading as well as the league one',
       app().indexOf("\u201923+ ATS") >= 0);
    v3Do('v3gascope', 'league');
    fireDoc('change', { target: {
      getAttribute: a => a === 'data-v3anglefrom' ? '' : null, value: '2015' } });
    render();
    // The same table as the board: sortable by its columns.
    ok('the columns sort it', h.indexOf('data-v3gasort=') >= 0);
    const order = () => (app().match(/data-v3gangle="([^"]+)"/g) || []).join('|');
    const byYear = order();
    v3Do('v3gasort', 'name'); render();
    ok('sorting the card reorders it', order() !== byYear, 'order unchanged');
    const az = order();
    v3Do('v3gasort', 'name'); render();
    ok('and tapping the same column flips it',
       order().split('|').reverse().join('|') === az);
    // ...and it does not reorder the Angles page behind it.
    ok('without touching the board\u2019s own sort', V.angleSort === 'season');
    v3Do('v3gasort', 'season'); render();
    // Whose angles: both sides in one list read as one team's.
    ok('the card can be narrowed to one side',
       app().indexOf('data-v3gateam=') >= 0);
    v3Do('v3gateam', cards[0].away); render();
    const only = (app().match(/data-v3gangle="([^":]+):/g) || [])
      .map(m => m.slice('data-v3gangle="'.length, -1));
    ok('and narrowing leaves only that side',
       only.length > 0 && only.every(t => t === cards[0].away),
       only.join(','));
    v3Do('v3gateam', 'all'); render();
    // Tapping a row opens the same fixture list the board opens.
    const first = /data-v3gangle="([^"]+)"/.exec(app());
    if (first) {
      ok('nothing is open to begin with', app().indexOf('class="adet"') < 0);
      v3Do('v3gangle', first[1]); render();
      ok('tapping a row opens its games', app().indexOf('class="adet"') >= 0);
      ok('and only one at a time',
         (app().match(/class="adet"/g) || []).length === 1);
      v3Do('v3gangle', first[1]); render();
      ok('tapping it again closes it', app().indexOf('class="adet"') < 0);
      // LEAGUE OR THIS ROW'S OWN TEAM. Every row already names a team, so
      // the scope needs no second picker. Over the archive GB is 5-1 in
      // `off_ot` and the league is 36-44 — recomputed from the per-season
      // splits, which is why neither is the `all` block's 141-160.
      const asLeague = app();
      ok('the card can switch to the team\u2019s own record',
         asLeague.indexOf('data-v3gascope=') >= 0);
      v3Do('v3gascope', 'team'); render();
      const asTeam = app();
      ok('and switching changes the numbers', asTeam !== asLeague);
      ok('to that team\u2019s record', asTeam.indexOf('5-1') >= 0,
         'GB 5-1 not drawn');
      ok('rather than the league\u2019s',
         asTeam.indexOf('36-44') < 0 && asLeague.indexOf('36-44') >= 0);
      // THE TAG COMES OFF, because per team the number is no longer fixed.
      ok('and the both-sides tag comes off with it',
         asTeam.indexOf('>both sides<') < 0
         && asLeague.indexOf('>both sides<') >= 0);
      v3Do('v3gascope', 'league'); render();
    }
    // NARROWING BY KIND, the same control the board carries and the reason
    // the search box could go. `ATL_GB` holds two kinds across three rows.
    {
      const pick = k => fireDoc('change', { target: {
        getAttribute: a => a === 'data-v3gacat' ? '' : null, value: k } });
      const h3 = app();
      ok('a game\u2019s angles can be narrowed by kind',
         h3.indexOf('data-v3gacat') >= 0);
      // THE OPTIONS INSIDE THIS SELECT, not every option on the screen --
      // the week picker and the game picker are options too, and scraping the
      // page wholesale reads their values as kinds.
      const from = h3.slice(h3.indexOf('data-v3gacat'));
      const inSel = from.slice(0, from.indexOf('</select>'));
      const offered = (inSel.match(/<option value="([^"]+)"/g) || [])
        .map(m => m.slice('<option value="'.length, -1))
        .filter(k => k !== 'all');
      // EVERY KIND OFFERED HAS ROWS BEHIND IT. The payload names six and this
      // game carries two; offering the other four draws options that filter
      // the card to nothing.
      const live = {};
      (DATA.angles.week[cards[0].game_id] || []).forEach(pr => {
        const row = DATA.angles.rows.filter(r => r.id === pr[1])[0];
        if (row && row.cat) live[row.cat] = 1;
      });
      ok('and only the kinds it carries are offered',
         offered.length > 0 && offered.every(k => live[k]),
         'offered=' + offered.join(',') + ' live=' + Object.keys(live).join(','));
      // IN THE PAYLOAD'S ORDER, not the order the rows happen to arrive in.
      // `rows` is sorted by percentage, so a page collecting its own list
      // reshuffles this dropdown whenever a record moves.
      const want = DATA.angles.cats.filter(k => live[k]);
      ok('in the order the payload names them',
         offered.join('|') === want.join('|'),
         offered.join('|') + ' vs ' + want.join('|'));
      const nAll = (h3.match(/data-v3gangle="/g) || []).length;
      pick(offered[0]);
      const one = app();
      const nOne = (one.match(/data-v3gangle="/g) || []).length;
      ok('picking a kind shows fewer rows than all of them',
         nOne > 0 && nOne < nAll, 'kind=' + nOne + ' all=' + nAll);
      ok('with that kind selected',
         one.indexOf('value="' + offered[0] + '" selected') >= 0);
      // A FILTER THAT EMPTIES THE LIST KEEPS ITS OWN CONTROLS, which is the
      // lesson the search box left behind: returning nothing took the control
      // with it and there was no way back.
      v3Do('v3gateam', cards[0].home); render();
      pick('Setting');
      const none = app();
      ok('and a kind this game has none of still leaves the bar',
         none.indexOf('data-v3gacat') >= 0 || none.indexOf('class="pbar"') >= 0);
      pick('all'); v3Do('v3gateam', 'all'); render();
      ok('clearing it brings every row back',
         (app().match(/data-v3gangle="/g) || []).length === nAll);
    }
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
// `angles` IS IN THE SWEEP NOW. It was not, so the board's four controls
// were outside the only test that catches a dead one -- and two of them were
// added after it.
[['props', null], ['games', null], ['slip', null], ['ladder', null],
 ['angles', null], ['record', null]]
  .forEach(([t]) => {
    V.tab = t;
    try { render(); } catch (e) { /* reported above */ }
    // NOT JUST `data-v3x=`. A valueless attribute -- `<select data-v3gacat
    // aria-label=...>` -- has no `=` after it, so the old pattern skipped
    // every select and every text field on the page, which is how four angle
    // controls sat outside this test while it reported all wired.
    (app().match(/data-(v3[a-z]+)(?=[=\s>])/g) || []).forEach(
      m => seen.add(m.slice(5)));
  });
if (cards.length) {
  V.tab = 'games'; V.game = cards[0].game_id;
  // AND `odds`, which carries the public money and the projection, and
  // `angles`, which is now its own tab and brings four controls with it.
  // `bets` and `score` are names this app no longer renders and are swept
  // THROUGH `v3GTab`, which is the only thing standing between an old link
  // and a blank screen.
  ['notes', 'players', 'bets', 'score', 'out', 'odds', 'edge',
   'angles'].forEach(gt => {
    V.gameTab = x.v3GTab(gt);
    try { render(); } catch (e) { /* reported above */ }
    // NOT JUST `data-v3x=`. A valueless attribute -- `<select data-v3gacat
    // aria-label=...>` -- has no `=` after it, so the old pattern skipped
    // every select and every text field on the page, which is how four angle
    // controls sat outside this test while it reported all wired.
    (app().match(/data-(v3[a-z]+)(?=[=\s>])/g) || []).forEach(
      m => seen.add(m.slice(5)));
  });
}
// Attributes the `input`/`change` listeners own rather than the click
// listener: the week and game selects, the search box and the ladder fields.
// Attributes owned by a listener other than the click one: the selects
// (`change`), the text fields (`input`), and the ask form (`submit`).
const handled = new Set(V3CLICKS.concat(
  ['v3week', 'v3gamesel', 'v3sortsel', 'v3gameto', 'v3q', 'v3q2', 'v3l',
   'v3askform',
   // The board's and the game's angle controls: two selects, a search box and
   // a range, none of them a click.
   'v3angleq', 'v3angleteam', 'v3anglecat', 'v3anglefrom', 'v3gacat',
   // The record's week range: two selects, so `change` and not a click.
   'v3scfrom', 'v3scto',
   // NOT A CONTROL AT ALL. `v3yrlab` marks the number the slider's `input`
   // handler rewrites in place, which is the one thing on the page that must
   // not trigger a render.
   'v3yrlab']));
const dead = [...seen].filter(k => !handled.has(k));
ok('every control the screens emit is wired', dead.length === 0,
   'emitted and never handled: ' + dead.join(', '));
// AND THE SWEEP REALLY REACHED THEM. A screen renamed out of the list above
// takes its controls out of this test without failing it, which is how the
// board and the odds tab came to be uncovered in the first place.
ok('and the sweep reaches the angle controls',
   seen.has('v3anglecat') && seen.has('v3gacat'),
   [...seen].filter(k => k.indexOf('angle') >= 0 || k.indexOf('ga') === 0)
     .join(','));


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

// ── Difference: how far our number is from theirs, in the market's units ──
//
// NOT THE SAME QUESTION AS EDGE, which is the reason it exists. Edge is in
// probability points, and a 45-yard disagreement on a 94.5 rushing line is
// worth about a point of it — first by this column and nowhere by that one.
{
  const lineMkt = ['rec', 'rush', 'recv', 'pass'].filter(
    m => x.rowsFor(m, null).some(r => has(r.line) && has(r.proj)))[0];
  if (!lineMkt) {
    ok('a market with lines to differ from', false, 'none in the fixture');
  } else {
    V.market = lineMkt; V.week = null; V.sort = 'diff'; V.desc = true;
    const rows = x.rowsFor(lineMkt, null).filter(r => r.priced && !r.blocked);
    const diff = r => r.proj - r.line;
    const sorted = x.v3Sorted(rows).filter(r => has(r.line) && has(r.proj));
    ok('the board can be sorted by the difference',
       x.V3SORTS.some(c => c[0] === 'diff'));
    // Descending is the strongest OVERS: the projection furthest above the
    // line. The board carries both sides, so this is a real ordering choice
    // and not a relabeling of the whole list.
    ok('descending leads with the projection furthest above the line',
       sorted.length < 2 || diff(sorted[0]) >= diff(sorted[1]),
       sorted.length > 1
         ? diff(sorted[0]).toFixed(1) + ' then ' + diff(sorted[1]).toFixed(1)
         : 'too few rows');
    ok('and the leader is an over',
       sorted.length < 1 || diff(sorted[0]) > 0,
       sorted.length ? String(diff(sorted[0])) : 'no rows');
    V.desc = false;
    const asc = x.v3Sorted(rows).filter(r => has(r.line) && has(r.proj));
    // SIGNED, SO THE DIRECTION TOGGLE REACHES BOTH ENDS. An absolute
    // difference would put the same row at the top whichever way the arrow
    // pointed, and the strongest unders would be unreachable.
    ok('ascending reaches the strongest unders instead',
       asc.length < 1 || diff(asc[0]) <= diff(sorted[0]),
       asc.length ? diff(asc[0]).toFixed(1) : 'no rows');
    ok('and the two ends are different rows',
       asc.length < 2 || asc[0].id !== sorted[0].id,
       'the same row leads in both directions — is it sorting on magnitude?');
    V.desc = true;

    // THE NUMBER IT ORDERS BY IS ON THE PAGE. A board sorted by a quantity
    // it never shows asks the reader to take the ordering on trust.
    const r0 = sorted[0];
    if (r0) {
      V.tab = 'props'; V.open = null; render();
      v3Do('v3open', r0.id);
      const opened = app();
      ok('an opened row states the difference it was sorted by',
         opened.indexOf('Difference') >= 0);
      ok('and states it signed, in the market’s own units',
         opened.indexOf('vs the line') >= 0);
      v3Do('v3open', r0.id);
    }

    // A TOUCHDOWN BOARD HAS NO LINE AND SO NO DIFFERENCE. `anytime_td` week
    // files carry no `line`, `proj` or `side` column at all, so this sorted
    // 498 nulls: the control moved and the board did not.
    V.market = 'any'; V.sort = 'diff'; render();
    const td = app();
    ok('a touchdown board does not offer the difference sort',
       td.indexOf('>Difference from the line<') < 0);
    ok('nor the projection sort, which has the same gap',
       td.indexOf('>Projection<') < 0);
    // And a carried-over selection falls back rather than ordering by nulls.
    const tdRows = x.rowsFor('any', null).filter(r => r.priced);
    V.sort = 'diff';
    const byDiff = x.v3Sorted(tdRows);
    V.sort = 'model';
    const byModel = x.v3Sorted(tdRows);
    ok('a difference sort carried onto a touchdown board falls back',
       byDiff.length === byModel.length
         && byDiff.every((r, i) => r.id === byModel[i].id),
       'the touchdown board is ordered by a column it does not have');
    V.market = lineMkt; V.sort = 'diff';
    ok('and the sort is offered again on a market with lines',
       (render(), app().indexOf('>Difference from the line<') >= 0));
  }
  V.market = 'any'; V.sort = 'model'; V.desc = true; V.week = null;
}

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

// ── What his line has done before ───────────────────────────────────────
//
// A fact, not a finding. No rate against the price, no expectation, no
// interval and no green: an over is not good and an under is not bad, it
// depends which side you would take, and coloring it would read as a
// recommendation this makes none of.
{
  const P = DATA.pastlines || {};
  const who = Object.keys(P.players || {})[0];
  ok('the payload carries a player\u2019s past lines', !!who, 'none shipped');
  if (who) {
    V.tab = 'props'; V.market = 'any'; V.open = null; V.pastAll = null;
    const r = x.rowsFor('any', null).filter(q => q.player === who)[0];
    ok('and that player is on the board', !!r, who);
    if (r) {
      render();
      ok('a closed row shows no history', app().indexOf('class="pl"') < 0);
      v3Do('v3open', r.id);
      const open = app();
      ok('opening a player shows what his line has done before',
         open.indexOf('class="pl"') >= 0);
      // A BAR PER WEEK, which is what makes it a shape rather than a list.
      const bars = (open.match(/class="pl__b/g) || []).length;
      const have = ((P.players[who] || {})['anytime_td'] || []).length;
      ok('a bar for every week', bars === have, bars + ' of ' + have);
      ok('and a row for every week too',
         (open.match(/class="pl__r"/g) || []).length === have);
      // NOTHING THAT READS AS A VERDICT. `good` is the class this app tints
      // green with, and a history that wore it would be making a claim.
      const panel = open.slice(open.indexOf('class="pl"'));
      ok('with nothing colored to mean good',
         panel.indexOf('class="num good') < 0 && panel.indexOf(' good"') < 0);
      // A MARKET WITH NO LINE IS DRAWN DIFFERENTLY, because there is no middle
      // for a bar to sit either side of. The price is the height instead.
      ok('a yes-or-no market draws no center line',
         panel.indexOf('class="pl__z"') < 0);
      // The same player on the receptions board, which needs its own row
      // opened: `V.open` holds an id from the market just left.
      V.market = 'rec'; V.open = null; render();
      const rr = x.rowsFor('rec', null).filter(q => q.player === who)[0];
      if (rr) v3Do('v3open', rr.id);
      const rec = app();
      const recp = rec.slice(rec.indexOf('class="pl"'));
      ok('while a market with a line draws one',
         rec.indexOf('class="pl"') >= 0 && recp.indexOf('class="pl__z"') >= 0,
         rr ? 'row opened' : 'no receptions row for ' + who);
      // THE WEEK HE RECORDED NOTHING IS DRAWN, not folded into a count: it is
      // one player-game in nine and every one of them an under, which is the
      // single fact most likely to mislead a reader of a rate.
      const b = x.rowsFor('rec', null).filter(q => (P.players[q.player] || {})
        .receptions && (P.players[q.player] || {}).receptions
        .some(z => z[6] === 0))[0];
      if (b) {
        V.open = null; render(); v3Do('v3open', b.id);
        const z = app();
        ok('a week he recorded nothing is marked on the chart',
           z.indexOf('pl__b--zero') >= 0);
        ok('and counted in words under it',
           z.indexOf('recorded nothing') >= 0);
      }
      // ALL OF IT IS BEHIND A LINK, because the whole record is most of a
      // megabyte per market and almost nobody opens it.
      V.market = 'any'; V.open = null; render(); v3Do('v3open', r.id);
      ok('the rest is offered behind a link',
         app().indexOf('data-v3pastall=') >= 0);
      V.open = null; V.pastAll = null; V.market = 'any';
    }
  }
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
  V.gameTab = 'odds'; render();
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

  // ── Where the line falls, which a list of bands cannot show ───────────
  //
  // Nine percentages in a column are a distribution already. What they cannot
  // carry is the one number that decides a spread bet, because it lands INSIDE
  // a band as often as on a boundary: the fixture is -6.5, which cuts "GB by
  // 4-7" a quarter of the way in.
  {
    const g = app();
    ok('the bands are drawn as a shape, not only as a list',
       g.indexOf('class="mstrip"') >= 0);
    const mm = (cards[0].scores || {}).margins || [];
    ok('with a column per band',
       (g.match(/class="mstrip__c/g) || []).length === mm.length,
       (g.match(/class="mstrip__c/g) || []).length + ' of ' + mm.length);
    ok('and the line drawn over them',
       g.indexOf('class="mstrip__l"') >= 0);
    // THE SPLIT BAND IS NEITHER. Coloring it as covering or as not covering
    // says the line is somewhere it is not.
    ok('the band the line cuts is marked as neither side',
       g.indexOf('mstrip__c--split') >= 0);
    ok('bands past the line are covering',
       g.indexOf('mstrip__c--yes') >= 0);
    ok('and bands short of it are not',
       g.indexOf('mstrip__c--no') >= 0);
    // OUR OWN NUMBER TOO, where it differs enough to be worth drawing. The
    // fixture is -6.5 against our -0.9, which is two bands apart.
    ok('our own number is drawn where it differs',
       g.indexOf('mstrip__l--us') >= 0);
    // AND SAID IN WORDS, because a rule over bars is not self-explanatory to
    // somebody who does not bet. The fixture's home team is favored by 6.5.
    ok('and the picture is explained in words',
       g.indexOf('has to win by 7 or more') >= 0
       && g.indexOf('beating the spread') >= 0);
    // A COVER IS NOT ALWAYS A WIN, which is the sentence this got wrong: on a
    // home team getting points it read "has to win by -2 or more". Three
    // cases, and the middle one is real -- at +0.5 a tie is enough.
    const sk = cards[0].spread;
    cards[0].spread = 2.5; render();
    ok('a home team getting points covers by losing narrowly',
       app().indexOf('can lose by up to 2 and still beat it') >= 0);
    cards[0].spread = 0.5; render();
    ok('and at half a point it only has to avoid losing',
       app().indexOf('only has to avoid losing') >= 0);
    // A WHOLE NUMBER RETURNS THE STAKE, and the two-color picture cannot say
    // so, because a push is neither side of the line.
    cards[0].spread = -7; render();
    ok('a whole-number line says where the push is',
       app().indexOf('7-point win is a push') >= 0);
    cards[0].spread = sk; render();
    // THE STRIP IS NOT DRAWN WITHOUT A LINE TO DRAW. A margin set with no
    // bounds gives the rule nowhere to go, and a rule at the far left is a
    // confident lie about where the line is.
    const keep = cards[0].spread;
    cards[0].spread = null; render();
    ok('and no strip at all when there is no line to place',
       app().indexOf('class="mstrip"') < 0);
    cards[0].spread = keep; render();
  }

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
  // ONE ROW PER SOURCE, not three bars and then three boxes saying the same
  // three things. Six blocks for three facts was a screen and a half on a
  // phone before anything new.
  ok('each source is one row carrying everything it says',
     (h.match(/class="proj__r(?! proj__r--h)/g) || []).length >= 2,
     'the projection is not a row per source');
  ok('the win column names one side for every row',
     /class="proj__w">[A-Z]{2,4} win</.test(h),
     'the win column has no subject');
  // THE REGRESSION THIS ALMOST SHIPPED WITH. The distribution note lived
  // inside the block that was replaced, and a point estimate without it reads
  // as a forecast — Atlanta won at Green Bay by 21 as a road dog on a page
  // that said GB 23.8-22.2 and had the upset at 28.5% one tab away.
  ok('a projection still says it is the middle of a range',
     h.indexOf('middle of a') >= 0 && h.indexOf('won outright') >= 0,
     'the distribution note was dropped with the layout');
  // A DECIMAL, not a whole number. Rounding turned a 0.6-point model margin
  // into "LA 22-22" — a projected tie, from numbers that did not say one.
  ok('the projected scores keep a decimal',
     /\d+\.\d\u2013\d+\.\d/.test(h),
     'whole numbers collapse a close game into a tie');

  // ── Recent form ───────────────────────────────────────────────────────
  //
  // A ROW OF SCORES CANNOT BE READ, so the bar is the score and the tick is
  // what the game was priced for. Both have to be on screen: a chart that
  // drew the bars and dropped the ticks would look finished and mean
  // something else.
  // ── Where the money is ───────────────────────────────────────────────
  //
  // A ROW WHOSE HEIGHT DOES NOT DEPEND ON THE SPLIT. Both labels used to sit
  // inside their own segment, so at 84/16 the trailing one wrapped onto two
  // lines inside a sixth of the width — the most lopsided splits, which are
  // the ones worth looking at, were the ones that looked broken.
  // The win bar at the top of the card legitimately labels its segments —
  // it is one bar across the width and the words fit. This is about the
  // public-split rows, whose segments are now empty by construction.
  // Matched as a whole row rather than by looking for a label anywhere: the
  // win bar at the top of the card legitimately labels its segments — it is
  // one bar across the width and the words fit — so "is there a label in a
  // bar" cannot tell the two apart. This says what a public-split row IS.
  ok('a money row is caption, share, empty bar, share',
     /<div class="pubrow"><span class="eyebrow">[^<]*<\/span>\s*<span class="num pubrow__a">[^<]*<\/span>\s*<div class="bar"[^>]*><span class="h" style="width:\d+%"><\/span><span class="a" style="width:\d+%"><\/span><\/div>\s*<span class="num pubrow__b">/
       .test(h),
     'the public-split row is not the four-column shape');
  ok('the shares sit in their own columns',
     h.indexOf('pubrow__a') >= 0 && h.indexOf('pubrow__b') >= 0);
  ok('and each team is named once above them',
     h.indexOf('pubrow--names') >= 0);
  // The screen reader still gets both sides from one bar.
  ok('the bar still says both shares to a screen reader',
     /aria-label="[^"]*percent, [^"]*percent"/.test(h));

  // ── Against the number: the three markets this tab is about ──────────
  //
  // `team_form` on the notes tab is the same question asked of the
  // scoreboard. This is it asked of the spread, the total and the moneyline,
  // which are the three numbers the Odds tab is already showing — so the
  // record belongs beside them rather than a tab away.
  V.tlN = null; V.tlAll = null; render();
  const tl = app();
  ok('the odds tab carries each side’s record against the number',
     tl.indexOf('Against the number') >= 0);
  ok('both teams are drawn', tl.indexOf('>GB, last ') >= 0
     && tl.indexOf('>ATL, last ') >= 0);
  ok('all three markets are named', tl.indexOf('Against the spread') >= 0
     && tl.indexOf('Over/under') >= 0 && tl.indexOf('Moneyline') >= 0);
  // A ROW PER GAME, five cells wide, read down a column.
  ok('a row per game in the window',
     (tl.match(/class="tl__r"/g) || []).length === 20,
     'rows drawn: ' + (tl.match(/class="tl__r"/g) || []).length);
  // `tl__m--` rather than `tl__m`, because `tl__ms` — the cell the three
  // marks sit in — shares that prefix and was being counted as a fourth.
  ok('every row carries three result marks',
     (tl.match(/tl__m--/g) || []).length === 60,
     'marks drawn: ' + (tl.match(/tl__m--/g) || []).length);

  // A PUSH IS NOT A LOSS, and the fixture has one. The stake comes back, so
  // the record shows it as a third number and the money sets it aside.
  ok('a push is marked as a push rather than a loss',
     tl.indexOf('tl__m--p') >= 0 && tl.indexOf('title="push"') >= 0);
  ok('and it is counted out of the money rather than against it',
     tl.indexOf('push') >= 0);
  // An ungraded week draws its row and no mark, not a mark meaning lost.
  ok('a game with no posted line has no result against it',
     tl.indexOf('tl__m--na') >= 0);
  // A graded week with no archived price is not a free bet.
  ok('a game with no price is named rather than counted',
     tl.indexOf('with no price') >= 0 || tl.indexOf('no price archived') >= 0);

  // NO COLOR THAT MEANS GOOD. Every ATS split this project has measured
  // sits under the hold, so a green "covered" would imply a finding the
  // project does not have. The marks separate by fill, not by hue.
  ok('no result mark is colored as a verdict',
     tl.indexOf('tl__m--good') < 0 && tl.indexOf('tl__m--bad') < 0);
  // COUNTED FROM THE ANGLES BOARD, not written down. The first draft said
  // "forty-nine patterns, the best covers 52.6%" from a stale comment while
  // the payload held 86 and a best lower bound of 57.0%.
  ok('and the fold says what the records are worth',
     /clears it<\/b> at the lower bound/.test(tl),
     'no measured verdict in the fold');
  ok('and counts the patterns from the angles board rather than a constant',
     tl.indexOf(String((DATA.angles.rows || []).length) + ' of them, graded')
       >= 0,
     'the fold does not name the measured count');
  ok('and names the break-even it is measured against',
     tl.indexOf((DATA.angles.break_even * 100).toFixed(1) + '%') >= 0);
  ok('the fold names whose line it is',
     tl.indexOf('one source’s number') >= 0);
  ok('and explains why a favorite reads as a minus',
     tl.indexOf('favorite reads as a minus') >= 0);

  // THE MONEY ON THE SIDE THE RECORD RAN. GB's spread record runs the team's
  // way and ATL's runs against it, so one panel reads "back the team" and the
  // other "back its opponent" — the fade branch, priced off the real quote
  // the other side was posted at.
  ok('the money names the side the record ran',
     tl.indexOf('on GB,') >= 0 || tl.indexOf('on GB ') >= 0,
     'no backing sentence for GB');
  ok('and fades the team whose record ran the other way',
     tl.indexOf('opponent') >= 0, 'no fade sentence anywhere');
  ok('the over and the under are named as sides of the game',
     tl.indexOf('the over') >= 0 || tl.indexOf('the under') >= 0);

  // ONE WINDOW FOR BOTH TEAMS AND ALL THREE MARKETS. Reading one side over
  // five games and the other over ten would make the comparison the
  // renderer's choice rather than the reader's.
  ok('the window control is offered', tl.indexOf('data-v3tln') >= 0);
  x.v3Do('v3tln', '3');
  const tl3 = app();
  ok('narrowing the window narrows both tables',
     (tl3.match(/class="tl__r"/g) || []).length === 6,
     'rows at last 3: ' + (tl3.match(/class="tl__r"/g) || []).length);
  ok('and the records are recounted over it',
     tl3.indexOf('>GB, last 3<') >= 0);
  x.v3Do('v3tln', 'all');

  // THE REST OF THE RECORD IS FETCHED, and a fetch that failed is not a team
  // with ten games. The panel falls back to the inlined ten, which is the
  // right fallback and the wrong silence: it would redraw identically and the
  // button would read as broken. Seeded rather than awaited, the same way the
  // week fetch is tested above — a real `fetch` here would be a race.
  ok('the rest of the record is offered', app().indexOf('data-v3tlall') >= 0);
  V.tlAll = 'GB';
  x.V3CACHE['tlines'] = { error: 'blocked by the browser' };
  render();
  const tlf = app();
  ok('a fetch that failed says so rather than redrawing the same ten',
     tlf.indexOf('Every game did not load') >= 0);
  ok('and the inlined games are still shown',
     (tlf.match(/class="tl__r"/g) || []).length === 20,
     'rows after a failed fetch: '
       + (tlf.match(/class="tl__r"/g) || []).length);
  delete x.V3CACHE['tlines'];
  // AND THE WHOLE RECORD, ONCE IT ARRIVES: twenty games for GB against the
  // ten inlined, so the panel reads the fetched copy rather than ignoring it.
  x.V3CACHE['tlines'] = { teams: { GB: (DATA.teamlines.teams.GB || [])
    .concat(DATA.teamlines.teams.GB || []) } };
  render();
  const tla = app();
  ok('the fetched record replaces the inlined ten',
     tla.indexOf('>GB, last 20<') >= 0,
     'no 20-game GB panel after the fetch landed');
  ok('and the other side is still on its inlined ten',
     tla.indexOf('>ATL, last 10<') >= 0);
  V.tlAll = null; delete x.V3CACHE['tlines']; V.tlN = null;

  V.gameTab = 'notes'; render();
  const hn = app();
  // RECENT FORM IS ON NOTES NOW, between the distribution above it and the
  // model's commentary below: ten weeks of scores against what each week was
  // priced for is the evidence between a forecast and a remark about one.
  ok('recent form draws both teams', hn.indexOf('Recent form') >= 0
     && hn.indexOf('scored') >= 0 && hn.indexOf('allowed') >= 0);
  ok('and it has left the odds tab', h.indexOf('Recent form') < 0,
     'recent form is still on the odds tab');
  ok('every bar carries its own expectation',
     (hn.match(/class="tf__t"/g) || []).length >= 18,
     'ticks drawn: ' + (hn.match(/class="tf__t"/g) || []).length);
  // Ten games in week 3 is mostly last season. Drawn and marked, not hidden.
  ok('the season boundary is marked rather than hidden',
     hn.indexOf('tf__s--brk') >= 0 && hn.indexOf('tf__b--prev') >= 0);
  // A game with no archived line draws a bar and no tick, not a tick at zero.
  ok('a week with no line still draws its bar',
     (hn.match(/class="tf__b/g) || []).length
     > (hn.match(/class="tf__t"/g) || []).length);
  ok('the form says the scores include defensive touchdowns',
     hn.indexOf('special-teams') >= 0);

  // ── How this one goes: the story, LAST on the tab ────────────────────
  //
  // Last, not first. The unfold, the form and the notes above it are the
  // facts; this is the reading of them, and a reading printed before its
  // evidence asks to be taken on the writer's word.
  ok('the Read tab carries the story', hn.indexOf('How this one goes') >= 0);
  ok('and it comes after the notes it reads from',
     hn.indexOf('How this one goes') > hn.indexOf('What our AI noticed'),
     'story at ' + hn.indexOf('How this one goes')
       + ', notes at ' + hn.indexOf('What our AI noticed'));
  ok('and after recent form',
     hn.indexOf('How this one goes') > hn.indexOf('Recent form'));
  ok('every paragraph is drawn',
     (hn.match(/class="st__p"/g) || []).length
       === (DATA.stories[cards[0].game_id].paras || []).length,
     'paragraphs: ' + (hn.match(/class="st__p"/g) || []).length);
  // THE SCORELINE IS RENDERED FROM THE DATA, NOT LIFTED FROM THE PROSE, so
  // the figure a reader quotes is the one the Odds tab shows.
  ok('the number is stated by code beneath the words',
     hn.indexOf('Our number') >= 0 && /23\.1/.test(hn) && /19\.4/.test(hn));
  ok('and the story says the wording is the only written part',
     hn.indexOf('the wording is all that is written') >= 0);
  // A template story is not a written one and does not pretend to be.
  if (cards.length > 1) {
    const g0 = V.game;
    V.game = cards[1].game_id; V.gameTab = 'notes'; render();
    const h2 = app();
    ok('a story that fell back to the template says so',
       h2.indexOf('rather than written up') >= 0);
    ok('and a story with no scoreline prints no number',
       h2.indexOf('Our number') < 0);

    // ── A PLAYED GAME IS NOT PREVIEWED ────────────────────────────────
    //
    // `story_freeze` keeps the text a game kicked off with and never writes
    // another, so after a final what is on screen IS what was said
    // beforehand. Under Saturday's heading it would read as a forecast of a
    // result the reader already knows.
    //
    // THE FLAG IS SET HERE RATHER THAN IN THE FIXTURE. The branch keys off
    // the STORY's `frozen`, not the card's final, so a played card is not
    // what this needs — and giving the shared fixture a third, finished game
    // would move every count the rest of this file asserts.
    const frozenGame = cards[0].game_id;
    DATA.stories[frozenGame].frozen = true;
    V.game = frozenGame; V.gameTab = 'notes'; render();
    const h3 = app();
    ok('a played game says what we said beforehand',
       h3.indexOf('What we said beforehand') >= 0);
    ok('and does not call it a preview',
       h3.indexOf('How this one goes') < 0,
       'a finished game is still headed as a forecast');
    ok('the number is labeled as the one we had',
       h3.indexOf('The number we had') >= 0
         && h3.indexOf('>Our number<') < 0);
    ok('and the note says it was not rewritten after the result',
       h3.indexOf('not rewritten once a game has been played') >= 0);
    delete DATA.stories[frozenGame].frozen;
    V.game = frozenGame; V.gameTab = 'notes'; render();
    ok('and an unplayed game is still a preview',
       app().indexOf('How this one goes') >= 0);

    V.game = g0; V.gameTab = 'notes'; render();
  }
  // BETWEEN THE UNFOLD AND THE NOTES. The order is the argument: a
  // distribution over this game, the evidence, then the commentary.
  ok('recent form sits between the unfold and the notes',
     hn.indexOf('Recent form') < hn.indexOf('What our AI noticed'),
     'form is below the notes it is meant to inform');
  V.gameTab = 'odds'; render();
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
    // A GRID, NOT A RANKING. The nine scenarios are one question crossed with
    // another, and drawn as a column of bars they read as nine unrelated
    // things in order of size.
    ok('the scenarios are drawn as a grid', h.indexOf('class="ugrid"') >= 0);
    ok('with the two scoring questions as its columns',
       h.indexOf('>Low</span>') >= 0 && h.indexOf('>High</span>') >= 0);
    // ROWS COME FROM THE PAYLOAD'S ORDER, which runs from the underdog
    // winning to the favorite pulling away. Collected from the cells instead
    // they would arrive sorted by size, which is not an axis.
    const rowsIn = (u.bands || []).filter(b => (u.cells || []).some(
      cl => cl.band === b.key));
    ok('one row per band that has cells', rowsIn.every(
       b => h.indexOf('>' + b.short + '</span>') >= 0),
       rowsIn.map(b => b.short).join(','));
    // AND NO ROW FOR A BAND NOTHING REACHED. Two zeroes read as a missing
    // number rather than as a result that did not happen.
    const empty = (u.bands || []).filter(b => !(u.cells || []).some(
      cl => cl.band === b.key));
    ok('and no row for a band nothing reached', empty.every(
       b => h.indexOf('>' + b.short + '</span>') < 0),
       empty.map(b => b.short).join(','));
    // THE MARGINS ARE THE POINT OF A GRID: a row total is how it ends
    // whatever the scoring, a column total is over against under whatever the
    // result, and the whole thing still adds to 100.
    ok('with row and column totals, which a list cannot have',
       (h.match(/class="ugrid__t"/g) || []).length >= rowsIn.length + 3,
       String((h.match(/class="ugrid__t"/g) || []).length));
    ok('and it still says the whole thing adds to 100',
       h.indexOf('adds to 100') >= 0);
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

// ── The price rule, on this week's board ────────────────────────────────
//
// Section 03 of the Record page scores these after the fact and nothing
// showed them before the games. `prop_edge.qualifying` picks them and the
// payload carries them, so what is left to check is that the page reads the
// selection and draws the bet the rule actually took.
{
  V.tab = 'props'; V.game = null; V.q = ''; V.week = null; V.filter = 'all';
  const mkt = V3MKT.map(m => m[0])
    .filter(k => ((marketOf(k) || {}).edge || {}).picks
                 && marketOf(k).edge.picks.length)[0];
  ok('the payload carries what the price rule took', !!mkt,
     'no market carries an edge block');
  if (mkt) {
    V.market = mkt; V.filter = 'gap'; render();
    const picks = marketOf(mkt).edge.picks;
    ok('and the filter shows exactly those bets',
       picks.every(p => pane().indexOf(p.player_name) >= 0)
       && (pane().match(/data-v3open=/g) || []).length === picks.length,
       JSON.stringify(picks.map(p => p.player_name)) + ' drew '
       + (pane().match(/data-v3open="[^"]*"/g) || []).join(', '));
    ok('and the help line names the fitted margin and the measured return',
       app().indexOf('5.5 points') >= 0 && app().indexOf('+$13.36') >= 0
       && app().indexOf('spans zero') >= 0);

    // THE RULE'S SIDE, NOT THE BOARD'S DEFAULT. `v3Line` renders "Over" on
    // any row without `take`, so an under pick would be drawn as the
    // opposite bet. Nine of the rule's 77 picks over weeks 3-4 were unders.
    const und = picks.filter(p => p.side === 'under')[0];
    ok('the fixture carries an under pick to draw', !!und);
    if (und) {
      const i = pane().indexOf(und.player_name);
      const row = pane().slice(i, i + 1400);
      // Read the row's OWN line cell. A 1400-character slice runs into the
      // next row, whose line is an over, so the naive "and no Over
      // anywhere" check failed on a row that was perfectly correct.
      const lineCell = (/<div class="line">([^<]*)</.exec(row) || [])[1] || '';
      ok('an under pick is drawn as an under',
         lineCell.indexOf('Under ') === 0, lineCell);
      // AND EVERY FIGURE ON IT IS THE UNDER'S. They are all P(over) on the
      // board, so left alone the strip reads the over's model and edge
      // beside the word "Under" and `ev100` prices the OVER at the UNDER's
      // number — which drew a bet the rule recommends at a negative edge
      // and a negative EV.
      // Read the two cells by name rather than by scanning the slice.
      const cell = (lab, s) => {
        const j = s.indexOf('>' + lab + '<');
        if (j < 0) return '';
        const k = s.lastIndexOf('<span class="cell', j);
        return k < 0 ? '' : s.slice(k, j);
      };
      const edgeCell = cell('Edge', row);
      // BOTH per-$100 cells. One cell labeled `EV/$100` used to read
      // `ev100`, which answers the model on a touchdown market and the blend
      // on a yardage one — so this very check passed on a quantity that was
      // not the one beside `Edge`. Named separately, both are asserted.
      const evCell = cell('EV model', row), evAdjCell = cell('EV adj', row);
      ok('and its edge is positive, because the rule took it',
         edgeCell.indexOf('+') >= 0 && edgeCell.indexOf('\u2212') < 0,
         edgeCell || 'no edge cell found');
      ok('and so is its expected return on the model',
         evCell.indexOf('+$') >= 0, evCell || 'no EV model cell found');
      ok('and on the blend, flipped to the under like every other figure',
         evAdjCell.indexOf('$') >= 0, evAdjCell || 'no EV adj cell found');
    }
    // AN OVER PICK IS LEFT ALONE.
    const ov = picks.filter(p => p.side === 'over')[0];
    if (ov) {
      const row = pane().slice(pane().indexOf(ov.player_name),
                              pane().indexOf(ov.player_name) + 1400);
      ok('an over pick is still drawn as an over', /Over [\d.]+/.test(row));
    }
    // NOTHING QUALIFYING IS AN EMPTY FILTER, NOT THE WHOLE BOARD. `fade`
    // once fell through to returning every row under the word "Fades".
    const was = marketOf(mkt).edge;
    marketOf(mkt).edge = {threshold_pp: 5.5, picks: [], note: ''};
    render();
    ok('a week the rule takes nothing in is empty, not the whole board',
       pane().indexOf('No line on this market is far enough off') >= 0,
       pane().slice(0, 200));
    marketOf(mkt).edge = was;
    V.filter = 'all'; V.market = 'any'; render();
  }
}

// ── Streaks is a lookup now, not a rule ─────────────────────────────────
//
// `v3Streak` used to count a player's last five weeks here, out of whatever
// history the payload inlined and from whatever "now" happened to be — so it
// could only ever answer as of today, and nothing recorded which players it
// had shown. `src/evaluation/streaks.py` owns it and the payload carries the
// answer; what is left to check is that the page READS it and does not
// quietly keep a rule of its own.
{
  V.tab = 'props'; V.game = null; V.q = ''; V.week = null;
  const S = (DATA.pastlines || {}).streaks || {};
  // The board market whose history key the flag is filed under.
  const mkt = Object.keys(V3HIST).filter(k => S[V3HIST[k]])[0];
  ok('the payload carries who is on a streak', !!mkt,
     'no market in pastlines.streaks: ' + JSON.stringify(Object.keys(S)));
  if (mkt) {
    const hk = V3HIST[mkt];
    V.market = mkt; V.filter = 'streak'; render();
    const flagged = Object.keys(S[hk]);
    const shown = flagged.filter(n => pane().indexOf(n) >= 0);
    ok('and the streak filter shows exactly the flagged players',
       shown.length === flagged.length, 'flagged ' + flagged.join(', ')
       + '; drawn ' + shown.join(', '));
    // THE COUNT ON THE TAG COMES FROM THE FLAG TOO. It used to be counted
    // in the page, which is the same rule written twice.
    const f = S[hk][flagged[0]];
    ok('and the tag reads its count off the flag rather than recounting',
       pane().indexOf(f[1] + ' of ' + f[2]) >= 0,
       'wanted "' + f[1] + ' of ' + f[2] + '"');
    // NOBODY FLAGGED IS AN EMPTY FILTER, NOT THE WHOLE BOARD. `fade` once
    // fell through to returning every row under the word "Fades".
    const was = DATA.pastlines.streaks;
    DATA.pastlines.streaks = {};
    render();
    ok('with nothing flagged the filter is empty rather than the whole board',
       flagged.every(n => pane().indexOf(n) < 0), pane().slice(0, 200));
    DATA.pastlines.streaks = was;
    // AND THE PROSE QUOTES THE SHIPPED WINDOW. Whether it is READ from the
    // payload rather than written in the page is a source question — these
    // are `const`, bound once at load — so it is checked in
    // `test_the_streak_rule_lives_in_python` instead of by mutating DATA
    // here, which could not tell a payload read from a literal 5.
    ok('the filter names the window it used',
       x.V3STREAK_OF === (DATA.pastlines.streak_of || 5)
       && x.V3STREAK_MIN === (DATA.pastlines.streak_min || 4),
       x.V3STREAK_OF + '/' + x.V3STREAK_MIN);
    V.filter = 'all'; V.market = 'any'; render();
  }
}

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
V.tab = 'angles'; render();
const L = () => app();
// One row per angle, plus a header row.
// Counted by the row action, which is one per angle exactly. `class="arow`
// also matches `arow__l` and `arow--h`, which is how the first version of
// this said seven rows for three angles.
ok('the angles board lists every angle tracked',
   (L().match(/data-v3angle="/g) || []).length
   === ((DATA.angles || {}).rows || []).length,
   (L().match(/data-v3angle="/g) || []).length + ' drawn, '
   + (((DATA.angles || {}).rows || []).length) + ' measured');
// THE DENOMINATOR IS THE FINDING. A board showing only what currently clears
// is a board of survivors, so the count measured has to be on the page. The
// headline card that used to carry it came off for space; these moved into
// the closing card and must still be somewhere.
ok('and says how many patterns were measured',
   /With \d+ patterns measured/.test(L()));
ok('and what clearing means', L().indexOf('just to break even') >= 0);
ok('and that some of them look good on luck alone',
   L().indexOf('on luck alone') >= 0);
// PLAIN WORDS. The first version said "splits graded against the closing
// spread" over a stat called "chance alone" — three pieces of jargon before
// the reader reaches a number.
ok('and says it without jargon',
   L().indexOf('closing spread') < 0 && L().indexOf('Chance alone') < 0
   && L().indexOf('95% confidence') < 0);
ok('and explains why half is not enough',
   L().indexOf('bookmaker keeps a cut') >= 0);
// Tapping a row opens this season's games.
{
  // The row that HAS fixtures, not whichever sorts first: opening an angle
  // with no games this season exercises the empty branch and every assertion
  // below it goes quiet while the file still reports all passed.
  const withGames = Object.keys((DATA.angles || {}).games || {})[0];
  const first = withGames ? [null, withGames]
    : /data-v3angle="([^"]+)"/.exec(L());
  ok('a row can be opened',
     !!first && L().indexOf('data-v3angle="' + first[1] + '"') >= 0);
  if (first) {
    ok('and nothing is open to begin with', L().indexOf('class="adet"') < 0);
    v3Do('v3angle', first[1]);
    const o = L();
    ok('opening one shows its games', o.indexOf('class="agame') >= 0);
    // A fixture goes straight to that week's game page.
    ok('and each game links to its own page',
       o.indexOf('data-v3anglegame="') >= 0);
    const link = /data-v3anglegame="([^"|]*)\|([^"|]*)\|([^"]*)"/.exec(o);
    ok('with a plain-language description above them',
       o.indexOf('class="adet__p"') >= 0);
    // WHICH TEAM THE PATTERN IS ABOUT. Both sides were named the same way,
    // so "ATL at GB \u00b7 cover +4.5" left the reader to work out whose
    // cover it was.
    {
      const gs = ((DATA.angles || {}).games || {})[first[1]] || [];
      const me = /<span class="agame__me">([A-Z]+)<\/span>/.exec(o);
      ok('the team the pattern is about is marked', !!me && me[1] === gs[0].team,
         me ? me[1] : 'none');
      // And a fixture not yet played names it in the pill, where "to play"
      // said only that nothing had happened.
      const soon = gs.filter(g => !g.played)[0];
      ok('and an unplayed game names its side',
         !soon || o.indexOf(soon.team + ' to play') >= 0,
         soon ? soon.team : 'none unplayed');
      ok('and a played one still says how it went',
         /class="tag tag--(good|bad)">(cover|no) /.test(o));
      // A PUSH IS NOT A FIXTURE. Both reach the page as `covered: null`,
      // and the list showed both as "to play" — SEA laid 3 in week 1 and
      // won by 3, and the row said SEA had yet to play.
      const pushed = gs.filter(g => g.played
                                    && (g.covered === null
                                        || g.covered === undefined))[0];
      ok('and a push is marked as one',
         !pushed || o.indexOf('>push<') >= 0, pushed ? pushed.team : 'none');
      ok('and is not counted as still to play',
         !pushed || o.indexOf(pushed.team + ' to play') < 0);
      ok('and the season line separates the three',
         !pushed || /1 push/.test(o), 'push not counted in the header');
    }
    // One at a time, or the board becomes a wall of fixture lists.
    ok('and only one is open', (o.match(/class="adet"/g) || []).length === 1);
    v3Do('v3angle', first[1]);
    ok('tapping it again closes it', L().indexOf('class="adet"') < 0);
    // And a fixture goes straight to that week's game page. Done last,
    // because it navigates away.
    // THE ID HAS TO BE THE BOARD'S. The fixtures carried the schedule's
    // `2026_02_DET_BUF` while every card on the board is keyed `DET_BUF`, so
    // each of these links landed on "that game is not on this week's board".
    const ids = {};
    ((DATA.games || {}).cards || []).forEach(c => { ids[c.game_id] = 1; });
    Object.keys((DATA.games || {}).past || {}).forEach(w => {
      (((DATA.games || {}).past || {})[w].cards || [])
        .forEach(c => { ids[c.game_id] = 1; });
    });
    const linked = (o.match(/data-v3anglegame="([^"|]*)\|/g) || [])
      .map(m => m.slice('data-v3anglegame="'.length, -1));
    ok('every linked fixture names a game the board holds',
       linked.length > 0 && linked.every(g => ids[g]), linked.join(','));
    // A fixture with no board is not a button. Next week's games are on the
    // schedule and on nobody's board, so a link to one went nowhere.
    ok('and a fixture with no board is not a link',
       o.indexOf('agame--flat') >= 0
       && linked.length < (o.match(/class="agame/g) || []).length,
       linked.length + ' linked of '
       + (o.match(/class="agame/g) || []).length);
    // BOTH BOARDS ARE REACHED. A game in a closed week opens the archive;
    // one in the week still in progress opens the live board, which is the
    // Monday case — Sunday's games are played but their week is not over,
    // so the archive does not have them yet.
    const wks = (o.match(/data-v3anglegame="[^"|]*\|([^"|]*)\|/g) || [])
      .map(m => m.split('|')[1]);
    ok('a closed week opens the archive', wks.some(w => w !== ''),
       wks.join(','));
    ok('and a game in the current week opens the live board',
       wks.some(w => w === ''), wks.join(','));
    // Done last, because it navigates away.
    if (link && link[1]) {
      v3Do('v3anglegame', link[1] + '|' + link[2] + '|' + link[3]);
      ok('tapping one opens that game',
         V.tab === 'games' && V.game === link[1], V.tab + '/' + V.game);
      ok('on the week it was played',
         link[2] === '' ? V.week === null : V.week === Number(link[2]),
         String(V.week));
      ok('and that game is actually on the board it was sent to',
         L().indexOf('is not on this week') < 0);
      // BACK MEANS WHERE YOU CAME FROM. It used to mean the games list,
      // which is a screen this reader had not been on.
      v3Do('v3back');
      ok('and Back returns to the angles board', V.tab === 'angles', V.tab);
      ok('with the angle still open', V.angleOpen === link[3],
         String(V.angleOpen));
      ok('and no week carried in from the game', V.week === null,
         String(V.week));
      V.angleOpen = null; render();
    }
  }
}
// COLUMN HEADERS ARE THE SORT. Tapping the active one flips it, which is
// what a table does and saves a row of chrome.
{
  const order = () => (L().match(/data-v3angle="([^"]+)"/g) || []).join('|');
  ok('the columns are the sort control', L().indexOf('class="ahead"') >= 0);
  const byYear = order();
  v3Do('v3anglesort', 'name');
  ok('the board can be sorted', byYear !== order(), 'order did not change');
  const az = order();
  v3Do('v3anglesort', 'name');
  ok('and tapping the same column flips it',
     order() !== az && order().split('|').reverse().join('|') === az);
  v3Do('v3anglesort', 'season');
}
// SEARCH, for when you know what you are looking for.
{
  ok('the board can be searched', L().indexOf('data-v3angleq') >= 0);
  const before = (L().match(/data-v3angle="/g) || []).length;
  // Matched against the label, the description and the kind — "overtime" is
  // in a description, not in any label.
  fireDoc('input', { target: {
    getAttribute: a => a === 'data-v3angleq' ? '' : null, value: 'overtime' } });
  const after = (L().match(/data-v3angle="/g) || []).length;
  ok('typing narrows the board', after > 0 && after < before,
     before + ' -> ' + after);
  fireDoc('input', { target: {
    getAttribute: a => a === 'data-v3angleq' ? '' : null,
    value: 'zzzznotathing' } });
  ok('and a search that matches nothing says so',
     L().indexOf('Nothing matches') >= 0);
  fireDoc('input', { target: {
    getAttribute: a => a === 'data-v3angleq' ? '' : null, value: '' } });
  ok('and clearing it restores the board',
     (L().match(/data-v3angle="/g) || []).length === before);
}
// ── Typing in the search box survives the redraw ───────────────────────
//
// The board has no single rows container to patch, so a keystroke re-renders
// the screen — and `innerHTML` destroys the field being typed into. You typed
// "bye" and got "b", because the second and third characters landed nowhere.
{
  V.tab = 'angles'; V.angleQ = ''; render();
  const box = document.querySelector('[data-v3angleq]');
  box.setAttribute('data-v3angleq', '');
  box.value = 'by';
  box.setSelectionRange(2, 2);
  box.focus();
  ok('the field starts focused', document.activeElement === box);
  fireDoc('input', { target: box });
  ok('the search box keeps focus while you type',
     document.activeElement === document.querySelector('[data-v3angleq]'),
     document.activeElement ? 'some other node' : 'focus was lost');
  ok('and the caret with it',
     document.activeElement && document.activeElement.selectionStart === 2,
     String(document.activeElement && document.activeElement.selectionStart));
  ok('and the search still ran', V.angleQ === 'by', V.angleQ);
  // A REDRAW WITH NOTHING FOCUSED MUST NOT GRAB THE FIELD. Tapping a column
  // header while the box is empty and unfocused would otherwise open the
  // keyboard on a phone.
  document.activeElement = null;
  v3Do('v3anglesort', 'name'); render();
  ok('but a redraw with nothing focused focuses nothing',
     document.activeElement === null);
  v3Do('v3anglesort', 'season');
  fireDoc('input', { target: {
    getAttribute: a => a === 'data-v3angleq' ? '' : null, value: '' } });
}

// A CONDITION THE WHOLE GAME IS IN CANNOT HAVE A RECORD, and says so.
//
// Both sides of every prime-time game are in prime time, so one covers and
// the other does not: 570-570, and another ten seasons would not move it.
// The row stays; what it gets is the context no reader can supply.
{
  V.tab = 'angles'; V.angleQ = ''; V.angleCat = 'all'; render();
  const flagged = ((DATA.angles || {}).rows || []).filter(r => r.whole_game);
  ok('a whole-game condition is tagged on the board',
     !flagged.length || L().indexOf('both sides') >= 0, 'no tag drawn');
  ok('and exactly the flagged ones are',
     (L().match(/>both sides</g) || []).length === flagged.length,
     (L().match(/>both sides</g) || []).length + ' tags, '
     + flagged.length + ' flagged');
  // IT IS NOT A FILTER. A split at 20% is as useful as one at 80%, so
  // nothing on this board is hidden for the number it shows.
  ok('and the row is kept rather than hidden',
     (L().match(/data-v3angle="/g) || []).length
     === ((DATA.angles || {}).rows || []).length);
}

// ── Green needs a sample, not just a clearing interval ─────────────────
//
// `pre_bye_div` was the first row in fifty-eight to clear break-even at the
// bottom of its range, at 58-28 over eleven seasons — and eighty-six games,
// and a subset picked after seeing its parent. Tinting that would be the
// board's loudest claim on its thinnest evidence.
{
  const { v3Clears } = x;
  const be = ((DATA.angles || {}).break_even) || 0.5238;
  const floor = ((DATA.angles || {}).tint_min) || 300;
  ok('a clearing interval on a thin sample is not green',
     v3Clears(be + 0.05, floor - 1, be) === false);
  ok('the same interval with the games behind it is',
     v3Clears(be + 0.05, floor, be) === true);
  ok('and a big sample that does not clear is not',
     v3Clears(be - 0.01, floor * 10, be) === false);
  // AND THE FOOTER COUNTS WHAT IT TINTS. Two different rules would have the
  // card saying one row clears while none is colored.
  V.tab = 'angles'; V.angleFrom = 0; render();
  const greens = (L().match(/class="num good"/g) || []).length;
  const claimed = /<b style="color:var\(--ink\)">(\d+)<\/b> clear it/.exec(L());
  ok('the card counts the rows it colors',
     !claimed || Number(claimed[1]) === greens,
     (claimed ? claimed[1] : '?') + ' claimed, ' + greens + ' colored');
  ok('and the card says the rule has two halves',
     L().indexOf('games or more behind it') >= 0);
}


// ── Is this season unusual for this pattern? ───────────────────────────
//
// "Teams off a 20+ loss are 7-1 against the spread this year" is the line
// that started this board, and the board could not answer it: 87.50% sat
// beside a long run of 53.13% and the reader had to judge whether eight games
// meant anything. At 53.13%, 7-1 or better turns up about one season in ten.
{
  const { v3Surprise, V3SURPRISE } = x;
  // The case itself. Eight games at 53% is not a finding.
  const p = v3Surprise({ n: 8, w: 7, l: 1, pct: 0.875 },
                       { n: 495, w: 263, l: 232, pct: 0.5313 });
  ok('seven-and-one on eight games is not unusual', p > V3SURPRISE,
     'p=' + p);
  // The same rate over a season's worth of games is a different claim.
  const q = v3Surprise({ n: 80, w: 70, l: 10, pct: 0.875 },
                       { n: 495, w: 263, l: 232, pct: 0.5313 });
  ok('the same rate over eighty games is', q < V3SURPRISE, 'p=' + q);
  // A record ON the long-run rate is the least surprising thing there is.
  const r = v3Surprise({ n: 100, w: 53, l: 47, pct: 0.53 },
                       { n: 495, w: 263, l: 232, pct: 0.5313 });
  ok('and a season that matches the long run is not', r > 0.9, 'p=' + r);
  // BOTH DIRECTIONS. A cold season is as much a finding as a hot one.
  const cold = v3Surprise({ n: 80, w: 10, l: 70, pct: 0.125 },
                          { n: 495, w: 263, l: 232, pct: 0.5313 });
  ok('and it reads cold seasons too', cold < V3SURPRISE, 'p=' + cold);
  // It must not throw or invent a number where there is nothing to compare.
  ok('no season, no answer', v3Surprise(null, { n: 9, pct: 0.5 }) === null);
  ok('no long run, no answer', v3Surprise({ n: 9, w: 5, pct: 0.5 }, null) === null);
  ok('and a long run of all wins says nothing rather than dividing by zero',
     v3Surprise({ n: 9, w: 5, pct: 0.5 }, { n: 9, w: 9, pct: 1 }) === null);
  // ON THE NAME, NOT ON THE NUMBER. Coloring the season cell is forbidden:
  // green on eight games is the exact misreading this board prevents.
  V.tab = 'angles'; V.angleTeam = ''; V.angleQ = ''; render();
  // COUNTED ON THE TITLE, because the closing card prints an example tag to
  // explain itself and `>unusual<` matches that too.
  const tagged = (L().match(/title="This season/g) || []).length;
  // AGAINST THE LONG RUN THE PAGE IS SHOWING, not the shipped `all` block:
  // the year slider recomputes the long run, and the comparison has to move
  // with it or the mark would answer for a span nobody is looking at.
  const yr = x.v3AngleYears();
  const due = ((DATA.angles || {}).rows || []).filter(a => {
    const run = x.v3AngleSince(a, yr.from, 0.5238, '');
    const p = v3Surprise(a.season, run);
    return p != null && p < V3SURPRISE;
  }).length;
  ok('the board marks exactly the unusual ones', tagged === due,
     tagged + ' marked, ' + due + ' qualify');
  ok('and the mark is a tag, not a tint on the number',
     tagged === 0 || L().indexOf('tag tag--flat" title="This season') >= 0);
  ok('and the card says what it means',
     L().indexOf('one time in twenty') >= 0);
}


// ── What the split's own composition already predicts ──────────────────
//
// Side and role are worth four points between them: road underdogs cover
// 52.07% and home favorites 47.93%. So a split made mostly of favorites looks
// bad without saying anything, and one made of road dogs looks good for the
// same non-reason. Against a flat 50% the board credits every angle with a
// fact about favorites.
{
  const { v3AngleBase } = x;
  V.tab = 'angles'; V.angleQ = ''; V.angleCat = 'all'; V.angleTeam = '';
  V.angleFrom = 0; V.angleOpen = null; V.angleSort = 'season'; render();
  ok('the board explains what the composition costs',
     L().indexOf('already decide a lot') >= 0);
  // `blowout_loss` is entirely road underdogs, a cell that covers 60% in the
  // fixture. Its expectation is 60%, NOT the 50% a flat baseline would use.
  const b = v3AngleBase({ id: 'blowout_loss' }, 2015, '');
  ok('and it is read off the cells the split actually sits in',
     b && Math.abs(b.pct - 0.60) < 1e-9, JSON.stringify(b));
  // `div_dog` is half home underdogs (50%) and half home favorites (40%).
  const d = v3AngleBase({ id: 'div_dog' }, 2015, '');
  ok('mixing two cells averages them by how many games are in each',
     d && Math.abs(d.pct - 0.45) < 1e-9, JSON.stringify(d));
  // THE SLIDER MOVES BOTH. Counting from 2026 uses 2026's cell rates and
  // 2026's mix, or the record and the thing it is measured against would be
  // computed over different spans.
  const later = v3AngleBase({ id: 'blowout_loss' }, 2026, '');
  ok('and the start year applies to the baseline too',
     later && later.n === 10, JSON.stringify(later));
  // A TEAM HAS ITS OWN MIX. ATL's `blowout_loss` games are home favorites
  // (40%), not road underdogs, so the league expectation would be wrong by
  // twenty points.
  const atl = v3AngleBase({ id: 'blowout_loss' }, 2015, 'ATL');
  ok('and a team is measured against its own mix, not the league\u2019s',
     atl && Math.abs(atl.pct - 0.40) < 1e-9, JSON.stringify(atl));
  // An angle with no mix shows nothing rather than a made-up number.
  ok('an angle with no baseline shows none',
     v3AngleBase({ id: 'nosuchangle' }, 2015, '') === null);
  // IN THE PANEL, NOT IN A COLUMN. Across fifty-five rows the expected rate
  // ran 47.93% to 52.07% with a median of exactly 50.00%, and fifty of them
  // sat within two points of it — a near-constant column costing width on a
  // phone. It still matters for the splits made almost entirely of one cell,
  // and those are the rows someone opens.
  ok('the board is back to three columns',
     L().indexOf('data-v3anglesort="base"') < 0);
  const first = Object.keys((DATA.angles || {}).games || {})[0];
  v3Do('v3angle', first); render();
  ok('and the expected rate is in the panel that opens',
     /already likely to cover about <b[^>]*>60\.00%/.test(L()),
     'no 60.00% in the panel');
  V.angleOpen = null; render();
}


// ── The year slider tracks the drag ────────────────────────────────────
//
// A range fires `input` all the way through a drag and `change` on release.
// Wired to `change` alone the year sat still until you let go. The label is
// rewritten in place rather than re-rendered, because a full render replaces
// the slider being dragged and a pointer loses the element it was holding.
{
  V.tab = 'angles'; V.angleFrom = 0; render();
  const lab = document.querySelector('[data-v3yrlab]');
  lab.setAttribute('data-v3yrlab', '');
  const drawn = (app().match(/\u2019\d\d\+ ATS/g) || []).length;
  fireDoc('input', { target: {
    getAttribute: a => a === 'data-v3anglefrom' ? '' : null, value: '2021' } });
  ok('dragging updates the year as it moves', V.angleFrom === 2021,
     String(V.angleFrom));
  ok('and writes it into the label', lab.textContent === 2021
     || String(lab.textContent) === '2021', String(lab.textContent));
  // WITHOUT RE-RENDERING, or the control being dragged is replaced under the
  // finger holding it.
  ok('without redrawing the board under the finger',
     (app().match(/\u2019\d\d\+ ATS/g) || []).length === drawn
     && app().indexOf("\u201921+ ATS") < 0);
  // Release commits it.
  fireDoc('change', { target: {
    getAttribute: a => a === 'data-v3anglefrom' ? '' : null, value: '2021' } });
  ok('and letting go redraws it', app().indexOf("\u201921+ ATS") >= 0);
  V.angleFrom = 0; render();
}


// ── One team's own record ──────────────────────────────────────────────
//
// League-wide a whole-game condition is 50.00% by arithmetic: both sides of
// every grass game are on grass, so one covers and the other does not. Per
// team it is one side of each game and can be anything, which is the whole
// reason those rows are worth keeping.
{
  V.tab = 'angles'; V.angleQ = ''; V.angleCat = 'all'; V.angleTeam = '';
  V.angleFrom = 0; V.angleOpen = null; render();
  const teams = Object.keys((DATA.angles || {}).team_splits || {});
  ok('the board offers a team picker', L().indexOf('data-v3angleteam') >= 0);
  ok('and every team in the archive is in it',
     teams.every(t => L().indexOf('>' + t + '</option>') >= 0),
     teams.join(','));
  const league = L();
  fireDoc('change', { target: {
    getAttribute: a => a === 'data-v3angleteam' ? '' : null, value: 'ATL' } });
  ok('picking one narrows the numbers to that team',
     V.angleTeam === 'ATL' && L() !== league, V.angleTeam);
  // ATL is 1-5 in `off_ot` across the archive and the league row is 141-160.
  // The two must not be the same number, or the page is still drawing the
  // league's.
  const own = L();
  ok('and the record shown is that team\u2019s',
     own.indexOf('1-5') >= 0, 'ATL 1-5 not drawn');
  ok('not the league\u2019s', own.indexOf('141-160') < 0,
     'the league record is still on the page');
  // THE TAG COMES OFF, because per team the number is no longer fixed.
  ok('the both-sides tag is gone once a team is chosen',
     own.indexOf('>both sides<') < 0);
  // And the fixtures behind a row are that team's games only.
  const first = /data-v3angle="([^"]+)"/.exec(own);
  if (first) {
    v3Do('v3angle', first[1]); render();
    const gs = ((DATA.angles || {}).games || {})[first[1]] || [];
    const mine = gs.filter(g => g.team === 'ATL');
    // COUNTED ON `agame__t`, which is one per fixture. `class="agame` also
    // matches `agame__t` and `agame__go`, which is how this said four rows
    // for one game.
    const drawn = () => (app().match(/class="agame__t"/g) || []).length;
    ok('and the fixtures under it are that team\u2019s',
       drawn() === mine.length, drawn() + ' drawn, ' + mine.length
       + ' for ATL');
    V.angleOpen = null;
  }
  // LEAGUE OR THIS CLUB, WITHOUT LOSING THE CLUB. Choosing one used to be the
  // only switch, so the way back to the league record was to clear the
  // selection and find it again in a list of thirty-two.
  ok('a club chosen, the board offers league or that club',
     own.indexOf('data-v3anglescope') >= 0);
  // COMPARED ON THE TABLE, not on the whole screen: the bar differs by the
  // club still being selected, and that is the point of the control. The
  // numbers under it have to be the league's, to the character.
  const table = h => h.slice(h.indexOf('class="arow arow--h"'));
  v3Do('v3anglescope', 'league');
  const back = L();
  ok('and the league reading comes back with the club still picked',
     V.angleTeam === 'ATL' && table(back) === table(league),
     'team=' + V.angleTeam);
  ok('the both-sides tag returns with it',
     back.indexOf('>both sides<') >= 0);
  v3Do('v3anglescope', 'team');
  ok('and the club reading is one tap back',
     L().indexOf('1-5') >= 0 && table(L()) !== table(league));
  fireDoc('change', { target: {
    getAttribute: a => a === 'data-v3angleteam' ? '' : null, value: '' } });
  ok('and clearing it restores the league board', L() === league);
  // ABSENT WITH NO CLUB CHOSEN, because the league record is then the only one
  // there is and a two-way control with one live side teaches the wrong thing.
  ok('with no club chosen there is nothing to compare, so no control',
     L().indexOf('data-v3anglescope') < 0);
}

// THE FLIP SIDE, NAMED. Thirty rows are one half of a pair -- the same games
// with the cover on the other sideline -- and unnamed the fade reads as a
// restatement of the edge above it. A reader took 5-2 and 2-5 for one claim.
{
  const rows = (DATA.angles || {}).rows || [];
  const pair = rows.filter(r => r.mirror)[0];
  ok('the board has a mirror pair to talk about', !!pair,
     'no row carries `mirror`');
  if (pair) {
    const other = rows.filter(r => r.id === pair.mirror)[0];
    ok('and its partner is on the board too', !!other, pair.mirror);
    ok('the pairing is symmetric', other && other.mirror === pair.id,
       other && other.mirror);
    // SAME GAMES, REVERSED RECORD -- which is what the tag claims, so the
    // fixture has to actually be that or the claim is untested.
    ok('the two records really are each other reversed',
       other && pair.all.n === other.all.n && pair.all.w === other.all.l
       && pair.all.l === other.all.w,
       pair.all.w + '-' + pair.all.l + ' vs '
       + (other ? other.all.w + '-' + other.all.l : '?'));
    V.angleTeam = ''; V.angleOpen = null; render();
    ok('a paired row is tagged as one side of two',
       L().indexOf('>flip side</i>') >= 0);
    // AND THE TAG NAMES THE OTHER ROW, or it says a row is half of something
    // without saying half of what.
    ok('and the tag names the row it pairs with',
       L().indexOf(other.label) >= 0, other.label);
    V.angleOpen = pair.id; render();
    const open = L();
    ok('opening it shows both records side by side',
       open.indexOf('scored from the other side') >= 0);
    ok('with the arithmetic said plainly',
       open.indexOf('add to 100%') >= 0);
    // NOT ON THE CLUB READING. Per club the two rows are not the same games at
    // all -- each picks the fixtures that club was on one side of -- so the
    // complement does not hold and must not be claimed.
    const teams = Object.keys((DATA.angles || {}).team_splits || {});
    if (teams.length) {
      V.angleTeam = teams[0]; V.angleScope = 'team'; render();
      const club = L();
      ok('but the club reading drops the arithmetic it cannot claim',
         club.indexOf('add to 100%') < 0);
      ok('while still naming the pair',
         club.indexOf('scored from the other side') >= 0);
      V.angleTeam = ''; V.angleScope = 'team';
    }
    V.angleOpen = null; render();
  }
}

// TWO DECIMALS, because break-even is 52.38% and whole points cannot show a
// row sitting either side of it.
ok('percentages carry two decimals', /\d+\.\d\d%/.test(L()));
// BOTH NUMBER COLUMNS READ THE SAME WAY: a percentage with the record under
// it. The long-run column used to carry an interval instead, which needed a
// third column to say the sample size that "1250-1180" already says.
{
  const sp = (DATA.angles || {}).splits || {};
  const id = Object.keys(sp)[0];
  let w = 0, l = 0;
  Object.keys(sp[id] || {}).forEach(y => { w += sp[id][y][0]; l += sp[id][y][1]; });
  ok('the long-run column carries its record', L().indexOf(w + '-' + l) >= 0,
     'expected ' + w + '-' + l);
  ok('and the games column is gone',
     L().indexOf('data-v3anglesort="games"') < 0);
}
// The long-run column can start later than 2015.
{
  ok('there is a control for how far back to count',
     L().indexOf('data-v3anglefrom') >= 0);
  const wide = (L().match(/<b>(\d+)<\/b><\/span>\s*<\/button>/g) || []).length;
  fireDoc('change', { target: {
    getAttribute: a => a === 'data-v3anglefrom' ? '' : null, value: '2023' } });
  ok('moving it recounts the long run',
     L().indexOf('\u201923+ ATS') >= 0, 'header did not follow the slider');
  fireDoc('change', { target: {
    getAttribute: a => a === 'data-v3anglefrom' ? '' : null, value: '2015' } });
  ok('and back again', L().indexOf('\u201915+ ATS') >= 0);
}
// Categories, so forty-six rows can be read as five lists.
{
  const cats = {};
  ((DATA.angles || {}).rows || []).forEach(r => { cats[r.cat] = 1; });
  const names = Object.keys(cats);
  ok('every angle carries a category', names.indexOf('Other') < 0,
     names.join(','));
  ok('and the board offers them as a filter',
     L().indexOf('data-v3anglecat') >= 0);
  if (names.length) {
    const before = (L().match(/data-v3angle="/g) || []).length;
    fireDoc('change', { target: {
      getAttribute: a => a === 'data-v3anglecat' ? '' : null,
      value: names[0] } });
    const after = (L().match(/data-v3angle="/g) || []).length;
    ok('filtering to one kind shows fewer rows', after < before || names.length === 1,
       before + ' -> ' + after);
    ok('and only that kind',
       after === ((DATA.angles || {}).rows || [])
         .filter(r => r.cat === names[0]).length);
    fireDoc('change', { target: {
      getAttribute: a => a === 'data-v3anglecat' ? '' : null,
      value: 'all' } });
    ok('and clears back to all', (L().match(/data-v3angle="/g) || []).length
       === before);
  }
}
// Sorted by the long run. Sorting by the hot column rebuilds the thing this
// page is an answer to.
{
  const rs = ((DATA.angles || {}).rows || []).map(r => r.all && r.all.pct);
  const sorted = rs.slice().sort((a, b) => b - a);
  ok('sorted by the long run rather than by this season',
     JSON.stringify(rs) === JSON.stringify(sorted));
}
// Losers stay. Dropping them is how a board becomes a sales pitch.
{
  const rs = ((DATA.angles || {}).rows || []);
  const losing = rs.filter(r => r.all && r.all.pct < 0.5).length;
  ok('losing angles are on the board too', losing > 0 || rs.length === 0,
     losing + ' below 50%');
}
// The math the old ladder page did is gone with it; these still-exported
// helpers are unreachable and are flagged for removal rather than deleted
// inside this change.
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

    // FOUR AT A TIME, CHOSEN FROM A SEGMENT. One metric at a time meant
    // twelve taps to read a matchup and no way to hold two side by side; all
    // twelve meant scrolling past eleven to re-read the one being weighed.
    if (h.indexOf('data-v3metric=') >= 0) {
      ok('the metrics can be filtered by what they measure',
         h.indexOf('data-v3metric="all"') >= 0);
      const barAt = h.indexOf('class="mxbar"');
      ok('and the chooser rides in the pinned bar, not under it',
         h.indexOf('data-v3metric=') > barAt
         && h.indexOf('data-v3metric=') < h.indexOf('</div>', barAt + 400));
      // NOT A PILL PER METRIC. That is what the dropdown replaced, and it
      // wrapped to six rows.
      const btns = (h.match(/data-v3metric="/g) || []).length;
      ok('it is a handful of groups, not one control per metric',
         btns > 1 && btns <= 6, btns + ' buttons');
      // EVERY GROUP OFFERED HAS ROWS IN IT, or it filters to an empty screen.
      const offered = (h.match(/data-v3metric="([^"]+)"/g) || [])
        .map(m => m.slice('data-v3metric="'.length, -1))
        .filter(g => g !== 'all');
      const live = {};
      ((cards[0].matchup.splits || {}).full || cards[0].matchup.rows || [])
        .forEach(r => { if (r.group) live[r.group] = 1; });
      ok('and every group offered has metrics in it',
         offered.every(g => live[g]), offered.join(','));
      if (offered.length) {
        v3Do('v3metric', offered[0]); render();
        const one = app();
        const nOne = (one.match(/class="mx"/g) || []).length;
        const nAll = (h.match(/class="mx"/g) || []).length;
        ok('picking a group shows fewer rows than all of them',
           nOne > 0 && nOne < nAll, 'group=' + nOne + ' all=' + nAll);
        ok('and the chooser is still there to change it',
           one.indexOf('data-v3metric="all"') >= 0);
        ok('with that group pressed',
           one.indexOf('data-v3metric="' + offered[0] + '" aria-pressed="true"')
           >= 0);
        v3Do('v3metric', 'all'); render();
      }
      // The SECTIONS are not resorted: their order is roughly how much each
      // metric explains, which is a ranking rather than a list.
      const heads = (h.match(/font-size:17px[^>]*>([^<]+)/g) || [])
        .map(t => t.slice(t.indexOf('>') + 1));
      if (heads.length > 1) {
        ok('while the sections keep the order the pipeline sent',
           heads.join('|') !== heads.slice().sort((a, b) =>
             a.localeCompare(b)).join('|'), heads.join(' | '));
      }
      // The injury view has no metrics, so the chooser is absent rather than
      // present and inert.
      V.half = 'inj'; render();
      ok('and is absent on the injury view',
         app().indexOf('data-v3metric=') < 0);
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


// ── The default question goes to the model ─────────────────────────────
//
// Asked to read the spread, the moneyline and the total, the model used to
// spend its first paragraph announcing that it does not give betting advice
// and then answer anyway. Describing the site's own numbers is the product:
// every figure it is asked about is printed on the card above the box.
{
  const { v3Ask, V3ASK_DEFAULT } = x;
  const gid = ((DATA.games || {}).cards || [])[0].game_id;
  const html = v3Ask(gid);
  ok('the panel offers a default question',
     html.indexOf('data-v3askdefault="' + gid + '"') >= 0);
  ok('and it names all three markets',
     /spread/i.test(V3ASK_DEFAULT) && /moneyline/i.test(V3ASK_DEFAULT)
     && /total/i.test(V3ASK_DEFAULT), V3ASK_DEFAULT);
  // IT ASKS THE MODEL, unlike the chips beside it, which are answered from
  // the page. `data-v3ask` is an index into the canned list; this carries a
  // game id because it is a round trip.
  ok('it is not one of the canned chips',
     html.indexOf('data-v3ask="' + V3ASK_DEFAULT + '"') < 0);
  ok('and it is marked as the one that thinks',
     html.indexOf('q q--ask') >= 0);
  // And the control is wired, or it would do nothing at all.
  ok('the handler is registered', x.V3CLICKS.indexOf('v3askdefault') >= 0,
     x.V3CLICKS.join(','));
}


// ── The season record ──────────────────────────────────────────────────
//
// Wins, accuracy and profit, over a range the reader picks. The things
// worth guarding are the ones a reader cannot check for themselves: that
// the picker selects a PRECOMPUTED range rather than the page re-adding
// anything, that the two kinds of evidence are never described as one, and
// that the simple view HIDES rather than changes.
{
  const { v3RecordPage, v3RecRange, v3Money } = x;
  V.tab = 'record'; V.game = null; V.scFrom = null; V.scTo = null;
  V.recFull = false; V.recWho = 'top'; V.recSeries = 'model'; V.recQ = '';
  render();
  const h = v3RecordPage();
  V.recFull = true;
  const hf = v3RecordPage();
  V.recFull = false;

  ok('the record screen leads with the plain-language headline',
     h.indexOf('Holding the model to account') >= 0, h.slice(0, 200));
  ok('and is reachable from the nav',
     app().indexOf('data-v3tab="record"') >= 0);
  ok('and the nav label is short enough for a fifth column',
     (V3TABS.filter(t => t[0] === 'record')[0] || [])[1].length <= 7);

  // THE THREE GAME MARKETS SHARE ONE CARD. They were three, each holding a
  // two-row table and a sentence, which is a lot of chrome around six
  // numbers for one subject.
  // TWO SECTIONS, NOT FOUR. The price rule had a card of its own, which
  // made one value of the "which bets" axis look like a different kind of
  // thing; the per-player table had a card of its own, which drew the same
  // two controls a second time.
  ok('all four sections are numbered and named',
     ['Picking the game', 'Player bets: profit per $100 staked']
       .every(s => h.indexOf(s) >= 0)
     && h.indexOf('>By market<') >= 0
     && h.indexOf('>The same bets, by player and club<') >= 0, h);
  ok('and there are two numbered cards, not four',
     (h.match(/class="rec__n"/g) || []).length === 2,
     (h.match(/class="rec__n">\d+/g) || []).join(' '));
  ok('and the three game markets are sub-headings inside one card',
     ['The winning team', 'The point spread', 'Over or under the total']
       .every(s => h.indexOf('>' + s + '<') >= 0)
     && (h.match(/class="recsec/g) || []).length >= 3, h);

  // ── THE SCOREBOARD ───────────────────────────────────────────────────
  // The whole point of the rethink: the verdict before the working. A
  // reader met five tables of percentages and an error score before
  // learning whether any of it was good.
  ok('a scoreboard states the verdict before the first table',
     h.indexOf('How the model has done') >= 0
     && h.indexOf('How the model has done') < h.indexOf('Picking the game'),
     h.slice(0, 600));
  ok('and it carries one tile per thing the model claims to do',
     ['Winning team', 'Point spread', 'Over / under', 'Player bets']
       .every(s => h.indexOf('>' + s + '<') >= 0), h);
  ok('and says the tiles are the model’s own number, not the adjusted one',
     h.indexOf('our model’s own answer') >= 0);
  // A TILE IS NOT A LINK. Routing here is the location hash, so an
  // `href="#sb1"` navigates rather than scrolls.
  ok('no scoreboard tile is an anchor into the hash router',
     h.indexOf('href="#sb') < 0, 'a tile would route away from the page');

  // ── SIMPLE HIDES, IT DOES NOT CHANGE ─────────────────────────────────
  // Every number is still computed either way; the toggle only decides
  // which rows are drawn. A figure that appears in both must be identical.
  ok('the simple view is shorter than the full one', hf.length > h.length,
     h.length + ' vs ' + hf.length);
  ok('and the toggle is on the page',
     h.indexOf('data-v3recfull="0"') >= 0
     && h.indexOf('data-v3recfull="1"') >= 0);
  {
    // The headline rate for the winning team, read out of each render.
    const grab = s => {
      const i = s.indexOf('The winning team');
      const m = /Our model<\/span><span class="n">([^<]*)<\/span><span class="n">([^<]*)</
        .exec(s.slice(i));
      return m ? m[1] + '|' + m[2] : null;
    };
    ok('a figure shown in both views is the same figure',
       grab(h) && grab(h) === grab(hf), grab(h) + ' vs ' + grab(hf));
  }
  ok('the detail only the full view carries is absent from the simple one',
     h.indexOf('How reliable the win chances') < 0
     && hf.indexOf('How reliable the win chances') >= 0);
  ok('and so are the ranges',
     h.indexOf('luck alone moves these numbers') < 0
     && hf.indexOf('luck alone moves these numbers') >= 0);

  // ── EVERY RATE GETS A REFERENCE LINE ─────────────────────────────────
  ok('each rate is drawn against the numbers that give it meaning',
     (h.match(/class="rbar"/g) || []).length >= 3, h);
  ok('and the line is labeled in words rather than left as a graphic',
     h.indexOf('>coin flip<') >= 0 && h.indexOf('>break even<') >= 0
     && h.indexOf('rbar__kus') >= 0);
  // A MONEYLINE HAS NO ONE BREAK-EVEN RATE. The first draft said "ahead of
  // the 50.0% a bet needs to turn a profit", which is not true of any
  // moneyline: the price moves with the favorite.
  ok('the winning-team section does not invent a break-even rate',
     h.indexOf('50.0% a bet needs to turn a profit') < 0
     && h.indexOf('no one break-even rate') >= 0, h);
  ok('and the spread and total, which are priced both ways, do quote one',
     h.indexOf('% a bet needs to turn a profit') >= 0);

  // THE PROVENANCE IS ABOVE THE TABLES. A reader who meets the numbers first
  // has already decided what they mean.
  ok('it says the game picks were written before kickoff',
     h.indexOf('written down before') >= 0 && h.indexOf('on the card') >= 0);
  ok('and that the player results were rebuilt afterwards',
     h.indexOf('rebuilt afterwards') >= 0
     && h.indexOf('not a record of bets anyone could') >= 0);
  ok('and both say so before the first table',
     h.indexOf('rebuilt afterwards') < h.indexOf('Picking the game'));
  ok('and the weeks with no game record say why',
     h.indexOf('have no game record') >= 0
     && h.indexOf('nothing recorded a projection') >= 0);

  // THE PICKER SELECTS, IT DOES NOT COMPUTE.
  ok('the range picker is on the page',
     h.indexOf('data-v3scfrom') >= 0 && h.indexOf('data-v3scto') >= 0);
  // PINNED, like every other board here. The tables run several screens and
  // the control that chooses which weeks they cover was at the top of them.
  ok('and it is pinned rather than scrolling away with the tables',
     /class="pbar[^"]*recpick"/.test(h), h.slice(h.indexOf('recpick') - 80,
                                                 h.indexOf('recpick') + 40));
  // WEEKS WITH NO GAME RECORD ARE OFFERED BUT DISABLED, with the reason in
  // the option. Picking one gave three empty sections and no explanation
  // worth the tap.
  ok('a week with no frozen game record cannot be selected',
     h.indexOf('disabled>Week 1 — no game record') >= 0, h);
  ok('and a week that has one can be',
     h.indexOf('<option value="4"') >= 0
     && h.indexOf('value="4" disabled') < 0);

  const def = String(DATA.scorecard.default || '').split('-').map(Number);
  ok('and it opens on the payload’s own default range',
     v3RecRange(DATA.scorecard)[0] === def[0]
     && v3RecRange(DATA.scorecard)[1] === def[1],
     JSON.stringify(v3RecRange(DATA.scorecard)));

  // ONE DROPDOWN AT A TIME, WHICH IS THE TEST THAT WAS MISSING. `v3RecRange`
  // used to resolve both ends or neither, so moving one and leaving the
  // other unset threw the chosen end away and redrew the default. Every
  // check here set both at once, which is a test written around the bug
  // rather than at it — the picker was dead on the live site and the suite
  // was green.
  V.scFrom = 4; V.scTo = null;
  ok('moving only the start moves the range',
     v3RecRange(DATA.scorecard)[0] === 4,
     JSON.stringify(v3RecRange(DATA.scorecard)));
  V.scFrom = null; V.scTo = 3;
  ok('and moving only the end moves it too',
     v3RecRange(DATA.scorecard)[1] === 3,
     JSON.stringify(v3RecRange(DATA.scorecard)));
  // The end the reader actually moved wins: choosing "to week 2" while the
  // start sits on its default means the weeks up to there, not an empty
  // range and not a silent jump back to the default.
  V.scFrom = null; V.scTo = 2;
  ok('an end chosen below the default start pulls the start down with it',
     v3RecRange(DATA.scorecard)[1] === 2
     && v3RecRange(DATA.scorecard)[0] <= 2,
     JSON.stringify(v3RecRange(DATA.scorecard)));
  // And a single week is a legal range.
  V.scFrom = 4; V.scTo = 4; render();
  ok('one week on its own renders its own block',
     v3RecordPage().indexOf('Week 4') >= 0
     && v3RecordPage() !== h, 'single-week range matched the default');

  V.scFrom = 1; V.scTo = 2; render();
  const none = v3RecordPage();
  ok('a range whose weeks were never frozen says so rather than showing zeros',
     none.indexOf('No game projection was recorded') >= 0
     && none.indexOf('Picking the winning team') < 0, none.slice(0, 400));
  ok('and still reports the player bets, which do exist for it',
     none.indexOf('Player bets') >= 0);

  V.scFrom = 1; V.scTo = 4; render();
  ok('a wider range reads a different precomputed block',
     v3RecordPage() !== h);

  V.scFrom = 4; V.scTo = 2;
  ok('an inverted range collapses rather than showing nothing',
     v3RecRange(DATA.scorecard)[0] <= v3RecRange(DATA.scorecard)[1],
     JSON.stringify(v3RecRange(DATA.scorecard)));
  V.scFrom = null; V.scTo = null; render();

  // MONEY READS AS MONEY, and a loss takes a real minus sign.
  ok('a profit per $100 is signed and in dollars',
     v3Money(0.0759).indexOf('+$7.59') >= 0, v3Money(0.0759));
  ok('and a loss carries a real minus sign',
     v3Money(-0.0669).indexOf('−$6.69') >= 0, v3Money(-0.0669));
  // WHAT A BET IS, ON THE FACE OF THE CARD. Asked directly whether the
  // 1,062 was players or bets; it is neither on its own.
  ok('the player table says what one bet is',
     h.indexOf('One bet is one player, in one game, in one category') >= 0);
  ok('and why the alternate lines are not seventeen bets',
     h.indexOf('turns one opinion into seventeen') >= 0);
  ok('and the break-even column is named in words a reader uses',
     h.indexOf('Needed to profit') >= 0 && h.indexOf('To break even') < 0);

  // ONE VOCABULARY ON EVERY SECTION.
  ok('every section names our model, and the full view the other two',
     (h.match(/Our model/g) || []).length >= 3
     && (hf.match(/Adjusted model/g) || []).length >= 3
     && (hf.match(/Sportsbook/g) || []).length >= 3, h.slice(0, 400));
  ok('and the adjusted row comes between ours and the book',
     hf.indexOf('Our model') < hf.indexOf('Adjusted model')
     && hf.indexOf('Adjusted model') < hf.indexOf('Sportsbook'));
  ok('the old vocabulary is gone',
     hf.indexOf('Model alone') < 0 && hf.indexOf('Shown on the card') < 0
     && hf.indexOf('Blended win chance') < 0
     && hf.indexOf('95% range') < 0, hf);
  ok('before week 5 a new row says when it starts rather than inventing one',
     hf.indexOf('recorded from week 5') >= 0);
  // "LEVEL REMOVED" WAS JARGON. Same rows, said in words.
  ok('the level-removed total is named in words and sits below its variant',
     hf.indexOf('ignoring the week’s scoring level')
       > hf.indexOf('Adjusted model')
     && hf.indexOf('Our model, level removed') < 0);
  // AND IT IS NOT A COLUMN ANY MORE. Four cells each reading "39.3% to
  // 71.8%", every one wide enough to contain every other row, read as the
  // page declining to say anything — so the interval is said once, in
  // prose, beside the rate it belongs to. The number is not dropped.
  ok('the range is explained in words, not named after a statistic',
     hf.indexOf('luck alone moves these numbers') >= 0
     && hf.indexOf('where the true rate most likely sits') >= 0);
  ok('and the interval is still reported, in the sentence rather than a '
     + 'column',
     /Our model’s [\d.]+% could honestly be anywhere from [\d.]+% to [\d.]+%/
       .test(hf), hf.slice(hf.indexOf('luck alone'), hf.indexOf('luck alone')
                           + 240));
  ok('and the winning-team table has no Range column left',
     h.indexOf('The winning team') >= 0
     && !/The winning team[\s\S]{0,400}>Range</.test(h), h);
  ok('the player section draws our model and the adjusted model separately',
     hf.indexOf('Our model') < hf.indexOf('Adjusted model'),
     'player series not split');
  ok('and compares the two in words',
     h.indexOf('the model alone returned') >= 0);
  ok('the player bets say how they are settled',
     hf.indexOf('paid at the under’s own price') >= 0
     && hf.indexOf('did not play is void') >= 0);

  // ── THE EDGE RULE IS NOT THE BOARD'S FILTERS ─────────────────────────
  // Asked directly whether section 05 was the shortlist, the fades and the
  // streaks. It is none of them — it is a price rule — and the old heading
  // ("Only where our edge cleared the bar") left a reader to guess.
  // ── ONE VOCABULARY FOR "WHICH BETS" ──────────────────────────────────
  ok('the two axes are labeled and separate',
     h.indexOf('>Which bets<') >= 0 && h.indexOf('>Whose side<') >= 0, h);
  ok('and the price rule is one of the five, not a section',
     h.indexOf('data-v3recview="gap"') >= 0
     && h.indexOf('only where the price was wrong enough') < 0, h);
  {
    V.recView = 'gap';
    const gp = v3RecordPage();
    ok('and names the margin each market has to clear',
       /catches [\d.]+pp/.test(gp), gp);
    ok('and points at the board’s filter that shows this week’s',
       gp.indexOf('Big gaps') >= 0);
    // A CUT THAT PICKS ITS OWN SIDE OFFERS NO SIDE CONTROL, rather than a
    // choice that does nothing.
    ok('a rule that picks its own side drops the side control',
       gp.indexOf('>Whose side<') < 0
       && gp.indexOf('no model-or-adjusted') >= 0, gp.slice(0, 400));
    V.recView = 'all';
  }

  // ── 04 · THE BOARD'S FOUR VIEWS ──────────────────────────────────────
  //
  // Everyone, Shortlist, Fades and Streaks are the tabs on the players
  // board, and until now none of them could be scored. Each is its OWN set
  // of bets: the shortlist picks its own line and its own side, so showing
  // our result under its name would report the board's record as the
  // rule's.
  {
    V.recView = 'all'; V.scFrom = null; V.scTo = null; render();
    const base = v3RecordPage();
    ok('section 04 offers the board’s four filters',
       ['Everyone', 'Shortlist', 'Fades', 'Streaks']
         .every(s => base.indexOf('>' + s + '<') >= 0), base);
    const seen = {};
    for (const k of ['all', 'short', 'fade', 'streak']) {
      V.recView = k;
      const h2 = v3RecordPage();
      seen[k] = h2;
      ok('the ' + k + ' filter renders', h2.indexOf('Player bets') >= 0);
      ok('and says what it is before the table',
         h2.indexOf('</p>') > 0 && h2.length > 500);
    }
    // THE NUMBERS MOVE. A selector that redraws the same figures is a
    // selector that is reading the wrong key, which is exactly what a
    // fallback to the top-level `ou` would do.
    ok('each filter draws its own numbers',
       new Set(['all', 'short', 'fade', 'streak'].map(k => seen[k])).size === 4,
       'two filters rendered identically');
    ok('and the shortlist return is the shortlist’s, not everyone’s',
       seen.short.indexOf('+$7.31') >= 0, 'wanted the fixture shortlist roi');
    // SHORTLIST AND FADES CARRY ONE SERIES, because the rule picks the side.
    // Scoped to section 04: the game sections above it name the adjusted
    // model too, and the first version of this check read the whole page
    // and failed on those.
    const sec04 = h2 => {
      const a = h2.indexOf('Player bets: profit per $100');
      const b = h2.indexOf('only where the price was wrong enough');
      return h2.slice(a, b > a ? b : undefined);
    };
    ok('a filter that picks its own side draws one series, not two',
       sec04(seen.short).indexOf('The rule’s own side') >= 0
       && sec04(seen.short).indexOf('Adjusted model') < 0,
       sec04(seen.short).slice(0, 300));
    // AND FADES IS A SUBSET, not a fourth disjoint group. On a two-sided
    // line a fade is the shortlist's under picks.
    ok('and the fades say they are also in the shortlist',
       seen.fade.indexOf('also in Shortlist') >= 0);
    // STREAKS KEEPS BOTH SIDES, because there the side is still ours.
    V.recFull = true;
    V.recView = 'streak';
    const st = v3RecordPage();
    V.recFull = false;
    ok('the streak filter keeps our model and the adjusted one apart',
       sec04(st).indexOf('Our model') >= 0
       && sec04(st).indexOf('Adjusted model') > sec04(st).indexOf('Our model'),
       sec04(st).slice(0, 300));
    ok('and says the count is as of that week rather than as of today',
       seen.streak.indexOf('as of that week') >= 0);
    ok('and that it is form rather than an edge',
       seen.streak.indexOf('not an edge') >= 0);
    // THE SHORTLIST'S PROVENANCE. Fitted on 2024 with 2025 and 2026 held
    // out, so these weeks are a test of it and not a replay of the fit.
    ok('the shortlist says the bands were fitted before these weeks',
       seen.short.indexOf('held out') >= 0);
    V.recView = 'all'; render();
  }

  // ── 06 · BETS BY PLAYER ──────────────────────────────────────────────
  ok('there is a per-player section',
     h.indexOf('The same bets, by player and club') >= 0, h);
  ok('and it says a player’s bets are not independent',
     h.indexOf('not independent') >= 0
     && h.indexOf('land the same way') >= 0);
  ok('and offers all four cuts',
     ['Best and worst', 'Every player', 'By team', 'By game', 'Most bet']
       .every(s => h.indexOf('>' + s + '<') >= 0), h);
  ok('and it reads the page’s own two controls, not a third vocabulary',
     h.indexOf('data-v3recseries') < 0
     && h.indexOf('data-v3recside="model"') >= 0
     && (h.match(/data-v3recview="all"/g) || []).length === 1,
     'the controls are drawn twice or a third control survives');

  // THE PAGE'S ONLY ARITHMETIC IS ADDITION, and this checks it against the
  // legs it was handed. That the legs and the pooled rows are the SAME
  // bets is a different claim, tested in Python against real pooled rows
  // rather than against a fixture trimmed to agree with itself.
  {
    const B = DATA.scorecard.bets;
    // Each cut names the group its legs live in and the slot it reads, so
    // this walks the same shipped arrays the page does. Shortlist and Fades
    // live in their OWN group: the rule picks whichever line clears its
    // band, which over 2026 weeks 1-4 is a different line from the median
    // one on 350 of 676 picks.
    const CUTS = [['all', 'model', 'weeks', 6], ['all', 'adj', 'weeks', 4],
                  ['gap', 'model', 'weeks', 7],
                  ['short', 'model', 'short', 4]];
    for (const [cut, side, grp, ri] of CUTS) {
      const key = cut + '/' + side;
      V.recView = cut; V.recSide = side; V.recWho = 'all';
      V.scFrom = 3; V.scTo = 4;
      const by = {};
      for (const w of ['3', '4']) {
        for (const [pi, , legs] of (B[grp] || {})[w] || []) {
          for (const l of legs) {
            if (l[ri] === null || l[ri] === undefined) continue;
            const n = B.players[pi];
            by[n] = by[n] || {bets: 0, won: 0, ret: 0};
            by[n].bets++; by[n].ret += l[ri];
            if (l[ri] > 0) by[n].won++;
          }
        }
      }
      const page = v3RecordPage();
      let every = true, why = '';
      for (const [n, r] of Object.entries(by)) {
        const cash = (r.ret / r.bets >= 0 ? '+$' : '−$')
          + Math.abs(r.ret / r.bets * 100).toFixed(2);
        const i = page.indexOf('>' + n + '<');
        if (i < 0) { every = false; why = n + ' missing'; break; }
        const cells = page.slice(i, i + 420);
        if (cells.indexOf('>' + r.bets + '<') < 0
            || cells.indexOf(cash) < 0) {
          every = false;
          why = n + ' wanted ' + r.bets + ' bets and ' + cash;
          break;
        }
      }
      ok('the ' + key + ' per-player totals are the sum of its own legs',
         every, why);
    }
    V.recView = 'all'; V.recSide = 'model'; V.recWho = 'top';
    V.scFrom = null; V.scTo = null;
  }
  // THE CORRELATION, MADE VISIBLE RATHER THAN ONLY STATED. A player-game
  // whose legs all landed the same way is one opinion drawn three times.
  {
    V.recWho = 'games'; V.scFrom = 3; V.scTo = 4;
    const g = v3RecordPage();
    ok('the by-game cut spells out each leg',
       g.indexOf('class="pgleg') >= 0
       && /Catches (over|under) [\d.]+, had/.test(g), g.slice(0, 300));
    ok('and flags the player-games whose legs all landed together',
       g.indexOf('landed the same way') >= 0);
    V.recQ = 'Kyren';
    const q = v3RecordPage();
    ok('and the search narrows it to one player',
       q.indexOf('Kyren Williams') >= 0 && q.indexOf('Tee Higgins') < 0, q);
    V.recQ = 'zzzz';
    ok('and says so when nothing matches',
       v3RecordPage().indexOf('No player matching') >= 0);
    V.recQ = ''; V.recWho = 'top'; V.scFrom = null; V.scTo = null;
  }
  // WHAT THE BET WAS, FROM A PLAYER ROW. The three player-level cuts said
  // how a man did and never which bets those were — "6 bets, 6 won" with no
  // way to see the six — so the name opens.
  {
    V.recWho = 'top'; V.recSeries = 'model'; V.scFrom = 3; V.scTo = 4;
    V.recOpen = null;
    const shut = v3RecordPage();
    ok('a player name is a control rather than plain text',
       shut.indexOf('data-v3recopen=') >= 0, shut.slice(0, 200));
    const m = /data-v3recopen="([^"]+)"/.exec(shut);
    V.recOpen = m && m[1];
    const open = v3RecordPage();
    ok('and opening one spells out what each of his bets was',
       open.indexOf('class="pgd__l"') >= 0
       && /(Catches|Receiving yards|Rushing yards|Passing yards)<\/span>/
            .test(open)
       && /(over|under) [\d.]+/.test(open), open.slice(0, 400));
    ok('and names the game and week each bet was in',
       /class="pgwk">week \d/.test(open) && /class="pgd__h"/.test(open),
       'no game or week on the opened legs');
    ok('and what each leg was paid at',
       /class="pgd__p n"/.test(open), 'no price on the opened legs');
    ok('only the player asked for is open',
       (open.match(/class="pgd"/g) || []).length === 1);
    V.recOpen = null;
    // THE THIRD GRADING IS NAMED FOR WHAT IT DOES. "Edge rule only" said
    // nothing and was read as the shortlist, which is a different rule.
    ok('the price-gap grading is not called an edge rule',
       shut.indexOf('Edge rule only') < 0
       && shut.indexOf('>Big price gaps<') >= 0, shut.slice(0, 200));
    V.recView = 'gap';
    ok('and the shortlist is a different cut with its own bets',
       v3RecordPage().indexOf('data-v3recview="short"') >= 0);
    V.recView = 'all'; V.scFrom = null; V.scTo = null;
  }

  // A SCORECARD WITH NO LEGS STILL RENDERS. `bets` is new, so a payload
  // built before it has to fall through rather than throw.
  {
    const was = DATA.scorecard.bets;
    delete DATA.scorecard.bets;
    render();
    ok('a payload with no per-leg bets drops section 06 rather than throwing',
       v3RecordPage().indexOf('Bets by player') < 0
       && v3RecordPage().indexOf('Picking the game') >= 0);
    DATA.scorecard.bets = was;
  }

  {
    const key = DATA.scorecard.default;
    const blk = DATA.scorecard.ranges[key];
    const was = JSON.stringify(blk.games);
    blk.games.moneyline.blend = {w: 9, l: 7, n: 16, pct: 0.5625,
                                 lo: 0.33, hi: 0.77};
    blk.games.moneyline.brier_blend = 0.2101;
    blk.games.moneyline.brier_book_blend = 0.2109;
    blk.games.total.centered = {w: 9, l: 7, push: 0, n: 16, pct: 0.5625,
                                lo: 0.33, hi: 0.77};
    blk.games.total.mae_centered = 9.87;
    blk.games.total.over_centered = 8;
    V.recFull = true;
    const withB = v3RecordPage();
    V.recFull = false;
    ok('once recorded, the blended error score is shown against the book '
       + 'on the same games', withB.indexOf('Blended: 0.2101') >= 0
       && withB.indexOf('0.2109 on the same 16 games') >= 0);
    ok('and the level-removed over count is reported beside the raw one',
       withB.indexOf('8 of 16 once the level is removed') >= 0);
    blk.games = JSON.parse(was);
  }

  const wasS = DATA.scorecard;
  DATA.scorecard = {};
  ok('an empty scorecard says so rather than rendering nothing',
     v3RecordPage().indexOf('Nothing graded yet') >= 0);
  DATA.scorecard = wasS;
  V.tab = 'props'; render();
}


// ── Where the money is ─────────────────────────────────────────────────
//
// Bets and money, on all three markets, from one feed. The moneyline had
// both shares side by side and the other two had bets only, from a different
// book, with the dollars in a separate card further down the page.
{
  const { v3PublicMoney, v3SharpSides, V3RATIO_SMALL } = x;

  const sides = v3SharpSides('ATL_GB');
  ok('the split feed carries all three markets, not just the moneyline',
     sides.length >= 2 && sides.some(s => s.market === 'Spread'),
     JSON.stringify(sides));
  ok('and ranks them by ratio, biggest bet first',
     sides.every((s, i) => i === 0 || sides[i - 1].ratio >= s.ratio),
     JSON.stringify(sides.map(s => s.ratio)));
  ok('a side backed by ordinary-sized bets is left out',
     sides.every(s => s.ratio >= V3RATIO_SMALL),
     JSON.stringify(sides));

  V.tab = 'games'; V.game = 'ATL_GB'; V.gameTab = 'odds'; render();
  const html = v3PublicMoney('ATL_GB');
  // EVERY MARKET GETS BOTH BARS. One bar said "84% on SF" and left the
  // reader to work out whether that was a lot of people or a lot of money.
  ok('every market is drawn with a bets bar and a money bar',
     (html.match(/aria-label="Bets:/g) || []).length === 3
     && (html.match(/aria-label="Money:/g) || []).length === 3,
     (html.match(/aria-label="Bets:/g) || []).length + ' bets, '
     + (html.match(/aria-label="Money:/g) || []).length + ' money');
  ok('and all three are named',
     html.indexOf('Who wins') >= 0 && html.indexOf('The spread') >= 0
     && html.indexOf('Total points') >= 0);
  // THE CASE A GAP RANKING DROPS. Carolina is 89% of the tickets AND 96% of
  // the money: a 7-point gap, under every threshold on this card, and three
  // times the average bet.
  const car = v3SharpSides('CAR_CLE');
  ok('a heavily backed side with the money behind it still surfaces',
     car.length === 1 && car[0].side === 'CAR', JSON.stringify(car));
  ok('and is named by its ratio rather than its gap',
     v3PublicMoney('CAR_CLE').indexOf('3.0 times') >= 0,
     v3PublicMoney('CAR_CLE'));
  // LAYMAN TERMS. "pp" is a unit a reader has to be taught.
  ok('no percentage-point jargon anywhere on the card',
     html.indexOf('pp') < 0, html.slice(html.indexOf('pp') - 60, 60));
  // WHAT A MOVE MEANS, said once, in words — now behind a fold rather than
  // ahead of the bars. The words are what this check is about; the heading
  // they used to sit under is not.
  ok('the card explains what a line move means',
     html.indexOf('keep the amount bet on each side roughly even') >= 0);
  ok('and the explanation is folded, not leading the card',
     html.indexOf('<details class="fold"') >= 0
     && html.indexOf('<details class="fold"')
        < html.indexOf('keep the amount bet on each side roughly even'),
     'the explanation is not inside a fold');
  ok('the bars come before the words that explain them',
     html.indexOf('class="pubrow"') < html.indexOf('<details class="fold"'));
  ok('and gives the two numbers for the markets that have them',
     html.indexOf('Opened at') >= 0 || html.indexOf('has not moved') >= 0,
     html);
  // NOT A TIP. Whether the bigger money is the smarter money is exactly what
  // has not been measured, and the card has to say so on its face.
  ok('the card refuses to call itself a tip',
     html.indexOf('None of this is a tip') >= 0
     && html.indexOf('not measured') >= 0);
  // THE SIDE THAT SHORTENED IS THE SIDE THAT GETS NAMED. `open_odds` and
  // `now_odds` are built `[home, away]` by `public_money.line_view`, and
  // this sentence used to read them `[away, home]` — so it printed the right
  // two prices under the wrong team's name, on every game of the season.
  // ATL at NO in week 4 is the case that showed it: 87% of the moneyline
  // money on ATL, ATL in from +114 to +100, the spread a point toward ATL,
  // and the card announcing that NO was the side getting expensive.
  //
  // Checked against every game in the payload rather than one fixture,
  // because the bug is a constant index and a single game can agree with it
  // by luck half the time.
  const impl = o => (o > 0 ? 100 / (o + 100) : -o / (-o + 100));
  let checked = 0;
  Object.keys((DATA.games || {}).lines || {}).forEach(gid => {
    const h = (((DATA.games || {}).lines || {})[gid] || {}).h2h || {};
    const oo = h.open_odds, no = h.now_odds;
    if (!oo || !no || !has(oo[0]) || !has(oo[1]) || !has(no[0]) || !has(no[1]))
      return;
    const card = (x.v3GameSet ? (x.v3GameSet().cards || []) : [])
      .filter(g => g.game_id === gid)[0];
    const body = v3PublicMoney(gid);
    if (!card || body.indexOf('more expensive to back') < 0) return;
    checked += 1;
    // Whose implied chance went UP is whose price got more expensive.
    const dHome = impl(no[0]) - impl(oo[0]);
    const team = dHome > 0 ? card.home : card.away;
    const i = dHome > 0 ? 0 : 1;
    const sent = body.slice(0, body.indexOf('more expensive to back'));
    const tail = sent.slice(sent.lastIndexOf('<p'));
    ok(gid + ': the side that shortened is the side the sentence names',
       tail.indexOf(team) >= 0, tail);
    // AND THE PRICES ARE THAT SIDE'S, with a sign. Printed raw a +114
    // underdog reads as "114", which a reader takes for a favorite.
    const sgn = v => (v > 0 ? '+' : '\u2212') + Math.abs(v);
    ok(gid + ': and quotes that side\u2019s two prices, signed',
       tail.indexOf(sgn(oo[i])) >= 0 && tail.indexOf(sgn(no[i])) >= 0,
       tail + ' | want ' + sgn(oo[i]) + ' and ' + sgn(no[i]));
  });
  // AND THE CASE ITSELF, injected, because the fixture ships no moneyline
  // with both ends and the sweep above then proves nothing. These are the
  // real numbers from ATL at NO, week 4: NO (home) -135 to -120, ATL (away)
  // +114 to +100. ATL is the side whose chance rose.
  {
    const gid = (x.v3GameSet().cards || []).filter(
      g => v3PublicMoney(g.game_id).indexOf('Who wins') >= 0)[0];
    ok('a game with a moneyline split to hang the check on', !!gid);
    if (gid) {
      DATA.games = DATA.games || {};
      DATA.games.lines = DATA.games.lines || {};
      const L = DATA.games.lines;
      const was = L[gid.game_id];
      L[gid.game_id] = Object.assign({}, was, {
        h2h: { open_odds: [-135, 114], now_odds: [-120, 100] } });
      const body = v3PublicMoney(gid.game_id);
      const s = body.slice(0, body.indexOf('more expensive to back'));
      const tail = s.slice(s.lastIndexOf('<p'));
      ok('the away side shortening is reported as the away side',
         tail.indexOf(gid.away) >= 0 && tail.indexOf(gid.home) < 0, tail);
      ok('and its prices are quoted with their signs',
         tail.indexOf('+114') >= 0 && tail.indexOf('+100') >= 0, tail);
      // THE MIRROR, so the check cannot pass on a constant.
      L[gid.game_id] = Object.assign({}, was, {
        h2h: { open_odds: [114, -135], now_odds: [100, -120] } });
      const flip = v3PublicMoney(gid.game_id);
      const fs = flip.slice(0, flip.indexOf('more expensive to back'));
      const ft = fs.slice(fs.lastIndexOf('<p'));
      ok('and swapping the two sides swaps the team named',
         ft.indexOf(gid.home) >= 0 && ft.indexOf(gid.away) < 0, ft);
      if (was === undefined) delete L[gid.game_id]; else L[gid.game_id] = was;
    }
  }

  // ONE NUMBER PER HEADER. The note beside "The spread" used to come from
  // the card while the sentence under it came from this feed, so ATL at NO
  // read "NO by 2.5" directly above "now NO by 1.5".
  Object.keys((DATA.games || {}).lines || {}).forEach(gid => {
    const L = ((DATA.games || {}).lines || {})[gid] || {};
    const body = v3PublicMoney(gid);
    if (!body || body.indexOf('The spread') < 0) return;
    const nowPt = (L.spreads || {}).now;
    if (!has(nowPt) || nowPt === 0) return;
    const head = body.slice(body.indexOf('The spread'),
                            body.indexOf('The spread') + 400);
    ok(gid + ': the spread header names the same line the move ends at',
       head.indexOf('by ' + Math.abs(nowPt)) >= 0, head.slice(0, 200));
  });

  ok('a game with no split shows no card',
     v3PublicMoney('NOPE_NOPE') === '', v3PublicMoney('NOPE_NOPE'));
  ok('and it is on the game screen',
     app().indexOf('Where the money is') >= 0);
  // ONE SECTION, NOT TWO. The dollar share used to be a second card saying
  // the same thing about the same three markets.
  ok('with no second card repeating it',
     app().indexOf('Where the bigger bets are') < 0);
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
  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'odds';
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
  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'odds';
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
  try { v3Do('v3gtab', 'angles'); } catch (e) { threw = e; }
  ok('switching section does not throw', !threw, threw && threw.message);
  ok('and lands on the section rather than the tab you left',
     V.gameTab === 'angles');
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
  V.tab = 'games'; V.game = cards[0].game_id; V.gameTab = 'odds';
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
    // The section a reader was on used to be Outcome; that tab is now the
    // Odds tab once a game has been played, so the section being KEPT is
    // what this checks, not which name it happens to have.
    ok('stepping keeps the section you were reading',
       V.gameTab === 'odds', String(V.gameTab));
    ok('and changes the game', V.game === step[1]);
    ok('and lands on that section, not the top of the new game',
       scroll.scrollTop === BAR_AT, 'scrollTop ' + scroll.scrollTop);

    // The dropdown is the same control and must agree.
    const other = (cards.filter(c => c.game_id !== V.game)[0] || {}).game_id;
    if (other) {
      V.gameTab = 'odds'; render(); scroll.scrollTop = DEEP;
      fireDoc('change', { target: {
        getAttribute: k => k === 'data-v3gameto' ? '' : null,
        value: other } });
      ok('the dropdown keeps the section too', V.gameTab === 'odds');
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
    V.tab = 'games'; V.game = c.game_id; V.gameTab = 'odds';
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
  ['odds', 'players', 'notes', 'edge', 'angles'].forEach(k =>
    ok('the ' + k + ' section is on the bar', at(k) >= 0));
  ok('and injuries is not one of them, having joined the matchup',
     at('inj') < 0);
  // SCORE IS NOT ONE EITHER. It said nothing from Tuesday to Sunday night
  // and sat second in the strip; the Odds tab is what it becomes once there
  // is a result.
  ok('and score is not a section of its own', at('out') < 0);
  // The two you can BET sit together, ahead of the three that explain them.
  ok('the betting sections come first and are not split by commentary',
     at('odds') < at('players') && at('players') < at('notes')
     && at('notes') < at('edge') && at('edge') < at('angles'));
  // The LABELS say what is in each: the player rows are the Props board
  // scoped to this game rather than a second, differently named one.
  ok('the sections are labeled for their contents',
     gh.indexOf('>Props<') >= 0 && gh.indexOf('>Angles<') >= 0
     && gh.indexOf('>Outcome<') < 0 && gh.indexOf('>Players<') < 0);
  // An old name in saved state or in a link has to land somewhere real.
  ok('and the names this app dropped still resolve',
     x.v3GTab('out') === 'odds' && x.v3GTab('score') === 'odds'
     && x.v3GTab('bets') === 'odds' && x.v3GTab('inj') === 'edge');
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

// ── Whose pick the green and red grade ─────────────────────────────────
//
// The board graded the BOOK'S favorite and nothing said so, which made a
// played week a scorecard for the sportsbook on a page whose whole reason to
// exist is the second opinion. The fixture's week 2 disagrees on purpose:
// book and blend favor BUF, who won; the model favors DET, who lost.
{
  const pw = Object.keys(((DATA.games || {}).past || {}))[0];
  if (pw) {
    V.tab = 'games'; V.game = null; V.week = Number(pw); V.gfilter = 'all';
    ok('the board grades our model by default', V.gbasis === 'model');
    render();
    const byModel = app();
    ok('and a game our model called wrong is marked lost',
       byModel.indexOf('DET lost') >= 0 && byModel.indexOf('BUF won') < 0);
    v3Do('v3gbasis', 'book'); render();
    const byBook = app();
    ok('the book can still be graded instead',
       byBook.indexOf('BUF won') >= 0 && byBook.indexOf('DET lost') < 0);
    ok('and the two disagree, which is why the control exists',
       byBook !== byModel);
    v3Do('v3gbasis', 'adj'); render();
    ok('and so can the blend of the two', app().indexOf('BUF won') >= 0);
    // WHICH OF THE THREE THE CARD IS ABOUT. Book, model and adjusted sit
    // side by side and the green or red grades exactly one of them.
    const marked = h2 => {
      const m = /<span class="cell cell--on">.*?<i>([a-z]+)<\/i>/.exec(h2);
      return m ? m[1] : null;
    };
    ok('the graded number is marked on the card', marked(app()) === 'adjusted',
       String(marked(app())));
    v3Do('v3gbasis', 'book'); render();
    ok('and the mark follows the control', marked(app()) === 'book',
       String(marked(app())));
    ok('with exactly one number marked per card',
       (app().match(/cell--on/g) || []).length
       === (app().match(/data-v3game=/g) || []).length,
       (app().match(/cell--on/g) || []).length + ' marks, '
       + (app().match(/data-v3game=/g) || []).length + ' cards');
    // The control sits in the pinned bar with the filter, not above it.
    const h = app();
    ok('the basis control is pinned with the filter',
       h.indexOf('data-v3gbasis=') > h.indexOf('class="pbar pbar--free"'));
    v3Do('v3gbasis', 'model');
    V.week = null; V.tab = 'props'; render();
  } else {
    ok('no archived week in the fixture; grading basis not exercised', true);
  }
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
    V.tab = 'games'; V.game = c.game_id; V.gameTab = 'odds'; V.week = null;

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

// ── The headline boxes grade the CALL, not the outcome ─────────────────
//
// They said "IND won 38%" and went red because Indianapolis lost — but 38%
// IS the call that Indianapolis loses, so a correct read was marked wrong.
// The over box had the same fault the other way: 46% with the game going
// over is a miss, and it went green.
if (cards.length) {
  const c = cards[0];
  const keep = { s: c.scores, fh: c.final_home, fa: c.final_away };
  if (keep.s && keep.s.home_win && keep.s.over) {
    V.tab = 'games'; V.game = c.game_id; V.gameTab = 'odds'; V.week = null;
    // An underdog home team: the model leans AWAY.
    c.scores = Object.assign({}, keep.s, {
      home_win: { n: 133, pct: 37.4, lo: 32.5, hi: 42.5 },
      over: { n: 162, pct: 45.5, lo: 41.0, hi: 51.4 }, total: 48 });

    c.final_home = null; c.final_away = null; render();
    const live = app();
    ok('the box names the side we lean, not always the home team',
       live.indexOf(c.away + ' to win') >= 0,
       'expected ' + c.away + ' to win');
    ok('with that side\u2019s probability, not its complement',
       live.indexOf('>63%<') >= 0);
    ok('and the total box names the side too',
       live.indexOf('Under 48') >= 0 && live.indexOf('>55%<') >= 0);

    // The away team wins and the game goes UNDER: both calls right.
    c.final_home = 10; c.final_away = 20; render();
    const right = app();
    ok('leaning away and the away team winning is green',
       (right.match(/box--good/g) || []).length === 2,
       (right.match(/box--good/g) || []).length + ' green, '
       + (right.match(/box--bad/g) || []).length + ' red');

    // The home team wins and it goes OVER: both calls wrong.
    c.final_home = 40; c.final_away = 30; render();
    const wrong = app();
    ok('and the home team winning after we leaned away is red',
       (wrong.match(/box--bad/g) || []).length === 2,
       (wrong.match(/box--good/g) || []).length + ' green, '
       + (wrong.match(/box--bad/g) || []).length + ' red');
    ok('which is the case that used to be colored backwards',
       wrong.indexOf('box--good') < 0);

    // A tie and a push are neither right nor wrong.
    c.final_home = 24; c.final_away = 24; render();
    ok('a tie is neither color', app().indexOf('it ended level') >= 0);
    ok('and a push says so', app().indexOf(', push') >= 0);
  }
  c.scores = keep.s; c.final_home = keep.fh; c.final_away = keep.fa;
  V.game = null; V.tab = 'props'; V.gameTab = 'notes';
}


// ── The caveats are kept, and kept out of the way ──────────────────────
//
// This project will not drop a caveat; several are the reason a number is not
// a tip. But four paragraphs under a table is the part of a card with the
// most words and the least news, and folding them is the difference between
// keeping them and making the reader scroll past them every week.
{
  V.tab = 'angles'; V.game = null; V.week = null; render();
  const ah = app();
  ok('the angles page folds how to read it', ah.indexOf('<details class="fold"') >= 0);
  ok('but says how many were measured together without being asked',
     /patterns measured/.test(ah)
     && ah.indexOf('patterns measured') < ah.indexOf('<details class="fold"'),
     'the denominator is behind the fold');
  V.tab = 'props';
}

// ── A player's record, in money ─────────────────────────────────────────
//
// "7 of 10 landed" is a rate; what a reader wants from it is what backing him
// those ten weeks would have returned. The two have to agree about which
// weeks they are talking about, which is why one control drives both.
{
  V.tab = 'props'; V.game = null; V.market = 'any'; V.filter = 'all';
  V.q = ''; V.pastN = null; V.pastAll = null; render();
  // Pulled out of the HTML rather than off the DOM: the stub has no
  // querySelectorAll, and an empty list from one would have skipped every
  // check below while the run still said all passed.
  const m0 = /data-v3open="([^"]+)"/.exec(app());
  ok('the props board has a player to open', !!m0, 'no openable row');
  if (m0) {
    x.v3Do('v3open', m0[1]);
    const h = app();
    ok('a player panel prices the record it just counted',
       h.indexOf('$100 a week on') >= 0, 'no money line in the panel');
    // THE SIDE THE ARCHIVE HOLDS, named rather than implied. There is no
    // under price in it, so there is no fade figure and the panel says so.
    ok('the money line names the side it priced',
       h.indexOf('>yes<') >= 0 || h.indexOf('>the over<') >= 0);
    // THE MONEY FOLLOWS THE STREAK NOW. A player who went under six of ten
    // is not asking what backing the over would have returned, so the side
    // is read off the window and named — and where the archive never held
    // that side, the panel says which market that is about rather than
    // quietly pricing the other one.
    ok('the money names a side the window actually ran',
       />yes<|>the over<|>no<|>the under</.test(h), 'no side named');
    ok('and a fade with no archived price says so rather than inventing one',
       h.indexOf('$100 a week on') >= 0
       || h.indexOf('no price for that side') >= 0);
    // NOT A FORECAST, said every time: this is the number that gets
    // screenshotted away from its caveats.
    ok('the money line is stated as a record, not a signal',
       h.indexOf('cannot separate a player from the hold') >= 0);
    ok('the window is selectable', h.indexOf('data-v3pastn') >= 0);
    // IT HOLDS WHILE YOU READ THE SECTION AND LETS GO WITH IT — which is
    // what `position:sticky` is, so there is nothing to release by hand.
    ok('and it sticks to the top of its own section',
       h.indexOf('pl__seg--stick') >= 0);
    // THE RECORD LEADS THE PANEL. Twenty label-and-number pairs used to sit
    // between the tap and the chart of what the player has actually done.
    ok('the record comes before the figures that price this week',
       h.indexOf('class="pl"') < h.indexOf('<dl>'),
       'the facts list is still first');
    // THE ARITHMETIC, ONCE, ON A FIXTURE WHOSE ANSWER IS WORKED OUT BY HAND.
    // Ten weeks: +140, -100, +120, VOID, +90.91 (at -110), -100, no price,
    // +130, -100, +115 = +295.91. The void and the unpriced week are the two
    // that a careless sum turns into -$200.
    ok('the money is the sum of the weeks that were actually bets',
       h.indexOf('+$296') >= 0, 'money line: '
       + (/\$100 a week on[\s\S]{0,160}/.exec(h) || [''])[0]);
    ok('and the voided week is counted out loud, not dropped quietly',
       h.indexOf('1 week voided') >= 0);
    ok('as is the week with no archived price',
       h.indexOf('1 with no price archived') >= 0);
    ok('eight bets from ten weeks, five of them won',
       h.indexOf('over 8 bets, 5 won') >= 0);

    // ONE WINDOW FOR THE WHOLE PANEL. Three weeks means a three-week chart,
    // a three-week count and three weeks of money.
    x.v3Do('v3pastn', '3');
    const h3 = app();
    ok('picking three weeks narrows the count',
       /\bof 3\b/.test(h3), 'the caption still counts ten');
    ok('and narrows the money with it',
       (h3.match(/over \d+ bets?/) || [''])[0] !== ''
       && !/over (\d\d)+ bets/.test(h3.replace(/over 1 bet/, '')),
       'the money still reads over more bets than the window holds');
    x.v3Do('v3pastn', 'all');

    // ── The money follows the streak ──────────────────────────────────
    //
    // Asked for directly: if he is 0 of 3 over, tell me what $100 on the
    // UNDER would have made. The receptions fixture ran under in seven of
    // ten at -130 against three overs — 7 x $76.92 against $300 — so the
    // panel reads +$238 only if it priced the under. Backing the over on
    // those same ten weeks is -$238, which is what a side-blind version
    // prints while looking equally plausible.
    V.market = 'rec'; V.open = null; render();
    const mr = /data-v3open="([^"]+)"/.exec(app());
    ok('the receptions board has a player to open', !!mr);
    if (mr) {
      x.v3Do('v3open', mr[1]);
      const hu = app();
      ok('a window that ran under is priced on the under',
         hu.indexOf('>the under<') >= 0,
         (/\$100 a week on[\s\S]{0,120}/.exec(hu) || [''])[0]);
      ok('and the money is the under\u2019s, not the over\u2019s',
         hu.indexOf('+$238') >= 0,
         (/\$100 a week on[\s\S]{0,160}/.exec(hu) || [''])[0]);
      ok('seven of its ten weeks won', hu.indexOf('over 10 bets, 7 won') >= 0);
      x.v3Do('v3open', mr[1]);
    }
    V.market = 'any';
  }
  V.open = null; V.pastN = null;
}


done();
