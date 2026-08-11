# syntax=docker/dockerfile:1.7
#
# Build once, deploy anywhere: the image carries code *and* the pipeline
# artifacts the app reads (models/, output/, data/processed/, schedules), so a
# container is self-contained on ECS Fargate with no S3/EFS dependency.
#
#   docker build -t nfl-td-predict .
#   docker run --rm -p 8501:8501 --env-file .env nfl-td-predict

# ── Stage 1: dependencies ───────────────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Only the metadata + package skeleton, so the (slow) dependency resolve is
# cached and does not re-run every time app.py changes.
COPY pyproject.toml README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && pip install .

# xgboost's Linux wheel hard-depends on nvidia-nccl-cu12 (~400 MB) for
# multi-GPU training. Fargate is CPU-only and nccl is imported lazily, so
# dropping it shrinks the image by a third with no effect on CPU predict/train.
RUN pip uninstall -y nvidia-nccl-cu12 \
    && find /opt/venv -name '__pycache__' -type d -prune -exec rm -rf {} + \
    && find /opt/venv -name '*.pyc' -delete

# ── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# libgomp1 is LightGBM/XGBoost's OpenMP runtime — the Linux equivalent of the
# `brew install libomp` step in the README. Without it `import lightgbm` fails.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    MPLCONFIGDIR=/tmp/matplotlib

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# Artifacts first (large, change on retrain), code last (changes constantly).
COPY --chown=appuser:appuser models ./models
COPY --chown=appuser:appuser output ./output
COPY --chown=appuser:appuser data ./data
COPY --chown=appuser:appuser config ./config
COPY --chown=appuser:appuser docker ./docker
COPY --chown=appuser:appuser scripts ./scripts
COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser app.py pyproject.toml README.md ./
# Theme lives here; without it the container falls back to Streamlit's default look.
COPY --chown=appuser:appuser .streamlit ./.streamlit

RUN chmod +x docker/entrypoint.sh && chown appuser:appuser /app

USER appuser
EXPOSE 8501

# ALB/ECS target-group checks should point at the same path.
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD ["python", "/app/docker/healthcheck.py"]

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["app"]
