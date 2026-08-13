# Model iteration plan

How we change the first-TD and anytime-TD models without fooling ourselves, and
how we keep every version we ever liked.

The goal is **Top-1 accuracy** on both markets. Profit is not the objective here;
it is a guard rail (see [Phase 5](#phase-5--serve-and-monitor)).

Two problems have to be solved together, in this order:

1. **We cannot currently measure a change worth making.** Walk-forward pools
   ~1,130 games, so the binomial standard error on Top-1 is ±1.5% (anytime) and
   ±1.1% (first TD). Nearly every idea below is worth 1–2 points. Today they all
   land inside the error bar.
2. **We cannot go back.** `models/` holds exactly one state. A retrain
   overwrites the thing that was working, and the evidence for why a choice was
   made lives in code comments that have already gone stale twice — the
   `production_model()` docstring still claims anytime TD serves `lgbm` at 54.6%
   Top-1, while `settings.yaml` records the re-derived truth (`xgb`, 50.9%).

So: lock first, measure second, model third.

---

## Ground rules

**Every change is an experiment with a written verdict.** A change is proposed
as a config overlay or a recipe flag, scored on identical folds against the
reigning champion, and recorded in the ledger with one of three verdicts:

| Verdict | Meaning |
| --- | --- |
| `PROMOTED` | Cleared the gate. Becomes the new default version. |
| `REJECTED` | Did not clear the gate. Stays in the ledger so nobody retries it blind. |
| `KEPT_WITH_JUSTIFICATION` | Tripped a guard metric but promoted anyway. **Requires a written reason in the manifest.** |

That third row is the answer to "if it starts to degrade, call it out and decide
whether it is still justified". The tool never silently accepts a trade-off; it
makes you type the reason, and the reason ships inside the version manifest.

**The promotion gate** (chosen 2026-08-12):

- Paired Top-1 improvement ≥ 1 standard error of the *paired* difference, **and**
- no guard metric (Top-3, Top-5, AUC, Brier) worse by more than its own noise
  band, where the noise band is the measured seed-to-seed spread from Phase 1d.

Guard trips are reported with the numbers, not auto-rejected.

**Gate scope**: both markets (`first_td`, `anytime_td`) × all four models
(`lr`, `lgbm`, `xgb`, `ensemble`). The walk-forward already fits all four per
fold, so scoring them is nearly free — and it keeps the app's per-model numbers
honest and the production choice re-derivable.

**Two tiers of evaluation**:

| Tier | What it does | Cost | Use |
| --- | --- | --- | --- |
| **Screen** | Cached folds, production model only, no retrain of surrounding artifacts | minutes | Kill bad ideas cheaply |
| **Gate** | Full 4-fold retrain of every artifact, all models, both markets | slow | Anything that will be promoted |

A screen result never promotes anything. It only decides what is worth gating.

---

## Phase 0 — Lock the baseline — **DONE (2026-08-12)**

**Goal**: today's models become a version we can always return to, before a
single line of modelling code changes.

Shipped as `src/models/versioning.py`, `scripts/22_version.py`,
`tests/test_versioning.py` and the Makefile targets below. The baseline is
locked and served as **`2026.08.12-baseline`**.

### Layout

```
models/
  anytime_td/                       <- unchanged. What the app and pipeline read.
  first_td/
  versions/                         <- gitignored (new .gitignore line)
    2026.08.12-baseline/
      anytime_td/*.pkl, *.json
      first_td/*.pkl, *.json
    2026.08.19-condlogit/
  registry/                         <- COMMITTED
    2026.08.12-baseline.json
    2026.08.19-condlogit.json
    CURRENT.json
    ledger.jsonl
```

`.gitignore` currently reads `models/*.pkl`, which does not cover nested paths —
add `models/versions/`. The registry is JSON only and stays in git, so the full
history of what was tried, what won, and why is queryable forever even though
the weights are not.

### Manifest (`models/registry/<id>.json`)

```json
{
  "id": "2026.08.12-baseline",
  "created": "2026-08-12",
  "git_sha": "e1c04f8",
  "parent": null,
  "verdict": "PROMOTED",
  "justification": null,
  "change": "Baseline lock. No modelling change.",
  "config": { "...full settings.yaml snapshot..." },
  "feature_cols": { "anytime_td": 319, "first_td": 319, "sha256": "..." },
  "metrics": {
    "anytime_td": { "xgb": {"top1": 0.509, "top3": 0.861, "auc": 0.8409, "brier": 0.09135}, "...": {} },
    "first_td":   { "ensemble": {"top1": 0.162, "auc": 0.8221, "brier": 0.02744}, "...": {} }
  },
  "artifacts": { "anytime_td": {"xgb.pkl": "<sha256>", "...": "..."} },
  "runtime":   { "anytime_td": {"blend_weight.json": {"sha256": "...", "value": {"market_weight": 0.428}}} }
}
```

`artifacts` and `runtime` are separate because one artifact in `models/` is not
fitted at training time. `blend_weight.json` is refit during *prediction* from
graded odds history that grows every week the season is live, so it moves
without a retrain. Enforcing it byte-for-byte would fail verification after
every `make predict` and train an operator to ignore the check — worse than
having none. It is recorded with its value inlined (so the manifest says what
weight the version served) and its drift is reported, not failed.

> Building this surfaced a bug in that refit. The guard compared the stored
> `n_rows` — archive rows surviving the join with model predictions — against
> the eligible rows going in. The join always loses some (6,985 of 7,624), so
> the condition was permanently true and **every** `make predict` replayed the
> entire archive and rewrote the artifact, landing on a weight that differed in
> the eleventh decimal. Fixed in `predict.blend_weight_needs_fit`, with a
> regression test.

The config snapshot and git SHA are what make a version *reproducible in
principle*; the artifact hashes are what make it *verifiable in practice*
(nflverse revises historical data, so retraining from the same SHA is not
guaranteed to be bit-identical — which is exactly why we keep the weights).

### CLI — `scripts/22_version.py`

```bash
make lock ID=2026.08.12-baseline NOTE="baseline lock"   # snapshot models/ -> versions/ + manifest
make versions                                           # list, newest first, with Top-1 per market
make version-show ID=...                                # manifest, metrics, justification
make promote ID=...                                     # copy version -> models/, update CURRENT.json
make rollback                                           # promote the previous CURRENT
make version-diff A=... B=...                           # config diff + paired metric table
```

`promote` and `rollback` are the *same operation* — copy a version's artifacts
over `models/` and repoint `CURRENT.json`. One code path, so rollback cannot rot
from disuse.

Two further safeguards, both learned from this project's own history:

- **`promote` clears the live market directory before copying.** A merge leaves
  the previous version's files behind, and a stale calibrator or
  `rank_calibration.json` keeps being loaded — quietly changing what is served.
- **`promote` refuses when the live artifacts match no locked version.** An
  un-snapshotted retrain is the only copy of itself; promotion would destroy it.
  `--force` overrides when the live state is scrap.

### Delivered

- `src/models/versioning.py` — snapshot, restore, hash, manifest, verify
- `scripts/22_version.py` + Makefile targets + the `models/versions/` gitignore
- `models/registry/2026.08.12-baseline.json` and `CURRENT.json`, **to commit**
- `tests/test_versioning.py` — 16 tests. The round-trips run against a temporary
  `models/` tree, because a rollback path that is never exercised does not work
  when you need it. The last test runs against the real repository: `models/`
  must hold exactly what `CURRENT.json` claims, so a retrain that lands without
  a lock fails `make test` instead of quietly making the committed record a lie.

---

## Phase 1 — Make the measurement trustworthy — **DONE (2026-08-12)**

**Nothing in Phase 3 is worth starting until this is done.** This phase changes
no model; it changes what we can see.

Shipped as `src/evaluation/ranking.py` (the denominator and per-game rows),
`src/evaluation/harness.py` (folds, overlays, execution),
`src/evaluation/compare.py` (paired tests and the gate),
`src/utils/config.py::config_overlay`, `scripts/23_experiment.py`, and
`tests/test_evaluation_harness.py`. `scripts/11_walkforward.py` is now a report
over the shared harness rather than its own private copy of it.

### 1a. Fix the metric denominator

`_fold_metrics` in `scripts/11_walkforward.py` builds `best` only from games
where a scorer survived `_filter_low_activity`, then divides by `len(best)`.
Games where the real scorer was filtered out disappear from the denominator:
1,115 of 1,139 games for first TD, 1,130 for anytime.

Two consequences: the headline number is flattered, and — the reason this
blocks everything — any experiment that widens or narrows the candidate pool is
scored on a *different* denominator, so pool changes are not comparable.
Loosening the filter adds hard games and can lower measured Top-1 while strictly
improving the product.

Fix: denominator = every played game whose scorer exists in the candidate pool
at all; a filtered-out scorer counts as a miss. The eight games per four-season
window with no scorer anywhere in the pool are excluded and reported — the label
is not in the data and no ranking can win them.

> **Measured, the re-baseline is smaller than expected**: first TD 1,115 → 1,131
> games, about −0.2 points of Top-1 (ensemble 16.2% → 16.0%, xgb 17.0% → 16.8%);
> anytime TD 1,130 → 1,131 games, about −0.05. The correction matters for
> comparability, not for the headline. `production_model()`'s stale docstring
> was removed at the same time, and the walk-forward comments in
> `settings.yaml` were re-derived.

### 1b. Per-game outcome records

Every evaluation writes, per fold and per model, one row per game:
`{game_id, model, hit_at_1, rank_of_best_scorer, prob_top1, prob_top2}`. Pooled
percentages are derived from these. This single change is what makes paired
statistics, the coin-flip diagnostic, and the error decomposition all possible
from the same artifact.

### 1c. `src/evaluation/harness.py`

One place that owns:

- **Fold construction and caching.** `scripts/19_tune.py` already does this
  internally (`_folds`); lift it out so the tuner, the walk-forward and every
  new experiment share identical folds. Cache keyed on
  (target, feature-matrix hash, fold definition).
- **Config overlays.** A dict deep-merged over `settings.yaml`, passed down —
  never written to disk. Note `get_config()` caches a process-global `_config`
  and `run_all.py` mutates that singleton in place; overlays must not inherit
  that pattern or experiments will leak state into each other.
- **Recipe execution**: given (overlay, tier), produce per-game records for both
  markets and all four models.

### 1d. The seed noise floor

Retrain the identical baseline config at 5 seeds and publish the spread of Top-1
and every guard metric. Two payoffs: any claimed gain below that spread is known
to be noise, and the spread *becomes* the "materially worse" band in the
promotion gate. We do not currently know this number, which means we do not
currently know what a real improvement looks like.

### 1e. `src/evaluation/compare.py` + the gate

- **Top-1 / Top-3 / Top-5**: the paired per-game difference of the hit
  indicators, with its own standard error, plus McNemar's exact test on the
  discordant games. Two variants agree on most games; the information about
  which is better lives entirely in the ones where they disagree. This is the
  highest-leverage change in the whole plan.
- **AUC / Brier**: pooled, compared against the measured seed noise (1d) rather
  than bootstrapped. A difference smaller than what the random seed produces on
  its own is not a difference, and that band is the honest test.
- `gate(comparison) -> {verdict, top_k, row, guards_tripped}`, implementing the
  rule in [Ground rules](#ground-rules). `GUARD_TRIPPED` is the verdict that
  forces the conversation: Top-1 improved, something else regressed, and
  promoting it means writing down why.

### 1f. Ledger

`models/registry/ledger.jsonl`, append-only, one row per experiment: id,
timestamp, git SHA, tier, overlay diff, per-market/per-model metrics, paired
deltas vs champion, verdict, justification. Committed.

### Delivered

```bash
make noise-floor SEEDS=5                       # 1d; also records the champion run
make screen EXP=experiments/example-depth4.yaml  # fast tier, ledger row, never promotes
make gate   EXP=experiments/example-depth4.yaml  # full tier, ledger row, verdict
make experiments                               # the ledger
make walkforward TARGET=first_td               # the report, over the same harness
```

A fold costs about **13 seconds** per model on this data, so a full gate — two
markets, four folds, three models plus the ensemble — is a few minutes, and the
whole five-seed noise floor is around half an hour. There is no budget reason to
skip the gate before promoting.

Two things worth knowing about the diagnostics that came free with the per-game
rows, before Phase 2 even starts:

- **Coin flips.** Games where the top two probabilities sit within a point:
  **16.0%** of anytime-TD games, **29.5%** of first-TD games. Nearly a third of
  the first-TD market is a coin flip by the model's own reckoning, which caps
  how much Top-1 is available to win there.
- **Unranked games.** 16 first-TD games and 1 anytime game per four-season
  window have their scorer removed by the candidate filter. Now counted as
  misses and reported rather than dropped.

---

## Phase 2 — Diagnose where Top-1 is lost — **DONE (2026-08-12)**

Measurement only, no model change. Its job is to **order Phase 3** so we spend
effort where the loss actually is.

Shipped as `src/evaluation/diagnose.py`, `scripts/24_diagnose.py`,
`tests/test_diagnose.py`, and dated snapshots in `diagnostics/`. Run with
`make diagnose TARGET=...`.

### What it found

Four folds, 2022–2025, production model per market.

**The two markets are not the same problem.** Against the book, over the games
it priced 8+ players in and one of them scored:

| | book Top-1 | model Top-1 | |
| --- | --- | --- | --- |
| anytime_td (844 games) | 52.3% | **55.9%** | +3.7pp, 2.3 se — we lead |
| first_td (795 games) | 18.9% | 18.5% | −0.4pp, 0.3 se — level |

So there is no gap to the market to close on anytime TD; we are already ahead of
it. On first TD we are level with the price at the top and slightly ahead at
Top-5 (+1.5pp).

**First TD's real gap is quarterbacks, and it is narrow.**

This paragraph first read "the ranking has collapsed onto running backs",
citing 92% RB top picks and a 2.2% Top-1 in receiver-won games. That was wrong,
and it was wrong because the slice had no benchmark beside it. The book puts a
back top in **88.8%** of the same games, and scores **3.8%** on receiver-won
games. Concentration on backs is the structure of the market, not a defect —
and "Top-1 when a receiver won" is close to a tautology, since picking a back
means you cannot hit a receiver game.

Three cuts are needed to tell those apart, and `by_position_vs_market` now
prints all three with the book beside each:

| | pick share (ours / book) | mass vs actual | within-position AUC (ours / book) |
| --- | --- | --- | --- |
| RB | 92.8% / 88.4% | 53.0% / 49.2% | **0.8264** / 0.8126 |
| WR | 6.6% / 7.7% | 39.7% / 37.3% | **0.7614** / 0.7480 |
| QB | **0.6% / 3.9%** | 7.3% / 7.3% | 0.7229 / **0.7395** |

**Pick share should exceed win share.** One lead back outranks four receivers
splitting the same mass, so a Top-1 optimiser concentrates by design; spreading
picks to match the outcome distribution is probability matching, which is
strictly worse for accuracy. Over-valuation shows up in *mass against actual*,
and there it does not: every position lands within a point or two, RB at ratio
1.02. We also out-discriminate the book *within* RB and WR.

Quarterbacks are the exception, and the shape of the failure is specific. Our
QB mass is exactly right in aggregate (7.3% against 7.3%), yet we put a QB top
in 0.6% of games against the book's 3.9%. In the 62 QB-won games both we and
the book give the actual scorer a median rank of 8 — but the book has him
**top-3 in 35.5% of them against our 16.1%**. Correct on average, flat at the
top: we never elevate the specific goal-line rushing quarterbacks the book
identifies. Closing to the book's rate on those games is worth about +0.8pp of
Top-1.

This is the same defect `stage2.py` documents from the betting side — "under-
predicts quarterbacks by 9.2 points" — reached independently.

**Anytime TD's misses are the share, not the rate.** 78.0% of its 564 misses are
the right team and the wrong player. The market-driven Poisson half is doing its
job; the usage half is where the error lives.

**Anytime TD over-rates DEF/ST at the very top.** When its top pick is a
defence, it hits 16.3% over 123 games — against 58.0% when the pick is a back.
Those 123 games are 11% of the slate. Bringing them merely to the WR pick rate
(44.2%) would be worth about 3 points of Top-1 on its own, which is larger than
anything else on the Phase 3 list.

**Confidence does not discriminate.** In coin-flip games (top two within a
point) anytime TD hits 48.1% against 51.4% in decided games — a 3-point spread
across a distinction that ought to separate a near-certainty from a toss-up. On
first TD it is 12.9% against 17.3%. The probability *gap* is not carrying the
information its size implies.

**The pool is not the constraint.** 99.9% ceiling on anytime, 98.6% on first TD.
Widening the candidate pool cannot be where the wins are.

### What that changes about Phase 3

Re-ordered by measured effect rather than by expected effect:

1. **Position-conditional shape at the top of the board.** The largest measured
   defect on both markets, and it was not on the original list. Anytime TD's
   DEF/ST top picks hit 16.3% against 58.0% for backs, worth ~3 points; first
   TD never elevates a quarterback (0.6% of picks against the book's 3.9%),
   worth ~0.8. Both are the same shape: a position whose aggregate mass is
   right but whose top end is flat. That is a calibration problem (3c), not a
   feature or objective one, and it is the cheapest thing here to try.
2. **3a, multinomial shares within team-game — anytime TD.** 78% of its misses
   are right-team-wrong-player, which is exactly what this fixes.
3. **3a, conditional logit — first TD.** Still worth testing: a softmax over the
   game's candidates is the true likelihood for a one-winner market, and it
   models cross-position competition directly rather than leaving it to a
   pointwise fit. Demoted from first place because the evidence that motivated
   putting it there turned out to be a misread — the ranking has not collapsed,
   it is level with the market.
4. **3d, market features — first TD only.** We already beat the book on anytime
   TD, so there is little of its information left to import there. On first TD
   we are level, so it is worth more.
5. **3e/3f, feature ablation and pool thresholds — demoted.** The pool ceiling is
   99%+ and the losses are structural, not informational.

---

## Phase 3 — The experiments so far

| experiment | verdict | Top-1 on the production model |
| --- | --- | --- |
| First TD from a blend with the anytime model | REJECTED | −0.35pp (xgb −1.41, p=0.026) |
| First TD from competing-Poisson team rates | REJECTED | −0.62pp (all four models worse) |
| **DEF/ST out of the offensive share denominator** | **KEPT_WITH_JUSTIFICATION** | **+2.56pp, p=0.000** |
| Conditional logit — train the objective we score (3a) | REJECTED | first TD −0.09pp (p=1.000); anytime −2.74pp (p=0.016) |

The pattern is worth naming. Both rejected experiments were *theoretically*
motivated — sound arguments about likelihoods and generative structure — and
both cost accuracy. The one that worked came from a measurement nobody was
looking for: predicted-against-actual by position and board rank, which showed
defences published at 0.908 against an actual 0.153.

**Look for defects, not improvements.** A defect has a mechanism you can point
at and a size you can measure before you write any code. An improvement has an
argument.

### Where the remaining headroom is not

After the DEF/ST fix, four candidate leads were sized before building anything.
Three of them dissolved on measurement. Recording them so they are not
rediscovered:

**Anytime TD beats the book on every decomposition.** Splitting the top pick
into its two halves, over 849 priced games:

| | right team | right player *given* right team | overall |
| --- | --- | --- | --- |
| us | **97.9%** | **56.8%** | **55.6%** |
| book | 95.4% | 54.4% | 51.9% |

This also retires the Phase 2 reading that "78% of misses are
right-team-wrong-player, so the share half is where the error lives". At 97.9%
right-team, almost every remaining miss *must* be within-team by arithmetic.
That figure describes a model picking the right team nearly always — it is not a
diagnosis, and it was another slice read without a benchmark beside it.

**Ranking defences needs features that do not exist.** Only 44 of 319 features
are non-null and varying on DEF/ST rows, and 77 are constant. A model trained on
DEF/ST rows alone reaches AUC 0.5045 — worse than the global model's 0.54 and
indistinguishable from chance. Everything available describes the offence
(targets allowed, coach tendencies); nothing describes takeaway ability, return
units, or the opponent's turnover-proneness. This is a feature-building project
against play-by-play, and it buys Top-5, not Top-1: a defence at its true 11%
should rarely be anyone's top pick.

**First TD's quarterback gap is not a compression defect.** The hypothesis was
that QB probabilities were correct on average but too flat to ever reach the
top. Measured, within-game share spread:

| | ours p95/p50 | book p95/p50 | ours max | book max |
| --- | --- | --- | --- | --- |
| RB | **6.47** | 4.89 | 0.398 | 0.244 |
| QB | **3.90** | 3.28 | 0.217 | 0.162 |

We give quarterbacks *more* spread than the book, and rank each game's best QB
about as highly (median rank 9 against 10; top-5 in 26.2% against 28.3%). The
book puts a QB top more often because **we concentrate harder on top backs**,
not because we bury quarterbacks. Our back discrimination is the better of the
two (AUC 0.8264 against 0.8126) and we win more RB-scored games, so matching the
book's mix would be probability matching — the same error as the RB misread.

**What that leaves.** Both markets are close to what this feature set supports:
anytime TD is ahead of the book on Top-1, Top-3, Top-5, both halves of the
decomposition, and within-position AUC everywhere except QB; first TD is level
with it. The next real gains need new *information*, not new fitting — turnover
and return-unit features for defences, and whatever else the play-by-play holds
that 319 columns do not yet capture.

### Two ways the harness flattered a candidate

Both were found by being the first thing to add a *new model* rather than a new
config value, and both are the dangerous kind: they do not fail, they improve.

**The champion went stale.** The gate pairs a candidate against the champion's
saved per-game rows. The DEF/ST fix was promoted on 2026-08-12 and the champion
was not re-run, so it still described the pre-fix model. The first
conditional-logit screen duly reported **+2.56pp on Top-1 for an overlay whose
model was never trained** — the entire delta was the DEF/ST fix being counted a
second time. `champion_drift` now compares the champion's recorded version
against what `CURRENT.json` serves and says so before any verdict is printed.
The tell, once the champion was re-baselined, is that the unchanged `xgb` row
reads `+0.00pp, 0 of 1131 games differ` — which is what an overlay that does not
touch a model should always produce, and is worth checking on every gate.

**The screen omitted its own subject.** `screen_models` returned only the model
the market serves, so an overlay adding `condlogit` trained everything except
`condlogit`, then printed a full result table under the experiment's name. It
now also trains whatever the overlay adds to `models.active`. Relatedly,
`compare_all` intersected model names, so a model the champion lacks produced no
comparison at all — and a gate that prints nothing reads exactly like a gate
that found nothing wrong. New models are now paired against what the market
serves, and the table names both sides when they differ.

The ledger row from the invalid run is retained and marked `VOID`, with a
retraction row naming what was wrong. Deleting it would leave the record
looking like the mistake never happened, which is the failure this ledger exists
to prevent.

A third defect fell out of the same run. `_break_ties` nudged calibrated
probabilities *upward* to restore ordering isotonic had flattened, and the
anytime-TD xgb calibrator tops out at 0.999999 — so the nudge could produce
p > 1. Nothing rejected it; the values flowed into `1 - exp(-lambda*s)` and into
Brier until sklearn refused a 1.00006. The nudge now subtracts, which is bounded
by construction. Measured cost on the served model: 3 of 1131 games change,
2 won and 1 lost.

### A note on reading these slices

The RB misread is worth keeping as a warning. A slice of our own numbers with no
benchmark beside it produced a confident, specific, wrong conclusion that
survived into a committed plan — and the fix was not more analysis but printing
the book's column next to ours. Any new cut added here should carry its
benchmark in the same table, not in a follow-up.

`scripts/24_diagnose.py --target ...` produces a report and a dated JSON
snapshot (committed), so the diagnosis itself is trackable over time.

1. **Market benchmark.** The odds archive covers 847/849 games across 2023–25.
   Rank by de-vigged price, compute the book's Top-1 on the same games. This is
   the headroom number. If the book gets 52% on anytime and we get ~51%, this is
   a grinding problem; if we are already ahead, the accuracy ceiling is close
   and the honest report says so.
2. **Team-vs-player decomposition.** On misses: right team / wrong player, or
   wrong team? Anytime TD is factored exactly that way (`team_lambda` × `share`),
   so this splits the error into "the market-driven Poisson rate is wrong" and
   "the usage model is wrong" — two completely different fixes.
3. **Rank-of-actual-scorer distribution** and the **top1–top2 probability gap**.
   The share of games that are genuine coin flips is the practical ceiling.
4. **Slices**: Top-1 by scorer position, favourite/underdog, game total, week.
   `stage2.py` already documents a 9.2-point QB miss; this is where structural
   misses surface.
5. **Candidate-pool ceiling**, now measurable honestly against the fixed
   denominator: 97.9% of first-TD games and 99.2% of anytime games retain a
   scorer after `_filter_low_activity`. That 2.1% is a hard cap on first-TD
   Top-1 until the filter changes.

---

## Phase 3 — The model levers

Each item is one experiment through the harness: screen first, gate if it
survives, ledger row either way. **Order within this phase is set by Phase 2**;
the sequence below is the prior.

### 3a. Train the objective we are scoring — **RUN 2026-08-13, REJECTED**

`src/models/ranker.py` implements the conditional logit as `condlogit`: an
XGBoost fitted on the within-group multinomial likelihood, softmax over a
game's candidates for first TD and over a team-game for anytime. Same features,
same tree hyperparameters as `xgb`, same folds. Only the loss differs.

Screened on both markets against `2026.08.13-champion-defst`:

| | Top-1 | Top-3 | Top-5 | AUC | coin flips |
| --- | --- | --- | --- | --- | --- |
| first TD — xgb | 16.8% | 37.1% | 53.2% | 0.8225 | 37.0% |
| first TD — condlogit | 16.7% | **38.2%** | **54.0%** | 0.8222 | 43.5% |
| anytime — xgb | **53.4%** | **85.8%** | 93.3% | 0.8320 | 16.5% |
| anytime — condlogit | 50.7% | 84.2% | 93.4% | 0.8285 | — |

Paired: first TD −0.09pp on Top-1, 34 games won against 35 lost, p=1.000 —
level, not merely insignificant. Anytime −2.74pp, 63 won against 94 lost,
p=0.016, with Top-3, AUC and Brier guards all tripped.

**This was the strongest remaining argument that the model is fitting-limited,
and it does not survive contact.** The plan called it "the single biggest
structural gap in the repo", and the reasoning was sound: Top-1 is a within-game
argmax, exactly one player wins, and the multinomial likelihood is the
likelihood of that event rather than an approximation of it. Trained on it, the
model ranks first TD no better and anytime distinctly worse.

Two things the numbers say about *why*, both worth keeping:

- **On first TD it trades Top-1 for Top-3/Top-5.** Top-3 +1.06pp and Top-5
  +0.80pp, with the coin-flip rate rising from 37.0% to 43.5%. A softmax is
  indifferent between two candidates it cannot separate, so it stops
  manufacturing a gap the data does not support. It orders the shortlist better
  and commits to the top of it less. That is the correct behaviour for the loss
  and the wrong behaviour for the metric.
- **On anytime the grouping throws away what the joint model needs.** Grouping
  by team-game learns only *relative* standing within a team, but `combine`
  multiplies a team-level Poisson rate by that share — and the cross-team
  information the pointwise loss retains is doing real work. The multiple-winner
  case is also a weaker fit: several players score, so the "exactly one wins"
  structure that makes this exact for first TD is only an approximation here.

The one live thread: adding `condlogit` to the ensemble moved the ensemble from
51.8% to 54.0% on anytime and 16.0% to 16.6% on first TD, so it does carry
information the others do not. Neither beats the served `xgb` (53.5% / 16.8%) by
anything like a standard error, so this is a lead and not a result.

**What this settles.** The Phase 2 conclusion — data-limited, not
fitting-limited — was reached by measuring the feature set, and a fair objection
was that it had never been tested against a change of *objective*. It has been
now, on the objective with the best theoretical claim, and the conclusion holds.
The remaining items in this phase are calibration shape (3c), family ablation
(3e) and pool thresholds (3f), none of which had the prior 3a had.

The screening infrastructure this run exercised had two defects of its own, both
of which flattered the candidate and neither of which failed loudly — see
"Two ways the harness flattered a candidate" below.

### 3a as originally planned *(kept for the reasoning)*

Everything is trained pointwise on binary log loss. Top-1 is a within-game
argmax. Three ways to close that gap:

- **Conditional logit / softmax over the game's candidates for first TD.** This
  is not an approximation — exactly one player wins per game, which *is* the
  multinomial likelihood. A 17% Top-1 model trained on the wrong likelihood is
  the single biggest structural gap in the repo.
- **Learning-to-rank** (`rank:pairwise` / `lambdarank`) with `qid = game_id`,
  or `game_id × team` for anytime, since team-game is the group the joint model
  actually consumes.
- **Fit shares directly** for anytime: multinomial within team-game against TD
  counts, rather than normalising binary probabilities after the fact.

Servability is already solved: `apply_joint`'s docstring notes the share basis
need only be *proportional within a team*, so a pure ranker drops into the
anytime path with no calibration story at all.

### 3b. First-TD joint path A/B *(cheapest — code already exists)*

`predict.py` normalises raw first-TD probabilities within game;
`joint.first_td_probability` implements the competing-Poisson derivation and is
**never called**. The walk-forward also skips the joint path for `first_td`
entirely. One flag, one gate run.

### 3c. Calibration shape — the "temperature" lever

Isotonic is a monotone *step* function. Within one game a monotone map cannot
reorder — so calibration looks Top-1-neutral, and it is not, for two reasons:

- **Ties.** Players landing on the same step come out identical; this needed the
  `_break_ties` hack in `scoring.py`, and the top score was tied in 10–25% of
  games.
- **Shape.** In the anytime path calibrated probabilities are renormalised into
  shares, so the *shape* of the transform — not just its ordering — decides
  which team's players rise. It is rank-changing across teams.

Experiments: temperature scaling, Platt, beta calibration, monotone spline (all
strictly increasing, so ties vanish); and the fit population (priced-only vs all
candidates), currently a hard-coded policy in `_serving_population`.

### 3d. Let the model see the market

`sbook_*` columns are excluded from training because they were null
historically. Three seasons of graded archive now exist. A ranker trained on the
priced population *with* price features is the natural extension of what
`stage2.py` already does for bet selection, moved to the ranking problem — and
strictly stronger than the post-hoc probability-level blend, because a tree can
interact price with usage.

### 3e. Feature-family ablation

319 columns across ~40 builder modules on ~100k rows. Ablate **by family**, not
by column: ~40 screens, cheap on cached folds. Prune families that do not earn
their keep — fewer features is variance reduction even at equal Top-1. This is
also the standing answer to "does this new feature actually enhance the model":
a new family enters via the same ablation harness that judges the existing ones.

### 3f. Candidate pool and filter thresholds

Only testable now that the denominator is fixed (1a). Trades pool ceiling
against pool noise: 33 candidates per game survive the filter, from 51.8.

### 3g. Weather forecasts *(optional, has an external dependency)*

`temp` and `wind` are discarded as train/serve skew — correctly, since they are
measured at kickoff. A pre-kickoff **forecast** feed restores them honestly.
Real signal for goal-line-heavy game scripts. Needs a data source decision
first; parked until 3a–3e are exhausted.

---

## Phase 4 — The config sweep surface

With overlays (1c) in place, sweeping is mechanical. Generalise
`scripts/19_tune.py` from "xgb hyperparameters" to "any overlay", and standardise
multi-seed averaging for anything landing inside the noise floor.

Sweepable: model hyperparameters (existing), `rolling_windows`, calibration
method and fit population, ensemble shrinkage, `blend.bootstrap_market_weight`
and the fitted weight, the joint conversion's level/dispersion grid,
rank-calibration on/off, `_filter_low_activity` thresholds, and per-market model
choice.

Every sweep writes ledger rows. A sweep that finds nothing is a result worth
keeping — `19_tune.py`'s existing finding ("this model is not
hyperparameter-limited") is exactly the kind of conclusion that should live in
the ledger rather than in a docstring.

---

## Phase 5 — Serve and monitor

- **App shows the served version.** Version id, its walk-forward numbers, and
  the git SHA, so what you are looking at traces to a locked version.
- **Rank economics as a non-gating report.** Accuracy is the goal, but an
  accuracy win that wrecks the bet card should be visible. Run
  `scripts/14_rank_economics.py` on every promotion and attach the result to the
  manifest. It never blocks a promotion; it just refuses to let the trade-off be
  invisible.
- **Weekly monitoring**: rolling Top-1 by week against the walk-forward
  expectation, plus feature-drift against the `train_null_rates.pkl` already
  saved at train time. `weekly_review.py` covers calibration today; it does not
  yet track ranking against expectation.
- **CI**: `make test` continues to run the leakage suite, plus the new
  CURRENT.json-vs-`models/` hash check.

---

## Day-to-day loop, once Phases 0–1 land

```bash
make screen EXP=experiments/rank-pairwise.yaml   # minutes. Worth pursuing?
make gate   EXP=experiments/rank-pairwise.yaml   # full retrain, paired verdict
make lock   ID=2026.08.19-rank-pairwise NOTE="lambdarank, qid=game_id"
make promote ID=2026.08.19-rank-pairwise         # becomes the default
make rollback                                    # if it disappoints in the wild
```

Champion never changes without a ledger row. Every ledger row carries a paired
delta and a verdict. Every promotion is one command from being undone.
