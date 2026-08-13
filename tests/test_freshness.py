"""Regression tests for the "is this number describing the current model" check.

    pytest tests/test_freshness.py -v
"""
from __future__ import annotations

import os
import time

import pytest

from src.evaluation import freshness as F


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A models/ and output/ pair whose timestamps can be set deliberately."""
    models = tmp_path / "models" / "anytime_td"
    output = tmp_path / "output" / "anytime_td"
    models.mkdir(parents=True)
    output.mkdir(parents=True)

    def get_path(key, target_type=None):
        return {"models": models, "output": output}[key]

    monkeypatch.setattr(F, "get_path", get_path)
    return models, output


def _touch(path, when: float, payload: str = "{}"):
    path.write_text(payload)
    os.utime(path, (when, when))


def test_an_evaluation_older_than_the_model_is_reported(tree):
    models, output = tree
    now = time.time()
    _touch(output / "walkforward.json", now - 7200)     # two hours old
    _touch(models / "xgb.pkl", now)                     # retrained since

    stale = F.stale_artifacts("anytime_td")
    assert [s["artifact"] for s in stale] == ["walkforward.json"]
    assert stale[0]["behind_seconds"] == pytest.approx(7200, abs=5)
    assert "make walkforward" in stale[0]["command"], (
        "a staleness report has to say how to fix it, or it is just alarming"
    )


def test_a_current_evaluation_is_not_reported(tree):
    models, output = tree
    now = time.time()
    _touch(models / "xgb.pkl", now - 60)
    _touch(output / "walkforward.json", now)
    assert F.stale_artifacts("anytime_td") == []


def test_clustering_does_not_age_the_evaluation(tree):
    """`make clusters` writes into models/, and it runs after training.

    The first version of this check counted those files toward the model's
    timestamp, so running clusters reported every evaluation artifact as stale —
    including ones regenerated seconds earlier. A false alarm on every artifact
    at once is how a warning gets ignored.
    """
    models, output = tree
    now = time.time()
    _touch(models / "xgb.pkl", now - 3600)
    _touch(output / "walkforward.json", now - 1800)
    _touch(models / "clusters_player.json", now)        # clustered just now

    assert F.stale_artifacts("anytime_td") == []


def test_prediction_does_not_age_the_evaluation(tree):
    """`blend_weight.json` is refit at predict time, every week the archive grows."""
    models, output = tree
    now = time.time()
    _touch(models / "xgb.pkl", now - 3600)
    _touch(output / "walkforward.json", now - 1800)
    _touch(models / "blend_weight.json", now)

    assert F.stale_artifacts("anytime_td") == []


def test_the_oldest_backtest_frame_governs(tree):
    """A refreshed 2025 frame says nothing about a 2023 frame that was not."""
    models, output = tree
    now = time.time()
    _touch(output / "backtest_2023.csv", now - 7200, "a,b")
    _touch(output / "backtest_2025.csv", now, "a,b")
    _touch(models / "xgb.pkl", now - 60)

    stale = F.stale_artifacts("anytime_td")
    assert len(stale) == 1
    assert "1 of 2 backtest frames" in stale[0]["artifact"]


def test_a_missing_artifact_is_not_called_stale(tree):
    """Never built and out of date are different problems.

    Conflating them makes a fresh checkout look broken, and the app already
    handles absence by falling back or hiding the panel.
    """
    models, _ = tree
    _touch(models / "xgb.pkl", time.time())
    assert F.stale_artifacts("anytime_td") == []
