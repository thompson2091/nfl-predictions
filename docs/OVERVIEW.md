# Overview

What this repo is, what the models actually are, and where everything lives.
Start here; [MODEL_ITERATION.md](MODEL_ITERATION.md) is how you change a model
without fooling yourself, and [DATA_SOURCES.md](DATA_SOURCES.md) is where every
number comes from and what is known to be wrong with it.

A weekly NFL player-prop pipeline. It ingests nflverse data and sportsbook
odds, trains a model per market, and publishes a board you read before a slate.
Every constant is fitted and stamped with provenance, every promotion is gated
per market and per model, and every claim is measured against the market rather
than against the model's own opinion.

## The six markets

| Market | What the model predicts | Beats its market? |
|---|---|---|
| Anytime TD | Team rate x player share -> P(scores) | Not raw; shows CLV |
| First TD | Same ranker, normalised within game | Not raw; shows CLV |
| Receptions | A count, then any line off its distribution | No raw; **yes blended** |
| Rushing / receiving / passing yards | A fitted quantile curve | No, either way |

**The touchdown markets do not ask "does this player score".** That question
needs a level bolted on afterwards and treats teammates as independent when
they compete for the same goal-line carries. Instead the problem is factored
the way the game works:

    team touchdowns   N ~ Poisson(lambda)    lambda fitted on the betting lines
    whose they are    s_i                    fitted on usage and matchup
    at least one      P = 1 - (1 - mu/r)^r   mu = lambda * s_i, r fitted

Expected touchdowns sum to `lambda` by construction, so the constraint is
structural rather than a patch, and the first-TD market falls out of the same
two pieces as competing Poisson processes. The conversion carries **two
levels** — one for players a book priced and one for players no book would
quote, who score at 0.41% against a priced player's 16.1%.

**The count and yardage markets predict the count, not the line.** Applying the
line afterwards means one model prices every line a book posts, including ones
it has never seen, and cannot put P(>2.5) below P(>3.5) without noticing.

**The honest headline:** no model here beats its market on raw output. What
they have is information the price does not fully contain, so the served number
is shrunk toward the de-vigged market, and the measurable claim is
closing-line value — the market moves ~60% of the time toward the players we
rate above the opening price, against a 54% shuffle null. That is evidence the
disagreement anticipates the market. It is **not** evidence a book would take
the bet at a price that pays.

## Served state

| | Version | Features | Model |
|---|---|---|---|
| `anytime_td` | 2026.09.21-unpriced-conversion | 236 | xgb |
| `first_td` | 2026.08.19-clean-matrix | 318 | xgb |

Train 2015-2023, validate 2024, test 2025, predict 2026. The candidate matrix
carries 388 columns across 39 builder families; each market serves a named
allow-list of families, not everything on disk. `lr`, `lgbm` and `xgb` are all
trained and an ensemble is available; both markets currently serve `xgb`.

## Directory structure

```
src/
  ingest/       nflverse + The Odds API -> data/raw, data/archive
  targets/      candidate pool and touchdown extraction
  features/     one builder per family; ablated by family, never by column
  models/       joint model, count model, calibration, versioning + registry
  prediction/   THE SERVED PATH: predict, blend, bets, receptions, yards
  evaluation/   backtest, walk-forward, CLV, parity, cover, shortlists
  export/       board builders: site.html and the site/v2 PWA
  clustering/   player-type clusters
scripts/        numbered pipeline stages, 01_ingest -> 51_export_app
tests/          671 tests, mostly leakage and served-vs-evaluated parity
config/         settings.yaml: splits, seasons, family allow-lists
experiments/    config overlays, screened and gated before anything promotes
models/         weights, fitted artifacts, versions/, registry/
data/           raw/, processed/, archive/ (the odds history)
output/         per-market backtests, metrics, published predictions
site/           published boards; v2 is the installable one
```

## How a week runs

`scripts/week_rollover.sh` (launchd) waits for nflverse to publish the weekly
roster — before it lands, the upcoming week has 32 candidate rows and no people
— then runs ingest, targets, candidates, features, predict, shortlist and the
board. Odds capture runs on 15 launchd slots derived from the season's actual
kickoffs, and a closing capture rebuilds the board so the published page is
never older than the prices on it.

## Before you trust a number

This project's failures have not been crashes. They have been **plausible,
well-formatted, wrong probabilities**: a join fan-out that leaked a label into
its own feature, sparse frames leaking through row *existence* rather than
value, in-play prices archived as closes and then preferred by every dedupe,
an encoder silently choosing its own reference level, and more than one check
that quietly stopped checking and reported the skip as a pass.

That history is why the guard rails look disproportionate:

- **Fit constants, never set them.** Every level, weight, dispersion and
  threshold is fitted and saved with `seasons_used`, `n_rows` and `fit_date`.
  A fit that returns zero is a real answer and is kept.
- **One definition per number.** Training and serving build their matrices
  through one function; the board and the backtest read one payload builder.
  Copies drift, silently.
- **Gate per market and per model.** A screen over-reports on purpose; the
  gate runs eight market/model cells and one surviving cell is a rejection.
- **Assert the row count after any join that precedes a `shift()`.**

`docs/DATA_SOURCES.md` keeps the ranked list of what is still wrong.
