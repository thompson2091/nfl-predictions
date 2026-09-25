#!/usr/bin/env python3
"""Can the receptions model beat the book? One bench, several answers.

The standing measurement is that it cannot: log loss 0.689 against the market's
0.644 on 2025, and 0.7030 against 0.6769 on 2026 week 1. This runs the
candidate improvements against the same graded lines so the comparison is
between variants rather than between write-ups.

    python scripts/48_receptions_lab.py              # every variant
    python scripts/48_receptions_lab.py --only base,script

Variants, in the order they were argued for:

  base    the model as served — the anytime-TD matrix, one global dispersion.
  script  + game context. Receptions are a volume market and volume is decided
          by whether a team is throwing, which is decided by the scoreboard.
          The closing spread and total are in nflverse's own schedule file, so
          this costs nothing and needs no API credit.
  disp    + dispersion as a function of the predicted mean rather than one
          number for the league. A nine-target WR1 and a three-target TE do not
          have the same spread around their mean, and `src/models/count.py`
          already names this as the obvious refinement.
  blend   + the book. The market's own number is the single best feature
          available and the model has never seen it. This fits one weight on
          held-out seasons and shrinks our probability toward the book's,
          which is how a model stops losing to a market: by predicting the
          residual rather than the whole thing.

`blend` is the one that decides whether the rest is worth doing. If moving
toward the book does not close the gap, nothing that improves our own number in
isolation will either — and that result is worth having.

Every variant is fitted on train, has its free parameters set on validation,
and is scored on test. Nothing is chosen on the season it is reported on.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass

sys.path.insert(0, ".")

import numpy as np
import polars as pl

from src.models.count import (XGBCountModel, design_matrix, fair_two_way,
                              fit_dispersion, prob_over)
from src.utils.config import get_config
from src.utils.paths import get_path

ID_COLS = {"game_id", "season", "week", "home_team", "away_team", "game_type",
           "player_id", "player_name", "team", "target", "receptions"}


def log_loss(p: np.ndarray, y: np.ndarray) -> float:
    q = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))


def game_context() -> pl.DataFrame:
    """Per team-game: what the market expected the scoreboard to look like.

    `spread_line` and `total_line` are the closing numbers and are in the
    schedule file already, so this is free and needs no API call. Both are
    knowable before kickoff, which is the only thing that matters for whether
    they can be used.

    The derived columns are the ones with a mechanism behind them rather than
    the raw pair. A team's own implied total says how much offense is expected;
    the opponent's says how much they will have to chase; and the margin says
    which way the game script runs. A trailing team throws, and a team throwing
    is the entire reason a receptions line moves.
    """
    s = pl.read_parquet(get_path("raw") / "schedules.parquet")
    keep = [c for c in ("game_id", "season", "week", "home_team", "away_team",
                        "spread_line", "total_line", "roof") if c in s.columns]
    s = s.select(keep).filter(pl.col("spread_line").is_not_null()
                              & pl.col("total_line").is_not_null())
    # spread_line is from the home team's perspective: positive means the home
    # side is favored by that many.
    home = s.select([
        pl.col("game_id"), pl.col("season"), pl.col("week"),
        pl.col("home_team").alias("team"),
        (pl.col("total_line") / 2 + pl.col("spread_line") / 2).alias("ctx_team_total"),
        (pl.col("total_line") / 2 - pl.col("spread_line") / 2).alias("ctx_opp_total"),
        pl.col("spread_line").alias("ctx_margin"),
        pl.col("total_line").alias("ctx_total"),
        pl.lit(1).alias("ctx_home"),
    ])
    away = s.select([
        pl.col("game_id"), pl.col("season"), pl.col("week"),
        pl.col("away_team").alias("team"),
        (pl.col("total_line") / 2 - pl.col("spread_line") / 2).alias("ctx_team_total"),
        (pl.col("total_line") / 2 + pl.col("spread_line") / 2).alias("ctx_opp_total"),
        (-pl.col("spread_line")).alias("ctx_margin"),
        pl.col("total_line").alias("ctx_total"),
        pl.lit(0).alias("ctx_home"),
    ])
    return pl.concat([home, away], how="vertical").with_columns(
        # Negative margin is the underdog, which is the side expected to throw.
        (-pl.col("ctx_margin")).alias("ctx_deficit"))


def frame(with_context: bool) -> tuple[pl.DataFrame, list[str]]:
    feats = pl.read_parquet(get_path("processed", "anytime_td") / "features.parquet")
    ws = (pl.scan_parquet(get_path("raw") / "weekly_stats.parquet")
          .select(["season", "week", "player_id", "receptions"]).collect())
    df = feats.join(ws, on=["season", "week", "player_id"], how="left")
    df = df.filter(pl.col("receptions").is_not_null())
    if with_context:
        ctx = game_context().drop("game_id")
        df = df.join(ctx, on=["season", "week", "team"], how="left")
    fcols = [c for c in df.columns if c not in ID_COLS and df[c].dtype.is_numeric()]
    return df, fcols


def graded(season: int) -> pl.DataFrame | None:
    """Archived closes for a season, joined to what the player actually caught."""
    from src.ingest.odds_history import (HISTORY_PATH, SCHEMA, _conform,
                                         _resolve_player_id, drop_in_play,
                                         resolve_game_ids)
    if not HISTORY_PATH.exists():
        return None
    h = _conform(pl.read_parquet(HISTORY_PATH), SCHEMA).filter(
        (pl.col("market") == "receptions") & (pl.col("snapshot") == "close")
        & (pl.col("season") == season) & pl.col("point").is_not_null()
        & pl.col("fair_prob").is_not_null())
    if h.height == 0:
        return None
    h = drop_in_play(resolve_game_ids(h))
    h = h.with_columns(_resolve_player_id(h)).filter(pl.col("player_id").is_not_null())
    h = (h.sort("captured_at")
          .unique(subset=["season", "week", "player_id", "point"], keep="last"))
    ws = (pl.scan_parquet(get_path("raw") / "weekly_stats.parquet")
          .select(["season", "week", "player_id", "receptions"]).collect())
    return h.join(ws, on=["season", "week", "player_id"], how="inner").filter(
        pl.col("receptions").is_not_null())


@dataclass
class Scored:
    n: int
    model: float
    market: float
    blend: float | None = None
    weight: float | None = None

    @property
    def beats(self) -> bool:
        best = self.blend if self.blend is not None else self.model
        return best < self.market


def dispersion_by_mu(mu: np.ndarray, y: np.ndarray, bins: int = 5) -> dict:
    """One dispersion per band of predicted mean, instead of one for the league.

    Fitted on validation only, and the bands are quantiles of `mu` so each
    carries the same number of games rather than the same width. Returns the
    edges alongside the values so scoring uses the identical split.
    """
    mu = np.asarray(mu, float)
    edges = np.quantile(mu, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    out = []
    for i in range(bins):
        m = (mu >= edges[i]) & (mu < edges[i + 1])
        # A band with too few games cannot fit anything honest; fall back to
        # the pooled number rather than to a value invented from 30 rows.
        out.append(fit_dispersion(mu[m], y[m])["dispersion"] if m.sum() >= 300
                   else fit_dispersion(mu, y)["dispersion"])
    return {"edges": edges.tolist(), "r": out}


def apply_dispersion(d: dict | float, mu: np.ndarray) -> np.ndarray:
    if not isinstance(d, dict):
        return np.full(len(mu), float(d))
    edges, rs = np.asarray(d["edges"]), np.asarray(d["r"])
    idx = np.clip(np.searchsorted(edges, mu, side="right") - 1, 0, len(rs) - 1)
    return rs[idx]


def fit_blend(p_model: np.ndarray, p_book: np.ndarray, y: np.ndarray) -> float:
    """The weight on our number that minimises log loss against the book's.

    In log-odds space, so the blend cannot leave [0, 1] and a shrink toward the
    book is a straight line rather than a chord across a curve.

    A weight near zero is the honest answer that we add nothing. It is reported
    rather than floored, because "the best mix of us and the market is all
    market" is the result, not a failure to converge.
    """
    def lo(p):
        q = np.clip(p, 1e-6, 1 - 1e-6)
        return np.log(q / (1 - q))
    a, b = lo(p_model), lo(p_book)
    best, bw = None, 0.0
    for w in np.linspace(0, 1, 101):
        p = 1 / (1 + np.exp(-(w * a + (1 - w) * b)))
        ll = log_loss(p, y)
        if best is None or ll < best:
            best, bw = ll, float(w)
    return bw


def blend_at(p_model: np.ndarray, p_book: np.ndarray, w: float) -> np.ndarray:
    def lo(p):
        q = np.clip(p, 1e-6, 1 - 1e-6)
        return np.log(q / (1 - q))
    return 1 / (1 + np.exp(-(w * lo(p_model) + (1 - w) * lo(p_book))))


def run(variant: str, cfg: dict) -> dict:
    ctx = variant in ("script", "disp", "blend")
    df, fcols = frame(with_context=ctx)
    tr = df.filter(pl.col("season") <= cfg["splits"]["train_end"])
    va = df.filter(pl.col("season") == cfg["splits"]["val_season"])

    m = XGBCountModel()
    m.feature_names = fcols
    Xtr, ytr = design_matrix(tr, fcols), tr["receptions"].to_numpy().astype(float)
    Xva, yva = design_matrix(va, fcols), va["receptions"].to_numpy().astype(float)
    m.fit(Xtr, ytr, Xva, yva,
          (cfg.get("model", {}).get("xgb_count", {}) | {"seed": cfg["model"]["seed"]}))

    mu_va = m.predict_mu(Xva)
    disp = (dispersion_by_mu(mu_va, yva) if variant in ("disp", "blend")
            else float(m.dispersion))

    out = {"variant": variant, "n_features": len(fcols), "seasons": {}}
    weight = None
    for season in (cfg["splits"]["val_season"], cfg["splits"]["test_season"]):
        g = graded(season)
        if g is None or g.height == 0:
            continue
        te = df.filter(pl.col("season") == season)
        mu = m.predict_mu(design_matrix(te, fcols))
        te = te.select(["season", "week", "player_id"]).with_columns(pl.Series("mu", mu))
        j = g.join(te, on=["season", "week", "player_id"], how="inner")
        if j.height == 0:
            continue

        r = apply_dispersion(disp, j["mu"].to_numpy())
        over, push = np.zeros(j.height), np.zeros(j.height)
        # prob_over takes one dispersion, so a per-band r is applied by group.
        for rv in np.unique(r):
            sel = r == rv
            o, p = prob_over(j["mu"].to_numpy()[sel], j["point"].to_numpy()[sel], float(rv))
            over[sel], push[sel] = o, p
        p_model = fair_two_way(over, push)

        y_raw, line = j["receptions"].to_numpy(), j["point"].to_numpy()
        ok = y_raw != line                       # whole-number pushes drop out
        y = (y_raw > line).astype(float)[ok]
        pm, pk = p_model[ok], j["fair_prob"].to_numpy()[ok]

        sc = Scored(n=int(ok.sum()), model=log_loss(pm, y), market=log_loss(pk, y))
        if variant == "blend":
            if season == cfg["splits"]["val_season"]:
                weight = fit_blend(pm, pk, y)
            if weight is not None:
                sc.blend = log_loss(blend_at(pm, pk, weight), y)
                sc.weight = weight
        out["seasons"][str(season)] = sc.__dict__ | {"beats": sc.beats}
    return out


VARIANTS = ["base", "script", "disp", "blend"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", default=",".join(VARIANTS))
    args = ap.parse_args()
    cfg = get_config()
    want = [v.strip() for v in args.only.split(",") if v.strip() in VARIANTS]

    results = []
    for v in want:
        print(f"\n=== {v} " + "=" * (56 - len(v)), file=sys.stderr)
        r = run(v, cfg)
        results.append(r)
        for season, s in r["seasons"].items():
            best = s["blend"] if s["blend"] is not None else s["model"]
            tag = "MODEL" if best < s["market"] else "market"
            extra = (f"  blend {s['blend']:.5f} (w={s['weight']:.2f} on us)"
                     if s["blend"] is not None else "")
            print(f"  {season}: n={s['n']:>5,}  model {s['model']:.5f}  "
                  f"market {s['market']:.5f}{extra}  -> {tag} better")

    path = get_path("output", "receptions") / "lab.json"
    path.write_text(json.dumps(results, indent=1))
    print(f"\nWrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
