#!/usr/bin/env bash
# Single image, several jobs. `app` serves Streamlit (the default); the pipeline
# verbs run the numbered scripts so ECS can reuse the same image for run-task.
set -euo pipefail

run_stage() {
    echo "── $1 ──"
    shift
    python "$@"
}

cmd="${1:-app}"
[ $# -gt 0 ] && shift

case "$cmd" in
    app)
        exec streamlit run app.py \
            --server.port="${PORT:-${STREAMLIT_SERVER_PORT:-8501}}" \
            "$@"
        ;;
    ingest)     exec python scripts/01_ingest.py "$@" ;;
    targets)    exec python scripts/02_targets.py "$@" ;;
    candidates) exec python scripts/03_candidates.py "$@" ;;
    features)   exec python scripts/04_features.py "$@" ;;
    train)      exec python scripts/05_train.py "$@" ;;
    predict)    exec python scripts/06_predict.py "$@" ;;
    all)
        # Mirrors `make all` for the target type in config/settings.yaml.
        run_stage "ingest"     scripts/01_ingest.py
        run_stage "targets"    scripts/02_targets.py
        run_stage "candidates" scripts/03_candidates.py
        run_stage "features"   scripts/04_features.py
        run_stage "train"      scripts/05_train.py
        ;;
    pipeline)
        # Both target types. run_all.py assumes raw data is already on disk.
        exec python scripts/run_all.py "$@"
        ;;
    shell)
        exec bash "$@"
        ;;
    *)
        exec "$cmd" "$@"
        ;;
esac
