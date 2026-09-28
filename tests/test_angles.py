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


def test_the_card_leads_with_the_long_run_not_the_season():
    """"7-1 this year" is the number that travels and the one that is noise."""
    from src.export import v3js
    src = v3js.js()
    i = src.index("function v3Angles")
    body = src[i:i + 3000]
    assert "since 2015" in body, "the long-run record is not on the card"
    assert body.index("since 2015") < body.index("this year"), (
        "the season record is printed ahead of the long-run one")
    assert "Break-even" in body, "the card does not say what clears"
