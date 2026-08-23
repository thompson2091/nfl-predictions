"""The table that explains every negative return here without the model.

The failure this pins is a decomposition that does not add up. `book error` and
`margin` have to sum to `overpay`, and `overpay` has to be the thing that
decides the return — if those come apart, the table tells a story about the
bookmaker that its own columns do not support.

    pytest tests/test_market_shape.py -v
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.evaluation.market_shape import measure


def _frame(n: int, book: float, actual_rate: float, margin: float,
           seed: int = 0) -> pd.DataFrame:
    """A market whose opinion and margin are both known exactly."""
    rng = np.random.default_rng(seed)
    posted = book + margin
    return pd.DataFrame({
        "market_prob": np.full(n, book),
        "scored": (rng.random(n) < actual_rate).astype(float),
        "dec": np.full(n, 1.0 / posted),
        "odds": np.full(n, 100.0),
        "game_id": [f"g{i // 4}" for i in range(n)],
    })


def test_the_decomposition_adds_up(monkeypatch, tmp_path):
    """book error + margin = overpay, or the columns are three stories."""
    df = pd.concat([_frame(4000, 0.05, 0.03, 0.02, seed=1),
                    _frame(4000, 0.40, 0.42, 0.05, seed=2)],
                   ignore_index=True)
    path = tmp_path / "backtest_xgb_2024.csv"
    df.to_csv(path, index=False)
    monkeypatch.setattr("src.evaluation.market_shape.backtest_files",
                        lambda tt, m: [path])
    out = measure("anytime_td", "xgb", deciles=2)
    assert out is not None and len(out["rows"]) == 2
    for r in out["rows"]:
        assert r["book_error_pp"] + r["margin_pp"] == pytest.approx(
            r["overpay_pp"], abs=1e-9)
        assert r["margin_pp"] == pytest.approx(
            r["posted_pct"] - r["book_pct"], abs=1e-9)


def test_the_bias_and_the_margin_are_reported_separately(monkeypatch, tmp_path):
    """A book can be wrong and still be too expensive, and those differ.

    The bottom slice here is a market that is two points too high on a longshot;
    the top is one that is two points too *low* on a favourite. Both lose money
    at the posted price, and only this split says why.
    """
    df = pd.concat([_frame(6000, 0.05, 0.03, 0.02, seed=3),
                    _frame(6000, 0.40, 0.42, 0.05, seed=4)],
                   ignore_index=True)
    path = tmp_path / "backtest_xgb_2024.csv"
    df.to_csv(path, index=False)
    monkeypatch.setattr("src.evaluation.market_shape.backtest_files",
                        lambda tt, m: [path])
    lo, hi = measure("anytime_td", "xgb", deciles=2)["rows"]
    assert lo["book_error_pp"] > 0, "overpriced longshot"
    assert hi["book_error_pp"] < 0, "underpriced favourite"
    # The phenomenon the real table shows: similar overpay in points, wildly
    # different returns. Four points above the truth is most of a 5% price and
    # a tenth of a 40% one, which is why the return column and the points
    # column have to sit side by side to be read at all.
    assert lo["roi"] < hi["roi"] < 0
    assert abs(lo["overpay_pp"] - hi["overpay_pp"]) < 1.5, (
        "the fixture is built with comparable overpay at both ends")
    assert lo["roi"] < hi["roi"] - 20, (
        "the same overpay has to cost far more at the longshot end, or the "
        "table is not explaining the ROI ladder it claims to explain")


def test_no_priced_backtest_is_no_table(monkeypatch):
    monkeypatch.setattr("src.evaluation.market_shape.backtest_files",
                        lambda tt, m: [])
    assert measure("anytime_td", "xgb") is None
