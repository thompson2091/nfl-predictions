"""Locked model versions: snapshot, promote, roll back.

`models/` holds exactly one state. Every `make train` overwrites it, so the
model that was working on Tuesday is gone on Wednesday and there is no way
back — and the evidence for why a choice was made has, twice, survived only as
a code comment that later went stale. `production_model()` still describes
anytime TD as serving `lgbm` at 54.6% Top-1; `settings.yaml` records the
re-derived truth, `xgb` at 50.9%. Neither the weights nor the reasoning was
recoverable.

A **version** fixes both. It is a snapshot of every artifact both markets serve,
plus a manifest recording what produced it:

    models/
      anytime_td/                     what the pipeline and app read
      first_td/
      versions/2026.08.12-baseline/   the snapshot            (gitignored)
        anytime_td/*.pkl, *.json
        first_td/*.pkl, *.json
      registry/                       the record              (COMMITTED)
        2026.08.12-baseline.json
        CURRENT.json

The weights are too big and too regenerable to live in git; the manifest is
neither, so it does. What is committed is the full history of what was tried,
what won, and why — queryable forever, whether or not the weights survive.

Reproducing a version from its git SHA and config snapshot is *not* guaranteed
to be bit-identical, because nflverse revises historical play-by-play. That is
precisely why the weights are kept on disk and hashed: the manifest proves which
artifacts produced the metrics it claims.

`promote` and `rollback` are the same operation — copy a version over `models/`
and repoint `CURRENT.json`. One code path, so the rollback we hope never to need
cannot rot from disuse.
"""
from __future__ import annotations

import hashlib
import json
import pickle
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from src.utils.config import get_config
from src.utils.paths import PROJECT_ROOT, get_path

#: Both markets are snapshotted together. A version is a state of the *code and
#: config*, and those are shared; promotion is still per-market, so first TD can
#: move to a new version while anytime TD stays put.
MARKETS = ("first_td", "anytime_td")

#: Date-prefixed so `ls` sorts chronologically, slugged so it says what changed.
ID_PATTERN = re.compile(r"^\d{4}\.\d{2}\.\d{2}-[a-z0-9][a-z0-9._-]*$")

#: Artifacts that live in `models/` but are not fitted at training time.
#:
#: `blend_weight.json` is refit during *prediction*, from graded odds history
#: that grows every week the season is live (see `predict._anchor_to_market`).
#: `clusters_player.json` and `clusters_bet.json` are fitted by
#: `scripts/21_clusters.py`, which runs after training and is re-run on its own.
#:
#: All of them change without a retrain, so enforcing them byte-for-byte fails
#: verification after an ordinary `make predict` or `make clusters` — training
#: an operator to ignore the check, which is worse than not having one. Running
#: the clusters script is exactly what broke this check the first time.
#:
#: They are still recorded, with their contents inlined where they are small
#: enough to be worth reading, so a manifest says what the version was serving.
#: Drift is *reported* rather than failed.
RUNTIME_ARTIFACTS = frozenset({
    "blend_weight.json", "clusters_player.json", "clusters_bet.json",
})

#: Written to `output/<market>/` by training rather than to `models/<market>/`,
#: and describing exactly the weights that training produced. They are locked
#: with those weights and restored with them, because otherwise a promote moves
#: the model and leaves the numbers behind — which is how the app came to show
#: a 318-feature model's accuracy for the 242-feature one it was serving.
TRAINING_REPORTS = ("metrics.json",)

#: The three outcomes an experiment can have. `KEPT_WITH_JUSTIFICATION` is the
#: one that matters: a candidate may be promoted despite tripping a guard
#: metric, but only with a written reason, and the reason ships inside the
#: manifest. Nothing degrades silently.
VERDICTS = ("PROMOTED", "REJECTED", "KEPT_WITH_JUSTIFICATION")


class VersionError(RuntimeError):
    """A versioning operation that would lose or misrepresent artifacts."""


# --------------------------------------------------------------------------
# Locations
# --------------------------------------------------------------------------

def models_root() -> Path:
    return get_path("models")


def versions_root() -> Path:
    p = models_root() / "versions"
    p.mkdir(parents=True, exist_ok=True)
    return p


def registry_root() -> Path:
    p = models_root() / "registry"
    p.mkdir(parents=True, exist_ok=True)
    return p


def version_dir(version_id: str) -> Path:
    return versions_root() / version_id


def manifest_path(version_id: str) -> Path:
    return registry_root() / f"{version_id}.json"


def current_path() -> Path:
    return registry_root() / "CURRENT.json"


# --------------------------------------------------------------------------
# Hashing — what makes a claim about artifacts checkable
# --------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_tree(root: Path) -> dict[str, str]:
    """Every file under `root`, by path relative to it, hashed.

    Sorted so the mapping is stable across filesystems and comparable between
    a live directory and a snapshot of it.
    """
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): _sha256(p)
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def _is_runtime(relpath: str) -> bool:
    # A kept copy is as runtime as the file it is a copy of. `write_kept`
    # snapshots a refit-in-place artifact into `history/` beside it, so those
    # files appear in a served model directory and in no locked version —
    # which `verify_current` read as two unexpected artifacts the first time
    # the blend weight refit itself.
    parts = Path(relpath).parts
    if "history" in parts[:-1]:
        return True
    return Path(relpath).name in RUNTIME_ARTIFACTS


def _is_report(relpath: str) -> bool:
    return Path(relpath).name in TRAINING_REPORTS


def split_runtime(hashes: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """(fitted, runtime). Only the fitted half is enforced by `verify_current`.

    Training reports are dropped from both halves. They ride inside the version
    so a promote carries the numbers with the weights, but they are restored to
    `output/<market>/` rather than `models/<market>/` — so comparing a live
    model directory against a snapshot that contains them would report one
    missing file forever.
    """
    fitted = {k: v for k, v in hashes.items()
              if not _is_runtime(k) and not _is_report(k)}
    runtime = {k: v for k, v in hashes.items()
               if _is_runtime(k) and not _is_report(k)}
    return fitted, runtime


def _runtime_record(market_dir: Path, hashes: dict[str, str]) -> dict:
    """Runtime artifacts with their contents inlined — they are a few hundred
    bytes each, and the value is the whole point: a manifest that records a
    market weight of 0.42 tells you what the version was actually serving."""
    out = {}
    for rel, sha in hashes.items():
        entry: dict = {"sha256": sha}
        try:
            entry["value"] = json.loads((market_dir / rel).read_text())
        except (OSError, ValueError):
            entry["value"] = None
        out[rel] = entry
    return out


def live_hashes(markets=MARKETS) -> dict[str, dict[str, str]]:
    """Hashes of the artifacts currently being served out of `models/`."""
    return {m: hash_tree(models_root() / m) for m in markets}


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------

def git_state() -> dict:
    """The commit a version was built from, and whether the tree was dirty.

    A dirty tree is recorded rather than refused. Refusing would push people to
    commit noise just to lock a model; recording means the manifest never
    claims a clean provenance it does not have.
    """
    def run(*args: str) -> str | None:
        try:
            out = subprocess.run(args, cwd=PROJECT_ROOT, capture_output=True,
                                 text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    sha = run("git", "rev-parse", "HEAD")
    status = run("git", "status", "--porcelain")
    return {
        "sha": sha,
        "short_sha": sha[:7] if sha else None,
        "branch": run("git", "rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(status) if status is not None else None,
    }


def _feature_summary(market_dir: Path) -> dict | None:
    """How many features the snapshot trains on, and a hash of exactly which.

    The count alone cannot tell two feature sets apart; the hash can, so a
    version diff can say "same 319 columns" rather than guessing.
    """
    path = market_dir / "feature_cols.pkl"
    if not path.exists():
        return None
    cols = pickle.loads(path.read_bytes())
    digest = hashlib.sha256("\n".join(cols).encode()).hexdigest()
    return {"n": len(cols), "sha256": digest}


def pooled_walkforward(market: str) -> dict | None:
    """Games-weighted walk-forward metrics per model, from the saved folds.

    Read from `output/<market>/walkforward.json` rather than recomputed: this
    module records what was measured, it does not measure. A missing file is
    reported as missing rather than filled with a default, because a manifest
    that invents its own accuracy is worse than one that admits it has none.

    Standard errors are the binomial ones on the pooled games. They are wide —
    +/-1.5% on anytime TD — which is the whole reason the iteration plan puts
    paired testing ahead of any modeling change. See docs/MODEL_ITERATION.md.
    """
    path = get_path("output", market) / "walkforward.json"
    if not path.exists():
        return None
    from src.evaluation.harness import walkforward_rows
    rows, stamp = walkforward_rows(market)
    if not rows:
        return None
    stamped = stamp.get("feature_hash")

    provenance = {"measured": stamp.get("measured"),
                  "n_features": stamp.get("n_features"),
                  "feature_hash": stamped, "stale": None}
    try:
        from src.evaluation.harness import feature_matrix_hash
        current = feature_matrix_hash(market)
        provenance["stale"] = (stamped != current)
        if provenance["stale"]:
            print(f"  WARNING {market}: walkforward.json was measured on "
                  f"feature matrix {stamped or 'unrecorded'}, current is "
                  f"{current}. The metrics recorded in this manifest describe "
                  f"a different model. Re-run `make walkforward TARGET={market}`.")
    except Exception:                      # noqa: BLE001 - provenance is advisory
        pass

    out: dict[str, dict] = {}
    for name in sorted({r["model"] for r in rows}):
        sub = [r for r in rows if r["model"] == name]
        total = sum(r["games"] for r in sub)
        if total <= 0:
            continue
        agg = {k: sum(r[k] * r["games"] for r in sub) / total
               for k in ("top1", "top3", "top5", "auc", "brier")}
        agg["games"] = total
        agg["folds"] = sorted(r["test_season"] for r in sub)
        agg["top1_se"] = (agg["top1"] * (1 - agg["top1"]) / total) ** 0.5
        out[name] = {k: (round(v, 5) if isinstance(v, float) else v)
                     for k, v in agg.items()}
    if out:
        out["_provenance"] = provenance
    return out or None


# --------------------------------------------------------------------------
# Lock
# --------------------------------------------------------------------------

def lock(version_id: str, note: str, *, verdict: str = "PROMOTED",
         justification: str | None = None, parent: str | None = None,
         markets=MARKETS, experiment: dict | None = None) -> dict:
    """Snapshot what `models/` currently serves, and record what made it.

    Refuses to overwrite an existing version: a version id is a claim that a
    specific set of weights produced a specific set of numbers, and silently
    rebinding it makes every ledger row that references it a lie. Pick a new id.
    """
    if not ID_PATTERN.match(version_id):
        raise VersionError(
            f"'{version_id}' is not a valid version id. Use YYYY.MM.DD-slug, "
            "e.g. 2026.08.12-baseline.")
    if verdict not in VERDICTS:
        raise VersionError(f"verdict must be one of {VERDICTS}, got '{verdict}'")
    if verdict == "KEPT_WITH_JUSTIFICATION" and not justification:
        raise VersionError(
            "KEPT_WITH_JUSTIFICATION requires a written justification — that is "
            "the entire point of the verdict. What guard was tripped, and why is "
            "the change still worth it?")
    if manifest_path(version_id).exists() or version_dir(version_id).exists():
        raise VersionError(f"Version '{version_id}' already exists.")

    dest = version_dir(version_id)
    copied: dict[str, list[str]] = {}
    for market in markets:
        src = models_root() / market
        if not src.exists():
            raise VersionError(
                f"No artifacts for {market} at {src} — run `make train` first.")
        files = [p for p in sorted(src.iterdir()) if p.is_file()]
        if not files:
            raise VersionError(f"{src} holds no artifacts to lock.")
        (dest / market).mkdir(parents=True, exist_ok=True)
        for p in files:
            shutil.copy2(p, dest / market / p.name)
        copied[market] = [p.name for p in files]

        # `output/<market>/metrics.json` is the accuracy the app displays, and
        # it was the one artifact describing a model that lived outside the
        # version holding that model. Promoting swapped the weights and left
        # the numbers, so the app reported a 318-feature model's accuracy for a
        # 242-feature one. Snapshotted here and restored by `promote`.
        for extra in TRAINING_REPORTS:
            report = get_path("output", market) / extra
            if report.exists():
                shutil.copy2(report, dest / market / extra)
                copied[market].append(extra)

    manifest = {
        "id": version_id,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note,
        "verdict": verdict,
        "justification": justification,
        "parent": parent or _current_version(markets[0]),
        "git": git_state(),
        "markets": list(markets),
        "config": get_config(),
        "features": {m: _feature_summary(dest / m) for m in markets},
        "metrics": {m: pooled_walkforward(m) for m in markets},
        "experiment": experiment,
        "artifacts": {m: split_runtime(hash_tree(dest / m))[0] for m in markets},
        "runtime": {
            m: _runtime_record(dest / m, split_runtime(hash_tree(dest / m))[1])
            for m in markets
        },
    }
    manifest_path(version_id).write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def load_manifest(version_id: str) -> dict:
    path = manifest_path(version_id)
    if not path.exists():
        raise VersionError(f"No manifest for '{version_id}' at {path}")
    return json.loads(path.read_text())


def is_manifest(payload) -> bool:
    """Does this JSON describe a locked version?

    The registry holds more than manifests — `CURRENT.json`, `CHAMPION.json`,
    `noise_floor.json`, `ledger.jsonl` — and it will hold more over time. This
    identifies a manifest by its own shape rather than by a list of filenames
    to exclude, which would have to be updated every time something new is
    written beside them and would fail loudly the first time it was not.
    """
    return (isinstance(payload, dict) and isinstance(payload.get("id"), str)
            and isinstance(payload.get("artifacts"), dict))


def list_versions() -> list[dict]:
    """Every locked version, newest first, with its artifacts' presence noted."""
    out = []
    for path in sorted(registry_root().glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except ValueError:
            continue
        if not is_manifest(payload):
            continue
        payload["_artifacts_present"] = version_dir(payload["id"]).exists()
        out.append(payload)
    return sorted(out, key=lambda m: m["id"], reverse=True)


# --------------------------------------------------------------------------
# Promote / roll back — one operation, two names
# --------------------------------------------------------------------------

def _read_current() -> dict:
    path = current_path()
    return json.loads(path.read_text()) if path.exists() else {}


def _current_version(market: str) -> str | None:
    return (_read_current().get(market) or {}).get("version")


def market_dir(market: str, version_id: str | None = None) -> Path:
    """Where to load this market's artifacts from.

    `None`, or the version already being served, resolves to `models/<market>/`
    — the live directory, which is what the pipeline writes and the app reads
    by default. Any other version resolves into its snapshot.

    A snapshot is a record of what produced a set of numbers, so **nothing may
    write into one**. Callers pointed at a version other than the served one
    must pass `persist=False` down the prediction path, or the blend weight
    refit will rewrite the snapshot and the manifest's hashes will stop
    describing it.
    """
    if version_id is None or version_id == _current_version(market):
        return models_root() / market
    directory = version_dir(version_id) / market
    if not directory.exists():
        raise VersionError(
            f"Version '{version_id}' has no {market} artifacts on this machine "
            f"({directory}). Weights are gitignored, so a version locked "
            "elsewhere has a manifest here but no files.")
    return directory


#: Config sections that change how a model *scores*, and therefore have to be
#: restored when previewing a version. Everything else in the snapshot is left
#: alone deliberately.
#:
#: The manifest holds the whole of `settings.yaml`, and applying all of it would
#: restore settings that have nothing to do with the model and some that would
#: break the page doing it — `app.version_selector` would switch off the very
#: control being used, `paths` would point at wherever the machine that locked
#: the version kept its data, and `betting` would silently restake the board.
#:
#: What is here is what decides the number: which model serves each market, the
#: joint model's share rules, the first-TD path flags, the market blend, and the
#: season boundaries those are measured against.
SCORING_CONFIG_KEYS = ("models", "model", "joint", "first_td", "blend", "splits")


def scoring_config(version_id: str | None, market: str | None = None) -> dict:
    """The scoring-relevant config a version was locked with.

    Two of this project's model changes were config-only — switching first TD to
    xgb, and holding DEF/ST out of the offensive share denominator. A preview
    that restores weights but not settings cannot reproduce either of them, so
    those versions scored identically to what was being served and the version
    selector looked broken for the second time.

    Returns `{}` for no version, so callers can wrap unconditionally.
    """
    if not version_id:
        return {}
    try:
        manifest = load_manifest(version_id)
    except VersionError:
        return {}
    config = manifest.get("config") or {}
    current = get_config()

    out: dict = {}
    for key in SCORING_CONFIG_KEYS:
        if key in config:
            out[key] = config[key]
        elif key in current:
            # The version predates this setting existing. Merging would leave
            # today's value in place, which is the opposite of a preview:
            # `2026.08.12-baseline-remeasured` has no `joint` section at all, so
            # inheriting today's `exclude_defst_from_shares: true` would apply a
            # fix that version was locked before. An empty section restores the
            # default in force at the time, because that is what the code's own
            # `.get(key, default)` calls fall back to.
            out[key] = {}
    return out


def artifacts_key(manifest: dict, market: str) -> str:
    """Fingerprint of a version's weights for one market.

    Two versions can differ in every way that matters to the record — config,
    metrics, the reason they exist — and still carry byte-identical weights.
    `2026.08.12-first-td-xgb` changed only which model is served, and
    `2026.08.12-baseline-remeasured` only re-recorded metrics after the
    denominator was corrected. Neither retrained anything.
    """
    files = (manifest.get("artifacts") or {}).get(market, {})
    payload = "|".join(f"{k}:{v}" for k, v in sorted(files.items()))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def available_versions(market: str, distinct_weights: bool = False) -> list[dict]:
    """Versions whose artifacts are actually on disk, newest first.

    A manifest without weights cannot be loaded, so it is not offered. That is
    the normal state for a version locked on another machine.

    `distinct_weights` collapses versions that would score identically. Offering
    a choice that cannot change the board is worse than not offering it: the
    selector looks broken, and the natural conclusion is that version switching
    does not work rather than that these two versions are the same model. The
    served version wins its group so the list always contains what is running;
    otherwise the newest does.
    """
    served = _current_version(market)
    out = []
    for manifest in list_versions():
        if not (version_dir(manifest["id"]) / market).exists():
            continue
        out.append({
            "id": manifest["id"],
            "served": manifest["id"] == served,
            "note": manifest.get("note"),
            "created": manifest.get("created"),
            "metrics": (manifest.get("metrics") or {}).get(market),
            "artifacts_key": artifacts_key(manifest, market),
        })

    if not distinct_weights:
        return out

    kept: dict[str, dict] = {}
    for v in out:                       # already newest-first
        key = v["artifacts_key"]
        if key not in kept or v["served"]:
            if key in kept and kept[key]["served"]:
                continue
            kept[key] = v
    # `duplicates` records what was folded away, so the app can say so rather
    # than silently showing a shorter list than the registry holds.
    by_key: dict[str, list[str]] = {}
    for v in out:
        by_key.setdefault(v["artifacts_key"], []).append(v["id"])
    for v in kept.values():
        v["duplicates"] = [i for i in by_key[v["artifacts_key"]] if i != v["id"]]
    return sorted(kept.values(), key=lambda v: v["id"], reverse=True)


def snapshot_key(manifest: dict, markets=MARKETS) -> str:
    """Fingerprint of a version's weights across every market it holds."""
    return "|".join(artifacts_key(manifest, m) for m in markets)


def duplicate_groups(markets=MARKETS) -> list[dict]:
    """Versions whose snapshots are byte-identical, grouped.

    Four versions locked in one evening produced two distinct sets of weights:
    `2026.08.12-first-td-xgb` changed only which model is served, and
    `2026.08.12-baseline-remeasured` only re-recorded metrics after the
    denominator was corrected. Neither retrained anything, so each is a second
    copy of the snapshot above it.

    Grouping is by content, not by intent. A version that happens to reproduce
    an earlier one bit-for-bit is a duplicate however different the reason for
    locking it was — and the manifests keep those reasons regardless.
    """
    present = [m for m in list_versions() if version_dir(m["id"]).exists()]
    groups: dict[str, list[dict]] = {}
    for manifest in present:
        groups.setdefault(snapshot_key(manifest, markets), []).append(manifest)

    served = {(_read_current().get(m) or {}).get("version") for m in markets}
    out = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        ids = [m["id"] for m in members]
        # Keep what is being served; otherwise the newest, which is the one a
        # rollback is most likely to want and the one whose manifest describes
        # the most recent measurement of those weights.
        keep = next((i for i in ids if i in served), max(ids))
        out.append({
            "key": key,
            "keep": keep,
            "drop": sorted(i for i in ids if i != keep),
            "bytes": sum(p.stat().st_size
                         for i in ids if i != keep
                         for p in version_dir(i).rglob("*") if p.is_file()),
        })
    return sorted(out, key=lambda g: g["keep"], reverse=True)


def prune_duplicates(markets=MARKETS, apply: bool = False) -> dict:
    """Delete weight snapshots that another version already holds byte-for-byte.

    **Manifests are never touched.** They are the committed record — provenance,
    config snapshot, metrics, the justification for a guard that was tripped —
    and they are a few kilobytes each. What goes is the redundant copy of the
    weights, which is regenerable in principle and duplicated in fact.

    Nothing unique is ever deleted, and nothing served: a version survives
    pruning unless an identical snapshot remains on disk afterwards, so every
    manifest still resolves to retrievable weights.

    Defaults to a dry run. Deleting artifacts on the strength of a hash
    comparison is exactly the kind of thing to look at before doing.
    """
    groups = duplicate_groups(markets)
    removed, freed = [], 0
    for group in groups:
        for version_id in group["drop"]:
            directory = version_dir(version_id)
            if not directory.exists():
                continue
            size = sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())
            if apply:
                shutil.rmtree(directory)
            removed.append({"id": version_id, "identical_to": group["keep"],
                            "bytes": size})
            freed += size
    return {"applied": apply, "groups": groups, "removed": removed,
            "bytes_freed": freed}


def identical_snapshot(version_id: str, markets=MARKETS) -> str | None:
    """Another version whose weights match this one's, if any is on disk.

    Derived from the manifests rather than recorded at prune time, so a pruned
    version can still say where its bytes live without anyone having edited a
    committed record to say so.
    """
    try:
        target = load_manifest(version_id)
    except VersionError:
        return None
    key = snapshot_key(target, markets)
    for manifest in list_versions():
        if manifest["id"] == version_id or not version_dir(manifest["id"]).exists():
            continue
        if snapshot_key(manifest, markets) == key:
            return manifest["id"]
    return None


def current_version(market: str) -> dict | None:
    """What this market is serving, for anything that wants to display it.

    Returns the version id, when it was promoted, its git SHA, its recorded
    walk-forward metrics, and any mismatch between the manifest and the
    artifacts actually on disk. None when nothing has been promoted.
    """
    version_id = _current_version(market)
    if not version_id:
        return None
    try:
        manifest = load_manifest(version_id)
    except VersionError:
        return {"id": version_id, "known": False, "problems": [
            f"CURRENT.json names {version_id}, which has no manifest"]}
    entry = _read_current().get(market) or {}
    return {
        "id": version_id,
        "known": True,
        "promoted_at": entry.get("promoted_at"),
        "note": manifest.get("note"),
        "git": (manifest.get("git") or {}).get("short_sha"),
        "dirty": (manifest.get("git") or {}).get("dirty"),
        "metrics": (manifest.get("metrics") or {}).get(market),
        "problems": verify_current(markets=(market,)),
    }


def unlocked_markets(markets=MARKETS) -> list[str]:
    """Markets whose live artifacts match no locked version.

    Promotion overwrites `models/`. If what is there right now was never
    locked — a retrain nobody snapshotted — overwriting it destroys the only
    copy. This is what lets `promote` refuse instead.
    """
    live = live_hashes(markets)
    known = [m for m in list_versions() if m["_artifacts_present"]]
    out = []
    for market in markets:
        fitted, _ = split_runtime(live[market])
        matched = False
        for version in known:
            recorded = (version.get("artifacts") or {}).get(market)
            if not recorded:
                continue
            # Both sides through the same filter. Filtering only the live side
            # compares a fitted-only dict against one that still carries
            # clusters_*.json and blend_weight.json, so nothing ever matched and
            # this reported every market as unlocked — directly contradicting
            # `verify_current`, which had this same bug fixed earlier and says
            # the artifacts DO match. A guard that disagrees with its neighbour
            # about the same files teaches you to ignore both.
            if split_runtime(recorded)[0] == fitted:
                matched = True
                break
        if not matched:
            out.append(market)
    return out


def verify_current(markets=MARKETS) -> list[str]:
    """Problems with the claim that `models/` is the version CURRENT names.

    Returns a list of human-readable problems; empty means the served state is
    exactly the version the registry says it is. A retrain that lands without a
    lock shows up here, which is the point — the committed record should never
    quietly disagree with the weights on disk.

    Runtime artifacts are excluded; see `RUNTIME_ARTIFACTS` and `runtime_drift`.
    """
    current = _read_current()
    live = live_hashes(markets)
    problems = []
    for market in markets:
        entry = current.get(market)
        if not entry:
            problems.append(f"{market}: CURRENT.json names no version")
            continue
        try:
            manifest = load_manifest(entry["version"])
        except VersionError as e:
            problems.append(f"{market}: {e}")
            continue
        expected, _ = split_runtime(
            manifest.get("artifacts", {}).get(market, {}))
        fitted, _ = split_runtime(live[market])
        if expected != fitted:
            missing = sorted(set(expected) - set(fitted))
            extra = sorted(set(fitted) - set(expected))
            changed = sorted(f for f in set(expected) & set(fitted)
                             if expected[f] != fitted[f])
            problems.append(
                f"{market}: served artifacts differ from {entry['version']} — "
                f"{len(changed)} changed{' ' + str(changed) if changed else ''}, "
                f"{len(missing)} missing, {len(extra)} unexpected")
    return problems


def runtime_drift(markets=MARKETS) -> list[str]:
    """Runtime artifacts that have moved since the served version was locked.

    Informational, never a failure: `blend_weight.json` is *supposed* to move as
    graded odds history accumulates. Worth surfacing anyway, because "the model
    is identical but its market weight went from 0.50 to 0.31" is exactly the
    kind of change that alters every published probability while every hash the
    gate checks stays put.
    """
    current = _read_current()
    live = live_hashes(markets)
    notes = []
    for market in markets:
        entry = current.get(market)
        if not entry:
            continue
        try:
            manifest = load_manifest(entry["version"])
        except VersionError:
            continue
        recorded = (manifest.get("runtime") or {}).get(market, {})
        _, live_runtime = split_runtime(live[market])
        for rel, sha in sorted(live_runtime.items()):
            was = recorded.get(rel, {})
            if was.get("sha256") != sha:
                notes.append(
                    f"{market}: {rel} has changed since {entry['version']} was "
                    f"locked (expected, it is refit at predict time)")
    return notes


#: Artifacts derived from a trained model, written elsewhere in the pipeline,
#: and describing whichever model was live when they were produced. Promoting
#: swaps the weights and leaves every one of these behind.
#:
#: The value is the command that regenerates it. Keeping the two together is
#: the point: a warning that a file is stale without saying how to fix it gets
#: ignored, and this list is long enough that nobody remembers it.
DERIVED_ARTIFACTS = {
    "backtest_*.csv": "make evaluate",
    "rank_economics*.json": "python scripts/14_rank_economics.py --target {market}",
    "predictions_*.csv": "python scripts/06_predict.py --season <s> --week <w>",
    "walkforward.json": "make walkforward TARGET={market}",
    "clv.json": "python scripts/13_clv.py --target {market}",
}


def _is_orphan(path, market: str) -> bool:
    """Is this artifact one that nothing in the pipeline regenerates?

    Two kinds exist, and reporting them as stale is worse than useless: the
    warning never clears, so it stops being read and takes the real ones with
    it. `rank_economics_<model>.json` for a model this market does not serve
    needs backtest frames for that model, which no longer exist;
    `predictions_<season>_week<w>.csv` for a season outside the configured
    range is a one-off nobody will produce again.

    An orphan is not "fine" — it is a file that should probably be deleted.
    It is simply not a *staleness* problem, and conflating the two is how a
    permanent two-line warning trains an operator to ignore the banner.
    """
    from src.utils.config import get_config, production_model

    name = path.name
    if name.startswith("rank_economics_") and name.endswith(".json"):
        model = name[len("rank_economics_"):-len(".json")]
        return model != production_model(market)
    if name.startswith("predictions_"):
        try:
            season = int(name.split("_")[1])
        except (IndexError, ValueError):
            return False
        # Predictions are produced for the test season (parity checks) and the
        # predict season (the live board). `seasons.start` is the training
        # floor, not a prediction floor — reading it as one left a 2018 file
        # from an ad-hoc run blocking every export forever.
        cfg = get_config()
        lo = int((cfg.get("splits") or {}).get("test_season", 0))
        hi = int((cfg.get("seasons") or {}).get("predict_season", 9999))
        return not (lo <= season <= hi)
    return False


def _is_a_record(path) -> bool:
    """Is this a board that was published, rather than one owed a rebuild?

    **THIS GUARD USED TO DEMAND THE DISEASE.** A promotion made every
    `predictions_<season>_week<w>.csv` look stale, including weeks that
    finished a month ago, and the fix it printed was
    `python scripts/06_predict.py --season <s> --week <w>`. Running that on a
    played week does not refresh anything: it overwrites the board that was
    live with today's model scoring a game whose result is already known, and
    the live odds cache no longer prices a finished week, so the rebuilt
    board loses `has_market_price` for nearly everybody. That is precisely
    how weeks 3 and 4 of 2026 came to list 24 and 47 priced players of ~500,
    and it is what `src.export.prediction_freeze` exists to prevent.

    A past week's board is a RECORD. It is not derived from the served model
    and it must not be regenerated from it; it should disagree with today's
    model, because a different model produced it. Only a week that has not
    kicked off is owed a rebuild.

    A week whose kickoff cannot be read counts as a record, so the guard
    never advises overwriting a board it is unsure about.
    """
    m = re.match(r"predictions_(\d{4})_week(\d+)\.csv$", path.name)
    if not m:
        return False
    try:
        from src.evaluation.tracked_rules import week_has_started

        return week_has_started(int(m.group(1)), int(m.group(2)))
    except Exception:                                            # noqa: BLE001
        return True


def stale_derived(markets=MARKETS) -> list[dict]:
    """Derived artifacts written before the model they claim to describe.

    Promotion swaps weights and nothing else. On 2026-08-19 the backtest
    frames, rank economics and served predictions all still described the
    previous model after a promote, and the only thing that noticed was
    `test_served_path_matches_the_evaluated_path` — which found the served
    probability matched NO stage of the evaluated path. The app was one test
    run away from publishing a board whose accuracy figures belonged to a
    different model.

    Compared on modification time against `promoted_at`, so no artifact needs a
    new format and a file regenerated after the promotion is current whatever
    wrote it.
    """
    from datetime import datetime as _dt

    if not current_path().exists():
        return []
    current = json.loads(current_path().read_text())

    out = []
    for market in markets:
        entry = current.get(market) or {}
        stamp = entry.get("promoted_at")
        if not stamp:
            continue
        when = _dt.fromisoformat(stamp).timestamp()
        root = get_path("output", market)
        if not root.exists():
            continue
        for pattern, fix in DERIVED_ARTIFACTS.items():
            for path in sorted(root.glob(pattern)):
                if _is_orphan(path, market):
                    continue
                if _is_a_record(path):
                    continue
                if path.stat().st_mtime < when:
                    out.append({
                        "market": market, "artifact": path.name,
                        "version": entry["version"], "promoted_at": stamp,
                        "fix": fix.format(market=market),
                    })
    return out


def promote(version_id: str, markets=MARKETS, *, force: bool = False) -> dict:
    """Serve `version_id`: copy its artifacts over `models/` and repoint CURRENT.

    The live market directory is cleared before copying rather than merged into.
    A merge leaves artifacts from the previous version behind — a stale
    calibrator or rank calibration is exactly the kind of thing that keeps being
    loaded and quietly changes what is served.

    Refuses when the live artifacts belong to no locked version, so an
    un-snapshotted retrain cannot be destroyed by a promotion. `force` overrides,
    for when you know the live state is scrap.
    """
    manifest = load_manifest(version_id)
    src_root = version_dir(version_id)
    if not src_root.exists():
        twin = identical_snapshot(version_id)
        if twin:
            raise VersionError(
                f"'{version_id}' has no weights on disk, but "
                f"'{twin}' holds byte-identical ones — it was pruned as a "
                f"duplicate. Promote '{twin}' instead; it serves the same "
                "model. Their manifests differ only in why they were locked.")
        raise VersionError(
            f"Manifest for '{version_id}' exists but its artifacts do not, at "
            f"{src_root}. Weights are gitignored — this version was locked on "
            "another machine or the directory was cleaned. Retrain from "
            f"git {manifest.get('git', {}).get('short_sha')} with its config "
            "snapshot, or pick another version.")

    unlocked = unlocked_markets(markets)
    if unlocked and not force:
        raise VersionError(
            f"Live artifacts for {', '.join(unlocked)} match no locked version. "
            "Promoting would overwrite them and they are the only copy. Lock "
            "them first (`make lock ID=... NOTE=...`), or pass --force if they "
            "are scrap.")

    current = _read_current()
    for market in markets:
        src = src_root / market
        if not src.exists():
            raise VersionError(f"Version '{version_id}' holds no {market} artifacts.")
        dest = models_root() / market
        dest.mkdir(parents=True, exist_ok=True)
        for p in dest.iterdir():
            if p.is_file():
                p.unlink()
        for p in sorted(src.iterdir()):
            if not p.is_file():
                continue
            if p.name in TRAINING_REPORTS:
                # These belong beside the model's output, not among its weights.
                out = get_path("output", market)
                out.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, out / p.name)
                continue
            shutil.copy2(p, dest / p.name)

        entry = current.get(market, {})
        history = [v for v in entry.get("history", []) if v != version_id]
        history.append(version_id)
        current[market] = {
            "version": version_id,
            "promoted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "history": history,
        }

    current_path().write_text(json.dumps(current, indent=2) + "\n")
    return current


def rollback(markets=MARKETS, *, force: bool = False) -> dict:
    """Promote the version served before the current one, per market."""
    current = _read_current()
    targets = {}
    for market in markets:
        history = (current.get(market) or {}).get("history", [])
        if len(history) < 2:
            raise VersionError(
                f"{market} has no earlier version to roll back to "
                f"(history: {history or 'empty'}).")
        targets[market] = history[-2]

    distinct = set(targets.values())
    if len(distinct) > 1:
        # Per-market promotion is allowed, so the markets can genuinely sit on
        # different versions. Roll each back to its own predecessor.
        for market, version_id in targets.items():
            promote(version_id, markets=(market,), force=force)
        return _read_current()
    return promote(distinct.pop(), markets=markets, force=force)


# --------------------------------------------------------------------------
# Diff
# --------------------------------------------------------------------------

def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in (d or {}).items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def diff(version_a: str, version_b: str) -> dict:
    """What changed between two versions: config, features, and measured metrics.

    Metric deltas here are *unpaired* — two pooled numbers subtracted. They
    describe the versions; they do not decide between them. Promotion decisions
    need the paired comparison built in Phase 1 of docs/MODEL_ITERATION.md,
    because these pooled figures carry +/-1.5% of standard error and almost every
    change worth making is smaller than that.
    """
    a, b = load_manifest(version_a), load_manifest(version_b)
    fa, fb = _flatten(a.get("config", {})), _flatten(b.get("config", {}))
    config_changes = {
        k: (fa.get(k), fb.get(k))
        for k in sorted(set(fa) | set(fb)) if fa.get(k) != fb.get(k)
    }

    metrics = {}
    for market in MARKETS:
        ma = (a.get("metrics") or {}).get(market) or {}
        mb = (b.get("metrics") or {}).get(market) or {}
        rows = {}
        # `_provenance` shares this dict and is metadata, not a model row.
        for model in sorted(k for k in set(ma) | set(mb)
                            if not k.startswith("_")):
            ra, rb = ma.get(model), mb.get(model)
            rows[model] = {
                k: (None if not ra or not rb else round(rb[k] - ra[k], 5))
                for k in ("top1", "top3", "top5", "auc", "brier")
            }
            rows[model]["a"] = ra
            rows[model]["b"] = rb
        if rows:
            metrics[market] = rows

    return {
        "a": version_a,
        "b": version_b,
        "git": {"a": a.get("git"), "b": b.get("git")},
        "config_changes": config_changes,
        "features": {m: ((a.get("features") or {}).get(m),
                         (b.get("features") or {}).get(m)) for m in MARKETS},
        "metrics": metrics,
        "unpaired": True,
    }
