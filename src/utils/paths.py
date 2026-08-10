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
