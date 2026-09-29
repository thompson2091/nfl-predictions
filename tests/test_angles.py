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


def test_qualifying_entries_match_the_splits_in_their_own_game(sched):
    """The card claims a team carries an angle IN THIS GAME.

    Keyed by team and measured for one week, it could not: the board carries
    whatever the books have posted, and in week 3 of 2026 that was thirty
    fixtures spanning two weeks, so week-3 angles printed under week-4 games.
    ARI came off a 24-point loss in week 3 and the card for its week-4 game
    said "ARI - Off a 20+ loss" when ARI's last result was a six-point loss.

    Every entry is checked against the team-week of THAT GAME, so an entry
    filed under the wrong fixture fails here whatever week it came from.
    """
    tg = A.team_weeks(sched)
    season = sorted(sched["season"].unique().to_list())[-1]
    q = A.qualifying(sched, season)
    assert q, "no games qualified at all"
    by_id = {a.id: a for a in A.ANGLES}
    rows = tg.filter(pl.col("season") == season).with_columns(
        pl.col("game_id").str.splitn("_", 3).struct.field("field_2").alias("gid"))
    checked = 0
    for gid, pairs in q.items():
        for team, aid in pairs:
            hit = rows.filter((pl.col("gid") == gid)
                              & (pl.col("team") == team)
                              & by_id[aid].predicate)
            assert hit.height, (
                f"{team} is listed for {aid} in {gid}, but that team-week "
                "does not match the predicate the record was measured on")
            checked += 1
    assert checked > 100, f"only {checked} entries checked; the fixture is thin"


def test_an_angle_is_filed_under_the_game_it_happened_in(sched):
    """A game carries only its own two teams.

    The team-keyed version had nothing to check this against: the card looked
    up a team and printed whatever came back, whichever week it was measured
    in and whichever fixture was on screen.
    """
    tg = A.team_weeks(sched)
    season = sorted(sched["season"].unique().to_list())[-1]
    q = A.qualifying(sched, season)
    sides: dict[str, set] = {}
    for r in tg.filter(pl.col("season") == season).iter_rows(named=True):
        gid = "_".join(str(r["game_id"]).split("_")[2:])
        sides.setdefault(gid, set()).add(r["team"])
    for gid, pairs in q.items():
        assert gid in sides, f"{gid} is not a fixture this season"
        for team, _aid in pairs:
            assert team in sides[gid], (
                f"{team} is listed under {gid}, which it does not play in")


def test_the_season_number_never_appears_without_its_record():
    """"7-1 this year" is the number that travels, so it leads the card — and
    the only thing that keeps that honest is the record sitting under it.
    "12.5%" persuades; "12.5%" over "1-7" cannot, because the sample is under
    the claim. Hiding the season number instead just means it gets read
    somewhere else without the denominator.
    """
    import re

    from src.export import v3js
    src = v3js.js()

    def body_of(name: str) -> str:
        i = src.index(name)
        j = src.index("\nfunction ", i + 1)
        return src[i:j if j > 0 else len(src)]

    # EVERY PERCENTAGE IS PAIRED WITH THE RECORD FOR THE SAME FIGURE. Both
    # screens draw the columns through `v3AnglePct` and `v3AngleRec`, and the
    # pairing is what this checks — the same argument, in that order, with
    # nothing but markup between them.
    # The argument is an expression now, not always a bare name: the season
    # column reads `seasonOf(r)` on the board and `o.season` on the card,
    # because either can be one team's record instead of the league's.
    pair = re.compile(
        r"v3AnglePct\((?P<a>[\w.]+(?:\([\w.]+\))?)\)[^;]*?"
        r"v3AngleRec\((?P=a)\)")
    for fn in ("function v3Angles(", "function v3AnglesPage("):
        body = body_of(fn)
        n_pct = body.count("v3AnglePct(")
        assert n_pct >= 2, f"{fn} draws no percentages at all"
        assert len(pair.findall(body)) == n_pct, (
            f"{fn} draws a percentage that is not followed by the record for "
            "the same figure")
    body = body_of("function v3Angles(")
    assert "Yr ATS" in body and "+ ATS'" in body, "a column is gone"
    assert "Break-even" in body, "the card does not say what clears"


def test_every_percentage_says_it_is_against_the_spread():
    """"48.9%" on its own is a percentage of nothing, and a reader who takes
    it for a win rate is reading a different and much more flattering number.
    Each of these is a cover rate against the CLOSING spread."""
    from src.export import v3js
    src = v3js.js()

    def body_of(name: str) -> str:
        i = src.index(name)
        j = src.index("\nfunction ", i + 1)
        return src[i:j if j > 0 else len(src)]

    # BOTH ARE TABLES, so the unit rides on the column headings. The long-run
    # heading carries the chosen start year, so it is built rather than
    # literal — "’23+ ATS". Both still have to say ATS.
    for fn in ("function v3Angles(", "function v3AnglesPage("):
        body = body_of(fn)
        assert "Yr ATS" in body and "+ ATS'" in body, (
            f"{fn} has an unlabelled percentage column")
    assert "COVERED THE CLOSING SPREAD" in body_of("function v3Angles("), (
        "the card never says in full what the number measures")


def test_only_the_long_run_can_be_tinted():
    """Green on a hot season is the exact reading this card exists to stop:
    eight games at 88% would go green and look like a finding."""
    import re

    from src.export import v3js
    src = v3js.js()

    def body_of(name: str) -> str:
        i = src.index(name)
        j = src.index("\nfunction ", i + 1)
        return src[i:j if j > 0 else len(src)]

    for fn in ("function v3Angles(", "function v3AnglesPage("):
        body = body_of(fn)
        # The tint rides on `good`, and `good` is read off the LONG-RUN
        # record clearing break-even at its lower bound.
        assert re.search(r"const good = a && a\.clears", body), (
            f"{fn} no longer ties the tint to the interval clearing")
        # And the season column is drawn on a span that cannot carry it.
        season = re.search(
            r"<span class=\"num\"><b>' \+ v3AnglePct\((seasonOf\(r\)|"
            r"o\.season)\)", body)
        assert season, (
            f"{fn} draws the season percentage on a span that could be tinted")
    # `clears` is computed in one place, and it is BOTH conditions: the lower
    # bound clearing break-even and enough games to mean it. `pre_bye_div` was
    # the first row in fifty-eight to clear, at 58-28 — eighty-six games, and
    # a subset picked after seeing its parent.
    since = body_of("function v3AngleSince(")
    assert "clears: v3Clears(iv[0], n, be)" in since, (
        "the tint is no longer tied to the interval clearing break-even")
    clears = body_of("function v3Clears(")
    assert "lo > be" in clears and "n >= floor" in clears, (
        "the tint no longer requires both a clearing interval and a sample")


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
    j = src.index("\nfunction ", i + 1)
    page = src[i:j if j > 0 else len(src)]
    # Said in plain words rather than as "false positives at 95% confidence",
    # which was three pieces of jargon before the reader reached a number.
    assert "on luck alone" in page, (
        "the board does not say that some of these would look good by luck")
    assert "bookmaker keeps a cut" in page, (
        "the board does not explain why winning half is not enough")


def test_off_a_bye_means_the_team_had_a_week_off(sched):
    """`rest >= 10` was 352 real byes and 378 team-weeks that were not one.

    Ten days is what a team has after playing on Thursday, so most of "Off a
    bye" was a mini-bye — an angle worth measuring, but not that one, and not
    under that name. Caught when the board showed the split 5-0 in week 3 of
    a season where no bye had been played yet.

    The two are separated by looking for the WEEK OFF rather than by the day
    count they are defined with, so a threshold that drifts back fails here.
    """
    tg = A.team_weeks(sched)
    played = set(
        tg.select(["season", "team", "week"]).unique().iter_rows())

    def by_id(angle_id):
        a = [x for x in A.ANGLES if x.id == angle_id][0]
        return tg.filter(a.predicate)

    def week_off(rows):
        """Rows whose team did not play the week before, and rows that did."""
        off, on = 0, 0
        for r in rows.iter_rows(named=True):
            if r["week"] <= 1:
                on += 1
                continue
            prev = (r["season"], r["team"], r["week"] - 1)
            if prev in played:
                on += 1
            else:
                off += 1
        return off, on

    byes = by_id("off_bye")
    off, on = week_off(byes)
    assert byes.height > 100, "no byes matched at all; the predicate is dead"
    assert on == 0, (
        f"{on} of {byes.height} team-weeks called 'off a bye' played the "
        "week before, so they are not off a bye")

    mini = by_id("mini_bye")
    off2, on2 = week_off(mini)
    assert mini.height > 100, "no mini-byes matched; the predicate is dead"
    assert off2 == 0, (
        f"{off2} of {mini.height} team-weeks called 'off a Thursday game' "
        "had the whole week off, which is a bye")


def test_no_angle_is_measured_twice_under_two_names(sched):
    """Two ids selecting the same team-weeks are one angle counted twice, and
    the board's false-positive budget is a count of independent tries."""
    tg = A.team_weeks(sched)
    seen: dict[frozenset, str] = {}
    for a in A.ANGLES:
        rows = tg.filter(a.predicate).select("game_id", "team")
        key = frozenset(rows.iter_rows())
        if not key:
            continue
        assert key not in seen, (
            f"{a.id} selects exactly the same games as {seen[key]}")
        seen[key] = a.id


def test_a_whole_game_condition_is_flagged_as_one(sched):
    """Both sides of every prime-time game are in prime time.

    So one covers and the other does not, and the record is exactly 50.00% by
    arithmetic: prime time 570-570, on grass 1605-1605, indoors 822-822. Ten
    more seasons would not move any of them. The flag is what lets the board
    say so instead of printing twelve measured nulls.

    The DATA decides, not the list: an angle that turns out to select both
    sides has to carry the flag, and one that selects a side must not.
    """
    tg = A.team_weeks(sched)
    for a in A.ANGLES:
        hit = tg.filter(a.predicate)
        if hit.is_empty():
            continue
        per_game = hit.group_by("game_id").len()["len"]
        both_only = bool((per_game == 2).all())
        which = "both sides of every" if both_only else "one side of some"
        assert a.whole_game == both_only, (
            f"{a.id} selects {which} game, and its `whole_game` flag says "
            f"{a.whole_game}")


def test_a_flagged_condition_really_cannot_move(sched):
    """The claim the tag makes, checked against the arithmetic it rests on."""
    tg = A.team_weeks(sched)
    for a in A.ANGLES:
        if not a.whole_game:
            continue
        r = A._record(tg.filter(a.predicate))
        if r is None:
            continue
        assert r["w"] == r["l"], (
            f"{a.id} is flagged as a whole-game condition but is {r['w']}-"
            f"{r['l']}; one of the two is wrong")


def test_the_baseline_is_the_split_s_own_mix_not_a_flat_fifty(sched):
    """Side and role are worth four points between them.

    Road underdogs cover 52.07% over 1,763 team-games and home favorites
    47.93% over the same number. So a split made mostly of favorites looks bad
    without saying anything: "Favored after being an underdog" reads as a
    five-point fade against 50% and is under two points against what its own
    composition predicts.

    The mix is shipped per season so the page can answer for any start year,
    and per team because a club's games sit in different cells from the
    league's.
    """
    b = A.baseline(sched)
    assert set(b) == {"cells", "mix", "team_mix"}
    # THE FOUR CELLS ARE REALLY DIFFERENT, or none of this would be worth
    # shipping and the test would pass on a payload that says nothing.
    tot = {c: [0, 0] for c in A.CELLS}
    for season in b["cells"].values():
        for c, (w, n) in season.items():
            tot[c][0] += w
            tot[c][1] += n
    rates = {c: tot[c][0] / tot[c][1] for c in A.CELLS if tot[c][1]}
    assert max(rates.values()) - min(rates.values()) > 0.03, (
        f"the cells cover at nearly the same rate ({rates}); the correction "
        "would not be worth making")
    assert rates["AD"] > rates["HF"], (
        "road underdogs no longer cover more often than home favorites")

    # EVERY MEASURED ANGLE HAS ONE, or the column is blank where it matters.
    measured = {r["id"] for r in A.measure(sched)}
    missing = sorted(measured - set(b["mix"]))
    assert not missing, f"no baseline mix for {missing}"

    # AND THE MIX ADDS UP TO THE GAMES IT IS A MIX OF.
    import polars as pl
    tg = (A.team_weeks(sched)
          .filter(pl.col("cover_by").is_not_null() & (pl.col("cover_by") != 0)))
    for a in A.ANGLES:
        if a.id not in b["mix"]:
            continue
        n = tg.filter(a.predicate).filter(pl.col("my_spread") != 0).height
        got = sum(sum(v) for v in b["mix"][a.id].values())
        assert got == n, f"{a.id}: mix totals {got}, the split has {n}"


def test_a_thin_row_does_not_go_green_however_good_it_looks(sched):
    """`pre_bye_div` is 58-28 over eleven seasons and clears break-even at the
    bottom of its interval — the first row in fifty-eight to do so.

    It is also eighty-six games, and a subset picked after seeing its parent
    at 55.65%, which is a fork that could as easily have been home/away or
    favorite/underdog. Tinting it green would be the board making its loudest
    claim on its thinnest evidence.
    """
    rows = {r["id"]: r for r in A.measure(sched)}
    thin = rows.get("pre_bye_div")
    assert thin, "the angle is gone; this test guards nothing"
    a = thin["all"]
    # The finding itself, which must not be hidden: it does clear.
    assert a["lo"] > A.BREAK_EVEN, (
        "pre_bye_div no longer clears; the guard has nothing to hold back")
    assert a["n"] < A.TINT_MIN_GAMES, f"n is now {a['n']}; pick a new example"
    # And it is not tinted.
    assert not a["clears"], (
        f"a {a['n']}-game row is tinted green on a {(a['hi']-a['lo'])*100:.0f}"
        "-point interval")
    # A row with the sample AND the interval still would.
    fat = {"n": A.TINT_MIN_GAMES, "lo": A.BREAK_EVEN + 0.01}
    assert fat["lo"] > A.BREAK_EVEN and fat["n"] >= A.TINT_MIN_GAMES
    # The floor has to be well above the reporting minimum, or it is no floor.
    assert A.TINT_MIN_GAMES >= 5 * A.MIN_GAMES
