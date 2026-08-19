"""The receptions confidence panel must not overstate what it measured.

The panel exists because the model's stated confidence is not its hit rate —
it claims 85% and lands 69% on held-out seasons. A panel that reports that
badly is worse than no panel, so these pin the arithmetic that the copy on the
page depends on.

    pytest tests/test_receptions_hit_rates.py -v
"""
from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.evaluation.receptions_hit_rates import (BANDS, _sided, calibration,
                                                 selectivity, sweep)


def test_confidence_is_read_on_the_side_taken_not_on_the_over():
    """A strong under call is a strong call.

    P(over)=0.18 means "he goes under, and we are 82% sure". Grading it on the
    over would score a confident correct pick as a 18% claim that missed, and
    would report the model as far worse calibrated than it is — in the
    direction that makes the panel's warning look worse than the truth.
    """
    df = pl.DataFrame({
        "p_model": [0.18, 0.82, 0.55],
        "y_over": [0.0, 1.0, 0.0],
        "game_id": ["g1", "g1", "g2"],
    })
    out = _sided(df, "p_model")
    assert out["side"].to_list() == ["under", "over", "over"]
    assert out["conf"].to_list() == pytest.approx([0.82, 0.82, 0.55])
    # The under call was right (he did not go over) and so was the over call.
    assert out["hit"].to_list() == [1.0, 1.0, 0.0]


def test_bands_start_at_a_coin_flip_because_confidence_cannot_be_lower():
    """`max(p, 1-p)` is bounded below by 0.5; bands starting at 0 would be empty."""
    assert BANDS[0] == 0.50
    assert BANDS[-1] > 1.0, "the top edge must be exclusive-safe for conf == 1.0"


def test_a_perfectly_calibrated_model_reads_as_honest():
    """The control: if claims match outcomes, no band is flagged.

    Without this, a bug that always reports overconfidence would look exactly
    like the finding the panel is built on.
    """
    rng = np.random.default_rng(0)
    n = 4000
    p = rng.uniform(0.5, 0.95, n)
    y = (rng.uniform(size=n) < p).astype(float)
    df = pl.DataFrame({"p_model": p, "y_over": y,
                       "game_id": [f"g{i % 200}" for i in range(n)]})
    out = _sided(df, "p_model")
    for lo, hi in zip(BANDS, BANDS[1:]):
        m = out.filter((pl.col("conf") >= lo) & (pl.col("conf") < hi))
        if m.height < 200:
            continue
        claimed, measured = m["conf"].mean(), m["hit"].mean()
        assert abs(measured - claimed) < 0.05, (
            f"band {lo}-{hi}: a calibrated generator read {measured:.3f} "
            f"against {claimed:.3f}; the measurement itself is biased")


def test_selectivity_reports_the_coverage_it_costs():
    """A threshold without its share is unusable: 100% accuracy on zero rows."""
    out = selectivity(0.60)
    if out is None:
        pytest.skip("no receptions backtests in this checkout")
    assert 0.0 <= out["share"] <= 1.0
    assert out["n"] > 0 and out["games"] > 0
    assert out["ci_lo"] <= out["measured"] <= out["ci_hi"]

    tighter = selectivity(0.80)
    assert tighter["n"] <= out["n"], "a higher bar cannot keep more rows"
    assert tighter["share"] <= out["share"]


def test_the_panels_headline_claim_still_holds():
    """The page says the model runs hot and worst at the top. Hold it to that.

    If a retrain fixes the calibration this fails, which is the point — the
    warning copy in `render_receptions_selectivity` would then be false and has
    to be rewritten with it.
    """
    cal = calibration()
    if cal is None:
        pytest.skip("no receptions backtests in this checkout")

    top = max(cal["bands"], key=lambda b: b["lo"])
    assert top["measured"] < top["claimed"], (
        "the panel warns that the top band overstates; it no longer does")
    assert not top["honest"], (
        "the top band's claim now sits inside its own interval — the warning "
        "on the page is no longer supported and must be rewritten")

    gaps = [b["gap"] for b in sorted(cal["bands"], key=lambda b: b["lo"])]
    assert gaps[-1] <= gaps[0], (
        "the page says the gap widens with the claim; it no longer does")


def test_the_sweep_is_monotone_in_coverage_if_not_in_accuracy():
    """Accuracy may plateau — that is the finding — but coverage must fall."""
    rows = sweep()
    if not rows:
        pytest.skip("no receptions backtests in this checkout")
    shares = [r["share"] for r in rows]
    assert shares == sorted(shares, reverse=True), (
        "raising the threshold must keep fewer lines")
