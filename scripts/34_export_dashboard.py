#!/usr/bin/env python3
"""One interactive HTML dashboard, on the model each market currently serves.

    python scripts/34_export_dashboard.py                 # -> site/dashboard.html
    python scripts/34_export_dashboard.py --open
    python scripts/34_export_dashboard.py --season 2026 --week 1
    python scripts/34_export_dashboard.py --json          # payload only, no HTML

Distinct from `20_export_html.py`, which freezes the Streamlit app by running
it. This one assembles its numbers directly from the same `src/` functions the
app calls, so it can show things the app has no widget for: a master table
that carries unpriced players alongside priced ones, combinations built over
that same wider pool, a reader-chosen full cover, and a by-team table covering
the whole slate.

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

from src.export.dashboard import PAGE_SHOW_STOPS
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

# ── Which model, which week ───────────────────────────────────────────────

#: Where a manifest keeps the commit it was built from, most specific first.
#: `git_state` in src/models/versioning.py writes these; this read used to ask
#: for "commit", which no manifest has ever contained, so the Model tab's
#: commit reference was None from the day it was written. Pinned against the
#: writer by a test, because a key name is exactly the kind of thing two files
#: drift on silently.
GIT_SHA_KEYS = ("short_sha", "sha")


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
        "git": next((g[k] for k in GIT_SHA_KEYS if (g := manifest.get("git") or {}).get(k)), None),
        "n_features": features.get("n_columns") or features.get("n_features"),
        "n_families": features.get("n_families"),
        "recorded": metrics,
        "problems": cur.get("problems") or [],
        "dirty": bool(cur.get("dirty")),
    }


def read_ablation(a: dict | None, wf: dict | None) -> tuple[dict, dict | None]:
    """(families, meta) from an ablation artifact, empty unless it is current.

    Split out to be testable on its own, because the thing worth testing is a
    refusal. `27_ablate.py` retrains without every family, which is roughly one
    walk-forward each, so the artifact outlives the matrix easily — and a stale
    one does not look stale. Its numbers are real, well-formed, and about a
    model nobody is serving. The feature hash is the only thing separating
    those two cases, so a missing hash on either side is a no.
    """
    if not a:
        return {}, None
    mine, theirs = a.get("feature_hash"), (wf or {}).get("feature_hash")
    fresh = bool(mine and theirs and mine == theirs)
    meta = {"measured": a.get("measured"), "model": a.get("model"),
            "fresh": fresh}
    return ((a.get("families") or {}) if fresh else {}), meta


def _recipe(target_type: str, model: str) -> dict | None:
    """What the served model was actually fitted on, and how it scored.

    Both halves come from artifacts rather than from this file. The column list
    is `feature_cols.pkl` in the market's own model directory — the list the
    scorer asks the matrix for, so it is what the model is fitted on by
    definition rather than by description. The family for each column is read
    off `diagnostics/feature_families.json`, which records which builder
    produced it.

    Those two do not have to agree, and where they disagree the columns are
    reported as unattributed rather than dropped. The families map is written
    from one run of the assembler and a market with a wider matrix will carry
    columns it never saw; saying so is the point, because a feature reaching
    the model with no recorded provenance is exactly the thing worth seeing.
    """
    import pickle

    cols_path = get_path("models", target_type) / "feature_cols.pkl"
    if not cols_path.exists():
        return None
    try:
        with open(cols_path, "rb") as fh:
            cols = list(pickle.load(fh))
    except Exception:                                        # noqa: BLE001
        return None

    fam_path = Path(__file__).resolve().parents[1] / "diagnostics" / "feature_families.json"
    owner: dict[str, str] = {}
    if fam_path.exists():
        try:
            fams = json.loads(fam_path.read_text()).get("families") or {}
            for name, members in fams.items():
                for c in members:
                    owner[c] = name
        except Exception:                                    # noqa: BLE001
            owner = {}

    grouped: dict[str, list[str]] = {}
    orphans: list[str] = []
    for c in cols:
        fam = owner.get(c)
        if fam is None:
            orphans.append(c)
        else:
            grouped.setdefault(fam, []).append(c)

    families = sorted(
        ({"name": k, "n": len(v), "cols": sorted(v)} for k, v in grouped.items()),
        key=lambda f: (-f["n"], f["name"]))

    # Per-season accuracy for the model actually served, not for whichever the
    # walk-forward happened to write last.
    wf_path = get_path("output", target_type) / "walkforward.json"
    seasons, wf = [], None
    if wf_path.exists():
        try:
            wf = json.loads(wf_path.read_text())
            rows = [r for r in (wf.get("rows") or []) if r.get("model") == model]
            seasons = [{
                "season": r.get("test_season"), "games": r.get("games"),
                "top1": r.get("top1"), "top3": r.get("top3"),
                "top5": r.get("top5"), "auc": r.get("auc"),
                "brier": r.get("brier"),
            } for r in rows]
        except Exception:                                    # noqa: BLE001
            seasons = []

    # What each family is worth, measured by retraining without it.
    #
    # Not an importance score. `scripts/27_ablate.py` opens by saying why:
    # importance answers "which features does the model lean on", and a family
    # it leans on heavily can still be replaceable, because retrained without
    # it the correlated survivors take over. Only retraining measures that.
    # Deltas are paired per game, because pooled Top-1 carries about 1.5 points
    # and cannot resolve a family worth half of one.
    #
    # Attached only when the ablation was measured on the feature set being
    # served — the hashes have to agree, or the numbers describe a different
    # model and belong nowhere near this page.
    abl_path = (Path(__file__).resolve().parents[1] / "diagnostics"
                / f"ablation_{target_type}.json")
    ablation, abl_meta = {}, None
    if abl_path.exists():
        try:
            ablation, abl_meta = read_ablation(json.loads(abl_path.read_text()), wf)
        except Exception:                                    # noqa: BLE001
            ablation, abl_meta = {}, None

    for f in families:
        hit = ablation.get(f["name"])
        if hit:
            # Reported as what the family is worth, which is the negative of
            # what removing it does. A reader asking which features move the
            # needle is not asking what happens when they are taken away.
            f["worth_top1"] = -float(hit["top1_delta"]) * 100
            f["p_value"] = hit.get("p_value")
            f["wins"] = hit.get("wins")
            f["losses"] = hit.get("losses")

    return {
        "n_features": len(cols),
        "n_families": len(families),
        "families": families,
        "ablation": abl_meta,
        "unattributed": sorted(orphans),
        "seasons": seasons,
        "source": str(cols_path.relative_to(Path(__file__).resolve().parents[1])),
    }


def latest_slate(target_type: str) -> tuple[int | None, int | None]:
    """The season and week the board should be showing, on any day of the week.

    Defined in `src/evaluation/slate.py` so the app and this exporter cannot
    drift apart — they used to disagree, and the disagreement was invisible
    because both rendered something.
    """
    from src.evaluation.slate import current_slate
    return current_slate(target_type)


#: Re-exported for the tests that assert what an empty board looks like.
from src.evaluation.slate import DEFST_ONLY_ROWS as _DEFST_ONLY_ROWS  # noqa: E402


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
    # The seasons, not only the count. This ladder and the walk-forward strip
    # at the top of the same page are measured on DIFFERENT windows — the
    # strip pools every retrained fold, the ladder only the seasons with
    # archived prices — and on 2026-08-19 they read 49.6% and 51.6% for the
    # same Top-1 with nothing on the page explaining why. The 2022 fold is in
    # one and not the other, and it is the weakest of the four at 45.7%.
    seasons = sorted(
        d["game_id"].str.slice(0, 4).cast(pl.Int64).unique().to_list())
    return {"games": d["game_id"].n_unique(), "rows": d.height,
            "blended": blended, "k": rows,
            "seasons": seasons,
            "span": (f"{seasons[0]}-{seasons[-1]}" if seasons else None)}


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


def parity(target_type: str, model: str, version: str | None) -> dict | None:
    """`Closer — backable` and `Closer — fade`, for the cover section.

    The same call the app's tiles make — see `src/evaluation/market_parity.py`
    for why it is not computed here. Only the directional halves ship: the
    overall figure blends them, and the two disagree so sharply that the blend
    reads as something you could act on when most of it is fade skill.

    This came back after the head-to-head pane was removed. It is a different
    claim in a different place — not "is the model good", which the evaluation
    harness answers, but "is there any basis for backing these picks over the
    price", which is the question a page about covering the field begs.
    """
    from src.evaluation import harness
    from src.evaluation.market_parity import compare
    from src.models.versioning import market_dir
    try:
        md = market_dir(target_type, version) if version else None
        h = compare(target_type, model, harness._features(target_type),
                    model_dir=md or get_path("models", target_type))
    except Exception as e:                                   # noqa: BLE001
        print(f"    parity unavailable: {e}", file=sys.stderr)
        return None
    if not h:
        return None
    keep = ("disagree_higher_pct", "disagree_higher_n",
            "disagree_lower_pct", "disagree_lower_n", "span", "players")
    out = {k: h[k] for k in keep if k in h}
    return out or None


# ── This week ─────────────────────────────────────────────────────────────

def _american(o) -> str | None:
    try:
        return f"{int(o):+d}"
    except (TypeError, ValueError):
        return None


def _i(x):
    """A whole number that survives JSON, or None. A pandas merge that found
    no match leaves NaN, and `int(nan)` raises rather than returning null."""
    v = _f(x)
    return None if v is None else int(v)


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

    shop = shopped_raw = None
    try:
        d = best_vs_consensus(season, week, target_type)
        shopped_raw = d if d is not None and d.height else None
        shop = shopped_raw.to_pandas() if shopped_raw is not None else None
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
            b = b.merge(
                shop[["player_name_norm", "best_odds", "best_book", "n_best"]],
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
                # How many books were level at that price. The named one is
                # the alphabetically first of them, which is arbitrary — this
                # is what stops the name reading as the only book offering it.
                "n_best": _i(r.get("n_best")),
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

    # The shortlist, off the board already in hand rather than a second build:
    # `board_for_week` runs a prediction, and running it twice to answer two
    # questions about one week is a minute of export for nothing.
    short = None
    try:
        import json as _json

        from src.evaluation.shortlist import shortlist as _shortlist

        clv_p = get_path("output", target_type) / "clv.json"
        econ_p = get_path("output", target_type) / "rank_economics.json"
        clv = _json.loads(clv_p.read_text()) if clv_p.exists() else None
        econ_j = _json.loads(econ_p.read_text()) if econ_p.exists() else None
        if clv and clv.get("by_edge"):
            short = _shortlist(board, target_type=target_type, clv=clv,
                               econ=econ_j, shopped=shopped_raw)
    except Exception as e:                                   # noqa: BLE001
        problems.append(f"Shortlist: {e}")
    return {"rows": rows, "problems": problems, "shortlist": short}


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
    cfg = get_config()
    who = served(target_type)
    model = who["model"]
    s, w = latest_slate(target_type)
    season = season if season is not None else s
    week = week if week is not None else w
    print(f"  {target_type}: {model} on {who['version']} — "
          f"{season} week {week}", file=sys.stderr)

    df, _ = _backtests(target_type, model)

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

    combo_rec = load_combos(get_path("output", target_type) / "combo_backtest.json")

    return {
        "key": target_type, "label": label, "season": season, "week": week,
        "served": who, "model": model,
        # What the served model was fitted on, and how it scored season by
        # season. Read from the model's own artifacts, so it describes what is
        # being served rather than what this file believes about it.
        "recipe": _recipe(target_type, model),
        # Still read by the master table and by Combinations, which both show
        # the blended Top-K ladder beside a pick's rank.
        "topk": topk_ladder(df),
        "rule": rule,
        "longshot": load_longshot(get_path("output", target_type) / "longshot_skill.json"),
        # Only the stops this page's own control can ask for. The file on
        # disk keeps every one the app's 5-50 slider offers; carrying them all
        # here is four fifths of a 1,100-row grid that nothing on the page can
        # look up, embedded twice over.
        # The rule, and how it has actually done. Trimmed to the pooled arms:
        # the per-season detail is in the artifact and the page's job is the
        # verdict, which is one line per arm.
        # Reference for reading any table here: what a position typically
        # does, what it is charged, and what we say about it.
        "positions": _position_rates(target_type),
        # Why every return here is negative, without reference to the model.
        "market_shape": _market_shape(target_type),
        "shortlist": (None if not pl_out.get("shortlist") else
                      {**pl_out["shortlist"],
                       "record": _shortlist_record(target_type),
                       "tracked_record": _tracked_record(target_type)}),
        "combo_record": ({"span": combo_rec.get("span"),
                          "rows": [r for r in (combo_rec.get("rows") or [])
                                   if r.get("show") in set(PAGE_SHOW_STOPS)]}
                         if combo_rec else None),
        "min_edge": float(cfg.get("betting", {}).get("min_edge_pp", 2.0)),
        "players": pl_out["rows"],
        "problems": pl_out["problems"] + tm["problems"],
        "teams": tm["rows"],
        "cover": cover_variants(pl_out["rows"], target_type,
                                parity(target_type, model, who["version"])),
    }


def _tracked_record(target_type: str) -> dict | None:
    """How the rules under observation have done since they were written down."""
    from src.evaluation.tracked_rules import score
    try:
        return (score(target_type) or {}).get("rules")
    except Exception:                                        # noqa: BLE001
        return None


def _market_shape(target_type: str) -> dict | None:
    """The book's error, its margin, and what the two cost, by decile."""
    from src.evaluation.market_shape import load
    return load(get_path("output", target_type) / "market_shape.json")


def _position_rates(target_type: str) -> dict | None:
    """The measured position table, if `scripts/42_position_rates.py` has run."""
    from src.evaluation.position_rates import load
    return load(get_path("output", target_type) / "position_rates.json")


def _shortlist_record(target_type: str) -> dict | None:
    """The graded verdict on the shortlist rule, pooled arms only."""
    p = get_path("output", target_type) / "shortlist_backtest.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    return {
        "seasons": d.get("seasons"), "skipped": d.get("skipped_seasons"),
        "priced_at": d.get("priced_at"),
        # The half no book sells, and the only measured return here that
        # clears zero. Carried whole: the page shows the group's realized rate
        # against its price, not just the return, because the return is
        # priced at a number no market posts.
        "fade": d.get("fade"),
        "fade_in_band": d.get("fade_in_band"),
        "arms": [{"arm": a["arm"], "note": a.get("note"),
                  **({} if a.get("pooled") is None else
                     {k: a["pooled"][k] for k in
                      ("n", "roi", "lo", "hi", "hit_pct", "breakeven_pct",
                       "breakeven_gap_pp", "verdict", "shopped")})}
                 for a in d.get("arms", [])],
    }


def cover_variants(rows: list[dict], target_type: str,
                   par: dict | None) -> dict:
    """What a full cover needs, for a page that lets the reader pick the legs.

    The selection is made in the browser, so no set of precomputed portfolios
    could cover it — n players chosen from a slate of hundreds is not an
    enumerable space. What ships instead is the ingredients: each player's
    probability and decimal price, plus the measured teammate correlation, and
    the page enumerates the 2^n patterns for whichever handful is picked.

    That is the one place this file duplicates arithmetic that also lives in
    `src.prediction.cover`, and it is a deliberate exception rather than an
    oversight: a static page cannot call Python. `tests/test_cover.py` pins the
    Python side to closed forms — k scorers return (1+d)^k - 1 at a flat price,
    winning slips are 2^k - 1 — and `tests/test_dashboard_export.py` pins the
    JavaScript to the same ones, so the two are checked against a third thing
    rather than against each other.
    """
    from src.prediction.portfolio import fit_correlation

    try:
        rho = float((fit_correlation(target_type) or {}).get("teammate_rho") or 0.0)
    except Exception:                                        # noqa: BLE001
        rho = 0.0
    from src.evaluation.cover_backtest import load as load_cover
    from src.utils.paths import get_path as _gp

    record = load_cover(_gp("output", target_type) / "cover_backtest.json")
    # What an unpriced leg should be assumed to pay on *this* market. Carried
    # rather than typed into the page, because +100 is odds-on for an anytime
    # leg near the top of the board and a fifth of the real price for a
    # first-TD one, and the payout table cannot tell the reader which — it is
    # built from prices and does not move when the probabilities do.
    from src.prediction.cover import assumed_price, price_curve

    probs = [r.get("ours") for r in rows]
    decs = [r.get("dec") for r in rows]
    return {"rho": rho, "max_players": 12, "record": record,
            # The median is the last resort; the curve is what an unpriced leg
            # is actually charged, per leg, at its own probability.
            "assumed_dec": assumed_price(probs, decs),
            "price_curve": price_curve(probs, decs),
            "parity": par, "selection": selection(target_type)}


def selection(target_type: str) -> dict | None:
    """The one line worth carrying from `make cover-selection`.

    That measurement is 44 variants, a hindsight ceiling, a walk-forward
    chooser and a random control redrawn five times, which is a page of its own
    and not one anybody wants under a bet slip. What ships is the only pattern
    in it that is not a single cell — the unblended ordering against the
    published one at matched size — with the control's luckiest redraw beside
    it, because without that the reader has no way to know a best-of-44 is
    worth nothing on its own.
    """
    from src.evaluation.cover_selection import load as load_sel

    sel = load_sel(get_path("output", target_type) / "cover_selection.json")
    if not sel:
        return None
    fam = sel.get("unblended_vs_published") or {}
    best_pair = (max(fam.get("sizes") or [], key=lambda p: p["gap"], default=None)
                 if not fam.get("identical") else None)
    ctl = sel.get("control") or {}
    return {
        "weeks": sel.get("weeks"), "span": sel.get("span"),
        "n_variants": sel.get("n_variants"),
        "identical": bool(fam.get("identical")),
        "model_wins": fam.get("model_wins"),
        "n_sizes": len(fam.get("sizes") or []),
        "best_pair": best_pair,
        "baseline_roi": (sel.get("baseline_result") or {}).get("roi"),
        "chooser_roi": (sel.get("chooser") or {}).get("roi"),
        "best_variant": (sel.get("best_variant") or {}).get("name"),
        "best_variant_roi": (sel.get("best_variant") or {}).get("roi"),
        "any_beats_zero": (sel.get("verdict") or {}).get("any_variant_beats_zero"),
        "control_best_roi": (ctl.get("best_roi") or {}).get("max"),
        "control_chooser_roi": (ctl.get("chooser_roi") or {}).get("max"),
    }


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


def receptions(season: int | None, week: int | None) -> dict:
    """The count market, which does not fit the shape every other tab assumes.

    Every pane on this page reads `M()` — one of `DATA.markets` — and every one
    of those is a player with a probability of a yes/no event. Receptions is a
    player, a *line*, and a distribution over counts, and the same player
    appears three times because three books drew the line in three places. So
    it gets its own payload and its own tab rather than a third entry in
    `markets`, where it would have silently broken the shortlist, the parlay
    builder and the combination search at once.

    Two blocks. `board` is what we say about this week against what is posted;
    `forward` is how that claim has held up on the weeks already played, which
    is the part that decides whether the board is worth reading at all.
    """
    from src.evaluation.receptions_forward import record
    from src.prediction.receptions import board_for_week, load_model

    s, w = latest_slate("anytime_td")
    season = season if season is not None else s
    week = week if week is not None else w
    print(f"  receptions: {season} week {week}", file=sys.stderr)

    from src.prediction.receptions import load_blend

    # The weight actually fitted, so no screen has to carry "17% / 83%" as a
    # typed-in constant that the next refit silently falsifies.
    out = {"season": season, "week": week, "rows": [], "problem": "",
           "forward": None, "model": load_model() is not None,
           "blend": load_blend()}
    if season is None or week is None:
        out["problem"] = "no slate to show"
        return out

    board, msg = board_for_week(season, week)
    out["problem"] = msg
    if board is not None and board.height:
        # `implied_prob` and `overround` are the over's vigged price and the
        # two sides summed, and they are here so the page can price the UNDER.
        # Without them a row carries one price while the board sells two
        # sides, and the under leg was being paid at the over's number — which
        # is near enough at -110/-110 and badly wrong at -160.
        keep = ["player_name", "team", "game_id", "mu", "point", "odds",
                "implied_prob", "overround",
                "fair_prob", "model_only", "ours", "edge_pp", "ev",
                "n_books", "thin",
                # How many games the projection is built from. A rolling mean
                # of one game and of fifty are the same number on screen
                # otherwise, which is how a player with a single career game
                # came to sit 12th of 502 with nothing saying so.
                "games_observed"]
        out["rows"] = board.select([c for c in keep if c in board.columns]
                                   ).to_dicts()
    try:
        out["forward"] = record(season)
    except Exception as e:                                   # noqa: BLE001
        # A missing forward record must not take the board down with it: the
        # board is this week and the record is last week, and they fail for
        # different reasons.
        out["problem"] = (out["problem"] + " · " if out["problem"] else "") + \
            f"forward record unavailable ({type(e).__name__})"
    return out


def build(season: int | None, week: int | None) -> dict:
    ensure_registered()
    return clean({
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "markets": [market(k, label, season, week) for k, label in MARKETS],
        "receptions": receptions(season, week),
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
