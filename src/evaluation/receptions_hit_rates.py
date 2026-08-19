"""When the receptions model says 80%, how often is it right?

The anytime-TD board answers "who scores", and `hit_rates` measures it by
asking how often the top-ranked pick is the one who did. Receptions is not that
shape. It is a two-sided line: every row is a (player, line) pair and the
question is whether he goes over or under, so there is no "top pick" and no
ranking within a game. The reliability question is calibration — of the rows
where we claimed 80% confidence, did 80% land?

**Confidence is on the side taken, not on the over.** The model emits P(over).
A row at P(over)=0.18 is not a weak claim, it is a strong claim about the
under, and scoring it on the over would report the model as badly calibrated
when it is confidently right. Everything here reads `max(p, 1-p)` and grades
against whether the chosen side landed.

**The market is shown beside every band, and it is not decoration.** This model
does not beat this market — log loss 0.669 vs 0.644 in 2024 and 0.689 vs 0.673
in 2025, both held out (`output/receptions/summary.json`). A calibration table
without that comparison invites reading "78% in the 0.8 band" as an edge, when
the book was more accurate on the same rows. The honest claim this supports is
"our stated confidence means what it says", not "we know better".

Intervals are bootstrapped over GAMES, not rows. A player has several lines,
players share a game, and a blowout moves all of them together, so treating
4,555 rows as 4,555 independent observations would understate the interval by
roughly the square root of the clustering.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from src.evaluation.hit_rates import MIN_GAMES, _clustered_rate
from src.utils.paths import get_path

#: Confidence bands on `max(p, 1-p)`, so they start at 0.5 rather than 0. Below
#: 0.55 the model is saying it does not know, which is a real answer and worth
#: showing rather than hiding.
BANDS = (0.50, 0.55, 0.60, 0.70, 0.80, 1.01)

#: A band this thin is a description of those rows, not an estimate.
MIN_ROWS = 60


def _backtests() -> pl.DataFrame | None:
    """Every held-out season the receptions backtest has written."""
    root = get_path("output") / "receptions"
    frames = [pl.read_csv(p) for p in sorted(root.glob("backtest_*.csv"))]
    if not frames:
        return None
    df = pl.concat(frames, how="vertical")
    return df.filter(pl.col("y_over").is_not_null()
                     & pl.col("p_model").is_not_null())


def _sided(df: pl.DataFrame, prob_col: str) -> pl.DataFrame:
    """Add the side taken, the confidence in it, and whether it landed."""
    return df.with_columns([
        pl.when(pl.col(prob_col) >= 0.5).then(pl.lit("over"))
          .otherwise(pl.lit("under")).alias("side"),
        pl.max_horizontal(pl.col(prob_col), 1 - pl.col(prob_col)).alias("conf"),
        pl.when(pl.col(prob_col) >= 0.5)
          .then(pl.col("y_over")).otherwise(1 - pl.col("y_over")).alias("hit"),
    ])


def calibration(bands: tuple[float, ...] = BANDS) -> dict | None:
    """Claimed confidence against measured hit rate, model and market side by side.

    Returns None when no backtest exists, so a caller can say "not measured"
    rather than draw an empty table.
    """
    df = _backtests()
    if df is None or df.is_empty():
        return None

    out = {"rows": df.height,
           "seasons": sorted(df["season"].unique().to_list()),
           "games": int(df["game_id"].n_unique()),
           "bands": []}

    model = _sided(df, "p_model")
    has_market = "fair_prob" in df.columns and df["fair_prob"].is_not_null().any()
    market = _sided(df.filter(pl.col("fair_prob").is_not_null()), "fair_prob") \
        if has_market else None

    for lo, hi in zip(bands, bands[1:]):
        m = model.filter((pl.col("conf") >= lo) & (pl.col("conf") < hi))
        if m.height < MIN_ROWS:
            continue
        rate, lo_ci, hi_ci = _clustered_rate(
            m["hit"].to_numpy().astype(float),
            m["game_id"].to_numpy(), seed=int(lo * 100))
        row = {"lo": lo, "hi": min(hi, 1.0), "n": m.height,
               "games": int(m["game_id"].n_unique()),
               "claimed": float(m["conf"].mean()),
               "measured": rate, "ci_lo": lo_ci, "ci_hi": hi_ci,
               "over_share": float((m["side"] == "over").mean())}
        row["gap"] = row["measured"] - row["claimed"]
        row["honest"] = bool(row["ci_lo"] <= row["claimed"] <= row["ci_hi"])

        if market is not None:
            k = market.filter((pl.col("conf") >= lo) & (pl.col("conf") < hi))
            if k.height >= MIN_ROWS:
                k_rate, k_lo, k_hi = _clustered_rate(
                    k["hit"].to_numpy().astype(float),
                    k["game_id"].to_numpy(), seed=int(lo * 100))
                row["market"] = {"n": k.height, "claimed": float(k["conf"].mean()),
                                 "measured": k_rate, "ci_lo": k_lo, "ci_hi": k_hi}
        out["bands"].append(row)

    if not out["bands"]:
        return None

    # One headline number: across every band, is the stated confidence a
    # promise the measurement keeps? Reported as the worst miss, because an
    # average gap hides a band that is badly wrong in one direction.
    misses = [b for b in out["bands"] if not b["honest"]]
    out["all_bands_honest"] = not misses
    out["worst_gap"] = max((abs(b["gap"]) for b in out["bands"]), default=0.0)
    out["worst_band"] = max(out["bands"], key=lambda b: abs(b["gap"]))["lo"]
    return out


def selectivity(threshold: float) -> dict | None:
    """What you get by only acting above a confidence threshold.

    The counterpart to `hit_rates.rate_at`: the trade is always coverage for
    accuracy, and a threshold is only useful if it leaves enough rows to act
    on. `share` is what fraction of priced lines survive it.
    """
    df = _backtests()
    if df is None or df.is_empty():
        return None
    model = _sided(df, "p_model")
    kept = model.filter(pl.col("conf") >= threshold)
    if kept.height == 0:
        return {"threshold": threshold, "n": 0, "share": 0.0,
                "measured": float("nan"), "ci_lo": float("nan"),
                "ci_hi": float("nan"), "games": 0, "enough": False}
    rate, lo, hi = _clustered_rate(kept["hit"].to_numpy().astype(float),
                                   kept["game_id"].to_numpy(),
                                   seed=int(threshold * 100))
    games = int(kept["game_id"].n_unique())
    return {"threshold": threshold, "n": kept.height,
            "share": kept.height / model.height, "games": games,
            "measured": rate, "ci_lo": lo, "ci_hi": hi,
            "claimed": float(kept["conf"].mean()),
            "enough": games >= MIN_GAMES}


def sweep(thresholds=(0.55, 0.60, 0.65, 0.70, 0.75, 0.80)) -> list[dict]:
    """The whole accuracy-for-coverage curve, for a chart or a table."""
    return [r for t in thresholds if (r := selectivity(t)) is not None]
