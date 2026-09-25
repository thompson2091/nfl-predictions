"""site/v3 — the app a casual bettor reads.

v2 is a board: seven tabs, six markets, four filters, every number the project
knows. It is the right tool for someone who already knows what an edge is. v3
is the same data answering a different question — "what should I look at, and
why" — for someone who does not, and will not, learn the vocabulary first.

**The calculation layer is v1's and is not forked.** `rowsFor` normalizes a
touchdown board and a yardage board into one row shape; `betProb`, `ev100`,
`amToDec` and `money` are the arithmetic underneath every figure here. Those
are covered by the existing tests and are imported by `v3.render`, exactly as
v2 imports them. What v3 owns is the shell, the screens and the wording.

Three things this version has that v2 does not, all of them asked for:

- **The week picker is global.** In v2 the picker belongs to a market and has
  to be set again each time you switch. Here it sits in the header, survives
  every navigation, and when it points at a played week EVERY screen shows
  that week's numbers as they were, graded green and red. A past week is a
  different mode, not a different tab, and the header says so in amber so it
  cannot be mistaken for this week's board.
- **Fades are a filter beside the others.** The project's best-measured
  player-level result is a list of people to leave alone, and v2 buried it
  behind a market-specific control.
- **Kickoff times, Eastern.** A slate reads as a weekend rather than as an
  alphabet, and prime time is labeled because it is a real betting split.
"""
from __future__ import annotations

JS = r"""
// ── v3 ──────────────────────────────────────────────────────────────────
//
// Everything below runs AFTER v1's modules, and deliberately shadows their
// `render`, `route` and `go`. v1's page builders come along for the ride and
// are never called; see `v3.render` for why that is cheaper than the refactor
// that would remove them.

const V3TABS = [
  // Games first, and the app opens on it: the slate is the way in, and the
  // player board is what you reach FROM a game more often than the reverse.
  ['games', 'Games', 'M4 5h16v15H4zM4 10h16M9 3v4M15 3v4'],
  ['props', 'Props', 'M12 11a3.5 3.5 0 100-7 3.5 3.5 0 000 7zM5 21c0-3.9 3.1-6 7-6s7 2.1 7 6'],
  ['picks', 'Picks', 'M5 4h14v16l-3-2-2 2-2-2-2 2-2-2-3 2zM9 9h6M9 13h4'],
  ['ladder', 'Ladder', 'M7 3v18M17 3v18M7 7h10M7 12h10M7 17h10'],
];

// key, button label, what the bet pays on, the question the screen answers.
const V3MKT = [
  ['any', 'Scores a TD',
   'Pays if the player scores a touchdown at any point in the game.',
   'Who scores this week?'],
  ['first', 'Scores first',
   'Pays only if the player scores the game’s very first touchdown. Harder, so it pays more.',
   'Who scores first?'],
  ['rec', 'Catches',
   'Pays if the player makes more catches than the number shown.',
   'Who beats their catches line?'],
  ['rush', 'Rushing yds',
   'Pays if the player runs for more yards than the number shown.',
   'Who beats their rushing line?'],
  ['recyds', 'Receiving yds',
   'Pays if the player gains more receiving yards than the number shown.',
   'Who beats their receiving line?'],
  ['passyds', 'Passing yds',
   'Pays if the quarterback throws for more yards than the number shown.',
   'Who beats their passing line?'],
];

// The board's market keys are `any` and `first`; the history files are built
// per TARGET TYPE and named `anytime_td` and `first_td`. Looking one up under
// the other returns undefined, and "no history" renders identically to "no
// weeks played yet" — which is a normal state, so nothing complains. This
// map is the only thing standing between the picker and shipping dead.
const V3HIST = { any: 'anytime_td', first: 'first_td', rec: 'receptions',
  rush: 'rushing_yards', recyds: 'receiving_yards', passyds: 'passing_yards' };

// Every column you can order the board by. `get` returns null where a row
// has no value, and nulls sort last in BOTH directions — a row with no price
// is not the best-priced row, and it is not the worst either.
// THREE ESTIMATES, NAMED SEPARATELY, ALL THREE SORTABLE.
//
// The board carries three numbers for the same event and the first version
// showed two of them under one label. They are not interchangeable:
//   MODEL    `model_only` — what the model says with no sight of the price.
//   BOOK     the de-vigged market price.
//   ADJUSTED `ours` — the blend, which has the book inside it.
// Sorting by "our chance" hid which of the three was being ordered, and on a
// touchdown market `betProb` answers MODEL while on a yardage market it
// answers ADJUSTED — so the same control sorted by different quantities
// depending on the tab you were on.
const V3SORTS = [
  ['model', 'Model', r => has(r.modelOnly) ? r.modelOnly : r.ours],
  ['book', 'Book', r => r.book],
  ['adj', 'Adjusted (blend)', r => r.ours],
  ['edge', 'Edge', r => r.edge],
  ['ev', 'EV per $100', r => ev100(r)],
  ['odds', 'Odds', r => has(r.dec) ? r.dec : null],
  ['proj', 'Projection', r => has(r.proj) ? r.proj : null],
  ['fav', 'Starred first', r => (isFav(r.id) ? 1 : 0)],
  ['player', 'Name', r => r.player],
];

const v3Model = r => has(r.modelOnly) ? r.modelOnly : r.ours;

const V3KEY = 'picksix.v3';
const V3SHOW = 25;

const V = Object.assign({
  tab: 'games', market: 'any', sort: 'model', desc: true, filter: 'all',
  gfilter: 'all',
  week: null, game: null, gameTab: 'notes', cat: 'all',
  picks: {}, betType: 'twos', stake: 10, shown: V3SHOW,
  lodds: 100, rungs: 6, q: '', half: 'full',
  ask: '', answer: '',
  // The saved picks, and which of them the Picks tab is showing. `saved` was
  // a boolean nothing read; the slip and the saved copy are different things
  // and only one of them was ever stored.
  saved: [], savedFilter: 'all', pick: null,
}, v3Load());

function v3Load() {
  try { return JSON.parse(localStorage.getItem(V3KEY) || '{}'); }
  catch (e) { return {}; }
}
// Only the parts worth surviving a reload. The scroll position, the open
// note and the typed question are about this visit.
function v3Save() {
  try {
    localStorage.setItem(V3KEY, JSON.stringify({
      market: V.market, sort: V.sort, filter: V.filter, picks: V.picks,
      betType: V.betType, stake: V.stake, game: V.game,
      desc: V.desc, gfilter: V.gfilter,
      // The saved picks themselves, not a flag. `V.saved` used to be a
      // boolean that nothing read and nothing kept.
      saved: V.saved, savedFilter: V.savedFilter,
      lodds: V.lodds, rungs: V.rungs }));
  } catch (e) { /* private window, blocked storage — the app still works */ }
}

// ── small helpers ───────────────────────────────────────────────────────

// THREE ID SCHEMES, ONE KEY.
//
// Cards and game rows carry `ATL_GB`; the player boards carry
// `2026_03_ATL_GB`. Comparing them raw matched nothing, and matching nothing
// renders as "no priced players in this game" — a legitimate state, so the
// Who-scores tab shipped permanently empty and said something reasonable
// while doing it. The Python side has `_game_key` for the same reason.
function v3Key(gid) {
  const b = String(gid || '').split('_');
  return b.length >= 2 ? b.slice(-2).join('_') : String(gid || '');
}
const v3Same = (a, b) => v3Key(a) === v3Key(b);

// `d` decimals, default none above 10%. A spread and a total are coin flips
// by construction, so a whole-number percentage prints 50% on every one of
// them and hides the only thing that varies — which is the vig, and is the
// reason one side of a total is worth taking over the other.
const v3Pct = (p, d) => !has(p) ? '—'
  : (d != null ? (p * 100).toFixed(d)
     : p < 0.1 ? (p * 100).toFixed(1) : Math.round(p * 100)) + '%';
const v3Win = (s, o) => o < 0 ? s * 100 / -o : s * o / 100;
const v3Dash = s => String(s == null ? '' : s).replace(/-/g, '−');

// The value verdict, in words rather than in a number nobody asked for.
//
// The thresholds are not fitted and are not claimed to be: +5 and -10 per
// $100 are wide enough that a row has to disagree with the book clearly
// before it is labeled, which is the point. `ev100` is v1's and already
// prefers the model-only probability on a touchdown market, where the blend
// has the book baked into it and would grade the book against itself.
function v3Value(row) {
  const ev = ev100(row);
  const scr = v3Script(row);
  if (!has(ev)) return ['', ''];
  if (ev >= 5) return ['Good value', 'tag tag--good'];
  if (ev <= -10) return ['Pricey', 'tag tag--bad'];
  return ['Fair price', 'tag'];
}

function v3Payout(row) {
  if (!has(row.odds)) return '';
  return '$10 wins $' + v3Win(10, row.odds).toFixed(2);
}

// What the bet actually is, spelled out. A yardage row is only meaningful
// with its line attached, and "Over 24.5" is the bet where "24.5" is trivia.
function v3Line(row) {
  if (row.kind !== 'ou' || !has(row.line)) return '';
  const u = unitOf(row.key) || '';
  const side = row.take === 'under' ? 'Under' : 'Over';
  const proj = has(row.proj) ? ' · we project ' + row.proj.toFixed(1) : '';
  return side + ' ' + row.line + (u ? ' ' + u : '') + proj;
}

function v3MktLabel() {
  const m = V3MKT.filter(x => x[0] === V.market)[0];
  return m ? m[1].toLowerCase() : V.market;
}

function v3Fixture(row) {
  const bits = [row.team, row.pos].filter(Boolean).join(' ');
  return [bits, row.game].filter(Boolean).join(' · ');
}

// ── the week picker, which is global ────────────────────────────────────

// WHICH WEEKS THE PICKER OFFERS depends on the screen, because the two
// archives genuinely differ: the props board needs play-by-play and the games
// board needs archived LINES, and a week can have one without the other.
// Offering a week the current screen cannot show is how the picker came to
// look broken on the landing page.
function v3Weeks() {
  // Slip and Ladder do not vary by week, so they offer none — and because
  // this one function decides, the header hides the control and `v3Do` drops
  // a stale week on the way in, from the same answer.
  if (V.tab === 'picks' || V.tab === 'ladder') return [];
  if (V.tab === 'games') {
    return Object.keys(((DATA.games || {}).past) || {})
      .map(Number).filter(n => !isNaN(n)).sort((a, b) => a - b);
  }
  const h = (DATA.history || {})[V3HIST[V.market]] || {};
  return (h.has || []).slice().sort((a, b) => a - b);
}

function v3Header() {
  const weeks = v3Weeks();
  // No weeks offered, no control — rather than an empty one that looks
  // usable. `v3Weeks` is the single answer to which weeks a screen has.
  if (!weeks.length) {
    return '<header class="hd">'
      + '<div class="hd__b">' + esc(DATA.brand || 'Pick Six') + '</div>'
      + '<div class="wk" style="border:0;background:transparent">'
      + esc((DATA.season || '') + ' \u00b7 week ' + (DATA.week || ''))
      + '</div></header>';
  }
  const past = V.week != null;
  const opts = ['<option value="">This week</option>'].concat(
    weeks.map(w => '<option value="' + w + '"' +
      (V.week === w ? ' selected' : '') + '>Week ' + w + '</option>')).join('');
  return '<header class="hd">'
    + '<div class="hd__b">' + esc(DATA.brand || 'Pick Six') + '</div>'
    + '<div class="wk' + (past ? ' wk--past' : '') + '">'
    + (past ? 'Showing ' : '')
    + '<select data-v3week aria-label="Which week to show">' + opts + '</select>'
    + '</div></header>';
}

// Said on the page rather than left to the picker's own styling. A reader who
// has scrolled past the header needs to know these numbers are settled.
function v3PastBanner() {
  if (V.week == null) return '';
  const h = (DATA.history || {})[V3HIST[V.market]] || {};
  const acc = (h.accuracy || {})[String(V.week)] || {};
  const n = acc.n;
  return '<div class="past">Week ' + V.week + ' has been played. These are the '
    + 'numbers as they stood before kickoff, with what happened marked '
    + 'against them'
    + (has(n) ? ' — ' + n + ' priced picks graded.' : '.')
    + '</div>';
}

// ── past-week rows, fetched on demand ───────────────────────────────────
//
// The rows live in `data/h-<market>-<week>.json` rather than in the page: a
// full season across six markets measured 20MB inlined. The index stays in
// the payload so the picker can draw itself without fetching, which is why
// it never flickers.

const V3CACHE = {};

// A FAILED FETCH IS NOT AN EMPTY WEEK, AND SAYING SO IS THE WHOLE FIX.
//
// `.catch(() => [])` turned every failure into "no rows", which renders as
// "no priced picks recorded" — indistinguishable from a week that genuinely
// had none. The commonest failure is not a missing file: it is opening
// index.html from the filesystem, where the browser blocks `fetch` for
// `file://` outright. Every past week on every market came back empty and
// the page explained it away.
function v3Fetch(market, week, then) {
  const k = market + ':' + week;
  if (V3CACHE[k]) { then(V3CACHE[k]); return; }
  const path = (DATA.history_path || 'data/h-{market}-{week}.json')
    .replace('{market}', market).replace('{week}', String(week));
  const fail = why => { V3CACHE[k] = { error: why }; then(V3CACHE[k]); };
  let p;
  try { p = fetch(path); } catch (e) { fail(String(e)); return; }
  p.then(r => {
    if (!r.ok) { fail('the server answered ' + r.status + ' for ' + path); return; }
    return r.json().then(rows => { V3CACHE[k] = { rows: rows || [] };
                                   then(V3CACHE[k]); });
  }).catch(e => fail(
    location.protocol === 'file:'
      ? 'past weeks are separate files, and a browser will not let a page '
        + 'opened from your filesystem read them. Serve the folder over http '
        + '(python3 -m http.server) and they will load.'
      : 'could not load ' + path + ' (' + e + ')'));
}

// A graded row, normalized onto the same field names the live rows use, so
// every renderer below is written once. `won` is the only addition, and it is
// three-valued: true, false, or null for a pick that was never settled.
function v3Graded(market, raw) {
  const td = market === 'anytime_td' || market === 'first_td';
  return (raw || []).map(r => ({
    kind: td ? 'td' : 'ou', key: V.market,
    player: r.player_name, team: r.team,
    game: fixtureOf(r.game_id), gameId: r.game_id || '',
    ours: td ? r.probability : r.ours,
    modelOnly: td ? r.prob_model : r.model,
    book: r.book, odds: r.odds, dec: has(r.odds) ? amToDec(r.odds) : null,
    line: r.line, proj: r.proj, lo: r.lo, hi: r.hi,
    edge: r.edge, take: r.side, rank: r.rank,
    // ABSENT IS NOT FALSE. The first-TD board has never carried
    // `has_market_price`, so `!!undefined` marked all 500 rows unpriced and
    // the market rendered "no priced picks recorded" on every past week —
    // indistinguishable from a week whose board was genuinely empty.
    priced: td ? (r.has_market_price == null ? true : !!r.has_market_price)
               : has(r.line),
    actual: r.actual,
    // WHAT THEY ACTUALLY HAD. The touchdown boards grade to a tick and never
    // said whether it was one score or three; `tdCount` is that number and
    // `tdOrder` which touchdown of the game was theirs, so a first-TD miss
    // can say how close it came instead of only that it lost.
    tdCount: r.td_count, tdOrder: r.td_order,
    won: td ? (has(r.scored) ? !!r.scored : null)
            : (r.won == null ? null : !!r.won),
  }));
}

// ── screen: this week ───────────────────────────────────────────────────

function v3Screen() {
  switch (V.tab) {
    case 'props': return v3Week();
    case 'picks': return v3Picks();
    case 'ladder': return v3Ladder();
    default: return V.game ? v3Game(V.game) : v3Games();
  }
}

// The market pills and the three filters, built once because two screens
// show them and a control added to one has to appear on the other.
function v3MarketControls() {
  const cur = V3MKT.filter(m => m[0] === V.market)[0] || V3MKT[0];
  // Inside a game each button carries how many players it holds, because a
  // market can hold none and the only way to find out was to tap it.
  const mkts = V3MKT.filter(m => served(m[0])).map(m => {
    const n = V.game ? v3GameMkt(m[0], V.game) : null;
    return '<button class="mkt' + (n === 0 ? ' mkt--none' : '')
      + '" data-v3mkt="' + m[0] + '" aria-pressed="'
      + (m[0] === V.market) + '">' + esc(m[1])
      + (n === null ? '' : ' <i>' + n + '</i>') + '</button>';
  }).join('');
  const filterHelp = {
    all: '',
    short: 'Our shortlist: the picks this project would actually place.',
    fav: 'Players you have starred. The same list v2 uses.',
    fade: 'Players priced above our number. These are bets to LEAVE ALONE, '
        + 'not bets to place \u2014 no book posts the other side.',
  }[V.filter] || '';
  return '<div class="mkts">' + mkts + '</div>'
    + '<p class="help">' + esc(cur[2]) + '</p>'
    + '<div class="seg seg--4">'
    + v3Seg('v3filter', [['all', 'Everyone'], ['short', 'Shortlist'],
                         ['fade', 'Fades'], ['fav', 'Starred']], V.filter)
    + '</div>'
    + (filterHelp ? '<p class="help">' + esc(filterHelp) + '</p>' : '');
}

function v3Week() {
  const cur = V3MKT.filter(m => m[0] === V.market)[0] || V3MKT[0];

  const filterHelp = {
    all: '',
    short: 'Our shortlist: the picks this project would actually place.',
    fav: 'Players you have starred. The same list v2 uses.',
    fade: 'Players priced above our number. These are bets to LEAVE ALONE, '
        + 'not bets to place \u2014 no book posts the other side.',
  }[V.filter] || '';

  return '<div class="wrap">'
    + v3PastBanner()
    + '<h1 class="h1">' + esc(V.week == null ? cur[3] : 'Week ' + V.week) + '</h1>'
    + '<p class="lede">Our number next to the sportsbook\u2019s.'
    + (V.week == null ? ' Tap a row for everything we know about it.' : '')
    + '</p>'
    + v3MarketControls()
    // ONLY ON A LIVE WEEK. On a graded week the prices stopped moving and
    // "the market has moved toward us on 9 of 14" is a fact about the past
    // dressed as one about a board you could still bet.
    + (V.week == null
       ? v3ClvNote(rowsFor(V.market, null).filter(r => r.priced && !r.blocked),
                   'of the picks on this market')
       : '')
    + v3GamePicker()
    + v3Search()
    + v3SortBar()
    + '<div class="list" id="v3rows">' + v3Rows() + '</div>'
    + v3Explainer()
    + '</div>';
}

// THE GAME FILTER, AND IT SURVIVES THE MARKET.
//
// Asked for directly: "a lot of times I'm looking at a specific game and
// clicking between the markets and need to reselect the game every time".
// `v3Do` deliberately leaves `V.game` alone on a market change.
function v3GamePicker() {
  const cards = v3GameSet().cards || [];
  if (!cards.length) return '';
  const opts = ['<option value="">All games</option>'].concat(
    cards.map(c => '<option value="' + esc(c.game_id) + '"'
      + (V.game === c.game_id ? ' selected' : '') + '>'
      + esc(c.away + ' at ' + c.home) + '</option>')).join('');
  return '<div class="picker' + (V.game ? ' picker--on' : '') + '">'
    + '<span class="eyebrow">Game</span>'
    + '<select data-v3gamesel aria-label="Filter to one game">' + opts
    + '</select></div>';
}

// Sort by any column, either way. The two presets the casual reader wants are
// just two of the columns, so there is one control rather than a tidy pair
// that cannot express "order by expected value ascending".
// SEARCH, above every player list.
//
// Five hundred priced players and a scroll. Typing three letters is the
// difference between "is my guy on here" taking a second and taking a minute.
//
// The input is NOT re-rendered while you type — `v3Rows` is patched in place
// and the box keeps focus and caret. Re-rendering the field being typed into
// is the bug that made v2's search unusable and drops a character on every
// keystroke.
function v3Search() {
  return '<div class="search">'
    + '<input type="search" data-v3q placeholder="Search players" '
    + 'value="' + esc(V.q || '') + '" aria-label="Search players">'
    + (V.q ? '<button class="searchx" data-v3clearq="1" '
             + 'aria-label="Clear search">\u2715</button>' : '')
    + '</div>';
}

function v3SortBar() {
  const opts = V3SORTS.map(c => '<option value="' + c[0] + '"'
    + (V.sort === c[0] ? ' selected' : '') + '>' + esc(c[1]) + '</option>')
    .join('');
  return '<div class="picker">'
    + '<span class="eyebrow">Sort by</span>'
    + '<select data-v3sortsel aria-label="Sort the board">' + opts + '</select>'
    + '<button class="dirbtn" data-v3dir="1" aria-label="'
    + (V.desc ? 'Highest first' : 'Lowest first') + '">'
    + (V.desc ? '\u2193 High' : '\u2191 Low') + '</button></div>';
}

function v3Seg(attr, opts, on) {
  return opts.map(o => '<button data-' + attr + '="' + o[0] + '" aria-pressed="'
    + (o[0] === on) + '">' + esc(o[1]) + '</button>').join('');
}

function v3Sorted(rows) {
  const col = V3SORTS.filter(c => c[0] === V.sort)[0] || V3SORTS[0];
  const get = col[2];
  const out = rows.slice();
  out.sort((a, b) => {
    const x = get(a), y = get(b);
    // Nulls last whichever way the arrow points. Flipping the direction
    // should reorder the rows that HAVE a value, not promote the ones that
    // do not to the top of the board.
    if (x == null && y == null) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    const c = typeof x === 'string' ? x.localeCompare(y) : x - y;
    return V.desc ? -c : c;
  });
  return out;
}

function v3Rows() {
  // A past week is fetched, so this returns a placeholder and the fetch
  // re-renders into the same node. Rendering nothing while it lands would
  // read as an empty week, which is a legitimate state and so invisible.
  if (V.week != null) {
    const mk = V3HIST[V.market], k = mk + ':' + V.week;
    if (!V3CACHE[k]) {
      v3Fetch(mk, V.week, () => {
        const host = document.getElementById('v3rows');
        if (host) host.innerHTML = v3Rows();
      });
      return '<div class="empty">Loading week ' + V.week + '…</div>';
    }
    // A FAILURE IS NOT AN EMPTY WEEK. See `v3Fetch`: the commonest cause is
    // the page being opened from the filesystem, where the browser refuses
    // to fetch the week files at all, and the old code rendered that as "no
    // priced picks recorded" — which is what a genuinely empty week says.
    if (V3CACHE[k].error) {
      return '<div class="empty"><b>Week ' + V.week + ' did not load.</b><br>'
        + esc(V3CACHE[k].error) + '</div>';
    }
    let rows = v3Graded(mk, V3CACHE[k].rows).filter(r => r.priced);
    if (V.game) rows = rows.filter(r => v3Same(r.gameId, V.game));
    rows = v3Match(rows);
    if (!rows.length) {
      if (V.game && !V.q) return v3GameEmpty(V.game);
      return '<div class="empty">No priced picks recorded '
        + 'for week ' + V.week + ' on this market. The week loaded; the board '
        + 'carried no priced rows for it.</div>';
    }
    return v3Sorted(rows).slice(0, V.shown).map(v3PastRow).join('')
      + v3MoreBtn(rows.length);
  }

  // `rowsFor` knows 'short' and 'fade'; 'fav' and 'all' are the full board
  // filtered here. Passing 'fav' through would return nothing and read as an
  // empty week.
  const view = (V.filter === 'short' || V.filter === 'fade') ? V.filter : null;
  let rows = rowsFor(V.market, view).filter(r => r.priced && !r.blocked);
  if (V.filter === 'fav') rows = rows.filter(r => isFav(r.id));
  if (V.game) rows = rows.filter(r => v3Same(r.gameId, V.game));
  rows = v3Match(rows);
  if (!rows.length) {
    if (V.game && !V.q && V.filter === 'all') return v3GameEmpty(V.game);
    return '<div class="empty">' + (V.filter === 'fade'
      ? 'Nothing on this market is priced far enough above our number to '
        + 'flag this week.'
      : V.q
      ? 'No player matching \u201c' + esc(V.q) + '\u201d on this market.'
      : V.filter === 'fav'
      ? 'Nothing starred on this market. Tap the star beside a player to '
        + 'keep them here.'
      : 'No priced players on this market yet.') + '</div>';
  }
  return v3Sorted(rows).slice(0, V.shown).map(v3Row).join('')
    + v3MoreBtn(rows.length);
}

function v3MoreBtn(total) {
  if (total <= V.shown) return '';
  return '<button class="more" data-v3more="1">See all ' + total
    + ' players</button>';
}

function v3Row(row) {
  const v = v3Value(row);
  const inSlip = !!V.picks[row.id];
  const line = v3Line(row);
  const open = V.open === row.id;
  // TWO SOURCES, AND THE REPORT WINS.
  //
  // `row.status` is the roster's code — ACT, RES, INA — which says whether a
  // player is on the team. The injury REPORT says whether he will play, and
  // it is the one that decides a bet: a Questionable receiver is active on
  // the roster and a coin flip in a prop. Shown together where they differ.
  const inj = (DATA.injuries || {})[row.player];
  const warn = (inj
    ? '<span class="' + (inj.s === 'Out' ? 'tag tag--bad'
        : inj.s === 'Doubtful' ? 'tag tag--warn' : 'tag tag--warn') + '">'
      + esc(inj.s) + (inj.i ? ' \u00b7 ' + esc(inj.i) : '') + '</span>'
    : '')
    + (row.status && row.status !== 'ACT'
       ? '<span class="tag tag--warn">' + esc(row.status) + '</span>' : '');
  const ev = ev100(row);
  const scr = v3Script(row);
  // The strip carries the numbers the old board carried, on the row, so the
  // common case needs no tap: our number, the book's, the gap, and what the
  // gap is worth. Asked for: "I kinda liked being able to see all of the data
  // in the main view as opposed to clicking in."
  const strip = '<div class="strip num">'
    + v3Cell('Model', v3Pct(v3Model(row), 1))
    + v3Cell('Book', v3Pct(row.book, 1))
    + v3Cell('Adjusted', v3Pct(row.ours, 1))
    + v3Cell('Edge', has(row.edge) ? (row.edge > 0 ? '+' : '')
        + row.edge.toFixed(1) + 'pp' : '\u2014',
        has(row.edge) ? (row.edge > 0 ? 'good' : 'bad') : '')
    + v3Cell('EV/$100', has(ev) ? (ev > 0 ? '+$' : '\u2212$')
        + Math.abs(ev).toFixed(2) : '\u2014',
        has(ev) ? (ev > 0 ? 'good' : 'bad') : '')
    + '</div>';
  return '<div class="row' + (open ? ' row--open' : '') + '">'
    + '<button class="rowbtn" data-v3open="' + esc(row.id) + '" '
    + 'aria-expanded="' + open + '"><div class="row__m">'
    + '<div class="row__t"><div style="min-width:0">'
    + '<div class="name">' + esc(row.player) + '</div>'
    + '<div class="sub">' + esc(v3Fixture(row)) + '</div>'
    + (line ? '<div class="line">' + esc(line) + '</div>' : '')
    + '</div><div class="chance">'
    + (has(row.odds) ? '<span class="pill num">' + v3Dash(american(row.odds))
        + '</span>' : '')
    + '<span class="sub num">' + esc(v3Payout(row)) + '</span>'
    + '</div></div>'
    + strip
    + '<div class="tags">'
    + (v[0] ? '<span class="' + v[1] + '">' + v[0] + '</span>' : '')
    + warn
    + (row.thin ? '<span class="tag tag--warn">Thin market</span>' : '')
    + (scr ? '<span class="tag tag--warn">Script risk</span>' : '')
    + '<span class="tag">' + (open ? 'Hide detail' : 'More') + '</span>'
    + '</div></div></button>'
    + '<div class="rowacts">'
    + v3Star(row)
    + '<button class="add" data-v3pick="' + esc(row.id) + '" aria-pressed="'
    + inSlip + '" aria-label="' + (inSlip ? 'Remove ' : 'Add ')
    + esc(row.player) + '">' + (inSlip ? '\u2713' : '+') + '</button>'
    + '</div>'
    + (open ? v3Detail(row) : '')
    + '</div>';
}

// FAVORITES, ON v1's STORAGE RATHER THAN A SECOND LIST.
//
// `isFav` and `toggleFav` are v1's and already in the bundle, keyed by the
// same row id v2 uses. Sharing the store means a player starred in v2 is
// starred here — two lists under two keys would be the same feature twice,
// disagreeing.
// WHAT THIS PICK IS RIDING ON.
//
// A projection assumes a game. Thursday's Green Bay backs were projected on
// an ordinary afternoon and spent the second half three scores behind, and
// nothing on the page had said the number assumed a game that did not happen.
//
// `script_risk` measures how much each market moves with the final margin —
// rushing a lot, receiving barely — and `score_dist` says how likely each
// margin is here. Only flagged where BOTH are true: the market is genuinely
// script-dependent, and this game has a real chance of the script that hurts.
function v3Script(row) {
  const g = (v3GameSet().cards || []).filter(
    c => v3Same(c.game_id, row.gameId))[0];
  const sc = g && g.script;
  if (!sc || !row.team || !row.pos) return null;
  const hit = sc[row.team + '|' + row.pos + '|' + row.key];
  // Below a one-in-eight chance of the bad script this is a caveat nobody
  // needs; the flag is worth having only while it could actually happen.
  if (!hit || hit.p < 0.12) return null;
  return hit;
}

function v3Star(row) {
  const on = isFav(row.id);
  return '<button class="star" data-v3fav="' + esc(row.id) + '" '
    + 'aria-pressed="' + on + '" aria-label="'
    + (on ? 'Unstar ' : 'Star ') + esc(row.player) + '">'
    + (on ? '\u2605' : '\u2606') + '</button>';
}

function v3Cell(label, value, tone) {
  return '<span class="cell"><b' + (tone ? ' class="' + tone + '"' : '')
    + '>' + value + '</b><i>' + esc(label) + '</i></span>';
}

// Everything the board knows about one row. Asked for: "I kinda thought that
// clicking on this condensed view of a player would show full stats."
//
// Built from fields that may be absent, so each is emitted only when it has a
// value — a detail panel of eleven em-dashes says less than four real numbers.
function v3Detail(row) {
  const f = [];
  const add = (l, v) => { if (v != null && v !== '') f.push([l, v]); };
  add('Model (no price)', v3Pct(row.modelOnly, 1));
  add('Book (de-vigged)', v3Pct(row.book, 1));
  add('Adjusted (blend)', v3Pct(row.ours, 1));
  add('Priced on', has(row.modelOnly) && row.kind === 'td'
    ? 'Model' : 'Adjusted');
  add('Edge', has(row.edge)
    ? (row.edge > 0 ? '+' : '') + row.edge.toFixed(1) + 'pp' : null);
  add('Price', has(row.odds) ? v3Dash(american(row.odds)) : null);
  add('Best price', has(row.best)
    ? v3Dash(american(row.best)) + (row.bestBook ? ' at ' + row.bestBook : '')
    : null);
  add('Opened at', has(row.openOdds) ? v3Dash(american(row.openOdds)) : null);
  // Raw against raw. See `v3NowImplied`: against `book` this read the
  // overround and flipped the sign on 316 of 814 rows.
  if (has(row.openImplied) && has(v3NowImplied(row))) {
    const mv = (v3NowImplied(row) - row.openImplied) * 100;
    add('Moved', (mv > 0 ? '+' : '') + mv.toFixed(1) + 'pp since open');
  }
  add('Line', has(row.line) ? row.line + ' ' + (unitOf(row.key) || '') : null);
  add('We project', has(row.proj) ? row.proj.toFixed(1) : null);
  if (has(row.lo) && has(row.hi))
    add('Likely range', row.lo.toFixed(1) + ' to ' + row.hi.toFixed(1));
  add('Books quoting', has(row.nBooks) ? String(row.nBooks) : null);
  add('Board rank', has(row.rank) ? '#' + row.rank : null);
  add('Position', row.pos);
  add('Availability', row.status);
  const scr = v3Script(row);
  if (scr) {
    add('If the game goes badly',
        Math.round((1 - scr.mult) * 100) + '% lower, and there is a '
        + Math.round(scr.p * 100) + '% chance of it');
    add('Script tilt', scr.tilt > 1
        ? '+' + Math.round((scr.tilt - 1) * 100) + '% on the likely scripts'
        : Math.round((scr.tilt - 1) * 100) + '% on the likely scripts');
  }
  const rep = (DATA.injuries || {})[row.player];
  if (rep) {
    add('Injury report', rep.s + (rep.i ? ' \u00b7 ' + rep.i : ''));
    add('Practice', rep.p);
  }
  add('Our read', row.read);
  return '<div class="detail"><dl>'
    + f.map(x => '<div><dt>' + esc(x[0]) + '</dt><dd class="num">' + x[1]
        + '</dd></div>').join('')
    + '</dl></div>';
}

// WHAT HAPPENED, IN THE ROW'S OWN UNITS.
//
// Three markets settle on three different quantities and the row has space
// for one short phrase. An over/under line settles on the stat, so it prints
// the stat. An anytime board settles on whether they scored, so it prints how
// many. A first-TD board settles on WHICH touchdown was theirs, and printing
// a count there would put "1 TD" beside a cross on every player who scored
// second — true, and an answer to a question nobody asked.
//
// Empty when nothing was recorded, so a row that cannot say what happened
// says nothing rather than "0".
function v3Ord(n) {
  const t = n % 100;
  const s = (t >= 11 && t <= 13) ? 'th'
    : n % 10 === 1 ? 'st' : n % 10 === 2 ? 'nd' : n % 10 === 3 ? 'rd' : 'th';
  return n + s;
}

function v3Had(row) {
  if (row.key === 'first_td') {
    if (!has(row.tdCount)) return '';
    if (!row.tdCount) return 'no TD';
    return has(row.tdOrder)
      ? v3Ord(row.tdOrder) + ' TD of the game' : 'scored';
  }
  if (row.kind === 'td') {
    if (!has(row.tdCount)) return '';
    return !row.tdCount ? 'no TD'
      : row.tdCount + (row.tdCount === 1 ? ' TD' : ' TDs');
  }
  if (!has(row.actual)) return '';
  const u = unitOf(row.key) || '';
  return row.actual + (u ? ' ' + u : '');
}

// A settled row. The color IS the information: green won, red lost, gray
// never settled. Everything else is what was shown before kickoff, unchanged,
// so the two can be compared.
function v3PastRow(row) {
  const won = row.won;
  const cls = won === true ? ' row--won' : won === false ? ' row--lost' : '';
  const mark = won === true ? '<span class="mark mark--won">✓</span>'
    : won === false ? '<span class="mark mark--lost">✕</span>'
    : '<span class="mark mark--void">–</span>';
  const line = v3Line(row);
  // The row tint and the mark already say won or lost; this says by how
  // much. Left neutral on purpose — the same fact in three colors is noise.
  const had = v3Had(row);
  const got = had ? '<span class="tag num">' + esc(had) + '</span>' : '';
  return '<div class="row' + cls + '"><div class="row__m">'
    + '<div class="row__t"><div style="min-width:0">'
    + '<div class="name">' + esc(row.player) + '</div>'
    + '<div class="sub">' + esc(v3Fixture(row)) + '</div>'
    + (line ? '<div class="line">' + esc(line) + '</div>' : '')
    + '</div><div class="chance"><b class="num">' + v3Pct(betProb(row))
    + '</b><span class="eyebrow">We said</span></div></div>'
    + '<div class="tags">'
    + (has(row.odds) ? '<span class="pill num">' + v3Dash(american(row.odds))
        + '</span>' : '')
    + got
    + (has(row.book) ? '<span class="sub num">book ' + v3Pct(row.book)
        + '</span>' : '')
    + '</div></div>' + mark + '</div>';
}

function v3Explainer() {
  return '<div class="card"><div class="name">How to read a pick</div>'
    + '<p class="lede" style="font-size:15px;line-height:20px">'
    + '<b style="color:var(--ink)">Our chance</b> is how often we think it '
    + 'happens. <b style="color:var(--ink)">Good value</b> means that at this '
    + 'price, the bet should come out ahead over time if our chance is right. '
    + '<b style="color:var(--ink)">Pricey</b> means the sportsbook is charging '
    + 'too much. A likely pick can still be pricey. We rate prices; you decide '
    + 'what to bet.</p></div>';
}

// THE ADJUSTED WIN PROBABILITY, derived the same way everywhere.
//
// `game_blend` fits a weight on the SPREAD; the win probability has to move
// by the same fraction, or the adjusted number on the list and the adjusted
// bar on the game page are two different quantities with one name.
function v3AdjWin(c) {
  if (!c || !c.blend || !has(c.blend.spread) || !has(c.spread)
      || !has(c.model_spread) || !has(c.win_home) || !has(c.model_win_home))
    return null;
  const denom = c.model_spread - c.spread;
  const w = denom ? (c.blend.spread - c.spread) / denom : 0;
  return c.win_home + w * (c.model_win_home - c.win_home);
}

function v3Kick(c) {
  const when = [c.kick_day, c.kick_et].filter(Boolean).join(' ');
  return when + (c.prime ? ' · prime time' : '');
}

// ── screen: games ───────────────────────────────────────────────────────

// THE WEEK SELECTOR APPLIES HERE TOO.
//
// It was honoured only by the props board. Games then became the landing
// page, so the picker sat in the header on the first screen anyone sees and
// changed nothing — the most convincing kind of broken. The payload has
// carried `games.past` all along.
function v3GameSet() {
  if (V.week == null) return DATA.games || {};
  const p = ((DATA.games || {}).past || {})[String(V.week)];
  return p ? { cards: p.cards || [], rows: p.rows || [], past: true }
           : { cards: [], rows: [], past: true, absent: true };
}

function v3Games() {
  const g = v3GameSet();
  const cards = g.cards || [];
  if (!cards.length) {
    return '<div class="wrap">' + v3PastBanner() + '<h1 class="h1">Games</h1>'
      + '<div class="card"><p class="lede" style="font-size:15px">'
      + (g.absent
         ? 'No game lines were archived for week ' + V.week + '.'
         : 'No game lines have been captured for this week yet. The board is '
           + 'built from an odds archive, and until it runs there is nothing '
           + 'here to show.')
      + '</p></div></div>';
  }
  // THE LEAN IS DERIVED FROM THE NUMBER THE CARD PRINTS.
  //
  // It used to come from the sign of `model_spread` while the percentage came
  // from `model_win_home`, and on a near-pick'em the two disagree: CIN at PIT
  // had the model at -0.7 (home favored, so the tag said "picks the other
  // side") and the model win probability at 48.5% for the home side, which
  // favors the AWAY team. Both honest, both from the model, contradicting
  // each other on the same card. Where a win probability exists it decides,
  // because it is the one on screen.
  const lean = c => {
    const haveP = has(c.win_home) && has(c.model_win_home);
    if (!haveP && (!has(c.spread) || !has(c.model_spread))) return ['', ''];
    if (haveP) {
      const d = (c.model_win_home - c.win_home) * 100;
      if ((c.win_home >= 0.5) !== (c.model_win_home >= 0.5))
        return ['Our model picks the other side', 'tag tag--warn'];
      if (Math.abs(d) < 3) return ['Our model agrees', 'tag'];
      // "Closer" and "by more" are about the FAVORITE, so the sign has to be
      // read from the favorite's side rather than from the home side.
      const towardFav = (c.win_home >= 0.5) ? d > 0 : d < 0;
      return [towardFav ? 'Our model: by more' : 'Our model: a closer game',
              'tag tag--ours'];
    }
    const d = c.model_spread - c.spread;
    if ((c.spread < 0) !== (c.model_spread < 0))
      return ['Our model picks the other side', 'tag tag--warn'];
    if (Math.abs(d) < 1) return ['Our model agrees', 'tag'];
    return [Math.abs(c.model_spread) < Math.abs(c.spread)
      ? 'Our model: a closer game' : 'Our model: by more', 'tag tag--ours'];
  };
  // A SEPARATE FILTER FROM THE BOARD'S, because they are different sets.
  // Sharing `V.filter` meant picking "Fades" on This week and arriving here
  // with no segment pressed and every game shown, or picking "Model
  // disagrees" and going back to a board silently unfiltered.
  const FGROUPS = {
    all: () => true,
    flip: c => lean(c)[1] === 'tag tag--warn',
    agree: c => lean(c)[1] === 'tag',
    diff: c => lean(c)[1] !== 'tag',
  };
  const flips = cards.filter(FGROUPS.flip).length;
  const agree = cards.filter(FGROUPS.agree).length;
  const show = cards.filter(FGROUPS[V.gfilter] || FGROUPS.all);

  const rows = show.map(c => {
    const l = lean(c);
    const fav = has(c.spread)
      ? (c.spread < 0 ? c.home : c.away) + ' by ' + Math.abs(c.spread) : '';
    const tot = has(c.total) ? c.total + ' total pts' : '';
    // THE SAME THREE NUMBERS THE PLAYER ROWS CARRY, EACH UNDER ITS LABEL.
    //
    // This printed a lean — "our model picks the other side" — beside a bare
    // "CIN 63% to win", where the 63% was the BOOK's number with nothing
    // saying so. Read together the two contradict each other. Book, model and
    // the gap are now labeled, and the lean becomes a summary of numbers
    // that are on the screen rather than a claim about numbers that are not.
    // EVERY CELL NAMES ITS TEAM. "63.0% CIN · book" beside a bare "51.5%
    // model" reads as two teams' numbers, and on this very card the model's
    // 51.5% belongs to the SAME side as the book's 63% — so the reader who
    // assumes otherwise gets the direction backwards.
    const mw = has(c.model_win_home) ? c.model_win_home : null;
    const aw = v3AdjWin(c);
    const side = has(c.win_home) && c.win_home >= 0.5 ? c.home : c.away;
    const forSide = v => v == null ? null
      : (side === c.home ? v : 1 - v);
    const bookPct = forSide(has(c.win_home) ? c.win_home : null);
    const modelPct = forSide(mw);
    const adjPct = forSide(aw);
    const gap = (bookPct == null || modelPct == null) ? null
      : (modelPct - bookPct) * 100;
    const cell = (label, v) => v == null ? ''
      : v3Cell(label, esc(side) + ' ' + v3Pct(v, 1));
    // THE RESULT, where the week has been played. Green when the side the
    // book favored won, red when it did not — the same three-valued mark
    // the props board uses, because a game with no final is not a loss.
    const played = has(c.final_home) && has(c.final_away);
    const won = !played ? null
      : (side === c.home ? c.final_home > c.final_away
                         : c.final_away > c.final_home);
    const finalTxt = !played ? ''
      : '<span class="tags"><span class="' + (won ? 'tag tag--good'
          : 'tag tag--bad') + '">' + esc(c.away) + ' ' + c.final_away
        + '\u2013' + c.final_home + ' ' + esc(c.home) + '</span>'
        + '<span class="sub">' + (won ? esc(side) + ' won' : esc(side)
            + ' lost') + '</span></span>';
    const strip = bookPct == null ? ''
      : '<span class="strip num" style="grid-template-columns:repeat(4,auto);'
        + 'justify-content:start;gap:16px">'
        + cell('book', bookPct)
        + cell('model', modelPct)
        + cell('adjusted', adjPct)
        + (gap == null ? '' : v3Cell('gap', (gap > 0 ? '+' : '')
            + gap.toFixed(1) + 'pp',
            Math.abs(gap) < 3 ? '' : (gap > 0 ? 'good' : 'bad')))
        + '</span>';
    return '<a class="g" data-v3game="' + esc(c.game_id) + '"><div class="g__m">'
      + '<span class="kick">' + esc(v3Kick(c)) + '</span>'
      + '<span class="name">' + esc(c.away) + ' at ' + esc(c.home) + '</span>'
      + '<span class="sub num">' + esc([fav, tot].filter(Boolean).join(' \u00b7 '))
      + '</span>'
      + strip
      + finalTxt
      + (l[0] ? '<span class="tags"><span class="' + l[1] + '">' + l[0]
          + '</span></span>' : '')
      + '</div><span class="chev">\u203a</span></a>';
  }).join('');

  return '<div class="wrap">'
    + v3PastBanner()
    + '<h1 class="h1">' + (V.week == null ? 'Games' : 'Week ' + V.week) + '</h1>'
    + '<p class="lede">' + (V.week == null
      ? 'Who the sportsbooks expect to win, and where our model sees it '
        + 'differently. Tap a game for the notes.'
      : 'What the market and our model said before each of these kicked off, '
        + 'with the final score.') + '</p>'
    + '<div class="card"><div class="stats">'
    + '<div class="stat"><span class="eyebrow">Games</span><b class="num">'
    + cards.length + '</b></div>'
    + '<div class="stat"><span class="eyebrow">Upset picks</span><b class="num">'
    + flips + '</b></div>'
    + '<div class="stat"><span class="eyebrow">Model agrees</span><b class="num">'
    + agree + '</b></div></div></div>'
    + '<div class="seg seg--4">'
    + v3Seg('v3gfilter', [['all', 'All'], ['flip', 'Upset picks'],
                          ['agree', 'Agrees'], ['diff', 'Disagrees']],
            V.gfilter)
    + '</div>'
    + '<div class="list">' + (rows || '<div class="empty">'
      + (V.gfilter === 'flip'
         ? 'Our model picks the same winner as the book in every game this week.'
         : V.gfilter === 'agree'
         ? 'Our model differs from the book on every game this week.'
         : V.gfilter === 'diff'
         ? 'Our model and the book are within a point of each other on every '
           + 'game this week.'
         : 'No games on the board yet.') + '</div>')
    + '</div>'
    + '<div class="card"><div class="name">Reading a game line</div>'
    + '<p class="lede" style="font-size:15px;line-height:20px">'
    + '<b style="color:var(--ink)">GB by 6.5</b> means the books expect Green '
    + 'Bay to win by about a touchdown. <b style="color:var(--ink)">Total '
    + 'points</b> is both teams’ scores added together. '
    + '<b style="color:var(--ink)">% to win</b> is the sportsbook’s own '
    + 'chance with their cut taken out.</p>'
    + '<p class="help">Our model is built without sight of the betting line, '
    + 'so where it differs it is a second opinion rather than a rounding of '
    + 'the same one.</p></div>'
    + '</div>';
}

// ── screen: one game ────────────────────────────────────────────────────

function v3Game(gid) {
  const c = (v3GameSet().cards || []).filter(x => x.game_id === gid)[0];
  if (!c) return '<div class="wrap"><a class="back" data-v3back="1">'
    + '‹ Games</a><div class="card">That game is not on this week’s '
    + 'board.</div></div>';
  const notes = (DATA.notes || {})[gid] || [];
  const cats = ['all'].concat(notes.map(n => n.cat).filter(
    (v, i, a) => a.indexOf(v) === i));
  const shown = notes.filter(n => V.cat === 'all' || n.cat === V.cat);

  return '<div class="wrap">'
    + '<div class="gamenav">'
    + '<a class="back" data-v3back="1">‹ All games</a>'
    + v3GameSwitch(gid)
    + '</div>'
    + '<div class="card">'
    + '<div class="vs"><div><b>' + esc(c.away) + '</b><div class="sub">away</div>'
    + '</div><div style="text-align:center;color:var(--mut2)">at</div>'
    + '<div style="text-align:right"><b>' + esc(c.home) + '</b>'
    + '<div class="sub">home</div></div></div>'
    + '<div class="sub" style="margin-top:8px">' + esc(v3Kick(c)) + '</div>'
    + v3WinBar(c)
    + v3Compare(c)    + '</div>'
    // ASKING SITS DIRECTLY UNDER THE SCORE CARD.
    //
    // It is the first thing to do with a game rather than the last, and
    // below the public split it fell under the fold on a phone: the control
    // that answers anything was the one thing you had to scroll to find.
    // Above the tab bar, so every tab has it.
    + '<button class="askbtn" data-v3sheet="ask">'
    + '<span>Ask about this game</span><i>\u2192</i></button>'
    // PUBLIC MONEY IS GAME CONTEXT, so it sits with the matchup above the
    // tabs rather than under whichever tab you happen to be on. The injury
    // report is a SECTION, not context, so it became a tab of its own —
    // under the matchup card it pushed every control two screens down.
    + v3PublicMoney(gid)
    // Directly under it, because it is the other half of the same feed: the
    // bars above are the ticket share and this is the dollar share.
    + v3Sharp(gid)
    // ONE DISTRIBUTION, ONE TAB.
    //
    // Bets and Score were two renderings of the same thing: `score_dist`
    // answers both from ONE call to `comparables(spread, total)` — the same
    // historical games — as a final-score table and as a ladder of lines.
    // Reading "PIT by 5.2" against "% to hit over 24" meant moving between
    // two tabs to see one distribution twice. Matchup stays separate because
    // it answers WHY rather than WHAT.
    + '<div class="seg seg--5">'
    + v3Seg('v3gtab', [['notes', 'Notes'], ['players', 'Players'],
                       ['out', 'Outcome'], ['edge', 'Matchup'],
                       ['inj', 'Injuries']], V.gameTab)
    + '</div>'
    // THE TAB'S OWN CONTENT COMES FIRST, CONTEXT UNDER IT.
    //
    // The injury report and the public split sat between the tab bar and the
    // content, so every filter and sort control on the Players tab was two
    // screens below the tab you pressed to reach it: change a market, scroll
    // back down, read, scroll up again. Both blocks are the same all week
    // whichever tab you are on, which is exactly what should not be between
    // a control and the rows it controls.
    + (V.gameTab === 'players' ? v3GamePlayers(gid)
     : V.gameTab === 'out' ? v3GameOutcome(c, gid)
     : V.gameTab === 'edge' ? v3Matchup(c)
     : V.gameTab === 'inj' ? v3Injuries(c, true)
     : v3GameNotes(gid, cats, shown))
    + '</div>';
}

// WHAT SHARE OF BETS IS ON EACH SIDE, AND WHICH WAY IT HAS DRIFTED.
//
// Scraped from Sportsbook Review's consensus feed and archived per capture,
// so the week's drift is recoverable: a side that opened at 50% and is at 71%
// by Sunday is a different fact from one that sat at 71% all week, and the
// second is invisible from a single read.
//
// **The page does not tell you to fade it.** "The public is wrong" is a
// folk theorem, not a result, and this project has not measured one. What is
// shown is the split, the drift, and the line move beside it — because the
// interesting case is the DISAGREEMENT: tickets piling onto a side while the
// number moves the other way is somebody with a strong opinion outweighing a
// crowd, and that is the shape `rlm` was written to look for.
// THE OFFICIAL INJURY REPORT, WHICH COSTS NOTHING.
//
// nflverse publishes it — status, body part and practice participation — so
// there is no reason to spend a search on the one piece of real-time context
// that is already free. Only players carrying a designation: a roster row
// with no status is a player who is fine, and listing three hundred of those
// per game buries the six that matter.
//
// Skill positions are marked, because those are the ones that move a player
// market. An Out guard matters to the game; an Out receiver matters to a prop.
// OFFENSE AGAINST DEFENSE, AS DIFFERENTIALS.
//
// A raw rate is unreadable: "Cincinnati 36.4% early-down success" means
// nothing without knowing what Pittsburgh's defense allows. Each row pairs
// one side's offense with the other's defense and leads with the gap, which
// is the number a reader can act on — and shows BOTH halves, because a
// matchup has two and showing one is showing half a game.
function v3Matchup(c) {
  const m = c && c.matchup;
  if (!m || !m.rows) {
    return '<div class="card"><p class="lede" style="font-size:15px">No '
      + 'play-by-play for this season yet, so there is nothing to compare.'
      + '</p></div>';
  }
  const g = m.games || {};
  // FULL GAME, FIRST HALF, SECOND HALF. The same eight rows rather than
  // twenty-four: a half is a different view of one matchup, not a different
  // matchup. A team that scripts its opening drives shows up in the first
  // half and is invisible in the season total.
  const halves = m.halves || [['full', 'Full game']];
  const split = (m.splits && m.splits[V.half]) ? V.half : 'full';
  const rows = (m.splits && m.splits[split]) || m.rows || [];
  const seg = halves.length < 2 ? '' :
    '<div class="seg seg--' + halves.length + '" style="margin-top:12px">'
    + halves.map(h => '<button data-v3half="' + esc(h[0]) + '" aria-pressed="'
        + (h[0] === split) + '">' + esc(h[1]) + '</button>').join('')
    + '</div>';
  const pct = v => (v * 100).toFixed(1) + '%';
  const fmt = (k, v) => k === 'epa_play' ? (v >= 0 ? '+' : '') + v.toFixed(3)
    : pct(v);
  const row = (r, p) => {
    // The bar is the EDGE, centered: right of the middle is an advantage for
    // the offense, left is the defense winning it.
    const e = r.key === 'epa_play' ? p.edge * 100 : p.edge * 100;
    const w = Math.min(50, Math.abs(e) * (r.key === 'epa_play' ? 3 : 2.2));
    const good = p.edge > 0;
    return '<div class="mx">'
      + '<div class="mx__h"><span>' + esc(p.offense) + ' offense <i>vs</i> '
      + esc(p.defense) + ' defense</span>'
      + '<b class="num ' + (good ? 'good' : 'bad') + '">'
      + (p.edge > 0 ? '+' : '') + fmt(r.key, p.edge) + '</b></div>'
      + '<div class="mx__b"><i class="' + (good ? 'r' : 'l') + '" style="width:'
      + Math.max(2, w) + '%"></i></div>'
      + '<div class="mx__f num">' + fmt(r.key, p.off_val) + ' against '
      + fmt(r.key, p.def_val) + ' allowed</div>'
      + '</div>';
  };
  return '<div class="card"><div class="eyebrow">Based on</div>'
    + '<p class="lede" style="font-size:15px;line-height:20px;margin-top:4px">'
    + 'Every game each side has played this season BEFORE this one'
    + (Object.keys(g).length
       ? ' \u2014 ' + Object.keys(g).map(t => esc(t) + ' ' + g[t]).join(', ')
       : '') + '.</p>'
    + (m.thin ? '<p class="help">Two games or fewer. Treat every number here '
        + 'as a first impression rather than a rate.</p>' : '')
    + '</div>'
    + seg
    + rows.map(r =>
        '<h2 class="h1" style="font-size:17px;line-height:22px;margin-top:20px">'
        + esc(r.label)
        + (r.proxy ? ' <span class="tag tag--warn">proxy</span>' : '') + '</h2>'
        + '<p class="help">' + esc(r.note) + '</p>'
        + '<div class="card">' + r.sides.map(p => row(r, p)).join('') + '</div>'
      ).join('')
    + (m.missing && m.missing.length
       ? '<div class="card"><div class="name">Not shown, and why</div>'
         + m.missing.map(x => '<div class="gap"><b>' + esc(x.what) + '</b>'
             + '<span>' + esc(x.why) + '</span></div>').join('') + '</div>'
       : '');
}

function v3Injuries(c, full) {
  const inj = c && c.injuries;
  if (!inj) return full
    ? '<div class="card"><p class="lede" style="font-size:15px">No injury '
      + 'report filed for this game yet. The league files it midweek.</p></div>'
    : '';
  const teams = Object.keys(inj);
  if (!teams.length) return '';
  const tone = s => s === 'Out' ? 'tag tag--bad'
    : s === 'Doubtful' ? 'tag tag--warn' : 'tag';
  return '<div class="card"><div class="name">Injury report</div>'
    + teams.map(t => '<div class="inj">'
        + '<div class="eyebrow" style="margin-top:8px">' + esc(t) + '</div>'
        + inj[t].map(r => '<div class="injrow">'
            + '<span class="' + tone(r.status) + '">' + esc(r.status)
            + '</span>'
            + '<span class="injrow__n"><b>' + esc(r.player) + '</b>'
            + '<i>' + esc([r.pos, r.injury, r.practice].filter(Boolean)
                          .join(' \u00b7 ')) + '</i></span></div>').join('')
        + '</div>').join('')
    + '<p class="help">The league\u2019s own report, filed midweek. '
    + 'Designations can change up to 90 minutes before kickoff.</p></div>';
}

// WHERE THE LINE OPENED AND WHERE IT IS NOW.
//
// Shown WITH the ticket split rather than apart from it, because the pair is
// the story: a crowd piled onto one side while the number moved the other way
// is money outvoting tickets, and either number alone is half of it.
//
// The open is the GAME WEEK's, not the lookahead line posted in May. A
// three-point move since May is a season of news; a three-point move since
// Tuesday is this week's money.
function v3Moved(gid) {
  const L = ((DATA.games || {}).lines || {})[gid];
  if (!L) return '';
  const c = (v3GameSet().cards || []).filter(x => x.game_id === gid)[0] || {};
  const bits = [];
  const sp = L.spreads, to = L.totals;
  if (sp && has(sp.open) && has(sp.now)) {
    // Signed toward the HOME side, as the cards are. A move toward the home
    // team is the number getting more negative.
    const toward = sp.move < 0 ? c.home : c.away;
    bits.push(['Spread',
      (sp.open < 0 ? c.home + ' ' + sp.open : c.away + ' -' + sp.open),
      (sp.now < 0 ? c.home + ' ' + sp.now : c.away + ' -' + sp.now),
      Math.abs(sp.move) < 0.25 ? 'unmoved'
        : Math.abs(sp.move) + ' toward ' + toward]);
  }
  if (to && has(to.open) && has(to.now)) {
    bits.push(['Total', String(to.open), String(to.now),
      Math.abs(to.move) < 0.25 ? 'unmoved'
        : Math.abs(to.move) + ' ' + (to.move > 0 ? 'up' : 'down')]);
  }
  // THE MONEYLINE MOVES TOO, and it was the one market this block left out.
  //
  // `open`/`now`/`move` are null on a moneyline because it has no point, so
  // the block that reads those skipped it. The PRICES are there, and the
  // price is the whole market: a side going +120 -> +110 has shortened, and
  // shortening is money arriving.
  //
  // Read as implied chance rather than as the raw number, because -142 to
  // -130 and +120 to +110 are moves of different sizes in the same direction
  // and only the probability says which is bigger. `amToDec` is the one
  // conversion in this codebase; 1/decimal is its implied chance.
  const ml = L.h2h, oo = ml && ml.open_odds, no = ml && ml.now_odds;
  if (oo && no && has(oo[0]) && has(oo[1]) && has(no[0]) && has(no[1])) {
    // Stored [away, home], as the archive stores them.
    const shift = i => 1 / amToDec(no[i]) - 1 / amToDec(oo[i]);
    const sides = [[c.away, 0], [c.home, 1]];
    for (const [team, i] of sides) {
      const d = shift(i) * 100;
      bits.push([team + ' to win', v3Dash(oo[i]), v3Dash(no[i]),
                 Math.abs(d) < 0.25 ? 'unmoved'
                   : d > 0 ? 'shortened ' + d.toFixed(1) + 'pp'
                           : 'drifted ' + Math.abs(d).toFixed(1) + 'pp']);
    }
  }
  if (!bits.length) return '';
  return '<div class="moved">'
    + '<div class="eyebrow">Since this week\u2019s line went up'
    + (sp && sp.open_at ? ' (' + esc(sp.open_at) + ')' : '') + '</div>'
    + bits.map(b => '<div class="moved__r"><span>' + esc(b[0]) + '</span>'
        + '<span class="num">' + esc(b[1]) + ' \u2192 <b>' + esc(b[2])
        + '</b></span>'
        + '<span class="sub">' + esc(b[3]) + '</span></div>').join('')
    + '</div>';
}

// TICKETS COUNT BETS; MONEY COUNTS DOLLARS. THE GAP IS THE SIGNAL.
//
// Sportsbook Review publishes tickets only, and nothing at all on the
// moneyline. Action Network publishes both, on all three markets, so this is
// the moneyline block the section never had — and the one number on this
// page that says something a crowd size cannot: a side taking 11% of the
// tickets and 46% of the money is a few large bets, not a public opinion.
// Atlanta at Green Bay read exactly that in week 3.
//
// A gap needs to be worth a sentence before it gets one. Under
// `V3GAP_SMALL` the two shares are the same bet, rounded differently.
const V3GAP_SMALL = 8;

function v3Splits(gid) {
  const all = (DATA.games || {}).splits || {};
  let blk = all[gid];
  if (!blk) {
    for (const k of Object.keys(all)) {
      if (v3Same(k, gid)) { blk = all[k]; break; }
    }
  }
  return blk || null;
}

function v3SplitRow(label, m) {
  if (!m || !m.sides || !m.sides.length) return '';
  const top = m.sides[0];
  if (top.tickets == null || top.money == null) return '';
  const w = Math.round(top.tickets);
  const gap = top.gap;
  const big = has(gap) && Math.abs(gap) >= V3GAP_SMALL;
  return '<div class="pub">'
    + '<div class="pub__h"><span class="eyebrow">' + esc(label) + '</span> '
    + '<span class="sub num">' + esc(top.side) + ' \u00b7 '
    + top.tickets.toFixed(0) + '% of bets, ' + top.money.toFixed(0)
    + '% of the money</span></div>'
    + '<div class="bar" role="img" aria-label="' + esc(top.side) + ' '
    + w + ' percent of bets">'
    + '<span class="h num" style="width:' + w + '%;justify-content:flex-start">'
    + esc(top.side) + ' ' + top.tickets.toFixed(0) + '%</span>'
    + '<span class="a num" style="width:' + (100 - w)
    + '%;justify-content:flex-end">'
    + (w >= 97 ? '' : (m.sides[1] ? esc(m.sides[1].side) + ' '
        + (m.sides[1].tickets == null ? '' : m.sides[1].tickets.toFixed(0) + '%')
        : '')) + '</span></div>'
    + (big
       ? '<p class="help" style="margin-top:6px">'
         + (gap > 0
            ? esc(top.side) + ' has ' + Math.abs(gap).toFixed(0) + ' points '
              + 'more of the MONEY than of the bets \u2014 fewer, larger '
              + 'wagers than the ticket count suggests.'
            : esc(top.side) + ' has ' + Math.abs(gap).toFixed(0) + ' points '
              + 'less of the money than of the bets \u2014 a lot of small '
              + 'tickets without the money behind them.')
         + '</p>'
       : '')
    + '</div>';
}

function v3PublicMoney(gid) {
  const pub = ((DATA.games || {}).public || {})[gid];
  if (!pub) {
    return '<div class="card"><div class="eyebrow">Share of bets</div>'
      + '<p class="lede" style="font-size:15px;line-height:20px;margin-top:6px">'
      + 'Not captured for this week. Run the public-money script and it will '
      + 'appear here.</p></div>';
  }
  const rows = ((DATA.games || {}).rows || []).filter(
    r => v3Same(r.game_id, gid));
  const label = { spreads: 'Against the spread', totals: 'Total points',
                  h2h: 'To win' };
  const blocks = ['spreads', 'totals', 'h2h'].map(mk => {
    const m = pub[mk];
    if (!m || !m.sides || m.sides.length < 2) return '';
    const top = m.sides[0], bot = m.sides[1];
    const w = Math.round(top.pct);
    // The line move on the SAME side the tickets are on, so the two can
    // disagree visibly rather than sitting in separate paragraphs.
    // AGAINST THE CROWD, measured on the real opening line where we have
    // one. The archived open/close pair is two captures minutes apart on some
    // weeks; the feed's history is the line as it actually moved.
    const L = ((DATA.games || {}).lines || {})[gid] || {};
    const card = (v3GameSet().cards || []).filter(x => x.game_id === gid)[0] || {};
    let mv = null;
    if (mk === 'totals' && L.totals && has(L.totals.move)) {
      mv = top.side === 'Over' ? L.totals.move : -L.totals.move;
    } else if (mk === 'spreads' && L.spreads && has(L.spreads.move)) {
      mv = top.side === card.home ? -L.spreads.move : L.spreads.move;
    }
    if (mv == null) {
      mv = rows.filter(r => r.market === mk && r.outcome === top.side)
        .map(r => r.move_pp).filter(has)[0];
    }
    const against = has(mv) && mv < -0.25;
    return '<div class="pub">'
      + '<div class="pub__h"><span class="eyebrow">' + esc(label[mk] || mk)
      + '</span> '
      + (has(top.drift)
         ? '<span class="sub num">' + (top.drift > 0 ? '+' : '\u2212')
           + Math.abs(top.drift).toFixed(1) + 'pp on ' + esc(top.side)
           + ' this week</span>'
         : '<span class="sub">one capture so far</span>')
      + '</div>'
      + '<div class="bar" role="img" aria-label="' + esc(top.side) + ' '
      + w + ' percent of bets">'
      + '<span class="h num" style="width:' + w + '%;justify-content:'
      + 'flex-start">' + esc(top.side) + ' ' + top.pct.toFixed(0) + '%</span>'
      + '<span class="a num" style="width:' + (100 - w)
      + '%;justify-content:flex-end">'
      + (w >= 97 ? '' : esc(bot.side) + ' ' + bot.pct.toFixed(0) + '%')
      + '</span>'
      + '</div>'
      + (against
         ? '<p class="help" style="margin-top:6px">Most tickets are on '
           + esc(top.side) + ' and the price has moved AWAY from it '
           + '(' + Math.abs(mv).toFixed(1) + ' against it). That is money '
           + 'disagreeing with the crowd.</p>' : '')
      + '</div>';
  }).join('');
  const mv = v3Moved(gid);
  const sp = v3Splits(gid);
  const ml = sp ? v3SplitRow('To win (moneyline)', sp.moneyline) : '';
  if (!blocks && !mv && !ml) return '';
  return '<div class="card"><div class="name">Where the public is</div>'
    + mv
    + ml
    + blocks
    + '<p class="help">Share of bets placed, from Sportsbook Review. A crowd '
    + 'being on one side is not evidence it is wrong \u2014 this project has '
    + 'not measured that. It is worth seeing next to which way the price '
    + 'moved.</p>'
    // THE MONEYLINE SPLIT IS ABSENT, NOT ZERO, and the difference matters.
    // The feed returns 0% on every moneyline on every game, which is it
    // declining to publish rather than a market nobody bet. Drawing a 0% bar
    // would be stating a number nobody stated; saying nothing would read as
    // an oversight. The price move above is what there is.
    + (ml
       ? '<p class="help">The moneyline split is Action Network\u2019s, which '
         + 'publishes money as well as tickets. The spread and total bars are '
         + 'Sportsbook Review\u2019s, which publishes neither the moneyline '
         + 'nor the money \u2014 two books, two customer bases, kept '
         + 'apart rather than averaged into a crowd that does not exist.</p>'
       : '<p class="help">No ticket split for the moneyline: Sportsbook '
         + 'Review publishes none, on any game. Its price move is '
         + 'above.</p>')
    + '</div>';
}

// WHERE THE BIG MONEY IS, ACROSS ALL THREE MARKETS.
//
// The bars above are ticket shares. This is the other half of the same feed:
// the share of the DOLLARS, which only Action Network publishes, on the
// moneyline, the spread and the total alike.
//
// **Ranked on the ratio, not the gap.** Money share minus ticket share is
// capped by the ticket share — a side already holding 89% of the tickets can
// gain at most 11 points however large its bets are — so the gap sorts by how
// unpopular a side is. Carolina at 89% of tickets and 96% of the money is the
// case that exposes it: a 7-point gap, which is under the threshold that earns
// a sentence anywhere else on this card, and three times the average bet.
//
// Nothing here is a claim that the big money is right. That is precisely what
// has not been measured yet, and the note says so.
const V3RATIO_SMALL = 1.5;

const V3SHARPMKT = [['moneyline', 'To win'], ['spread', 'Spread'],
                    ['total', 'Total']];

function v3SharpSides(gid) {
  const sp = v3Splits(gid);
  if (!sp) return [];
  const out = [];
  V3SHARPMKT.forEach(m => {
    const blk = sp[m[0]];
    if (!blk || !blk.sides) return;
    blk.sides.forEach(s => {
      if (!has(s.ratio) || s.ratio < V3RATIO_SMALL) return;
      out.push({ market: m[1], side: s.side, ratio: s.ratio,
                 tickets: s.tickets, money: s.money });
    });
  });
  return out.sort((a, b) => b.ratio - a.ratio);
}

function v3Sharp(gid) {
  const rows = v3SharpSides(gid);
  if (!rows.length) return '';
  return '<div class="card"><div class="name">Where the bigger bets are</div>'
    + '<p class="lede" style="font-size:15px;line-height:20px;margin-top:6px">'
    + 'Tickets count bets; money counts dollars. These sides are carrying a '
    + 'bigger average bet than the other side of the same market.</p>'
    + '<div class="list" style="margin-top:10px">'
    + rows.map(r => '<div class="row"><div class="row__m">'
        + '<div class="row__t"><div style="min-width:0">'
        + '<div class="name">' + esc(r.side) + '</div>'
        + '<div class="sub">' + esc(r.market) + ' · '
        + r.tickets.toFixed(0) + '% of bets, ' + r.money.toFixed(0)
        + '% of the money</div>'
        + '</div><div class="chance"><b class="num">' + r.ratio.toFixed(1)
        + '×</b><span class="eyebrow">the bet</span></div>'
        + '</div></div></div>').join('')
    + '</div>'
    + '<p class="help">A side at 2× is backed by bets twice the size of '
    + 'the ones on the other side. <b style="color:var(--ink)">This is not a '
    + 'tip.</b> Whether the bigger money is the smarter money is exactly what '
    + 'this project has not measured — the split archive began on '
    + '25 September and the first week whose opening line, splits and close '
    + 'all land in order is the first one that can answer it.</p>'
    + '</div>';
}

// THE CHANCE OF WINNING, BOOK AND MODEL, ON THE SAME SCALE.
//
// One bar showed the sportsbooks' number and our model appeared only as a
// projected score two boxes below, which left the reader converting points
// into a probability in their head. Both are bars now, stacked, so the
// comparison is the thing you see rather than the thing you work out.
//
// Our model does not predict a win chance — it predicts a margin and a total
// — so the conversion runs through `score_dist`: how often did games hung at
// OUR number actually go the home side's way. See `_attach_scores`.
// SWITCHING GAMES WITHOUT GOING BACK FIRST.
//
// Reading one game and then the next meant Back, find the row again, tap. The
// same select the board uses, except this one NAVIGATES rather than filters —
// and it keeps the tab you are on, so comparing the score ladders of four
// games is four taps rather than twelve.
function v3GameSwitch(gid) {
  const cards = v3GameSet().cards || [];
  if (cards.length < 2) return '';
  let i = -1;
  cards.forEach((c, k) => { if (c.game_id === gid) i = k; });
  const step = d => {
    const j = i + d;
    return (i < 0 || j < 0 || j >= cards.length) ? ''
      : '<button class="gstep" data-v3game="' + esc(cards[j].game_id)
        + '" aria-label="' + (d < 0 ? 'Previous' : 'Next') + ' game">'
        + (d < 0 ? '\u2039' : '\u203a') + '</button>';
  };
  return '<div class="gsel">' + step(-1)
    + '<select data-v3gameto aria-label="Switch game">'
    + cards.map(c => '<option value="' + esc(c.game_id) + '"'
        + (c.game_id === gid ? ' selected' : '') + '>'
        + esc(c.away + ' at ' + c.home) + '</option>').join('')
    + '</select>' + step(1) + '</div>';
}

function v3WinBar(c) {
  const bars = [];
  if (has(c.win_home)) bars.push(['Sportsbooks', c.win_home, null]);
  if (has(c.model_win_home))
    bars.push(['Our model', c.model_win_home, c.model_win_n]);
  // ADJUSTED: the fitted blend of the two above it. The weight comes from
  // `game_blend`, swept over 1,904 walk-forward games rather than chosen, and
  // it is small — which is the useful part. It says how far the model has
  // earned the right to move the book, and "about a seventh of the way" is a
  // more honest answer than either number alone.
  const aw = v3AdjWin(c);
  if (aw != null) bars.push(['Adjusted', aw, null]);
  if (!bars.length) return '';
  return '<div style="margin-top:16px;display:flex;flex-direction:column;'
    + 'gap:10px">'
    + bars.map(b => {
        const h = Math.round(b[1] * 100), a = 100 - h;
        return '<div>'
          + '<div class="eyebrow" style="display:flex;justify-content:'
          + 'space-between"><span>' + esc(b[0]) + '</span>'
          + (b[2] ? '<span style="text-transform:none;letter-spacing:0">from '
             + b[2] + ' past games</span>' : '') + '</div>'
          + '<div class="bar" style="margin-top:4px" role="img" aria-label="'
          + esc(c.away) + ' ' + a + ' percent, ' + esc(c.home) + ' ' + h
          + ' percent">'
          + '<span class="a num" style="width:' + a + '%">' + esc(c.away)
          + ' ' + a + '%</span>'
          + '<span class="h num" style="width:' + h + '%">' + esc(c.home)
          + ' ' + h + '%</span></div></div>';
      }).join('')
    + '</div>';
}

// The two projections, side by side, as SCORES — whole numbers, because
// "KC 28.8-17.2" is not a football score and reads as spurious precision on
// a number whose interval is ten points wide.
function v3Compare(c) {
  const line = (label, sp, tot, cls) => {
    if (!has(sp) || !has(tot)) return '';
    const hh = tot / 2 - sp / 2, aa = tot / 2 + sp / 2;
    const lead = hh >= aa ? c.home : c.away;
    // TEAM ON ITS OWN LINE, SCORE UNDER IT. Three boxes across at phone
    // width and "CIN 23.0-19.5" wrapped mid-score, reading as two numbers on
    // two rows.
    //
    // One decimal on the score: rounding turned a 0.6-point model margin into
    // "LA 22-22", a projected tie built from numbers that did not say one.
    return '<div class="cmp' + (cls || '') + '">'
      + '<span class="eyebrow">' + esc(label) + '</span>'
      + '<b class="cmp__t">' + esc(lead) + '</b>'
      + '<b class="num cmp__s">' + Math.max(hh, aa).toFixed(1)
      + '\u2013' + Math.min(hh, aa).toFixed(1) + '</b>'
      + '<span class="sub num">by ' + Math.abs(sp) + ' \u00b7 ' + tot
      + ' pts</span></div>';
  };
  const a = line('Sportsbooks', c.spread, c.total, '');
  const b = line('Our model', c.model_spread, c.model_total, ' cmp--ours');
  const adj = c.blend
    ? line('Adjusted', c.blend.spread, c.blend.total, ' cmp--adj') : '';
  if (!a && !b) return '';
  // THE OTHER SIDE OF THE PROJECTION, BESIDE IT.
  //
  // A point estimate is the whole headline and the distribution was a tab
  // away. On 25 September Atlanta won at Green Bay by 21 as a road dog: the
  // page said "GB 23.8-22.2" and every number looked wrong, while the same
  // build had an outright Atlanta win at 28.5% — which is not a long shot,
  // and is a number nobody saw without changing tabs. Said here, a projection
  // reads as the middle of a distribution rather than as a forecast.
  const u = c.unfold;
  const note = (u && !u.thin && u.headline)
    ? '<p class="help" style="margin-top:8px">A projection is the middle of a '
      + 'range, not a call. In ' + u.n + ' games priced like this one, '
      + esc(u.dog) + ' won outright <b>'
      + u.headline.upset.pct.toFixed(0) + '%</b> of the time and '
      + u.headline.one_score.pct.toFixed(0) + '% finished within one score.</p>'
    : '';
  return '<div class="' + (adj ? 'three' : 'two')
    + '" style="margin-top:16px">' + a + b + adj + '</div>' + note;
}

function v3GameNotes(gid, cats, shown) {
  if (!shown.length) {
    return '<div class="card"><p class="lede" style="font-size:15px">'
      + 'Nothing in this game disagrees with the market enough to be worth a '
      + 'note. That is a real answer, not a missing one.</p></div>';
  }
  const pills = cats.map(k => '<button class="cat" data-v3cat="' + esc(k)
    + '" aria-pressed="' + (V.cat === k) + '">'
    + esc(k === 'all' ? 'All' : k) + '</button>').join('');
  return v3Unfold()
    + '<h2 class="h1" style="font-size:22px;line-height:28px;margin-top:20px">'
    + 'What our AI noticed</h2>'
    + '<p class="help">Written from this week’s prices and our model’s '
    + 'numbers. Every figure below is computed; only the wording is written.</p>'
    + '<div class="cats">' + pills + '</div>'
    + shown.map(v3Note).join('')
    + '<p class="help" style="margin-top:12px">These notes explain the game. '
    + 'They do not tell you what to bet.</p>';
}

// HOW THE GAME MAY UNFOLD, as a partition that adds to 100%.
//
// Counted, not reasoned: every row is real games hung at this spread and
// total, grouped by how they finished. Overlapping scenarios — "one-score
// 50%, shootout 31%, upset 28%" — read as a ranking and cannot be one,
// because they add to more than everything that can happen and nothing on
// screen says which of them overlap. This column adds up.
function v3Unfold() {
  const c = (v3GameSet().cards || []).filter(
    x => x.game_id === V.game)[0];
  const u = c && c.unfold;
  if (!u || u.thin || !u.cells || !u.cells.length) return '';
  const h = u.headline || {};
  const chip = (v, l) => '<div class="fig"><b class="num">' + v + '</b>'
    + '<span>' + esc(l) + '</span></div>';
  return '<h2 class="h1" style="font-size:22px;line-height:28px;'
    + 'margin-top:20px">How it may unfold</h2>'
    + '<p class="help">Counted from ' + u.n + ' past games hung at this '
    + 'spread and total. Not a forecast of this one \u2014 what happened in '
    + 'the ones priced like it.</p>'
    + '<div class="card"><div class="figs">'
    + chip(h.one_score.pct.toFixed(0) + '%', 'within one score')
    + chip(h.upset.pct.toFixed(0) + '%', u.dog + ' wins')
    + chip(h.shootout.pct.toFixed(0) + '%', 'high scoring')
    + '</div><div style="margin-top:12px">'
    + u.cells.filter(x => x.pct >= 1).map(x =>
        '<div class="mrow"><span class="mrow__l">' + esc(x.label) + '</span>'
        + '<div class="mbar"><i style="width:' + Math.min(100, Math.max(2, x.pct * 4))
        + '%"></i></div>'
        + '<span class="mrow__v num">' + x.pct.toFixed(0) + '%</span></div>')
      .join('')
    + '</div><p class="help" style="margin-top:8px">These are every way the '
    + 'game can go, so the column adds to 100.</p></div>';
}

function v3Note(n) {
  const figs = (n.stats || []).map(s =>
    '<div class="fig"><b class="num">' + esc(s.v) + '</b><span>' + esc(s.l)
    + '</span></div>').join('');
  // `context` before the rest: a coaching note that renders unlabelled reads
  // as a reason to bet, and `situational_features` measured thirteen of these
  // on 2,853 games without one of them clearing the vig.
  const flag = n.counted ? '<span class="tag tag--good">Counted</span>'
    : n.context ? '<span class="tag">Context, not an edge</span>'
    : n.measured ? '<span class="tag tag--good">Measured</span>'
    : n.model ? '<span class="tag tag--ours">Our model</span>'
    : n.avoid ? '<span class="tag tag--bad">Avoid</span>' : '';
  // THE BUTTON ONLY EXISTS WHERE IT DOES SOMETHING.
  //
  // It used to appear on every note and add a string nobody could bet: the
  // slip is keyed by board row id, and a line or coaching note has no row.
  // `pick_id` is set at selection time for the notes whose subject IS a row,
  // and only those get a button — which is automatic, not a weekly chore.
  const id = n.pick_id;
  const on = id && !!V.picks[id];
  return '<article class="note">'
    + '<div class="note__h"><span class="eyebrow">' + esc(n.cat) + '</span>'
    + flag + '</div>'
    + '<h3>' + esc(n.title) + '</h3>'
    + (figs ? '<div class="figs">' + figs + '</div>' : '')
    + '<p><b style="color:var(--ink)">Why it matters: </b>' + esc(n.why) + '</p>'
    + '<div class="note__f"><div><span class="sub">Related pick</span>'
    + '<div class="name" style="font-size:15px">' + esc(n.pick) + '</div></div>'
    + (id
       ? '<button class="btn" data-v3pick="' + esc(id) + '" aria-pressed="'
         + on + '">' + (on ? 'Added' : 'Add') + '</button>'
       : '')
    + '</div></article>';
}

// ASK ANYTHING, through a proxy that holds the key and the context.
//
// The canned questions stay, because they are answered instantly and for
// free from data already in the page, and most of what anyone wants to know
// is one of them. The box is for the rest.
//
// The endpoint takes a GAME ID and a QUESTION, nothing else: the brief it
// answers from lives on the server and is chosen by that id. A client that
// could send its own context could send anything, and the endpoint would
// become a general-purpose model billed to whoever owns the key.
//: `bare` drops the card and the heading, for the sheet — which draws both
//: itself, and whose background is the card color, so a card inside it is a
//: panel on a panel with a shadow between them.
function v3Ask(gid, bare) {
  const qs = v3Questions(gid);
  const a = V.answer;
  return (bare ? '<div>'
          : '<div class="card"><div class="name">Ask about this game</div>')
    + '<p class="help">Quick answers below are computed from this page. The '
    + 'box asks our model, which can also look up news.</p>'
    + (qs.length ? '<div class="qs">' + qs.map((q, i) =>
        '<button class="q" data-v3ask="' + i + '">' + esc(q.q) + '</button>')
      .join('') + '</div>' : '')
    + '<form class="ask" data-v3askform="' + esc(gid) + '">'
    + '<input type="text" data-v3q2 maxlength="400" '
    + 'placeholder="Ask anything about this game" value="' + esc(V.q2 || '')
    + '" aria-label="Ask a question about this game"'
    + (V.asking ? ' disabled' : '') + '>'
    + '<button type="submit" aria-label="Ask"' + (V.asking ? ' disabled' : '')
    + '>' + (V.asking ? '\u2026' : '\u2192') + '</button></form>'
    + (V.asking ? '<div class="ans"><span class="thinking">Thinking'
        + '\u2026</span></div>' : '')
    + (a ? '<div class="ans">' + esc(a).replace(/\n\n/g, '</div><div class="ans">')
        + '</div>' : '')
    + (V.answerErr ? '<div class="ans ans--bad">' + esc(V.answerErr)
        + '</div>' : '')
    + (V.answerLive ? '<p class="help">Answered by our model from this '
        + 'week\u2019s data' + (V.searched ? ', with a web search' : '')
        + '. It can be wrong; the numbers on the page are the source.</p>' : '')
    + '</div>';
}

//: Where the proxy lives, relative to the page.
const V3ASK_URL = 'ask.php';

function v3AskSend(gid, q) {
  V.asking = true; V.answer = ''; V.answerErr = ''; V.answerLive = false;
  render();
  let done = false;
  const finish = (ans, err, searched) => {
    if (done) return;
    done = true;
    V.asking = false; V.answer = ans || ''; V.answerErr = err || '';
    V.answerLive = !!ans; V.searched = !!searched;
    render();
  };
  // A visible ceiling on the wait. Without it a proxy that never answers
  // leaves "Thinking..." on the screen forever, which reads as a hang.
  setTimeout(() => finish('', 'That took too long. Try again, or ask one of '
    + 'the quick questions above.'), 60000);
  fetch(V3ASK_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ game: gid, q: q }),
  }).then(r => r.json().then(j => ({ ok: r.ok, j: j })))
    .then(x => {
      if (x.ok && x.j && x.j.answer) finish(x.j.answer, '', x.j.searched);
      else finish('', (x.j && x.j.error) || 'Could not answer that one.');
    })
    .catch(e => finish('', location.protocol === 'file:'
      ? 'Asking needs the site served over http, not opened as a file.'
      : 'Could not reach the answering service.'));
}

function v3Questions(gid) {
  const rows = rowsFor('any', null).filter(
    r => r.priced && v3Same(r.gameId, gid));
  if (!rows.length) return [];
  const byP = rows.slice().sort((a, b) => (betProb(b) || 0) - (betProb(a) || 0));
  const byV = rows.slice().sort((a, b) => (ev100(b) || -1e9) - (ev100(a) || -1e9));
  const c = (v3GameSet().cards || []).filter(x => x.game_id === gid)[0] || {};
  const out = [];
  if (byP[0]) out.push({ q: 'Who’s most likely to score?',
    a: byP[0].player + ', at ' + v3Pct(betProb(byP[0])) + '. '
     + (has(byP[0].odds) ? 'He is priced at ' + v3Dash(american(byP[0].odds))
        + ', which implies ' + v3Pct(byP[0].book) + '. ' : '')
     + (byP[1] ? 'Next is ' + byP[1].player + ' at ' + v3Pct(betProb(byP[1]))
        + '.' : '') });
  const longs = byV.filter(r => has(r.odds) && r.odds >= 250);
  if (longs[0]) out.push({ q: 'Best long shot here?',
    a: longs[0].player + ' at ' + v3Dash(american(longs[0].odds))
     + '. We make him ' + v3Pct(betProb(longs[0])) + ' where the price implies '
     + v3Pct(longs[0].book) + '. He misses most of the time — that is what '
     + 'the price means — but a $10 bet wins $'
     + v3Win(10, longs[0].odds).toFixed(2) + '.' });
  // Answered from the RECORD where there is one, not from the model alone.
  // "our model expects 51.1 and cannot see the line" invites the obvious
  // question and answers nothing a reader can use; "51% of games priced here
  // went over" is the same question answered with games.
  const sc = c.scores;
  if (has(c.total)) {
    let a = 'The books set the total at ' + c.total + ' points. ';
    if (sc && !sc.thin) {
      a += 'In ' + sc.n + ' past games priced near this number, '
         + sc.over.pct.toFixed(0) + '% went over and the average game '
         + 'finished on ' + sc.mean_total + '. ';
    }
    if (has(c.model_total)) {
      a += 'Our own model, built without sight of the line so that it can '
         + 'disagree with it, expects ' + c.model_total + '.';
    }
    out.push({ q: 'Will it be high scoring?', a: a });
  }
  const u = c.unfold;
  if (u && !u.thin && u.cells && u.cells.length) {
    out.push({ q: 'How is this likely to go?',
      a: 'Across ' + u.n + ' games priced like this one, the commonest shape '
       + 'was ' + u.cells[0].label.toLowerCase() + ' at '
       + u.cells[0].pct.toFixed(0) + '%. '
       + u.headline.one_score.pct.toFixed(0) + '% finished within one score, '
       + 'and ' + u.dog + ' won outright '
       + u.headline.upset.pct.toFixed(0) + '% of the time.' });
  }
  return out;
}

// WHICH MARKETS THIS GAME ACTUALLY HAS PLAYERS ON.
//
// The Players tab opens on whatever market the board was left on, and the
// board opens on "Scores a TD". Week 2 archived touchdown prices for two of
// its sixteen games, so fourteen of them opened the tab on a market holding
// nothing and said "no priced picks recorded for week 2 on this market" —
// which reads as "this game has no players" rather than "not this one".
//
// Counted WITHOUT the filter and the search box: the question is whether the
// game has players on a market at all, not whether the current view happens
// to show them. `by_game` rides in the payload for the past-week case, so
// this answers for six markets without fetching any of them.
function v3GameMkt(mkey, gid) {
  if (V.week == null) {
    return rowsFor(mkey, null)
      .filter(r => r.priced && !r.blocked && v3Same(r.gameId, gid)).length;
  }
  const blk = (DATA.history || {})[V3HIST[mkey]] || {};
  return ((blk.by_game || {})[String(V.week)] || {})[v3Key(gid)] || 0;
}

function v3GameMkts(gid) {
  return V3MKT.filter(m => served(m[0]) && v3GameMkt(m[0], gid) > 0);
}

//: Called from the click handlers, NEVER from a render. A render that
//: rewrites `V` is how every sort flip came to push a history entry.
function v3MarketForGame(gid) {
  if (!gid || v3GameMkt(V.market, gid) > 0) return;
  const m = v3GameMkts(gid)[0];
  if (m) V.market = m[0];
}

// An empty market inside a game is nearly always the wrong market rather
// than an empty game, so say which ones hold players and let them be tapped.
function v3GameEmpty(gid) {
  const ms = v3GameMkts(gid), wk = V.week == null ? '' : ' in week ' + V.week;
  if (!ms.length) {
    return '<div class="empty">No priced players in this game on any market'
      + wk + '. The board is built from an odds archive; where it captured '
      + 'no prices for a game there is nothing to show.</div>';
  }
  return '<div class="empty"><b>No players on this market for this game'
    + wk + '.</b><br>This game has players on:<div class="mkts" '
    + 'style="margin-top:10px">'
    + ms.map(m => '<button class="mkt" data-v3mkt="' + esc(m[0]) + '">'
        + esc(m[1]) + ' <i>' + v3GameMkt(m[0], gid) + '</i></button>').join('')
    + '</div></div>';
}

// THE PLAYERS TAB IS THIS WEEK'S BOARD WITH THE GAME FIXED.
//
// It was a separate, cut-down list: one market, one sort, no filters, no
// stars, no detail. Two renderers for the same thing is how the touchdown
// shortlist once disagreed with its own board about a player, and it also
// meant every control added to the board had to be added twice or silently
// not exist here. Same markets, same filters, same sort, same rows.
function v3GamePlayers(gid) {
  const prev = V.game;
  V.game = gid;
  const body = v3MarketControls() + v3Search() + v3SortBar()
    + '<div class="list" id="v3rows">' + v3Rows() + '</div>';
  V.game = prev;
  return '<p class="help" style="margin-top:16px">Every priced player in this '
    + 'game, on the market you pick. The same board as This week.</p>' + body;
}

// HOW THIS GAME IS LIKELY TO FINISH, from games that were priced like it.
//
// The distribution is empirical: every past game hung at roughly this spread
// and total, and what actually happened in them. See `score_dist` for why it
// is not a smooth model — NFL scores are built from 3s and 7s, so 27-24
// happens far more often than 28-25, and anything that smooths that spreads
// probability onto scorelines which essentially never occur.
//
// **The margins lead and the exact scores follow.** Each margin band pools
// dozens of games and carries an interval; an exact scoreline is four games
// in four hundred. Putting the scorelines first would be putting the least
// reliable number in the biggest type.
// HOW IT FINISHES, THEN WHAT THAT PAYS.
//
// The score table says where the distribution sits; the ladder says what it
// means at each line a book posts. Same `comparables()` set behind both, so
// they cannot disagree, and now they cannot be read apart either.
//: `bets` and `score` were separate tabs before they became `out`. A saved
//: session, a bookmark and a back entry can all still name one. ONE mapping,
//: used by the click handler, the boot and `popstate` alike.
function v3GTab(v) {
  return (v === 'bets' || v === 'score') ? 'out' : v;
}

function v3GameOutcome(c, gid) {
  return v3GameScores(c) + v3GameBets(gid);
}

function v3GameScores(c) {
  const d = c && c.scores;
  if (!d || !d.n) {
    return '<div class="card"><p class="lede" style="font-size:15px">No line '
      + 'on this game yet, so there is nothing to compare it with.</p></div>';
  }
  if (d.thin) {
    return '<div class="card"><p class="lede" style="font-size:15px">Only '
      + d.n + ' past games were priced near this spread and total \u2014 too '
      + 'few to draw a distribution from. Under ' + d.min_n + ' it would be a '
      + 'list of anecdotes with percentages on it.</p></div>';
  }
  const bar = (pct, tone) => '<div class="mbar"><i style="width:'
    + Math.max(1, pct) + '%' + (tone ? ';background:' + tone : '') + '"></i></div>';
  // WHICH OF THESE ACTUALLY HAPPENED. On a played week the distribution stops
  // being a forecast, and the row the game landed in is the only one worth
  // finding quickly. A live card has no finals and nothing is marked.
  const fh = c.final_home, fa = c.final_away;
  const played = has(fh) && has(fa);
  const margins = (d.margins || []).filter(m => m.n).map(m => {
    // `mlo`/`mhi` are the MARGIN bounds, inclusive and home-positive.
    // `lo`/`hi` on the same row are the Wilson interval on the percentage,
    // and reading those as a margin marks whichever band happens to have a
    // confidence interval straddling the final score.
    const mg = played ? fh - fa : null;
    const landed = played && (m.mlo != null || m.mhi != null)
      && (m.mlo == null || mg >= m.mlo) && (m.mhi == null || mg <= m.mhi);
    return '<div class="mrow' + (landed ? ' mrow--on' : '') + '">'
      + '<span class="mrow__l">' + esc(m.band)
      + (landed ? ' \u00b7 happened' : '') + '</span>'
      + bar(m.pct, landed ? 'var(--good)'
            : m.band.indexOf(d.home) === 0 ? 'var(--ours)' : 'var(--mut3)')
      + '<span class="mrow__v num">' + m.pct.toFixed(1) + '%</span></div>';
  }).join('');
  const scores = (d.scores || []).map(x => {
    const landed = played && x.home === fh && x.away === fa;
    return '<div class="srow' + (landed ? ' srow--on' : '') + '">'
      + '<b class="num">' + esc(d.home) + ' ' + x.home
      + '\u2013' + x.away + ' ' + esc(d.away)
      + (landed ? ' \u00b7 this one' : '') + '</b>'
      + '<span class="sub num">' + x.pct.toFixed(1) + '% \u00b7 ' + x.n
      + ' of ' + d.n + '</span></div>';
  }).join('');
  // The two headline boxes become right-or-wrong once the game is in.
  const wonTone = !played ? '' : (fh > fa ? ' box--good' : ' box--bad');
  const overTone = !played ? ''
    : ((fh + fa) > d.total ? ' box--good' : ' box--bad');

  return '<div class="card"><div class="eyebrow">Based on</div>'
    + '<p class="lede" style="font-size:15px;line-height:20px;margin-top:4px">'
    + '<b>' + d.n + ' past games</b> hung within 2 points of this spread and '
    + '3.5 of this total. Not a simulation \u2014 what actually happened in '
    + 'them.</p>'
    + '<div class="two" style="margin-top:12px">'
    + '<div class="box' + wonTone + '"><span class="eyebrow">' + esc(d.home)
    + ' won</span><b class="num">' + d.home_win.pct.toFixed(0) + '%</b>'
    + '<span class="sub num">'
    + (played ? (fh > fa ? esc(d.home) + ' did' : esc(d.home) + ' did not')
              : d.home_win.lo.toFixed(0) + '\u2013'
                + d.home_win.hi.toFixed(0) + '% range') + '</span></div>'
    + '<div class="box' + overTone + '"><span class="eyebrow">Went over '
    + d.total + '</span><b class="num">' + d.over.pct.toFixed(0) + '%</b>'
    + '<span class="sub num">'
    + (played ? 'finished ' + (fh + fa) + ((fh + fa) > d.total ? ', over'
                                                              : ', under')
              : d.over.lo.toFixed(0) + '\u2013' + d.over.hi.toFixed(0)
                + '% range') + '</span></div></div>'
    + '<p class="help">Average result in those games: '
    + d.mean_total + ' total points, winner by '
    + Math.abs(d.mean_margin) + '.</p></div>'
    + '<h2 class="h1" style="font-size:19px;line-height:24px;margin-top:20px">'
    + 'How it finished</h2>'
    + '<div class="card">' + margins + '</div>'
    + '<h2 class="h1" style="font-size:19px;line-height:24px;margin-top:20px">'
    + 'Most common exact scores</h2>'
    + '<div class="card">' + scores
    + '<p class="help" style="margin-top:10px">Counts, not odds. The top '
    + 'scoreline here appeared a handful of times in ' + d.n + ' games, so '
    + 'treat the order as interesting and the percentage as very rough. The '
    + 'bands above pool far more games each.</p></div>';
}

// THE GAME MARKETS AS A SCORE LADDER, NOT AS A LIST OF BOOKS.
//
// This used to print every alternate line every book was quoting. That is
// eleven spreads and four totals per game, each with a fair chance of 50% —
// because a spread IS a coin flip by construction, so the column that looked
// like information was the one quantity that cannot vary. Nobody reads a page
// to learn that a -110 line is even money.
//
// What varies, and what a bettor actually wants, is: how many points is each
// side likely to score, and how often has a number like this been beaten.
// That comes from `score_dist` — real games priced like this one — and it
// gives a ladder rather than a single probability, so you can find YOUR
// number rather than the one the book chose to lead with.
function v3GameBets(gid) {
  const c = (v3GameSet().cards || []).filter(x => x.game_id === gid)[0];
  const L = c && c.ladders;
  const rows = ((DATA.games || {}).rows || []).filter(
    r => v3Same(r.game_id, gid));
  if (!L || !L.n) {
    return '<div class="card"><p class="lede" style="font-size:15px">No line '
      + 'on this game yet, so there is nothing to compare it with.</p></div>';
  }
  if (L.thin) {
    return '<div class="card"><p class="lede" style="font-size:15px">Only '
      + L.n + ' past games were priced near this spread and total — too few '
      + 'to build a table from.</p></div>';
  }

  // The best price on each side of the MAIN line, so "is it a good bet" has
  // an answer without listing every book. One number per side, not eleven.
  const priced = mk => {
    const rs = rows.filter(r => r.market === mk);
    if (!rs.length) return '';
    const best = {};
    rs.forEach(r => {
      const k = r.outcome;
      if (!best[k] || (r.ev100 || -99) > (best[k].ev100 || -99)) best[k] = r;
    });
    return Object.keys(best).slice(0, 2).map(k => {
      const r = best[k];
      // A SPREAD is signed; a TOTAL is not. "Over +44.5" reads as a
      // handicap and is just the number of points in the game.
      const pt = !has(r.point) ? ''
        : ' ' + (mk === 'spreads' && r.point > 0 ? '+' : '') + r.point;
      return '<span class="quote"><b>' + esc(k) + esc(pt) + '</b> '
        + v3Dash(american(r.best)) + '<i> at ' + esc(
          String(r.best_book || '').split(',')[0].trim()) + '</i></span>';
    }).join('');
  };

  // ONCE THE GAME IS PLAYED, EVERY ROW HAS AN ANSWER.
  //
  // Each row asks whether the game went over a number, and on a week that has
  // been played that is no longer a chance — it is a fact. `actual` colors
  // the rows it settled: green where the number was cleared, red where it was
  // not. A live week passes null and nothing is colored, because a table of
  // green rows on a game nobody has played would be reading a forecast as a
  // result.
  const table = (title, note, rowsIn, mark, actual) =>
    '<h2 class="h1" style="font-size:19px;line-height:24px;margin-top:20px">'
    + esc(title) + '</h2>'
    + (note ? '<p class="help">' + note + '</p>' : '')
    + (actual != null
       ? '<p class="help"><b>Finished at ' + actual + '.</b> Green cleared, '
         + 'red did not.</p>' : '')
    + '<div class="card"><div class="ltab">'
    + '<div class="ltab__h"><span>Over</span><span>Hit</span>'
    + '<span>How often</span></div>'
    + rowsIn.map(r => {
        const on = mark != null && Math.abs(r.line - mark) < 0.01;
        const hit = actual == null ? null : actual > r.line;
        return '<div class="ltab__r' + (on ? ' ltab__r--on' : '')
          + (hit == null ? '' : hit ? ' ltab__r--hit' : ' ltab__r--miss')
          + '">'
          + '<span class="num">' + r.line + (on ? ' \u00b7 posted' : '')
          + '</span>'
          + '<span class="num">' + r.pct.toFixed(0) + '%</span>'
          + '<span>' + v3Mini(r.pct) + '<i class="num">' + r.n + ' of '
          + L.n + '</i></span></div>';
      }).join('')
    + '</div></div>';

  // The finals, where there are any. A live card has none and everything
  // below reads exactly as it did before.
  const fh = c.final_home, fa = c.final_away;
  const played = has(fh) && has(fa);
  const finalTotal = played ? fh + fa : null;
  const finalMargin = played ? fh - fa : null;

  const teams = (L.teams || []).map(t =>
    table(t.team + ' points', 'How often ' + esc(t.team) + ' scored more than '
          + 'each number, in games priced like this one.', t.rows, null,
          !played ? null : t.team === c.home ? fh : t.team === c.away ? fa
                                                                     : null))
    .join('');

  return '<div class="card"><div class="eyebrow">Based on</div>'
    + '<p class="lede" style="font-size:15px;line-height:20px;margin-top:4px">'
    + '<b>' + L.n + ' past games</b> hung near this spread and total. The '
    + 'percentages are what happened in them, not a simulation.</p>'
    + (priced('spreads') || priced('totals')
       ? '<div class="quotes">' + priced('spreads') + priced('totals')
         + '</div>' : '')
    + '</div>'
    + table('Total points', 'The posted total is marked.',
            (L.total || {}).rows || [], (L.total || {}).posted, finalTotal)
    + table('Winning margin',
            'How often the home side won by more than each number. Negative '
            + 'means the away side won.',
            (L.spread || {}).rows || [], (L.spread || {}).posted, finalMargin)
    + teams
    + '<p class="help" style="margin-top:12px">Nothing here is smoothed, so '
    + 'the far ends of each table are ragged \u2014 that is sample, and the '
    + 'counts beside each row show how much of it there is.</p>';
}

const v3Mini = pct => '<em class="mini"><i style="width:'
  + Math.max(1, Math.round(pct)) + '%"></i></em>';

// ── screen: my picks ────────────────────────────────────────────────────

function v3Legs() {
  const out = [];
  for (const key of Object.keys(V.picks)) {
    const mk = key.split('|')[0];
    const hit = rowsFor(mk, null).filter(r => r.id === key)[0];
    if (hit) out.push(hit);
  }
  return out;
}

// ── screen: picks ──────────────────────────────────────────────────────
//
// The slips you kept, and how they turned out. `settle` is v2's and is not
// reforked: it reads `DATA.results`, which maps a leg to hit or miss and
// carries only graded weeks, so a leg it does not know keeps the whole slip
// PENDING rather than being assumed missed. A pick that reads Lost because a
// name failed to match is worse than one that reads Pending an hour longer.
function v3Picks() {
  const all = v3Saved().map(settle);
  const settled = all.filter(p => p.status !== 'Pending');
  const won = settled.filter(p => p.status === 'Won');
  const net = settled.reduce((a, p) => a + (p.net || 0), 0);

  if (!all.length) {
    return '<div class="wrap"><h1 class="h1">Picks</h1>'
      + '<p class="lede">Nothing kept yet. Add players from Props or a game, '
      + 'open the slip from the bar at the bottom, and press '
      + '\u201cSave to Picks\u201d. What you save stays here and settles '
      + 'itself as the games finish.</p></div>';
  }

  const counts = { all: all.length, pending: all.length - settled.length,
                   won: won.length, lost: settled.length - won.length };
  const f = V.savedFilter || 'all';
  const chips = [['all', 'All'], ['pending', 'Pending'], ['won', 'Won'],
                 ['lost', 'Lost']]
    .map(c => '<button class="mkt' + (counts[c[0]] ? '' : ' mkt--none')
      + '" data-v3savedfilter="' + c[0] + '" aria-pressed="' + (f === c[0])
      + '">' + esc(c[1]) + ' <i>' + counts[c[0]] + '</i></button>').join('');

  const keep = p => f === 'all'
    || (f === 'pending' && p.status === 'Pending')
    || (f === 'won' && p.status === 'Won')
    || (f === 'lost' && p.status === 'Lost');
  const shown = all.filter(keep).slice().reverse();

  return '<div class="wrap"><h1 class="h1">Picks</h1>'
    + '<p class="lede">Slips you kept. They settle on their own as the games '
    + 'finish.</p>'
    // THE RECORD, ONLY ONCE THERE IS ONE. Printing "0 settled, $0 net"
    // beside three pending slips reads as a result rather than as a wait.
    + (settled.length
       ? '<div class="card"><div class="three">'
         + '<div><span class="eyebrow">Settled</span>'
         + '<b class="num">' + settled.length + '</b></div>'
         + '<div><span class="eyebrow">Won</span>'
         + '<b class="num">' + won.length + '</b></div>'
         + '<div><span class="eyebrow">Net</span>'
         + '<b class="num ' + (net >= 0 ? 'good' : 'bad') + '">'
         + (net >= 0 ? '+' : '\u2212') + '$' + Math.abs(net).toFixed(2)
         + '</b></div></div></div>'
       : '')
    + '<div class="mkts" style="margin-top:16px">' + chips + '</div>'
    + (shown.length
       ? shown.map(v3PickCard).join('')
       : '<div class="empty">Nothing here is ' + esc(f) + '.</div>')
    + '</div>';
}

// A SAVED PICK OPENS THE SAME WAY THE SLIP DOES.
//
// The card is a summary; the question a reader actually has is the one the
// slip answers — what does this pay, at how many legs, and how likely is
// each. Drawn from the curve STORED WITH THE PICK, never recomputed from
// today's board: the prices have moved since, and a record that re-derived
// itself would quietly restate what was taken.
function v3PickBody() {
  const p = (v3Saved().filter(x => x.id === V.pick)[0]);
  if (!p) return '<p class="lede" style="font-size:15px">That pick is no '
    + 'longer saved.</p>';
  const st = settle(p);
  const pend = st.status === 'Pending';
  const n = (p.legs || []).length;
  const legs = (st.legs || []).map(l => {
    const dot = l.state === 'hit' ? 'good' : l.state === 'miss' ? 'bad' : 'pend';
    return '<div class="legline"><span><i class="dot dot--' + dot + '"></i>'
      + esc(l.label || l.player) + '</span>'
      + '<span class="sub num">' + (has(l.odds) ? v3Dash(american(l.odds))
                                                : '\u2014') + '</span></div>';
  }).join('');
  return '<div class="sub">' + esc(p.marketLabel) + ' \u00b7 week '
    + esc(String(p.week)) + ' \u00b7 $' + Number(p.stake).toFixed(0)
    + (p.slips > 1 ? ' each on ' + p.slips + ' slips' : '')
    + ' \u00b7 saved ' + esc(String(p.savedAt || '').slice(0, 10)) + '</div>'
    + '<div style="margin-top:12px">' + legs + '</div>'
    + '<div class="card" style="margin-top:16px">'
    + '<div class="sub">' + (p.betType === 'parlay'
        ? 'If every pick lands, you get back' : 'Best case, you get back')
    + '</div>'
    + '<div class="big num">$'
    + Number((p.outlay || 0) + Math.max.apply(null,
        (p.rows || [{ net: 0 }]).map(r => r.net || 0))).toFixed(2) + '</div>'
    + '<div class="sub num">You put in $' + Number(p.outlay || 0).toFixed(2)
    + '</div>'
    + '<div style="margin-top:16px">'
    + [v3OutHead()].concat(v3OutRows(p.rows || [], n,
                                     pend ? null : st.hits)).join('')
    + '</div>'
    // THE CURVE IS FROZEN AND SAYS SO. Its prices are the ones at save time.
    + '<p class="help">These are the prices this was saved at, not today\u2019s.</p>'
    + '</div>'
    + (pend ? ''
       : '<div class="box' + (st.net >= 0 ? ' box--good' : ' box--bad')
         + '" style="margin-top:12px"><span class="name" style="font-size:15px">'
         + esc(st.status) + ' \u00b7 ' + st.hits + ' of ' + n + ' landed'
         + '</span><span class="sub num">'
         + (st.net >= 0 ? '+' : '\u2212') + '$' + Math.abs(st.net).toFixed(2)
         + '</span></div>')
    + '<button class="cta" data-v3unkeep="' + esc(p.id) + '" '
    + 'style="background:var(--card);color:var(--bad);border-color:var(--bad)">'
    + 'Remove from Picks</button>';
}

function v3PickCard(p) {
  const pend = p.status === 'Pending';
  const tone = pend ? '' : p.status === 'Won' ? 'good' : 'bad';
  const legs = (p.legs || []).map(l => {
    const dot = l.state === 'hit' ? 'good' : l.state === 'miss' ? 'bad' : 'pend';
    return '<div class="legline"><span><i class="dot dot--' + dot + '"></i>'
      + esc(l.label || l.player) + '</span>'
      + '<span class="sub num">' + (has(l.odds) ? v3Dash(american(l.odds))
                                                : '\u2014') + '</span></div>';
  }).join('');
  // The row of the stored curve that actually happened. Re-derived nothing:
  // a full cover pays every sub-slip whose legs landed, and those have
  // different prices, so there is no single number to multiply.
  const row = (p.rows || []).filter(r => r.hit === p.hits)[0];
  return '<div class="card" data-v3pickopen="' + esc(p.id) + '" '
    + 'role="button" tabindex="0" style="cursor:pointer">'
    + '<div class="pub__h"><span class="name">' + esc(p.name) + '</span>'
    + '<span class="tag' + (tone ? ' tag--' + tone : '') + '">'
    + esc(p.status) + '</span></div>'
    + '<div class="sub" style="margin-top:2px">' + esc(p.marketLabel)
    + ' \u00b7 week ' + esc(String(p.week)) + ' \u00b7 $'
    + Number(p.stake).toFixed(0)
    + (p.slips > 1 ? ' each on ' + p.slips + ' slips' : '') + '</div>'
    + '<div style="margin-top:10px">' + legs + '</div>'
    + (pend
       ? '<div class="sub num" style="margin-top:10px">Pays '
         + (p.dec ? v3Dash(american(decToAm(p.dec))) : '\u2014')
         + ' if every pick lands \u00b7 ' + v3Pct(p.chance) + '</div>'
       : '<div class="three panel" style="margin-top:10px">'
         + '<div><span class="eyebrow">Landed</span><b class="num">'
         + p.hits + ' of ' + (p.legs || []).length + '</b></div>'
         + '<div><span class="eyebrow">Put in</span><b class="num">$'
         + Number(p.outlay || 0).toFixed(2) + '</b></div>'
         + '<div><span class="eyebrow">Came back</span>'
         + '<b class="num ' + ((p.net || 0) >= 0 ? 'good' : 'bad') + '">'
         + ((p.net || 0) >= 0 ? '+' : '\u2212') + '$'
         + Math.abs(p.net || 0).toFixed(2) + '</b></div></div>')
    + '<p class="help" style="margin-top:10px">Tap for the full breakdown.</p>'
    + '</div>';
}

// THE SLIP, IN A SHEET OVER WHATEVER YOU ARE READING.
//
// It used to be a tab, which meant leaving the board to look at what you had
// just added to it and then navigating back. v2 opened it as a panel from the
// bar at the bottom and that is the better shape: the slip is about the page
// you are on, so it sits over it and closes back onto it.
function v3SlipBody() {
  const legs = v3Legs();
  if (!legs.length) {
    return '<p class="lede" style="font-size:15px">Nothing added yet. Tap + '
      + 'beside a player and they will show up here with what the bet '
      + 'pays.</p>';
  }
  const dec = legs.map(l => l.dec).filter(has);
  const ps = legs.map(l => betProb(l)).filter(has);
  const ok = dec.length === legs.length && ps.length === legs.length;
  const type = V3BETTYPES.filter(t => t[0] === V.betType)[0] || V3BETTYPES[0];
  const saved = v3IsSaved(legs);

  // EVERY LEG CAN BE REMOVED THREE WAYS: swipe it, press the cross, or untap
  // the tick. The first version had only the tick, which meant a pick you no
  // longer wanted had to be hunted down on the board it came from.
  const rows = legs.map(l => '<div class="legwrap" data-leg="' + esc(l.id) + '">'
    + '<button class="legdel" data-v3drop="' + esc(l.id)
    + '" aria-label="Remove ' + esc(l.player) + '">Remove</button>'
    + '<div class="row"><div class="row__m">'
    + '<div class="row__t"><div style="min-width:0">'
    + '<div class="name">' + esc(l.player) + '</div>'
    + '<div class="sub">' + esc(v3Fixture(l)) + '</div>'
    + (v3Line(l) ? '<div class="line">' + esc(v3Line(l)) + '</div>' : '')
    + '</div><div class="chance"><b class="num">' + v3Pct(betProb(l), 1)
    + '</b><span class="sub num">' + v3Dash(american(l.odds))
    + '</span></div></div></div>'
    + '<button class="add" data-v3drop="' + esc(l.id) + '" '
    + 'aria-label="Remove ' + esc(l.player) + '">\u2715</button>'
    + '</div></div>').join('');

  return '<p class="help" style="margin-top:0">' + legs.length + ' pick'
    + (legs.length === 1 ? '' : 's') + '. Swipe one left to remove it.</p>'
    + '<div class="list">' + rows + '</div>'
    + '<div class="chooser">'
    + '<button class="choose" data-v3sheet="bet">'
    + '<span class="eyebrow">How</span>'
    + '<b>' + esc(type[1]) + '</b></button>'
    + '<button class="choose" data-v3sheet="stake">'
    + '<span class="eyebrow">Stake</span>'
    + '<b class="num">$' + V.stake + '</b></button>'
    + '</div>'
    + '<p class="help">' + esc(type[2]) + '</p>'
    + (ok ? v3Outcomes(legs, V.stake)
          : '<div class="card"><p class="lede" style="font-size:15px">One of '
            + 'these picks has no posted price, so the payout cannot be worked '
            + 'out. Remove it to see the numbers.</p></div>')
    // SAVING IS A COPY. The slip is untouched by it, so the same legs can be
    // saved at one stake and then rebuilt at another.
    + (ok ? '<button class="cta" data-v3keep="1"' + (saved ? ' disabled' : '')
            + '>' + (saved ? '\u2713 Saved to Picks' : 'Save to Picks')
            + '</button>'
          : '')
    + (saved ? '<button class="cta" data-v3tab="picks" '
               + 'style="background:var(--card);color:var(--ours);'
               + 'border-color:var(--ours)">See your Picks</button>' : '')
    + '<button class="cta" data-v3clear="1" style="background:var(--card);'
    + 'color:var(--bad);border-color:var(--bad)">Clear the slip</button>';
}

// Enumerate every combination rather than approximating. With a handful of
// legs this is 2^n and instant, and it is the only way "2 of 3 land" can
// state a real chance rather than a hand-wave.
//
// TREATED AS INDEPENDENT, AND THAT IS A REAL ASSUMPTION. Two players in the
// same game are not: if one scores, the other's team is more likely behind.
// The page says so rather than burying it, because the error runs one way —
// a same-game parlay's true chance is HIGHER than the product for players on
// the same side, and lower across sides.
// ── same-game correlation ───────────────────────────────────────────────
//
// TWO PICKS IN ONE GAME ARE NOT INDEPENDENT, and the slip has said so in
// small print under a number that assumed they were. They are close to
// independent GIVEN HOW THE GAME GOES, so the chance is taken across the
// margin bands rather than through them:
//
//     P(all land) = SUM over bands  P(band) * PRODUCT P(leg | band)
//
// `DATA.games.bands` is that partition per game, counted over games the
// market priced alike; `script_fits` moves each leg within a band, fitted per
// position and market. A leg on the away bench reads the same game flipped,
// which is what makes two opposing backs pull against each other.
//
// Each leg is rescaled to keep its own marginal, so the single-leg number the
// board shows never moves — only the joint does.
//
// Mirrors `src/models/correlation.py`, and a test runs both on the same
// inputs and fails if they disagree.
const V3FLIP = { 'won big': 'lost big', 'won': 'lost', 'close': 'close',
                 'lost': 'won', 'lost big': 'won big' };
const V3BANDS = ['won big', 'won', 'close', 'lost', 'lost big'];

function v3Cond(p, mult, probs) {
  let tilt = 0;
  for (const b of V3BANDS) tilt += (probs[b] || 0) * mult[b];
  if (!(tilt > 0)) return null;
  const out = {};
  for (const b of V3BANDS) {
    if (!(probs[b] > 0)) continue;
    out[b] = Math.min(1, Math.max(0, p * mult[b] / tilt));
  }
  return out;
}

// One game's legs, priced together. Legs from other games stay independent of
// these, which is the same assumption the slip already makes between games.
function v3JointOne(gid, legs) {
  const g = (v3GameSet().cards || []).filter(c => v3Same(c.game_id, gid))[0];
  const probs = g && g.bands;
  if (!probs || legs.length < 2) return null;
  const fits = (DATA.games || {}).script_fits || {};
  const conds = [];
  for (const leg of legs) {
    const p = betProb(leg);
    if (p == null) return null;
    const f = fits[leg.pos + '|' + V3SCRIPTSTAT[leg.key]];
    if (!f) { const flat = {}; for (const b in probs) flat[b] = p;
              conds.push(flat); continue; }
    const home = leg.team === g.home;
    const mult = {};
    for (const b of V3BANDS) mult[b] = f.mult[home ? b : V3FLIP[b]];
    const c = v3Cond(p, mult, probs);
    if (!c) return null;
    conds.push(c);
  }
  let together = 0, independent = 1;
  for (const b in probs) {
    let q = probs[b];
    for (const c of conds) q *= (c[b] || 0);
    together += q;
  }
  for (const leg of legs) independent *= betProb(leg);
  if (!(independent > 0)) return null;
  const k = ((DATA.games || {}).correlation || {}).k || 1;
  return { independent: independent,
           lift: Math.pow(together / independent, k) };
}

//: Board market key to the stat `script_fits` is keyed by.
const V3SCRIPTSTAT = { rush: 'rushing_yards', recyds: 'receiving_yards',
                       rec: 'receptions', passyds: 'passing_yards',
                       any: 'carries', first: 'carries' };

// The whole slip: every game's legs corrected, games independent of each
// other. Returns the combined multiplier and which games moved.
function v3Correlation(legs) {
  const byGame = {};
  for (const leg of legs) {
    const k = v3Key(leg.gameId);
    (byGame[k] = byGame[k] || []).push(leg);
  }
  let lift = 1, moved = 0, games = 0;
  for (const k of Object.keys(byGame)) {
    if (byGame[k].length < 2) continue;
    games++;
    const r = v3JointOne(k, byGame[k]);
    if (!r || r.lift == null) continue;
    lift *= r.lift;
    if (Math.abs(r.lift - 1) >= 0.005) moved++;
  }
  return games ? { lift: lift, games: games, moved: moved } : null;
}

// ── closing-line value, while it is still happening ────────────────────
//
// THE ONE CLAIM THIS PROJECT HAS ACTUALLY PROVEN, AND IT WAS INVISIBLE.
//
// No model here beats its market on raw output. What the archive shows is
// that the market MOVES TOWARD the players we rate above the opening price —
// about 60% of the time against a 54% shuffle null, over ~18,000 closes. That
// is measured in a backtest nobody reading the board can see.
//
// Every row already carries `openImplied`, so the same thing is checkable
// live: of the picks we rated above the number the book opened, how many has
// the market since come toward? It is the project's own claim, counted on
// this week's board, before the games are played.
//
// Counted ONLY on rows we rated above the open. "The price moved" is not the
// claim; "it moved our way on the ones we disagreed about" is, and counting
// the rest would dilute it toward 50% by construction.
// LIKE FOR LIKE, OR THE DIFFERENCE IS NOT A MOVE.
//
// `openImplied` is the RAW implied probability of the opening price. It is
// kept raw deliberately — `opening_prices` says so in as many words: "the
// implied figure is always there, and comparing it to the board's implied
// price is like for like — both carry the book's margin, so the difference is
// the market moving rather than the margin changing."
//
// `book` is the DE-VIGGED number. Subtracting the raw open from the de-vigged
// now measures the overround, not the market, and it does so in one direction:
// the de-vig only ever lowers a touchdown price, so the difference reads
// negative whatever the market did.
//
// Measured on the live board the day this was found: of 814 priced rows, 316
// carried the move with the WRONG SIGN. Kyren Williams showed "-12.0pp" on a
// market that had come 8.6pp toward him. It also drove the closing-line note,
// which is this project's one measured claim — a slip of five picks the market
// had moved toward reported "0 of 5".
function v3NowImplied(row) {
  return has(row.odds) ? 1 / amToDec(row.odds) : null;
}

function v3Clv(rows) {
  let n = 0, toward = 0;
  for (const r of rows || []) {
    const open = r.openImplied, now = v3NowImplied(r), ours = betProb(r);
    if (!has(open) || !has(now) || !has(ours)) continue;
    if (ours <= open) continue;          // we did not rate it above the open
    n++;
    if (now > open) toward++;
  }
  return n ? { n: n, toward: toward, pct: toward / n } : null;
}

function v3ClvNote(rows, what) {
  const c = v3Clv(rows);
  // Under a handful of picks the share is noise and printing it invites a
  // reader to draw a conclusion from four coin flips.
  if (!c || c.n < 4) return '';
  return '<p class="help">Since these lines opened, the market has moved '
    + 'toward our number on <b>' + c.toward + ' of ' + c.n + '</b> '
    + esc(what) + ' we rated above the opening price'
    + (c.pct >= 0.5 ? '' : '') + '. Over three seasons that has run near 60%, '
    + 'against 54% for a shuffled list — it is the one edge this project has '
    + 'measured, and it is about the PRICE moving, not about the bet '
    + 'winning.</p>';
}

// THE CAVEAT BECOMES A NUMBER.
//
// It used to read "two players in the same game are not independent — on the
// same team a parlay is worth a little more than this says, on opposite
// teams a little less", under a number that had not been corrected. It is
// corrected now, so the note says which way and by how much, and says
// nothing at all when no two picks share a game.
function v3CorrNote(legs) {
  const c = v3Correlation(legs);
  if (!c || !c.games) {
    return '<p class="help">No two picks here are in the same game, so '
      + 'multiplying the chances is the right answer.</p>';
  }
  const pct = Math.abs(c.lift - 1) * 100;
  if (pct < 0.5) {
    return '<p class="help">Two of these picks share a game. Priced together '
      + 'rather than multiplied, which changes the answer by less than half '
      + 'a point here.</p>';
  }
  const up = c.lift > 1;
  return '<p class="help">' + (c.games > 1 ? 'Some of these picks share a '
      + 'game' : 'Two of these picks share a game')
    + ', so they are priced TOGETHER rather than multiplied: '
    + (up ? 'they want the same kind of game, which makes this land '
          : 'the game that helps one tends to hurt the other, which makes '
            + 'this land ')
    + pct.toFixed(1) + '% ' + (up ? 'more' : 'less') + ' often than '
    + 'multiplying the chances says. Counted over '
    + v3Num2((((DATA.games || {}).correlation || {}).n) || 0)
    + ' past pairs.</p>';
}

//: Thousands separators, for a count that runs to six figures.
function v3Num2(n) {
  return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

// ── the slip, and the picks it becomes ─────────────────────────────────
//
// A SLIP IS NOT A SAVED PICK, AND THIS PAGE CONFLATED THEM.
//
// v2 had it right and v3 lost it: the slip is the thing you are building
// right now, reachable from the bar at the bottom of whatever you are
// reading, and it is gone the moment you clear it. A SAVED pick is a copy
// taken at a price, which then settles itself as the games finish. One is a
// draft, the other is a record, and a tab called "My picks" that showed the
// draft meant there was nowhere for the record to live.
//
// So the bar opens the slip in a sheet, over the board you are on — the
// popup v2 had — and the tab is the saved ones.
//
// WHAT IS STORED IS THE STRUCTURE, NOT A POINTER AT THE BOARD. The legs, the
// bet type, the stake and the whole payout curve, because prices move under a
// saved slip and a record that re-derived itself from today's board would
// quietly rewrite what you actually took.
function v3Saved() {
  return Array.isArray(V.saved) ? V.saved : [];
}

//: The slip as it stands, as a comparable string. Saving twice without
//: changing anything should say "saved", not make a second copy.
function v3Sig(legs) {
  return V.betType + '|' + V.stake + '|'
    + legs.map(l => l.id).slice().sort().join(',');
}

function v3IsSaved(legs) {
  const sig = v3Sig(legs);
  return v3Saved().some(p => p.sig === sig && p.week === DATA.week);
}

function v3SaveSlip() {
  const legs = v3Legs();
  if (!legs.length) return;
  if (v3IsSaved(legs)) return;
  const m = v3SlipMath(legs, V.stake);
  const type = V3BETTYPES.filter(t => t[0] === V.betType)[0] || V3BETTYPES[0];
  const dec = legs.every(l => has(l.dec))
    ? legs.reduce((a, l) => a * l.dec, 1) : null;
  const p = {
    id: 'p' + Date.now().toString(36),
    sig: v3Sig(legs),
    name: legs.length + (legs.length === 1 ? ' pick' : ' picks'),
    marketLabel: type[1],
    week: DATA.week, season: DATA.season,
    betType: V.betType, stake: V.stake, size: 0,
    slips: m.slips, outlay: m.cost, chance: m.all, priced: m.priced,
    dec: dec, ev: m.ev,
    // The curve, at the stake it was priced at. Net is linear in the stake,
    // so a card can re-read it at another one — but only if it knows which
    // stake produced it.
    rows: m.byK.map(b => ({ hit: b.hit, slipsWon: b.slipsWon, chance: b.p,
                            net: b.net, netLo: b.lo, netHi: b.hi })),
    rowStake: V.stake,
    legs: legs.map(l => ({ id: l.id, key: l.key, player: l.player,
                           side: l.take, label: v3LegLabel(l), odds: l.odds,
                           dec: l.dec, p: betProb(l), game: l.game })),
    savedAt: new Date().toISOString(),
  };
  V.saved = v3Saved().concat([p]);
  v3Save();
}

//: What a leg is called on a saved card, once the board it came from has
//: moved on. Built at save time for that reason.
function v3LegLabel(l) {
  const line = v3Line(l);
  return l.player + (line ? ' \u00b7 ' + line : '');
}

function v3DropSaved(id) {
  V.saved = v3Saved().filter(p => p.id !== id);
  v3Save();
}

// ONE OUTCOME TABLE, TWO SOURCES.
//
// The slip computes its curve from today's prices; a saved pick reads the
// curve it was stored with. The same table draws both, or the page would
// show two different-looking answers to one question depending on whether
// the reader had pressed save.
function v3OutHead() {
  return '<div class="out" style="border:0;min-height:0;padding-bottom:8px">'
    + '<span class="eyebrow">If…</span>'
    + '<span class="eyebrow">Chance</span>'
    + '<span class="eyebrow">You’d be</span></div>';
}

//: `list` is anything carrying `hit`, a chance and a net — `v3SlipMath`'s
//: `byK` or a saved pick's stored `rows`. `now` marks the row that actually
//: happened, which only a settled pick has.
function v3OutRows(list, n, now) {
  const label = k => k === 0 ? 'None land'
    : k === n ? 'All ' + n + ' land' : k + ' of ' + n + ' land';
  const out = [];
  for (let k = n; k >= 0; k--) {
    const r = (list || []).filter(x => x.hit === k)[0];
    if (!r) continue;
    const net = r.net, pr = has(r.p) ? r.p : r.chance;
    const col = net > 0.005 ? 'var(--good)' : net < -0.005 ? 'var(--bad)'
      : 'var(--mut)';
    const on = now != null && now === k;
    out.push('<div class="out' + (on ? ' out--on' : '') + '">'
      + '<span>' + label(k) + (on ? ' · this one' : '') + '</span>'
      + '<span class="num">' + v3Pct(pr) + '</span>'
      + '<span class="num" style="font-weight:600;color:' + col + '">'
      + (Math.abs(net) < 0.005 ? '$0.00'
         : (net >= 0 ? '+' : '−') + '$' + Math.abs(net).toFixed(2))
      + '</span></div>');
  }
  return out;
}

// THE MATH, SEPARATE FROM THE DRAWING.
//
// It used to be one function that computed the payout curve and returned
// HTML. A saved pick has to store that curve — `settle` reads it back to say
// what a slip actually paid, months after the prices moved — and a curve that
// only exists inside a string cannot be stored. Same numbers, two readers.
//
// `byK[k]` is the chance exactly k legs land and the net that follows. For a
// parlay the net is the same whichever k legs they are; for singles and pairs
// it is not, so `lo` and `hi` carry the spread and `net` is the
// probability-weighted middle — which is what the row prints.
function v3SlipMath(legs, stake, betType) {
  const type = betType || V.betType;
  const n = legs.length;
  const d = legs.map(l => l.dec), p = legs.map(l => betProb(l));
  const cost = type === 'parlay' ? stake
    : type === 'singles' ? n * stake : (n * (n - 1) / 2) * stake;
  const byK = [];
  for (let i = 0; i <= n; i++) {
    byK.push({ hit: i, p: 0, ev: 0, lo: null, hi: null, slipsWon: 0 });
  }
  let ev = 0;
  for (let m = 0; m < (1 << n); m++) {
    let pr = 1, k = 0, ret = 0, won = 0;
    const hit = [];
    for (let i = 0; i < n; i++) {
      const h = !!(m & (1 << i));
      hit.push(h); pr *= h ? p[i] : 1 - p[i]; if (h) k++;
    }
    if (type === 'parlay') {
      ret = k === n ? stake * d.reduce((a, b) => a * b, 1) : 0;
      won = k === n ? 1 : 0;
    } else if (type === 'singles') {
      for (let i = 0; i < n; i++) if (hit[i]) { ret += stake * d[i]; won++; }
    } else {
      for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++)
        if (hit[i] && hit[j]) { ret += stake * d[i] * d[j]; won++; }
    }
    const net = ret - cost;
    const b = byK[k];
    b.p += pr; b.ev += pr * net; ev += pr * net;
    b.slipsWon = Math.max(b.slipsWon, won);
    b.lo = b.lo == null ? net : Math.min(b.lo, net);
    b.hi = b.hi == null ? net : Math.max(b.hi, net);
  }
  for (const b of byK) b.net = b.p ? b.ev / b.p : (b.lo == null ? 0 : b.lo);
  const best = type === 'parlay' ? stake * d.reduce((a, b) => a * b, 1)
    : type === 'singles' ? stake * d.reduce((a, b) => a + b, 0)
    : (() => { let t = 0; for (let i = 0; i < n; i++)
        for (let j = i + 1; j < n; j++) t += stake * d[i] * d[j]; return t; })();
  const all = byK[n] ? byK[n].p : 0;
  return { n: n, cost: cost, best: best, ev: ev, byK: byK, all: all,
           slips: type === 'parlay' ? 1
                  : type === 'singles' ? n : (n * (n - 1) / 2),
           priced: d.every(has) && p.every(has) };
}

function v3Outcomes(legs, stake) {
  const n = legs.length;
  const m = v3SlipMath(legs, stake);
  const byK = m.byK, cost = m.cost, best = m.best, ev = m.ev;

  const rows = [v3OutHead()].concat(v3OutRows(byK, n));
  return '<div class="card">'
    + '<div class="sub">' + (V.betType === 'parlay'
        ? 'If every pick lands, you get back' : 'Best case, you get back')
    + '</div>'
    + '<div class="big num">$' + best.toFixed(2) + '</div>'
    + '<div class="sub num">You put in $' + cost.toFixed(2)
    + (V.betType === 'parlay' ? '' : ' in total') + '</div>'
    + '<div style="margin-top:16px">' + rows.join('') + '</div>'
    + '<div class="box" style="margin-top:16px">'
    + '<span class="name" style="font-size:15px">'
    + (ev >= 0 ? 'Worth it over time' : 'Costs a little over time') + '</span>'
    + '<span class="sub">Made many times, this averages about '
    + (ev >= 0 ? '+' : '−') + '$' + Math.abs(ev).toFixed(2)
    + ' a go, if our chances are right.</span></div>'
    + v3CorrNote(legs)
    + v3ClvNote(legs, 'of your picks')
    + '</div>';
}

// ── screen: ladder ──────────────────────────────────────────────────────

// THE LADDER, DRIVEN BY WHAT YOU TYPE.
//
// It used to offer four stakes and three canned "kinds" of pick, which meant
// the one question it exists to answer — what does MY bet at MY price turn
// into — could only be asked in twelve ways. Stake, odds and the number of
// rungs are fields now, and the table follows them.
//
// The table is patched in place on every keystroke rather than re-rendered,
// for the same reason the search box is: replacing the input being typed
// into loses focus and the caret.
function v3LadderInputs() {
  const f = (key, label, val, hint, mode) =>
    '<label class="lfield"><span class="eyebrow">' + esc(label) + '</span>'
    + '<input data-v3l="' + key + '" inputmode="' + mode + '" value="'
    + esc(String(val)) + '" aria-label="' + esc(label) + '">'
    + (hint ? '<i>' + esc(hint) + '</i>' : '') + '</label>';
  return '<div class="lfields">'
    + f('stake', 'Start with', '$' + V.stake, '', 'decimal')
    + f('odds', 'Odds each step', v3Dash(american(V.lodds)),
        v3OddsHint(), 'text')
    + f('rungs', 'Steps', V.rungs, '', 'numeric')
    + '</div>';
}

function v3OddsHint() {
  const d = amToDec(V.lodds);
  return 'about ' + Math.round(100 / d) + '% each';
}

//: Parsed leniently — "+150", "150", "-150", "$25", "25" all mean something
//: obvious, and a field that rejects "$25" because of the dollar sign is a
//: field that makes the reader do the app's job.
function v3Num(v) {
  const n = parseFloat(String(v).replace(/[^0-9.\-]/g, ''));
  return isFinite(n) ? n : null;
}

function v3Rungs() {
  const d = amToDec(V.lodds), p = 1 / d, start = V.stake;
  const n = Math.max(1, Math.min(20, V.rungs));
  let out = '';
  for (let k = 1; k <= n; k++) {
    const pk = Math.pow(p, k), bank = start * Math.pow(d, k);
    out += '<div class="rung' + ((k - 1) % 2 ? ' rung--alt' : '') + '">'
      + '<span class="num" style="font-weight:600;color:var(--mut)">' + k
      + '</span>'
      + '<span class="num" style="font-size:17px;font-weight:600">$'
      + (bank >= 1000 ? Math.round(bank).toLocaleString() : bank.toFixed(2))
      + '</span>'
      + '<span><span class="num" style="font-weight:600">' + v3Pct(pk)
      + '</span><br><span class="sub num">about 1 in '
      + Math.max(1, Math.round(1 / pk)) + '</span></span></div>';
  }
  return out;
}

function v3LadderSummary() {
  const d = amToDec(V.lodds);
  const n = Math.max(1, Math.min(20, V.rungs));
  const end = V.stake * Math.pow(d, n);
  const p = Math.pow(1 / d, n);
  return n + ' wins in a row turns $' + V.stake.toFixed(2) + ' into $'
    + (end >= 1000 ? Math.round(end).toLocaleString() : end.toFixed(2))
    + ' \u2014 about ' + v3Pct(p) + ', or 1 in '
    + Math.max(1, Math.round(1 / p)) + '.';
}

function v3Ladder() {
  return '<div class="wrap"><h1 class="h1">The ladder</h1>'
    + '<p class="lede">Start small. Each time a bet wins, the whole amount '
    + 'rides on the next one. Climb as high as you like and stop whenever you '
    + 'want. One loss and you are back to the start.</p>'
    + v3LadderInputs()
    + '<div class="list"><div class="rung" style="border:0">'
    + '<span class="eyebrow">Step</span>'
    + '<span class="eyebrow">You\u2019d have</span>'
    + '<span class="eyebrow">Chance</span></div>'
    + '<div id="v3rungs">' + v3Rungs() + '</div></div>'
    + '<div class="card"><div class="name" id="v3lsum">'
    + esc(v3LadderSummary()) + '</div>'
    + '<p class="lede" style="font-size:15px;margin-top:6px">Each row assumes '
    + 'every step above it won. The chance is how often you would get that '
    + 'far if every pick is priced fairly \u2014 which is the generous '
    + 'assumption, because the book\u2019s cut means they are not.</p>'
    + '</div></div>';
}

// ── shell ───────────────────────────────────────────────────────────────

// THE BOTTOM SHEET. A phone picks from a sheet, not from a page of radio
// buttons — the first version laid the bet-type and stake controls out inline
// and the screen became a form. v2 had this right.
const V3SHEETS = {
  bet: () => v3SheetHTML('How do you want to bet?',
    V3BETTYPES.map(t => v3Opt(t[1], V.betType === t[0], t[2], 'v3type', t[0]))
      .join('')),
  stake: () => v3SheetHTML(
    V.betType === 'parlay' ? 'How much?' : 'How much on each bet?',
    [5, 10, 20, 25, 50, 100].map(x =>
      v3Opt('$' + x, V.stake === x, '', 'v3stake', String(x))).join('')),
  sort: () => v3SheetHTML('Sort by',
    V3SORTS.map(c => v3Opt(c[1], V.sort === c[0], '', 'v3sortpick', c[0]))
      .join('')),
  // ASKING IS ABOUT WHATEVER YOU ARE LOOKING AT.
  //
  // The box lived at the bottom of the Notes tab, so a question prompted by
  // a number on Matchup or Outcome meant leaving that number, scrolling past
  // every note, asking, and navigating back. A tab of its own has the same
  // fault and costs a sixth of the tab bar. In the sheet it opens over
  // whichever tab raised the question and closes back onto it.
  ask: () => v3SheetHTML('Ask about this game', v3Ask(V.game, true)),
  slip: () => v3SheetHTML('Your slip', v3SlipBody()),
  pick: () => v3SheetHTML('Saved pick', v3PickBody()),
};

function v3SheetHTML(title, body) {
  return '<div class="sheet__grab"><i></i></div>'
    + '<div class="sheet__head"><b>' + esc(title) + '</b>'
    + '<button class="sheet__x" data-v3close="1" aria-label="Close">'
    + '\u2715</button></div>'
    + '<div class="sheet__body">' + body + '</div>';
}

function v3Opt(label, on, note, attr, val) {
  return '<button class="opt" data-' + attr + '="' + esc(val) + '" '
    + 'aria-pressed="' + on + '"><span class="radio"><i></i></span>'
    + '<span><span class="name">' + esc(label) + '</span>'
    + (note ? '<br><span class="sub">' + esc(note) + '</span>' : '')
    + '</span></button>';
}

function v3Sheet() {
  const scrim = document.getElementById('scrim');
  const sheet = document.getElementById('sheet');
  if (!scrim || !sheet) return;
  if (!V.sheet || !V3SHEETS[V.sheet]) {
    scrim.className = 'scrim'; sheet.className = 'sheet'; sheet.innerHTML = '';
    return;
  }
  sheet.innerHTML = V3SHEETS[V.sheet]();
  scrim.className = 'scrim open'; sheet.className = 'sheet open';
}

// ROUND ROBIN FIRST, AND IT IS THE DEFAULT.
//
// It was called "Any two", which describes the mechanic and hides the name
// everyone actually uses for it. It also sat second behind all-or-nothing,
// which is the hardest bet on the list to win — a poor thing to open on for
// a reader who does not bet much.
//
// A round robin here is every PAIR. Bigger sizes exist in the wild; this
// builds the 2-leg cover and says so, rather than offering a size control
// whose larger settings this page cannot price.
const V3BETTYPES = [
  ['twos', 'Round robin',
   'A separate bet on every pair. Any two landing wins something, so one '
   + 'miss does not empty the slip.'],
  ['parlay', 'All or nothing',
   'One bet. Every pick has to land. Biggest payout, hardest to win.'],
  ['singles', 'Each on its own',
   'Separate bets. Every pick that lands pays out.'],
];

function v3Nav() {
  return V3TABS.map(t =>
    '<a data-v3tab="' + t[0] + '"' + (V.tab === t[0] && !V.game
      ? ' aria-current="page"' : '') + '>'
    + '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" '
    + 'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
    + 'stroke-linejoin="round" aria-hidden="true"><path d="' + t[2]
    + '"></path></svg>' + esc(t[1]) + '</a>').join('');
}

// THE SLIP BAR, WITH A WAY OUT OF IT.
//
// The first version was a floating button with no dismiss and no clear: once
// a pick was added the bar sat there and the only way to empty it was to find
// each row again and untap it. Three ways out now, because a phone pattern
// that only works with a thumb strands anyone on a desktop: swipe it left,
// press the cross, or open it and remove legs.
function v3Slipbar() {
  const legs = v3Legs();
  if (!legs.length) return '';
  const names = legs.map(l => esc(v3Surname(l.player))).join(' \u00b7 ');
  const dec = legs.every(l => has(l.dec))
    ? legs.reduce((a, l) => a * l.dec, 1) : null;
  return '<div class="slipwrap" id="slipwrap">'
    + '<button class="slipdel" data-v3clear="1" aria-label="Clear all picks">'
    + 'Clear</button>'
    + '<div class="slipbar">'
    + '<span class="slipbar__count num">' + legs.length + '</span>'
    + '<span class="slipbar__main">'
    + '<span class="slipbar__price num">'
    + (dec ? v3Dash(american(decToAm(dec))) : '\u2014') + '</span>'
    + '<span class="slipbar__legs">' + names + '</span></span>'
    + '<button class="slipbar__open" data-v3sheet="slip">Open</button>'
    + '<button class="slipbar__x" data-v3clear="1" aria-label="Clear all picks">'
    + '\u2715</button>'
    + '</div></div>';
}

// Matched on the whole row's name, case- and accent-insensitively, so
// "kupp", "Kupp" and "KUPP" all find him and "a.j." finds A.J. Brown.
function v3Match(rows) {
  const q = (V.q || '').trim().toLowerCase();
  if (!q) return rows;
  return rows.filter(r => String(r.player || '').toLowerCase().indexOf(q) >= 0);
}

const v3Surname = n => {
  const b = String(n || '').trim().split(' ');
  return b.length > 1 ? b[b.length - 1] : (b[0] || '');
};

// A BACK STACK, because a phone has a back gesture and a browser has a
// button and neither of them knew this app existed. Every navigation pushes;
// `popstate` restores. Only the fields that name a SCREEN are in the entry —
// putting the whole of `V` in there would make changing a sort order a
// history step, and twelve taps of Back would be twelve sort orders.
function v3Where() {
  return { tab: V.tab, game: V.game, gameTab: V.gameTab, week: V.week,
           market: V.market };
}

let v3Booted = false;

function v3Push() {
  // Guarded. A page without `history.pushState` still has to render — the
  // back gesture is an enhancement, and losing it must not lose the app.
  if (typeof history === 'undefined' || !history.pushState) return;
  const w = v3Where();
  const hash = '#/' + w.tab + (w.game ? '/' + w.game + '/' + w.gameTab : '');
  const at = (typeof location !== 'undefined' && location.hash) || '';
  try {
    if (!v3Booted) { history.replaceState(w, '', hash); v3Booted = true; }
    else if (at !== hash) history.pushState(w, '', hash);
    else history.replaceState(w, '', hash);
  } catch (e) { /* file:// refuses pushState in some browsers */ }
}

if (typeof window !== 'undefined' && window.addEventListener) {
  window.addEventListener('popstate', ev => {
    if (ev && ev.state) {
      Object.assign(V, ev.state);
      // An entry pushed before Bets and Score merged still names one of them.
      V.gameTab = v3GTab(V.gameTab);
      if (V.tab === 'slip') V.tab = 'picks';
      if (!Array.isArray(V.saved)) V.saved = [];
      V.top = true; render(true);
    }
  });
}

function render(fromHistory) {
  const el = id => document.getElementById(id);
  const app = el('app');
  if (!app) return;
  if (!fromHistory) v3Push();
  const scroll = el('scroll');
  const y = scroll ? scroll.scrollTop : 0;
  if (el('appbar')) el('appbar').innerHTML = v3Header();
  app.innerHTML = v3Screen();
  if (el('slipbarHost')) el('slipbarHost').innerHTML = v3Slipbar();
  if (el('tabbar')) el('tabbar').innerHTML = v3Nav();
  v3Sheet();
  // KEPT WITHIN A SCREEN, RESET ON NAVIGATION.
  //
  // Re-rendering the shell on every tap would throw you to the top each time
  // you starred a row, so the position is restored by default. But opening a
  // game from halfway down the Games list landed you halfway down the GAME —
  // a different page at someone else's scroll offset. `v3Nav` actions set
  // `V.top`, and only those start at the beginning.
  if (scroll) scroll.scrollTop = V.top ? 0 : y;
  V.top = false;
  v3Save();
}

// One delegated listener. Every control is a `data-v3*` attribute, so a
// control that is added and never wired here does nothing at all rather than
// throwing — which is why `test_every_v3_control_is_handled` exists.
const V3CLICKS = ['v3tab', 'v3mkt', 'v3sort', 'v3filter', 'v3gfilter', 'v3pick', 'v3more',
                  'v3keep', 'v3unkeep', 'v3savedfilter', 'v3pickopen',
                  'v3game', 'v3back', 'v3gtab', 'v3cat', 'v3type',
                  'v3stake', 'v3ask', 'v3open', 'v3dir',
                  'v3fav', 'v3clear', 'v3sheet', 'v3close', 'v3drop', 'v3clearq',
                  'v3half',
                  'v3sortpick'];

document.addEventListener('click', ev => {
  let node = ev.target;
  while (node && node !== document.body) {
    for (const k of V3CLICKS) {
      const v = node.getAttribute && node.getAttribute('data-' + k);
      if (v != null) { ev.preventDefault(); v3Do(k, v); return; }
    }
    node = node.parentNode;
  }
});

// The scrim closes the sheet, which is what every phone user expects and what
// makes a sheet feel like a sheet rather than a modal you are trapped in.
document.addEventListener('click', ev => {
  if (ev.target && ev.target.id === 'scrim' && V.sheet) {
    V.sheet = null; render();
  }
});

// TYPING PATCHES THE ROWS, IT DOES NOT RE-RENDER THE SHELL.
//
// Re-rendering replaces the input being typed into, which loses focus and
// the caret and drops every second keystroke. Only `#v3rows` is rewritten.
document.addEventListener('submit', ev => {
  const f = ev.target;
  if (!f || !f.getAttribute) return;
  const gid = f.getAttribute('data-v3askform');
  if (gid === null) return;
  ev.preventDefault();
  const q = (V.q2 || '').trim();
  if (q && !V.asking) v3AskSend(gid, q);
});

document.addEventListener('input', ev => {
  const t = ev.target;
  if (t && t.getAttribute && t.getAttribute('data-v3l') !== null) {
    const which = t.getAttribute('data-v3l');
    const n = v3Num(t.value);
    if (n != null) {
      if (which === 'stake') V.stake = Math.max(0.01, n);
      else if (which === 'rungs') V.rungs = Math.max(1, Math.min(20, Math.round(n)));
      // An american price of 0 or between -100 and 100 is not a price. Left
      // alone rather than coerced, so a half-typed "-1" on the way to "-150"
      // does not snap the table to something the reader did not ask for.
      else if (which === 'odds' && (n >= 100 || n <= -100)) V.lodds = n;
    }
    const rows = document.getElementById('v3rungs');
    if (rows) rows.innerHTML = v3Rungs();
    const sum = document.getElementById('v3lsum');
    if (sum) sum.textContent = v3LadderSummary();
    v3Save();
    return;
  }
  if (t && t.getAttribute && t.getAttribute('data-v3q2') !== null) {
    // Held in state but NOT re-rendered: replacing the field being typed
    // into loses focus and the caret.
    V.q2 = t.value;
    return;
  }
  if (!t || !t.getAttribute || t.getAttribute('data-v3q') === null) return;
  V.q = t.value;
  V.shown = V3SHOW;
  const host = document.getElementById('v3rows');
  if (host) host.innerHTML = v3Rows();
  v3Save();
});

document.addEventListener('change', ev => {
  const t = ev.target;
  if (!t || !t.getAttribute) return;
  if (t.getAttribute('data-v3week') != null) {
    V.week = t.value === '' ? null : Number(t.value);
    V.shown = V3SHOW; V.open = null;
    // A market that held players last week may hold none in this one, and
    // the tab would go empty under a picker the reader just moved.
    if (V.gameTab === 'players' && V.game) v3MarketForGame(V.game);
    render();
  } else if (t.getAttribute('data-v3gamesel') != null) {
    V.game = t.value === '' ? null : t.value;
    V.shown = V3SHOW; V.open = null; render();
  } else if (t.getAttribute('data-v3sortsel') != null) {
    V.sort = t.value; render();
  } else if (t.getAttribute('data-v3gameto') != null) {
    // The TAB is kept. Jumping to the next game's notes when you were reading
    // its score ladder is the same annoyance in a different place.
    V.game = t.value; V.open = null; V.answer = ''; V.top = true; render();
  }
});

//: The actions that change which SCREEN you are on. Everything else edits the
//: screen you are already looking at and must not move you.
//: `v3gtab` is NOT here. Switching section inside a game is not leaving the
//: page — you are looking at the same matchup — and sending the reader to the
//: top means scrolling back down past the card, the bars and the public split
//: every time they compare two tabs. `v3mkt` is out for the same reason: the
//: rows change, the page does not.
const V3NAV = { v3tab: 1, v3game: 1, v3back: 1 };

function v3Do(kind, v) {
  if (V3NAV[kind]) V.top = true;
  switch (kind) {
    case 'v3tab': {
      V.tab = v; V.game = null; V.shown = V3SHOW;
      // A week the destination cannot show is dropped rather than carried
      // into a screen that would render it empty.
      if (V.week != null && v3Weeks().indexOf(V.week) < 0) V.week = null;
      break;
    }
    // The market changes; the GAME FILTER DOES NOT. Looking at one game and
    // clicking between markets should not mean re-picking the game each time.
    case 'v3mkt': V.market = v; V.shown = V3SHOW; break;
    case 'v3sort': V.sort = v; break;
    case 'v3filter': V.filter = v; V.shown = V3SHOW; break;
    case 'v3gfilter': V.gfilter = v; break;
    case 'v3more': V.shown = 1e9; break;
    // Tapping the open row closes it: one open at a time, so the board does
    // not turn into a wall of detail panels you have to close individually.
    case 'v3open': V.open = V.open === v ? null : v; break;
    case 'v3dir': V.desc = !V.desc; break;
    case 'v3clearq': V.q = ''; V.shown = V3SHOW; break;
    case 'v3half': V.half = v; break;
    case 'v3fav': toggleFav(v); break;
    case 'v3clear': V.picks = {}; break;
    case 'v3drop': delete V.picks[v]; break;
    case 'v3sheet': V.sheet = v; break;
    case 'v3sortpick': V.sort = v; V.sheet = null; break;
    case 'v3close': V.sheet = null; break;
    // SAVING IS A COPY, NOT A MOVE. The slip stays exactly as it is, so the
    // same legs can be saved at one stake and then rebuilt at another.
    case 'v3keep': v3SaveSlip(); break;
    case 'v3unkeep': v3DropSaved(v); if (V.pick === v) V.sheet = null; break;
    case 'v3pickopen': V.pick = v; V.sheet = 'pick'; break;
    case 'v3savedfilter': V.savedFilter = v; break;
    case 'v3pick':
      if (V.picks[v]) delete V.picks[v]; else V.picks[v] = true; break;
    case 'v3game': V.tab = 'games'; V.game = v; V.gameTab = 'notes';
      V.cat = 'all'; V.answer = ''; V.answerErr = ''; V.q2 = '';
      V.answerLive = false; break;
    case 'v3back': V.game = null; V.answer = ''; break;
    case 'v3gtab':
      V.gameTab = v3GTab(v);
      // Opening Players on a market this game holds nothing on is the
      // commonest way the tab looks broken. Done here rather than in the
      // renderer, which must not write state.
      if (V.gameTab === 'players' && V.game) v3MarketForGame(V.game);
      break;
    case 'v3cat': V.cat = v; break;
    // BACK TO THE SLIP, NOT TO NOTHING.
    //
    // These two choosers are opened only from inside the slip sheet, and
    // closing to null closed the slip with them — so changing the bet type
    // or the stake dismissed the thing you were changing it on, and the new
    // payout table was never seen. Closing to null was right when the slip
    // was a tab and the sheet sat over it; it stopped being right when the
    // slip itself became the sheet.
    case 'v3type': V.betType = v; V.sheet = 'slip'; break;
    case 'v3stake': V.stake = Number(v); V.sheet = 'slip'; break;
    case 'v3ask': {
      const qs = v3Questions(V.game);
      V.answer = (qs[Number(v)] || {}).a || '';
      V.answerLive = false; V.answerErr = ''; V.searched = false;
      break;
    }
  }
  render();
}

// ── Swipe left to remove ────────────────────────────────────────────────
//
// A phone pattern and only a phone pattern: driven by touch events, which a
// mouse does not send, so every swipeable thing also carries a button. The
// element behind is already in place at the right edge with the row sitting
// on top of it, which is why the movement can follow a thumb instead of
// playing an animation after one.
//
// **The gesture gives up as soon as it looks vertical.** Claiming every
// horizontal-ish drag makes the list impossible to scroll, so the first move
// decides: more X than Y and it is a swipe, otherwise the browser keeps it
// and this never interferes again for that touch.
const V3SWIPE_OPEN = 96;

(function v3Swipes() {
  let node = null, x0 = 0, y0 = 0, dx = 0, decided = false, own = false;

  const target = el => {
    while (el && el !== document.body) {
      if (el.classList && (el.classList.contains('legwrap')
                           || el.classList.contains('slipwrap'))) return el;
      el = el.parentNode;
    }
    return null;
  };
  const width = el => el.classList.contains('slipwrap') ? 112 : V3SWIPE_OPEN;
  const slider = el => el.querySelector(
    el.classList.contains('slipwrap') ? '.slipbar' : '.row');

  document.addEventListener('touchstart', ev => {
    const t = ev.touches && ev.touches[0];
    node = t ? target(ev.target) : null;
    if (!node) return;
    x0 = t.clientX; y0 = t.clientY; dx = 0; decided = false; own = false;
  }, { passive: true });

  document.addEventListener('touchmove', ev => {
    if (!node) return;
    const t = ev.touches[0];
    const mx = t.clientX - x0, my = t.clientY - y0;
    if (!decided) {
      decided = Math.abs(mx) > 6 || Math.abs(my) > 6;
      if (!decided) return;
      own = Math.abs(mx) > Math.abs(my);
      if (!own) { node = null; return; }
      node.setAttribute('data-swipe', 'dragging');
    }
    const open = node.getAttribute('data-swipe') === 'open';
    dx = Math.max(-width(node), Math.min(0, mx - (open ? width(node) : 0)));
    const s = slider(node);
    if (s) s.style.transform = 'translateX(' + dx + 'px)';
  }, { passive: true });

  const end = () => {
    if (!node || !own) { node = null; return; }
    const s = slider(node);
    if (s) s.style.transform = '';
    // Past a third of the way and it stays open; short of that it springs
    // back. A fixed pixel threshold feels wrong on a narrow phone.
    node.setAttribute('data-swipe',
                      Math.abs(dx) > width(node) / 3 ? 'open' : 'closed');
    node = null;
  };
  document.addEventListener('touchend', end, { passive: true });
  document.addEventListener('touchcancel', end, { passive: true });
})();

// `week` was this tab's key before it was renamed Props. Normalized ONCE, at
// boot, rather than inside `v3Screen` — a renderer that rewrites the state it
// is rendering makes every render a state change, and the back stack started
// pushing an entry every time the sort direction was flipped.
if (V.tab === 'week') V.tab = 'props';

// `slip` was this tab's key before the slip became a sheet and the tab became
// the SAVED picks. A remembered state naming it would select no tab at all.
if (V.tab === 'slip') V.tab = 'picks';

// And `saved` was a boolean flag before it was the saved picks themselves. A
// stored `false` would make every read of it throw or silently return
// nothing, which is a reader's whole history disappearing on upgrade.
if (!Array.isArray(V.saved)) V.saved = [];

// A remembered state naming a tab that no longer exists would select none
// and render the notes with no pill lit.
V.gameTab = v3GTab(V.gameTab);

// A market that this export does not carry must not be the one the app opens
// on, and a remembered market can outlive the build that had it.
if (!served(V.market)) {
  const first = V3MKT.filter(m => served(m[0]))[0];
  V.market = first ? first[0] : 'any';
}
render();
"""


def js() -> str:
    return JS
