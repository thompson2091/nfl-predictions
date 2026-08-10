.PHONY: all ingest targets candidates features train predict clean

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
