// Adding a leg, at a width where the slip is a sheet and at one where it is not.
//
// On a desktop the slip is a panel beside the board: it is already on screen,
// and filling it in as you go is the whole point. On a phone it is a sheet
// that covers the board you are picking FROM, so opening it on every add
// means dismissing it before the next pick — which is the difference between
// choosing six players and choosing one six times.
//
//   node tests/js/sheetslip.js <payload.json> <page.js>
const { loadPage, reporter } = require('./domstub.js');

const { ok, done } = reporter();
const x = loadPage(process.argv[2], process.argv[3],
  ['S', 'toggleLeg', 'rowsFor', 'slipHandle', 'slipSlot', 'clearSlip']);
const { S, toggleLeg, rowsFor, slipHandle, slipSlot, clearSlip } = x;

// A width is a claim about layout, so it is made the way the stylesheet makes
// it — one query, the same one the breakpoint uses.
const at = px => { globalThis.matchMedia = q => ({ matches: px <= 1100, media: q }); };

const rows = rowsFor(S.market, 'all').filter(r => r.priced);
if (rows.length < 2) { ok('the fixture has two priced rows to add', false); done(); }

// ── A phone ─────────────────────────────────────────────────────────────
at(390);
S.route = 'week';
clearSlip();
S.slipOpen = false;
toggleLeg(rows[0]);
ok('a phone does not open the sheet on the first add', S.slipOpen === false,
   'the sheet covers the board it was picked from');
ok('the leg went in all the same', S.slip.legs.length === 1);
toggleLeg(rows[1]);
ok('nor on the second', S.slipOpen === false);
ok('both legs are on the slip', S.slip.legs.length === 2);

// And the way back in is on screen, because nothing else opened.
ok('the handle in the corner is what opens it', !!slipHandle());
ok('and the sheet itself is not rendered until then', slipSlot() === null);

// ── A desktop ───────────────────────────────────────────────────────────
at(1440);
clearSlip();
S.slipOpen = false;
toggleLeg(rows[0]);
ok('a panel beside the board still fills in as you go', S.slipOpen === true);
ok('so there is nothing in the corner to tap', slipHandle() === null);

// ── No layout to ask about ──────────────────────────────────────────────
// A stub DOM, a test, an old browser: the answer is the desktop one, because
// every caller written before this existed expects it.
delete globalThis.matchMedia;
clearSlip();
S.slipOpen = false;
toggleLeg(rows[0]);
ok('with no matchMedia the behaviour is unchanged', S.slipOpen === true);

done();
