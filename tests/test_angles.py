"""Angles are measured together, graded from the day added, never pruned.

Twenty were registered on 2026-09-28 over 5,732 graded team-games. None clears
break-even at the lower bound of its interval. That is the honest state of the
idea, and the board has to be able to say so.
"""
from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from src.evaluation import angles as A


@pytest.fixture(scope="module")
def sched():
    from src.utils.paths import get_path
    p = get_path("raw") / "schedules.parquet"
    if not p.exists():
        pytest.skip("no schedules on disk")
    return pl.read_parquet(p)


def test_a_push_is_neither_a_cover_nor_a_loss(sched):
    """Counting it as either drags every rate toward 50% by an amount that
    varies with the split, which is worse than dropping it."""
    tg = A.team_weeks(sched)
    pushes = tg.filter(pl.col("cover_by") == 0)
    assert pushes.height, "fixture has no pushes; this proves nothing"
    for r in A.measure(sched):
        # `n` is wins plus losses exactly — no half-games anywhere.
        assert r["all"]["n"] == r["all"]["w"] + r["all"]["l"]


def test_the_away_side_is_the_negation_of_the_home_spread(sched):
    """`spread_line` is the HOME number. Reading it as the away team's makes
    every underdog split a favorite split and vice versa."""
    tg = A.team_weeks(sched)
    g = tg.filter(pl.col("my_spread").is_not_null())
    home = g.filter(pl.col("at_home"))
    away = g.filter(~pl.col("at_home"))
    # Same games from both sides: the spreads must sum to zero.
    assert abs(float(home["my_spread"].sum())
               + float(away["my_spread"].sum())) < 1e-6


def test_every_angle_is_reported_including_the_ones_that_fail(sched):
    """A board of the angles that currently clear is a board of survivors."""
    rows = A.measure(sched)
    assert len(rows) >= 15, f"only {len(rows)} angles reported"
    below = [r for r in rows if r["all"]["pct"] < 0.50]
    assert below, "no losing angle survived to the board; something prunes"


def test_nothing_clears_break_even_at_the_lower_bound(sched):
    """The measured state on 2026-09-28, and the thing the page must not
    overstate. If this ever fails, an angle has genuinely started clearing and
    the claim on the card should be revisited — deliberately, not silently.
    """
    rows = A.measure(sched)
    clearing = [r["label"] for r in rows if r["all"]["clears"]]
    assert not clearing, (
        f"these now clear break-even at the lower bound: {clearing} — "
        "revisit the wording on the card, which says none do")


def test_an_angle_added_later_is_graded_from_the_day_it_was_added(sched):
    """THE WHOLE DEFENSE AGAINST MINING. All-time for a mined angle includes
    the hot stretch that got it noticed; `since` starts the day it was written
    down and nothing in it can have been selected on."""
    rows = {r["id"]: r for r in A.measure(sched)}
    for a in A.ANGLES:
        if a.id not in rows:
            continue
        r = rows[a.id]
        assert r["added"] == a.added.isoformat()
        if r["since"] is not None:
            # Whatever is in `since` has to be a subset of all-time.
            assert r["since"]["n"] <= r["all"]["n"]


def test_a_mined_angle_is_labeled_as_one():
    """A row added because it was hot must not read like a registered one."""
    for a in A.ANGLES:
        if a.added > date(2026, 9, 28):
            assert a.mined, (
                f"{a.id} was added after registration but is not marked mined")


def test_qualifying_teams_match_the_splits(sched):
    """The card claims a team carries an angle; that has to be the same
    predicate the record was measured on."""
    tg = A.team_weeks(sched)
    seasons = sorted(sched["season"].unique().to_list())
    season = seasons[-1]
    weeks = sorted(tg.filter(pl.col("season") == season)["week"].unique()
                   .to_list())
    if not weeks:
        pytest.skip("no weeks")
    week = weeks[len(weeks) // 2]
    q = A.qualifying(sched, season, week)
    by_id = {a.id: a for a in A.ANGLES}
    for team, ids in list(q.items())[:5]:
        for aid in ids:
            hit = tg.filter((pl.col("season") == season)
                            & (pl.col("week") == week)
                            & (pl.col("team") == team)
                            & by_id[aid].predicate)
            assert hit.height, f"{team} listed for {aid} but does not match it"


def test_the_season_number_never_appears_without_its_record():
    """"7-1 this year" is the number that travels, so it leads the card — and
    the only thing that keeps that honest is the record sitting under it.
    "12.5%" persuades; "12.5%" over "1-7" cannot, because the sample is under
    the claim. Hiding the season number instead just means it gets read
    somewhere else without the denominator.
    """
    from src.export import v3js
    src = v3js.js()
    i = src.index("function v3Angles")
    body = src[i:i + 3500]
    # One helper renders every column, so a percentage cannot be drawn
    # without the record: they are the same expression.
    assert "const cell = (eyebrow, d, tone)" in body, (
        "the columns are no longer built by one helper, so a percentage can "
        "now be shown without its win-loss")
    assert "d.w + '-' + d.l" in body, "the record is not printed"
    for col in ("This year", "Since 2015"):
        assert col in body, f"the {col!r} column is gone"
    assert "Break-even" in body, "the card does not say what clears"


def test_every_percentage_says_it_is_against_the_spread():
    """"48.9%" on its own is a percentage of nothing, and a reader who takes
    it for a win rate is reading a different and much more flattering number.
    Each of these is a cover rate against the CLOSING spread."""
    from src.export import v3js
    src = v3js.js()
    for fn in ("function v3Angles", "function v3AnglesPage"):
        i = src.index(fn)
        body = src[i:i + 4000]
        assert "' ATS</span>'" in body, (
            f"{fn} draws a percentage with no unit on it")
    i = src.index("function v3Angles")
    assert "COVERED THE CLOSING SPREAD" in src[i:i + 4000], (
        "the card never says in full what the number measures")


def test_only_the_long_run_can_be_tinted():
    """Green on a hot season is the exact reading this card exists to stop:
    eight games at 88% would go green and look like a finding."""
    from src.export import v3js
    src = v3js.js()
    i = src.index("function v3Angles")
    body = src[i:i + 3500]
    assert "cell('This year', r.season, false)" in body, (
        "the season column can be tinted; it must never be")
    assert "a.lo > be" in body, (
        "the tint is no longer tied to the interval clearing break-even")


def test_no_angle_reads_the_future(sched):
    """NEXT WEEK'S CLOSING LINE IS THIS WEEK'S RESULT, WEARING A HAT.

    Two angles were written against `next_spread` on the reasoning that next
    week's line is posted before this week kicks off. That is true of
    look-ahead lines and false of this data: `spread_line` is each game's
    CLOSING number, set after the previous week has been played. "Favored,
    underdog next week" came back at 43.6% over 1,049 games and its mirror at
    55.4% — a nine-point edge across eleven seasons in the most efficient
    market there is, which is what a leak looks like when it is working.

    Nothing may reach forward again. A lag is fine; a lead is the outcome.
    """
    tg = A.team_weeks(sched)
    assert "next_spread" not in tg.columns, (
        "a forward-looking column is back on the frame")
    import inspect
    src = inspect.getsource(A)
    body = src[src.index("ANGLES: tuple"):src.index("def team_weeks")]
    assert "shift(-1)" not in body and "next_" not in body, (
        "an angle predicate reaches into a later week")


def test_the_board_states_its_own_false_positive_budget(sched):
    """"3 of 50 clear" reads as a finding until you know the expectation was
    2.5. With fifty splits at 95% confidence, a couple clearing is what chance
    alone produces."""
    rows = A.measure(sched)
    expected = len(rows) * A.EXPECTED_FALSE_POSITIVES
    assert expected > 1.0, (
        "with this many angles the expected count of chance clears is under "
        "one, so the warning on the board would be overstating it")
    from src.export import v3js
    src = v3js.js()
    i = src.index("function v3AnglesPage")
    assert "by chance" in src[i:i + 4500], (
        "the board does not say how many clears chance alone would produce")
