"""What each position actually does, what it is charged, and what we say.

Three numbers a reader keeps re-deriving by eye, put in one table:

  * **How often a position scores.** A running back is not a wide receiver is
    not a quarterback, and "12%" means nothing until you know which.
  * **What the book charges for it.** The de-vigged price beside the realised
    rate is the market's own accuracy, position by position — and the gap is
    where a market-wide edge would have to live if one existed.
  * **What we say.** Our mean probability against the same realised rate is a
    calibration check the pooled figures cannot give: a model that is 2 points
    hot on tight ends and 2 cold on backs looks perfect in aggregate and is
    wrong on every row.

Measured over the priced population by default, because that is the population
anybody bets — the whole rated slate includes deep reserves nobody has ever
posted a price for, and their scoring rate drags every row toward zero without
describing a bet anyone could make. `all_rated` carries the wider number for
context.

Positions come from the feature matrix's own dummies rather than a roster join,
so a row is labelled with exactly what the model was told about it. Wide
receiver is the reference category — no dummy — which is why it is derived by
elimination here rather than read.
"""
from __future__ import annotations

import polars as pl

from src.evaluation.combo_backtest import backtest_files, _season
from src.utils.paths import get_path

#: The dummies the feature matrix carries, in the order a reader thinks about
#: them. Wide receiver is the reference category and has no column.
POSITION_DUMMIES = ("RB", "WR", "TE", "QB", "FB", "DEFST")

#: Below this many player-weeks a position's rate is noise dressed as a fact.
MIN_ROWS = 200


def _position_expr(available: list[str]) -> pl.Expr:
    """Label each row with its position, WR by elimination."""
    expr = None
    for p in POSITION_DUMMIES:
        col = f"position_{p}"
        if col not in available:
            continue
        expr = (pl.when(pl.col(col) == 1).then(pl.lit(p)) if expr is None
                else expr.when(pl.col(col) == 1).then(pl.lit(p)))
    return (pl.lit("WR") if expr is None else expr.otherwise(pl.lit("WR")))


def _features(target_type: str) -> pl.DataFrame | None:
    path = get_path("processed", target_type) / "features.parquet"
    if not path.exists():
        return None
    lf = pl.scan_parquet(path)
    cols = lf.collect_schema().names()
    dummies = [c for c in cols if c.startswith("position_")]
    need = ["season", "week", "game_id", "player_id", "target"]
    if not set(need) <= set(cols):
        return None
    return (lf.select(need + dummies)
            .with_columns(_position_expr(dummies).alias("position"))
            .select(need + ["position"])
            .collect())


def _priced(target_type: str, model: str) -> pl.DataFrame | None:
    """Every backtested player-week that carried a price, with what we said."""
    frames = []
    for path in backtest_files(target_type, model):
        df = pl.read_csv(path)
        if not {"player_id", "week", "scored", "odds"} <= set(df.columns):
            continue
        keep = ["player_id", "week", "scored", "odds", "market_prob"]
        keep += [c for c in ("prob_calibrated", "final") if c in df.columns]
        df = df.select(keep).with_columns(pl.lit(_season(path)).alias("season"))
        frames.append(df.drop_nulls(subset=["odds", "market_prob"]))
    if not frames:
        return None
    return pl.concat(frames, how="diagonal_relaxed")


def measure(target_type: str, model: str) -> dict | None:
    """Realised rate, price and model estimate for each position.

    Returns `None` rather than an empty table when either half is missing: a
    position table built from prices with no outcomes, or outcomes with no
    prices, is two different questions averaged together.
    """
    feats = _features(target_type)
    priced = _priced(target_type, model)
    if feats is None or priced is None:
        return None

    j = priced.join(feats, on=["season", "week", "player_id"], how="inner")
    if j.height == 0:
        return None
    prob_col = ("prob_calibrated" if "prob_calibrated" in j.columns
                else "final" if "final" in j.columns else None)

    # The seasons that actually carry both halves. Reading them off the feature
    # matrix instead spans every season it holds — 2015-2026 — and labels a
    # three-season measurement with a decade.
    seasons = sorted(j["season"].unique().to_list())
    rows = []
    for pos in sorted(set(j["position"].to_list())):
        part = j.filter(pl.col("position") == pos)
        if part.height < MIN_ROWS:
            continue
        wide = feats.filter((pl.col("position") == pos)
                            & pl.col("season").is_in(seasons))
        rows.append({
            "position": pos,
            "priced_weeks": int(part.height),
            "scored_pct": float(part["scored"].mean() * 100),
            # The market's own accuracy on this position, margin removed.
            "book_pct": float(part["market_prob"].mean() * 100),
            "ours_pct": (None if prob_col is None
                         else float(part[prob_col].mean() * 100)),
            "median_odds": float(part["odds"].median()),
            # Context: the same rate over everyone the model rates, priced or
            # not. Far lower, and not a bet anyone can make.
            "all_rated_pct": float(wide["target"].mean() * 100),
            "all_rated_weeks": int(wide.height),
        })
    if not rows:
        return None
    rows.sort(key=lambda r: -r["scored_pct"])
    return {
        "kind": "position_rates",
        "target_type": target_type, "model": model,
        "seasons": seasons,
        "span": f"{seasons[0]}-{seasons[-1]}" if seasons else "",
        "min_rows": MIN_ROWS,
        "rows": rows,
    }


def load(path) -> dict | None:
    import json
    from pathlib import Path

    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else None
