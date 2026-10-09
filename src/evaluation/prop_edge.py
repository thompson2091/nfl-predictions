"""Bet only where our number beats the price by more than a fitted margin.

The card's player rows bet EVERY player-game on whichever side our number
leans, at any size of lean and any price. A 0.4-point lean on a -160 under is
a bet there, which is why the row tracks the book's margin rather than the
model. This is the rule that row was standing in for, pre-registered:

    edge = our blended P(over) - the book's de-vigged P(over)
    over  if edge >  threshold
    under if edge < -threshold
    paid at the median archived price OF THE SIDE TAKEN

**ONE LINE PER PLAYER-GAME, CHOSEN BEFORE THE EDGE IS LOOKED AT.** The line
closest to that player's median line — the card's own rule — so the threshold
cannot go shopping among seventeen alternates for the one that clears it.

**THE UNDER'S OWN PRICE.** `odds_books` carries both sides per book from 2023;
the backtests carry only the over (`fair_prob` is two-way de-vigged, the price
is not). A bet with no archived price for its side is not a bet.

**SCRATCHES ARE VOID**, as books void them — see `prop_settlement`. The
backtests are inner-joined to `weekly_stats`, so a scratch is already absent
there; so, unavoidably, is a player who played and recorded nothing, which
flatters overs and short-changes unders by a little. Conditioning on projected
usage, which the blind-under study needed, is not needed here: that study
GRADED scratches, and a voided scratch carries no artifact.

**THE THRESHOLD IS FITTED, WALK-FORWARD.** Per market, on the seasons before
the one being scored, by return on the grid below, with a floor on bets so a
threshold that finds twelve lucky ones cannot win. Saved with provenance in
`models/<market>/edge_threshold.json`.
"""
from __future__ import annotations

import json
from datetime import date

import numpy as np
import polars as pl

MARKETS = ("receptions", "receiving_yards", "rushing_yards", "passing_yards")

#: Thresholds tried, in percentage points of probability. Half-point steps:
#: finer than the de-vig's own rounding is pretending.
GRID = tuple(x / 2 for x in range(0, 31))

#: Fewest bets a season-pooled threshold may rest on. Below it the fit picks
#: noise: at 100 bets a return's standard error is about ten points.
MIN_BETS = 150

FILE = "edge_threshold.json"


def payout(odds: float) -> float:
    o = float(odds)
    return o / 100.0 if o > 0 else 100.0 / abs(o)


def main_lines(d: pl.DataFrame, keys=("season", "week", "game_id", "player_key"),
               line: str = "point") -> pl.DataFrame:
    """One row per player-game: the line closest to his median line."""
    med = pl.col(line).median().over(list(keys))
    return (d.with_columns((pl.col(line) - med).abs().alias("_off"))
             .sort(["_off", line])
             .unique(subset=list(keys), keep="first")
             .drop("_off"))


def attach_prices(d: pl.DataFrame, season: int, market: str) -> pl.DataFrame:
    """Median over and under prices, joined on game, player, line."""
    from src.evaluation.prop_settlement import side_prices

    p = side_prices(season)
    if p is None or p.is_empty():
        return d.with_columns(pl.lit(None, dtype=pl.Float64).alias("price_over"),
                              pl.lit(None, dtype=pl.Float64).alias("price_under"))
    p = p.filter(pl.col("market") == market)
    ov = (p.filter(pl.col("side") == "yes")
           .select(["game_id", "player_name_norm", "point",
                    pl.col("odds").cast(pl.Float64).alias("price_over")]))
    un = (p.filter(pl.col("side") == "no")
           .select(["game_id", "player_name_norm", "point",
                    pl.col("odds").cast(pl.Float64).alias("price_under")]))
    k = ["game_id", "player_name_norm", "point"]
    return (d.with_columns(pl.col("point").cast(pl.Float64))
             .join(ov.with_columns(pl.col("point").cast(pl.Float64)), on=k, how="left")
             .join(un.with_columns(pl.col("point").cast(pl.Float64)), on=k, how="left"))


def select(d: pl.DataFrame, threshold_pp: float) -> pl.DataFrame:
    """The bets the rule takes. Needs `p_blend`, `fair_prob` and both prices.

    Adds `side`, `edge_pp` (signed toward the side taken) and `price`.
    """
    e = (pl.col("p_blend") - pl.col("fair_prob")) * 100
    t = float(threshold_pp)
    d = d.with_columns(e.alias("_e"))
    d = d.with_columns(
        pl.when(pl.col("_e") > t).then(pl.lit("over"))
          .when(pl.col("_e") < -t).then(pl.lit("under"))
          .otherwise(None).alias("side"))
    d = d.filter(pl.col("side").is_not_null()).with_columns(
        pl.when(pl.col("side") == "over").then(pl.col("_e"))
          .otherwise(-pl.col("_e")).alias("edge_pp"),
        pl.when(pl.col("side") == "over").then(pl.col("price_over"))
          .otherwise(pl.col("price_under")).alias("price"))
    return d.filter(pl.col("price").is_not_null()).drop("_e")


def returns(bets: pl.DataFrame, won_col: str = "won") -> np.ndarray:
    pr = bets["price"].to_numpy()
    won = bets[won_col].to_numpy().astype(bool)
    return np.where(won, [payout(x) for x in pr], -1.0)


def cluster_ci(r: np.ndarray, games: np.ndarray, n_boot: int = 2000,
               seed: int = 0) -> tuple[float, float, float]:
    """Mean return and a 95% interval resampling whole games."""
    if len(r) == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    u, inv = np.unique(games, return_inverse=True)
    sums = np.bincount(inv, weights=r)
    cnts = np.bincount(inv)
    bs = []
    for _ in range(n_boot):
        k = rng.integers(0, len(u), len(u))
        bs.append(sums[k].sum() / cnts[k].sum())
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return float(r.mean()), float(lo), float(hi)


def backtest_frame(market: str, season: int, weight: float) -> pl.DataFrame | None:
    """A season's backtest at one line per player-game, blended and priced."""
    from src.models.count import blend_to_market
    from src.prediction.predict import _norm_name_expr
    from src.utils.paths import get_path

    path = get_path("output", market) / f"backtest_{season}.csv"
    if not path.exists():
        return None
    d = pl.read_csv(path).drop_nulls(["p_model", "fair_prob", "y_over"])
    d = d.with_columns(_norm_name_expr("player_name_raw").alias("player_name_norm"),
                       pl.col("player_id").alias("player_key"))
    d = main_lines(d)
    d = d.with_columns(pl.Series("p_blend", blend_to_market(
        d["p_model"].to_numpy(), d["fair_prob"].to_numpy(), weight)))
    return attach_prices(d, season, market)


def _score(d: pl.DataFrame, t: float) -> tuple[int, float]:
    b = select(d, t)
    if b.is_empty():
        return 0, float("nan")
    b = b.with_columns(
        pl.when(pl.col("side") == "over").then(pl.col("y_over") == 1)
          .otherwise(pl.col("y_over") == 0).alias("won"))
    return b.height, float(returns(b).mean())


def fit_threshold(frames: list[pl.DataFrame], min_bets: int = MIN_BETS) -> dict:
    """The grid threshold with the best pooled return over `frames`."""
    d = pl.concat(frames, how="vertical_relaxed")
    curve = []
    for t in GRID:
        n, roi = _score(d, t)
        curve.append({"threshold_pp": t, "n": n, "roi": roi})
    ok = [c for c in curve if c["n"] >= min_bets and c["roi"] == c["roi"]]
    best = max(ok, key=lambda c: c["roi"]) if ok else None
    return {"threshold_pp": best["threshold_pp"] if best else None,
            "fit_roi": best["roi"] if best else None,
            "fit_n": best["n"] if best else 0, "curve": curve}


def refit(market: str, seasons: list[int], weight: float,
          write: bool = True) -> dict | None:
    """Fit and save one market's threshold on `seasons`, at serving weight."""
    from src.utils.paths import get_path

    frames = [f for s in seasons if (f := backtest_frame(market, s, weight)) is not None]
    if not frames:
        return None
    got = fit_threshold(frames)
    out = {"kind": f"{market}_edge_threshold", "threshold_pp": got["threshold_pp"],
           "fit_roi": got["fit_roi"], "fit_n": got["fit_n"],
           "blend_weight": weight, "fitted_on": sorted(seasons),
           "min_bets": MIN_BETS, "fit_date": date.today().isoformat(),
           "curve": got["curve"]}
    if write:
        from src.utils.history import write_kept

        write_kept(get_path("models", market) / FILE, json.dumps(out, indent=1))
    return out


def load_threshold(market: str) -> float | None:
    from src.utils.paths import get_path

    path = get_path("models", market) / FILE
    if not path.exists():
        return None
    try:
        t = json.loads(path.read_text())["threshold_pp"]
    except Exception:                                            # noqa: BLE001
        return None
    return None if t is None else float(t)


def qualifying(season: int, market: str, rows: list[dict],
               threshold_pp: float | None = None) -> list[dict]:
    """The bets this rule takes from `week_history.ou_week` rows.

    Rows are re-settled first (`prop_settlement.settle_rows`), collapsed to one
    line per player-game, and `ours` is read as the blended P(over). Each
    returned row carries `side`, `edge_pp` and the side's own `price`; `won`
    is graded on the rule's side, null for a void or an unsettled game.
    """
    from src.evaluation.prop_settlement import _norm, settle_rows

    t = load_threshold(market) if threshold_pp is None else threshold_pp
    if t is None or not rows:
        return []
    s = settle_rows(season, market, rows)
    keep = [r for r in s if r.get("ours") is not None and r.get("book") is not None
            and r.get("line") is not None]
    if not keep:
        return []
    names = _norm([r.get("player_name") or "" for r in keep])
    d = pl.DataFrame([{
        "game_id": r.get("game_id"), "player_name": r.get("player_name"),
        "player_name_norm": n, "player_key": n, "season": season, "week": 0,
        "point": float(r["line"]), "p_blend": float(r["ours"]),
        "fair_prob": float(r["book"]), "actual": r.get("actual"),
        "void": bool(r.get("void")),
    } for r, n in zip(keep, names)], infer_schema_length=None)
    d = main_lines(d)
    d = attach_prices(d, season, market)
    b = select(d, t)
    out = []
    for r in b.iter_rows(named=True):
        won = None
        if not r["void"] and r["actual"] is not None and float(r["actual"]) != r["point"]:
            won = (float(r["actual"]) > r["point"]) == (r["side"] == "over")
        out.append({**r, "won": won, "threshold_pp": t})
    return out
