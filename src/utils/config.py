import yaml
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "settings.yaml"
_config = None


def get_config() -> dict:
    global _config
    if _config is None:
        with open(_CONFIG_PATH) as f:
            _config = yaml.safe_load(f)
    return _config
