"""How the count model is doing on the season being played, week by week.

`scripts/30_receptions.py` grades the model on held-out history, which answers
"was this ever any good". It cannot answer "is it any good now", and those come
apart: the backtest reads a backfilled archive where the historical endpoint
returns exactly one closing price per player and line, while the live season is
assembled from captures that fire several times a Sunday, overlap each other,
and keep quoting after kickoff.

So this is deliberately not the same code path. It deduplicates, it drops
in-play prices (`odds_history.drop_in_play`), and it reports per week rather
than pooled, because a pooled figure over three weeks hides the week the model
fell over.

What it is for is the claim in `src/prediction/receptions.py`: that the market
prices this market better than we do. That is a measurement, and a measurement
made once in August is an assertion by September. This re-makes it every week
against the prices actually on offer, and it is expected to keep saying the
market is better. The week it says otherwise is the week to look for a leak
rather than to start betting — the first version of this model beat receptions
by +17-22% ROI and that was the NGS existence leak.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from src.utils.paths import get_path


def _log_loss(p: np.ndarray, y: np.ndarray) -> float:
    q = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))


def graded(season: int, snapshot: str = "close") -> pl.DataFrame | None:
    """Every posted line of the season that has since been settled.

    One row per (week, player, line): what the book charged, what we said, and
    what he caught. Weeks still to be played drop out on the weekly-stats join,
    which is the only gate needed — a player with no stat line did not play.
    """
    from src.ingest.odds_history import (HISTORY_PATH, SCHEMA, _conform,
                                         _resolve_player_id, drop_in_play,
                                         resolve_game_ids)
    from src.prediction.receptions import expected_counts, load_model
    from src.models.count import fair_two_way, prob_over

    art = load_model()
    if art is None or not HISTORY_PATH.exists():
        return None

    h = _conform(pl.read_parquet(HISTORY_PATH), SCHEMA).filter(
        (pl.col("market") == "receptions") & (pl.col("season") == season)
        & (pl.col("snapshot") == snapshot) & pl.col("point").is_not_null()
        & pl.col("fair_prob").is_not_null())
    if h.height == 0:
        return None

    # Resolve, then drop in-play, then keep the newest of what is left. The
    # order is load-bearing: the kickoff is looked up by game id, and an
    # in-play quote is the newest by construction, so deduplicating first would
    # select exactly the rows the next step exists to remove.
    h = drop_in_play(resolve_game_ids(h))
    if h.height == 0:
        return None
    h = h.with_columns(_resolve_player_id(h))
    h = (h.filter(pl.col("player_id").is_not_null())
          .sort("captured_at")
          .unique(subset=["week", "player_id", "point"], keep="last"))

    mus = []
    for week in sorted(h["week"].unique().to_list()):
        m = expected_counts(season, int(week), art)
        if m is not None and m.height:
            mus.append(m.select(["season", "week", "player_id", "mu"]))
    if not mus:
        return None
    mu = pl.concat(mus, how="vertical")

    ws = (pl.scan_parquet(get_path("raw") / "weekly_stats.parquet")
          .select(["season", "week", "player_id", "receptions"]).collect())

    j = (h.join(mu, on=["season", "week", "player_id"], how="inner")
          .join(ws, on=["season", "week", "player_id"], how="inner")
          .filter(pl.col("receptions").is_not_null()))
    if j.height == 0:
        return None

    over, push = prob_over(j["mu"].to_numpy(), j["point"].to_numpy(),
                           float(art["dispersion"]))
    return j.with_columns([
        pl.Series("p_model", fair_two_way(over, push)),
        (pl.col("receptions") > pl.col("point")).cast(pl.Float64).alias("y_over"),
        (pl.col("receptions") == pl.col("point")).alias("push"),
    ])


def record(season: int) -> dict | None:
    """The forward measurement, pooled and per week.

    `beats_market` is stated rather than left to be inferred, the same way
    `scripts/30_receptions.py` states it, because a table of two log losses
    invites the reader to squint at which is smaller.
    """
    g = graded(season)
    if g is None or g.height == 0:
        return None

    # A whole-number line that lands exactly is a push: stake returned, neither
    # side graded. Scoring it as a loss would penalise both us and the market
    # for an outcome neither of them called wrong.
    live = g.filter(~pl.col("push"))
    if live.height == 0:
        return None

    def block(d: pl.DataFrame) -> dict:
        y = d["y_over"].to_numpy()
        pm, pk = d["p_model"].to_numpy(), d["fair_prob"].to_numpy()
        return {
            "n": int(d.height),
            "over_rate": float(y.mean()),
            "model_log_loss": _log_loss(pm, y),
            "market_log_loss": _log_loss(pk, y),
            "model_brier": float(np.mean((pm - y) ** 2)),
            "market_brier": float(np.mean((pk - y) ** 2)),
        }

    weeks = []
    for wk in sorted(live["week"].unique().to_list()):
        d = live.filter(pl.col("week") == wk)
        if d.height < 2:
            continue
        weeks.append({"week": int(wk), **block(d)})

    pooled = block(live)
    return {
        "season": season,
        "pushes": int(g["push"].sum()),
        "pooled": pooled,
        "weeks": weeks,
        # The honest headline. It is expected to be False.
        "beats_market": pooled["model_log_loss"] < pooled["market_log_loss"],
        "note": (
            "Log loss, lower is better. The market is the de-vigged two-sided "
            "price. This is measured on the prices actually on offer before "
            "kickoff, so it is what betting the model would have faced."
        ),
    }


def report(season: int) -> str:
    r = record(season)
    if r is None:
        return (f"RECEPTIONS FORWARD — nothing settled yet for {season}.\n"
                f"  Needs archived closing lines and a played week.")
    p = r["pooled"]
    lines = [
        f"RECEPTIONS FORWARD — {season}",
        f"  {p['n']:,} settled lines ({r['pushes']} pushes), "
        f"over rate {p['over_rate']:.1%}",
        f"  log loss  model {p['model_log_loss']:.4f}  "
        f"market {p['market_log_loss']:.4f}  "
        f"-> {'MODEL' if r['beats_market'] else 'market'} better",
    ]
    for w in r["weeks"]:
        tag = "model" if w["model_log_loss"] < w["market_log_loss"] else "market"
        lines.append(f"    week {w['week']:>2}  n={w['n']:>4}  "
                     f"model {w['model_log_loss']:.4f}  "
                     f"market {w['market_log_loss']:.4f}  ({tag})")
    if r["beats_market"]:
        lines.append("  The model is ahead of the market. On this market that "
                     "has meant a leak every\n  previous time it has happened. "
                     "Check before believing it.")
    return "\n".join(lines)
