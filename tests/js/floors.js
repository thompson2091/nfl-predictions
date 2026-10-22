// The 90% floors view and its Record block, rendered.
//
// The floors are set and graded in Python; this checks the half only the
// page can get wrong: that the view says these are not bets, quotes the
// measured loss from the payload rather than a number typed into the page,
// shows a market that missed its target with a warning instead of hiding it,
// and that the Record block counts pending floors once and apart.
//
//   node tests/js/floors.js <payload.json> <page.js>
const { loadPage, textOf, reporter } = require('./domstub.js');

const { ok, done } = reporter();
const x = loadPage(process.argv[2], process.argv[3],
  ['V', 'render', 'DATA', 'v3Floors', 'v3RecFloors', 'v3MarketControls']);
const { V, render, DATA } = x;
const pane = () => document.getElementById('app').innerHTML;
const txt = h => textOf({ _html: h }).join(' ');

V.tab = 'props'; V.week = null; V.game = null; V.q = ''; V.shown = 25;
V.market = 'recyds'; V.filter = 'floor';
let err = null;
try { render(); } catch (e) { err = e; }
ok('the floors view renders', !err, err && (err.message + '\n' + err.stack));
let h = pane();
ok('the floors filter is on the bar', h.indexOf('data-v3filter="floor"') >= 0
   && h.indexOf('seg--7') >= 0);
ok('it says these are not bets', h.indexOf('Not bets.') >= 0, txt(h));
ok('it quotes the measured loss from the payload',
   h.indexOf('lost about $4 per $100 on 2025') >= 0, txt(h));
ok('a passing market shows its held-out record',
   h.indexOf('floors held 90.8% of the time over 1,800 player-games') >= 0
   && h.indexOf('Below 90') < 0, txt(h));
ok('the floor and the book price are on the row',
   h.indexOf('Over 24.5') >= 0 && h.indexOf('-900') >= 0, txt(h));
ok('a missing rung leaves the price blank',
   h.indexOf('Over 10.5') >= 0 && (h.match(/-900|\+\d{3}/g) || []).length === 1);
ok('a weak band marks its rows',
   (h.match(/recthin--warn/g) || []).length === 1
   && h.indexOf('projected under 30') >= 0, txt(h));
ok('the bench player off the board is not listed', h.indexOf('Bench') < 0);
ok('no sort control on a list with one order', h.indexOf('data-v3sortsel') < 0);

V.market = 'passyds'; render(); h = pane();
ok('a market below target carries a warning and its rows',
   h.indexOf('Below 90.0% in testing') >= 0 && h.indexOf('Alpha') >= 0, txt(h));

V.market = 'any'; render(); h = pane();
ok('a touchdown market explains floors are over/under only',
   h.indexOf('four over/under markets') >= 0, txt(h));

V.market = 'recyds'; V.week = 3; render(); h = pane();
ok('a past week points to the record', h.indexOf('Record page') >= 0, txt(h));
V.week = null;

V.filter = 'all'; render();
ok('the board filter still renders after floors', pane().indexOf('v3rows') >= 0);

// ── The Record block ─────────────────────────────────────────────────────
const rec = x.v3RecFloors(DATA.scorecard.floors);
ok('the record grades floors per market against the target',
   rec.indexOf('90% floors') >= 0 && rec.indexOf('Catches') >= 0
   && rec.indexOf('92.5%') >= 0 && rec.indexOf('90.0%') >= 0, txt(rec));
ok('pending floors are counted once and apart',
   rec.indexOf('Waiting') >= 0 && (rec.match(/>3</g) || []).length === 1, txt(rec));
ok('a market holding below target is named',
   rec.indexOf('Passing yards is holding below 90.0%') >= 0
   && rec.indexOf('class="dn"') >= 0, txt(rec));
ok('no record yet says so rather than vanishing',
   x.v3RecFloors(null).indexOf('No floors have been recorded') >= 0);
V.tab = 'record';
err = null;
try { render(); } catch (e) { err = e; }
ok('the record screen renders with the floors block', !err
   && pane().indexOf('sbfloor') >= 0, err && err.message);

done();
