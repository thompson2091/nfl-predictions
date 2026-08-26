import os
from pathlib import Path
from src.utils.config import get_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_path(key: str, target_type: str = None) -> Path:
    """Get path for a config key, optionally scoped to a target type.

    When target_type is provided, processed/models/output paths get a
    target_type subdirectory (e.g., models/first_td/).
    Raw data paths are never scoped.
    """
    p = PROJECT_ROOT / get_config()["paths"][key]
    if target_type and key in ("processed", "models", "output", "plots"):
        p = p / target_type
    p.mkdir(parents=True, exist_ok=True)
    return p


def records_dir() -> Path:
    """Where the two files that cannot be regenerated live.

    Everything under `output/` is rebuilt by a make target. The tracked rules'
    weekly picks and the bets actually placed are not: they record what was
    true at a moment, and re-deriving them later would quietly run today's
    model over last week's board.

    `NFL_RECORDS_DIR` moves them, which exists for exactly one caller — the
    rehearsal in `scripts/44_rehearse.py`. A dry run has to drive the real
    scripts to prove anything, and a dry run that appended August prices as
    week 1's tracked picks would corrupt the record the forward test is for.
    """
    p = Path(os.environ.get("NFL_RECORDS_DIR") or (PROJECT_ROOT / "data"))
    p.mkdir(parents=True, exist_ok=True)
    return p
