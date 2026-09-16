// The ladder pane's arithmetic, and the sentence it is obliged to carry.
//
// The maths is not the risk here — start × d^n is hard to get wrong. What is
// easy to get wrong is showing the winning branch on its own, so the chance of
// the whole run is checked as carefully as the payout, and so is the caveat
// that the chance is read off a price that includes the bookmaker's margin.
//
//   node tests/js/ladder.js <payload.json> <page.js>
const { loadPage, textOf, reporter } = require('./domstub.js');

const { ok, done } = reporter();
const x = loadPage(process.argv[2], process.argv[3],
  ['S', 'has', 'parsePrice', 'LADDER_MAX']);
const { S, parsePrice, LADDER_MAX } = x;
globalThis.render = () => {};

const near = (a, b, tol) => Math.abs(a - b) <= (tol == null ? 1e-6 : tol);
const paneText = () => textOf(paneLadder()).join(' ');

// ── The defaults, against hand arithmetic ────────────────────────────────
// -170 is 1 + 100/170 decimal. $100 rolled ten times is 100 × d^10.
const d = parsePrice('-170');
ok('American converts to the decimal the rollover uses',
   near(d, 1 + 100 / 170, 1e-9), String(d));

const expected = 100 * Math.pow(d, 10);
ok('ten rungs land where the arithmetic says', near(expected, 10213.0, 1.0),
   expected.toFixed(2));

const txt = paneText();
ok('the payout is on the pane', txt.includes('$10,2'), txt.slice(0, 200));

// ── The branch the table does not draw ───────────────────────────────────
const runAll = Math.pow(1 / d, 10);
ok('running the table is about one time in a hundred',
   near(runAll, 0.0098, 0.0005), runAll.toFixed(5));
ok('the chance of the whole run is shown beside the payout',
   /Chance of running it/.test(txt));
ok('the pane says the chance is read off the posted price',
   /margin/.test(txt) && /price/.test(txt));
ok('the pane says what it assumes', /assumes every leg wins/i.test(txt));
ok('the pane says it does not use the model',
   /Nothing here draws on the model/.test(txt));

// ── The inverse question ─────────────────────────────────────────────────
const need = Math.ceil(Math.log(10000 / 100) / Math.log(d));
ok('bets-to-target is the rounded-up log ratio', need === 10, String(need));
ok('bets-to-target is on the pane', /Bets to the target/.test(txt));

// ── A price that cannot clear the target ─────────────────────────────────
S.ladder.betsRaw = '3'; S.ladder.bets = 3;
const short = paneText();
ok('falling short is stated, with the shortfall',
   /Finishes/.test(short) && /short of/.test(short));
S.ladder.bets = 10; S.ladder.betsRaw = '10';

// ── Half-typed prices must not shout ─────────────────────────────────────
S.ladder.oddsRaw = '-1';
ok('a half-typed price is left alone', !/is not a price/.test(paneText()));
// `+50` stays silent on purpose: it is also the first three characters of
// `+500`, and a warning that fires mid-keystroke shoves the table down the
// page. Only a string no price begins with gets told.
S.ladder.oddsRaw = '+50';
ok('a price that could still be finished stays silent',
   !/is not a price/.test(paneText()));
S.ladder.oddsRaw = '1.2.3';
ok('a string no price starts with is told',
   /is not a price/.test(paneText()));
S.ladder.oddsRaw = '-170';

// ── An underdog compounds faster and lands less often ────────────────────
const plus = parsePrice('+150');
ok('a longer price pays more per rung', plus > d);
ok('and clears the target in fewer bets',
   Math.ceil(Math.log(100) / Math.log(plus)) < need);
ok('while running the table less often',
   Math.pow(1 / plus, 10) < runAll);

ok('the rung ceiling is declared rather than typed into the field',
   typeof LADDER_MAX === 'number' && LADDER_MAX > 0);

done();
