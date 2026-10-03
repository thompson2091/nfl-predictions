"""What a team's three game markets have done before, which is a fact.

`player_history` makes this argument one level down and makes it at length: a
line, what happened against it, and the date are three facts, and the machinery
of a claim — a rate against a price, an expectation, an interval, a color that
means good — is absent on purpose. This is that panel for the spread, the total
and the moneyline.

**IT IS NOT AN ATS MODEL AND THE PROJECT HAS MEASURED WHY NOT.** `cover.py` and
the angles board tested forty-nine spread splits together over 504 team-weeks
since 2015: the best of them covers 52.6% against a 52.38% break-even, and not
one clears at the lower bound of its interval. So a team that has covered six
of ten has done that and nothing follows from it. The panel says so in the
reader's words rather than leaving the record to imply otherwise, and the
record is still shown, because "what has this team done against the number" is
the question people open a game to ask.

**WHOSE LINE IT IS.** The schedule feed posts one number per game, and it is
near the close rather than at it. Measured against this project's own captured
consensus over the 48 played games of 2026, the feed's `total_line` matches our
archived CLOSE exactly on 23 of them and sits 0.10 points from it on average,
against 0.22 from the open. So it is one source's closing number: the right
thing to grade a result against, and not a price a reader could have taken.
The panel says "one source's close" and does not say "best price".

**PUSHES ARE SET ASIDE, NOT LOST.** A game that lands exactly on the number
returns the stake, and counting it as a loss would understate every record by
the 156 ATS and 56 total pushes in the archive. `player_history` makes the same
distinction for a man who did not play, and for the same reason: the direction
of the error flatters a reader into a bet.

**BOTH SIDES ARE REAL QUOTES HERE**, which is the one way this panel is better
off than the player one. The player archive holds the Yes and the Over and
nothing else, so "what if you had faded him" is a question it cannot answer.
The schedule posts both moneylines and both spread prices, so fading a team is
priced at the number the books actually showed.
"""
from __future__ import annotations

import polars as pl

from src.evaluation.team_form import LAST, team_games
from src.utils.paths import get_path

#: The three markets, and what a row of each is called. `side` is what backing
#: the team itself means in words, and `fade` its opposite — the page prints
#: whichever way the window ran.
MARKETS: tuple[tuple[str, str, str, str], ...] = (
    ("ats", "Against the spread", "covered", "did not cover"),
    ("ou", "Over/under", "over", "under"),
    ("ml", "Moneyline", "won", "lost"),
)

#: Result encoding, shared by all three: the team's side came in, pushed, or
#: did not. One vocabulary rather than three, so the page grades a row the same
#: way whichever column it is in.
WON, PUSH, LOST = 1, 0, -1


def _result(mine: pl.Expr, theirs: pl.Expr) -> pl.Expr:
    """WON where mine beats theirs, PUSH on a tie, LOST otherwise.

    Null in, null out: a game with no posted line has no result against it,
    and a row that reported LOST for want of a number would be a loss the
    team never took.
    """
    return (pl.when(mine.is_null() | theirs.is_null()).then(None)
              .when(mine > theirs).then(WON)
              .when(mine == theirs).then(PUSH)
              .otherwise(LOST).cast(pl.Int8))


def graded(schedule: pl.DataFrame, season: int, week: int) -> pl.DataFrame:
    """`team_games` with the three results added.

    The cover rule is `margin > sp`, and `sp` is the team's own spread from
    `team_games` — positive when favored. A team favored by 2.5 covers by
    winning by more than 2.5, which is the comparison written out. The
    symmetry of the answer is what the tests assert: every game has exactly
    one cover and one non-cover, so a flipped sign cannot pass.
    """
    g = team_games(schedule, season, week)
    if g.is_empty():
        return g
    margin = pl.col("pf") - pl.col("pa")
    points = pl.col("pf") + pl.col("pa")
    # PREFIXED, because `team_games` already carries a column called `ml` and
    # it is the PRICE. A result and a price under one name is how a panel comes
    # to grade a game against +330.
    return g.with_columns([
        _result(margin, pl.col("sp")).alias("r_ats"),
        _result(points, pl.col("tot")).alias("r_ou"),
        # No line to beat on a moneyline: the result is the scoreboard, and a
        # tie is the push.
        _result(margin, pl.lit(0.0)).alias("r_ml"),
    ])


def rows_for(season: int, week: int, last: int | None = None,
             schedule: pl.DataFrame | None = None) -> dict[str, list]:
    """Per team, its completed games before (season, week), newest first.

    Each row is

        [season, week, opp, home, pf, pa, sp, tot,
         ats, ou, ml, sp_odds, sp_odds_opp, over_odds, under_odds,
         ml_odds, ml_odds_opp]

    THE FIRST SIX FIELDS ARE `team_form`'S, IN ORDER, so the page labels a row
    with the `v3PastWhen` it already has and reads `vs`/`at` the same way. A
    panel that needed its own date formatter would be a second place for the
    playoffs to be numbered wrong.

    `last` caps per team, newest kept. None is the whole record, which is what
    the fetched file carries.
    """
    if schedule is None:
        schedule = pl.read_parquet(get_path("raw") / "schedules.parquet")
    need = {"season", "week", "home_team", "away_team", "home_score",
            "away_score", "spread_line", "total_line"}
    if not need.issubset(set(schedule.columns)):
        return {}
    g = graded(schedule, season, week)
    if g.is_empty():
        return {}

    def num(v, cast=float):
        return None if v is None else cast(v)

    out: dict[str, list] = {}
    for team, grp in g.group_by("team"):
        name = team[0] if isinstance(team, tuple) else team
        grp = grp.sort("_ord", descending=True)
        if last is not None:
            grp = grp.head(last)
        rows = []
        for r in grp.iter_rows(named=True):
            rows.append([
                int(r["season"]), int(r["week"]), r["opp"], int(r["home"]),
                int(r["pf"]), int(r["pa"]),
                num(r["sp"]), num(r["tot"]),
                num(r["r_ats"], int), num(r["r_ou"], int), num(r["r_ml"], int),
                num(r["sp_odds"], int), num(r["sp_odds_opp"], int),
                num(r["over_odds"], int), num(r["under_odds"], int),
                num(r["ml"], int), num(r["ml_opp"], int),
            ])
        out[name] = rows
    return out


def market_meta() -> list[dict]:
    """What the page needs to draw each market without hardcoding it."""
    return [{"key": k, "label": lab, "won": won, "lost": lost}
            for k, lab, won, lost in MARKETS]


def coverage(schedule: pl.DataFrame | None = None) -> dict:
    """How much of the played record carries all three markets.

    A silent join failure here would empty the panel rather than break it,
    which is the shape of bug this project keeps finding, so the number is
    asserted in a test rather than printed and forgotten.
    """
    if schedule is None:
        schedule = pl.read_parquet(get_path("raw") / "schedules.parquet")
    played = schedule.filter(pl.col("home_score").is_not_null())
    if played.is_empty():
        return {"games": 0, "priced": 0, "rate": None}
    have = [c for c in ("spread_line", "total_line", "home_moneyline")
            if c in played.columns]
    if len(have) < 3:
        return {"games": played.height, "priced": 0, "rate": 0.0}
    ok = played.filter(pl.all_horizontal(
        [pl.col(c).is_not_null() for c in have])).height
    return {"games": played.height, "priced": ok, "rate": ok / played.height}
