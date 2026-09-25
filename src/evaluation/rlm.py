"""Reverse line movement: the line moved against the side the money is on.

The public-money angle without a public-money feed. "94% of spread tickets are
on the Eagles -7" is not derivable here — The Odds API does not sell bet
percentages and the services that do are scraped rather than licensed — but the
thing that angle is reaching for is: when a line moves TOWARD the unpopular
side, somebody with a strong opinion is pushing it, and tickets are not what
moves a number.

What is derivable is the move itself, from the open and close this project now
archives. A side is "reverse" when the market moved away from it while it was
the side you would expect tickets on — the favorite, or the over. That is a
proxy and it is stated as one: without ticket counts the popular side has to be
assumed rather than observed, and the assumption is only usually right.

**Every number this module returns carries its n.** A pattern measured on six
games looks like a system and is a coin flip: P(1 or fewer of 6 | fair coin) is
10.9%. Anything that reports a hit rate without the sample size behind it
manufactures exactly the belief this project spends its test suite guarding
against, and a bets page built on that would do it at scale.

Break-even at -110 is 52.38%. A rule that does not clear it with its interval
is not a rule, and `evaluate` says so in those words rather than leaving the
reader to do it.
"""
from __future__ import annotations

import math

import polars as pl

#: How far a line has to move before it counts as a move at all. Below this it
#: is book noise and rounding, not a market forming an opinion.
MIN_MOVE_PP = 1.0

#: Break-even at -110, which is what a SPREAD or TOTAL is quoted at. It is the
#: wrong yardstick for a moneyline and that mistake is easy to make: the first
#: version of `evaluate` compared every definition to it and reported "moneyline
#: moved toward this side" as clearing at 62.3%. Those sides are favorites
#: priced at 56.8% — beating a coin flip is not beating THEM. Every definition
#: is now scored against the price it would actually be taken at, and this
#: constant survives only to label the spread and total markets.
BREAK_EVEN = 0.5238


def _wilson(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson interval — not normal approximation.

    At the sample sizes a betting system actually has, the textbook interval
    goes out of bounds and understates the width. Wilson stays inside [0, 1]
    and is honest at n = 20, which is where these live.
    """
    if n == 0:
        return (0.0, 1.0)
    p = hits / n
    d = 1 + z * z / n
    center = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, center - half), min(1.0, center + half))


def moves(seasons: list[int] | None = None) -> pl.DataFrame:
    """Open-to-close movement per game and market, joined to the outcome.

    One row per (game, market, side). `move_pp` is signed in that side's
    favor: positive means the market came toward it.
    """
    from src.ingest.game_lines import LINES_PATH

    if not LINES_PATH.exists():
        return pl.DataFrame()
    d = pl.read_parquet(LINES_PATH)
    if seasons:
        d = d.filter(pl.col("season").is_in(seasons))
    if d.is_empty():
        return pl.DataFrame()

    ends = {}
    for snap in ("open", "close"):
        s = d.filter(pl.col("snapshot") == snap)
        if s.is_empty():
            return pl.DataFrame()
        ends[snap] = (s.sort("captured_at")
                      .unique(subset=["season", "week", "game_id", "market",
                                      "outcome", "point", "bookmaker"],
                              keep="last")
                      .group_by(["season", "week", "game_id", "market",
                                 "outcome", "point"])
                      .agg([pl.col("implied_prob").median().alias(f"{snap}_prob"),
                            pl.len().alias(f"{snap}_books")]))

    # `nulls_equal`: `point` is null on every moneyline and a polars join drops
    # null keys, which would silently remove the whole h2h market.
    j = ends["open"].join(ends["close"],
                          on=["season", "week", "game_id", "market", "outcome",
                              "point"], how="inner", nulls_equal=True)
    return j.with_columns(
        ((pl.col("close_prob") - pl.col("open_prob")) * 100).alias("move_pp"))


def graded(seasons: list[int] | None = None) -> pl.DataFrame:
    """Movement with the result attached: did that side win?

    Totals grade on the game's own total against the line. Spreads grade the
    named team against its own number. Moneyline grades on who won. Pushes are
    dropped — a push is not a bet that lost, and counting it as one drags every
    hit rate down by however often lines land on the number.
    """
    from src.utils.paths import get_path

    mv = moves(seasons)
    if mv.is_empty():
        return mv

    s = (pl.read_parquet(get_path("raw") / "schedules.parquet")
         .filter(pl.col("game_type") == "REG")
         .select(["season", "week", "home_team", "away_team",
                  "home_score", "away_score"])
         .drop_nulls(["home_score", "away_score"])
         .with_columns((pl.col("away_team") + "_" + pl.col("home_team"))
                       .alias("game_id")))
    j = mv.join(s.select(["game_id", "season", "week", "home_team",
                          "home_score", "away_score"]),
                on=["season", "week", "game_id"], how="inner")
    if j.is_empty():
        return j

    margin = pl.col("home_score") - pl.col("away_score")
    is_home = pl.col("outcome") == pl.col("home_team")
    total = pl.col("home_score") + pl.col("away_score")

    # Signed so that "won" means the side named by `outcome` won its bet.
    won = (pl.when(pl.col("market") == "h2h")
             .then(pl.when(is_home).then(margin > 0).otherwise(margin < 0))
           .when(pl.col("market") == "spreads")
             .then(pl.when(is_home)
                     .then(margin + pl.col("point") > 0)
                     .otherwise(-margin + pl.col("point") > 0))
           .when(pl.col("market") == "totals")
             .then(pl.when(pl.col("outcome") == "Over")
                     .then(total > pl.col("point"))
                     .otherwise(total < pl.col("point")))
           .otherwise(None))
    push = (pl.when(pl.col("market") == "spreads")
              .then(pl.when(is_home).then(margin + pl.col("point") == 0)
                      .otherwise(-margin + pl.col("point") == 0))
            .when(pl.col("market") == "totals")
              .then(total == pl.col("point"))
            .otherwise(margin == 0))
    return (j.with_columns([won.alias("won"), push.alias("push")])
             .filter(~pl.col("push") & pl.col("won").is_not_null()))


def evaluate(seasons: list[int] | None = None,
             min_move: float = MIN_MOVE_PP) -> list[dict]:
    """Every definition, scored against the price it would be taken at.

    **Not against a flat break-even.** A rule that selects favorites wins more
    than half by construction, and comparing that to 52.38% reports an edge
    where there is none. What matters is the hit rate against the CLOSING
    implied probability of the very sides selected: win 58.9% of bets priced at
    56.8% and you have something; win 58.9% of bets priced at 62% and you are
    losing while your hit rate looks excellent.

    `roi_pct` is the flat-stake return at the median closing price, which is
    conservative — nobody can bet a median, and the best book beats it by about
    1.2pp on a moneyline. The interval on the hit rate is Wilson; a definition
    whose LOWER bound sits under its own implied price is reported as not
    clearing, which is nearly all of them at these sample sizes.
    """
    g = graded(seasons)
    if g.is_empty():
        return []

    out = []
    defs = [
        ("market moved toward this side", pl.col("move_pp") >= min_move),
        ("market moved away from this side", pl.col("move_pp") <= -min_move),
        ("market moved toward the over", (pl.col("market") == "totals")
         & (pl.col("outcome") == "Over") & (pl.col("move_pp") >= min_move)),
        ("market moved toward the under", (pl.col("market") == "totals")
         & (pl.col("outcome") == "Under") & (pl.col("move_pp") >= min_move)),
        ("moneyline moved toward this side", (pl.col("market") == "h2h")
         & (pl.col("move_pp") >= min_move)),
        ("spread moved toward this side", (pl.col("market") == "spreads")
         & (pl.col("move_pp") >= min_move)),
    ]
    for name, expr in defs:
        s = g.filter(expr)
        n = s.height
        if n == 0:
            out.append({"definition": name, "n": 0, "hit_rate": None,
                        "lo": None, "hi": None, "clears": False,
                        "verdict": "no games matched"})
            continue
        hits = int(s["won"].sum())
        lo, hi = _wilson(hits, n)
        rate = hits / n

        # THE VERDICT IS ABOUT MONEY, AND SO IS ITS INTERVAL.
        #
        # An earlier version compared the hit-rate interval to an average
        # break-even and reported two definitions as clearing — one returning
        # +$0.18 per $100 and one LOSING $3.78. Both readings were defensible
        # and neither was useful, because a hit rate cannot be compared to an
        # average price when the prices run from -450 to +381: the same 52%
        # is a fortune on longshots and a catastrophe on favorites.
        #
        # So the unit is the return on one flat stake. Each bet pays `dec - 1`
        # when it wins and -1 when it loses; the definition's edge is the mean
        # of that, and its uncertainty is the ordinary standard error of that
        # mean. "Returns between -9% and +2% per $100" is one statement, in
        # the unit the reader is betting in, and it needs no reconciliation.
        per_bet = (s.with_columns(
            pl.when(pl.col("won")).then(1.0 / pl.col("close_prob") - 1.0)
              .otherwise(-1.0).alias("_r"))["_r"])
        roi = float(per_bet.mean()) * 100
        # Standard error of the mean. Normal rather than Wilson: this is a
        # mean of a bounded-below but unbounded-above quantity, not a
        # proportion, and at n in the hundreds the CLT is the right tool.
        sd = float(per_bet.std(ddof=1)) if n > 1 else 0.0
        se = (sd / (n ** 0.5)) * 100 if n > 1 else 0.0
        roi_lo, roi_hi = roi - 1.96 * se, roi + 1.96 * se

        # Kept as description, never as the verdict: it is what a reader wants
        # to see and cannot be acted on by itself.
        dec_all = 1.0 / s["close_prob"]
        implied = float(1.0 / dec_all.mean())
        won_dec = 1.0 / s.filter(pl.col("won"))["close_prob"]
        mean_dec_won = float(won_dec.mean()) if won_dec.len() else None
        # Beating the average break-even while losing money means the bets it
        # wins are priced shorter than the ones it loses. That is a fact about
        # the definition, so it is surfaced rather than reconciled away.
        price_bias = (rate > implied) != (roi > 0)

        clears = roi_lo > 0
        loses = roi_hi < 0
        if clears:
            verdict = f"returns {roi_lo:+.1f}% to {roi_hi:+.1f}% per $100"
        elif loses:
            verdict = (f"loses money at every plausible rate "
                       f"({roi_lo:+.1f}% to {roi_hi:+.1f}% per $100)")
        else:
            verdict = (f"not measurably different from break-even "
                       f"({roi_lo:+.1f}% to {roi_hi:+.1f}% per $100)")
        out.append({
            "definition": name, "n": n, "hits": hits, "hit_rate": rate,
            "lo": lo, "hi": hi, "implied": implied,
            "roi_pct": roi, "roi_lo": roi_lo, "roi_hi": roi_hi,
            "clears": clears, "loses": loses, "verdict": verdict,
            "price_bias": price_bias, "mean_dec_won": mean_dec_won,
            "mean_dec_all": float(dec_all.mean()),
        })
    return out
