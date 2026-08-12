import copy
from contextlib import contextmanager
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "settings.yaml"
_config = None


def get_config() -> dict:
    global _config
    if _config is None:
        with open(_CONFIG_PATH) as f:
            _config = yaml.safe_load(f)
    return _config


def deep_merge(base: dict, overlay: dict) -> dict:
    """`overlay` on top of `base`, recursing into nested dicts.

    Lists replace rather than merge. `models.active: [xgb]` has to mean "only
    xgb", not "the existing three plus xgb again", or a screen restricting the
    model set would silently train everything.
    """
    out = copy.deepcopy(base)
    for key, value in (overlay or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


@contextmanager
def config_overlay(overlay: dict | None):
    """Run a block with `overlay` merged over the config, then put it back.

    Experiments are config diffs, and the config is a process-global singleton
    that `run_all.py` already mutates in place. Two consequences if experiments
    do the same by hand: a run that raises leaves the mutation behind, and the
    next experiment measures a recipe nobody asked for. This restores the
    original object on every exit, including exceptions.

    It deliberately does **not** write `config/settings.yaml`. An experiment
    that edits the served config on its way past is one that changes what the
    pipeline does days later, for reasons nobody can reconstruct.
    """
    global _config
    saved = get_config()
    try:
        _config = deep_merge(saved, overlay or {})
        yield _config
    finally:
        _config = saved


def config_diff(base: dict, other: dict) -> dict[str, tuple]:
    """Flattened `key.path -> (base, other)` for every value that differs.

    What a ledger row records as "the change": readable, and small enough that
    a reader can see the whole experiment at a glance.
    """
    def flat(d: dict, prefix: str = "") -> dict:
        out = {}
        for k, v in (d or {}).items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                out.update(flat(v, key))
            else:
                out[key] = v
        return out

    fa, fb = flat(base), flat(other)
    return {k: (fa.get(k), fb.get(k))
            for k in sorted(set(fa) | set(fb)) if fa.get(k) != fb.get(k)}


def production_model(target_type: str | None = None) -> str:
    """Which model serves this market.

    The two markets do not want the same model, and a single global setting
    quietly served the wrong one to whichever market lost the argument. The
    per-market choice lives in `models.production_by_target`, with
    `models.production` as the fallback so a market with no entry — or a config
    written before this existed — still resolves.

    The walk-forward numbers behind each choice are in `config/settings.yaml`
    next to the setting itself, and are re-derived by `make walkforward`. They
    used to be repeated here too, and the copy went stale: this docstring
    claimed anytime TD served `lgbm` at 54.6% Top-1 long after the config had
    been corrected to `xgb` at 50.9%. Measurements belong in one place, beside
    the thing they justify.
    """
    cfg = get_config()
    models = cfg["models"]
    if target_type is None:
        target_type = cfg["target"]["type"]
    return models.get("production_by_target", {}).get(
        target_type, models["production"]
    )
