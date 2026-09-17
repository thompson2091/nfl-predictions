#!/usr/bin/env python3
"""Train and honestly grade the three yardage models.

The fourth, fifth and sixth markets, and the first that are not counts. One
script for all three because they differ in their label column and nothing
else that matters — the candidate pool, the feature matrix, the grading and
the blend are identical, and three copies of this file would have drifted the
first time one of them was fixed.

    python scripts/49_yards.py                       # all three, train + grade
    python scripts/49_yards.py --market passing_yards
    python scripts/49_yards.py --skip-train          # re-grade what is on disk

What this script deliberately is NOT is a claim of betting edge. The receptions
model does not beat its market on its own and neither, most likely, will these:
a 7% hold is what a well-priced market looks like, and the first version of the
receptions model that DID beat it by +17-22% ROI was how the NGS existence leak
was found. The summary this writes states both the raw and the blended
comparison in numbers so no screen has to infer which claim is being made.

See src/models/yards.py for why these predict a quantile function rather than a
mean plus a distribution, which is the one real modelling difference from
scripts/30_receptions.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

sys.path.insert(0, ".")

import numpy as np
import polars as pl

from src.models.count import blend_to_market, design_matrix, fit_market_blend
from src.models.yards import XGBQuantileModel, interval, prob_over, quantile_at
from src.utils.config import get_config
from src.utils.paths import get_path

#: The four label columns and the identifiers, none of which are features.
#:
#: All four labels are excluded from every market's feature list, not just the
#: one being fitted. Leaving `receiving_yards` in the matrix while predicting
#: `rushing_yards` would hand the model the same game's box score, which is the
#: plainest leak there is and would not raise anything.
ID_COLS = {"game_id", "season", "week", "home_team", "away_team", "game_type",
           "player_id", "player_name", "team", "target",
           "receptions", "receiving_yards", "rushing_yards", "passing_yards"}

#: Per-market training pool, and the *only* place a filter is allowed to touch
#: the population.
#:
#: `gate` is a column of the feature matrix, so it is known before kickoff.
#: Gating on the outcome instead — "rows where he actually threw a pass" — is
#: the selection leak that produced the receptions rookie at 8.52: the model
#: gets fitted on a population it cannot identify on a Tuesday.
#:
#: Only passing yards is gated. 96% of played player-games record zero passing
#: yards, and a quantile model spending its capacity learning that wide
#: receivers do not throw is not wrong, only wasteful — `position_QB` comes off
#: a roster and costs nothing. Rushing and receiving are left ungated because
#: their zero mass is real signal about real candidates: a tight end who might
#: catch nothing is exactly the row the 15th percentile is for, and books do
#: price the occasional wide-receiver carry.
MARKETS: dict[str, dict] = {
    "rushing_yards": {"gate": None},
    "receiving_yards": {"gate": None},
    "passing_yards": {"gate": "position_QB"},
}


def _frame(market: str) -> tuple[pl.DataFrame, list[str]]:
    """The shared feature matrix, labelled with one yardage column.

    REUSED from anytime_td rather than rebuilt, for the reason given in
    scripts/30_receptions.py: who is on a roster this week and how he has been
    used are the same questions whatever is being predicted, and a second copy
    of an 80MB matrix would only drift from the first.
    """
    feats = pl.read_parquet(get_path("processed", "anytime_td") / "features.parquet")
    ws = (pl.scan_parquet(get_path("raw") / "weekly_stats.parquet")
          .select(["season", "week", "player_id", market]).collect())
    df = feats.join(ws, on=["season", "week", "player_id"], how="left")
    # A row with no weekly stat is a player who did not play, and the label is
    # unknowable rather than zero. nflverse writes 0 rather than null for a
    # player who played and did none of it, so this filter means "played" and
    # keeps every honest zero.
    df = df.filter(pl.col(market).is_not_null())
    gate = MARKETS[market]["gate"]
    if gate:
        if gate not in df.columns:
            raise KeyError(f"training gate {gate!r} is not a column of the "
                           f"feature matrix; refusing to fit {market} on an "
                           f"ungated pool by accident")
        df = df.filter(pl.col(gate) == 1)
    fcols = [c for c in df.columns if c not in ID_COLS and df[c].dtype.is_numeric()]
    return df, fcols


def train(df: pl.DataFrame, fcols: list[str], market: str) -> XGBQuantileModel:
    cfg = get_config()
    tr = df.filter(pl.col("season") <= cfg["splits"]["train_end"])
    va = df.filter(pl.col("season") == cfg["splits"]["val_season"])

    def XY(d):
        return design_matrix(d, fcols), d[market].to_numpy().astype(float)

    Xtr, ytr = XY(tr)
    Xva, yva = XY(va)
    m = XGBQuantileModel()
    m.feature_names = fcols
    m.market = market
    m.fit(Xtr, ytr, Xva, yva,
          get_config().get("model", {}).get("xgb_quantile", {})
          | {"seed": get_config()["model"]["seed"]})
    q = m.predict_quantiles(Xva)
    lo, hi = interval(q)
    inside = float(np.mean((yva >= lo) & (yva <= hi)))
    print(f"  trained on {tr.height:,} rows (<= {cfg['splits']['train_end']}), "
          f"validated on {va.height:,} ({cfg['splits']['val_season']})")
    print(f"  median {quantile_at(q, 0.5).mean():7.2f} vs actual mean "
          f"{yva.mean():7.2f};  15-85 interval covers {inside:.1%} "
          f"(nominal 70.0%)")
    return m


def graded_lines(season: int, market: str) -> pl.DataFrame | None:
    """Archived closing lines joined to what the player actually gained."""
    from src.ingest.odds_history import (HISTORY_PATH, SCHEMA, _conform,
                                         _resolve_player_id, drop_in_play)

    if not HISTORY_PATH.exists():
        return None
    h = _conform(pl.read_parquet(HISTORY_PATH), SCHEMA).filter(
        (pl.col("market") == market) & (pl.col("snapshot") == "close")
        & (pl.col("season") == season) & pl.col("point").is_not_null())
    if h.height == 0:
        return None
    # Prices archived under `close` that were taken after kickoff. Every dedupe
    # in this project keeps the newest capture, so without this the fourth
    # quarter wins. See odds_history.drop_in_play.
    h = drop_in_play(h)
    if h.height == 0:
        return None
    h = h.with_columns(_resolve_player_id(h)).filter(pl.col("player_id").is_not_null())
    ws = (pl.scan_parquet(get_path("raw") / "weekly_stats.parquet")
          .select(["season", "week", "player_id", market]).collect())
    # fair_prob is null where only one side was posted. A market comparison
    # over rows the market has no de-vigged number for would be NaN.
    return h.join(ws, on=["season", "week", "player_id"], how="inner").filter(
        pl.col(market).is_not_null() & pl.col("fair_prob").is_not_null())


def _priced(m: XGBQuantileModel, df: pl.DataFrame, fcols: list[str],
            season: int, market: str) -> pl.DataFrame | None:
    """Every archived line for a season, priced by the model. One join, reused."""
    lines = graded_lines(season, market)
    if lines is None or lines.height == 0:
        return None
    te = df.filter(pl.col("season") == season)
    if te.height == 0:
        return None
    q = m.predict_quantiles(design_matrix(te, fcols))
    te = te.select(["season", "week", "player_id", "game_id"]).with_columns(
        [pl.Series(f"q{i}", q[:, i]) for i in range(q.shape[1])])
    j = lines.join(te, on=["season", "week", "player_id"], how="inner")
    if j.height == 0:
        return None
    qq = np.stack([j[f"q{i}"].to_numpy() for i in range(q.shape[1])], axis=1)
    over, push = prob_over(qq, j["point"].to_numpy(), m.levels)
    # A push belongs to neither side, so it comes out before our number is set
    # beside the book's — a book's Over 40.0 price is a claim about the two
    # outcomes that resolve, not all three.
    p_model = np.clip(over / np.clip(1.0 - push, 1e-9, None), 0.0, 1.0)
    return j.with_columns([pl.Series("p_model", p_model),
                           pl.Series("push_mass", push)])


def _ll(p, y):
    q = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))


def _ll_rows(p, y):
    q = np.clip(p, 1e-9, 1 - 1e-9)
    return -(y * np.log(q) + (1 - y) * np.log(1 - q))


def compare(p_model, p_book, y, games, n_boot: int = 4000, seed: int = 0) -> dict:
    """Is our number better than the book's, or does it only look that way?

    Three questions, because a raw log-loss comparison answered none of them
    and the first run of this script reported `beats_market: True` on all of
    them being wrong at once.

    **Resampled by game, not by row.** A book posts five passing lines on one
    quarterback and every one of them settles on the same afternoon against the
    same defence. Treating those as five independent observations is what turns
    53 fixtures into an n of 1,352 and a coin flip into a finding. That first
    run measured a +0.0036 gain whose 95% interval over games was
    [-0.0329, +0.0381], with P(gain > 0) = 0.581.

    **Concentration**, because a mean gain can be one afternoon. In that same
    run the top five of 53 fixtures accounted for 640% of the total gain — the
    rest of the board gave most of it back — and we were ahead in 49% of
    fixtures, which is the number a fair coin produces.

    **Book depth at the line.** This is the one specific to yardage markets.
    Books agree on a receptions line and scatter on a yardage one, so the
    median behind `fair_prob` is a median of one or two quotes rather than
    four, and a single book's de-vig is a NOISY estimate of the market rather
    than the market. Split by depth, that first run beat the book by +0.0057 on
    1-book lines and LOST on both 2-book (-0.0128) and 3+-book (-0.0026) ones.
    Beating a noisy reading of a price is not beating the price.
    """
    y = np.asarray(y, dtype=float)
    lm, lk = _ll_rows(np.asarray(p_model), y), _ll_rows(np.asarray(p_book), y)
    games = np.asarray(games)
    uniq = np.unique(games)
    idx = {u: np.where(games == u)[0] for u in uniq}

    rng = np.random.default_rng(seed)
    gains = np.empty(n_boot)
    for b in range(n_boot):
        ii = np.concatenate([idx[u] for u in rng.choice(uniq, len(uniq), replace=True)])
        gains[b] = lk[ii].mean() - lm[ii].mean()

    per = np.array([lk[idx[u]].sum() - lm[idx[u]].sum() for u in uniq])
    total = per.sum()
    top5 = np.sort(per)[::-1][:5].sum()
    return {
        "gain": float(lk.mean() - lm.mean()),
        "n_rows": int(len(y)), "n_games": int(len(uniq)),
        "ci95": [float(np.percentile(gains, 2.5)), float(np.percentile(gains, 97.5))],
        "p_gain_positive": float(np.mean(gains > 0)),
        "share_in_top5_fixtures": float(top5 / total) if total else None,
        "fixtures_won": float(np.mean(per > 0)),
    }


#: Week bands the early-season bias is reported over. Not a model parameter —
#: see `by_week` for why fitting anything per band was measured and dropped.
WEEK_BANDS = ((1, 2), (3, 5), (6, 12), (13, 25))


def by_week(p_model, p_book, y, weeks) -> list[dict]:
    """Where in the season our number is wrong — against the book's, not alone.

    The `market_bias` column is the point of this function, and reading
    `model_bias` without it is how a season's outcomes get mistaken for a
    defect in the model. Passing yards, weeks 1-2:

        2024   over rate 0.350   we say 0.487 (+0.137)   book says 0.493 (+0.143)
        2025   over rate 0.456   we say 0.527 (+0.070)   book says 0.501 (+0.044)

    Our early-season bias looks alarming on its own and mostly is not ours. In
    2024 the book was further out than we were: a fortnight in which unders
    settled at 65% is a property of 829 rows across about 60 fixtures, not of
    anything either of us believed. In 2025 we are 2.6 points worse than the
    book, which is real and small. Averaged over the two, our excess over the
    book in weeks 1-2 is about a point.

    On the other two markets the early weeks are where we are BETTER: 2025
    weeks 1-2 receiving is +0.002 against the book's +0.035, rushing -0.009
    against +0.073.

    What this table does show is a season-long defect in rushing yards. We say
    0.39-0.46 in every band of both seasons against true rates of 0.43-0.49 —
    persistently short on the over, which is a real calibration error rather
    than a sample. It reaches the board barely at all: that model's fitted
    blend weight is 0.06, so 94% of what is served there is the book.

    TRIED AND REJECTED: a blend weight fitted per week band. Fitted on 2024 it
    chose 1.00 for weeks 1-2 — keep ALL of our number in the band it had just
    been shown we were worst in — because 2024's own weeks 1-2 settled under at
    0.350 and the fit read that as signal. On 2025 it came out 0.0029 WORSE
    than the flat weight, with a 95% interval over games of [-0.0077, +0.0020]
    and P(better) = 0.11. So the flat weight stands and the bands are reported
    rather than corrected — the same answer game script and banded dispersion
    got on receptions.
    """
    y = np.asarray(y, dtype=float)
    w = np.asarray(weeks)
    pm, pk = np.asarray(p_model, dtype=float), np.asarray(p_book, dtype=float)
    out = []
    for lo, hi in WEEK_BANDS:
        m = (w >= lo) & (w <= hi)
        if m.sum() < 50:
            continue
        out.append({"weeks": f"{lo}-{hi}", "n": int(m.sum()),
                    "over_rate": float(y[m].mean()),
                    "model_mean_p": float(pm[m].mean()),
                    "market_mean_p": float(pk[m].mean()),
                    "model_bias": float(pm[m].mean() - y[m].mean()),
                    "market_bias": float(pk[m].mean() - y[m].mean())})
    return out


def by_depth(p_model, p_book, y, n_books) -> list[dict]:
    """The same comparison, split by how many books quoted that exact line."""
    y = np.asarray(y, dtype=float)
    nb = np.asarray(n_books, dtype=float)
    out = []
    for lo, hi, label in ((1, 1, "1 book"), (2, 2, "2 books"), (3, 1e9, "3+ books")):
        m = (nb >= lo) & (nb <= hi)
        if m.sum() < 30:
            continue
        out.append({"depth": label, "n": int(m.sum()),
                    "model": _ll(np.asarray(p_model)[m], y[m]),
                    "market": _ll(np.asarray(p_book)[m], y[m])})
        out[-1]["gain"] = out[-1]["market"] - out[-1]["model"]
    return out


def fit_blend(m, df, fcols, season: int, market: str, model_dir) -> dict | None:
    """Fit how far to shrink our number toward the book's, on one season.

    Fitted on validation and never on test, for the same reason the receptions
    blend is: it is a claim about how much we add to a price, and fitting it
    where the trees have already been is a claim about memorisation.
    """
    j = _priced(m, df, fcols, season, market)
    if j is None:
        return None
    y_raw, line = j[market].to_numpy(), j["point"].to_numpy()
    ok = y_raw != line                       # whole-number pushes drop out
    if ok.sum() < 200:
        print(f"  blend: only {int(ok.sum())} gradeable lines in {season}; "
              f"not fitting one")
        return None
    blend = fit_market_blend(j["p_model"].to_numpy()[ok],
                             j["fair_prob"].to_numpy()[ok],
                             (y_raw > line).astype(float)[ok],
                             kind=f"{market}_market_blend")
    blend["fitted_on"] = season
    path = model_dir / "market_blend.json"
    path.write_text(json.dumps(blend, indent=1))
    print(f"  blend fitted on {season}: keep {blend['weight']:.0%} of our "
          f"number, {1 - blend['weight']:.0%} of the book's "
          f"({blend['n']:,} lines)")
    return blend


def backtest(m, df, fcols, season: int, market: str,
             blend: dict | None = None) -> dict | None:
    j = _priced(m, df, fcols, season, market)
    if j is None:
        print(f"  {season}: no graded lines in the archive")
        return None
    y_raw, line = j[market].to_numpy(), j["point"].to_numpy()
    gradeable = y_raw != line
    y = (y_raw > line).astype(float)[gradeable]
    pm = j["p_model"].to_numpy()[gradeable]
    pk = j["fair_prob"].to_numpy()[gradeable]
    if len(y) == 0:
        return None

    out_dir = get_path("output", market)
    j.filter(pl.Series(gradeable)).with_columns(pl.Series("y_over", y)).select(
        ["season", "week", "game_id", "player_name_raw", "player_id", "point",
         "odds", "implied_prob", "fair_prob", "p_model", market, "y_over"]
    ).write_csv(out_dir / f"backtest_{season}.csv")

    res = {
        "season": season, "n": int(len(y)), "pushes": int((~gradeable).sum()),
        "over_rate": float(y.mean()),
        "model": {"log_loss": _ll(pm, y), "brier": float(np.mean((pm - y) ** 2)),
                  "mean_p": float(pm.mean())},
        "market": {"log_loss": _ll(pk, y), "brier": float(np.mean((pk - y) ** 2)),
                   "mean_p": float(pk.mean())},
    }
    gm = j.filter(pl.Series(gradeable))["game_id"].to_numpy()
    res["vs_market"] = compare(pm, pk, y, gm)
    res["by_depth"] = by_depth(
        pm, pk, y, j.filter(pl.Series(gradeable))["n_books"].fill_null(1).to_numpy())
    res["by_week"] = by_week(
        pm, pk, y, j.filter(pl.Series(gradeable))["week"].to_numpy())
    # "Better" means the interval over GAMES excludes zero, not that the mean
    # landed on the right side of it. See `compare`.
    res["model_beats_market"] = bool(res["vs_market"]["ci95"][0] > 0)

    if blend:
        pbl = blend_to_market(pm, pk, blend["weight"])
        res["blend"] = {"log_loss": _ll(pbl, y),
                        "brier": float(np.mean((pbl - y) ** 2)),
                        "weight": blend["weight"],
                        "fitted_on": blend.get("fitted_on")}
        res["blend"]["vs_market"] = compare(pbl, pk, y, gm)
        res["blend_beats_market"] = bool(res["blend"]["vs_market"]["ci95"][0] > 0)
        # In-sample for the blend where the weight was fitted on this season.
        res["blend"]["in_sample"] = blend.get("fitted_on") == season
    tag = "model better" if res["model_beats_market"] else "not separable"
    line_txt = (f"  {season}: n={len(y):,}  log loss model "
                f"{res['model']['log_loss']:.5f} vs market "
                f"{res['market']['log_loss']:.5f}  ({tag})")
    if blend:
        line_txt += (f"  blend {res['blend']['log_loss']:.5f}"
                     + ("  (in sample)" if res["blend"]["in_sample"] else ""))
    print(line_txt)
    v = res["vs_market"]
    print(f"      over {v['n_games']} fixtures: gain {v['gain']:+.5f} "
          f"CI [{v['ci95'][0]:+.5f}, {v['ci95'][1]:+.5f}] "
          f"P(gain>0)={v['p_gain_positive']:.3f}; ahead in "
          f"{v['fixtures_won']:.0%} of fixtures")
    for d in res["by_depth"]:
        print(f"      {d['depth']:9s} n={d['n']:5d}  model {d['model']:.5f}  "
              f"market {d['market']:.5f}  gain {d['gain']:+.5f}")
    for d in res["by_week"]:
        flag = "  <-- serving here" if d["weeks"] == "1-2" else ""
        print(f"      wk {d['weeks']:5s} n={d['n']:5d}  over rate {d['over_rate']:.3f}  "
              f"we say {d['model_mean_p']:.3f} (bias {d['model_bias']:+.3f})  "
              f"book says {d['market_mean_p']:.3f} ({d['market_bias']:+.3f}){flag}")
    return res


def run(market: str, skip_train: bool) -> dict:
    cfg = get_config()
    print(f"\n=== {market} ===")
    df, fcols = _frame(market)
    print(f"  frame: {df.height:,} labelled rows, {len(fcols)} features"
          + (f", gated on {MARKETS[market]['gate']}" if MARKETS[market]["gate"] else ""))

    model_dir = get_path("models", market)
    model_path = model_dir / "xgb_quantile.pkl"
    if skip_train and model_path.exists():
        m = XGBQuantileModel.load(model_path)
        print(f"  loaded {model_path}")
    else:
        m = train(df, fcols, market)
        m.save(model_path)
        print(f"  saved -> {model_path}")

    blend = fit_blend(m, df, fcols, cfg["splits"]["val_season"], market, model_dir)
    results = [r for r in
               (backtest(m, df, fcols, s, market, blend)
                for s in (cfg["splits"]["val_season"], cfg["splits"]["test_season"]))
               if r]

    summary = {
        "kind": "yards_summary", "market": market,
        "fit_date": date.today().isoformat(),
        "n_features": len(fcols), "levels": list(m.levels),
        "gate": MARKETS[market]["gate"],
        "splits": {k: cfg["splits"][k]
                   for k in ("train_end", "val_season", "test_season")},
        "seasons": results,
        # Stated rather than left to be inferred. See the module docstring.
        "beats_market": bool(results) and all(
            r["model_beats_market"] for r in results),
        "blend": blend,
        "blend_beats_market": bool(results) and all(
            r.get("blend_beats_market") for r in results),
    }
    path = get_path("output", market) / "summary.json"
    path.write_text(json.dumps(summary, indent=1))
    print(f"  summary -> {path}")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=sorted(MARKETS), action="append",
                    help="Repeatable. Default: all three.")
    ap.add_argument("--skip-train", action="store_true")
    args = ap.parse_args()

    out = [run(mk, args.skip_train) for mk in (args.market or sorted(MARKETS))]
    print("\n" + "=" * 62)
    for s in out:
        print(f"  {s['market']:16s} beats_market {str(s['beats_market']):5s}  "
              f"blend_beats_market {str(s['blend_beats_market']):5s}  "
              f"weight {(s['blend'] or {}).get('weight', float('nan')):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
