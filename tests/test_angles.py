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


#: Angles added after the founding day and NOT mined. Each one is here
#: because it was written down before it was measured, which is the whole
#: distinction `mined` exists to carry — and each is named individually, so
#: adding a hot row still has to come past this list and say so.
#:
#: The four spread bands complete a partition rather than adding four
#: patterns: the board had the two ends of the line and nothing between them,
#: so "road favorite" pooled a team laying 1.5 with one laying 9.5. They were
#: written as a set, measured afterwards, and the losing bands were kept —
#: `test_the_spread_bands_partition_the_line` is what makes "a partition"
#: checkable rather than a claim in a comment.
REGISTERED_LATER = {
    "fav_3h_to_6h", "fav_7_to_9h", "dog_3h_to_6h", "dog_7_to_9h",
}


def test_a_mined_angle_is_labeled_as_one():
    """A row added because it was hot must not read like a registered one."""
    for a in A.ANGLES:
        if a.added > date(2026, 9, 28) and a.id not in REGISTERED_LATER:
            assert a.mined, (
                f"{a.id} was added after registration but is not marked mined")


def test_every_later_registration_is_still_on_the_board():
    """An exemption for an angle that has gone is an exemption for the next
    one to take its name."""
    ids = {a.id for a in A.ANGLES}
    gone = sorted(REGISTERED_LATER - ids)
    assert not gone, f"exempted but no longer an angle: {gone}"


def test_the_spread_bands_partition_the_line(sched):
    """Every favorite falls in exactly one band, and so does every underdog.

    This is what makes the four new rows a partition rather than four more
    patterns. A gap would be a team on nobody's row; an overlap would be a
    team counted twice, and both read as a measured result rather than as an
    arithmetic slip.
    """
    import polars as pl

    tg = A.team_weeks(sched).filter(pl.col("my_spread").is_not_null()
                                    & (pl.col("my_spread") != 0))
    bands = {a.id: a.predicate for a in A.ANGLES
             if a.id in ("fav_3_or_less", "fav_3h_to_6h", "fav_7_to_9h",
                         "big_fav", "dog_3_or_less", "dog_3h_to_6h",
                         "dog_7_to_9h", "big_dog")}
    assert len(bands) == 8, sorted(bands)
    hits = tg.select([p.cast(pl.Int32).alias(k) for k, p in bands.items()])
    total = hits.select(pl.sum_horizontal(pl.all()).alias("n"))["n"]
    assert total.min() == 1, "a team-game falls on no band"
    assert total.max() == 1, "a team-game falls on two bands"


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


def test_a_record_so_far_excludes_the_game_it_describes(sched):
    """`wins_before` counts the season up to but NOT including this week.

    `cum_sum` includes the current row, so without subtracting it back out a
    team is credited with the result of the game being predicted — "losing
    record but favored" would then be partly a measure of having just lost.
    """
    tg = A.team_weeks(sched)
    for c in ("wins_before", "losses_before"):
        assert c in tg.columns, f"{c} is gone"
    # A team's first game of a season has no record behind it, whatever it did.
    first = tg.filter(pl.col("week") == pl.col("week").min()
                      .over(["season", "team"]))
    assert int(first["wins_before"].sum()) == 0, (
        "a team carries wins into its own opener")
    assert int(first["losses_before"].sum()) == 0
    # And the two together never exceed the games already played.
    played = tg.with_columns(
        (pl.col("wins_before") + pl.col("losses_before")).alias("_n"))
    over = played.filter(pl.col("_n") >= pl.col("week"))
    assert over.is_empty(), (
        f"{over.height} rows count more games than the week allows; the "
        "current result is being counted")


def test_an_opponent_angle_reads_the_opponent_not_the_team(sched):
    """The first three angles on this board that ask about the other side.

    A self-join on the game is easy to get backwards, and backwards it would
    silently restate an angle that is already here: `opp_off_bye` would become
    `off_bye`, and the two would agree to the game.
    """
    tg = A.team_weeks(sched)
    assert "opp_prev_margin" in tg.columns
    # THE JOIN IS THE RIGHT WAY ROUND: a team's `opp_prev_margin` is the
    # OTHER side's `prev_margin` in the same game.
    by = {(r["game_id"], r["team"]): r for r in tg.iter_rows(named=True)}
    checked = 0
    for (gid, team), r in list(by.items()):
        other = by.get((gid, r["opp"]))
        if other is None or other["prev_margin"] is None:
            continue
        assert r["opp_prev_margin"] == other["prev_margin"], (
            f"{team} in {gid} carries the wrong side's last result")
        checked += 1
        if checked > 400:
            break
    assert checked > 100, f"only {checked} pairs checked"
    # And it is NOT the team's own, which is what a self-join gone wrong gives.
    same = tg.filter(pl.col("opp_prev_margin").is_not_null()
                     & pl.col("prev_margin").is_not_null()
                     & (pl.col("opp_prev_margin") == pl.col("prev_margin")))
    assert same.height < tg.height * 0.2, (
        "the opponent's last result matches the team's own too often; the "
        "join is probably reading the same row back")


def test_every_angle_has_a_kind_the_filter_offers():
    """A category is how either surface narrows eighty rows to a screen.

    So an angle that arrives without one is not merely uncategorised, it is
    unreachable: `measure` files it under "Other", neither filter lists that,
    and the only way to it is scrolling the whole board — the thing the kinds
    exist to stop. Same guarantee `test_every_matchup_metric_has_a_group`
    gives the metrics, and it is here because both filters now depend on it.
    """
    ids = [a.id for a in A.ANGLES]
    missing = [i for i in ids if i not in A.CATEGORY]
    assert not missing, f"no category for {missing}"
    stale = [i for i in A.CATEGORY if i not in ids]
    assert not stale, f"{stale} are categorised but are not angles"
    # Every kind an angle claims is one the filter actually offers.
    unknown = sorted({c for c in A.CATEGORY.values()} - set(A.CATEGORIES))
    assert not unknown, f"{unknown} is used but is not in CATEGORIES"
    # And no offered kind is empty, which would draw an option that filters
    # the board to nothing.
    for cat in A.CATEGORIES:
        live = [i for i in ids if A.CATEGORY.get(i) == cat]
        assert live, f"the {cat!r} kind has no angles left in it"


def test_a_quarterbacks_record_against_one_opponent_looks_backward(sched):
    """Counted before this meeting, across seasons, and played games only.

    Three ways this goes wrong silently. Counting the current game makes every
    first meeting look like a second. Taking the running total per club rather
    than per quarterback loses every player who changed teams — which is the
    case that prompted the angle. And letting an unplayed fixture into the
    count turns the column null from that point on, which reads as "no streak"
    on exactly the games the board is for.
    """
    tg = A.team_weeks(sched)
    for c in ("qb_seen", "qb_won", "qb_lost", "qb_never_beat",
              "qb_never_lost", "opp_qb_never_beat"):
        assert tg.filter(pl.col(c).is_null()).height == 0, (
            f"{c} is null somewhere; an unplayed fixture has poisoned the "
            f"running total")
    # A first meeting has no prior record, whatever else is true of it.
    first = tg.filter(pl.col("qb_seen") == 0)
    assert first.height > 1000, f"only {first.height} first meetings"
    assert first.filter((pl.col("qb_won") > 0)
                        | (pl.col("qb_lost") > 0)).height == 0, (
        "a first meeting carries a prior record")
    # The flags say what they claim to.
    bad = tg.filter(pl.col("qb_never_beat")
                    & ((pl.col("qb_seen") < 2) | (pl.col("qb_won") > 0)))
    assert bad.height == 0, f"{bad.height} rows claim a streak they lack"
    # ACROSS CLUBS, which per-team accumulation would miss. Watson faced
    # Pittsburgh for Houston in 2020 and for Cleveland in 2022 and 2023, so by
    # the 2023 meeting the count has to be two, not one.
    ids = sched.filter(pl.col("game_type") == "REG")
    names = pl.concat([
        ids.select([pl.col(f"{s}_qb_id").alias("qb"),
                    pl.col(f"{s}_qb_name").alias("nm")])
        for s in ("home", "away")]).drop_nulls().unique(subset=["qb"])
    w = (tg.join(names, on="qb", how="left")
           .filter(pl.col("nm").str.contains("Watson")
                   & (pl.col("opp") == "PIT"))
           .sort(["season", "week"]))
    assert w.height >= 3, f"only {w.height} Watson-Pittsburgh meetings"
    seen = w["qb_seen"].to_list()
    assert seen == list(range(len(seen))), (
        f"the count should run 0,1,2,... and runs {seen}; the total is "
        f"probably being taken per club rather than per quarterback")
    assert w["qb_won"].to_list() == [0] * len(seen), (
        "a quarterback credited with a win he does not have")
    # And the opponent's copy is the other side of the same fixture.
    by = {(r["game_id"], r["team"]): r for r in tg.iter_rows(named=True)}
    checked = 0
    for (gid, team), r in list(by.items()):
        other = by.get((gid, r["opp"]))
        if other is None:
            continue
        assert r["opp_qb_never_beat"] == other["qb_never_beat"], (
            f"{team} in {gid} carries the wrong side's quarterback record")
        checked += 1
        if checked > 400:
            break
    assert checked > 100, f"only {checked} pairs checked"


def test_a_mirror_pair_is_the_same_games_from_the_other_side(sched):
    """Thirty rows are one half of a pair, and the page has to say so.

    A reader read "Quarterback has never beaten this opponent" at 5-2 and
    "Opposing quarterback has never beaten this team" at 2-5 as the same claim.
    They are the same games with the cover on the other sideline, which is the
    opposite claim, and nothing on the row said it.

    BOTH HALVES OF THE TEST MATTER. Reversed records alone would pair the
    wrong rows: `pickem`, `div_home_dog` and `div_road_fav` are all 208-208 on
    416 games. Equal game sets alone would pair a condition with a re-slicing
    of itself.
    """
    rows = A.measure(sched)
    by = {r["id"]: r for r in rows}
    mir = {r["id"]: r["mirror"] for r in rows if r["mirror"]}
    assert len(mir) >= 20, f"only {len(mir)} rows paired; expected thirty"
    for x, y in mir.items():
        assert y in by, f"{x} points at {y}, which is not on the board"
        assert mir.get(y) == x, f"{x} -> {y} is not symmetric"
        a, b = by[x]["all"], by[y]["all"]
        assert a["n"] == b["n"] and a["w"] == b["l"] and a["l"] == b["w"], (
            f"{x} is {a['w']}-{a['l']} and {y} is {b['w']}-{b['l']}; a mirror "
            f"has to be the exact reverse")
        # A whole-game condition is 50% because it holds both sides itself, not
        # because another row is its upside down. It carries its own tag.
        assert not by[x]["whole_game"], (
            f"{x} is a whole-game condition and cannot have a mirror")
    # THE FALSE POSITIVE THE RECORD TEST ALONE WOULD MAKE. Three rows whose
    # records are indistinguishable, and only two of them a pair.
    #
    # THE CLAIM, NOT A SNAPSHOT OF IT. This was pinned to all three being
    # exactly 208-208 on 416 games, which they were on the day it was written
    # and stopped being on 2026-10-04, when the ingest that graded a Thursday
    # divisional game moved two of them by one: 209-208, 208-209, 208-208.
    # The point survived the change untouched — the records are still within a
    # game of each other and `pickem` is still not their mirror — so what is
    # asserted now is that, rather than the coincidence that illustrated it.
    # A test that fails every time a divisional game is played is a test that
    # gets its number bumped without being read.
    same = [i for i in ("pickem", "div_home_dog", "div_road_fav") if i in by]
    if len(same) == 3:
        recs = {i: (by[i]["all"]["w"], by[i]["all"]["l"]) for i in same}
        spread = max(w for w, _ in recs.values()) - min(w for w, _ in recs.values())
        assert spread <= 2, (
            f"these three no longer have near-identical records, so they no "
            f"longer demonstrate the false positive: {recs}")
        assert mir.get("div_home_dog") == "div_road_fav", mir.get("div_home_dog")
        assert "pickem" not in mir, (
            "pickem was paired on an identical record, which is the mistake "
            "the game-set half of the test exists to prevent")
