#!/usr/bin/env python3
"""Log a bet you actually placed, and grade the ones that have settled.

    # after placing it, with the price you were actually given
    python scripts/15_wager.py add --season 2026 --week 1 \
        --player "Blake Corum" --game 2026_01_SF_LA --odds 125 --stake 1 \
        --book draftkings

    # any time — settled bets get outcomes, unsettled ones wait
    python scripts/15_wager.py report

The board's numbers come from a replay that assumed closing consensus prices in
unlimited size. This is the only thing in the project that measures what those
assumptions cost. Log every bet, including the ones you regret — a log that only
contains bets worth remembering measures nothing.
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from src.betting import wagers
from src.utils.config import get_config


def _lookup(season: int, week: int, target: str, player: str) -> dict:
    """Pull what the model thought, so it is stored as of the bet, not later."""
    import polars as pl
    from src.prediction.bets import board_for_week
    from src.utils.config import production_model

    try:
        board, _ = board_for_week(season, week, target, production_model(target))
    except Exception:
        return {}
    if board is None or board.height == 0:
        return {}
    if "prob_model" in board.columns:
        board = board.with_columns(
            pl.col("prob_model").rank(descending=True, method="ordinal")
            .over("game_id").alias("bet_rank"))
    hit = board.filter(pl.col("player_name").str.to_lowercase()
                       .str.contains(player.lower(), literal=True))
    if hit.height == 0:
        return {}
    r = hit.row(0, named=True)
    return {
        "game_id": r.get("game_id"),
        "model_prob": r.get("prob_model", r.get("probability")),
        "market_prob": r.get("market_prob"),
        "bet_rank": r.get("bet_rank"),
        "consensus_odds": r.get("odds"),
    }


def add(a) -> int:
    found = _lookup(a.season, a.week, a.target, a.player)
    if not found and not a.game:
        print(f"Could not find '{a.player}' on the {a.season} week {a.week} "
              f"board, and no --game given. Pass --game to log it anyway.")
        return 1
    wagers.record(
        season=a.season, week=a.week,
        game_id=a.game or found.get("game_id"),
        player_name=a.player, odds_taken=a.odds, stake=a.stake,
        market=a.target, book=a.book,
        model_prob=found.get("model_prob"), market_prob=found.get("market_prob"),
        bet_rank=found.get("bet_rank"),
        consensus_odds=a.consensus or found.get("consensus_odds"),
        note=a.note,
    )
    edge = ""
    if found.get("model_prob") is not None and found.get("market_prob") is not None:
        edge = (f"  model {found['model_prob']:.1%} vs book "
                f"{found['market_prob']:.1%} "
                f"({(found['model_prob'] - found['market_prob']) * 100:+.1f} pts)")
    shop = ""
    con = a.consensus or found.get("consensus_odds")
    if con is not None:
        shop = f"  consensus was {con:+d}"
    print(f"Logged: {a.player} {a.odds:+d} for {a.stake:g} "
          f"at {a.book or 'unnamed book'}{shop}{edge}")
    return 0


def report(a) -> int:
    s = wagers.summary(a.target)
    if s is None:
        print("No wagers logged yet.")
        return 0

    print(f"\n{'=' * 62}\nWAGER LOG — {s['target_type']}\n{'=' * 62}")
    print(f"  placed {s['n_placed']}   settled {s['n_settled']}")
    if s.get("n_settled"):
        print(f"  staked {s['staked']:.2f}   profit {s['profit']:+.2f}   "
              f"ROI {s['roi']:+.1f}%   hit {s['hit_pct']:.0f}%")
    if s.get("n_shopped"):
        print(f"\n  Line shopping: {s['line_shopping_pp']:+.2f} pts on "
              f"{s['n_shopped']} bets")
        print("    Price you got vs the consensus we modeled against. Positive "
              "means\n    you beat it, and every backtest figure is that much "
              "conservative.")
    if s.get("n_clv"):
        print(f"\n  Closing line value: {s['clv_pp']:+.2f} pts on {s['n_clv']} "
              f"bets, beat the close {s['clv_beat_close_pct']:.0f}% of the time")
        print("    Whether the market moved your way after you bet. The one "
              "measure\n    that does not depend on who scored.")

    if s["n_settled"] < 100:
        print(f"\n  {s['n_settled']} settled bets is far too few to judge a "
              f"12% edge — expect\n  a whole season before the ROI here means "
              f"anything. The two gaps\n  above stabilise much sooner.")
    print()
    return 0


if __name__ == "__main__":
    cfg = get_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=cfg["target"]["type"])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="log a bet you placed")
    p.add_argument("--season", type=int, required=True)
    p.add_argument("--week", type=int, required=True)
    p.add_argument("--player", required=True)
    p.add_argument("--odds", type=int, required=True,
                   help="American price you were ACTUALLY given, not the board's")
    p.add_argument("--stake", type=float, required=True)
    p.add_argument("--game", help="game_id; looked up from the board if omitted")
    p.add_argument("--book", help="which sportsbook")
    p.add_argument("--consensus", type=int,
                   help="consensus price at the time, if you know it")
    p.add_argument("--note")
    p.set_defaults(fn=add)

    r = sub.add_parser("report", help="grade settled bets and show the gaps")
    r.set_defaults(fn=report)

    args = ap.parse_args()
    sys.exit(args.fn(args))
