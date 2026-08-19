"""Us against the sportsbook, on the players it actually priced.

The headline claim of this project — "vs bookmaker", "Closer — backable" and
"Closer — fade" — used to live inside `app.py`, where it could not be called by
anything that was not Streamlit and could not be tested without one. It moved
here when a second surface (`scripts/34_export_dashboard.py`) needed the same
three numbers: a re-implementation would have been a fourth version of the
de-vigging and the joint path, and every previous copy of either in this
project has drifted.

Three things this does that a naive Brier comparison does not, each of which
changed the answer when it was added:

  * **Scores the joint path**, not raw model output. Comparing a ranking the
    board never shows against the bookmaker answers a question nobody asked.
  * **De-vigs across the joined population only.** Including prices for players
    that are never scored rescales everyone — see `blend.devig_market`.
  * **Resamples whole games** for the interval. Two players in one game share a
    defence, a game script and a final score, so treating them as independent
    understates the uncertainty by a wide margin.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import polars as pl

from src.utils.paths import get_path

#: Below this many priced player-games the Brier differences involved — third
#: decimal — are indistinguishable from resampling noise, so there is no
#: comparison to report.
MIN_PLAYERS = 500

#: Bootstrap draws for the overall interval, resampling games.
DRAWS = 400

#: Which slice counts as "we disagree with the book". The top decile of the
#: absolute gap: agreement is not skill, so it is excluded rather than diluted.
DISAGREE_Q = 0.9

#: Below this many players a directional half is a description of those players
#: rather than an estimate of anything.
MIN_DIRECTIONAL = 100


def expected_scorers(target_type: str, model_dir: Path | None = None) -> float:
    """How many players are expected to score in a game — the de-vig target.

    Exactly one player scores the first touchdown. For anytime TD the count is
    read from the prior fitted during training, so it tracks the league's
    scoring environment rather than a number someone typed once.
    """
    if target_type == "first_td":
        return 1.0
    path = (model_dir or get_path("models", target_type)) / "scorer_rate_prior.json"
    if path.exists():
        return float(json.loads(path.read_text())["mean_scorers_per_game"])
    return 4.3


def _directional(top: pl.DataFrame) -> dict:
    """Accuracy on big disagreements, split into backable and fade.

    Reported apart because the combined figure is not a betting signal and
    reads like one: most of the accuracy on big disagreements comes from
    correctly rating players *down*, and these markets only sell the Yes side.
    Quoting the blend sells fade skill as though it were a bet.
    """
    from sklearn.metrics import brier_score_loss

    out = {}
    for name, sub in (("higher", top.filter(pl.col("mp") > pl.col("fair"))),
                      ("lower", top.filter(pl.col("mp") < pl.col("fair")))):
        if sub.height < MIN_DIRECTIONAL:
            continue
        y = sub["target"].to_numpy().astype(float)
        if y.sum() == 0 or y.sum() == len(y):
            continue
        b = brier_score_loss(y, sub["mp"].to_numpy())
        m = brier_score_loss(y, sub["fair"].to_numpy())
        out[f"disagree_{name}_pct"] = (m - b) / m * 100
        out[f"disagree_{name}_n"] = int(sub.height)
    return out


def scored_against_market(target_type: str, model: str, features: pl.DataFrame,
                          model_dir: Path | None = None,
                          active_models=None) -> pl.DataFrame | None:
    """Our probability and the book's fair price, one row per priced player.

    Split out from `compare` so a caller that wants the joined frame — to bucket
    it, or to score a different statistic on it — does not have to re-derive the
    scoring and de-vigging to get there.
    """
    from src.ingest.odds_history import load_graded_history
    from src.models.scoring import score
    from src.models.trainer import _filter_low_activity, prepare_data

    graded = load_graded_history(target_type)
    md = model_dir or get_path("models", target_type)
    fc_path = md / "feature_cols.pkl"
    if graded is None or features is None or not fc_path.exists():
        return None

    from src.models.joint import load_conversion, load_team_rate
    feature_cols = pickle.loads(fc_path.read_bytes())
    team_model = load_team_rate(md / "team_td_rate.json")
    conversion = load_conversion(md / "td_conversion.json")
    exp = expected_scorers(target_type, md)

    parts = []
    for season in sorted(graded["season"].unique().to_list()):
        d = _filter_low_activity(
            features.filter((pl.col("season") == season)
                            & pl.col("target").is_not_null()))
        if d.height == 0:
            continue
        X, _ = prepare_data(d, feature_cols)
        d = d.with_columns(pl.Series(
            "mp", score(model, X, feature_cols, md, active_models=active_models)))
        if target_type != "first_td" and team_model is not None:
            from src.models.joint import apply_joint
            d = apply_joint(d, d, team_model, score_col="mp", out_col="mp",
                            conversion=conversion)

        j = d.select(["game_id", "player_id", "mp", "target"]).join(
            graded.filter(pl.col("season") == season)
                  .select(["game_id", "player_id", "implied_prob"]),
            on=["game_id", "player_id"], how="inner")
        if j.height == 0:
            continue
        j = j.with_columns(
            (pl.col("implied_prob") / pl.col("implied_prob").sum().over("game_id")
             * exp).alias("fair"))
        parts.append(j.with_columns(pl.lit(season).alias("season")))

    if not parts:
        return None
    return pl.concat(parts)


def compare(target_type: str, model: str, features: pl.DataFrame,
            model_dir: Path | None = None, active_models=None,
            seed: int = 0) -> dict | None:
    """The three tiles, pooled over every season we hold prices for.

    A single season is ~7,000 priced players and the differences are in the
    third decimal, so a one-season read swings on noise — the same model
    measured +2.1% on 2025 and +0.6% on 2024. Returns None rather than a
    figure when there is not enough priced history to say anything.
    """
    try:
        from sklearn.metrics import brier_score_loss, roc_auc_score
    except Exception:                                        # noqa: BLE001
        return None

    j = scored_against_market(target_type, model, features, model_dir,
                              active_models)
    if j is None or j.height < MIN_PLAYERS:
        return None

    j = j.with_columns((pl.col("mp") - pl.col("fair")).abs().alias("gap"))
    y = j["target"].to_numpy().astype(float)
    ours, mkt = j["mp"].to_numpy(), j["fair"].to_numpy()

    top = j.filter(pl.col("gap") >= float(np.quantile(j["gap"].to_numpy(), DISAGREE_Q)))
    yt = top["target"].to_numpy().astype(float)
    bo = brier_score_loss(yt, top["mp"].to_numpy())
    bm = brier_score_loss(yt, top["fair"].to_numpy())
    b_all, m_all = brier_score_loss(y, ours), brier_score_loss(y, mkt)

    games = j["game_id"].to_numpy()
    uniq = np.unique(games)
    idx = {g: np.flatnonzero(games == g) for g in uniq}
    rng = np.random.default_rng(seed)
    boot = []
    for _ in range(DRAWS):
        pick = rng.choice(len(uniq), len(uniq), replace=True)
        rows = np.concatenate([idx[uniq[i]] for i in pick])
        yb = y[rows]
        if yb.sum() == 0 or yb.sum() == len(yb):
            continue
        bb = brier_score_loss(yb, ours[rows])
        mb = brier_score_loss(yb, mkt[rows])
        boot.append((mb - bb) / mb * 100)
    boot = np.array(boot) if boot else np.array([0.0])

    seasons = sorted(j["season"].unique().to_list())
    return {
        "seasons": seasons,
        "span": f"{seasons[0]}-{seasons[-1]}" if len(seasons) > 1 else str(seasons[0]),
        "players": j.height,
        "games": int(len(uniq)),
        "overall_better_pct": (m_all - b_all) / m_all * 100,
        "overall_lo": float(np.percentile(boot, 2.5)),
        "overall_hi": float(np.percentile(boot, 97.5)),
        "disagree_better_pct": (bm - bo) / bm * 100,
        **_directional(top),
        "auc_ours": roc_auc_score(y, ours),
        "auc_market": roc_auc_score(y, mkt),
    }
