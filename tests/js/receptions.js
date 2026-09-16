// The Receptions tab: the one pane that must not read like a bet card.
//
// It is the only tab built on a market this project is measurably worse at
// than the book. Every previous time the count model appeared to beat
// receptions it was a leak, so the page's job here is to put the verdict in
// front of the board rather than behind it — and the failure mode is not a
// crash, it is a column of positive numbers with the context quietly missing.
//
// So what is pinned is the framing as much as the arithmetic: that the losing
// verdict is stated, that the disagreement column is not called an edge, that
// a thin consensus is marked rather than dropped, and that the tab reads its
// own payload instead of `M()` — which holds touchdown players and would
// render nonsense without erroring.
//
//   node tests/js/receptions.js <payload.json> <page.js>
const { loadPage, textOf, reporter } = require('./domstub.js');

const { ok, done } = reporter();
const x = loadPage(process.argv[2], process.argv[3], ['S', 'M', 'has']);
const { S, M } = x;
globalThis.render = () => {};

const paneText = () => textOf(paneReceptions()).join(' ');
const R = DATA.receptions;
const txt = paneText();

// ── It reads its own payload, not the market ────────────────────────────
ok('every posted line is on the page',
   R.rows.every(r => txt.includes(r.player_name)),
   R.rows.map(r => r.player_name).join(', '));
ok('it does not render the touchdown board instead',
   !txt.includes(M().players[0].player),
   'a TD player leaked into the receptions tab');

// ── The verdict leads, and it is the losing one ─────────────────────────
ok('the market is named as the better calibrated side',
   /The market/.test(txt) && txt.includes(R.forward.pooled.market_log_loss.toFixed(4)));
ok('our own log loss is shown beside it, not hidden',
   txt.includes(R.forward.pooled.model_log_loss.toFixed(4)));
ok('the number of settled lines behind the verdict is stated',
   txt.includes(R.forward.pooled.n.toLocaleString()));
ok('it says in as many words that this is not a bet card',
   /bet card/i.test(txt));

// ── The column is a disagreement, not an edge ───────────────────────────
ok('the column is called a disagreement', txt.includes('Disagreement'));
ok('no column on this tab is labelled an edge',
   !/\bEdge\b/.test(txt), txt.match(/\bEdge\b.{0,40}/));

// ── A thin line is marked, not dropped ──────────────────────────────────
const thin = R.rows.filter(r => r.thin);
ok('the fixture has a thin line to reason about', thin.length > 0);
ok('a thin line is still shown by default',
   thin.every(r => txt.includes(r.player_name)),
   'a one-book price is the only price there is; dropping it hides the market');
S.r.thick = true;
const hidden = paneText();
ok('and can be hidden on request',
   thin.every(r => !hidden.includes(r.player_name)));
S.r.thick = false;

// ── The search narrows the board ────────────────────────────────────────
S.r.q = R.rows[0].player_name.split(' ')[0];
const narrowed = paneText();
ok('searching a name keeps that player', narrowed.includes(R.rows[0].player_name));
const other = R.rows.find(r => !r.player_name.startsWith(S.r.q));
ok('and drops the others', other ? !narrowed.includes(other.player_name) : true);
S.r.q = '';

// ── The weekly record is per week, because pooling hides a bad week ─────
ok('every graded week is listed',
   R.forward.weeks.every(w => paneText().includes(String(w.week))));
ok('the in-play exclusion is explained where the record is',
   /in-play/i.test(txt));

// ── The leak warning fires when the model looks good ────────────────────
// The dangerous state is the one that looks like success, so it is the one
// worth rendering in a test rather than trusting by reading.
DATA.receptions = JSON.parse(JSON.stringify(R));
DATA.receptions.forward.beats_market = true;
const won = paneText();
ok('a model ahead of the market is flagged as probably a bug',
   /leak|bug/i.test(won) && /investigate/i.test(won));
ok('and the NGS leak is named as the precedent', /NGS/.test(won));
DATA.receptions = R;

// ── No model on disk is a state, not a blank pane ───────────────────────
DATA.receptions = { model: false, rows: [], forward: null };
ok('a missing model says which command builds it',
   /make receptions/.test(paneText()));
DATA.receptions = R;

done();
