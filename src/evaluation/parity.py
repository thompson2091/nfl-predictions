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

    from src.utils.paths import get_path as _gp

    # The parity frame first, when one exists. `make evaluate` builds the
    # season frames with --walk-forward, whose folds retrain on earlier seasons
    # and so cannot be compared to the served weights; `make parity-frame`
    # builds this one on the production model for exactly this check. Falling
    # back to the season frame keeps the old behaviour, and the tags below
    # explain the skip when it cannot be used.
    parity_frame = _gp("output", target_type) / f"parity_{season}.csv"
    if parity_frame.exists():
        frames = [parity_frame]
    else:
        frames = [p for p in backtest_files(target_type)
                  if p.stem.endswith(str(season))]
    if not frames:
        return None

    # Artifacts of different vintages are not a parity failure, they are a
    # staleness one, and conflating the two turns this check into noise during
    # any rebuild. If the features moved after the backtest frame was written,
    # the two paths are being asked about different inputs.
    from src.utils.paths import get_path

    feats = get_path("processed", target_type) / "features.parquet"
    if feats.exists() and feats.stat().st_mtime > frames[0].stat().st_mtime:
        return {"stale": True, "target_type": target_type, "season": season,
                "week": week, "n": 0}

    bt = pl.read_csv(frames[0]).filter(pl.col("week") == week)
    if bt.height == 0:
        return None

    # A walk-forward frame is not comparable and never was. Its fold retrains
    # from scratch on the seasons before the one being scored, so `raw_prob`
    # comes from weights production does not serve — the difference is 0.0147
    # mean on anytime TD against 1.9e-9 for a frame built on the production
    # model. `make evaluate` passes --walk-forward, which is right for the
    # measurement it is making and wrong for this one, so the two silently
    # disagreed for as long as the frames were fresh enough to be compared.
    #
    # Frames written before this column existed carry no answer; treat them as
    # unknown rather than assume, since assuming "not walk-forward" is what
    # produced a year of confident wrong failures.
    if "walk_forward" in bt.columns:
        if bool(bt["walk_forward"][0]):
            return {"walk_forward": True, "target_type": target_type,
                    "season": season, "week": week, "n": 0}
    else:
        return {"untagged": True, "target_type": target_type,
                "season": season, "week": week, "n": 0}

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
    if res.get("walk_forward"):
        return True, (
            f"{target_type} {season} wk{week}: the backtest frame was built "
            f"with --walk-forward, whose folds retrain on earlier seasons — "
            f"not comparable to the served model. Rebuild one for parity with "
            f"`python scripts/10_backtest.py --season {season} "
            f"--target {target_type}`"
        )
    if res.get("untagged"):
        return True, (
            f"{target_type} {season} wk{week}: the backtest frame predates the "
            f"`walk_forward` tag, so it cannot say which weights wrote it — "
            f"re-run `make evaluate`"
        )
    if res.get("stale"):
        return True, (
            f"{target_type} {season} wk{week}: features are newer than the "
            f"backtest frame — re-run `make evaluate` before trusting parity"
        )

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
