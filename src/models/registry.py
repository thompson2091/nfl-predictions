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


def ensure_registered():
    """Import all model modules so decorators fire."""
    import src.models.logistic  # noqa: F401
    import src.models.lightgbm_model  # noqa: F401
    import src.models.xgboost_model  # noqa: F401
    import src.models.ranker  # noqa: F401
    import src.models.count  # noqa: F401
