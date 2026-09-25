"""site/v3 — the app a casual bettor reads.

v2 is a board: seven tabs, six markets, four filters, every number the project
knows. It is the right tool for someone who already knows what an edge is. v3
is the same data answering a different question — "what should I look at, and
why" — for someone who does not, and will not, learn the vocabulary first.

**The calculation layer is v1's and is not forked.** `rowsFor` normalises a
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
  alphabet, and prime time is labelled because it is a real betting split.
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
  ['week', 'This week', 'M4 11l8-7 8 7v9h-5v-6H9v6H4z'],
  ['games', 'Games', 'M3 12h18M7 8l-4 4 4 4M17 8l4 4-4 4'],
  ['slip', 'My picks', 'M5 4h14v16l-3-2-2 2-2-2-2 2-2-2-3 2zM9 9h6M9 13h4'],
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
  tab: 'week', market: 'any', sort: 'model', desc: true, filter: 'all',
  week: null, game: null, gameTab: 'notes', cat: 'all',
  picks: {}, betType: 'parlay', stake: 10, shown: V3SHOW,
  ask: '', answer: '', saved: false,
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
      desc: V.desc }));
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
// before it is labelled, which is the point. `ev100` is v1's and already
// prefers the model-only probability on a touchdown market, where the blend
// has the book baked into it and would grade the book against itself.
function v3Value(row) {
  const ev = ev100(row);
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

function v3Weeks() {
  const h = (DATA.history || {})[V3HIST[V.market]] || {};
  return (h.has || []).slice().sort((a, b) => a - b);
}

function v3Header() {
  const weeks = v3Weeks();
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

// A graded row, normalised onto the same field names the live rows use, so
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
    priced: td ? !!r.has_market_price : has(r.line),
    actual: r.actual,
    won: td ? (has(r.scored) ? !!r.scored : null)
            : (r.won == null ? null : !!r.won),
  }));
}

// ── screen: this week ───────────────────────────────────────────────────

function v3Screen() {
  switch (V.tab) {
    case 'games': return V.game ? v3Game(V.game) : v3Games();
    case 'slip': return v3Slip();
    case 'ladder': return v3Ladder();
    default: return v3Week();
  }
}

// The market pills and the three filters, built once because two screens
// show them and a control added to one has to appear on the other.
function v3MarketControls() {
  const cur = V3MKT.filter(m => m[0] === V.market)[0] || V3MKT[0];
  const mkts = V3MKT.filter(m => served(m[0])).map(m =>
    '<button class="mkt" data-v3mkt="' + m[0] + '" aria-pressed="'
    + (m[0] === V.market) + '">' + esc(m[1]) + '</button>').join('');
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
    + v3GamePicker()
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
  const cards = (DATA.games || {}).cards || [];
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
    if (!rows.length) return '<div class="empty">No priced picks recorded '
      + 'for week ' + V.week + ' on this market. The week loaded; the board '
      + 'carried no priced rows for it.</div>';
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
  if (!rows.length) {
    return '<div class="empty">' + (V.filter === 'fade'
      ? 'Nothing on this market is priced far enough above our number to '
        + 'flag this week.'
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
  const warn = row.status && row.status !== 'ACT'
    ? '<span class="tag tag--warn">' + esc(row.status) + '</span>' : '';
  const ev = ev100(row);
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

// FAVOURITES, ON v1's STORAGE RATHER THAN A SECOND LIST.
//
// `isFav` and `toggleFav` are v1's and already in the bundle, keyed by the
// same row id v2 uses. Sharing the store means a player starred in v2 is
// starred here — two lists under two keys would be the same feature twice,
// disagreeing.
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
  if (has(row.openImplied) && has(row.book)) {
    const mv = (row.book - row.openImplied) * 100;
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
  add('Our read', row.read);
  return '<div class="detail"><dl>'
    + f.map(x => '<div><dt>' + esc(x[0]) + '</dt><dd class="num">' + x[1]
        + '</dd></div>').join('')
    + '</dl></div>';
}

// A settled row. The colour IS the information: green won, red lost, grey
// never settled. Everything else is what was shown before kickoff, unchanged,
// so the two can be compared.
function v3PastRow(row) {
  const won = row.won;
  const cls = won === true ? ' row--won' : won === false ? ' row--lost' : '';
  const mark = won === true ? '<span class="mark mark--won">✓</span>'
    : won === false ? '<span class="mark mark--lost">✕</span>'
    : '<span class="mark mark--void">–</span>';
  const line = v3Line(row);
  const got = has(row.actual)
    ? '<span class="sub num">had ' + row.actual + '</span>' : '';
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

// The one game the week most disagrees about, as a way in.
function v3Watch() {
  if (V.week != null) return '';
  const cards = ((DATA.games || {}).cards || []).filter(
    c => has(c.spread) && has(c.model_spread));
  if (!cards.length) return '';
  const best = cards.slice().sort((a, b) =>
    Math.abs(b.model_spread - b.spread) - Math.abs(a.model_spread - a.spread))[0];
  const notes = ((DATA.notes || {})[best.game_id] || []).length;
  return '<a class="card" style="display:block" data-v3game="'
    + esc(best.game_id) + '">'
    + '<div style="display:flex;justify-content:space-between;align-items:center">'
    + '<span class="eyebrow">Game to watch</span>'
    + (notes ? '<span class="tag tag--ours">' + notes + ' game notes</span>' : '')
    + '</div>'
    + '<div class="name" style="font-size:22px;line-height:28px;margin-top:8px">'
    + esc(best.away) + ' at ' + esc(best.home) + '</div>'
    + '<div class="sub">' + esc(v3Kick(best)) + '</div>'
    + '<div style="color:var(--ours);font-weight:600;margin-top:8px">'
    + 'See what our AI noticed</div></a>';
}

function v3Kick(c) {
  const when = [c.kick_day, c.kick_et].filter(Boolean).join(' ');
  return when + (c.prime ? ' · prime time' : '');
}

// ── screen: games ───────────────────────────────────────────────────────

function v3Games() {
  const g = DATA.games || {};
  const cards = g.cards || [];
  if (!cards.length) {
    return '<div class="wrap"><h1 class="h1">Games</h1>'
      + '<div class="card"><p class="lede" style="font-size:15px">No game '
      + 'lines have been captured for this week yet. The board is built from '
      + 'an odds archive, and until it runs there is nothing here to show.'
      + '</p></div></div>';
  }
  const lean = c => {
    if (!has(c.spread) || !has(c.model_spread)) return ['', ''];
    const d = c.model_spread - c.spread;
    if ((c.spread < 0) !== (c.model_spread < 0))
      return ['Our model picks the other side', 'tag tag--warn'];
    if (Math.abs(d) < 1) return ['Our model agrees', 'tag'];
    return [Math.abs(c.model_spread) < Math.abs(c.spread)
      ? 'Our model: a closer game' : 'Our model: by more', 'tag tag--ours'];
  };
  const flips = cards.filter(c => lean(c)[1] === 'tag tag--warn').length;
  const agree = cards.filter(c => lean(c)[1] === 'tag').length;
  const show = V.filter === 'diff'
    ? cards.filter(c => lean(c)[1] !== 'tag') : cards;

  const rows = show.map(c => {
    const l = lean(c);
    const fav = has(c.spread)
      ? (c.spread < 0 ? c.home : c.away) + ' by ' + Math.abs(c.spread) : '';
    const tot = has(c.total) ? c.total + ' total pts' : '';
    const win = has(c.win_home)
      ? (c.win_home >= 0.5 ? c.home + ' ' + v3Pct(c.win_home)
                           : c.away + ' ' + v3Pct(c.win_away)) + ' to win' : '';
    return '<a class="g" data-v3game="' + esc(c.game_id) + '"><div class="g__m">'
      + '<span class="kick">' + esc(v3Kick(c)) + '</span>'
      + '<span class="name">' + esc(c.away) + ' at ' + esc(c.home) + '</span>'
      + '<span class="sub num">' + esc([fav, tot].filter(Boolean).join(' · '))
      + '</span>'
      + '<span class="tags">' + (l[0] ? '<span class="' + l[1] + '">' + l[0]
        + '</span>' : '') + '<span class="sub num">' + esc(win) + '</span></span>'
      + '</div><span class="chev">›</span></a>';
  }).join('');

  return '<div class="wrap">'
    + '<h1 class="h1">Games</h1>'
    + '<p class="lede">Who the sportsbooks expect to win, and where our model '
    + 'sees it differently. Tap a game for the notes.</p>'
    + v3Watch()
    + '<div class="card"><div class="stats">'
    + '<div class="stat"><span class="eyebrow">Games</span><b class="num">'
    + cards.length + '</b></div>'
    + '<div class="stat"><span class="eyebrow">Upset picks</span><b class="num">'
    + flips + '</b></div>'
    + '<div class="stat"><span class="eyebrow">Model agrees</span><b class="num">'
    + agree + '</b></div></div></div>'
    + '<div class="seg seg--2">'
    + v3Seg('v3filter', [['all', 'All games'], ['diff', 'Model disagrees']],
            V.filter === 'diff' ? 'diff' : 'all')
    + '</div>'
    + '<div class="list">' + (rows || '<div class="empty">Every game this week '
      + 'has our model and the book within a point of each other.</div>')
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
  const c = ((DATA.games || {}).cards || []).filter(x => x.game_id === gid)[0];
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
    + '<div class="seg seg--4">'
    + v3Seg('v3gtab', [['notes', 'Notes'], ['players', 'Players'],
                       ['bets', 'Bets'], ['score', 'Final score']], V.gameTab)
    + '</div>'
    + v3PublicMoney(gid)
    + (V.gameTab === 'players' ? v3GamePlayers(gid)
     : V.gameTab === 'bets' ? v3GameBets(gid)
     : V.gameTab === 'score' ? v3GameScores(c)
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
    const mv = rows.filter(r => r.market === mk && r.outcome === top.side)
      .map(r => r.move_pp).filter(has)[0];
    const against = has(mv) && mv < -0.5;
    return '<div class="pub">'
      + '<div class="pub__h"><span class="eyebrow">' + esc(label[mk] || mk)
      + '</span>'
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
           + '(\u2212' + Math.abs(mv).toFixed(1) + 'pp). That is money '
           + 'disagreeing with the crowd.</p>' : '')
      + '</div>';
  }).join('');
  if (!blocks) return '';
  return '<div class="card"><div class="name">Where the public is</div>'
    + blocks
    + '<p class="help">Share of bets placed, from Sportsbook Review. A crowd '
    + 'being on one side is not evidence it is wrong \u2014 this project has '
    + 'not measured that. It is worth seeing next to which way the price '
    + 'moved.</p></div>';
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
  const cards = (DATA.games || {}).cards || [];
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
    return '<div class="cmp' + (cls || '') + '">'
      + '<span class="eyebrow">' + esc(label) + '</span>'
      + '<b class="num">' + esc(lead) + ' ' + Math.round(Math.max(hh, aa))
      + '\u2013' + Math.round(Math.min(hh, aa)) + '</b>'
      + '<span class="sub num">' + esc(sp < 0 ? c.home : c.away) + ' by '
      + Math.abs(sp) + ' \u00b7 ' + tot + ' pts</span></div>';
  };
  const a = line('Sportsbooks', c.spread, c.total, '');
  const b = line('Our model', c.model_spread, c.model_total, ' cmp--ours');
  if (!a && !b) return '';
  return '<div class="two" style="margin-top:16px">' + a + b + '</div>';
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
    + v3Ask(gid)
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
  const c = ((DATA.games || {}).cards || []).filter(
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

// The questions are fixed and their answers are computed. A free-text box
// would need a server the site does not have, and a box that quietly answers
// only three things is worse than three buttons that say what they are.
function v3Ask(gid) {
  const qs = v3Questions(gid);
  if (!qs.length) return '';
  return '<div class="card"><div class="name">Ask about this game</div>'
    + '<div class="qs">' + qs.map((q, i) =>
        '<button class="q" data-v3ask="' + i + '">' + esc(q.q) + '</button>')
      .join('') + '</div>'
    + (V.answer ? '<div class="ans">' + esc(V.answer) + '</div>' : '')
    + '</div>';
}

function v3Questions(gid) {
  const rows = rowsFor('any', null).filter(
    r => r.priced && v3Same(r.gameId, gid));
  if (!rows.length) return [];
  const byP = rows.slice().sort((a, b) => (betProb(b) || 0) - (betProb(a) || 0));
  const byV = rows.slice().sort((a, b) => (ev100(b) || -1e9) - (ev100(a) || -1e9));
  const c = ((DATA.games || {}).cards || []).filter(x => x.game_id === gid)[0] || {};
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
  const body = v3MarketControls() + v3SortBar()
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
  const margins = (d.margins || []).filter(m => m.n).map(m =>
    '<div class="mrow"><span class="mrow__l">' + esc(m.band) + '</span>'
    + bar(m.pct, m.band.indexOf(d.home) === 0 ? 'var(--ours)' : 'var(--mut3)')
    + '<span class="mrow__v num">' + m.pct.toFixed(1) + '%</span></div>').join('');
  const scores = (d.scores || []).map(x =>
    '<div class="srow"><b class="num">' + esc(d.home) + ' ' + x.home
    + '\u2013' + x.away + ' ' + esc(d.away) + '</b>'
    + '<span class="sub num">' + x.pct.toFixed(1) + '% \u00b7 ' + x.n
    + ' of ' + d.n + '</span></div>').join('');

  return '<div class="card"><div class="eyebrow">Based on</div>'
    + '<p class="lede" style="font-size:15px;line-height:20px;margin-top:4px">'
    + '<b>' + d.n + ' past games</b> hung within 2 points of this spread and '
    + '3.5 of this total. Not a simulation \u2014 what actually happened in '
    + 'them.</p>'
    + '<div class="two" style="margin-top:12px">'
    + '<div class="box"><span class="eyebrow">' + esc(d.home)
    + ' won</span><b class="num">' + d.home_win.pct.toFixed(0) + '%</b>'
    + '<span class="sub num">' + d.home_win.lo.toFixed(0) + '\u2013'
    + d.home_win.hi.toFixed(0) + '% range</span></div>'
    + '<div class="box"><span class="eyebrow">Went over ' + d.total
    + '</span><b class="num">' + d.over.pct.toFixed(0) + '%</b>'
    + '<span class="sub num">' + d.over.lo.toFixed(0) + '\u2013'
    + d.over.hi.toFixed(0) + '% range</span></div></div>'
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
  const c = ((DATA.games || {}).cards || []).filter(x => x.game_id === gid)[0];
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
      const pt = has(r.point) ? ' ' + (r.point > 0 ? '+' : '') + r.point : '';
      return '<span class="quote"><b>' + esc(k) + esc(pt) + '</b> '
        + v3Dash(american(r.best)) + '<i> at ' + esc(
          String(r.best_book || '').split(',')[0].trim()) + '</i></span>';
    }).join('');
  };

  const table = (title, note, rowsIn, mark) =>
    '<h2 class="h1" style="font-size:19px;line-height:24px;margin-top:20px">'
    + esc(title) + '</h2>'
    + (note ? '<p class="help">' + note + '</p>' : '')
    + '<div class="card"><div class="ltab">'
    + '<div class="ltab__h"><span>Over</span><span>Hit</span>'
    + '<span>How often</span></div>'
    + rowsIn.map(r => {
        const on = mark != null && Math.abs(r.line - mark) < 0.01;
        return '<div class="ltab__r' + (on ? ' ltab__r--on' : '') + '">'
          + '<span class="num">' + r.line + (on ? ' \u00b7 posted' : '')
          + '</span>'
          + '<span class="num">' + r.pct.toFixed(0) + '%</span>'
          + '<span>' + v3Mini(r.pct) + '<i class="num">' + r.n + ' of '
          + L.n + '</i></span></div>';
      }).join('')
    + '</div></div>';

  const teams = (L.teams || []).map(t =>
    table(t.team + ' points', 'How often ' + esc(t.team) + ' scored more than '
          + 'each number, in games priced like this one.', t.rows, null))
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
            (L.total || {}).rows || [], (L.total || {}).posted)
    + table('Winning margin',
            'How often the home side won by more than each number. Negative '
            + 'means the away side won.',
            (L.spread || {}).rows || [], (L.spread || {}).posted)
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

function v3Slip() {
  const legs = v3Legs();
  if (!legs.length) {
    return '<div class="wrap"><h1 class="h1">My picks</h1>'
      + '<p class="lede">Nothing added yet. Tap + beside a player on This '
      + 'week and they will show up here with what the bet pays.</p></div>';
  }
  const dec = legs.map(l => l.dec).filter(has);
  const ps = legs.map(l => betProb(l)).filter(has);
  const ok = dec.length === legs.length && ps.length === legs.length;
  const type = V3BETTYPES.filter(t => t[0] === V.betType)[0] || V3BETTYPES[0];

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

  return '<div class="wrap"><h1 class="h1">My picks</h1>'
    + '<p class="lede">' + legs.length + ' pick'
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
    + '<button class="cta" data-v3clear="1" style="background:var(--card);'
    + 'color:var(--bad);border-color:var(--bad)">Clear all picks</button>'
    + '</div>';
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
function v3Outcomes(legs, stake) {
  const n = legs.length;
  const d = legs.map(l => l.dec), p = legs.map(l => betProb(l));
  const cost = V.betType === 'parlay' ? stake
    : V.betType === 'singles' ? n * stake : (n * (n - 1) / 2) * stake;
  const byK = []; for (let i = 0; i <= n; i++) byK.push({ p: 0, ev: 0 });
  let ev = 0;
  for (let m = 0; m < (1 << n); m++) {
    let pr = 1, k = 0, ret = 0;
    const hit = [];
    for (let i = 0; i < n; i++) {
      const h = !!(m & (1 << i));
      hit.push(h); pr *= h ? p[i] : 1 - p[i]; if (h) k++;
    }
    if (V.betType === 'parlay') {
      ret = k === n ? stake * d.reduce((a, b) => a * b, 1) : 0;
    } else if (V.betType === 'singles') {
      for (let i = 0; i < n; i++) if (hit[i]) ret += stake * d[i];
    } else {
      for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++)
        if (hit[i] && hit[j]) ret += stake * d[i] * d[j];
    }
    const net = ret - cost;
    byK[k].p += pr; byK[k].ev += pr * net; ev += pr * net;
  }
  const best = V.betType === 'parlay' ? stake * d.reduce((a, b) => a * b, 1)
    : V.betType === 'singles' ? stake * d.reduce((a, b) => a + b, 0)
    : (() => { let t = 0; for (let i = 0; i < n; i++)
        for (let j = i + 1; j < n; j++) t += stake * d[i] * d[j]; return t; })();

  const label = k => k === 0 ? 'None land'
    : k === n ? 'All ' + n + ' land' : k + ' of ' + n + ' land';
  const rows = [];
  for (let k = n; k >= 0; k--) {
    const net = byK[k].p ? byK[k].ev / byK[k].p : 0;
    const col = net > 0.005 ? 'var(--good)' : net < -0.005 ? 'var(--bad)'
      : 'var(--mut)';
    rows.push('<div class="out"><span>' + label(k) + '</span>'
      + '<span class="num">' + v3Pct(byK[k].p) + '</span>'
      + '<span class="num" style="font-weight:600;color:' + col + '">'
      + (Math.abs(net) < 0.005 ? '$0.00'
         : (net >= 0 ? '+' : '−') + '$' + Math.abs(net).toFixed(2))
      + '</span></div>');
  }
  return '<div class="card">'
    + '<div class="sub">' + (V.betType === 'parlay'
        ? 'If every pick lands, you get back' : 'Best case, you get back')
    + '</div>'
    + '<div class="big num">$' + best.toFixed(2) + '</div>'
    + '<div class="sub num">You put in $' + cost.toFixed(2)
    + (V.betType === 'parlay' ? '' : ' in total') + '</div>'
    + '<div style="margin-top:16px"><div class="out" '
    + 'style="border:0;min-height:0;padding-bottom:8px">'
    + '<span class="eyebrow">If…</span>'
    + '<span class="eyebrow">Chance</span>'
    + '<span class="eyebrow">You’d be</span></div>'
    + rows.join('') + '</div>'
    + '<div class="box" style="margin-top:16px">'
    + '<span class="name" style="font-size:15px">'
    + (ev >= 0 ? 'Worth it over time' : 'Costs a little over time') + '</span>'
    + '<span class="sub">Made many times, this averages about '
    + (ev >= 0 ? '+' : '−') + '$' + Math.abs(ev).toFixed(2)
    + ' a go, if our chances are right.</span></div>'
    + '<p class="help">Chances assume each pick is independent. Two players in '
    + 'the same game are not — on the same team a parlay is worth a little '
    + 'more than this says, on opposite teams a little less.</p>'
    + '</div>';
}

// ── screen: ladder ──────────────────────────────────────────────────────

function v3Ladder() {
  const kinds = [['safe', 'Safer picks', 'Favourites. Win more often, pay less.', -150],
                 ['even', 'Coin flips', 'About a 50-50 shot each time.', 100],
                 ['bold', 'Long shots', 'Win less often, pay a lot more.', 200]];
  const kind = V.ladderKind || 'even';
  const o = (kinds.filter(k => k[0] === kind)[0] || kinds[1])[3];
  const d = amToDec(o), pStep = 1 / d, start = V.stake;
  const rungs = [1, 2, 3, 4, 5, 6].map((n, i) => {
    const p = Math.pow(pStep, n), bank = start * Math.pow(d, n);
    return '<div class="rung' + (i % 2 ? ' rung--alt' : '') + '">'
      + '<span class="num" style="font-weight:600;color:var(--mut)">' + n
      + '</span>'
      + '<span class="num" style="font-size:17px;font-weight:600">$'
      + (bank >= 1000 ? Math.round(bank).toLocaleString() : bank.toFixed(2))
      + '</span>'
      + '<span><span class="num" style="font-weight:600">' + v3Pct(p)
      + '</span><br><span class="sub num">about 1 in '
      + Math.max(1, Math.round(1 / p)) + '</span></span></div>';
  }).join('');
  return '<div class="wrap"><h1 class="h1">The ladder</h1>'
    + '<p class="lede">Start small. Each time a bet wins, the whole amount '
    + 'rides on the next one. Climb as high as you like and stop whenever you '
    + 'want. One loss and you are back to the start.</p>'
    + '<h2 class="eyebrow" style="margin:24px 2px 0">Start with</h2>'
    + '<div class="stakes">' + [5, 10, 20, 50].map(v =>
        '<button class="stake" data-v3stake="' + v + '" aria-pressed="'
        + (V.stake === v) + '">$' + v + '</button>').join('') + '</div>'
    + '<h2 class="eyebrow" style="margin:24px 2px 0">Kind of pick on each step'
    + '</h2>'
    + kinds.map(k => '<button class="opt" data-v3kind="' + k[0]
        + '" aria-pressed="' + (kind === k[0]) + '">'
        + '<span class="radio"><i></i></span><span>'
        + '<span class="name">' + esc(k[1]) + '</span><br>'
        + '<span class="sub">' + esc(k[2]) + ' Odds '
        + v3Dash(american(k[3])) + '.</span></span></button>').join('')
    + '<div class="list"><div class="rung" style="border:0">'
    + '<span class="eyebrow">Step</span>'
    + '<span class="eyebrow">You’d have</span>'
    + '<span class="eyebrow">Chance</span></div>' + rungs + '</div>'
    + '<div class="card"><p class="lede" style="font-size:15px">Each row '
    + 'assumes every step above it won. The chance is how often you would get '
    + 'that far if every pick is priced fairly — which is the generous '
    + 'assumption, because the book’s cut means they are not.</p></div>'
    + '</div>';
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

const V3BETTYPES = [
  ['parlay', 'All or nothing',
   'One bet. Every pick has to land. Biggest payout, hardest to win.'],
  ['twos', 'Any two',
   'A smaller bet on each pair. Two landing wins something.'],
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
  if (!legs.length || V.tab === 'slip') return '';
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
    + '<button class="slipbar__open" data-v3tab="slip">Open</button>'
    + '<button class="slipbar__x" data-v3clear="1" aria-label="Clear all picks">'
    + '\u2715</button>'
    + '</div></div>';
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
    if (ev && ev.state) { Object.assign(V, ev.state); V.top = true; render(true); }
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
const V3CLICKS = ['v3tab', 'v3mkt', 'v3sort', 'v3filter', 'v3pick', 'v3more',
                  'v3game', 'v3back', 'v3gtab', 'v3cat', 'v3type',
                  'v3stake', 'v3kind', 'v3ask', 'v3open', 'v3dir',
                  'v3fav', 'v3clear', 'v3sheet', 'v3close', 'v3drop',
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

document.addEventListener('change', ev => {
  const t = ev.target;
  if (!t || !t.getAttribute) return;
  if (t.getAttribute('data-v3week') != null) {
    V.week = t.value === '' ? null : Number(t.value);
    V.shown = V3SHOW; V.open = null; render();
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
const V3NAV = { v3tab: 1, v3game: 1, v3back: 1, v3gtab: 1, v3mkt: 1 };

function v3Do(kind, v) {
  if (V3NAV[kind]) V.top = true;
  switch (kind) {
    case 'v3tab': V.tab = v; V.game = null; V.shown = V3SHOW; break;
    // The market changes; the GAME FILTER DOES NOT. Looking at one game and
    // clicking between markets should not mean re-picking the game each time.
    case 'v3mkt': V.market = v; V.shown = V3SHOW; break;
    case 'v3sort': V.sort = v; break;
    case 'v3filter': V.filter = v; V.shown = V3SHOW; break;
    case 'v3more': V.shown = 1e9; break;
    // Tapping the open row closes it: one open at a time, so the board does
    // not turn into a wall of detail panels you have to close individually.
    case 'v3open': V.open = V.open === v ? null : v; break;
    case 'v3dir': V.desc = !V.desc; break;
    case 'v3fav': toggleFav(v); break;
    case 'v3clear': V.picks = {}; V.saved = false; break;
    case 'v3drop': delete V.picks[v]; V.saved = false; break;
    case 'v3sheet': V.sheet = v; break;
    case 'v3sortpick': V.sort = v; V.sheet = null; break;
    case 'v3close': V.sheet = null; break;
    case 'v3pick':
      if (V.picks[v]) delete V.picks[v]; else V.picks[v] = true; break;
    case 'v3game': V.tab = 'games'; V.game = v; V.gameTab = 'notes';
      V.cat = 'all'; V.answer = ''; break;
    case 'v3back': V.game = null; V.answer = ''; break;
    case 'v3gtab': V.gameTab = v; break;
    case 'v3cat': V.cat = v; break;
    case 'v3type': V.betType = v; V.sheet = null; V.saved = false; break;
    case 'v3stake': V.stake = Number(v); V.sheet = null; V.saved = false; break;
    case 'v3kind': V.ladderKind = v; break;
    case 'v3ask': {
      const qs = v3Questions(V.game);
      V.answer = (qs[Number(v)] || {}).a || ''; break;
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
