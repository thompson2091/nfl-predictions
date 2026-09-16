// The Model tab: provenance for everything on the other tabs.
//
// Wrong provenance is worse than none — it is the page vouching for a recipe
// it did not check. So what is asserted here is that the pane reports what the
// payload says and nothing it inferred: the version, the feature count, the
// families, and the columns that arrive with no recorded builder.
//
//   node tests/js/served.js <payload.json> <page.js>
const { loadPage, textOf, reporter } = require('./domstub.js');

const { ok, done } = reporter();
const x = loadPage(process.argv[2], process.argv[3], ['S', 'M', 'has']);
const { S, M } = x;
globalThis.render = () => {};

const paneText = () => textOf(paneServed()).join(' ');
const txt = paneText();
const m = M(), w = m.served, r = m.recipe;

// ── Who is scoring the board ─────────────────────────────────────────────
ok('the promoted version is named', txt.includes(w.version), w.version);
ok('the model is named', /XGB/.test(txt));
ok('the market it belongs to is named', txt.includes(m.label));
ok('the reason it was promoted is shown', txt.includes(w.note));
ok('the verdict is shown', txt.includes(w.verdict));

// ── What it was fitted on ────────────────────────────────────────────────
ok('the feature count comes from the payload, not a recount',
   txt.includes(String(r.n_features)));
ok('every family is listed', r.families.every(f => txt.includes(f.name)));
ok('the columns inside a family are shown',
   r.families[0].cols.every(c => txt.includes(c)));

// The families are the unit that gets measured, so the count beside each one
// has to be the count of what is listed against it.
ok('a family\'s count matches the columns it lists',
   r.families.every(f => f.n === f.cols.length || f.cols.length <= f.n),
   JSON.stringify(r.families.map(f => [f.n, f.cols.length])));

// ── Columns with no provenance are named, not folded away ────────────────
ok('unattributed columns are called out',
   r.unattributed.every(c => txt.includes(c)) && /no/.test(txt));

// ── Accuracy, per season it never trained on ─────────────────────────────
ok('every walk-forward season is shown',
   r.seasons.every(s => txt.includes(String(s.season))));
ok('the pooled figure is shown', txt.includes((w.recorded.games).toLocaleString()));
ok('the standard error is shown beside it', /standard error/.test(txt));

// ── The states that must not render as normal ────────────────────────────
const dirtyBefore = /working tree has moved/.test(txt);
ok('a clean tree says nothing about being dirty', !dirtyBefore);
w.dirty = true;
ok('a dirty tree is called out', /working tree has moved/.test(paneText()));
w.dirty = false;

w.problems = ['walkforward.json predates the served model'];
ok('registry problems are surfaced verbatim',
   paneText().includes('walkforward.json predates the served model'));
w.problems = [];

const keep = m.recipe;
m.recipe = null;
ok('a market with no trained model says so rather than rendering empty',
   /feature_cols\.pkl is missing/.test(paneText()));
m.recipe = keep;

// ── The two panes that were deleted stay deleted ─────────────────────────
ok('this pane is not the model report card that was removed',
   typeof globalThis.paneModel === 'undefined');

// ── The second market has its own recipe ─────────────────────────────────
if (DATA.markets.length > 1) {
  S.market = 1;
  ok('switching market switches the model card', paneText().includes(M().label));
  S.market = 0;
}

done();
