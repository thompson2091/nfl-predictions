"""Where the market is wrong, and why its margin eats the difference anyway.

Every negative return in this project has the same explanation, and it is not
about the model. Split the priced population by the bookmaker's own de-vigged
number and three columns fall out:

  * **What the book says**, margin removed.
  * **What actually happened.**
  * **What the posted price implied**, margin included — the number you are
    actually paying.

The first two show a textbook favorite-longshot bias: on anytime TD the book's
de-vigged number is nearly three points too high on its longest shots and more
than a point too low on its shortest. That is a real, exploitable-looking error
in the direction everyone expects.

The third column is why it is not exploitable. The margin is larger than the
bias at every decile, so the posted price is above the realized rate everywhere
— worst at the bottom, where a two-point error costs half the stake, and least
bad at the top, where it costs eight percent. That single table explains the
whole ROI ladder in `rank_economics.by_odds_bucket` without reference to the
model at all, and it is the reason the best available answer in this project is
"lose 8%" rather than "win".

It also explains the one thing that does measure positive. The book being three
points high on longshots *is* the fade edge: `shortlist_backtest.fade_side`
prices laying that group at +25%, on the side no book sells. Overpriced
longshots and a profitable fade are the same fact seen from two directions.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.evaluation.combo_backtest import _season, backtest_files
from src.evaluation.rank_economics import clustered_roi

#: How many slices of the priced population. Ten is what a reader can hold, and
#: with ~20,000 bets it leaves ~2,000 a row — enough that a decile's realized
#: rate is a measurement rather than a rumour.
DECILES = 10


def measure(target_type: str, model: str, deciles: int = DECILES) -> dict | None:
    """The book's own number, the outcome, and the price, by decile.

    Sliced on the *de-vigged* market number rather than on the posted odds, so
    the rows are ordered by the bookmaker's opinion rather than by its margin —
    which is the whole point, since the two columns then separate what the book
    believes from what it charges.
    """
    frames = []
    for path in backtest_files(target_type, model):
        df = pd.read_csv(path)
        if not {"market_prob", "scored", "dec", "game_id"} <= set(df.columns):
            continue
        df["season"] = _season(path)
        frames.append(df)
    if not frames:
        return None

    df = pd.concat(frames, ignore_index=True).dropna(
        subset=["market_prob", "scored", "dec"])
    if df.empty:
        return None
    df["pnl"] = np.where(df["scored"] == 1, df["dec"].astype(float) - 1.0, -1.0)

    try:
        bucket = pd.qcut(df["market_prob"], deciles, labels=False,
                         duplicates="drop")
    except ValueError:
        return None

    rows = []
    for i in sorted(pd.unique(bucket.dropna())):
        part = df[bucket == i]
        if part.empty:
            continue
        stat = clustered_roi(part["pnl"].to_numpy(), part["game_id"].to_numpy())
        # The same rows from the other side: backing "No" at the de-vigged
        # price. No model is involved — this is the market's own bias and
        # nothing else, which is what makes the band it marks out a fact about
        # the market rather than a fact about us.
        mp = part["market_prob"].to_numpy()
        lay_pnl = np.where(part["scored"].to_numpy() == 1,
                           -(1.0 - mp) / mp, 1.0)
        lay = clustered_roi(lay_pnl, part["game_id"].to_numpy())
        book = float(part["market_prob"].mean()) * 100
        actual = float(part["scored"].mean()) * 100
        posted = float(np.mean(1.0 / part["dec"].astype(float))) * 100
        rows.append({
            "decile": int(i) + 1,
            "n": int(len(part)),
            "book_pct": book,
            "actual_pct": actual,
            # What the book's opinion gets wrong, before it charges anything.
            "book_error_pp": book - actual,
            "posted_pct": posted,
            # What it charges for that opinion.
            "margin_pp": posted - book,
            # What you pay above the truth: the sum of the two, and the reason
            # every row of this table loses.
            "overpay_pp": posted - actual,
            "median_odds": float(part["odds"].median())
            if "odds" in part.columns else None,
            "roi": stat["roi"], "lo": stat["lo"], "hi": stat["hi"],
            "verdict": stat["verdict"],
            "lay_roi": lay["roi"], "lay_lo": lay["lo"], "lay_hi": lay["hi"],
            # What a No price could charge here before the bias is gone.
            "lay_carries_pct": ((1 - float(part["scored"].mean()))
                                / (1 - float(part["market_prob"].mean())) - 1) * 100,
        })
    if not rows:
        return None
    # The band where the market's own bias pays for itself: the run of deciles
    # whose lay interval clears zero. Derived rather than chosen, so a re-run
    # on new seasons moves the band instead of leaving a hand-picked one
    # describing a market that has changed.
    payers = [r for r in rows if r["lay_lo"] > 0]
    fade_band = None
    if payers:
        lo, hi = min(r["decile"] for r in payers), max(r["decile"] for r in payers)
        inside = [r for r in rows if lo <= r["decile"] <= hi]
        n = sum(r["n"] for r in inside)
        fade_band = {
            "deciles": [lo, hi],
            "book_lo_pct": min(r["book_pct"] for r in inside),
            "book_hi_pct": max(r["book_pct"] for r in inside),
            "n": n,
            # Weighted by bets, so the summary describes the band rather than
            # the average of its rows.
            "book_pct": sum(r["book_pct"] * r["n"] for r in inside) / n,
            "actual_pct": sum(r["actual_pct"] * r["n"] for r in inside) / n,
        }
        fade_band["carries_pct"] = (
            (1 - fade_band["actual_pct"] / 100)
            / (1 - fade_band["book_pct"] / 100) - 1) * 100

    seasons = sorted(df["season"].unique().tolist())
    return {
        "kind": "market_shape",
        "fade_band": fade_band,
        "target_type": target_type, "model": model,
        "seasons": [int(s) for s in seasons],
        "span": f"{seasons[0]}-{seasons[-1]}" if seasons else "",
        "deciles": len(rows),
        "rows": rows,
    }


def load(path) -> dict | None:
    import json
    from pathlib import Path

    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else None
