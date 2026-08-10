# nfl-predictions

NFL touchdown prediction engine with calibrated probabilities, plus a Streamlit
app for exploring predictions, model performance, and parlays.

Two prediction targets are supported:

- **First TD scorer** — who scores the game's first touchdown
- **Anytime TD scorer** — who scores at any point in the game

## Requirements

- Python 3.11+
- `libomp` (LightGBM's OpenMP runtime). On macOS: `brew install libomp`.
  Without it, `import lightgbm` fails with a `libomp.dylib` dlopen error.

## Setup

```bash
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e .
```

(`pip install -e .` works too if you'd rather not use `uv`.)

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
| `make clean` | — | Delete generated data, models, and output |

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
