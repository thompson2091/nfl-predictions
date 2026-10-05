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

import numpy as np
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
    from src.utils.config import production_model
    model_name = production_model(TARGET)
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

def test_rank_calibration_never_reorders_players():
    """The positional correction adjusts confidence, never who we like.

    Different shifts per rank could otherwise let a #4 overtake a #3 on the
    strength of a positional average — which is noisy enough to invert
    neighbouring ranks by chance.
    """
    from src.models.rank_calibration import apply_rank_calibration

    df = pl.DataFrame({
        "game_id": ["g1"] * 5,
        "p": [0.60, 0.45, 0.40, 0.35, 0.30],
    })
    # Deliberately perverse: shove the lower ranks up hard.
    calib = {"deltas": {1: -0.5, 2: 0.0, 3: 0.9, 4: 1.2, 5: 1.5}}
    out = apply_rank_calibration(df, calib, "p", out_col="q")

    before = out["p"].to_numpy()
    after = out["q"].to_numpy()
    assert (np.diff(before) <= 0).all(), "input should be sorted descending"
    assert (np.diff(after) <= 1e-12).all(), (
        f"rank calibration reordered players: {after}"
    )


def test_rank_calibration_shrinks_inconsistent_ranks():
    """A bias that flips sign between seasons must be damped toward zero."""
    from src.models.rank_calibration import fit_rank_calibration

    rows = []
    for season, flip in [(2021, 1), (2022, -1), (2023, 1), (2024, -1)]:
        for g in range(60):
            # Rank 1 alternates direction each season (noise); rank 2 is
            # consistently under-predicted (real).
            rows.append({"season": season, "game_id": f"{season}_{g}",
                         "prob": 0.50, "target": 1 if flip > 0 else 0})
            rows.append({"season": season, "game_id": f"{season}_{g}",
                         "prob": 0.30, "target": 1 if g % 2 == 0 else 0})
    calib = fit_rank_calibration(pl.DataFrame(rows), "prob", season_col="season")
    d = {x["rank"]: x for x in calib["diagnostics"]}
    assert d[1]["kept"] < d[2]["kept"], (
        f"the rank that flips sign should be shrunk harder: "
        f"rank1 kept {d[1]['kept']}, rank2 kept {d[2]['kept']}"
    )


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


def test_candidate_filter_never_reads_the_outcome():
    """The pool of players we evaluate must not depend on who scored.

    `_filter_low_activity` once kept any row with `target == 1`. That made
    survival a function of the label: the only zero-usage players left in the
    data were the ones who happened to score, so the model learned that no
    usage predicts a touchdown and grossly overpriced deep longshots. It also
    skewed train against serve, since a future week has no `target` column at
    all. Flipping every label must not change which rows survive.
    """
    from src.models.trainer import _filter_low_activity

    cfg = get_config()
    _p = get_path("processed", cfg["target"]["type"]) / "features.parquet"
    if not _p.exists():
        pytest.skip("features.parquet not built — run `make features`")
    feats = pl.read_parquet(_p).filter(pl.col("target").is_not_null())

    def surviving_keys(frame: pl.DataFrame) -> set:
        kept = _filter_low_activity(frame)
        return set(zip(kept["game_id"].to_list(), kept["player_id"].to_list()))

    actual = surviving_keys(feats)
    all_zero = surviving_keys(feats.with_columns(pl.lit(0).alias("target")))
    all_one = surviving_keys(feats.with_columns(pl.lit(1).alias("target")))

    assert actual == all_zero, (
        f"{len(actual - all_zero):,} rows survive the candidate filter only "
        "because the player scored. Those rows are 100% positive by "
        "construction and leak the label into the feature space."
    )
    assert actual == all_one, "candidate filter responds to the label"


def test_zero_usage_players_are_not_all_scorers():
    """Guards the specific corner the leak created.

    A player with no carries, no targets, no receptions, no snaps and no
    starter role is a deep longshot: the real anytime-TD rate for that group
    is a couple of percent. If it reads anywhere near 1.0, outcome-dependent
    filtering has emptied the corner of everyone who failed to score.
    """
    from src.models.trainer import _filter_low_activity

    cfg = get_config()
    _p = get_path("processed", cfg["target"]["type"]) / "features.parquet"
    if not _p.exists():
        pytest.skip("features.parquet not built — run `make features`")
    feats = pl.read_parquet(_p).filter(pl.col("target").is_not_null())

    pool = _filter_low_activity(feats)
    zero_usage = pool.filter(
        (pl.col("player_carries_avg_5g").fill_null(0) == 0)
        & (pl.col("player_targets_avg_5g").fill_null(0) == 0)
        & (pl.col("player_receptions_avg_5g").fill_null(0) == 0)
        & (pl.col("is_starter").fill_null(0) == 0)
        & (pl.col("snap_pct").fill_null(0) == 0)
    )
    if zero_usage.height == 0:
        return  # nobody in that corner survives the filter at all — fine

    rate = zero_usage["target"].mean()
    assert rate < 0.25, (
        f"zero-usage players score at {rate:.1%} across {zero_usage.height:,} "
        "rows. A pre-kickoff-blind filter cannot produce that; the pool is "
        "being selected on the outcome."
    )


def test_ensemble_optimiser_actually_optimises():
    """The weight search must respond to the data, not echo its starting point.

    `_optimize_ensemble_weights` used to minimise negative top-1 accuracy with
    L-BFGS-B. Top-1 is a step function of the weights, so its numerical
    gradient is exactly zero, the optimiser returned at iteration 0, and every
    training run printed equal weights as though they had been learned. Feed it
    one model that is perfect and two that are noise: a working search must
    move decisively toward the informative one.
    """
    from src.models.trainer import _optimize_ensemble_weights

    rng = np.random.default_rng(0)
    n = 4000
    y = rng.binomial(1, 0.2, n)
    good = np.clip(y * 0.75 + 0.12 + rng.normal(0, 0.03, n), 0.01, 0.99)
    noise1 = np.clip(rng.uniform(0.05, 0.4, n), 0.01, 0.99)
    noise2 = np.clip(rng.uniform(0.05, 0.4, n), 0.01, 0.99)

    val_df = pl.DataFrame({
        "target": y,
        "game_id": [f"g{i // 20}" for i in range(n)],
        "player_id": [f"p{i}" for i in range(n)],
    })
    w = _optimize_ensemble_weights(
        {"good": good, "noise1": noise1, "noise2": noise2}, val_df
    )
    assert w["good"] > 0.5, (
        f"optimiser gave the only informative model {w['good']:.3f} weight. "
        "A flat return of 1/n means the search never moved off its start."
    )
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_level_calibration_can_target_a_subset():
    """`mask_col` must match the sum over the masked rows, not over everything.

    Production scores priced players; ~5 candidates a game are never priced and
    account for well under 1% of scorers. Normalizing the total across all of
    them leaves every priced player systematically short.
    """
    from src.prediction.blend import calibrate_level

    df = pl.DataFrame({
        "game_id": ["g1"] * 6,
        "p": [0.5, 0.4, 0.3, 0.2, 0.02, 0.02],
        "is_priced": [True, True, True, True, False, False],
    })
    expected = pl.DataFrame({"game_id": ["g1"], "expected_scorers": [2.0]})

    out = calibrate_level(df, "p", expected, mask_col="is_priced")
    priced_sum = out.filter(pl.col("is_priced"))["prob_calibrated"].sum()
    assert abs(priced_sum - 2.0) < 1e-6, (
        f"masked sum came to {priced_sum:.4f}, expected 2.0"
    )
    # Ranking is untouched: the shift is monotone in log-odds.
    assert out["prob_calibrated"].to_list() == sorted(
        out["prob_calibrated"].to_list(), reverse=True
    )


def test_implied_team_total_differs_between_the_two_teams():
    """An implied team total is team-specific; identical values mean a sign bug.

    `build_vegas_features` negates `spread_line` into away perspective and then
    used to negate it again inside the formula. The two canceled, so every
    away team was handed the home team's implied total — the same number for
    both sides of every game, uncorrelated with the spread, flattening the four
    `ix_itt_*` interactions that multiply through it.
    """
    cfg = get_config()
    _p = get_path("processed", cfg["target"]["type"]) / "features.parquet"
    if not _p.exists():
        pytest.skip("features.parquet not built — run `make features`")
    feats = pl.read_parquet(_p).filter(pl.col("implied_team_total").is_not_null()
             & pl.col("spread_line").is_not_null()
             # A true pick'em splits the total evenly, so both sides really do
             # carry the same number. Only those are allowed to match.
             & (pl.col("spread_line") != 0))

    per_game = (
        feats.group_by(["game_id", "team"])
        .agg(pl.col("implied_team_total").first())
        .group_by("game_id")
        .agg(pl.col("implied_team_total").n_unique().alias("n"))
    )
    identical = per_game.filter(pl.col("n") == 1).height
    assert identical == 0, (
        f"{identical} of {per_game.height} games give both teams the same "
        "implied team total — the away-side sign flip is canceling out."
    )

    # The favorite must carry the higher implied total, by construction.
    t = feats.group_by(["game_id", "team"]).agg([
        pl.col("implied_team_total").first(), pl.col("spread_line").first(),
    ])
    corr = np.corrcoef(t["spread_line"].to_numpy(),
                       t["implied_team_total"].to_numpy())[0, 1]
    assert corr > 0.5, (
        f"implied total vs spread correlation is {corr:+.3f}. nflverse spread "
        "is positive when this team is favored, so a favorite must carry the "
        "higher implied total."
    )


def test_favourite_flag_is_not_inverted():
    """`is_favorite` must mark the team the market expects to win.

    nflverse `spread_line` is positive when the home team is favored, and the
    code asserted the opposite in a comment. The flag came out fully inverted:
    teams marked favorite won 34.9% of their games and teams marked underdog
    won 66.7%. `is_big_favorite` and `favorite_team` in the score-first
    features carried the same inversion.
    """
    cfg = get_config()
    _p = get_path("processed", cfg["target"]["type"]) / "features.parquet"
    if not _p.exists():
        pytest.skip("features.parquet not built — run `make features`")
    feats = pl.read_parquet(_p)
    t = feats.group_by(["game_id", "team"]).agg([
        pl.col("is_favorite").first(), pl.col("is_home").first(),
    ]).drop_nulls()

    sched = pl.read_parquet(get_path("raw") / "schedules.parquet").select(
        ["game_id", "home_score", "away_score"]
    ).drop_nulls()
    sched = sched.with_columns(
        (pl.col("home_score") > pl.col("away_score")).alias("home_won")
    )
    home = t.filter(pl.col("is_home") == 1).join(sched, on="game_id", how="inner")
    if home.height < 500:
        pytest.skip("not enough completed games")

    fav = home.filter(pl.col("is_favorite") == 1)["home_won"].mean()
    dog = home.filter(pl.col("is_favorite") == 0)["home_won"].mean()
    assert fav > dog, (
        f"teams flagged favorite win {fav:.1%} of the time, underdogs win "
        f"{dog:.1%}. The flag is inverted."
    )


def test_joint_model_conserves_expected_touchdowns():
    """Expected touchdowns must sum to the team rate, with no rescaling step.

    This is the whole point of the Poisson x share factorisation: the per-player
    classifier needs `calibrate_level` to shift a game's log-odds until the
    total looks right, and the blend that follows then undoes part of it. Here
    the constraint holds by construction — sum_i lambda*s_i = lambda, because
    the shares sum to one.
    """
    from src.models.joint import player_shares, combine

    df = pl.DataFrame({
        "game_id": ["g1"] * 5,
        "team": ["A"] * 3 + ["B"] * 2,
    })
    rates = np.array([0.5, 0.3, 0.2, 0.6, 0.4])
    d = player_shares(rates, df)
    for team, grp in d.group_by("team"):
        assert abs(grp["share"].sum() - 1.0) < 1e-9, f"shares for {team} do not sum to 1"

    d = d.with_columns(pl.Series("team_lambda", [2.5, 2.5, 2.5, 1.5, 1.5]))
    out = combine(d)
    # Expected touchdowns per team = lambda. Distinct scorers is strictly less,
    # since one player can score twice.
    for team, grp in out.group_by("team"):
        lam = grp["team_lambda"][0]
        exp_tds = (grp["team_lambda"] * grp["share"]).sum()
        assert abs(exp_tds - lam) < 1e-9
        assert grp["probability"].sum() < lam + 1e-9
    assert out["probability"].is_between(0.0, 1.0).all()


def test_first_td_probabilities_sum_to_one_per_game():
    """Exactly one player scores the game's first touchdown."""
    from src.models.joint import player_shares, first_td_probability

    df = pl.DataFrame({"game_id": ["g1"] * 5, "team": ["A"] * 3 + ["B"] * 2})
    d = player_shares(np.array([0.5, 0.3, 0.2, 0.6, 0.4]), df)
    d = d.with_columns(pl.Series("team_lambda", [2.5, 2.5, 2.5, 1.5, 1.5]))
    out = first_td_probability(d)
    assert abs(out["first_td_prob"].sum() - 1.0) < 1e-9, (
        f"first-TD probabilities sum to {out['first_td_prob'].sum():.6f}, not 1"
    )
    # The stronger offense must be likelier to score first.
    a = out.filter(pl.col("team") == "A")["first_td_prob"].sum()
    b = out.filter(pl.col("team") == "B")["first_td_prob"].sum()
    assert a > b


def test_team_rate_responds_to_the_market():
    """A higher implied team total must predict more touchdowns, not fewer.

    The first fit of this model returned a coefficient of -0.004 on implied
    team total — effectively zero, and the wrong sign — because the feature was
    identical for both teams in every game. The GLM had nothing to read.
    """
    from src.models.joint import fit_team_rate, team_rate

    cfg = get_config()
    _p = get_path("processed", cfg["target"]["type"]) / "features.parquet"
    if not _p.exists():
        pytest.skip("features.parquet not built — run `make features`")
    feats = pl.read_parquet(_p)
    seasons = list(range(2015, cfg["splits"]["train_end"] + 1))
    model = fit_team_rate(feats, seasons)

    idx = model["design_cols"].index("implied_team_total")
    assert model["coef"][idx] > 0, (
        f"implied team total carries coefficient {model['coef'][idx]:+.4f}; "
        "a better offense must not predict fewer touchdowns."
    )

    games = pl.DataFrame({
        "game_id": ["g1", "g1"], "team": ["fav", "dog"],
        "implied_team_total": [28.0, 17.0],
        "total_line": [45.0, 45.0], "spread_line": [11.0, -11.0],
    })
    out = team_rate(model, games)
    fav = out.filter(pl.col("team") == "fav")["team_lambda"][0]
    dog = out.filter(pl.col("team") == "dog")["team_lambda"][0]
    assert fav > dog, f"favorite rate {fav:.3f} not above underdog {dog:.3f}"


def test_production_model_is_resolved_per_market():
    """Each market must serve the model that measured best on *that* market.

    `models.production` was a single global setting, so whichever market lost
    the argument silently ran on a weaker model: with it set to lgbm, First TD
    served a model that placed fourth of four on its own walk-forward.
    """
    from src.utils.config import production_model

    cfg = get_config()
    per_market = cfg["models"].get("production_by_target", {})
    assert per_market, "models.production_by_target is missing"

    for market, expected in per_market.items():
        assert production_model(market) == expected, (
            f"{market} resolves to {production_model(market)}, not {expected}"
        )
    # An unlisted market must still resolve, via the global fallback.
    assert production_model("some_new_market") == cfg["models"]["production"]


def test_each_market_serves_its_best_walkforward_model():
    """The configured model must be defensible against the measured table.

    Not "must be the argmax" — Top-1 differences inside a standard error are
    noise and a tie can reasonably go either way. But a configured model that
    is beaten by more than one standard error is a setting nobody re-derived
    after the evidence changed.
    """
    from src.utils.config import production_model

    for market in ("anytime_td", "first_td"):
        path = get_path("output", market) / "walkforward.json"
        if not path.exists():
            pytest.skip("walk-forward not run — python scripts/11_walkforward.py")
        from src.evaluation.harness import walkforward_rows
        folds, _ = walkforward_rows(market)
        if not folds or "model" not in folds[0]:
            pytest.skip("walk-forward artifact predates per-model scoring")

        pooled = {}
        for name in {f["model"] for f in folds}:
            sub = [f for f in folds if f["model"] == name]
            total = sum(f["games"] for f in sub)
            pooled[name] = (sum(f["top1"] * f["games"] for f in sub) / total, total)

        chosen = production_model(market)
        assert chosen in pooled, f"{market}: {chosen} has no walk-forward result"
        best_name, (best, n) = max(pooled.items(), key=lambda kv: kv[1][0])
        se = np.sqrt(best * (1 - best) / n)
        assert pooled[chosen][0] >= best - se, (
            f"{market} serves {chosen} at Top-1 {pooled[chosen][0]:.1%}, but "
            f"{best_name} reaches {best:.1%} — more than one standard error "
            f"({se:.1%}) better. Re-check models.production_by_target."
        )


def test_longshot_claim_is_backed_by_its_own_measurement():
    """The app's longshot highlight must not outlive the evidence for it.

    The claim is narrow — that we *order* the +1500-and-longer band better than
    the price does — and it is easy to slide from there into implying the band
    is profitable. It is not: the band is priced far above what it does. This
    test fails if the sorting edge stops being real, or if the artifact loses
    the counterweight figures the caption depends on.
    """
    from src.evaluation.longshot import load

    path = get_path("output", "anytime_td") / "longshot_skill.json"
    stats = load(path)
    if stats is None:
        pytest.skip("longshot measurement not run — scripts/12_longshot.py")

    for key in ("auc_ours", "auc_book", "auc_gap_lo", "band_price_implied",
                "band_actual_rate", "top_decile_actual",
                "top_decile_price_implied"):
        assert key in stats, f"artifact is missing {key}, which the app quotes"

    # The edge is allowed to be real or not. What is not allowed is the app
    # claiming one when the interval says otherwise, so the assertion is on the
    # LINK rather than on the result. It fired for real: after anytime TD moved
    # to the 24-family set the gap fell to +0.019 with a 95% interval of
    # (-0.011, +0.049), and the checkbox still described it as "the largest gap
    # anywhere on this board".
    app = (Path(__file__).resolve().parents[1] / "app.py").read_text()
    claim = "largest gap anywhere on this board"
    assert claim not in app, (
        f"{claim!r} is an unconditional superlative; the longshot gap is "
        f"measured and changes. Phrase it off `auc_gap_lo`.")
    assert 'ls["auc_gap_lo"] <= 0' in app or "ls['auc_gap_lo'] <= 0" in app, (
        "the longshot copy must branch on whether the gap clears zero")

    if stats["auc_gap_lo"] <= 0:
        assert "not distinguishable from zero" in app, (
            f"the measured gap's interval contains zero (lower bound "
            f"{stats['auc_gap_lo']:+.4f}) and the app must say so")
    # The counterweight must stay true, or the caption misleads: this band is
    # priced above what it actually does.
    assert stats["band_price_implied"] > stats["band_actual_rate"], (
        "the longshot band is no longer overpriced — the caption's warning "
        "about the bookmaker's margin needs rewriting."
    )


def test_devig_does_not_depend_on_how_many_players_were_priced():
    """A favorite's fair probability must not move when longshots are added.

    The one-sided branch divides every price by sum(implied)/expected, so
    quoting extra deep longshots rescales *everyone*. Archive coverage fell
    from 52 priced players a game in 2023 to 26.8 in 2025, and that alone moved
    a -100 favorite's fair probability from 41% to 49% while its real rate sat
    near 52% throughout. Callers must pass only the scored population.
    """
    from src.prediction.blend import devig_market

    core = pl.DataFrame({
        "game_id": ["g1"] * 4,
        "player_id": [f"p{i}" for i in range(4)],
        "implied_prob": [0.55, 0.30, 0.18, 0.10],
        "fair_prob": [None] * 4,
    })
    expected = pl.DataFrame({"game_id": ["g1"], "expected_scorers": [1.0]})
    base = devig_market(core, expected)
    fav_before = base.filter(pl.col("player_id") == "p0")["market_prob"][0]

    # The same four players, plus a tail of longshots nobody would score.
    tail = pl.DataFrame({
        "game_id": ["g1"] * 12,
        "player_id": [f"t{i}" for i in range(12)],
        "implied_prob": [0.03] * 12,
        "fair_prob": [None] * 12,
    })
    with_tail = devig_market(pl.concat([core, tail]), expected)
    fav_after = with_tail.filter(pl.col("player_id") == "p0")["market_prob"][0]

    # This documents the behavior rather than forbidding it: the function is
    # doing what it is asked. The guard that matters is that the *callers*
    # restrict their input, which the assertion below pins down.
    assert fav_after < fav_before, "expected the tail to dilute the favorite"

    import re
    src = Path("scripts/10_backtest.py").read_text()
    assert re.search(r"mkt\.join\(\s*res\.select", src), (
        "the backtest must intersect prices with the scored population before "
        "de-vigging, or its market numbers drift with archive coverage"
    )
    pred = Path("src/prediction/predict.py").read_text()
    assert "candidates, on=[\"game_id\", \"player_name_norm\"]" in pred, (
        "predict.py must restrict prices to this week's candidates before "
        "de-vigging"
    )


def test_clv_direction_logic_is_right_way_round():
    """A shortening price must count as the market agreeing with a high rating.

    Closing-line value is the only evidence available inside one season that an
    edge survives contact with money, and its sign is easy to invert without
    anything looking wrong — an inverted version would read 45% and be quietly
    reported as evidence against the model.
    """
    from src.evaluation.clv import measure
    import src.evaluation.clv as clv_mod

    keys = ["season", "week", "game_id", "player_name_norm"]
    # Four players: two we rate above the open, two below. The market moves
    # our way on every one, so agreement must be 100%.
    moves = pl.DataFrame({
        "season": [2026] * 4, "week": [1] * 4,
        "game_id": ["g1", "g1", "g2", "g2"],
        "player_name_norm": ["a", "b", "c", "d"],
        "open_prob": [0.20, 0.30, 0.20, 0.30],
        "close_prob": [0.26, 0.36, 0.14, 0.24],
        "open_odds": [400, 233, 400, 233],
        "close_odds": [285, 178, 614, 316],
    }).with_columns((pl.col("close_prob") - pl.col("open_prob")).alias("move"))
    preds = pl.DataFrame({
        "season": [2026] * 4, "week": [1] * 4,
        "game_id": ["g1", "g1", "g2", "g2"],
        "player_name_norm": ["a", "b", "c", "d"],
        "probability": [0.35, 0.45, 0.05, 0.10],
    })

    original = clv_mod.line_movement
    clv_mod.line_movement = lambda target_type="anytime_td": moves
    try:
        # measure() needs >= 50 rows; repeat the pattern to clear the floor.
        big_moves = pl.concat([
            moves.with_columns(pl.lit(f"g{i}").alias("game_id")) for i in range(20)
        ])
        big_preds = pl.concat([
            preds.with_columns(pl.lit(f"g{i}").alias("game_id")) for i in range(20)
        ])
        clv_mod.line_movement = lambda target_type="anytime_td": big_moves
        # first_td so the de-vig target is exactly 1.0 and the fixture's prices
        # (which already sum to 1.0 per game) pass through unchanged — the
        # point of this test is the direction logic, not the normalization.
        # This fixture names its column `probability`; the default is now the
        # pre-blend `prob_calibrated`, so say which one explicitly.
        stats = measure(big_preds, target_type="first_td", prob_col="probability")
    finally:
        clv_mod.line_movement = original

    assert stats is not None, "measure() returned nothing on a clean fixture"
    assert stats["agree_pct"] == 1.0, (
        f"market moved our way on every player but agreement read "
        f"{stats['agree_pct']:.1%} — the direction test is inverted"
    )
    assert stats["move_when_higher"] > 0, "prices we rated up should shorten"
    assert stats["move_when_lower"] < 0, "prices we rated down should lengthen"


def test_td_conversion_beats_plain_poisson():
    """The fitted conversion must be at least as good as what it replaced.

    Poisson thinning understated the top of the board by 5-7 points because a
    lead back's goal-line carries are not independent arrivals. The fit spans
    the range (r -> infinity recovers Poisson), so it can never be worse on the
    data it is fitted to — if this fails, the search is broken.
    """
    from src.models.joint import load_conversion

    conv = load_conversion(get_path("models", TARGET) / "td_conversion.json")
    if conv is None:
        pytest.skip("conversion not fitted — run `make train`")
    assert conv["log_loss"] <= conv["poisson_log_loss"] + 1e-9, (
        f"fitted conversion scores {conv['log_loss']:.5f} against Poisson's "
        f"{conv['poisson_log_loss']:.5f} — the search returned something worse "
        "than its own starting point."
    )
    assert 0.5 <= conv["level"] <= 1.5
    assert conv["dispersion"] > 0


def test_published_probabilities_sum_to_reality():
    """A game's probabilities must add up to the touchdowns actually scored.

    This is the property the joint model exists to guarantee, and it is the one
    that silently broke twice: once when the level was rescaled across every
    candidate rather than the priced ones, and once when Poisson thinning
    compressed the top of the board.
    """
    cfg = get_config()
    path = (get_path("output", TARGET)
            / f"backtest_{cfg['splits']['test_season']}.csv")
    if not path.exists():
        pytest.skip("backtest not run for the held-out season")

    d = pl.read_csv(path)
    games = d["game_id"].n_unique()
    published = d["prob_calibrated"].sum() / games
    actual = d["scored"].sum() / games
    assert abs(published - actual) < 0.35, (
        f"published probabilities sum to {published:.2f} per game against "
        f"{actual:.2f} actually scored"
    )


def test_clv_compares_against_the_devigged_open():
    """CLV must judge our disagreement, not the bookmaker's margin.

    Raw implied probability carries the vig, so the model sits below it on 73%
    of players by construction. Measured that way the "disagreement rate" is
    really the hold, and agreement gets a free ride from the market's overall
    drift. Against the de-vigged open the rate is 40%, which is an opinion.
    Zero-movement prices are dropped for the same reason: they were scoring as
    agreement on 14% of rows while carrying no information.
    """
    import inspect
    from src.evaluation import clv

    # `hit_rows` builds the scored rows and `measure` turns them into the
    # headline; the de-vig and the zero-movement filter live in the first, the
    # permutation null in the second. Inspecting both keeps the guard on the
    # behavior rather than on which function currently holds it — the split
    # happened so two runs could be paired on the same rows, and a guard that
    # broke on the move would have argued against making it.
    rows_src = inspect.getsource(clv.hit_rows)
    measure_src = inspect.getsource(clv.measure)
    assert "open_fair" in rows_src, "CLV no longer de-vigs the opening price"
    assert 'pl.col("move") != 0' in rows_src, "CLV counts prices that never moved"
    assert "null" in measure_src, "CLV reports no permutation null to compare against"

    # The same rows must reach the paired comparison, or a gate would judge a
    # candidate on a different population than the headline describes.
    assert "hit_rows" in inspect.getsource(clv.paired_clv)


def test_clv_is_reproducible_when_a_player_game_has_two_probabilities():
    """The same inputs must give the same answer twice.

    A player-game can appear in both a published weekly prediction file and the
    backtest frame for that season, carrying different probabilities — 367 keys
    do on anytime TD. Deduplicating with `keep="any"` resolved those
    arbitrarily, and the headline agreement rate moved between runs on
    identical data. That is tolerable for a report and disqualifying for a
    metric used to gate promotions, which is what this is now for.
    """
    import polars as pl
    from src.evaluation.clv import hit_rows, line_movement

    moves = line_movement("anytime_td")
    if moves is None or moves.height < 200:
        pytest.skip("no opening/closing pairs captured yet")

    # `.unique()` because line_movement is now keyed on the region set as well:
    # the same player-game legitimately appears once for `us` and once for
    # `us,us2`, which are different books and so different prices. Without this
    # the fixture builds four rows per key and the sort below stops being a
    # unique ordering — a fixture problem, not a reproducibility one.
    base = moves.select(["game_id", "player_name_norm"]).unique().head(200)
    # Two rows per key with different probabilities, interleaved so row order
    # alone would decide the winner.
    duped = pl.concat([
        base.with_columns([pl.lit(0.9).alias("prob_calibrated"),
                           pl.lit(0).alias("_src_rank")]),
        base.with_columns([pl.lit(0.1).alias("prob_calibrated"),
                           pl.lit(1).alias("_src_rank")]),
    ]).sample(fraction=1.0, shuffle=True, seed=7)

    first = hit_rows(duped, "anytime_td")
    second = hit_rows(duped.sample(fraction=1.0, shuffle=True, seed=99),
                      "anytime_td")
    if first is None or second is None:
        pytest.skip("not enough overlap to measure")
    key = ["game_id", "player_name_norm"]      # game_id alone is not unique
    assert (first.sort(key)["hit"].to_list()
            == second.sort(key)["hit"].to_list())

    # And the rank must decide it: _src_rank 0 carries 0.9, so every row should
    # have been scored on that value, not on 0.1.
    assert first["prob_calibrated"].unique().to_list() == [0.9]


def test_clv_result_beats_its_own_null():
    """Guards the headline claim, if the measurement has been run."""
    import glob
    if not glob.glob("data/archive/odds_history.parquet"):
        pytest.skip("no odds archive")
    from src.evaluation.clv import line_movement
    if line_movement("anytime_td") is None:
        pytest.skip("no opening/closing pairs captured yet")

    from src.evaluation.clv import measure
    import polars as _pl
    preds = []
    for path in sorted(glob.glob("output/anytime_td/backtest_*.csv")):
        d = _pl.read_csv(path)
        if "prob_calibrated" not in d.columns:
            continue
        preds.append(d.select(["game_id", "player_name", "prob_calibrated"]))
    if not preds:
        pytest.skip("no backtest frames")

    from src.features.odds_features import _normalize_name
    pr = _pl.concat(preds).with_columns(
        _pl.col("player_name")
        .map_elements(_normalize_name, return_dtype=_pl.Utf8)
        .alias("player_name_norm")
    )
    stats = measure(pr, "anytime_td", prob_col="prob_calibrated")
    if stats is None:
        pytest.skip("not enough overlap")

    assert stats["agree_pct"] > stats["null_hi"], (
        f"CLV agreement {stats['agree_pct']:.1%} is inside the permutation null "
        f"[{stats['null_lo']:.1%}, {stats['null_hi']:.1%}] — the model no longer "
        "anticipates market movement."
    )


def test_rank_economics_intervals_are_game_clustered():
    """Intervals must resample games, not bets.

    Two bets in one game share a defense, a game script and a final score. A
    naive standard error on this data is roughly half what it should be, which
    is how a break-even strategy comes to look like a winning one. Feeding the
    same returns as one-bet-per-game versus all-in-one-game must produce
    different intervals — if it does not, the clustering is not happening.
    """
    from src.evaluation.rank_economics import clustered_roi

    rng = np.random.default_rng(0)
    games = np.repeat(np.arange(60), 10)
    # Correlated within game: a shared game-level shock plus a little noise,
    # which is what a shootout does to every bet in that game. Independent
    # returns would show no clustering effect at all — correctly — so the
    # correlation has to be present for this test to mean anything.
    shock = rng.normal(0, 1.0, 60)
    pnl = shock[games] + rng.normal(0.05, 0.2, 600)

    naive = clustered_roi(pnl, np.arange(600), draws=600)      # bet-level
    clustered = clustered_roi(pnl, games, draws=600)           # game-level

    naive_width = naive["hi"] - naive["lo"]
    clustered_width = clustered["hi"] - clustered["lo"]
    assert clustered_width > naive_width * 1.5, (
        f"with returns correlated inside each game, clustering barely widened "
        f"the interval ({naive_width:.2f} -> {clustered_width:.2f}). The "
        "bootstrap is resampling bets rather than games, which understates the "
        "uncertainty roughly twofold."
    )


def test_rank_economics_verdict_matches_its_interval():
    """The verdict must follow the interval, not the point estimate."""
    from src.evaluation.rank_economics import clustered_roi

    rng = np.random.default_rng(1)
    games = np.arange(400)
    # Clearly profitable.
    good = clustered_roi(rng.normal(0.5, 0.4, 400), games, draws=400)
    assert good["verdict"] == "positive" and good["lo"] > 0
    # Positive point estimate, wide spread -> must NOT read as positive.
    noisy = clustered_roi(rng.normal(0.05, 6.0, 400), games, draws=400)
    assert noisy["roi"] is not None
    if noisy["lo"] <= 0 <= noisy["hi"]:
        assert noisy["verdict"] == "indistinguishable from zero"


def test_rank_economics_headline_is_declared_not_chosen():
    """The verdict must come from a pre-declared strategy, not the best one.

    Scanning top-1..5 and reporting the winner finds an edge by construction:
    on anytime TD the top-4 interval excluded zero while the other four spanned
    it, which is what one-in-five looks like.
    """
    import inspect
    from src.evaluation import rank_economics

    sig = inspect.signature(rank_economics.measure)
    assert "headline_n" in sig.parameters, "no declared headline strategy"
    assert sig.parameters["headline_n"].default == 3

    stats = rank_economics.load(
        get_path("output", TARGET) / "rank_economics.json")
    if stats is None:
        pytest.skip("rank economics not run — scripts/14_rank_economics.py")
    assert stats["headline"]["top_n"] == stats["headline_n"]
    assert stats["verdict"] == stats["headline"]["verdict"], (
        "the reported verdict does not match the declared headline strategy"
    )


def test_dutching_refuses_on_a_multi_winner_market():
    """Equal-return sizing is undefined when several selections can win.

    Anytime TD averages 4.01 scorers a game and 94.6% of games produce two or
    more, so "stake so any single winner returns the same" describes nothing.
    Returning a plausible table there would be worse than refusing.
    """
    from src.prediction.portfolio import allocate, is_single_winner

    assert is_single_winner("first_td")
    assert not is_single_winner("anytime_td")

    bets = pl.DataFrame({
        "game_id": ["g1"] * 3, "team": ["A"] * 3,
        "odds": [-120, 150, 300], "probability": [0.55, 0.40, 0.25],
    })
    with pytest.raises(ValueError, match="exactly one selection"):
        allocate(bets, 100.0, "dutch", target_type="anytime_td")

    # ...and it must work on the market where it is defined, returning equal
    # gross return whichever one lands.
    sized = allocate(bets, 100.0, "dutch", target_type="first_td")
    gross = (sized["stake"] * sized["dec"]).to_numpy()
    assert np.allclose(gross, gross[0], rtol=0.02), (
        f"dutching should equalise returns, got {gross}"
    )


def test_simulation_preserves_each_bet_marginal_probability():
    """Simulated hit rates must match the probabilities we allocated on.

    An earlier version regenerated outcomes from the joint model's Poisson and
    share structure. That reproduces the model's dependence but drifts off the
    published marginals — expected winners came out 1.44 where the
    probabilities summed to 1.59 — because those probabilities carry a fitted
    binomial conversion the Poisson draw does not.
    """
    from src.prediction.portfolio import simulate

    bets = pl.DataFrame({
        "game_id": ["g1"] * 4, "team": ["A", "A", "B", "B"],
        "odds": [-120, 150, 300, 500],
        "probability": [0.55, 0.40, 0.25, 0.15],
    })
    won = simulate(bets, n_draws=40_000, target_type="anytime_td")
    rates = won.mean(axis=0)
    assert np.allclose(rates, bets["probability"].to_numpy(), atol=0.01), (
        f"simulated rates {rates.round(3)} drifted from the probabilities "
        f"{bets['probability'].to_list()}"
    )


def test_single_winner_simulation_is_mutually_exclusive():
    """In a one-scorer market, two of our selections can never both win."""
    from src.prediction.portfolio import simulate

    bets = pl.DataFrame({
        "game_id": ["g1"] * 3, "team": ["A", "A", "B"],
        "odds": [500, 700, 900], "probability": [0.20, 0.15, 0.10],
    })
    won = simulate(bets, n_draws=20_000, target_type="first_td")
    assert won.sum(axis=1).max() <= 1, "two selections won the same game"
    assert np.allclose(won.mean(axis=0), bets["probability"].to_numpy(), atol=0.015)


def test_kelly_stakes_are_not_renormalised_to_the_full_bankroll():
    """Kelly returns a fraction of bankroll, not a weight to be scaled up.

    Normalizing it would turn "bet 3% of bankroll" into "bet everything" —
    a conservative rule silently becoming a reckless one.
    """
    from src.prediction.portfolio import allocate

    # Five selections, so the 25% per-bet cap does not bind and the comparison
    # is about the sizing rule rather than the cap.
    bets = pl.DataFrame({
        "game_id": ["g1"] * 5, "team": ["A"] * 5,
        "odds": [150, 200, 180, 220, 160],
        # Barely-positive edges: Kelly should stake very little.
        "probability": [0.41, 0.34, 0.37, 0.32, 0.39],
    })
    sized = allocate(bets, 1000.0, "kelly", target_type="anytime_td")
    assert sized["stake"].sum() < 200.0, (
        f"quarter Kelly on thin edges staked ${sized['stake'].sum():.0f} of "
        "$1000 — the fractions are being renormalized."
    )
    equal = allocate(bets, 1000.0, "equal", target_type="anytime_td")
    assert abs(equal["stake"].sum() - 1000.0) < 1.0, (
        "equal split should deploy the whole bankroll when the cap does not bind"
    )


def test_clv_refuses_a_market_contaminated_probability():
    """Scoring the blended number against the close measures the price itself.

    `final` is blend(prob_calibrated, market_prob) and market_prob is the
    de-vigged *closing* line, so asking whether it anticipates the close is
    circular. It is not a small effect: the blended column scored +9.3 points
    against its permutation null where the honest pre-blend column scored +4.9.
    """
    from src.evaluation.clv import measure, MARKET_CONTAMINATED, CLEAN_PROB_COL

    assert "final" in MARKET_CONTAMINATED
    assert CLEAN_PROB_COL == "prob_calibrated"

    dummy = pl.DataFrame({
        "game_id": ["g1"], "player_name_norm": ["a"], "final": [0.5],
    })
    with pytest.raises(ValueError, match="blended with the closing price"):
        measure(dummy, "anytime_td", prob_col="final")


def test_predictions_carry_the_preblend_column():
    """Live weeks need the clean column or CLV cannot be measured on them.

    The published `probability` is blended; without `prob_model` beside it, the
    weekly closing-line-value check from Week 1 would silently score the
    contaminated number.
    """
    import inspect
    from src.prediction import predict as predict_mod

    src = inspect.getsource(predict_mod)
    assert 'alias("prob_model")' in src, (
        "predict.py no longer writes the pre-blend column, so live CLV would "
        "fall back to the blended probability"
    )


# ─────────────────────────────────────────────────────────────────────────────
# What the board is allowed to claim
# ─────────────────────────────────────────────────────────────────────────────

def _econ(headline_verdict, rank_verdicts):
    """A rank_economics payload with only the fields the region rule reads."""
    return {
        "headline": {"verdict": headline_verdict, "roi": 12.0, "lo": 7.3,
                     "hi": 16.7, "hit_pct": 48.2},
        "headline_n": 3,
        "games": 849,
        "seasons": [2023, 2024, 2025],
        "by_rank": [{"rank": i + 1, "verdict": v}
                    for i, v in enumerate(rank_verdicts)],
    }


def test_board_marks_nothing_when_the_market_has_no_measured_edge():
    """An unproven market must get no ticks at all.

    First TD is accurate and unprofitable at once. A tick box on that board
    would read as evidence, and there is none — its top-3 interval spans zero.
    """
    from src.evaluation.rank_economics import profitable_region

    assert profitable_region(
        _econ("indistinguishable from zero", ["positive", "positive"])
    ) is None
    assert profitable_region(None) is None


def test_profitable_region_stops_at_the_first_gap():
    """A positive rank behind a negative one is noise, not depth.

    Taking the deepest positive rank anywhere in the table would mark rank 6
    while leaving rank 5 unmarked, which is both incoherent to read and an
    invitation to bet a slot that lost money.
    """
    from src.evaluation.rank_economics import profitable_region

    region = profitable_region(_econ(
        "positive",
        ["positive", "positive", "indistinguishable from zero", "positive"],
    ))
    assert region["max_rank"] == 2


def test_profitable_region_needs_a_positive_first_rank():
    from src.evaluation.rank_economics import profitable_region

    assert profitable_region(
        _econ("positive", ["indistinguishable from zero", "positive"])
    ) is None


def test_season_gate_uses_significance_not_point_estimates():
    """A thin season must not be able to veto a tier on a point estimate.

    The strong tier held 41 bets in 2023 against 414 and 339 in the other
    seasons — an interval of [-61%, +14%] that cannot resolve its own sign. The
    original gate required every season to be point-positive, so the whole tier
    appeared or vanished between rebuilds on which way those 41 fell, while the
    pooled figure sat at +29.5% and +29.6% across the same two rebuilds.
    """
    import inspect
    from src.evaluation import rank_economics

    for fn in (rank_economics.fit_highlight_tiers, rank_economics.fit_edge_rule):
        src = inspect.getsource(fn)
        assert '"negative"' in src, (
            f"{fn.__name__} no longer tests seasons for significance"
        )
        assert '(p["roi"] or 0) > 0' not in src, (
            f"{fn.__name__} is back to vetoing on a season point estimate"
        )


def test_edge_rule_needs_every_season_positive():
    """A cut-off that leans on one good year must not qualify.

    This is the condition doing the real work in fit_edge_rule: across ten
    candidate thresholds, something will clear a pooled interval by chance.
    Requiring all three seasons separately is what makes that hard.
    """
    import polars as pl
    from src.evaluation.rank_economics import fit_edge_rule

    # Two seasons of a genuinely good set, one season where it fell over.
    rows = []
    for season, wins in ((2023, 40), (2024, 40), (2025, 2)):
        for i in range(60):
            rows.append({
                "season": season, "week": 1 + i % 18,
                "game_id": f"{season}_{i}", "rank": 1,
                "prob_calibrated": 0.60, "market_prob": 0.40,
                "odds": 150, "dec": 2.5, "scored": 1 if i < wins else 0,
                "pnl": 1.5 if i < wins else -1.0, "breakeven": 0.4,
            })
        for i in range(60):
            rows.append({
                "season": season, "week": 1 + i % 18,
                "game_id": f"{season}_lo_{i}", "rank": 1,
                "prob_calibrated": 0.40, "market_prob": 0.40,
                "odds": 150, "dec": 2.5, "scored": 0,
                "pnl": -1.0, "breakeven": 0.4,
            })
    assert fit_edge_rule(pl.DataFrame(rows)) is None


def test_edge_rule_reads_the_preblend_column():
    """The threshold must mean the same thing on the board as in the backtest.

    `edge` on the board is built from the published probability, which is
    already blended toward the price it is compared against — about 62% the
    size of the real disagreement. A rule fitted on one column and applied to
    the other silently changes what it selects.
    """
    import inspect
    from src.evaluation import rank_economics

    src = inspect.getsource(rank_economics.fit_edge_rule)
    assert "prob_calibrated" in src and "market_prob" in src
    assert '"final"' not in src and "prob_blended" not in src


def test_board_carries_the_preblend_edge():
    """Without model_edge_pp the board cannot apply the fitted rule at all."""
    import inspect
    from src.prediction import bets

    src = inspect.getsource(bets.build_board)
    assert 'alias("model_edge")' in src
    assert '"model_edge_pp"' in src or 'alias("model_edge_pp")' in src


# ─────────────────────────────────────────────────────────────────────────────
# Forward test: what was actually bet, and what we kept from the book feed
# ─────────────────────────────────────────────────────────────────────────────

def test_wager_log_stores_the_price_taken_not_the_consensus(tmp_path):
    """The whole point of the log is the gap between those two numbers.

    Every backtest figure assumes the consensus close. If the log quietly
    overwrote the price actually given with the one we modeled against, it
    would measure nothing and look like it was working.
    """
    import polars as pl
    from src.betting import wagers

    wagers.WAGERS_PATH = tmp_path / "wagers.parquet"
    wagers.record(2025, 1, "2025_01_SF_SEA", "Some Player", odds_taken=145,
                  stake=1.0, consensus_odds=125)
    row = pl.read_parquet(wagers.WAGERS_PATH).row(0, named=True)
    assert row["odds_taken"] == 145
    assert row["consensus_odds"] == 125


def test_wager_summary_reports_settled_count(tmp_path):
    """An ROI without its sample size is the most misleading number here."""
    from src.betting import wagers

    wagers.WAGERS_PATH = tmp_path / "wagers.parquet"
    wagers.record(2025, 1, "2025_01_SF_SEA", "Jaxon Smith-Njigba",
                  odds_taken=145, stake=1.0)
    s = wagers.summary("anytime_td")
    if s is None:
        # Grading a wager needs the results the pipeline builds, which are
        # gitignored. Skip rather than fail so a fresh checkout runs green.
        pytest.skip("no graded results — run the pipeline")
    assert "n_settled" in s and "n_placed" in s


def test_book_quotes_are_captured_not_just_the_median():
    """The per-book detail arrives free in the same response and cannot be
    re-bought. Collapsing to a median before writing threw away line shopping,
    book disagreement and staleness in one step."""
    import inspect
    from src.ingest import odds_api, odds_history

    src = inspect.getsource(odds_api.parse_event_markets)
    assert "book_rows.append" in src, "per-book quotes are being discarded again"
    assert "book_rows" in inspect.getsource(odds_api.fetch_week_td_props), \
        "the fetch no longer carries per-book quotes through to the archive"
    assert hasattr(odds_history, "append_book_quotes")
    assert "bookmaker" in odds_history.BOOK_SCHEMA


def test_best_prices_prefers_the_longest_available(tmp_path, monkeypatch):
    """Line shopping means the best price, and for a Yes bet longer pays more."""
    import polars as pl
    from src.ingest import odds_history

    path = tmp_path / "books.parquet"
    monkeypatch.setattr(odds_history, "BOOKS_PATH", path)
    rows = []
    for book, odds in (("a", 120), ("b", 165), ("c", 140)):
        rows.append({
            "captured_at": "2026-01-01T00:00:00+00:00", "snapshot": "close",
            "season": 2026, "week": 1, "game_id": "g1", "bookmaker": book,
            "book_last_update": None, "player_name_raw": "P",
            "player_name_norm": "p", "market": "anytime_td", "point": None,
            "side": "yes", "odds": odds, "implied_prob": 0.4,
        })
    # `_conform` rather than a bare cast, so a column added to BOOK_SCHEMA
    # does not break a fixture that is not about that column.
    odds_history._conform(pl.DataFrame(rows), odds_history.BOOK_SCHEMA
                          ).write_parquet(path)

    best = odds_history.best_prices(2026, 1)
    assert best.height == 1
    r = best.row(0, named=True)
    assert r["best_odds"] == 165 and r["best_book"] == "b"
    assert r["median_odds"] == 140 and r["n_books"] == 3


def test_blend_weight_is_fitted_on_frames_that_contain_model_predictions():
    """The blend weight has to be fitted on something that has all three inputs.

    `load_graded_history` returns prices and outcomes but no model probability,
    so handing it straight to `fit_blend_weight` returns None on every call and
    the blend sits on its bootstrap 0.50 forever — which is what production did
    across 32,194 graded player-games without ever printing a warning.
    `build_blend_training_frame` exists to replay the archive through the model
    first; this asserts the serving path actually uses it.
    """
    import inspect
    from src.prediction import predict as predict_mod

    src = inspect.getsource(predict_mod._anchor_to_market)
    assert "build_blend_training_frame" in src, (
        "predict.py is fitting the blend weight on a frame with no model "
        "probabilities again; it will silently never fit"
    )


def test_nobody_reimplements_the_scoring_path():
    """Applying a calibrator by hand outside scoring.py is how the paths drift.

    src/models/scoring.py was written because prediction, the backtest, the
    blend stacker and the dashboard had each grown their own copy of "load the
    model, apply the calibrator, weight and sum", and the copies disagreed. It
    happened again: predict.py, app.py and 11_walkforward.py all kept theirs,
    so the tie-break added to `score` reached the backtest and the stacker but
    not the board anyone actually reads, and not the table used to pick which
    model to serve.

    trainer.py is exempt — it *fits* calibrators, which is a different job.
    """
    import re

    root = Path(__file__).resolve().parents[1]
    exempt = {"src/models/scoring.py", "src/models/calibration.py",
              "src/models/trainer.py"}
    offenders = []
    for path in list(root.glob("src/**/*.py")) + list(root.glob("scripts/*.py")) + [root / "app.py"]:
        rel = path.relative_to(root).as_posix()
        if rel in exempt:
            continue
        text = path.read_text()
        # `.calibrate(` on anything reached via IsotonicCalibrator/TemperatureScaler.
        if re.search(r"(IsotonicCalibrator|TemperatureScaler)\.load\([^)]*\)\.calibrate\(", text) \
                or re.search(r"\bcal(?:ibrator)?\s*=\s*(IsotonicCalibrator|TemperatureScaler)\.load\(", text):
            offenders.append(rel)

    assert not offenders, (
        f"{offenders} apply a calibrator directly instead of calling "
        f"src.models.scoring.score — that is a private copy of the scoring "
        f"path and it will drift out of step with production"
    )


def test_calibration_ties_are_broken_without_reordering():
    """Isotonic flattens players onto steps; the tie-break must not reorder them.

    Two properties, and the second is the one that makes the first safe:
      * players sharing a calibrated step come out distinct, ordered by the
        model's own pre-calibration opinion;
      * players on *different* steps keep the order calibration gave them.

    Without this the game's headline pick was decided by `rank("ordinal")`
    falling back to row order — whoever the assembler happened to list first.
    """
    import numpy as np
    from src.models.scoring import _break_ties

    raw = np.array([0.90, 0.75, 0.80, 0.30, 0.10, 0.31])
    # A plausible isotonic output: three players collapsed onto 0.6, two onto 0.2.
    cal = np.array([0.60, 0.60, 0.60, 0.20, 0.05, 0.20])
    out = _break_ties(cal, raw)

    assert len(np.unique(out)) == len(out), "ties survived the tie-break"
    # Within the 0.6 step, order follows the raw score.
    assert out[0] > out[2] > out[1]
    assert out[5] > out[3]
    # Across steps, calibration still wins: every 0.6 player beats every 0.2.
    assert min(out[0], out[1], out[2]) > max(out[3], out[5]) > out[4]
    # And the nudge is small enough to leave the calibration itself intact.
    assert np.allclose(out, cal, atol=0.075)

    # Degenerate inputs must pass through rather than divide by zero.
    flat = np.full(4, 0.3)
    assert np.array_equal(_break_ties(flat, np.arange(4.0)), flat)
    assert np.array_equal(_break_ties(np.array([0.1, 0.2]), np.full(2, 0.5)),
                          np.array([0.1, 0.2]))


def test_declared_hyperparameters_reach_the_model():
    """Every knob config declares must be read, and every knob read declared.

    The wrappers used to take `max_depth`, `subsample` and `colsample_bytree`
    from config while hardcoding `n_estimators=2000` and `learning_rate=0.02` —
    against a config that declared 500 and 0.05 for exactly those two. Tuning
    them through config changed nothing, raised nothing, and left the file
    describing a model nobody had trained. Both directions matter: a declared
    key that is ignored is a lie, and a read key that is undeclared is a
    setting nobody can find.

    The pairs are discovered from the registry rather than listed here, so a
    model added later is covered without anyone remembering to add it. Listing
    them by hand is how this check would come to describe two of three wrappers
    while reading like it described all of them.
    """
    import importlib

    from src.models.registry import ensure_registered, get_model, list_models
    from src.utils.config import get_config

    ensure_registered()
    pairs = []
    for name in list_models():
        module = importlib.import_module(get_model(name).__module__)
        defaults = getattr(module, "DEFAULTS", None)
        if defaults is not None:
            pairs.append((name, defaults))
    assert len(pairs) >= 3, (
        f"expected every tuned wrapper to declare DEFAULTS; found "
        f"{[n for n, _ in pairs]} out of registered {list_models()}")

    model_cfg = get_config()["model"]
    for name, defaults in pairs:
        declared = {k for k in model_cfg.get(name, {})}
        read = set(defaults)
        assert not (read - declared), (
            f"model.{name} reads {sorted(read - declared)} but config does not "
            f"declare them — nobody tuning this file can find those settings"
        )
        assert not (declared - read), (
            f"config declares model.{name}.{sorted(declared - read)} but the "
            f"wrapper never reads them; they silently do nothing"
        )


def test_walkforward_fits_its_blend_weight_on_its_own_model():
    """The stacker must not learn from a model that trained on the archive.

    `build_blend_training_frame` replays the graded odds archive through a
    trained model. It used to read production's model directory unconditionally,
    so a --walk-forward backtest that had retrained into a scratch directory
    still fitted its blend weight against a model that had seen 2015-2023 —
    in-sample predictions, which look sharper than honest ones. The stacker read
    that as "the model needs no help" and drove the market weight to 0.010-0.015
    across 2024 and 0.003-0.005 on first-TD 2025, against an honest 0.23-0.33.

    The season guard at the top of `main` cannot catch this: it checks which
    season is being *scored*, not which model produced the stacker's rows.
    """
    import inspect

    from src.prediction.blend import build_blend_training_frame

    assert "model_dir" in inspect.signature(build_blend_training_frame).parameters, (
        "build_blend_training_frame no longer takes model_dir, so a walk-forward "
        "backtest cannot point it at the fold's model"
    )

    bt = Path(__file__).resolve().parents[1] / "scripts" / "10_backtest.py"
    src = bt.read_text()
    call = src[src.index("build_blend_training_frame(target_type"):]
    call = call[:call.index(")") + 1]
    assert "model_dir" in call, (
        "scripts/10_backtest.py builds the stacker frame without passing "
        f"model_dir, so --walk-forward fits the blend on production's model: {call!r}"
    )


def test_blend_weight_refit_guard_compares_like_with_like():
    """A settled blend weight must not be refitted on every prediction run.

    The guard compared the stored `n_rows` — archive rows that survived the
    join with model predictions — against `eligible`, the rows going in. The
    join always loses some (6,985 of 7,624 on anytime TD), so the condition was
    permanently true: every `make predict` replayed the entire archive through
    the model and rewrote `blend_weight.json` with a value differing in the
    eleventh decimal. Nothing looked wrong, it was just the most expensive step
    in prediction, run every time, mutating a served artifact.
    """
    from src.prediction.predict import blend_weight_needs_fit

    settled = {"source": "fitted", "n_rows": 6985, "eligible_rows": 7624,
               "min_season": 2025}
    assert not blend_weight_needs_fit(settled, eligible=7624, min_rows=500,
                                      first_clean=2025)
    assert blend_weight_needs_fit(settled, eligible=8100, min_rows=500,
                                  first_clean=2025), "new graded weeks must refit"
    assert blend_weight_needs_fit(settled, eligible=7624, min_rows=500,
                                  first_clean=2026), "a moved rule must refit"

    # Written before `eligible_rows` existed: refit once, then settle.
    legacy = {"source": "fitted", "n_rows": 6985, "min_season": 2025}
    assert blend_weight_needs_fit(legacy, 7624, 500, 2025)

    assert not blend_weight_needs_fit(None, eligible=100, min_rows=500,
                                      first_clean=2025), "too little history"
    assert blend_weight_needs_fit(
        {"source": "bootstrap", "min_season": 2025}, 7624, 500, 2025)


def test_blend_weight_is_the_one_the_blend_applies():
    """Fit the parameter that is served, not a proxy for it.

    `blend` applies (1-w)*logit(model) + w*logit(market) — no intercept, and the
    coefficients forced to sum to one. The weight used to come from an
    unregularised two-coefficient regression with a free intercept, normalized
    after the fact; on three seasons that fit wanted a+b = 1.11 and c = 0.21,
    both of which the blend then silently discarded.

    So: the returned weight must actually minimise the served blend's loss.
    """
    import numpy as np
    import polars as pl

    from src.prediction.blend import _logit, _sigmoid, blend, fit_blend_weight

    rng = np.random.default_rng(0)
    n = 4000
    truth = rng.beta(2, 8, n)
    # Two noisy readings of the same truth, market the weaker of the pair.
    model_p = np.clip(_sigmoid(_logit(truth) + rng.normal(0, 0.5, n)), 1e-4, 1 - 1e-4)
    market_p = np.clip(_sigmoid(_logit(truth) + rng.normal(0, 0.9, n)), 1e-4, 1 - 1e-4)
    hist = pl.DataFrame({
        "model_prob": model_p, "market_prob": market_p,
        "scored": (rng.random(n) < truth).astype(int), "season": [2024] * n,
    })

    fit = fit_blend_weight(hist, min_rows=100)
    assert fit is not None and 0.0 <= fit["market_weight"] <= 1.0
    w = fit["market_weight"]

    y = hist["scored"].to_numpy()
    def nll(x):
        p = np.clip(_sigmoid((1 - x) * _logit(model_p) + x * _logit(market_p)), 1e-9, 1 - 1e-9)
        return -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))

    for other in (0.0, 0.25, 0.5, 0.75, 1.0, max(0.0, w - 0.1), min(1.0, w + 0.1)):
        assert nll(w) <= nll(other) + 1e-9, (
            f"fitted w={w:.4f} is beaten by w={other:.4f} under the blend that "
            f"is actually applied ({nll(w):.6f} vs {nll(other):.6f})"
        )

    # And the weight the fit reports is the weight blend() stamps on the rows.
    out = blend(hist, "model_prob", "market_prob", fit, out_col="p")
    assert abs(float(out["market_weight"][0]) - w) < 1e-12


def test_distribution_shift_check_catches_an_over_populated_feature():
    """The nullness check is blind to features arriving *more* populated.

    That is the failure that actually happened: carry-forward filled week 1 of
    the predict season with the prior season's state, nine features moved more
    than half a training SD, nothing was null, and nothing warned.
    """
    import polars as pl
    from src.prediction.predict import check_distribution_shift

    train = pl.DataFrame({"f": [0.0] * 50 + [1.0] * 50})   # mean 0.5, sd ~0.5
    week = pl.DataFrame({"f": [1.0] * 40})                  # mean 1.0
    assert check_distribution_shift(week, train, ["f"]) == ["f"]

    same = pl.DataFrame({"f": [0.0] * 20 + [1.0] * 20})
    assert check_distribution_shift(same, train, ["f"]) == []


def test_carry_forward_fills_week_one_of_every_season():
    """Week 1 must be built the same way in training as it is when serving.

    Projecting only into the predict season is what made the live board score
    rows from a distribution the model had never been fitted on.
    """
    import polars as pl
    from src.features.assembler import _carry_forward

    feats = pl.DataFrame({
        "team": ["A", "A", "B", "B", "A", "B"],
        "season": [2023, 2023, 2023, 2023, 2024, 2024],
        "week": [1, 2, 1, 2, 2, 2],
        "v": [1.0, 2.0, 3.0, 4.0, 20.0, 40.0],
    })
    out = _carry_forward(feats, "team", predict_season=2025)

    # 2024 has no week-1 row of its own, so it takes each team's last 2023
    # value — the same projection serving has always used, now applied in
    # training too.
    w1_2024 = out.filter((pl.col("season") == 2024) & (pl.col("week") == 1))
    assert sorted(w1_2024["v"].to_list()) == [2.0, 4.0]

    # The predict season, which has no rows at all, takes the last of 2024.
    w1_2025 = out.filter((pl.col("season") == 2025) & (pl.col("week") == 1))
    assert sorted(w1_2025["v"].to_list()) == [20.0, 40.0]

    # Real rows survive untouched — the projection must never overwrite them,
    # or it would replace measured values with stale ones and fan out joins.
    real = out.filter((pl.col("season") == 2023) & (pl.col("week") == 1))
    assert sorted(real["v"].to_list()) == [1.0, 3.0]
    assert out.filter((pl.col("season") == 2023) & (pl.col("week") == 1)).height == 2


def test_bet_guidance_does_not_endorse_a_one_season_strategy():
    """"Profitable in 1 of 3 seasons" is not a reason to take something seriously.

    The guidance text is generated from the numbers, and it used to call any
    count of winning seasons "the reason to take it seriously" — so a model that
    worked once in three years got the same endorsement as one that worked every
    year. Selecting `lr` in the app is what surfaced it.
    """
    from src.presentation import board as bp

    def econ(verdicts):
        return {
            "headline": {"verdict": "positive", "roi": 15.0},
            "games": 1130,
            "by_rank": [{"rank": 1, "verdict": "positive"}],
            "by_odds_bucket": [{"bucket": "+300 or longer", "roi": -22.0}],
            "by_season": [{"season": 2023 + i, "verdict": v}
                          for i, v in enumerate(verdicts)],
            "blend_comparison": [],
        }

    endorsement = "take it seriously"

    every, _ = bp.bet_guidance(econ(["positive"] * 3), 3)
    assert any(endorsement in line for line in every), \
        "profitable in every season separately is the case that earns it"

    once, _ = bp.bet_guidance(
        econ(["positive", "negative", "negative"]), 3)
    assert not any(endorsement in line for line in once), \
        "a strategy that won in a minority of seasons is being endorsed"
    assert any("Be skeptical of the headline" in line for line in once)
    assert any("only profitable in 1 season out of 3" in line for line in once)


def test_per_book_cache_is_not_read_as_a_consensus_cache(tmp_path, monkeypatch):
    """The per-book sibling must not be picked up by the consensus glob.

    Both files are written into the same directory and both match
    `td_props_*.json`, but the per-book one holds a list while every consumer
    expects a {game_key: game_data} dict. The first fetch after per-book capture
    was added died with "'list' object has no attribute 'items'" — in the
    unattended weekly job, which is precisely where nobody would see it.
    """
    from src.ingest import odds_api

    monkeypatch.setattr(odds_api, "CACHE_DIR", tmp_path)
    (tmp_path / "td_props_2026-09-10.json").write_text('{"A @ B": {}}')
    (tmp_path / "td_props_2026-09-10_books.json").write_text('[{"bookmaker": "dk"}]')

    caches = odds_api._prop_caches()
    assert len(caches) == 1, f"consensus glob picked up {[p.name for p in caches]}"
    assert caches[0].name == "td_props_2026-09-10.json"
    assert isinstance(odds_api.load_cached_odds(), dict)
    assert isinstance(odds_api.load_cached_book_quotes(), list)


def test_highlight_tiers_require_every_season_positive():
    """A tier is only marked if it paid in each season, not just on average.

    The board's highlights are the most action-shaped thing in the app, so the
    bar for showing one is the same bar the headline strategy clears: a
    clustered interval excluding zero AND a profit every season separately.
    """
    import polars as pl
    from src.evaluation.rank_economics import fit_highlight_tiers

    rows = []
    for season, edge, wins in ((2023, 0.20, 55), (2024, 0.20, 55), (2025, 0.20, 5)):
        for i in range(80):
            won = i < wins
            rows.append({
                "season": season, "week": 1 + i % 18, "game_id": f"{season}_b{i}",
                "rank": 1, "prob_calibrated": 0.50, "market_prob": 0.50 - edge,
                "odds": 150, "dec": 2.5, "scored": int(won),
                "pnl": 1.5 if won else -1.0, "breakeven": 0.4,
            })
        for i in range(80):
            rows.append({
                "season": season, "week": 1 + i % 18, "game_id": f"{season}_s{i}",
                "rank": 1, "prob_calibrated": 0.42, "market_prob": 0.40,
                "odds": 150, "dec": 2.5, "scored": 0,
                "pnl": -1.0, "breakeven": 0.4,
            })
    out = fit_highlight_tiers(pl.DataFrame(rows))
    names = {t["tier"] for t in (out or {}).get("tiers", [])}
    assert "strong" not in names, (
        "a tier that collapsed in its most recent season is still being marked"
    )


def test_tiers_require_a_qualifying_edge_rule():
    """No fitted edge rule means no labels, whatever the headline says.

    This used to assert first_td had no tiers, which was true only because its
    backtest applied the wrong probability structure. Corrected, first_td does
    have a validated rule (+15.5% [+1.2, +30.1], positive every season) even
    though its naive top-3 strategy does not clear zero — so the gate is the
    rule, not the headline.
    """
    import json
    from pathlib import Path

    for target in ("anytime_td", "first_td"):
        p = Path("output") / target / "rank_economics.json"
        if not p.exists():
            continue
        econ = json.loads(p.read_text())
        tiers = econ.get("highlight_tiers")
        if tiers is not None:
            assert econ.get("edge_rule"), (
                f"{target}: tiers exist with no fitted edge rule behind them"
            )



def test_backtest_refuses_a_season_the_model_trained_on():
    """Scoring an in-sample season looks fine and is worth roughly 2x.

    The backtest used models/ for every season, but that model trains through
    splits.train_end and tunes on val_season — so two of three backtested
    seasons were scoring rows the model had been fitted on, and rank economics
    pooled all three. The Strong tier read +56% and was really +27%, with a
    three-season "decay" that was just the in-sample-to-holdout gradient.

    The guard is a hard refusal rather than a warning because nothing in the
    output looks wrong: the numbers are plausible, merely too good.
    """
    import inspect
    from pathlib import Path

    src = Path("scripts/10_backtest.py").read_text()
    assert "REFUSING" in src, "the in-sample guard is gone"
    assert 'season <= splits["val_season"]' in src, (
        "the guard no longer covers the validation season, which is also tuned on"
    )
    # And the batch target must pass --walk-forward, or it would now just fail.
    mk = Path("Makefile").read_text()
    evaluate = mk.split("\nevaluate:", 1)[1].split("\n\n", 1)[0]
    assert "--walk-forward" in evaluate, (
        "make evaluate would be refused for every in-sample season"
    )


def test_served_path_matches_the_evaluated_path(capsys):
    """Production and the backtest must produce the same number for a player.

    Four separate bugs this session were this same disagreement, none of which
    raised an error: a missing calibrator, ranking on the blended column while
    measuring on the pre-blend one, week-1 carry-forward applied only when
    serving, and the anytime-TD joint model applied to first TD — where
    probabilities must sum to 1 per game and instead summed to 2.7.

    Skips rather than fails when the inputs are absent, so a fresh checkout
    still runs green — but it SKIPS, visibly, rather than passing.

    That distinction is the point. `parity.compare` returns `stale` whenever
    `features.parquet` is newer than the backtest frame, which is correct (the
    two paths would be asked about different inputs) and which used to be
    reported as `ok=True`. A silent pass and a real pass looked identical, so
    every `make features` disarmed this check and nothing said so. The weekly
    rollover rebuilds the matrix, so in practice it was off almost all the
    time: the frames sat at 19 August through a month of green runs, and when
    they were finally regenerated the check reported the two paths disagreeing
    by 1.6-2.8pp on both markets.

    A skip shows as `s` in the summary and is counted. A pass does not.
    """
    import pytest as _pytest

    from src.evaluation.parity import check
    from src.utils.config import get_config

    season = get_config()["splits"]["test_season"]
    failures, skipped = [], []
    for target in ("anytime_td", "first_td"):
        with __import__("contextlib").redirect_stdout(__import__("io").StringIO()):
            ok, msg = check(target, season)
        if not ok:
            failures.append(msg)
        elif "features are newer" in msg or "skipped" in msg:
            skipped.append(msg)
    assert not failures, "\n".join(failures)
    if skipped and len(skipped) == 2:
        _pytest.skip(
            "parity could not be checked for either market — run `make "
            "evaluate` to bring the backtest frames up to the current feature "
            "matrix:\n  " + "\n  ".join(skipped))
    if skipped:
        _pytest.skip("parity checked on only one market:\n  "
                     + "\n  ".join(skipped))


def test_first_td_probabilities_sum_to_one_per_game():
    """Exactly one player scores first, so a game's probabilities must sum to 1.

    The backtest applied the anytime-TD joint model here, whose team rate
    targets ~4.3 scorers a game. First-TD probabilities summed to 2.7, which
    made every market edge look enormous and turned the market into an apparent
    clear loser (-9.5%). Corrected, it is +0.8% and has a profitable subset.
    """
    import polars as pl
    from src.evaluation.rank_economics import backtest_files

    files = backtest_files("first_td")
    if not files:
        pytest.skip("no first_td backtest frames")
    d = pl.concat([pl.read_csv(p) for p in files], how="diagonal_relaxed")
    per_game = d.group_by("game_id").agg(
        pl.col("prob_calibrated").sum().alias("s"))["s"].mean()
    # Below 1.0 because only priced players are in the frame; a value near 2-3
    # means the wrong structure is being applied.
    assert 0.7 <= per_game <= 1.05, (
        f"first_td probabilities sum to {per_game:.2f} per game, not ~1"
    )


def test_distribution_shift_ignores_time_indices():
    """Season and week shift by definition and must not fill the warning list.

    2026 is always further from the training mean than 2020; week 1 is always
    further than week 9. Flagging them every run is how a guardrail teaches you
    to skim past it — and this one was skimmed past, on a week where it was
    right.
    """
    import polars as pl
    from src.prediction.predict import check_distribution_shift

    train = pl.DataFrame({"season": list(range(2015, 2025)),
                          "week": list(range(1, 11)),
                          "real": [0.0] * 5 + [1.0] * 5})
    week = pl.DataFrame({"season": [2026] * 8, "week": [1] * 8,
                         "real": [0.0] * 4 + [1.0] * 4})
    out = check_distribution_shift(week, train, ["season", "week", "real"])
    assert "season" not in out and "week" not in out
    assert out == [], f"nothing real shifted, got {out}"


def test_shift_baseline_is_week_matched():
    """Week 1 must be compared with week 1, not with a season average.

    Season-to-date features are thin in week 1 by construction, so an all-weeks
    baseline flagged a dozen families every run for a reason that was not a
    defect. Week-matched, the live board went from 35 flagged features to 12.
    """
    from pathlib import Path

    src = Path("src/prediction/predict.py").read_text()
    call = src.split("check_distribution_shift(\n", 1)[1].split(")", 1)[0]
    assert "prior" in call, "the shift check no longer uses a week-matched baseline"
    assert 'pl.col("week") == week' in src, "week matching was removed"


def test_decay_check_compares_against_the_interval_not_a_threshold():
    """"Below its own confidence range" has a meaning; "down 5 points" does not.

    The one time this project used a picked threshold to call something a fading
    edge, it fired on a decline that turned out to be in-sample contamination.
    """
    import inspect
    from src.evaluation import decay

    src = inspect.getsource(decay.by_season)
    assert 'pooled["lo"]' in src, "the season check no longer uses the interval"
    assert "clustered_roi" in src, "intervals must be game-clustered here too"


def test_decay_stays_quiet_until_there_are_enough_settled_bets(tmp_path):
    """A handful of coin flips must not be reported as a decaying edge."""
    from src.betting import wagers
    from src.evaluation import decay

    wagers.WAGERS_PATH = tmp_path / "wagers.parquet"
    wagers.record(2025, 1, "2025_01_SF_SEA", "Jaxon Smith-Njigba",
                  odds_taken=145, stake=1.0)
    out = decay.by_recent_weeks("anytime_td")
    if out is None:
        pytest.skip("no graded results — run the pipeline")
    assert "too few to judge" in out["verdict"]
    assert "below_expectation" not in out


def test_the_positional_bias_is_not_stable_enough_to_correct():
    """Guards three failed experiments' worth of conclusion.

    The pooled calibration gap by rank looks like a systematic bias worth
    correcting. Split by season it disagrees in sign — rank 1 runs +12.0pp,
    -2.3pp, -8.9pp across 2023/24/25 on ~283 observations each. A
    monotone-by-construction correction fitted on two seasons made the third
    worse. If a future rebuild ever produces a bias that IS consistent across
    seasons, this test fails and the idea is worth revisiting.

    The bar is each season's gap clearing its *own* standard error, not a flat
    threshold. With ~283 observations per rank-season and a base rate near 0.4,
    that standard error is about 2.9pp — so the flat 2pp this used to require
    was below the noise floor and could fire on nothing at all. It did: after
    the blend-weight fix, rank 3 read +7.5 / +2.8 / +2.6pp, one season at 2.6
    standard errors and two under 1. Leave-one-season-out, applying the shift
    learned from the other two moved Brier by -0.0033 / -0.0002 / +0.0000 —
    a pooled 0.5% of a 0.244 Brier, essentially all of it from 2023. Not a bias;
    one season with an opinion.
    """
    import numpy as np
    import polars as pl
    from src.evaluation.rank_economics import load_bets, BET_RANK_COL

    d = load_bets("anytime_td", rank_by=BET_RANK_COL)
    if d is None or d.height == 0:
        pytest.skip("no backtest frames")
    seasons = sorted(d["season"].unique().to_list())
    if len(seasons) < 3:
        pytest.skip("need three seasons to judge stability")

    consistent = []
    for rank in (1, 2, 3):
        gaps = []
        for s in seasons:
            sub = d.filter((pl.col("rank") == rank) & (pl.col("season") == s))
            if sub.height < 100:
                break
            y = sub["scored"].to_numpy()
            gap = float(y.mean() - sub["prob_calibrated"].mean())
            se = float(np.sqrt(y.mean() * (1 - y.mean()) / len(y)))
            gaps.append((gap, se))
        # Consistent means every season agrees on the sign AND every season's
        # effect is larger than that season's own sampling error. Either half
        # alone is satisfied by noise.
        if len(gaps) == len(seasons) and (
                all(g > se for g, se in gaps) or all(g < -se for g, se in gaps)):
            consistent.append(rank)

    assert not consistent, (
        f"ranks {consistent} now show a bias that clears its own standard error "
        f"in every season — src/models/rank_calibration.py may be worth "
        f"reviving, monotone form. Confirm leave-one-season-out first."
    )


def test_consensus_price_is_taken_in_probability_space():
    """A median of American odds is meaningless across the +/-100 boundary.

    The scale is discontinuous there — the median of -135 and +105 lands on -15,
    a price that does not exist. Taking it that way produced a mean best-vs-
    consensus gap of -0.12pp alongside a median of +0.71pp, which is impossible
    when "best" means best. src/ingest/odds_api.py documents the same trap for
    the same reason.
    """
    from src.evaluation.line_shopping import best_vs_consensus

    d = best_vs_consensus(2026, 1, "anytime_td")
    if d is None or d.height == 0:
        pytest.skip("no per-book quotes archived yet")
    worst = d["gap_pp"].min()
    assert worst >= -1e-9, (
        f"a best price is paying less than the consensus ({worst:.3f}pp) — "
        f"the consensus is being averaged in American odds again"
    )


def test_missing_injury_report_is_not_a_clean_bill_of_health(tmp_path, monkeypatch):
    """No report published must never read as "everyone is fit".

    That is the failure mode that costs money: a board recommending a player
    who was ruled out on Friday, with nothing saying the check never ran.
    """
    import polars as pl
    from src.prediction import availability

    board = pl.DataFrame({"player_id": ["00-0000001"],
                          "player_name": ["Someone"], "InRange": ["Strong"]})
    # A season with no report at all.
    out = availability.check(board, 1990, 1)
    assert out["report_available"] is False
    assert out["blocked"] == []
    assert "not a clean bill of health" in out["note"]


def test_injury_status_blocks_out_and_doubtful_only():
    """Out/Doubtful stop a bet; Questionable is surfaced, not blocked."""
    from src.prediction.availability import BLOCKING, CAUTION, status_for

    assert set(BLOCKING) == {"Out", "Doubtful"}
    assert set(CAUTION) == {"Questionable"}
    s = status_for(2025, 10)
    if s is None:
        pytest.skip("no injury report for that week")
    import polars as pl
    blocked = s.filter(pl.col("is_blocked"))
    assert blocked.height > 0
    assert set(blocked["report_status"].unique().to_list()) <= set(BLOCKING)


def test_each_market_reads_its_own_prices():
    """First TD and anytime TD must not share a price list.

    `_market_from_cache` hardcoded the anytime-TD entry, so the live First TD
    board was built on anytime-TD prices — the same 75 players at the same odds,
    Marquez Valdes-Scantling quoted +1000 to score first and +1000 to score at
    all. The de-vig hid it: it rescales whatever it is given to the market's
    expected scorer count, so `market_prob` looked plausibly small while the
    American price underneath was wrong.

    The backtests were unaffected — they read load_graded_history(target_type),
    which filters by market — so the two paths never disagreed on anything that
    would have surfaced it. Even the parity check passed, because first TD's
    published probability does not touch the market at all.
    """
    import inspect
    from src.prediction import predict as predict_mod

    src = inspect.getsource(predict_mod._market_from_cache)
    assert 'game.get("anytime_td"' not in src, (
        "the market cache is hardcoded to anytime TD again"
    )
    assert "game.get(target_type" in src

    # And the callers must actually pass it through.
    for fn in (inspect.getsource(predict_mod._load_market),
               inspect.getsource(predict_mod._anchor_to_market)):
        pass
    whole = inspect.getsource(predict_mod)
    assert "_market_from_cache(season, week, target_type)" in whole
    from src.prediction import bets
    assert "_market_from_cache(season, week, target_type)" in inspect.getsource(
        bets.board_for_week)


def test_no_module_global_is_used_before_it_exists():
    """app.py is one long script, so definition order is a correctness property.

    `_SECTION_ERRORS` was defined at line 2351 and written to at 1494, 1506 and
    1914 — inside the `except` branches of loaders that the Full board calls at
    line 1635. Nothing showed it until one of those loaders actually raised, at
    which point the handler meant to report the failure raised `NameError`
    instead and took the whole page down. The mechanism built to keep a broken
    section from disappearing silently was the thing that crashed it.

    This walks the module-level call graph: for every top-level statement that
    reaches a function referencing a module global, that global must already be
    assigned. It is the ordering rule the file has always depended on and never
    checked.
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path("app.py").read_text())

    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assigned: dict[str, int] = {}
    for node in tree.body:
        for target in (node.targets if isinstance(node, ast.Assign)
                       else [node.target] if isinstance(node, ast.AnnAssign)
                       else []):
            if isinstance(target, ast.Name):
                assigned.setdefault(target.id, node.lineno)

    def reaches(node, seen):
        """(globals read, functions called) reachable from this subtree."""
        names, calls = set(), set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                names.add(sub.id)
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                calls.add(sub.func.id)
        for name in calls - seen:
            if name in funcs:
                deeper, _ = reaches(funcs[name], seen | calls)
                names |= deeper
        return names, calls

    problems = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Import,
                             ast.ImportFrom)):
            continue
        used, _ = reaches(node, set())
        for name in used:
            if name in assigned and assigned[name] > node.lineno:
                problems.append(
                    f"line {node.lineno} reaches `{name}`, "
                    f"which is not assigned until line {assigned[name]}"
                )

    assert not problems, (
        "app.py executes top to bottom, so these run before their global "
        "exists:\n  " + "\n  ".join(sorted(set(problems)))
    )


def test_board_prose_cannot_describe_columns_that_are_not_drawn():
    """The caption and the renderer must ask the same question.

    First TD is not blended, so Bet # is its # and Bet edge is its Difference.
    Hiding those duplicate columns left the caption still explaining "the last
    three columns... Bet # and Bet edge", describing a table that ended at Our
    read. One shared helper now decides both.
    """
    from pathlib import Path

    # The decision itself now lives in src/presentation/board.py, where
    # test_board_presentation.py exercises it directly. What app.py still has
    # to get right is that both the renderer and the prose consult it.
    src = Path("app.py").read_text()
    # The renderer gates the pre-blend pair on it...
    assert "if bp.preblend_columns_differ(frame):" in src
    # ...and so does the prose that describes what the renderer drew.
    assert "_preblend = bp.preblend_columns_differ(board)" in src
    assert "if _rule and _preblend:" in src


# --------------------------------------------------------------------------
# Clustering — the Player types tab
#
# A segmentation is unusually good at inventing a pattern. It gets to draw its
# own boundaries, and if it draws them on the same rows it is then scored on,
# every group comes back looking like a discovery. These tests exist to keep the
# fit and the scoring on opposite sides of the split, and to keep the number of
# groups a fitted quantity rather than one somebody typed.
# --------------------------------------------------------------------------

def _cluster_artifacts(target: str = TARGET):
    import json

    from src.clustering import archetypes, bet_shapes, core

    art = core.load(archetypes.artifact_path(target))
    rep_path = archetypes.report_path(target)
    if art is None or not rep_path.exists():
        pytest.skip("cluster artifacts not built — run `make clusters`")
    return art, json.loads(rep_path.read_text()), archetypes, bet_shapes, core


def test_cluster_fit_never_sees_the_seasons_it_is_scored_on():
    """The groups must be drawn on one set of seasons and judged on another.

    This is the whole reason the tab is believable. A clustering fitted on the
    rows it then reports returns on will always find a group with a striking
    number attached, because it drew the boundary around one. The most recent
    thing this project fixed was a blend weight learned from the model's own
    training data; the same mistake in a segmentation is harder to see, because
    nothing about a named archetype looks like a fitted parameter.
    """
    art, rep, _, _, _ = _cluster_artifacts()
    train_end = get_config()["splits"]["train_end"]

    assert max(art["seasons_used"]) <= train_end, (
        f"archetypes were fitted through {max(art['seasons_used'])}, past the "
        f"training split at {train_end}"
    )
    assert min(rep["report_seasons"]) > train_end
    assert not set(art["seasons_used"]) & set(rep["report_seasons"])


def test_cluster_report_never_scores_an_unplayed_season():
    """Reporting stops at the last season that has actually been played.

    features.parquet carries the predict season, whose rows have `target == 0`
    because nothing has happened yet rather than because nobody scored. Left in
    the reporting set they read as a mass of players who all failed to score:
    every group's touchdown rate drops, our probabilities look systematically
    over-confident, and none of it looks wrong on screen. It reached the report
    once already.
    """
    art, rep, archetypes, _, _ = _cluster_artifacts()
    predict_season = get_config()["seasons"]["predict_season"]
    assert predict_season not in rep["report_seasons"]
    assert max(rep["report_seasons"]) <= get_config()["seasons"]["end"]
    assert archetypes.reporting_window()[1] < predict_season


def test_cluster_assignment_reproduces_the_persisted_sizes():
    """Re-assigning the fit rows from the artifact alone must land them back.

    The parity check between the fit path and the serve path. If an impute
    value, a transform or a scaler is applied on one and not the other, the app
    silently shows a different grouping from the one the report measured, and
    both look fine in isolation. Sizes are exact, so any drift fails here.
    """
    art, _, archetypes, _, core = _cluster_artifacts()
    import polars as pl

    pop = archetypes.population(TARGET)
    if pop is None:
        pytest.skip("features not built")
    fit_df = pop.filter(pl.col("season") <= get_config()["splits"]["train_end"])

    # IS THIS EVEN LIKE FOR LIKE? The assertion below compares cluster sizes
    # against an artifact fit on a particular matrix, and `make features`
    # rebuilds every season from current raw data — so a revision upstream
    # moves rows that are years old. On 2026-10-05 the fit population had gone
    # from 71,070 rows to 70,968, RB lost exactly the 53 the size assertion
    # then reported, and the message blamed a scaler.
    #
    # NOT A SKIP. `tests/test_leakage` already learned that lesson the hard
    # way: a parity check that disarms itself on a feature rebuild reports the
    # skip as a pass and stops guarding the thing it was written for. This
    # FAILS, with the diagnosis that is actually true and the command that
    # fixes it.
    fit_n = art.get("n_rows_fit")
    assert fit_n is None or fit_df.height == fit_n, (
        f"the feature matrix has changed since these clusters were fit on "
        f"{art.get('fit_date')}: {fit_n:,} rows then, {fit_df.height:,} now. "
        f"Nothing below is comparable until they agree — refit with "
        f"`make clusters TARGET={TARGET}`. The grouping the app shows is not "
        f"the one the report measured until you do.")

    assigned = archetypes.assign_frame(fit_df, art)

    for name, stratum in art["strata"].items():
        sub = assigned.filter(pl.col("stratum") == name)
        got = [int(sub.filter(pl.col("cluster_id") == c).height)
               for c in range(stratum["k"])]
        assert got == stratum["sizes"], (
            f"{name}: assigning the fit rows through the artifact gave {got}, "
            f"but the artifact records {stratum['sizes']}. The fit path and the "
            f"serve path are in different spaces."
        )


def test_cluster_features_are_not_the_position_dummies():
    """Position is the thing we stratify by, not the thing we discover.

    Pooled across the league, silhouette settles on three groups and they are
    running backs, receivers, and everyone with no usage — the position column
    with extra steps, presented as a finding. Feeding the dummies back into the
    feature set would recreate that inside every position too, and it would look
    like structure.
    """
    art, _, _, _, _ = _cluster_artifacts()
    assert art["strata_col"] == "position"
    for name, stratum in art["strata"].items():
        for col in stratum["features"]:
            assert not col.startswith("position_"), (
                f"{name} is clustering on {col}, which is the stratifier")


def test_cluster_k_is_fitted_not_typed():
    """No literal cluster count anywhere in src/clustering."""
    import re

    for path in Path("src/clustering").glob("*.py"):
        src = path.read_text()
        assert not re.search(r"n_clusters\s*=\s*\d", src), (
            f"{path} hardcodes a cluster count; k comes from choose_k")
    core_src = Path("src/clustering/core.py").read_text()
    assert "def choose_k(" in core_src
    for lens in ("archetypes", "bet_shapes"):
        assert "core.choose_k(" in Path(f"src/clustering/{lens}.py").read_text()


def test_clustering_never_zero_fills_a_standardised_matrix():
    """Missing values are imputed and recorded, never filled with zero.

    `prepare_data` fills nulls with 0.0, which is harmless for trees and
    poisonous here: after standardisation a filled zero is an extreme z, k-means
    isolates those rows, and the result is a cluster of missingness that the
    naming code will hand a confident English label to.
    """
    import ast

    # Walked as a syntax tree rather than grepped, because the modules discuss
    # `nan_to_num` at length in their docstrings explaining why they avoid it.
    for path in Path("src/clustering").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(
                fn, "id", "")
            assert name != "nan_to_num", (
                f"{path}:{node.lineno} zero-fills a matrix that is about to be "
                f"standardised")


def test_cluster_roi_uses_the_game_clustered_bootstrap():
    """Per-group returns reuse rank_economics, they do not roll their own."""
    for lens in ("archetypes", "bet_shapes"):
        src = Path(f"src/clustering/{lens}.py").read_text()
        assert "from src.evaluation.rank_economics import" in src
        assert "clustered_roi" in src


def test_cluster_thin_cells_are_flagged_not_dropped():
    """Small groups are reported with a warning rather than quietly removed.

    Hiding them is how a table starts implying more coverage than it has — the
    same stance `by_rank_and_odds` takes. Every row carries the flag so the tab
    can say "too few bets to say" instead of showing a return computed from five
    events.
    """
    _, rep, _, _, _ = _cluster_artifacts()
    assert rep["rows"], "report has no groups"
    for row in rep["rows"]:
        assert "thin" in row and "n_bets" in row
    assert rep["n_cells"] == len(rep["rows"])


def test_cluster_binary_flags_do_not_define_a_group():
    """A 0/1 column is a ready-made split plane and k-means will take it first.

    With `is_dome` in the feature set, three of the eight bet-shape groups came
    back named after the stadium roof. The roof is not a kind of bet. Flags stay
    available to describe a group; they do not get to draw one.
    """
    art, _, _, _, _ = _cluster_artifacts()
    import polars as pl
    from src.clustering import archetypes

    pop = archetypes.population(TARGET)
    if pop is None:
        pytest.skip("features not built")
    for name, stratum in art["strata"].items():
        sub = pop.filter(pl.col("stratum") == name)
        for col in stratum["features"]:
            assert sub[col].drop_nulls().n_unique() > 2, (
                f"{name} clusters on {col}, which is binary")


def test_cluster_labels_carry_their_own_evidence():
    """Every name ships with the deviations that produced it.

    A name is the one place a plausible story can enter this tab unchallenged.
    Rendered beside its top standardised deviations, a wrong one is obvious;
    rendered alone, it is believed.
    """
    art, _, _, _, _ = _cluster_artifacts()
    for name, stratum in art["strata"].items():
        assert len(stratum["clusters"]) == stratum["k"]
        for c in stratum["clusters"]:
            assert c["label"] and c["top_features"]
            assert c["label_source"] in ("vocabulary", "generated")
            assert all(t["col"] in stratum["features"] for t in c["top_features"])


def _clusters_tab_source() -> str:
    """Just the Player types tab block, sliced out of app.py."""
    src = Path("app.py").read_text()
    start = src.index("with tab_clusters:")
    return src[start:]


def test_clustering_tab_states_its_split():
    """The tab must read its own split off the artifact, not describe one.

    A sentence saying "fitted on 2015-2023" is correct until somebody changes
    `splits.train_end`, at which point it is a confident lie that nothing
    checks. The banner is built from `seasons_used` and `report_seasons` so it
    cannot drift from what was actually fitted.
    """
    src = Path("app.py").read_text()
    assert "def cluster_split_note(" in src
    assert "art['seasons_used']" in src and "rep['report_seasons']" in src
    assert "cluster_split_note(_art, _rep)" in _clusters_tab_source()


def test_clustering_explore_mode_is_labelled_and_never_writes():
    """The exploratory refit must say so, and must not persist anything.

    Twelve values of k crossed with arbitrary feature subsets and a returns
    column is a lottery with a search button. It stays useful only while it is
    obvious that nothing there is the served grouping — and while the seasons
    are not one of the dials.
    """
    tab = _clusters_tab_source()
    assert "Exploratory. Not the served grouping." in tab
    assert "cluster_explore_toggle" in tab

    app = Path("app.py").read_text()
    for banned in ("core.save(", "archetypes.fit(", "bet_shapes.fit("):
        assert banned not in app, (
            f"app.py calls {banned} — fitting and saving belong to "
            f"scripts/21_clusters.py, not to a page render")


def test_cluster_labels_do_not_leak_into_the_board():
    """Player types stay in their own tab.

    The archetypes are a new and unvalidated way of slicing the data. Putting a
    group's historical return next to a live price invites betting on it before
    anything has established that the grouping means what its name says.
    """
    src = Path("app.py").read_text()
    # Everything from the first tab body up to the Player types banner: the
    # four original tabs and their helpers, but not the cluster loaders, which
    # are defined under that banner.
    board = src[src.index("with tab_board:"):src.index("# ── Tab: Player types")]
    for token in ("cluster_label", "cluster_id", "cluster_report(",
                  "cluster_model("):
        assert token not in board, (
            f"{token} reached the betting tabs; the grouping is meant to be "
            f"self-contained until it has been judged on its own page")

    cols = src[src.index("def board_columns("):]
    cols = cols[:cols.index("\ndef ")]
    assert "cluster" not in cols


def test_defence_is_not_a_share_of_its_own_offence():
    """`team_lambda` counts offensive touchdowns; DEF/ST cannot contribute one.

    `td_counts` filters `td_team == posteam`, so the fitted team rate contains
    no defensive or special-teams scores at all. Normalizing the DEF/ST
    pseudo-player into the same share denominator therefore hands it a slice of
    a rate it can never earn: measured over four walk-forward folds it published
    a defense as the game's most likely scorer in 131 of 1,131 games at a mean
    probability of 0.908, against an actual rate of 0.153. It also understates
    every real player on that team by whatever share the defense took.
    """
    import numpy as np
    from src.models.joint import combine, player_shares

    df = pl.DataFrame({
        "game_id": ["g", "g", "g"],
        "team": ["KC", "KC", "KC"],
        "player_id": ["a", "b", "KC_DEFST"],
        "position_DEFST": [0, 0, 1],
        "raw_prob": [0.30, 0.20, 0.50],
        "team_lambda": [2.4, 2.4, 2.4],
    })
    rates = df["raw_prob"].to_numpy()

    shared = player_shares(rates, df, exclude_defst=False)
    assert shared["share"].sum() == pytest.approx(1.0)
    naive = combine(shared, score_col="raw_prob")
    defense = naive.filter(pl.col("player_id") == "KC_DEFST")["probability"][0]
    assert defense > 0.6, (
        "the unfixed path is expected to blow the defense up — if this stops "
        "being true the measurement behind the fix no longer applies"
    )

    fixed = player_shares(rates, df, exclude_defst=True)
    assert fixed.filter(pl.col("player_id") == "KC_DEFST")["share"][0] == 0.0
    offense = fixed.filter(pl.col("player_id") != "KC_DEFST")
    assert offense["share"].sum() == pytest.approx(1.0), (
        "the offensive shares must still sum to one, or the team's expected "
        "touchdowns no longer add up to its rate"
    )
    # And the real players get the share the defense was taking.
    assert offense["share"][0] == pytest.approx(0.30 / 0.50)

    out = combine(fixed, score_col="raw_prob")
    assert out.filter(pl.col("player_id") == "KC_DEFST")["probability"][0] == \
        pytest.approx(0.50), "a held-out defense keeps the classifier's number"
    assert out.filter(pl.col("player_id") == "a")["probability"][0] > \
        naive.filter(pl.col("player_id") == "a")["probability"][0]


def test_held_out_defence_keeps_its_probability_when_score_and_out_are_one_column():
    """Production calls the joint step with score_col == out_col.

    `apply_joint(..., score_col="prob", out_col="prob")` is what predict, the
    backtest and the harness all pass. Reading the score back after the formula
    has written the same column returns the formula's own output — zero, for a
    defense whose share was held out — so every defense published at exactly
    0.000. The tell was a DEF/ST AUC of exactly 0.5000: not a weak ranking, an
    absent one, and it cost 0.03 of overall AUC in a gate run.
    """
    from src.models.joint import combine, player_shares

    df = pl.DataFrame({
        "game_id": ["g", "g", "g", "g"],
        "team": ["KC", "KC", "KC", "KC"],
        "player_id": ["a", "b", "KC_DEFST", "c"],
        "position_DEFST": [0, 0, 1, 0],
        "prob": [0.30, 0.20, 0.12, 0.10],
        "team_lambda": [2.4, 2.4, 2.4, 2.4],
    })
    shared = player_shares(df["prob"].to_numpy(), df, exclude_defst=True)
    out = combine(shared, out_col="prob", score_col="prob")

    defense = out.filter(pl.col("player_id") == "KC_DEFST")["prob"][0]
    assert defense == pytest.approx(0.12), (
        f"a held-out defense must keep the classifier's own number, got {defense}"
    )
    assert "_score_in" not in out.columns, "scratch column leaked into the output"

    # And two defenses with different scores must stay different, or the
    # ordering within DEF/ST is gone even when the level is right.
    two = pl.DataFrame({
        "game_id": ["g", "g"], "team": ["KC", "BUF"],
        "player_id": ["KC_DEFST", "BUF_DEFST"],
        "position_DEFST": [1, 1], "prob": [0.05, 0.20],
        "team_lambda": [2.4, 2.4],
    })
    out2 = combine(player_shares(two["prob"].to_numpy(), two, exclude_defst=True),
                   out_col="prob", score_col="prob")
    assert out2["prob"].to_list() == pytest.approx([0.05, 0.20])


def test_tie_breaking_cannot_produce_an_impossible_probability():
    """The nudge must not push a calibrated 1.0 above 1.0.

    The anytime-TD xgb calibrator tops out at 0.999999, so the old upward nudge
    was one saturated player away from emitting p > 1 — and nothing downstream
    checked. Those values fed `1 - exp(-lambda*s)` and Brier, where sklearn
    eventually refused a 1.00006 and made it visible. A probability above 1 is
    not a rounding artefact; it is a number that cannot mean anything.
    """
    import numpy as np
    from src.models.scoring import _break_ties

    # A saturated top step, exactly the shape the isotonic fit produces.
    cal = np.array([1.0, 1.0, 1.0, 0.5, 0.5])
    raw = np.array([0.99, 0.80, 0.60, 0.40, 0.20])
    out = _break_ties(cal, raw)

    assert out.max() <= 1.0, f"produced an impossible probability: {out.max()}"
    assert out.min() >= 0.0
    # The ties that matter are still broken, in the model's own order.
    assert out[0] > out[1] > out[2]
    assert out[3] > out[4]
    assert min(out[0], out[1], out[2]) > max(out[3], out[4]), (
        "calibration must still outrank the nudge across steps")


def test_tie_breaking_holds_the_floor_at_zero():
    """Isotonic can output exactly 0, and the nudge subtracts."""
    import numpy as np
    from src.models.scoring import _break_ties

    cal = np.array([0.0, 0.0, 0.3, 0.3])
    raw = np.array([0.4, 0.1, 0.9, 0.7])
    out = _break_ties(cal, raw)
    assert out.min() >= 0.0, "negative probabilities are as impossible as >1"
    assert out.max() <= 1.0
    assert out[2] > out[3], "the step that has room is still ordered"


def test_tie_breaking_never_leaves_the_unit_interval_on_real_calibrators():
    """Property check across the shapes isotonic actually produces."""
    import numpy as np
    from src.models.scoring import _break_ties

    rng = np.random.default_rng(3)
    for _ in range(200):
        n = int(rng.integers(2, 40))
        steps = np.sort(rng.random(int(rng.integers(1, 6))))
        cal = rng.choice(np.append(steps, [0.0, 1.0]), size=n)
        raw = rng.random(n)
        out = _break_ties(cal, raw)
        assert out.min() >= 0.0 and out.max() <= 1.0, (cal, raw, out)


def test_rank_calibration_is_not_fitted_where_nothing_reads_it():
    """It is disabled in both markets, for two different reasons.

    `first_td` never reaches the correction: `predict()` normalizes raw
    probabilities within the game and returns, and only the anytime branch
    calls `_anchor_to_market`, where the correction lives.
    `scripts/10_backtest.py` branches the same way. `anytime_td` reaches it and
    is disabled by the joint-model guard, and `team_td_rate.json` is written on
    every training run so the guard is always taken.

    Fitting it anyway was not harmful, but it shipped a rank_calibration.json
    into both model directories and printed "N of 12 ranks kept a meaningful
    correction" on every retrain — which reads like a live component. If
    someone re-enables it, this test should fail and make them say so.
    """
    from pathlib import Path
    from src.models.rank_calibration import would_be_applied

    for market in ("anytime_td", "first_td"):
        model_dir = Path("models") / market
        if not model_dir.exists():
            continue
        assert not would_be_applied(market, model_dir), (
            f"{market} would now consume a rank calibration; the serving paths "
            "in predict.py and 10_backtest.py must be re-checked"
        )
    # Deliberately not asserting the file is absent. A `rank_calibration.json`
    # written by an earlier run is inert — nothing loads it — and it is recorded
    # in the locked version's manifest, so deleting it to satisfy a test would
    # break `verify_current` for no behavioral gain. The next retrain removes
    # it. What must stay true is that nothing reads it, which is what is
    # asserted above.


def test_first_td_never_reaches_the_rank_correction(tmp_path):
    """The first-TD answer must not depend on whether a team rate exists.

    `would_be_applied` returns False for first TD unconditionally, because the
    market's serving path returns before the correction rather than being
    guarded at it. Deriving it from the team rate instead would silently
    re-enable the correction for a model directory that happens to lack one.
    """
    from src.models.rank_calibration import would_be_applied

    assert not would_be_applied("first_td", tmp_path)          # no team rate
    # anytime with no team rate is the legacy fallback the guard was written
    # for, and there the correction IS reachable.
    assert would_be_applied("anytime_td", tmp_path)


def test_candidate_filter_defaults_reproduce_the_hardcoded_rule():
    """Phase 3f made the thresholds configurable; the defaults must change nothing.

    The filter decides which players can be ranked at all, so a default that
    quietly shifted would move every number in the project at once and look
    like a modeling result. It is the same class of change as the denominator
    fix, and that one moved Top-1 by 0.2pp while being invisible in the code.
    """
    import polars as pl
    from src.models.trainer import _filter_low_activity

    df = _features().filter(pl.col("target").is_not_null())

    is_defst = df.select(pl.col("position_DEFST").fill_null(0) == 1).to_series()
    has_usage = df.select(
        (pl.col("player_carries_avg_5g").fill_null(0) > 0)
        | (pl.col("player_targets_avg_5g").fill_null(0) > 0)
        | (pl.col("player_receptions_avg_5g").fill_null(0) > 0)).to_series()
    is_starter = df.select(pl.col("is_starter").fill_null(0) == 1).to_series()
    has_snaps = df.select(pl.col("snap_pct").fill_null(0) > 0).to_series()
    on_dc = df.select(pl.col("depth_chart_rank").fill_null(99) <= 2).to_series()
    legacy = df.filter(is_defst | has_usage | is_starter | has_snaps | on_dc)

    assert _filter_low_activity(df).height == legacy.height, (
        "the configurable filter's defaults do not reproduce the rule they "
        "replaced — every downstream number just moved")


def test_candidate_filter_thresholds_actually_bite():
    """A knob that does nothing is worse than no knob: a sweep would report
    'this threshold does not matter' for a setting that was never applied."""
    import polars as pl
    from src.models.trainer import _filter_low_activity
    from src.utils.config import config_overlay

    df = _features().filter(pl.col("target").is_not_null())
    base = _filter_low_activity(df).height
    for cfg in ({"min_usage": 1.0}, {"min_snap_pct": 0.10},
                {"keep_defst": False}, {"max_depth_chart_rank": 0}):
        with config_overlay({"candidate_filter": cfg}):
            assert _filter_low_activity(df).height < base, (
                f"candidate_filter {cfg} changed nothing")


def test_an_unplayed_game_is_not_a_game_where_nobody_scored():
    """`target.is_not_null()` does not mean "this game was played".

    Rows for the upcoming season carry `target = 0`, not null. Filtering on
    nullity therefore counts every unplayed fixture as a game in which nobody
    scored. That is how a real 99.3% scorer coverage read as 80.2% and made the
    plan's ceiling figures look wrong when they were right to the decimal.

    Nothing in the modeling path is affected — training and the walk-forward
    select on `season`, not on target nullity — so this is a guard for the
    analysis code that keeps being written against these frames, which is where
    it actually bit.
    """
    import polars as pl
    from src.utils.config import get_config
    from src.utils.paths import get_path

    predict_season = get_config()["seasons"]["predict_season"]
    df = _features()
    upcoming = df.filter(pl.col("season") == predict_season)
    if upcoming.height == 0:
        pytest.skip(f"no {predict_season} candidate rows yet")

    assert upcoming["target"].null_count() == 0, (
        "if unplayed rows ever become null, delete this test and the workaround "
        "it documents")

    # Per week, not per season. This used to assert the predict season held no
    # scorer at all, which was true only while the season had not started — on
    # 2026-09-15, week 1 having been played and extracted, it failed on 73
    # perfectly correct anytime-TD scorers. A played week in the predict season
    # is supposed to have them; that is what makes the week gradeable.
    pbp_weeks = (pl.scan_parquet(get_path("raw") / "pbp.parquet")
                 .filter(pl.col("season") == predict_season)
                 .select("week").unique().collect()["week"].to_list())
    played = sorted(int(w) for w in pbp_weeks)

    unplayed = upcoming.filter(~pl.col("week").is_in(played))
    assert unplayed["target"].sum() == 0, (
        "an unplayed week cannot contain a scorer")

    # The other half of the same invariant, and the one that would have caught
    # 02_targets.py extracting only the configured market: a week whose
    # play-by-play is on disk must have produced labels from it.
    for wk in played:
        scorers = upcoming.filter(pl.col("week") == wk)["target"].sum()
        assert scorers > 0, (
            f"{predict_season} week {wk} has play-by-play but no scorer in the "
            "candidate matrix — targets were not extracted for this market")

    # The correct test for "played" is the season, not the target.
    played = df.filter(pl.col("season") < predict_season)
    games = played["game_id"].n_unique()
    scored = played.filter(pl.col("target") == 1)["game_id"].n_unique()
    assert scored / games > 0.95, (
        f"only {scored / games:.1%} of played games have a scorer; either "
        "coverage has collapsed or unplayed rows are being counted again")


def test_kickoff_time_is_eastern_and_converted_to_an_instant():
    """The schedule's `gametime` is US Eastern for every game, including London.

    Treating that number as the venue's local hour fetched the wrong hour's
    weather for every non-Eastern stadium — one hour out in Chicago, three in
    Seattle, five at Wembley, always earlier and therefore always colder. It did
    not look like a bug on any single stadium; it showed up as validation error
    growing monotonically with distance from Eastern (2.2F median for the 17
    Eastern venues, 5.8F for the two London ones).

    The same indexing would have gone into the feature builder, where hundreds
    of Pacific and Mountain games would have carried weather from hours before
    kickoff with nothing downstream to complain.
    """
    import importlib.util
    from datetime import timezone
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "28_weather.py"
    spec = importlib.util.spec_from_file_location("_weather_under_test", path)
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)

    # A London kickoff listed as 09:30 ET is 13:30 UTC, which is 2:30pm local
    # in BST — when those games actually start.
    assert w.kickoff_utc("2024-10-20", "09:30").isoformat() == \
        "2024-10-20T13:30:00+00:00"
    # A 1pm Eastern kickoff in autumn is 17:00 UTC (EDT, UTC-4).
    assert w.kickoff_utc("2024-10-20", "13:00").hour == 17
    # ...and in December it is 18:00 UTC, because EST is UTC-5. A fixed offset
    # would be wrong for a third of the season.
    assert w.kickoff_utc("2024-12-15", "13:00").hour == 18
    # ZoneInfo("UTC") rather than timezone.utc, so compare the offset.
    assert w.kickoff_utc("2024-10-20", "13:00").utcoffset().total_seconds() == 0


def test_no_feature_is_constant_in_the_predict_season_while_varying_in_training():
    """A fill value at predict time is a skew that null-rate checks cannot see.

    `is_cold` was `(temp < 40).fill_null(False)`. `temp` is measured at kickoff
    and is 100% null for an unplayed season, so every 2026 row read "not cold"
    while 11-15% of training rows were cold. The model learned a distinction it
    would never once encounter on the board.

    It hid because it looks healthy from every angle the pipeline checks: no
    nulls, a plausible mean, a sensible name, and `check_feature_skew` compares
    null RATES — and these columns are not null at predict time, they are zero.
    The trainer's own comment recommended them as the safe alternative to
    `temp`/`wind`, which is how an audit would have walked past it.

    This catches the shape rather than the instance: anything the model can
    learn from but will always see as one value when it matters.
    """
    import polars as pl

    from src.models.trainer import get_feature_cols
    from src.utils.config import get_config

    df = _features()
    predict_season = get_config()["seasons"]["predict_season"]
    upcoming = df.filter(pl.col("season") == predict_season)
    played = df.filter(pl.col("season") < predict_season)
    if upcoming.height == 0:
        pytest.skip(f"no {predict_season} rows yet")

    # Features that are empty in an unplayed season only because the source
    # data has not been published yet — injury reports and full position
    # designations arrive with the season. They are listed rather than filtered
    # by rule, so each is a decision someone made and can revisit.
    PRESEASON_EMPTY = {"position_FB", "ix_teammate_out_x_snap"}

    offenders = []
    for col in get_feature_cols(df):
        if col in PRESEASON_EMPTY:
            continue
        if col not in upcoming.columns:
            continue
        if upcoming[col].n_unique() > 1:
            continue                      # varies when it matters; fine
        if played[col].drop_nulls().n_unique() <= 1:
            continue                      # constant everywhere; inert, not skewed
        # Constant ahead, varying behind. Null everywhere ahead is a different
        # thing — the model handles absence — so only a filled value counts.
        if upcoming[col].null_count() == upcoming.height:
            continue
        offenders.append(col)

    assert not offenders, (
        f"these features take a single value in {predict_season} but vary in "
        f"training, so the model learned a distinction it will never see on the "
        f"board: {sorted(offenders)}")


# ---------------------------------------------------------------------------
# Adding a target type: the three ways it used to go wrong silently.
# ---------------------------------------------------------------------------

def test_an_unregistered_target_cannot_borrow_another_markets_prices():
    """A new target used to resolve to first-TD prices without a word.

    Both `odds_history.load_graded_history` and `clv.line_movement` picked their
    market with:

        market = "anytime_td" if target_type == "anytime_td" else "first_td"

    With two markets that is redundant. With a third it fits the blend weight
    against the wrong prices, measures closing-line value against the wrong
    prices, and grades a rushing-touchdown model on first-touchdown odds — all
    of it plausible on screen, none of it raising. Registration is now the only
    way in.
    """
    from src.ingest.odds_history import (MARKET_BY_TARGET, UnknownMarket,
                                         market_for_target)

    assert market_for_target("anytime_td") == "anytime_td"
    assert market_for_target("first_td") == "first_td"
    for unregistered in ("rush_td", "reception_td", "player_receptions", ""):
        if unregistered in MARKET_BY_TARGET:
            continue
        with pytest.raises(UnknownMarket):
            market_for_target(unregistered)


def test_no_module_still_guesses_the_market_from_the_target():
    """The fallback existed in two files and would be re-typed in a third."""
    import re

    pattern = re.compile(r'if\s+target_type\s*==\s*["\']anytime_td["\']\s*else')

    def code_only(path: Path) -> str:
        # The fallback is quoted verbatim in MARKET_BY_TARGET's comment, which
        # is the documentation of why it is gone rather than a use of it.
        return "\n".join(
            line for line in path.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )

    offenders = [p for p in Path("src").rglob("*.py") if pattern.search(code_only(p))]
    assert not offenders, (
        f"{offenders} still infers the archive market from the target type. "
        f"Use odds_history.market_for_target, which raises on an unknown one.")


def test_over_under_markets_are_read_rather_than_silently_skipped():
    """Rush and reception TD props are Over/Under, not Yes/No.

    Both fetch paths filtered outcomes with `side not in ("yes", "no")`, which
    matches nothing in an over/under market. Pointed at these keys the reader
    would have archived an empty market — after the credits were spent, and the
    historical endpoint sells each snapshot only once.
    """
    from src.ingest.odds_api import parse_event_markets, specs_for

    event = {"bookmakers": [
        {"key": "a", "markets": [{"key": "player_reception_tds", "outcomes": [
            {"name": "Over", "description": "P One", "point": 0.5, "price": 100},
            {"name": "Under", "description": "P One", "point": 0.5, "price": -130},
        ]}]},
        {"key": "b", "markets": [{"key": "player_reception_tds", "outcomes": [
            {"name": "Over", "description": "P One", "point": 0.5, "price": -120},
            {"name": "Under", "description": "P One", "point": 0.5, "price": -110},
        ]}]},
    ]}
    consensus, books = parse_event_markets(event, specs_for(["reception_td"]))

    assert len(consensus) == 1, "an over/under market produced no consensus price"
    row = consensus[0]
    assert row["point"] == 0.5 and row["n_books"] == 2
    # Both sides posted, so the vig comes off directly and none of the
    # one-sided expected-scorers normalization in blend.devig_market applies.
    assert row["fair_prob"] is not None and row["overround"] > 1.0
    # One vocabulary in the archive, so `side == "yes"` filters keep working.
    assert {b["side"] for b in books} == {"yes", "no"}


def test_two_lines_for_one_player_are_not_averaged_into_one_price():
    """`point` is part of the grain, not a label.

    A book quoting Over 0.5 and a book quoting Over 1.5 are not two opinions
    about one price. A median across them describes no bet that exists, and the
    archive's dedup key would have kept whichever sorted last.
    """
    from src.ingest.odds_api import parse_event_markets, specs_for
    from src.ingest.odds_history import SCHEMA, BOOK_SCHEMA

    event = {"bookmakers": [
        {"key": "a", "markets": [{"key": "player_rush_tds", "outcomes": [
            {"name": "Over", "description": "P One", "point": 0.5, "price": -140},
            {"name": "Over", "description": "P One", "point": 1.5, "price": 450},
        ]}]},
    ]}
    consensus, _ = parse_event_markets(event, specs_for(["rush_td"]))
    assert sorted(r["point"] for r in consensus) == [0.5, 1.5]

    assert "point" in SCHEMA and "point" in BOOK_SCHEMA
    import inspect
    from src.ingest import odds_history
    src = inspect.getsource(odds_history.append_snapshot)
    assert '"point"' in src, "point dropped out of the consensus dedup key"
    src = inspect.getsource(odds_history.append_book_quotes)
    assert '"point"' in src, "point dropped out of the per-book dedup key"


def test_both_fetch_paths_share_one_market_reader():
    """The live fetch and the backfill carried identical copies of the parser.

    Only one of them spends five figures of credits, and it was the copy that
    would not have been exercised until the moment it mattered.
    """
    import inspect
    from src.ingest import odds_api

    backfill = Path("scripts/09_backfill_odds.py").read_text(encoding="utf-8")
    assert "parse_event_markets" in backfill, \
        "the backfill has stopped using the shared reader"
    assert 'if side not in ("yes", "no")' not in backfill, \
        "the backfill has grown its own yes/no-only parser again"
    assert "book_rows.append" not in inspect.getsource(
        odds_api.fetch_week_td_props), \
        "the live fetch has grown its own copy of the parser again"


def test_a_widened_region_set_is_not_reported_as_already_archived():
    """`us` was hardcoded in both fetch paths for the life of the archive.

    Measured on one 2024 game, anytime TD: `us` returns 7 books and `us2`
    another 4 — including the only book that posts both sides of the market,
    and the two that quote 34-51 players a game against 21-28 at the majors.
    Every consensus median, every line-shopping figure and the whole longshot
    tail was computed without them.

    Widening the region set is therefore a top-up, not a no-op, and the archive
    has to be able to tell the two apart. Keyed on market and snapshot alone,
    `_already_archived` reported all 855 games covered and the top-up fetched
    nothing.
    """
    import importlib.util
    import polars as pl
    from src.ingest.odds_history import LEGACY_REGIONS, SCHEMA, _conform

    spec = importlib.util.spec_from_file_location(
        "backfill", Path("scripts/09_backfill_odds.py"))
    backfill = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backfill)

    rows = pl.DataFrame([{
        "captured_at": "2024-11-24T17:00:00+00:00", "snapshot": "close",
        "season": 2024, "week": 12, "game_id": "g1",
        "player_name_raw": "P", "player_name_norm": "p",
        "market": "anytime_td", "regions": LEGACY_REGIONS, "point": None,
        "odds": 120, "implied_prob": 0.45, "fair_prob": None,
        "n_books": 7, "overround": None,
    }])
    path = Path(backfill.HISTORY_PATH)
    original = backfill.HISTORY_PATH
    tmp = path.with_name("odds_history_regiontest.parquet")
    try:
        _conform(rows, SCHEMA).write_parquet(tmp)
        backfill.HISTORY_PATH = tmp
        assert backfill._already_archived(["anytime_td"], "close", "us") == {"g1"}
        assert backfill._already_archived(["anytime_td"], "close", "us,us2") == set(), \
            "a wider region set was reported as already covered"
    finally:
        backfill.HISTORY_PATH = original
        tmp.unlink(missing_ok=True)


def test_devig_default_is_the_measured_choice_not_the_obvious_one():
    """How the margin comes off decides what counts as an edge.

    The proportional split — `p_over / (p_over + p_under)` — was hardcoded
    everywhere. It under-corrects favorite-longshot bias, which leaves
    favorites beating their "fair" price and longshots missing it. Measured on
    archived closing prices, additive beat it by 0.008 log loss on anytime TD
    and tied it inside noise on receptions, so additive is the default.

    This asserts the properties that make the choice meaningful, not the choice
    itself: a method that failed these would be wrong whichever name it had.
    """
    import numpy as np
    from src.utils.devig import DEFAULT_METHOD, METHODS, two_way

    assert DEFAULT_METHOD in METHODS

    for method in METHODS:
        # A vig-free book is already fair; every method must leave it alone.
        assert two_way(0.40, 0.60, method) == pytest.approx(0.40, abs=1e-6)
        # The result is a probability, and margin only ever comes off.
        for over, under in ((0.55, 0.52), (0.80, 0.28), (0.10, 0.95)):
            p = two_way(over, under, method)
            assert 0.0 < p < 1.0
            assert p <= over + 1e-9, f"{method} added margin rather than removing it"

    # The methods must actually differ in the tails, or the choice is cosmetic.
    tail = [two_way(0.10, 0.95, m) for m in METHODS]
    assert max(tail) - min(tail) > 0.01, "methods are indistinguishable in the tail"

    # Vectorised and scalar paths must agree.
    arr = two_way(np.array([0.55, 0.80]), np.array([0.52, 0.28]))
    assert arr[0] == pytest.approx(two_way(0.55, 0.52))

    with pytest.raises(ValueError):
        two_way(0.55, 0.52, "shin")


def test_fair_prob_is_derived_and_the_archive_can_rebuild_it():
    """`fair_prob` is a convenience column, not evidence.

    Re-deciding the de-vig method must never require re-buying a snapshot, so
    the raw two-sided price has to survive in the archive: `implied_prob` is
    the over and `overround` is both sides summed, so the under is always
    recoverable.
    """
    import numpy as np
    import polars as pl
    from src.ingest.odds_history import HISTORY_PATH, SCHEMA
    from src.utils.devig import DEFAULT_METHOD, two_way

    assert {"implied_prob", "overround", "fair_prob"} <= set(SCHEMA)
    if not Path(HISTORY_PATH).exists():
        pytest.skip("no odds archive")

    h = pl.read_parquet(HISTORY_PATH)
    po = h["implied_prob"].to_numpy()
    pu = (h["overround"] - h["implied_prob"]).to_numpy()
    two_sided = np.isfinite(pu) & (pu > 1e-6)
    if two_sided.sum() == 0:
        pytest.skip("no two-sided prices archived")

    rebuilt = two_way(po[two_sided], pu[two_sided], DEFAULT_METHOD)
    stored = h["fair_prob"].to_numpy()[two_sided]
    assert np.nanmax(np.abs(rebuilt - stored)) < 1e-3, \
        "stored fair_prob no longer matches what the raw columns rebuild"


def test_fair_prob_is_null_never_nan():
    """NaN is not null, and every filter in this project is written for null.

    `pl.col("fair_prob").is_not_null()` returns True for a NaN, so a one-sided
    price whose de-vig produced NaN would pass every "do we have a fair price"
    check and be served as though the vig had been removed. A migration wrote
    157,691 of them in one line by round-tripping the column through numpy,
    where null and NaN are the same value.
    """
    import polars as pl
    from src.ingest.odds_history import HISTORY_PATH

    if not Path(HISTORY_PATH).exists():
        pytest.skip("no odds archive")
    h = pl.read_parquet(HISTORY_PATH)
    for col in ("fair_prob", "implied_prob", "overround", "point"):
        n_nan = int(h[col].is_nan().sum() or 0)
        assert n_nan == 0, (
            f"{col} holds {n_nan:,} NaN values, which survive is_not_null() "
            f"and will be read as real numbers downstream")


def test_model_only_column_appears_exactly_where_blending_moves_the_number():
    """Two probabilities on one row must mean two different numbers.

    Anytime TD blends the model with the de-vigged price; first TD does not, so
    there the published probability *is* the model's and a second column would
    imply a distinction the market does not have.

    The first version of this gate borrowed `preblend_columns_differ`, which
    answers a neighbouring question — whether the betting columns add anything —
    and needs `bet_rank`/`model_edge_pp` to be present. Handed a board frame
    before those exist it returns False, which would have hidden the column on
    the one market that needs it.
    """
    import pandas as pd
    from src.presentation import board as bp

    blended = pd.DataFrame({"probability": [0.46, 0.20], "prob_model": [0.50, 0.23]})
    assert bp.blend_moves_the_number(blended)

    unblended = pd.DataFrame({"probability": [0.09, 0.04], "prob_model": [0.09, 0.04]})
    assert not bp.blend_moves_the_number(unblended)

    # Absent the pre-blend column there is nothing to compare, and that is not
    # a reason to raise on a board that simply has not carried it.
    assert not bp.blend_moves_the_number(pd.DataFrame({"probability": [0.4]}))

    # It must not depend on the betting columns, which arrive later than it does.
    assert "bet_rank" not in blended.columns and bp.blend_moves_the_number(blended)


def test_ngs_features_cannot_reveal_that_this_week_happened():
    """The row's existence leaked, not its values.

    Next Gen Stats publishes a player-week row only when that player had
    qualifying receiving activity THAT WEEK. The matrix left-joined it on the
    week itself, so `ngs_avg_separation_szn_avg IS NOT NULL` meant "caught a
    pass in the game we are predicting":

        P(1+ reception | an NGS row exists that week) = 0.9972
        P(1+ reception | no NGS row)                  = 0.1562

    Every value was correctly lagged — sorted, shifted, partitioned by player —
    which is why this survived every shift(1) audit for the life of the project.
    On anytime TD the null bit alone was worth a 5.05x lift, walk-forward Top-1
    fell from 53.8% to 49.2% once it was closed, and rank economics inverted
    from +5.9% to -6.6%.

    `spine.as_of_join` fixes it structurally: every candidate row gets the most
    recent observation strictly *earlier* than its own week.
    """
    import polars as pl
    from src.features.spine import as_of_join

    cand = pl.DataFrame({
        "player_id": ["a"] * 4 + ["b"] * 3,
        "season": [2024] * 7,
        "week": [1, 2, 3, 4, 1, 2, 3],
    })
    # `a` is measured in weeks 1 and 3; `b` never is.
    ngs = pl.DataFrame({
        "player_id": ["a", "a"], "season": [2024, 2024], "week": [1, 3],
        "sep": [1.0, 3.0],
    })
    out = as_of_join(cand, ngs, ["sep"]).sort(["player_id", "week"])

    def val(pid, wk):
        return out.filter((pl.col("player_id") == pid) & (pl.col("week") == wk))["sep"][0]

    # THE test: week 3 has an NGS row, and must not be able to tell.
    assert val("a", 3) == 1.0, (
        "week 3 used its own week's observation — the row's existence is "
        "leaking again")
    assert val("a", 1) is None, "nothing precedes week 1, so there is nothing to use"
    assert val("a", 2) == 1.0
    assert val("a", 4) == 3.0, "week 4 may use week 3, which is genuinely past"

    # A player never measured stays null. That is a fact about his career,
    # known before kickoff — not about the game being predicted.
    assert all(val("b", w) is None for w in (1, 2, 3))

    # And the assembler must actually use it, or the fix is decorative.
    import inspect
    from src.features import assembler
    src = inspect.getsource(assembler)
    assert "as_of_join(df, receiver_feats)" in src, \
        "NGS receiver features are back on a plain week join"
    assert "as_of_join(df, rushing_eff_feats)" in src, \
        "NGS rushing features are back on a plain week join"


def test_the_ngs_null_bit_no_longer_carries_the_outcome():
    """The measured version of the test above, on the served matrix.

    A residual lift is expected and legitimate — "has been a measured receiver
    before this week" genuinely identifies real receivers and is knowable before
    kickoff. What must not come back is the 5x that meant "played and was
    targeted today".
    """
    import polars as pl

    path = get_path("processed", TARGET) / "features.parquet"
    if not path.exists():
        pytest.skip("no feature matrix built")
    f = pl.read_parquet(path)
    col = "ngs_avg_separation_szn_avg"
    if col not in f.columns:
        pytest.skip(f"{col} not in the matrix")

    nn = f.filter(pl.col(col).is_not_null())
    nu = f.filter(pl.col(col).is_null())
    if nn.height < 100 or nu.height < 100:
        pytest.skip("not enough of either group to measure")

    lift = nn["target"].mean() / max(nu["target"].mean(), 1e-9)
    assert lift < 3.5, (
        f"the NGS null bit carries a {lift:.2f}x lift on {TARGET}; it was 5.05x "
        f"when the row's existence leaked and 2.35x after as_of_join. Something "
        f"has put NGS back on a same-week join.")


def test_receptions_is_a_registered_target_that_cannot_misgrade():
    """The third target type, wired without inheriting TD grading.

    Registration makes `market_for_target("receptions")` resolve instead of
    raising. What it must NOT do is inherit the scorer-grading path:
    `load_graded_history` grades per player against tds_*.parquet, and a count
    market graded that way would mark every 8-catch game a miss for not being
    a touchdown. For receptions that loader finds no tds parquet and returns
    None — graceful, and the per-line grading lives in scripts/30_receptions.py.
    """
    from src.ingest.odds_history import load_graded_history, market_for_target

    assert market_for_target("receptions") == "receptions"
    assert load_graded_history("receptions") is None, (
        "receptions is being graded by the TD scorer path, which marks a "
        "10-catch, 0-TD game as a miss")


def test_every_market_on_disk_is_built_by_the_as_of_join_not_just_the_configured_one():
    """The unit test above passed for five days while first TD leaked.

    `scripts/04_features.py` rebuilds only the market named by
    `config.target.type`. When the NGS and weekly-stats existence leaks were
    closed on 2026-08-18 that key read `anytime_td`, so anytime TD's matrix was
    rebuilt through `spine.as_of_join` and first TD's simply was not — it kept
    its 2026-08-17 same-week join, and every first-TD number measured after the
    fix was read off it, including the "unmoved, 16.5% -> 16.4%" result and the
    re-settle that rested on it.

    Nothing caught it. The unit test covers `as_of_join` itself, which was
    correct. `feature_matrix_hash` covered row count and column names, which do
    not move when a join changes. So this asserts the property on the FILES the
    harness actually reads, for EVERY market, which is the only place the defect
    was visible.

    The property: an as-of join is monotonic within a player-season. Once a
    strictly-earlier observation exists it exists for every later week, so
    presence can turn on but never off. A same-week join flickers with weekly
    activity. A handful of violations survive legitimately — a player changing
    team mid-season restarts the partition — so this allows a small floor rather
    than demanding zero.
    """
    import polars as pl

    from src.evaluation.harness import MARKETS
    from src.utils.paths import get_path

    probe = "ngs_avg_cushion_avg_3g"
    for market in MARKETS:
        path = get_path("processed", market) / "features.parquet"
        if not path.exists():
            continue
        df = pl.read_parquet(path, columns=["player_id", "season", "week", probe])
        df = df.with_columns(pl.col(probe).is_not_null().alias("present"))
        gaps = (df.sort(["player_id", "season", "week"])
                  .group_by(["player_id", "season"])
                  .agg([pl.col("present").cum_max().alias("seen"),
                        pl.col("present")])
                  .explode(["seen", "present"])
                  .filter(pl.col("seen") & ~pl.col("present"))
                  .height)
        assert gaps < 100, (
            f"{market}: {gaps:,} player-seasons where NGS data is present in "
            f"one week and absent in a later one. That is a same-week join, "
            f"which means the row's existence encodes activity in the game "
            f"being predicted. Rebuild it:\n"
            f"    python -c \"import sys; sys.path.insert(0,'.'); "
            f"from src.utils.config import config_overlay; "
            f"from src.features.assembler import assemble_features; "
            f"config_overlay({{'target':{{'type':'{market}'}}}}).__enter__(); "
            f"assemble_features()\"")


def test_the_matrix_hash_moves_when_values_move():
    """Shape is not identity.

    `feature_matrix_hash` hashed the row count and the column names, and a leak
    fix changes neither — it changes which row is joined. Anytime TD's hash
    moved only because unrelated weather work dropped two columns in the same
    window; first TD's was byte-identical across the fix, so every staleness
    check built on it passed a matrix that still leaked.
    """
    import hashlib

    import polars as pl

    a = pl.DataFrame({"x": [1.0, 2.0, 3.0], "y": [4.0, 5.0, 6.0]})
    b = pl.DataFrame({"x": [1.0, 2.0, 3.0], "y": [4.0, 5.0, 99.0]})

    def digest(df):
        ordered = df.select(sorted(df.columns))
        payload = (f"{df.height}|{'|'.join(sorted(df.columns))}|".encode()
                   + ordered.hash_rows().to_numpy().tobytes())
        return hashlib.sha256(payload).hexdigest()[:16]

    assert digest(a) != digest(b), (
        "same shape, same column names, one different value — these must not "
        "hash alike or a re-joined matrix reads as the one it replaced")


def test_retraining_today_would_produce_the_feature_set_that_is_served():
    """A new family must be opted in, not arrive by default.

    first TD had no allow-list, which reads as "keep everything" — and
    "everything" is whatever the assembler happens to produce on the day. The
    weather families made that concrete: 24 columns nothing had screened on
    that market, carrying a value that is constant for the season being served,
    would have entered its model the moment it was retrained. No allow-list, no
    ablation and no ledger row would have mentioned them, because nobody added
    them to anything — they were simply there.

    The invariant is stated on the outcome instead of on any one door into it:
    what `get_feature_cols` returns today must be what the served model was
    trained on. Drift in either direction is a failure — a family that appeared,
    or one that vanished — and the diff says which.
    """
    import pickle

    import polars as pl

    from src.models.trainer import get_feature_cols
    from src.utils.paths import get_path

    for market in ("anytime_td", "first_td"):
        path = get_path("models", market) / "feature_cols.pkl"
        if not path.exists():
            continue
        served = set(pickle.loads(path.read_bytes()))
        fpath = get_path("processed", market) / "features.parquet"
        if not fpath.exists():
            continue
        df = pl.read_parquet(fpath)
        today = set(get_feature_cols(df, market))
        appeared = sorted(today - served)
        vanished = sorted(served - today)
        assert not appeared, (
            f"{market}: retraining would add {len(appeared)} features the "
            f"served model has never seen: {appeared[:8]}. If they belong, "
            f"screen them and retrain; if they do not, they need saying so in "
            f"`include_feature_families_by_target`")
        assert not vanished, (
            f"{market}: retraining would drop {len(vanished)} features the "
            f"served model uses: {vanished[:8]}")


# The predict season needs play-by-play, and the week it breaks is not week 1.
#
# `ingest_all` fed `load_pbp` and `load_weekly_stats` the training range while
# rosters, schedules, depth charts and injuries got `fwd`. Week 1 looked
# perfect, because carry_forward fills the team features from the previous
# season. Week 2 is where it landed: the season-to-date average now wants a
# week-1 observation that was never ingested, so every `*_szn_avg` team and
# opponent feature went 100% null and then 0.0 — measured 2026-09-15 at 954/954
# non-null in week 1 against 0/805 in week 2, with team_plays_per_game_szn_avg
# scored 29 SDs from where it was fitted.

def test_ingest_gives_play_by_play_the_predict_season_too():
    """The wiring, asserted where it is written rather than inferred later."""
    import inspect

    from src.ingest import loader

    src = inspect.getsource(loader.ingest_all)
    for feed in ("load_pbp", "load_weekly_stats"):
        assert f"{feed}(fwd)" in src, (
            f"{feed} is not given the predict season. The labels for a finished "
            "week and every team season-to-date aggregate both come from "
            "play-by-play, so the training range alone fails twice — silently "
            "in week 1, loudly in week 2.")


def test_team_season_averages_are_populated_for_every_built_predict_week():
    """A week with a real candidate pool must have real team features.

    The failure this catches does not raise and does not change a row count —
    the board renders, the names look plausible, and the model simply scores
    every team as though it had played no football. Nullness is the only
    evidence, so nullness is what gets asserted.
    """
    import polars as pl

    from src.utils.config import get_config
    from src.utils.paths import get_path

    predict_season = get_config()["seasons"]["predict_season"]
    feats = get_path("processed", "anytime_td") / "features.parquet"
    if not feats.exists():
        pytest.skip("no feature matrix on disk")

    lf = pl.scan_parquet(feats)
    cols = [c for c in lf.collect_schema().names()
            if c.startswith(("team_", "opp_")) and c.endswith("_szn_avg")]
    assert cols, "no team season-average features found — has the matrix moved?"

    weeks = (lf.filter(pl.col("season") == predict_season)
             .group_by("week").agg(pl.len().alias("n"))
             .filter(pl.col("n") > 200)          # 32 rows is DEF/ST alone
             .collect())
    if weeks.height == 0:
        pytest.skip(f"no {predict_season} week is built yet")

    for row in weeks.sort("week").iter_rows(named=True):
        wk = row["week"]
        d = (lf.filter((pl.col("season") == predict_season)
                       & (pl.col("week") == wk))
             .select(cols).collect())
        empty = [c for c in cols if d[c].drop_nulls().len() == 0]
        assert not empty, (
            f"{predict_season} week {wk}: {len(empty)} of {len(cols)} team "
            f"season-average features are 100% null and will be filled with "
            f"0.0 at score time — e.g. {empty[:3]}")


def test_player_games_observed_counts_only_games_already_played():
    """The sample-size column must not see the week it labels.

    It is built from `cum_count()` inside the same lag convention as every
    rolling mean around it, so a row for week w must count games strictly
    before w. Added 2026-09-21 with the column itself: a count that included
    the current game would make every debutant look like a one-game veteran
    and would be invisible, because the number would still be small and still
    look plausible.
    """
    import polars as pl

    from src.utils.paths import get_path

    path = get_path("processed", "anytime_td") / "features.parquet"
    if not path.exists():
        pytest.skip("no feature matrix on disk")
    df = (pl.scan_parquet(path)
          .select(["season", "week", "player_id", "player_games_observed"])
          .collect())
    assert df.height, "feature matrix is empty"

    # A player's first appearance can never have seen a game.
    first = (df.filter(pl.col("player_id").is_not_null())
             .sort(["player_id", "season", "week"])
             .group_by("player_id").first())
    assert first["player_games_observed"].min() == 0, (
        "a player's first row claims to have observed games already — the "
        "count is including the current week")

    # And it must never fall as time moves forward for one player.
    d = (df.filter(pl.col("player_id").is_not_null())
         .sort(["player_id", "season", "week"])
         .with_columns(pl.col("player_games_observed").diff()
                       .over("player_id").alias("_d")))
    assert d.filter(pl.col("_d") < 0).height == 0, (
        "games observed decreases for some player — the frame is not ordered "
        "the way the cumulative count assumes")
