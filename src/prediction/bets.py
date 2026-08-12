"""Turn probabilities into bets you can actually place.

A probability is not a bet. A bet needs a price, a positive expectation *at that
price*, and a stake. This module does the last mile:

- You are paid at the **raw** book price, so expected value is computed against
  it. Nothing else would be honest about the payout.
- Your **edge** is measured against the **de-vigged** price, because the vig is
  the book's margin, not a mispricing. On anytime-TD props the overround runs
  ~1.23x; comparing a model number to the raw price manufactures roughly 5
  points of fake edge on every single line.
- EV comes in two bases, for the same reason `edge` and `model_edge` do:
  `ev_per_unit` uses the published (blended) probability, `ev_model_per_unit`
  the pre-blend one. The second is the betting number — see `prob_bet`.
  Both are per unit staked, so the `*_pct` versions are also dollars per $100.
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


def board_for_week(season: int, week: int, target_type: str, model_name: str,
                   bankroll: float | None = None) -> tuple[pl.DataFrame, str]:
    """Every priced player for one week. Returns (board, status message).

    Shared by the CLI (scripts/08_bets.py) and the app so both show exactly the
    same numbers — a bet card that disagrees with itself depending on where you
    read it is worse than no bet card.
    """
    from src.models.market_prior import load_prior, expected_scorers
    from src.prediction.blend import devig_market
    from src.prediction.predict import predict, _market_from_cache, _norm_name_expr
    from src.utils.paths import get_path

    result = predict(season, week, model_name=model_name, target_type=target_type)
    if result is None:
        return pl.DataFrame(), "No predictions for this week — run the pipeline."

    market = _market_from_cache(season, week, target_type)
    if market is None or market.height == 0:
        return pl.DataFrame(), (
            f"No sportsbook prices cached for week {week}. "
            f"Run `make odds WEEK={week}` to fetch them."
        )

    prior = load_prior(get_path("models", target_type) / "scorer_rate_prior.json")
    if prior is None:
        return pl.DataFrame(), "No scorer-rate prior — run `make train`."

    feats = pl.read_parquet(get_path("processed", target_type) / "features.parquet")
    wk = feats.filter((pl.col("season") == season) & (pl.col("week") == week))
    games = wk.group_by("game_id").agg(
        [pl.col("total_line").first(), pl.col("spread_line").first()]
    )
    market = devig_market(market, expected_scorers(prior, games))

    preds = result.with_columns(_norm_name_expr("player_name").alias("player_name_norm"))
    board = build_board(preds, market, bankroll)
    if board.height == 0:
        return board, "No players could be matched to a sportsbook price."
    return board, ""


def build_board(predictions: pl.DataFrame, market: pl.DataFrame,
                bankroll: float | None = None) -> pl.DataFrame:
    """Every priced player, with the same numbers computed for all of them.

    This is the single source the recommended / overvalued / full views all
    filter. Computing the maths once means the three views can never disagree
    about the same player — and it lets you inspect a player we did *not*
    recommend on exactly the same terms as one we did.

    Args:
        predictions: needs player_name, team, game_label, probability.
        market: needs player_name_norm, game_id, odds (American), market_prob.
    """
    cfg = get_config()
    bcfg = cfg.get("betting", {})
    kelly_fraction = float(bcfg.get("kelly_fraction", 0.25))
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

    # Kelly: f* = (p*b - q) / b, b = decimal odds - 1. Clipped at 0 because a
    # negative Kelly means "bet the other side", which these markets don't offer.
    b = pl.col("decimal_odds") - 1.0
    df = df.with_columns(
        (((pl.col("probability") * b) - (1.0 - pl.col("probability"))) / b)
        .clip(lower_bound=0.0)
        .alias("kelly_full")
    )
    # `prob_bet` is the number a *bet* is judged on, as opposed to the number we
    # publish. `probability` has already been pulled toward the price it is
    # being compared against, so a disagreement measured on it comes out about
    # 62% the size of the real one, and shrinks most exactly where the
    # disagreement is largest. Every profitability figure in
    # src/evaluation/rank_economics.py is measured pre-blend, so a betting rule
    # — or an EV — expressed in these terms has to read this column, or the
    # threshold means something different on screen than it did in the backtest.
    # first_td publishes the model number directly and has no pre-blend column;
    # there the two bases coincide and every pair below is equal by definition.
    df = df.with_columns(
        (pl.col("prob_model") if "prob_model" in df.columns
         else pl.col("probability")).alias("prob_bet")
    )
    df = df.with_columns([
        (pl.col("prob_bet") - pl.col("market_prob")).alias("model_edge"),
        # Judged pre-blend, but still paid at the raw price — the two choices are
        # independent, and mixing them up in either direction is what makes a
        # board disagree with its own backtest.
        (pl.col("prob_bet") * b - (1.0 - pl.col("prob_bet")))
        .alias("ev_model_per_unit"),
    ])

    return df.with_columns([
        (pl.col("kelly_full") * kelly_fraction).alias("kelly_stake_frac"),
        (pl.col("kelly_full") * kelly_fraction * bankroll).round(2).alias("stake"),
        # Per unit staked x100. That is a percentage of stake and also dollars
        # per $100 staked, which is how both the CLI card and the app render it.
        (pl.col("ev_per_unit") * 100).round(1).alias("ev_pct"),
        (pl.col("ev_model_per_unit") * 100).round(1).alias("ev_model_pct"),
        (pl.col("edge") * 100).round(1).alias("edge_pp"),
        (pl.col("model_edge") * 100).round(1).alias("model_edge_pp"),
    ]).sort("ev_pct", descending=True)


def build_bet_card(predictions: pl.DataFrame, market: pl.DataFrame,
                   bankroll: float | None = None) -> pl.DataFrame:
    """The recommended plays: we're above the fair price and the EV is positive."""
    cfg = get_config()
    bcfg = cfg.get("betting", {})
    min_edge = float(bcfg.get("min_edge_pp", 2.0)) / 100.0
    min_ev = float(bcfg.get("min_ev_pct", 0.0)) / 100.0

    board = build_board(predictions, market, bankroll)
    if board.height == 0:
        return board
    return board.filter(
        (pl.col("edge") >= min_edge) & (pl.col("ev_per_unit") > min_ev)
    )


def build_fade_card(board: pl.DataFrame) -> pl.DataFrame:
    """Players the market rates far *higher* than we do.

    Carries a stake of 0 by construction. Sportsbooks do not post a "will not
    score" price on these props — measured across a live slate, 0 of 142 quotes
    carried the other side — so there is normally no way to bet against a player.
    This is therefore a "don't back these" list, and a check on our own model: if
    the book is confident and we are not, one of us is wrong, and the book is
    right far more often than we are.
    """
    cfg = get_config()
    min_edge = float(cfg.get("betting", {}).get("min_edge_pp", 2.0)) / 100.0
    if board.height == 0:
        return board
    return board.filter(pl.col("edge") <= -min_edge).sort("edge_pp")


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
