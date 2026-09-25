"""The fade, expressed as a bet a sportsbook will actually take.

The largest measured edge in this project is the touchdown fade: inside the
band, players rated well under the book's number score far less often than
priced, +47.7% on 2,205 of them. It is unbettable. No book posts the No side
of a touchdown prop, and `lay_sheet` exists because collecting it means an
exchange and an order book that may not be there.

A yardage line HAS a posted under. If the same view expresses there, the edge
becomes placeable anywhere. This measures whether it does.

**MOST OF THE APPARENT EFFECT IS PLAYERS WHO DID NOT PLAY.** Taken at face
value the fade group goes under 58.5% of the time against a 52.4% baseline,
which reads as a large edge on top of a market that is already tilted. It is
not: 4.6% of priced players recorded ZERO targets, 99.6% of those went under —
a man who does not play goes under everything — and they are over-represented
among heavy fades, because a model rating someone far below his price is
often reading the same thin usage that gets him scratched.

Remove them and the baseline falls to 50.1%, which is what a fair market
should look like and is the number that says the rest of the measurement can
be trusted.

**AND THE CORRECTION IS ITSELF INVALID.** Filtering on targets or carries
conditions on a POST-GAME quantity. Nobody knows at bet time how many times a
man will touch the ball, so a rate measured inside "he saw a target" is not a
rate anyone can bet. It replaced a scratch artifact with a look-ahead one.

How completely usage drives this, on rushing yards:

    carries  1-2    n   846   under 72.0%
    carries  3-5    n 1,021   under 56.0%
    carries  6-10   n 1,101   under 50.3%
    carries 11-15   n   761   under 49.7%
    carries 16+     n   738   under 25.1%

The under is not a view about a player, it is a reading of how much he played.
Restricted to a real workload the baseline goes the other way — 43% unders, so
blind OVERS would win 57% — which is as unbettable as the first number and for
the same reason.

So neither column below is an edge. What they bracket is a real question the
measurement cannot answer as built: the unfiltered number includes scratches,
which the inactives check can partly see in advance; the filtered one uses
information that does not exist yet. The test that would settle it conditions
on PROJECTED usage — which this project has, in the share model — and that is
the version worth building.

For the record, the numbers as measured:

    every line, played          n 9,583   under 50.1%   [49.1, 51.1]
    fade <= -8pp, played        n 1,511   under 53.5%   [51.0, 56.0]
    fade <= -12pp, played       n   729   under 55.7%   [52.1, 59.3]

A 5.6-point lift over the baseline, from a signal fitted for a different
market, on a line the book will take. The interval's lower bound is 52.1%
against a 52.38% break-even, so it does not clear — by a quarter of a point,
on 729 bets.

**One line per player-week, the one the most books quote.** The archive holds
alternates, and counting them all inflates n while correlating every outcome
inside a player-week: the same man going under 40.5, 45.5 and 50.5 yards is
one result, not three. Measured across alternates the sample looks four times
larger and the interval four times tighter than the evidence supports.
"""
from __future__ import annotations

import math

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
    # The main line, not every alternate: the most-quoted point per player-week.
    main = (drop_in_play(h).sort("captured_at")
            .group_by(["season", "week", "player_name_norm", "point"])
            .agg(pl.len().alias("books"))
            .sort(["season", "week", "player_name_norm", "books"],
                  descending=[False, False, False, True])
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
    return j.with_columns([
        (pl.col(stat) < pl.col("point")).alias("under"),
        (pl.col(usage).fill_null(0) > 0).alias("played")
        if usage in j.columns else pl.lit(True).alias("played"),
    ])


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
