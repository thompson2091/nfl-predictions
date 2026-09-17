"""The quantile CDF, checked against distributions whose answer is known.

`src/models/yards.py` replaces a fitted distribution with an interpolated one,
so the thing that can silently go wrong is the interpolation rather than the
fit. These tests hand it quantiles taken from a distribution with a closed
form and ask it for probabilities that can be looked up.
"""
from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from src.models.yards import (QUANTILE_LEVELS, cdf, interval, prob_over,
                              quantile_at, rearrange)

LEVELS = QUANTILE_LEVELS


def _normal_rows(mus, sds):
    """Fitted-quantile matrix taken exactly from normals."""
    a = np.asarray(LEVELS)
    return np.stack([stats.norm.ppf(a, loc=m, scale=s)
                     for m, s in zip(mus, sds)])


def test_cdf_reproduces_the_levels_it_was_given():
    """At a fitted quantile the CDF must return that quantile's own level."""
    q = _normal_rows([250.0, 40.0], [60.0, 25.0])
    for j, a in enumerate(LEVELS):
        got = cdf(q, q[:, j])
        assert np.allclose(got, a, atol=1e-9), f"level {a}: {got}"


def test_cdf_recovers_a_normal_between_the_fitted_points():
    """Interpolated between levels, not just at them.

    Tolerance is the honest cost of 21 straight segments across a curve, and
    it is asserted rather than described: 0.006 is roughly half a cent on a
    coin-flip price, and a looser bound here would let a real interpolation
    bug through.
    """
    mu, sd = 250.0, 60.0
    q = _normal_rows([mu], [sd])
    xs = np.linspace(mu - 2.0 * sd, mu + 2.0 * sd, 60)
    got = np.array([cdf(q, np.array([x]))[0] for x in xs])
    want = stats.norm.cdf(xs, mu, sd)
    assert np.max(np.abs(got - want)) < 0.006, np.max(np.abs(got - want))


def test_prob_over_at_the_median_is_a_coin_flip():
    """A line ON the median prices at 50%, whatever the row's spread.

    The medians here are deliberately fractional. A whole-number line takes
    the continuity correction in `prob_over` and is a genuinely different
    question — the half-yard band around it carries real mass on a tight row,
    which `test_whole_number_line_carries_push_mass...` covers separately.
    """
    q = _normal_rows([250.3, 40.3, 8.3], [60.0, 25.0, 9.0])
    med = quantile_at(q, 0.5)
    over, push = prob_over(q, med)
    assert np.all(push == 0.0)
    assert np.allclose(over, 0.5, atol=1e-9), over


def test_cdf_is_monotone_across_the_whole_line():
    """Including through both tail joins, where two rules meet."""
    q = _normal_rows([250.0], [60.0])
    xs = np.linspace(-200.0, 700.0, 4000)
    f = np.array([cdf(q, np.array([x]))[0] for x in xs])
    assert np.all(np.diff(f) >= -1e-12), "CDF went backwards"
    assert f[0] < 1e-3 and f[-1] > 0.999


def test_tails_are_continuous_at_the_join():
    """The exponential tail must meet the interpolation at the outermost quantile.

    A discontinuity here would price a line one yard below the 2nd percentile
    completely differently from one at it, which is the kind of jump that shows
    up as a fake edge rather than as an error.
    """
    q = _normal_rows([250.0], [60.0])
    for edge, expect in ((q[0, 0], LEVELS[0]), (q[0, -1], LEVELS[-1])):
        inside = cdf(q, np.array([edge + 1e-6]))[0]
        outside = cdf(q, np.array([edge - 1e-6]))[0]
        assert abs(inside - outside) < 1e-4, (edge, inside, outside)
        assert abs(inside - expect) < 1e-3


def test_tail_does_not_price_every_far_line_identically():
    """The reason the tail is exponential rather than clamped.

    Books post a 0.5-yard rushing line on quarterbacks. If the rule below the
    lowest fitted quantile were a clamp, every line down there would carry the
    same probability and the column would stop separating anyone.
    """
    q = _normal_rows([60.0], [30.0])
    lo = q[0, 0]
    a = cdf(q, np.array([lo - 5.0]))[0]
    b = cdf(q, np.array([lo - 25.0]))[0]
    assert a > b > 0.0, (a, b)
    assert a < LEVELS[0]


def test_wide_row_gets_a_wider_tail_than_a_narrow_one():
    """The tail scale comes from the fitted gap, not from a constant."""
    q = _normal_rows([60.0, 60.0], [10.0, 60.0])
    drop = np.array([q[0, 0], q[1, 0]]) - 5.0
    f = cdf(q, drop)
    # Five yards below its own 2nd percentile is a bigger step for the tight
    # distribution than for the wide one, so its CDF must fall further.
    assert f[0] < f[1], f


def test_whole_number_line_carries_push_mass_and_a_half_point_does_not():
    q = _normal_rows([40.0], [20.0])
    over_w, push_w = prob_over(q, np.array([40.0]))
    over_h, push_h = prob_over(q, np.array([40.5]))
    assert push_h[0] == 0.0
    assert push_w[0] > 0.0
    # The push band is [39.5, 40.5]; over on the whole line excludes it.
    assert over_w[0] < over_h[0] + 1e-9
    assert abs((over_w[0] + push_w[0]) - cdf(q, np.array([39.5]))[0] * 0 -
               (1.0 - cdf(q, np.array([39.5]))[0])) < 1e-9


def test_rearrange_repairs_crossing_and_leaves_sorted_rows_alone():
    good = np.array([[1.0, 2.0, 3.0]])
    assert np.array_equal(rearrange(good), good)
    crossed = np.array([[1.0, 5.0, 3.0]])
    assert np.array_equal(rearrange(crossed), np.array([[1.0, 3.0, 5.0]]))


def test_prob_over_sorts_before_pricing():
    """A crossed row must not reach the CDF, whoever hands it over.

    Asserted against the exact right answer rather than a plausible band. The
    bucket index in `cdf` is a count of quantiles at or below the line, which
    is order-independent — so a crossed row lands in the RIGHT bucket and
    reads the WRONG two bounds out of it. A loose assertion here passes with
    the sort removed, which is how this test was caught not testing itself.

    Levels 0.50 and 0.55 sit at 50.0 and 52.51 for this row, so a line at 50.5
    is a fifth of the way across that step: F = 0.50 + 0.05 * 0.2 = 0.510 and
    the over is 0.490. Unsorted, the step is read backwards and the answer is
    0.450 — a four-point error, which on a coin-flip market is the difference
    between no bet and a large one.
    """
    a = np.asarray(LEVELS)
    q = stats.norm.ppf(a, loc=50, scale=20)[None, :].copy()
    q[0, 10], q[0, 11] = q[0, 11], q[0, 10]        # cross the median
    over, _ = prob_over(q, np.array([50.5]))
    assert abs(over[0] - 0.490) < 0.002, over


def test_interval_is_the_fitted_15_and_85():
    q = _normal_rows([250.0], [60.0])
    lo, hi = interval(q)
    assert np.allclose(lo, stats.norm.ppf(0.15, 250, 60), atol=1e-8)
    assert np.allclose(hi, stats.norm.ppf(0.85, 250, 60), atol=1e-8)
    assert lo[0] < hi[0]


def test_interval_separates_two_rows_with_the_same_median():
    """The column exists to tell a target hog from a deep threat."""
    q = _normal_rows([40.0, 40.0], [8.0, 35.0])
    lo, hi = interval(q)
    assert (hi - lo)[1] > 3 * (hi - lo)[0]


def test_negative_outcomes_are_representable():
    """Gamma, Tweedie and the negative binomial cannot do this, and 7.5% of
    rushing player-games are negative."""
    q = _normal_rows([4.0], [8.0])
    assert q[0, 0] < 0
    over, _ = prob_over(q, np.array([-0.5]))
    assert 0.5 < over[0] < 1.0, over


def test_shape_can_differ_between_rows_which_is_the_whole_point():
    """A skewed row and a symmetric one, priced from the same call."""
    a = np.asarray(LEVELS)
    sym = stats.norm.ppf(a, loc=100, scale=30)
    skew = stats.lognorm.ppf(a, s=1.0, scale=20)
    q = np.stack([sym, skew])
    med = quantile_at(q, 0.5)
    # Same question of both: how much mass sits two medians out?
    far_sym = 1.0 - cdf(q, np.array([med[0] * 2, med[1] * 2]))[0]
    far_skew = 1.0 - cdf(q, np.array([med[0] * 2, med[1] * 2]))[1]
    assert far_skew > far_sym * 2, (far_sym, far_skew)


def test_line_vector_length_is_checked():
    q = _normal_rows([250.0, 40.0], [60.0, 25.0])
    with pytest.raises(ValueError):
        cdf(q, np.array([250.0]))
