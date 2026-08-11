.PHONY: all ingest targets candidates features train predict clean \
	docker-build docker-up docker-down docker-logs docker-shell \
	docker-pipeline docker-prod docker-build-amd64 \
	backtest walkforward longshot economics evaluate wager wager-report

# Defaults so the evaluation targets run without arguments. Override per call:
#   make backtest SEASON=2024 TARGET=first_td
TARGET ?= anytime_td
SEASON ?= 2025

all: ingest targets candidates features train

ingest:
	python scripts/01_ingest.py

targets:
	python scripts/02_targets.py

candidates:
	python scripts/03_candidates.py

features:
	python scripts/04_features.py

train:
	python scripts/05_train.py

predict:
	python scripts/06_predict.py

# Snapshot sportsbook prices into the append-only archive. Run weekly in season —
# unarchived weeks can never be used to calibrate model vs market.
# Usage: make odds WEEK=1
odds:
	python scripts/07_odds.py --week $(WEEK)

# Closing-line value needs both ends of the market. Run `open-line` once when
# the week's board first goes up (usually Tuesday) and `odds` again near
# kickoff; scripts/13_clv.py then measures whether the market moved toward the
# players we rated above the opening price. That is the only evidence available
# within one season that an edge survives contact with money — bet outcomes are
# far too few and too skewed to settle it. Usage: make open-line WEEK=1
open-line:
	python scripts/07_odds.py --week $(WEEK) --snapshot open --force-refresh

clv:
	python scripts/13_clv.py

# Actionable bet card: model vs de-vigged market, ranked by EV, Kelly-staked.
# Needs cached prices — run `make odds WEEK=n` first. Usage: make bets WEEK=1
bets:
	python scripts/08_bets.py --week $(WEEK)

# ── Evaluation ────────────────────────────────────────────────────────────
# These read the odds archive and the backtest frames. Re-run them after any
# retrain: the app reads their output, so leaving them stale makes the board
# and the evidence behind it disagree about the same model.

# Replay a season through the production path. Needs an odds archive.
# Usage: make backtest SEASON=2025 TARGET=anytime_td
backtest:
	python scripts/10_backtest.py --season $(SEASON) --target $(TARGET)

# Retrain per test season and score each on data it never saw. The honest
# accuracy numbers on the Model performance tab come from here.
walkforward:
	python scripts/11_walkforward.py --target $(TARGET)

# Does our ranking beat the book inside the longshot band?
longshot:
	python scripts/12_longshot.py --target $(TARGET)

# Does being right pay? Rank/price profitability and the fitted edge rule that
# the board's "Worth backing" column reads.
economics:
	python scripts/14_rank_economics.py --target $(TARGET)

# Everything the app reads, rebuilt in dependency order, for both markets.
# Run this after `make train` or the app will quote a model that no longer exists.
evaluate:
	@for t in anytime_td first_td; do \
		for s in 2023 2024 2025; do \
			python scripts/10_backtest.py --season $$s --target $$t; \
		done; \
		python scripts/14_rank_economics.py --target $$t; \
		python scripts/11_walkforward.py --target $$t; \
	done
	python scripts/12_longshot.py --target anytime_td

# ── Betting ───────────────────────────────────────────────────────────────
# Log a bet you actually placed, at the price you actually got. The only
# measurement of what the backtest's assumptions cost in practice.
#   make wager ARGS="--season 2026 --week 1 --player 'Blake Corum' --odds 125 --stake 1"
wager:
	python scripts/15_wager.py add $(ARGS)

wager-report:
	python scripts/15_wager.py report

test:
	python -m pytest tests/ -q

# Deletes only what can be regenerated for free. data/archive/ is NEVER touched —
# it holds purchased historical odds that the API sells once and cannot be
# re-downloaded without paying again.
clean:
	rm -rf data/raw/*.parquet data/processed/*.parquet models/*.pkl output/*.json output/*.csv output/plots/*.png

# Timestamped copy of the irreplaceable odds archive. Run before anything risky.
backup-odds:
	@mkdir -p data/archive/backups
	@test -f data/archive/odds_history.parquet \
		&& cp data/archive/odds_history.parquet \
		   "data/archive/backups/odds_history_$$(date +%Y%m%d_%H%M%S).parquet" \
		&& echo "Backed up to data/archive/backups/" \
		|| echo "No archive yet — nothing to back up."

test-ingest:
	python scripts/01_ingest.py --test-mode

# ── Docker ──────────────────────────────────────────────────────────────────

IMAGE ?= nfl-td-predict
TAG ?= latest

docker-build:
	docker compose build

docker-up:
	docker compose up

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f app

docker-shell:
	docker compose run --rm app shell

# Override the stage: make docker-pipeline STAGE=predict
STAGE ?= all
docker-pipeline:
	docker compose --profile pipeline run --rm pipeline $(STAGE)

# Serve the baked image with no bind mounts — what Fargate will actually run.
docker-prod:
	docker compose --profile prod up --build prod

# Fargate runs linux/amd64 (unless the task is configured for ARM64).
docker-build-amd64:
	docker buildx build --platform linux/amd64 -t $(IMAGE):$(TAG) --load .
