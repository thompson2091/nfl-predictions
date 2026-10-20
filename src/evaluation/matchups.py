"""This week's games, as the market prices them and as the books disagree.

The data layer behind a matchup or bets view. Everything here comes from the
game-line archive (`ingest/game_lines`); nothing is modeled, and that is
deliberate.

**Why there is no model opinion on the total here.** The obvious thing to show
beside a posted total is what we make it. This project cannot honestly supply
that. `models/joint.fit_team_rate` is a Poisson regression of team touchdowns
on `implied_team_total`, `total_line` and `abs_spread` — its own docstring says
its job is to read the market's number and convert points into touchdowns, not
to re-forecast the game. Printing its output beside the total would be printing
the total twice and calling the second one a second opinion.

What IS independent is the share model: `build_vegas_features` is not in the
anytime-TD allow-list, so the ranking of WHO scores is formed without seeing
the line. The level is the market's; the ordering is ours. A view that wants a
genuine model view on a total needs a model trained without the vegas family,
which is an experiment (`exclude_feature_families: [build_vegas_features]`),
not a read of what exists.

So what this module reports is what the market says, how much the books
disagree about it, and — once both ends of a week exist — which way it moved.
Those are facts, and the disagreement is the one with money in it: the best
moneyline beats the consensus by 1.23pp, which is 2.4% of return for holding
more than one account.
"""
from __future__ import annotations

import polars as pl

#: Below this many books quoting one outcome, "consensus" is one or two
#: opinions wearing the word. Spreads and totals scatter across points, so a
#: specific line is quoted by a median of 6 and 4 books where a moneyline is
#: quoted by 20 — the same reason `n_books` means something narrower on the
#: yardage markets.
MIN_BOOKS = 4


def _load(season: int, week: int, snapshot: str | None = None) -> pl.DataFrame:
    from src.ingest.game_lines import LINES_PATH

    if not LINES_PATH.exists():
        return pl.DataFrame()
    d = pl.read_parquet(LINES_PATH).filter(
        (pl.col("season") == season) & (pl.col("week") == week))
    if snapshot:
        d = d.filter(pl.col("snapshot") == snapshot)
    return d


def _this_week_only(d: pl.DataFrame, season: int, week: int) -> pl.DataFrame:
    """Drop games the archive filed here that are played in another week.

    THE CAPTURE FILES BY WHEN IT RAN, NOT BY WHEN THE GAME IS PLAYED. Books
    post the next week's lines days early, so week 3 of 2026 was archived with
    thirty games in it: its own sixteen and fourteen belonging to week 4. The
    board read the file as one week and showed all thirty under "This week" —
    sixteen finished games beside fourteen that had not kicked off — and week
    3's archived page would have kept the fourteen after the rollover.

    Corrected on the way out rather than in the archive, so it applies to every
    week already captured. The SCHEDULE decides which week a game is in, which
    is the one place that cannot be wrong about it.
    """
    try:
        from src.utils.paths import get_path

        sched = (pl.read_parquet(get_path("raw") / "schedules.parquet")
                 .filter((pl.col("season") == season)
                         & (pl.col("game_type") == "REG"))
                 .select([(pl.col("away_team") + "_" + pl.col("home_team"))
                          .alias("game_id"), pl.col("week").alias("_wk")]))
    except Exception:                                            # noqa: BLE001
        # A missing schedule must not empty the board: showing a week with an
        # extra game in it beats showing no week at all.
        return d
    out = d.join(sched, on="game_id", how="left")
    # Left alone where the schedule has never heard of the id. That is a
    # different fault from a game filed under the wrong week, and dropping it
    # here would hide it.
    return (out.filter(pl.col("_wk").is_null() | (pl.col("_wk") == week))
               .drop("_wk"))


def board(season: int, week: int, snapshot: str = "close") -> pl.DataFrame:
    """Per game, market and outcome: the consensus, the best price, and who has it.

    `gap_pp` is the best price minus the consensus in probability points, which
    is the only form the improvement can be read in — a price is not better by
    "30 cents", it is better by the extra chance you are paid for.

    Returns the newest capture per book, so a week holding several snapshots
    prices one line once rather than pooling a Tuesday quote with a Sunday one.
    """
    d = _load(season, week, snapshot)
    if d.is_empty():
        return pl.DataFrame()
    d = _this_week_only(d, season, week)
    if d.is_empty():
        return pl.DataFrame()
    # NO PRICE QUOTED AFTER KICKOFF. Newest-per-book below selects exactly
    # those, and on 2026 weeks 3-5 it put 29 cards on in-play lines: LV @ NO
    # read NO at 9.5% to win against 64.9% before kickoff, with NO losing.
    # The Record already filtered them (`season_scorecard._book_lines`), so
    # the card and the grade disagreed. Same filter, same rows now.
    from src.ingest.odds_history import drop_in_play
    d = drop_in_play(d)
    if d.is_empty():
        return pl.DataFrame()

    d = d.sort("captured_at")
    # HOW MANY BOOKS ARE ON THIS LINE NOW. Newest-per-(book, point) below keeps
    # a line a book left days ago, so counting its books found Tuesday's
    # number: KC @ MIA 2026 week 3 carded 11.5 against a 9.5 close, and 23 of
    # 93 spreads sat half a point or more off. A book quotes one point per
    # capture, so its newest quote per outcome is where it stands.
    now = (d.unique(subset=["game_id", "market", "outcome", "bookmaker"],
                    keep="last")
             .group_by(["game_id", "market", "outcome", "point"])
             .agg(pl.len().alias("n_current")))
    d = d.unique(subset=["game_id", "market", "outcome", "point", "bookmaker"],
                 keep="last")
    g = (d.group_by(["game_id", "home_team", "away_team", "market", "outcome",
                     "point"])
           .agg([pl.col("implied_prob").median().alias("consensus_prob"),
                 pl.col("implied_prob").min().alias("best_prob"),
                 # NOT a median of American odds. That scale is discontinuous
                 # at +/-100, so the median of books quoting -110 and +120
                 # lands on an impossible number — `odds_api._prob_to_american`
                 # documents the same bug turning into 20x payouts. Consensus
                 # is taken in probability space and converted below.
                 pl.col("odds").max().alias("best_odds"),
                 pl.len().alias("n_books")])
           .filter(pl.col("n_books") >= MIN_BOOKS))
    if g.is_empty():
        return g

    # Who is offering the best, joined back rather than tracked through the
    # aggregate: ties are real (two books at the same number) and taking the
    # first alphabetically would invent a preference.
    # `nulls_equal` because `point` is null on every moneyline, and a polars
    # join drops null keys by default — which returned `best_book` as None for
    # every h2h row while the spreads and totals beside them resolved fine.
    # Same trap `clv.line_movement` carries a note about.
    who = (d.join(g.select(["game_id", "market", "outcome", "point", "best_odds"]),
                  on=["game_id", "market", "outcome", "point"], how="inner",
                  nulls_equal=True)
             .filter(pl.col("odds") == pl.col("best_odds"))
             .group_by(["game_id", "market", "outcome", "point"])
             .agg(pl.col("bookmaker").sort().str.join(", ").alias("best_book")))

    from src.ingest.odds_api import _prob_to_american

    out = (g.join(who, on=["game_id", "market", "outcome", "point"], how="left",
                  nulls_equal=True)
            .join(now, on=["game_id", "market", "outcome", "point"], how="left",
                  nulls_equal=True)
            .with_columns(pl.col("n_current").fill_null(0)))
    return (out.with_columns([
                ((pl.col("consensus_prob") - pl.col("best_prob")) * 100)
                .alias("gap_pp"),
                pl.col("consensus_prob")
                .map_elements(_prob_to_american, return_dtype=pl.Int64)
                .alias("consensus_odds"),
            ])
            # `point` IS PART OF THE KEY, so it is part of the sort. A market
            # carries several lines at once — the spread at 9.0 and at 9.5 are
            # two rows with the same game, market and outcome — and sorting on
            # the first three left their order to whatever the group_by
            # happened to produce. Two builds of one unchanged archive then
            # emitted the same rows in a different order, which reads
            # downstream as the numbers having changed. `nulls_last` because a
            # moneyline's point is null and has to land somewhere fixed.
            .sort(["game_id", "market", "outcome", "point"], nulls_last=True))


def movement(season: int, week: int) -> pl.DataFrame:
    """How each line moved between its opening capture and its latest one.

    Empty until a week holds both ends. That is the normal state for the week
    being played, not a fault — the open is archived when the lines go up and
    the close before kickoff, and there is nothing to difference in between.

    `move_pp` is signed in the outcome's own favor: positive means the market
    came toward that side. On a two-sided market the other side carries the
    mirror image, which is what makes a one-sided move visible as such.
    """
    d = _load(season, week)
    if d.is_empty() or d["snapshot"].n_unique() < 2:
        return pl.DataFrame()

    ends = []
    for snap, keep in (("open", "first"), ("close", "last")):
        s = d.filter(pl.col("snapshot") == snap)
        if s.is_empty():
            return pl.DataFrame()
        ends.append(
            s.sort("captured_at")
             .unique(subset=["game_id", "market", "outcome", "point", "bookmaker"],
                     keep=keep)
             .group_by(["game_id", "market", "outcome", "point"])
             .agg([pl.col("implied_prob").median().alias(f"{snap}_prob"),
                   pl.len().alias(f"{snap}_books")]))

    # `nulls_equal` for the same reason as in `board`: `point` is null on
    # every moneyline, and without it the whole h2h market silently drops out
    # of the movement table while spreads and totals stay.
    j = ends[0].join(ends[1], on=["game_id", "market", "outcome", "point"],
                     how="inner", nulls_equal=True)
    from src.ingest.odds_api import _prob_to_american

    return (j.with_columns([
                ((pl.col("close_prob") - pl.col("open_prob")) * 100).alias("move_pp"),
                pl.col("open_prob").map_elements(_prob_to_american, return_dtype=pl.Int64)
                  .alias("open_odds"),
                pl.col("close_prob").map_elements(_prob_to_american, return_dtype=pl.Int64)
                  .alias("close_odds"),
            ])
            .sort("move_pp", descending=True))


def summary(season: int, week: int, snapshot: str = "close") -> str:
    """A readable block: what the books disagree about most, per market."""
    b = board(season, week, snapshot)
    if b.is_empty():
        return (f"No game lines archived for {season} week {week} "
                f"({snapshot}). Run `python scripts/53_game_lines.py "
                f"--snapshot {snapshot}`.")
    out = [f"Game lines — {season} week {week} ({snapshot})",
           f"  {b['game_id'].n_unique()} games, "
           f"{b.height} outcomes with {MIN_BOOKS}+ books"]
    for mk in ("h2h", "spreads", "totals"):
        s = b.filter(pl.col("market") == mk)
        if s.is_empty():
            continue
        out.append(f"\n  {mk} — best beats consensus by "
                   f"{s['gap_pp'].median():.2f}pp median, "
                   f"{s['gap_pp'].max():.2f}pp at the widest")
        for r in s.sort("gap_pp", descending=True).head(3).iter_rows(named=True):
            pt = "" if r["point"] is None else f" {r['point']:+g}"
            out.append(f"      {r['game_id']:<9} {str(r['outcome']):<6}{pt:<6} "
                       f"{r['consensus_odds']:>6.0f} -> {r['best_odds']:>6.0f}  "
                       f"+{r['gap_pp']:.2f}pp  {r['best_book']}")
    return "\n".join(out)
