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


def production_model(target_type: str | None = None) -> str:
    """Which model serves this market.

    The two markets do not want the same model, and a single global setting
    quietly served the wrong one to whichever market lost the argument.
    Measured by walk-forward over ~1,100 games each:

        anytime_td   lgbm  Top-1 54.6%   vs lr 50.8%, xgb 53.5%, ens 53.3%
        first_td     ens   Top-1 17.1%   vs lr 16.0%, lgbm 16.4%, xgb 16.9%

    `models.production_by_target` holds the per-market choice and
    `models.production` remains the fallback, so a market with no entry — or a
    config written before this existed — still resolves.
    """
    cfg = get_config()
    models = cfg["models"]
    if target_type is None:
        target_type = cfg["target"]["type"]
    return models.get("production_by_target", {}).get(
        target_type, models["production"]
    )
