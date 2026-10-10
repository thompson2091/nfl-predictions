"""One line per prediction run: what produced the board that was written.

Nothing recorded, for any run, which model version, which commit, which fitted
weights or which odds capture a board came from — so a board on disk could not
be traced to anything, and two boards for one week could not be told apart.
`append` writes one JSON line to `archive/runs/<season>.jsonl`, which lives in
git with the freezes for the same reason they do: it describes a moment and
nothing can regenerate it.

Every field is best-effort. A manifest that could stop a prediction run would
be a worse trade than a manifest with a missing hash.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "archive" / "runs"

#: Files refit in place that change what a board says without a version bump.
SERVED = ("blend_weight.json", "edge_threshold.json",
          "market_blend_served.json")


def _sha(p: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except Exception:                                            # noqa: BLE001
        return None


def _git() -> dict:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "src",
                                "scripts", "config"], cwd=ROOT,
                               capture_output=True, text=True, timeout=10)
        return {"commit": sha.stdout.strip() or None,
                "dirty": bool(dirty.stdout.strip())}
    except Exception:                                            # noqa: BLE001
        return {"commit": None, "dirty": None}


def _served_version(market: str) -> str | None:
    try:
        cur = json.loads((ROOT / "models" / "registry" / "CURRENT.json").read_text())
        return (cur.get(market) or {}).get("version")
    except Exception:                                            # noqa: BLE001
        return None


def served_version(market: str) -> str | None:
    """What model a board was scored by, as one short string.

    The touchdown markets have locked versions in `CURRENT.json`. The four
    over/under markets do not — their models are a `.pkl` and two JSON files
    refit in place — so for those this is a hash of every file in
    `models/<market>/`, which changes exactly when what is served changes.
    Stamped on every frozen board so the forward record can be split by the
    model that made it rather than pooling two versions under one number.
    """
    v = _served_version(market)
    if v:
        return v
    d = ROOT / "models" / market
    if not d.is_dir():
        return None
    h = hashlib.sha256()
    for f in sorted(p for p in d.iterdir() if p.is_file()):
        h.update(f.name.encode())
        h.update((_sha(f) or "").encode())
    return "files:" + h.hexdigest()[:12]


def _latest_capture() -> str | None:
    try:
        import polars as pl

        from src.ingest.odds_history import HISTORY_PATH

        got = pl.scan_parquet(HISTORY_PATH).select(
            pl.col("captured_at").max()).collect().item()
        return None if got is None else str(got)
    except Exception:                                            # noqa: BLE001
        return None


def entry(market: str, season: int, week: int, **extra) -> dict:
    model_dir = ROOT / "models" / market
    return {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "market": market, "season": int(season), "week": int(week),
        **_git(),
        "version": _served_version(market),
        "served": {f: _sha(model_dir / f) for f in SERVED
                   if (model_dir / f).exists()},
        "features": _sha(ROOT / "data" / "processed" / market / "features.parquet"),
        "odds_captured_at": _latest_capture(),
        **extra,
    }


def append(market: str, season: int, week: int, **extra) -> Path | None:
    import os

    # A test that drives `predict` is not a run anyone served. The parity
    # check does exactly that, and its lines would be noise in a file that
    # lives in git.
    if os.environ.get("PYTEST_CURRENT_TEST") and RUNS == ROOT / "archive" / "runs":
        return None
    try:
        RUNS.mkdir(parents=True, exist_ok=True)
        p = RUNS / f"{int(season)}.jsonl"
        with p.open("a") as fh:
            fh.write(json.dumps(entry(market, season, week, **extra),
                                sort_keys=True) + "\n")
        return p
    except Exception:                                            # noqa: BLE001
        return None
