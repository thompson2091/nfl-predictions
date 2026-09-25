"""The fade, expressed as a bet a sportsbook will actually take.

The largest measured edge in this project is the touchdown fade: inside the
band, players rated well under the book's number score far less often than
priced. It is unbettable. No book posts the No side of a touchdown prop, and
`lay_sheet` exists because collecting it means an exchange and an order book
that may not be there.

A yardage line HAS a posted under. This measures whether the same view
expresses there, and it does — but only once the question is asked in a form
that can be answered before kickoff.

**THE FIRST TWO ANSWERS WERE BOTH WRONG, IN OPPOSITE DIRECTIONS.**

Taken raw, the fade group went under 58.5% against a 52.4% baseline. That was
scratches: 4.6% of priced players recorded zero targets, 99.6% of those went
under, and they cluster among heavy fades because a model rating someone far
below his price is often reading the same thin usage that gets him ruled out.

Removing them by filtering on `targets` or `carries` replaced a scratch
artifact with a look-ahead one. Nobody knows at bet time how many times a man
will touch the ball. Conditioning on it is not a rate anyone can bet, and it
is enormous: on rushing, 1-2 actual carries goes under 72% of the time and 16+
goes under 24%. The under was reading how much he played, not who he is.

**THE ANSWER IS TO CONDITION ON PROJECTED USAGE, WHICH IS KNOWN IN ADVANCE.**

`player_targets_avg_3g` and `player_carries_avg_3g` are lagged rolling means —
already features of the touchdown model, already computed as of the week being
priced. Substituting them for the post-game counts makes the measurement
placeable, and the substitution is not cosmetic: the actual-usage gradient runs
100% to 24% across bands, the projection of that same gradient runs 61% to 53%.
Usage is far less predictable than it is decisive, which is exactly why the
look-ahead version looked so good.

What survives is smaller, real, and stronger where the player plays more:

    fade <= -8pp, projected usage >= 3      n     under      95% interval
      receiving_yards                      784    60.5%     [57.0, 63.8]
      receptions                           777    61.9%     [58.4, 65.3]
      rushing_yards                        736    59.2%     [55.6, 62.7]

Break-even at -110 is 52.38%, so all three clear on the lower bound. Per
season, receiving yards runs 61.3 / 59.2 / 60.8 and receptions 61.0 / 61.9 /
63.3 across 2023-2025; rushing clears in two of the three. The effect grows
with the cut (-12pp reaches 63.0% on rushing) and with projected usage, which
is the opposite of the scratch artifact's shape and is the reason to believe
it: a signal driven by non-participation would fade as the workload rises.

Restricted instead to projected usage BELOW 3, the fade adds nothing — 56.7%
at -5pp against a 57.0% baseline. The thin-usage rows carry a high under rate
no matter what the model thinks, and the model's opinion is only worth money
on players who are going to be on the field.

**One line per player-week, and it is the BALANCED line.** See `board`: the
earlier rule took the most-quoted point, which sounds right and was picking
near-randomly across a seven-yard span.
"""
from __future__ import annotations

import math
from pathlib import Path

import polars as pl

#: Markets with a posted under and a stat to settle it against.
MARKETS = {"receiving_yards": "receiving_yards",
           "receptions": "receptions",
           "rushing_yards": "rushing_yards"}

#: How far below the book a touchdown rating has to sit to count as a fade.
#: The touchdown shortlist's own veto threshold is smaller; these are wider
#: because the question is whether a STRONG disagreement carries across.
CUTS = (-5.0, -8.0, -12.0)

#: Break-even at -110, which is what a yardage line is quoted at.
BREAK_EVEN = 0.5238

#: Where the lagged usage means live. These are FEATURES of the touchdown
#: model, built with `shift(1)` over prior weeks, so reading them here adds no
#: information the pricing model did not already have.
PROJ_PATH = "data/processed/anytime_td/features.parquet"

#: Projected touches below which the fade stops being worth anything. Not a
#: fitted threshold — the bands are flat enough that anything from 3 to 6
#: reads the same, and 3 keeps the sample. See the module docstring.
MIN_PROJECTED_USAGE = 3.0


def _wilson(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = hits / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - half), min(1.0, c + half))


def board(market: str = "receiving_yards") -> pl.DataFrame:
    """Every archived line for a player the touchdown model also rated.

    One row per player-week: the main line, the touchdown edge, the result,
    and whether he was involved at all.
    """
    import pandas as pd

    from src.evaluation.combo_backtest import _season, backtest_files
    from src.features.odds_features import _normalize_name
    from src.ingest.odds_history import (HISTORY_PATH, SCHEMA, _conform,
                                         drop_in_play)
    from src.utils.paths import get_path

    stat = MARKETS[market]
    frames = []
    for path in backtest_files("anytime_td", "xgb"):
        d = pd.read_csv(path)
        d = d.dropna(subset=["market_prob", "prob_calibrated", "player_name",
                             "week"])
        if "has_market_price" in d.columns:
            d = d[d["has_market_price"].astype(bool)]
        d["season"] = _season(path)
        frames.append(d[["season", "week", "player_name", "prob_calibrated",
                         "market_prob"]])
    if not frames:
        return pl.DataFrame()
    td = pl.from_pandas(pd.concat(frames, ignore_index=True))
    # The backtest files hold a handful of player-games priced twice — same
    # player, same game, same model number, two archived prices (De'Von Achane
    # at +155 and +230 in one week). 25 of 6,949, but each becomes two rows on
    # the join and two bets on one line. Collapsed to the median price, which
    # is how every other surface here treats more than one book.
    td = (td.group_by(["season", "week", "player_name"])
            .agg([pl.col("prob_calibrated").median(),
                  pl.col("market_prob").median()]))
    td = td.with_columns(
        ((pl.col("prob_calibrated") - pl.col("market_prob")) * 100)
        .alias("td_edge_pp"))
    td = td.with_columns(pl.col("player_name")
                         .map_elements(_normalize_name, return_dtype=pl.Utf8)
                         .alias("pn"))

    h = _conform(pl.read_parquet(HISTORY_PATH), SCHEMA)
    h = h.filter((pl.col("market") == market) & pl.col("point").is_not_null()
                 & (pl.col("snapshot") == "close"))
    # THE MAIN LINE IS THE BALANCED ONE, NOT THE MOST-QUOTED ONE.
    #
    # This selected the point the most books quoted, which sounds right and is
    # not: 94% of archived points are quoted by exactly ONE book, so 88.4% of
    # player-weeks had every candidate tied at one, and `unique(keep="first")`
    # over a parallel group-by broke the tie by whichever row the engine
    # emitted first. The tied points span a median of SEVEN YARDS, so the
    # "main line" was a near-random draw from a player's alternate ladder, and
    # the same code gave different answers on consecutive runs — 59.0% one
    # time and 55.5% the next on the same cell.
    #
    # A yardage prop's primary line is the one priced closest to even money;
    # the alternates fan out from it at longer and shorter odds. So the point
    # is chosen by minimising the mean distance of its prices from 0.5. That
    # leaves 6.6% still tied, broken on `point` so the result is reproducible.
    # The chosen lines sit at a median |p - 0.5| of 0.024, which is -110.
    main = (drop_in_play(h)
            .with_columns((pl.col("implied_prob") - 0.5).abs().alias("_off"))
            .group_by(["season", "week", "player_name_norm", "point"])
            .agg(pl.col("_off").mean().alias("balance"))
            .sort(["season", "week", "player_name_norm", "balance", "point"])
            .unique(subset=["season", "week", "player_name_norm"], keep="first")
            .rename({"player_name_norm": "pn"}))

    usage = "targets" if market != "rushing_yards" else "carries"
    cols = ["season", "week", "player_display_name", stat]
    ws = pl.scan_parquet(get_path("raw") / "weekly_stats.parquet")
    have = ws.collect_schema().names()
    if usage in have:
        cols.append(usage)
    ws = ws.select(cols).collect().with_columns(
        pl.col("player_display_name")
        .map_elements(_normalize_name, return_dtype=pl.Utf8).alias("pn"))
    # Two men can share a name in one week — there are two DJ Turners, and one
    # of them caught 28 yards while the other caught none. Joined on the name
    # they BOTH attach to the same line, and whichever the model rated gets
    # graded twice, once against the other's stat line. Dropped rather than
    # guessed: a wrong result is worse than a missing one, because only the
    # missing one is visible.
    dupes = (ws.group_by(["season", "week", "pn"]).agg(pl.len().alias("_n"))
             .filter(pl.col("_n") > 1).select(["season", "week", "pn"]))
    if dupes.height:
        ws = ws.join(dupes, on=["season", "week", "pn"], how="anti")

    j = (td.join(main.select(["season", "week", "pn", "point"]),
                 on=["season", "week", "pn"], how="inner")
           .join(ws.drop("player_display_name"),
                 on=["season", "week", "pn"], how="inner")
           .drop_nulls([stat, "point"]))
    # A push is not a bet that lost.
    j = j.filter(pl.col(stat) != pl.col("point"))
    j = j.with_columns([
        (pl.col(stat) < pl.col("point")).alias("under"),
        (pl.col(usage).fill_null(0) > 0).alias("played")
        if usage in j.columns else pl.lit(True).alias("played"),
    ])
    return _attach_projection(j, usage)


def _attach_projection(j: pl.DataFrame, usage: str) -> pl.DataFrame:
    """Add `proj_usage`: the lagged three-game mean of touches.

    The whole point of the module. `usage` here is the POST-GAME count and
    must never be filtered on; `proj_usage` is what was knowable on the
    Saturday. Null for a player with no prior three games, which is a real
    category (debuts, returns) and is left null rather than zero-filled so a
    caller has to decide what to do with it.
    """
    from src.features.odds_features import _normalize_name

    col = f"player_{usage}_avg_3g"
    path = Path(PROJ_PATH)
    if not path.exists():
        return j.with_columns(pl.lit(None, dtype=pl.Float64).alias("proj_usage"))
    f = (pl.scan_parquet(path).select(["season", "week", "player_name", col])
         .collect()
         .with_columns(pl.col("player_name")
                       .map_elements(_normalize_name, return_dtype=pl.Utf8)
                       .alias("pn"))
         .drop("player_name")
         # One row per key: the feature frame carries a player once per
         # candidate market, and the lagged mean is identical across them.
         .group_by(["season", "week", "pn"])
         .agg(pl.col(col).median().alias("proj_usage")))
    return j.join(f, on=["season", "week", "pn"], how="left")


def evaluate(market: str = "receiving_yards") -> list[dict]:
    """Under rate by touchdown-fade size, with and without the scratches.

    Both, always. The version that keeps them is the one that looks like an
    edge, and the difference between the two IS the finding.
    """
    b = board(market)
    if b.is_empty():
        return []
    out = []
    for played_only in (False, True):
        s = b.filter(pl.col("played")) if played_only else b
        for cut in (None,) + CUTS:
            sel = s if cut is None else s.filter(pl.col("td_edge_pp") <= cut)
            n = sel.height
            if n < 50:
                continue
            hits = int(sel["under"].sum())
            lo, hi = _wilson(hits, n)
            out.append({
                "market": market, "played_only": played_only, "cut": cut,
                "n": n, "under_rate": hits / n, "lo": lo, "hi": hi,
                "clears": lo > BREAK_EVEN,
            })
    return out


def evaluate_projected(market: str = "receiving_yards",
                       min_usage: float = MIN_PROJECTED_USAGE) -> list[dict]:
    """Under rate by fade size, among players PROJECTED to be involved.

    The bettable form of `evaluate`. Everything here is knowable on the
    Saturday: the touchdown model's disagreement with the book, and a lagged
    three-game mean of touches. Nothing conditions on what happened.

    Rows with no projection are DROPPED rather than kept or zero-filled. A
    player with no prior three games is genuinely unpriceable by this rule,
    and both of the alternatives smuggle in an assumption — keeping them
    treats "unknown" as "involved", zero-filling treats it as "scratch".
    """
    b = board(market)
    if b.is_empty():
        return []
    b = b.filter(pl.col("proj_usage").is_not_null()
                 & (pl.col("proj_usage") >= min_usage))
    out = []
    for cut in (None,) + CUTS:
        sel = b if cut is None else b.filter(pl.col("td_edge_pp") <= cut)
        n = sel.height
        if n < 50:
            continue
        hits = int(sel["under"].sum())
        lo, hi = _wilson(hits, n)
        out.append({"market": market, "min_usage": min_usage, "cut": cut,
                    "n": n, "under_rate": hits / n, "lo": lo, "hi": hi,
                    "clears": lo > BREAK_EVEN})
    return out


def usage_gradient(market: str = "receiving_yards") -> list[dict]:
    """Under rate by usage band, projected against actual, side by side.

    Kept as a permanent exhibit rather than a one-off check. The two columns
    are the whole argument of this module: they are the same quantity, one
    known before kickoff and one after, and they disagree so violently
    (100% to 24% versus 61% to 53%) that any result conditioned on the wrong
    one is measuring the schedule rather than the market.
    """
    b = board(market)
    if b.is_empty():
        return []
    actual = "carries" if market == "rushing_yards" else "targets"
    out = []
    for lo_, hi_ in ((0, 1), (1, 3), (3, 6), (6, 11), (11, 16), (16, None)):
        row = {"band": f"{lo_}-{hi_ - 1}" if hi_ else f"{lo_}+"}
        for label, col in (("proj", "proj_usage"), ("actual", actual)):
            if col not in b.columns:
                continue
            m = pl.col(col).is_not_null() & (pl.col(col) >= lo_)
            if hi_ is not None:
                m = m & (pl.col(col) < hi_)
            sel = b.filter(m)
            row[f"{label}_n"] = sel.height
            row[f"{label}_under"] = (float(sel["under"].mean())
                                     if sel.height else None)
        out.append(row)
    return out
