"""The over/under models' own probability, put on the scale it lands on.

The yardage and catches models price a line from a predicted distribution, and
that distribution is too narrow: measured 2026-10-09 on the 2024-25 backtests,
the raw over probability is about five times too extreme in log-odds (Platt
slope 0.18 receiving, 0.19 rushing, 0.38 catches). "Model only" is the
headline column of the props page and the record's first line, and on 2026 it
reads worse than a coin flip (log loss 0.70-0.73 against the book's 0.69),
while the adjusted column — the same number shrunk toward the book — does not.

This is a two-number map, fitted where the trees never looked:

    p_cal = expit(a + b * logit(p_raw))

`b` undoes the overconfidence and `a` any level offset. It is monotone, so it
never reorders a player's lines or the board, and it leaves the distribution
(the projection, the interval) alone: only the probability a line is beaten
is rescaled. The blend toward the book is then fitted on the calibrated
number, so "adjusted" is a blend of two calibrated opinions.

Fitted per market, like the blend (`evaluation.prop_blend`), and saved twice:

    ou_calibration.json          validation season only — what is REPORTED,
                                 so the test season stays out of sample
    ou_calibration_served.json   every out-of-tree season — what is SERVED

`load` reads the served file first. Absent both, the raw number passes through
unchanged and `calibrated` says so.
"""
from __future__ import annotations

import json
from datetime import date

import numpy as np

MARKETS = ("receptions", "receiving_yards", "rushing_yards", "passing_yards")
REPORT_FILE = "ou_calibration.json"
SERVED_FILE = "ou_calibration_served.json"

_EPS = 1e-6


def _logit(p):
    q = np.clip(np.asarray(p, dtype=float), _EPS, 1 - _EPS)
    return np.log(q / (1 - q))


def _expit(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=float)))


def log_loss(p, y) -> float:
    p = np.clip(np.asarray(p, dtype=float), _EPS, 1 - _EPS)
    y = np.asarray(y, dtype=float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def fit(p_raw, y) -> dict:
    """(a, b) by maximum likelihood: logistic regression of y on logit(p_raw).

    Newton's method on two parameters, unregularised — there are thousands of
    rows and two numbers, and a penalty would only pull `b` toward zero, which
    is a direction this fit already has a strong opinion about.
    """
    x = _logit(p_raw)
    y = np.asarray(y, dtype=float)
    X = np.column_stack([np.ones_like(x), x])

    def nll(beta):
        z = X @ beta
        return float(np.sum(np.logaddexp(0, z) - y * z))

    # From the flat model (b = 0), with step halving: Newton started at b = 1
    # on a model this overconfident takes its first step from weights near
    # zero and runs off to infinity.
    m = float(np.clip(y.mean(), _EPS, 1 - _EPS))
    beta = np.array([np.log(m / (1 - m)), 0.0])
    cur = nll(beta)
    for _ in range(100):
        p = _expit(X @ beta)
        g = X.T @ (y - p)
        H = (X * (p * (1 - p))[:, None]).T @ X
        step = np.linalg.solve(H + 1e-9 * np.eye(2), g)
        t = 1.0
        while t > 1e-6 and nll(beta + t * step) > cur:
            t /= 2
        beta = beta + t * step
        new = nll(beta)
        if cur - new < 1e-10:
            break
        cur = new
    a, b = float(beta[0]), float(beta[1])
    return {"a": a, "b": b, "n": int(len(y)),
            "log_loss_raw": log_loss(p_raw, y),
            "log_loss_calibrated": log_loss(apply(p_raw, {"a": a, "b": b}), y)}


def apply(p_raw, cal: dict | None):
    """The calibrated probability, or `p_raw` untouched when unfitted."""
    if not cal:
        return np.asarray(p_raw, dtype=float)
    return _expit(cal["a"] + cal["b"] * _logit(p_raw))


def load(market: str, model_dir=None) -> dict | None:
    """The served calibration, then the validation-only one, else None."""
    from src.utils.paths import get_path

    root = model_dir or get_path("models", market)
    for name in (SERVED_FILE, REPORT_FILE):
        path = root / name
        if not path.exists():
            continue
        try:
            cal = json.loads(path.read_text())
            if {"a", "b"} <= set(cal) and cal["b"] > 0:
                return cal
        except Exception:                                        # noqa: BLE001
            continue
    return None


def refit(market: str, write: bool = True) -> dict | None:
    """Fit both files for one market from its out-of-tree backtests.

    The report fit (validation season) is scored on the test season, which is
    the out-of-sample claim; the served fit uses both. Each line a backtest
    graded is a row, as in the blend fit.
    """
    from src.evaluation.prop_blend import _backtest, out_of_tree_seasons
    from src.utils.paths import get_path

    val, test = out_of_tree_seasons()
    dv, dt = _backtest(market, val), _backtest(market, test)
    if dv is None or dt is None:
        return None
    raw = "p_model_raw" if "p_model_raw" in dv.columns else "p_model"
    rep = fit(dv[raw].to_numpy(), dv["y_over"].to_numpy())
    pt, yt, bt = (dt[raw].to_numpy(), dt["y_over"].to_numpy(),
                  dt["fair_prob"].to_numpy())
    rep.update({
        "kind": f"{market}_ou_calibration", "fitted_on": [val],
        "scored_on": test,
        "test_log_loss_raw": log_loss(pt, yt),
        "test_log_loss_calibrated": log_loss(apply(pt, rep), yt),
        "test_log_loss_book": log_loss(bt, yt),
        "fit_date": date.today().isoformat(),
    })
    both = np.concatenate([dv[raw].to_numpy(), pt])
    yb = np.concatenate([dv["y_over"].to_numpy(), yt])
    srv = fit(both, yb)
    srv.update({"kind": f"{market}_ou_calibration_served",
                "fitted_on": [val, test], "validation": {k: rep[k] for k in ("a", "b")},
                "fit_date": date.today().isoformat()})
    if write:
        from src.utils.history import write_kept

        root = get_path("models", market)
        write_kept(root / REPORT_FILE, json.dumps(rep, indent=1))
        write_kept(root / SERVED_FILE, json.dumps(srv, indent=1))
    return {"report": rep, "served": srv}


def calibrate_market(market: str) -> dict | None:
    """After a training script writes its backtests: fit, rewrite, refit.

    1. Fit both calibration files from the backtests' raw number.
    2. Rewrite each backtest with `p_model` calibrated by the VALIDATION fit
       and the raw number kept as `p_model_raw`. The test season is then
       scored by a map it never saw, so every downstream reader of these
       files (the served blend, the Gaps margins, the shortlist backtest, the
       confidence bands) works on the number the board will show.
    3. Refit the validation blend (`market_blend.json`) on the calibrated
       number. The served blend is refit by the caller, as before, and reads
       the served calibration through `prop_blend._backtest`.

    Idempotent: a backtest that already has `p_model_raw` is calibrated from
    that column, never from its own calibrated output.
    """
    import polars as pl

    from src.evaluation.prop_blend import out_of_tree_seasons
    from src.models.count import fit_market_blend
    from src.utils.paths import get_path

    out_dir = get_path("output", market)
    paths = {s: out_dir / f"backtest_{s}.csv" for s in out_of_tree_seasons()}
    if not all(p.exists() for p in paths.values()):
        return None
    for p in paths.values():
        d = pl.read_csv(p)
        if "p_model_raw" not in d.columns:
            d.with_columns(pl.col("p_model").alias("p_model_raw")).write_csv(p)
    got = refit(market, write=True)
    if got is None:
        return None
    rep = got["report"]
    for p in paths.values():
        d = pl.read_csv(p)
        d.with_columns(pl.Series("p_model", apply(d["p_model_raw"].to_numpy(), rep))
                       ).write_csv(p)
    val = pl.read_csv(paths[out_of_tree_seasons()[0]]).drop_nulls(
        ["p_model", "fair_prob", "y_over"])
    blend = fit_market_blend(val["p_model"].to_numpy(), val["fair_prob"].to_numpy(),
                             val["y_over"].to_numpy(), kind=f"{market}_market_blend")
    blend["fitted_on"] = out_of_tree_seasons()[0]
    blend["on"] = "calibrated"
    (get_path("models", market) / "market_blend.json").write_text(
        json.dumps(blend, indent=1))
    print(f"  calibration: slope {rep['b']:.3f}, offset {rep['a']:+.3f} on "
          f"{rep['fitted_on']}; {rep['scored_on']} log loss raw "
          f"{rep['test_log_loss_raw']:.5f} -> {rep['test_log_loss_calibrated']:.5f} "
          f"(book {rep['test_log_loss_book']:.5f}); served slope "
          f"{got['served']['b']:.3f}; blend on calibrated keeps {blend['weight']:.0%}")
    return {"calibration": got, "blend": blend}
