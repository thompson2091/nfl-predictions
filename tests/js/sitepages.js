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
   'chanceTxt', 'slipSlot', 'slipHandle', 'clearSlip']);
const { S, rowsFor, applyFilters, slipMath, choose, settle, legOf, PAGES, has,
        combosOf, saveCombo, comboSaved, COMBO_POOL_MAX,
        chanceTxt, slipSlot, slipHandle, clearSlip } = x;

const txt = n => textOf(n).join(' ');

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
ok('shortlist rows carry the graded band', short.every(r => r.band !== undefined));
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
ok('the full cover is one slip', m.slips.length === 1 && m.k === 3);
ok('all-hit is the product of the legs',
   Math.abs(m.all - priced.reduce((a, r) => a * r.ours, 1)) < 1e-9);
S.slip.size = 2;
m = slipMath();
ok('by-2s over three legs is three slips', m.slips.length === 3, String(m.slips.length));
ok('and risks three stakes', Math.abs(m.outlay - 30) < 1e-9, String(m.outlay));
ok('the breakdown covers every outcome that can pay',
   m.rows.length === 2 && m.rows[0].hit === 3 && m.rows[1].hit === 2);
ok('the chances in the breakdown are probabilities',
   m.rows.every(r => r.chance >= 0 && r.chance <= 1));
S.slip.size = 0;

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
ok('one leg missing loses a full cover', settle(mk(['any|A', 'any|C'])).status === 'Lost');
const rr = settle(mk(['any|A', 'any|B', 'any|C'], { size: 2, slips: 3, outlay: 30 }));
ok('a by-2s with two hits still wins', rr.status === 'Won', rr.status);
ok('and pays once per winning pair, not once overall',
   Math.abs(rr.net - (10 * 3 * 1 - 30)) < 1e-9, String(rr.net));
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
ok('an empty, closed slip takes no width from the board', slipSlot(true) === null);
ok('and offers no handle when there is nothing in it', slipHandle() === null);

const rows = rowsFor('any', 'all').filter(r => r.priced).slice(0, 2);
S.slip.legs = rows.map(r => legOf(r));
ok('a closed slip with legs still yields the board its width', slipSlot(true) === null);
const h = slipHandle();
ok('but offers a handle saying how many are in it', h !== null && /2/.test(txt(h)), h && txt(h));
S.slipOpen = true;
ok('opening it brings the panel back', slipSlot(true) !== null);
ok('with the legs still in it', txt(slipSlot(true)).indexOf(rows[0].player) >= 0);

// A conflict has to be visible even with the slip put away, or the prompt is
// posted to a panel nobody can see.
S.slipOpen = false;
S.conflict = { row: rowsFor('first', 'all')[0], side: null };
ok('a market conflict forces the panel open', slipSlot(true) !== null);
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
   /Clear/.test(textOf(slipSlot(true)).join(' ')));
clearSlip();
ok('clearing removes every leg at once', S.slip.legs.length === 0);
ok('and resets the round robin with them', S.slip.size === 0);
ok('and keeps the stake, which is a preference not a pick', S.slip.stake === 10);
ok('an emptied slip stops taking the board\'s width', S.slipOpen === false && slipSlot(true) === null);
ok('and offers no handle, because there is nothing to come back to', slipHandle() === null);

done();
