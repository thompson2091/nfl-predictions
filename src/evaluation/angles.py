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
    #: THE CONDITION IS THE GAME'S, NOT A TEAM'S, so both sides of every
    #: fixture qualify. One of them covers and the other does not, which
    #: makes the record exactly 50.00% by arithmetic rather than by
    #: measurement: prime time is 570-570, on grass 1605-1605, indoors
    #: 822-822, and another ten seasons would not move any of them. The board
    #: keeps them and says so, because a reader who does not know that reads
    #: twelve measured nulls.
    whole_game: bool = False


#: THE FOUNDING TWENTY, all registered the same day, none chosen for being hot.
#: Their all-time record IS their evidence, because nothing selected them.
_REG = date(2026, 9, 28)
#: The second batch, registered together the same evening.
_REG2 = date(2026, 9, 28)
#: The third, measured before being added rather than after.
_REG3 = date(2026, 9, 29)

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
    # THIRTEEN DAYS, NOT TEN. Ten caught every team coming off a Thursday
    # game as well, and there are more of those than there are byes: over
    # 2015-2026, `rest >= 10` was 352 real byes and 378 team-weeks that were
    # nothing of the kind, so most of "Off a bye" was not off a bye. Thirteen
    # separates them exactly -- every bye in the archive is 13 days or more
    # and no mini-bye reaches it -- and the Thursday cases have their own row
    # below, which is the angle that was accidentally being measured here.
    Angle("off_bye", "Off a bye",
          "{team} is off a bye.", _REG, pl.col("rest") >= 13),
    Angle("mini_bye", "Off a Thursday game",
          "{team} played last Thursday, so it has ten days.", _REG,
          (pl.col("rest") >= 10) & (pl.col("rest") < 13)),
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
          "{team} plays in prime time.", _REG, pl.col("prime"),
          whole_game=True),
    Angle("prime_dog", "Prime-time underdog",
          "{team} is a prime-time underdog.", _REG,
          pl.col("prime") & (pl.col("my_spread") < 0)),
    Angle("high_total", "Total of 50+",
          "The total is {detail}.", _REG, pl.col("total_line") >= 50,
          whole_game=True),
    Angle("low_total", "Total of 40 or under",
          "The total is {detail}.", _REG, pl.col("total_line") <= 40,
          whole_game=True),
    Angle("off_ot", "Off an overtime game",
          "{team} went to overtime last week.", _REG, pl.col("prev_ot")),
    Angle("indoors", "Indoors",
          "The game is indoors.", _REG,
          pl.col("roof").is_in(["dome", "closed"]),
          whole_game=True),

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
          "The line is 3.", _REG2, pl.col("my_spread").abs() == 3,
          whole_game=True),
    Angle("spread_7", "Line of exactly 7",
          "The line is 7.", _REG2, pl.col("my_spread").abs() == 7,
          whole_game=True),
    Angle("pickem", "Pick'em or within a point",
          "The line is a pick'em.", _REG2, pl.col("my_spread").abs() <= 1,
          whole_game=True),
    Angle("dog_3_or_less", "Underdog of 3 or less",
          "{team} is getting {detail}.", _REG2,
          (pl.col("my_spread") < 0) & (pl.col("my_spread") >= -3)),
    Angle("fav_3_or_less", "Favored by 3 or less",
          "{team} is laying {detail}.", _REG2,
          (pl.col("my_spread") > 0) & (pl.col("my_spread") <= 3)),
    Angle("thursday", "On Thursday",
          "{team} plays Thursday.", _REG2, pl.col("weekday") == "Thursday",
          whole_game=True),
    Angle("monday", "On Monday",
          "{team} plays Monday.", _REG2, pl.col("weekday") == "Monday",
          whole_game=True),
    Angle("early_season", "Weeks 1-4",
          "It is early in the season.", _REG2, pl.col("week") <= 4,
          whole_game=True),
    Angle("late_season", "Week 15 onward",
          "It is late in the season.", _REG2, pl.col("week") >= 15,
          whole_game=True),
    Angle("on_grass", "On grass",
          "The game is on grass.", _REG2,
          pl.col("surface").str.contains("grass"),
          whole_game=True),
    Angle("div_fav", "Divisional favorite",
          "{team} is favored in a divisional game.", _REG2,
          pl.col("div_game") & (pl.col("my_spread") > 0)),
    # ---- THE THIRD BATCH, AND ALL EIGHT ARE MARKED MINED ------------------
    #
    # Eight, chosen from twenty that were MEASURED FIRST. That is the whole
    # reason for the flag. None was picked for being hot -- the twelve left
    # out went for being duplicates of splits already here, samples too thin
    # to say anything, or whole-game conditions with no side, and against the
    # rate its own composition predicts not one of the twenty was two standard
    # errors from expectation. But the records were seen before the choice was
    # made, and this module's own rule is that a subset chosen after seeing
    # the numbers does not get to be presented as pre-registered.
    #
    # So their all-time record is context and `since` is the evidence: it
    # starts today, on games nobody has seen, and it is the column that
    # settles whether any of these was real.
    #
    # THE FIRST TWO ARE THE CELLS THE BOARD WAS MISSING. `home_dog` and
    # `road_fav` were here from the start; `road_dog` and `home_fav` were not,
    # and they are the two biggest splits in the archive — 1,763 team-games
    # each against 1,100 — and the two furthest from even. Their absence is
    # why the composition effect was invisible: a board that tracks the two
    # flat cells and omits the two steep ones cannot show that side and role
    # are worth four points between them.
    Angle("road_dog", "Road underdog",
          "{team} is an underdog on the road.", _REG3,
          (~pl.col("at_home")) & (pl.col("my_spread") < 0), mined=True),
    Angle("home_fav", "Home favorite",
          "{team} is favored at home.", _REG3,
          pl.col("at_home") & (pl.col("my_spread") > 0), mined=True),
    Angle("revenge", "Lost to them earlier this season",
          "{team} lost to this opponent earlier this season.", _REG3,
          pl.col("revenge"), mined=True),
    Angle("qb_second", "Second start for a new quarterback",
          "{team} starts the same new quarterback a second time.", _REG3,
          pl.col("prev_qb_change") & (~pl.col("qb_change")), mined=True),
    Angle("new_coach", "New head coach",
          "{team} has a different head coach than last season.", _REG3,
          pl.col("coach") != pl.col("_last_coach"), mined=True),
    Angle("road_after_two_home", "First road game after two at home",
          "{team} is on the road after two straight at home.", _REG3,
          (~pl.col("at_home")) & pl.col("prev_home") & pl.col("prev2_home"), mined=True),
    Angle("fav_after_dog", "Favored after being an underdog",
          "{team} was an underdog last week and is favored now.", _REG3,
          (pl.col("my_spread") > 0) & (pl.col("prev_spread") < 0), mined=True),
    Angle("dog_after_fav", "Underdog after being favored",
          "{team} was favored last week and is an underdog now.", _REG3,
          (pl.col("my_spread") < 0) & (pl.col("prev_spread") > 0), mined=True),

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
    "mini_bye": "Played on Thursday and so has ten days, not seven — a "
                "mini-bye, without the week off.",
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
    "road_dog": "An underdog playing away from home \u2014 the most common "
                "spot there is, and the one furthest from even.",
    "home_fav": "Favored at home, which is the other side of the same coin.",
    "revenge": "Already lost to this opponent once this season.",
    "qb_second": "The new quarterback\u2019s second start, rather than his "
                 "first.",
    "new_coach": "A different head coach than the one who finished last "
                 "season.",
    "road_after_two_home": "Away after two straight home games.",
    "fav_after_dog": "Getting points last week, laying them this week.",
    "dog_after_fav": "Laying points last week, getting them this week.",
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
    "off_bye": "Rest", "mini_bye": "Rest", "short_week": "Rest",
    "rest_edge": "Rest",
    "rest_deficit": "Rest",
    # What the price says about them.
    "home_dog": "The line", "road_fav": "The line", "big_fav": "The line",
    "big_dog": "The line", "div_dog": "The line", "div_fav": "The line",
    "spread_3": "The line", "spread_7": "The line", "pickem": "The line",
    "dog_3_or_less": "The line", "fav_3_or_less": "The line",
    "road_dog": "The line", "home_fav": "The line",
    "fav_after_dog": "The line", "dog_after_fav": "The line",
    # Where they are in the season and who they just saw.
    "third_road": "Spot", "second_road": "Spot", "home_after_road": "Spot",
    "rematch": "Spot", "qb_change": "Spot", "revenge": "Spot",
    "qb_second": "Spot", "new_coach": "Spot",
    "road_after_two_home": "Spot",
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
            pl.col("game_id"),
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
    tg = tg.with_columns([
        (pl.col("qb") != pl.col("prev_qb")).alias("qb_change"),
        pl.col("week").alias("_wk"),
    ])
    # THE SECOND START, which is a different spot from the first. Lagged from
    # `qb_change` rather than compared to the quarterback two weeks ago, so a
    # team that changed twice running is not counted as settled.
    tg = tg.with_columns(
        pl.col("qb_change").shift(1).over(["season", "team"])
          .alias("prev_qb_change"))
    # A NEW HEAD COACH, against whoever finished the previous season. Compared
    # to last season rather than to last week: a coach fired mid-season shows
    # up in `coach` immediately, and calling that "new" every week until
    # January would make the split a measure of how long ago the firing was.
    last = (tg.group_by(["season", "team"]).agg(pl.col("coach").last())
              .with_columns((pl.col("season") + 1).alias("season"))
              .rename({"coach": "_last_coach"}))
    tg = tg.join(last, on=["season", "team"], how="left")
    # LOST TO THIS OPPONENT EARLIER THIS SEASON. Divisional sides meet twice
    # and the second meeting is the one people call a revenge spot. Only
    # EARLIER weeks count, which is what keeps it backward-looking: joining on
    # the pair alone would mark the first meeting as revenge for the second.
    lost = (tg.filter(pl.col("margin") < 0)
              .select(["season", "team", "opp",
                       pl.col("week").alias("_lost_wk")])
              .unique(subset=["season", "team", "opp"], keep="first"))
    tg = tg.join(lost, on=["season", "team", "opp"], how="left")
    return tg.with_columns(
        (pl.col("_lost_wk").is_not_null()
         & (pl.col("_lost_wk") < pl.col("week"))).fill_null(False)
        .alias("revenge"))


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
            "whole_game": a.whole_game,
            "all": allt, "since": _record(added), "season": _record(cur),
        })
    out.sort(key=lambda r: -r["all"]["pct"])
    return out


def season_splits(schedules: pl.DataFrame) -> dict:
    """Wins and losses per angle PER SEASON, so any start year can be asked.

    The page lets a reader say "since 2020" rather than taking 2015 on trust,
    and the honest way to serve that is to ship the seasons and add them up
    where the question is asked. Re-measuring per start year on this side
    would mean eleven copies of every record, and computing it from a single
    total is not possible at all — you cannot subtract seasons you did not
    keep.

    Tiny on the wire: a couple of integers per angle per season.
    """
    tg = team_weeks(schedules).filter(
        pl.col("cover_by").is_not_null() & (pl.col("cover_by") != 0))
    out: dict = {}
    for a in ANGLES:
        g = (tg.filter(a.predicate)
             .group_by("season")
             .agg([pl.col("covered").sum().alias("w"), pl.len().alias("n")])
             .sort("season"))
        rows = {}
        for r in g.iter_rows(named=True):
            rows[str(r["season"])] = [int(r["w"]), int(r["n"]) - int(r["w"])]
        if rows:
            out[a.id] = rows
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
                "game_id": r["game_id"],
                # THE BOARD KEYS GAMES BY `AWAY_HOME`, which is the odds
                # archive's id; the schedule's is `SEASON_WEEK_AWAY_HOME`.
                # Shipping only the long one is why every fixture on this
                # list linked to "that game is not on this week's board" —
                # the two ids never matched. Carry both rather than have
                # the page parse an id format it does not own.
                "gid": "_".join(str(r["game_id"]).split("_")[2:]),
                "home": bool(r["at_home"]), "spread": r["my_spread"],
                "pf": r["pf"], "pa": r["pa"],
                "covered": bool(r["covered"]) if graded else None,
                # PLAYED AND UNGRADED IS A PUSH, NOT A FIXTURE. Both arrive
                # as `covered: None` — one because the game landed exactly on
                # the number, the other because it has not kicked off — and
                # the list showed both as "to play". SEA laid 3 in week 1 and
                # won by 3; the row said SEA had yet to play.
                "played": r["pf"] is not None,
                "by": round(float(r["cover_by"]), 1)
                      if r["cover_by"] is not None else None,
            })
        if rows:
            out[a.id] = rows
    return out


def team_splits(schedules: pl.DataFrame) -> dict:
    """Wins and losses per angle PER TEAM PER SEASON.

    **THIS IS WHAT MAKES A WHOLE-GAME CONDITION WORTH KEEPING.** League-wide,
    `on_grass` is 1605-1605 and always will be: both teams in a grass game are
    on grass, so one covers and the other does not. Per team it is one side of
    each game and can be anything — San Francisco is 67-72 on grass, which is
    a record rather than an identity.

    Shipped per season rather than as a total, for the same reason the league
    splits are: the page recomputes any start year from these without another
    measurement. 14,436 leaf records, about 205 KB.

    THE SAMPLES ARE SMALL and nothing here pretends otherwise — the median
    team-and-angle pair is 25 graded games, where the interval runs about
    forty points wide. The page prints the record and the interval beside
    every rate, and the tint still only fires when the lower bound clears.
    """
    tg = team_weeks(schedules)
    out: dict = {}
    for a in ANGLES:
        f = (tg.filter(a.predicate)
               .filter(pl.col("cover_by").is_not_null()
                       & (pl.col("cover_by") != 0))
               .group_by(["team", "season"])
               .agg([pl.col("covered").sum().alias("w"), pl.len().alias("n")]))
        for r in f.iter_rows(named=True):
            (out.setdefault(r["team"], {}).setdefault(a.id, {})
                [str(r["season"])]) = [int(r["w"]), int(r["n"] - r["w"])]
    return out


#: The four cells a team-game falls into: home or away, favored or not.
#: A pick'em is neither, and there are four of them in eleven seasons.
CELLS = ("AD", "AF", "HD", "HF")


def _cell() -> pl.Expr:
    side = pl.when(pl.col("at_home")).then(pl.lit("H")).otherwise(pl.lit("A"))
    role = (pl.when(pl.col("my_spread") > 0).then(pl.lit("F"))
              .when(pl.col("my_spread") < 0).then(pl.lit("D"))
              .otherwise(pl.lit("P")))
    return (side + role).alias("cell")


def baseline(schedules: pl.DataFrame) -> dict:
    """What each split's own composition already predicts, before the angle.

    **SIDE AND ROLE ARE WORTH FOUR POINTS BETWEEN THEM.** Road underdogs cover
    52.07% and home favorites 47.93%, over 1,763 team-games each. So a split
    made mostly of favorites looks bad without saying anything, and one made
    of road dogs looks good for the same non-reason. Measured against a flat
    50%, "Favored after being an underdog" reads as a five-point fade on 1,108
    games; measured against what its own mix predicts, it is under two points
    and inside noise.

    Returns `{"cells": {season: {cell: [w, n]}}, "mix": {angle: {season:
    [n per cell]}}}`, both per season so the page can recompute the expectation
    for whatever start year is chosen without another measurement. Four counts
    an angle-season, which is a few kilobytes.

    Not one of the fifty-five measured angles is two standard errors from its
    own baseline. Chance alone would put two or three there.
    """
    g = (team_weeks(schedules)
         .filter(pl.col("cover_by").is_not_null() & (pl.col("cover_by") != 0))
         .with_columns(_cell()))
    cells: dict = {}
    for r in (g.group_by(["season", "cell"])
               .agg([pl.col("covered").sum().alias("w"), pl.len().alias("n")])
               .iter_rows(named=True)):
        if r["cell"] in CELLS:
            cells.setdefault(str(r["season"]), {})[r["cell"]] = [
                int(r["w"]), int(r["n"])]
    mix: dict = {}
    for a in ANGLES:
        f = g.filter(a.predicate)
        if f.is_empty():
            continue
        by: dict = {}
        for r in f.group_by(["season", "cell"]).len().iter_rows(named=True):
            if r["cell"] not in CELLS:
                continue
            row = by.setdefault(str(r["season"]), [0, 0, 0, 0])
            row[CELLS.index(r["cell"])] = int(r["len"])
        if by:
            mix[a.id] = by
    # THE SAME MIX PER TEAM, so the column does not have to vanish when one is
    # chosen. A club's own games sit in different cells from the league's --
    # a perennial favorite is mostly HF and would be credited with a fade it
    # has not earned -- and a baseline that disappears where it is needed is
    # worse than none. 304 KB, against a payload near five megabytes.
    team_mix: dict = {}
    for a in ANGLES:
        f = g.filter(a.predicate)
        if f.is_empty():
            continue
        for r in (f.group_by(["team", "season", "cell"]).len()
                   .iter_rows(named=True)):
            if r["cell"] not in CELLS:
                continue
            row = (team_mix.setdefault(r["team"], {}).setdefault(a.id, {})
                           .setdefault(str(r["season"]), [0, 0, 0, 0]))
            row[CELLS.index(r["cell"])] = int(r["len"])
    return {"cells": cells, "mix": mix, "team_mix": team_mix}


def qualifying(schedules: pl.DataFrame, season: int) -> dict:
    """Which angles each side carries, KEYED BY GAME.

    Keyed by team and computed for one week, this was wrong twice over. The
    board carries whatever the books have posted, which in week 3 of 2026 was
    thirty fixtures spanning two weeks, so a week-3 answer was printed under
    week-4 games: ARI came off a 24-point loss in week 3 and the card for ARI
    at NYG, a week-4 game, said "ARI · Off a 20+ loss" when ARI's last result
    was a six-point loss. And keying by team alone left nothing to check it
    against — the card looked up the team and printed whatever came back.

    So every week of the season is measured, and each entry is filed under the
    game it belongs to. A card can then ask only for its own game, and a week
    that has not been measured yields nothing rather than the wrong thing.
    """
    tg = team_weeks(schedules).filter(pl.col("season") == season)
    hits: dict = {}
    for a in ANGLES:
        for r in tg.filter(a.predicate).iter_rows(named=True):
            gid = "_".join(str(r["game_id"]).split("_")[2:])
            hits.setdefault(gid, []).append([r["team"], a.id])
    return hits
