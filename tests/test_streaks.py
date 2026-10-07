"""The streak rule, which used to live in the page.

`v3Streak` counted back from whatever "now" was, so asking it about week 3
got today's answer. These pin the three things that made it worth moving: the
window is as-of, a short record is silent rather than approximate, and
whichever direction is the market's own norm is not a finding about a player.

Parity with the JavaScript it replaces was measured once, on the live payload
of 2026-10-07, across all six markets: 277 flagged players, identical sets,
identical directions and identical baselines. That is recorded in the commit
rather than re-run here, because the JavaScript is gone.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from src.evaluation import streaks


def row(season, week, line, did):
    """A `player_history.history` row: [season, week, opp, home, line, odds,
    did, played, other]."""
    return [season, week, "OPP", 1, line, -110, did, 1, 110]


def over_run(n, season=2026, first_week=1):
    """`n` weeks newest first, every one of them over the line."""
    return [row(season, first_week + n - 1 - i, 5.5, 9.0) for i in range(n)]


def test_five_overs_is_a_streak():
    assert streaks.direction(over_run(5), 2026, 6, False) == "over"


def test_four_of_five_is_enough_and_three_is_not():
    r = over_run(5)
    r[0] = row(2026, 5, 5.5, 1.0)                   # newest week went under
    assert streaks.direction(r, 2026, 6, False) == "over"
    r[1] = row(2026, 4, 5.5, 1.0)
    assert streaks.direction(r, 2026, 6, False) is None


def test_the_window_is_as_of_the_week_asked_about():
    """THE REASON THIS MOVED. The same rows answer differently for different
    weeks, and the page could only ever answer for today."""
    # Weeks 1-5 over, weeks 6-10 under. Newest first.
    rows = ([row(2026, 10 - i, 5.5, 1.0) for i in range(5)]
            + [row(2026, 5 - i, 5.5, 9.0) for i in range(5)])
    assert streaks.direction(rows, 2026, 11, False) == "under"
    assert streaks.direction(rows, 2026, 6, False) == "over"
    # And a week with nothing behind it is not a streak either way.
    assert streaks.direction(rows, 2026, 2, False) is None


def test_the_window_crosses_the_season_boundary():
    """Five weeks into a season does not exist in week 3, so the record is
    one record and not one per season."""
    rows = (over_run(2, season=2026, first_week=1)
            + over_run(3, season=2025, first_week=16))
    assert streaks.direction(rows, 2026, 3, False) == "over"


def test_a_short_or_ragged_record_is_silent():
    assert streaks.direction(over_run(4), 2026, 6, False) is None
    gap = over_run(5)
    gap[2] = row(2026, 3, 5.5, None)                # no result that week
    assert streaks.direction(gap, 2026, 6, False) is None
    noline = over_run(5)
    noline[2] = row(2026, 3, None, 9.0)             # no line that week
    assert streaks.direction(noline, 2026, 6, False) is None


def test_the_line_is_the_one_he_was_quoted_that_week():
    """Not this week's line, which he never played against.

    A player's number moves week to week — three catches against 1.5 and
    three against 3.5 are not the same week — so counting past games against
    today's line reports a run the player never had. Each row carries its own
    line and that is the one compared.
    """
    # Three catches every week. Against the lines he actually had, four of
    # the five went over; against a flat 3.5 none of them would have.
    rows = [row(2026, 5, 1.5, 3.0), row(2026, 4, 2.5, 3.0),
            row(2026, 3, 2.5, 3.0), row(2026, 2, 1.5, 3.0),
            row(2026, 1, 4.5, 3.0)]
    assert streaks.direction(rows, 2026, 6, False) == "over"
    flat = [row(2026, 5 - i, 3.5, 3.0) for i in range(5)]
    assert streaks.direction(flat, 2026, 6, False) == "under"


def test_a_yesno_market_needs_no_line():
    rows = [row(2026, 5 - i, None, 1) for i in range(5)]
    assert streaks.direction(rows, 2026, 6, True) == "over"
    assert streaks.direction(rows, 2026, 6, False) is None


def test_the_direction_that_is_the_market_is_not_flagged():
    """A tag on 97% of the board is a label for the market wearing a
    player's name. First touchdown in 2026: 385 of 398 eligible players had
    "did not score in 4 of his last 5"."""
    # Twenty players who all went under, one who went over.
    unders = {f"u{i}": [row(2026, 5 - j, None, 0) for j in range(5)]
              for i in range(20)}
    per = dict(unders, star=[row(2026, 5 - j, None, 1) for j in range(5)])
    base = streaks.baseline(per, 2026, 6, True)
    assert base["under"] > 0.5 and base["over"] < 0.5
    f = streaks.flags({"first_td": per}, 2026, [6])
    assert [k[2] for k in f] == ["star"], f
    assert f[(6, "first_td", "star")] == "over"


def test_the_baseline_is_as_of_too():
    """A direction that became the norm in week 10 was not the norm in week
    6, and a baseline read from today would suppress it in both."""
    # Over through week 5, under from week 6.
    per = {f"p{i}": ([row(2026, 10 - j, 5.5, 1.0) for j in range(5)]
                     + [row(2026, 5 - j, 5.5, 9.0) for j in range(5)])
           for i in range(20)}
    assert streaks.baseline(per, 2026, 6, False)["over"] > 0.5
    assert streaks.baseline(per, 2026, 11, False)["under"] > 0.5


def test_nothing_to_measure_flags_nothing():
    """With no eligible population every direction would be rare, which
    would flag the whole board. The empty answer is 1.0 both ways."""
    assert streaks.baseline({}, 2026, 6, False) == {"over": 1.0, "under": 1.0}
    thin = {"a": over_run(2)}
    assert streaks.baseline(thin, 2026, 6, False) == {"over": 1.0,
                                                      "under": 1.0}
    assert streaks.flags({"receptions": thin}, 2026, [6]) == {}


def _mixed(n=10, season=2026):
    """A record with no streak in it, to make up an eligible population.

    Padding matters and the first draft of this test got it wrong: padding
    with players who all ran one way put that direction's baseline at 1.0,
    which suppressed it — the test then failed for the rule's own correct
    reason rather than for the one it was written to catch.
    """
    return [row(season, n - i, 5.5, 9.0 if i % 2 else 1.0) for i in range(n)]


def test_flags_are_keyed_by_week_so_a_past_week_keeps_its_answer():
    """THE WHOLE POINT. Week 6's answer does not move when week 11 lands."""
    rows = ([row(2026, 10 - i, 5.5, 1.0) for i in range(5)]
            + [row(2026, 5 - i, 5.5, 9.0) for i in range(5)])
    per = dict({"x": rows}, **{f"p{i}": _mixed() for i in range(9)})
    f = streaks.flags({"receptions": per}, 2026, [6, 11])
    assert f.get((11, "receptions", "x")) == "under"
    assert f.get((6, "receptions", "x")) == "over"
