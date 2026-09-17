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
   'ev100', 'betProb']);
const { S, rowsFor, applyFilters, slipMath, choose, settle, legOf, PAGES, has,
        combosOf, saveCombo, comboSaved, COMBO_POOL_MAX,
        chanceTxt, slipSlot, slipHandle, clearSlip, table,
        ev100, betProb } = x;

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
ok('sorting is on the value, not the rendered string',
   (() => { const s = applyFilters(all, { ...f, sort: 'ours', dir: -1 });
            for (let i = 1; i < s.length; i++) if (s[i - 1].ours < s[i].ours) return false;
            return true; })());

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
ok('receptions shows far more than the book has quoted',
   rec.length > quoted.length * 5, rec.length + ' rows, ' + quoted.length + ' quoted');
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

done();
