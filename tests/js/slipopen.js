// The slip opens when it is asked for, and not before.
//
// Adding a leg used to open it. On a phone that is the sheet covering the
// board you are picking FROM; on a desktop it is 360px taken from the board,
// so the table reflows under the hand that is picking from it — columns move
// and the row you were aiming at shifts. Neither is what "add another one"
// should do, so neither happens.
//
//   node tests/js/slipopen.js <payload.json> <page.js>
const { loadPage, textOf, reporter } = require('./domstub.js');

const { ok, done } = reporter();
const x = loadPage(process.argv[2], process.argv[3],
  ['S', 'toggleLeg', 'rowsFor', 'slipHandle', 'slipSlot', 'clearSlip']);
const { S, toggleLeg, rowsFor, slipHandle, slipSlot, clearSlip } = x;

// A width is a claim about layout, so it is made the way the stylesheet makes
// it — the same query the breakpoint uses.
const at = px => { globalThis.matchMedia = q => ({ matches: px <= 1100, media: q }); };
const reset = () => { clearSlip(); S.conflict = null; S.slipOpen = false; };

S.route = 'week';
const rows = rowsFor(S.market, 'all').filter(r => r.priced);
if (rows.length < 2) { ok('the fixture has two priced rows to add', false); done(); }

[['a phone', 390], ['a desktop', 1440]].forEach(([what, px]) => {
  at(px);
  reset();
  toggleLeg(rows[0]);
  ok(what + ' does not open the slip on the first add', S.slipOpen === false);
  ok(what + ': the leg went in all the same', S.slip.legs.length === 1);
  toggleLeg(rows[1]);
  ok(what + ': nor on the second', S.slipOpen === false);
  ok(what + ': both legs are on it', S.slip.legs.length === 2);
  ok(what + ': the handle in the corner is what opens it', !!slipHandle());
  ok(what + ': and the panel is not rendered until then', slipSlot() === null);
  // Which the handle does, because that is the only way back in.
  S.slipOpen = true;
  ok(what + ': asked for, it opens', !!slipSlot());
  ok(what + ': and the handle stands down', slipHandle() === null);
});

// ── The one thing that still opens it by itself ─────────────────────────
// A slip holds one market. Adding a leg from another asks a question, and a
// question nobody can see is a tap that did nothing.
at(1440);
reset();
const other = rowsFor('rec', 'all').filter(r => r.priced)[0];
if (!other) { ok('the fixture carries a second market', false); done(); }
toggleLeg(rows[0]);
toggleLeg(other, 'over');
ok('a market conflict is raised', !!S.conflict);
ok('and shows itself even though the slip is closed',
   S.slipOpen === false && slipSlot() !== null,
   'a prompt that has to be answered cannot be behind a closed panel');
ok('naming the market it would replace',
   textOf(slipSlot()).join(' ').indexOf('Receptions') >= 0);

// ── No layout to ask about ──────────────────────────────────────────────
delete globalThis.matchMedia;
reset();
toggleLeg(rows[0]);
ok('with no matchMedia nothing opens either', S.slipOpen === false);

done();
