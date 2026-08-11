"""Do the served path and the evaluated path produce the same numbers?

Four separate bugs in this project were the same bug: production and evaluation
quietly disagreeing about what the pipeline does, with nothing failing.

  * The backtest applied no calibrator while the app applied one.
  * The board ranked on the blended probability while the money was measured on
    the pre-blend one — worth eight points of return.
  * Week 1 was built with carry-forward when serving and without it in training.
  * The backtest applied the anytime-TD joint model to first TD, whose
    probabilities must sum to 1 per game and instead summed to 2.7.

None of them raised an error. Each produced plausible numbers that were simply
describing a different pipeline from the one being run, and each was found by
accident. This module turns that into a check: score a week both ways, join on
the player, and report the gap.

A non-zero gap is not automatically a bug — a historical week has no cached
sportsbook prices, so the served path cannot blend and legitimately differs.
`compare` reports the gap on each stage separately so a real divergence is
distinguishable from a missing input.
"""
from __future__ import annotations

import polars as pl

#: Anything above this is a disagreement worth explaining. Probabilities here
#: live on 0-1 and the differences that mattered were 0.07 to 0.31, so a
#: thousandth is comfortably below anything meaningful and comfortably above
#: floating-point noise.
TOLERANCE = 1e-3


def compare(season: int, week: int, target_type: str,
            model_name: str | None = None) -> dict | None:
    """Score one week through both paths and measure the gap.

    Returns None when the inputs for a comparison are not present — no backtest
    frame for that season, or no overlap after joining — rather than inventing
    a passing result.
    """
    from src.evaluation.rank_economics import backtest_files
    from src.prediction.predict import predict
    from src.utils.config import production_model

    model_name = model_name or production_model(target_type)

    frames = [p for p in backtest_files(target_type)
              if p.stem.endswith(str(season))]
    if not frames:
        return None
    bt = pl.read_csv(frames[0]).filter(pl.col("week") == week)
    if bt.height == 0:
        return None

    served = predict(season, week, model_name=model_name,
                     target_type=target_type)
    if served is None:
        return None

    keep = [c for c in ("prob_calibrated", "final") if c in bt.columns]
    joined = served.select(["game_id", "player_name", "probability"]).join(
        bt.select(["game_id", "player_name"] + keep),
        on=["game_id", "player_name"], how="inner",
    )
    if joined.height == 0:
        return None

    out = {
        "target_type": target_type, "season": season, "week": week,
        "model": model_name, "n": int(joined.height),
    }
    for col in keep:
        gap = (joined["probability"] - joined[col]).abs()
        out[f"vs_{col}"] = {
            "mean": float(gap.mean()),
            "max": float(gap.max()),
            "agrees": bool(gap.max() <= TOLERANCE),
        }
    # The served path publishes one number. It should equal whichever backtest
    # column represents the same stage — `final` for a market that blends,
    # `prob_calibrated` for one that does not. Agreeing with *neither* is the
    # signature of the bugs above.
    out["agrees_with_some_stage"] = any(
        out[f"vs_{c}"]["agrees"] for c in keep
    )
    return out


def check(target_type: str, season: int, week: int | None = None,
          model_name: str | None = None) -> tuple[bool, str]:
    """(ok, message) for a single week, suitable for a test or a CLI."""
    from src.evaluation.rank_economics import backtest_files

    if week is None:
        frames = [p for p in backtest_files(target_type)
                  if p.stem.endswith(str(season))]
        if not frames:
            return True, f"{target_type} {season}: no backtest frame — skipped"
        week = int(pl.read_csv(frames[0])["week"].min())

    res = compare(season, week, target_type, model_name)
    if res is None:
        return True, f"{target_type} {season} wk{week}: not comparable — skipped"

    if res["agrees_with_some_stage"]:
        return True, (f"{target_type} {season} wk{week}: served output matches "
                      f"the evaluated path (n={res['n']})")

    detail = "  ".join(
        f"{k}: mean {v['mean']:.4f} max {v['max']:.4f}"
        for k, v in res.items() if isinstance(v, dict)
    )
    return False, (
        f"{target_type} {season} wk{week}: the served probability matches NO "
        f"stage of the evaluated path (n={res['n']}). {detail}\n"
        f"    One of predict.py or scripts/10_backtest.py is doing something "
        f"the other is not."
    )
