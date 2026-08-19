"""Model registry: register and look up model classes by name."""
from __future__ import annotations

_MODELS: dict[str, type] = {}


def register(name: str):
    """Decorator to register a model class.

    Usage:
        @register("lr")
        class LogisticModel:
            ...
    """
    def decorator(cls):
        _MODELS[name] = cls
        return cls
    return decorator


def get_model(name: str) -> type:
    """Look up a registered model class by name."""
    if name not in _MODELS:
        raise ValueError(
            f"Unknown model '{name}'. Available: {list(_MODELS.keys())}"
        )
    return _MODELS[name]


def list_models() -> list[str]:
    """Return names of all registered models."""
    return list(_MODELS.keys())


#: Imported for their `@register` side effect. Split because the consequence of
#: one being absent differs: without a REQUIRED module the app cannot serve a
#: prediction at all, while an OPTIONAL one only removes a model nothing is
#: configured to use.
REQUIRED_MODEL_MODULES = (
    "src.models.logistic",
    "src.models.lightgbm_model",
    "src.models.xgboost_model",
)

#: Registered, not active, and not needed to serve. `condlogit` and `xgbrank`
#: are both tried-and-rejected; `count` serves the receptions page only.
OPTIONAL_MODEL_MODULES = (
    "src.models.ranker",
    "src.models.count",
    "src.models.pairwise",
)

#: Optional modules that failed to import, with the reason. Read by the app so
#: a degraded state is visible rather than silent.
MISSING_OPTIONAL: dict[str, str] = {}


def ensure_registered():
    """Import all model modules so decorators fire.

    Optional modules are allowed to fail. `src/models/pairwise.py` was added on
    2026-08-19 and the containerised app died at import with
    ModuleNotFoundError — a bare `import` at startup means any image whose
    source is a commit behind takes the whole UI down for a model that is not
    even active. The same shape is already documented in
    `odds_history.resolve_player_ids`: a missing optional input killed the app
    in the production image, and the fix there was the same, return less rather
    than raise.

    A required module still raises: without it there is nothing to serve, and
    failing loudly is correct.
    """
    import importlib

    for name in REQUIRED_MODEL_MODULES:
        importlib.import_module(name)

    for name in OPTIONAL_MODEL_MODULES:
        try:
            importlib.import_module(name)
            MISSING_OPTIONAL.pop(name, None)
        except Exception as exc:                       # noqa: BLE001
            MISSING_OPTIONAL[name] = f"{type(exc).__name__}: {exc}"
