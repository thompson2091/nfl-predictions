"""How well we sort the players a sportsbook has written off.

This module used to open by calling the longshot band "the board's largest
measured edge over the market" — the book's ordering at AUC 0.54 against ours
at 0.76, described as stable across three seasons with a bootstrap interval
nowhere near zero. Re-measured on 2026-08-18 after two existence leaks were
closed:

    ours 0.55   book 0.52   (n = 6,624, +1500 or longer, 2023-2025)

The gap was 0.22 and is now 0.025. Almost all of it was the leak. Both NGS
availability and the weekly-stats families told the model which players had
actually played and been used that week, and in a band that is mostly deep
reserves — the third tight end, the backup back — that bit separates the
handful who were active and involved from the majority who were not. That is
exactly the distinction the band's AUC was rewarding, and it is not available
before kickoff.

What survives is a genuine but small ordering advantage over a book that
barely orders this band at all, and the price premium, which is unchanged and
large: the tail is priced at about 4.8% against a true rate of 2.4%, so the
book charges roughly a 95% margin there and blind betting the band loses about
half its stake. Our best-rated tenth comes in at 3.3% against a price implying
5.5% — below the price, not above it.

So the honest reading is now the opposite of the original: this band is where
the book's margin is largest and our remaining advantage is smallest. The
module still measures the sorting and still publishes the premium beside it,
so nothing in the app can quote one without the other.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from src.utils.paths import get_path

#: American price at or beyond which a player counts as a longshot. Chosen as
#: the point where the book's within-band ordering stops being informative, not
#: tuned for returns.
LONGSHOT_ODDS = 1500


def measure(target_type: str = "anytime_td",
            seasons: list[int] | None = None) -> dict | None:
    """Compare our ordering against the book's inside the longshot band.

    Reads the walk-forward backtest CSVs, so it describes the same production
    path the app publishes rather than raw model output.
    """
    from sklearn.metrics import roc_auc_score

    out_dir = get_path("output", target_type)
    frames = []
    for path in sorted(out_dir.glob("backtest_*.csv")):
        season = int(path.stem.split("_")[-1])
        if seasons and season not in seasons:
            continue
        frames.append(pl.read_csv(path).with_columns(pl.lit(season).alias("season")))
    if not frames:
        return None

    df = pl.concat(frames, how="diagonal_relaxed")
    for col in ("odds", "final", "market_prob", "scored", "dec"):
        if col not in df.columns:
            return None

    band = df.filter(pl.col("odds") >= LONGSHOT_ODDS)
    y = band["scored"].to_numpy().astype(float)
    if band.height < 200 or y.sum() < 20:
        return None

    ours = band["final"].to_numpy()
    book = band["market_prob"].to_numpy()
    price_implied = (1.0 / band["dec"].to_numpy())

    rng = np.random.default_rng(0)
    gaps = []
    for _ in range(2000):
        i = rng.integers(0, len(y), len(y))
        if 0 < y[i].sum() < len(i):
            gaps.append(roc_auc_score(y[i], ours[i]) - roc_auc_score(y[i], book[i]))
    gaps = np.array(gaps)

    # What the app's highlight actually surfaces: our best-rated tenth.
    cut = float(np.quantile(ours, 0.90))
    top = band.filter(pl.col("final") >= cut)
    weeks = max(band["season"].n_unique() * 18, 1)

    return {
        "target_type": target_type,
        "min_odds": LONGSHOT_ODDS,
        "seasons": sorted(band["season"].unique().to_list()),
        "n": band.height,
        "scorers": int(y.sum()),
        "auc_ours": float(roc_auc_score(y, ours)),
        "auc_book": float(roc_auc_score(y, book)),
        "auc_gap": float(roc_auc_score(y, ours) - roc_auc_score(y, book)),
        "auc_gap_lo": float(np.percentile(gaps, 2.5)),
        "auc_gap_hi": float(np.percentile(gaps, 97.5)),
        # The honest counterweight to the AUC: the band is priced well above
        # what it does, so sorting it well is not the same as beating it.
        "band_actual_rate": float(y.mean()),
        "band_price_implied": float(price_implied.mean()),
        "band_flat_roi": float(
            (y * (band["dec"].to_numpy() - 1) - (1 - y)).mean()
        ),
        "top_decile_n": top.height,
        "top_decile_per_week": top.height / weeks,
        "top_decile_actual": float(top["scored"].mean()),
        "top_decile_price_implied": float((1.0 / top["dec"].to_numpy()).mean()),
    }


def save(stats: dict, path: Path) -> None:
    Path(path).write_text(json.dumps(stats, indent=2))


def load(path: Path) -> dict | None:
    if not Path(path).exists():
        return None
    return json.loads(Path(path).read_text())
