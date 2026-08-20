"""What a full cover would actually have returned, week by week.

`cover.portfolio` prices a cover from model probabilities and today's odds. It
says what *should* happen. This says what *did*: the same rule replayed over
every graded backtest week, with the prices that were actually on the board and
the players who actually scored.

The distinction matters more here than anywhere else on the page. A cover's
expected value is a product of five estimates and five prices, and a product
compounds whatever is wrong with each term. If the model is 2 points
overconfident per leg, a single is 2 points wrong and a five-fold is closer to
10 — so the gap between what a cover is projected to return and what it returns
is the sharpest available reading on calibration. It is also the number nobody
can argue with: slips either landed or they did not.

**The rule replayed.** Each week, take the top N of the board by the published
column, one player per game, and back every non-empty subset at a flat stake.
One per game rather than N from one fixture because a single game's top five
are usually teammates, which correlates the legs and guts the all-score tail.

**Only priced legs.** A cover cannot be graded without a payout for every leg,
so a week contributes only the players a book had priced. That biases the pool
toward games books post early, and the summary says how much of the board it
kept rather than leaving it implied.
"""
from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from src.evaluation.combo_backtest import backtest_files
from src.prediction.bets import american_to_decimal

#: Pool sizes replayed. Two is the smallest cover that is not a single, and
#: eight is 255 slips — past there a week's outlay dwarfs any sane bankroll and
#: the tail carries the whole result.
SIZES = (3, 4, 5, 6, 7, 8)


def _season(path: Path) -> int:
    return int(path.stem.split("_")[-1])


def load_weeks(target_type: str, model: str | None = None) -> list[dict]:
    """Every graded week as a priced, ranked board."""
    from src.evaluation.hit_rates import _label_col, _prob_col

    weeks = []
    for path in backtest_files(target_type, model):
        df = pd.read_csv(path)
        if "week" not in df.columns:
            continue
        try:
            pc = _prob_col(__import__("polars").from_pandas(df.head(1)))
            lc = _label_col(__import__("polars").from_pandas(df.head(1)))
        except KeyError:
            continue
        if "odds" not in df.columns:
            continue
        d = df.dropna(subset=["odds", pc, lc])
        if "has_market_price" in d.columns:
            d = d[d["has_market_price"].astype(bool)]
        if d.empty:
            continue
        for week, chunk in d.groupby("week"):
            weeks.append({
                "season": _season(path), "week": int(week),
                # Underscored names, because the frames already carry a
                # `scored` column of their own and renaming the label column
                # onto it produced two columns with one name — after which
                # `board["scored"]` is a DataFrame and every comparison raises
                # "truth value of an array is ambiguous".
                "board": chunk.rename(columns={pc: "_p", lc: "_hit"})
                              .reset_index(drop=True),
                "n_priced": len(chunk),
            })
    return weeks


def replay_week(board: pd.DataFrame, n: int, stake: float = 1.0) -> dict | None:
    """Back every subset of this week's top `n`, one per game, and grade it."""
    top = (board.sort_values("_p", ascending=False)
                .drop_duplicates(subset=["game_id"], keep="first")
                .head(n))
    if len(top) < n:
        return None

    dec = top["odds"].astype(float).map(american_to_decimal).to_numpy()
    hit = top["_hit"].astype(float).to_numpy()
    if not np.isfinite(dec).all():
        return None

    idx = range(n)
    staked = returned = 0.0
    slips = won = 0
    for size in range(1, n + 1):
        for legs in combinations(idx, size):
            slips += 1
            staked += stake
            if hit[list(legs)].all():
                won += 1
                returned += stake * float(np.prod(dec[list(legs)]))

    singles_staked = stake * slips
    per = singles_staked / n
    singles_returned = float(sum(per * d for d, h in zip(dec, hit) if h))

    return {
        "n": n, "slips": slips, "staked": staked, "returned": returned,
        "net": returned - staked, "won": won,
        "scorers": int(hit.sum()),
        "model_prob": float(top["_p"].mean()),
        "singles_net": singles_returned - singles_staked,
    }


def measure(target_type: str, model: str | None = None,
            stake: float = 1.0) -> dict | None:
    """Replay every pool size over every graded week."""
    weeks = load_weeks(target_type, model)
    if not weeks:
        return None

    out = {"target_type": target_type, "model": model, "stake": stake,
           "weeks": len(weeks),
           "span": f"{min(w['season'] for w in weeks)}-"
                   f"{max(w['season'] for w in weeks)}",
           "sizes": []}

    for n in SIZES:
        rows = [r for w in weeks if (r := replay_week(w["board"], n, stake))]
        if len(rows) < 8:
            continue
        staked = sum(r["staked"] for r in rows)
        returned = sum(r["returned"] for r in rows)
        net = returned - staked
        singles = sum(r["singles_net"] for r in rows)
        scorers = np.array([r["scorers"] for r in rows])
        # The distribution that decides everything: a cover lives or dies on
        # how often the top end of it lands, and that tail is thin.
        dist = {int(k): int((scorers == k).sum()) for k in range(n + 1)}
        profitable = [r for r in rows if r["net"] > 0]
        # A week-clustered bootstrap, because the point estimate is worthless
        # here without one. A cover's return is carried by its rarest weeks:
        # first TD at N=3 read +52.7% off 10 profitable weeks in 60 with the
        # single best week supplying 35.5% of everything returned. Resampling
        # weeks is the honest interval — the week is the independent unit, and
        # the skew is the whole story.
        rng = np.random.default_rng(20260819)
        nets = np.array([r["net"] for r in rows])
        stakes = np.array([r["staked"] for r in rows])
        draws = rng.integers(0, len(rows), size=(2000, len(rows)))
        boot = nets[draws].sum(axis=1) / np.maximum(stakes[draws].sum(axis=1), 1e-9)
        out["sizes"].append({
            "n": n, "weeks": len(rows), "slips_per_week": rows[0]["slips"],
            "staked": staked, "returned": returned, "net": net,
            "roi": net / staked if staked else 0.0,
            "singles_net": singles,
            "singles_roi": singles / staked if staked else 0.0,
            "weeks_profitable": len(profitable),
            "best_week": max(r["net"] for r in rows),
            "worst_week": min(r["net"] for r in rows),
            "mean_scorers": float(scorers.mean()),
            "scorer_distribution": dist,
            # A cover's return is dominated by its rarest outcomes, so the
            # share carried by the single best week says whether the headline
            # is a rate or an anecdote.
            "top_week_share": (max(r["returned"] for r in rows) / returned
                               if returned else None),
            "roi_lo": float(np.quantile(boot, 0.05)),
            "roi_hi": float(np.quantile(boot, 0.95)),
            "roi_beats_zero": bool(np.quantile(boot, 0.05) > 0),
        })

    if not out["sizes"]:
        return None
    best = max(out["sizes"], key=lambda s: s["roi"])
    out["best_size"] = best["n"]
    out["best_roi"] = best["roi"]
    # "Profitable" means the interval clears zero, not that the point estimate
    # is positive. Nothing here has ever cleared it.
    out["any_profitable"] = any(s["roi_beats_zero"] for s in out["sizes"])
    out["best_point_estimate_positive"] = best["roi"] > 0
    return out


def save(stats: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats, indent=2) + "\n")
    return path


def load(path: Path) -> dict | None:
    if not Path(path).exists():
        return None
    return json.loads(Path(path).read_text())
