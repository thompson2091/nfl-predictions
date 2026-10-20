"""Hand an Out player's projected work to the teammates who will do it.

The models take who is Out as an input (`build_vacated_share`), and on
2024-25 that closed about a third of the gap: when a back projected 30+
rushing yards was Out, the backs who played were still projected 65 a
team-game and gained 88. A tree barely uses a signal present on 5% of rows.

So this is the rest, done directly. Per team-game, the Out players' own
projected means at the position are pooled and split among the active
players there by recent share; `beta` — fitted on 2024 in
scripts/72_vacated.py and judged on 2025 — says how much of that pool
actually moves. Yardage scales each player's whole distribution by
(mean + beta * slice) / mean; catches add to the expected count.

A market with no fitted file is left exactly as the model said.
"""
from __future__ import annotations

import json

import numpy as np
import polars as pl

from src.utils.paths import get_path

#: Per market: who the Out pool comes from and goes to, and the share that
#: splits it. Targets move between positions — a receiver's absence feeds the
#: tight end too — so receiving pools every pass catcher; carries stay with
#: the backs.
RULES = {
    "rushing_yards": ("rb", "player_rush_share_avg_5g"),
    "receiving_yards": ("catchers", "player_target_share_avg_5g"),
    "receptions": ("catchers", "player_target_share_avg_5g"),
}

#: A slice is divided by the player's own mean; this floor stops a player
#: projected near zero from turning a few yards into a multiple of nothing.
MEAN_FLOOR = 1.0


def _group(df: pl.DataFrame, who: str) -> pl.Expr:
    if who == "rb":
        return pl.col("position_RB").fill_null(0) == 1
    no = [c for c in ("position_QB", "position_FB", "position_DEFST") if c in df.columns]
    e = pl.lit(True)
    for c in no:
        e = e & (pl.col(c).fill_null(0) != 1)
    return e


def allocation(df: pl.DataFrame, mean: np.ndarray, market: str) -> np.ndarray:
    """Each active player's slice of what his Out teammates were projected for."""
    who, share = RULES[market]
    if share not in df.columns or "is_out" not in df.columns:
        return np.zeros(df.height)
    d = df.select(["game_id", "team", "is_out", share,
                   *[c for c in ("position_RB", "position_QB", "position_FB",
                                 "position_DEFST") if c in df.columns]]).with_columns(
        pl.Series("_m", mean), _group(df, who).alias("_g"),
        (pl.col("is_out").fill_null(0) == 1).alias("_o"))
    d = d.with_columns(
        pl.when(pl.col("_g") & pl.col("_o")).then(pl.col("_m")).otherwise(0.0).alias("_pool"),
        pl.when(pl.col("_g") & ~pl.col("_o")).then(pl.col(share).fill_null(0).clip(lower_bound=0))
          .otherwise(0.0).alias("_w"))
    d = d.with_columns(
        pl.col("_pool").sum().over(["game_id", "team"]).alias("_P"),
        pl.col("_w").sum().over(["game_id", "team"]).alias("_W"))
    return d.select(
        pl.when(pl.col("_W") > 0).then(pl.col("_P") * pl.col("_w") / pl.col("_W"))
          .otherwise(0.0)).to_series().to_numpy()


def scale_quantiles(q: np.ndarray, mean: np.ndarray, slice_: np.ndarray,
                    beta: float) -> np.ndarray:
    s = (mean + beta * slice_) / np.maximum(mean, MEAN_FLOOR)
    s = np.where(slice_ > 0, np.maximum(s, 1.0), 1.0)
    return q * s[:, None]


def path(market: str):
    return get_path("models", market) / "vacated.json"


def load_beta(market: str) -> float | None:
    p = path(market)
    if not p.exists():
        return None
    try:
        return float(json.loads(p.read_text())["beta"])
    except Exception:                                            # noqa: BLE001
        return None
