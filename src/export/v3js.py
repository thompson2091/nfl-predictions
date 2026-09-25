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

const V3KEY = 'picksix.v3';
const V3SHOW = 25;

const V = Object.assign({
  tab: 'week', market: 'any', sort: 'likely', filter: 'all',
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
      betType: V.betType, stake: V.stake, game: V.game }));
  } catch (e) { /* private window, blocked storage — the app still works */ }
}

// ── small helpers ───────────────────────────────────────────────────────

const v3Pct = p => !has(p) ? '—' : (p < 0.1 ? (p * 100).toFixed(1) : Math.round(p * 100)) + '%';
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

function v3Fetch(market, week, then) {
  const k = market + ':' + week;
  if (V3CACHE[k]) { then(V3CACHE[k]); return; }
  const path = (DATA.history_path || 'data/h-{market}-{week}.json')
    .replace('{market}', market).replace('{week}', String(week));
  fetch(path).then(r => r.ok ? r.json() : []).catch(() => [])
    .then(rows => { V3CACHE[k] = rows || []; then(V3CACHE[k]); });
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

function v3Week() {
  const cur = V3MKT.filter(m => m[0] === V.market)[0] || V3MKT[0];
  const mkts = V3MKT.filter(m => served(m[0])).map(m =>
    '<button class="mkt" data-v3mkt="' + m[0] + '" aria-pressed="'
    + (m[0] === V.market) + '">' + esc(m[1]) + '</button>').join('');

  const sortHelp = V.sort === 'likely'
    ? 'Highest chance first. Likely picks usually pay less.'
    : 'Where the price is best compared with our chance. Riskier, bigger payouts.';
  const filterHelp = {
    all: '',
    short: 'Our shortlist: the picks this project would actually place.',
    fade: 'Players priced above our number. These are bets to LEAVE ALONE, '
        + 'not bets to place — no book posts the other side.',
  }[V.filter] || '';

  return '<div class="wrap">'
    + v3PastBanner()
    + '<h1 class="h1">' + esc(V.week == null ? cur[3] : 'Week ' + V.week) + '</h1>'
    + '<p class="lede">Our number next to the sportsbook’s, in plain '
    + 'English.' + (V.week == null ? ' Tap + to add a player to your picks.' : '')
    + '</p>'
    + '<div class="mkts">' + mkts + '</div>'
    + '<p class="help">' + esc(cur[2]) + '</p>'
    + v3Watch()
    + '<div class="seg seg--3">'
    + v3Seg('v3filter', [['all', 'Everyone'], ['short', 'Shortlist'],
                         ['fade', 'Fades']], V.filter)
    + '</div>'
    + (filterHelp ? '<p class="help">' + esc(filterHelp) + '</p>' : '')
    + '<div class="seg seg--2">'
    + v3Seg('v3sort', [['likely', 'Most likely'], ['value', 'Best value']], V.sort)
    + '</div>'
    + '<p class="help">' + esc(sortHelp) + '</p>'
    + '<div class="list" id="v3rows">' + v3Rows() + '</div>'
    + v3Explainer()
    + '</div>';
}

function v3Seg(attr, opts, on) {
  return opts.map(o => '<button data-' + attr + '="' + o[0] + '" aria-pressed="'
    + (o[0] === on) + '">' + esc(o[1]) + '</button>').join('');
}

function v3Sorted(rows) {
  const out = rows.slice();
  if (V.sort === 'value') {
    out.sort((a, b) => (ev100(b) == null ? -1e9 : ev100(b))
                     - (ev100(a) == null ? -1e9 : ev100(a)));
  } else {
    out.sort((a, b) => (betProb(b) || 0) - (betProb(a) || 0));
  }
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
    let rows = v3Graded(mk, V3CACHE[k]).filter(r => r.priced);
    if (V.game) rows = rows.filter(r => r.gameId === V.game
                                     || fixtureOf(r.gameId) === V.game);
    if (!rows.length) return '<div class="empty">No priced picks recorded '
      + 'for week ' + V.week + ' on this market.</div>';
    return v3Sorted(rows).slice(0, V.shown).map(v3PastRow).join('')
      + v3MoreBtn(rows.length);
  }

  let rows = rowsFor(V.market, V.filter === 'all' ? null : V.filter)
    .filter(r => r.priced && !r.blocked);
  if (V.game) rows = rows.filter(r => r.gameId === V.game
                                   || fixtureOf(r.gameId) === V.game);
  if (!rows.length) {
    return '<div class="empty">' + (V.filter === 'fade'
      ? 'Nothing on this market is priced far enough above our number to '
        + 'flag this week.'
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
  const warn = row.status && row.status !== 'ACT'
    ? '<span class="tag tag--warn">' + esc(row.status) + '</span>' : '';
  return '<div class="row"><div class="row__m">'
    + '<div class="row__t"><div style="min-width:0">'
    + '<div class="name">' + esc(row.player) + '</div>'
    + '<div class="sub">' + esc(v3Fixture(row)) + '</div>'
    + (line ? '<div class="line">' + esc(line) + '</div>' : '')
    + '</div><div class="chance"><b class="num">' + v3Pct(betProb(row))
    + '</b><span class="eyebrow">Our chance</span></div></div>'
    + '<div class="tags">'
    + (has(row.odds) ? '<span class="pill num">' + v3Dash(american(row.odds))
        + '</span>' : '')
    + '<span class="sub num">' + esc(v3Payout(row)) + '</span>'
    + (v[0] ? '<span class="' + v[1] + '">' + v[0] + '</span>' : '')
    + warn
    + '</div></div>'
    + '<button class="add" data-v3pick="' + esc(row.id) + '" aria-pressed="'
    + inSlip + '" aria-label="' + (inSlip ? 'Remove ' : 'Add ')
    + esc(row.player) + '">' + (inSlip ? '✓' : '+') + '</button>'
    + '</div>';
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
    + '<p class="help">Our game model cannot see the betting line and is not '
    + 'yet validated, so treat its view as a lean, not a call.</p></div>'
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
    + '<a class="back" data-v3back="1">‹ Games</a>'
    + '<div class="card">'
    + '<div class="vs"><div><b>' + esc(c.away) + '</b><div class="sub">away</div>'
    + '</div><div style="text-align:center;color:var(--mut2)">at</div>'
    + '<div style="text-align:right"><b>' + esc(c.home) + '</b>'
    + '<div class="sub">home</div></div></div>'
    + '<div class="sub" style="margin-top:8px">' + esc(v3Kick(c)) + '</div>'
    + v3WinBar(c)
    + '<div class="two" style="margin-top:16px">'
    + '<div class="box"><span class="eyebrow">Books expect</span>'
    + '<b class="num">' + v3ScoreTxt(c, 'proj') + '</b>'
    + '<span class="sub">' + esc(v3LineTxt(c, false)) + '</span></div>'
    + '<div class="box box--ours"><span class="eyebrow" '
    + 'style="color:var(--ours)">Our model</span>'
    + '<b class="num">' + v3ScoreTxt(c, 'model') + '</b>'
    + '<span class="sub">' + esc(v3LineTxt(c, true)) + '</span></div>'
    + '</div></div>'
    + '<div class="seg seg--3">'
    + v3Seg('v3gtab', [['notes', 'Game notes'], ['players', 'Who scores'],
                       ['bets', 'Game bets']], V.gameTab)
    + '</div>'
    + (V.gameTab === 'players' ? v3GamePlayers(gid)
     : V.gameTab === 'bets' ? v3GameBets(gid)
     : v3GameNotes(gid, cats, shown))
    + '</div>';
}

function v3WinBar(c) {
  if (!has(c.win_home)) return '';
  const h = Math.round(c.win_home * 100), a = 100 - h;
  return '<div style="margin-top:16px">'
    + '<div class="eyebrow">Chance of winning · sportsbooks</div>'
    + '<div class="bar" style="margin-top:6px" role="img" aria-label="'
    + esc(c.away) + ' ' + a + ' percent, ' + esc(c.home) + ' ' + h + ' percent">'
    + '<span class="a num" style="width:' + a + '%">' + a + '%</span>'
    + '<span class="h num" style="width:' + h + '%">' + h + '%</span>'
    + '</div></div>';
}

function v3ScoreTxt(c, which) {
  const hh = which === 'model' ? c.model_home : c.proj_home;
  const aa = which === 'model' ? c.model_away : c.proj_away;
  if (!has(hh) || !has(aa)) return '—';
  const lead = hh >= aa ? c.home : c.away;
  return lead + ' ' + Math.max(hh, aa).toFixed(1).replace(/\.0$/, '')
    + '–' + Math.min(hh, aa).toFixed(1).replace(/\.0$/, '');
}

function v3LineTxt(c, model) {
  const sp = model ? c.model_spread : c.spread;
  const tot = model ? c.model_total : c.total;
  const bits = [];
  if (has(sp)) bits.push((sp < 0 ? c.home : c.away) + ' by ' + Math.abs(sp));
  if (has(tot)) bits.push(tot + ' total points');
  if (model && !bits.length) return 'No model number for this game';
  return bits.join(' · ') + (model ? ' · still being tested' : '');
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
  return '<h2 class="h1" style="font-size:22px;line-height:28px;margin-top:20px">'
    + 'What our AI noticed</h2>'
    + '<p class="help">Written from this week’s prices and our model’s '
    + 'numbers. Every figure below is computed; only the wording is written.</p>'
    + '<div class="cats">' + pills + '</div>'
    + shown.map(v3Note).join('')
    + v3Ask(gid)
    + '<p class="help" style="margin-top:12px">These notes explain the game. '
    + 'They do not tell you what to bet.</p>';
}

function v3Note(n) {
  const figs = (n.stats || []).map(s =>
    '<div class="fig"><b class="num">' + esc(s.v) + '</b><span>' + esc(s.l)
    + '</span></div>').join('');
  // `context` before the rest: a coaching note that renders unlabelled reads
  // as a reason to bet, and `situational_features` measured thirteen of these
  // on 2,853 games without one of them clearing the vig.
  const flag = n.context ? '<span class="tag">Context, not an edge</span>'
    : n.measured ? '<span class="tag tag--good">Measured</span>'
    : n.unproven ? '<span class="tag tag--warn">Unproven</span>'
    : n.avoid ? '<span class="tag tag--bad">Avoid</span>' : '';
  const on = !!V.picks['note:' + n.id];
  return '<article class="note">'
    + '<div class="note__h"><span class="eyebrow">' + esc(n.cat) + '</span>'
    + flag + '</div>'
    + '<h3>' + esc(n.title) + '</h3>'
    + (figs ? '<div class="figs">' + figs + '</div>' : '')
    + '<p><b style="color:var(--ink)">Why it matters: </b>' + esc(n.why) + '</p>'
    + '<div class="note__f"><div><span class="sub">Related pick</span>'
    + '<div class="name" style="font-size:15px">' + esc(n.pick) + '</div></div>'
    + '<button class="btn" data-v3note="' + esc(n.id) + '" aria-pressed="' + on
    + '">' + (on ? 'Added' : 'Add') + '</button></div>'
    + '</article>';
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
    r => r.priced && (r.gameId === gid || fixtureOf(r.gameId) === gid));
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
  if (has(c.total) && has(c.model_total)) out.push({ q: 'Will it be high scoring?',
    a: 'The books set the total at ' + c.total + ' points. Our model expects '
     + 'about ' + c.model_total + ', a '
     + (Math.abs(c.model_total - c.total) < 3 ? 'small' : 'clear') + ' lean '
     + 'toward ' + (c.model_total > c.total ? 'more' : 'fewer') + ' points. '
     + 'That model cannot see the betting line and is unproven.' });
  return out;
}

function v3GamePlayers(gid) {
  const rows = rowsFor('any', null).filter(
    r => r.priced && (r.gameId === gid || fixtureOf(r.gameId) === gid));
  if (!rows.length) return '<div class="card">No priced touchdown market for '
    + 'this game yet.</div>';
  return '<h2 class="h1" style="font-size:22px;line-height:28px;margin-top:20px">'
    + 'Who might score</h2>'
    + '<p class="help">Chance to score a touchdown at any point in the game.</p>'
    + '<div class="list">'
    + rows.sort((a, b) => (betProb(b) || 0) - (betProb(a) || 0))
        .map(v3Row).join('') + '</div>';
}

// The game markets, as bets rather than as a read-out. This is what v2's
// Bets tab carries and the first v3 sketch dropped.
function v3GameBets(gid) {
  const rows = ((DATA.games || {}).rows || []).filter(
    r => r.game_id === gid || fixtureOf(r.game_id) === gid);
  if (!rows.length) return '<div class="card">No game lines captured for this '
    + 'game.</div>';
  const label = { h2h: 'To win', spreads: 'Spread', totals: 'Total' };
  const groups = ['h2h', 'spreads', 'totals'];
  return groups.map(mk => {
    const rs = rows.filter(r => r.market === mk);
    if (!rs.length) return '';
    return '<h2 class="h1" style="font-size:19px;line-height:24px;margin-top:20px">'
      + esc(label[mk] || mk) + '</h2><div class="list">'
      + rs.map(r => {
        const pt = has(r.point) ? ' ' + (r.point > 0 ? '+' : '') + r.point : '';
        const ev = r.ev100;
        const tag = has(ev) ? (ev >= 2 ? '<span class="tag tag--good">Good '
          + 'value</span>' : ev <= -4 ? '<span class="tag tag--bad">Pricey'
          + '</span>' : '<span class="tag">Fair price</span>') : '';
        return '<div class="row"><div class="row__m"><div class="row__t">'
          + '<div><div class="name">' + esc(r.outcome) + esc(pt) + '</div>'
          + '<div class="sub">best ' + v3Dash(american(r.best)) + ' at '
          + esc(r.best_book || '') + ' · ' + (r.n_books || 0)
          + ' books</div></div>'
          + '<div class="chance"><b class="num">' + v3Pct(r.fair)
          + '</b><span class="eyebrow">Fair chance</span></div></div>'
          + '<div class="tags"><span class="pill num">'
          + v3Dash(american(r.consensus)) + '</span>' + tag
          + (has(r.move_pp) && Math.abs(r.move_pp) >= 1
             ? '<span class="sub num">moved ' + (r.move_pp > 0 ? '+' : '')
               + r.move_pp.toFixed(1) + 'pp</span>' : '')
          + '</div></div></div>';
      }).join('') + '</div>';
  }).join('');
}

// ── screen: my picks ────────────────────────────────────────────────────

function v3Legs() {
  const out = [];
  for (const key of Object.keys(V.picks)) {
    if (key.indexOf('note:') === 0) continue;
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
  const S_ = V.stake;
  const dec = legs.map(l => l.dec).filter(has);
  const ps = legs.map(l => betProb(l)).filter(has);
  const ok = dec.length === legs.length && ps.length === legs.length;

  const types = [
    ['parlay', 'All or nothing',
     'One bet. Every pick has to land. Biggest payout, hardest to win.'],
    ['twos', 'Any two',
     'A smaller bet on each pair. Two landing is enough to win something.'],
    ['singles', 'Each on its own',
     'Separate bets. Every pick that lands pays out.'],
  ];

  const rows = legs.map(l => '<div class="row"><div class="row__m">'
    + '<div class="row__t"><div><div class="name">' + esc(l.player) + '</div>'
    + '<div class="sub">' + esc(v3Fixture(l)) + '</div>'
    + (v3Line(l) ? '<div class="line">' + esc(v3Line(l)) + '</div>' : '')
    + '</div><div class="chance"><b class="num">' + v3Pct(betProb(l))
    + '</b><span class="sub num">' + v3Dash(american(l.odds))
    + '</span></div></div></div>'
    + '<button class="add" data-v3pick="' + esc(l.id)
    + '" aria-pressed="true" aria-label="Remove ' + esc(l.player)
    + '">✓</button></div>').join('');

  return '<div class="wrap"><h1 class="h1">My picks</h1>'
    + '<p class="lede">' + legs.length + ' pick'
    + (legs.length === 1 ? '' : 's') + '. Choose how to bet them and see what '
    + 'could happen.</p>'
    + '<div class="list">' + rows + '</div>'
    + '<h2 class="eyebrow" style="margin:24px 2px 0">How do you want to bet?</h2>'
    + types.map(t => '<button class="opt" data-v3type="' + t[0]
        + '" aria-pressed="' + (V.betType === t[0]) + '">'
        + '<span class="radio"><i></i></span><span>'
        + '<span class="name">' + esc(t[1]) + '</span><br>'
        + '<span class="sub">' + esc(t[2]) + '</span></span></button>').join('')
    + '<h2 class="eyebrow" style="margin:24px 2px 0">'
    + (V.betType === 'parlay' ? 'How much?' : 'How much on each bet?') + '</h2>'
    + '<div class="stakes">' + [5, 10, 20, 50].map(v =>
        '<button class="stake" data-v3stake="' + v + '" aria-pressed="'
        + (V.stake === v) + '">$' + v + '</button>').join('') + '</div>'
    + (ok ? v3Outcomes(legs, S_)
          : '<div class="card"><p class="lede" style="font-size:15px">One of '
            + 'these picks has no posted price, so the payout cannot be worked '
            + 'out. Remove it to see the numbers.</p></div>')
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

function v3Nav() {
  return '<nav class="nav" aria-label="Main">' + V3TABS.map(t =>
    '<a data-v3tab="' + t[0] + '"' + (V.tab === t[0] && !V.game
      ? ' aria-current="page"' : '') + '>'
    + '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" '
    + 'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
    + 'stroke-linejoin="round" aria-hidden="true"><path d="' + t[2]
    + '"></path></svg>' + esc(t[1]) + '</a>').join('') + '</nav>';
}

function v3Fab() {
  const n = v3Legs().length;
  if (!n || V.tab === 'slip') return '';
  return '<a class="fab" data-v3tab="slip">'
    + '<span style="display:flex;align-items:center;gap:8px;font-weight:600">'
    + '<b class="num">' + n + '</b> pick' + (n === 1 ? '' : 's') + '</span>'
    + '<span style="font-weight:600">See payout</span></a>';
}

function render() {
  const app = document.getElementById('app');
  if (!app) return;
  app.innerHTML = '<div class="wrap">' + v3Header() + '</div>'
    + v3Screen() + v3Fab() + v3Nav();
  v3Save();
}

// One delegated listener. Every control is a `data-v3*` attribute, so a
// control that is added and never wired here does nothing at all rather than
// throwing — which is why `test_every_v3_control_is_handled` exists.
const V3CLICKS = ['v3tab', 'v3mkt', 'v3sort', 'v3filter', 'v3pick', 'v3more',
                  'v3game', 'v3back', 'v3gtab', 'v3cat', 'v3note', 'v3type',
                  'v3stake', 'v3kind', 'v3ask'];

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

document.addEventListener('change', ev => {
  const t = ev.target;
  if (t && t.getAttribute && t.getAttribute('data-v3week') != null) {
    V.week = t.value === '' ? null : Number(t.value);
    V.shown = V3SHOW;
    render();
  }
});

function v3Do(kind, v) {
  switch (kind) {
    case 'v3tab': V.tab = v; V.game = null; V.shown = V3SHOW; break;
    // The market changes; the GAME FILTER DOES NOT. Looking at one game and
    // clicking between markets should not mean re-picking the game each time.
    case 'v3mkt': V.market = v; V.shown = V3SHOW; break;
    case 'v3sort': V.sort = v; break;
    case 'v3filter': V.filter = v; V.shown = V3SHOW; break;
    case 'v3more': V.shown = 1e9; break;
    case 'v3pick':
      if (V.picks[v]) delete V.picks[v]; else V.picks[v] = true; break;
    case 'v3note':
      if (V.picks['note:' + v]) delete V.picks['note:' + v];
      else V.picks['note:' + v] = true; break;
    case 'v3game': V.tab = 'games'; V.game = v; V.gameTab = 'notes';
      V.cat = 'all'; V.answer = ''; break;
    case 'v3back': V.game = null; V.answer = ''; break;
    case 'v3gtab': V.gameTab = v; break;
    case 'v3cat': V.cat = v; break;
    case 'v3type': V.betType = v; break;
    case 'v3stake': V.stake = Number(v); break;
    case 'v3kind': V.ladderKind = v; break;
    case 'v3ask': {
      const qs = v3Questions(V.game);
      V.answer = (qs[Number(v)] || {}).a || ''; break;
    }
  }
  render();
}

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
