#!/usr/bin/env python3
"""Train and honestly grade the receptions count model.

The third target type, and a different shape from the two before it: a count,
graded per (player, line) rather than per player, in the lowest-hold market on
the board (~7% overround against anytime TD's ~23%, measured on our own
archive). One model prices every line — see src/models/count.py for why a
classifier per line is the wrong tool.

What this script deliberately is NOT: a claim of betting edge. The first
version of this model beat the receptions market by +17-22% ROI, which is how
the NGS existence leak was found — the edge was the leak. On clean features it
does not beat the market, and the summary this writes says so in numbers
rather than leaving the reader to infer it.

    python scripts/30_receptions.py            # train + backtest + artifacts
    python scripts/30_receptions.py --skip-train   # re-grade existing model
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

sys.path.insert(0, ".")

import numpy as np
import polars as pl

from src.models.count import (XGBCountModel, blend_to_market, design_matrix,
                             fair_two_way, fit_market_blend, prob_over)
from src.utils.config import get_config
from src.utils.paths import get_path

#: Identifier columns of the shared feature matrix; everything else numeric is
#: a feature. The matrix is REUSED from anytime_td rather than rebuilt — the
#: candidate pool (who is on a roster this week) and the features (usage,
#: matchup, pace) answer the receptions question as directly as the touchdown
#: one, and a second copy of an 80MB matrix would only drift from the first.
ID_COLS = {"game_id", "season", "week", "home_team", "away_team", "game_type",
           "player_id", "player_name", "team", "target", "receptions",
           # Context for the board and the input to `fit_shrinkage`, not a
           # model feature — see the matching note in `trainer.get_feature_cols`.
           # Left in, it silently makes the served model a 370-feature model.
           "player_games_observed"}


def _frame() -> tuple[pl.DataFrame, list[str]]:
    from src.models.prop_frame import feature_cols, labeled

    feats = pl.read_parquet(get_path("processed", "anytime_td") / "features.parquet")
    # The label requires that he played — whether he plays is not knowable
    # before kickoff — but playing with no catch is a zero, not a gap.
    df = labeled(feats, "receptions")
    return df, feature_cols(df, ID_COLS)


def train(df: pl.DataFrame, fcols: list[str]) -> XGBCountModel:
    cfg = get_config()
    tr = df.filter(pl.col("season") <= cfg["splits"]["train_end"])
    va = df.filter(pl.col("season") == cfg["splits"]["val_season"])

    def XY(d):
        # `design_matrix`, not a bare `to_numpy`, so training and the weekly
        # board build the matrix from one definition. See src/models/count.py.
        return design_matrix(d, fcols), d["receptions"].to_numpy().astype(float)

    Xtr, ytr = XY(tr)
    Xva, yva = XY(va)
    m = XGBCountModel()
    m.feature_names = fcols
    m.fit(Xtr, ytr, Xva, yva,
          get_config().get("model", {}).get("xgb_count", {}) | {"seed": get_config()["model"]["seed"]})
    print(f"Trained on {tr.height:,} rows (<= {cfg['splits']['train_end']}), "
          f"dispersion fitted on {va.height:,} ({cfg['splits']['val_season']}): "
          f"r = {m.dispersion}")
    return m


def graded_lines(season: int) -> pl.DataFrame | None:
    """Archived closing lines joined to what the player actually caught."""
    from src.ingest.odds_history import HISTORY_PATH, SCHEMA, _conform, _resolve_player_id

    if not HISTORY_PATH.exists():
        return None
    h = _conform(pl.read_parquet(HISTORY_PATH), SCHEMA).filter(
        (pl.col("market") == "receptions") & (pl.col("snapshot") == "close")
        & (pl.col("season") == season) & pl.col("point").is_not_null())
    if h.height == 0:
        return None
    # Prices quoted after kickoff out first: every dedupe here keeps the
    # newest capture, which selects them (see odds_history.drop_in_play).
    # This backtest never had the filter the yardage one does.
    from src.ingest.odds_history import drop_in_play
    from src.models.prop_frame import outcomes
    h = drop_in_play(h)
    if h.height == 0:
        return None
    h = h.with_columns(_resolve_player_id(h)).filter(pl.col("player_id").is_not_null())
    # Settled as a book settles: a snap with no catch is 0, not a missing row.
    ws = outcomes("receptions").with_columns(
        pl.col("season").cast(h["season"].dtype), pl.col("week").cast(h["week"].dtype))
    # fair_prob is null where only one side was posted; a market comparison
    # over rows where the market has no de-vigged number would be NaN, which
    # is how the 2025 column first printed as `nan` and read as a broken model
    # rather than a thin book.
    return h.join(ws, on=["season", "week", "player_id"], how="inner").filter(
        pl.col("receptions").is_not_null() & pl.col("fair_prob").is_not_null())


def fit_blend(m: XGBCountModel, df: pl.DataFrame, fcols: list[str],
              season: int, model_dir) -> dict | None:
    """Fit how far to shrink our number toward the book's, on one season.

    Fitted on validation and never on test, for the same reason the dispersion
    is: it is a claim about how much we add to a price, and fitting it where
    the trees have already been is a claim about memorisation.

    Nothing else in this script moved the model. Game context from the closing
    spread and total, and a dispersion fitted per band of predicted mean, were
    both measured and both made 2025 very slightly worse — see
    `scripts/48_receptions_lab.py`. The blend is the only change that helped,
    and it helped by using the market rather than by improving us.
    """
    lines = graded_lines(season)
    if lines is None or lines.height == 0:
        return None
    te = df.filter(pl.col("season") == season)
    mu = m.predict_mu(design_matrix(te, fcols))
    te = te.select(["season", "week", "player_id"]).with_columns(pl.Series("mu", mu))
    j = lines.join(te, on=["season", "week", "player_id"], how="inner")
    if j.height == 0:
        return None
    over, push = prob_over(j["mu"].to_numpy(), j["point"].to_numpy(), m.dispersion)
    p_model = fair_two_way(over, push)
    y_raw, line = j["receptions"].to_numpy(), j["point"].to_numpy()
    ok = y_raw != line
    if ok.sum() < 200:
        return None
    blend = fit_market_blend(p_model[ok], j["fair_prob"].to_numpy()[ok],
                             (y_raw > line).astype(float)[ok])
    blend["fitted_on"] = season
    path = model_dir / "market_blend.json"
    path.write_text(json.dumps(blend, indent=1))
    print(f"Market blend fitted on {season}: keep {blend['weight']:.0%} of our "
          f"number, {1 - blend['weight']:.0%} of the book's "
          f"({blend['n']:,} lines) -> {path}")
    return blend


def backtest(m: XGBCountModel, df: pl.DataFrame, fcols: list[str], season: int,
             blend: dict | None = None) -> dict | None:
    lines = graded_lines(season)
    if lines is None or lines.height == 0:
        print(f"  {season}: no graded lines in the archive")
        return None
    te = df.filter(pl.col("season") == season)
    mu = m.predict_mu(design_matrix(te, fcols))
    te = te.select(["season", "week", "player_id", "game_id"]).with_columns(
        pl.Series("mu", mu))
    j = lines.join(te, on=["season", "week", "player_id"], how="inner")

    over, push = prob_over(j["mu"].to_numpy(), j["point"].to_numpy(), m.dispersion)
    p_model = fair_two_way(over, push)
    y_raw = j["receptions"].to_numpy()
    line = j["point"].to_numpy()
    gradeable = y_raw != line                      # whole-number pushes drop out
    y = (y_raw > line).astype(float)[gradeable]
    pm = p_model[gradeable]
    pk = j["fair_prob"].to_numpy()[gradeable]

    def ll(p):
        q = np.clip(p, 1e-9, 1 - 1e-9)
        return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))

    out_dir = get_path("output", "receptions")
    bt = j.filter(pl.Series(gradeable)).with_columns([
        pl.Series("p_model", pm), pl.Series("y_over", y)])
    bt.select(["season", "week", "game_id", "player_name_raw", "player_id",
               "point", "odds", "implied_prob", "fair_prob", "p_model",
               "receptions", "y_over"]).write_csv(out_dir / f"backtest_{season}.csv")

    res = {
        "season": season, "n": int(len(y)), "pushes": int((~gradeable).sum()),
        "over_rate": float(y.mean()),
        "model": {"log_loss": ll(pm), "brier": float(np.mean((pm - y) ** 2)),
                  "mean_p": float(pm.mean())},
        "market": {"log_loss": ll(pk), "brier": float(np.mean((pk - y) ** 2)),
                   "mean_p": float(pk.mean())},
    }
    if blend:
        pbl = blend_to_market(pm, pk, blend["weight"])
        res["blend"] = {"log_loss": ll(pbl), "brier": float(np.mean((pbl - y) ** 2)),
                        "weight": blend["weight"], "fitted_on": blend.get("fitted_on")}
        res["blend_beats_market"] = res["blend"]["log_loss"] < res["market"]["log_loss"]
    tag = "model better" if res["model"]["log_loss"] < res["market"]["log_loss"] \
        else "MARKET better"
    print(f"  {season}: n={len(y):,}  log loss model {res['model']['log_loss']:.5f} "
          f"vs market {res['market']['log_loss']:.5f}  ({tag})")
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-train", action="store_true",
                    help="Reuse models/receptions/xgb_count.pkl instead of refitting.")
    args = ap.parse_args()

    cfg = get_config()
    df, fcols = _frame()
    print(f"Receptions frame: {df.height:,} labeled rows, {len(fcols)} features")

    model_dir = get_path("models", "receptions")
    model_path = model_dir / "xgb_count.pkl"
    if args.skip_train and model_path.exists():
        m = XGBCountModel.load(model_path)
        print(f"Loaded {model_path} (dispersion r = {m.dispersion})")
    else:
        m = train(df, fcols)
        m.save(model_path)
        print(f"Saved -> {model_path}")

    blend = fit_blend(m, df, fcols, cfg["splits"]["val_season"], model_dir)

    # How much to pull a thin-history projection back toward a debutant's base
    # rate. Fitted every run rather than chosen, and it currently fits to
    # ZERO — measured over 2024-2026 the model is about as accurate on players
    # with <= 3 games as on established ones (bias +0.16 against +0.12), so
    # there is nothing to correct. That is the answer, not a missing fit, and
    # it is written down so a later season that disagrees changes the board on
    # its own. See `src/models/count.py:fit_shrinkage`.
    from src.models.count import fit_shrinkage, position_labels
    va_rows = df.filter(pl.col("season") == cfg["splits"]["val_season"])
    shrink = None
    if va_rows.height and "player_games_observed" in va_rows.columns:
        mu_va = m.predict_mu(design_matrix(va_rows, fcols))
        shrink = fit_shrinkage(
            mu_va, va_rows["receptions"].to_numpy().astype(float),
            va_rows["player_games_observed"].fill_null(0).to_numpy().astype(float),
            position_labels(va_rows),
            seasons_used=[cfg["splits"]["val_season"]])
        (model_dir / "shrinkage.json").write_text(json.dumps(shrink, indent=1))
        print(f"Shrinkage k = {shrink['k_games']} games "
              f"({'no correction' if not shrink['k_games'] else 'applied'}) "
              f"-> {model_dir / 'shrinkage.json'}")

    results = []
    for season in (cfg["splits"]["val_season"], cfg["splits"]["test_season"]):
        r = backtest(m, df, fcols, season, blend)
        if r:
            results.append(r)

    # The SERVED weight, refitted on both backtests just written. The
    # validation-only `blend` above stays what the summary reports.
    from src.evaluation.prop_blend import refit_served
    served = refit_served("receptions")
    if served:
        print(f"Served blend on {served['fitted_on']}: keep "
              f"{served['weight']:.0%} of our number ({served['n']:,} lines)")

    summary = {
        "kind": "receptions_summary",
        "fit_date": date.today().isoformat(),
        "dispersion": m.dispersion,
        "n_features": len(fcols),
        "splits": {k: cfg["splits"][k] for k in ("train_end", "val_season", "test_season")},
        "seasons": results,
        # Stated here so no screen has to infer it: this model does not beat
        # this market. The first version that appeared to (+17-22% ROI) is how
        # the NGS existence leak was found.
        "beats_market": bool(results) and all(
            r["model"]["log_loss"] < r["market"]["log_loss"] for r in results),
        "blend": blend,
        "shrinkage": shrink,
        # The number that is actually served. On its own the model loses to
        # this market; blended toward it, it wins by a little. Both are stated
        # so no screen has to infer which claim is being made.
        "blend_beats_market": bool(results) and all(
            r.get("blend_beats_market") for r in results),
    }
    path = get_path("output", "receptions") / "summary.json"
    path.write_text(json.dumps(summary, indent=1))
    print(f"\nSummary -> {path}")
    print(f"beats_market: {summary['beats_market']}  "
          f"blend_beats_market: {summary['blend_beats_market']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
