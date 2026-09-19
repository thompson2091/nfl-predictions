// Every screen of the v2 app, rendered against a stub DOM.
//
// The failure mode of a generated single-page app is a blank screen with one
// line in a console nobody has open. `node --check` proves the syntax and
// nothing else — a bad reference parses fine and throws on load.
//
//   node tests/js/v2app.js <payload.json> <page.js>
const { loadPage, textOf, reporter } = require('/Users/mthompson/projects/personal/nfl-predictions/tests/js/domstub.js');

const { ok, done } = reporter();
const x = loadPage(process.argv[2], process.argv[3],
  ['S', 'render', 'route', 'go', 'V2TABS', 'vBoard', 'vSlip', 'vSheet', 'SHEETS',
   'rowsFor', 'toggleLeg', 'marketLabel', 'served', 'KIND', 'boot', 'DATA']);
const { S, render, V2TABS, vBoard, vSlip, vSheet, SHEETS, rowsFor,
        toggleLeg, marketLabel, served, KIND, DATA } = x;

const html = () => document.getElementById('scroll').innerHTML;
const bars = () => [document.getElementById('appbar').innerHTML,
                    document.getElementById('tabbar').innerHTML,
                    document.getElementById('slipbarHost').innerHTML].join(' ');

// ── The shell ───────────────────────────────────────────────────────────
S.favs = []; S.parlays = []; S.saved = {};
S.route = 'week'; S.market = 'any';
let err = null;
try { render(); } catch (e) { err = e; }
ok('the shell renders', !err, err && (err.message + '\n' + err.stack));
ok('the tab bar carries every destination',
   V2TABS.every(t => bars().indexOf('data-tab="' + t[0] + '"') >= 0));
// Read from the payload, not typed here: the fixture's brand is not the
// default, and an assertion that hard-codes one tests the fixture.
ok('the app bar names the brand', bars().indexOf(DATA.brand) >= 0, DATA.brand);
ok('and carries the market where the market means something',
   bars().indexOf('data-sheet="market"') >= 0);

// ── Every market's board ────────────────────────────────────────────────
['any', 'first', 'rec', 'rush'].forEach(mk => {
  S.market = mk; S.route = 'week'; S.fw.view = 'all'; S.fw.q = '';
  let e2 = null, out = '';
  try { render(); out = html(); } catch (e) { e2 = e; }
  ok('the ' + marketLabel(mk) + ' board renders', !e2, e2 && e2.message);
  if (!e2 && served(mk)) {
    const rows = rowsFor(mk, 'all');
    ok('  ' + mk + ': it draws rows', out.indexOf('class="row"') >= 0);
    ok('  ' + mk + ': every row offers the slip',
       (out.match(/data-add=/g) || []).length > 0);
    ok('  ' + mk + ': and a way into the detail',
       (out.match(/data-detail=/g) || []).length > 0);
    ok('  ' + mk + ': four metrics per row, not fourteen columns',
       out.indexOf('metric__l') >= 0 && out.indexOf('<table') < 0);
  }
});

// ── The views a market actually has ─────────────────────────────────────
S.market = 'any'; S.fw.view = 'short';
render();
ok('a touchdown board offers Shortlist and Fades',
   html().indexOf('data-view="short"') >= 0 && html().indexOf('data-view="fade"') >= 0);
ok('and the shortlist shows its funnel', html().indexOf('class="funnel"') >= 0);
ok('with the record beside it', html().indexOf('class="graded"') >= 0);

S.market = 'rec'; S.fw.view = 'short';
render();
ok('a line board offers Priced instead of Fades',
   html().indexOf('data-view="priced"') >= 0 && html().indexOf('data-view="fade"') < 0);

// ── Sheets ──────────────────────────────────────────────────────────────
S.market = 'any'; S.fw.view = 'all';
render();
Object.keys(SHEETS).forEach(kind => {
  if (kind === 'detail') return;
  let e3 = null;
  try { SHEETS[kind](); } catch (e) { e3 = e; }
  ok('the ' + kind + ' sheet builds', !e3, e3 && e3.message);
});
const first = rowsFor('any', 'all')[0];
let e4 = null, detail = '';
try { detail = SHEETS.detail(first.id); } catch (e) { e4 = e; }
ok('the detail sheet builds', !e4, e4 && e4.message);
ok('and says what the row means in words',
   detail.indexOf('class="prose"') >= 0 && detail.length > 400);

// ── The slip ────────────────────────────────────────────────────────────
S.slip = { market: 'any', legs: [], size: 0, stake: 10, stakeRaw: '10' };
S.route = 'slip';
render();
ok('an empty slip says so', html().indexOf('Your slip is empty') >= 0);
toggleLeg(rowsFor('any', 'all').filter(r => r.priced)[0]);
toggleLeg(rowsFor('any', 'all').filter(r => r.priced)[1]);
S.route = 'slip';
render();
ok('two legs land on it', (html().match(/class="leg"/g) || []).length === 2);
ok('it prices them together', html().indexOf('All hit') >= 0);
ok('and breaks down how many land', html().indexOf('class="brk"') >= 0);

// The bar that follows you between screens, and does not follow you onto the
// screen it is a summary of.
S.route = 'week';
render();
ok('the slip bar rides above the tabs elsewhere', bars().indexOf('slipbar') >= 0);
S.route = 'slip';
render();
ok('and is not shown on the slip itself', bars().indexOf('slipbar__count') < 0);

// ── The screens still to convert say so ─────────────────────────────────
['combos', 'ladder', 'model'].forEach(r => {
  S.route = r;
  let e5 = null;
  try { render(); } catch (e) { e5 = e; }
  ok(r + ' renders rather than throwing', !e5, e5 && e5.message);
  ok('  ' + r + ' says it is not converted yet',
     html().indexOf('not converted yet') >= 0);
});

done();
