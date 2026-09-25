"""Separating the money from the tickets, and asking where it went.

**The public split is two numbers, not one.** Tickets count bets; money counts
dollars. A side taking 11% of the bets and 46% of the dollars is a small number
of large ones, and that is the only thing in a public feed with a story behind
it. Atlanta at Green Bay read exactly that on 2026-09-25.

**The raw gap is the wrong statistic and it flatters underdogs.** Money share
minus ticket share is mechanically capped by the ticket share: a side already
holding 89% of the tickets can gain at most 11 points, while a side on 11% has
89 to play with. Ranking by the gap therefore ranks by how unpopular a side is.
What this uses instead is DOLLARS PER TICKET — money share over ticket share,
divided by the same thing on the other side of the same market. It is
symmetric, it is unbounded in neither direction by construction, and a ratio of
6.9 means the average dollar backing that side is 6.9 times the size of one
backing the other.

**No threshold is declared here.** Which ratio counts as sharp is exactly the
question, and picking 1.5 in advance would answer it by assertion. Sides are
split into bands cut at quantiles of the observed ratios, so the bands come
from the data and move with it season to season.

**What this measures is CLOSING-LINE VALUE, not the win rate.** Whether a side
wins is a question about a few hundred games a season; whether the price moved
toward it is a question about every quote in between, and it is answerable in
weeks rather than seasons. That is the same argument the promotion gate makes.
The win rate is reported beside it because it is cheap to carry, and it is
reported with its sample size because a pattern measured on six games looks
like a system and is a coin flip.

**It will refuse to report.** The split archive began on 2026-09-25 and holds
one capture. Until a split lands BEFORE a close on enough games, every number
here would be noise wearing a decimal point, so `report` says what is missing
instead of printing one. See `docs/DATA_SOURCES.md` for what feeds it.
"""
from __future__ import annotations

import polars as pl

from src.evaluation.rlm import _wilson

#: Split market name -> game-line market name. The two archives are written by
#: different scrapers and neither is wrong; this is where they meet. A mismatch
#: does not raise, it joins nothing, which reads as a quiet week.
MARKET_MAP: dict[str, str] = {
    "moneyline": "h2h",
    "spread": "spreads",
    "total": "totals",
}

#: How many sides a band needs before its numbers are printed rather than
#: withheld. Below this the interval is wider than any effect worth having.
MIN_SIDES = 30

#: How many bands the ratios are cut into. Quantiles, not fixed edges, so the
#: cuts are a property of the data rather than of this file.
N_BANDS = 4


def splits(seasons: list[int] | None = None) -> pl.DataFrame:
    """Every archived split capture, with dollars per ticket attached.

    One row per (capture, game, market, side). `ratio` is that side's dollars
    per ticket divided by the other side's, so 1.0 means the two sides are
    backed by the same average bet and there is nothing to see.
    """
    from src.ingest.action_public import load

    d = load()
    if d.is_empty():
        return pl.DataFrame()
    if seasons:
        d = d.filter(pl.col("season").is_in(seasons))
    d = d.filter(pl.col("tickets_pct").is_not_null()
                 & pl.col("money_pct").is_not_null()
                 & (pl.col("tickets_pct") > 0))
    if d.is_empty():
        return pl.DataFrame()

    # Dollars per ticket, then the same figure on the other side of the same
    # market. A market with anything other than two sides is dropped rather
    # than compared against a partial denominator.
    d = d.with_columns((pl.col("money_pct") / pl.col("tickets_pct")).alias("dpt"))
    key = ["captured_at", "game_id", "market"]
    both = (d.group_by(key)
            .agg([pl.len().alias("_n"), pl.col("dpt").sum().alias("_dpt_sum")])
            .filter(pl.col("_n") == 2))
    d = (d.join(both, on=key, how="inner")
          .with_columns((pl.col("_dpt_sum") - pl.col("dpt")).alias("_other")))
    return (d.filter(pl.col("_other") > 0)
             .with_columns((pl.col("dpt") / pl.col("_other")).alias("ratio"))
             .drop(["_n", "_dpt_sum", "_other"]))


def _line_prob(seasons: list[int] | None = None) -> pl.DataFrame:
    """The consensus price per (game, market, outcome) at each end of the week.

    Median across books, computed on read. The book rows stay on disk; this is
    what the market thought, not a price anybody could take.
    """
    from src.ingest.game_lines import LINES_PATH

    if not LINES_PATH.exists():
        return pl.DataFrame()
    d = pl.read_parquet(LINES_PATH)
    if seasons:
        d = d.filter(pl.col("season").is_in(seasons))
    if d.is_empty():
        return pl.DataFrame()
    return (d.sort("captured_at")
            .group_by(["season", "week", "game_id", "market", "outcome",
                       "snapshot"])
            .agg([pl.col("implied_prob").median().alias("prob"),
                  pl.col("captured_at").max().alias("at"),
                  pl.len().alias("books")]))


def paired(seasons: list[int] | None = None) -> pl.DataFrame:
    """Split captures joined to the close, with the move in that side's favor.

    ONLY CAPTURES TAKEN BEFORE THE CLOSE. A split read after the line closed
    cannot have predicted it, and keeping those rows would score the archive's
    own timing as if it were foresight — the same trap as grading an open
    against a price that came first.

    `move_pp` is signed in the side's favor: positive means the market came
    toward the side the money was on.
    """
    s = splits(seasons)
    if s.is_empty():
        return pl.DataFrame()
    lines = _line_prob(seasons)
    if lines.is_empty():
        return pl.DataFrame()

    close = (lines.filter(pl.col("snapshot") == "close")
             .select(["season", "week", "game_id", "market", "outcome",
                      pl.col("prob").alias("close_prob"),
                      pl.col("at").alias("close_at")]))
    s = s.with_columns(pl.col("market").replace_strict(
        MARKET_MAP, default=None).alias("_mkt"))
    j = (s.filter(pl.col("_mkt").is_not_null())
          .join(close,
                left_on=["season", "week", "game_id", "_mkt", "side"],
                right_on=["season", "week", "game_id", "market", "outcome"],
                how="inner"))
    if j.is_empty():
        return j
    # The market as it stood when the split was read. Falls back to the open
    # when no capture precedes the split, and drops the row when neither does
    # rather than treating the close as its own baseline — a move of exactly
    # zero would otherwise be manufactured for every late capture.
    opens = (lines.filter(pl.col("snapshot") == "open")
             .select(["season", "week", "game_id", "market", "outcome",
                      pl.col("prob").alias("open_prob"),
                      pl.col("at").alias("open_at")]))
    j = j.join(opens,
               left_on=["season", "week", "game_id", "_mkt", "side"],
               right_on=["season", "week", "game_id", "market", "outcome"],
               how="left")
    # The parentheses are load-bearing: `&` binds tighter than `<`, so the
    # unbracketed form ANDs the two columns and compares the capture against
    # the result.
    return (j.filter((pl.col("captured_at") < pl.col("close_at"))
                     & pl.col("open_prob").is_not_null())
             .with_columns(((pl.col("close_prob") - pl.col("open_prob")) * 100)
                           .alias("move_pp")))


def bands(r: pl.Series, n: int = N_BANDS) -> list[float]:
    """Quantile cuts of the observed ratios, so no threshold is asserted."""
    if r.is_empty():
        return []
    qs = [r.quantile(i / n) for i in range(1, n)]
    out: list[float] = []
    for q in qs:
        if q is not None and (not out or q > out[-1]):
            out.append(float(q))
    return out


def evaluate(seasons: list[int] | None = None) -> list[dict]:
    """Per band of dollars-per-ticket: how far the market moved toward it.

    Each row carries its sample size. A band under `MIN_SIDES` reports the
    count and withholds the rest.
    """
    p = paired(seasons)
    if p.is_empty():
        return []
    cuts = bands(p["ratio"])
    label = pl.lit(f"under {cuts[0]:.2f}x") if cuts else pl.lit("all")
    expr = pl.when(pl.col("ratio") < cuts[0]).then(label) if cuts else None
    for i, c in enumerate(cuts):
        hi = cuts[i + 1] if i + 1 < len(cuts) else None
        name = (f"{c:.2f}x to {hi:.2f}x" if hi is not None else f"{c:.2f}x and up")
        cond = (pl.col("ratio") >= c) if hi is None else (
            (pl.col("ratio") >= c) & (pl.col("ratio") < hi))
        expr = cond.__and__(pl.lit(True)) if expr is None else expr
        expr = (pl.when(cond).then(pl.lit(name)).otherwise(expr)
                if expr is not None else pl.when(cond).then(pl.lit(name)))
    p = p.with_columns((expr if expr is not None else pl.lit("all"))
                       .alias("band"))

    out = []
    for (band,), blk in p.group_by(["band"], maintain_order=True):
        n = blk.height
        row = {"band": band, "n": n}
        if n < MIN_SIDES:
            out.append(row)
            continue
        moved = int((blk["move_pp"] > 0).sum())
        lo, hi = _wilson(moved, n)
        row.update({
            "move_pp": float(blk["move_pp"].mean()),
            "toward": moved / n, "lo": lo, "hi": hi,
            "median_ratio": float(blk["ratio"].median()),
        })
        out.append(row)
    return sorted(out, key=lambda r: -r["n"])


def format_report(rows: list[dict], p: pl.DataFrame | None = None) -> str:
    """The table, or a plain statement of what is missing."""
    if not rows:
        return (
            "No split capture yet sits before a close.\n\n"
            "The public-split archive began on 2026-09-25 and the week-3 lines\n"
            "had already closed when it did. `scripts/public_money.sh` runs\n"
            "four times a day, so the first measurable week is the next one\n"
            "whose open, splits and close all land in that order.")
    lines = ["Dollars per ticket, against where the line went\n",
             f"  {'band':22s} {'n':>5} {'median':>8} {'move':>8} "
             f"{'toward':>8}  {'95% interval':>16}"]
    for r in rows:
        if "move_pp" not in r:
            lines.append(f"  {r['band']:22s} {r['n']:5d}   too few sides to "
                         f"report (needs {MIN_SIDES})")
            continue
        lines.append(
            f"  {r['band']:22s} {r['n']:5d} {r['median_ratio']:7.2f}x "
            f"{r['move_pp']:+7.2f} {r['toward']:7.1%}  "
            f"[{r['lo']:.1%}, {r['hi']:.1%}]")
    lines.append(
        "\n  `move` is the mean closing-line move in the side's favor, in\n"
        "  probability points. `toward` is how often it moved that way at all.\n"
        "  A band that beats the others on both is money worth following; one\n"
        "  that does not is a crowd with bigger accounts.")
    return "\n".join(lines)


def report(seasons: list[int] | None = None) -> str:
    return format_report(evaluate(seasons))
