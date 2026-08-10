# nfl-predictions

NFL touchdown prediction engine with calibrated probabilities, plus a Streamlit
app for exploring predictions, model performance, and parlays.

Two prediction targets are supported:

- **First TD scorer** — who scores the game's first touchdown
- **Anytime TD scorer** — who scores at any point in the game

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
ANTHROPIC_API_KEY=...   # optional — enables AI edge analysis in the app
ODDS_API_KEY=...        # optional — enables live sportsbook TD props
```

Both are optional. Without `ANTHROPIC_API_KEY` the AI analysis panel shows a
notice instead of commentary; without `ODDS_API_KEY` the app falls back to
cached odds.

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

## Running the app

```bash
source .venv/bin/activate
streamlit run app.py
```

Opens at <http://localhost:8501>. The sidebar selects the target type
(first TD / anytime TD) and the model. Three tabs:

- **Predictions** — ranked player probabilities, model-vs-Vegas edges, and
  optional AI-written analysis of the biggest disagreements
- **Model Performance** — calibration curves and evaluation metrics
- **Parlay Builder** — combine legs and see joint probabilities

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
- **Secrets** — pass `ANTHROPIC_API_KEY` and `ODDS_API_KEY` via the task
  definition's `secrets` block (Secrets Manager / SSM). Both are optional; the
  app degrades gracefully without them.
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
  (`max_adjustment`)
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
  prediction/       AI adjustments applied to model output
  analysis/         Claude-powered edge analysis
  evaluation/       metrics and plots
  utils/            config and path helpers
notebooks/          exploratory notebooks
```

Generated `data/`, `models/*.pkl`, and `output/` are gitignored.
