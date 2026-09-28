"""Against-the-spread angles, measured together and graded from the day added.

**THE LIST IS THE EXPERIMENT, AND SO IS THE DATE ON EACH ROW.**

An angle is a split of team-weeks — off a blowout loss, off a bye, divisional
underdog — and the claim attached to one is always the same: teams in this
split cover more often than the price implies. Break-even at -110 is 52.38%.

Twenty were measured together on 2026-09-28 over 5,732 graded team-games
(2015-2026). NONE clears break-even at the lower bound of its interval and two
clear on the point estimate alone, both barely, both spanning it. The baseline
is 50.00% to two decimals. That is the honest state of this idea.

**WHY ANGLES MAY BE ADDED AFTER SEEING THEM WIN, WHICH SOUNDS LIKE CHEATING.**

Because the alternative — a fixed list — throws away the only thing that makes
a noticed angle testable. Adding one is not the error; presenting a mined
angle with the same standing as a pre-registered one is. So every angle
carries the date it joined, and its record is reported twice: all-time, which
for an added angle includes the hot stretch that got it noticed and is
therefore not evidence, and SINCE ADDED, which is a clean forward test nobody
can tune. An angle that was real keeps covering after the day it was written
down. One that was a hot eight games reverts, in public, on its own row.

That is also why nothing is ever removed for going cold. A row that reverted
is the most informative row on the page, and deleting it would leave a board
of survivors that looks like a system and is a selection artifact.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import polars as pl

#: Break-even on a standard -110 spread price.
BREAK_EVEN = 0.5238

#: Below this a split cannot say anything and is not reported.
MIN_GAMES = 50


@dataclass(frozen=True)
class Angle:
    """One split, its predicate, and the day it was written down."""

    id: str
    label: str
    #: Prose for the card, with `{team}` filled in.
    blurb: str
    #: The day this joined the board. All-time includes whatever made it
    #: interesting; `since` starts here and is the part that can be trusted.
    added: date
    #: Built against the team-week frame from `team_weeks`.
    predicate: object
    #: True where it joined because it was hot rather than at registration.
    mined: bool = False


#: THE FOUNDING TWENTY, all registered the same day, none chosen for being hot.
#: Their all-time record IS their evidence, because nothing selected them.
_REG = date(2026, 9, 28)

ANGLES: tuple[Angle, ...] = (
    Angle("blowout_loss", "Off a 20+ loss",
          "{team} lost by {detail} last week.", _REG,
          pl.col("prev_margin") <= -20),
    Angle("bad_loss", "Off a 14+ loss",
          "{team} lost by {detail} last week.", _REG,
          pl.col("prev_margin") <= -14),
    Angle("blowout_win", "Off a 20+ win",
          "{team} won by {detail} last week.", _REG,
          pl.col("prev_margin") >= 20),
    Angle("two_losses", "Off two straight losses",
          "{team} has lost two in a row.", _REG,
          (pl.col("prev_margin") < 0) & (pl.col("prev2_margin") < 0)),
    Angle("two_wins", "Off two straight wins",
          "{team} has won two in a row.", _REG,
          (pl.col("prev_margin") > 0) & (pl.col("prev2_margin") > 0)),
    Angle("off_bye", "Off a bye",
          "{team} is off a bye.", _REG, pl.col("rest") >= 10),
    Angle("short_week", "On a short week",
          "{team} is on a short week.", _REG, pl.col("rest") <= 4),
    Angle("rest_edge", "Rest edge of 3+ days",
          "{team} has {detail} more days of rest.", _REG,
          (pl.col("rest") - pl.col("opp_rest")) >= 3),
    Angle("rest_deficit", "Rest deficit of 3+ days",
          "{team} has {detail} fewer days of rest.", _REG,
          (pl.col("opp_rest") - pl.col("rest")) >= 3),
    Angle("home_dog", "Home underdog",
          "{team} is a home underdog.", _REG,
          pl.col("at_home") & (pl.col("my_spread") < 0)),
    Angle("road_fav", "Road favorite",
          "{team} is favored on the road.", _REG,
          (~pl.col("at_home")) & (pl.col("my_spread") > 0)),
    Angle("big_fav", "Favoured by 10+",
          "{team} is laying {detail}.", _REG, pl.col("my_spread") >= 10),
    Angle("big_dog", "Underdog by 10+",
          "{team} is getting {detail}.", _REG, pl.col("my_spread") <= -10),
    Angle("div_dog", "Divisional underdog",
          "{team} is a divisional underdog.", _REG,
          pl.col("div_game") & (pl.col("my_spread") < 0)),
    Angle("prime", "In prime time",
          "{team} plays in prime time.", _REG, pl.col("prime")),
    Angle("prime_dog", "Prime-time underdog",
          "{team} is a prime-time underdog.", _REG,
          pl.col("prime") & (pl.col("my_spread") < 0)),
    Angle("high_total", "Total of 50+",
          "The total is {detail}.", _REG, pl.col("total_line") >= 50),
    Angle("low_total", "Total of 40 or under",
          "The total is {detail}.", _REG, pl.col("total_line") <= 40),
    Angle("off_ot", "Off an overtime game",
          "{team} went to overtime last week.", _REG, pl.col("prev_ot")),
    Angle("indoors", "Indoors",
          "The game is indoors.", _REG,
          pl.col("roof").is_in(["dome", "closed"])),
)


def team_weeks(schedules: pl.DataFrame) -> pl.DataFrame:
    """One row per team-game, with last week's result carried forward.

    Pushes are dropped rather than counted as half: a push returns the stake,
    so it is neither a cover nor a loss, and including it as either moves
    every rate toward 50% by an amount that varies with the split.
    """
    s = schedules.filter(
        (pl.col("game_type") == "REG") & pl.col("spread_line").is_not_null())

    def side(is_home: bool) -> pl.DataFrame:
        t, o = ("home", "away") if is_home else ("away", "home")
        sign = 1 if is_home else -1
        return s.select([
            pl.col("season"), pl.col("week"), pl.col("gameday"),
            pl.col(f"{t}_team").alias("team"),
            pl.col(f"{o}_team").alias("opp"),
            pl.lit(is_home).alias("at_home"),
            (sign * pl.col("result")).alias("margin"),
            (sign * (pl.col("result") - pl.col("spread_line"))).alias("cover_by"),
            # `spread_line` is the HOME spread, so the away side is its
            # negation; positive means this team is favored.
            (sign * pl.col("spread_line")).alias("my_spread"),
            pl.col(f"{t}_rest").alias("rest"),
            pl.col(f"{o}_rest").alias("opp_rest"),
            pl.col("div_game").cast(pl.Boolean).alias("div_game"),
            pl.col("total_line"),
            pl.col("overtime").cast(pl.Boolean).alias("overtime"),
            pl.col("gametime"), pl.col("roof"),
        ])

    tg = pl.concat([side(True), side(False)]).sort(["season", "team", "week"])
    return tg.with_columns([
        pl.col("margin").shift(1).over(["season", "team"]).alias("prev_margin"),
        pl.col("margin").shift(2).over(["season", "team"]).alias("prev2_margin"),
        pl.col("overtime").shift(1).over(["season", "team"]).alias("prev_ot"),
        (pl.col("gametime").str.slice(0, 2).cast(pl.Int32, strict=False) >= 20)
        .alias("prime"),
        (pl.col("cover_by") > 0).alias("covered"),
    ])


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def _record(f: pl.DataFrame) -> dict | None:
    graded = f.filter(pl.col("cover_by").is_not_null()
                      & (pl.col("cover_by") != 0))
    n = graded.height
    if not n:
        return None
    k = int(graded["covered"].sum())
    lo, hi = wilson(k, n)
    return {"n": n, "w": k, "l": n - k, "pct": k / n, "lo": lo, "hi": hi,
            "clears": lo > BREAK_EVEN}


def measure(schedules: pl.DataFrame, season: int | None = None) -> list[dict]:
    """Every angle's record: all-time, since it was added, and this season.

    `since` is the one that carries weight for an angle added because it was
    hot — it starts the day the angle was written down, so nothing in it can
    have been selected on.
    """
    tg = team_weeks(schedules)
    out = []
    for a in ANGLES:
        f = tg.filter(a.predicate)
        allt = _record(f)
        if allt is None or allt["n"] < MIN_GAMES:
            continue
        added = f.filter(
            pl.col("gameday").str.to_date(strict=False) >= pl.lit(a.added))
        cur = f.filter(pl.col("season") == season) if season else f.head(0)
        out.append({
            "id": a.id, "label": a.label, "blurb": a.blurb,
            "added": a.added.isoformat(), "mined": a.mined,
            "all": allt, "since": _record(added), "season": _record(cur),
        })
    out.sort(key=lambda r: -r["all"]["pct"])
    return out


def qualifying(schedules: pl.DataFrame, season: int, week: int) -> dict:
    """Which angles each team carries into this week's game."""
    tg = team_weeks(schedules)
    wk = tg.filter((pl.col("season") == season) & (pl.col("week") == week))
    hits: dict = {}
    for a in ANGLES:
        for r in wk.filter(a.predicate).iter_rows(named=True):
            hits.setdefault(r["team"], []).append(a.id)
    return hits
