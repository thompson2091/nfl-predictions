# nfl-predictions

NFL touchdown prediction engine with calibrated probabilities, plus a Streamlit
app for exploring predictions, model performance, and parlays.

**New here? Read [`docs/OVERVIEW.md`](docs/OVERVIEW.md)** — what the models
actually are, what they do and do not beat, and where everything lives.

Six markets are served. The two touchdown markets are the original pair and
share a ranker:

- **First TD scorer** — who scores the game's first touchdown
- **Anytime TD scorer** — who scores at any point in the game
- **Receptions** — a count model, priced at any line a book posts
- **Rushing / receiving / passing yards** — a fitted quantile curve each

## Requirements

- Docker (the quickest path — see [Docker](#docker)), **or**
- Python 3.11+ and `libomp` (LightGBM's OpenMP runtime). On macOS:
  `brew install libomp`. Without it, `import lightgbm` fails with a
  `libomp.dylib` dlopen error.

## Setup

```bash
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"
```

(`pip install -e ".[dev]"` works too if you'd rather not use `uv`.) The `dev`
extra adds Jupyter for the notebooks; plain `-e .` installs only what the
pipeline and app need.

### Environment variables

Create a `.env` in the project root:

```
ODDS_API_KEY=...        # optional — lets the pipeline snapshot sportsbook prices
ANTHROPIC_API_KEY=...   # optional — phrases game notes, and powers the Ask box
```

`ODDS_API_KEY` is read by the **pipeline**, not the app: `make odds` snapshots
live prices into the archive at `data/archive/`, and the app reads that archive.
Without the key the pipeline cannot capture new prices, but the app still runs
against whatever is already archived.

`ANTHROPIC_API_KEY` is read in two places, neither of them the Streamlit app:

- **`src/analysis/game_notes.py`** phrases the notes on a game page. It never
  invents a number: a note is selected from the payload first, and the model
  is asked only to word it. Two guards check the wording before it ships —
  every figure must match one in the payload numerically, and the direction
  must agree with the pick. Without the key the notes fall back to their
  written phrasing.
- **`deploy/ask.php`** answers typed questions on the published board. The key
  lives on the **server**, at `/etc/picksix/anthropic.key`, never in the page.
  Without it the endpoint reports that the service is not configured and the
  board works in full, minus the box.

The older `src/prediction/ai_adjustments.py` still reads the key and is still
called by nothing. See [`docs/DEPLOY.md`](docs/DEPLOY.md) for the proxy, its
rate limits and how the key is installed.

## Running the pipeline

The app reads artifacts produced by the pipeline, so **run this before starting
the app** — otherwise you'll see `No features.parquet found for <target>`.

```bash
make all      # ingest -> targets -> candidates -> features -> train
make predict  # generate predictions for the upcoming week
```

Individual stages:

| Command | Script | What it does |
| --- | --- | --- |
| `make ingest` | `scripts/01_ingest.py` | Pull raw play-by-play and roster data via `nfl_data_py` |
| `make targets` | `scripts/02_targets.py` | Derive first-TD / anytime-TD labels |
| `make candidates` | `scripts/03_candidates.py` | Build the per-game candidate player pool |
| `make features` | `scripts/04_features.py` | Assemble the feature matrix |
| `make train` | `scripts/05_train.py` | Train and calibrate models |
| `make predict` | `scripts/06_predict.py` | Score the upcoming week |
| `make odds WEEK=n` | `scripts/07_odds.py` | Snapshot sportsbook props into the archive |
| `make bets WEEK=n` | `scripts/08_bets.py` | Actionable bet card: EV vs de-vigged market, Kelly stakes |
| `make test` | `tests/` | Leakage + train/serve skew regression tests |
| `make clean` | — | Delete generated data, models, and output |

### Getting bets

```bash
make odds WEEK=1   # pull and archive current prices
make bets WEEK=1   # rank plays by EV, size them by fractional Kelly
```

A play only appears if a book prices it. **Edge is measured against the de-vigged
price; EV is computed at the raw price you're actually paid.** Anytime-TD books
run ~1.23x overround, so comparing a model number to the raw price invents
roughly 5 points of edge on every line. Stake sizing is fractional Kelly — set
your bankroll and risk fraction under `betting:` in `config/settings.yaml`.

`make test` runs regression tests for the three leakage/skew bugs that shipped
undetected. Run it after touching anything in `src/features/`.

> **Run `make odds WEEK=n` every week the season is live**, even weeks you don't
> bet. The Odds API only serves *current* markets, so an unarchived week is gone
> for good — and `data/raw/odds_history.parquet` is what the model-vs-market
> blend weight is fit from. Until it has enough graded rows the blend falls back
> to the bootstrap value in `config/settings.yaml` and says so in its output.

**Read [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) before trusting a number
the app shows you.** It documents every feed, its refresh cadence, and two
failure modes that produce plausible-looking but wrong probabilities silently.

`make test-ingest` runs ingestion for only the most recent season
(`seasons.end`) — useful for a fast smoke test.

To build artifacts for **both** target types in one pass:

```bash
make ingest                 # required first — run_all.py does NOT ingest
python scripts/run_all.py   # targets -> candidates -> features -> train, x2
```

> **`run_all.py` starts at label extraction, not ingestion.** On a fresh
> checkout `data/raw/` is empty (it's gitignored), and running `run_all.py`
> without ingesting first will fail. `make all` covers a single target type
> end to end including ingest; `run_all.py` covers both target types but
> assumes raw data is already on disk.

## Changing the model

Pooled Top-1 carries ±1.5% of standard error over the walk-forward's 1,131
games, and almost every change worth making is worth one to two points. So a
change is not judged by comparing two percentages — it is scored on the same
folds and compared to the champion **per game**, where only the games the two
disagree about carry any information.

```bash
make noise-floor SEEDS=5                      # once: what is the random seed alone worth?
make screen EXP=experiments/my-idea.yaml      # fast: production model, one market
make gate   EXP=experiments/my-idea.yaml      # both markets, every model, verdict
make experiments                              # the ledger: what has been tried
```

An experiment is a config overlay in a YAML file — see
[`experiments/`](experiments/). Overlays are merged over `config/settings.yaml`
for the length of a run and never written to it, so nothing an experiment does
reaches the app. A fold costs about 13 seconds per model, so a full gate is a
few minutes.

Every run appends to `models/registry/ledger.jsonl`, committed, whether it won
or lost. `PROMOTED` means: adopt the overlay into `config/settings.yaml`,
`make train`, then lock and promote the result.

## Model versions

`models/` holds exactly one state and every `make train` overwrites it. Lock a
state you like and it survives:

```bash
make lock ID=2026.08.12-baseline NOTE="baseline lock"   # snapshot models/
make versions                                           # what exists, what is served
make version-show ID=2026.08.12-baseline                # metrics, config, git SHA
make promote ID=2026.08.12-baseline                     # make it the default
make rollback                                           # back to the previous one
make version-verify                                     # does models/ match the record?
```

Weights live in `models/versions/<id>/` and are gitignored (~3.3 MB a version).
The manifest in `models/registry/<id>.json` **is** committed: it carries the git
SHA, the full config snapshot, the feature-set hash and the walk-forward metrics
for every model on both markets. `CURRENT.json` names what is being served.

`make test` asserts that `models/` holds exactly what `CURRENT.json` claims, so
a retrain that lands without a lock fails rather than silently making the
committed record wrong. Promotion is per-market with `MARKET=first_td`.

Read [`docs/MODEL_ITERATION.md`](docs/MODEL_ITERATION.md) before changing the
model: it is the phased plan for measuring whether a change is real, and the
promotion gate a new version has to clear.

## Running the app

```bash
source .venv/bin/activate
streamlit run app.py
```

Opens at <http://localhost:8501>. The sidebar selects the target type
(first TD / anytime TD) and the model. Six tabs:

- **Shortlist** — the picks this project would actually place
- **Full board** — every priced player, model against the de-vigged market
- **Weekly results** — graded weeks, and what the board said beforehand
- **Model performance** — calibration curves and evaluation metrics
- **Betting reality** — what the record is after the vig, stated plainly
- **Player types** — archetype clusters and the bet shapes they suit

The old Predictions tab and its AI commentary panel are gone; the parlay
views collapsed into Full board, which is the same table filtered.

## The published board

The Streamlit app is for exploring. What actually gets read before a slate is a
static single-page board, built from the same payload and published to a web
host.

```bash
python scripts/52_export_v3.py   # build into site/v3/
python scripts/58_deploy.py      # build, upload, promote — one SSH connection
python scripts/58_deploy.py --dry-run
```

The board carries the week's props on every market, a page per game (notes,
players, outcome, matchup edges, injuries), a bet slip, a ladder calculator,
and a week picker that reaches back over graded weeks with winners and losers
colour-coded. Outcome holds the final-score table and the ladder of lines
together, because `score_dist` answers both from one set of comparable games.

Each game page also has an **Ask box**: a typed question answered against a
brief this repo publishes for that game, with web search available for things
the brief cannot know, such as late injury news. It is served by a small PHP
proxy, `deploy/ask.php`, which holds the API key server-side and caps spend at
15 questions per IP per hour and 300 a day.

Read [`docs/DEPLOY.md`](docs/DEPLOY.md) before deploying: it covers the upload
order, the cache headers that stop a deploy landing invisibly, how the key is
installed, and what the host cannot do.

## Docker

One image serves everything: it bakes the code **and** the artifacts the app
reads (`models/`, `output/`, `data/processed/`, `data/raw/schedules.parquet`),
so a container needs no S3 bucket or EFS mount. Build once, run the same image
locally and on ECS Fargate.

### Local dev

```bash
cp .env.example .env    # optional keys; Compose picks .env up automatically
make docker-build
make docker-up          # http://localhost:8501
```

`docker compose up` bind-mounts `app.py`, `src/`, `scripts/`, `config/`,
`data/`, `models/`, and `output/` over the baked copies, with Streamlit's
watcher in polling mode — edit a file on the host and the app reloads. Host
artifacts shadow the image's, so a local retrain shows up immediately.

| Command | What it does |
| --- | --- |
| `make docker-build` | Build the image |
| `make docker-up` / `make docker-down` | Start / stop the app |
| `make docker-logs` | Tail app logs |
| `make docker-shell` | Bash shell in the container |
| `make docker-pipeline` | Run the full pipeline (`STAGE=predict` to pick one stage) |
| `make docker-prod` | Serve on :8502 with no mounts — exactly what Fargate runs |
| `make docker-build-amd64` | Build `linux/amd64` for Fargate |

The entrypoint takes a verb: `app` (default), `ingest`, `targets`,
`candidates`, `features`, `train`, `predict`, `all` (single target type, ingest
through train), `pipeline` (`run_all.py`, both target types), `shell`, or any
command to exec directly.

```bash
docker compose --profile pipeline run --rm pipeline predict
docker run --rm -p 8501:8501 --env-file .env nfl-td-predict
```

### Deploying to ECS Fargate

```bash
make docker-build-amd64 IMAGE=<acct>.dkr.ecr.<region>.amazonaws.com/nfl-td-predict TAG=v1
docker push <acct>.dkr.ecr.<region>.amazonaws.com/nfl-td-predict:v1
```

Task settings that matter:

- **Platform** — build `linux/amd64` unless the task definition specifies
  `ARM64` (Apple Silicon builds default to arm64 and will fail to start on an
  x86 task).
- **Port** — container port `8501`. The entrypoint honours `PORT` if you'd
  rather set one.
- **Health check** — `/_stcore/health` for the ALB target group; the image also
  carries a Docker `HEALTHCHECK` on the same endpoint.
- **Size** — 1 vCPU / 4 GB is comfortable; the app loads a ~59 MB feature
  parquet per target type into memory. The image is ~2 GB, well under the 20 GB
  default ephemeral storage.
- **Secrets** — the serving task needs none. `ODDS_API_KEY` belongs on the
  pipeline task that runs `make odds`; pass it via the task definition's
  `secrets` block (Secrets Manager / SSM). `ANTHROPIC_API_KEY` belongs on the
  same pipeline task if you want written game notes; the Ask box reads its own
  copy on the web host and never from here.
- **Authentication** — there is none in the app. Anyone who can reach the port
  gets the full board and the betting pages. Put it behind an authenticating
  proxy (ALB OIDC, Cognito, an identity-aware proxy) before exposing it.
- **Filesystem** — leave `readonlyRootFilesystem` off, or mount writable
  volumes at `/app/data`, `/app/models`, `/app/output`, and `/app/config`:
  `get_path()` calls `mkdir(parents=True, exist_ok=True)`, and `run_all.py`
  rewrites `config/settings.yaml` in place.
- **Websockets** — Streamlit holds a websocket per session, so raise the ALB
  idle timeout (300s) and enable target-group stickiness if you run more than
  one task.
- **Refreshing predictions** — artifacts are baked in, so new predictions mean
  a rebuild and redeploy. Run the pipeline (locally or as an ECS run-task with
  the same image), rebuild, push a new tag, update the service.

## Configuration

`config/settings.yaml` drives the pipeline. Key sections:

- `target.type` — default target (`first_td` or `anytime_td`)
- `seasons` — training range (2015–2025) and `predict_season`
- `splits` — train / validation / test season boundaries
- `models.active` — which models to train (`lr`, `lgbm`, `xgb`);
  `models.production` picks the default shown in the app
- `model.*` — per-model hyperparameters and the random seed
- `ai_context` — toggles AI adjustments and caps their magnitude
  (`max_adjustment`). Inert: nothing currently calls the AI adjustment code.
- `paths` — where raw data, processed data, models, and output are written

## Layout

```
app.py              Streamlit app
Dockerfile          multi-stage build (deps -> slim runtime)
docker-compose.yml  local dev (app), pipeline, and prod-parity services
docker/             entrypoint + container health check
config/             settings.yaml
scripts/            numbered pipeline stages + run_all.py
src/
  ingest/           nfl_data_py and odds API loaders
  targets/          TD label extraction and candidate pools
  features/         feature builders (matchup, usage, pace, red zone, ...)
  models/           trainers, registry, calibration
  prediction/       board pricing, availability, portfolio sizing
  presentation/     pure board-display rules (tiers, labels, money formatting)
  clustering/       player archetypes and bet shapes
  analysis/         game notes: selected from the payload, phrased by a model
  export/           the published boards (site/v2, site/v3) and the Ask briefs
  evaluation/       metrics, plots, backtests, CLV
  utils/            config and path helpers
deploy/             ask.php and the .htaccess the deploy ships
site/               published boards; v3 is what squarespro.com serves
notebooks/          exploratory notebooks
```

Generated `data/`, `models/*.pkl`, and `output/` are gitignored.
