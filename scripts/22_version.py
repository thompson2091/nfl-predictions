#!/usr/bin/env python3
"""Lock, inspect, promote and roll back model versions.

`models/` holds one state and every retrain overwrites it. This is how a state
you liked survives the next `make train`, and how you get back to it.

    python scripts/22_version.py lock 2026.08.12-baseline --note "baseline lock"
    python scripts/22_version.py list
    python scripts/22_version.py show 2026.08.12-baseline
    python scripts/22_version.py promote 2026.08.12-baseline
    python scripts/22_version.py rollback
    python scripts/22_version.py diff 2026.08.12-baseline 2026.08.19-condlogit
    python scripts/22_version.py verify

Promotion is per-market (`--market first_td`) because the two markets do not
have to move together. Locking is not: a version is a state of the code and the
config, and those are shared.

See docs/MODEL_ITERATION.md for how versions, experiments and the promotion gate
fit together.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models.versioning import (  # noqa: E402
    MARKETS, VERDICTS, VersionError, current_path, diff, list_versions,
    load_manifest, lock, promote, registry_root, rollback, runtime_drift,
    unlocked_markets, verify_current, version_dir,
)


def _markets(arg: str | None) -> tuple[str, ...]:
    return MARKETS if not arg else (arg,)


def _metric_line(market: str, metrics: dict | None) -> str:
    if not metrics:
        return f"    {market:11s} no walk-forward metrics recorded"
    parts = []
    for model, m in metrics.items():
        parts.append(f"{model} {m['top1']:.1%}")
    return f"    {market:11s} Top-1  " + "  ".join(parts)


def cmd_lock(a) -> int:
    manifest = lock(a.id, a.note, verdict=a.verdict,
                    justification=a.justification, parent=a.parent)
    print(f"Locked {manifest['id']}")
    print(f"  git       {manifest['git'].get('short_sha')} "
          f"({manifest['git'].get('branch')})"
          + ("  [dirty tree]" if manifest["git"].get("dirty") else ""))
    print(f"  artifacts {version_dir(a.id)}")
    print(f"  manifest  {registry_root() / (a.id + '.json')}  <- commit this")
    for market in manifest["markets"]:
        n = len(manifest["artifacts"][market])
        feats = manifest["features"].get(market)
        print(f"  {market:11s} {n} files"
              + (f", {feats['n']} features" if feats else ""))
        print(_metric_line(market, (manifest["metrics"] or {}).get(market)))
    if manifest["verdict"] == "KEPT_WITH_JUSTIFICATION":
        print(f"\n  GUARD TRIPPED, kept anyway: {manifest['justification']}")
    if not a.promote:
        print("\nNot serving yet. `python scripts/22_version.py promote "
              f"{a.id}` to make it the default.")
        return 0
    return cmd_promote(argparse.Namespace(id=a.id, market=None, force=False))


def cmd_list(a) -> int:
    versions = list_versions()
    if not versions:
        print("No versions locked yet. `make lock ID=YYYY.MM.DD-slug NOTE=\"...\"`")
        return 0
    current = json.loads(current_path().read_text()) if current_path().exists() else {}
    serving = {m: (current.get(m) or {}).get("version") for m in MARKETS}

    print(f"{'':2s} {'version':28s} {'git':9s} {'verdict':24s} note")
    print("-" * 100)
    for v in versions:
        marks = "".join(
            {"first_td": "F", "anytime_td": "A"}[m]
            for m in MARKETS if serving.get(m) == v["id"]
        )
        flag = "*" if marks else " "
        missing = "" if v["_artifacts_present"] else "  [artifacts absent]"
        print(f"{flag}{marks:2s}{v['id']:28s} "
              f"{(v['git'].get('short_sha') or '-'):9s} "
              f"{v['verdict']:24s} {v.get('note', '')}{missing}")
    print("\n* = currently served.  F = first_td,  A = anytime_td")
    return 0


def cmd_show(a) -> int:
    m = load_manifest(a.id)
    if a.json:
        print(json.dumps(m, indent=2))
        return 0
    print(f"{m['id']}")
    print(f"  created   {m['created']}")
    print(f"  note      {m.get('note')}")
    print(f"  verdict   {m['verdict']}")
    if m.get("justification"):
        print(f"  because   {m['justification']}")
    print(f"  parent    {m.get('parent')}")
    print(f"  git       {m['git'].get('short_sha')} ({m['git'].get('branch')})"
          + ("  [dirty tree]" if m["git"].get("dirty") else ""))
    print(f"  artifacts {'present' if version_dir(a.id).exists() else 'ABSENT'} "
          f"at {version_dir(a.id)}")
    for market in m["markets"]:
        feats = (m.get("features") or {}).get(market)
        print(f"\n  {market}"
              + (f"  ({feats['n']} features, {feats['sha256'][:8]})" if feats else ""))
        metrics = (m.get("metrics") or {}).get(market)
        if not metrics:
            print("    no walk-forward metrics recorded")
            continue
        print(f"    {'model':10s} {'Top-1':>16s} {'Top-3':>8s} {'Top-5':>8s} "
              f"{'AUC':>8s} {'Brier':>9s} {'games':>7s}")
        for name, r in metrics.items():
            print(f"    {name:10s} {r['top1']:>8.1%} +/-{r['top1_se']:<5.1%} "
                  f"{r['top3']:>7.1%} {r['top5']:>7.1%} {r['auc']:>8.4f} "
                  f"{r['brier']:>9.5f} {r['games']:>7d}")
    if m.get("experiment"):
        print(f"\n  experiment {json.dumps(m['experiment'], indent=2)}")
    return 0


def cmd_promote(a) -> int:
    markets = _markets(a.market)
    current = promote(a.id, markets=markets, force=a.force)
    for market in markets:
        entry = current[market]
        prev = entry["history"][-2] if len(entry["history"]) > 1 else None
        print(f"{market:11s} now serving {entry['version']}"
              + (f"  (was {prev})" if prev else ""))
    print(f"\nUpdated {current_path()}  <- commit this")
    print("The app and pipeline read models/<market>/ directly, so this is live.")
    return 0


def cmd_rollback(a) -> int:
    markets = _markets(a.market)
    current = rollback(markets=markets, force=a.force)
    for market in markets:
        print(f"{market:11s} rolled back to {current[market]['version']}")
    print(f"\nUpdated {current_path()}  <- commit this")
    return 0


def cmd_diff(a) -> int:
    d = diff(a.a, a.b)
    print(f"{d['a']}  ->  {d['b']}")
    print(f"  git {d['git']['a'].get('short_sha')} -> {d['git']['b'].get('short_sha')}")

    print("\nConfig changes:")
    if not d["config_changes"]:
        print("  none")
    for key, (old, new) in d["config_changes"].items():
        print(f"  {key}: {old!r} -> {new!r}")

    print("\nFeatures:")
    for market, (fa, fb) in d["features"].items():
        if not fa or not fb:
            continue
        same = "same columns" if fa["sha256"] == fb["sha256"] else "DIFFERENT columns"
        print(f"  {market:11s} {fa['n']} -> {fb['n']}  ({same})")

    for market, rows in d["metrics"].items():
        print(f"\n{market} — walk-forward deltas (unpaired):")
        print(f"  {'model':10s} {'Top-1':>18s} {'Top-3':>10s} {'AUC':>11s} {'Brier':>11s}")
        for model, r in rows.items():
            if r["a"] is None or r["b"] is None:
                print(f"  {model:10s} {'(missing in one version)':>18s}")
                continue
            print(f"  {model:10s} {r['a']['top1']:>7.1%}->{r['b']['top1']:<6.1%}"
                  f"{r['top1']*100:+5.1f}pp "
                  f"{r['top3']*100:+9.1f}pp {r['auc']:+11.4f} {r['brier']:+11.5f}")

    print("\nThese are pooled, unpaired differences and carry roughly +/-1.5pp of "
          "standard error.\nThey describe the versions; they do not decide between "
          "them. Use the paired\ncomparison (docs/MODEL_ITERATION.md, Phase 1) for "
          "that.")
    return 0


def cmd_verify(a) -> int:
    problems = verify_current()
    current = json.loads(current_path().read_text()) if current_path().exists() else {}
    for market in MARKETS:
        entry = current.get(market) or {}
        print(f"{market:11s} CURRENT says {entry.get('version', '(none)')}")
    unlocked = unlocked_markets()
    if unlocked:
        print(f"\nLive artifacts match no locked version: {', '.join(unlocked)}")
        print("Lock them before promoting anything, or they are lost.")
    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\nServed artifacts match the versions CURRENT.json names.")
    for note in runtime_drift():
        print(f"  note: {note}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("lock", help="snapshot models/ as a new version")
    p.add_argument("id", help="version id, YYYY.MM.DD-slug")
    p.add_argument("--note", required=True, help="what changed, in one line")
    p.add_argument("--verdict", default="PROMOTED", choices=VERDICTS)
    p.add_argument("--justification", default=None,
                   help="required when a guard metric was tripped and the change "
                        "is kept anyway")
    p.add_argument("--parent", default=None,
                   help="version this was built from (defaults to what is served)")
    p.add_argument("--promote", action="store_true", help="also serve it")
    p.set_defaults(fn=cmd_lock)

    p = sub.add_parser("list", help="every locked version, newest first")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("show", help="one version's manifest")
    p.add_argument("id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("promote", help="serve a version")
    p.add_argument("id")
    p.add_argument("--market", choices=MARKETS, default=None)
    p.add_argument("--force", action="store_true",
                   help="overwrite live artifacts that were never locked")
    p.set_defaults(fn=cmd_promote)

    p = sub.add_parser("rollback", help="serve the previous version")
    p.add_argument("--market", choices=MARKETS, default=None)
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_rollback)

    p = sub.add_parser("diff", help="config, features and metrics between versions")
    p.add_argument("a")
    p.add_argument("b")
    p.set_defaults(fn=cmd_diff)

    p = sub.add_parser("verify", help="does models/ match what CURRENT.json claims")
    p.set_defaults(fn=cmd_verify)

    a = ap.parse_args()
    try:
        return a.fn(a)
    except VersionError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
