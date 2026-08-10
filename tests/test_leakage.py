"""Regression tests for leakage and train/serve skew.

Every test here corresponds to a bug that shipped, produced confident-looking
predictions, and was invisible until someone compared the output to a real
sportsbook price. None of them raised an error at the time. They are cheap to
run and they are the difference between a model that is wrong and a model that
is wrong *and you believe it*.

    pytest tests/ -v

Tests that need built artifacts skip when those are absent, so a fresh checkout
still runs green.
"""
from __future__ import annotations

import pickle
from pathlib import Path

import polars as pl
import pytest

from src.utils.config import get_config
from src.utils.paths import get_path

TARGET = "anytime_td"


def _features() -> pl.DataFrame:
    p = get_path("processed", TARGET) / "features.parquet"
    if not p.exists():
        pytest.skip("features.parquet not built — run `make features`")
    return pl.read_parquet(p)


# --------------------------------------------------------------------------
# 1. Row existence must not encode the outcome
# --------------------------------------------------------------------------

@pytest.mark.parametrize("col", [
    "player_i10_touches_szn_avg",
    "player_rz_touches_szn_avg",
    "player_carries_szn_avg",
    "player_gl_carries_szn_avg",
    "player_h1_touches_szn_avg",
])
def test_nullness_alone_does_not_predict_the_target(col):
    """A feature being null must not, by itself, tell you who scored.

    Usage frames built from play-by-play only contain a row where that usage
    happened, so a raw left join makes "not null" mean "had a goal-line touch in
    this very game". That was worth up to a 26x lift on P(scored) before any
    value was read, and it survived every shift(1) audit because the *values*
    were correctly lagged. src/features/spine.py densifies against the candidate
    pool to fix it.
    """
    df = _features()
    if col not in df.columns:
        pytest.skip(f"{col} not present")
    d = df.filter(pl.col("target").is_not_null())
    nn = d.filter(pl.col(col).is_not_null())
    nu = d.filter(pl.col(col).is_null())
    if nn.height < 500 or nu.height < 500:
        pytest.skip("not enough rows on both sides to judge")

    lift = nn["target"].mean() / max(nu["target"].mean(), 1e-9)
    # Some lift is legitimate: a player with too little history to roll is
    # genuinely less likely to score. Game-level leakage looked like 15-26x.
    assert lift < 6.0, (
        f"{col}: nullness alone gives a {lift:.1f}x lift in P(scored) "
        f"({nn['target'].mean():.3f} vs {nu['target'].mean():.3f}). The frame is "
        f"probably sparse — densify it via src/features/spine.py."
    )


# --------------------------------------------------------------------------
# 2. Joins must not fan out ahead of a shift()
# --------------------------------------------------------------------------

def test_team_target_tendency_has_one_row_per_game_team():
    """Duplicated rows put shift(1) on another row of the SAME game.

    This one joined per-scoring-team rows to games on game_id alone, giving
    22,698 rows for 6,600 keys, and leaked each team's current result into its
    own 'historical' rate. DEF/ST top picks hit 100% on holdout.
    """
    if not (get_path("processed", TARGET) / f"tds_{TARGET}.parquet").exists():
        pytest.skip("targets not built")
    from src.features.target_history_features import build_team_target_tendency

    out = build_team_target_tendency(TARGET)
    keys = out.select(["game_id", "team"]).unique().height
    assert out.height == keys, (
        f"fan-out: {out.height} rows for {keys} (game_id, team) pairs"
    )


# --------------------------------------------------------------------------
# 3. Predict-time features must look like training features
# --------------------------------------------------------------------------

def test_predict_season_features_are_not_wholesale_null():
    """The 2025 weekly-stats gap blanked 143 of 324 features at predict time.

    prepare_data turns null into 0.0 without complaint, so the model scored rows
    unlike anything it trained on and implied 7.6 TD scorers per game against a
    true ~4.3.
    """
    df = _features()
    cfg = get_config()
    predict_season = cfg["seasons"]["predict_season"]
    fc_path = get_path("models", TARGET) / "feature_cols.pkl"
    if not fc_path.exists():
        pytest.skip("model not trained")
    feature_cols = pickle.loads(fc_path.read_bytes())

    pred = df.filter(pl.col("season") == predict_season)
    train = df.filter(pl.col("season") <= cfg["splits"]["train_end"])
    if pred.height == 0:
        pytest.skip("no predict-season rows")

    degraded = []
    for c in feature_cols:
        if c not in df.columns:
            continue
        gap = float(pred[c].is_null().mean()) - float(train[c].is_null().mean())
        if gap > 0.5:
            degraded.append(c)

    assert not degraded, (
        f"{len(degraded)} feature(s) are >50pp more null at predict time than in "
        f"training and will silently become 0.0: {degraded[:10]}"
    )


# --------------------------------------------------------------------------
# 4. The published probabilities must be physically sane
# --------------------------------------------------------------------------

def test_scorer_rate_prior_matches_reality():
    """The fitted expectation must track the actual number of scorers."""
    path = get_path("models", TARGET) / "scorer_rate_prior.json"
    if not path.exists():
        pytest.skip("prior not fitted — run `make train`")
    import json
    prior = json.loads(path.read_text())

    df = _features().filter(pl.col("target").is_not_null())
    actual = (
        df.group_by("game_id").agg(pl.col("target").sum().alias("n"))["n"].mean()
    )
    fitted = prior["mean_scorers_per_game"]
    assert abs(fitted - actual) < 1.0, (
        f"prior says {fitted:.2f} scorers/game, data says {actual:.2f}"
    )


def test_level_calibration_preserves_ranking():
    """Anchoring the level must never reorder a game's players."""
    import numpy as np
    from src.prediction.blend import calibrate_level

    df = pl.DataFrame({
        "game_id": ["g1"] * 5,
        "raw_prob": [0.9, 0.7, 0.5, 0.3, 0.1],
    })
    expected = pl.DataFrame({"game_id": ["g1"], "expected_scorers": [1.5]})
    out = calibrate_level(df, "raw_prob", expected)

    before = np.argsort(-df["raw_prob"].to_numpy())
    after = np.argsort(-out["prob_calibrated"].to_numpy())
    assert (before == after).all(), "level calibration reordered players"
    assert abs(out["prob_calibrated"].sum() - 1.5) < 1e-3


def test_reported_accuracy_matches_metrics_json():
    """What the app displays must equal what training measured.

    The app ranked over the *unfiltered* candidate pool while training, metrics
    and predict() all apply _filter_low_activity. That put ~5,200 extra
    deep-bench rows per season into the ranking — rows whose null features become
    0.0 — and some outranked real starters. The app showed Top-1 as 10.2% for a
    model whose measured Top-1 was 63.4%.
    """
    import json
    import numpy as np
    from src.models.registry import get_model, ensure_registered

    metrics_path = get_path("output", TARGET) / "metrics.json"
    fc_path = get_path("models", TARGET) / "feature_cols.pkl"
    if not (metrics_path.exists() and fc_path.exists()):
        pytest.skip("model not trained")

    ensure_registered()
    cfg = get_config()
    model_name = cfg["models"]["production"]
    reported = next(
        (m["top_1_accuracy"] for m in json.loads(metrics_path.read_text())
         if m["model"] == f"{model_name} (test)"), None,
    )
    if reported is None:
        pytest.skip(f"no test metrics for {model_name}")

    from src.models.trainer import prepare_data, _filter_low_activity
    feature_cols = pickle.loads(fc_path.read_bytes())
    df = _features().filter(
        (pl.col("season") == cfg["splits"]["test_season"]) & pl.col("target").is_not_null()
    )
    df = _filter_low_activity(df)

    model = get_model(model_name).load(get_path("models", TARGET) / f"{model_name}.pkl")
    model.feature_names = feature_cols
    X, _ = prepare_data(df, feature_cols)
    e = df.with_columns(pl.Series("prob", model.predict_proba(X)))
    e = e.with_columns(
        pl.col("prob").rank(descending=True, method="ordinal").over("game_id").alias("r")
    )
    best = e.filter(pl.col("target") == 1).group_by("game_id").agg(
        pl.col("r").min().alias("b")
    )["b"].to_list()
    recomputed = sum(1 for x in best if x == 1) / len(best)

    assert abs(recomputed - reported) < 0.02, (
        f"recomputed Top-1 {recomputed:.1%} != reported {reported:.1%}. The "
        f"evaluation pool has drifted from the one production scores."
    )


# --------------------------------------------------------------------------
# 5. Betting maths
# --------------------------------------------------------------------------

def test_devig_lowers_probabilities():
    """Raw book prices overstate every player; de-vigging must reduce them."""
    from src.prediction.blend import devig_market

    odds = pl.DataFrame({
        "game_id": ["g1"] * 4,
        "player_name_norm": list("abcd"),
        "implied_prob": [0.60, 0.50, 0.40, 0.30],  # sums to 1.80
    })
    expected = pl.DataFrame({"game_id": ["g1"], "expected_scorers": [1.5]})
    out = devig_market(odds, expected)
    assert out["market_prob"].sum() == pytest.approx(1.5, abs=1e-6)
    assert (out["market_prob"] < out["implied_prob"]).all()


def test_ev_and_kelly_are_consistent():
    """A fair coin at fair odds must be zero EV and zero stake."""
    from src.prediction.bets import american_to_decimal, build_bet_card

    assert american_to_decimal(100) == pytest.approx(2.0)
    assert american_to_decimal(-200) == pytest.approx(1.5)

    preds = pl.DataFrame({
        "game_id": ["g1"], "player_name": ["x"], "player_name_norm": ["x"],
        "team": ["AAA"], "game_label": ["A @ B"], "probability": [0.50],
    })
    market = pl.DataFrame({
        "game_id": ["g1"], "player_name_norm": ["x"],
        "odds": [100], "market_prob": [0.50],
    })
    card = build_bet_card(preds, market)
    assert card.height == 0, "a zero-edge bet at fair odds should not qualify"


def test_positive_edge_produces_a_positive_stake():
    from src.prediction.bets import build_bet_card

    preds = pl.DataFrame({
        "game_id": ["g1"], "player_name": ["x"], "player_name_norm": ["x"],
        "team": ["AAA"], "game_label": ["A @ B"], "probability": [0.60],
    })
    market = pl.DataFrame({
        "game_id": ["g1"], "player_name_norm": ["x"],
        "odds": [100], "market_prob": [0.50],
    })
    card = build_bet_card(preds, market)
    assert card.height == 1
    row = card.row(0, named=True)
    assert row["ev_pct"] == pytest.approx(20.0, abs=0.1)   # 0.6*1 - 0.4
    assert row["stake"] > 0
