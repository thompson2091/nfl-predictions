"""The served over/under blend weight, fitted on every season the trees never saw.

`scripts/30_receptions.py` and `scripts/49_yards.py` fit each market's blend on
the VALIDATION season only (2024) and score it on the test season (2025). That
is the right protocol for REPORTING — it is what makes the 2025 result an
out-of-sample claim — and it is the wrong one for SERVING 2026, because it
throws away a whole completed season that the trees (trained through 2023)
never saw. Both seasons are out of the trees; only one was used.

So this fits the weight that is served on validation + test together and saves
it beside the validation fit rather than over it:

    market_blend.json          validation season only — the reported number
    market_blend_served.json   every out-of-tree season — the served number
    market_blend_live.json     the season being played, once it can carry it

`load_blend` reads them in the reverse of that order. Nothing is replaced: the
validation fit is still what `summary.json` reports and what the forward
record falls back to.

Measured 2026-10-06, scored on 2026 weeks 1-4 (all lines, never in any fit),
log loss of the blend minus the market's, in thousandths:

    market            2024 fit     2024+2025 fit    change
    receptions        0.17 -3.72   0.21 -4.26       -0.53
    receiving yards   0.19 -0.20   0.21 -0.07       +0.13
    rushing yards     0.06 -1.63   0.12 -2.69       -1.06
    passing yards     0.55 -11.6   0.48 -11.5       +0.16

Every change is inside its own noise (bootstrap SE 1.6-10 thousandths). The
case for the refit is not that 2026 proved it better — four weeks cannot — but
that it is fitted on twice the rows and includes the most recent completed
season, and the one season it can be checked against does not object.
"""
from __future__ import annotations

import json
from datetime import date

import polars as pl

MARKETS = ("receptions", "receiving_yards", "rushing_yards", "passing_yards")

SERVED_FILE = "market_blend_served.json"


def _backtest(market: str, season: int) -> pl.DataFrame | None:
    from src.utils.paths import get_path

    path = get_path("output", market) / f"backtest_{season}.csv"
    if not path.exists():
        return None
    d = pl.read_csv(path)
    need = {"p_model", "fair_prob", "y_over"}
    if not need <= set(d.columns):
        return None
    # The SERVED calibration, where the backtest kept the raw number: the
    # file's own `p_model` is calibrated by the validation-only fit, which is
    # right for scoring the test season and not what the board serves.
    # See `src/models/ou_calibration.py`.
    if "p_model_raw" in d.columns:
        from src.models import ou_calibration

        cal = ou_calibration.load(market)
        if cal and cal.get("kind", "").endswith("_served"):
            d = d.with_columns(pl.Series(
                "p_model", ou_calibration.apply(d["p_model_raw"].to_numpy(), cal)))
    return d.drop_nulls(list(need))


def out_of_tree_seasons() -> list[int]:
    """Validation and test seasons: graded, and never seen by the trees."""
    from src.utils.config import get_config

    s = get_config()["splits"]
    return [int(s["val_season"]), int(s["test_season"])]


def refit_served(market: str, seasons: list[int] | None = None,
                 write: bool = True) -> dict | None:
    """Fit the served weight for one market on its out-of-tree backtests."""
    from src.models.count import fit_market_blend
    from src.utils.paths import get_path

    seasons = seasons or out_of_tree_seasons()
    parts = [b for s in seasons if (b := _backtest(market, s)) is not None]
    if not parts:
        return None
    d = pl.concat(parts, how="vertical_relaxed")
    out = fit_market_blend(d["p_model"].to_numpy(), d["fair_prob"].to_numpy(),
                           d["y_over"].to_numpy(),
                           kind=f"{market}_market_blend_served")
    out["fitted_on"] = sorted({int(s) for s in d["season"].unique().to_list()})
    out["fit_date"] = date.today().isoformat()
    root = get_path("models", market)
    val = root / "market_blend.json"
    if val.exists():
        try:
            out["validation_weight"] = json.loads(val.read_text())["weight"]
        except Exception:                                        # noqa: BLE001
            pass
    if write:
        from src.utils.history import write_kept

        write_kept(root / SERVED_FILE, json.dumps(out, indent=1))
    return out


def refit_all(write: bool = True) -> dict:
    return {m: refit_served(m, write=write) for m in MARKETS}
