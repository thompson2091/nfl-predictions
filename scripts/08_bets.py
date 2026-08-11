#!/usr/bin/env python3
"""Produce an actionable bet card for a given week.

    python scripts/08_bets.py --week 1

Requires cached sportsbook prices (`make odds WEEK=n`) — a play without a price
is not a bet.
"""
import argparse
import sys

sys.path.insert(0, ".")

import polars as pl

from src.prediction.bets import build_bet_card, format_bet_card
from src.prediction.predict import predict, _market_from_cache, _norm_name_expr
from src.models.market_prior import load_prior, expected_scorers
from src.prediction.blend import devig_market
from src.utils.config import get_config
from src.utils.paths import get_path


def main(season: int, week: int, target_type: str, model_name: str) -> int:
    result = predict(season, week, model_name=model_name, target_type=target_type)
    if result is None:
        print("No predictions produced.")
        return 1

    market = _market_from_cache(season, week)
    if market is None or market.height == 0:
        print("\nNo cached sportsbook prices — run `make odds WEEK=%d` first." % week)
        return 1

    # De-vig against the same fitted expectation the model is anchored to.
    model_dir = get_path("models", target_type)
    prior = load_prior(model_dir / "scorer_rate_prior.json")
    feats = pl.read_parquet(get_path("processed", target_type) / "features.parquet")
    wk = feats.filter((pl.col("season") == season) & (pl.col("week") == week))
    games = wk.group_by("game_id").agg([
        pl.col("total_line").first(), pl.col("spread_line").first(),
    ])
    market = devig_market(market, expected_scorers(prior, games))

    preds = result.with_columns(_norm_name_expr("player_name").alias("player_name_norm"))
    card = build_bet_card(preds, market)

    report = format_bet_card(card, target_type, season, week)
    print("\n" + report)

    out_dir = get_path("output", target_type)
    if card.height:
        card.write_csv(out_dir / f"bets_{season}_week{week}.csv")
    (out_dir / f"bets_{season}_week{week}.txt").write_text(report)
    print(f"\nSaved: {out_dir / f'bets_{season}_week{week}.txt'}")
    return 0


if __name__ == "__main__":
    cfg = get_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=cfg["seasons"]["predict_season"])
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--target", default=cfg["target"]["type"])
    # Resolved after parsing: the right model depends on --target.
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    if a.model is None:
        from src.utils.config import production_model
        a.model = production_model(a.target)
    sys.exit(main(a.season, a.week, a.target, a.model))
