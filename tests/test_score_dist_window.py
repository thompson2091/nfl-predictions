"""The exact-score table is counted on its own, wider comparable set.

`SPREAD_TOL`/`TOTAL_TOL` serve the margin bands and the totals, where
conditioning on the line earns its keep — walk-forward Brier on "home covers"
is 0.162 conditioned against 0.173 unconditioned. An exact scoreline is a
different question: at that window no scoreline in a comparable set has been
seen more than once or twice, so 40% of games led with a score that had
happened twice, and the page called it the most likely final.
"""
from __future__ import annotations

import pytest

from src.models import score_dist as sd


@pytest.fixture(scope="module")
def hist():
    h = sd.history()
    if h.is_empty():
        pytest.skip("no schedules on disk")
    return h


def test_the_scores_window_is_wider_than_the_bands_window():
    """If these ever converge, the table is back to counting anecdotes."""
    assert sd.SCORE_SPREAD_TOL > sd.SPREAD_TOL
    assert sd.SCORE_TOTAL_TOL > sd.TOTAL_TOL


def test_every_scoreline_shown_has_really_happened_enough_times(hist):
    """THE NOISE THIS REMOVED. A scoreline seen twice is not a forecast."""
    s = sd.summary(6.5, 44.5, "GB", "ATL", hist=hist)
    assert s["scores"], "no scorelines survived the floor"
    for r in s["scores"]:
        # `n` is the count from the set the RANKING used, so it is directly
        # comparable with the floor. It used to come from the narrow band,
        # which put "seen 4 times" beside a row ranked on 30 occurrences.
        assert r["n"] >= sd.SCORE_MIN_SEEN, (
            f"{r['home']}-{r['away']} was seen {r['n']} times, "
            f"below SCORE_MIN_SEEN={sd.SCORE_MIN_SEEN}")


def test_the_scores_are_counted_on_a_bigger_set_than_the_bands(hist):
    """`scores_n` exists precisely because it differs from `n`. The page
    prints "26 of N" and reading N off the bands would overstate the rate
    several-fold."""
    s = sd.summary(6.5, 44.5, "GB", "ATL", hist=hist)
    assert s["scores_n"] > s["n"], (
        f"scores counted on {s['scores_n']} vs bands on {s['n']}")


def test_the_probability_is_the_measured_rate_not_the_share(hist):
    """`p` is what the k-th pick ACTUALLY lands, measured walk-forward — not
    this scoreline's share of the lookalike games.

    The share said nothing about whether we picked well: a scoreline can be
    common in general and a poor call here. The kernel's own weight is no use
    either — normalized it gives the top pick 19.4% against a measured 1.37%.
    """
    s = sd.summary(6.5, 44.5, "GB", "ATL", hist=hist)
    rates = sd._rank_rates(())
    assert rates, "no measured rank rates"
    # `rates` is per TIER now, not per rank: the record separates three steps
    # and no more, so rates[0] is the top pick's.
    assert s["scores"][0]["p"] == pytest.approx(100 * rates[0], abs=0.01)
    # And it is emphatically NOT the share of the comparable set.
    top = s["scores"][0]
    share = 100 * top["n"] / s["scores_n"]
    assert abs(top["p"] - share) > 0.05, (
        "p has collapsed back into the historical share")


def test_the_number_steps_exactly_where_the_record_separates(hist):
    """Three tiers, because three is what the measurement supports.

    Ranks 2-5 against 6-10 is z=+0.50 — one band — while 6-10 against 11-20 is
    z=+2.54 and is real. Nine descending numbers would invent an order the
    outcomes do not have; one flat number for sixteen rows hides a step that
    is there.
    """
    s = sd.summary(6.5, 44.5, "GB", "ATL", hist=hist)
    ps = [r["p"] for r in s["scores"]]
    assert len(set(ps)) == len(sd.SCORE_TIERS), (
        f"{len(set(ps))} distinct numbers, expected {len(sd.SCORE_TIERS)}")
    # And they descend: a later tier can never be likelier than an earlier one.
    assert ps == sorted(ps, reverse=True), ps
    assert ps[0] > ps[-1], "the list does not step down at all"


def test_the_card_says_what_the_whole_list_is_worth(hist):
    """Eight rows of near-identical percentages invite picking one. The number
    a reader needs is that the entire list is a long shot."""
    s = sd.summary(6.5, 44.5, "GB", "ATL", hist=hist)
    assert 2.0 < s["scores_covered"] < 15.0, s["scores_covered"]


def test_the_list_is_ordered_for_this_game_not_the_league(hist):
    """The whole point of the kernel. A three-point game and a seven-point
    game must not lead with the same scoreline."""
    a = sd.summary(-3.0, 45.5, "DAL", "BAL", hist=hist)["scores"][0]
    b = sd.summary(7.0, 44.5, "GB", "ATL", hist=hist)["scores"][0]
    assert (a["home"], a["away"]) != (b["home"], b["away"]), (
        "both games led with the same scoreline")


def test_a_shootout_still_does_not_show_a_defensive_scoreline(hist):
    """The window is wide, not absent. It has to keep excluding the genuinely
    different game or it is just the league's all-time list."""
    s = sd.summary(0.0, 54.0, "AAA", "BBB", hist=hist)
    if not s["scores"]:
        pytest.skip("no scorelines at this line")
    totals = [r["home"] + r["away"] for r in s["scores"]]
    assert min(totals) >= 30, f"a 54-point game offered {min(totals)} points"


def test_the_modal_is_no_longer_a_six_way_tie(hist):
    """At the old window 10 of 16 games had a tied most-common score and one
    had six level at two games each, which is what made the build
    non-deterministic in the first place."""
    s = sd.summary(6.5, 44.5, "GB", "ATL", hist=hist)
    assert s["modal_tied"] <= 2, (
        f"{s['modal_tied']} scorelines tied for most common")
    assert s["modal"]["n"] >= sd.SCORE_MIN_SEEN
