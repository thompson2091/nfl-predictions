#!/usr/bin/env python3
"""Fetch this week's sportsbook TD props, archive them, and rebuild the parquet.

Run this every week the season is live — even weeks you aren't betting. The Odds
API only serves *current* markets, so a week that isn't snapshotted is a week
that can never be used to calibrate the model against the book. The archive is
what `blend.fit_blend_weight` learns from.

    python scripts/07_odds.py --season 2026 --week 1
"""
import argparse
import sys

sys.path.insert(0, ".")

import polars as pl

from src.ingest.odds_api import (DEFAULT_MARKETS, DEFAULT_REGIONS,
                                 fetch_week_td_props, build_odds_parquet,
                                 load_cached_book_quotes)
from src.ingest.odds_history import append_snapshot, append_book_quotes
from src.utils.config import get_config


def _to_rows(odds: dict, markets=DEFAULT_MARKETS) -> pl.DataFrame:
    """Flatten the API payload into one row per player per line per market."""
    from src.features.odds_features import TEAM_ABBREV, _normalize_name

    rows = []
    for game in odds.values():
        home = TEAM_ABBREV.get(game.get("home_team", ""))
        away = TEAM_ABBREV.get(game.get("away_team", ""))
        for market in markets:
            for p in game.get(market, []):
                rows.append({
                    # game_id is resolved against schedules downstream; the
                    # team pair plus date is enough to join on.
                    "game_id": f"{away}_{home}" if home and away else None,
                    "player_name_raw": p["player"],
                    "player_name_norm": _normalize_name(p["player"]),
                    "market": market,
                    # Null for yes/no markets; the line for over/under ones.
                    # Part of the archive's key, so it has to survive the trip.
                    "point": p.get("point"),
                    "odds": p.get("odds"),
                    "implied_prob": p.get("implied_prob"),
                    "fair_prob": p.get("fair_prob"),
                    "n_books": p.get("n_books"),
                    "overround": p.get("overround"),
                })
    return pl.DataFrame(rows) if rows else pl.DataFrame()


if __name__ == "__main__":
    cfg = get_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=cfg["seasons"]["predict_season"])
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--force-refresh", action="store_true")
    ap.add_argument(
        "--snapshot", choices=["open", "close"], default="close",
        help="Which end of the market this fetch is. Run once early in the "
             "week with --snapshot open and again near kickoff with the "
             "default; the pair is what makes closing-line value measurable.",
    )
    ap.add_argument(
        "--markets", nargs="+", default=list(DEFAULT_MARKETS),
        help="Archive market names to fetch (see odds_api.MARKET_SPECS). "
             "Credits are billed per market, so every addition costs money "
             "every week the season is live.",
    )
    ap.add_argument(
        "--regions", default=DEFAULT_REGIONS,
        help="Bookmaker regions, comma separated. Billed markets x regions.",
    )
    args = ap.parse_args()

    markets = tuple(args.markets)
    odds = fetch_week_td_props(force_refresh=args.force_refresh,
                               markets=markets, regions=args.regions)
    if not odds:
        print("No odds returned. Is ODDS_API_KEY set in .env?")
        sys.exit(1)

    print(f"Fetched {len(odds)} games")
    append_snapshot(_to_rows(odds, markets), season=args.season,
                    week=args.week, snapshot=args.snapshot,
                    regions=args.regions)
    # Same response, no extra credits, and unbuyable afterwards.
    append_book_quotes(load_cached_book_quotes(), season=args.season,
                       week=args.week, snapshot=args.snapshot,
                       regions=args.regions)
    build_odds_parquet()
