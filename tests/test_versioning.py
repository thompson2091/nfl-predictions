"""Regression tests for locked model versions.

Two jobs. The round-trip tests run against a temporary `models/` tree and prove
that promote and rollback actually move the bytes — a rollback path that is
never exercised is a rollback path that does not work when you need it. The
last test runs against the real repository and asserts that what is being
served matches what `CURRENT.json` claims, so a retrain that lands without a
lock fails here instead of quietly making the committed record a lie.

    pytest tests/test_versioning.py -v
"""
from __future__ import annotations

import json

import pytest

from src.models import versioning as V


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A fake `models/` tree, so no test can touch what the app serves."""
    root = tmp_path / "models"
    for market in V.MARKETS:
        (root / market).mkdir(parents=True)
        (root / market / "xgb.pkl").write_bytes(b"version-one")
        (root / market / "team_td_rate.json").write_text('{"kind": "v1"}')
    (root / "anytime_td" / "blend_weight.json").write_text(
        '{"kind": "blend_weight", "market_weight": 0.5}')
    monkeypatch.setattr(V, "models_root", lambda: root)
    return root


def _write(root, payload: bytes):
    for market in V.MARKETS:
        (root / market / "xgb.pkl").write_bytes(payload)


def test_lock_records_hashes_that_match_the_snapshot(sandbox):
    m = V.lock("2026.01.01-one", "first")
    for market in V.MARKETS:
        fitted, _ = V.split_runtime(
            V.hash_tree(V.version_dir("2026.01.01-one") / market))
        assert m["artifacts"][market] == fitted
        assert "xgb.pkl" in m["artifacts"][market]


def test_a_version_id_cannot_be_rebound(sandbox):
    """A version id is a claim that specific weights produced specific numbers.

    Silently rebinding it would make every ledger row referencing that id
    describe artifacts it never saw.
    """
    V.lock("2026.01.01-one", "first")
    _write(sandbox, b"something-else")
    with pytest.raises(V.VersionError, match="already exists"):
        V.lock("2026.01.01-one", "again")


@pytest.mark.parametrize("bad_id", ["baseline", "2026-01-01-x", "2026.01.01-",
                                    "2026.01.01-Caps"])
def test_version_ids_must_be_dated_and_slugged(sandbox, bad_id):
    with pytest.raises(V.VersionError, match="valid version id"):
        V.lock(bad_id, "note")


def test_keeping_a_degraded_change_demands_a_written_reason(sandbox):
    """The whole point of the third verdict: nothing degrades silently."""
    with pytest.raises(V.VersionError, match="requires a written justification"):
        V.lock("2026.01.01-one", "note", verdict="KEPT_WITH_JUSTIFICATION")

    m = V.lock("2026.01.01-one", "note", verdict="KEPT_WITH_JUSTIFICATION",
               justification="Brier +0.0004, inside the seed noise floor; "
                             "Top-1 +1.8pp paired.")
    assert m["justification"]


def test_promote_then_rollback_restores_the_earlier_bytes(sandbox):
    V.lock("2026.01.01-one", "first")
    V.promote("2026.01.01-one")

    _write(sandbox, b"version-two")
    V.lock("2026.01.02-two", "second")
    V.promote("2026.01.02-two")
    assert (sandbox / "anytime_td" / "xgb.pkl").read_bytes() == b"version-two"

    V.rollback()
    for market in V.MARKETS:
        assert (sandbox / market / "xgb.pkl").read_bytes() == b"version-one"
    current = json.loads(V.current_path().read_text())
    assert current["anytime_td"]["version"] == "2026.01.01-one"


def test_promotion_clears_artifacts_the_new_version_does_not_have(sandbox):
    """A merge would leave the previous version's files behind.

    A stale calibrator or rank_calibration.json keeps being loaded and quietly
    changes what is served, which is the failure this project has already had
    in other forms.
    """
    V.lock("2026.01.01-one", "first")
    for market in V.MARKETS:
        (sandbox / market / "stale_calibrator.pkl").write_bytes(b"leftover")
    V.lock("2026.01.02-two", "second")
    V.promote("2026.01.01-one")

    for market in V.MARKETS:
        assert not (sandbox / market / "stale_calibrator.pkl").exists()
    assert not V.verify_current()


def test_promotion_refuses_to_destroy_an_unlocked_retrain(sandbox):
    V.lock("2026.01.01-one", "first")
    V.promote("2026.01.01-one")
    _write(sandbox, b"a retrain nobody snapshotted")

    assert set(V.unlocked_markets()) == set(V.MARKETS)
    with pytest.raises(V.VersionError, match="match no locked version"):
        V.promote("2026.01.01-one")

    V.promote("2026.01.01-one", force=True)
    assert (sandbox / "anytime_td" / "xgb.pkl").read_bytes() == b"version-one"


def test_markets_can_be_promoted_independently(sandbox):
    V.lock("2026.01.01-one", "first")
    V.promote("2026.01.01-one")
    _write(sandbox, b"version-two")
    V.lock("2026.01.02-two", "second")

    # Both markets are snapshotted together, so at this point the live tree
    # holds version two for both. Take first_td forward and hold anytime_td
    # back — the case where a change helps one market and not the other.
    V.promote("2026.01.02-two", markets=("first_td",))
    V.promote("2026.01.01-one", markets=("anytime_td",))

    assert (sandbox / "first_td" / "xgb.pkl").read_bytes() == b"version-two"
    assert (sandbox / "anytime_td" / "xgb.pkl").read_bytes() == b"version-one"
    current = json.loads(V.current_path().read_text())
    assert current["first_td"]["version"] == "2026.01.02-two"
    assert current["anytime_td"]["version"] == "2026.01.01-one"
    assert not V.verify_current()


def test_verify_reports_a_retrain_that_landed_without_a_lock(sandbox):
    V.lock("2026.01.01-one", "first")
    V.promote("2026.01.01-one")
    assert V.verify_current() == []

    _write(sandbox, b"retrained in place")
    problems = V.verify_current()
    assert len(problems) == len(V.MARKETS)
    assert "differ from 2026.01.01-one" in problems[0]


def test_a_refit_blend_weight_is_recorded_but_does_not_fail_verification(sandbox):
    """`blend_weight.json` is refit at predict time, not train time.

    It moves every week the odds archive grows. Failing verification on it
    would train an operator to ignore the check, so it is recorded — with its
    value, since that is what tells you what the version was serving — and its
    drift is reported instead.
    """
    m = V.lock("2026.01.01-one", "first")
    V.promote("2026.01.01-one")
    assert "blend_weight.json" not in m["artifacts"]["anytime_td"]
    assert m["runtime"]["anytime_td"]["blend_weight.json"]["value"] == {
        "kind": "blend_weight", "market_weight": 0.5}

    (sandbox / "anytime_td" / "blend_weight.json").write_text(
        '{"kind": "blend_weight", "market_weight": 0.31}')

    assert V.verify_current() == []
    assert V.unlocked_markets() == []
    drift = V.runtime_drift()
    assert len(drift) == 1 and "blend_weight.json" in drift[0]


def test_registry_side_files_are_not_mistaken_for_manifests(sandbox):
    """The registry holds more than manifests, and will hold more over time.

    `CHAMPION.json`, `noise_floor.json` and the ledger live beside them. Reading
    every `*.json` as a version made `verify` raise KeyError the moment the
    experiment runner wrote its first side-file — a failure with no relationship
    to what the command was asked to do.
    """
    V.lock("2026.01.01-one", "first")
    V.promote("2026.01.01-one")
    (V.registry_root() / "noise_floor.json").write_text(
        '{"measured": "2026-01-01", "spread": {}}')
    (V.registry_root() / "CHAMPION.json").write_text('{"run": "some-run"}')
    (V.registry_root() / "ledger.jsonl").write_text('{"id": "x"}\n')

    assert [v["id"] for v in V.list_versions()] == ["2026.01.01-one"]
    assert V.verify_current() == []


def test_rollback_needs_somewhere_to_go(sandbox):
    V.lock("2026.01.01-one", "first")
    V.promote("2026.01.01-one")
    with pytest.raises(V.VersionError, match="no earlier version"):
        V.rollback()


def test_diff_reports_config_changes_between_versions(sandbox, monkeypatch):
    V.lock("2026.01.01-one", "first")
    real = V.get_config()
    monkeypatch.setattr(
        V, "get_config",
        lambda: {**real, "model": {**real["model"], "seed": 7}})
    _write(sandbox, b"version-two")
    V.lock("2026.01.02-two", "second")

    d = V.diff("2026.01.01-one", "2026.01.02-two")
    assert d["config_changes"]["model.seed"] == (real["model"]["seed"], 7)
    assert d["unpaired"] is True


# --------------------------------------------------------------------------
# Against the real repository
# --------------------------------------------------------------------------

def test_served_models_are_the_version_the_registry_claims():
    """`models/` must hold exactly what CURRENT.json says it holds.

    Without this, the committed record drifts from the weights on disk the
    first time someone runs `make train` and forgets to lock — and every
    manifest metric then describes a model nobody is serving.
    """
    if not V.current_path().exists():
        pytest.skip("no version promoted yet — `make lock` then `make promote`")
    problems = V.verify_current()
    assert not problems, (
        "Served artifacts do not match CURRENT.json:\n  "
        + "\n  ".join(problems)
        + "\n\nIf you retrained, lock the result "
          "(`make lock ID=YYYY.MM.DD-slug NOTE=\"...\"`) and promote it. If you "
          "did not, something overwrote models/ and the served state is "
          "unidentified."
    )


def test_versions_with_identical_weights_are_offered_once(sandbox):
    """A choice that cannot change the board is worse than no choice.

    Two of this project's four locked versions changed config or re-recorded
    metrics without retraining: `first-td-xgb` only switched which model is
    served, and `baseline-remeasured` only restated metrics after the
    denominator was corrected. Offering all four made the selector look broken
    — you pick a different version and nothing moves.
    """
    V.lock("2026.01.01-one", "first")
    V.promote("2026.01.01-one")
    V.lock("2026.01.02-config-only", "same weights, different config")

    every = V.available_versions("anytime_td")
    assert len(every) == 2, "the registry still holds both"

    offered = V.available_versions("anytime_td", distinct_weights=True)
    assert len(offered) == 1
    assert offered[0]["id"] == "2026.01.01-one", "the served version wins its group"
    assert offered[0]["duplicates"] == ["2026.01.02-config-only"]

    # A genuine retrain is a separate group and stays on the list.
    _write(sandbox, b"version-two")
    V.lock("2026.01.03-retrained", "actually different")
    offered = V.available_versions("anytime_td", distinct_weights=True)
    assert {v["id"] for v in offered} == {"2026.01.01-one", "2026.01.03-retrained"}


def test_pruning_deletes_only_duplicated_weights(sandbox):
    """Retire the redundant copy, never the only one.

    Four versions locked in one evening produced two distinct sets of weights:
    two of them changed config or re-recorded metrics without retraining. The
    duplicate snapshots are 2.2 MB each of bytes that already exist elsewhere.
    """
    V.lock("2026.01.01-one", "first")
    V.promote("2026.01.01-one")
    V.lock("2026.01.02-config-only", "same weights, different config")
    _write(sandbox, b"genuinely retrained")
    V.lock("2026.01.03-retrained", "different weights")

    dry = V.prune_duplicates(apply=False)
    assert [r["id"] for r in dry["removed"]] == ["2026.01.02-config-only"]
    assert V.version_dir("2026.01.02-config-only").exists(), "dry run must not delete"

    done = V.prune_duplicates(apply=True)
    assert done["bytes_freed"] > 0
    assert not V.version_dir("2026.01.02-config-only").exists()
    assert V.version_dir("2026.01.01-one").exists(), "the served copy survives"
    assert V.version_dir("2026.01.03-retrained").exists(), "unique weights survive"


def test_pruning_never_touches_a_manifest(sandbox):
    """The manifest is the committed record and the reason the version exists.

    Weights are regenerable in principle and duplicated in fact; the
    justification for a tripped guard is neither.
    """
    V.lock("2026.01.01-one", "first")
    V.promote("2026.01.01-one")
    V.lock("2026.01.02-config-only", "note that must survive",
           verdict="KEPT_WITH_JUSTIFICATION", justification="the reason")

    V.prune_duplicates(apply=True)
    manifest = V.load_manifest("2026.01.02-config-only")
    assert manifest["justification"] == "the reason"
    assert manifest["note"] == "note that must survive"
    assert [v["id"] for v in V.list_versions()] == [
        "2026.01.02-config-only", "2026.01.01-one"], "both still listed"


def test_a_pruned_version_says_where_its_bytes_went(sandbox):
    """Promoting one must not read as "your version is gone"."""
    V.lock("2026.01.01-one", "first")
    V.promote("2026.01.01-one")
    V.lock("2026.01.02-config-only", "same weights")
    V.prune_duplicates(apply=True)

    assert V.identical_snapshot("2026.01.02-config-only") == "2026.01.01-one"
    with pytest.raises(V.VersionError, match="byte-identical"):
        V.promote("2026.01.02-config-only")


def test_the_served_version_wins_its_group(sandbox):
    """Never prune what is running, whatever the ids sort like."""
    V.lock("2026.01.01-one", "first")
    V.promote("2026.01.01-one")
    V.lock("2026.01.09-later-duplicate", "same weights, newer id")

    dry = V.prune_duplicates(apply=False)
    assert dry["groups"][0]["keep"] == "2026.01.01-one"
    assert dry["groups"][0]["drop"] == ["2026.01.09-later-duplicate"]
