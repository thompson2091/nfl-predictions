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


def test_a_manifest_locked_before_a_file_became_runtime_still_matches(sandbox):
    """RUNTIME_ARTIFACTS grows, and old manifests were written under the old set.

    `2026.08.12-first-td-xgb` was locked before the cluster files were
    classified as runtime, so its manifest still lists them under `artifacts`.
    Filtering only the live side compared a fitted-only dict against one that
    still carried them, nothing matched, and `unlocked_markets` reported every
    market as never locked — printing "Lock them before promoting anything, or
    they are lost" directly above `verify_current` saying the artifacts match.

    Two guards disagreeing about the same files is worse than either being
    wrong alone: it teaches you to ignore both.
    """
    V.lock("2026.01.01-old", "locked before the classification changed")
    V.promote("2026.01.01-old")
    assert V.unlocked_markets() == []

    # Rewrite the manifest the way an older lock would have written it, with a
    # runtime artifact recorded among the fitted ones.
    path = V.registry_root() / "2026.01.01-old.json"
    manifest = json.loads(path.read_text())
    for market in V.MARKETS:
        runtime = manifest.get("runtime", {}).get(market, {})
        for name, entry in runtime.items():
            manifest["artifacts"][market][name] = entry["sha256"]
        manifest["runtime"][market] = {}
    path.write_text(json.dumps(manifest, indent=2))

    assert V.unlocked_markets() == [], (
        "a manifest predating the runtime classification must still match")
    assert V.verify_current() == [], "and the two guards must agree"


def test_a_promote_carries_the_numbers_with_the_weights():
    """`metrics.json` is the accuracy the app shows, and it used to be orphaned.

    Training writes it to `output/<market>/`, versions snapshot
    `models/<market>/`, and `promote` moved only the latter. Promoting the
    242-feature model therefore left the 318-feature model's accuracy on
    display. It is now locked with the weights it describes and restored
    beside them — but restored to `output/`, not `models/`, so it must not
    count as a missing artifact when the live directory is verified.
    """
    from src.models import versioning as V

    assert "metrics.json" in V.TRAINING_REPORTS

    fitted, runtime = V.split_runtime({
        "xgb.pkl": "a", "blend_weight.json": "b", "metrics.json": "c"})
    assert "metrics.json" not in fitted, (
        "a report restored to output/ would read as missing from models/")
    assert "metrics.json" not in runtime
    assert "xgb.pkl" in fitted and "blend_weight.json" in runtime


def test_every_locked_version_reports_metrics_from_its_own_feature_set():
    """The check that would have caught the mislabelled lock.

    A manifest reads its accuracy out of `walkforward.json`, which is one
    global file that whatever ran last overwrites. On 2026-08-19 a 242-feature
    version recorded 318-feature accuracy that way.
    """
    import json

    from src.models import versioning as V

    for path in sorted(V.registry_root().glob("2026.08.19-*.json")):
        m = json.loads(path.read_text())
        for market, metrics in (m.get("metrics") or {}).items():
            prov = (metrics or {}).get("_provenance") or {}
            locked = (m.get("features") or {}).get(market, {}).get("n")
            if not prov.get("n_features") or not locked:
                continue
            assert prov["n_features"] == locked, (
                f"{m['id']} / {market}: manifest reports accuracy measured on "
                f"{prov['n_features']} features for a model locked with "
                f"{locked}. The numbers describe a different model.")


def test_a_missing_optional_model_module_does_not_take_the_app_down():
    """`src/models/pairwise.py` was added and the container died at import.

    A bare `import` inside `ensure_registered` means any image whose source is
    one commit behind fails at startup with ModuleNotFoundError — for a model
    that is registered, inactive and rejected. The app cannot serve a board
    because a module nothing uses is absent.

    The registry itself is not cleared here. `importlib.import_module` returns a
    cached module without re-running its `@register` decorator, so clearing it
    would leave an empty registry that no re-import repopulates — which is a
    property of the import system, not of the code under test.
    """
    import importlib

    import src.models.registry as R

    real = importlib.import_module

    def missing(name, *a, **k):
        if name == "src.models.pairwise":
            raise ModuleNotFoundError("No module named 'src.models.pairwise'")
        return real(name, *a, **k)

    try:
        importlib.import_module = missing
        R.MISSING_OPTIONAL.clear()
        R.ensure_registered()          # must not raise
        assert "src.models.pairwise" in R.MISSING_OPTIONAL, (
            "a degraded registry must say so; silence is how a stale image "
            "goes unnoticed")
        assert "ModuleNotFoundError" in R.MISSING_OPTIONAL["src.models.pairwise"]

        def missing_required(name, *a, **k):
            if name == "src.models.xgboost_model":
                raise ModuleNotFoundError("no xgboost_model")
            return real(name, *a, **k)

        importlib.import_module = missing_required
        with pytest.raises(ModuleNotFoundError):
            R.ensure_registered()
    finally:
        importlib.import_module = real
        R.MISSING_OPTIONAL.clear()
        R.ensure_registered()

    assert {"lr", "lgbm", "xgb"} <= set(R.list_models())
    assert not R.MISSING_OPTIONAL, "everything imports in a complete checkout"


def test_every_registered_model_module_is_listed_in_one_of_the_two_tuples():
    """A module added to neither tuple would never register at all."""
    import pathlib as _p

    import src.models.registry as R

    listed = set(R.REQUIRED_MODEL_MODULES) | set(R.OPTIONAL_MODEL_MODULES)
    root = _p.Path(__file__).resolve().parents[1] / "src" / "models"
    on_disk = {f"src.models.{f.stem}" for f in root.glob("*.py")
               if f.stem not in {"__init__", "registry"}}
    # Only modules that actually call @register need listing.
    registering = {m for m in on_disk
                   if "@register(" in (root / f"{m.split('.')[-1]}.py").read_text()}
    assert registering <= listed, (
        f"these declare @register but are imported by nobody: "
        f"{sorted(registering - listed)}")


def test_promotion_does_not_silently_leave_artifacts_describing_another_model():
    """The sixth instance of the day's pattern, and the one that reached the app.

    `promote` swaps weights and nothing else. Backtest frames, rank economics,
    the walk-forward, CLV and the served prediction files all describe whichever
    model was live when they were written, and the app reads every one of them.
    On 2026-08-19 a promotion left three of those stale and only
    `test_served_path_matches_the_evaluated_path` noticed — by finding that the
    served probability matched NO stage of the evaluated path.

    Compared on modification time against `promoted_at`, so nothing needs a new
    format and anything regenerated afterwards is current whatever wrote it.
    """
    from src.models import versioning as V

    if not V.current_path().exists():
        pytest.skip("nothing promoted in this checkout")

    stale = V.stale_derived()
    assert isinstance(stale, list)
    for row in stale:
        assert {"market", "artifact", "version", "fix"} <= set(row), (
            "a staleness report without the command that fixes it gets ignored")
        assert row["fix"], f"{row['artifact']} has no regeneration command"

    # Every pattern must name a real command, or the report sends people nowhere.
    for pattern, fix in V.DERIVED_ARTIFACTS.items():
        assert fix.strip(), f"{pattern} has no fix"
        assert "make " in fix or "python scripts/" in fix, (
            f"{pattern} -> {fix!r} is not runnable")


def test_the_staleness_check_clears_once_an_artifact_is_regenerated(tmp_path,
                                                                    monkeypatch):
    """A check that never clears is a check people learn to ignore."""
    import json as _json
    from datetime import datetime, timedelta, timezone

    from src.models import versioning as V

    out = tmp_path / "output" / "anytime_td"
    out.mkdir(parents=True)
    cur = tmp_path / "CURRENT.json"
    promoted = datetime.now(timezone.utc).replace(microsecond=0)
    cur.write_text(_json.dumps({"anytime_td": {
        "version": "v1", "promoted_at": promoted.isoformat()}}))

    monkeypatch.setattr(V, "current_path", lambda: cur)
    monkeypatch.setattr(V, "get_path", lambda *a: out)

    old = out / "walkforward.json"
    old.write_text("{}")
    stamp = (promoted - timedelta(hours=1)).timestamp()
    import os
    os.utime(old, (stamp, stamp))
    assert any(r["artifact"] == "walkforward.json"
               for r in V.stale_derived(("anytime_td",))), "written before the promote"

    fresh = (promoted + timedelta(minutes=1)).timestamp()
    os.utime(old, (fresh, fresh))
    assert not V.stale_derived(("anytime_td",)), "regenerated after — must clear"


def test_the_freshness_guard_never_asks_for_a_played_week_to_be_rebuilt():
    """A GUARD THAT PRESCRIBED THE DISEASE.

    A promotion made every `predictions_<season>_week<w>.csv` look stale —
    weeks that finished a month ago included — and the fix it printed was
    `python scripts/06_predict.py --season <s> --week <w>`. On a played week
    that command does not refresh anything. It overwrites the board that was
    live with today's model scoring a game whose result is known, and the
    live odds cache holds no prices for a finished week, so the rebuilt board
    loses `has_market_price` for nearly everyone.

    That is not hypothetical: it is how weeks 3 and 4 of 2026 came to list 24
    and 47 priced players of about 500 each. The deploy refused to publish
    until somebody ran it, so the guard was pointing at the loaded foot.
    """
    from src.models.versioning import _is_a_record

    class P:
        def __init__(self, name):
            self.name = name

    # A week long finished is a record and is never owed a rebuild.
    assert _is_a_record(P("predictions_2026_week1.csv"))
    assert _is_a_record(P("predictions_2025_week9.csv"))
    # A week far in the future has not kicked off and still is.
    assert not _is_a_record(P("predictions_2026_week18.csv"))
    # And nothing else is exempted by accident.
    for other in ("backtest_2025.csv", "walkforward.json", "clv.json",
                  "rank_economics_xgb.json"):
        assert not _is_a_record(P(other)), other


def test_an_unreadable_schedule_does_not_advise_overwriting_a_board():
    """Unsure is not the same as owed. If the kickoff cannot be read the
    board counts as a record, because the cost of a wrong rebuild is a
    week of prices nothing can bring back."""
    import src.evaluation.tracked_rules as TR
    from src.models.versioning import _is_a_record

    class P:
        name = "predictions_2026_week7.csv"

    def boom(*a, **k):
        raise RuntimeError("no schedule")

    was = TR.week_has_started
    TR.week_has_started = boom
    try:
        assert _is_a_record(P())
    finally:
        TR.week_has_started = was


def test_a_kept_copy_is_not_an_unexpected_artifact():
    """`write_kept` snapshots into `history/` inside a served model directory.

    The snapshot machinery exists so the weight a board was served with last
    week survives this week's refit. It put those copies beside the file they
    snapshot, which is inside `models/<market>/` — so the first time the blend
    weight actually refit itself, `verify_current` reported two unexpected
    artifacts and the served state read as unidentified. A kept copy is as
    runtime as the file it is a copy of.
    """
    assert V._is_runtime("history/blend_weight.20261013T120025.json")
    assert V._is_runtime("history/edge_threshold.20261013T120025.json")
    # Nested one deeper, and under a market directory, both still runtime.
    assert V._is_runtime("anytime_td/history/blend_weight.20260101T000000.json")

    # And the exclusion is the directory, not the word: a fitted artifact that
    # merely has "history" in its filename is still enforced.
    assert not V._is_runtime("history_features.pkl")
    assert not V._is_runtime("anytime_td/xgb_history.pkl")
    # A file literally named `history` is a file, not a directory of kept
    # copies, so it is fitted until something says otherwise.
    assert not V._is_runtime("history")

    # The split follows, which is what `verify_current` actually reads.
    fitted, runtime = V.split_runtime({
        "xgb_model.pkl": "a",
        "blend_weight.json": "b",
        "history/blend_weight.20261013T120025.json": "c",
    })
    assert set(fitted) == {"xgb_model.pkl"}, fitted
    assert set(runtime) == {
        "blend_weight.json", "history/blend_weight.20261013T120025.json"}
