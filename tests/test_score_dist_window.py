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


def test_the_percentage_matches_its_own_denominator(hist):
    """One definition per number: `pct` must be `n / scores_n`, not `n / n`."""
    s = sd.summary(6.5, 44.5, "GB", "ATL", hist=hist)
    for r in s["scores"]:
        assert r["pct"] == pytest.approx(r["n"] / s["scores_n"] * 100, abs=0.06)


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
