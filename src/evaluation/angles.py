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
#: The second batch, registered together the same evening.
_REG2 = date(2026, 9, 28)

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

    # ---- THE SECOND THIRTY, registered together on the same day -----------
    #
    # Registered, not mined: none was chosen for being hot, and all thirty are
    # measured whatever they say. That matters more at fifty than at twenty —
    # see `EXPECTED_FALSE_POSITIVES` below.
    Angle("three_losses", "Off three straight losses",
          "{team} has lost three in a row.", _REG2,
          (pl.col("prev_margin") < 0) & (pl.col("prev2_margin") < 0)
          & (pl.col("prev3_margin") < 0)),
    Angle("three_wins", "Off three straight wins",
          "{team} has won three in a row.", _REG2,
          (pl.col("prev_margin") > 0) & (pl.col("prev2_margin") > 0)
          & (pl.col("prev3_margin") > 0)),
    Angle("off_cover", "Off a cover", "{team} covered last week.", _REG2,
          pl.col("prev_cover")),
    Angle("off_ats_loss", "Off a non-cover",
          "{team} did not cover last week.", _REG2, ~pl.col("prev_cover")),
    Angle("two_covers", "Off two straight covers",
          "{team} has covered two in a row.", _REG2,
          pl.col("prev_cover") & pl.col("prev2_cover")),
    Angle("two_non_covers", "Off two straight non-covers",
          "{team} has failed to cover twice.", _REG2,
          (~pl.col("prev_cover")) & (~pl.col("prev2_cover"))),
    Angle("close_loss", "Off a one-score loss",
          "{team} lost by {detail} last week.", _REG2,
          (pl.col("prev_margin") < 0) & (pl.col("prev_margin") >= -8)),
    Angle("close_win", "Off a one-score win",
          "{team} won by {detail} last week.", _REG2,
          (pl.col("prev_margin") > 0) & (pl.col("prev_margin") <= 8)),
    Angle("scored_30", "Off scoring 30+",
          "{team} scored {detail} last week.", _REG2, pl.col("prev_pf") >= 30),
    Angle("scored_under_14", "Off scoring under 14",
          "{team} scored {detail} last week.", _REG2, pl.col("prev_pf") < 14),
    Angle("allowed_30", "Off allowing 30+",
          "{team} allowed {detail} last week.", _REG2, pl.col("prev_pa") >= 30),
    Angle("allowed_under_14", "Off allowing under 14",
          "{team} allowed {detail} last week.", _REG2, pl.col("prev_pa") < 14),
    Angle("third_road", "Third straight road game",
          "{team} is on the road a third straight week.", _REG2,
          (~pl.col("at_home")) & (~pl.col("prev_home"))
          & (~pl.col("prev2_home"))),
    Angle("second_road", "Second straight road game",
          "{team} is on the road again.", _REG2,
          (~pl.col("at_home")) & (~pl.col("prev_home"))),
    Angle("home_after_road", "Home after two road games",
          "{team} is home after two away.", _REG2,
          pl.col("at_home") & (~pl.col("prev_home")) & (~pl.col("prev2_home"))),
    Angle("rematch", "Rematch with last week's opponent",
          "{team} plays the same opponent again.", _REG2,
          pl.col("opp") == pl.col("prev_opp")),
    Angle("qb_change", "New starting quarterback",
          "{team} has a different starter under center.", _REG2,
          pl.col("qb_change") & pl.col("prev_qb").is_not_null()),
    Angle("spread_3", "Line of exactly 3",
          "The line is 3.", _REG2, pl.col("my_spread").abs() == 3),
    Angle("spread_7", "Line of exactly 7",
          "The line is 7.", _REG2, pl.col("my_spread").abs() == 7),
    Angle("pickem", "Pick'em or within a point",
          "The line is a pick'em.", _REG2, pl.col("my_spread").abs() <= 1),
    Angle("dog_3_or_less", "Underdog of 3 or less",
          "{team} is getting {detail}.", _REG2,
          (pl.col("my_spread") < 0) & (pl.col("my_spread") >= -3)),
    Angle("fav_3_or_less", "Favored by 3 or less",
          "{team} is laying {detail}.", _REG2,
          (pl.col("my_spread") > 0) & (pl.col("my_spread") <= 3)),
    Angle("thursday", "On Thursday",
          "{team} plays Thursday.", _REG2, pl.col("weekday") == "Thursday"),
    Angle("monday", "On Monday",
          "{team} plays Monday.", _REG2, pl.col("weekday") == "Monday"),
    Angle("early_season", "Weeks 1-4",
          "It is early in the season.", _REG2, pl.col("week") <= 4),
    Angle("late_season", "Week 15 onward",
          "It is late in the season.", _REG2, pl.col("week") >= 15),
    Angle("on_grass", "On grass",
          "The game is on grass.", _REG2,
          pl.col("surface").str.contains("grass")),
    Angle("div_fav", "Divisional favorite",
          "{team} is favored in a divisional game.", _REG2,
          pl.col("div_game") & (pl.col("my_spread") > 0)),
)

#: PLAIN ENGLISH FOR EACH, because the label is jargon the first time you meet
#: it. "Off a 20+ loss" tells a handicapper everything and a newcomer nothing,
#: and the reason people bet the split is usually the interesting part — it is
#: nearly always a claim that the market overreacts to something.
PLAIN: dict[str, str] = {
    "blowout_loss": "Beaten by three touchdowns or more last week. The theory "
                    "is that the line overcorrects after an embarrassment.",
    "bad_loss": "Beaten by two touchdowns or more last week.",
    "blowout_win": "Won by three touchdowns or more last week. The theory is "
                   "that the line chases a statement win too far.",
    "two_losses": "Has lost its last two games.",
    "two_wins": "Has won its last two games.",
    "off_bye": "Had a week off, so extra rest and time to prepare.",
    "short_week": "Playing again on four days or fewer, usually a Thursday.",
    "rest_edge": "Has at least three more days off than the opponent.",
    "rest_deficit": "Has at least three fewer days off than the opponent.",
    "home_dog": "At home and still not favored, which says the market rates "
                "the visitor highly.",
    "road_fav": "Favoured despite playing away from home.",
    "big_fav": "Favoured by ten points or more. Big favorites have to win "
               "convincingly, not just win.",
    "big_dog": "Getting ten points or more, so it can lose and still pay.",
    "div_dog": "An underdog against a team it plays twice a year. Familiarity "
               "is supposed to keep these close.",
    "prime": "A national night game.",
    "prime_dog": "An underdog in a national night game.",
    "high_total": "The two teams are expected to score 50 or more between "
                  "them.",
    "low_total": "A game expected to be low-scoring, 40 points or fewer.",
    "off_ot": "Played overtime last week, so an extra quarter of football in "
              "the legs.",
    "indoors": "Played under a roof, so no weather.",
    "three_losses": "Has lost three in a row.",
    "three_wins": "Has won three in a row.",
    "off_cover": "Beat the spread last week, whether or not it won.",
    "off_ats_loss": "Failed to beat the spread last week.",
    "two_covers": "Has beaten the spread two weeks running.",
    "two_non_covers": "Has failed to beat the spread two weeks running.",
    "close_loss": "Lost by eight points or fewer \u2014 one score.",
    "close_win": "Won by eight points or fewer \u2014 one score.",
    "scored_30": "Put up 30 or more last week.",
    "scored_under_14": "Scored fewer than 14 last week.",
    "allowed_30": "Gave up 30 or more last week.",
    "allowed_under_14": "Held the opponent under 14 last week.",
    "third_road": "Away from home a third straight week.",
    "second_road": "Away from home a second straight week.",
    "home_after_road": "Home at last after two straight on the road.",
    "rematch": "Playing the same opponent it played last week.",
    "qb_change": "A different quarterback is starting than last week.",
    "spread_3": "The line is exactly three \u2014 a field goal, the most "
                "common margin in football.",
    "spread_7": "The line is exactly seven \u2014 a touchdown.",
    "pickem": "Essentially a coin flip; neither side is favored.",
    "dog_3_or_less": "A small underdog, getting three points or fewer.",
    "fav_3_or_less": "A small favorite, laying three points or fewer.",
    "thursday": "Playing on Thursday night.",
    "monday": "Playing on Monday night.",
    "early_season": "One of the first four weeks, when form is still unknown.",
    "late_season": "Week 15 or later, when some teams have nothing to play "
                   "for.",
    "on_grass": "Played on natural grass rather than turf.",
    "div_fav": "Favoured against a team it plays twice a year.",
}


#: WHAT KIND OF THING EACH ONE IS. Forty-six rows is past the length anyone
#: reads top to bottom, and the groupings people already think in — how the
#: team has been playing, how rested it is, what the line says, where it is —
#: are the ones worth filtering by.
CATEGORY: dict[str, str] = {
    # How the team has been playing.
    "blowout_loss": "Form", "bad_loss": "Form", "blowout_win": "Form",
    "two_losses": "Form", "two_wins": "Form", "three_losses": "Form",
    "three_wins": "Form", "off_cover": "Form", "off_ats_loss": "Form",
    "two_covers": "Form", "two_non_covers": "Form", "close_loss": "Form",
    "close_win": "Form", "scored_30": "Form", "scored_under_14": "Form",
    "allowed_30": "Form", "allowed_under_14": "Form", "off_ot": "Form",
    # Time off.
    "off_bye": "Rest", "short_week": "Rest", "rest_edge": "Rest",
    "rest_deficit": "Rest",
    # What the price says about them.
    "home_dog": "The line", "road_fav": "The line", "big_fav": "The line",
    "big_dog": "The line", "div_dog": "The line", "div_fav": "The line",
    "spread_3": "The line", "spread_7": "The line", "pickem": "The line",
    "dog_3_or_less": "The line", "fav_3_or_less": "The line",
    # Where they are in the season and who they just saw.
    "third_road": "Spot", "second_road": "Spot", "home_after_road": "Spot",
    "rematch": "Spot", "qb_change": "Spot",
    # Everything about the occasion rather than the team.
    "prime": "Setting", "prime_dog": "Setting", "high_total": "Setting",
    "low_total": "Setting", "indoors": "Setting", "thursday": "Setting",
    "monday": "Setting", "early_season": "Setting", "late_season": "Setting",
    "on_grass": "Setting",
}


#: WITH FIFTY SPLITS AT 95% CONFIDENCE, TWO OR THREE ARE EXPECTED TO CLEAR BY
#: CHANCE ALONE. That is not a caveat on the board, it is a number the board
#: has to print beside the count that actually cleared — "3 of 50 clear" reads
#: as a finding until you know the expectation was 2.5.
EXPECTED_FALSE_POSITIVES = 0.05


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
            pl.col(f"{t}_score").alias("pf"), pl.col(f"{o}_score").alias("pa"),
            pl.col(f"{t}_qb_id").alias("qb"),
            pl.col(f"{t}_coach").alias("coach"),
            pl.col("surface"), pl.col("weekday"),
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
    tg = tg.with_columns([
        (pl.col("cover_by") > 0).alias("covered"),
        (pl.col("gametime").str.slice(0, 2).cast(pl.Int32, strict=False) >= 20)
        .alias("prime"),
    ])
    # LAGS ARE TAKEN OVER (season, team) AND NEVER ACROSS ONE. A team's last
    # game in January is not the one before its opener.
    lag = lambda c, n=1: pl.col(c).shift(n).over(["season", "team"])
    tg = tg.with_columns([
        lag("margin").alias("prev_margin"),
        lag("margin", 2).alias("prev2_margin"),
        lag("margin", 3).alias("prev3_margin"),
        lag("overtime").alias("prev_ot"),
        lag("covered").alias("prev_cover"),
        lag("covered", 2).alias("prev2_cover"),
        lag("pf").alias("prev_pf"),
        lag("pa").alias("prev_pa"),
        lag("at_home").alias("prev_home"),
        lag("at_home", 2).alias("prev2_home"),
        lag("opp").alias("prev_opp"),
        lag("qb").alias("prev_qb"),
        lag("my_spread").alias("prev_spread"),
        # NEXT WEEK'S SPREAD IS NOT AVAILABLE AND THE COLUMN IS GONE.
        #
        # It was here for the look-ahead and sandwich spots, on the reasoning
        # that next week's line is posted before this week kicks off. That is
        # true of look-ahead lines and false of this data: `spread_line` is
        # each game's CLOSING number, and next week's close is set after this
        # week's result is known. So a team whose line improves next week is
        # largely a team that played well this week, and conditioning on it
        # reads the outcome being predicted.
        #
        # The size of it is what gave it away. "Favored, underdog next week"
        # came back at 43.6% over 1,049 games (z=-4.17) and the mirror,
        # "underdog, favorite next week", at 55.4% (z=+3.46) — a nine-point
        # ATS edge persisting for eleven seasons in the most efficient market
        # there is. The symmetry is the tell: both sides point at the team
        # having already played the game.
    ])
    return tg.with_columns([
        (pl.col("qb") != pl.col("prev_qb")).alias("qb_change"),
        # Beat the same opponent already this season, or lost to them.
        pl.col("week").alias("_wk"),
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
            "plain": PLAIN.get(a.id, ""),
            "cat": CATEGORY.get(a.id, "Other"),
            "added": a.added.isoformat(), "mined": a.mined,
            "all": allt, "since": _record(added), "season": _record(cur),
        })
    out.sort(key=lambda r: -r["all"]["pct"])
    return out


def season_games(schedules: pl.DataFrame, season: int) -> dict:
    """The games behind each angle's season record, so "0-5" can be opened.

    A record with no games under it is a number to take on faith. Five losses
    is an anecdote until you can see which five — and on a season sample that
    is the whole of what there is to check.

    Ungraded games are carried with `covered: None` rather than dropped: a
    fixture that has not kicked off is part of the angle this week and leaving
    it out makes the list disagree with the board that pointed at it.
    """
    tg = team_weeks(schedules).filter(pl.col("season") == season)
    out: dict = {}
    for a in ANGLES:
        rows = []
        for r in tg.filter(a.predicate).sort("week").iter_rows(named=True):
            graded = r["cover_by"] is not None and r["cover_by"] != 0
            rows.append({
                "week": r["week"], "team": r["team"], "opp": r["opp"],
                "home": bool(r["at_home"]), "spread": r["my_spread"],
                "pf": r["pf"], "pa": r["pa"],
                "covered": bool(r["covered"]) if graded else None,
                "by": round(float(r["cover_by"]), 1)
                      if r["cover_by"] is not None else None,
            })
        if rows:
            out[a.id] = rows
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
