"""How often is a pick right, at the confidence the model claims?

`rank_economics` answers "does this pay at the price". This answers a different
question, and for a board read as a shortlist rather than a bet card it is the
more useful one: when the model says 0.55, how often does that player actually
score?

The two questions have opposite answers on anytime TD right now. Profitability
is negative at -5.7% [-10.5, -1.1], while the top pick is right 49.8% of the
time against a 16.2% base rate. A model can sort well and still not beat a
price, because the price already knows most of what the sorting knows.

**Bands are empirical, not the model's own claim.** Every rate here is measured
on backtested seasons the model did not train on, so "60%" means sixty games in
a hundred, not a number the calibrator asserted. That distinction earns its
keep immediately: measured on 849 held-out anytime-TD games,

    top pick, every game        849 games   49.8%
    top pick priced >= 0.50     339 games   58.4%
    top pick priced >= 0.55     233 games   59.7%
    top pick priced >= 0.60     132 games   53.0%   <- falls

The model's most confident band is its *least* accurate above 0.55. That is a
top-end calibration fault rather than a ceiling, and a UI that displayed the
model's own probability without this table would present those picks as the
best ones on the board.

**Intervals are game-clustered.** Two picks in one game share a defence, a game
script and a final score, so they are not independent draws — the same reason
`rank_economics.clustered_roi` resamples whole games, and the same factor of
about two in the width of the interval.
"""
from __future__ import annotations

import glob

import numpy as np
import polars as pl

from src.utils.paths import get_path

#: Below this many games a band's rate is a description of those games rather
#: than an estimate of anything. Matches rank_economics.MIN_BETS in spirit.
MIN_GAMES = 40

#: Band edges on the calibrated probability. Deliberately coarse: a finer grid
#: splits the top of the board into groups too small to resolve, which is how a
#: 132-game band comes to look like a finding.
DEFAULT_BANDS = (0.0, 0.20, 0.30, 0.40, 0.50, 0.55, 1.01)


def _load_backtests(target_type: str, model: str | None = None) -> pl.DataFrame | None:
    out = get_path("output", target_type)
    suffix = f"_{model}" if model else ""
    files = [f for f in sorted(glob.glob(str(out / f"backtest{suffix}_2*.csv")))
             if model or "_xgb_" not in f and "_ensemble_" not in f]
    if not files:
        return None
    df = pl.concat([pl.read_csv(f) for f in files], how="diagonal_relaxed")
    return df if df.height else None


def _prob_col(df: pl.DataFrame) -> str:
    """The column the board publishes, which is the blended one.

    `final` first, deliberately, and the opposite of `rank_economics`' choice.
    That module ranks on `prob_calibrated` because a bet is a disagreement with
    the price and blending is the act of conceding it. This module is describing
    the number displayed on screen: the board shows the blended probability, so
    bands measured on the pre-blend column would attach a rate to a value that
    was never the one being rated. The two differ — mean 0.1548 blended against
    0.1578 pre-blend — so it is a real mismatch, not a naming preference.
    """
    for c in ("final", "probability", "prob_calibrated"):
        if c in df.columns:
            return c
    raise KeyError(f"no probability column in {df.columns[:12]}")


def _label_col(df: pl.DataFrame) -> str:
    for c in ("actual", "target"):
        if c in df.columns:
            return c
    raise KeyError(f"no outcome column in {df.columns[:12]}")


def _clustered_rate(hit: np.ndarray, games: np.ndarray, draws: int = 2000,
                    seed: int = 0) -> tuple[float, float, float]:
    """Mean of `hit` with a game-clustered bootstrap interval."""
    if len(hit) == 0:
        return float("nan"), float("nan"), float("nan")
    uniq = np.unique(games)
    idx = {g: np.flatnonzero(games == g) for g in uniq}
    rng = np.random.default_rng(seed)
    boot = np.array([
        hit[np.concatenate([idx[uniq[i]]
                            for i in rng.choice(len(uniq), len(uniq), True)])].mean()
        for _ in range(draws)
    ])
    return float(hit.mean()), float(np.quantile(boot, 0.05)), float(np.quantile(boot, 0.95))


def top_pick_bands(target_type: str, model: str | None = None,
                   bands: tuple[float, ...] = DEFAULT_BANDS) -> dict | None:
    """Hit rate of each game's single best pick, by the confidence it carries.

    One row per game, because that is how the board is read: the question is
    "should I act on this week's top pick", not "how do all candidates score".
    """
    df = _load_backtests(target_type, model)
    if df is None:
        return None
    pc, lc = _prob_col(df), _label_col(df)

    top = df.sort(pc, descending=True).group_by("game_id").first()
    games_total = top.height
    base = float(df[lc].mean())

    rows = []
    for lo, hi in zip(bands[:-1], bands[1:]):
        sel = top.filter((pl.col(pc) >= lo) & (pl.col(pc) < hi))
        if sel.height < MIN_GAMES:
            continue
        rate, l, h = _clustered_rate(sel[lc].to_numpy().astype(float),
                                     sel["game_id"].to_numpy())
        rows.append({"lo": lo, "hi": hi, "games": sel.height,
                     "share_of_games": sel.height / games_total,
                     "hit_rate": rate, "lo_ci": l, "hi_ci": h,
                     "mean_claimed": float(sel[pc].mean())})

    # Cumulative view: "take every top pick at or above this confidence".
    cuts = []
    for lo in bands[:-1]:
        sel = top.filter(pl.col(pc) >= lo)
        if sel.height < MIN_GAMES:
            continue
        rate, l, h = _clustered_rate(sel[lc].to_numpy().astype(float),
                                     sel["game_id"].to_numpy())
        cuts.append({"threshold": lo, "games": sel.height,
                     "share_of_games": sel.height / games_total,
                     "hit_rate": rate, "lo_ci": l, "hi_ci": h})

    return {"target_type": target_type, "model": model, "games": games_total,
            "base_rate": base, "bands": rows, "cuts": cuts,
            "overall_hit_rate": float(top[lc].mean())}


def best_threshold(summary: dict, target: float = 0.60) -> dict | None:
    """The least selective cut whose measured rate clears `target`.

    Least selective rather than highest rate on purpose: the highest rate in a
    table is usually the smallest group, and picking it is choosing the noisiest
    cell. Returns None when nothing clears the bar, which is an answer.
    """
    if not summary or not summary.get("cuts"):
        return None
    ok = [c for c in summary["cuts"] if c["hit_rate"] >= target]
    return min(ok, key=lambda c: c["threshold"]) if ok else None
