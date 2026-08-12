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

## Phase 1 — Make the measurement trustworthy

**Nothing in Phase 3 is worth starting until this is done.** This phase changes
no model; it changes what we can see.

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

Fix: denominator = every played game in the fold; a filtered-out scorer counts
as a miss.

> **This will move the headline numbers down by roughly 0.8–2 points.** That is
> a re-baseline, not a regression. It has to be done before the baseline lock's
> metrics are treated as a target, and it means updating the walk-forward
> comments in `settings.yaml`, the `production_model()` docstring, and
> `tests/test_leakage.py::test_each_market_serves_its_best_walkforward_model`.

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

- **Top-1**: McNemar on the games where champion and candidate disagree. Two
  variants agree on most games; testing only the discordant ones is several
  times more powerful than comparing two independent ±1.5% figures. This is the
  highest-leverage change in the whole plan.
- **Top-3 / Top-5 / AUC / Brier**: game-level paired bootstrap of the
  difference.
- `gate(candidate, champion) -> {verdict, per_metric_deltas, guards_tripped}`,
  implementing the rule in [Ground rules](#ground-rules).

### 1f. Ledger

`models/registry/ledger.jsonl`, append-only, one row per experiment: id,
timestamp, git SHA, tier, overlay diff, per-market/per-model metrics, paired
deltas vs champion, verdict, justification. Committed.

### Deliverables

```bash
make screen EXP=experiments/condlogit.yaml     # fast tier, ledger row, no promotion
make gate   EXP=experiments/condlogit.yaml     # full tier, ledger row, gate verdict
make noise-floor                               # 1d, refreshes the guard bands
```

Plus a re-locked `2026.08.12-baseline` manifest carrying the *corrected*
metrics, and a rewrite of the stale walk-forward comments in `settings.yaml` and
`production_model()`.

---

## Phase 2 — Diagnose where Top-1 is lost

Measurement only, no model change. Its job is to **order Phase 3** so we spend
effort where the loss actually is.

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

### 3a. Train the objective we are scoring *(largest expected effect)*

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
