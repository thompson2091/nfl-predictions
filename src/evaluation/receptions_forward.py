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

import json

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
    from src.prediction.receptions import (expected_counts, load_blend,
                                           load_model)
    from src.models.count import blend_to_market, fair_two_way, prob_over

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
    raw = fair_two_way(over, push)
    # Graded on what the board serves, which is the blend. Grading the raw
    # model would report a number nobody is shown and would keep saying the
    # market is better after the change that made it not be.
    w = load_blend()
    served = raw if w is None else blend_to_market(raw, j["fair_prob"].to_numpy(), w)
    return j.with_columns([
        pl.Series("p_model_raw", raw),
        pl.Series("p_model", served),
        (pl.col("receptions") > pl.col("point")).cast(pl.Float64).alias("y_over"),
        (pl.col("receptions") == pl.col("point")).alias("push"),
    ])


#: Settled lines needed before the live season is allowed to fit its own blend
#: weight. One free parameter does not need many, but a weight refitted on two
#: weeks would swing with each of them and the number being served would be
#: chasing noise it had just seen. Receptions settle at roughly 280 lines a
#: week, so this is about week eight.
MIN_BLEND_LINES = 2000


def _shipped_weight() -> float | None:
    """The weight fitted at training time, which is the fallback."""
    path = get_path("models", "receptions") / "market_blend.json"
    if not path.exists():
        return None
    try:
        return float(json.loads(path.read_text())["weight"])
    except Exception:                                            # noqa: BLE001
        return None


def refit_blend(season: int, min_n: int = MIN_BLEND_LINES,
                write: bool = True) -> dict | None:
    """Refit the market blend on the season being played, once it can carry it.

    The weight shipped with the model is fitted on 2024 and fixed. It is
    holding up — 2025 out of sample, and 2026 week 1 — but a weight fitted two
    seasons ago is an assumption about how much the model adds *now*, and the
    live season is the only evidence about that.

    Fitted on every line settled so far and applied to the weeks after, so what
    it serves is always out of sample for the week it is serving. It is
    deliberately NOT what the forward record grades with: see
    `walk_forward_weights`.
    """
    from src.models.count import fit_market_blend

    g = graded(season)
    if g is None or g.height == 0:
        return None
    live = g.filter(~pl.col("push"))
    if live.height < min_n:
        return None

    out = fit_market_blend(live["p_model_raw"].to_numpy(),
                           live["fair_prob"].to_numpy(),
                           live["y_over"].to_numpy())
    out["fitted_on"] = season
    out["through_week"] = int(live["week"].max())
    out["live"] = True
    if write:
        path = get_path("models", "receptions") / "market_blend_live.json"
        path.write_text(json.dumps(out, indent=1))
        out["path"] = str(path)
    return out


def walk_forward_weights(live: pl.DataFrame, fallback: float) -> dict[int, float]:
    """The weight in force for each week, fitted only on the weeks before it.

    Without this, refitting on the live season would make the forward record
    in-sample for its own weight and the headline would improve for no reason
    anyone should believe. A week is graded with what could have been known
    before it kicked off, which for the early weeks is the weight shipped with
    the model.
    """
    from src.models.count import fit_market_blend

    weeks = sorted(live["week"].unique().to_list())
    out, w = {}, fallback
    for wk in weeks:
        out[int(wk)] = w
        prior = live.filter(pl.col("week") <= wk)
        if prior.height >= MIN_BLEND_LINES:
            w = fit_market_blend(prior["p_model_raw"].to_numpy(),
                                 prior["fair_prob"].to_numpy(),
                                 prior["y_over"].to_numpy())["weight"]
    return out


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
        raw = d["p_model_raw"].to_numpy() if "p_model_raw" in d.columns else pm
        return {
            "n": int(d.height),
            "over_rate": float(y.mean()),
            "raw_log_loss": _log_loss(raw, y),
            "model_log_loss": _log_loss(pm, y),
            "market_log_loss": _log_loss(pk, y),
            "model_brier": float(np.mean((pm - y) ** 2)),
            "market_brier": float(np.mean((pk - y) ** 2)),
        }

    # Grade each week with the weight that could have been known before it
    # kicked off. Serving uses everything settled so far, which is right for a
    # bet; grading must not, or the record is in sample for its own weight.
    from src.models.count import blend_to_market
    from src.prediction.receptions import load_blend

    shipped = _shipped_weight()
    by_week = walk_forward_weights(live, shipped if shipped is not None else 1.0)
    live = live.with_columns(
        pl.col("week").replace_strict(by_week, default=shipped or 1.0).alias("_w"))
    live = live.with_columns(pl.Series("p_model", blend_to_market(
        live["p_model_raw"].to_numpy(), live["fair_prob"].to_numpy(), 0.0)))
    # `blend_to_market` takes one weight, so apply it per distinct value.
    served = live["p_model_raw"].to_numpy().copy()
    for w in sorted(set(by_week.values())):
        sel = (live["_w"] == w).to_numpy()
        if sel.any():
            served[sel] = blend_to_market(live["p_model_raw"].to_numpy()[sel],
                                          live["fair_prob"].to_numpy()[sel], w)
    live = live.with_columns(pl.Series("p_model", served))

    weeks = []
    for wk in sorted(live["week"].unique().to_list()):
        d = live.filter(pl.col("week") == wk)
        if d.height < 2:
            continue
        weeks.append({"week": int(wk), "weight": float(by_week[int(wk)]), **block(d)})

    pooled = block(live)
    return {
        "season": season,
        "pushes": int(g["push"].sum()),
        "pooled": pooled,
        "weeks": weeks,
        # The honest headline. It is expected to be False.
        "beats_market": pooled["model_log_loss"] < pooled["market_log_loss"],
        # The alarm, and it is a different question from the one above.
        #
        # What we serve is the model shrunk toward the book, and it is
        # *supposed* to beat the book — that is what the blend was fitted to
        # do, measured out of sample on 2025 and again here. So "we are ahead"
        # is no longer a warning sign and a flag that fired on it would cry
        # wolf every week.
        #
        # The raw model beating the market is still a warning sign, because
        # nothing has made that plausible: it loses by 0.017 on 2025 and 0.028
        # here, and every previous time it appeared to win it was a leak.
        "raw_beats_market": pooled["raw_log_loss"] < pooled["market_log_loss"],
        "weights": {str(k): v for k, v in by_week.items()},
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
        f"  log loss  served {p['model_log_loss']:.4f}  "
        f"market {p['market_log_loss']:.4f}  "
        f"raw {p['raw_log_loss']:.4f}  "
        f"-> {'MODEL' if r['beats_market'] else 'market'} better",
    ]
    for w in r["weeks"]:
        tag = "model" if w["model_log_loss"] < w["market_log_loss"] else "market"
        lines.append(f"    week {w['week']:>2}  n={w['n']:>4}  "
                     f"model {w['model_log_loss']:.4f}  "
                     f"market {w['market_log_loss']:.4f}  ({tag})")
    if r["raw_beats_market"]:
        lines.append("  THE RAW MODEL IS AHEAD OF THE MARKET, which nothing "
                     "makes plausible — it loses\n  by 0.017 on 2025 — and "
                     "which has meant a leak every previous time. Check\n"
                     "  before believing it.")
    elif r["beats_market"]:
        lines.append("  Ahead of the market, which is what the blend was "
                     "fitted to do: 17% of our\n  number against 83% of the "
                     "book's, fitted on a season it never trained on. The\n"
                     "  gain is real and small; it is not a betting edge.")
    return "\n".join(lines)
