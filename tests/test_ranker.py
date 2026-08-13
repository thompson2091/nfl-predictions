"""The conditional-logit objective, checked against its own definition.

A wrong gradient does not crash. It trains, produces a model, and quietly
optimises something nobody chose — which on this project would show up as a
Top-1 number that moves for no reason anyone can name. So the gradient and
Hessian are checked numerically against the loss they claim to differentiate,
rather than by eye.

    pytest tests/test_ranker.py -v
"""
from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.models.ranker import (DEFAULTS, ConditionalLogitModel, _drop_singletons,
                               _group_softmax, conditional_logit_nll,
                               conditional_logit_objective, group_ids)


def loss(scores, y, groups, n_groups):
    """-sum_i y_i log p_i, the thing the objective must differentiate."""
    p = _group_softmax(scores, groups, n_groups)
    return float(-(y * np.log(np.clip(p, 1e-12, None))).sum())


def test_softmax_normalises_within_each_group_not_across_them():
    scores = np.array([1.0, 2.0, 0.5, 3.0])
    groups = np.array([0, 0, 1, 1])
    p = _group_softmax(scores, groups, 2)
    assert p[:2].sum() == pytest.approx(1.0)
    assert p[2:].sum() == pytest.approx(1.0)
    # and the total is the number of groups, not 1 — the giveaway if the
    # normalisation were global.
    assert p.sum() == pytest.approx(2.0)


def test_softmax_is_shift_invariant():
    """Max-shifting for stability must not change the answer."""
    groups = np.array([0, 0, 0])
    a = _group_softmax(np.array([1.0, 2.0, 3.0]), groups, 1)
    b = _group_softmax(np.array([1001.0, 1002.0, 1003.0]), groups, 1)
    assert a == pytest.approx(b)


def test_gradient_matches_numerical_derivative():
    """The central check: grad really is dLoss/dscore."""
    rng = np.random.default_rng(0)
    groups = np.array([0, 0, 0, 1, 1, 2, 2, 2, 2])
    y = np.array([0., 1., 0., 1., 0., 0., 0., 1., 0.])
    scores = rng.normal(size=groups.size)
    grad, _ = conditional_logit_objective(groups, 3)(y, scores)

    eps = 1e-6
    for i in range(groups.size):
        up, down = scores.copy(), scores.copy()
        up[i] += eps
        down[i] -= eps
        numeric = (loss(up, y, groups, 3) - loss(down, y, groups, 3)) / (2 * eps)
        assert grad[i] == pytest.approx(numeric, abs=1e-5), f"row {i}"


def test_hessian_matches_the_numerical_second_derivative():
    groups = np.array([0, 0, 0, 1, 1])
    y = np.array([0., 1., 0., 1., 0.])
    scores = np.array([0.3, -0.4, 1.2, 0.0, 0.7])
    _, hess = conditional_logit_objective(groups, 2)(y, scores)

    eps = 1e-4
    for i in range(groups.size):
        up, down = scores.copy(), scores.copy()
        up[i] += eps
        down[i] -= eps
        numeric = (loss(up, y, groups, 2) - 2 * loss(scores, y, groups, 2)
                   + loss(down, y, groups, 2)) / eps ** 2
        assert hess[i] == pytest.approx(numeric, abs=1e-3), f"row {i}"


def test_a_group_whose_winner_was_filtered_out_contributes_nothing():
    """~2% of first-TD games lose their scorer to the candidate filter.

    Those groups carry no information about who would have won. If they
    contributed gradient, the model would be taught to push every candidate in
    them down — a preference for nobody, learned from every such game.
    """
    groups = np.array([0, 0, 1, 1])
    y = np.array([1., 0., 0., 0.])          # group 1 has no winner
    grad, hess = conditional_logit_objective(groups, 2)(y, np.array([0.5, 0.2, 0.9, 0.1]))
    assert grad[2:] == pytest.approx([0.0, 0.0])
    assert (hess[2:] > 0).all(), "hessian must stay positive; xgboost divides by it"


def test_two_winners_in_a_group_is_the_anytime_case():
    """Anytime TD groups by team-game, where several players can score."""
    groups = np.array([0, 0, 0])
    y = np.array([1., 1., 0.])
    grad, _ = conditional_logit_objective(groups, 1)(y, np.zeros(3))
    # Two winners, three equal scores: each p = 1/3, so grad = 2/3 - y.
    assert grad == pytest.approx([2 / 3 - 1, 2 / 3 - 1, 2 / 3])
    assert grad.sum() == pytest.approx(0.0), (
        "within a group the gradient must sum to zero — the softmax can only "
        "move probability between candidates, never add any"
    )


def test_the_loss_is_minimised_by_scoring_the_winner_highest():
    groups = np.zeros(3, dtype=np.int64)
    y = np.array([1., 0., 0.])
    right = loss(np.array([3.0, 0.0, 0.0]), y, groups, 1)
    flat = loss(np.zeros(3), y, groups, 1)
    wrong = loss(np.array([0.0, 3.0, 0.0]), y, groups, 1)
    assert right < flat < wrong


def test_the_eval_metric_ignores_groups_with_no_winner():
    """Otherwise the metric improves as the pool loses scorers."""
    groups = np.array([0, 0, 1, 1])
    y_with = np.array([1., 0., 0., 0.])
    metric = conditional_logit_nll(groups, 2)
    scores = np.array([1.0, 0.0, 1.0, 0.0])
    # Group 1 has no winner. Its scores must not affect the reported NLL.
    other = np.array([1.0, 0.0, -5.0, 5.0])
    assert metric(y_with, scores) == pytest.approx(metric(y_with, other))


def test_group_ids_use_the_market_s_own_unit_of_competition():
    df = pl.DataFrame({
        "game_id": ["g1", "g1", "g1", "g1"],
        "team": ["KC", "KC", "BUF", "BUF"],
    })
    # First TD: one winner in the whole game, so the game is the group.
    assert len(set(group_ids(df, "first_td").tolist())) == 1
    # Anytime: the joint model consumes team-level shares, so players compete
    # within their own team, not against the opponent's.
    assert len(set(group_ids(df, "anytime_td").tolist())) == 2


def test_singleton_groups_are_dropped_before_fitting():
    """A one-candidate group has softmax 1.0 whatever the score is."""
    groups = np.array([0, 0, 1, 2, 2])
    y = np.array([1., 0., 1., 0., 1.])
    X = np.arange(10.0).reshape(5, 2)
    g, y2, X2 = _drop_singletons(groups, y, X)
    assert g.size == 4 and y2.size == 4 and X2.shape[0] == 4
    assert sorted(np.bincount(g).tolist()) == [2, 2]
    assert set(np.unique(g).tolist()) == {0, 1}, "codes must stay contiguous"


def test_it_learns_a_within_group_ranking_it_could_not_learn_pointwise():
    """The point of the objective, on data built to require it.

    Every group has exactly one winner and the winner is the candidate with the
    largest first feature *within its own group*. The absolute value carries no
    information — a pointwise learner sees the same feature value winning in one
    group and losing in another.
    """
    rng = np.random.default_rng(7)
    n_groups, per = 300, 6
    groups = np.repeat(np.arange(n_groups), per)
    x = rng.normal(size=groups.size)
    offset = np.repeat(rng.normal(scale=5.0, size=n_groups), per)
    feature = x + offset                      # within-group order preserved
    y = np.zeros(groups.size)
    for g in range(n_groups):
        idx = np.where(groups == g)[0]
        y[idx[np.argmax(x[idx])]] = 1.0

    X = np.column_stack([feature, rng.normal(size=groups.size)])
    model = ConditionalLogitModel()
    model.feature_names = ["feature", "noise"]
    cfg = {**DEFAULTS, "n_estimators": 120, "learning_rate": 0.1,
           "max_depth": 3, "min_child_weight": 1, "early_stopping_rounds": None}
    model.fit(X, y, X, y, cfg, groups=(groups, groups))

    scores = model.predict_proba(X)
    hits = sum(1 for g in range(n_groups)
               if y[np.where(groups == g)[0][
                   np.argmax(scores[np.where(groups == g)[0]])]] == 1.0)
    assert hits / n_groups > 0.5, (
        f"top-1 {hits / n_groups:.1%} against {1 / per:.1%} for random guessing"
    )


def test_saving_drops_the_training_closures():
    """The objective closes over one fold's group array; it must not persist."""
    rng = np.random.default_rng(1)
    groups = np.repeat(np.arange(20), 3)
    y = np.tile([1.0, 0.0, 0.0], 20)
    X = rng.normal(size=(60, 3))
    model = ConditionalLogitModel()
    model.feature_names = ["a", "b", "c"]
    model.fit(X, y, X, y, {**DEFAULTS, "n_estimators": 5,
                           "early_stopping_rounds": None},
              groups=(groups, groups))

    import pickle
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "m.pkl"
        model.save(path)
        blob = pickle.loads(path.read_bytes())
        assert not callable(blob["model"].get_params()["objective"])
        restored = ConditionalLogitModel.load(path)
        assert restored.predict_proba(X).shape == (60,)
        assert restored.feature_names == ["a", "b", "c"]


def test_fitting_without_groups_is_an_error_not_a_silent_pointwise_fit():
    model = ConditionalLogitModel()
    X, y = np.zeros((4, 2)), np.array([1., 0., 1., 0.])
    with pytest.raises(ValueError, match="needs group ids"):
        model.fit(X, y, X, y, DEFAULTS)
