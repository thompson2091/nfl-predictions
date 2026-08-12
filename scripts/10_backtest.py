#!/usr/bin/env python3
"""Walk-forward backtest of the real betting pipeline against archived odds.

Answers the only question that matters: would this app have made money?

Two things make this honest rather than flattering:

1. **It runs the production path**, not raw model output — model -> level
   calibration against the fitted scorer-rate prior -> de-vig the market ->
   blend -> bet card filters -> Kelly stake. A backtest of a path you don't
   actually run tells you nothing about the path you do.

2. **It walks forward.** The blend weight for week W is fitted only on games
   that finished before week W. Fitting it on the whole archive and then
   "testing" on part of that archive would leak the answer into the question.

    python scripts/10_backtest.py --season 2025

Requires an odds archive (scripts/09_backfill_odds.py).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, ".")

import numpy as np
import polars as pl

from src.ingest.odds_history import load_graded_history
from src.models.market_prior import load_prior, expected_scorers
from src.models.registry import get_model, ensure_registered
from src.models.scoring import score
from src.models.trainer import prepare_data, _filter_low_activity
from src.prediction.blend import (
    blend, calibrate_level, devig_market, fit_blend_weight,
)
from src.utils.config import get_config, production_model
from src.utils.paths import get_path


def _calibration(label: str, p: np.ndarray, y: np.ndarray) -> None:
    """Predicted vs actual by bucket — the underconfidence check."""
    print(f"\n  {label}")
    for lo, hi in [(0, .10), (.10, .20), (.20, .30), (.30, .45), (.45, 1.01)]:
        m = (p >= lo) & (p < hi)
        if m.sum() < 50:
            continue
        gap = p[m].mean() - y[m].mean()
        flag = "OVER " if gap > 0.02 else ("under" if gap < -0.02 else "  ok ")
        print(f"    {lo:.2f}-{hi:.2f}  n={m.sum():4d}  pred={p[m].mean():.3f}  "
              f"actual={y[m].mean():.3f}  {flag}")




def _clustered_roi(sel: pl.DataFrame, draws: int = 2000):
    """Flat-stake ROI with a game-clustered interval.

    Thin wrapper over src.evaluation.rank_economics.clustered_roi so this script
    and the rank-economics report can never disagree about what an interval
    means.
    """
    from src.evaluation.rank_economics import clustered_roi

    pnl = (sel["scored"].to_numpy().astype(float) * (sel["dec"].to_numpy() - 1)
           - (1 - sel["scored"].to_numpy().astype(float)))
    r = clustered_roi(pnl, sel["game_id"].to_numpy(), draws=draws)
    return r["lo"], r["hi"], r["roi"], r["concentration"]


def main(season: int, target_type: str, model_name: str,
         walk_forward: bool = False) -> int:
    """Replay one season through the production betting path.

    With `walk_forward`, the model is retrained from scratch on seasons before
    this one before scoring it. Without it, the season is scored by whatever
    model is in models/ — which trains through `splits.train_end`, so replaying
    2023 or 2024 scores rows the model was fitted on.

    That contamination is not academic. Measured on the Strong highlight tier:
    +84.9% on the in-sample season, +53.7% on the validation season, and
    +23.4% (interval spanning zero) on the only clean one. Reading those three
    as a time trend suggested a fading market edge; they are the ordinary
    in-sample-to-holdout gradient, and pooling them inflated every figure the
    board was built on.
    """
    ensure_registered()
    cfg = get_config()
    bcfg = cfg.get("betting", {})
    # The blend settings live under `blend:`, not `betting:`. Reading them from
    # bcfg meant `min_history_rows` and `bootstrap_market_weight` silently fell
    # through to their defaults in every backtest ever run, so the walk-forward
    # never used the configured values.
    blcfg = cfg.get("blend", {})
    min_edge = float(bcfg.get("min_edge_pp", 2.0)) / 100.0

    # Refuse to score a season the model was fitted on. This is a hard stop
    # rather than a warning because the failure is invisible in the output: the
    # numbers look plausible, they are simply too good, and they get pooled with
    # honest ones. It inflated the Strong tier from +27% to +56% and produced a
    # three-season "decay" that was entirely an artifact of which seasons were
    # in-sample.
    splits = cfg["splits"]
    if not walk_forward and season <= splits["val_season"]:
        which = ("trained on" if season <= splits["train_end"]
                 else "tuned on (validation season)")
        print(
            f"REFUSING: {season} is a season the model was {which} "
            f"(train_end={splits['train_end']}, val_season={splits['val_season']}).\n"
            f"Scoring it with models/ would measure the model against its own "
            f"training data.\n"
            f"Re-run with --walk-forward to retrain on earlier seasons first."
        )
        return 2

    model_dir = get_path("models", target_type)
    scratch = None
    if walk_forward:
        import tempfile
        from src.models.trainer import train_all

        scratch = Path(tempfile.mkdtemp(prefix=f"bt_{target_type}_{season}_"))
        model_dir = scratch / "models"
        splits = {"train_end": season - 2, "val_season": season - 1,
                  "test_season": season}
        print(f"Walk-forward: retraining on seasons <= {splits['train_end']} "
              f"(val {splits['val_season']}) before scoring {season}")
        train_all(target_type, splits=splits, model_dir=model_dir,
                  output_dir=scratch / "output")

    prior = load_prior(model_dir / "scorer_rate_prior.json")
    if prior is None:
        print("No scorer-rate prior — run `make train`.")
        return 1

    graded = load_graded_history(target_type)
    if graded is None or graded.height == 0:
        print("No graded odds archive — run scripts/09_backfill_odds.py.")
        return 1

    # Stacker training data, computed once and sliced per fold below.
    #
    # `model_dir` has to be passed explicitly. It defaults to production, and
    # under --walk-forward that would score the archive with a model trained on
    # the seasons the archive covers — the stacker would then see in-sample
    # predictions, conclude the model needs no market help, and drive the
    # weight to ~0.01. The guard at the top of this function does not catch it:
    # it checks the season being scored, not the one the stacker learned from.
    from src.prediction.blend import build_blend_training_frame
    stack = build_blend_training_frame(target_type, model_name,
                                       model_dir=model_dir)
    if stack is None:
        print("Could not build blend training frame.")
        return 1

    import pickle
    feature_cols = pickle.loads((model_dir / "feature_cols.pkl").read_bytes())

    # The calibrator is part of the production path: predict.py and the app both
    # apply it. This script did not, so every ROI and calibration number it ever
    # printed described an uncalibrated model while the app served a calibrated
    # one — a backtest of a path nobody runs, which is exactly what the module
    # docstring above promises not to do.
    from src.models.joint import apply_joint, load_team_rate, load_conversion
    team_model = load_team_rate(model_dir / "team_td_rate.json")
    conversion = load_conversion(model_dir / "td_conversion.json")
    if team_model is not None:
        print(f"Joint model: team rate {team_model['mean_team_tds']:.2f} "
              f"TDs/team-game (RMSE {team_model['rmse']:.2f})")

    # Skipped when the joint model is active — see the note in predict.py.
    # Stacking an additive per-rank correction on the joint output collapsed
    # the top ranks into ties and took 2025 AUC from 0.862 to 0.497.
    from src.models.rank_calibration import apply_rank_calibration, load as load_rank
    rank_calib = None if team_model is not None else load_rank(
        model_dir / "rank_calibration.json")
    if rank_calib:
        print(f"Applying rank calibration ({len(rank_calib.get('deltas', {}))} ranks)")

    print(f"Scoring with {model_name} via the shared scorer (calibrators applied)")

    feats = pl.read_parquet(get_path("processed", target_type) / "features.parquet")
    weeks = sorted(
        feats.filter((pl.col("season") == season) & pl.col("target").is_not_null())
        ["week"].unique().to_list()
    )

    all_rows = []
    for wk in weeks:
        wdf = _filter_low_activity(
            feats.filter((pl.col("season") == season) & (pl.col("week") == wk))
        )
        if wdf.height == 0:
            continue

        X, _ = prepare_data(wdf, feature_cols)
        # Canonical scorer: handles "ensemble" and applies each model's
        # calibrator, which is what production does. Hand-rolling it here is how
        # this script ended up backtesting an uncalibrated model.
        probs = score(model_name, X, feature_cols, model_dir)
        res = wdf.select(["game_id", "player_id", "player_name", "team", "target"]) \
                 .with_columns(pl.Series("raw_prob", probs))

        # --- production step 1: anchor the level to the fitted prior ---
        games = wdf.group_by("game_id").agg(
            [pl.col("total_line").first(), pl.col("spread_line").first()]
        )
        exp = expected_scorers(prior, games)

        # --- production step 2: de-vig this week's market ---
        mkt = graded.filter((pl.col("season") == season) & (pl.col("week") == wk))
        if mkt.height == 0:
            continue

        # First TD has exactly one scorer per game, so its probabilities must
        # sum to 1 within a game — which is what predict() does and what this
        # script did not. It applied the anytime-TD joint model instead, whose
        # team rate targets ~4.3 scorers a game, and produced first-TD
        # probabilities summing to 2.7 per game. Every first_td figure built on
        # this was structurally wrong, not merely noisy: the inflated numbers
        # made every market edge look enormous, which is how the market came to
        # read as a clear loser (-9.5%).
        #
        # Measured against outcomes, production's rule is simply better:
        #   normalise within game   Brier 0.03520  AUC 0.7987  sum/game 1.000
        #   joint model             Brier 0.04550  AUC 0.7843  sum/game 2.732
        if target_type == "first_td":
            res = res.with_columns(
                (pl.col("raw_prob") / pl.col("raw_prob").sum().over("game_id"))
                .alias("prob_calibrated")
            )
        # Joint structure, same call the app and predict.py make.
        elif team_model is not None:
            res = apply_joint(res, wdf, team_model, score_col="raw_prob",
                              out_col="prob_calibrated", conversion=conversion)
        else:
            share = float(prior.get("priced_share", 1.0))
            priced_keys = mkt.select(["game_id", "player_id"]).unique().with_columns(
                pl.lit(True).alias("is_priced")
            )
            res = res.join(priced_keys, on=["game_id", "player_id"], how="left") \
                     .with_columns(pl.col("is_priced").fill_null(False))
            res = calibrate_level(
                res, "raw_prob",
                exp.with_columns(pl.col("expected_scorers") * share),
                out_col="prob_calibrated", mask_col="is_priced",
            )

        # The positional correction is part of the served path too — the level
        # shift moves a whole game at once and cannot fix a bias that varies by
        # rank within it. Same parity point as the calibrator above.
        if rank_calib:
            res = apply_rank_calibration(
                res, rank_calib, "prob_calibrated", out_col="prob_calibrated"
            )
        # De-vig over the players we actually score, not every price in the
        # archive. The one-sided normalisation divides by sum(implied), so
        # including deep longshots nobody rates drags every favourite down —
        # and the archive's longshot coverage halved between 2023 and 2025.
        mkt = devig_market(
            mkt.join(res.select(["game_id", "player_id"]),
                     on=["game_id", "player_id"], how="inner")
               .select(["game_id", "player_id", "implied_prob", "fair_prob",
                        "odds", "scored"]),
            exp,
        )

        # --- production step 3: blend, using ONLY prior weeks to fit the weight ---
        past = stack.filter(
            (pl.col("season") < season)
            | ((pl.col("season") == season) & (pl.col("week") < wk))
        )
        fitted = fit_blend_weight(past, min_rows=blcfg.get("min_history_rows", 500))
        weight = fitted or {
            "market_weight": float(blcfg.get("bootstrap_market_weight", 0.5)),
            "source": "bootstrap",
        }

        merged = res.join(
            mkt.select(["game_id", "player_id", "market_prob", "odds", "scored"]),
            on=["game_id", "player_id"], how="inner",
        )
        if merged.height == 0:
            continue
        if target_type == "first_td":
            # predict() publishes the normalised number for this market without
            # blending, so `final` has to be that too or the backtest measures a
            # path nobody runs. Whether first TD *should* blend is a real
            # question, but it has to be answered by changing both paths at
            # once, not by leaving them disagreeing.
            merged = merged.with_columns([
                pl.col("prob_calibrated").alias("final"),
                pl.col("market_prob").is_not_null().alias("has_market_price"),
            ])
        else:
            merged = blend(merged, "prob_calibrated", "market_prob", weight,
                           out_col="final")
        all_rows.append(merged.with_columns([
            pl.lit(wk).alias("week"),
            pl.lit(weight["market_weight"]).alias("w_market"),
            pl.lit(weight.get("source", "?")).alias("w_src"),
        ]))

    if not all_rows:
        print("Nothing to evaluate — no weeks had both predictions and prices.")
        return 1

    df = pl.concat(all_rows)
    y = df["scored"].to_numpy().astype(float)
    print(f"\n{'=' * 72}")
    print(f"WALK-FORWARD BACKTEST — {target_type} {season} — model={model_name}")
    print(f"{'=' * 72}")
    print(f"player-games: {df.height:,}   games: {df['game_id'].n_unique()}   "
          f"base rate: {y.mean():.4f}")
    print(f"blend weight: {df['w_market'].min():.2f}-{df['w_market'].max():.2f} "
          f"({df['w_src'].unique().to_list()})")

    print("\nCALIBRATION AT EACH STAGE (this is the underconfidence check):")
    for col, lbl in [("raw_prob", "1. raw model"),
                     ("prob_calibrated", "2. + level calibration"),
                     ("market_prob", "3. market (de-vigged)"),
                     ("final", "4. FINAL blended (what you'd bet)")]:
        _calibration(lbl, df[col].to_numpy(), y)
        s = df[col].sum() / df["game_id"].n_unique()
        print(f"    sums to {s:.2f}/game among priced players "
              f"(actual {y.sum() / df['game_id'].n_unique():.2f})")

    # --- ROI through the real bet-card rules ---
    df = df.with_columns(
        pl.when(pl.col("odds") > 0).then(1 + pl.col("odds") / 100)
        .otherwise(1 + 100 / -pl.col("odds")).alias("dec")
    )
    df = df.with_columns([
        (pl.col("final") - pl.col("market_prob")).alias("edge"),
        (pl.col("final") * (pl.col("dec") - 1) - (1 - pl.col("final"))).alias("ev"),
    ])
    print(f"\n{'-' * 72}")
    print("RETURNS THROUGH THE PRODUCTION BET CARD (flat 1u stakes)")
    print(f"{'-' * 72}")
    print("Read the interval, not the point estimate. Returns on touchdown props")
    print("are dominated by a few long-odds hits, so a naive standard error is")
    print("badly optimistic; these resample whole games, since players in one")
    print("game share a defence, a game script and a final score.")
    print()
    print(f"{'filter':32s} {'bets':>6s} {'hit':>7s} {'ROI':>8s} {'95% interval':>22s} {'':>10s}")
    for lbl, flt in [
        ("every priced player", pl.lit(True)),
        (f"bet card (edge>={min_edge*100:.0f}pp, EV>0)",
         (pl.col("edge") >= min_edge) & (pl.col("ev") > 0)),
        ("edge>=5pp, EV>0", (pl.col("edge") >= 0.05) & (pl.col("ev") > 0)),
        ("edge>=10pp, EV>0", (pl.col("edge") >= 0.10) & (pl.col("ev") > 0)),
    ]:
        sel = df.filter(flt)
        if sel.height == 0:
            print(f"{lbl:32s} {0:>6}")
            continue
        lo, hi, roi, conc = _clustered_roi(sel)
        verdict = "indistinguishable from zero" if lo <= 0 <= hi else (
            "positive" if lo > 0 else "negative")
        print(f"{lbl:32s} {sel.height:6d} "
              f"{sel['scored'].mean():6.1%} {roi:7.1f}% "
              f"[{lo:+7.1f}%, {hi:+7.1f}%]  {verdict}")
        if conc is not None and conc > 0.5:
            print(f"{'':32s} {'':>6} top 10 winners are {conc:.0%} of the profit "
                  f"— this is a handful of results, not a rate")

    # Tagged with the model that produced it. The app lets you switch models,
    # and an untagged file meant the Betting reality tab kept quoting whichever
    # model happened to run last while the board scored with the one you had
    # selected — two different models described as one.
    out_dir = get_path("output", target_type)
    out = out_dir / f"backtest_{model_name}_{season}.csv"
    df.write_csv(out)
    print(f"\nSaved per-bet detail: {out}")

    # Untagged copy for the production model, so anything still globbing
    # backtest_<season>.csv keeps working.
    if model_name == production_model(target_type):
        legacy = out_dir / f"backtest_{season}.csv"
        df.write_csv(legacy)
        print(f"Also wrote production copy: {legacy}")
    return 0


if __name__ == "__main__":
    cfg = get_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=cfg["splits"]["test_season"])
    ap.add_argument("--target", default=cfg["target"]["type"])
    # Resolved after parsing: the right model depends on --target.
    ap.add_argument("--model", default=None)
    ap.add_argument("--walk-forward", action="store_true",
                    help="Retrain on earlier seasons before scoring this one. "
                         "Required for any season at or before splits.train_end, "
                         "which the model was fitted on.")
    a = ap.parse_args()
    if a.model is None:
        from src.utils.config import production_model
        a.model = production_model(a.target)
    sys.exit(main(a.season, a.target, a.model, a.walk_forward))
