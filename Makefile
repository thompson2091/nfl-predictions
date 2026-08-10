.PHONY: all ingest targets candidates features train predict clean \
	docker-build docker-up docker-down docker-logs docker-shell \
	docker-pipeline docker-prod docker-build-amd64

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

# Actionable bet card: model vs de-vigged market, ranked by EV, Kelly-staked.
# Needs cached prices — run `make odds WEEK=n` first. Usage: make bets WEEK=1
bets:
	python scripts/08_bets.py --week $(WEEK)

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
