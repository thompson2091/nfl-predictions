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
// `dirty` records the tree's state when the version was LOCKED, not now. The
// notice has to say that: a reader told the tree "has moved since" goes and
// cleans a tree that was never the problem.
ok('a clean lock says nothing about uncommitted changes',
   !/uncommitted changes/.test(txt));
w.dirty = true;
const dirtyTxt = paneText();
ok('a version locked from a dirty tree is called out',
   /locked from a tree with uncommitted changes/.test(dirtyTxt));
ok('and the notice says cleaning the tree now will not fix it',
   /Cleaning the tree/.test(dirtyTxt) && /Locking a new version/.test(dirtyTxt));
ok('the recorded commit is shown beside it', dirtyTxt.includes(w.git));
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


// ── What each family is worth ────────────────────────────────────────────
// Measured by retraining without it, not by an importance score. A family the
// model leans on can still be replaceable, and only retraining tells them
// apart — so the distinction has to survive onto the page, or the number gets
// read as importance by anyone who knows the word.
const withWorth = r.families.filter(f => typeof f.worth_top1 === 'number');
if (withWorth.length) {
  ok('what each family is worth is shown',
     withWorth.every(f => txt.includes(f.worth_top1.toFixed(2))));
  ok('the page says this is ablation and not importance',
     /not an importance score/i.test(txt) && /retrained without it/.test(txt));
  ok('the paired per-game comparison is shown',
     withWorth.every(f => txt.includes(String(f.wins))));

  // A family the model was better without is a real result, not a blank.
  const negative = withWorth.filter(f => f.worth_top1 < 0);
  if (negative.length) ok('a family worth nothing is shown as such, not hidden',
     negative.every(f => txt.includes(f.worth_top1.toFixed(2))));

  // Sorted by worth: the question this table gets opened with.
  const order = withWorth.slice().sort((a, b) => b.worth_top1 - a.worth_top1);
  const at = order.map(f => txt.indexOf(f.name));
  ok('families are ordered by what they are worth',
     at.every((v, i) => i === 0 || at[i - 1] < v), JSON.stringify(at));
}

// A stale ablation must not be shown at all — the numbers would be real and
// about a different model.
const keepAbl = r.ablation, keepFams = r.families;
r.ablation = { measured: '2026-01-01T00:00:00+00:00', model: 'xgb', fresh: false };
r.families = r.families.map(f => {
  const c = Object.assign({}, f); delete c.worth_top1; return c;
});
const staleTxt = paneText();
ok('an ablation measured on another feature set is refused, and says why',
   /describes a different model/.test(staleTxt) && /hash/.test(staleTxt));
r.ablation = keepAbl; r.families = keepFams;

done();
