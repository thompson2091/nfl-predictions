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
   'rowsFor', 'toggleLeg', 'marketLabel', 'served', 'KIND', 'boot', 'DATA',
   'patchBoard', 'clearSlip', 'saveSlip', 'settle', 'wire', 'patchTotals']);
const { S, render, V2TABS, vBoard, vSlip, vSheet, SHEETS, rowsFor,
        toggleLeg, marketLabel, served, KIND, DATA } = x;

const html = () => document.getElementById('scroll').innerHTML;

// A click on a control carrying `data-<attr>="<val>"`, through the page's own
// delegated handler. `closest` is the thing under test: it is given the real
// selector the page builds and answers only if this control is in it.
x.wire();
// What `boot` does that matters here: put `route` on hashchange, so `go()`
// actually navigates instead of setting a string nobody reads.
window.addEventListener('hashchange', x.route);
function clickData(attr, val) {
  const node = {
    dataset: { [attr]: val },
    getAttribute: k => (k === 'data-' + attr ? val : null),
    closest(sel) {
      return sel.split(',').indexOf('[data-' + attr + ']') >= 0 ? node : null;
    },
  };
  let reached = false;
  const spy = { closest: sel => { const r = node.closest(sel); reached = !!r; return r; } };
  fireDoc('click', { target: spy });
  return reached;
}
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

// ── The other three screens ─────────────────────────────────────────────
['combos', 'ladder', 'model'].forEach(r => {
  S.route = r;
  let e5 = null;
  try { render(); } catch (e) { e5 = e; }
  ok(r + ' renders', !e5, e5 && e5.message);
  ok('  ' + r + ' is converted, not a placeholder',
     html().indexOf('not converted yet') < 0);
});

S.route = 'combos'; S.market = 'any'; S.cb.pool = 'all'; S.cb.legs = 3;
render();
ok('combos builds slips', html().indexOf('class="combo"') >= 0, html().slice(0, 200));
ok('and each offers to load itself', html().indexOf('data-load="0"') >= 0);
ok('and says how many it searched', html().indexOf('slips of 3') >= 0);

S.route = 'ladder';
render();
ok('the ladder draws its rungs', (html().match(/class="rung"/g) || []).length > 1);
ok('with its three fields', ['f-start', 'f-odds', 'f-bets']
   .every(id => html().indexOf('id="' + id + '"') >= 0));
ok('and an answer box that can be patched without them',
   html().indexOf('id="ladderout"') >= 0,
   'typing into a field must not replace the field');

S.route = 'model';
render();
ok('the model page reports every served market',
   (html().match(/class="keystats"/g) || []).length >= 2);
ok('and puts the features behind a tap', html().indexOf('data-fam=') >= 0);

// ── The count line is a component, not a bare div ───────────────────────
S.route = 'week'; S.market = 'any'; S.fw.view = 'all'; S.fw.q = '';
render();
ok('the count under the board is styled', html().indexOf('class="count"') >= 0);

// ── Typing never replaces the input ─────────────────────────────────────
// Which is the whole of the iOS zoom fix: the system scrolls and scales to a
// newly focused element, and re-rendering the screen per keystroke focused a
// brand-new one every time.
const before = document.getElementById('scroll').innerHTML;
ok('the board list is a box of its own', before.indexOf('id="boardlist"') >= 0);
S.fw.q = 'alpha';
x.patchBoard();
// Read the patched node, not the screen: the stub keeps `innerHTML` as a
// string rather than parsing it into children, so writing into `#boardlist`
// cannot show up inside `#scroll`'s string. A browser has no such gap.
const list = () => document.getElementById('boardlist').innerHTML;
ok('patching narrows the board',
   list().indexOf('Alpha Back') >= 0 && list().indexOf('Bravo') < 0,
   list().slice(0, 160));
ok('and never redraws the search input', list().indexOf('id="q"') < 0,
   'the input lives above the box that gets patched, which is the iOS fix');
S.fw.q = '';
x.patchBoard();

// ── Saved ───────────────────────────────────────────────────────────────
S.route = 'saved'; S.parlays = []; S.savedFilter = 'all';
render();
ok('an empty Saved page says so', html().indexOf('Nothing saved yet') >= 0);
ok('Saved has a tab of its own',
   bars().indexOf('data-tab="saved"') >= 0);
ok('and the tab bar carries all six', (bars().match(/data-tab=/g) || []).length >= 6);

// One saved slip, settled from the fixture's results map.
S.slip = { market: 'any', legs: [], size: 0, stake: 10, stakeRaw: '10' };
toggleLeg(rowsFor('any', 'all').filter(r => r.priced)[0]);
toggleLeg(rowsFor('any', 'all').filter(r => r.priced)[1]);
x.saveSlip();
S.route = 'saved';
render();
ok('a saved slip appears', (html().match(/data-open=/g) || []).length === 1,
   html().slice(0, 200));
ok('with a way to delete it', html().indexOf('data-del=') >= 0);
ok('and the filters over it', html().indexOf('data-sf="pending"') >= 0);
ok('and a record at the top', html().indexOf('class="keystats"') >= 0);

// ── Swipe to clear ──────────────────────────────────────────────────────
S.slip = { market: 'any', legs: [], size: 0, stake: 10, stakeRaw: '10' };
toggleLeg(rowsFor('any', 'all').filter(r => r.priced)[0]);
S.route = 'week';
render();
const bar = document.getElementById('slipbarHost').innerHTML;
ok('the slip bar has something under it to swipe to',
   bar.indexOf('class="slipdel"') >= 0);
ok('and that something clears the slip',
   bar.indexOf('data-act="clearslip"') >= 0);
ok('the bar is the thing that moves', bar.indexOf('id="slipwrap"') >= 0);



// ── An empty slip has no bar ────────────────────────────────────────────
// `slipMath` answers an empty slip with a real object, so the bar tested it
// for truthiness and got one. Then `allPriced([])` — an `every` over nothing
// — said the slip was fully priced, `parlayDec([])` handed back 1, and
// `decToAm(1)` is -100/0. The bar sat at the bottom of the screen saying
// "-Infinity" with nothing in it.
S.route = 'week';
x.clearSlip();
S.route = 'week';
render();
ok('an empty slip shows no bar at all',
   document.getElementById('slipbarHost').innerHTML === '',
   document.getElementById('slipbarHost').innerHTML);
ok('and nothing anywhere says Infinity',
   [html(), bars()].join(' ').indexOf('Infinity') < 0);

toggleLeg(rowsFor('any', 'all').filter(r => r.priced)[0]);
S.route = 'week';
render();
ok('one leg brings it back', bars().indexOf('slipbar__count') >= 0);
ok('priced, and saying so', bars().indexOf('Infinity') < 0
   && /slipbar__price num">[+−-]/.test(bars()), bars().slice(0, 300));



// ── A saved slip says what the slip said ────────────────────────────────
S.route = 'week';
x.clearSlip();
toggleLeg(rowsFor('any', 'all').filter(r => r.priced)[0]);
toggleLeg(rowsFor('any', 'all').filter(r => r.priced)[1]);
x.saveSlip();
S.route = 'saved'; S.savedFilter = 'all';
render();
const card = html();
ok('the saved card carries All hit', card.indexOf('All hit') >= 0);
// The VALUE, not the absence of the word "NaN". `has(NaN)` is false and
// `american('')` returns an empty string, so reading a `dec` that was never
// saved renders a blank where the price goes — silently, which is why the
// first version of this assertion passed against exactly that bug.
const totals = (card.match(/total__v num[^>]*>([^<]*)</g) || [])
  .map(t => t.slice(t.indexOf('>') + 1, -1));
ok('and a real price where Pays is',
   /^[+\u2212-]?\d+$/.test(totals[1] || ''),
   'Pays rendered ' + JSON.stringify(totals[1]) + ' — v1 stores no `dec`, so '
   + 'reading one off the record leaves this blank');
ok('and the EV at its own stake', card.indexOf('EV on $') >= 0);
ok('and the payout curve underneath', card.indexOf('class="brk"') >= 0);
ok('with its own stake box', card.indexOf('data-pstake=') >= 0);
ok('and boxes the stake can patch without redrawing itself',
   card.indexOf('id="ptot-') >= 0 && card.indexOf('id="pbrk-') >= 0);

// ── The breakdown is headed once ────────────────────────────────────────
S.route = 'slip';
render();
const slip = html();
ok('the breakdown has one set of headings',
   (slip.match(/Legs in/g) || []).length === 1, 'a secthead said it again');
ok('which are the table’s own', slip.indexOf('<thead>') >= 0);



// ── EV on the board ─────────────────────────────────────────────────────
S.route = 'week'; S.market = 'any'; S.fw.view = 'all'; S.fw.q = '';
render();
// ONE row. Sliced to the first and cut at the second, or the counts below
// are every row on the board at once — which still has the right ratio and
// none of the right numbers.
const rowsHTML = html().slice(html().indexOf('class="row"'));
const row = rowsHTML.slice(0, rowsHTML.indexOf('class="row"', 10));
// Each metric cell, with the classes it carries. Split on `<span
// class="metric` and every cell comes apart, because `metric__l` starts the
// same way — the first version of this produced sixteen empty labels and
// said so in the failure message, which is the only reason I noticed.
const cells = [];
const re = /<span class="metric([^"]*)"><span class="metric__l">([^<]*)</g;
let mm;
while ((mm = re.exec(row)) !== null) cells.push({ cls: mm[1], label: mm[2] });
const narrow = cells.filter(c => c.cls.indexOf('--wide') < 0).map(c => c.label);
const wide = cells.filter(c => c.cls.indexOf('--wide') >= 0).map(c => c.label);

ok('a phone gets five metrics', narrow.length === 5, narrow.join(' · '));
ok('and EV comes straight after Edge',
   narrow.indexOf('EV $100') === narrow.indexOf('Edge') + 1, narrow.join(' · '));
ok('with Open the one held back for a wide screen',
   wide.length === 1 && wide[0] === 'Open', wide.join(' · '));

// Every board shows the same five, Model included. A line board used to put
// the projection where Model goes, so the number that says what we thought on
// our own was missing from four of the six markets.
['any', 'rec', 'rush', 'recyds', 'passyds'].forEach(mk => {
  if (!served(mk)) return;
  S.market = mk; S.fw.view = 'all'; S.fw.q = '';
  render();
  const one = html().slice(html().indexOf('class="row"'));
  const cut = one.slice(0, one.indexOf('class="row"', 10) + 1 || undefined);
  const got = [];
  const re2 = /<span class="metric([^"]*)"><span class="metric__l">([^<]*)</g;
  let m2;
  while ((m2 = re2.exec(cut)) !== null) {
    if (m2[1].indexOf('--wide') < 0) got.push(m2[2]);
  }
  ok('  ' + mk + ' shows Model · Book · Adj · Edge · EV $100',
     got.join(' · ') === 'Model · Book · Adj · Edge · EV $100', got.join(' · '));
});

// And a line board carries its projection beside the line it is against.
S.market = 'rec'; S.fw.view = 'priced';
render();
const ouRow = html().slice(html().indexOf('class="row"'));
ok('the line and the projection are one pill',
   /class="odds num">[^<]*\u2192[^<]*</.test(ouRow),
   (ouRow.match(/class="odds num">[^<]*</) || ['none'])[0]);



// ── Load, from Combinations into the slip ───────────────────────────────
// Through the real handler, by dispatching a click at the button — not by
// calling `loadCombo` directly. Six controls were drawn correctly and were
// unreachable, and every test that called the function behind them passed.
S.route = 'combos'; S.market = 'any'; S.cb.pool = 'all'; S.cb.legs = 3;
x.clearSlip();
S.route = 'combos';
render();
ok('Combinations draws a Load button', html().indexOf('data-load="0"') >= 0);
const fired = clickData('load', '0');
ok('clicking it is reachable by the handler', fired, 'closest() found nothing');
ok('it fills the slip', S.slip.legs.length === 3, String(S.slip.legs.length));
ok('and shows it', S.route === 'slip', S.route);



// ── The ladder's headline reads as three words, not three sentences ─────
S.route = 'ladder';
render();
const keys = (html().match(/keystat__l">([^<]*)</g) || [])
  .map(k => k.slice(k.indexOf('>') + 1, -1));
ok('the ladder is headed Payout · Chance · At risk',
   keys.slice(0, 3).join(' · ') === 'Payout · Chance · At risk', keys.join(' · '));



// ── The stake moves everything it decides ───────────────────────────────
// EV and every Net in the breakdown are functions of the stake. The three
// totals were patched when it changed and the breakdown was not, so the slip
// disagreed with its own table until something else forced a render.
S.route = 'week';
x.clearSlip();
toggleLeg(rowsFor('any', 'all').filter(r => r.priced)[0]);
toggleLeg(rowsFor('any', 'all').filter(r => r.priced)[1]);
S.slip.stake = 10; S.slip.stakeRaw = '10';
S.route = 'slip';
render();
const nets = () => (document.getElementById('slipbrk').innerHTML
  .match(/num (?:pos|neg)">([^<]*)</g) || []).map(t => t.slice(t.indexOf('>') + 1, -1));
const evOf = () => (document.getElementById('sliptotals').innerHTML
  .match(/total__v num[^>]*>([^<]*)</g) || []).map(t => t.slice(t.indexOf('>') + 1, -1))[2];

// The box exists in the rendered markup; the stub keeps `innerHTML` as a
// string rather than parsing it, so it is only a readable node once
// `patchTotals` has written into it. A browser has no such gap.
ok('the breakdown is in a box that can be repatched',
   html().indexOf('id="slipbrk"') >= 0, 'nothing to patch');
x.patchTotals();
const netsAt10 = nets(), evAt10 = evOf();
ok('and that box holds the curve', netsAt10.length > 0, netsAt10.join(' '));

S.slip.stake = 40; S.slip.stakeRaw = '40';
x.patchTotals();
const netsAt40 = nets(), evAt40 = evOf();
ok('the EV follows the stake', evAt40 !== evAt10, evAt10 + ' -> ' + evAt40);
ok('and so does every Net in the breakdown',
   netsAt40.join() !== netsAt10.join(),
   netsAt10.join(' ') + '  ->  ' + netsAt40.join(' '));
// Four times the stake is four times the money, because net is linear in it.
ok('four times the stake, four times the net',
   Math.abs(parseFloat(netsAt40[0].replace(/[^0-9.]/g, ''))
            - 4 * parseFloat(netsAt10[0].replace(/[^0-9.]/g, ''))) < 0.02,
   netsAt10[0] + ' -> ' + netsAt40[0]);
ok('and the EV label says which stake it is on',
   document.getElementById('sliptotals').innerHTML.indexOf('EV on $40') >= 0);



// ── Coming back to where you were ───────────────────────────────────────
// A tab bar is a set of places you keep, not five links you follow once.
const scrollEl = () => document.getElementById('scroll');

location.hash = '#week';
scrollEl().scrollTop = 420;
location.hash = '#combos';
ok('leaving a tab is leaving it at a place', scrollEl().scrollTop === 0,
   'a new tab starts at the top');
location.hash = '#week';
ok('and coming back puts you there again', scrollEl().scrollTop === 420,
   String(scrollEl().scrollTop));

// Clear goes back to wherever the slip was opened from.
S.market = 'any'; S.cb.pool = 'all'; S.cb.legs = 3;
location.hash = '#combos';
scrollEl().scrollTop = 260;
clickData('load', '0');
ok('Load from Combinations lands on the slip', S.route === 'slip', S.route);
ok('with legs on it', S.slip.legs.length === 3);
clickData('act', 'clearslip');
ok('clearing it goes back to Combinations, not the board',
   S.route === 'combos', S.route);
ok('at the place it was left', scrollEl().scrollTop === 260,
   String(scrollEl().scrollTop));

// From the board, Clear still goes to the board.
location.hash = '#week';
toggleLeg(rowsFor('any', 'all').filter(r => r.priced)[0]);
location.hash = '#slip';
clickData('act', 'clearslip');
ok('and from the board it still goes to the board', S.route === 'week', S.route);

// Tapping the tab you are on is "take me to the top".
location.hash = '#week';
scrollEl().scrollTop = 500;
clickData('tab', 'week');
ok('tapping the current tab returns to the top', scrollEl().scrollTop === 0,
   String(scrollEl().scrollTop));

done();
