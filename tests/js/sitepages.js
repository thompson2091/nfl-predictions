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
  ['S', 'rowsFor', 'applyFilters', 'slipMath', 'choose', 'settle', 'legOf', 'PAGES', 'has']);
const { S, rowsFor, applyFilters, slipMath, choose, settle, legOf, PAGES, has } = x;

const txt = n => textOf(n).join(' ');

// ── Every page renders ──────────────────────────────────────────────────
const pages = { week: pageWeek, saved: pageSaved, ladder: pageLadder, model: pageModel };
Object.entries(pages).forEach(([name, fn]) => {
  let out = null, err = null;
  try { out = fn(); } catch (e) { err = e; }
  ok('page "' + name + '" renders', !err, err && (err.message + '\n' + err.stack));
  if (out) ok('page "' + name + '" is not blank', txt(out).trim().length > 40);
});

// ── The nav is four pages, and the shortlist is not one of them ─────────
ok('nav carries exactly the four pages', PAGES.length === 4,
   PAGES.map(p => p[0]).join(','));
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
DATA.results = { 'any|A': 'hit', 'any|B': 'hit', 'any|C': 'miss' };
ok('every leg hitting wins a full cover', settle(mk(['any|A', 'any|B'])).status === 'Won');
ok('one leg missing loses a full cover', settle(mk(['any|A', 'any|C'])).status === 'Lost');
const rr = settle(mk(['any|A', 'any|B', 'any|C'], { size: 2, slips: 3, outlay: 30 }));
ok('a by-2s with two hits still wins', rr.status === 'Won', rr.status);
ok('and pays once per winning pair, not once overall',
   Math.abs(rr.net - (10 * 3 * 1 - 30)) < 1e-9, String(rr.net));
ok('an unknown leg keeps the whole slip pending rather than losing it',
   settle(mk(['any|A', 'any|Unknown Person'])).status === 'Pending',
   'a name that fails to join must not read as a loss');

done();
