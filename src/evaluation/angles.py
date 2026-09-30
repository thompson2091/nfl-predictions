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

#: AND BELOW THIS IT IS NOT TINTED, however good it looks.
#:
#: Clearing break-even at the bottom of the interval is the board's strongest
#: statement and for fifty-eight angles nothing had ever earned it. The first
#: row that did was `pre_bye_div` at 58-28 — eighty-six games, and a subset
#: picked after seeing its parent, which is a fork that could as easily have
#: been home/away or favorite/underdog. Tinting that green would have been the
#: board making its loudest claim on its thinnest evidence, which is the
#: opposite of what every other guard here does.
#:
#: Three hundred is where the interval comes in around five points wide rather
#: than twenty. The row still shows its rate, its record and its range; it
#: just does not get the color.
TINT_MIN_GAMES = 300


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
#: The bye pair, asked for and measured the same day.
_REG4 = date(2026, 9, 30)
#: The ninth batch: the opponent's situation, and the rest of a list of ten.
_REG5 = date(2026, 9, 30)
#: What survived of a claim that did not check out.
_REG6 = date(2026, 9, 30)
#: The cell the divisional rows were averaging over.
_REG7 = date(2026, 9, 30)
#: Three mirrors the board was missing, found by auditing it for inverses.
_REG8 = date(2026, 9, 30)
#: The complementary seven, added so a game card reads the same from either
#: sideline. See the block above `div_home_fav`.
_REG9 = date(2026, 9, 30)
#: The quarterback against one opponent, which is a dimension nothing else
#: here had: the player rather than the club.
_REG10 = date(2026, 9, 30)

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
    # ---- ONE OF TWO ASKED FOR -----------------------------------------
    #
    # The other was "divisional dog, any day", which is `div_dog` above:
    # 548-498 over 1,046 games, the same split under the name it already had.
    #
    # This one is what is left of a claim that did not survive checking.
    # "Divisional underdogs on Thursday in weeks 4, 5 and 6 since 2016 are
    # 26-16" needs forty-two games, and there are twenty-nine Thursday games
    # of ANY kind in that window -- fourteen of them divisional, going 5-9.
    # Widened to every week the split is real and says nothing much, which is
    # the version worth tracking.
    #
    # A HUNDRED AND TWO GAMES CANNOT GO GREEN, by `TINT_MIN_GAMES`, and should
    # not: an interval on a sample this size runs twenty points wide.
    Angle("div_dog_thu", "Divisional underdog on Thursday",
          "{team} is a divisional underdog on a Thursday.", _REG6,
          pl.col("div_game") & (pl.col("my_spread") < 0)
          & (pl.col("weekday") == "Thursday"), mined=True),

    # ---- THE CELL THE OTHER DIVISIONAL ROWS WERE AVERAGING OVER -----------
    #
    # Split divisional games four ways and the result sits in exactly one box:
    #
    #     home dog   416   208-208   50.00%
    #     home fav   630   290-340   46.03%
    #     road dog   630   340-290   53.97%
    #     road fav   416   208-208   50.00%
    #
    # BOTH FLAT CELLS ARE EXACTLY EVEN, on the same 416 games. That is why
    # "divisional underdog" (home dog + road dog) and "divisional road team"
    # (road dog + road fav) both print 548-498: each is this cell plus a cell
    # that contributes nothing. The label on the board was never what was
    # being measured.
    #
    # Nor is Thursday: the divisional tilt is 46.97/53.03 on Thursday against
    # 46.03/53.97 on every other day, and Thursday on its own is 97-95. See
    # `div_dog_thu` above -- Thursday slices this cell to a tenth and adds no
    # information.
    #
    # IT STILL DOES NOT CLEAR. The lower bound is 50.06% against a 52.38%
    # break-even, so this row prints as a near miss, which is the point of
    # having it: `div_dog` and `div_home_dog` cannot show where their own
    # numbers come from, and this one can.
    Angle("div_road_dog", "Divisional road underdog",
          "{team} is a road underdog against a divisional rival.", _REG7,
          pl.col("div_game") & (~pl.col("at_home"))
          & (pl.col("my_spread") < 0), mined=True),

    # ---- TEN MEASURED, NINE ADDED -----------------------------------------
    #
    # THE FIRST THREE ARE ABOUT THE OPPONENT, which is a dimension none of the
    # sixty above has: they all ask what shape the team is in, and none asks
    # what shape the team across from it is in. Both land on 50%, which is
    # only sayable because both are tracked.
    #
    # `div_home_dog` IS WORTH A ROW BECAUSE IT IS 50.00%. It is the claim that
    # divisional home dogs are live, and over eleven seasons it is 208-208 —
    # an answer that can only be given if the question is on the board.
    #
    # THE TENTH WAS LEFT OUT. "Divisional home underdog with a low total"
    # covers 57.76% under 42 and 51.85% under 44, so the threshold picks the
    # answer, and the cuts are nested subsets of a split that is exactly even.
    # Shipping it would ship a choice of number as if it were football.
    Angle("opp_off_bye", "Facing a team off a bye",
          "{team} plays an opponent coming off a bye.", _REG5,
          pl.col("opp_rest") >= 13, mined=True),
    Angle("opp_short_week", "Facing a team on a short week",
          "{team} plays an opponent on a short week.", _REG5,
          pl.col("opp_rest") <= 4, mined=True),
    Angle("opp_blowout_loss", "Facing a team off a 20+ loss",
          "{team} plays an opponent beaten by {detail} last week.", _REG5,
          pl.col("opp_prev_margin") <= -20, mined=True),
    Angle("div_home_dog", "Divisional home underdog",
          "{team} is a home underdog against a divisional rival.", _REG5,
          pl.col("div_game") & pl.col("at_home") & (pl.col("my_spread") < 0),
          mined=True),
    Angle("div_back_to_back", "Second divisional game in a row",
          "{team} plays a second straight divisional game.", _REG5,
          pl.col("div_game") & pl.col("prev_div"), mined=True),
    Angle("close_loss_3", "Off a loss by a field goal or less",
          "{team} lost by {detail} last week.", _REG5,
          (pl.col("prev_margin") < 0) & (pl.col("prev_margin") >= -3),
          mined=True),
    Angle("close_win_3", "Off a win by a field goal or less",
          "{team} won by {detail} last week.", _REG5,
          (pl.col("prev_margin") > 0) & (pl.col("prev_margin") <= 3),
          mined=True),
    Angle("bad_team_favored", "Losing record but favored",
          "{team} is favored with a losing record.", _REG5,
          (pl.col("losses_before") > pl.col("wins_before"))
          & (pl.col("my_spread") > 0) & (pl.col("week") >= 5), mined=True),
    Angle("good_team_dog", "Winning record but an underdog",
          "{team} is an underdog with a winning record.", _REG5,
          (pl.col("wins_before") > pl.col("losses_before"))
          & (pl.col("my_spread") < 0) & (pl.col("week") >= 5), mined=True),

    # ---- THE BYE PAIR, added on request and measured before adding ---------
    #
    # `off_bye` was already here; these are the three it did not cover. Marked
    # mined for the same reason as the batch above: the records were seen
    # before the choice was made.
    #
    # `pre_bye_div` IS THE FIRST ROW EVER TO CLEAR BREAK-EVEN at the bottom of
    # its interval, at 58-28 over eleven seasons. It is also 86 games, and a
    # subset picked after seeing its parent at 55.65% — a fork that could as
    # easily have been home/away or favorite/underdog. See `TINT_MIN_GAMES`
    # for what the board does about that.
    Angle("bye_div", "Off a bye, divisional",
          "{team} is off a bye against a divisional rival.", _REG4,
          (pl.col("rest") >= 13) & pl.col("div_game"), mined=True),
    Angle("pre_bye", "The week before a bye",
          "{team} plays its last game before a bye.", _REG4,
          pl.col("pre_bye"), mined=True),
    Angle("pre_bye_div", "Before a bye, divisional",
          "{team} plays a divisional rival in its last game before a bye.",
          _REG4, pl.col("pre_bye") & pl.col("div_game"), mined=True),
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

    # ---- THE THREE MIRRORS THE BOARD WAS ACTUALLY MISSING ----------------
    #
    # An audit for angles with no inverse turns up two kinds, and only one of
    # them is worth a row.
    #
    # MOST MISSING INVERSES ARE THE SAME GAMES FLIPPED. "Divisional home
    # favorite" is `div_road_dog` scored from the other sideline -- the same
    # 630 games, 290-340 instead of 340-290 -- and so are prime-time favorite,
    # outdoors, on turf, and facing a team before its bye. The board already
    # prints four such pairs (`home_dog`/`road_fav`, `home_fav`/`road_dog`,
    # `div_dog`/`div_fav`, `off_bye`/`opp_off_bye`), which is a presentation
    # choice; repeating it would grow the count of angles without growing the
    # number of things measured.
    #
    # THESE THREE ARE NOT THAT. Each covers games the angle it mirrors does
    # not, so each can disagree with it, and two of them do.
    #
    # `good_win` closes a tier that was asymmetric: losses were tracked at
    # both 14+ and 20+, wins only at 20+, so the board could say a bad loss
    # was priced wrong without being able to say the same of a good win.
    #
    # `second_home` and `third_home` are not the arithmetic complements of
    # `second_road` and `third_road` -- 811 games against 814, and both under
    # 50%. Two straight home games and two straight road games BOTH cover less
    # than half the time, which is only visible with both tracked, and which
    # no single "travel hurts" story explains.
    Angle("good_win", "Off a 14+ win",
          "{team} won by {detail} last week.", _REG8,
          pl.col("prev_margin") >= 14, mined=True),
    Angle("second_home", "Second straight home game",
          "{team} is home again.", _REG8,
          pl.col("at_home") & pl.col("prev_home"), mined=True),
    Angle("third_home", "Third straight home game",
          "{team} is home a third straight week.", _REG8,
          pl.col("at_home") & pl.col("prev_home") & pl.col("prev2_home"),
          mined=True),

    # ---- THE QUARTERBACK AGAINST ONE OPPONENT -----------------------------
    #
    # A NEW DIMENSION, not another cut of an old one. Every angle above is
    # about a club: how it has been playing, how rested it is, what its line
    # says. These three are about the man taking the snaps, across seasons and
    # across rosters -- Deshaun Watson is 0-3 against Pittsburgh in three
    # seasons for two clubs, and `revenge` cannot see it because `revenge` is
    # one club within one season.
    #
    # THE FACT THAT PROMPTED THEM IS NOT EVIDENCE, and the board should be the
    # thing that says so. A quarterback against one opponent is 2,452 cells at
    # a MEDIAN OF TWO GAMES; on the 169 with six or more, the spread between
    # them is 18.0% against 17.4% from chance alone, a ratio of 1.03. Three
    # straight losses happens to a coin one time in eight. So the per-player
    # record stays off the board and the league-wide spot goes on it, which is
    # the only version of the question that has a sample.
    #
    # NEITHER SIDE CLEARS. Never beaten them is a fade at 46.28% on 242 games
    # and never lost to them is 53.29% on 319 -- over the games floor, and its
    # lower bound is 47.8%, so no tint. The three-meeting cut looks stronger
    # and is not: it takes 242 games down to 70.
    #
    # SINCE 2015 ONLY, which the plain words have to say. The archive starts
    # there, so "has never beaten them" means not in eleven seasons, not never
    # in a career. Watson's 0-3 is wholly inside the window; a veteran's
    # earlier meetings are invisible and the row cannot tell the difference.
    Angle("qb_never_beat", "Quarterback has never beaten them",
          "{team}’s quarterback has never beaten this opponent.", _REG10,
          pl.col("qb_never_beat"), mined=True),
    Angle("qb_never_lost", "Quarterback has never lost to them",
          "{team}’s quarterback has never lost to this opponent.",
          _REG10, pl.col("qb_never_lost"), mined=True),
    Angle("opp_qb_never_beat", "Facing a quarterback who has never beaten them",
          "{team} faces a quarterback who has never beaten it.", _REG10,
          pl.col("opp_qb_never_beat"), mined=True),

    # ---- THE COMPLEMENTARY SEVEN ------------------------------------------
    #
    # ADDED FOR THE GAME CARD, NOT FOR THE BOARD. Each one below is an angle
    # already here, scored from the other sideline: the same games, the same
    # grading, the record subtracted from 100%. On the board that is a second
    # row saying what the first row said. On a game's Odds tab it is not, and
    # the Odds tab is the reason they are here.
    #
    # THE CASE, from the card that prompted it -- NE at BUF, week 4 of 2026.
    # NE carried `Divisional road underdog 53.97%`. BUF carried `Divisional
    # favorite 47.61%` and `Home favorite 47.93%` and nothing else, because the
    # cell it was actually in -- divisional home favorite, 46.03% -- had no
    # row. The underdog got the sharp number and the favorite got two blends.
    # A card is read one game at a time, and on one game the complement is not
    # a restatement, it is the other half of the fixture.
    #
    # THE COST IS PAID IN CARD LENGTH, and it is not small: `outdoors` fires on
    # 70.3% of sides and `on_turf` on 40.6%, both of them 50.00% by arithmetic,
    # so most cards grow by two rows that cannot say anything. A side already
    # carries eleven angles at the median and seventeen at the worst. That
    # trade was put to the reader who asked for these and taken deliberately:
    # symmetry everywhere beats precision in three places and a gap elsewhere.
    #
    # NOTHING HERE IS EVIDENCE OF ANYTHING. Seven rows that are arithmetic
    # complements of seven existing rows add seven to the board's count and
    # zero to the number of independent splits it tracks. Do not read the
    # board's length as a count of findings; `EXPECTED_FALSE_POSITIVES` is
    # computed from the splits, and these are not new ones.
    Angle("div_home_fav", "Divisional home favorite",
          "{team} is favored at home against a divisional rival.", _REG9,
          pl.col("div_game") & pl.col("at_home") & (pl.col("my_spread") > 0),
          mined=True),
    Angle("div_road_fav", "Divisional road favorite",
          "{team} is favored on the road against a divisional rival.", _REG9,
          pl.col("div_game") & (~pl.col("at_home"))
          & (pl.col("my_spread") > 0), mined=True),
    Angle("prime_fav", "Prime-time favorite",
          "{team} is favored in prime time.", _REG9,
          pl.col("prime") & (pl.col("my_spread") > 0), mined=True),
    Angle("beat_them", "Beat them earlier this season",
          "{team} beat this opponent earlier this season.", _REG9,
          pl.col("beat_them"), mined=True),
    Angle("opp_pre_bye", "Facing a team before its bye",
          "{team} plays an opponent in its last game before a bye.", _REG9,
          pl.col("opp_pre_bye"), mined=True),
    # THE LAST TWO ARE WHOLE-GAME CONDITIONS and are flagged as such: both
    # sides play outdoors, both sides play on turf, so one covers and the other
    # does not and the record is 2045-2045 and 1261-1261 for as long as the
    # sport is played. `indoors` and `on_grass` have carried the flag from the
    # start for the same reason.
    Angle("outdoors", "Outdoors",
          "The game is outdoors.", _REG9,
          # The positive list, not the negation of `indoors`: a roof value
          # nobody has seen yet should fall through both rows visibly rather
          # than be swept into this one.
          pl.col("roof").is_in(["outdoors", "open"]),
          whole_game=True, mined=True),
    Angle("on_turf", "On turf",
          "The game is on turf.", _REG9,
          ~pl.col("surface").str.contains("grass"),
          whole_game=True, mined=True),
)

#: PLAIN ENGLISH FOR EACH, because the label is jargon the first time you meet
#: it. "Off a 20+ loss" tells a handicapper everything and a newcomer nothing,
#: and the reason people bet the split is usually the interesting part — it is
#: nearly always a claim that the market overreacts to something.
PLAIN: dict[str, str] = {
    "blowout_loss": "Beaten by three touchdowns or more last week. The theory "
                    "is that the line overcorrects after an embarrassment.",
    "bad_loss": "Beaten by two touchdowns or more last week.",
    "good_win": "Won by two touchdowns or more last week.",
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
    "second_home": "At home a second straight week.",
    "qb_never_beat": "Their starting quarterback has faced this opponent at "
                     "least twice since 2015 and never won.",
    "qb_never_lost": "Their starting quarterback has faced this opponent at "
                     "least twice since 2015 and never lost.",
    "opp_qb_never_beat": "The quarterback they face has tried at least twice "
                         "since 2015 and never beaten them.",
    "third_home": "At home a third straight week.",
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
    "div_dog_thu": "A divisional underdog in a Thursday night game.",
    "div_road_dog": "An underdog on the road against a team it plays twice a year.",
    "div_home_fav": "Favoured at home against a team it plays twice a year.",
    "div_road_fav": "Favoured on the road against a team it plays twice a year.",
    "prime_fav": "Favoured in a night game the whole country is watching.",
    "beat_them": "Already beat this opponent once this season.",
    "opp_pre_bye": "Their opponent plays its last game before a week off.",
    "outdoors": "Played in the open air rather than under a roof.",
    "on_turf": "Played on artificial turf rather than natural grass.",
    "opp_off_bye": "Their opponent had a week off; they did not.",
    "opp_short_week": "Their opponent is playing on four days\u2019 rest or "
                      "fewer.",
    "opp_blowout_loss": "Their opponent was beaten by three touchdowns or "
                        "more last week.",
    "div_home_dog": "A home underdog against a team it plays twice a year.",
    "div_back_to_back": "A second divisional game in consecutive weeks.",
    "close_loss_3": "Lost by three points or fewer last week.",
    "close_win_3": "Won by three points or fewer last week.",
    "bad_team_favored": "Favored despite having lost more than it has won.",
    "good_team_dog": "Getting points despite having won more than it has "
                     "lost.",
    "bye_div": "Off a bye, against a team it plays twice a year.",
    "pre_bye": "Their last game before a week off.",
    "pre_bye_div": "Their last game before a week off, against a divisional "
                   "rival.",
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


#: THE ORDER THE FILTER OFFERS THEM IN, which is not the order they happen to
#: appear in. `measure()` sorts its rows by percentage, so a page that
#: collected categories as it met them would reorder its own dropdown every
#: time a record moved. Shipped from here instead, the way
#: `matchup_stats.GROUPS` is the source of truth for metric groups.
#:
#: Roughly outside-in: what the line says, then how the team has been playing,
#: then where and when, then the situation, then rest, then the other team.
CATEGORIES: tuple[str, ...] = (
    "The line", "Form", "Setting", "Spot", "Rest", "Opponent",
)

#: WHAT KIND OF THING EACH ONE IS. Forty-six rows is past the length anyone
#: reads top to bottom, and the groupings people already think in — how the
#: team has been playing, how rested it is, what the line says, where it is —
#: are the ones worth filtering by.
#:
#: EVERY ANGLE NEEDS ONE, and a test says so. An angle added without an entry
#: falls to "Other", which no filter offers, so it stops being findable on
#: either surface without anything failing.
CATEGORY: dict[str, str] = {
    # How the team has been playing.
    "blowout_loss": "Form", "bad_loss": "Form", "blowout_win": "Form",
    "good_win": "Form",
    "two_losses": "Form", "two_wins": "Form", "three_losses": "Form",
    "three_wins": "Form", "off_cover": "Form", "off_ats_loss": "Form",
    "two_covers": "Form", "two_non_covers": "Form", "close_loss": "Form",
    "close_win": "Form", "scored_30": "Form", "scored_under_14": "Form",
    "allowed_30": "Form", "allowed_under_14": "Form", "off_ot": "Form",
    # Time off.
    "off_bye": "Rest", "mini_bye": "Rest", "short_week": "Rest",
    "bye_div": "Rest", "pre_bye": "Rest", "pre_bye_div": "Rest",
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
    "second_home": "Spot", "third_home": "Spot",
    "qb_never_beat": "Spot", "qb_never_lost": "Spot",
    "opp_qb_never_beat": "Opponent",
    # THE OPPONENT is its own kind: every other angle here asks what shape the
    # team is in, and these three ask about the team across from it.
    "opp_off_bye": "Opponent", "opp_short_week": "Opponent",
    "opp_blowout_loss": "Opponent",
    "div_home_dog": "The line", "bad_team_favored": "The line",
    "div_dog_thu": "The line", "div_road_dog": "The line",
    "div_home_fav": "The line", "div_road_fav": "The line",
    "prime_fav": "Setting", "outdoors": "Setting", "on_turf": "Setting",
    "beat_them": "Spot", "opp_pre_bye": "Opponent",
    "good_team_dog": "The line",
    "close_loss_3": "Form", "close_win_3": "Form",
    "div_back_to_back": "Spot",
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
    tg = tg.with_columns(
        (pl.col("_lost_wk").is_not_null()
         & (pl.col("_lost_wk") < pl.col("week"))).fill_null(False)
        .alias("revenge"))
    # AND BEAT THEM EARLIER THIS SEASON, which is the same rematch seen from
    # the other sideline. Only one side of a rematch can hold it -- two teams
    # meet at most twice in a regular season, so there is one prior meeting and
    # somebody won it -- and a tie leaves it False on both.
    won = (tg.filter(pl.col("margin") > 0)
             .select(["season", "team", "opp",
                      pl.col("week").alias("_won_wk")])
             .unique(subset=["season", "team", "opp"], keep="first"))
    tg = tg.join(won, on=["season", "team", "opp"], how="left")
    tg = tg.with_columns(
        (pl.col("_won_wk").is_not_null()
         & (pl.col("_won_wk") < pl.col("week"))).fill_null(False)
        .alias("beat_them"))
    # THE WEEK BEFORE A BYE, and it is not a look-ahead.
    #
    # Byes are on the schedule when it is published in the spring, so a team
    # playing its last game before one is a fact available months in advance —
    # unlike a closing line, which is set after the previous week is played and
    # is what got the look-ahead angles removed.
    #
    # COMPUTED FROM THE FULL SCHEDULE, not from the frame above. That one drops
    # games with no closing spread, and a dropped row leaves a gap in the week
    # numbers that looks exactly like a bye: 352 of the real 384 were found
    # that way, and the 32 it missed were missing for a reason unrelated to
    # byes.
    full = (schedules.filter(pl.col("game_type") == "REG")
            .select(["season", "week", "home_team", "away_team"]))
    long = pl.concat([
        full.select(["season", "week", pl.col(t).alias("team")])
        for t in ("home_team", "away_team")]).unique()
    pre = (long.sort(["season", "team", "week"])
           .with_columns(pl.col("week").shift(-1).over(["season", "team"])
                         .alias("_nxt"))
           .filter(pl.col("_nxt").is_not_null()
                   & (pl.col("_nxt") > pl.col("week") + 1))
           .select(["season", "team", "week"])
           .with_columns(pl.lit(True).alias("pre_bye")))
    tg = (tg.join(pre, on=["season", "team", "week"], how="left")
            .with_columns(pl.col("pre_bye").fill_null(False)))
    # THIS QUARTERBACK AGAINST THIS OPPONENT, across seasons and rosters.
    #
    # `revenge` is the team's record and only within one season. This follows
    # the PLAYER: Deshaun Watson is 0-3 against Pittsburgh over three seasons
    # and two clubs, and nothing else here can see that.
    #
    # NOT A LOOK-AHEAD. The prior record counts PLAYED meetings only, before
    # this one, and the starter is announced before kickoff -- which is the
    # same footing `qb_change` and `qb_second` already stand on.
    #
    # COUNTED ON THIS FRAME, not the full schedule, and that is safe here
    # where it was not for `pre_bye`: the 208 games this frame drops for
    # having no closing spread are exactly the 208 with no starter named, all
    # of them 2026 fixtures nobody has played. No prior meeting is lost.
    #
    # GLOBAL CHRONOLOGICAL ORDER, not per team: a quarterback's meetings with
    # one opponent run across seasons and clubs, so the running total has to
    # be taken over (quarterback, opponent) with the frame in date order.
    tg = tg.sort(["season", "week"]).with_columns([
        pl.col("margin").is_not_null().cast(pl.Int8).alias("_qbp"),
        ((pl.col("margin") > 0).fill_null(False)).cast(pl.Int8).alias("_qbw"),
        ((pl.col("margin") < 0).fill_null(False)).cast(pl.Int8).alias("_qbl"),
    ])
    qk = ["qb", "opp"]
    tg = tg.with_columns([
        (pl.col("_qbp").cum_sum().over(qk) - pl.col("_qbp")).alias("qb_seen"),
        (pl.col("_qbw").cum_sum().over(qk) - pl.col("_qbw")).alias("qb_won"),
        (pl.col("_qbl").cum_sum().over(qk) - pl.col("_qbl")).alias("qb_lost"),
    ]).drop(["_qbp", "_qbw", "_qbl"])
    # TWO MEETINGS, NOT THREE. Three is the cut that sounds stronger and is
    # not: it takes the sample from 242 games to 70, which buys noise rather
    # than confidence. A tie counts as neither, so a quarterback who drew once
    # and lost once has still never beaten them.
    tg = tg.with_columns([
        ((pl.col("qb_seen") >= 2) & (pl.col("qb_won") == 0))
        .fill_null(False).alias("qb_never_beat"),
        ((pl.col("qb_seen") >= 2) & (pl.col("qb_lost") == 0))
        .fill_null(False).alias("qb_never_lost"),
    ])
    # THE OPPONENT'S SITUATION, which nothing here had ever used: all sixty
    # angles above are about the team itself. `opp_rest` already rides on the
    # frame; the opponent's LAST RESULT does not, and a self-join on the game
    # is the whole of it.
    tg = tg.join(
        tg.select(["game_id", pl.col("team").alias("opp"),
                   pl.col("prev_margin").alias("opp_prev_margin"),
                   # The opponent's bye is on the same join, and `pre_bye` is
                   # already computed above, so it costs nothing. Nor does the
                   # quarterback fact, which is why it is computed above too.
                   pl.col("pre_bye").alias("opp_pre_bye"),
                   pl.col("qb_never_beat").alias("opp_qb_never_beat")]),
        on=["game_id", "opp"], how="left")
    tg = tg.with_columns([
        pl.col("opp_pre_bye").fill_null(False),
        pl.col("opp_qb_never_beat").fill_null(False),
    ])
    # RECORD SO FAR, counted BEFORE this week's game. `cum_sum` includes the
    # current row, so each is subtracted back out — without that a team is
    # credited with the result it has not played yet.
    tg = tg.sort(["season", "team", "week"]).with_columns(
        (pl.col("margin") > 0).cast(pl.Int8).alias("_w"))
    tg = tg.with_columns([
        (pl.col("_w").cum_sum().over(["season", "team"]) - pl.col("_w"))
            .alias("wins_before"),
        ((1 - pl.col("_w")).cum_sum().over(["season", "team"])
         - (1 - pl.col("_w"))).alias("losses_before"),
        pl.col("div_game").shift(1).over(["season", "team"]).alias("prev_div"),
    ])
    return tg.drop("_w")


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
            # BOTH CONDITIONS. See `TINT_MIN_GAMES`: an eighty-six-game row
            # clearing at the lower bound is a wide interval that happens to
            # start high, not a finding.
            "clears": lo > BREAK_EVEN and n >= TINT_MIN_GAMES}


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
