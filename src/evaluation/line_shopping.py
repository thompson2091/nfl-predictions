"""What the best available price is worth, against the one we modeled on.

Every profitability figure in this project is computed against a consensus
median across books. Nobody can bet a median. The price you can actually take is
the best one on offer, and the gap between those two is pure, riskless edge —
it requires no model to be right, only an account at more than one book.

That gap is frequently larger than the entire measured advantage. A player
quoted +150 at one book and +180 at another is a 4-point swing in implied
probability; the fitted edge rule's whole cut-off is 1 point. So the numbers on
the Betting reality tab are conservative by however much this measures, and
knowing by how much changes what the strategy is worth.

The archive this reads only began on 2026-08-11, because the ingestion collapsed
every book to a median before writing and threw the rest away. It cannot be
backfilled: The Odds API sells each snapshot once. So this starts thin — two
books at first — and gets useful as the season runs. `summary` reports how many
books it actually saw rather than implying more coverage than it has.
"""
from __future__ import annotations

import polars as pl


def _implied(odds: pl.Expr) -> pl.Expr:
    """American odds to implied probability, vig included."""
    return (pl.when(odds > 0).then(100.0 / (odds + 100.0))
            .otherwise(-odds / (-odds + 100.0)))


def best_vs_consensus(season: int, week: int, market: str = "anytime_td",
                      snapshot: str | None = "close") -> pl.DataFrame | None:
    """Per player: the best price, who offered it, and what it beats.

    `gap_pp` is in probability points and is the quantity that matters — a
    price improvement means nothing until it is expressed as the extra chance
    you are being paid for.

    **`snapshot=None` MEANS EVERY SNAPSHOT, AND IS WHAT A LIVE WEEK WANTS.**
    "The price you can actually take" is the newest quote, not a label. A week
    still being played has no close at all, and asking for one got a board
    whose Best price was SHORTER than its own posted price on 199 of 571
    priced rows — 35% — because the two came from different populations: the
    posted price off the live cache consensus, the best price off whatever the
    archive happened to hold under the word "close".

    Measured 2026-10-07, Jahmyr Gibbs first TD, week 5:

        close   fanatics        +270    1 book    Monday
        open    williamhill_us  +305   10 books   Wednesday
        posted  (live cache)    +300

    The dedupe below already keeps each book's NEWEST capture, so pooling the
    snapshots cannot resurrect a stale quote — a book that moved between the
    open and the close still contributes only its close.

    The `"close"` default stands so `scripts/18_shop.py` and
    `scripts/39_shortlist.py` keep measuring what they measured.
    """
    from src.ingest.odds_history import BOOKS_PATH

    if not BOOKS_PATH.exists():
        return None
    # The books archive names a game three different ways depending on when the
    # row was written; grouping on the raw value splits one player across two
    # ids. See `odds_history.resolve_game_ids`.
    from src.ingest.odds_history import drop_in_play, resolve_game_ids

    # `drop_in_play` first: an in-play quote is both the newest and the most
    # extreme, so it wins the dedupe below and then wins "best price" too.
    df = drop_in_play(resolve_game_ids(pl.read_parquet(BOOKS_PATH))).filter(
        (pl.col("season") == season) & (pl.col("week") == week)
        & (pl.col("market") == market) & (pl.col("side") == "yes")
    )
    if snapshot is not None:
        df = df.filter(pl.col("snapshot") == snapshot)
    if df.height == 0:
        return None

    # One row per book per player: a repeated fetch in the same week would
    # otherwise count a book twice and flatter the spread between them.
    df = (df.sort("captured_at")
            .unique(subset=["game_id", "player_name_norm", "bookmaker"],
                    keep="last"))

    # Consensus is taken in probability space and only then converted back.
    # A median of American odds is meaningless: the scale is discontinuous at
    # +/-100, so the median of -135 and +105 lands on -15, a price that does not
    # exist. src/ingest/odds_api.py documents the same trap; taking it here
    # produced a negative mean gap alongside a positive median, which is
    # impossible when "best" means best and is what exposed the bug.
    df = df.with_columns(_implied(pl.col("odds")).alias("_imp"))

    out = (df.group_by(["game_id", "player_name_norm"])
             .agg([
                 pl.col("player_name_raw").first().alias("player"),
                 # Best price = the one paying most = lowest implied probability.
                 pl.col("odds").sort_by("_imp").first().alias("best_odds"),
                 pl.col("_imp").min().alias("_best_imp"),
                 pl.col("_imp").median().alias("_consensus_imp"),
                 # TIES BREAK BY NAME, AND THE TIE IS THE COMMON CASE.
                 #
                 # Sorting on the price alone leaves every tied book equally
                 # eligible and `first` takes whichever the sort happened to
                 # leave in front, which polars does not promise to keep stable
                 # between runs. Measured on 2026 week 3 anytime TD: 254 of 538
                 # players — 47% — had two or more books level at the best
                 # price, one had eight, and three consecutive builds of the
                 # same archive named a different book each time. The page then
                 # reported "best price at fanduel" and "at betparx" on
                 # successive deploys with no market movement behind it.
                 #
                 # Alphabetical is arbitrary, and deliberately so: there is
                 # nothing in this archive that makes one tied book better than
                 # another, and inventing a preference would be a claim. What
                 # it buys is that the same archive always answers the same
                 # way. `n_best` carries how many were level, so a reader can
                 # see that the name is one of several rather than the only
                 # book with that price.
                 pl.col("bookmaker").sort_by(["_imp", "bookmaker"]).first()
                   .alias("best_book"),
                 (pl.col("bookmaker").filter(pl.col("_imp") == pl.col("_imp").min())
                    .n_unique()).alias("n_best"),
                 pl.col("bookmaker").n_unique().alias("n_books"),
             ]))
    return out.with_columns([
        # Positive means the best price pays for more than the consensus
        # implies — i.e. the consensus understates what you can get.
        ((pl.col("_consensus_imp") - pl.col("_best_imp")) * 100).alias("gap_pp"),
        (pl.when(pl.col("_consensus_imp") >= 0.5)
           .then(-pl.col("_consensus_imp") / (1 - pl.col("_consensus_imp")) * 100)
           .otherwise((1 - pl.col("_consensus_imp")) / pl.col("_consensus_imp") * 100)
         ).round(0).cast(pl.Int64).alias("consensus_odds"),
    ]).sort("gap_pp", descending=True)


def summary(season: int, week: int, market: str = "anytime_td",
            snapshot: str | None = "close") -> dict | None:
    """How much the best price is worth this week, and how thin the sample is.

    Reports `n_books_max` prominently. With two books a "best price" is barely
    a choice, and the figure will grow simply because more books get archived —
    which would look like an improving edge and is not one.
    """
    d = best_vs_consensus(season, week, market, snapshot)
    if d is None or d.height == 0:
        return None

    shoppable = d.filter(pl.col("n_books") > 1)
    return {
        "season": season, "week": week, "market": market, "snapshot": snapshot,
        "players": int(d.height),
        "players_with_choice": int(shoppable.height),
        "n_books_max": int(d["n_books"].max()),
        "mean_gap_pp": float(shoppable["gap_pp"].mean()) if shoppable.height else 0.0,
        "median_gap_pp": float(shoppable["gap_pp"].median()) if shoppable.height else 0.0,
        "max_gap_pp": float(shoppable["gap_pp"].max()) if shoppable.height else 0.0,
        # Every backtested figure is measured at the consensus, so this is how
        # much of an understatement they are — assuming you take the best price
        # every time, which is the assumption to check against the wager log.
        "understatement_note": (
            "Backtested returns are computed at the consensus price. Taking the "
            "best available instead adds roughly this many probability points "
            "per bet, before any model edge."
        ),
    }


def report(season: int, week: int, market: str = "anytime_td") -> str:
    s = summary(season, week, market)
    if s is None:
        return (f"LINE SHOPPING — no per-book quotes archived for {market} "
                f"{season} week {week}.\n"
                f"  Run `make odds-close` during the week; capture began "
                f"2026-08-11 and cannot be backfilled.")
    lines = [
        f"LINE SHOPPING — {market} {season} week {week} ({s['snapshot']})",
        f"  {s['players']} players, {s['players_with_choice']} quoted by more "
        f"than one book, {s['n_books_max']} books at most",
    ]
    if s["players_with_choice"]:
        lines.append(f"  best vs consensus: mean {s['mean_gap_pp']:+.2f}pp, "
                     f"median {s['median_gap_pp']:+.2f}pp, "
                     f"best {s['max_gap_pp']:+.2f}pp")
        lines.append("  Every backtested return is measured at the consensus, "
                     "so they understate\n  what a shopped price would have "
                     "produced by about this much per bet.")
    if s["n_books_max"] < 3:
        lines.append("  NOTE: too few books for this to mean much yet. It will "
                     "grow as more are\n  archived, which is coverage improving "
                     "rather than an edge improving.")
    return "\n".join(lines)
