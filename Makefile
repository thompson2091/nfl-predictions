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

clean:
	rm -rf data/raw/*.parquet data/processed/*.parquet models/*.pkl output/*.json output/*.csv output/plots/*.png

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
