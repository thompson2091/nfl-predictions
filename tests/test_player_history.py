"""A player's past lines: every join that can miss, and what it costs.

Every failure this file guards looked like a thin archive rather than a bug.
A join that drops the current season, a dedupe keyed on the book's spelling, a
name that never matched, an alternate line printed as the main one -- none of
them raises, and all of them render as a player who happens to have no history.
So the assertions here are about coverage and shape, not about values.
"""
import polars as pl
import pytest

from src.evaluation import player_history as PH


@pytest.fixture(scope="module")
def closing():
    return PH._closing()


def test_the_name_rules_match_the_ones_the_rest_of_the_project_uses():
    """Two normalizations differing by one rule fail on a handful of players.

    This one adds two cases and must otherwise agree with
    `odds_history._norm_expr` exactly, so a plain name has to come out the same
    from both.
    """
    from src.ingest.odds_history import _norm_expr

    names = ["Ja'Marr Chase", "A.J. Brown", "Marvin Harrison Jr.",
             "Kenneth Walker III", "Amon-Ra St. Brown", "Tank Dell"]
    d = pl.DataFrame({"n": names})
    mine = d.select(PH._norm(pl.col("n")).alias("k"))["k"].to_list()
    theirs = d.select(_norm_expr("n").alias("k"))["k"].to_list()
    assert mine == theirs, list(zip(names, mine, theirs))


def test_the_two_things_books_do_to_a_name_are_handled():
    """Both cost real players and both were found in the live archive.

    A curly apostrophe is not an ASCII one, and U+2019 against U+0027 is why
    Ja'Marr Chase was half missing. A bracketed team is how some books
    disambiguate two men with one name.
    """
    d = pl.DataFrame({"n": ["Ja’Marr Chase", "Ja'Marr Chase",
                            "Trey McBride (ARI)", "Michael Thomas (NO)"]})
    got = d.select(PH._norm(pl.col("n")).alias("k"))["k"].to_list()
    assert got[0] == got[1], got[:2]
    assert got[2] == "trey mcbride", got[2]
    assert got[3] == "michael thomas", got[3]


def test_most_of_the_archive_finds_an_actual(closing):
    """A silent join failure empties the section rather than breaking it.

    The four markets with a line should sit near 98%. The touchdown markets are
    lower on purpose and not a fault: they quote "no touchdown", "no scorer" and
    team defenses, none of which is a person with a stat line.
    """
    rate = PH.match_rate()
    for mkt in ("receptions", "receiving_yards", "rushing_yards",
                "passing_yards"):
        assert rate[mkt] is not None and rate[mkt] > 0.95, (
            f"{mkt} resolved {rate[mkt]:.1%}; a join is missing")
    for mkt in ("anytime_td", "first_td"):
        assert rate[mkt] is not None and rate[mkt] > 0.60, (
            f"{mkt} resolved {rate[mkt]:.1%}")


def test_this_seasons_weeks_are_in_it(closing):
    """THE BUG THIS EXISTS FOR, and it cost the only weeks anybody reads.

    The current season's rows arrive with a short game id -- `CIN_PIT` where
    every other season and the weekly stats say `2026_03_CIN_PIT` -- so every
    join on the id dropped them. Three rows out of sixty-five for one player,
    and 92.6% against 98.4% overall: small enough to look like an archive that
    had not caught up.
    """
    newest = closing["season"].max()
    short = closing.filter(~pl.col("game_id").str.contains(r"^\d{4}_"))
    assert short.height == 0, (
        f"{short.height} rows still carry a short game id, so they will not "
        f"join to anything")
    h = PH.history(last=None)
    seasons = {r[0] for per in h.values() for rows in per.values()
               for r in rows}
    assert newest in seasons, (
        f"the archive holds {newest} and the history stops at {max(seasons)}")


def test_a_player_gets_one_row_per_week_per_market():
    """A book that spells a man two ways left him in twice.

    The dedupe used to key on the book's own spelling, so "Joe Burrow" and
    "Joe Burrow (CIN)" both survived and one week drew two bars.
    """
    h = PH.history(last=None)
    for mkt, per in h.items():
        for who, rows in per.items():
            weeks = [(r[0], r[1]) for r in rows]
            assert len(weeks) == len(set(weeks)), (
                f"{who} has {len(weeks) - len(set(weeks))} duplicate weeks in "
                f"{mkt}")


def test_the_line_shown_is_the_main_one_not_an_alternate():
    """Books hang several points on one player and only one is his line.

    Taking the newest capture picked among them arbitrarily, which printed
    Chase at 2.5 for -200 as "his line that week". The main line is the one
    priced nearest a coin flip, so the prices on a two-sided market should
    cluster near even rather than spread to the ends.
    """
    h = PH.history(last=None)
    odds = [r[5] for r in h["receptions"].values().__iter__().__next__()] \
        if False else [r[5] for rows in h["receptions"].values() for r in rows
                       if r[5] is not None]
    assert odds, "no receptions prices at all"
    near = sum(1 for o in odds if -200 < o < 200)
    assert near / len(odds) > 0.9, (
        f"only {near / len(odds):.0%} of receptions prices are near even; "
        f"alternates are being picked over the main line")


def test_a_man_who_did_not_play_is_a_zero_not_a_gap():
    """The distortion this whole table exists to make visible.

    Joining prices to stat lines and keeping the matches deletes every week
    somebody was quoted and then sat out. On receptions that is about one
    player-game in nine and every one of them went under, so deleting them
    shows a rosier record than the one that happened -- in exactly the
    direction that flatters a reader into a bet.
    """
    h = PH.history(last=None)
    rows = [r for rows in h["receptions"].values() for r in rows]
    zeros = [r for r in rows if r[6] == 0]
    share = len(zeros) / len(rows)
    assert 0.05 < share < 0.25, (
        f"{share:.1%} of receptions weeks are zero; around 13% is the real "
        f"rate, so this is either dropping them or inventing them")


def test_the_board_looks_a_player_up_by_the_name_it_prints():
    """The page does `players[row.player]`, exactly as it does for injuries.

    Normalizing on the page would put the same rules in two places, one of them
    untested, and a rule that drifted would empty the section for a handful of
    players and look like a thin archive.
    """
    got = PH.for_board(["Ja’Marr Chase", "Ja'Marr Chase",
                        "Trey McBride (ARI)", "Nobody At All"], last=4)
    assert "Ja’Marr Chase" in got, sorted(got)
    assert "Ja'Marr Chase" in got, sorted(got)
    assert "Trey McBride (ARI)" in got, sorted(got)
    assert "Nobody At All" not in got
    # Filed under BOTH spellings, because the board may print either.
    assert (got["Ja’Marr Chase"]["receptions"]
            == got["Ja'Marr Chase"]["receptions"])
    for rows in got["Ja'Marr Chase"].values():
        assert len(rows) <= 4
        # Newest first, so a cap keeps the recent weeks.
        keys = [(r[0], r[1]) for r in rows]
        assert keys == sorted(keys, reverse=True), keys


def test_every_row_is_the_shape_the_page_unpacks():
    """`[season, week, opp, home, line, odds, did, played, other]`, in order.

    The page indexes these by position, so a field arriving in the wrong place
    is a silent mis-draw rather than an error.

    `played` is last and arrived last, which is why `v3PastMoney` treats a
    seven-field row as played: a cached payload written before it existed
    should keep its old answer rather than have every week voided.
    """
    h = PH.history(last=3)
    seen = 0
    for mkt, per in h.items():
        meta = [m for m in PH.market_meta() if m["key"] == mkt][0]
        for rows in per.values():
            for r in rows:
                assert len(r) == 9, r
                # A void is not a loss and a zero is not a void: the money
                # figure needs to tell them apart, and only this says so.
                assert r[7] in (0, 1), r
                # The fade's price, or nothing. Never a guess.
                assert r[8] is None or isinstance(r[8], int), r
                assert isinstance(r[0], int) and isinstance(r[1], int)
                assert isinstance(r[2], str) and r[3] in (0, 1)
                assert r[5] is None or isinstance(r[5], int)
                if meta["kind"] == "yesno":
                    assert r[6] in (0, 1), r
                else:
                    # Rushing yards go negative: a sack behind the line is a
                    # real week and a floor of zero would reject it.
                    assert isinstance(r[6], float), r
                seen += 1
            if seen > 2000:
                return
    assert seen > 100, f"only {seen} rows checked"


def test_the_other_side_is_recovered_only_where_it_was_really_quoted():
    """`overround` is p_yes + p_no, so the fade's price is arithmetic.

    It is arithmetic that means something on a line, where both sides are
    posted: the recovered probability has a median of 0.556 on receptions and
    0.535 on the yardage markets. On the touchdown markets it is 0.996 and
    1.000 — nobody posts "will not score" at -999900, and that figure is the
    complement of a longshot rather than a price. Pricing a fade off it would
    show a 99% win rate at a cent a bet.
    """
    h = PH.history(last=5)
    meta = {m["key"]: m for m in PH.market_meta()}
    for mkt, per in h.items():
        rows = [r for v in per.values() for r in v]
        if not rows:
            continue
        got = [r for r in rows if len(r) > 8 and r[8] is not None]
        if meta[mkt]["kind"] == "yesno":
            assert not got, (
                f"{mkt} recovered a fade price from a one-sided market")
        else:
            assert len(got) > len(rows) * 0.9, (
                f"{mkt}: only {len(got)} of {len(rows)} carry the other side")
            # And it is a price somebody could have taken.
            for r in got:
                assert abs(r[8]) >= 100, r
                assert abs(r[8]) <= 5000, (
                    f"{mkt}: {r[8]} is the complement of a longshot, not a "
                    "price")
