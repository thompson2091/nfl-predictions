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
  // Replaced the let-it-ride ladder. That was a calculator — it took a
  // stake and a price and multiplied; nothing in it was measured. This
  // is the opposite: twenty splits, every one of them graded, and the
  // headline is that none of them clears.
  ['angles', 'Angles', 'M4 19h16M4 19l5-7 4 3 6-9'],
  // "Record", not "Scorecard": a fifth column on a 375px phone has about
  // six characters before the label wraps under its own icon.
  ['record', 'Record', 'M4 4h16v16H4zM8 8h8M8 12h8M8 16h5'],
];

// key, button label, what the bet pays on, the question the screen answers.
// `[key, name, what it pays, page title, PILL]`.
//
// THE FIFTH IS A SHORT LABEL AND ONLY THE MARKET CONTROL USES IT. Six markets
// on one row of a phone is about 50px each, and "Receiving yds" does not go
// in 50px.
//
// THE THREE YARDAGE MARKETS SHARE ONE PATTERN AND THE COUNT MARKET DOES NOT.
// Rush, Rec and Pass are the same bet on three body parts, so they read as a
// set; receptions is a different kind of number, so it is named for what it
// counts. Shortening both receiving markets toward their stem gave "Rec" and
// "Rec yd" — a letter apart, sitting next to each other, one counting catches
// and one counting yards. "Catches" is two characters longer than that and
// cannot be misread.
//
// It is a separate field rather than a rename because the full name still has
// work to do: it is the heading on the board, the subject of "no priced
// players on scores a td", and the label in the empty-state grid, which has
// the width for it. A pill is the one place the name is competing for space.
const V3MKT = [
  ['any', 'Scores a TD',
   'Pays if the player scores a touchdown at any point in the game.',
   'Who scores this week?', 'Anytime'],
  ['first', 'Scores first',
   'Pays only if the player scores the game’s very first touchdown. Harder, so it pays more.',
   'Who scores first?', 'First'],
  ['rec', 'Catches',
   'Pays if the player makes more catches than the number shown.',
   'Who beats their catches line?', 'Catches'],
  ['rush', 'Rushing yds',
   'Pays if the player runs for more yards than the number shown.',
   'Who beats their rushing line?', 'Rush'],
  ['recyds', 'Receiving yds',
   'Pays if the player gains more receiving yards than the number shown.',
   'Who beats their receiving line?', 'Rec'],
  ['passyds', 'Passing yds',
   'Pays if the quarterback throws for more yards than the number shown.',
   'Who beats their passing line?', 'Pass'],
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
// HOW FAR OUR NUMBER IS FROM THEIRS, IN THE UNITS THE MARKET IS POSTED IN.
//
// `edge` already answers "how far apart are we" in probability points, and it
// is not the same question. Saquon Barkley on week 3 was projected 49.1
// rushing yards against a 94.5 line — a 45-yard disagreement worth 1.2
// points of edge, because a 94.5 line sits in the fat part of a wide
// distribution and moving 45 yards through it barely moves the probability.
// Sorted by edge he is nowhere; sorted by this he is first, which is the row
// a reader scanning for "where do we most disagree" wants to find.
//
// SIGNED, NOT ABSOLUTE, and the same sign convention `edge` already uses:
// positive is the over, negative the under. The board carries both sides —
// 401 unders to 317 overs on week 3's rushing board — so an absolute value
// would mix them into one list and throw away the direction. Signed, the
// board's own ↓High/↑Low toggle reaches both ends: high is the strongest
// overs, low the strongest unders. Absolute cannot be undone; this can.
const v3Diff = r => (r.kind === 'ou' && has(r.line) && has(r.proj))
  ? r.proj - r.line : null;

//: `line` is true of a sort that only means anything on a market with a line
//: and a projection. The touchdown boards carry neither — `anytime_td` week
//: files have no `line`, `proj` or `side` column at all — so these sorted 498
//: nulls and left the order untouched, which reads as a broken control rather
//: than as an inapplicable one. `v3SortBar` offers them where they apply.
const V3SORTS = [
  ['model', 'Model', r => has(r.modelOnly) ? r.modelOnly : r.ours],
  ['book', 'Book', r => r.book],
  ['adj', 'Adjusted (blend)', r => r.ours],
  ['edge', 'Edge', r => r.edge],
  ['ev', 'EV per $100', r => ev100(r)],
  ['odds', 'Odds', r => has(r.dec) ? r.dec : null],
  ['proj', 'Projection', r => has(r.proj) ? r.proj : null, true],
  ['diff', 'Difference from the line', r => v3Diff(r), true],
  ['fav', 'Starred first', r => (isFav(r.id) ? 1 : 0)],
  ['player', 'Name', r => r.player],
];

//: Whether the market on screen posts a line to differ from. `KIND` is v1's
//: and is the same table `rowsFor` branches on to build the rows in the first
//: place, so this cannot disagree with what the rows actually carry — which a
//: second list of market names here eventually would.
const v3MktLines = () => KIND[V.market] === 'ou';

const v3Model = r => has(r.modelOnly) ? r.modelOnly : r.ours;

const V3KEY = 'picksix.v3';
const V3SHOW = 25;

const V = Object.assign({
  tab: 'games', market: 'any', sort: 'model', desc: true, filter: 'all',
  gfilter: 'all',
  //: WHOSE PICK THE GREEN AND RED GRADE. The board used to grade the book's
  //: favorite and nothing said so, which made a played week a scorecard for
  //: the sportsbook on a page whose whole point is the second opinion. Our
  //: model is the default; book and adjusted are one tap away.
  gbasis: 'model',
  week: null, game: null, gameTab: 'odds', cat: 'all',
  picks: {}, betType: 'twos', stake: 10, shown: V3SHOW,
  lodds: 100, rungs: 6, q: '', half: 'full', metric: 'all',
  // Sorted by THIS YEAR by default: it is the column a reader came for, and
  // the all-time one beside it is what keeps that honest.
  angleSort: 'season', angleDesc: true, angleOpen: null, angleCat: 'all',
  //: The earliest season the long-run column counts. Every season is shipped
  //: separately so this can move without another measurement.
  angleFrom: 0, angleQ: '',
  //: The same table on a game card, with its own sort and filter so ordering
  //: one does not reorder the other.
  gaSort: 'season', gaDesc: true, gaOpen: null, gaTeam: 'all',
  //: Whose record the two columns show. League-wide by default: it is the
  //: bigger sample, and the median team-and-angle pair is 25 graded games.
  gaScope: 'league',
  //: Which kind of pattern a game's angles are narrowed to, or all of them.
  gaCat: 'all',
  //: Whose full record has been fetched and opened out. One at a time: the
  //: whole market is a megabyte and nobody reads two players' careers at once.
  pastAll: null,
  //: How many of a player's recent weeks the history panel reads over. Null
  //: is everything inlined; a number is the reader asking a narrower
  //: question, and the chart, the count and the money all answer it.
  pastN: null,
  //: Whose whole line record has been fetched and opened out, and over how
  //: many games the team panel reads. Null is the ten inlined; a number is
  //: the reader asking a narrower question, and the records, the dollars and
  //: the rows all answer the same one.
  tlAll: null, tlN: null,
  //: One club's own games on the board, or every club's.
  angleTeam: '',
  //: And on the board, whose record the columns show once a club is chosen.
  //: `team` is what choosing one has always done; `league` is the new half,
  //: and it keeps the selection so the two readings are two taps apart.
  angleScope: 'team',
  ask: '', answer: '',
  // The saved picks, and which of them the Picks tab is showing. `saved` was
  // a boolean nothing read; the slip and the saved copy are different things
  // and only one of them was ever stored.
  saved: [], savedFilter: 'all', pick: null,
  //: The Record page. `recFull` is the simple/detailed switch and is the
  //: only thing that decides which rows a section draws — every number is
  //: still computed, so turning it on cannot change a figure, only reveal
  //: one. `recWho` picks which cut of the per-player table is showing and
  //: `recSeries` which of the three gradings it reads.
  recFull: false, recWho: 'top', recSeries: 'model', recQ: '', recShown: 40,
  //: Which of the players board's four filters section 04 is scoring.
  recView: 'all',
  //: Whose legs are open in the per-player table. One at a time.
  recOpen: null,
  //: How the per-player table is ordered. Total profit by default, not the
  //: rate: a player bet six times moves the season more than one bet twice.
  recSort: 'ret', recSortDesc: true,
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
      desc: V.desc, gfilter: V.gfilter, gbasis: V.gbasis,
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
  if (V.tab === 'picks' || V.tab === 'angles' || V.tab === 'record')
    return [];
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
    case 'angles': return v3AnglesPage();
    case 'record': return v3RecordPage();
    default: return V.game ? v3Game(V.game) : v3Games();
  }
}

// The market pills and the three filters, built once because two screens
// show them and a control added to one has to appear on the other.
// `after` lands between the pinned bar and the prose under it. The board
// passes its CLV line there: that number is PER MARKET, so read from above
// the bar it never changed in front of you — you tapped Rush, the rows
// redrew, and the one line that also moved was two screens up.
function v3MarketControls(after) {
  const cur = V3MKT.filter(m => m[0] === V.market)[0] || V3MKT[0];
  // Inside a game each button carries how many players it holds, because a
  // market can hold none and the only way to find out was to tap it.
  // THE SAME SEGMENTED CONTROL THE FILTER ROW USES.
  //
  // These were rounded pills sized to their own labels, which meant the row
  // was only as wide as the names happened to be — six of them overflowed and
  // scrolled sideways, hiding half the markets behind a gesture nothing on
  // screen advertises. A `seg` divides the width evenly instead, so every
  // market is on screen at every width and the control reads as one thing
  // rather than six loose buttons.
  //
  // THE PLAYER COUNT GOES, THE DIMMING STAYS. An even sixth of a phone is
  // about 50px and a number does not fit beside a name in it. The count was
  // there to answer "does this market hold anyone for this game" without
  // tapping — `mkt--none` still answers that, by greying the ones that hold
  // nobody. The exact figure is the part that did not survive the width.
  const served_ = V3MKT.filter(m => served(m[0]));
  const mkts = served_.map(m => {
    const n = V.game ? v3GameMkt(m[0], V.game) : null;
    return '<button' + (n === 0 ? ' class="mkt--none"' : '')
      + ' data-v3mkt="' + m[0] + '" aria-pressed="'
      + (m[0] === V.market) + '">' + esc(m[4] || m[1]) + '</button>';
  }).join('');
  // ONLY THE ONE THAT STOPS A MISTAKE.
  //
  // "Our shortlist: the picks this project would actually place" and "Players
  // you have starred" said what their own buttons say. Fades does not: the
  // word reads like a bet to place, and it is the opposite — so that line
  // stays, cut to the part that prevents the misread.
  const filterHelp = {
    fade: 'Priced ABOVE our number \u2014 bets to leave alone, not to place.',
    // The same caution the tag carries, said once at the top rather than on
    // every row: a lopsided five weeks is a fact about the past, and this
    // project has not measured it into an edge.
    // The thresholds and the measured return, read off the payload — see
    // `v3EdgeNote`. Said here rather than on every row, like the others.
    gap: v3EdgeNote(),
    streak: 'Players who went one way in ' + V3STREAK_MIN + ' of their last '
      + V3STREAK_OF + ' weeks, against the line they were quoted each week. '
      + 'Recent form, not an edge \u2014 nothing here is filtered on price.',
  }[V.filter] || '';
  // ONE PINNED BAR, THREE TIGHT ROWS, AND THE PROSE UNDERNEATH IT.
  //
  // Stacked at full size these ran about 250px before the first player: six
  // 44px market buttons in a 3x2 grid, a sentence about the market, a 4-way
  // filter, a search box and a sort row. That is fine to read once and
  // impossible to pin — a bar that deep leaves no board under it.
  //
  // So each control keeps ONE TAP and loses its padding. The markets become a
  // strip that scrolls sideways instead of a grid that wraps, which is the
  // whole 96px-to-32px saving; search and sort share a line, and "Sort by"
  // goes, because a dropdown of sort names does not need a label saying it
  // sorts. Roughly 118px, and every filter is still one tap from anywhere in
  // the list.
  //
  // THE TWO HELP LINES STAY, BELOW THE BAR. They explain what you are looking
  // at rather than change it, so they are not worth pinned pixels — and they
  // are what makes the bar itself safe to shrink, because the meaning is
  // still on the page.
  return '<div class="pbar">'
    + '<div class="seg seg--' + served_.length + '">' + mkts + '</div>'
    + '<div class="seg seg--6">'
    + v3Seg('v3filter', [['all', 'Everyone'], ['short', 'Shortlist'],
                         ['fade', 'Fades'], ['streak', 'Streaks'],
                         // THE ONE FILTER WITH A MEASURED RETURN BEHIND IT,
                         // which is why it is on the bar rather than buried:
                         // every other filter here is a description of the
                         // board and this one is a pre-registered bet.
                         ['gap', 'Big gaps'],
                         ['fav', 'Starred']], V.filter)
    + '</div>'
    + '<div class="pbar__row">' + v3Search() + v3SortBar() + '</div>'
    + '</div>'
    + (after || '')
    + '<p class="help">' + esc(cur[2]) + '</p>'
    + (filterHelp ? '<p class="help">' + esc(filterHelp) + '</p>' : '');
}

function v3Week() {
  const cur = V3MKT.filter(m => m[0] === V.market)[0] || V3MKT[0];


  return '<div class="wrap">'
    + v3PastBanner()
    + '<h1 class="h1">' + esc(V.week == null ? cur[3] : 'Week ' + V.week) + '</h1>'
    + '<p class="lede">Our number next to the sportsbook\u2019s.'
    + (V.week == null ? ' Tap a row for everything we know about it.' : '')
    + '</p>'
    + v3BoardBar()
    // UNDER THE PINNED BAR, because the number is per market. Above it, you
    // tapped Rush, the rows redrew, and the one line that also changed was
    // two screens up where you could not see it.
    //
    // ONLY ON A LIVE WEEK. On a graded week the prices stopped moving and
    // "the market has moved toward us on 9 of 14" is a fact about the past
    // dressed as one about a board you could still bet.
    + v3MarketControls(V.week == null
       ? v3ClvNote(rowsFor(V.market, null).filter(r => r.priced && !r.blocked),
                   'of the picks on this market')
       : '')
    + '<div class="list" id="v3rows">' + v3Rows() + '</div>'
    + v3Explainer()
    + '</div>';
}

// THE GAME FILTER, AND IT SURVIVES THE MARKET.
//
// Asked for directly: "a lot of times I'm looking at a specific game and
// clicking between the markets and need to reselect the game every time".
// `v3Do` deliberately leaves `V.game` alone on a market change.
// THE SAME BAR THE GAME SCREEN HAS, on the board.
//
// It was a plain "Game" dropdown sitting in the flow, which meant two
// different controls for one idea — step between games on a game screen,
// choose one from a list on the board — and the board's scrolled away the
// moment you started reading. This is the game screen's control: back,
// steppers either side of the name, Ask on the right, in the same pinned
// wrapper, so `--gtabs-h` offsets the filter bar under it without knowing
// which screen it is on.
//
// BACK AND ASK APPEAR ONLY WITH A GAME CHOSEN. Both are about one game: back
// means leave it, which on the board is "all games" rather than a screen to
// return to, and Ask has nothing to ask about across sixteen matchups. A
// disabled button that is nearly always disabled is worse than no button.
function v3BoardBar() {
  const cards = v3GameSet().cards || [];
  if (!cards.length) return '';
  let i = -1;
  cards.forEach((c, k) => { if (c.game_id === V.game) i = k; });
  const step = d => {
    const j = i + d;
    // From "all games" the forward arrow starts at the first, and there is
    // nothing behind it — the same rule the game screen uses at either end.
    return (j < 0 || j >= cards.length) ? ''
      : '<button class="gstep" data-v3boardgame="' + esc(cards[j].game_id)
        + '" aria-label="' + (d < 0 ? 'Previous' : 'Next') + ' game">'
        + (d < 0 ? '\u2039' : '\u203a') + '</button>';
  };
  const opts = ['<option value="">All games</option>'].concat(
    cards.map(c => '<option value="' + esc(c.game_id) + '"'
      + (V.game === c.game_id ? ' selected' : '') + '>'
      + esc(c.away + ' at ' + c.home) + '</option>')).join('');
  return '<div class="gtabs"><div class="gtabs__row">'
    + (V.game ? '<button class="gback" data-v3boardgame="" '
        + 'aria-label="Back to all games">\u2039</button>' : '')
    + '<div class="gsel">' + step(-1)
    + '<select data-v3gamesel aria-label="Filter to one game">' + opts
    + '</select>' + step(1) + '</div>'
    + (V.game ? '<button class="askbtn askbtn--mini" data-v3sheet="ask"'
        + ' aria-label="Ask about this game">'
        + '<span>Ask</span><i>\u2192</i></button>' : '')
    + '</div></div>';
}

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
  // The line-only sorts are offered where there is a line. A touchdown board
  // picked up "Difference from the line" and sorted by 498 nulls — the
  // control moved and the board did not, which is worse than not offering it.
  const opts = V3SORTS.filter(c => v3MktLines() || !c[3])
    .map(c => '<option value="' + c[0] + '"'
    + (V.sort === c[0] ? ' selected' : '') + '>' + esc(c[1]) + '</option>')
    .join('');
  return '<div class="picker">'
    + '<span class="eyebrow">Sort by</span>'
    + '<select data-v3sortsel aria-label="Sort the board">' + opts + '</select>'
    + '<button class="dirbtn" data-v3dir="1" aria-label="'
    + (V.desc ? 'Highest first' : 'Lowest first') + '">'
    + (V.desc ? '\u2193 High' : '\u2191 Low') + '</button></div>';
}

// THE CAVEATS STAY; THEY STOP BEING THE PAGE.
//
// This project will not drop a caveat — several of them are the reason a
// number is not a tip, and `angles` would be a list of winning patterns
// without them. But four paragraphs under a table is the part of the card
// with the most words and the least news, and on the second visit it is
// scrolled past. Folded, it is one line until somebody wants it, and it is
// still there in the page for the reader who does.
//
// `<details>` rather than a button and a state flag: it survives a re-render
// without being in `V`, it opens from the keyboard, and a reader who prints
// the page or searches it finds the text either way.
function v3Fold(label, html) {
  if (!html) return '';
  return '<details class="fold"><summary>' + esc(label) + '</summary>'
    + '<div class="fold__b">' + html + '</div></details>';
}

function v3Seg(attr, opts, on) {
  return opts.map(o => '<button data-' + attr + '="' + o[0] + '" aria-pressed="'
    + (o[0] === on) + '">' + esc(o[1]) + '</button>').join('');
}

function v3Sorted(rows) {
  let col = V3SORTS.filter(c => c[0] === V.sort)[0] || V3SORTS[0];
  // A LINE-ONLY SORT ON A BOARD WITH NO LINES FALLS BACK RATHER THAN SORTING
  // NULLS. Switching from Catches to Scores a TD carries the chosen sort
  // across, and `v3SortBar` stops offering it there — so without this the
  // select reverts to showing the first option while the rows stay ordered by
  // a column that is null on every one of them. Here rather than in the
  // market switch, because a bookmark and a remembered session arrive the
  // same way and never pass through it.
  if (col[3] && !v3MktLines()) col = V3SORTS[0];
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
  if (V.filter === 'streak') rows = rows.filter(r => v3Streak(r));
  // THE RULE'S SIDE AND THE RULE'S PRICE, not the board's default.
  //
  // `v3Line` renders "Over" on any row without `take`, and `v3Row` shows
  // `odds`, which is the OVER's price. Both are right for a board that
  // displays the over and our chance of it, and both are wrong here: over
  // 2026 weeks 3-4 NINE of the rule's 77 picks were unders, so one pick in
  // eight would have been drawn as the opposite bet at the wrong price.
  //
  // `underOdds` rather than the rule's own `price`: the archived median is
  // what the measured return was priced at, and this is a bet you are about
  // to place, so the number on the row is the one the book is showing. The
  // help line says the return was measured at the median across books.
  if (V.filter === 'gap') {
    const m = marketOf(V.market);
    rows = rows.map(r => {
      const hit = v3EdgeHit(m, r);
      if (!hit) return null;
      const und = hit.side === 'under';
      return Object.assign({}, r, {
        take: hit.side, takeGap: hit.edge_pp,
        odds: und ? (has(r.underOdds) ? r.underOdds : null) : r.odds,
        dec: und ? (has(r.underDec) ? r.underDec : null) : r.dec,
      });
    }).filter(Boolean);
  }
  if (V.game) rows = rows.filter(r => v3Same(r.gameId, V.game));
  rows = v3Match(rows);
  if (!rows.length) {
    if (V.game && !V.q && V.filter === 'all') return v3GameEmpty(V.game);
    return '<div class="empty">' + (V.filter === 'fade'
      ? 'Nothing on this market is priced far enough above our number to '
        + 'flag this week.'
      : V.q
      ? 'No player matching \u201c' + esc(V.q) + '\u201d on this market.'
      : V.filter === 'streak'
      ? 'Nobody on this market went one way in ' + V3STREAK_MIN + ' of their '
        + 'last ' + V3STREAK_OF + ' weeks. A player needs five weeks with a '
        + 'line and a result to be counted at all.'
      : V.filter === 'gap'
      ? (KIND[V.market] !== 'ou'
         ? 'The price rule is fitted on the over/under markets only. Pick '
           + 'catches, receiving, rushing or passing yards.'
         : ((marketOf(V.market) || {}).edge || {}).note
         ? 'The price rule could not run on this market: '
           + esc(((marketOf(V.market) || {}).edge || {}).note)
         : 'No line on this market is far enough off our number this week. '
           + 'Most weeks it takes a handful, and early in the week it takes '
           + 'fewer \u2014 the closing prices have not landed yet.')
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
    // A CONTRADICTION, NOT A DISAGREEMENT. The market declining to quote the
    // passer we have as this team's lead, while pricing someone we rate below
    // him, is the books knowing he is not playing — so our number for the man
    // they DO quote was built on him being a backup. Our number being merely
    // far from the line is normal and is usually us being right, which is why
    // that is not what this marks. See `_flag_role_doubt`.
    + (row.role_doubt
       ? '<span class="tag tag--bad">Role changed</span>' : '')
    + (scr ? '<span class="tag tag--warn">Script risk</span>' : '')
    // Recent form, before the tap rather than after it. Asked for: "identify
    // potential outliers before clicking the player name".
    + v3StreakTag(row)
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

function v3Cell(label, value, tone, cls) {
  return '<span class="cell' + (cls ? ' ' + cls : '') + '"><b'
    + (tone ? ' class="' + tone + '"' : '')
    + '>' + value + '</b><i>' + esc(label) + '</i></span>';
}

// Everything the board knows about one row. Asked for: "I kinda thought that
// clicking on this condensed view of a player would show full stats."
//
// Built from fields that may be absent, so each is emitted only when it has a
// value — a detail panel of eleven em-dashes says less than four real numbers.
// WHAT HIS LINE HAS DONE BEFORE, which is the question people open a player
// to ask and the board cannot answer: the board prices one week.
//
// THIS MAKES NO CLAIM AND SAYS SO BY WHAT IT LEAVES OUT. No rate against the
// price, no expectation, no interval, and no green -- those are the machinery
// of an edge, and measuring an edge on a player prop needs a usage model, a 7%
// house cut cleared, and a baseline holding playing time constant. A line, what
// he did, and the date need none of it, and a week he caught nothing is a zero
// a reader can see for themselves rather than a distortion buried in a rate.
//: How many recent weeks a streak is read over, and how many of them have to
//: agree before it is worth saying. Four of five rather than five of five: a
//: perfect run is rare enough that the flag would almost never appear, and the
//: fact worth surfacing is a lopsided record, not an unbroken one.
//: The streak window, READ FROM THE PAYLOAD rather than written here.
//: `src/evaluation/streaks.py` owns the rule now, and a copy of its two
//: constants in this file would let the prose keep saying "4 of their last
//: 5" after the rule had changed, with nothing failing.
const V3STREAK_OF = ((DATA.pastlines || {}).streak_of) || 5;
const V3STREAK_MIN = ((DATA.pastlines || {}).streak_min) || 4;

// RECENT FORM, AGAINST THE LINE HE WAS QUOTED THAT WEEK.
//
// Not against this week's line. His number moves — three catches against 1.5
// and three against 3.5 are not the same week — so counting every past game
// against today's line would report a streak the player never actually ran.
// The chart above the fold already reads this way; this is the same question
// answered in one phrase for a reader who has not opened him yet.
//
// NOT A SIGNAL, AND DELIBERATELY NOT COLORED LIKE ONE. `player_history` makes
// the argument at length: a rate over five games has an interval wide enough
// to cover almost anything, and this project has measured no edge in recent
// form. It is drawn as a neutral tag beside the other facts, because a reader
// scanning a board can see it and a reader acting on it alone is not being
// told by the page that they should.
//
// Returns null unless the last five weeks all carry a line and a result, so a
// player with a short or ragged record is silent rather than flagged on three.
// ── The price rule, on this week's board ────────────────────────────────
//
// A MEMBERSHIP TEST, NOT A RULE. `prop_edge.qualifying` picks the bets — the
// same function the Record page's section 05 is scored with — and the
// payload carries them, so the board's filter and the card's return are
// about the same bets by construction rather than by agreement.
//
// Written in the page it would have to reproduce two things to be the same
// rule, and both are easy to get subtly wrong: the fitted threshold per
// market, and the reduction to ONE LINE PER PLAYER-GAME before the gap is
// read. Week 5 was carrying four rushing-yards lines for Jalon Daniels and
// five passing-yards lines for one quarterback; a filter that kept whichever
// of them cleared would be shopping among them, which is the inflation that
// once turned a +0.30% player edge into +6.89%.
function v3EdgeKeys(m) {
  const e = (m || {}).edge || {};
  return new Set((e.picks || []).map(r => ouKey(r.player_name, r.point)));
}
//: What the rule decided about a row: the side it took and how far our
//: number sat from the price, or null where it took nothing.
function v3EdgeHit(m, row) {
  const e = (m || {}).edge || {};
  return (e.picks || []).find(r => ouKey(r.player_name, r.point)
                                   === ouKey(row.player, row.line)) || null;
}
function v3IsEdge(row) {
  return KIND[V.market] === 'ou'
    && !!v3EdgeHit(marketOf(V.market), row);
}
//: The four fitted margins, in the words the help line uses.
function v3EdgeNote() {
  const e = (marketOf(V.market) || {}).edge || {};
  if (e.note) return 'The price rule could not run on this market: ' + e.note;
  return 'Only the lines where our number beats the sportsbook\u2019s own '
    + 'fair price by '
    + (has(e.threshold_pp) ? e.threshold_pp + ' points' : 'the fitted margin')
    + ', fitted on earlier seasons and taken at the price of the side bet. '
    + 'One bet per player, and the side shown is the rule\u2019s \u2014 on '
    + 'weeks 3-4 nine of its 77 picks were unders. Measured over those '
    + 'weeks it returned +$13.36 per $100 on 69 bets, with a range of '
    + '\u2212$12.70 to +$39.42 \u2014 which spans zero, so it is the best '
    + 'thing on the card and still 69 bets. That return was priced at the '
    + 'median across books at capture; the price here is the one on offer '
    + 'now.';
}

// A LOOKUP NOW, NOT A RULE. `src/evaluation/streaks.py` decides who is on
// one and the payload carries the answer under `pastlines.streaks`.
//
// THE RULE USED TO LIVE HERE AND THAT IS WHY IT LEFT. It counted back over
// whatever history the payload happened to inline, from whatever "now"
// happened to be, so it could only ever answer as of today: ask it how the
// streak picks did in week 3 and the answer changed every time a later week
// landed, and nothing anywhere recorded which players it had shown. A rule
// that cannot be asked about the past cannot be scored, and scoring it is
// what the Record page is for.
//
// Parity was measured before the JavaScript went, on the live payload of
// 2026-10-07 and across all six markets: 277 flagged players, identical
// sets, identical directions, identical baselines. `tests/js/v3app.js`
// keeps the board honest about reading the flag; `tests/test_streaks.py`
// keeps the rule honest about what it means.
//
// Everything the old code earned is still true of the Python: the window is
// five graded weeks, four of them have to run one way, a short or ragged
// record is silent rather than approximate, and whichever direction covers
// more than half the players a market can even count is that market's own
// default and is not flagged. "Did not score in 4 of his last 5" was true of
// 385 of the 398 players eligible on first touchdown — a label for the
// market wearing a player's name.
function v3Streak(row) {
  const mk = v3PastMarket();
  if (!mk || !row || !row.player) return null;
  const got = (((DATA.pastlines || {}).streaks || {})[mk] || {})[row.player];
  if (!got) return null;
  const meta = (((DATA.pastlines || {}).markets) || [])
    .filter(m => m.key === mk)[0] || {};
  return { n: got[1], of: got[2], over: got[0] === 'over',
           yes: meta.kind === 'yesno' };
}

function v3StreakTag(row) {
  const st = v3Streak(row);
  if (!st) return '';
  const what = st.yes ? (st.over ? 'scored' : 'did not score')
                      : (st.over ? 'over' : 'under');
  return '<span class="tag" title="Counted against the line he was quoted '
    + 'each week, not this week\u2019s. Recent form is not an edge this '
    + 'project has measured \u2014 it is here to be seen, not acted on.">'
    + st.n + ' of ' + st.of + ' ' + what + '</span>';
}

function v3PastMarket() {
  return V3HIST[V.market] || '';
}

// FETCHED, NOT INLINED, past the first ten. All of it in the page is 1.5 MB on
// top of the 4.5 it already carries; ten weeks is 495 KB and draws the chart.
// The rest arrives the same way a past week does.
function v3PastAll(mk, then) {
  const k = 'hist:' + mk;
  if (V3CACHE[k]) { then(V3CACHE[k]); return; }
  const path = 'data/hist-' + mk + '.json';
  const fail = why => { V3CACHE[k] = { error: why }; then(V3CACHE[k]); };
  let p;
  try { p = fetch(path); } catch (e) { fail(String(e)); return; }
  p.then(r => {
    if (!r.ok) { fail('the server answered ' + r.status); return; }
    return r.json().then(o => { V3CACHE[k] = { players: o || {} };
                                then(V3CACHE[k]); });
  }).catch(e => fail(String(e)));
}

function v3PastRows(row) {
  const mk = v3PastMarket();
  if (!mk || !row || !row.player) return null;
  const k = 'hist:' + mk;
  const full = V3CACHE[k] && V3CACHE[k].players
    && V3CACHE[k].players[row.player];
  if (V.pastAll === row.player && full) return { rows: full, all: true };
  const P = DATA.pastlines || {};
  const rows = ((P.players || {})[row.player] || {})[mk];
  return rows && rows.length ? { rows: rows, all: false } : null;
}

// WHAT BACKING HIM EVERY ONE OF THOSE WEEKS WOULD HAVE RETURNED.
//
// $100 a week at the price the archive holds, which is ONE SIDE: the Yes on a
// touchdown market and the Over on a line. The No and the Under are not in the
// archive at all, so "what if you had faded him" is a question this cannot
// answer and does not pretend to — the panel names the side it priced.
//
// A WEEK HE DID NOT PLAY IS A VOID, NOT A LOSS. `player_history` fills a man
// with no stat row as a zero, which is right for the record and wrong for the
// money: a book hands the stake back on an inactive player. Counting those as
// losing $100 would understate the return by 3,029 of 15,502 anytime-TD weeks
// — a fifth of the record — so they are set aside and counted out loud.
//
// NOT A FORECAST. Ten bets is nowhere near enough to separate a player from
// the vig; this is a record of what happened, which is why it is stated in
// dollars rather than as a rate or an edge.
function v3PastMoney(rows, meta, back) {
  const yes = meta.kind === 'yesno';
  const profit = o => o > 0 ? o : 10000 / -o;
  // WHICH SIDE THE MONEY WENT ON. Backing the over every week answers a
  // question nobody asked of a player who has gone under six times running:
  // what the record is worth is what BACKING THE RECORD would have returned.
  // `back` is 'over' or 'under'; the caller reads it off the window.
  const under = back === 'under';
  let money = 0, bets = 0, voids = 0, won = 0, unpriced = 0;
  rows.forEach(r => {
    // `played` and the other side's price both arrived after this row shape
    // did. An older cached payload has seven fields and no flag, and treating
    // "missing" as "played" keeps its old answer rather than voiding every
    // week in it.
    const played = r.length > 7 ? r[7] : 1;
    const odds = under ? (r.length > 8 ? r[8] : null) : r[5];
    const did = r[6], line = r[4];
    if (!has(odds)) { unpriced++; return; }
    if (played === 0) { voids++; return; }
    const over = yes ? did === 1 : (has(line) && did > line);
    const hit = under ? !over : over;
    bets++;
    if (hit) { won++; money += profit(odds); } else { money -= 100; }
  });
  return { money: money, bets: bets, voids: voids, won: won,
           unpriced: unpriced,
           side: under ? (yes ? 'no' : 'the under') : (yes ? 'yes' : 'the over') };
}

//: Which way the window ran, which is the side the money question is about.
//: Ties go to the over, because that is the side the archive always holds a
//: price for and a 5-5 record is not a streak in either direction.
function v3PastBack(rows, meta) {
  const yes = meta.kind === 'yesno';
  let over = 0, n = 0;
  rows.forEach(r => {
    const did = r[6], line = r[4];
    if (!has(did)) return;
    if (!yes && !has(line)) return;
    n++;
    if (yes ? did === 1 : did > line) over++;
  });
  return (n && over * 2 < n) ? 'under' : 'over';
}

function v3PastLines(row) {
  const mk = v3PastMarket();
  const got = v3PastRows(row);
  if (!got) return '';
  const P = DATA.pastlines || {};
  const meta = (P.markets || []).filter(m => m.key === mk)[0] || {};
  const yes = meta.kind === 'yesno';
  const every = got.rows;
  // ONE WINDOW FOR THE WHOLE PANEL. Reading the chart over ten weeks and the
  // money over three would be two answers to one question, and the reader
  // picked the question.
  const win = (V.pastN && V.pastN < every.length) ? V.pastN : every.length;
  const rows = every.slice(0, win);
  // r = [season, week, opponent, home, line, odds, did, played]
  const did = r => r[6], line = r => r[4];
  // THE CHART IS WHAT HE DID MINUS HIS LINE, because his line moves week to
  // week: nine catches against 6.5 and nine against 9.5 are not the same week,
  // and the raw count cannot say so while the margin can. On a market with no
  // line the chart is the price he was quoted instead.
  const val = r => yes ? v3PastImp(r[5])
    : (did(r) - (line(r) == null ? 0 : line(r)));
  const vals = rows.map(val);
  let top = 0;
  vals.forEach(v => { const a = Math.abs(v); if (a > top) top = a; });
  if (!top) top = 1;
  const bars = rows.map((r, i) => {
    const v = vals[i];
    const zero = !yes && did(r) === 0;
    const hit = yes ? did(r) === 1 : v > 0;
    // HALF THE BOX, BECAUSE A BAR ONLY HAS HALF OF IT.
    //
    // The bars grow from the midline: `.pl__b--up` is pinned to the top and
    // pushed down by half its own height, `--dn` the mirror. So the space a
    // bar can occupy is 36 of the 72 pixels, and scaling the biggest week to
    // 100% drew it at twice its room — it overflowed the chart and landed on
    // the sentence underneath, which is what "5 of 10 went over" was being
    // struck through by. `.pl__c` also clips now, so a future arithmetic
    // slip is a clipped bar rather than text with a bar through it.
    const h = Math.max(4, Math.round(Math.abs(v) / top * 50));
    const cls = 'pl__b' + (yes ? (hit ? ' pl__b--hit' : '')
      : (v > 0 ? ' pl__b--up' : ' pl__b--dn')) + (zero ? ' pl__b--zero' : '');
    const ttl = v3PastWhen(r) + ' ' + (r[3] ? 'vs ' : 'at ') + r[2] + ' \u2014 '
      + v3PastSaid(r, meta);
    return '<span class="' + cls + '" title="' + esc(ttl) + '" '
      + 'style="height:' + h + '%"></span>';
  }).slice().reverse().join('');
  const over = rows.filter(r => yes ? did(r) === 1
    : (line(r) != null && did(r) > line(r))).length;
  const zeros = rows.filter(r => !yes && did(r) === 0).length;
  const list = rows.map(r =>
    '<div class="pl__r"><span class="pl__w">' + esc(v3PastWhen(r)) + '</span>'
    + '<span class="pl__o">' + (r[3] ? 'vs ' : 'at ') + esc(r[2]) + '</span>'
    + '<span class="pl__v num">' + esc(v3PastSaid(r, meta)) + '</span></div>')
    .join('');
  const more = (!got.all && (DATA.pastlines || {}).inline
    && rows.length >= (DATA.pastlines || {}).inline)
    ? '<button class="pl__more" data-v3pastall="' + esc(row.player) + '">'
      + 'Show every week</button>' : '';
  // A FETCH THAT FAILED IS NOT A PLAYER WITH TEN WEEKS. `v3PastRows` falls
  // back to the inlined ten when the full record did not arrive, which is the
  // right fallback and the wrong silence: the panel redrew identically and the
  // button read as broken. The week fetch has said this since it was written —
  // see the `V3CACHE[k].error` branch in `v3Rows` — and this is the same
  // sentence for the other fetch.
  const ck = V3CACHE['hist:' + mk];
  const err = (V.pastAll === row.player && ck && ck.error)
    ? '<p class="pl__e">Every week did not load \u2014 ' + esc(ck.error)
      + '. These are the last ' + rows.length + '.</p>' : '';
  // THE SENTENCE FIRST, THEN THE PICTURE IT DESCRIBES.
  //
  // Printed underneath, the count read as a footnote to a chart the reader
  // had already given up on. A chart of bars above and below an unlabeled
  // line is not self-explanatory to anyone who has not built one; the same
  // ten weeks in a sentence are. So the words lead and the chart shows them.
  const cap = (yes ? over + ' of ' + rows.length + ' landed'
                   : over + ' of ' + rows.length + ' went over')
    + (zeros ? ' \u00b7 ' + zeros + ' week' + (zeros > 1 ? 's' : '')
               + ' he recorded nothing' : '');
  // WHAT THE COLORS MEAN, ON THE PAGE RATHER THAN IN A TOOLTIP. Blue above
  // and gray below was a convention the reader had to infer, and hovering a
  // bar to find out is not available on a phone at all.
  const key = (sw, txt) => '<span class="pl__k"><i class="pl__sw pl__sw--'
    + sw + '"></i>' + txt + '</span>';
  const legend = (yes
      ? key('up', 'scored') + key('dn', 'did not')
      : key('up', 'over his line that week') + key('dn', 'under'))
    + (zeros ? key('zero', 'recorded nothing') : '');
  // THE WINDOW THE READER PICKED. Only offered where it would narrow
  // anything: with six weeks on record, "last 10" is the same six.
  const opts = [3, 5, 10].filter(n => n < every.length)
    .map(n => [String(n), 'last ' + n]);
  opts.push(['all', 'all ' + every.length]);
  const pick = opts.length > 1
    ? '<div class="seg seg--' + opts.length + ' pl__seg pl__seg--stick">'
      + v3Seg('v3pastn', opts,
              (V.pastN && V.pastN < every.length) ? String(V.pastN) : 'all')
      + '</div>' : '';

  // WHICH WAY THIS WINDOW RAN, decided before the money is counted, because
  // it is what the money is about: a player who has gone under six weeks
  // running is not asking what backing the over would have returned.
  const back = v3PastBack(rows, meta);
  const m = v3PastMoney(rows, meta, back);
  const money = m.bets
    ? '<p class="pl__m">$100 a week on <b>' + esc(m.side) + '</b>: '
      + '<b class="' + (m.money >= 0 ? 'pos' : 'neg') + '">'
      + (m.money >= 0 ? '+$' : '\u2212$')
      + Math.abs(m.money).toFixed(0) + '</b> over ' + m.bets + ' bet'
      + (m.bets === 1 ? '' : 's') + ', ' + m.won + ' won'
      + (m.voids ? ' \u00b7 ' + m.voids + ' week'
         + (m.voids > 1 ? 's' : '') + ' voided, he did not play' : '')
      + (m.unpriced ? ' \u00b7 ' + m.unpriced + ' with no price archived' : '')
      + '</p>'
      // SAID EVERY TIME, because the number is the kind that gets screenshotted.
      + '<p class="help">The side this window actually ran, at the archived '
      + 'price, before any judgment about whether it will again \u2014 '
      + m.bets + ' bets cannot separate a player from the hold.'
      + (back === 'under'
         ? ' The under\u2019s price is recovered from the two-sided quote the '
           + 'books posted, not assumed.' : '')
      + '</p>'
    // NOTHING TO BET IS NOT A LOSS OF ZERO. A window that ran under on a
    // market where the archive never held the other side has no figure here,
    // and the reason is worth a line: it is the market, not the player.
    : (back === 'under'
       ? '<p class="help">This window ran ' + esc(yes ? 'no' : 'under')
         + ', and the archive holds no price for that side on this market '
         + '\u2014 the books quote the ' + esc(yes ? 'yes' : 'over')
         + ' and little else, so there is no figure to show.</p>'
       : '');

  return '<div class="pl">'
    + '<div class="pl__h">' + esc(meta.label || mk) + ', last '
    + rows.length + '</div>'
    + pick
    + '<p class="pl__s">' + cap + '</p>'
    + money
    + '<div class="pl__lg">' + legend + '</div>'
    + '<div class="pl__c">' + (yes ? '' : '<i class="pl__z"></i>') + bars
    + '</div>'
    + '<div class="pl__ax"><span>'
    + esc(v3PastWhen(rows[rows.length - 1])) + '</span><span>'
    + esc(v3PastWhen(rows[0])) + '</span></div>'
    + '<div class="pl__l">' + list + '</div>' + err + more + '</div>';
}

function v3PastImp(odds) {
  if (!has(odds)) return 0.5;
  return odds > 0 ? 100 / (odds + 100) : (-odds) / (-odds + 100);
}

// THE PLAYOFFS ARE NOT WEEK 22. The archive numbers them straight on from the
// regular season, so a Super Bowl line read as "wk22", which is a week that
// does not exist to anybody who watches football.
const V3PAST_WK = { 19: 'WC', 20: 'DIV', 21: 'CONF', 22: 'SB' };

function v3PastWhen(r) {
  const w = V3PAST_WK[r[1]] || ('wk' + r[1]);
  return '\u2019' + String(r[0]).slice(2) + ' ' + w;
}

function v3PastSaid(r, meta) {
  if (meta.kind === 'yesno') {
    return (r[6] === 1 ? 'yes' : 'no') + (has(r[5]) ? ' \u00b7 '
      + v3Dash(american(r[5])) : '');
  }
  const n = r[6], ln = r[4];
  const unit = meta.unit ? ' ' + meta.unit : '';
  return (ln == null ? '' : ln + ' \u00b7 ') + n + unit
    + (ln == null ? '' : ' \u00b7 ' + (n > ln ? 'over' : 'under'));
}

function v3Detail(row) {
  const f = [];
  // A THIRD ARGUMENT FOR THE FACTS THAT ARE SENTENCES. Most of this list is a
  // label and a number and pairs up two to a line happily. One of them is a
  // clause — "PIT to win, 1.5x the average bet — this player's side" — and in
  // half a row it wraps into a column of fragments. It takes the whole width
  // and goes last, where a sentence reads as the note it is rather than as a
  // field somebody squeezed.
  const add = (l, v, wide) => {
    if (v != null && v !== '') f.push([l, v, !!wide]);
  };
  add('Model (no price)', v3Pct(row.modelOnly, 1));
  add('Book (de-vigged)', v3Pct(row.book, 1));
  add('Adjusted (blend)', v3Pct(row.ours, 1));
  add('Priced on', has(row.modelOnly) && row.kind === 'td'
    ? 'Model' : 'Adjusted');
  add('Edge', has(row.edge)
    ? (row.edge > 0 ? '+' : '') + row.edge.toFixed(1) + 'pp' : null);
  add('Price', has(row.odds) ? v3Dash(american(row.odds)) : null);
  // NAMING ONE BOOK IMPLIES IT IS THE ONLY ONE. Books tie at the best price
  // on about half of all players — 254 of 538 on one week's anytime board, one
  // of them eight deep — and the name shown is the alphabetically first of
  // them, which is arbitrary by design. Saying how many were level is what
  // keeps "at ballybet" from reading as "only at ballybet".
  add('Best price', has(row.best)
    ? v3Dash(american(row.best))
      + (row.bestBook ? ' at ' + row.bestBook : '')
      + (has(row.bestN) && row.bestN > 1
         ? ' and ' + (row.bestN - 1) + ' other'
           + (row.bestN > 2 ? ' books' : ' book')
         : '')
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
  // THE NUMBER THE DIFFERENCE SORT ORDERS BY, SAID OUT LOUD. A board can be
  // sorted by a quantity it never shows, and the reader is then taking the
  // ordering on trust — which is the one thing this page is built not to ask.
  // In the market's own units, signed the way the sort is: over is positive.
  const dv = v3Diff(row);
  add('Difference', has(dv)
    ? v3Dash((dv > 0 ? '+' : '') + dv.toFixed(1)) + ' '
      + (unitOf(row.key) || '') + ' vs the line'
    : null);
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
  // LAST, AND ACROSS THE WHOLE PANEL. It is the only fact here about the
  // GAME rather than about the player, and the only one written as a clause.
  const gm = v3GameMoney(row);
  if (gm) {
    add('Big money in this game',
        gm.side + ' ' + gm.market.toLowerCase() + ', '
        + gm.ratio.toFixed(1) + '\u00d7 the average bet'
        + (gm.mine ? ' \u2014 this player\u2019s side'
           : gm.facing ? ' \u2014 the other side' : ''), true);
  }
  // THE RECORD FIRST, THE FIGURES UNDER IT.
  //
  // The panel opened with twenty label-and-number pairs and put the chart of
  // what the player has actually done below them, so a tap landed on Model,
  // Book, Adjusted, Edge, Price, Best price, Opened at, Moved, Line, We
  // project, Likely range, Books quoting — and the thing most people opened
  // him for was a scroll away. What he has done the last ten weeks leads now;
  // the figures that price this week follow it.
  // NO HEADER ON IT. The panel opens directly under the player it is about,
  // at every width, so the row above it is the title — which is the whole
  // reason the drawer that needed one is gone.
  return '<div class="detail">'
    + v3PastLines(row)
    + '<dl>'
    + f.map(x => '<div' + (x[2] ? ' class="detail__w"' : '') + '><dt>'
        + esc(x[0]) + '</dt><dd class="num">' + x[1]
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
  // THE BOARD'S MARKET KEY IS `first`, NOT `first_td`. `v3Graded` stamps rows
  // with `V.market`, which is a V3MKT key — the archive name `first_td` only
  // ever appears in `V3HIST` and in the fetched file's name. Checking for the
  // archive name here matched nothing, so every first-TD row fell through to
  // the count branch and printed "1 TD" beside a cross on each player who
  // scored second — the exact sentence this function exists to avoid. Both
  // spellings are accepted because only one of them is reachable and it is
  // not the obvious one.
  if (row.key === 'first' || row.key === 'first_td') {
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
    + 'what to bet.</p>'
    // Moved down from above the board, where it was five lines of standing
    // explanation on every screen. It belongs with the other things that are
    // true every week rather than at the top of the one thing that is not.
    + '<p class="lede" style="font-size:15px;line-height:20px;margin-top:12px">'
    + '<b style="color:var(--ink)">Prices moved toward us</b> counts the picks '
    + 'we rated above the opening price whose line then came our way. Over '
    + 'three seasons that has run near 60%, against 54% for a shuffled list — '
    + 'it is the one edge this project has measured, and it is about the PRICE '
    + 'moving, not about the bet winning.</p></div>';
}

// THE ADJUSTED WIN PROBABILITY, derived the same way everywhere.
//
// `game_blend` fits a weight on the SPREAD; the win probability has to move
// by the same fraction, or the adjusted number on the list and the adjusted
// bar on the game page are two different quantities with one name.
//
// `blend.win_home` is that number computed once in Python
// (`game_blend.blend_win`) and is preferred whenever the card carries it.
// Weeks frozen before it existed do not, and fall through to the
// interpolation below, which reads only frozen fields and the book's own
// price, so it is a derivation of what the card showed, not a recompute.
function v3AdjWin(c) {
  if (c && c.blend && has(c.blend.win_home)) return c.blend.win_home;
  if (!c || !c.blend || !has(c.blend.spread) || !has(c.spread)
      || !has(c.model_spread) || !has(c.win_home) || !has(c.model_win_home))
    return null;
  const denom = c.model_spread - c.spread;
  const w = denom ? (c.blend.spread - c.spread) / denom : 0;
  return c.win_home + w * (c.model_win_home - c.win_home);
}

// THE HOME SIDE'S CHANCE UNDER THE CHOSEN BASIS.
//
// Book, model or the blend of the two, in that order of fallback, so a card
// missing one number is still graded rather than dropped. Returns the HOME
// probability; the caller turns it into a side.
function v3GBasis(c) {
  const book = has(c.win_home) ? c.win_home : null;
  const model = has(c.model_win_home) ? c.model_win_home : null;
  const adj = v3AdjWin(c);
  const want = V.gbasis === 'book' ? 'book'
             : V.gbasis === 'adj' ? 'adjusted' : 'model';
  const by = { book: book, model: model, adjusted: adj };
  // WHICH NUMBER WAS USED, not only its value. The card marks that cell, and
  // marking the one that was asked for rather than the one that answered
  // would point at a blank cell on any game missing it.
  const used = by[want] != null ? want
             : (model != null ? 'model' : 'book');
  const v = by[used];
  return { home: v == null ? 0 : v, used: used };
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
    // WHOSE FAVORITE THE ROW IS ABOUT, and therefore what the green and the
    // red are grading. Falls back through the other two rather than dropping
    // the row: a game with no model number still has a book number, and a
    // blank row would be the basis quietly failing.
    const basis = v3GBasis(c);
    const side = basis.home >= 0.5 ? c.home : c.away;
    const forSide = v => v == null ? null
      : (side === c.home ? v : 1 - v);
    const bookPct = forSide(has(c.win_home) ? c.win_home : null);
    const modelPct = forSide(mw);
    const adjPct = forSide(aw);
    const gap = (bookPct == null || modelPct == null) ? null
      : (modelPct - bookPct) * 100;
    const cell = (label, v) => v == null ? ''
      : v3Cell(label, esc(side) + ' ' + v3Pct(v, 1), '',
               label === basis.used ? 'cell--on' : '');
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
      : '<span class="strip strip--basis num" '
        + 'style="grid-template-columns:repeat(4,auto);'
        + 'justify-content:start;gap:4px">'
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
    + '<div class="stat"><span class="eyebrow">Upsets</span><b class="num">'
    + flips + '</b></div>'
    + '<div class="stat"><span class="eyebrow">Model agrees</span><b class="num">'
    + agree + '</b></div></div></div>'
    // THE SAME MEASUREMENT, over game lines rather than player props.
    //
    // It only ever appeared on the props board, which made the project's one
    // measured edge look like a fact about touchdown props. It is a fact
    // about every line we rate, and the games board rates the moneylines,
    // spreads and totals — so it belongs here too, and only on a live week
    // for the same reason: on a graded week the prices stopped moving.
    + (V.week == null
       ? v3ClvNote(((DATA.games || {}).rows || [])
                     .filter(r => r.priced && !r.blocked),
                   'of the game lines on this board')
       : '')
    // PINNED, like every other filter in the app. Sixteen game cards is four
    // screens, and the control that narrows them sat above all four. The
    // counts and the measured edge above it stay in the flow: they are read
    // once, and they are what makes this bar the top of the page once you
    // start scrolling.
    //
    // `pbar` is the shared pinned-filter bar rather than a props-only one, so
    // the two boards cannot drift apart visually. `--free` because this one
    // stands on its own instead of tucking under a bar above it.
    + '<div class="pbar pbar--free"><div class="seg seg--4">'
    + v3Seg('v3gfilter', [['all', 'All'], ['flip', 'Upsets'],
                          ['agree', 'Agrees'], ['diff', 'Disagrees']],
            V.gfilter)
    + '</div>'
    // WHOSE PICK IS BEING GRADED, on its own line under the filter. Three
    // words rather than a sentence: the row underneath already labels every
    // percentage, so this only has to say which of them the row is about.
    + '<div class="gbasis"><span class="eyebrow">'
    + (V.week == null ? 'Side shown' : 'Graded on') + '</span>'
    + '<div class="seg seg--3">'
    + v3Seg('v3gbasis', [['book', 'Book'], ['model', 'Model'],
                         ['adj', 'Adj']], V.gbasis)
    + '</div></div></div>'
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
    + '‹ ' + (V.backTab === 'angles' ? 'Angles' : 'Games')
    + '</a><div class="card">That game is not on this week’s '
    + 'board.</div></div>';
  const notes = (DATA.notes || {})[gid] || [];
  const cats = ['all'].concat(notes.map(n => n.cat).filter(
    (v, i, a) => a.indexOf(v) === i));
  const shown = notes.filter(n => V.cat === 'all' || n.cat === V.cat);

  return '<div class="wrap">'
    // ONE DISTRIBUTION, ONE TAB.
    //
    // Bets and Score were two renderings of the same thing: `score_dist`
    // answers both from ONE call to `comparables(spread, total)` — the same
    // historical games — as a final-score table and as a ladder of lines.
    // Reading "PIT by 5.2" against "% to hit over 24" meant moving between
    // two tabs to see one distribution twice. Matchup stays separate because
    // it answers WHY rather than WHAT.
    // STICKS TO THE TOP OF THE PANE while you read. The sections are long —
    // the ladder alone runs four tables — so switching from deep inside one
    // meant scrolling all the way back up to a bar you could not see.
    //
    // Its own wrapper rather than making `.seg` sticky: the segmented control
    // is used for the market pills and the halves too, and those belong in the
    // flow. The wrapper also carries the page background, without which the
    // rounded corners of the control let content slide visibly behind it.
    // THE GAME SWITCHER RIDES WITH IT.
    //
    // It used to sit in its own nav at the very top, beside the back link,
    // which put it above the matchup card — so by the time you were reading
    // Outcome and wanted the same table for another game, the control for
    // changing game had scrolled off two screens ago and the only route was
    // back out to the list and in again. Pinned, changing game is the same
    // one tap as changing section, from wherever you have read to.
    // ASKING IS PINNED TOO, and shares the switcher's row.
    //
    // It used to sit directly under the score card, which is the first thing
    // you see and then the last thing you can reach: by the Outcome tables it
    // was three screens up. Pinned, it is available from wherever you have
    // read to, which is the point of a button whose whole job is "about THIS
    // game".
    //
    // On the same row rather than its own, because the bar already carries a
    // switcher and a five-way control. A third full-width row put it near
    // 140px on a phone — a sixth of the screen permanently spent on chrome —
    // and at that height a pinned bar stops being a convenience.
    + '<div class="gtabs">'
    + '<div class="gtabs__row">'
    // BACK LEADS THE ROW, and is the one control here that is not bordered.
    //
    // Three chevrons on one row is a puzzle: back, previous game and next
    // game all point the same way. So it reads as navigation rather than as
    // part of the stepper — plain, muted, outside the bordered group — which
    // is the same distinction the rest of the app draws between leaving a
    // screen and changing what is on it.
    + '<button class="gback" data-v3back="1" aria-label="'
    + (V.backTab === 'angles' ? 'Back to the angles board' : 'Back to all games')
    + '">\u2039</button>'
    + v3GameSwitch(gid)
    + '<button class="askbtn askbtn--mini" data-v3sheet="ask"'
    + ' aria-label="Ask about this game">'
    + '<span>Ask</span><i>\u2192</i></button>'
    + '</div>'
    + '<div class="seg seg--5">'
    // ORDERED BY WHAT YOU ARE DECIDING, not by how the sections were built.
    //
    // The three things you can bet come first and sit together — the game
    // price, the game result, the players — then the two that explain them.
    // Notes used to sit BETWEEN them, splitting the betting surfaces around
    // a piece of commentary.
    //
    // NAMED FOR WHAT IS IN THEM. `Outcome` covered the score distribution and
    // not the ladder of lines sitting under it, and both are about the score.
    // `Props` rather than `Players` because it is the Props board scoped to
    // this game — the same rows, the same markets, the same sort — and giving
    // one concept two names on one screen is how a reader concludes they are
    // two boards. The KEYS are unchanged: they are in saved state and in
    // links, and renaming a label is not a reason to break those.
    + v3Seg('v3gtab', [['odds', 'Odds'], ['players', 'Props'],
                       ['notes', 'Notes'], ['edge', 'Matchup'],
                       ['angles', 'Angles']], V.gameTab)
    + '</div></div>'
    // THE TAB'S OWN CONTENT COMES FIRST, CONTEXT UNDER IT.
    //
    // The injury report and the public split sat between the tab bar and the
    // content, so every filter and sort control on the Players tab was two
    // screens below the tab you pressed to reach it: change a market, scroll
    // back down, read, scroll up again. Both blocks are the same all week
    // whichever tab you are on, which is exactly what should not be between
    // a control and the rows it controls.
    + (V.gameTab === 'odds' ? v3GameOdds(c, gid)
     : V.gameTab === 'players' ? v3GamePlayers(gid)
     : V.gameTab === 'edge' ? v3GameMatchup(c)
     : V.gameTab === 'angles' ? v3Angles(c)
     : v3GameNotes(c, gid, cats, shown))
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
//: The metric groups, in the order the page offers them. Keys match
//: `matchup_stats.GROUPS`, which is where a metric is assigned to one and
//: where a test fails if a new metric arrives without a home.
const V3MXGROUPS = [['move', 'Moving'], ['score', 'Scoring'],
                    ['rush', 'Pressure'], ['tempo', 'Tempo']];

function v3Matchup(c) {
  const m = c && c.matchup;
  if (!m || !m.rows) {
    return '<div class="card"><p class="lede" style="font-size:15px">No '
      + 'play-by-play for this season yet, so there is nothing to compare.'
      + '</p></div>';
  }
  // FULL GAME, FIRST HALF, SECOND HALF. The same eight rows rather than
  // twenty-four: a half is a different view of one matchup, not a different
  // matchup. A team that scripts its opening drives shows up in the first
  // half and is invisible in the season total.
  const halves = m.halves || [['full', 'Full game']];
  // INJURIES ARE A FOURTH VIEW OF THIS MATCHUP, not a sixth section of the
  // game. Full game, first half and second half ask "how do these units
  // rate"; the injury report asks "which of them is actually playing". Same
  // question, same control — and as its own tab it was one more thing to
  // find, on a bar that already had five.
  const views = halves.concat([['inj', 'Injury']]);
  const on = V.half === 'inj' ? 'inj'
           : (m.splits && m.splits[V.half]) ? V.half : 'full';
  const rows = (m.splits && m.splits[on]) || m.rows || [];
  // STICKY, and offset by the height of the bar above it. `--gtabs-h` is
  // written by `render` from the real measured bar, because that bar's height
  // depends on how the matchup name wraps — hard-coding it left this one
  // either overlapping the bar or floating below it.
  // FOUR AT A TIME, or all of them. One metric at a time meant twelve taps to
  // read a matchup and no way to hold two side by side; all twelve meant
  // scrolling past eleven to re-read the one you were weighing. The groups
  // are the question a reader actually has — can they move it, do they
  // finish, do they get to the quarterback, how fast does the game go — and
  // each is two to five rows, which is a screen.
  //
  // NOT OFFENSE AGAINST DEFENSE, which is the obvious split and halves
  // nothing: every row already carries both directions.
  const seen = {};
  rows.forEach(r => { if (r.group) seen[r.group] = 1; });
  const groups = V3MXGROUPS.filter(g => seen[g[0]]);
  const pick = groups.some(g => g[0] === V.metric) ? V.metric : 'all';
  const shownRows = pick === 'all' ? rows : rows.filter(r => r.group === pick);
  // A DROPDOWN, NOT PILLS. There are eleven metrics with names like "Late-half
  // scoring drives", so as pills they wrapped to six rows — a chooser taller
  // than the thing it chooses, and far too tall to pin. One full-width select
  // is a fixed 38px whatever the list holds, which is what lets it ride in the
  // pinned bar with the halves instead of scrolling away above them.
  // ALPHABETICAL IN THE LIST, and only in the list. A dropdown is something
  // you scan for a name you already have in mind, so the order that helps is
  // the one that lets you stop scanning. The SECTIONS keep the order the
  // pipeline sends, which is roughly how much each metric explains — that is
  // a ranking, and sorting it by first letter would throw it away.
  //
  // A SEGMENT NOW, NOT A DROPDOWN. The dropdown was right when the choice was
  // one of twelve names: as pills those wrapped to six rows, a chooser taller
  // than the thing it chose. Five short group names fit one row, so the
  // choice can be read at a glance instead of opened to be seen.
  const sel = groups.length < 2 ? '' : '<div class="seg seg--'
    + (groups.length + 1) + '" style="margin-top:6px">'
    + [['all', 'All']].concat(groups)
        .map(k => '<button data-v3metric="' + esc(k[0]) + '" aria-pressed="'
          + (k[0] === pick) + '">' + esc(k[1]) + '</button>').join('')
    + '</div>';
  const seg = '<div class="mxbar"><div class="seg seg--' + views.length + '">'
    + views.map(h => '<button data-v3half="' + esc(h[0]) + '" aria-pressed="'
        + (h[0] === on) + '">' + esc(h[1]) + '</button>').join('')
    + '</div>'
    // The injury report has no metrics to filter, so the chooser is absent
    // rather than present and inert.
    + (on === 'inj' ? '' : sel) + '</div>';
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
  // The "Based on" card and the "Not shown, and why" list are both gone.
  //
  // Neither answered a question the reader had in front of them: that these
  // rates come from the season's earlier games is what a season rate IS, and
  // a list of metrics the page is NOT showing is a note about the pipeline
  // rather than about the game. Between them they cost a card at the top and
  // a card at the bottom of every matchup.
  //
  // THE THIN WARNING STAYS. That one is not background — it says the numbers
  // under it are two games' worth and should not be read as rates — so it
  // keeps the same banner every other thin sample in the app uses.
  return seg
    + (on === 'inj' ? v3Injuries(c, true)
       : (m.thin ? '<div class="thin" role="note"><b>Two games or fewer</b>'
            + '<span>Treat every number here as a first impression rather '
            + 'than a rate.</span></div>' : '')
         + shownRows.map(r =>
            '<h2 class="h1" style="font-size:17px;line-height:22px;'
            + 'margin-top:20px">' + esc(r.label)
            + (r.proxy ? ' <span class="tag tag--warn">proxy</span>' : '')
            + '</h2>'
            + '<p class="help">' + esc(r.note) + '</p>'
            + '<div class="card">' + r.sides.map(p => row(r, p)).join('')
            + '</div>').join(''));
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

// TICKETS COUNT BETS; MONEY COUNTS DOLLARS.
//
// Sportsbook Review publishes tickets only, and nothing at all on the
// moneyline. Action Network publishes both, on all three markets, which is
// why the whole section is drawn from it: one feed, one customer base, the
// same two bars on every market. The other book is kept for the one thing it
// can say that this cannot — two customer bases disagreeing — and is printed
// only when they do.
//
// A gap needs to be worth a sentence before it gets one. Under
// `V3GAP_SMALL` the two shares are the same bet, rounded differently.
const V3GAP_SMALL = 8;

// **Ranked on the ratio, not the gap.** Money share minus ticket share is
// capped by the ticket share — a side already holding 89% of the tickets can
// gain at most 11 points however large its bets are — so the gap sorts by how
// unpopular a side is. Carolina at 89% of tickets and 96% of the money is the
// case that exposes it: a 7-point gap, under the threshold that earns a
// sentence anywhere else, and three times the average bet.
const V3RATIO_SMALL = 1.5;

// A MARKET, IN BETS AND IN DOLLARS, ON TWO BARS THAT LINE UP.
//
// One bar said "84% on SF" and left the reader to decide whether that was a
// lot of people or a lot of money. Those are different facts and they are
// often different numbers: SF took 84% of the bets on its spread and 79% of
// the dollars, which is a crowd of small tickets with the bigger wagers on
// the other side. Stacked, the two bars answer it at a glance.
function v3MoneyBlock(label, note, m, move) {
  if (!m || !m.sides || m.sides.length < 2) return '';
  const a = m.sides[0], b = m.sides[1];
  if (a.tickets == null && a.money == null) return '';
  // THE NUMBERS OUTSIDE THE BAR, AND EACH TEAM NAMED ONCE.
  //
  // Both labels used to sit INSIDE their own segment, which made the layout a
  // function of the split: at 84/16 the trailing segment is a sixth of the
  // width and "CLE 16%" wrapped onto two lines inside it, so the row grew
  // taller the more lopsided it got — the cases worth looking at were the
  // ones that looked broken. The 88% escape hatch below it dropped the label
  // entirely past that point, which is a third behavior for one row.
  //
  // Four fixed columns instead, so nothing inside them depends on the split:
  // the caption, this side's share, the bar, the other side's share. The two
  // teams are named once in a header row over their own columns rather than
  // four times down the block.
  const bar = (cap, x, y) => {
    if (x == null || y == null) return '';
    const w = Math.max(0, Math.min(100, Math.round(x)));
    return '<div class="pubrow"><span class="eyebrow">' + cap + '</span>'
      + '<span class="num pubrow__a">' + x.toFixed(0) + '%</span>'
      + '<div class="bar" role="img" aria-label="' + cap + ': ' + esc(a.side)
      + ' ' + w + ' percent, ' + esc(b.side) + ' ' + (100 - w) + ' percent">'
      + '<span class="h" style="width:' + w + '%"></span>'
      + '<span class="a" style="width:' + (100 - w) + '%"></span>'
      + '</div>'
      + '<span class="num pubrow__b">' + y.toFixed(0) + '%</span></div>';
  };
  const names = (a.tickets != null || a.money != null)
    ? '<div class="pubrow pubrow--names"><span></span>'
      + '<span class="pubrow__a">' + esc(a.side) + '</span><span></span>'
      + '<span class="pubrow__b">' + esc(b.side) + '</span></div>'
    : '';
  // WHICH SIDE IS CARRYING THE BIGGER BETS, said as a comparison rather than
  // as a gap in percentage points. "5pp" is a unit a reader has to be taught;
  // "bigger bets are landing on ARI" is a sentence they already have.
  const cands = [a, b].filter(x => x.tickets != null && x.money != null);
  const bigger = cands.filter(x => has(x.ratio) && x.ratio >= V3RATIO_SMALL)
                      .sort((x, y) => y.ratio - x.ratio)[0];
  const who = bigger || cands.filter(
    x => has(x.gap) && x.gap >= V3GAP_SMALL)[0];
  return '<div class="pub">'
    + '<div class="pub__h"><span class="eyebrow">' + esc(label) + '</span>'
    + (note ? '<span class="sub">' + esc(note) + '</span>' : '') + '</div>'
    + names
    + bar('Bets', a.tickets, b.tickets)
    + bar('Money', a.money, b.money)
    + (who
       ? '<p class="help" style="margin-top:6px">Bigger bets are landing on '
         + '<b style="color:var(--ink)">' + esc(who.side) + '</b>: '
         + who.tickets.toFixed(0) + '% of the bets but '
         + who.money.toFixed(0) + '% of the money'
         + (has(who.ratio) && who.ratio >= V3RATIO_SMALL
            ? ', which is about ' + who.ratio.toFixed(1)
              + ' times the average bet on the other side.' : '.')
         + '</p>'
       : '')
    + (move ? '<p class="help" style="margin-top:4px">' + move + '</p>' : '')
    + '</div>';
}

//: Half a point and a point read as words; anything else is a number.
function v3Pts(n) {
  const a = Math.abs(n);
  return a === 0.5 ? 'half a point' : a === 1 ? 'a point' : a + ' points';
}

//: A home-signed spread as a sentence. `-8.5` is the HOME team laying 8.5.
function v3SpreadTxt(v, c) {
  if (!has(v)) return '';
  if (v === 0) return 'pick ’em';
  return (v < 0 ? c.home : c.away) + ' by ' + Math.abs(v);
}

function v3PublicMoney(gid) {
  const sp = v3Splits(gid);
  const pub = ((DATA.games || {}).public || {})[gid];
  const L = ((DATA.games || {}).lines || {})[gid] || {};
  const c = (v3GameSet().cards || []).filter(x => x.game_id === gid)[0] || {};
  if (!sp && !pub) {
    // NOTHING AT ALL FOR AN ID THAT NAMES NO GAME. "Not captured for this
    // week" is an answer about a real fixture; on an unknown id it reads as
    // a feed being down.
    if (!c.home) return '';
    return '<div class="card"><div class="eyebrow">Where the money is</div>'
      + '<p class="lede" style="font-size:15px;line-height:20px;margin-top:6px">'
      + 'Not captured for this week. Run the public-money script and it will '
      + 'appear here.</p></div>';
  }

  // WHAT THE NUMBER MOVED TO, AND WHICH WAY. Said as the two numbers and a
  // direction, because "+1.0pp" is a unit a reader has to be taught and
  // "opened at SF by 8.5, now SF by 7.5" is one they already have.
  const moveSpread = () => {
    const x = L.spreads;
    if (!x || !has(x.open) || !has(x.now)) return '';
    if (!has(x.move) || Math.abs(x.move) < 0.25)
      return 'It opened at ' + esc(v3SpreadTxt(x.open, c))
        + ' and has not moved.';
    return 'Opened at ' + esc(v3SpreadTxt(x.open, c)) + ', now '
      + esc(v3SpreadTxt(x.now, c)) + ' — ' + v3Pts(x.move)
      + ' toward ' + esc(x.move < 0 ? c.home : c.away) + '.';
  };
  const moveTotal = () => {
    const x = L.totals;
    if (!x || !has(x.open) || !has(x.now)) return '';
    if (!has(x.move) || Math.abs(x.move) < 0.25)
      return 'It opened at ' + x.open + ' and has not moved.';
    return 'Opened at ' + x.open + ', now ' + x.now + ' — '
      + v3Pts(x.move) + ' ' + (x.move > 0 ? 'higher, toward the Over.'
                                          : 'lower, toward the Under.');
  };
  // THE MONEYLINE HAS NO NUMBER TO MOVE, only a price, so it is read as the
  // chance that price implies. A side going -142 to -130 and one going +120
  // to +110 have moved by different amounts in the same direction, and only
  // the probability says which is bigger.
  const moveWin = () => {
    const x = L.h2h, oo = x && x.open_odds, no = x && x.now_odds;
    if (!oo || !no || !has(oo[0]) || !has(no[0]) || !has(oo[1]) || !has(no[1]))
      return '';
    // INDEX 0 IS HOME AND 1 IS AWAY, which is the order
    // `public_money.line_view` builds the pair in. Read the other way round
    // this named the opponent on every game in the season, and it named it
    // confidently: ATL at NO in week 4 took 87% of the moneyline money on
    // ATL, ATL shortened from +114 to +100, the spread moved a point toward
    // ATL — and the panel said NO was the side getting more expensive, under
    // bars that said the opposite.
    const d = (1 / amToDec(no[0]) - 1 / amToDec(oo[0])) * 100;
    const i = d > 0 ? 0 : 1;
    const team = d > 0 ? c.home : c.away;
    // THROUGH `american`, like every other price on the site. Printed raw, a
    // +114 underdog reads as "114" — no sign, and a reader who assumes the
    // minus everybody else omits gets the direction backwards too.
    const px = v => esc(v3Dash(american(v)));
    if (Math.abs(d) < 1)
      return 'The price opened at ' + px(oo[0]) + ' on '
        + esc(c.home) + ' and has barely moved.';
    return esc(team) + ' opened at ' + px(oo[i]) + ' and is now '
      + px(no[i]) + ' \u2014 more expensive to back than it was.';
  };

  // THE HEADER AND THE SENTENCE UNDER IT NAME THE SAME NUMBER. The note used
  // to come from the card, which is The Odds API's main line, while the move
  // underneath came from this feed's consensus — two definitions of "the
  // current spread" a few pixels apart, and on ATL at NO they disagreed by a
  // full point: the header said NO by 2.5 directly above "now NO by 1.5".
  // The feed wins where it has a number, because it is the one the sentence
  // is about; the card is the fallback.
  const nowPt = (k, fb) => {
    const v = (L[k] || {}).now;
    return has(v) ? v : fb;
  };
  const blocks = sp
    ? [v3MoneyBlock('Who wins', 'straight up, no points', sp.moneyline,
                    moveWin()),
       v3MoneyBlock('The spread',
                    v3SpreadTxt(nowPt('spreads', c.spread), c),
                    sp.spread, moveSpread()),
       v3MoneyBlock('Total points',
                    has(nowPt('totals', c.total))
                      ? 'over or under ' + nowPt('totals', c.total) : '',
                    sp.total, moveTotal())].join('')
    : '';
  if (!blocks) return '';

  // THE OTHER BOOK, ONLY WHERE IT DISAGREES. Two ticket counts for the same
  // market, drawn as two sets of bars, is a reader asking which one is right.
  // A different customer base leaning the other way is worth a line; the same
  // number twice is not.
  const other = [];
  if (pub) {
    [['spread', 'spreads', 'the spread'],
     ['total', 'totals', 'the total']].forEach(k => {
      const mine = ((sp[k[0]] || {}).sides || [])[0];
      const them = ((pub[k[1]] || {}).sides || []).filter(
        x => mine && x.side === mine.side)[0];
      if (mine && them && has(mine.tickets) && has(them.pct)
          && Math.abs(mine.tickets - them.pct) >= 10) {
        other.push(esc(mine.side) + ' on ' + k[2] + ' ('
                   + them.pct.toFixed(0) + '% against '
                   + mine.tickets.toFixed(0) + '%)');
      }
    });
  }

  // THE DATA FIRST, THE LESSON UNDER IT. This card opened with two sentences
  // about what bets and money are before showing either — a paragraph every
  // reader scrolls past from their second visit on. The distinction still has
  // to be made, so it is made below, with the rest of the explanation, behind
  // one line.
  return '<div class="card"><div class="name">Where the money is</div>'
    // THREE SELF-CONTAINED BLOCKS, which on a wide screen is three screens
    // of scrolling to compare two of them. `cols2` stacks below 900px and
    // pairs above it, so the phone is unchanged and the desktop shows the
    // spread beside the total.
    + '<div class="cols2">' + blocks + '</div>'
    + v3Fold('What these shares mean',
        '<p class="help">How many <b>bets</b> are on each side, and how much '
        + 'of the <b>money</b> \u2014 they are different things: a side can be '
        + 'the popular pick and still hold less of the cash.</p>'
        + '<p class="help">A sportsbook nudges these numbers to keep the '
        + 'amount bet on each side roughly even. When the number moves toward '
        + 'a team, backing that team has got more expensive \u2014 usually '
        + 'because bets have been arriving on it. A number that has not moved '
        + 'means the two sides are close to balanced.</p>'
        + '<p class="help">Shares are Action Network\u2019s, which publishes '
        + 'bets and money on all three markets.'
        + (other.length
           ? ' Sportsbook Review\u2019s customers lean the other way on '
             + other.join(' and ') + '.'
           : '')
        + ' <b>None of this is a tip.</b> A crowd being on one side is not '
        + 'evidence it is wrong, and whether the bigger money is the smarter '
        + 'money is exactly what this project has not measured \u2014 the '
        + 'split archive began on 25 September.</p>')
    + '</div>';
}

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

function v3GameMoney(row) {
  const sides = v3SharpSides(row && row.gameId);
  if (!sides.length) return null;
  const top = sides[0];
  // Whose side the money is on matters more than that it is there. A player
  // whose own team is carrying it is a different read from one facing it.
  const mine = row.team && top.side === row.team;
  const facing = row.team && !mine && top.market !== 'Total';
  return { side: top.side, ratio: top.ratio, market: top.market,
           mine: !!mine, facing: !!facing };
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
      : '<button class="gstep" data-v3gamestep="' + esc(cards[j].game_id)
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

// THREE SOURCES, ONE ROW EACH, RATHER THAN THE SAME THREE TWICE.
//
// This was two stacked blocks: three labeled win bars, then three boxes
// carrying the same three sources' projected scores. Six blocks for three
// facts, a screen and a half on a phone before anything new, and comparing
// the model to the book meant scrolling between two groups that were already
// in the same order.
//
// One row per source instead, carrying everything that source says. The
// comparison runs down a column, and it surfaces what the split layout hid:
// on PIT at CLE the blend's win number is the book's to the point — the model
// has not earned the right to move it — which took two bars a screen apart to
// notice.
//
// ONE SIDE FOR THE WHOLE COLUMN. Naming each row's own favorite would put
// "PIT 58%" above "CLE 51%" and ask the reader to flip one of them in their
// head before comparing. The book's favorite names the column, every row
// reports that side, and the score cell still names its own leader because
// that is where a disagreement between the three belongs.
function v3Projection(c) {
  const aw = v3AdjWin(c);
  const rows = [];
  if (has(c.win_home)) rows.push(['Sportsbooks', c.win_home, null,
                                  c.spread, c.total]);
  if (has(c.model_win_home))
    rows.push(['Our model', c.model_win_home, c.model_win_n,
               c.model_spread, c.model_total]);
  // ADJUSTED: the fitted blend of the two above it. The weight comes from
  // `game_blend`, swept over 1,904 walk-forward games rather than chosen, and
  // it is small — which is the useful part. It says how far the model has
  // earned the right to move the book.
  if (aw != null) rows.push(['Adjusted', aw, null,
                             (c.blend || {}).spread, (c.blend || {}).total]);
  if (!rows.length) return '';

  // Whose number the win column is. The book's lean where there is one, the
  // model's where there is not, so the column has a subject either way.
  const base = has(c.win_home) ? c.win_home : rows[0][1];
  const homeSide = base >= 0.5;
  const side = homeSide ? c.home : c.away;

  const cell = (r) => {
    const w = homeSide ? r[1] : 1 - r[1];
    const pct = Math.round(w * 100);
    // A SCORE IS STILL A SCORE. Same derivation as the boxes this replaces:
    // the total split by the spread, one decimal, because rounding turned a
    // 0.6-point model margin into a projected tie.
    const sp = r[3], tot = r[4];
    let score = '', sub = '';
    if (has(sp) && has(tot)) {
      const hh = tot / 2 - sp / 2, aa = tot / 2 + sp / 2;
      const lead = hh >= aa ? c.home : c.away;
      score = esc(lead) + ' ' + Math.max(hh, aa).toFixed(1) + '\u2013'
        + Math.min(hh, aa).toFixed(1);
      sub = 'by ' + Math.abs(sp) + ' \u00b7 ' + tot + ' pts';
    }
    return '<div class="proj__r' + (r[0] === 'Adjusted' ? ' proj__r--adj' : '')
      + '">'
      + '<div class="proj__s"><span class="eyebrow">' + esc(r[0]) + '</span>'
      + (r[2] ? '<span class="sub">from ' + r[2] + ' past games</span>' : '')
      + '</div>'
      + '<div class="proj__w"><b class="num">' + pct + '%</b></div>'
      // THE BAR IS THE COLUMN THAT STRETCHES. Everything else in the row is
      // sized to its text, so on a desktop the extra width went into the gap
      // between the label and the numbers and left them jammed at the right
      // edge. The bar is the one thing here that gets better with width.
      + '<span class="proj__bar" role="img" aria-label="' + esc(side) + ' '
      + pct + ' percent"><i style="width:' + pct + '%"></i></span>'
      + '<div class="proj__p">'
      + (score ? '<b class="num">' + score + '</b>' : '<b>\u2014</b>')
      + (sub ? '<span class="sub num">' + sub + '</span>' : '')
      + '</div></div>';
  };

  // THE OTHER SIDE OF THE PROJECTION, BESIDE IT.
  //
  // A point estimate is the whole headline and the distribution is a tab
  // away. On 25 September Atlanta won at Green Bay by 21 as a road dog: the
  // page said "GB 23.8-22.2" and every number looked wrong, while the same
  // build had an outright Atlanta win at 28.5% — not a long shot, and a
  // number nobody saw without changing tabs. Said here, a projection reads as
  // the middle of a distribution rather than as a forecast.
  const u = c.unfold;
  const note = (u && !u.thin && u.headline)
    ? '<p class="help" style="margin-top:10px">A projection is the middle of a '
      + 'range, not a call. In ' + u.n + ' games priced like this one, '
      + esc(u.dog) + ' won outright <b>'
      + u.headline.upset.pct.toFixed(0) + '%</b> of the time and '
      + u.headline.one_score.pct.toFixed(0) + '% finished within one score.</p>'
    : '';
  return '<div class="proj">'
    + '<div class="proj__r proj__r--h"><span></span>'
    + '<span class="proj__w">' + esc(side) + ' win</span><span></span>'
    + '<span class="proj__p">projected score</span></div>'
    + rows.map(cell).join('')
    + '</div>' + note;
}

// WHAT MIGHT HAPPEN, WHAT HAS BEEN HAPPENING, AND WHAT THE MODEL NOTICED.
//
// Recent form sits in the middle of those three on purpose: the unfold above
// it is a distribution over this game, the notes below it are commentary, and
// ten weeks of scores against what each week was priced for is the evidence
// between them. It is also the reason the notes are worth reading — a note
// about a team that has beaten its number five weeks running reads
// differently from the same note in the abstract.
// HOW THIS ONE GOES, UNDER THE EVIDENCE FOR IT.
//
// LAST ON THE TAB, not first. The unfold, the form and the notes above it are
// the facts; this is the reading of them, and a reading printed before its
// evidence asks to be taken on the writer's word. Scrolled to, it is the
// summary of everything already on screen.
//
// EVERY NUMBER IN IT WAS COMPUTED BEFORE THE TEXT WAS WRITTEN, and the
// scoreline beneath is rendered here from `story.scoreline` rather than from
// the prose — so the figure a reader quotes is the one the Odds tab shows,
// not one a sentence happened to contain. `game_story` has the long version,
// including the four claims the first real story got wrong and the checks
// that now reject them.
function v3Story(gid) {
  const s = (DATA.stories || {})[gid];
  if (!s || !(s.paras || []).length) return '';
  const sc = s.scoreline;
  // A PREVIEW OF A PLAYED GAME IS NOT A PREVIEW, AND IT SAYS SO.
  //
  // `story_freeze` keeps the text a game kicked off with and never writes
  // another, so what is on screen after a final IS what was said beforehand.
  // Printed under the same heading it had on Saturday it would read as a
  // forecast of a result the reader already knows — the same trap the Odds
  // tab avoids by letting the result lead and the projection become what was
  // said. This is that sentence for the words.
  const done = !!s.frozen;
  // A TEMPLATE STORY IS NOT A WRITTEN ONE AND DOES NOT PRETEND TO BE. With no
  // key, no network, or prose that failed a check, the page is plainer — the
  // standard `game_notes` sets — and the label is how a reader can tell.
  const tag = s.written ? ''
    : '<p class="help" style="margin-top:0">Built from the figures below '
      + 'rather than written up.</p>';
  return '<div class="card st">'
    + '<h2 class="h1 st__h">'
    + (done ? 'What we said beforehand' : 'How this one goes') + '</h2>' + tag
    + s.paras.map(p => '<p class="st__p">' + esc(p) + '</p>').join('')
    + (sc && has(sc.away_pts) && has(sc.home_pts)
       ? '<div class="st__n"><span class="eyebrow">'
         + (done ? 'The number we had' : 'Our number') + '</span>'
         + '<b class="num">' + esc(sc.away) + ' ' + sc.away_pts.toFixed(1)
         + ' – ' + esc(sc.home) + ' ' + sc.home_pts.toFixed(1) + '</b>'
         + '</div>'
       : '')
    + '<p class="help">'
    + (done
       ? 'Written before kickoff and kept exactly as it was. It is not '
         + 'rewritten once a game has been played, so this is what the board '
         + 'actually said rather than a version improved by knowing the '
         + 'result.'
       : 'Written from this week’s numbers. Every figure in it was '
         + 'computed first and checked against the facts it came from — '
         + 'the wording is all that is written, and a projection is the '
         + 'middle of a range rather than a call.')
    + '</p></div>';
}

function v3GameNotes(c, gid, cats, shown) {
  if (!shown.length) {
    return v3Unfold() + v3TeamForm(c)
      + '<div class="card"><p class="lede" style="font-size:15px">'
      + 'Nothing in this game disagrees with the market enough to be worth a '
      + 'note. That is a real answer, not a missing one.</p></div>'
      + v3Story(gid);
  }
  const pills = cats.map(k => '<button class="cat" data-v3cat="' + esc(k)
    + '" aria-pressed="' + (V.cat === k) + '">'
    + esc(k === 'all' ? 'All' : k) + '</button>').join('');
  return v3Unfold()
    + v3TeamForm(c)
    + '<h2 class="h1" style="font-size:22px;line-height:28px;margin-top:20px">'
    + 'What our AI noticed</h2>'
    + '<p class="help">Written from this week’s prices and our model’s '
    + 'numbers. Every figure below is computed; only the wording is written.</p>'
    + '<div class="cats">' + pills + '</div>'
    + shown.map(v3Note).join('')
    + '<p class="help" style="margin-top:12px">These notes explain the game. '
    + 'They do not tell you what to bet.</p>'
    + v3Story(gid);
}

// HOW THE GAME MAY UNFOLD, as a partition that adds to 100%.
//
// Counted, not reasoned: every row is real games hung at this spread and
// total, grouped by how they finished. Overlapping scenarios — "one-score
// 50%, shootout 31%, upset 28%" — read as a ranking and cannot be one,
// because they add to more than everything that can happen and nothing on
// screen says which of them overlap. This column adds up.
function v3UnfoldGrid(u) {
  const cells = u.cells || [];
  const by = {};
  let most = 0;
  cells.forEach(x => {
    by[x.band + '|' + x.side] = x;
    if (x.pct > most) most = x.pct;
  });
  // A band with no cells at all is left out rather than drawn empty: it is a
  // result that did not happen once in the comparable games, and a row of two
  // zeroes reads as a missing number.
  const rows = (u.bands || []).filter(
    b => by[b.key + '|over'] || by[b.key + '|under']);
  if (rows.length < 2) return '';
  const pct = x => (x ? x.pct : 0);
  const cell = x => {
    const v = pct(x);
    // Shaded by size, so the grid has a shape as well as numbers. The floor
    // keeps a 1% cell legible rather than invisible.
    const a = most > 0 ? Math.max(0.06, v / most * 0.45) : 0;
    // AN OVERLAY RATHER THAN A MIXED COLOR. A tint needs the accent at a
    // fraction, and neither `rgba()` on a hex custom property nor
    // `color-mix()` can be relied on here, so the accent is a layer at an
    // opacity and the number sits above it.
    return '<span class="ugrid__c' + (v ? '' : ' ugrid__c--0') + '"'
      + (x ? ' title="' + esc(x.label) + ' \u2014 ' + v.toFixed(1)
             + '%" aria-label="' + esc(x.label) + ', ' + v.toFixed(1) + '%"'
           : ' aria-label="did not happen once"')
      + '><i style="opacity:' + a.toFixed(2) + '"></i><b>'
      + (v ? v.toFixed(0) + '%' : '\u2013') + '</b></span>';
  };
  let cu = 0, co = 0;
  rows.forEach(b => {
    cu += pct(by[b.key + '|under']);
    co += pct(by[b.key + '|over']);
  });
  return '<div class="ugrid">'
    + '<span></span><span class="ugrid__h">Low</span>'
    + '<span class="ugrid__h">High</span><span class="ugrid__h">All</span>'
    + rows.map(b => {
        const un = by[b.key + '|under'], ov = by[b.key + '|over'];
        return '<span class="ugrid__r" title="' + esc(b.short) + '">'
          + esc(b.short) + '</span>' + cell(un) + cell(ov)
          + '<span class="ugrid__t">' + (pct(un) + pct(ov)).toFixed(0)
          + '%</span>';
      }).join('')
    + '<span class="ugrid__r" style="color:var(--mut)">All</span>'
    + '<span class="ugrid__t" style="text-align:center">' + cu.toFixed(0)
    + '%</span><span class="ugrid__t" style="text-align:center">'
    + co.toFixed(0) + '%</span><span class="ugrid__t">'
    + (cu + co).toFixed(0) + '%</span>'
    + '<span class="ugrid__f"><span>Rows: how it ends.</span>'
    + '<span>Columns: scoring against the total.</span></span>'
    + '</div>';
}

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
    + '</div>'
    // A GRID, BECAUSE THE PARTITION IS TWO QUESTIONS AND WAS DRAWN AS ONE.
    //
    // Nine bars in a column read as a ranking of nine unrelated scenarios.
    // They are not: they are how the game ends crossed with how much scoring
    // there is, and every cell is one answer to each. The grid says that once
    // in its headers where a list spelled it out nine times, and it makes the
    // margins visible -- a row total is "how it ends" whatever the scoring, a
    // column total is over against under whatever the result.
    //
    // ROW ORDER COMES FROM THE PAYLOAD, not from here. See
    // `score_dist.unfold`: a band added there would otherwise land wherever
    // this guessed, or nowhere.
    + v3UnfoldGrid(u)
    + '<p class="help" style="margin-top:8px">These are every way the '
    + 'game can go, so the whole grid adds to 100.</p></div>';
}

function v3Note(n) {
  const figs = (n.stats || []).map(s =>
    '<div class="fig"><b class="num">' + esc(s.v) + '</b><span>' + esc(s.l)
    + '</span></div>').join('');
  // `context` before the rest: a coaching note that renders unlabeled reads
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
    // THE QUESTION MOST PEOPLE CAME TO ASK, one tap and answered by the
    // model rather than from the page: the three markets read together, with
    // our number against the market's on each. The canned chips beside it
    // are instant and free; this one costs a round trip, so it is marked as
    // the one that thinks.
    + '<div class="qs"><button class="q q--ask" data-v3askdefault="'
    + esc(gid) + '"' + (V.asking ? ' disabled' : '') + '>'
    + esc(V3ASK_DEFAULT) + '</button>'
    + (qs.length ? qs.map((q, i) =>
        '<button class="q" data-v3ask="' + i + '">' + esc(q.q) + '</button>')
      .join('') : '')
    + '</div>'
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

//: THE DEFAULT QUESTION. Phrased as the reader would ask it and as the thing
//: the page is for: the spread, the moneyline and the total, read together,
//: with our model's number against the market's on each.
const V3ASK_DEFAULT = 'Read the spread, moneyline and total for me \u2014 '
  + 'what does the data say, and where does our model disagree?';

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
  // THE SAME GREEN LINE THE BOARD CARRIES, counted over THIS GAME's picks.
  //
  // The board's number is the whole market; a game screen reading the whole
  // market's number under this game's rows would be quoting a statistic about
  // somewhere else. `rowsFor` keys the game as `gameId`, and `v3Same` is what
  // every other filter on this screen compares with.
  const body = v3MarketControls(V.week == null
      ? v3ClvNote(rowsFor(V.market, null).filter(
          r => r.priced && !r.blocked && v3Same(r.gameId, gid)),
          'of this game\u2019s picks on this market')
      : '')
    + '<div class="list" id="v3rows">' + v3Rows() + '</div>';
  V.game = prev;
  // No preamble. "Every priced player in this game, on the market you pick"
  // described the screen to someone already looking at it, and it sat between
  // two pinned bars and the rows — the one place on the page that cannot
  // afford a sentence.
  return body;
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
// SECTIONS GET RENAMED AND SAVED STATE DOES NOT. `V.gameTab` is persisted
// and put in the URL, so a name this app no longer renders has to resolve to
// the section that absorbed it rather than falling through to Notes — which
// is silent, and reads as "the link forgot where I was".
function v3GTab(v) {
  // SCORE IS NOT A TAB ANY MORE, it is what the Odds tab becomes once the
  // game has been played. It was dead weight for six days a week: a tab that
  // said nothing until Sunday night, sitting second in a strip of five.
  // Three names have meant it over time and all three land on Odds.
  if (v === 'bets' || v === 'score' || v === 'out') return 'odds';
  // The injury report is part of the matchup now: it is the question of who
  // is on the field, which is what the efficiency table is comparing.
  if (v === 'inj') return 'edge';
  return v;
}

// THE MARKET, IN ONE PLACE.
//
// The price, the two win bars read against it, the public's tickets and the
// sharp dollars used to sit ABOVE the section bar as a permanent preamble.
// That put roughly a screen and a half between opening a game and reaching
// any of its sections, and the section bar — the thing that moves you around
// the game — was the one control you had to scroll to find.
//
// They belong together and they are one answer: what this game is priced at
// and who is backing it. As a section they are a tap away instead of a
// scroll, and every other section starts at the top of the page.
// WHAT THE TWO TEAMS HAVE DONE, AGAINST WHAT WAS EXPECTED OF THEM.
//
// A ROW OF SCORES CANNOT BE READ. 27, 14, 31, 20 invites an average — "this
// offense scores 23" — and the four games were played against four defenses
// the market priced differently. So the bar is the score and the tick across
// it is that week's implied team total: height says how much, the tick says
// whether it was more or less than the game was priced for. `team_form` has
// the long version, and `player_history` makes the identical argument one
// level down about a prop line that moves week to week.
//
// ONE SCALE FOR ALL FOUR ROWS. Two teams, points scored and points allowed,
// every bar measured against the same maximum — otherwise the taller of two
// offenses is whichever one the renderer scaled more generously.
function v3TeamForm(c) {
  const TF = DATA.teamform || {};
  const teams = TF.teams || {};
  const sides = [[c.away, teams[c.away]], [c.home, teams[c.home]]]
    .filter(x => x[1] && x[1].length);
  if (!sides.length) return '';
  // r = [season, week, opponent, home, pf, pa, exp_for, exp_against]
  let top = 0;
  sides.forEach(s => s[1].forEach(r => {
    [r[4], r[5], r[6], r[7]].forEach(v => { if (has(v) && v > top) top = v; });
  }));
  if (!top) return '';
  // Headroom, so the tallest bar is not flush with the ceiling and a tick at
  // the maximum is still drawn inside the box.
  top = top * 1.1;

  const season = sides[0][1][0] ? sides[0][1][0][0] : null;
  const barRow = (rows, val, exp) => {
    // Oldest on the left, which is the direction the axis underneath reads.
    const cells = rows.slice().reverse().map((r, i, arr) => {
      const v = val(r), e = exp(r);
      const over = has(v) && has(e) && v > e;
      const prev = season != null && r[0] < season;
      // The season changes BETWEEN two bars, so the divider belongs to the
      // first bar of the newer season rather than to either season's edge.
      const brk = i > 0 && arr[i - 1][0] !== r[0];
      const h = has(v) ? Math.max(2, Math.round(v / top * 100)) : 0;
      const t = has(e) ? Math.max(0, Math.min(100, Math.round(e / top * 100)))
        : null;
      const ttl = v3PastWhen(r) + ' ' + (r[3] ? 'vs ' : 'at ') + r[2]
        + ' \u2014 ' + v + (has(e) ? ', expected ' + e : '');
      return '<span class="tf__s' + (brk ? ' tf__s--brk' : '') + '" title="'
        + esc(ttl) + '">'
        + '<i class="tf__b' + (over ? ' tf__b--over' : '')
        + (prev ? ' tf__b--prev' : '') + '" style="height:' + h + '%"></i>'
        + (t == null ? ''
           : '<i class="tf__t" style="bottom:' + t + '%"></i>')
        + '</span>';
    }).join('');
    return '<div class="tf__c">' + cells + '</div>';
  };

  const count = (rows, val, exp) => rows.filter(
    r => has(val(r)) && has(exp(r)) && val(r) > exp(r)).length;
  const pf = r => r[4], pa = r => r[5], ef = r => r[6], ea = r => r[7];

  // SIX ALIGNED COLUMNS, NOT ONE PACKED STRING.
  //
  // This read "30-27 · expected 19.5-23" on one right-aligned line, which is
  // four numbers in two en-dashed pairs where the dash means "against" in one
  // and nothing in the other — and the reader has to remember that the first
  // of each pair is this team. Columns say it instead: what they scored, what
  // was expected of them, what they allowed, what was expected of that. The
  // numbers line up down the page, so a week that broke pattern is visible
  // without reading any of them.
  const cell = (v, exp) => {
    const over = has(v) && has(exp) && v > exp;
    return '<span class="tf__n num' + (over ? ' tf__n--over' : '') + '">'
      + (has(v) ? v : '\u2014') + '</span>'
      + '<span class="tf__x num">' + (has(exp) ? exp.toFixed(1) : '\u2014')
      + '</span>';
  };
  const block = (name, rows) => {
    const list = '<div class="tf__hd">'
      + '<span></span><span></span>'
      + '<span class="tf__n">scored</span><span class="tf__x">exp</span>'
      + '<span class="tf__n">allowed</span><span class="tf__x">exp</span>'
      + '</div>'
      + rows.map(r =>
        '<div class="tf__row' + (r[0] < season ? ' tf__row--prev' : '') + '">'
        + '<span class="pl__w">' + esc(v3PastWhen(r)) + '</span>'
        + '<span class="pl__o">' + (r[3] ? 'vs ' : 'at ') + esc(r[2])
        + '</span>' + cell(r[4], r[6]) + cell(r[5], r[7])
        + '</div>').join('');
    return '<div class="tf__t2">'
      + '<div class="pl__h">' + esc(name) + ', last ' + rows.length + '</div>'
      + '<p class="pl__s">Scored more than expected in '
      + count(rows, pf, ef) + ' of ' + rows.length + ' \u00b7 allowed more in '
      + count(rows, pa, ea) + '</p>'
      + '<div class="tf__r"><span class="tf__l">scored</span>'
      + barRow(rows, pf, ef) + '</div>'
      + '<div class="tf__r"><span class="tf__l">allowed</span>'
      + barRow(rows, pa, ea) + '</div>'
      + '<div class="pl__ax"><span>' + esc(v3PastWhen(rows[rows.length - 1]))
      + '</span><span>' + esc(v3PastWhen(rows[0])) + '</span></div>'
      + '<div class="pl__l">' + list + '</div></div>';
  };

  return '<div class="card tf">'
    + '<div class="pl__h">Recent form</div>'
    + '<div class="pl__lg">'
    + '<span class="pl__k"><i class="pl__sw pl__sw--up"></i>more than the game '
    + 'was priced for</span>'
    + '<span class="pl__k"><i class="pl__sw"></i>less</span>'
    + '<span class="pl__k"><i class="tf__sw"></i>what was expected that week'
    + '</span></div>'
    + sides.map(s => block(s[0], s[1])).join('')
    // SAID, NOT SUBTRACTED. A pick-six is seven points the offense did not
    // score and seven the total settled on, and this panel sits beside a
    // total. Taking them out would leave a number matching neither.
    + '<p class="help">Final scores, so defensive and special-teams '
    + 'touchdowns are in them. The expected line is the market\u2019s implied '
    + 'total for that team that week \u2014 the posted total and spread, '
    + 'split.</p></div>';
}

//: A row is
//:   [season, week, opp, home, pf, pa, sp, tot,
//:    ats, ou, ml, spOdds, spOddsOpp, overOdds, underOdds, mlOdds, mlOddsOpp]
//: and the first six are `team_form`'s, in order, so `v3PastWhen` and the
//: vs/at reading are the ones the player panel already uses.
const V3TL = { when: 0, wk: 1, opp: 2, home: 3, pf: 4, pa: 5, sp: 6, tot: 7 };

//: Which field holds each market's result, and the two prices for backing the
//: team and for fading it. Written down once: three markets each needing a
//: result column and a pair of prices is exactly the shape that gets
//: transposed by hand on the fourth copy.
//:
//: ON THE TOTAL, "back" IS THE OVER AND "fade" IS THE UNDER — the two sides
//: of the game rather than of the team, which is why its words differ.
const V3TLM = {
  ats: { res: 8, back: 11, fade: 12, w: 'covered', l: 'did not cover',
         bk: t => t, fd: t => t + '’s opponent' },
  ou: { res: 9, back: 13, fade: 14, w: 'over', l: 'under',
        bk: () => 'the over', fd: () => 'the under' },
  ml: { res: 10, back: 15, fade: 16, w: 'won', l: 'lost',
        bk: t => t, fd: t => t + '’s opponent' },
};

//: A team's rows: the whole record once fetched and opened, the inlined ten
//: otherwise. The fallback is deliberate and so is saying it out loud — see
//: the error branch in `v3TeamLines`, which is the same sentence the player
//: panel prints when a fetch fails and the panel redraws identically.
function v3TLRows(team) {
  const T = DATA.teamlines || {};
  const full = V3CACHE['tlines'] && V3CACHE['tlines'].teams
    && V3CACHE['tlines'].teams[team];
  if (V.tlAll === team && full) return { rows: full, all: true };
  const rows = (T.teams || {})[team];
  return rows && rows.length ? { rows: rows, all: false } : null;
}

// FETCHED, NOT INLINED, PAST THE FIRST TEN. All 32 teams back to 2015 is
// 413 KB; ten games each is 22 KB and answers "is this number high for them".
// One file rather than one per team: a reader who opens one side of a game
// opens the other in the next breath, and 413 KB once beats 32 round trips.
function v3TLFetch(then) {
  const k = 'tlines';
  if (V3CACHE[k]) { then(V3CACHE[k]); return; }
  const fail = why => { V3CACHE[k] = { error: why }; then(V3CACHE[k]); };
  let p;
  try { p = fetch('data/tlines.json'); } catch (e) { fail(String(e)); return; }
  p.then(r => {
    if (!r.ok) { fail('the server answered ' + r.status); return; }
    return r.json().then(o => { V3CACHE[k] = { teams: o || {} };
                                then(V3CACHE[k]); });
  }).catch(e => fail(String(e)));
}

//: A market's record over a window: wins, losses, and pushes counted out
//: rather than folded into either. A game that lands on the number returns
//: the stake, and there are 156 ATS and 56 total pushes in the archive — a
//: record that called those losses would be wrong in the direction that
//: flatters a reader into a bet.
function v3TLRec(rows, mk) {
  const f = V3TLM[mk].res;
  let w = 0, l = 0, p = 0;
  rows.forEach(r => {
    const v = r[f];
    if (!has(v)) return;
    if (v > 0) w++; else if (v < 0) l++; else p++;
  });
  return { w: w, l: l, p: p, n: w + l + p };
}

//: Which way the window ran, which is the side the money question is about.
//: A team that has failed to cover six of ten is not asking what backing it
//: would have returned. Ties go to backing the team, because that is the
//: reading someone opening a team's own panel came for.
function v3TLBack(rows, mk) {
  const rec = v3TLRec(rows, mk);
  return rec.l > rec.w ? 'fade' : 'back';
}

// WHAT BACKING THAT SIDE EVERY ONE OF THOSE GAMES WOULD HAVE RETURNED.
//
// $100 a game at the price the schedule feed holds for the side the record
// ran. BOTH SIDES ARE REAL QUOTES, which is the one way this panel is better
// off than the player one: the player archive holds the Yes and the Over and
// nothing else, so "what if you had faded him" is a question it cannot
// answer, while the schedule posts both moneylines and both spread prices.
//
// A PUSH IS NOT A LOSS. The stake comes back, so it is set aside and counted
// out loud — the same distinction `v3PastMoney` makes for a week a player did
// not take the field.
//
// NOT A FORECAST, and this one has a measurement behind the warning rather
// than only a small sample: forty-nine spread splits were tested together
// over 504 team-weeks and not one clears the vig at the lower bound of its
// interval. Ten games is far short of saying anything at all.
function v3TLMoney(rows, mk, dir) {
  const m = V3TLM[mk];
  const f = m.res, pf = dir === 'fade' ? m.fade : m.back;
  const profit = o => o > 0 ? o : 10000 / -o;
  let money = 0, bets = 0, pushes = 0, won = 0, unpriced = 0;
  rows.forEach(r => {
    const res = r[f], odds = r[pf];
    if (!has(res)) return;
    if (!has(odds)) { unpriced++; return; }
    if (res === 0) { pushes++; return; }
    // Fading wins exactly when backing loses. There is no third outcome once
    // the push is set aside, so this is the whole of it.
    const hit = dir === 'fade' ? res < 0 : res > 0;
    bets++;
    if (hit) { won++; money += profit(odds); } else { money -= 100; }
  });
  return { money: money, bets: bets, pushes: pushes, won: won,
           unpriced: unpriced };
}

// WHAT THE RECORDS ARE WORTH, COUNTED FROM THE ANGLES BOARD RATHER THAN
// WRITTEN DOWN.
//
// The first draft of this said "forty-nine spread patterns were measured and
// the best covers 52.6%", lifted from a comment. The payload said 86 patterns
// and a best lower bound of 57.0% — the comment had been true of a smaller
// list and the sentence it became was wrong twice over. So the numbers come
// from `DATA.angles`, which is the same measurement the Angles page reports,
// and they cannot go stale while the page says them.
//
// `clears` IS BOTH CONDITIONS, which is the part worth saying out loud: the
// lower bound beats break-even AND the split has at least `tint_min` games.
// An 86-game row clearing at the lower bound is a wide interval that happens
// to start high, and `angles.TINT_MIN_GAMES` has the long version.
function v3TLCaveat() {
  const A = DATA.angles || {};
  const rows = A.rows || [];
  const be = has(A.break_even) ? (A.break_even * 100).toFixed(1) + '%' : null;
  const clear = rows.filter(r => (r.all || {}).clears).length;
  // Absent rather than invented: a build with no angles block gets the
  // sentence that does not depend on one.
  const ats = (rows.length && be)
    ? '<p>These are results, not a model. This project measures spread '
      + 'patterns the same way on the Angles page — ' + rows.length
      + ' of them, graded together — and break-even at −110 is '
      + be + '. '
      + (clear
         ? '<b>' + clear + ' of them clears it</b> at the lower bound of its '
           + 'interval on a large enough sample.'
         : '<b>Not one of them clears it</b> at the lower bound of its '
           + 'interval on a large enough sample.')
      + ' A team that has covered six of ten has done that, and nothing '
      + 'follows from it about the game above.</p>'
    : '<p>These are results, not a model. A team that has covered six of ten '
      + 'has done that, and nothing follows from it about the game above.</p>';
  return ats
    // WHOSE LINE IT IS, without a figure that goes stale every Sunday. The
    // measurement behind this sentence is in `team_lines`, dated, where it is
    // context for whoever changes the code rather than a claim on a page.
    + '<p>The line is the one the schedule feed records for each game: one '
    + 'source’s number, close to the market’s close rather than at '
    + 'it, and not the best price you could have taken. The spread is from '
    + 'that team’s own side, so a favorite reads as a minus.</p>'
    + '<p>A game that lands exactly on the number is a push: the stake comes '
    + 'back, so it is counted separately rather than as a loss. The dollar '
    + 'figures are $100 a game on the side the record ran, at that archived '
    + 'price — and ten games cannot separate a team from the hold.</p>';
}

// WHAT THESE TWO TEAMS HAVE DONE AGAINST THE THREE NUMBERS ON THIS GAME.
//
// `team_form` beside it is the same question asked of the scoreboard: what
// they scored, against what was expected. This is the question asked of the
// markets a reader is actually looking at on the Odds tab — did the spread,
// the total and the moneyline come in — and `player_history` is the same
// panel one level down, for a prop line that moves week to week.
//
// THE RECORD FIRST, AND THE MONEY ON THE SIDE THE RECORD RAN. A record with
// no price beside it invites the arithmetic to be done badly in someone's
// head; the same record at the archived price is the honest version of the
// number they were going to reach for anyway.
//
// NO COLOR THAT MEANS GOOD on the result marks. The project has measured
// every ATS split it could build and not one clears the hold, so a green
// "covered" would be the page implying a finding it does not have. The marks
// read as what happened, and the fold under them says what that is worth.
function v3TeamLines(c, gid) {
  const T = DATA.teamlines || {};
  const meta = T.markets || [];
  if (!meta.length) return '';
  const sides = [c.away, c.home].map(t => [t, v3TLRows(t)])
    .filter(x => x[1]);
  if (!sides.length) return '';

  // ONE WINDOW FOR BOTH TEAMS AND ALL THREE MARKETS. The point of the panel
  // is comparing two teams, and reading one over five games and the other
  // over ten would make the comparison the renderer's choice rather than the
  // reader's.
  const least = Math.min.apply(null, sides.map(x => x[1].rows.length));
  const opts = [3, 5, 10].filter(n => n < least).map(n => [String(n), 'last ' + n]);
  opts.push(['all', 'all ' + least]);
  const pick = opts.length > 1
    ? '<div class="seg seg--' + opts.length + ' pl__seg">'
      + v3Seg('v3tln', opts,
              (V.tlN && V.tlN < least) ? String(V.tlN) : 'all') + '</div>'
    : '';

  const table = (team, got) => {
    const every = got.rows;
    const win = (V.tlN && V.tlN < every.length) ? V.tlN : every.length;
    const rows = every.slice(0, win);
    // THE SUMMARY BEFORE THE ROWS, because the record is what the reader came
    // for and ten rows of line-and-result is what backs it up. The same
    // ordering the player panel settled on: the sentence leads, the evidence
    // follows.
    const head = meta.map(m => {
      const rec = v3TLRec(rows, m.key);
      if (!rec.n) return '';
      const dir = v3TLBack(rows, m.key);
      const mm = V3TLM[m.key];
      const money = v3TLMoney(rows, m.key, dir);
      const side = dir === 'fade' ? mm.fd(team) : mm.bk(team);
      const fig = money.bets
        ? '<b class="' + (money.money >= 0 ? 'pos' : 'neg') + '">'
          + (money.money >= 0 ? '+$' : '−$')
          + Math.abs(money.money).toFixed(0) + '</b> on ' + esc(side)
          + ', ' + money.won + ' of ' + money.bets
          + (money.pushes ? ' · ' + money.pushes + ' push'
             + (money.pushes > 1 ? 'es' : '') : '')
          + (money.unpriced ? ' · ' + money.unpriced
             + ' with no price' : '')
        : '<span class="dim">no price archived</span>';
      return '<div class="tl__sr">'
        + '<span class="tl__sl">' + esc(m.label) + '</span>'
        + '<b class="tl__sv num">' + rec.w + '–' + rec.l
        + (rec.p ? '–' + rec.p : '') + '</b>'
        + '<span class="tl__sm">' + fig + '</span></div>';
    }).join('');

    const body = rows.map(r => {
      const mark = m => {
        const v = r[V3TLM[m].res];
        if (!has(v)) return '<span class="tl__m tl__m--na">—</span>';
        const t = v > 0 ? V3TLM[m].w : v < 0 ? V3TLM[m].l : 'push';
        const ch = v === 0 ? 'P'
          : m === 'ou' ? (v > 0 ? 'O' : 'U')
          : m === 'ats' ? (v > 0 ? 'C' : '–')
          : (v > 0 ? 'W' : 'L');
        return '<span class="tl__m tl__m--' + (v > 0 ? 'y' : v < 0 ? 'n' : 'p')
          + '" title="' + esc(t) + '">' + ch + '</span>';
      };
      const sp = r[V3TL.sp], tot = r[V3TL.tot];
      return '<div class="tl__r">'
        + '<span class="tl__w">' + esc(v3PastWhen(r)) + '</span>'
        + '<span class="tl__o">' + (r[V3TL.home] ? 'vs ' : 'at ')
        + esc(r[V3TL.opp]) + '</span>'
        + '<span class="tl__n num">'
        + (has(sp) ? v3Dash(sp > 0 ? '-' + sp : '+' + Math.abs(sp)) : '—')
        + '<span class="tl__t">' + (has(tot) ? tot : '—') + '</span>'
        + '</span>'
        + '<span class="tl__p num">' + r[V3TL.pf] + '–' + r[V3TL.pa]
        + '</span>'
        + '<span class="tl__ms">' + mark('ats') + mark('ou') + mark('ml')
        + '</span></div>';
    }).join('');

    const more = (!got.all && T.inline && every.length >= T.inline)
      ? '<button class="pl__more" data-v3tlall="' + esc(team) + '">'
        + 'Show every game</button>' : '';
    const ck = V3CACHE['tlines'];
    const err = (V.tlAll === team && ck && ck.error)
      ? '<p class="pl__e">Every game did not load — ' + esc(ck.error)
        + '. These are the last ' + rows.length + '.</p>' : '';

    return '<div class="tl">'
      + '<div class="pl__h">' + esc(team) + ', last ' + rows.length + '</div>'
      + '<div class="tl__s">' + head + '</div>'
      + '<div class="tl__hd"><span class="tl__w">when</span>'
      + '<span class="tl__o">opp</span>'
      + '<span class="tl__n">line<span class="tl__t">total</span></span>'
      + '<span class="tl__p">score</span>'
      + '<span class="tl__ms">ats&nbsp;o/u&nbsp;ml</span></div>'
      + '<div class="tl__b">' + body + '</div>' + err + more + '</div>';
  };

  // THE SPREAD IS PRINTED FROM THE TEAM'S OWN SIDE, which is the only reading
  // that makes a column of them comparable: "-2.5" in CLE's table means CLE
  // were favored by 2.5 that week, whoever was at home. `team_games` does
  // that flip once, in Python, where a test holds the sign.
  return '<div class="card tl__c">'
    + '<h3 class="tl__t3">Against the number</h3>'
    + '<p class="help">What each side has done against the three markets on '
    + 'this game. The spread is from that team’s own perspective, so '
    + '−2.5 means they were favored by 2.5 that week.</p>'
    + pick
    + '<div class="tl__g">' + sides.map(x => table(x[0], x[1])).join('')
    + '</div>'
    + v3Fold('What these records are and are not', v3TLCaveat())
    + '</div>';
}

// WHAT THE GAME IS PRICED AT, AND THEN WHAT IT CAME TO.
//
// Score used to be a tab of its own, second in the strip, saying nothing from
// Tuesday to Sunday evening. A played game is not a different subject from
// the same game unplayed — it is the same subject with an answer — so the
// result leads this tab once there is one and the projection sits under it as
// what was said beforehand. The frozen projection is what makes that honest:
// `projection_freeze` serves the number the board carried before kickoff
// rather than one recomputed afterwards.
function v3GameOdds(c, gid) {
  // NOT ONLY A FINAL SCORE. `v3GameScores` draws the margin bands and where
  // the line cuts them, which is a question about a game that has not been
  // played yet — gating the whole block on a result took the distribution off
  // the page for six days a week. It is always here; what moves is where.
  //
  // Before kickoff the price leads and the distribution sits under it. After,
  // the result leads and the projection becomes what was said beforehand —
  // which `projection_freeze` makes honest by serving the number the board
  // actually carried rather than one recomputed after the fact.
  const played = has(c.final_home) && has(c.final_away);
  const outcome = v3ThinNote(c) + v3GameScores(c) + v3GameBets(gid);
  return (played ? outcome : '')
    + '<div class="card">'
    + '<div class="vs"><div><b>' + esc(c.away) + '</b><div class="sub">away</div>'
    + '</div><div style="text-align:center;color:var(--mut2)">at</div>'
    + '<div style="text-align:right"><b>' + esc(c.home) + '</b>'
    + '<div class="sub">home</div></div></div>'
    + '<div class="sub" style="margin-top:8px">' + esc(v3Kick(c)) + '</div>'
    + v3Projection(c) + '</div>'
    + v3PublicMoney(gid)
    + (played ? '' : outcome)
    // AFTER THE PRICE AND THE PUBLIC, BEFORE NOTHING ELSE. The tab answers
    // "what is this game priced at and who is backing it"; what the two sides
    // have done against those same three numbers is the next question anyone
    // asks, and it was previously answerable only by leaving the game.
    + v3TeamLines(c, gid);
}

// WHAT THE SPLITS SAY, AND WHAT THEY ARE WORTH.
//
// An angle is "teams off a 20+ loss are 7-1 against the spread this year" —
// the kind of line that travels. That one is true and it is eight games.
// Over 504 team-weeks since 2015 the same split covers 52.6%, break-even at
// -110 is 52.38%, and the interval runs 48.2% to 56.9%. Forty-nine angles
// were measured together and NOT ONE clears at the lower bound.
//
// THE SAME TABLE AS THE BOARD, for the same reason it is a table there: the
// median game carries seventeen of these, which is past the length anyone
// reads top to bottom, and the whole use of it is comparing one column down
// the list. Sorting and the team filter have their own state, so ordering
// this card does not reorder the Angles page behind it.
//
// KEYED BY GAME. This used to look up the two teams and print whatever came
// back, which was a week-3 answer under a week-4 fixture: ARI came off a
// 24-point loss in week 3 and its week-4 card said "ARI · Off a 20+ loss"
// when ARI's last result was a six-point loss.
function v3Angles(c) {
  const A = DATA.angles || {};
  const mine = (A.week || {})[c.game_id] || [];
  if (!mine.length || !(A.rows || []).length) return '';
  const be = has(A.break_even) ? A.break_even : 0.5238;
  const yr = v3AngleYears();
  const from = yr.from;
  const by = {};
  (A.rows || []).forEach(r => { by[r.id] = r; });

  const team = (V.gaTeam === c.away || V.gaTeam === c.home) ? V.gaTeam : 'all';
  // LEAGUE-WIDE, OR THIS ROW'S OWN TEAM. Every row already names a team, so
  // the scope needs no second picker: on `team` each row reads its own club's
  // record. That is the only reading under which a whole-game condition says
  // anything — `On grass` is 1605-1605 for the league and 67-72 for SF.
  const own = V.gaScope === 'team';
  // NO SEARCH HERE, unlike the board. Fifty-five rows need one; a median of
  // seventeen, already split three ways by the team control, does not -- and
  // the box cost the pinned bar a third of its height for a filter nobody
  // reached for.
  const picked = mine
    .filter(pair => by[pair[1]] && (team === 'all' || pair[0] === team));
  // THE KINDS THIS GAME CARRIES, in the order the payload names them rather
  // than the order they turn up in: `rows` is sorted by percentage, so a list
  // collected here would reshuffle itself whenever a record moved. Narrowed
  // by the team control first, so every option offered has rows behind it,
  // and offered at all only where there are two to choose between.
  const seen = {};
  picked.forEach(pair => {
    const k = by[pair[1]].cat;
    if (k) seen[k] = 1;
  });
  const kinds = (A.cats || []).filter(k => seen[k]);
  // SELF-HEALING, NOT RESET. Walking to a game that carries none of the
  // chosen kind shows everything for that game and leaves the choice alone,
  // so walking back restores it.
  const cat = kinds.indexOf(V.gaCat) >= 0 ? V.gaCat : 'all';
  const rows = picked
    .filter(pair => cat === 'all' || by[pair[1]].cat === cat)
    .map(pair => ({
      team: pair[0], r: by[pair[1]],
      run: v3AngleSince(by[pair[1]], from, be, own ? pair[0] : ''),
      base: v3AngleBase(by[pair[1]], from, own ? pair[0] : ''),
      season: own ? v3AngleTeamYear(by[pair[1]], pair[0], DATA.season)
                  : by[pair[1]].season,
    }));
  // A FILTER THAT MATCHES NOTHING STILL LEAVES ITS CONTROLS ON SCREEN.
  // Returning nothing here took the search box with it, so a typo emptied the
  // section and there was no way left to clear it. The card is only absent
  // when the GAME carries no patterns, which is checked above.
  if (!rows.length && team === 'all' && cat === 'all') return '';

  const pct = d => (d && d.n) ? d.pct : -1;
  const SORTS = {
    season: o => pct(o.season),
    all: o => pct(o.run),
    name: o => o.team + ' ' + o.r.label,
  };
  const key = SORTS[V.gaSort] ? V.gaSort : 'season';
  const dir = V.gaDesc ? -1 : 1;
  rows.sort((a, b) => {
    const x = SORTS[key](a), y = SORTS[key](b);
    if (x < y) return -dir;
    if (x > y) return dir;
    return (a.team + a.r.label) < (b.team + b.r.label) ? -1 : 1;
  });

  const arrow = k => (key === k ? (V.gaDesc ? ' \u2193' : ' \u2191') : '');
  const head = (k, label) => '<button class="ahead" data-v3gasort="'
    + k + '" aria-pressed="' + (key === k) + '">' + label + arrow(k)
    + '</button>';
  const games = A.games || {};

  return '<h2 class="h1" style="font-size:19px;line-height:24px;'
    + 'margin-top:20px">Angles on this game</h2>'
    + '<p class="help">How often teams in each of these situations have '
    + 'COVERED THE CLOSING SPREAD \u2014 not how often they won. Tap one for '
    + 'this season\u2019s games.</p>'
    // WHOSE ANGLES. Both sides' splits in one list read as one team's until
    // you notice the prefix, and on a median seventeen rows that is a lot of
    // noticing. Three buttons answer it once.
    // PINNED, LIKE EVERY OTHER FILTER IN THE APP, and scoped so it lets go.
    //
    // The median game carries seventeen patterns, which is more than a screen,
    // so the controls that narrow them were above all of it. `.pbar` already
    // sticks at `--gtabs-h`, under the section bar rather than over it.
    //
    // WRAPPED WITH THE TABLE IT FILTERS. A sticky element stays stuck for as
    // long as its PARENT is on screen, so pinned to the tab itself this bar
    // would ride over the closing cards below the table, still offering to
    // filter a list that had scrolled away.
    + '<div class="gasec">'
    + '<div class="pbar">'
    + '<div class="pbar__row">'
    + '<div class="seg seg--3" style="flex:1">'
    + v3Seg('v3gateam', [['all', 'Both'], [c.away, c.away], [c.home, c.home]],
            team)
    + '</div></div>'
    // ROW TWO IS THE SAME ON BOTH SURFACES -- which kind, then whose record,
    // in that order. The board carries the identical pair, so a reader who
    // has learned one page has learned the other. Row one is where they
    // differ, and only because thirty-two teams need a list where two need
    // three buttons.
    + '<div class="pbar__row pbar__row--two">'
    + (kinds.length < 2 ? '' : '<div class="picker mxsel">'
       + '<select data-v3gacat aria-label="Filter by kind">'
       + ['all'].concat(kinds).map(k => '<option value="' + esc(k) + '"'
           + (k === cat ? ' selected' : '') + '>'
           + (k === 'all' ? 'All kinds' : esc(k)) + '</option>').join('')
       + '</select></div>')
    // WHOSE RECORD THE TWO COLUMNS ARE. League-wide is the bigger sample and
    // the default; one team's own games is the only reading under which a
    // whole-game condition can say anything, and it is one tap away.
    + '<div class="seg seg--2" style="flex:1">'
    + v3Seg('v3gascope', [['league', 'League'], ['team', 'Team']],
            own ? 'team' : 'league')
    + '</div></div>'
    // THE SAME SLIDER AS THE BOARD, and the same state behind it. The long
    // run and the expectation beside it both move with it, on the league
    // reading and the team reading alike.
    + v3YearSlider(yr.first, yr.last, from)
    + '</div>'
    + '<div class="card" style="margin-top:10px">'
    + '<div class="arow arow--h">'
    + head('name', 'Pattern')
    + head('season', 'Yr ATS')
    + head('all', '\u2019' + String(from).slice(2) + '+ ATS')
    + '</div>'
    + (rows.length ? '' : '<p class="help" style="padding:12px 0">'
       + (cat === 'all' ? esc(team) + ' carries none of these.'
          : 'Nothing under ' + esc(cat)
            + (team === 'all' ? '' : ' for ' + esc(team)) + ' on this game.')
       + '</p>')
    + rows.map(o => {
        const r = o.r, a = o.run;
        // COLOR TRACKS THE LONG RUN ONLY, and only once the interval clears.
        // Tinting a hot season would put green on eight games, which is the
        // exact reading the card exists to prevent.
        const good = a && a.clears;
        const id = o.team + ':' + r.id;
        const open = V.gaOpen === id;
        return '<button class="arow' + (open ? ' arow--on' : '')
          + '" data-v3gangle="' + esc(id) + '" aria-expanded="' + open + '">'
          + '<span class="arow__l"><b>' + esc(o.team) + '</b> '
          + esc(r.label) + (own ? '' : v3WholeTag(r)) + v3MirrorTag(r, by)
          + v3SurpriseTag(o.season, a) + '</span>'
          + '<span class="num"><b>' + v3AnglePct(o.season) + '</b>'
          + '<i>' + v3AngleRec(o.season) + '</i></span>'
          + '<span class="num' + (good ? ' good' : '') + '"><b>'
          + v3AnglePct(a) + '</b><i>' + v3AngleRec(a) + '</i></span>'
          + '</button>'
          + (open ? v3AngleGames(r, games, own ? o.team : '',
                                 v3BaseLine(a, o.base)
                                 + v3MirrorLine(r, by,
                                     x => v3AngleSince(x, from, be,
                                                       own ? o.team : ''),
                                     own ? o.team : '')) : '');
      }).join('')
    // THE DENOMINATOR IS THE FINDING, so it is on the card rather than in a
    // footnote. Without it a reader sees four splits and no idea that
    // forty-five others were measured at the same time and said nothing.
    // THE DENOMINATOR STAYS ON THE CARD. How many angles were measured
    // together is the finding, not a footnote, so it is the one line that
    // does not fold; everything under it explains how to read the table and
    // folds away until asked for.
    + '<p class="help" style="margin-top:10px">Break-even at \u2212110 is '
    + (be * 100).toFixed(2) + '%. Of the ' + (A.rows || []).length
    + ' angles measured together, <b style="color:var(--ink)">'
    + (A.rows || []).filter(
        r => r.all && v3Clears(r.all.lo, r.all.n, be)).length
    + '</b> clear it once the interval is taken into account. A season\u2019s '
    + 'worth of any one of these is a handful of games.</p>'
    + v3Fold('How to read this table', v3BaseNote()) + '</div></div>';
}

// WHO IS ON THE FIELD, THEN HOW THE UNITS COMPARE.
//
// Injuries were a section of their own, which split one question across two
// tabs: an efficiency table is a claim about personnel, and reading it
// without knowing who is out is reading last month's teams. Injuries come
// first because they are the part that changed this week — the EPA rates
// under them are a season's worth and move slowly.
function v3GameMatchup(c) {
  return v3Matchup(c);
}

function v3GameOutcome(c, gid) {
  return v3ThinNote(c) + v3GameScores(c) + v3GameBets(gid);
}

// A THIN WINDOW IS A CAVEAT, NOT A REFUSAL.
//
// Both tables below used to withhold themselves under `MIN_COMPARABLES`,
// which left the Outcome tab as two cards explaining twice why it was empty.
// That is the wrong trade: the distribution is still THIS game's comparables,
// and 52 games is thin for a percentage while being perfectly informative
// about shape — which side wins, by roughly how much, whether the total sits
// high or low. Withholding it gave the reader nothing to be careful WITH.
//
// So it is stated once, above both tables, in the terms that actually matter:
// the ordering holds and the percentages are soft. Once, because `summary`
// and `ladders` read the SAME comparable set, so the two notices were the
// same fact printed twice.
function v3ThinNote(c) {
  const d = c && c.scores;
  if (!d || !d.n || !d.thin) return '';
  return '<div class="thin" role="note"><b>Thin sample \u00b7 ' + d.n
    + ' past games</b>'
    + '<span>Not many games have been priced near this spread and total'
    + (has(d.min_n) ? ', against the ' + d.min_n + ' this normally wants' : '')
    + '. The shape below is real \u2014 it is what those games did \u2014 but '
    + 'a single extra game moves the percentages by a point or more, so read '
    + 'them as a lean rather than a price.</span></div>';
}

// WHERE THE LINE FALLS, which nine bars in a column cannot show.
//
// The list under this one carries every band's percentage and its interval.
// What a list cannot carry is the one number that decides a spread bet -- the
// margin the favorite has to beat -- because that lands INSIDE a band about as
// often as on a boundary: a 6.5 line cuts "by 4-7" a quarter of the way in.
// So the rule is drawn over the bars, not between them.
//
// COLORED BY WHICH SIDE OF THE LINE A BAND IS ON, not by which team. The list
// already colors by team, and it is not the question a line answers.
function v3MarginStrip(d, spread, model, mg) {
  const bands = (d.margins || []).filter(m => m.n);
  if (bands.length < 3 || !has(spread)) return '';
  let max = 0;
  bands.forEach(m => { if (m.pct > max) max = m.pct; });
  if (!(max > 0)) return '';
  // `spread` is the HOME number, so a favored home team carries a negative
  // one and has to win by more than this to cover.
  const t = -spread;
  // AN OPEN-ENDED BAND NEEDS A NOMINAL FAR EDGE, and only so a rule can be
  // placed inside it: a 17-point line falls in "by 15+", which has no upper
  // bound. Fourteen further points is the width of every closed band but the
  // tie and the three-pointer.
  const lo = m => (m.mlo == null ? m.mhi - 14 : m.mlo);
  const hi = m => (m.mhi == null ? m.mlo + 14 : m.mhi);
  const state = m => {
    if (m.mlo != null && m.mlo > t) return 'yes';
    if (m.mhi != null && m.mhi <= t) return 'no';
    return 'split';
  };
  // THE MARGIN FALLS LEFT TO RIGHT, which is the order the list is already in:
  // the home team's biggest wins first, the away team's last. So a threshold
  // sits this far from the left edge of the band that holds it.
  const at = x => {
    for (let i = 0; i < bands.length; i++) {
      const a = lo(bands[i]), b = hi(bands[i]);
      if (x >= a - 0.5 && x <= b + 0.5) {
        const f = Math.max(0, Math.min(1, (b - x + 0.5) / (b - a + 1)));
        return (i + f) / bands.length * 100;
      }
    }
    return x > hi(bands[0]) ? 0 : 100;
  };
  const rule = (x, cls, lab) => '<span class="mstrip__l' + cls + '" style="'
    + 'left:' + at(x).toFixed(2) + '%"><b>' + esc(lab) + '</b></span>';
  const hit = m => (mg != null && (m.mlo != null || m.mhi != null)
    && (m.mlo == null || mg >= m.mlo) && (m.mhi == null || mg <= m.mhi));
  const short = m => (m.mlo === 0 && m.mhi === 0) ? 'T'
    : String(m.band).replace(/^.* by /, '');
  // THE SMALLEST MARGIN THAT BEATS THE LINE, and it is not always a win.
  // Written as "has to win by -2 or more" the first time, on a home team
  // getting 2.5 points, which is a team that covers by LOSING narrowly. Three
  // cases, and the middle one is real: at +0.5 a tie is enough.
  const need = Math.floor(t) + 1;
  const what = need > 0 ? 'has to win by ' + need + ' or more'
    : need === 0 ? 'only has to avoid losing'
    : 'can lose by up to ' + (-need) + ' and still beat it';
  // AND THE PUSH, on a whole-number line, because the stake comes back and
  // neither side of the picture is right about it.
  const push = (t % 1 !== 0) ? ''
    : (t === 0 ? ' A tie is a push.'
       : ' A ' + Math.abs(t) + '-point ' + (t > 0 ? 'win' : 'loss')
         + ' is a push.');
  // OUR OWN RULE ONLY WHERE IT WOULD BE LEGIBLE. Measured in the picture, not
  // in points: this game is -2.5 against our -3.1, six tenths of a point
  // apart and 2% of the width apart, so two rules and two labels would land
  // on top of each other and read as one.
  const gap = has(model) ? Math.abs(at(t) - at(-model)) : 0;
  return '<div class="mstrip">'
    + bands.map(m => '<span class="mstrip__c mstrip__c--'
        + (hit(m) ? 'hit' : state(m)) + '" title="' + esc(m.band) + ' \u2014 '
        + m.pct.toFixed(1) + '%"><i style="height:'
        + (m.pct / max * 100).toFixed(1) + '%"></i></span>').join('')
    + rule(t, '', 'line')
    + (gap >= 5 ? rule(-model, ' mstrip__l--us', 'ours') : '')
    + '</div>'
    + '<div class="mstrip__ax">'
    + bands.map(m => '<span>' + esc(short(m)) + '</span>').join('')
    + '</div>'
    + '<div class="mstrip__ends"><span>' + esc(d.home) + ' wins by more</span>'
    + '<span>' + esc(d.away) + ' wins by more</span></div>'
    + '<div class="mkey"><span><i style="background:var(--ours)"></i>'
    + esc(d.home) + ' covers</span>'
    + '<span><i style="background:var(--mut3)"></i>' + esc(d.home)
    + ' does not</span>'
    + (mg != null ? '<span><i style="background:var(--good)"></i>where this '
       + 'one finished</span>' : '') + '</div>'
    + '<p class="help" style="margin-top:8px">Each bar is how often games '
    + 'priced like this one finished that way. The solid line is the '
    + 'bookmaker\u2019s number: ' + esc(d.home) + ' ' + what
    + ', so bars to the left of the line are ' + esc(d.home)
    + ' beating the spread and bars to the right are not.' + push
    + (gap >= 5 ? ' The dashed line is where our own number would put it.'
       : '') + '</p>';
}

function v3GameScores(c) {
  const d = c && c.scores;
  if (!d || !d.n) {
    return '<div class="card"><p class="lede" style="font-size:15px">No line '
      + 'on this game yet, so there is nothing to compare it with.</p></div>';
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
  // WHERE OUR MODEL POINTS, WHICH IS NOT WHERE THE LIST IS CENTRED.
  //
  // The list is ordered by fit to the MARKET's spread and total, because the
  // market is measurably the better center: moving the kernel off it by the
  // point or so our blend typically differs costs top-1 1.37% -> 1.20%, and by
  // four points 1.37% -> 0.70%. Ordering by our own number would be flattering
  // and worse.
  //
  // So this marker will often sit low, and that is the information rather than
  // a contradiction — the distance between the market's favorite and ours is
  // the disagreement this whole site is about. It was labeled "nearest our
  // number" beside a list nobody had said was centered anywhere else, which
  // read as a bug.
  //
  // `spread` here is AWAY-positive, as `v3Compare` reads it.
  // Adjusted first, then the model, then the book — the same order of
  // preference the rest of the page uses.
  const pj = (has(c.blend && c.blend.spread) && has(c.blend && c.blend.total))
      ? [c.blend.total / 2 - c.blend.spread / 2, c.blend.total / 2 + c.blend.spread / 2]
    : (has(c.model_spread) && has(c.model_total))
      ? [c.model_total / 2 - c.model_spread / 2, c.model_total / 2 + c.model_spread / 2]
    : (has(c.spread) && has(c.total))
      ? [c.total / 2 - c.spread / 2, c.total / 2 + c.spread / 2] : null;
  const dist = x => pj ? Math.hypot(x.home - pj[0], x.away - pj[1]) : null;

  // LIKELIEST FIRST, WHICH IS THE RANK THE KERNEL PRODUCED.
  //
  // This was sorted by distance to our projected score for a while, and that
  // ordering is measurably the wrong way round: walk-forward over 2,416
  // games, the row nearest our number lands 0.58% of the time — 1 in 173 —
  // while the kernel's own first pick lands 1.37%, 1 in 73. Leading with the
  // nearest put a score less than half as likely at the top, and the footer's
  // "our best pick lands 1 in 70" described a row nobody could point at.
  //
  // Proximity to a point estimate is not the same question as how often a
  // scoreline happens: 23-20 can sit half a point from our number while the
  // kernel rates 20-23 higher because it has happened more often in games
  // priced like this one. The distance is still SHOWN on every row, because
  // it is worth knowing; it just no longer decides the order.
  const ordered = (d.scores || []).map((x, i) => ({ x: x, rank: i + 1 }));
  const scores = ordered.map(o => {
    const x = o.x;
    const dd = pj ? dist(x) : null;
    const landed = played && x.home === fh && x.away === fa;
    // ONCE THE GAME IS IN, THE TINT IS A RESULT RATHER THAN AN INTENTION.
    //
    // Before kickoff a tinted row is one we like. After it, the same tint
    // still said "we like this" about a game already decided, which is the
    // only section on the page that did not grade itself — the two headline
    // boxes turn green or red, the margin band marks the one that landed, and
    // this list carried yesterday's opinion in yesterday's color.
    //
    // EVERY ROW IS GRADED, not just the ones we leaned on. Sixteen scores
    // were put up and one of them happened; the other fifteen were wrong, and
    // showing them in the same neutral grey as a live board hid the thing the
    // list is worst at. On a played week this reads as the scoreboard it is.
    const missed = played && !landed;
    // COLOR, NOT A LABEL. The tint for "within a point of our number" is gone
    // with the ordering it belonged to: it marked proximity, which turned out
    // to be a worse guide to the final than the rank beside it.
    return '<div class="srow' + (landed ? ' srow--on' : '')
      + (missed ? ' srow--miss' : '') + '">'
      + '<b class="num"><i class="srank">' + o.rank + '</i>'
      + esc(d.home) + ' ' + x.home
      + '\u2013' + x.away + ' ' + esc(d.away)
      + (landed ? ' \u00b7 this one' : '') + '</b>'
      // Only what belongs to THIS scoreline: how often it has happened, and
      // how far it sits from our number. The positional rate moved to the
      // footer, where it is true — `p` is the rate at a RANK, so beside "26
      // times" it read as a contradiction.
      + '<span class="sub num">' + (x.n ? x.n + ' times' : '')
      + (pj ? ' \u00b7 ' + dd.toFixed(1) + ' off' : '')
      + '</span></div>';
  }).join('');
  // A PLAYED GAME WITH NO GREEN ROW IS AMBIGUOUS otherwise: you cannot tell
  // whether the marking is broken or the final simply is not among the
  // sixteen — which is the common case, since a fifth of games finish on a
  // score nobody lists.
  const anyLanded = played && (d.scores || []).some(
    x => x.home === fh && x.away === fa);
  // THE SIDE WE LEAN, AND WHETHER THAT SIDE WAS RIGHT.
  //
  // These read as a grade and were not one. They said "IND won 38%" and went
  // red because Indianapolis lost — but 38% IS the call that Indianapolis
  // loses, so the box marked a correct read wrong. The over box had the same
  // fault pointing the other way: 46% with the game going over is a MISS,
  // and it went green. Both were coloring the outcome rather than the
  // prediction, which is the one thing a green-or-red box means.
  //
  // So each box states the side it favors. Under 50% for the home team is a
  // claim about the away team, and printing it as a home-team number asked
  // the reader to do the flip and then graded them on it.
  const hw = d.home_win.pct;
  const homeFav = hw >= 50;
  const winTeam = homeFav ? d.home : d.away;
  const winPct = homeFav ? hw : 100 - hw;
  // The interval belongs to the side being shown: the away band is the home
  // band mirrored, not the same two numbers under a different name.
  const winLo = homeFav ? d.home_win.lo : 100 - d.home_win.hi;
  const winHi = homeFav ? d.home_win.hi : 100 - d.home_win.lo;
  const tied = played && fh === fa;
  const winHit = played && !tied && (homeFav ? fh > fa : fa > fh);

  const overFav = d.over.pct >= 50;
  const totPct = overFav ? d.over.pct : 100 - d.over.pct;
  const totLo = overFav ? d.over.lo : 100 - d.over.hi;
  const totHi = overFav ? d.over.hi : 100 - d.over.lo;
  const finalTot = played ? fh + fa : null;
  const push = played && finalTot === d.total;
  const wentOver = played && finalTot > d.total;
  const totHit = played && !push && (overFav === wentOver);

  // A tie and a push are neither right nor wrong, so they are neither color.
  const wonTone = (!played || tied) ? '' : (winHit ? ' box--good' : ' box--bad');
  const overTone = (!played || push) ? '' : (totHit ? ' box--good' : ' box--bad');

  return '<div class="card"><div class="eyebrow">Based on</div>'
    + '<p class="lede" style="font-size:15px;line-height:20px;margin-top:4px">'
    + '<b>' + d.n + ' past games</b> hung within 2 points of this spread and '
    + '3.5 of this total. Not a simulation \u2014 what actually happened in '
    + 'them.</p>'
    // THE SCORES TABLE DOES NOT USE THAT SET, and saying "139 past games" above
    // a list whose rows read "of 2286" was two denominators in one card.
    + (d.scores_n && d.scores_n !== d.n
       ? '<p class="help">The exact-score list above is drawn from a wider net '
         + '\u2014 ' + d.scores_n + ' games \u2014 because a scoreline needs far '
         + 'more history behind it than a margin band does.</p>' : '')
    + '<div class="two" style="margin-top:12px">'
    + '<div class="box' + wonTone + '"><span class="eyebrow">' + esc(winTeam)
    + ' to win</span><b class="num">' + winPct.toFixed(0) + '%</b>'
    + '<span class="sub num">'
    + (played ? (tied ? 'it ended level'
                 : winHit ? esc(winTeam) + ' did' : esc(winTeam) + ' did not')
              : winLo.toFixed(0) + '\u2013' + winHi.toFixed(0) + '% range')
    + '</span></div>'
    + '<div class="box' + overTone + '"><span class="eyebrow">'
    + (overFav ? 'Over ' : 'Under ') + d.total + '</span>'
    + '<b class="num">' + totPct.toFixed(0) + '%</b>'
    + '<span class="sub num">'
    + (played ? 'finished ' + finalTot
                + (push ? ', push' : wentOver ? ', over' : ', under')
              : totLo.toFixed(0) + '\u2013' + totHi.toFixed(0) + '% range')
    + '</span></div></div>'
    + '<p class="help">Average result in those games: '
    + d.mean_total + ' total points, winner by '
    + Math.abs(d.mean_margin) + '.</p></div>'
    + '<h2 class="h1" style="font-size:19px;line-height:24px;margin-top:20px">'
    + 'How it finished</h2>'
    + '<div class="card">'
    + v3MarginStrip(d, c.spread, c.model_spread, played ? fh - fa : null)
    + margins + '</div>'
    + '<h2 class="h1" style="font-size:19px;line-height:24px;margin-top:20px">'
    + 'Likeliest exact scores</h2>'
    + '<div class="card">'
    + (pj ? '<div class="pub__h" style="margin-bottom:8px">'
            + '<span class="eyebrow">Our number</span> '
            + '<span class="sub num">' + esc(d.home) + ' ' + pj[0].toFixed(1)
            + '\u2013' + pj[1].toFixed(1) + ' ' + esc(d.away)
            + '</span></div>' : '')
    + scores
    // THE NUMBER THE OLD CARD HID. Eight rows of near-identical percentages
    // invited a reader to pick one; what they needed was that the whole list
    // is a long shot. Said first, in the biggest type on the card.
    + (has(d.scores_covered)
       ? '<div class="box" style="margin-top:12px">'
         + '<span class="eyebrow">These ' + (d.scores || []).length
         + ' put together</span><b class="num">'
         + d.scores_covered.toFixed(0) + '%</b>'
         + '<span class="sub">' + (100 - d.scores_covered).toFixed(0)
         + '% of games finish on a score nobody listed</span></div>' : '')
    // WHAT THE COLORS MEAN, IN THE TENSE THE GAME IS IN. Before kickoff they
    // are a call; after it they are a result, and one sentence cannot be both
    // without being wrong half the time.
    + (played
       ? '<p class="help" style="margin-top:10px">Likeliest first. Green is '
         + 'the score this game actually finished on'
         + (anyLanded ? '' : ', which is not on this list')
         + '. Every other one we put up was wrong.</p>'
       : '<p class="help" style="margin-top:10px">Likeliest first. The number '
         + 'on each row is its place in that order; the points beside it are '
         + 'how far the score sits from our projection, which is worth '
         + 'knowing and is NOT what the order is based on.</p>')
    + '<p class="help">Which sixteen appear is our call: real finals, weighted '
    + 'by how well each fits the market\u2019s spread and total, which predicts '
    + 'the final better than our own projection does. How often each has '
    + 'happened is beside it, so a close-but-rare score and a common-but-'
    + 'further one are both visible rather than settled for you.</p>'
    + '<p class="help">On the record our best pick lands about <b '
    + 'style="color:var(--ink)">1 in 70</b> and the rest about <b '
    + 'style="color:var(--ink)">1 in 180</b> \u2014 a rate per POSITION in our '
    + 'ranking, not per scoreline, which is why it is here and not on the '
    + 'rows.</p></div>';
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
  // WHAT THE TABLE IS FOR, SAID BEFORE THE TABLE.
  //
  // At the posted number the rate is 50% by construction — the book is
  // efficient, the median game sits 2.9pp off a coin flip and 50% is inside
  // the interval in seven games out of eight. So a reader who came for "is
  // this total high or low" got ten rows restating that more points are less
  // likely. The row worth reading is where OUR number falls, and the gap
  // between the two is the only thing here either of us is claiming.
  const gap = (mark, ours) => {
    if (mark == null || ours == null) return '';
    const dd = ours - mark;
    const at = r => r == null ? null : r.pct.toFixed(0) + '%';
    const find = v => (rowsOf || []).filter(
      r => Math.abs(r.line - v) < 0.26)[0];
    if (Math.abs(dd) < 0.25)
      return '<p class="help">Our number lands on the posted one, so there is '
        + 'nothing here to disagree about.</p>';
    return '<p class="help">Posted <b class="num">' + mark + '</b>, our number '
      + '<b class="num">' + ours.toFixed(1) + '</b> \u2014 we are '
      + Math.abs(dd).toFixed(1) + ' point' + (Math.abs(dd) >= 1.95 ? 's' : '')
      + ' ' + (dd > 0 ? 'higher' : 'lower') + '.</p>';
  };
  let rowsOf = null;
  const table = (title, note, rowsIn, mark, actual, ours) => {
    rowsOf = rowsIn;
    return '<h2 class="h1" style="font-size:19px;line-height:24px;margin-top:20px">'
    + esc(title) + '</h2>'
    + (note ? '<p class="help">' + note + '</p>' : '')
    + gap(mark, ours)
    + (actual != null
       ? '<p class="help"><b>Finished at ' + actual + '.</b> Green cleared, '
         + 'red did not.</p>' : '')
    + '<div class="card"><div class="ltab">'
    + '<div class="ltab__h"><span>Over</span><span>Hit</span>'
    + '<span>How often</span></div>'
    + rowsIn.map(r => {
        const on = mark != null && Math.abs(r.line - mark) < 0.01;
        // Our number is rounded to the nearest half when it becomes a rung,
        // so it is matched the same way rather than exactly.
        const mine = !on && ours != null
          && Math.abs(r.line - Math.round(ours * 2) / 2) < 0.01;
        const hit = actual == null ? null : actual > r.line;
        return '<div class="ltab__r' + (on ? ' ltab__r--on' : '')
          + (mine ? ' ltab__r--mine' : '')
          + (hit == null ? '' : hit ? ' ltab__r--hit' : ' ltab__r--miss')
          + '">'
          + '<span class="num">' + r.line + (on ? ' \u00b7 posted'
             : mine ? ' \u00b7 our number' : '')
          + '</span>'
          + '<span class="num">' + r.pct.toFixed(0) + '%</span>'
          + '<span>' + v3Mini(r.pct) + '<i class="num">' + r.n + ' of '
          + L.n + '</i></span></div>';
      }).join('')
    + '</div></div>';
  };

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
    + table('Total points', 'How often games priced like this one went over '
            + 'each number.',
            (L.total || {}).rows || [], (L.total || {}).posted, finalTotal,
            (L.total || {}).ours)
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
  // ONE LINE, AND THE NUMBER IS THE LINE.
  //
  // This ran five lines above every board: the count, then three seasons of
  // context, then what the number does and does not mean. All of it true, and
  // none of it changing between one board and the next — so it was a
  // paragraph of standing explanation charged to the top of a screen whose
  // job is to show players. The count is what moves, so the count stays here
  // and the explanation moved to "How to read a pick", which is where the
  // page already keeps what is true every week.
  //
  // "we rated above the open" stays. It is not padding, it is the condition
  // that defines the sample, and 77 of 115 without it is a different claim.
  //
  // AND IT IS CALLED OUT RATHER THAN SET IN THE HELP GREY. This is the one
  // edge the project has measured; printed in the same muted type as "pays if
  // the player scores a touchdown" it read as another line of instructions.
  return '<p class="clv"><b>' + c.toward + ' of ' + c.n + '</b> prices moved '
    + 'toward us \u2014 ' + esc(what) + ' we rated above the open.</p>';
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


// EVERY ANGLE, INCLUDING THE ONES THAT SAY NOTHING.
//
// The card on a game shows the two or three splits those teams carry. This is
// the whole board, and it exists because the denominator is the finding:
// twenty were measured together and a reader shown only the top few has no
// way to know that. With twenty splits at 95% confidence one is expected to
// look good by chance, so zero clearing is a clean null rather than a
// disappointing one.
//
// Sorted by the LONG RUN, not by this season. Sorting by the hot column would
// rebuild the thing this page is an answer to.
// Wilson, so a record computed on this side carries the same interval the
// measured one does. Without it, moving the start year would drop the column
// that says how much the number is worth.
function v3Wilson(k, n) {
  if (!n) return [0, 1];
  const z = 1.96, p = k / n, den = 1 + z * z / n;
  const c = (p + z * z / (2 * n)) / den;
  const h = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den;
  return [Math.max(0, c - h), Math.min(1, c + h)];
}

// WHICH BOARD HOLDS A FIXTURE, and whether it is the archived one.
//
// Decided by LOOKING FOR THE GAME, not by comparing week numbers. Two cases
// broke the arithmetic version. On a Monday, Sunday’s games belong to the
// week still in progress, so sending the reader to the archive found nothing
// — `games.past` does not hold the current week and will not until it
// closes. And next week’s fixtures are on the schedule but on no board at
// all, because their prices have not been captured, so a link to them landed
// on "that game is not on this week’s board".
//
// Returns null where nothing holds it, which is how the list knows not to
// make that row a button.
function v3AngleBoard(g) {
  const G = DATA.games || {};
  const id = g && g.gid;
  if (!id) return null;
  // The ARCHIVE IS ASKED FIRST, because it is keyed by this fixture's own
  // week and so cannot answer for a different game.
  const p = (G.past || {})[String(g && g.week)];
  if (p && (p.cards || []).some(c => c.game_id === id)) return { past: true };
  if ((G.cards || []).some(c => c.game_id === id)) return { past: false };
  return null;
}

// THE SHARED PARTS OF AN ANGLE, so the board and the game card cannot drift.
//
// Both draw the same rows from the same payload, and the first version of the
// game card had its own copy of the percentage, the record and the long run —
// three formatters that were already right twenty lines away, and the card
// quoted "since 2015" whatever the board's slider said.

//: TWO DECIMALS. Break-even is 52.38% and a column rounded to whole points
//: cannot show a row sitting either side of it.
const v3AnglePct = d => (d && d.n) ? (d.pct * 100).toFixed(2) + '%' : '\u2014';
const v3AngleRec = d => (d && d.n) ? d.w + '-' + d.l : '';

// Every season any angle has a record in, and the one the reader chose to
// count from. The range spans the archive rather than a year typed in here.
function v3AngleYears() {
  const splits = (DATA.angles || {}).splits || {};
  const yrs = {};
  Object.keys(splits).forEach(id => Object.keys(splits[id]).forEach(
    y => { yrs[y] = 1; }));
  const years = Object.keys(yrs).map(Number).sort((a, b) => a - b);
  const first = years.length ? years[0] : 2015;
  const last = years.length ? years[years.length - 1] : first;
  const from = (V.angleFrom && V.angleFrom >= first && V.angleFrom <= last)
    ? V.angleFrom : first;
  return { first: first, last: last, from: from };
}

// WHAT THE SPLIT'S OWN COMPOSITION ALREADY PREDICTS.
//
// Side and role are worth four points between them: road underdogs cover
// 52.07% and home favorites 47.93%, over 1,763 team-games each. So a split
// made mostly of favorites looks bad without saying anything, and one made of
// road dogs looks good for the same non-reason. Against a flat 50%, "Favored
// after being an underdog" reads as a five-point fade on a thousand games;
// against its own mix it is under two points and inside noise.
//
// Recomputed here rather than shipped as one number, because the start year
// and the team picker both change the population it has to answer for.
function v3AngleBase(r, from, team) {
  const B = (DATA.angles || {}).baseline || {};
  const mix = team ? ((B.team_mix || {})[team] || {})[r.id]
                   : (B.mix || {})[r.id];
  if (!mix) return null;
  const cells = B.cells || {};
  // The cell rates over the SAME span, so moving the slider moves both the
  // record and the thing it is being measured against.
  const w = [0, 0, 0, 0], n = [0, 0, 0, 0];
  Object.keys(cells).forEach(y => {
    if (Number(y) < from) return;
    V3CELLS.forEach((c, i) => {
      const v = cells[y][c];
      if (v) { w[i] += v[0]; n[i] += v[1]; }
    });
  });
  let num = 0, den = 0;
  Object.keys(mix).forEach(y => {
    if (Number(y) < from) return;
    V3CELLS.forEach((c, i) => {
      const k = mix[y][i];
      if (!k || !n[i]) return;
      num += (w[i] / n[i]) * k;
      den += k;
    });
  });
  return den ? { pct: num / den, n: den } : null;
}

// HOW FAR BACK TO COUNT, on both screens from one definition.
//
// Eleven seasons is a lot of football and the game has changed inside it, so
// a reader who only trusts the last five should be able to ask for the last
// five rather than take 2015 on faith. The board and a game's own card share
// `V.angleFrom`: how far back you trust is a view about football, not about
// which screen you happen to be on, and the column header names the year so
// the choice is never hidden.
function v3YearSlider(first, last, from) {
  if (!(last > first)) return '';
  return '<div class="yrs"><span class="eyebrow">Since</span>'
    + '<input type="range" data-v3anglefrom min="' + first + '" max="'
    + last + '" step="1" value="' + from + '" aria-label="Earliest season">'
    + '<b class="num" data-v3yrlab>' + from + '</b></div>';
}

//: Home or away, favored or not, in the order the payload packs them.
const V3CELLS = ['AD', 'AF', 'HD', 'HF'];

// WHAT "EXPECTED" MEANS, said once and in the same words on both screens.
function v3BaseNote() {
  return '<p class="help" style="margin-top:8px">Where a team plays and '
    + 'whether it is favored already decide a lot: a road underdog covers '
    + '<b style="color:var(--ink)">52.07%</b> of the time and a home favorite '
    + '<b style="color:var(--ink)">47.93%</b>, over 1,763 games each, whatever '
    + 'else is true of them. So a pattern made mostly of favorites looks bad '
    + 'without having done anything wrong. Open any row and it says what '
    + 'those particular games were going to do anyway.</p>'
    + '<p class="help" style="margin-top:8px">A row marked '
    + '<i class="tag tag--flat">unusual</i> is one whose record this season '
    + 'would turn up less than one time in twenty for that pattern. That is a '
    + 'remark about a small sample, not a signal \u2014 with '
    + ((DATA.angles || {}).rows || []).length + ' patterns on the board, two '
    + 'or three are marked by chance in a normal season.</p>'
    + '<p class="help" style="margin-top:8px">A rate turns '
    + '<b style="color:var(--good)">green</b> only when the bottom of its '
    + 'range clears ' + (((DATA.angles || {}).break_even || 0.5238) * 100)
      .toFixed(2) + '% <b style="color:var(--ink)">and</b> it has '
    + (((DATA.angles || {}).tint_min) || 300) + ' games or more behind it. '
    + 'On a hundred games a range runs twenty points wide, so one that starts '
    + 'high is a wide range rather than a finding.</p>';
}

// IS THIS SEASON UNUSUAL FOR THIS PATTERN?
//
// "Teams off a 20+ loss are 7-1 against the spread this year" is the line that
// started this board, and the board could not answer it: the season column
// printed 87.50% beside a long run of 53.13% and left the reader to judge
// whether eight games meant anything. They do not. At 53.13%, a record of 7-1
// or better turns up about one season in ten.
//
// So the two-sided binomial tail of this season's record against the
// pattern's OWN long-run rate, which is the one comparison a reader cannot do
// in their head. Computed iteratively rather than through factorials: n runs
// to ninety by January and `comb(90, 45)` is 10^26.
function v3Surprise(season, all) {
  if (!season || !season.n || !all || !all.n) return null;
  const p = all.pct, n = season.n, k = season.w;
  if (!(p > 0 && p < 1)) return null;
  const pmf = [];
  let v = Math.pow(1 - p, n);
  for (let i = 0; i <= n; i++) {
    pmf.push(v);
    v = v * ((n - i) / (i + 1)) * (p / (1 - p));
  }
  let lo = 0, hi = 0;
  for (let i = 0; i <= k; i++) lo += pmf[i];
  for (let i = k; i <= n; i++) hi += pmf[i];
  return Math.min(1, 2 * Math.min(lo, hi));
}

//: One season in twenty. With fifty-five patterns two or three are marked by
//: chance in a normal season, which the closing card says in the same breath.
const V3SURPRISE = 0.05;

// A NOTE, NOT A VERDICT. Beside the name rather than on the number, because
// `test_only_the_long_run_can_be_tinted` forbids coloring the season cell and
// is right to: green on eight games is the exact misreading this board exists
// to prevent. No color, no emphasis, and the word is "unusual" rather than
// "hot" -- "hot" reads as a tip.
function v3SurpriseTag(season, all) {
  const p = v3Surprise(season, all);
  return (p != null && p < V3SURPRISE)
    ? ' <i class="tag tag--flat" title="This season\u2019s record would turn '
      + 'up less than one time in twenty for this pattern. That is a remark '
      + 'about a small sample, not a signal.">unusual</i>' : '';
}

// THE EXPECTED RATE, IN THE PANEL RATHER THAN IN A COLUMN.
//
// It was a column beside the long run, and across fifty-five rows it printed
// between 47.93% and 52.07% with a median of exactly 50.00% — fifty of them
// within two points of their own expectation. A near-constant column costs
// width on a phone and teaches nothing after the first glance.
//
// It still matters for the handful of splits made almost entirely of one
// cell: `road_dog` expects 52.07% and `home_fav` 47.93%, so reading either
// against a flat 50% credits it with four points it has not earned. Those are
// the rows someone opens, and this is where they land.
function v3BaseLine(run, base) {
  if (!base || !run || !run.n) return '';
  const d = (run.pct - base.pct) * 100;
  // SAID WITHOUT THE WORDS "SIDE", "ROLE" OR "SPLIT", none of which a reader
  // who does not bet has met. The first version read "On side and role alone
  // a split of these games covers 51.53%. This one is +0.78 from that", and
  // never said 0.78 of what.
  return '<p class="adet__p">These games were already likely to cover about '
    + '<b style="color:var(--ink)">' + (base.pct * 100).toFixed(2) + '%</b> '
    + '\u2014 before the pattern, just from where each team played and '
    + 'whether it was favored. This pattern\u2019s record is '
    + (run.pct * 100).toFixed(2) + '%, so the pattern itself is worth '
    + '<b style="color:var(--ink)">' + (d > 0 ? '+' : '\u2212')
    + Math.abs(d).toFixed(2) + ' points</b>.</p>';
}


//: One team's record in one season, shaped like the league `season` block.
function v3AngleTeamYear(r, team, year) {
  const by = (((DATA.angles || {}).team_splits || {})[team] || {})[r.id] || {};
  const v = by[String(year)];
  if (!v) return null;
  const n = v[0] + v[1];
  return n ? { n: n, w: v[0], l: v[1], pct: v[0] / n } : null;
}

//: Every team the split archive knows, for the picker.
function v3AngleTeams() {
  return Object.keys((DATA.angles || {}).team_splits || {}).sort();
}

// GREEN NEEDS BOTH: an interval that clears break-even AND enough games to
// mean it. `pre_bye_div` was the first row in fifty-eight to clear, at 58-28
// over eleven seasons — eighty-six games, and a subset picked after seeing
// its parent. Tinting that would have been the board's loudest claim on its
// thinnest evidence. The row still shows its rate, its record and its range.
function v3Clears(lo, n, be) {
  const A = DATA.angles || {};
  const floor = has(A.tint_min) ? A.tint_min : 300;
  return lo > be && n >= floor;
}

// The long-run record, recomputed from the season-by-season splits for
// whatever start year is chosen.
//
// `team` narrows it to one club's own games. League-wide a whole-game
// condition is 50.00% by arithmetic — both sides of every grass game are on
// grass — and per team it is one side of each game and can be anything.
function v3AngleSince(r, from, be, team) {
  const A = DATA.angles || {};
  const by = team
    ? (((A.team_splits || {})[team] || {})[r.id] || {})
    : ((A.splits || {})[r.id] || {});
  let w = 0, l = 0;
  Object.keys(by).forEach(y => {
    if (Number(y) >= from) { w += by[y][0]; l += by[y][1]; }
  });
  const n = w + l;
  if (!n) return null;
  const iv = v3Wilson(w, n);
  return { n: n, w: w, l: l, pct: w / n, lo: iv[0], hi: iv[1],
           clears: v3Clears(iv[0], n, be) };
}

function v3AngleGames(r, games, team, note) {
  const gs = (games[r.id] || []).filter(g => !team || g.team === team);
  const plain = (r.plain ? '<p class="adet__p">' + esc(r.plain) + '</p>' : '')
    + (note || '');
  if (!gs.length) {
    return '<div class="adet">' + plain
      + '<p class="help" style="margin:0 0 8px">No games this season yet.'
      + '</p></div>';
  }
  const w = gs.filter(g => g.covered === true).length;
  const l = gs.filter(g => g.covered === false).length;
  // THREE STATES, NOT TWO. A game that landed exactly on the number is a
  // push: played, returns the stake, and counted in neither column. It
  // used to be lumped in with the fixtures still to come.
  const push = gs.filter(g => g.played && g.covered == null).length;
  const rest = gs.filter(g => !g.played).length;
  return '<div class="adet">' + plain
    // A HEADER STRIP, so this reads as a nested table rather than a panel
    // that appeared. It borrows the board's own column labels; the record
    // sits in the right-hand one because that is the column it grades.
    + '<div class="adet__h"><span>This season</span>'
    + '<span>' + w + '\u2013' + l
    + (push ? ' \u00b7 ' + push + ' push' : '')
    + (rest ? ' \u00b7 ' + rest + ' to play' : '') + '</span></div>'
    + gs.map(g => {
        const done = g.covered !== null && g.covered !== undefined;
        const pushed = !done && g.played;
        const tone = !done ? '' : (g.covered ? ' agame--won' : ' agame--lost');
        // ONLY LINKED WHERE THERE IS SOMETHING TO OPEN. A fixture whose
        // week has no board — next week's games, which are scheduled but
        // not yet priced — used to be a button that landed on "that game
        // is not on this week's board".
        const on = v3AngleBoard(g);
        // WHICH TEAM THE PATTERN IS ABOUT. Both sides were named the same
        // way, so "ATL at GB · cover +4.5" left the reader to work out
        // whose cover it was. The carrying team keeps the ink and the
        // weight; the fixture around it steps back.
        const line = '<span class="agame__t">'
          + '<b><span class="agame__me">' + esc(g.team) + '</span> '
          + (g.home ? 'vs' : 'at') + ' ' + esc(g.opp) + '</b>'
          + '<i>Wk ' + g.week
          + (has(g.spread) ? ' \u00b7 ' + (g.spread > 0 ? '\u2212' : '+')
             + Math.abs(g.spread) : '')
          + (has(g.pf) && has(g.pa) ? ' \u00b7 ' + g.pf + '\u2013' + g.pa
             : '') + '</i></span>'
          // A GAME NOT YET PLAYED NAMES ITS SIDE. "to play" said only that
          // nothing had happened, on the rows where knowing which team the
          // split points at is the whole use of the list. A push says so
          // in neutral: it is settled, and it is neither a cover nor a loss.
          + '<span class="tag ' + (pushed ? ''
             : !done ? 'tag--ours'
             : (g.covered ? 'tag--good' : 'tag--bad')) + '">'
          + (pushed ? 'push'
             : !done ? esc(g.team) + ' to play'
             : (g.covered ? 'cover ' : 'no ')
               + (g.by > 0 ? '+' : '') + g.by) + '</span>';
        if (!on) return '<div class="agame agame--flat' + tone + '">'
          + line + '<i class="agame__go"></i></div>';
        return '<button class="agame' + tone + '" data-v3anglegame="'
          + esc(g.gid || '') + '|' + (on.past ? g.week : '') + '|'
          + esc(r.id) + '">' + line
          + '<i class="agame__go">\u203a</i></button>';
      }).join('')
    + '</div>';
}

// A CONDITION THE WHOLE GAME IS IN, WHICH CANNOT HAVE A RECORD.
//
// Both sides of every prime-time game are in prime time, so one covers and
// the other does not and the split is exactly 50.00% — 570-570 on prime time,
// 1605-1605 on grass, 822-822 indoors. That is arithmetic, not measurement,
// and another ten seasons would not move it.
//
// The row stays, because dropping it would leave a reader wondering why the
// board does not track prime time. What it gets is the one piece of context
// no reader can supply for themselves: that this number was never able to
// say anything. Every OTHER row near 50% is a real measurement, and a split
// at 20% is as useful as one at 80% — which is why nothing here is filtered
// on the number.
function v3WholeTag(r) {
  return r && r.whole_game
    ? ' <i class="tag tag--flat" title="Both teams are in this situation, '
      + 'so one covers and the other does not. The record is 50% by '
      + 'arithmetic.">both sides</i>' : '';
}

// THE ROW THIS ONE IS THE OTHER HALF OF. Thirty of the board's rows are one
// side of a pair -- the same games with the cover on the other sideline -- and
// without saying so the fade reads as a restatement of the edge above it. A
// reader took "Quarterback has never beaten this opponent" at 5-2 and
// "Opposing quarterback has never beaten this team" at 2-5 for the same claim,
// which is the whole reason this exists.
function v3MirrorTag(r, by) {
  const o = (r && r.mirror && by) ? by[r.mirror] : null;
  if (!o) return '';
  return ' <i class="tag tag--flat" title="The same games as \u201c'
    + esc(o.label) + '\u201d, with the cover on the other side. Backing one '
    + 'is betting against the other.">flip side</i>';
}

// AND THE ARITHMETIC, IN THE OPENED PANEL, where there is room to show both
// numbers. Only on the league reading: per club the two rows are not the same
// games at all, because each picks the fixtures that club was on one side of.
function v3MirrorLine(r, by, runOf, team) {
  const o = (r && r.mirror && by) ? by[r.mirror] : null;
  if (!o) return '';
  const head = '<p class="adet__p">The same games as <b style="color:'
    + 'var(--ink)">' + esc(o.label) + '</b>, scored from the other side';
  if (team) return head + '.</p>';
  const a = runOf(r), b = runOf(o);
  if (!a || !a.n || !b || !b.n) return head + '.</p>';
  return head + ': <b style="color:var(--ink)">' + v3AngleRec(a) + '</b> here, '
    + '<b style="color:var(--ink)">' + v3AngleRec(b) + '</b> there. Every game '
    + 'that covers for one loses for the other, so the two add to 100% and '
    + 'backing both is backing neither.</p>';
}

// ── screen: record ──────────────────────────────────────────────────────
//
// WHAT THE MODEL HAS ACTUALLY DONE, in the words a reader already has: wins
// and losses, how often it was right, and what a hundred dollars would have
// come back as. Every number is computed in `season_scorecard` and looked up
// here — the picker selects a precomputed range rather than re-adding
// anything, so no figure on this page exists twice in two languages.
//
// TWO KINDS OF EVIDENCE AND THEY ARE NEVER POOLED. The game sections come
// from projections frozen at kickoff: a record of what was on the card. The
// player sections are rebuilt from today's model against archived prices,
// because nothing froze a player board before week 5. Each section says so
// on its own face.

//: A record as "18 / 14", with ties only where they happened.
function v3Rec(r) {
  if (!r || !r.n) return '—';
  return r.w + ' / ' + r.l + (r.push ? ' / ' + r.push : '');
}
function v3RecPct(r) {
  return (!r || !has(r.pct)) ? '—' : (r.pct * 100).toFixed(1) + '%';
}
function v3RecBand(r) {
  return (!r || !r.n) ? '—'
    : (r.lo * 100).toFixed(1) + '% to ' + (r.hi * 100).toFixed(1) + '%';
}
function v3RecPts(n2) { return !has(n2) ? '—' : n2.toFixed(2) + ' pts'; }
//: The book's own error, on each row's own games. The model is graded over
//: every frozen game and the blend over the ones that have a blend, so one
//: book figure under both rows would compare two different sets of games.
function v3RecBook(a, b) {
  if (!has(a)) return '—';
  return (!has(b) || Math.abs(a - b) < 0.005)
    ? a.toFixed(2) + ' pts'
    : a.toFixed(2) + ' / ' + b.toFixed(2) + ' pts';
}
//: A count with a thousands separator, because "1030" reads as a year.
function v3RecN(n) {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}
function v3Money(x) {
  return !has(x) ? '—'
    : (x >= 0 ? '+$' : '−$') + Math.abs(x * 100).toFixed(2);
}

// ── SIMPLE OR FULL ──────────────────────────────────────────────────────
//
// THE PAGE OPENS ON THE SHORT VERSION AND KEEPS EVERY NUMBER.
//
// Rendered end to end, the detailed page met a reader with a provenance
// disclaimer and then `error score 0.2534`, `Avg error 8.17 pts`, `To break
// even 56.4%`, `Our model, level removed` and two model rows nothing
// distinguished — five tables of percentages with no reference point on any
// of them, and the money, the one unit everybody reads, in section four.
//
// So the default is the headline row of each section with a verdict in
// words, and the toggle brings back everything that was ever here. Nothing
// is removed: `v3RecFull()` is the only thing that moves.
function v3RecFull() { return !!V.recFull; }

//: Where a rate sits against the three numbers that give it meaning: a coin
//: flip, the price, and the sportsbook on the same games. A reader who has
//: to be told that 56.3% beats 52.4% is being asked to do arithmetic the
//: page can do with a line.
function v3RecBar(pct, book, be) {
  if (!has(pct)) return '';
  const LO = 0.35, HI = 0.70;
  const at = v => Math.max(0, Math.min(100, ((v - LO) / (HI - LO)) * 100));
  const mark = (cls, v, t) => !has(v) ? ''
    : '<i class="rbar__' + cls + '" style="left:' + at(v).toFixed(1)
      + '%" title="' + t + '"></i>';
  return '<div class="rbar">'
    + mark('flip', 0.5, 'A coin flip, 50%')
    + mark('be', be, 'Break even, ' + (be * 100).toFixed(1) + '%')
    + mark('bk', book, 'The sportsbook, ' + (book * 100).toFixed(1) + '%')
    + '<b class="rbar__us' + (pct >= (has(be) ? be : 0.5) ? ' up' : ' dn')
    + '" style="left:' + at(pct).toFixed(1) + '%"></b></div>'
    + '<div class="rbar__k"><span>coin flip</span>'
    + (has(be) ? '<span>break even</span>' : '')
    + (has(book) ? '<span>sportsbook</span>' : '')
    + '<span class="rbar__kus">us</span></div>';
}

//: The verdict, in the words a reader would use. Beating the price is the
//: bar that matters and beating the book is the bar that is hard, so both
//: are said, and the sample caveat is said WITH them rather than under them.
//
// `be` IS NULL ON THE MONEYLINE AND THAT IS NOT AN OVERSIGHT. A spread or a
// total is priced the same both ways, so one break-even rate describes
// every bet on it. A moneyline is not: the price moves with the favorite,
// so picking 56% of winners says nothing on its own about profit, and the
// first draft of this said "ahead of the 50.0% a bet needs to turn a
// profit" — a sentence that is not true of any moneyline. With no fixed
// break-even the comparison that means something is the book on the same
// games, so that is the only one made.
function v3RecVerdict(pct, book, be, n, unit) {
  if (!has(pct)) return 'Not recorded for these weeks.';
  const out = [];
  if (has(be)) {
    out.push(pct >= be
      ? 'Ahead of the ' + (be * 100).toFixed(1)
        + '% a bet needs to turn a profit'
      : 'Below the ' + (be * 100).toFixed(1)
        + '% a bet needs to turn a profit');
    if (has(book)) {
      out.push(pct > book + 0.0005 ? 'and ahead of the sportsbook'
        : pct < book - 0.0005 ? 'but behind the sportsbook'
        : 'and level with the sportsbook');
    }
  } else if (has(book)) {
    out.push(pct > book + 0.0005
      ? 'Ahead of the sportsbook on the same games'
      : pct < book - 0.0005
      ? 'Behind the sportsbook on the same games'
      : 'Level with the sportsbook on the same games');
  } else {
    out.push(pct >= 0.5 ? 'Better than a coin flip'
                        : 'Worse than a coin flip');
  }
  let s = out.join(' ') + '.';
  if (has(n) && n > 0 && n < 60) {
    s += ' ' + n + ' ' + (unit || 'games') + ' is far too few to call it.';
  }
  return s;
}

//: One table. `cols` are the headings; `rows` are arrays of cells already
//: rendered. The first column carries the label and the rest are numbers.
//
//: `opts.prose` names columns that carry words rather than a figure. Every
//: column but the first is right-aligned and `white-space:nowrap`, which is
//: right for a rate and wrong for a list of a player's legs — unmarked, the
//: legs ran off the side of their own scroller instead of wrapping.
function v3RecTable(cols, rows, opts) {
  const o = opts || {};
  const pr = i => (o.prose || []).indexOf(i) >= 0;
  const cls = i => !i ? '' : pr(i) ? ' p' : ' n';
  const head = cols.map((c, i) =>
    '<span class="rec__h' + cls(i) + '">' + esc(c) + '</span>').join('');
  const body = rows.map(r => r.map((c, i) =>
    '<span' + (cls(i) ? ' class="' + cls(i).trim() + '"' : '') + '>' + c
    + '</span>').join('')).join('');
  return '<div class="recwrap"><div class="rec rec--' + cols.length
    + (o.cls ? ' ' + o.cls : '') + '">' + head + body + '</div></div>';
}

//: WHAT THE RANGE IS, IN WORDS. It was labeled "95% range" and nothing
//: said what that meant — a confidence interval is a term of art, and the
//: number it describes is the one most likely to be over-read on a page
//: reporting thirty-two games.
//
//: `rows` are [label, record] pairs whose interval to spell out. THE RANGE
//: MOVED OUT OF THE TABLE AND INTO THIS SENTENCE. As a column it was four
//: cells each reading "39.3% to 71.8%" — every one of them wide enough to
//: contain every other row, which reads as the page declining to say
//: anything, and it was the column asked to come off. The number itself is
//: not dropped: said once, in prose, beside the rate it belongs to, it is
//: the same information and a reader can tell what it is for.
function v3RecRangeNote(n, rows) {
  const said = (rows || []).filter(r => r[1] && r[1].n && has(r[1].pct))
    .map((r, i) => r[0] + '’s ' + v3RecPct(r[1])
      + (i ? ', ' : ' could honestly be anywhere from ')
      + (r[1].lo * 100).toFixed(1) + '% to '
      + (r[1].hi * 100).toFixed(1) + '%');
  return '<p class="help" style="margin-top:8px">Over '
    + (has(n) ? n + ' games' : 'this few games')
    + ', luck alone moves these numbers a long way. '
    + (said.length ? said.join('; ') + '. That is where the true rate most '
       + 'likely sits — not how much it might vary — and it narrows every '
       + 'week.'
       : 'The ranges quoted are where the true rate most likely sits, not '
       + 'how much it might vary, and they narrow every week.')
    + '</p>';
}

function v3RecHead(n, title, sub) {
  return '<div class="rec__t"><span class="rec__n">' + n + '</span>'
    + '<h2 class="rec__ttl">' + esc(title) + '</h2></div>'
    + (sub ? '<p class="help rec__sub">' + esc(sub) + '</p>' : '');
}

// ── The picker ──────────────────────────────────────────────────────────
//
// PINNED, like every other board on this site. The tables run several
// screens and the control that chooses which weeks they cover was at the
// top of them, so changing the range meant scrolling back up to a dropdown
// you could no longer see. `.pbar` is the same sticky bar the players board
// and the angles table already use.
//
// WEEKS WITHOUT A GAME RECORD ARE OFFERED BUT DISABLED, with the reason in
// the option itself. Weeks 1 and 2 of 2026 have no frozen projection and
// cannot get one — the feature matrix is rebuilt from current data, so a
// recomputed week is a different model's answer — and a reader who picks
// them gets three empty sections and no explanation worth the tap.
function v3RecPicker(S) {
  const ws = S.played || [];
  if (ws.length < 2) return '';
  const gw = S.game_weeks || [];
  const cur = v3RecRange(S);
  const sel = (attr, val, opts) =>
    '<div class="picker mxsel"><select data-' + attr + ' aria-label="'
    + (attr === 'v3scfrom' ? 'From week' : 'To week') + '">'
    + opts.map(w => '<option value="' + w + '"'
        + (w === val ? ' selected' : '')
        + (gw.indexOf(w) < 0 ? ' disabled' : '') + '>Week ' + w
        + (gw.indexOf(w) < 0 ? ' — no game record' : '') + '</option>').join('')
    + '</select></div>';
  return '<div class="pbar pbar--free recpick">'
    + '<div class="pbar__row pbar__row--two">'
    + sel('v3scfrom', cur[0], ws.filter(w => w <= cur[1]))
    + sel('v3scto', cur[1], ws.filter(w => w >= cur[0]))
    + '</div>'
    + '<div class="seg seg--2">'
    + '<button data-v3recfull="0" aria-pressed="' + (!v3RecFull())
    + '">Simple</button>'
    + '<button data-v3recfull="1" aria-pressed="' + v3RecFull()
    + '">Full detail</button>'
    + '</div></div>';
}

//: Which range is showing, falling back to the payload's own default when
//: the reader has chosen nothing or has chosen a pair that no longer exists.
function v3RecRange(S) {
  const ws = S.played || [];
  if (!ws.length) return [0, 0];
  const d = String(S.default || '').split('-');
  const da = Number(d[0]) || ws[0];
  const db = Number(d[1]) || ws[ws.length - 1];
  // EACH END FALLS BACK ON ITS OWN, and that is the whole bug fix. This used
  // to resolve both ends or neither: `if (a === null || b === null)` threw
  // away a chosen end because the OTHER one was still unset. Since each
  // handler only sets the end you touched, the first move of either dropdown
  // was discarded and the page redrew identically — the picker did nothing
  // until you had moved both. The JS test passed because it set both at
  // once, which is a test written around the bug rather than at it.
  let a = has(V.scFrom) ? V.scFrom : da;
  let b = has(V.scTo) ? V.scTo : db;
  if (ws.indexOf(a) < 0) a = ws[0];
  if (ws.indexOf(b) < 0) b = ws[ws.length - 1];
  // THE END THE READER ACTUALLY MOVED WINS. Choosing "to week 2" while the
  // start still sits on its default means the weeks up to there, not an
  // empty range and not a silent jump back to the default.
  if (a > b) {
    if (!has(V.scFrom)) a = b;
    else b = a;
  }
  return [a, b];
}

// ── The scoreboard ──────────────────────────────────────────────────────
//
// ONE TILE PER THING THE MODEL CLAIMS TO DO, ABOVE EVERYTHING. This page is
// where the model is held to account, so the first screen answers the only
// question a reader actually arrives with — is it any good — and the
// sections below it show the working.
//
// OUR MODEL IS THE NUMBER ON THE TILE. The adjusted number is what the card
// serves and is a row in every section below, but the thing being improved
// week to week is the model's own answer, so that is the one on the face.
function v3RecMoney110(r) {
  // Spread and total at the usual price, which is the price `BREAK_EVEN`
  // already assumes and ships. A push returns the stake, so it is a bet
  // that returned nothing rather than a bet that did not happen.
  if (!r || !r.n) return null;
  const n = r.w + r.l + (r.push || 0);
  return n ? (r.w * (100 / 110) - r.l) / n : null;
}

//
// A TILE IS NOT A LINK. The obvious `href="#sb1"` scrolls to the section on
// a static page and navigates on this one: routing here is the location
// hash — `popstate` in this file, `hashchange` in v1's shared core — so
// setting it to an unknown name sends the reader to whatever that resolves
// to, which is not the Record page.
function v3RecTile(label, record, pct, note, cls) {
  return '<div class="sbt' + (cls ? ' ' + cls : '') + '">'
    + '<span class="sbt__l">' + esc(label) + '</span>'
    + '<span class="sbt__v">' + pct + '</span>'
    + '<span class="sbt__r">' + record + '</span>'
    + '<span class="sbt__n">' + note + '</span></div>';
}

function v3RecBoard(g, p, S) {
  const be = has(S.break_even) ? S.break_even : 0.5238;
  const t = [];
  if (g && g.n) {
    const m = g.moneyline, sp = g.spread, to = g.total;
    t.push(v3RecTile('Winning team', v3Rec(m.ours), v3RecPct(m.ours),
      has(m.ours.pct) && has(m.book.pct)
        ? (m.ours.pct > m.book.pct ? 'ahead of the book’s '
           : m.ours.pct < m.book.pct ? 'behind the book’s '
           : 'level with the book’s ') + v3RecPct(m.book) : '—', 'sb1'));
    const spm = v3RecMoney110(sp.model);
    t.push(v3RecTile('Point spread', v3Rec(sp.model), v3RecPct(sp.model),
      has(spm) ? v3Money(spm) + ' per $100' : '—', 'sb2'));
    const tom = v3RecMoney110(to.model);
    t.push(v3RecTile('Over / under', v3Rec(to.model), v3RecPct(to.model),
      has(tom) ? v3Money(tom) + ' per $100' : '—', 'sb3'));
  }
  const mo = (p || {}).model_all || {};
  if (mo.bets) {
    t.push(v3RecTile('Player bets', v3RecN(mo.bets) + ' bets',
      v3Money(mo.roi), 'per $100 staked', 'sb4'));
  }
  if (!t.length) return '';
  // The one caveat that applies to every tile, said once.
  const n = (g && g.n) || 0;
  return '<div class="card sbcard">'
    + '<div class="eyebrow">How the model has done</div>'
    + '<div class="sbgrid">' + t.join('') + '</div>'
    + '<p class="help" style="margin-top:10px">Every figure is <b style="'
    + 'color:var(--ink)">our model’s own answer</b>, not the adjusted number '
    + 'the card serves — the sections below show both. A bet needs to land '
    + (be * 100).toFixed(1) + '% of the time to break even at the usual '
    + 'price'
    + (n ? ', and ' + n + ' games is far too few to call any of this' : '')
    + '.</p></div>';
}

function v3RecGames(g, S) {
  if (!g || !g.n) {
    // NOT A BLANK SECTION. A range with no frozen projection has a reason,
    // and the reason is the interesting part.
    const why = (S.missing || [])[0];
    return '<div class="card"><div class="eyebrow">Game picks</div>'
      + '<p class="lede" style="font-size:15px;margin-top:6px">No game '
      + 'projection was recorded before these weeks’ kickoffs'
      + (why ? ', and ' + esc(why.why) : '') + '.</p></div>';
  }
  const m = g.moneyline, sp = g.spread, to = g.total;
  const full = v3RecFull();
  const be = has(S.break_even) ? S.break_even : 0.5238;
  // ── 01 ────────────────────────────────────────────────────────────────
  // THE RANGE COLUMN IS GONE FROM THIS SECTION. Asked for directly: four
  // rows each carrying "39.3% to 71.8%" is four intervals wide enough to
  // contain every other row on the table, which reads as the page refusing
  // to say anything. The note underneath keeps saying what the spread of
  // outcomes is; the full view keeps the numbers.
  const mlRows = [['Our model', v3Rec(m.ours), v3RecPct(m.ours)]];
  if (full) {
    mlRows.push(['Adjusted model', v3Rec(m.blend), v3RecPct(m.blend)]);
    mlRows.push(['Sportsbook', v3Rec(m.book), v3RecPct(m.book)]);
    mlRows.push(['Where we picked against the book', v3Rec(m.disagree),
                 v3RecPct(m.disagree)]);
  } else if (m.book && m.book.n) {
    mlRows.push(['Sportsbook', v3Rec(m.book), v3RecPct(m.book)]);
  }
  const spRows = [['Our model', v3Rec(sp.model), v3RecPct(sp.model),
                   v3RecPts(sp.mae_model)]];
  if (full) {
    spRows.push(['Adjusted model', v3Rec(sp.blend), v3RecPct(sp.blend),
                 v3RecPts(sp.mae_blend)]);
  }
  spRows.push(['Sportsbook', '—', '—',
               v3RecBook(sp.mae_book, sp.mae_book_blend)]);
  const toRows = [['Our model', v3Rec(to.model), v3RecPct(to.model),
                   v3RecPts(to.mae_model)]];
  if (full) {
    toRows.push(['Adjusted model', v3Rec(to.blend), v3RecPct(to.blend),
                 v3RecPts(to.mae_blend)]);
  }
  toRows.push(['Sportsbook', '—', '—',
               v3RecBook(to.mae_book, to.mae_book_blend)]);
  if (full) {
    toRows.push(['Our model, ignoring the week’s scoring level',
                 v3Rec(to.centered), v3RecPct(to.centered),
                 v3RecPts(to.mae_centered)]);
    toRows.push(['Adjusted, ignoring the week’s scoring level',
                 v3Rec(to.blend_centered), v3RecPct(to.blend_centered),
                 v3RecPts(to.mae_blend_centered)]);
  }
  const spm = v3RecMoney110(sp.model), tom = v3RecMoney110(to.model);
  // ── ONE CARD, THREE MARKETS ─────────────────────────────────────────
  //
  // These were three cards, each holding a two-row table, a reference line
  // and a sentence. That is a great deal of chrome around six numbers, and
  // they are one subject: how the model did on the game itself. Asked
  // directly whether they could be a single card, and they can.
  //
  // The sub-headings keep their own names, so a reader still knows which
  // market they are reading; what goes is two card borders and two blocks
  // of padding.
  return '<div class="card" id="sb1">'
    + v3RecHead('01', 'Picking the game')
    + '<div class="recsec"><h3 class="recsec__t">The winning team</h3>'
    + v3RecTable(['Pick', 'Wins / losses', 'Correct'], mlRows)
    + v3RecBar(m.ours.pct, (m.book || {}).pct, null)
    + '<p class="help" style="margin-top:8px">'
    + esc(v3RecVerdict(m.ours.pct, (m.book || {}).pct, null, g.n, 'games'))
    + ' A moneyline has no one break-even rate — the price moves with the '
    + 'favorite — so the sportsbook on the same games is the comparison '
    + 'that means something.'
    + '</p>'
    + (full
       ? v3RecRangeNote(g.n, [['Our model', m.ours],
                              ['the adjusted model', m.blend],
                              ['the sportsbook', m.book]])
         + '<p class="help" style="margin-top:8px">How reliable the win '
         + 'chances themselves are, scored on how far each one sat from what '
         + 'happened — our ' + (has(m.brier_ours) ? m.brier_ours.toFixed(4)
             : '—') + ' against the sportsbook’s '
         + (has(m.brier_book) ? m.brier_book.toFixed(4) : '—')
         + '. Lower is better.'
         + (has(m.brier_blend)
            ? ' Blended: ' + m.brier_blend.toFixed(4) + ' against '
              + m.brier_book_blend.toFixed(4) + ' on the same ' + m.blend.n
              + ' games.'
            : ' The blended win chance is recorded from week 5.')
         + '</p>'
       : '')
    + '</div><div class="recsec" id="sb2">'
    + '<h3 class="recsec__t">The point spread</h3>'
    + '<p class="help">Average error is how many points the number missed '
    + 'the final winning margin by.</p>'
    + v3RecTable(['Prediction', 'W / L / push', 'Correct', 'Avg error'], spRows)
    + v3RecBar(sp.model.pct, null, be)
    + '<p class="help" style="margin-top:8px">'
    + esc(v3RecVerdict(sp.model.pct, null, be, sp.model.n, 'games'))
    + (has(spm) ? ' At the usual price that is <b style="color:var(--ink)">'
       + v3Money(spm) + ' per $100</b> staked.' : '')
    + '</p>'
    + (full ? v3RecRangeNote(sp.model.n, [['Our model', sp.model],
                                          ['the adjusted model', sp.blend]])
            : '')
    + '</div><div class="recsec" id="sb3">'
    + '<h3 class="recsec__t">Over or under the total</h3>'
    + '<p class="help">Average error is how many points the number missed '
    + 'the combined final score by.</p>'
    + v3RecTable(['Prediction', 'Wins / losses', 'Correct', 'Avg error'], toRows)
    + v3RecBar(to.model.pct, null, be)
    + '<p class="help" style="margin-top:8px">'
    + esc(v3RecVerdict(to.model.pct, null, be, to.model.n, 'games'))
    + (has(tom) ? ' At the usual price that is <b style="color:var(--ink)">'
       + v3Money(tom) + ' per $100</b> staked.' : '')
    + '</p>'
    + (full
       ? v3RecRangeNote(to.model.n, [['Our model', to.model],
                                     ['the adjusted model', to.blend]])
         + '<p class="help" style="margin-top:8px">The over was the pick in '
         + to.over + ' of ' + g.n + ' games'
         + (to.centered && to.centered.n
            ? ', and in ' + to.over_centered + ' of ' + to.centered.n
              + ' once the level is removed'
            : '')
         + '. Ignoring the week’s scoring level keeps which games the model '
         + 'rates high or low and drops how high it rates the week as a '
         + 'whole.</p>'
       : '')
    + '</div>';
}

//: A money cell, coloured by its sign.
function v3RecCash(v) {
  return '<b class="' + (v > 0 ? 'up' : v < 0 ? 'dn' : '') + '">'
    + v3Money(v) + '</b>';
}

//: One market's five cells, for whichever series is being drawn.
function v3RecBetRow(x) {
  return [esc(x.label), v3RecN(x.bets), v3RecPct({pct: x.hit, n: x.bets}),
          (x.be * 100).toFixed(1) + '%', v3RecCash(x.roi)];
}

// ── Bets, one at a time ─────────────────────────────────────────────────
//
// WHICH SERIES THE PER-PLAYER TABLES READ. The three on this page are the
// same bets graded three ways and they are not interchangeable, so the
// tables below say which one they are showing rather than quietly picking.
// "Edge rule only" said nothing — asked directly whether it was the
// shortlist, which is a DIFFERENT rule on a different page of this card. So
// each one is named for what it does and says so under the control.
// [key, label, return index, side index, what it is, price index].
// The price is per series because the three do not always take the same
// side, and an under is paid at the under's own number.
const V3RECSERIES = [
  ['model', 'Our model', 6, 5,
   'Every bet, on the side our raw model leaned.', 10],
  ['adj', 'Adjusted model', 4, 3,
   'The same bets, on the side the card actually served — our number already '
   + 'pulled toward the price.', 9],
  ['edge', 'Big price gaps', 7, 3,
   'Only the bets where our number beat the sportsbook’s own fair price by a '
   + 'margin fitted on earlier seasons — section 03 above. This is a price '
   + 'test and NOT the Shortlist, which is the fitted band rule in section '
   + '02 and picks its own lines.', 11],
];
function v3RecSeries() {
  const k = V.recSeries || 'model';
  return V3RECSERIES.filter(s => s[0] === k)[0] || V3RECSERIES[0];
}

//: `2026_03_ARI_SF` as `ARI @ SF`. The season and week are already on the
//: page twice and the clubs are the part a reader is scanning for.
function v3RecGameLabel(id) {
  const p = String(id || '').split('_');
  return p.length >= 4 ? p[p.length - 2] + ' @ ' + p[p.length - 1]
                       : String(id || '');
}

//: Every graded leg in the chosen weeks, grouped as it was shipped: by
//: player and game. See `season_scorecard.bets_block` — the legs are
//: shipped PER WEEK because there are 153 contiguous ranges in a season and
//: precomputing a player table for each would ship the same bet a hundred
//: and fifty times.
//
// THE ONLY ARITHMETIC THIS PAGE DOES IS ADDITION. Every per-leg number —
// the side taken, whether it won, what it returned — was computed in Python
// by the same code the pooled rows use, so nothing here is a second
// implementation of the accounting. `tests/js/v3app.js` adds the legs back
// up and checks the total against `players.model_all.roi`.
function v3RecLegs(S, a, b) {
  const B = S.bets || {};
  const out = [];
  for (let w = a; w <= b; w++) {
    const rows = (B.weeks || {})[String(w)];
    if (!rows) continue;
    for (const r of rows) out.push({p: r[0], g: r[1], w: w, legs: r[2],
                                    t: r[3]});
  }
  return out;
}

//: Totals over the chosen weeks, grouped by player or by club.
//
//: ONE FUNCTION FOR BOTH, because a club's row means exactly what a
//: player's row means — these bets, this many, this return — and two
//: implementations of that would be free to drift. `pick` names the thing
//: being counted and `label` turns it into a name.
function v3RecGroupRows(S, a, b, pick, label) {
  const s = v3RecSeries(), ri = s[2];
  const by = {};
  for (const pg of v3RecLegs(S, a, b)) {
    const k = pick(pg);
    if (k === null || k === undefined) continue;
    for (const l of pg.legs) {
      if (!has(l[ri])) continue;
      const r = by[k] || (by[k] = {key: k, name: label(k), bets: 0, won: 0,
                                   ret: 0, games: {}, players: {}});
      r.bets++; r.ret += l[ri];
      if (l[ri] > 0) r.won++;
      r.games[pg.g] = 1;
      r.players[pg.p] = 1;
    }
  }
  return Object.keys(by).map(k => {
    const r = by[k];
    r.games = Object.keys(r.games).length;
    r.players = Object.keys(r.players).length;
    r.hit = r.bets ? r.won / r.bets : null;
    r.roi = r.bets ? r.ret / r.bets : null;
    return r;
  });
}

function v3RecPlayerRows(S, a, b) {
  const names = (S.bets || {}).players || [];
  return v3RecGroupRows(S, a, b, pg => pg.p, k => names[k] || '?');
}

function v3RecTeamRows(S, a, b) {
  const tm = (S.bets || {}).teams || [];
  return v3RecGroupRows(S, a, b, pg => pg.t, k => tm[k] || '?');
}

//: One player-game, with its legs and whether they all landed together.
function v3RecPgRows(S, a, b) {
  const s = v3RecSeries(), ri = s[2], si = s[3], pi = s[5];
  const names = (S.bets || {}).players || [];
  const out = [];
  for (const pg of v3RecLegs(S, a, b)) {
    const legs = pg.legs.filter(l => has(l[ri]));
    if (!legs.length) continue;
    const won = legs.filter(l => l[ri] > 0).length;
    out.push({name: names[pg.p] || '?', g: pg.g, w: pg.w, legs: legs,
              team: (((S.bets || {}).teams) || [])[pg.t],
              si: si, ri: ri, pi: pi,
              // The streak direction is a fact about the PLAYER that week,
              // so it is the same on every leg of a player-game; read off
              // the first rather than repeated under each line.
              streak: legs[0][8],
              bets: legs.length, won: won,
              same: won === 0 || won === legs.length,
              ret: legs.reduce((t, l) => t + l[ri], 0)});
  }
  return out;
}

// ── The per-player table ────────────────────────────────────────────────
//
// NOT `v3RecTable`. That is a grid of loose spans, which cannot carry a
// clickable row and gives its label column all the slack — at 880px the
// name sat at one edge of the card and the figures at the other, a hand's
// width apart, which is unreadable and was asked about directly.
//
// So a row is one button with a shared column template, the way the players
// board's own rows work. Fixed figure columns and a capped measure keep the
// name and its numbers together at every width.
const V3RECSORTS = [['ret', 'Per $100'], ['hit', 'Hit rate'],
                    ['bets', 'Bets'], ['won', 'Won'], ['name', 'Player']];

function v3RecSortRows(rows) {
  const k = V.recSort || 'ret';
  const d = V.recSortDesc === false ? -1 : 1;
  const by = {
    // THE COLUMN SORTS BY WHAT THE COLUMN SAYS. It sorted by total profit
    // while showing per $100, so the figures came out looking unordered —
    // 38 bets at +$32.79 above 30 at +$24.50 is right by total and wrong
    // by the only number on screen.
    //
    // Ties break on the number of bets, so where two rows return the same
    // the one with more behind it is first. That does not stop a single
    // lucky bet topping the money column, which is what the note under
    // the table is for.
    ret: r => r.roi,
    hit: r => (has(r.hit) ? r.hit : -1),
    bets: r => r.bets, won: r => r.won,
  }[k];
  const out = rows.slice();
  if (k === 'name') {
    out.sort((a, b) => a.name.localeCompare(b.name) * d);
  } else {
    out.sort((a, b) => (by(b) - by(a)) * d || b.bets - a.bets
                       || b.ret - a.ret);
  }
  return out;
}

//: A sortable heading. Tapping the column already sorted flips it, which is
//: what a table does and saves a second control for direction.
function v3RecSortHead(what) {
  const k = V.recSort || 'ret';
  const d = V.recSortDesc === false ? ' ↑' : ' ↓';
  const cell = (key, label, cls) =>
    '<button class="rech' + (cls ? ' ' + cls : '')
    + (key === k ? ' rech--on' : '') + '" data-v3recsort="' + key + '">'
    + esc(label) + (key === k ? d : '') + '</button>';
  return '<div class="recg rech__r">'
    + cell('name', what || 'Player')
    + cell('bets', 'Bets', 'n') + cell('won', 'Won', 'n')
    + cell('hit', 'Hit rate', 'n') + cell('ret', 'Per $100', 'n')
    + '</div>';
}

//: One player's games, laid out as a record rather than a sentence: the
//: game, then a line per leg carrying the category, the side, the number,
//: what he did, the price he was paid at and what the leg returned.
function v3RecDrawer(rows, S) {
  const mk = (S.bets || {}).markets || [];
  return '<div class="pgd">' + rows.map(r => {
    const legs = r.legs.map(l => {
      const side = l[r.si] === 1 ? 'over' : l[r.si] === 0 ? 'under' : '';
      const price = l[r.pi];
      return '<div class="pgd__l">'
        + '<span class="pgd__m">' + esc(mk[l[0]] || '?') + '</span>'
        + '<span class="pgd__b">' + side + ' ' + l[1] + '</span>'
        + '<span class="pgd__a">had ' + l[2] + '</span>'
        + '<span class="pgd__p n">' + (has(price) ? v3Dash(american(price))
            : '—') + '</span>'
        + '<span class="pgd__r n ' + (l[r.ri] > 0 ? 'up' : 'dn') + '">'
        + v3Money(l[r.ri]) + '</span></div>';
    }).join('');
    return '<div class="pgd__g">'
      + '<div class="pgd__h"><b>'
      + esc(V.recWho === 'team' ? r.name : v3RecGameLabel(r.g)) + '</b>'
      + '<span class="pgwk">'
      + (V.recWho === 'team' ? esc(v3RecGameLabel(r.g)) + ' \u00b7 ' : '')
      + 'week ' + r.w + '</span>'
      + (r.streak ? '<span class="pgwk">had been going '
         + (r.streak === 1 ? 'over' : 'under') + '</span>' : '')
      + '</div>' + legs
      + (r.bets > 1 && r.same
         ? '<div class="pgall">all ' + r.bets + ' landed the same way</div>'
         : '')
      + '</div>';
  }).join('') + '</div>';
}

function v3RecPlayerTable(rows, S, pg, match, what) {
  const m = match || ((g, r) => g.name === r.name);
  const sorted = v3RecSortRows(rows);
  return '<div class="recwrap">' + v3RecSortHead(what)
    + sorted.map(r => {
      const open = V.recOpen === r.name;
      const mine = (pg || []).filter(g => m(g, r));
      return '<div class="recr' + (open ? ' recr--open' : '') + '">'
        + '<button class="recg recr__b" data-v3recopen="' + esc(r.name)
        + '" aria-expanded="' + open + '">'
        + '<span class="recr__n">' + esc(r.name)
        + (has(r.players) && r.players > 1 && V.recWho === 'team'
           ? '<span class="recr__s">' + r.players + ' players</span>' : '')
        + '<span class="recr__c">' + (open ? '−' : '+') + '</span></span>'
        + '<span class="n">' + r.bets + '</span>'
        + '<span class="n">' + r.won + '</span>'
        + '<span class="n">'
        + (has(r.hit) ? (r.hit * 100).toFixed(0) + '%' : '—') + '</span>'
        + '<span class="n">' + v3RecCash(r.roi) + '</span>'
        + '</button>'
        + (open ? (mine.length ? v3RecDrawer(mine, S)
                   : '<div class="pgd pgd--none">No leg detail for this '
                     + 'grading.</div>') : '')
        + '</div>';
    }).join('') + '</div>';
}

//: WHAT THE BET WAS: the category, the side, the number, and what he did.
function v3RecPgLeg(l, r, S) {
  const mk = (S.bets || {}).markets || [];
  const side = l[r.si] === 1 ? 'over' : l[r.si] === 0 ? 'under' : '';
  return '<span class="pgleg ' + (l[r.ri] > 0 ? 'up' : 'dn') + '">'
    + esc(mk[l[0]] || '?') + ' ' + side + ' ' + l[1]
    + ', had ' + l[2]
    // NOT "hot" OR "cold". Those read as a verdict, and recent form is the
    // one thing on this card the project has explicitly NOT measured into an
    // edge — `player_history` makes the argument at length. The fact is
    // which way he had been going, said flatly.
    + (l[8] ? ' · had been going ' + (l[8] === 1 ? 'over' : 'under') : '')
    + '</span>';
}

//: The legs of one player-game, spelled out: what the line was, what he
//: did, and which way the bet went. This is the view that makes the
//: correlation visible rather than only stated.
function v3RecPgTable(rows, S) {
  const mk = (S.bets || {}).markets || [];
  return v3RecTable(['Player and game', 'Bets', 'Won', 'What happened',
                     'Per $100'],
    rows.map(r => {
      const legs = r.legs.map(l => v3RecPgLeg(l, r, S)).join(' ');
      return ['<b>' + esc(r.name) + '</b><span class="pgwk"> · '
              + esc(v3RecGameLabel(r.g)) + ' · week ' + r.w + '</span>',
              String(r.bets), String(r.won),
              legs + (r.bets > 1 && r.same
                      ? '<span class="pgall">all ' + r.bets
                        + ' landed the same way</span>' : ''),
              v3RecCash(r.ret / r.bets)];
    }), {prose: [0, 3], cls: 'rec--pg'});
}

// ── 06 · Bets by player ─────────────────────────────────────────────────
//
// WHAT A BET IS, ON THE FACE OF THE CARD. One player, one game, one
// category. Over weeks 3-4 of 2026 that is 1,062 bets across 282 players
// and 501 player-games — a receiver is usually two bets in a game, catches
// and receiving yards, and a back who catches is three. "1,062" reads as
// far more evidence than it is, and nothing on this page said so.
//
// AND THEY MOVE TOGETHER. 464 of those player-games carried two or more
// legs and 222 of them, 48%, had every leg land the same way: a receiver
// who clears his catches number has almost always cleared his yards
// number. Six legs on one man is nearer one and a half opinions than six.
// The pooled intervals above already cluster by game, so the published
// return is not flattered by this — but a reader counting wins would be.
function v3RecByPlayer(p, S, a, b) {
  const B = S.bets || {};
  if (!B.weeks || !(B.players || []).length) return '';
  const s = v3RecSeries();
  const who = V.recWho || 'top';
  const rows = v3RecPlayerRows(S, a, b);
  if (!rows.length) return '';
  const pg = v3RecPgRows(S, a, b);
  const multi = pg.filter(r => r.bets > 1);
  const same = multi.filter(r => r.same).length;
  const seg = (attr, opts, cur) => '<div class="seg seg--' + opts.length
    + '">' + opts.map(o => '<button data-' + attr + '="' + o[0]
      + '" aria-pressed="' + (o[0] === cur) + '">' + esc(o[1])
      + '</button>').join('') + '</div>';
  let body = '', note = '';
  if (who === 'top') {
    const by = rows.slice().sort((x, y) => y.ret - x.ret);
    const n = Math.min(10, Math.floor(by.length / 2));
    body = '<div class="recsub">Best ' + n + '</div>'
      + v3RecPlayerTable(by.slice(0, n), S, pg)
      + '<div class="recsub">Worst ' + n + '</div>'
      + v3RecPlayerTable(by.slice(-n).reverse(), S, pg);
    note = 'The ten best and ten worst by TOTAL profit, so a player we bet '
      + 'six times counts for more than one we bet twice. Inside each ten '
      + 'the order follows whichever column you sorted — and a single lucky '
      + 'bet can top the money column, so read the bet count beside it.';
  } else if (who === 'team') {
    // BY CLUB, asked for after the player table landed. The same question
    // one level up: does the model read some offenses better than others?
    //
    // The caveat is STRONGER here, not weaker. A club's bets share a game
    // script as well as a player, so thirty bets on one offense is nearer a
    // handful of opinions than thirty.
    body = v3RecPlayerTable(v3RecTeamRows(S, a, b), S, pg,
                            (g, r) => g.team === r.name, 'Team');
    note = 'Every bet on a player from that club. A club’s bets share a '
      + 'game script as well as a player, so these move together even '
      + 'harder than one man’s do.';
  } else if (who === 'most') {
    const by = rows.slice().sort((x, y) => y.bets - x.bets || y.ret - x.ret);
    body = v3RecPlayerTable(by.slice(0, 25), S, pg);
    note = 'Where the model puts its opinions, which is a different question '
      + 'from which ones it got right.';
  } else if (who === 'games') {
    let by = pg.slice().sort((x, y) => y.bets - x.bets || y.ret - x.ret);
    if (V.recQ) {
      const q = V.recQ.toLowerCase();
      by = by.filter(r => r.name.toLowerCase().indexOf(q) >= 0
                       || v3RecGameLabel(r.g).toLowerCase().indexOf(q) >= 0);
    }
    body = v3RecSearch() + (by.length ? v3RecPgTable(by.slice(0, 40), S)
      : '<div class="empty">No player matching “' + esc(V.recQ) + '”.</div>');
    // No note of its own: the standing paragraph under every cut already
    // counts the player-games whose legs landed together, and this view is
    // the one that SHOWS them, so saying it twice on the same screen reads
    // as two different findings.
    note = 'Most legs first, so the player-games that move together are at '
      + 'the top. Search to find one player.';
  } else {
    let by = rows.slice().sort((x, y) => y.ret - x.ret);
    if (V.recQ) {
      const q = V.recQ.toLowerCase();
      by = by.filter(r => r.name.toLowerCase().indexOf(q) >= 0);
    }
    const shown = V.recShown || 40;
    body = v3RecSearch()
      + (by.length ? v3RecPlayerTable(by.slice(0, shown), S, pg)
         : '<div class="empty">No player matching “' + esc(V.recQ) + '”.</div>')
      + (by.length > shown
         ? '<button class="more" data-v3recmore="' + (shown + 60) + '">Show '
           + Math.min(60, by.length - shown) + ' more of ' + by.length
           + '</button>' : '');
    note = 'Every player we bet in these weeks, best return first.';
  }
  return '<div class="card" id="sb6">'
    + v3RecHead('04', 'Bets by player and club',
                'One bet is one player, in one game, in one category — so a '
                + 'receiver is usually two bets in a game and a back who '
                + 'catches is three.')
    + seg('v3recseries', V3RECSERIES.map(x => [x[0], x[1]]), s[0])
    + '<p class="help" style="margin-top:6px">' + esc(s[4]) + '</p>'
    + seg('v3recwho', [['top', 'Best and worst'], ['all', 'Every player'],
                       ['team', 'By team'], ['games', 'By game'],
                       ['most', 'Most bet']], who)
    + body
    + (note ? '<p class="help" style="margin-top:8px">' + esc(note) + '</p>'
            : '')
    + '<p class="help" style="margin-top:6px"><b style="color:var(--ink)">'
    + '“had been going over” or “under”</b> marks a leg '
    + 'where that player had run one way in ' + V3STREAK_MIN + ' of his last '
    + V3STREAK_OF + ' graded weeks going INTO that week — the Streaks filter '
    + 'in section 02. Recent form, not an edge; the side bet is still '
    + 'ours.</p>'
    + '<p class="help" style="margin-top:6px">A player’s bets are '
    + '<b style="color:var(--ink)">not independent</b>: ' + same + ' of the '
    + multi.length + ' player-games carrying more than one bet had every leg '
    + 'land the same way, because a receiver who clears his catches number '
    + 'has almost always cleared his yards number. Count them as opinions, '
    + 'not as wins. The ranges above already allow for it.</p>'
    + '</div>';
}

function v3RecSearch() {
  return '<div class="search recq"><input data-v3recq type="search" '
    + 'placeholder="Search a player" value="' + esc(V.recQ || '') + '">'
    + (V.recQ ? '<button class="searchx" data-v3recqx>×</button>' : '')
    + '</div>';
}

// ── The board's four views, scored ──────────────────────────────────────
//
// Everyone, Shortlist, Fades and Streaks are the tabs on the players board,
// and until now none of them could be scored: the shortlist was only ever
// applied to the live board, and the streak rule was evaluated in the page
// from whatever history the payload carried, so a question about week 3 got
// today's answer and changed as later weeks landed.
//
// EACH ONE IS ITS OWN SET OF BETS, not a filter on one set. The shortlist
// picks its own line and its own side, so showing our result under its name
// would report the board's record as the rule's.
const V3RECVIEWS = [
  ['all', 'Everyone',
   'Every player-game the model had a number for, on the side it leaned.'],
  ['short', 'Shortlist',
   'The lines the fitted rule would take — book depth first, then a '
   + 'disagreement whose size falls in the band that market has come our '
   + 'way in. The bands were fitted on 2024 with 2025 and 2026 held out, so '
   + 'these weeks are a real test of it. Priced at the side the rule takes, '
   + 'and reduced to one bet a player-game: it picked eight passing-yards '
   + 'lines on one quarterback in week 3.'],
  ['fade', 'Fades',
   'The shortlist’s under picks — the lines where our number says the '
   + 'posted over is too expensive. On a two-sided line a fade is not a '
   + 'separate group, so these bets are also in Shortlist above.'],
  ['streak', 'Streaks',
   'Our bets on players who went one way in four of their last five graded '
   + 'weeks, against the line they were quoted each week, counted as of that '
   + 'week and not as of today. Recent form, not an edge — nothing here is '
   + 'filtered on price. The side bet is still ours.'],
];
function v3RecView() {
  const k = V.recView || 'all';
  return V3RECVIEWS.filter(v => v[0] === k)[0] || V3RECVIEWS[0];
}

function v3RecPlayers(p, S) {
  if (!p || !(p.ou || []).length) return '';
  const full = v3RecFull();
  // OUR MODEL AND THE ADJUSTED MODEL, ON THE SAME BETS. `ou_week` picks its
  // side from the SERVED number, which on these markets is already pulled
  // toward the price — so the row this card has always shown was the
  // adjusted model wearing the model's name. Both are drawn now, and the
  // sportsbook stays the "needed to profit" COLUMN rather than becoming a
  // row: a book does not pick a side, and grading "always take the
  // favorite" would be a strategy nobody runs.
  const mkRows = (series, all, title) => {
    const r = (series || []).filter(x => x.bets).map(v3RecBetRow);
    if (!r.length) return [];
    r.unshift(['<b>' + title + '</b>', '', '', '', '']);
    if (all && all.bets) r.push(['All four', v3RecN(all.bets), '—', '—',
                                 v3RecCash(all.roi)]);
    return r;
  };
  // WHICHEVER VIEW IS SHOWING, ON ITS OWN BETS. `views.all` is the same
  // numbers the top-level keys carry, kept so a payload built before the
  // views existed still draws.
  const vw = v3RecView();
  const V_ = ((p.views || {})[vw[0]]) || {ou: p.ou, all: p.all,
                                          model: p.model,
                                          model_all: p.model_all, sides: 2};
  // Shortlist and Fades carry ONE series, because the rule picks the side.
  // Everyone and Streaks carry two, ours and the adjusted one, since there
  // the side is still ours to take.
  const two = V_.sides !== 1 && (V_.model || []).length;
  const rows = two
    ? (full ? mkRows(V_.model, V_.model_all, 'Our model')
                .concat(mkRows(V_.ou, V_.all, 'Adjusted model'))
            : mkRows(V_.model, V_.model_all, 'Our model'))
    : mkRows(V_.ou, V_.all, 'The rule’s own side');
  const a = (two ? V_.all : V_.all) || {};
  const mo = (two ? V_.model_all : V_.all) || {};
  const viewSeg = '<div class="seg seg--4" style="margin-top:8px">'
    + V3RECVIEWS.map(v => '<button data-v3recview="' + v[0]
        + '" aria-pressed="' + (v[0] === vw[0]) + '">' + esc(v[1])
        + '</button>').join('') + '</div>';
  const td = (p.td || []).map(x => esc(x.label) + ' ' + v3Pct(x.said, 1)
    + ' said'
    + (has(x.said_model) && Math.abs(x.said_model - x.said) >= 0.0005
       ? ' (model alone ' + v3Pct(x.said_model, 1) + ')' : '')
    + ' against ' + v3Pct(x.actual, 1) + ' actual (' + x.rows + ' rows)');
  // THE PRE-REGISTERED EDGE RULE, which is NOT the board's filters. Asked
  // directly whether this section was the shortlist, the fades and the
  // streaks, and it is none of them: those three are filters on the players
  // board — what the project would place, what is priced above our number,
  // and who has gone one way five weeks running — and this is a PRICE rule,
  // a bet only where the number beats the book's fair price by a fitted
  // margin. The heading said "our edge cleared the bar" and left a reader
  // to guess which edge.
  const edge = (p.edge || []).filter(x => x.bets).map(v3RecBetRow);
  const ea = p.edge_all || {};
  if (ea.bets) edge.push(['<b>All four</b>', '<b>' + v3RecN(ea.bets) + '</b>',
    '—', '—', v3RecCash(ea.roi)]);
  const thr = (p.edge || []).filter(x => x.bets && has(x.threshold_pp))
    .map(x => esc(x.label).toLowerCase() + ' ' + x.threshold_pp + 'pp');
  return '<div class="card" id="sb4">'
    + v3RecHead('02', 'Player bets: profit per $100 staked',
                'One bet is one player, in one game, in one category. The '
                + 'archive quotes alternate lines and counting each as its '
                + 'own bet turns one opinion into seventeen, so only the '
                + 'line nearest that player’s median counts.')
    + viewSeg
    + '<p class="help" style="margin-top:8px">' + esc(vw[2]) + '</p>'
    + (rows.length
       ? v3RecTable(['Category', 'Bets', 'Correct', 'Needed to profit',
                     'Per $100'], rows)
       : '<div class="empty">This filter took no bets in these weeks.</div>')
    + '<p class="help" style="margin-top:8px">'
    + 'Each category needs the rate in <b style="color:var(--ink)">Needed to '
    + 'profit</b> to break even at the price those bets were actually '
    + 'offered at — it is not the same 52.4% everywhere, because the prices '
    + 'are not.</p>'
    + (full
       ? '<p class="help" style="margin-top:6px">Ranges allow for players in '
         + 'the same game winning and losing together: '
         + (V_.ou || []).filter(x => x.bets).map(x => esc(x.label).toLowerCase()
             + ' ' + v3Money(x.lo) + ' to ' + v3Money(x.hi)).join('; ')
         + (a.bets ? '; all four ' + v3Money(a.lo) + ' to ' + v3Money(a.hi)
                   : '')
         + '.</p>'
       : '')
    + (two && mo.bets && a.bets && mo !== a
       ? '<p class="help" style="margin-top:6px">Over these bets the model '
         + 'alone returned ' + v3Money(mo.roi) + ' per $100 against the '
         + 'adjusted number’s ' + v3Money(a.roi) + '. Blending toward the '
         + 'price helps the touchdown markets and has not helped here.</p>'
       : '')
    + (full
       ? '<p class="help" style="margin-top:6px">Settled the way a book '
         + 'settles: an under is paid at the under’s own price, a player who '
         + 'did not play is void, and one who played and recorded nothing is '
         + 'graded at zero.</p>'
       : '')
    + (full && td.length ? '<p class="help" style="margin-top:6px">Touchdowns, '
       + 'predicted against actual: ' + td.join(' · ') + '.</p>' : '')
    + '</div>'
    + (edge.length
       ? '<div class="card" id="sb5">'
         + v3RecHead('03', 'The same bets, only where the price was wrong '
                     + 'enough',
                     'A bet only where our number beats the sportsbook’s own '
                     + 'fair price by a margin fitted on earlier seasons, '
                     + 'taken at the price of the side bet.')
         + v3RecTable(['Category', 'Bets', 'Correct', 'Needed to profit',
                       'Per $100'], edge)
         + '<p class="help" style="margin-top:8px"><b style="color:'
         + 'var(--ink)">This is a price rule, not the board’s filters.</b> '
         + 'Shortlist, Fades and Streaks on the Players tab are different '
         + 'things — what this project would place, what is priced above our '
         + 'number, and who has gone one way five weeks running. This is '
         + 'none of them: it bets any player whose price is far enough off '
         + 'our number'
         + (thr.length ? ', by ' + thr.join(', ') : '') + '.</p>'
         + (full
            ? '<p class="help" style="margin-top:6px">Ranges: '
              + (p.edge || []).filter(x => x.bets).map(x =>
                  esc(x.label).toLowerCase() + ' ' + v3Money(x.lo) + ' to '
                  + v3Money(x.hi)).join('; ')
              + (ea.bets ? '; all four ' + v3Money(ea.lo) + ' to '
                 + v3Money(ea.hi) : '')
              + '.</p>'
            : '')
         + '</div>'
       : '');
}

function v3RecordPage() {
  const S = DATA.scorecard || {};
  const ws = S.played || [];
  if (!ws.length || !S.ranges) {
    return '<div class="wrap"><h1 class="h1">Record</h1>'
      + '<div class="card"><p class="lede" style="font-size:15px">Nothing '
      + 'graded yet this season.</p></div></div>';
  }
  const r = v3RecRange(S);
  const block = S.ranges[r[0] + '-' + r[1]] || {};
  const g = block.games, p = block.players;
  const span = r[0] === r[1] ? 'Week ' + r[0] : 'Weeks ' + r[0] + '–' + r[1];
  const gw = (S.game_weeks || []);
  const inRange = gw.filter(w => w >= r[0] && w <= r[1]);
  return '<div class="wrap">'
    + '<div class="eyebrow">' + (S.season || '') + ' season · '
    + esc(span) + '</div>'
    + '<h1 class="h1">Holding the model to account</h1>'
    + '<p class="lede">' + (g && g.n ? g.n + ' games' : 'No frozen games')
    + ' · what it picked, what happened, and what it would have paid.</p>'
    + v3RecPicker(S)
    + v3RecBoard(g, p, S)
    // THE PROVENANCE, ABOVE THE NUMBERS RATHER THAN UNDER THEM. A reader who
    // reaches the tables first has already formed a view of what they mean.
    + '<div class="card recnote">'
    + '<div class="eyebrow">Where these come from</div>'
    + '<p class="help" style="margin-top:6px">'
    + (inRange.length
       ? '<b style="color:var(--ink)">Game picks were written down before '
         + 'kickoff</b> and are the numbers that were on the card.'
       : '<b style="color:var(--ink)">No game picks in this range</b> were '
         + 'recorded before kickoff.')
    + ' <b style="color:var(--ink)">Player results were rebuilt afterwards</b> '
    + 'with the current model against archived prices — a test of the '
    + 'model on weeks it did not serve, not a record of bets anyone could '
    + 'have placed.'
    + ((S.missing || []).length
       ? ' Week' + ((S.missing || []).length > 1 ? 's ' : ' ')
         + (S.missing || []).map(x => x.week).join(' and ')
         + ' have no game record: ' + esc(S.missing[0].why) + '.'
       : '')
    + '</p></div>'
    + v3RecGames(g, S) + v3RecPlayers(p, S) + v3RecByPlayer(p, S, r[0], r[1])
    + '</div>';
}

function v3AnglesPage() {
  const A = DATA.angles || {};
  const all = (A.rows || []).slice();
  const be = has(A.break_even) ? A.break_even : 0.5238;
  if (!all.length) {
    return '<div class="wrap"><h1 class="h1">Angles</h1>'
      + '<div class="card"><p class="lede" style="font-size:15px">Nothing '
      + 'measured yet. This needs a graded schedule on disk.</p></div></div>';
  }
  const yr = v3AngleYears();
  const first = yr.first, last = yr.last, from = yr.from;
  // ONE CLUB'S OWN GAMES, where a team is chosen. A whole-game condition is
  // 50.00% league-wide by arithmetic and a real record for one team: `On
  // grass` is 1605-1605 for the league and 67-72 for San Francisco.
  const teams = v3AngleTeams();
  const team = (V.angleTeam && teams.indexOf(V.angleTeam) >= 0)
    ? V.angleTeam : '';
  // LEAGUE OR THIS CLUB, once one is chosen. Choosing a club used to BE the
  // switch, and there was no way back to the league record short of clearing
  // the selection and finding it again in a list of thirty-two. The segment
  // keeps the selection and swaps the reading instead, so one open row can be
  // read both ways in two taps. `team` is the default, which is exactly what
  // choosing a club did before this existed.
  //
  // With no club chosen there is nothing to compare against, so the control
  // is absent rather than present and inert, and `scope` is the league.
  const scope = (team && V.angleScope !== 'league') ? team : '';
  const since = r => v3AngleSince(r, from, be, scope);
  const seasonOf = r => scope
    ? v3AngleTeamYear(r, scope, DATA.season) : r.season;
  const baseOf = r => v3AngleBase(r, from, scope);

  // THE KINDS, IN THE ORDER THE PAYLOAD NAMES THEM. Collected from the rows
  // instead -- which is what this did -- the list reordered itself whenever a
  // record moved, because `rows` arrives sorted by percentage.
  const seen = {};
  all.forEach(r => { if (r.cat) seen[r.cat] = 1; });
  const cats = ((A.cats && A.cats.length) ? A.cats : Object.keys(seen))
    .filter(c => seen[c]);
  const cat = (V.angleCat && cats.indexOf(V.angleCat) >= 0)
    ? V.angleCat : 'all';
  // MATCHED ON THE NAME, THE DESCRIPTION AND THE KIND. Someone looking for
  // "bye" should find "Off a bye"; someone looking for "rest" should find it
  // through the category as well as the label.
  const q = (V.angleQ || '').trim().toLowerCase();
  const hit = r => !q
    || (r.label || '').toLowerCase().indexOf(q) >= 0
    || (r.plain || '').toLowerCase().indexOf(q) >= 0
    || (r.cat || '').toLowerCase().indexOf(q) >= 0;
  const shown = (cat === 'all' ? all : all.filter(r => r.cat === cat))
    .filter(hit)
    .map(r => ({ r: r, run: since(r), base: baseOf(r) }));

  const pct = d => (d && d.n) ? d.pct : -1;
  const SORTS = {
    season: o => pct(seasonOf(o.r)),
    all: o => pct(o.run),
    name: o => o.r.label,
  };
  const key = SORTS[V.angleSort] ? V.angleSort : 'season';
  const dir = V.angleDesc ? -1 : 1;
  const rows = shown.slice().sort((a, b) => {
    const x = SORTS[key](a), y = SORTS[key](b);
    if (x < y) return -dir;
    if (x > y) return dir;
    // One stable tiebreak, so the order is the same on every build.
    return a.r.label < b.r.label ? -1 : 1;
  });

  const games = A.games || {};
  const arrow = k => (key === k ? (V.angleDesc ? ' \u2193' : ' \u2191') : '');
  const head = (k, label) => '<button class="ahead" data-v3anglesort="'
    + k + '" aria-pressed="' + (key === k) + '">' + label + arrow(k)
    + '</button>';

  const byId = {};
  all.forEach(r => { byId[r.id] = r; });
  const detail = r => v3AngleGames(r, games, scope,
    v3BaseLine(since(r), baseOf(r)) + v3MirrorLine(r, byId, since, scope));

  return '<div class="wrap">'
    + '<h1 class="h1">Angles</h1>'
    + '<p class="lede">Betting patterns people follow \u2014 \u201cteams '
    + 'bounce back after a beating\u201d, that sort of thing. Each row is how '
    + 'often that pattern actually beat the point spread. Tap one to see this '
    + 'season\u2019s games.</p>'
    + '<div class="pbar pbar--free">'
    // ROW ONE IS WHO, ROW TWO IS HOW TO SLICE, ROW THREE IS SINCE WHEN --
    // the same three on a game's angles, so a reader who has learned one page
    // has learned the other. Only row one differs, and only because
    // thirty-two teams need a list where a game's two need three buttons.
    + '<div class="pbar__row">'
    + '<div class="search"><input type="search" data-v3angleq '
    + 'placeholder="Search patterns" value="' + esc(V.angleQ || '') + '" '
    + 'aria-label="Search patterns">'
    + (V.angleQ ? '<button class="searchx" data-v3angleclear="1" '
        + 'aria-label="Clear search">\u2715</button>' : '')
    + '</div>'
    + '<div class="picker mxsel"><select data-v3angleteam '
    + 'aria-label="Show one team\u2019s record">'
    + ['<option value=""' + (team ? '' : ' selected') + '>All teams</option>']
        .concat(teams.map(t => '<option value="' + esc(t) + '"'
          + (t === team ? ' selected' : '') + '>' + esc(t) + '</option>'))
        .join('')
    + '</select></div></div>'
    + '<div class="pbar__row pbar__row--two">'
    + '<div class="picker mxsel"><select data-v3anglecat '
    + 'aria-label="Filter by kind">'
    + ['all'].concat(cats).map(c => '<option value="' + esc(c) + '"'
        + (c === cat ? ' selected' : '') + '>'
        + (c === 'all' ? 'All kinds' : esc(c)) + '</option>').join('')
    + '</select></div>'
    // ABSENT UNTIL THERE IS A CLUB TO COMPARE. With none chosen the league
    // record is the only one there is, and a two-way control with one live
    // side is a control that teaches the wrong thing.
    + (team ? '<div class="seg seg--2" style="flex:1">'
       + v3Seg('v3anglescope', [['league', 'League'], ['team', 'Team']],
               scope ? 'team' : 'league')
       + '</div>' : '')
    + '</div>'
    + v3YearSlider(first, last, from)
    + '</div>'
    + '<div class="card" style="margin-top:0">'
    + '<div class="arow arow--h">'
    + head('name', 'Pattern')
    + head('season', 'Yr ATS')
    + head('all', '\u2019' + String(from).slice(2) + '+ ATS')
    + '</div>'
    + (rows.length ? '' : '<p class="help" style="padding:12px 0">Nothing '
       + 'matches ' + (q ? '\u201c' + esc(V.angleQ) + '\u201d' : 'that')
       + '.</p>')
    + rows.map(o => {
        const r = o.r, a = o.run;
        const good = a && a.clears;
        const open = V.angleOpen === r.id;
        return '<button class="arow' + (open ? ' arow--on' : '')
          + '" data-v3angle="' + esc(r.id) + '" aria-expanded="' + open + '">'
          + '<span class="arow__l">' + esc(r.label)
          + (r.mined ? ' <i class="tag tag--warn">added</i>' : '')
          + (scope ? '' : v3WholeTag(r)) + v3MirrorTag(r, byId)
          + v3SurpriseTag(seasonOf(r), a) + '</span>'
          + '<span class="num"><b>' + v3AnglePct(seasonOf(r)) + '</b>'
          + '<i>' + v3AngleRec(seasonOf(r)) + '</i></span>'
          // THE RECORD UNDER THE PERCENTAGE, the same as the column beside
          // it. This used to carry the interval instead, which meant the two
          // number columns read differently and the games count needed a
          // third column to say what "1250-1180" already says.
          + '<span class="num' + (good ? ' good' : '') + '"><b>'
          + v3AnglePct(a) + '</b><i>' + v3AngleRec(a) + '</i></span>'
          + '</button>'
          + (open ? detail(r) : '');
      }).join('')
    + '</div>'
    + '<div class="card" style="margin-top:12px">'
    + '<div class="name">Why none of them is a system</div>'
    + '<p class="lede" style="font-size:15px;line-height:20px">Winning half '
    + 'your bets loses money, because the bookmaker keeps a cut: a split has '
    + 'to clear <b style="color:var(--ink)">' + (be * 100).toFixed(2)
    + '%</b> just to break even. At three to five hundred games an interval '
    + 'runs eight points wide \u2014 wide enough to contain both \u201cno '
    + 'edge\u201d and \u201ca good edge\u201d. Every angle here has been '
    + 'public for decades, which is the other half of it: the price already '
    + 'knows.</p>'
    // THE DENOMINATOR IS THE FINDING. The headline card that carried this
    // came off the top of the page for space; the count of patterns measured
    // has to survive somewhere, or a winner reads as a system.
    // HOW MANY WERE MEASURED STAYS; HOW TO READ THE TABLE FOLDS. The count
    // is the finding — a reader seeing four splits has no idea that seventy
    // eight others were measured beside them and said nothing — and the rest
    // explains the columns to somebody who has already read it once.
    + '<p class="help">With ' + all.length + ' patterns measured, two or '
    + 'three will look good on luck alone, so even a winner here would not '
    + 'mean much. Nothing is dropped for going cold either: a split that '
    + 'reverted is the most useful row on this page, and a board with the '
    + 'losers removed is a board of survivors.</p>'
    + v3Fold('How to read this table', v3BaseNote()) + '</div>'
    + '</div>';
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
           market: V.market,
           // WHICH ANGLE IS OPEN IS PART OF THE SCREEN. The browser's own
           // back gesture used to land on the angles board with everything
           // closed, so the row you had been reading was gone. `backTab`
           // rides along for the same reason: Back has to mean the same
           // thing whether you press the app's chevron or the phone's.
           angleOpen: V.angleOpen, backTab: V.backTab,
           backAngle: V.backAngle };
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
  // WHAT WAS BEING TYPED INTO, so it can be typed into again.
  //
  // `innerHTML` destroys the element that has focus. A search box that
  // re-renders the screen on every keystroke therefore loses the caret after
  // each character — you type "bye" and get "b", because the second and third
  // land nowhere. Recorded by the control's own `data-v3*` attribute, which
  // is the one thing about it that survives the redraw.
  const typing = v3Typing();
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
  //
  // `V.top === 'section'` is a THIRD case, for switching section inside a
  // game. Zero is wrong there: it would land you above the matchup card with
  // the section you just asked for still below the fold, so you would scroll
  // down to reach the thing you tapped for. This puts the pinned bar at the
  // top of the pane, which is exactly where it comes to rest anyway, and the
  // new section starts immediately under it.
  // THE PINNED BAR'S HEIGHT, PUBLISHED FOR WHATEVER PINS UNDER IT.
  //
  // The matchup's own bar sticks below this one, and its offset has to be the
  // real height: the game bar grows a line when a long matchup name wraps, and
  // a hard-coded number left the second bar either overlapping it or floating
  // clear of it. Measured after the re-render, so it is the new layout, and
  // `offsetHeight` rather than a rect because it is a height either way and
  // does not care whether the bar is currently stuck.
  if (scroll) {
    // Cleared before anything is measured: it is derived from the layout, so
    // last render's value would be counted as part of this one's.
    if (app.style) app.style.paddingBottom = '0px';
    const gb = document.querySelector && document.querySelector('.gtabs');
    scroll.style && scroll.style.setProperty
      && scroll.style.setProperty('--gtabs-h',
           (gb && gb.offsetHeight ? gb.offsetHeight : 0) + 'px');
  }
  if (scroll) {
    if (V.top === 'section') {
      // THE PANE IS RESTED AT ZERO BEFORE THE BAR IS MEASURED, because the
      // bar is sticky. Once you have scrolled past it the bar is PINNED, so
      // its rect already sits at the pane's top edge and `rect.top -
      // pane.top` is zero — adding that to the offset you were at returned
      // the offset you were at. The scroll was a no-op in the one case the
      // pinned bar exists for: you tapped Outcome from deep inside Notes and
      // stayed deep inside Notes' old offset.
      //
      // At zero the bar is back in the normal flow, where its rect is its
      // layout position. Both writes happen in the same task, so there is no
      // paint between them and nothing flickers.
      scroll.scrollTop = 0;
      // WHICHEVER BAR THIS SCREEN LEADS WITH. The game screen and the props
      // board lead with `.gtabs` and stack `.pbar` under it; the games board
      // has only `.pbar--free`. The two never appear together, so falling
      // back is the whole rule — and two queries rather than one selector
      // list because the harness memoises by selector string, and a list
      // would hand back a node the geometry was never installed on.
      const bar = document.querySelector
        && (document.querySelector('.gtabs')
            || document.querySelector('.pbar--free'));
      let at = 0;
      if (bar && bar.getBoundingClientRect && scroll.getBoundingClientRect) {
        // Measured after the re-render, so it is the NEW layout, and relative
        // to the pane rather than the window — the app header sits outside
        // the scroller and would otherwise be counted.
        at = bar.getBoundingClientRect().top
             - scroll.getBoundingClientRect().top;
      } else if (bar && has(bar.offsetTop)) {
        at = bar.offsetTop;
      }
      // MAKE THE ROOM RATHER THAN GIVE UP ON IT.
      //
      // Filtering to Upsets leaves one game card, and a page that short
      // cannot be scrolled far enough to bring the bar to the top — the
      // browser clamps, and the bar came to rest a third of the way down with
      // the heading sliced off above it. Landing at zero instead was tidier
      // but it made the SHORT filter behave differently from every other one:
      // Agrees pinned the bar, Upsets showed the whole page, and the same tap
      // did two things.
      //
      // So the shortfall becomes padding under the content. `max` is where
      // the pane can scroll to; adding exactly `at - max` makes the new
      // maximum `at`, which is the offset being asked for. Every filter then
      // lands the same way whatever it returns.
      //
      // Recomputed on EVERY render, not just this branch. Left over from a
      // previous filter it would be scrollable dead space; removed only here,
      // a later re-render would drop it under a reader standing on it.
      const max = (has(scroll.scrollHeight) && has(scroll.clientHeight))
        ? scroll.scrollHeight - scroll.clientHeight : null;
      if (bar && max != null && at > max && app.style)
        app.style.paddingBottom = (at - max) + 'px';
      scroll.scrollTop = Math.max(0, at);
    } else {
      scroll.scrollTop = V.top ? 0 : y;
    }
  }
  // AFTER THE SCROLL, because focusing an element scrolls it into view and
  // would otherwise undo the position just restored. `preventScroll` where
  // the browser has it; the ordering is what makes it right where it does not.
  v3Refocus(typing);
  V.top = false;
  v3Save();
}

// The focused control's `data-v3*` attribute and caret, or null.
function v3Typing() {
  const d = typeof document === 'undefined' ? null : document;
  const a = d && d.activeElement;
  if (!a || !a.attributes || a.selectionStart == null) return null;
  for (let i = 0; i < a.attributes.length; i++) {
    const n = a.attributes[i].name;
    if (n.indexOf('data-v3') === 0) {
      try {
        return { attr: n, start: a.selectionStart, end: a.selectionEnd };
      } catch (e) { return { attr: n, start: null, end: null }; }
    }
  }
  return null;
}

function v3Refocus(t) {
  if (!t || typeof document === 'undefined' || !document.querySelector) return;
  const el = document.querySelector('[' + t.attr + ']');
  if (!el || !el.focus) return;
  try { el.focus({ preventScroll: true }); } catch (e) { el.focus(); }
  if (t.start != null && el.setSelectionRange) {
    try { el.setSelectionRange(t.start, t.end); } catch (e) { /* not a text field */ }
  }
}

// One delegated listener. Every control is a `data-v3*` attribute, so a
// control that is added and never wired here does nothing at all rather than
// throwing — which is why `test_every_v3_control_is_handled` exists.
const V3CLICKS = ['v3tab', 'v3mkt', 'v3sort', 'v3filter', 'v3gfilter', 'v3gbasis', 'v3pick', 'v3more',
                  'v3keep', 'v3unkeep', 'v3savedfilter', 'v3pickopen',
                  'v3game', 'v3gamestep', 'v3back', 'v3gtab', 'v3cat', 'v3type',
                  'v3stake', 'v3ask', 'v3askdefault', 'v3open', 'v3dir',
                  'v3fav', 'v3clear', 'v3sheet', 'v3close', 'v3drop', 'v3clearq',
                  'v3half', 'v3metric', 'v3boardgame', 'v3anglesort', 'v3angle',
                  'v3anglegame', 'v3angleclear', 'v3anglescope', 'v3pastall',
                  'v3pastn', 'v3tlall', 'v3tln',
                  'v3gasort', 'v3gateam', 'v3gascope', 'v3gangle',
                  'v3sortpick',
                  'v3recfull', 'v3recwho', 'v3recseries', 'v3recmore',
                  'v3recqx', 'v3recview', 'v3recopen', 'v3recsort'];

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
  if (t.getAttribute('data-v3anglefrom') != null) {
    // A RANGE FIRES `input` ALL THE WAY THROUGH A DRAG and `change` on
    // release. Wired to `change` alone the year sat still until you let go.
    // Only the LABEL is rewritten here: a full render replaces the slider
    // being dragged, and a pointer loses the element it was holding.
    V.angleFrom = Number(t.value) || 0;
    const labs = document.querySelectorAll
      ? document.querySelectorAll('[data-v3yrlab]') : [];
    for (let i = 0; i < labs.length; i++) labs[i].textContent = V.angleFrom;
    return;
  }
  if (t.getAttribute('data-v3recq') != null) {
    // Same shape as the angles search below, and for the same reason: the
    // Record page's per-player table has no single rows container to swap,
    // so this re-renders and relies on `render` putting the caret back.
    V.recQ = t.value || '';
    V.recShown = 40;
    render();
    return;
  }
  if (t.getAttribute('data-v3angleq') != null) {
    // A SEARCH BOX FIRES `input`, NOT `change`. Wired into the change
    // listener it did nothing until the field lost focus, which on a phone is
    // never — you type and the board sits there.
    //
    // This one re-renders rather than patching a list in place: the angles
    // board has no single rows container to swap. That DOES replace the field
    // being typed into, which cost the caret on every keystroke until
    // `render` learned to put the focus back.
    V.angleQ = t.value || '';
    V.angleOpen = null;
    render();
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
  } else if (t.getAttribute('data-v3anglefrom') != null) {
    V.angleFrom = Number(t.value) || 0; render();
  } else if (t.getAttribute('data-v3angleteam') != null) {
    // A SELECT FIRES `change`, NOT `click`. Wired to the click listener it
    // drew and highlighted correctly and filtered nothing.
    V.angleTeam = t.value || ''; V.angleOpen = null; V.top = 'section';
    render();
  } else if (t.getAttribute('data-v3anglecat') != null) {
    // A `<select>` fires `change`, not `click`. Wired only into the click
    // table it drew correctly, highlighted correctly and filtered nothing.
    V.angleCat = t.value; V.angleOpen = null; V.top = 'section'; render();
  } else if (t.getAttribute('data-v3gacat') != null) {
    // A `<select>` again, so `change` and not the click table. No `V.top`
    // here: the game's other angle controls keep the reader where they were,
    // and this one sits in the same bar.
    V.gaCat = t.value; V.gaOpen = null; render();
  } else if (t.getAttribute('data-v3scfrom') != null) {
    // A `<select>`, so `change`. Both ends are kept in order here as well as
    // in the renderer: a reader who drags the start past the end means one
    // week, not an empty range.
    //
    // NO `V.top` HERE. The Record page has no `.gtabs` or `.pbar--free`, so
    // that branch measures nothing, falls back to zero and scrolls the pane
    // to the heading — which, on a page whose tables are below the fold,
    // looks exactly like the picker having done nothing.
    V.scFrom = Number(t.value);
    if (has(V.scTo) && V.scTo < V.scFrom) V.scTo = V.scFrom;
    render();
  } else if (t.getAttribute('data-v3scto') != null) {
    V.scTo = Number(t.value);
    if (has(V.scFrom) && V.scFrom > V.scTo) V.scFrom = V.scTo;
    render();
  } else if (t.getAttribute('data-v3sortsel') != null) {
    V.sort = t.value; render();
  } else if (t.getAttribute('data-v3gameto') != null) {
    // The TAB is kept. Jumping to the next game's notes when you were reading
    // its score ladder is the same annoyance in a different place.
    //
    // And so is the PLACE. `true` sent you to the top of the new game, above
    // the matchup card, with the section you had asked to keep below the fold
    // — the control is pinned now, so the reader has not moved and the page
    // should not either. `'section'` lands the new game's same section under
    // the bar you just used.
    V.game = t.value; V.open = null; V.answer = '';
    V.top = 'section'; render();
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
      V.backTab = null; V.backAngle = null;
      // A week the destination cannot show is dropped rather than carried
      // into a screen that would render it empty.
      if (V.week != null && v3Weeks().indexOf(V.week) < 0) V.week = null;
      break;
    }
    // The market changes; the GAME FILTER DOES NOT. Looking at one game and
    // clicking between markets should not mean re-picking the game each time.
    //
    // ALL THREE START AT THE TOP OF WHAT THEY JUST BUILT. Keeping the offset
    // was right when these controls sat above the board and went with it: you
    // were in one list and stayed where you were. Pinned, they changed the
    // list UNDER a bar that does not move, so tapping Rush from forty rows
    // down landed you forty rows into a different market — past the green CLV
    // line that had just changed, and past whatever the top of the new list
    // was, which is the part you asked for.
    //
    // `'section'` rather than `true`: zero is the top of the PAGE, above the
    // title and the counts, and these controls are not navigation.
    case 'v3mkt': V.market = v; V.shown = V3SHOW; V.top = 'section'; break;
    case 'v3sort': V.sort = v; break;
    case 'v3filter': V.filter = v; V.shown = V3SHOW; V.top = 'section'; break;
    case 'v3gfilter': V.gfilter = v; V.top = 'section'; break;
    case 'v3gbasis': V.gbasis = v; V.top = 'section'; break;
    case 'v3more': V.shown = 1e9; break;
    // Tapping the open row closes it: one open at a time, so the board does
    // not turn into a wall of detail panels you have to close individually.
    case 'v3open': V.open = V.open === v ? null : v; break;
    case 'v3dir': V.desc = !V.desc; break;
    case 'v3clearq': V.q = ''; V.shown = V3SHOW; break;
    case 'v3half': V.half = v; break;
    // The group filter changes the list under a pinned bar, so it
    // starts at the top of what it just built, like every other one.
    case 'v3metric': V.metric = v; V.top = 'section'; break;
    // The board's steppers CHANGE THE FILTER; they do not open the game. An
    // empty value is "all games", which is what back means here.
    case 'v3boardgame': V.game = v || null; V.shown = V3SHOW; V.open = null;
      break;
    // A column header. Tapping the one already sorted flips it, which is
    // what a table does and saves a second control for direction.
    case 'v3anglesort':
      if (V.angleSort === v) V.angleDesc = !V.angleDesc;
      else { V.angleSort = v; V.angleDesc = (v !== 'name'); }
      break;
    case 'v3angleclear': V.angleQ = ''; break;
    // THE RECORD PAGE'S OWN CONTROLS. None of them set `V.top`: the picker
    // bar is pinned, so the reader has not moved and the page should not
    // either — and on a page whose tables sit below the fold, a jump to the
    // heading reads exactly like the control having done nothing. That is
    // the mistake the week picker shipped with.
    case 'v3recfull': V.recFull = v === '1'; break;
    // The per-player cut, and the list it draws. `recShown` goes back to its
    // first page, because a reader who has paged forty rows into one cut did
    // not ask to land forty rows into another.
    case 'v3recwho': V.recWho = v; V.recShown = 40; break;
    case 'v3recseries': V.recSeries = v; V.recShown = 40; break;
    case 'v3recmore': V.recShown = Number(v); break;
    case 'v3recqx': V.recQ = ''; V.recShown = 40; break;
    case 'v3recview': V.recView = v; break;
    // Tapping the open player closes him, which is what the board's own
    // row-opener does.
    case 'v3recopen': V.recOpen = V.recOpen === v ? null : v; break;
    // A column header. Tapping the one already sorted flips it, which is
    // what a table does; a new column starts descending except the name,
    // where A-Z is what anybody means by sorting it.
    case 'v3recsort':
      if (V.recSort === v) V.recSortDesc = !V.recSortDesc;
      else { V.recSort = v; V.recSortDesc = (v !== 'name'); }
      break;
    // FETCHED ON THE TAP, not on the render: the full record for a market is
    // most of a megabyte and almost nobody opens it. The re-render is the
    // callback's job because the file may already be cached, in which case
    // this is synchronous and the render below it would draw the old panel.
    // The window the history panel reads over. 'all' is null rather than a
    // count, so a player with more weeks than the control offers still gets
    // every one of them when it is picked.
    case 'v3pastn': V.pastN = (v === 'all') ? null : parseInt(v, 10); break;
    case 'v3pastall': {
      const mk = v3PastMarket();
      V.pastAll = v;
      if (mk) v3PastAll(mk, () => render());
      break;
    }
    // The window the team panel reads over, and the tap that fetches the rest
    // of the record. Both teams on the card read the same window, so this is
    // one number rather than one per side.
    case 'v3tln': V.tlN = (v === 'all') ? null : parseInt(v, 10); break;
    case 'v3tlall':
      V.tlAll = v;
      v3TLFetch(() => render());
      break;
    // The reading changes under a pinned bar, so the board starts at
    // the top of what it just rebuilt -- the same as the kind and the
    // club beside it.
    case 'v3anglescope':
      V.angleScope = v; V.angleOpen = null; V.top = 'section';
      break;
    case 'v3gasort':
      if (V.gaSort === v) V.gaDesc = !V.gaDesc;
      else { V.gaSort = v; V.gaDesc = (v !== 'name'); }
      break;
    case 'v3gateam': V.gaTeam = v; V.gaOpen = null; break;
    case 'v3gascope': V.gaScope = v; V.gaOpen = null; break;
    case 'v3gangle': V.gaOpen = (V.gaOpen === v) ? null : v; break;
    case 'v3anglegame': {
      const bits = String(v).split('|');
      V.tab = 'games'; V.game = bits[0]; V.gameTab = 'odds';
      // A game the ARCHIVE holds is reached through the week picker; one on
      // the live board is `null`, which is what "This week" means everywhere
      // else. `v3AngleBoard` decides which, by looking for the game rather
      // than by comparing week numbers — on a Monday, Sunday's games are
      // still this week's and are not in the archive yet.
      V.week = bits[1] === '' ? null : Number(bits[1]);
      // WHERE BACK LEADS. Arriving from a fixture, "back" means the angles
      // board with that angle still open, not the games list — a screen this
      // reader has not been on and did not ask for.
      V.backTab = 'angles'; V.backAngle = bits[2] || null;
      V.top = true;
      break;
    }
    // Tapping the open one closes it: one at a time, or the board turns into
    // a wall of fixture lists you have to close individually.
    case 'v3angle': V.angleOpen = (V.angleOpen === v) ? null : v; break;
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
    case 'v3game': V.tab = 'games'; V.game = v; V.gameTab = 'odds';
      V.cat = 'all'; V.answer = ''; V.answerErr = ''; V.q2 = '';
      V.backTab = null; V.backAngle = null;
      V.answerLive = false; break;
    // STEPPING between games is not leaving the page the way tapping a game
    // in the list is: you are mid-read, and the arrow is beside the section
    // bar. So unlike `v3game` this keeps `V.gameTab` and lands on that same
    // section, which is what the sibling `<select>` in the same control does.
    case 'v3gamestep': V.tab = 'games'; V.game = v; V.open = null;
      V.cat = 'all'; V.answer = ''; V.answerErr = ''; V.q2 = '';
      V.answerLive = false; V.top = 'section'; break;
    case 'v3back':
      V.game = null; V.answer = '';
      if (V.backTab) {
        V.tab = V.backTab; V.angleOpen = V.backAngle;
        V.backTab = null; V.backAngle = null;
        // The angles board offers no weeks, so a week carried in from the
        // game would render nothing and could not be cleared.
        if (v3Weeks().indexOf(V.week) < 0) V.week = null;
      }
      break;
    case 'v3gtab':
      V.gameTab = v3GTab(v);
      // Start at the top of what you asked for. Keeping the offset left you
      // deep inside a section you had not read, at a position that belonged
      // to the one you left.
      V.top = 'section';
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
    // THE DEFAULT QUESTION goes to the model, unlike the chips beside it.
    // `v3AskSend` renders on its own when the answer lands, and again here
    // so the box shows it is thinking in the meantime.
    case 'v3askdefault':
      if (!V.asking) v3AskSend(v, V3ASK_DEFAULT);
      break;
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
