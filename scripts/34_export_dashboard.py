#!/usr/bin/env python3
"""One interactive HTML dashboard, on the model each market currently serves.

    python scripts/34_export_dashboard.py                 # -> site/dashboard.html
    python scripts/34_export_dashboard.py --open
    python scripts/34_export_dashboard.py --season 2026 --week 1
    python scripts/34_export_dashboard.py --json          # payload only, no HTML

Distinct from `20_export_html.py`, which freezes the Streamlit app by running
it. This one assembles its numbers directly from the same `src/` functions the
app calls, so it can show things the app has no widget for: every rank from
Top-1 to Top-10 rather than 1/3/5, a master table that carries unpriced players
alongside priced ones, combinations built over that same wider pool, and a
by-team table covering the whole slate.

**Which model.** `models/registry/CURRENT.json` names the promoted version per
market and the version's own config resolves the model, so the page can never
disagree with what the app serves. Nothing here picks a "best" of its own.

**Which week.** The newest season and week present in the feature matrix,
unless `--season`/`--week` say otherwise.

The output is one file with no external requests: every number is embedded as
JSON and the filtering, the combination search and the threshold controls all
run in the page.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, ".")

from src.models.registry import ensure_registered
from src.utils.config import config_overlay, get_config, production_model
from src.utils.paths import get_path

#: The two scorer markets. Receptions is deliberately out: it is a count market
#: with one model, no version registry, no blend, no joint model and no team
#: outlook, so every section below would be blank or would mean something else.
MARKETS = [("anytime_td", "Anytime TD"), ("first_td", "First TD")]

#: Where the Top-K table stops. The app reports 1/3/5 because those are the
#: figures the walk-forward artifact records; this recomputes from backtest
#: frames, so the whole ladder is available for the same cost.
KS = tuple(range(1, 11))

#: Threshold grid for "how often is this pick right". One point per percentage
#: point up to 0.70 — past that the backtest holds too few games to measure at
#: any market, and `rate_at` says so rather than guessing.
CUT_GRID = [round(x / 100, 2) for x in range(0, 71)]

#: Bootstrap draws for the threshold grid's intervals. The library default is
#: 2000; at 71 cuts x 4 series x 2 markets that is a minute of resampling for
#: intervals that move in the third decimal. 600 keeps the width honest.
DRAWS = 600


# ── Which model, which week ───────────────────────────────────────────────

def served(target_type: str) -> dict:
    """The promoted version for a market, and the model its config resolves to.

    Reads the registry rather than choosing: `CURRENT.json` is what the app
    serves and what `make promote` writes, so a dashboard that picked its own
    winner would be the only surface in the project showing those numbers.
    """
    from src.models.versioning import current_version, load_manifest, scoring_config

    try:
        cur = current_version(target_type) or {}
    except Exception:                                        # noqa: BLE001
        cur = {}
    version_id = cur.get("id")
    with config_overlay(scoring_config(version_id) if version_id else {}):
        model = production_model(target_type)

    manifest = {}
    if version_id:
        try:
            manifest = load_manifest(version_id)
        except Exception:                                    # noqa: BLE001
            manifest = {}
    metrics = ((manifest.get("metrics") or {}).get(target_type) or {}).get(model)
    features = (manifest.get("features") or {}).get(target_type) or {}
    return {
        "version": version_id,
        "model": model,
        "note": manifest.get("note"),
        "created": manifest.get("created"),
        "verdict": manifest.get("verdict"),
        "git": (manifest.get("git") or {}).get("commit"),
        "n_features": features.get("n_columns") or features.get("n_features"),
        "n_families": features.get("n_families"),
        "recorded": metrics,
        "problems": cur.get("problems") or [],
        "dirty": bool(cur.get("dirty")),
    }


def latest_slate(target_type: str) -> tuple[int | None, int | None]:
    """The newest season and week the feature matrix carries."""
    from src.evaluation import harness
    try:
        df = harness._features(target_type)
    except FileNotFoundError:
        return None, None
    season = int(df.select(pl.col("season").max()).item())
    week = int(df.filter(pl.col("season") == season)
                 .select(pl.col("week").min()).item())
    return season, week


# ── Accuracy, measured ────────────────────────────────────────────────────

def _backtests(target_type: str, model: str | None):
    """Backtest frames for the selected model, or production's, and which."""
    from src.evaluation.hit_rates import _load_backtests
    df = _load_backtests(target_type, model)
    if df is not None:
        return df, None
    prod = production_model(target_type)
    df = _load_backtests(target_type)
    return df, (prod if df is not None and prod != model else None)


def topk_ladder(df, ks=KS) -> dict | None:
    """Top-K for our published number, our pre-blend number, and the book's.

    Three series on identical rows and the same games, because the whole point
    of the comparison is that a price is the only honest baseline — and because
    the blend is the one thing between the two of ours, so showing them apart
    says what blending buys at each depth.
    """
    if df is None or "market_prob" not in df.columns:
        return None
    from src.evaluation.hit_rates import _label_col, _prob_col
    pub, lab = _prob_col(df), _label_col(df)
    d = df.filter(pl.col("market_prob").is_not_null())
    if d.height == 0:
        return None
    pre = "prob_calibrated" if "prob_calibrated" in d.columns else None

    def topk(col: str, k: int) -> float:
        t = (d.sort(col, descending=True).group_by("game_id").head(k)
             .group_by("game_id").agg(pl.col(lab).max().alias("any")))
        return float(t["any"].mean())

    rows = []
    for k in ks:
        row = {"k": k, "ours": topk(pub, k), "book": topk("market_prob", k)}
        if pre:
            row["model_only"] = topk(pre, k)
        rows.append(row)
    # Whether the blend moves anything at all. First TD publishes the model's
    # own number, so its two series are the same column and a chart with two
    # identical lines invites a reading of a distinction that is not there.
    blended = bool(pre and float((d[pub] - d[pre]).abs().max() or 0) > 1e-9)
    return {"games": d["game_id"].n_unique(), "rows": d.height,
            "blended": blended, "k": rows}


def _rate_frame(df, prob_col: str, label_col: str, top_only: bool):
    """One row per game (best pick) or per candidate, ranked by `prob_col`."""
    d = df.filter(pl.col(prob_col).is_not_null())
    if top_only:
        d = d.sort(prob_col, descending=True).group_by("game_id").first()
    return d.select([pl.col("game_id"),
                     pl.col(prob_col).alias("prob"),
                     pl.col(label_col).cast(pl.Float64).alias("hit")])


def hit_curve(frame, grid=CUT_GRID) -> list[dict]:
    """Measured rate at every threshold, with a game-clustered interval.

    Reports rather than filters, the same way the app's slider does: raising
    the bar makes picks better and rarer at once, and only both numbers
    together describe the trade.
    """
    from src.evaluation.hit_rates import MIN_GAMES, _clustered_rate
    out = []
    total = frame.height
    for t in grid:
        sel = frame.filter(pl.col("prob") >= t)
        if sel.height < MIN_GAMES:
            out.append({"t": t, "n": sel.height, "share": sel.height / total,
                        "rate": None, "lo": None, "hi": None, "few": True})
            continue
        rate, lo, hi = _clustered_rate(sel["hit"].to_numpy(),
                                       sel["game_id"].to_numpy(), draws=DRAWS)
        out.append({"t": t, "n": sel.height, "share": sel.height / total,
                    "rate": rate, "lo": lo, "hi": hi, "few": False})
    return out


def selectivity(df) -> dict | None:
    """The four curves: our top pick and any player, and the book's own two.

    The book's are here because "if I only act above X%" is a question anyone
    can ask of a price as easily as of a model, and without the answer the
    model's curve has no scale.
    """
    if df is None:
        return None
    from src.evaluation.hit_rates import _label_col, _prob_col
    pub, lab = _prob_col(df), _label_col(df)
    out = {"base_rate": float(df[lab].mean()),
           "games": df["game_id"].n_unique()}
    series = {"ours_top": (pub, True), "ours_any": (pub, False)}
    if "market_prob" in df.columns and df["market_prob"].null_count() < df.height:
        series["book_top"] = ("market_prob", True)
        series["book_any"] = ("market_prob", False)
    for name, (col, top) in series.items():
        fr = _rate_frame(df, col, lab, top)
        out[name] = {"n": fr.height, "overall": float(fr["hit"].mean()),
                     "curve": hit_curve(fr)}
    return out


def rank_rates(target_type: str, model: str, df) -> dict:
    """What happened to the Nth-ranked player in a game, across the backtests.

    The app fits this on the held-out season alone by re-scoring the feature
    matrix. Reading it off the same backtest frames every other number here
    uses is both cheaper and a larger sample, and it keeps "Typical at #"
    measured on the identical population as the Top-K ladder above it.
    """
    if df is None:
        return {}
    from src.evaluation.hit_rates import _label_col, _prob_col
    pub, lab = _prob_col(df), _label_col(df)
    d = df.with_columns(
        pl.col(pub).rank(descending=True, method="ordinal")
        .over("game_id").alias("rk"))
    agg = (d.group_by("rk")
           .agg([pl.col(lab).mean().alias("hit"), pl.len().alias("n")])
           .filter(pl.col("n") >= 30).sort("rk"))
    return {int(r): float(h) for r, h in zip(agg["rk"], agg["hit"])}


def head_to_head(target_type: str, model: str, version: str | None) -> dict | None:
    """`vs bookmaker`, `Closer — backable` and `Closer — fade`.

    The same call the app's tiles make — see `src/evaluation/market_parity.py`
    for why it is not computed here.
    """
    from src.evaluation import harness
    from src.evaluation.market_parity import compare
    from src.models.versioning import market_dir
    try:
        md = market_dir(target_type, version) if version else None
        return compare(target_type, model, harness._features(target_type),
                       model_dir=md or get_path("models", target_type))
    except Exception as e:                                   # noqa: BLE001
        print(f"    head-to-head unavailable: {e}", file=sys.stderr)
        return None


# ── This week ─────────────────────────────────────────────────────────────

def _american(o) -> str | None:
    try:
        return f"{int(o):+d}"
    except (TypeError, ValueError):
        return None


def _f(x):
    """A float that survives JSON: NaN and inf are not valid JSON literals."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(v) else round(v, 6)


def players(season: int, week: int, target_type: str, model: str,
            rates: dict, rule: dict | None, cuts: tuple[float, float]) -> dict:
    """Every player the model rates this week — priced and unpriced in one list.

    The app keeps these in two tables and says why: an unpriced row's estimate
    is **unblended**, because there is no price to blend toward, and the board's
    `#`, "Typical at #" and every hit-rate figure are measured on the priced
    population. Both facts survive the merge here rather than being dropped:

      * `priced` marks the row, and the page filters and labels on it.
      * `rank` ranks within the game over everyone shown, which is what a
        master table's `#` is read as. `priced_rank` is the board's own ladder,
        blank for unpriced rows, and it is the one "Typical at #" is keyed on —
        so the historical column never quotes a rate for a population it was
        not measured over.
    """
    from src.evaluation.line_shopping import best_vs_consensus
    from src.prediction.availability import status_for
    from src.prediction.bets import board_for_week
    from src.prediction.predict import predict
    from src.presentation import board as bp

    board, msg = board_for_week(season, week, target_type, model,
                                persist=False)
    problems = []
    if board is None or board.height == 0:
        board = pl.DataFrame()
        if msg:
            problems.append(msg)

    # Unpriced = everything the model rated, minus what the board matched to a
    # price. Deliberately not `bets.unpriced_for_week`, which filters on
    # `has_market_price` — a column `blend` writes, and first TD never blends,
    # so on that market it returns nothing and the whole rest of the slate
    # disappears. Subtracting the board is one path that answers for both
    # markets, and it is the same population either way: `board_for_week`
    # inner-joins predictions to the market, so what it did not keep is exactly
    # what no book has quoted.
    unpriced = pl.DataFrame()
    try:
        rated = predict(season, week, model_name=model,
                        target_type=target_type, persist=False)
        if rated is not None and rated.height:
            unpriced = (rated.join(board.select(["game_id", "player_name"]),
                                   on=["game_id", "player_name"], how="anti")
                        if board.height else rated)
    except Exception as e:                                   # noqa: BLE001
        problems.append(f"Unpriced players: {e}")

    shop = None
    try:
        d = best_vs_consensus(season, week, target_type)
        shop = d.to_pandas() if d is not None and d.height else None
    except Exception as e:                                   # noqa: BLE001
        problems.append(f"Best available price: {e}")
    inj = None
    try:
        d = status_for(season, week)
        inj = d.to_pandas() if d is not None and d.height else None
    except Exception as e:                                   # noqa: BLE001
        problems.append(f"Injury report: {e}")

    b = board.to_pandas() if board.height else None
    if b is not None:
        if shop is not None and "player_name_norm" in b.columns:
            b = b.merge(shop[["player_name_norm", "best_odds", "best_book"]],
                        on="player_name_norm", how="left")
        if inj is not None and "player_id" in b.columns and "player_id" in inj.columns:
            b = b.merge(inj[["player_id", "report_status", "is_blocked"]],
                        on="player_id", how="left")
        b["priced_rank"] = (b.groupby("game_label")["probability"]
                            .rank(ascending=False, method="first").astype(int))
        b["bet_rank"] = (b.groupby("game_label")[
            "prob_model" if "prob_model" in b.columns else "probability"]
            .rank(ascending=False, method="first").astype(int))
        tiers = bp.highlight_tier(b, rule) if rule else None
        if isinstance(tiers, str):
            tiers = None

    lo, hi = cuts
    rows = []
    if b is not None:
        tier_list = list(tiers) if tiers is not None else None
        for i, (_, r) in enumerate(b.iterrows()):
            # Falls back to the published number rather than blanking. First TD
            # is not blended, so its model-only view *is* the column beside it
            # and a blank would read as "not computed". `topk.blended` is what
            # tells the page to drop the column instead of printing it twice.
            model_only = _f(r.get("prob_model"))
            if model_only is None:
                model_only = _f(r.get("probability"))
            rows.append({
                "player": r["player_name"], "team": r.get("team"),
                "game": r.get("game_label"), "game_id": r.get("game_id"),
                "priced": True,
                "odds": _american(r.get("odds")),
                "odds_num": _f(r.get("odds")),
                "dec": _f(r.get("decimal_odds")),
                "best": _american(r.get("best_odds")),
                "best_book": (r.get("best_book")
                              if isinstance(r.get("best_book"), str) else None),
                "priced_rank": int(r["priced_rank"]),
                "at_rank": _f(rates.get(int(r["priced_rank"]))),
                "ours": _f(r.get("probability")),
                "model_only": model_only,
                "book": _f(r.get("market_prob")),
                "diff": _f(r.get("edge_pp")),
                "read": bp.confidence(float(r.get("edge_pp") or 0), lo, hi),
                "bet_rank": int(r["bet_rank"]),
                "bet_edge": _f(r.get("model_edge_pp")),
                "ev": _f(r.get("ev_model_pct")),
                "backing": (tier_list[i] if tier_list is not None else None),
                "status": (r.get("report_status")
                           if isinstance(r.get("report_status"), str) else None),
                "blocked": bool(r.get("is_blocked")) if "is_blocked" in b.columns else False,
            })

    if unpriced is not None and getattr(unpriced, "height", 0):
        for r in unpriced.to_pandas().itertuples():
            rows.append({
                "player": r.player_name, "team": getattr(r, "team", None),
                "game": getattr(r, "game_label", None),
                "game_id": getattr(r, "game_id", None),
                "priced": False,
                "odds": None, "odds_num": None, "dec": None,
                "best": None, "best_book": None,
                "priced_rank": None, "at_rank": None,
                "ours": _f(r.probability),
                "model_only": _f(getattr(r, "prob_model", r.probability)),
                "book": None, "diff": None, "read": None,
                "bet_rank": None, "bet_edge": None, "ev": None,
                "backing": None, "status": None, "blocked": False,
            })

    # One ladder over everyone in the game, assigned after the merge so the
    # master table's `#` means what it says. Deterministic on ties: two players
    # can share a probability to the last decimal and an unstable sort would
    # renumber them on every rebuild.
    rows.sort(key=lambda r: (r["game"] or "", -(r["ours"] or 0), r["player"]))
    n = 0
    prev = object()
    for r in rows:
        n = 1 if r["game"] != prev else n + 1
        prev = r["game"]
        r["rank"] = n
    rows.sort(key=lambda r: -(r["ours"] or 0))
    return {"rows": rows, "problems": problems}


def teams(season: int, week: int, target_type: str) -> dict:
    """The by-team table for the whole slate, with the two likeliest scorers.

    Every game, not only the priced ones: the board's game list is whatever a
    book has posted, which early in a week is a handful of them, and the team
    numbers exist for all of them.

    Both markets are scored regardless of which one is being built, because the
    columns need them: `first_td_pct` is a first-TD quantity and
    `expected_scorers` is an anytime one, and a team row shows both. **The
    named scorers, though, come from `target_type` alone.** They used to come
    from anytime TD on both pages, so the First TD table named the player most
    likely to score at *some* point in the game beside a column about who
    scores *first* — two different questions, one of them answered wrongly.
    """
    from src.models.joint import _game_lines, load_team_rate, team_rate
    from src.prediction.predict import predict
    from src.presentation import team_outlook as T
    from src.evaluation import harness

    preds, problems = {}, []
    for tt in ("first_td", "anytime_td"):
        try:
            preds[tt] = predict(season, week, model_name=production_model(tt),
                                target_type=tt, persist=False)
        except Exception as e:                               # noqa: BLE001
            preds[tt] = None
            problems.append(f"{tt} predictions: {e}")

    lam = None
    try:
        m = load_team_rate(get_path("models", "anytime_td") / "team_td_rate.json")
        feats = harness._features("anytime_td")
        wk = feats.filter((pl.col("season") == season) & (pl.col("week") == week))
        if m is not None and wk.height:
            lam = team_rate(m, _game_lines(wk))
    except Exception as e:                                   # noqa: BLE001
        problems.append(f"Team scoring rate: {e}")

    book = None
    try:
        from src.prediction.bets import board_for_week
        fb, _ = board_for_week(season, week, "first_td",
                               production_model("first_td"), persist=False)
        if fb is not None and fb.height and {"game_id", "team", "market_prob"} <= set(fb.columns):
            book = fb.select(["game_id", "team", "market_prob"])
    except Exception:                                        # noqa: BLE001
        book = None

    out = T.build(preds.get("first_td"), preds.get("anytime_td"), lam, book)
    if out.is_empty():
        return {"rows": [], "problems": problems}

    # The two likeliest scorers rather than one. A single name reads as "the
    # bet"; two read as what they are — where the team's touchdowns are
    # concentrated, and how far ahead the first name actually is.
    #
    # From the market being built, not from anytime TD: on first TD these are
    # the two likeliest to open the scoring, and the percentages are that
    # market's own, which are several times smaller. Sharing one set across
    # both pages put an anytime name and an anytime percentage on a first-TD
    # table, where both were answers to a question the page was not asking.
    ap = preds.get(target_type)
    if ap is not None and ap.height:
        top2 = (ap.sort("probability", descending=True)
                .group_by(["game_id", "team"])
                .agg([pl.col("player_name").alias("_names"),
                      pl.col("probability").alias("_probs")])
                .with_columns([
                    pl.col("_names").list.get(0, null_on_oob=True).alias("top1_player"),
                    pl.col("_probs").list.get(0, null_on_oob=True).alias("top1_pct"),
                    pl.col("_names").list.get(1, null_on_oob=True).alias("top2_player"),
                    pl.col("_probs").list.get(1, null_on_oob=True).alias("top2_pct"),
                ]).drop(["_names", "_probs"]))
        out = out.join(top2, on=["game_id", "team"], how="left")

    labels = None
    for p in preds.values():
        if p is not None and "game_label" in p.columns:
            labels = p.select(["game_id", "game_label"]).unique()
            break
    if labels is not None:
        out = out.join(labels, on="game_id", how="left")

    d = out.to_pandas()
    rows = []
    for r in d.itertuples():
        rows.append({
            "game": getattr(r, "game_label", None), "game_id": r.game_id,
            "team": r.team,
            "first_td": _f(getattr(r, "first_td_pct", None)),
            "book_first_td": _f(getattr(r, "book_first_td_pct", None)),
            "expected_tds": _f(getattr(r, "expected_tds", None)),
            "expected_scorers": _f(getattr(r, "expected_scorers", None)),
            "shutout": _f(getattr(r, "shutout_pct", None)),
            "candidates": _f(getattr(r, "candidates", None)),
            "top1_player": getattr(r, "top1_player", None),
            "top1_pct": _f(getattr(r, "top1_pct", None)),
            "top2_player": getattr(r, "top2_player", None),
            "top2_pct": _f(getattr(r, "top2_pct", None)),
        })
    rows.sort(key=lambda r: (r["game"] or "", r["team"] or ""))
    return {"rows": rows, "problems": problems}


# ── One market ────────────────────────────────────────────────────────────

def market(target_type: str, label: str, season: int | None,
           week: int | None) -> dict:
    from src.evaluation.combo_backtest import load as load_combos
    from src.evaluation.longshot import load as load_longshot
    from src.evaluation.rank_economics import load as load_econ
    from src.presentation import board as bp

    cfg = get_config()
    who = served(target_type)
    model = who["model"]
    s, w = latest_slate(target_type)
    season = season if season is not None else s
    week = week if week is not None else w
    print(f"  {target_type}: {model} on {who['version']} — "
          f"{season} week {week}", file=sys.stderr)

    df, fell_back = _backtests(target_type, model)

    econ = load_econ(get_path("output", target_type) / "rank_economics.json")
    rule = None
    if econ and econ.get("edge_rule"):
        seasons = econ.get("seasons") or []
        rule = {**econ["edge_rule"], "tiers": econ.get("highlight_tiers"),
                "games": econ.get("games"),
                "span": f"{seasons[0]}-{seasons[-1]}" if seasons else ""}

    # Where "Leans" and "Strong call" sit, read off the backtested season's own
    # spread rather than chosen — so the label means "unusually far from the
    # market for this model" and moves when the model does.
    bt = get_path("output", target_type) / f"backtest_{cfg['splits']['test_season']}.csv"
    cuts = (0.02, 0.05)
    if bt.exists():
        diffs = pl.read_csv(bt)["edge"].abs().drop_nulls().to_numpy()
        if len(diffs) > 100:
            cuts = (float(np.quantile(diffs, 0.33)), float(np.quantile(diffs, 0.66)))

    rates = rank_rates(target_type, model, df)
    print("    slate ...", file=sys.stderr)
    pl_out = players(season, week, target_type, model, rates, rule, cuts)
    print("    teams ...", file=sys.stderr)
    tm = teams(season, week, target_type)
    print("    accuracy ...", file=sys.stderr)

    legend = bp.tier_legend(rule) if rule else None
    combo_rec = load_combos(get_path("output", target_type) / "combo_backtest.json")

    from src.evaluation.harness import walkforward_rows
    wf_rows, _ = walkforward_rows(target_type)
    folds = [f for f in wf_rows if f.get("model", model) == model]
    wf = None
    if folds:
        total = sum(f["games"] for f in folds)
        wf = {"games": total, "seasons": len(folds),
              "span": f"{min(f['test_season'] for f in folds)}-"
                      f"{max(f['test_season'] for f in folds)}"}
        for k in ("top1", "top3", "top5"):
            p = sum(f[k] * f["games"] for f in folds) / total
            wf[k] = p
            wf[f"{k}_se"] = float(np.sqrt(p * (1 - p) / total))
        if all("median_rank" in f for f in folds):
            wf["median_rank"] = float(np.median([f["median_rank"] for f in folds]))

    return {
        "key": target_type, "label": label, "season": season, "week": week,
        "served": who, "model": model, "measured_on": fell_back,
        "walkforward": wf,
        "topk": topk_ladder(df),
        "h2h": head_to_head(target_type, model, who["version"]),
        "selectivity": selectivity(df),
        "rank_rates": {str(k): v for k, v in rates.items()},
        "rule": rule,
        "tier_legend": (legend.to_dict("records") if legend is not None else None),
        "econ": ({"headline": econ.get("headline"), "games": econ.get("games"),
                  "seasons": econ.get("seasons")} if econ else None),
        "longshot": load_longshot(get_path("output", target_type) / "longshot_skill.json"),
        "combo_record": ({"span": combo_rec.get("span"),
                          "rows": combo_rec.get("rows")} if combo_rec else None),
        "conf_cuts": [cuts[0] * 100, cuts[1] * 100],
        "min_edge": float(cfg.get("betting", {}).get("min_edge_pp", 2.0)),
        "test_season": cfg["splits"]["test_season"],
        "players": pl_out["rows"],
        "problems": pl_out["problems"] + tm["problems"],
        "teams": tm["rows"],
        "cover": cover_variants(pl_out["rows"], target_type),
    }


def cover_variants(rows: list[dict], target_type: str) -> dict:
    """Back every subset of the top N: one table per (N, pool), precomputed.

    Computed here rather than in the page, and the reason is not performance —
    255 slips over 256 patterns is nothing in a browser. It is that the app
    renders the same tables from `src.prediction.cover`, and a second
    implementation in JavaScript would be a second place for the arithmetic to
    drift. This project has spent a day on numbers that described a different
    model than the one they claimed; two copies of a payout formula is the same
    defect waiting to happen. One module, both consumers.

    Every (N, pool) the controls offer is enumerated, so switching a control
    reads a table rather than recomputing one.
    """
    from src.prediction.cover import portfolio
    from src.prediction.portfolio import fit_correlation

    try:
        rho = float((fit_correlation(target_type) or {}).get("teammate_rho") or 0.0)
    except Exception:                                        # noqa: BLE001
        rho = 0.0

    ranked = sorted((r for r in rows if r.get("ours") is not None),
                    key=lambda r: -float(r["ours"]))
    per_game, seen = [], set()
    for r in ranked:
        if r.get("game_id") in seen:
            continue
        seen.add(r.get("game_id"))
        per_game.append(r)

    def legs(src, n):
        return [{"name": r.get("player"), "team": r.get("team"),
                 "prob": float(r["ours"]),
                 "odds": r.get("odds_num") if r.get("priced") else None}
                for r in src[:n]]

    out = {"rho": rho, "variants": {}, "ladder": {}}
    for pool_name, src in (("per_game", per_game), ("all", ranked)):
        for n in range(2, 9):
            if len(src) < n:
                continue
            try:
                out["variants"][f"{pool_name}-{n}"] = portfolio(
                    legs(src, n), stake=1.0, rho=rho, assumed_decimal=2.0)
            except Exception:                                # noqa: BLE001
                continue

    # The scaling table, per pool, at that pool's own average price. Computed
    # here for the same reason the variants are: one implementation of
    # (1 + d)^k - 1, shared with the app.
    from src.prediction.cover import ladder as _ladder
    for pool_name, src in (("per_game", per_game), ("all", ranked)):
        v = out["variants"].get(f"{pool_name}-5") or out["variants"].get(
            f"{pool_name}-2")
        if not v:
            continue
        avg = sum(l["decimal"] for l in v["legs"]) / len(v["legs"])
        probs = [float(r["ours"]) for r in src[:10]]
        try:
            out["ladder"][pool_name] = {
                "decimal": avg, "rows": _ladder(avg, max_n=10, probs=probs)}
        except Exception:                                    # noqa: BLE001
            continue
    return out


def clean(x):
    """Make a payload embeddable in a `<script>` tag.

    NaN and Infinity are not JSON, and `JSON.parse` rejects them — but they
    arrive routinely from pandas and from any artifact with a missing figure.
    Serialising with `allow_nan=True` would produce a file that looks fine in
    Python and is a syntax error in the browser, so the conversion happens
    here, once, over everything, rather than at each of the forty places a
    float is read. Numpy scalars go the same way for the same reason.
    """
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return float(x) if np.isfinite(x) else None
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, np.ndarray):
        return clean(x.tolist())
    return x


def build(season: int | None, week: int | None) -> dict:
    ensure_registered()
    return clean({
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "markets": [market(k, label, season, week) for k, label in MARKETS],
    })


def _gate(force: bool) -> bool:
    """Refuse to publish numbers that describe a different model.

    An export is the one place a mislabelled figure leaves this machine.
    Everything else is read in context by someone who knows what was just run;
    a published page is read by whoever opens it with no way to tell what it
    was built from. On 2026-08-19 six separate artifacts were found describing
    a model other than the one they claimed, so this is a gate rather than a
    warning.
    """
    from src.evaluation.freshness import export_blockers

    blockers = export_blockers()
    if not blockers:
        return True
    print("Refusing to export — these would publish a different model's "
          "numbers:", file=sys.stderr)
    for b in blockers:
        print(f"  {b}", file=sys.stderr)
    if force:
        print("\n--force given; publishing anyway.", file=sys.stderr)
        return True
    print("\nFix them, or pass --force if you know why this snapshot is "
          "wanted anyway.", file=sys.stderr)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="site/dashboard.html")
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--json", action="store_true",
                    help="write the payload as JSON beside --out and stop")
    ap.add_argument("--force", action="store_true",
                    help="publish even when artifacts predate the served model")
    ap.add_argument("--open", dest="open_after", action="store_true")
    ap.add_argument("--verbose", action="store_true",
                    help="let the pipeline's own stdout through — a full board "
                         "and a distribution-shift report per scoring call, and "
                         "this makes six of them")
    args = ap.parse_args()
    if not _gate(getattr(args, "force", False)):
        return 0

    print("building dashboard ...", file=sys.stderr)
    sink = io.StringIO()
    with contextlib.nullcontext() if args.verbose else contextlib.redirect_stdout(sink):
        payload = build(args.season, args.week)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.json:
        p = out.with_suffix(".json")
        p.write_text(json.dumps(payload, indent=1, allow_nan=False))
        print(f"wrote {p} ({p.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)
        return 0

    from src.export.dashboard import render
    out.write_text(render(payload), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)
    if args.open_after:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
