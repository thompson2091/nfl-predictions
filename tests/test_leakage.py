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
    feats = pl.read_parquet(
        get_path("processed", cfg["target"]["type"]) / "features.parquet"
    ).filter(pl.col("target").is_not_null())

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
    feats = pl.read_parquet(
        get_path("processed", cfg["target"]["type"]) / "features.parquet"
    ).filter(pl.col("target").is_not_null())

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
    account for well under 1% of scorers. Normalising the total across all of
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
    used to negate it again inside the formula. The two cancelled, so every
    away team was handed the home team's implied total — the same number for
    both sides of every game, uncorrelated with the spread, flattening the four
    `ix_itt_*` interactions that multiply through it.
    """
    cfg = get_config()
    feats = pl.read_parquet(
        get_path("processed", cfg["target"]["type"]) / "features.parquet"
    ).filter(pl.col("implied_team_total").is_not_null()
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
        "implied team total — the away-side sign flip is cancelling out."
    )

    # The favourite must carry the higher implied total, by construction.
    t = feats.group_by(["game_id", "team"]).agg([
        pl.col("implied_team_total").first(), pl.col("spread_line").first(),
    ])
    corr = np.corrcoef(t["spread_line"].to_numpy(),
                       t["implied_team_total"].to_numpy())[0, 1]
    assert corr > 0.5, (
        f"implied total vs spread correlation is {corr:+.3f}. nflverse spread "
        "is positive when this team is favoured, so a favourite must carry the "
        "higher implied total."
    )


def test_favourite_flag_is_not_inverted():
    """`is_favorite` must mark the team the market expects to win.

    nflverse `spread_line` is positive when the home team is favoured, and the
    code asserted the opposite in a comment. The flag came out fully inverted:
    teams marked favourite won 34.9% of their games and teams marked underdog
    won 66.7%. `is_big_favorite` and `favorite_team` in the score-first
    features carried the same inversion.
    """
    cfg = get_config()
    feats = pl.read_parquet(
        get_path("processed", cfg["target"]["type"]) / "features.parquet"
    )
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
        f"teams flagged favourite win {fav:.1%} of the time, underdogs win "
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
    # The stronger offence must be likelier to score first.
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
    feats = pl.read_parquet(
        get_path("processed", cfg["target"]["type"]) / "features.parquet"
    )
    seasons = list(range(2015, cfg["splits"]["train_end"] + 1))
    model = fit_team_rate(feats, seasons)

    idx = model["design_cols"].index("implied_team_total")
    assert model["coef"][idx] > 0, (
        f"implied team total carries coefficient {model['coef'][idx]:+.4f}; "
        "a better offence must not predict fewer touchdowns."
    )

    games = pl.DataFrame({
        "game_id": ["g1", "g1"], "team": ["fav", "dog"],
        "implied_team_total": [28.0, 17.0],
        "total_line": [45.0, 45.0], "spread_line": [11.0, -11.0],
    })
    out = team_rate(model, games)
    fav = out.filter(pl.col("team") == "fav")["team_lambda"][0]
    dog = out.filter(pl.col("team") == "dog")["team_lambda"][0]
    assert fav > dog, f"favourite rate {fav:.3f} not above underdog {dog:.3f}"


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
        import json
        folds = json.loads(path.read_text())
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

    assert stats["auc_gap_lo"] > 0, (
        f"the sorting edge is no longer distinguishable from zero "
        f"(95% CI lower bound {stats['auc_gap_lo']:+.4f}). The highlight should "
        f"come out of the app."
    )
    assert stats["auc_ours"] > stats["auc_book"]
    # The counterweight must stay true, or the caption misleads: this band is
    # priced above what it actually does.
    assert stats["band_price_implied"] > stats["band_actual_rate"], (
        "the longshot band is no longer overpriced — the caption's warning "
        "about the bookmaker's margin needs rewriting."
    )


def test_devig_does_not_depend_on_how_many_players_were_priced():
    """A favourite's fair probability must not move when longshots are added.

    The one-sided branch divides every price by sum(implied)/expected, so
    quoting extra deep longshots rescales *everyone*. Archive coverage fell
    from 52 priced players a game in 2023 to 26.8 in 2025, and that alone moved
    a -100 favourite's fair probability from 41% to 49% while its real rate sat
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

    # This documents the behaviour rather than forbidding it: the function is
    # doing what it is asked. The guard that matters is that the *callers*
    # restrict their input, which the assertion below pins down.
    assert fav_after < fav_before, "expected the tail to dilute the favourite"

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
        # point of this test is the direction logic, not the normalisation.
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

    src = inspect.getsource(clv.measure)
    assert "open_fair" in src, "CLV no longer de-vigs the opening price"
    assert 'pl.col("move") != 0' in src, "CLV counts prices that never moved"
    assert "null" in src, "CLV reports no permutation null to compare against"


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

    Two bets in one game share a defence, a game script and a final score. A
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

    Normalising it would turn "bet 3% of bankroll" into "bet everything" —
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
        "$1000 — the fractions are being renormalised."
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
    overwrote the price actually given with the one we modelled against, it
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
    assert s is not None and "n_settled" in s and "n_placed" in s


def test_book_quotes_are_captured_not_just_the_median():
    """The per-book detail arrives free in the same response and cannot be
    re-bought. Collapsing to a median before writing threw away line shopping,
    book disagreement and staleness in one step."""
    import inspect
    from src.ingest import odds_api, odds_history

    src = inspect.getsource(odds_api.fetch_week_td_props)
    assert "book_rows.append" in src, "per-book quotes are being discarded again"
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
            "player_name_norm": "p", "market": "anytime_td", "side": "yes",
            "odds": odds, "implied_prob": 0.4,
        })
    pl.DataFrame(rows).cast(odds_history.BOOK_SCHEMA).write_parquet(path)

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
    src = Path("app.py").read_text()
    body = src.split("def _bet_guidance(", 1)[1].split("\ndef ", 1)[0]

    assert "good_seasons == len(seasons)" in body, (
        "guidance no longer distinguishes 'profitable every season' from "
        "'profitable once' — both would read as an endorsement"
    )
    endorsement = "take it seriously"
    all_seasons_branch, _, partial_branch = body.partition("    else:")
    assert endorsement in all_seasons_branch, "the endorsement went missing"
    assert endorsement not in partial_branch, (
        "a strategy that won in a minority of seasons is being endorsed"
    )


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
    still runs green.
    """
    from src.evaluation.parity import check
    from src.utils.config import get_config

    season = get_config()["splits"]["test_season"]
    failures = []
    for target in ("anytime_td", "first_td"):
        with capsys.disabled() if False else __import__("contextlib").redirect_stdout(
                __import__("io").StringIO()):
            ok, msg = check(target, season)
        if not ok:
            failures.append(msg)
    assert not failures, "\n".join(failures)


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
    assert out is not None
    assert "too few to judge" in out["verdict"]
    assert "below_expectation" not in out


def test_the_positional_bias_is_not_stable_enough_to_correct():
    """Guards three failed experiments' worth of conclusion.

    The pooled calibration gap by rank looks like a systematic bias worth
    correcting. Split by season it disagrees in sign — rank 1 runs +12.0pp,
    +3.2pp, -8.8pp across 2023/24/25 on ~283 observations each. A
    monotone-by-construction correction fitted on two seasons made the third
    worse. If a future rebuild ever produces a bias that IS consistent across
    seasons, this test fails and the idea is worth revisiting.
    """
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
            gaps.append(sub["scored"].mean() - sub["prob_calibrated"].mean())
        # "Consistent" means every season agrees on the sign and the effect is
        # not trivially small.
        if len(gaps) == len(seasons) and (
                all(g > 0.02 for g in gaps) or all(g < -0.02 for g in gaps)):
            consistent.append(rank)

    assert not consistent, (
        f"ranks {consistent} now show a consistent bias across every season — "
        f"src/models/rank_calibration.py may be worth reviving, monotone form"
    )
