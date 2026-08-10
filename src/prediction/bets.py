"""Turn probabilities into bets you can actually place.

A probability is not a bet. A bet needs a price, a positive expectation *at that
price*, and a stake. This module does the last mile:

- You are paid at the **raw** book price, so expected value is computed against
  it. Nothing else would be honest about the payout.
- Your **edge** is measured against the **de-vigged** price, because the vig is
  the book's margin, not a mispricing. On anytime-TD props the overround runs
  ~1.23x; comparing a model number to the raw price manufactures roughly 5
  points of fake edge on every single line.
- Stakes are Kelly, scaled by a fraction set in config. Full Kelly is famously
  correct and famously unusable — it assumes your probabilities are exact, and
  a model that is even slightly overconfident goes broke on full Kelly.

A play only appears if the book prices it. No price, no bet.
"""
from __future__ import annotations

import polars as pl

from src.utils.config import get_config


def american_to_decimal(odds: float) -> float:
    return 1.0 + (odds / 100.0 if odds > 0 else 100.0 / -odds)


def _decimal_expr(col: str) -> pl.Expr:
    return (
        pl.when(pl.col(col) > 0)
        .then(1.0 + pl.col(col) / 100.0)
        .otherwise(1.0 + 100.0 / -pl.col(col))
    )


def build_bet_card(predictions: pl.DataFrame, market: pl.DataFrame,
                   bankroll: float | None = None) -> pl.DataFrame:
    """Join model probabilities to live prices and rank by expected value.

    Args:
        predictions: needs player_name, team, game_label, probability.
        market: needs player_name_norm, game_id, odds (American), fair_prob.
    """
    cfg = get_config()
    bcfg = cfg.get("betting", {})
    kelly_fraction = float(bcfg.get("kelly_fraction", 0.25))
    min_edge = float(bcfg.get("min_edge_pp", 2.0)) / 100.0
    min_ev = float(bcfg.get("min_ev_pct", 0.0)) / 100.0
    if bankroll is None:
        bankroll = float(bcfg.get("bankroll", 1000.0))

    df = predictions.join(market, on=["game_id", "player_name_norm"], how="inner")
    if df.height == 0:
        return df

    df = df.with_columns(_decimal_expr("odds").alias("decimal_odds"))
    df = df.with_columns([
        # Paid at the raw price...
        (pl.col("probability") * (pl.col("decimal_odds") - 1.0)
         - (1.0 - pl.col("probability"))).alias("ev_per_unit"),
        # ...but judged against the vig-free one.
        (pl.col("probability") - pl.col("market_prob")).alias("edge"),
    ])

    # Kelly: f* = (p*b - q) / b, b = decimal odds - 1
    b = pl.col("decimal_odds") - 1.0
    df = df.with_columns(
        (((pl.col("probability") * b) - (1.0 - pl.col("probability"))) / b)
        .clip(lower_bound=0.0)
        .alias("kelly_full")
    )
    df = df.with_columns([
        (pl.col("kelly_full") * kelly_fraction).alias("kelly_stake_frac"),
        (pl.col("kelly_full") * kelly_fraction * bankroll).round(2).alias("stake"),
        (pl.col("ev_per_unit") * 100).round(1).alias("ev_pct"),
        (pl.col("edge") * 100).round(1).alias("edge_pp"),
    ])

    df = df.filter((pl.col("edge") >= min_edge) & (pl.col("ev_per_unit") > min_ev))
    return df.sort("ev_pct", descending=True)


def format_bet_card(card: pl.DataFrame, target_type: str, season: int,
                    week: int, top_n: int = 25) -> str:
    """Human-readable bet card."""
    lines = [
        f"ACTIONABLE BETS — {target_type} — {season} Week {week}",
        "=" * 92,
    ]
    if card.height == 0:
        lines.append("")
        lines.append("No qualifying plays. Either no sportsbook prices are cached")
        lines.append("(run `make odds WEEK=n`), or nothing clears the edge/EV floor")
        lines.append("in config/settings.yaml -> betting.")
        return "\n".join(lines)

    lines.append(
        f"{'Player':22s} {'Team':4s} {'Game':12s} {'Odds':>6s} "
        f"{'Model':>7s} {'Fair':>7s} {'Edge':>7s} {'EV':>7s} {'Stake':>8s}"
    )
    lines.append("-" * 92)
    for r in card.head(top_n).iter_rows(named=True):
        odds = int(r["odds"])
        lines.append(
            f"{r['player_name'][:22]:22s} {str(r['team'])[:4]:4s} "
            f"{str(r['game_label'])[:12]:12s} {odds:+6d} "
            f"{r['probability']*100:6.1f}% {r['market_prob']*100:6.1f}% "
            f"{r['edge_pp']:+6.1f} {r['ev_pct']:+6.1f}% {r['stake']:>8.2f}"
        )
    lines.append("-" * 92)
    tot = card.head(top_n)["stake"].sum()
    lines.append(f"{card.height} qualifying plays; staking {tot:.2f} across the top {min(top_n, card.height)}.")
    lines.append("")
    lines.append("Edge is vs the DE-VIGGED price; EV is at the price you're actually paid.")
    lines.append("Stakes are fractional Kelly — see config/settings.yaml -> betting.")
    return "\n".join(lines)
