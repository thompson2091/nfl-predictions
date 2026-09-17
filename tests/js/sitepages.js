// Every page of site.html, rendered against a stub DOM.
//
// A generated single-page file fails in exactly one way: it throws on load and
// shows a blank page with one line in a console nobody has open. `node --check`
// does not catch that — the syntax is fine, the reference is not. So each of
// the four pages is actually rendered, and the things that must be on them are
// asserted from the payload rather than typed in.
//
//   node tests/js/sitepages.js <payload.json> <page.js>
const { loadPage, textOf, reporter } = require('./domstub.js');

const { ok, done } = reporter();
const x = loadPage(process.argv[2], process.argv[3],
  ['S', 'rowsFor', 'applyFilters', 'slipMath', 'choose', 'settle', 'legOf', 'PAGES', 'has',
   'combosOf', 'saveCombo', 'comboSaved', 'COMBO_POOL_MAX',
   'chanceTxt', 'slipSlot', 'slipHandle', 'clearSlip', 'table',
   'ev100', 'betProb', 'el', 'pct', 'portfolio', 'brkTable', 'scaleRows',
   'moveTxt', 'marketLabel', 'MENU', 'KIND', 'marketOf', 'served',
   'gradedNote', 'M0', 'unitOf', 'oneLine', 'extraLines', 'spp',
   'parlayCard', 'DATA', 'pageModel', 'num2', 'fixtureOf']);
const { S, rowsFor, applyFilters, slipMath, choose, settle, legOf, PAGES, has,
        combosOf, saveCombo, comboSaved, COMBO_POOL_MAX,
        chanceTxt, slipSlot, slipHandle, clearSlip, table,
        ev100, betProb, el, pct, portfolio, brkTable, scaleRows,
        moveTxt, marketLabel, MENU, KIND, marketOf, served,
        gradedNote, M0, unitOf, oneLine, extraLines, spp,
        parlayCard, DATA, pageModel, num2, fixtureOf } = x;

const txt = n => textOf(n).join(' ');
const PAGE_SRC = require('fs').readFileSync(process.argv[3], 'utf8');

// ── Every page renders ──────────────────────────────────────────────────
const pages = { week: pageWeek, combos: pageCombos, saved: pageSaved,
                ladder: pageLadder, model: pageModel };
Object.entries(pages).forEach(([name, fn]) => {
  let out = null, err = null;
  try { out = fn(); } catch (e) { err = e; }
  ok('page "' + name + '" renders', !err, err && (err.message + '\n' + err.stack));
  if (out) ok('page "' + name + '" is not blank', txt(out).trim().length > 40);
});

// ── The nav is four pages, and the shortlist is not one of them ─────────
ok('nav carries exactly the five pages', PAGES.length === 5,
   PAGES.map(p => p[0]).join(','));
ok('combinations is a page, because its rows are slips and not players',
   PAGES.some(p => p[0] === 'combos'));
ok('shortlist is a view, not a page', !PAGES.some(p => p[0] === 'shortlist'));

// ── The three views are the same board under different rules ────────────
const all = rowsFor('any', 'all'), short = rowsFor('any', 'short'), fade = rowsFor('any', 'fade');
ok('the shortlist is smaller than the board', short.length < all.length,
   short.length + ' vs ' + all.length);
// The whole point of the rewrite: a shortlisted player is the *same row* as on
// the full board, not a second one built from a different payload entry. They
// used to disagree — the Adj column showed the pre-blend number on this view
// because the figures came from somewhere else.
ok('a shortlisted player is the board row, field for field',
   short.every(sr => {
     const br = all.find(r => r.id === sr.id);
     return br && ['ours', 'modelOnly', 'book', 'edge', 'odds', 'priced']
       .every(k => String(br[k]) === String(sr[k]));
   }),
   'the views filter one table rather than mapping a parallel one');
ok('the three numbers are genuinely three numbers',
   short.some(r => has(r.modelOnly) && has(r.ours) && r.modelOnly !== r.ours),
   'Model and Adj showing the same value is the bug this replaced');
ok('edge is measured on the pre-blend number, as the rule was backtested',
   short.filter(r => has(r.edge) && has(r.modelOnly) && has(r.book))
        .every(r => Math.abs(r.edge - (r.modelOnly - r.book) * 100) < 0.6),
   'an edge taken from the published probability is about 62% of the real one');
ok('fade rows exist to be kept off a slip', fade.length > 0);
// Ids must agree across views or a star set on the board is lost on the
// shortlist, which is the bug that made two separate pages feel broken.
const allIds = new Set(all.map(r => r.id));
ok('a shortlisted player has the same id as on the full board',
   short.every(r => allIds.has(r.id)),
   short.filter(r => !allIds.has(r.id)).map(r => r.id).slice(0, 3).join(','));

// ── Filters ─────────────────────────────────────────────────────────────
const f = { view: 'all', q: '', game: '', pos: '', priced: 'all', favOnly: false, sort: '', dir: -1 };
ok('no filter keeps everything', applyFilters(all, f).length === all.length);
const one = all[0];
ok('searching a name narrows to it',
   applyFilters(all, { ...f, q: one.player }).some(r => r.id === one.id));
ok('a two-term search matches across fields',
   applyFilters(all, { ...f, q: one.team + ' ' + one.player.split(' ')[0] }).length > 0,
   'terms are ANDed over player, team and game together');
ok('a nonsense search matches nothing',
   applyFilters(all, { ...f, q: 'zzzzqqq' }).length === 0);
ok('the position filter narrows and does not empty',
   (() => { const n = applyFilters(all, { ...f, pos: 'RB' }).length;
            return n > 0 && n < all.length; })());
ok('WR is filterable, being the reference level and not a gap',
   applyFilters(all, { ...f, pos: 'WR' }).length > 0);
ok('priced-only drops the unpriced',
   applyFilters(all, { ...f, priced: 'priced' }).every(r => r.priced));
// Sorting belongs to `table`, and this used to ask `applyFilters` for it —
// which does not sort, and says so in a comment. The assertion passed because
// the fixture happened to be in descending order, so it tested the fixture and
// not the code. Widening the fixture broke the coincidence and exposed it.
//
// Driven through `table` now, with a numeric column deliberately rendered as a
// string: "12%" and "9%" sort the wrong way as text and the right way as
// numbers, which is the bug the title names.
(() => {
  // 9, 11 and 12 rather than 0.09, 0.11, 0.12. Those three sort the SAME way
  // as text and as numbers ("0.09" < "0.11" < "0.12"), so a fixture built from
  // them passes with the comparison forced to a string and proves nothing.
  // These do not: as text "12" < "9", which is the wrong answer and the one
  // this assertion exists to catch.
  const rows = [{ v: 9, name: 'low' }, { v: 12, name: 'high' },
                { v: null, name: 'missing' }, { v: 11, name: 'mid' }];
  const cols = [{ w: '1fr', label: 'Name', sort: 'name',
                  cell: (d, r) => d.appendChild(el('span', { text: r.name })) },
                { w: '1fr', label: 'V', sort: 'v',
                  cell: (d, r) => d.appendChild(el('span',
                    { text: has(r.v) ? r.v + '%' : '' })) }];
  const order = dir => {
    S.sort.sorttest = { sort: 'v', dir: dir };
    return textOf(table(cols, rows, null, { id: 'sorttest' }))
      .filter(t => /^(low|high|mid|missing)$/.test(t));
  };
  const desc = order(-1), asc = order(1);
  ok('sorting is on the value, not the rendered string',
     desc.slice(0, 3).join(',') === 'high,mid,low', desc.join(','));
  ok('and reverses on the other click',
     asc.slice(0, 3).join(',') === 'low,mid,high', asc.join(','));
  ok('a missing value sorts last whichever way the column points',
     desc[3] === 'missing' && asc[3] === 'missing',
     'a blank that floats to the top is a row you re-sort past to read');
  delete S.sort.sorttest;
})();

// ── One slip, shared ────────────────────────────────────────────────────
S.slip = { market: 'any', legs: [], size: 0, stake: 10, stakeRaw: '10' };
const priced = all.filter(r => r.priced && has(r.dec)).slice(0, 3);
S.slip.legs = priced.map(r => legOf(r));
S.slip.market = 'any';
let m = slipMath();

// A slip is the full cover: every combination of its legs, which is what a
// book sells as a round robin. Three legs is seven slips — three singles,
// three doubles and the treble — not one.
ok('the full cover is every combination', m.slips === 7, String(m.slips));
ok('and risks a stake on each of them', Math.abs(m.outlay - 70) < 1e-9, String(m.outlay));
ok('all-hit is the product of the legs',
   Math.abs(m.all - priced.reduce((a, r) => a * r.ours, 1)) < 1e-6);

ok('the breakdown covers every outcome, not only the paying ones',
   m.rows.length === 4 && m.rows[0].hit === 3 && m.rows[3].hit === 0,
   m.rows.map(r => r.hit).join(','));
// With k legs in, the slips that pay are every non-empty subset of those k.
ok('and says how many slips each outcome pays',
   m.rows.map(r => r.slipsWon).join(',') === '7,3,1,0',
   m.rows.map(r => r.slipsWon).join(','));
ok('the chances in the breakdown are probabilities',
   m.rows.every(r => r.chance >= 0 && r.chance <= 1));
ok('and sum to one, so no outcome is missing',
   Math.abs(m.rows.reduce((a, r) => a + r.chance, 0) - 1) < 1e-6);
ok('losing everything is a loss of the whole outlay',
   Math.abs(m.rows[3].net + 70) < 1e-9, String(m.rows[3].net));

// The bug this replaced: each slip pays the product of ITS OWN legs' prices.
// Averaging the decimal across slips reports a payout no slip pays, and is
// out by more the further apart the prices are.
const decs = priced.map(r => r.dec);
const treble = 10 * decs[0] * decs[1] * decs[2];
const doubles = [[0,1],[0,2],[1,2]].map(([i, j]) => 10 * decs[i] * decs[j]);
const singles = decs.map(d => 10 * d);
const allWin = treble + doubles.reduce((a, b) => a + b, 0) + singles.reduce((a, b) => a + b, 0);
ok('every slip is priced on its own legs, not on an average',
   Math.abs(m.rows[0].net - (allWin - 70)) < 1e-6,
   'expected ' + (allWin - 70).toFixed(2) + ', got ' + m.rows[0].net.toFixed(2));

// Which legs landed changes what came back, so a k-of-n row is a range.
ok('a partial outcome reports the spread it can pay',
   m.rows[1].netLo < m.rows[1].net && m.rows[1].net < m.rows[1].netHi,
   [m.rows[1].netLo, m.rows[1].net, m.rows[1].netHi].map(v => v.toFixed(2)).join(' / '));

// ── choose(), which decides what a round robin pays ─────────────────────
ok('choose is the binomial coefficient',
   choose(5, 2) === 10 && choose(3, 3) === 1 && choose(3, 4) === 0 && choose(4, 0) === 1);

// ── Settlement ──────────────────────────────────────────────────────────
const mk = (legs, extra) => Object.assign({
  id: 'p1', name: 'test', market: 'any', marketLabel: 'Anytime TD', week: 2,
  size: 0, stake: 10, slips: 1, outlay: 10, chance: 0.3, dec: 3, priced: true,
  legs: legs.map(id => ({ id: id, player: id, label: id, odds: 200, dec: 3, p: 0.3 })),
}, extra || {});
const known = Object.keys(DATA.results || {});
ok('an unsettled week leaves a parlay pending',
   settle(mk(['any|Nobody At All'])).status === 'Pending');
ok('and shows no net while it is pending',
   settle(mk(['any|Nobody At All'])).net === 0);

// Force a settled case rather than depending on the week having been played.
// Keyed by week, because a player is a different bet in a different week and a
// shared key would settle a live parlay from a result it never had.
DATA.results = { '2|any|A': 'hit', '2|any|B': 'hit', '2|any|C': 'miss' };
ok('every leg hitting wins a full cover', settle(mk(['any|A', 'any|B'])).status === 'Won');
ok('one leg missing loses a single slip', settle(mk(['any|A', 'any|C'])).status === 'Lost');

// A saved cover settles from the curve it was saved with, not from one price.
// Three slips pay when two of three land; the curve says so and the old
// single-price arithmetic could not.
const cover = mk(['any|A', 'any|B', 'any|C'], {
  slips: 7, outlay: 70,
  rows: [{ hit: 3, slipsWon: 7, chance: 0.02, net: 400 },
         { hit: 2, slipsWon: 3, chance: 0.16, net: 50 },
         { hit: 1, slipsWon: 1, chance: 0.43, net: -40 },
         { hit: 0, slipsWon: 0, chance: 0.39, net: -70 }],
});
const rr = settle(cover);
ok('a cover with two of three landing still wins', rr.status === 'Won', rr.status);
ok('and pays what its curve says, not a re-derived single price',
   rr.net === 50, String(rr.net));
ok('a parlay saved before curves existed still settles',
   settle(mk(['any|A', 'any|C'])).status === 'Lost',
   'the fallback treats it as the single slip it was');

ok('an unknown leg keeps the whole slip pending rather than losing it',
   settle(mk(['any|A', 'any|Unknown Person'])).status === 'Pending',
   'a name that fails to join must not read as a loss');
// The week is load-bearing in the key: the same parlay in another week must
// not pick up this week's answers.
ok('a result from one week does not settle a parlay from another',
   settle(mk(['any|A', 'any|B'], { week: 3 })).status === 'Pending',
   'week 3 has no results, so a week-3 slip cannot be Won');

// ── Combinations ────────────────────────────────────────────────────────
//
// The page returns slips, and a slip saved from here has to be
// indistinguishable from one built by hand — same shape, same settlement, same
// round robin — or the Saved page would have two kinds of card in it.
ok('combosOf enumerates every subset and no duplicates',
   (() => { const c = combosOf(5, 3);
            const seen = new Set(c.map(x => x.join(',')));
            return c.length === 10 && seen.size === 10
                   && c.every(x => x.length === 3 && x[0] < x[1] && x[1] < x[2]); })());
ok('a pool of one yields no slips', combosOf(1, 2).length === 0);

S.parlays = [];
S.slip.stake = 10;
const cpool = rowsFor('any', 'all').filter(r => r.priced && has(r.dec)).slice(0, 4);
ok('the fixture has a pool to combine', cpool.length >= 3);
const s3 = { ix: [0, 1, 2], p: cpool.slice(0, 3).reduce((a, r) => a * r.ours, 1),
             dec: cpool.slice(0, 3).reduce((a, r) => a * r.dec, 1), ev: 0, sameGame: false };

ok('a combination is not saved before you save it', !comboSaved('any', s3, cpool));
saveCombo('any', s3, cpool);
ok('saving a combination adds one parlay', S.parlays.length === 1);
ok('and it is recognised as saved afterwards', comboSaved('any', s3, cpool));

const sv = S.parlays[0];
ok('the saved slip keeps every leg', sv.legs.length === 3);
ok('it names the market it belongs to', sv.market === 'any' && !!sv.marketLabel);
ok('it records the week, so it clears with the week', sv.week === DATA.week);
ok('it stores the structure, not a pointer',
   sv.size === 0 && sv.stake === 10 && has(sv.dec) && has(sv.chance));
ok('and carries a payout curve like everything else in the list',
   Array.isArray(sv.rows) && sv.rows.length === sv.legs.length + 1
   && sv.rows[0].hit === sv.legs.length && sv.rows[0].slipsWon === 1,
   'a combination is one slip, so only the top row pays');
ok('it is marked as coming from combinations', sv.from === 'combinations');

// The whole point of the shape matching: a combination has to settle through
// exactly the same code a hand-built slip does.
DATA.results = {};
cpool.slice(0, 3).forEach(r => { DATA.results[DATA.week + '|' + r.id] = 'hit'; });
ok('a saved combination settles like any other parlay',
   settle(sv).status === 'Won', settle(sv).status);
DATA.results[DATA.week + '|' + cpool[0].id] = 'miss';
ok('and loses when a leg misses', settle(sv).status === 'Lost');
DATA.results = {};
S.parlays = [];

// ── Every market, and every view of the board ───────────────────────────
//
// The harness rendered only the default market until a launch check found that
// nothing had ever exercised First TD or Receptions. First TD has an empty
// shortlist this week and Receptions has a different table shape, so both are
// exactly where a render would break.
['any', 'first', 'rec'].forEach(mk => {
  S.market = mk;
  [['week', pageWeek], ['combos', pageCombos]].forEach(([name, fn]) => {
    let err = null, out = null;
    try { out = fn(); } catch (e) { err = e; }
    ok(name + ' renders for market ' + mk, !err, err && err.message);
    if (out) ok('  ' + name + '/' + mk + ' is not blank', textOf(out).join(' ').length > 40);
  });
  if (mk !== 'rec') ['all', 'short', 'fade'].forEach(v => {
    S.fw.view = v;
    let err = null;
    try { pageWeek(); } catch (e) { err = e; }
    ok('week/' + mk + ' renders view "' + v + '"', !err, err && err.message);
  });
  S.fw.view = 'all';
});
S.market = 'first'; S.fw.view = 'short';
ok('an empty shortlist says so rather than showing an empty card',
   /Nothing survives every filter/.test(textOf(pageWeek()).join(' ')));
S.fw.view = 'all'; S.market = 'any';

// ── Readable probabilities at every scale ───────────────────────────────
ok('a coin flip reads as a percentage', chanceTxt(0.59) === '59%', chanceTxt(0.59));
ok('a one-percent chance keeps a decimal', chanceTxt(0.0098) === '0.98%', chanceTxt(0.0098));
ok('no scientific notation anywhere', !/e[-+]\d/.test(
  [0.5, 0.0098, 0.0004, 1e-7, 1e-12].map(chanceTxt).join(' ')),
  [0.5, 0.0098, 0.0004, 1e-7, 1e-12].map(chanceTxt).join(' '));
ok('a very long shot becomes odds against', /^1 in /.test(chanceTxt(0.0004)), chanceTxt(0.0004));
ok('zero and nonsense do not print NaN', chanceTxt(0) === '—' && chanceTxt(null) === '—');

// ── The slip is absent until it holds something ─────────────────────────
S.slip = { market: 'any', legs: [], size: 0, stake: 10, stakeRaw: '10' };
S.slipOpen = false; S.conflict = null;
ok('an empty, closed slip takes no width from the board', slipSlot() === null);
S.slipOpen = true;
ok('and an empty OPEN slip is still not shown — there is nothing in it',
   slipSlot() === null);
S.slipOpen = false;
ok('and offers no handle when there is nothing in it', slipHandle() === null);

// Asserted on the rendered pages, not only on the helper. The first version of
// this checked `slipSlot` alone and passed while This week still called
// `slipPanel` directly — a page-level swap that silently no-opped, so the slip
// sat on the board at "0 legs" and the helper it was supposed to go through
// was never reached. A helper nothing calls is not a behaviour.
['week', 'combos'].forEach(name => {
  const fn = name === 'week' ? pageWeek : pageCombos;
  ok(name + ' shows no slip panel when the slip is empty and closed',
     textOf(fn()).join(' ').indexOf('Your slip') < 0,
     'the panel is rendered by the page, so the page has to ask for it');
});

const rows = rowsFor('any', 'all').filter(r => r.priced).slice(0, 2);
S.slip.legs = rows.map(r => legOf(r));
ok('a closed slip with legs still yields the board its width', slipSlot() === null);
const h = slipHandle();
ok('but offers a handle saying how many are in it', h !== null && /2/.test(txt(h)), h && txt(h));
S.slipOpen = true;
ok('opening it brings the panel back', slipSlot() !== null);
ok('with the legs still in it', txt(slipSlot()).indexOf(rows[0].player) >= 0);
['week', 'combos'].forEach(name => {
  const fn = name === 'week' ? pageWeek : pageCombos;
  ok(name + ' renders the panel once it is open',
     textOf(fn()).join(' ').indexOf('Your slip') >= 0);
});

// A conflict has to be visible even with the slip put away, or the prompt is
// posted to a panel nobody can see.
S.slipOpen = false;
S.conflict = { row: rowsFor('first', 'all')[0], side: null };
ok('a market conflict forces the panel open', slipSlot() !== null);
S.conflict = null;

// ── The receptions board is everyone, not only the quoted ───────────────
S.market = 'rec';
const rec = rowsFor('rec', 'all');
const quoted = rec.filter(r => has(r.line));
// Quoted means a close was captured. A row standing on the opening line is
// not the book's current opinion and is counted separately.
const closed = rec.filter(r => has(r.line) && !r.stale);
ok('receptions shows far more than the book has currently quoted',
   rec.length > closed.length * 3, rec.length + ' rows, ' + closed.length + ' with a close');
ok('an unquoted row still carries a projection',
   rec.filter(r => !has(r.line)).every(r => has(r.proj)));
ok('and is not given a line it was never offered',
   rec.filter(r => !has(r.line)).every(r => !has(r.ours) && !has(r.book) && !r.priced));
S.market = 'any';

// ── The board is no longer warned over ──────────────────────────────────
S.market = 'rec';
ok('the receptions board carries no lecture',
   !/It is here to be measured against the close/.test(txt(pageWeek())));
S.market = 'any';

// ── Emptying the slip in one go ─────────────────────────────────────────
S.slip = { market: 'any', legs: rowsFor('any','all').slice(0,3).map(r => legOf(r)),
           size: 2, stake: 10, stakeRaw: '10' };
S.slipOpen = true;
ok('the panel offers one control that empties the whole slip',
   /Clear/.test(textOf(slipSlot()).join(' ')));
clearSlip();
ok('clearing removes every leg at once', S.slip.legs.length === 0);
ok('and resets the round robin with them', S.slip.size === 0);
ok('and keeps the stake, which is a preference not a pick', S.slip.stake === 10);
ok('an emptied slip stops taking the board\'s width', S.slipOpen === false && slipSlot() === null);
ok('and offers no handle, because there is nothing to come back to', slipHandle() === null);

// ── Sorting, on every table ─────────────────────────────────────────────
// Sorting belongs to the table, so a table with no page filter state sorts
// too. Four of them used to pass `null` and silently did nothing on a click.
const sortRows = [{ a: 3, b: 'c' }, { a: 1, b: 'a' }, { a: null, b: 'b' }];
const sortCols = [
  { w: '1fr', label: 'A', sort: 'a', cell: (d, r) => d.appendChild({ _text: String(r.a) }) },
  { w: '1fr', label: 'B', sort: 'b', cell: (d, r) => d.appendChild({ _text: r.b }) },
  { w: '1fr', label: 'X', nosort: 1, cell: (d) => d.appendChild({ _text: '-' }) },
];
// Select cells by value, not by position. The sorted header appends its arrow
// as a separate text node, so "every other token" silently stopped alternating
// the moment a column was sorted — which is how the first version of this read
// column A's values and asserted they were column B's.
const cells = () => textOf(table(sortCols, sortRows, null, { id: 't' }));
const colA = () => cells().filter(t => /^(1|3|null)$/.test(t));
const colB = () => cells().filter(t => /^[abc]$/.test(t));
const order = colA;

S.sort = {};
ok('unsorted keeps the given order', order().join(',') === '3,1,null', order().join(','));

S.sort.t = { sort: 'a', dir: -1 };
ok('descending puts the largest first', order()[0] === '3');
S.sort.t = { sort: 'a', dir: 1 };
ok('ascending puts the smallest first', order()[0] === '1');
ok('and a missing value sorts last either way',
   order().indexOf('null') > order().indexOf('3'),
   'a blank that floats to the top is a row you re-sort past to read the answer');

S.sort.t = { sort: 'b', dir: 1 };
ok('a text column sorts as text', colB().join(',') === 'a,b,c', colB().join(','));
S.sort.t = { sort: 'b', dir: -1 };
ok('and reverses on a second click', colB().join(',') === 'c,b,a', colB().join(','));
S.sort = {};

// ── Floor and ceiling, on the count market ──────────────────────────────
S.market = 'rec';
const recRows = rowsFor('rec', 'all').filter(r => has(r.lo) && has(r.hi));
ok('the count board carries a floor and a ceiling', recRows.length > 0);
ok('the floor is never above the ceiling', recRows.every(r => r.lo <= r.hi));
ok('and both bracket the projection',
   recRows.every(r => r.lo <= Math.ceil(r.proj) && r.hi >= Math.floor(r.proj)),
   recRows.filter(r => !(r.lo <= Math.ceil(r.proj) && r.hi >= Math.floor(r.proj)))
          .slice(0, 2).map(r => r.player + ' ' + r.lo + '-' + r.hi + ' proj ' + r.proj).join('; '));
ok('nobody catches a negative number of passes', recRows.every(r => r.lo >= 0));
ok('a bigger projection has a higher ceiling',
   (() => { const s = recRows.slice().sort((a, b) => b.proj - a.proj);
            return s[0].hi >= s[s.length - 1].hi; })());
// Two columns, not one cell: "highest floor" and "biggest ceiling" are
// different questions and a combined range answers neither.
ok('each is sortable on its own',
   /label: 'Floor'[\s\S]{0,200}?sort: 'lo'/.test(PAGE_SRC)
   && /label: 'Ceiling'[\s\S]{0,200}?sort: 'hi'/.test(PAGE_SRC));
S.market = 'any';

// ── Every column header explains itself ─────────────────────────────────
//
// Walked over the rendered pages rather than grepped out of the source, so a
// column added later is covered by this without anyone remembering to add it
// here. A header with no title is a column whose meaning lives only in
// whoever wrote it — and half of these are probabilities that differ by which
// information went into them, which is exactly the thing a label cannot carry.
function headersIn(node, out) {
  out = out || [];
  if (!node) return out;
  if (String(node.className || '').split(/\s+/).includes('hd')) {
    (node.children || []).forEach(c => out.push(c));
    return out;
  }
  (node.children || []).forEach(c => headersIn(c, out));
  return out;
}
const bare = [];
['any', 'first', 'rec'].forEach(mk => {
  S.market = mk;
  [['all', 'week'], ['short', 'week'], ['fade', 'week'], ['priced', 'week'],
   [null, 'combos'], [null, 'ladder'], [null, 'model']].forEach(([v, page]) => {
    if (v) S.fw.view = v;
    const fn = page === 'week' ? pageWeek : page === 'combos' ? pageCombos
             : page === 'ladder' ? pageLadder : pageModel;
    let out = null;
    try { out = fn(); } catch (e) { return; }
    headersIn(out).forEach(h => {
      if (!h.attrs || !h.attrs.title) {
        bare.push(mk + '/' + page + (v ? '/' + v : '') + ': "'
                  + String(h._text || '(unlabelled)').trim() + '"');
      }
    });
  });
  S.fw.view = 'all';
});
S.market = 'any';
ok('every column header carries a description', bare.length === 0,
   bare.slice(0, 8).join(' | '));

// ── Every number on a slip leg ──────────────────────────────────────────
const td = rowsFor('any','all').filter(r => r.priced && has(r.modelOnly) && has(r.book))[0];
const leg = legOf(td);
ok('a leg carries all three numbers and the price',
   /M \d+% · B \d+% · A \d+% · [+-−]\d+/.test(leg.sub), leg.sub);
S.slip = { market:'any', legs:[leg], size:0, stake:10, stakeRaw:'10' }; S.slipOpen = true;
const t = textOf(slipSlot()).join(' ');
ok('and the panel says what M, B and A are', /M model · B book · A adj/.test(t));
ok('the leg is rendered with them', t.indexOf(leg.sub) >= 0);

// Taking the under flips every probability, not only the one we price with.
S.market = 'rec';
const ou = rowsFor('rec','all').filter(r => r.priced && has(r.modelOnly) && has(r.book))[0];
const over = legOf(ou, 'over'), under = legOf(ou, 'under');
ok('an under flips all three', Math.abs(over.pm + under.pm - 1) < 1e-9
   && Math.abs(over.pb + under.pb - 1) < 1e-9 && Math.abs(over.p + under.p - 1) < 1e-9,
   'otherwise the leg shows the book on the over beside us on the under');
S.market = 'any';

// ── Expected return on $100 ─────────────────────────────────────────────
// The basis is the column. A touchdown EV taken from the published number is
// measured on a different quantity than every profitability figure this
// project quotes, and would read higher than the backtest it is compared to.
const evTd = rowsFor('any','all').filter(r => r.priced && has(r.modelOnly) && r.modelOnly !== r.ours);
ok('the fixture has rows where the two bases differ', evTd.length > 0);
ok('a touchdown bet is judged on the pre-blend number',
   evTd.every(r => betProb(r) === r.modelOnly),
   'the published probability has been pulled toward the price it is compared to');
ok('and EV follows it', evTd.every(r =>
   Math.abs(ev100(r) - 100 * (r.modelOnly * r.dec - 1)) < 1e-6));

S.market = 'rec';
const evOu = rowsFor('rec','all').filter(r => r.priced && has(r.dec));
ok('a receptions bet is judged on the served number',
   evOu.every(r => betProb(r) === r.ours),
   'there the blend is what was measured, and it beats the book');
S.market = 'any';

// The arithmetic, end to end: an even-money bet we rate at 60% returns $20.
ok('EV is the return on a flat hundred',
   Math.abs(ev100({ kind:'td', modelOnly: 0.6, ours: 0.6, dec: 2.0 }) - 20) < 1e-9,
   String(ev100({ kind:'td', modelOnly: 0.6, ours: 0.6, dec: 2.0 })));
ok('a fairly priced bet is worth nothing',
   Math.abs(ev100({ kind:'td', modelOnly: 0.5, ours: 0.5, dec: 2.0 })) < 1e-9);
ok('an unpriced row has no EV rather than a zero',
   ev100({ kind:'td', modelOnly: 0.5, ours: 0.5, dec: null }) === null);
S.market = 'any'; S.fw.view = 'all';

// ── Opening prices ──────────────────────────────────────────────────────
//
// The other end of the same measurement. Early in the week it is also more
// coverage than the close, not less: a count market's close held seven lines
// on the Wednesday of week 2 and the open held sixty-eight.
const opTd = rowsFor('any', 'all');
ok('the touchdown board carries an opening price',
   opTd.filter(r => has(r.openOdds)).length > 0);
ok('and the move is measured implied against implied, not against the de-vigged book',
   /1 \/ row.dec/.test(PAGE_SRC),
   'an opening touchdown price is one-sided and cannot be de-vigged, so half '
   + 'the difference would be the margin rather than the market');
const mv = opTd.find(r => has(r.openImplied) && has(r.dec));
ok('a moved market says which way it went relative to us',
   /moved [\d.]+pp (up|down) since it opened, (toward|away from) our number/
     .test(moveTxt(mv)) || /has not moved/.test(moveTxt(mv)),
   moveTxt(mv));
ok('an unpriced row claims no movement', moveTxt({ dec: null, openImplied: 0.5 }) === '');

S.market = 'rec';
const opOu = rowsFor('rec', 'all');
const withLine = opOu.filter(r => has(r.line));
ok('a count row with no close falls back to the opening line',
   withLine.filter(r => r.stale).length > 0);
ok('and that fallback is marked, not passed off as a close',
   withLine.filter(r => r.stale).every(r => r.stale === true));
ok('the fallback is what makes the pool usable at all',
   opOu.filter(r => r.priced).length > opOu.filter(r => has(r.line) && !r.stale).length,
   'a pool of only the closes is a handful of names permuted');
S.market = 'any';

// ── A count row falling back to the open is PRICED, not just lined ──────
//
// It used to carry a line and odds and nothing else — no model number, no
// book number, no edge. That is worse than an empty row, because the
// Combinations page multiplies these together and `p *= null` fills the All
// hit column with NaN on a board that looks populated.
S.market = 'rec';
const lined = rowsFor('rec', 'all').filter(r => r.priced);
ok('every lined count row carries a probability, not only a line',
   lined.length > 0 && lined.every(r => has(r.ours) && has(r.modelOnly)),
   lined.filter(r => !has(r.ours)).length + ' of ' + lined.length + ' have no number');
ok('and a book number to have been shrunk toward',
   lined.every(r => has(r.book)),
   'an over/under posts both sides at the open, so the de-vig is real there');
ok('so a combination of them is a number rather than NaN',
   lined.length >= 2 && isFinite(betProb(lined[0]) * betProb(lined[1])));

// ── The under is priced at the under's price ────────────────────────────
//
// An under leg used to carry the OVER's price while flipping every
// probability: harmless at -110 both ways, a different bet at -160/+130.
const twoSided = rowsFor('rec', 'all').find(r => has(r.odds) && has(r.underOdds)
                                                 && r.odds !== r.underOdds);
if (twoSided) {
  const o = legOf(twoSided, 'over'), u = legOf(twoSided, 'under');
  ok('the under leg is not paid at the over\'s price',
     u.odds !== o.odds && u.dec !== o.dec, o.odds + ' vs ' + u.odds);
  ok('and its probability is the other side of the same line',
     Math.abs((o.p + u.p) - 1) < 1e-9, o.p + ' + ' + u.p);
  ok('the two sides do not both look like value',
     !(o.odds > 0 && u.odds > 0) || twoSided.thin,
     'a two-way market with both sides plus-money has no margin in it');
} else {
  ok('a two-sided count row exists to check the under price on', false,
     'no row carries both an over and an under price');
}
// Asserted by rendering rather than by matching the source. The column is
// only useful if it reaches the page, and a regex over the source would pass
// on a column defined and never appended.
S.market = 'rec'; S.fw.view = 'priced';
const recHead = textOf(pageWeek()).join(' ');
ok('the count board shows the price every money figure is computed from',
   /\bOdds\b/.test(recHead),
   'EV $100 cannot be checked against a price that is not on screen');
ok('and still shows the line it is a price for',
   /\bLine\b/.test(recHead) && /EV \$100/.test(recHead));
S.fw.view = 'all';

// ── The combination says what it is ─────────────────────────────────────
ok('a count leg names its line, not just the player',
   /o' \+ r\.line\.toFixed\(1\)/.test(PAGE_SRC),
   '"St. Brown" and "St. Brown over 5.5" are different bets');

// ── Unpriced players are reachable on Combinations ──────────────────────
//
// They were never filtered out on purpose. The pool is capped at the
// COMBO_POOL_MAX players we rate highest, and those are the ones books have
// already quoted, so the cap did the excluding.
S.market = 'any';
const tdBoard = rowsFor('any', 'all').filter(r => has(r.ours));
const topN = tdBoard.slice().sort((a, b) => b.ours - a.ours).slice(0, COMBO_POOL_MAX);
ok('the cap alone hides every unpriced player',
   tdBoard.some(r => !r.priced) && topN.every(r => r.priced),
   'if the top ' + COMBO_POOL_MAX + ' already held an unpriced player the '
   + 'control would be unnecessary');
const unpricedPool = applyFilters(tdBoard, { q: '', game: '', pos: '', priced: 'unpriced' });
ok('and the Priced control reaches them',
   unpricedPool.length >= 2 && unpricedPool.every(r => !r.priced),
   unpricedPool.length + ' unpriced players');
ok('an unpriced slip still has a chance, just no payout',
   isFinite(betProb(unpricedPool[0]) * betProb(unpricedPool[1]))
   && !has(unpricedPool[0].dec));
ok('the Combinations page passes the control through',
   /priced: kind === 'td' \? \(c\.priced \|\| 'all'\) : 'all'/.test(PAGE_SRC));

// ── Expected scorers is about the fixture, not the filter ───────────────
//
// It used to be built from the rows on screen, so a fixture whose shortlisted
// players all came from one side printed that side's total as the game's,
// with the other half reading "—" and the bar pinned at 100%.
ok('the game card is built from the whole board',
   /function gameCard\(game, key\)[\s\S]{0,400}?rowsFor\(key, 'all'\)/.test(PAGE_SRC),
   'taking the filtered rows makes a filtered board look like a broken card');
ok('and it does not call an over/under projection a scorer',
   /kind === 'ou' \? marketLabel\(key\)\.toLowerCase\(\) : 'scorers'/.test(PAGE_SRC));
ok('nor count a player once per line he is quoted at',
   /seen\[r\.player\] \? false : \(seen\[r\.player\] = 1\)/.test(PAGE_SRC));

// ── Saved cards show the round robin ────────────────────────────────────
S.market = 'any';
const legs3 = rowsFor('any', 'all').filter(r => has(r.dec)).slice(0, 3)
  .map(r => legOf(r));
const pf = portfolio(legs3, 10, 0);
ok('the breakdown is one component, not two copies',
   (PAGE_SRC.match(/\['Legs in', 'Chance', 'Net'\]/g) || []).length === 1,
   'the slip and the card must not be able to disagree about the same slip');
const grid = brkTable(pf.rows, pf.slips, 3);
const gtxt = textOf(grid).join(' ');
ok('a card breakdown names every outcome from all-in to none',
   /3 of 3/.test(gtxt) && /0 of 3/.test(gtxt), gtxt);
ok('and carries a chance and a net for each',
   pf.rows.length === 4 && pf.rows.every(r => has(r.chance) && has(r.net)));
ok('a null chance prints as a dash rather than 0%',
   /—/.test(textOf(brkTable([{ hit: 1, slipsWon: 0, chance: null, net: -10 }], 1, 2)).join(' ')),
   'a combination slip only ever computed its all-hit probability');

// Net is linear in the stake, which is what lets a saved curve be re-read.
const twice = portfolio(legs3, 20, 0);
ok('doubling the stake doubles every net',
   pf.rows.every((r, i) => Math.abs(r.net * 2 - twice.rows[i].net) < 1e-9),
   'rescaling a saved curve would be wrong if it were not');
ok('and leaves every chance alone',
   pf.rows.every((r, i) => Math.abs(r.chance - twice.rows[i].chance) < 1e-12));
const scaled = scaleRows(pf.rows, 2);
ok('scaleRows reproduces a re-priced curve exactly',
   scaled.every((r, i) => Math.abs(r.net - twice.rows[i].net) < 1e-9));
ok('a settled card is not rescalable',
   /Rescaling\s*\n?\s*\/\/ a settled card would restate what was actually won/.test(PAGE_SRC)
   || /pend\) \{[\s\S]{0,300}?Stake per slip/.test(PAGE_SRC),
   'the one number on the page that is not a projection');
ok('the stake box has a focus key of its own',
   /'data-fk': 'stake-' \+ p\.id/.test(PAGE_SRC),
   'two pending parlays share a name, so an aria-label is not a unique handle');

// ── Six markets through one board ───────────────────────────────────────
//
// The menu resolution used to be `key === 'first' ? 1 : 0` with receptions
// special-cased beside it — a conditional that has to be edited in four
// places every time a market is added, and was.
S.market = 'any';
ok('every menu market resolves to a payload',
   MENU.every(g => g.items.every(([k]) => marketOf(k) && typeof marketOf(k) === 'object')),
   MENU.flatMap(g => g.items.map(([k]) => k)).join(','));
ok('and none of them resolves to the same block as another',
   (() => { const seen = new Set();
     for (const g of MENU) for (const [k] of g.items) {
       if (!served(k)) continue;
       const m = marketOf(k);
       if (seen.has(m)) return false;
       seen.add(m);
     } return true; })(),
   'two markets sharing one payload is how First TD read Anytime TD\'s board');
ok('a yardage board is served and is an over/under',
   served('rush') && KIND.rush === 'ou');
ok('its projection comes from `proj`, not the count market\'s `mu`',
   (() => { const r = rowsFor('rush', 'all').filter(x => has(x.proj));
            return r.length > 0 && r.every(x => has(x.proj)); })(),
   'a yardage model has no mean to read; the board shows its median');
ok('a yardage row prices its own line',
   rowsFor('rush', 'all').filter(x => x.priced).every(x => has(x.ours) && has(x.odds)));
ok('an unquoted yardage player is a projection with no bet',
   rowsFor('rush', 'all').some(x => !x.priced && has(x.proj) && !has(x.ours)));

// The blend weight shown is the one actually fitted, not a number typed in.
S.market = 'rush'; S.fw.view = 'priced';
const rushTxt = textOf(pageWeek()).join(' ');
ok('a yardage board renders', rushTxt.length > 200);
ok('and is labelled as itself, not as receptions',
   /Rushing yards/.test(rushTxt) && !/Receptions/.test(rushTxt), rushTxt.slice(0, 120));
ok('the served mix in the copy is read from the payload',
   /Math\.round\(w \* 100\)/.test(PAGE_SRC),
   'the Adj tooltip said "17% the model, 83% the book" for every market');
ok('a yardage market states its own graded record',
   /served as 6% our number and 94%/.test(gradedNote('rush')), gradedNote('rush'));
ok('and does not claim an edge',
   /Not a betting edge/.test(gradedNote('rush')));

// An over/under slip must not borrow the touchdown correlation, and a
// touchdown slip must still get it.
//
// Only the first of those two can fail today, and the comment says so rather
// than implying otherwise. No yardage or receptions payload carries a `cover`
// block, so `M0` returning the market instead of `{}` for an over/under slip
// changes nothing that can be observed — the guard in `M0` is defensive, not
// a fix for a bug that was there. The second assertion pins the payload
// invariant that makes it defensive: add a fitted correlation to an
// over/under block later and this is what says the guard has started
// mattering.
(() => {
  const rho = m => { S.slip = { market: m, legs: [], size: 0, stake: 10, stakeRaw: '10' };
                     return ((M0() || {}).cover || {}).rho; };
  const td = rho('any');
  ok('a touchdown slip uses the fitted teammate correlation',
     has(td) && td !== 0, String(td));
  ok('and a line slip prices its legs independently',
     !has(rho('rush')) && !has(rho('rec')),
     'that correlation is about SCORING — one offence stalls and neither of '
     + 'its players gets in. Nothing has measured it for a yardage line.');
})();
S.slip = { market: 'any', legs: [], size: 0, stake: 10, stakeRaw: '10' };
S.market = 'any'; S.fw.view = 'all';

// ── One row per player ──────────────────────────────────────────────────
//
// A board carries one row per (player, line) and books do not agree on the
// line. On closing prices across the archive: 8.69 lines per quarterback on
// passing yards, 5.4 per receiver, 5.0 per back — and 2.03 even on
// receptions, where only 45% of player-weeks carry a single line. They are
// not duplicates; each is a real bet. But a board that prints a man eight
// times leads with whichever of his lines sorted highest, which is usually
// the friendliest single quote.
S.market = 'rush'; S.fw.view = 'priced'; S.fw.allLines = false;
(() => {
  const priced = rowsFor('rush', 'all').filter(r => r.priced);
  const shown = oneLine(priced, { allLines: false });
  const names = new Set(shown.map(r => r.player));
  // Asserted on the RENDERED board, not on the helper. Calling `oneLine` here
  // and checking its output passes with the call site deleted from
  // `pageWeek`, which is the only place it matters — and did.
  //
  // Counted by NAME, not by line value. Checking that no non-consensus line
  // appears anywhere on the board is wrong on a real slate: with 63 players
  // one man's discarded 24.5 is another man's consensus 24.5, so the
  // assertion failed on live data while passing on a four-player fixture.
  const onBoard = txt(pageWeek());
  const dupes = priced.filter(r => !r.bestLine);
  const seen = n => onBoard.split(n).length - 1;
  const twice = [...new Set(dupes.map(r => r.player))].filter(n => seen(n) > 1);
  ok('a yardage board shows each player once',
     dupes.length > 0 && twice.length === 0,
     dupes.length + ' non-consensus lines; still doubled: '
     + twice.slice(0, 3).join(', '));
  ok('and the helper agrees with what was rendered',
     shown.length === names.size && shown.length < priced.length,
     shown.length + ' rows for ' + names.size + ' players, from ' + priced.length);
  ok('and the row it keeps is the line the most books drew',
     shown.every(r => priced.filter(o => o.player === r.player)
                            .every(o => (o.nBooks || 0) <= (r.nBooks || 0))),
     'picking each player\'s best PRICE instead triples the share of one-book '
     + 'rows, which is the band the model is measurably fooled by');
  ok('the toggle brings the rest back',
     oneLine(priced, { allLines: true }).length === priced.length);
  ok('and the chip counts what is hidden, not every row’s sibling count',
     extraLines(priced) === priced.length - shown.length,
     'summing nLines-1 over all rows reported 322 hidden on a board with 95');
})();

// Combinations collapses unconditionally — a parlay cannot hold one player
// twice, whatever the board is set to.
(() => {
  S.fw.allLines = true;
  const pool = oneLine(rowsFor('rush', 'all').filter(r => r.priced), null);
  const names = pool.map(r => r.player);
  ok('a combination pool never holds one player at two lines',
     new Set(names).size === names.length,
     'Mahomes over 215.5 AND over 217.5 is two legs of one event');
  ok('and that does not follow the board toggle',
     /oneLine\(rowsFor\(key, 'all'\), null\)/.test(PAGE_SRC));
  S.fw.allLines = false;
})();

// ── Formatting ──────────────────────────────────────────────────────────
ok('a gap of two probability points reads to two places',
   spp(14.2857) === '+14.29' && spp(-0.4) === '-0.40', spp(14.2857));
// The fixture's yardage floor and ceiling are 30.72 and 97.41, so a formatter
// that rounds is visibly different from one that does not. A fixture carrying
// round numbers cannot tell them apart, and did not.
//
// Two places on every market, not only on counts. Rounding yards to whole
// numbers was an argument about the model's confidence applied to a column
// that is not reporting confidence — it is separating players, and two
// receivers who both project 38 are 38.24 and 38.41.
ok('a yardage projection keeps two places, like a count',
   (() => { S.market = 'rush'; S.fw.view = 'priced';
            const t = textOf(pageWeek()).join(' ');
            // Taken from the rows rather than typed in. Hard-coding the
            // fixture's 30.72 passed on the fixture and failed on the live
            // payload, which has neither of those numbers in it — the same
            // mistake as asserting a line VALUE instead of a player name.
            const r = oneLine(rowsFor('rush', 'all').filter(x => x.priced), null)
              .find(x => has(x.lo) && Math.abs(x.lo - Math.round(x.lo)) > 0.02);
            return !!r && t.indexOf(r.lo.toFixed(2)) >= 0; })(),
   'a column printing 38.24 and 38.41 both as 38 has stopped separating the '
   + 'two players it exists to separate');
ok('and a count does too',
   (() => { S.market = 'rec'; S.fw.view = 'priced';
            const t = textOf(pageWeek()).join(' ');
            return /\d\.\d\d/.test(t); })());
ok('but a whole number is not padded to .00',
   num2(31) === '31' && num2(30.72) === '30.72', num2(31));
S.market = 'any'; S.fw.view = 'all';

// ── A pending card does not restate its own breakdown ───────────────────
//
// Pays / All hit / Legs in were three numbers above a table that gives all
// three and the outcomes they leave out. Settled, the same panel stops being
// a restatement and becomes the answer — which row actually happened.
(() => {
  const legsP = rowsFor('any', 'all').filter(r => has(r.dec)).slice(0, 2).map(r => legOf(r));
  const f = portfolio(legsP, 10, 0);
  const card = p => txt(parlayCard(settle(p)));
  const base = { id: 'tp', name: 'test', market: 'any', marketLabel: 'Anytime TD',
                 week: DATA.week, season: DATA.season, size: 0, stake: 10,
                 rowStake: 10, slips: f.slips, outlay: f.outlay, chance: f.all,
                 priced: true, dec: 3.0, ev: f.ev, legs: legsP,
                 rows: f.rows.map(r => ({ hit: r.hit, slipsWon: r.slipsWon,
                   chance: r.chance, net: r.net, netLo: r.netLo, netHi: r.netHi })) };
  const pending = card(base);
  ok('a pending card shows the breakdown', /Legs in/.test(pending) && /Chance/.test(pending));
  ok('and does not also carry a Pays / All hit panel above it',
     !/All hit/.test(pending),
     'the top row of the breakdown IS Pays and All hit');
  ok('a pending card still says what is at risk',
     /at risk/.test(pending), pending.slice(0, 160));

  // Settled: `DATA.results` decides, so mark both legs hit.
  const res = {};
  legsP.forEach(l => { res[DATA.week + '|' + l.id] = 'hit'; });
  const realResults = DATA.results;
  DATA.results = res;
  const done_ = card(base);
  DATA.results = realResults;
  ok('a settled card says which row happened and what came back',
     /Result/.test(done_) && /Legs in/.test(done_), done_.slice(0, 200));
})();

// ── The Model page ──────────────────────────────────────────────────────
(() => {
  S.route = 'model'; S.fam = {};
  const page = pageModel();
  const t = txt(page);

  // Every served market, and nothing that is not served.
  const want = [];
  MENU.forEach(g => g.items.forEach(([k]) => { if (served(k)) want.push(k); }));
  ok('every served market has a card on the Model page',
     want.every(k => t.indexOf(marketLabel(k)) >= 0),
     want.filter(k => t.indexOf(marketLabel(k)) < 0).join(','));

  // No colour that means "something has gone wrong". A standing finding is
  // not an alert.
  const modelBlock = PAGE_SRC.slice(PAGE_SRC.indexOf('function pageModel'),
                                   PAGE_SRC.indexOf('function stat('));
  ok('the Model page raises no alert boxes',
     !/warnbox|badbox/.test(modelBlock),
     'provenance belongs in the registry; a measured finding does not need red');

  // But the findings themselves survive, because the boards link here for them.
  ok('and still says what backing this model has returned',
     /−19\.6%|-19\.6%/.test(t), 'the graded record is the point of the page');
  ok('and what each line market is served as',
     /17% our number/.test(t) && /6% our number/.test(t));

  // The one unambiguous positive, with the reason it is not a bet.
  ok('it leads with what the model is measurably best at',
     /What it is best at/.test(t) && /\+25\.0%/.test(t), t.slice(0, 200));
  ok('and says why that is not money',
     /no sportsbook lets you lay a player/.test(t) && /commission/.test(t),
     'a +25% headline with no commission line would be the one dishonest '
     + 'screen in a project built around not having one');

  // Features: kept, folded.
  const famName = ((marketOf('any').recipe || {}).families || [{}])[0].name || '';
  ok('feature families are folded away by default',
     !!famName && t.indexOf(famName) < 0 && /feature families/.test(t));
  S.fam.any = true;
  const open = txt(pageModel());
  ok('and open on request',
     open.indexOf(famName) >= 0, 'the chip should unfold the table');
  ok('with a worth a top-1 accuracy could actually lose',
     !/\+[1-9]\d\d\.\d+ pp/.test(open) && /\+\d\.\d\d pp/.test(open),
     'these are already percentage points; multiplying by 100 printed '
     + '"+282.94 pp" against a top-1 of 49.6%');
  S.fam = {}; S.route = 'week';
})();

// ── A team's total is not always a sum ──────────────────────────────────
//
// Anytime TD adds because several players each score; receptions, receiving
// and rushing yards add because several players each catch and carry — team
// receiving comes out around 222 a game, which is what a team throws for.
// Passing yards does NOT add: one quarterback throws them, and every backup on
// the board carries a projection assuming a normal workload of his own.
// Summed, Minnesota's four quarterbacks made 631 passing yards.
(() => {
  const teamTotals = key => {
    const rows = oneLine(rowsFor(key, 'all').filter(r => has(r.proj)), null);
    const games = [...new Set(rows.map(r => r.game).filter(Boolean))];
    const g = games[0];
    const mine = rows.filter(r => r.game === g);
    const byTeam = {};
    mine.forEach(r => { (byTeam[r.team] = byTeam[r.team] || []).push(r.proj); });
    return { game: g, teams: Object.values(byTeam) };
  };

  ['passyds', 'recyds', 'rush'].forEach(key => {
    if (!served(key)) return;
    const { game, teams } = teamTotals(key);
    S.market = key; S.fw.view = 'priced'; S.fw.game = game;
    const t = txt(pageWeek());
    const sum = teams.reduce((a, v) => a + v.reduce((x, y) => x + y, 0), 0);
    const top = teams.reduce((a, v) => a + Math.max.apply(null, v), 0);
    const shown = parseFloat((t.match(/(?:add to|put) ([\d.]+)/) || [])[1]);
    const want = key === 'passyds' ? top : sum;
    ok('the ' + marketLabel(key) + ' game card totals its side correctly',
       Math.abs(shown - want) < 0.75,
       'card says ' + shown + '; sum is ' + sum.toFixed(1)
       + ', starters-only is ' + top.toFixed(1));
    if (key === 'passyds') {
      ok('and says why passing yards are not added up',
         /one quarterback throws them/.test(t), t.slice(0, 160));
      ok('and a team total lands where a team total lands',
         shown / 2 > 150 && shown / 2 < 320,
         'per side ' + (shown / 2).toFixed(0) + ' yards');
    }
    S.fw.game = '';
  });
  S.market = 'any'; S.fw.view = 'all';
})();

// ── The fixture, not the database key ───────────────────────────────────
//
// The touchdown payload carries a readable "DET @ BUF"; the line markets carry
// only the id. Their player cell and their Game filter both showed
// "2026_02_DET_BUF" — the dropdown read as a list of database keys.
(() => {
  MENU.forEach(g => g.items.forEach(([k]) => {
    if (!served(k)) return;
    const games = [...new Set(rowsFor(k, 'all').map(r => r.game).filter(Boolean))];
    ok(marketLabel(k) + ' filters by fixture, not by row id',
       games.length > 0 && games.every(x => /^[A-Z]{2,3} @ [A-Z]{2,3}$/.test(x)),
       games.slice(0, 2).join(' · '));
  }));
  S.market = 'rush'; S.fw.view = 'priced'; S.fw.game = '';
  ok('and the fixture is in the player cell beside his team',
     /[A-Z]{2,3} ·\s+[A-Z]{2,3} @ [A-Z]{2,3}/.test(txt(pageWeek())),
     'the touchdown board has shown this since it existed');
  ok('a value that is already a fixture is passed through, not blanked',
     fixtureOf('DET @ BUF') === 'DET @ BUF'
     && fixtureOf('2026_02_DET_BUF') === 'DET @ BUF'
     && fixtureOf(null) === '',
     'returning empty for an unparsed id empties the cell AND the filter, '
     + 'and an empty fixture renders as an empty cell rather than an error');
  S.market = 'any'; S.fw.view = 'all';
})();

// ── A defence does not catch passes ─────────────────────────────────────
//
// It is on the shared feature matrix because it scores touchdowns, and it
// arrived on the line boards carrying 2.34 projected receiving yards for
// Buffalo — one row per team, all 32 of them named "DEF/ST", so anything keyed
// on a player's name folds them into one row belonging to nobody.
(() => {
  const isDef = r => /DEF|ST$/.test(r.player || '');
  MENU.forEach(g => g.items.forEach(([k]) => {
    if (!served(k) || KIND[k] !== 'ou') return;
    ok('no defence is on the ' + marketLabel(k) + ' board',
       !rowsFor(k, 'all').some(isDef),
       rowsFor(k, 'all').filter(isDef).length + ' DEF/ST rows');
  }));
  ok('but a defence stays on the touchdown board, where it can score',
     rowsFor('any', 'all').some(isDef),
     'defensive touchdowns are a real market and this is it');
})();

done();
