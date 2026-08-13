#!/usr/bin/env python3
"""Run an experiment against the champion and record the verdict.

An experiment is a config overlay in a small YAML file:

    id: 2026.08.13-depth4
    note: "xgb max_depth 6 -> 4"
    overlay:
      model:
        xgb:
          max_depth: 4

    python scripts/23_experiment.py baseline --id 2026.08.12-baseline-run
    python scripts/23_experiment.py screen experiments/depth4.yaml
    python scripts/23_experiment.py gate   experiments/depth4.yaml
    python scripts/23_experiment.py noise-floor --seeds 5
    python scripts/23_experiment.py compare <run-a> <run-b>
    python scripts/23_experiment.py ledger

Every run appends a row to `models/registry/ledger.jsonl`, which is committed.
A rejected experiment is as worth recording as a promoted one — it is what stops
the same idea being retried blind, and this project has already lost that
knowledge twice to stale comments.

Nothing here changes what is served. A verdict of PROMOTED means "adopt this
overlay into config/settings.yaml, retrain, and lock the result" — see
docs/MODEL_ITERATION.md and `scripts/22_version.py`.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation import compare as C  # noqa: E402
from src.evaluation import harness as H  # noqa: E402
from src.models.versioning import (  # noqa: E402
    current_path, git_state, registry_root)
from src.utils.config import get_config, production_model  # noqa: E402

LEDGER = "ledger.jsonl"
CHAMPION = "CHAMPION.json"
NOISE = "noise_floor.json"


# --------------------------------------------------------------------------
# Registry side-files
# --------------------------------------------------------------------------

def champion_drift(champion_ref: dict | None) -> list[str]:
    """Warn when the champion no longer describes what is being served.

    The gate measures a candidate against the champion's saved per-game rows.
    If a promotion has happened since those rows were written, the champion is
    the *old* model and every subsequent experiment is credited with the
    improvement that promotion already delivered.

    This is not hypothetical. The conditional-logit screen was first run against
    a champion recorded before the DEF/ST share fix was promoted, and reported
    +2.56pp on Top-1 for an overlay that changed nothing about the model it
    trained — the whole gain was the fix being re-credited. A stale champion
    does not fail; it flatters.
    """
    if not champion_ref:
        return []
    recorded = champion_ref.get("version")
    if not recorded:
        return []
    try:
        current = json.loads(current_path().read_text())
    except (OSError, json.JSONDecodeError):
        return []
    served = {(e or {}).get("version") for e in current.values()} - {None}
    if not served or recorded in served:
        return []
    return [
        f"\nSTALE CHAMPION: the champion run was recorded against "
        f"'{recorded}', but {' and '.join(sorted(served))} is being served.",
        "Every comparison below therefore includes whatever changed between "
        "them, credited to this experiment.",
        "Re-baseline before believing any verdict:  make champion ID=<id>",
    ]


def _read(name: str, default=None):
    path = registry_root() / name
    return json.loads(path.read_text()) if path.exists() else default


def _write(name: str, payload) -> Path:
    path = registry_root() / name
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def append_ledger(row: dict) -> Path:
    path = registry_root() / LEDGER
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")
    return path


def read_ledger() -> list[dict]:
    path = registry_root() / LEDGER
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_experiment(path: str) -> dict:
    spec = yaml.safe_load(Path(path).read_text()) or {}
    for key in ("id", "note"):
        if not spec.get(key):
            raise SystemExit(f"{path}: '{key}' is required")
    spec.setdefault("overlay", {})
    return spec


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------

def _run(overlay: dict, tier: str, markets, seed=None, models=None) -> dict:
    print(f"Running {tier} — markets {', '.join(markets)}"
          + (f", seed {seed}" if seed is not None else ""))
    return H.run(overlay, markets=markets, models=models, seed=seed)


def _print_summary(summary: dict) -> None:
    for market, models in summary.items():
        print(f"\n{market}")
        print(f"  {'model':10s} {'Top-1':>16s} {'Top-3':>8s} {'Top-5':>8s} "
              f"{'AUC':>8s} {'Brier':>9s} {'games':>7s} {'coinflip':>9s}")
        for name, s in models.items():
            print(f"  {name:10s} {s['top1']:>8.1%} +/-{s['top1_se']:<5.1%} "
                  f"{s['top3']:>7.1%} {s['top5']:>7.1%} {s['auc']:>8.4f} "
                  f"{s['brier']:>9.5f} {s['games']:>7d} "
                  f"{s['coin_flip_share']:>8.1%}")
        for name, s in models.items():
            if s["unranked_games"]:
                print(f"  note: {name} — {s['unranked_games']} of {s['games']} "
                      f"games had no ranked scorer (counted as misses)")
                break


def cmd_baseline(a) -> int:
    """Score the current config and make it the champion to compare against.

    A locked version's manifest carries pooled metrics, which cannot be paired.
    Comparison needs the per-game rows, so the champion is *run*, once, and its
    rows are kept.
    """
    markets = (a.market,) if a.market else H.MARKETS
    result = _run({}, "baseline (gate tier)", markets)
    summary = H.summarise(result)
    H.save(result, a.id)
    _print_summary(summary)

    _write(CHAMPION, {"run": a.id,
                      "version": (_read("CURRENT.json", {}) or {})
                      .get("anytime_td", {}).get("version"),
                      "recorded": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    append_ledger({
        "id": a.id, "kind": "baseline", "tier": "gate",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git": git_state(), "overlay": {}, "note": a.note,
        "feature_hash": result["meta"]["feature_hash"],
        "seed": result["meta"]["seed"], "summary": summary,
        "verdict": "CHAMPION", "comparisons": [],
    })
    print(f"\nChampion set to '{a.id}'. Experiments now compare against it.")
    return 0


def _experiment(a, tier: str) -> int:
    spec = load_experiment(a.experiment)
    markets = (a.market,) if a.market else H.MARKETS
    models = None
    if tier == "screen":
        # One market, and only the model it serves. Screening both markets with
        # whichever model the first one happens to want is a gate wearing a
        # screen's name — first TD serves the ensemble, which means training
        # everything.
        if a.market is None:
            markets = (get_config()["target"]["type"],)
        models = H.screen_models(markets[0], spec["overlay"])
        print(f"Screen tier: {markets[0]}, training {', '.join(models)}. "
              "A screen never promotes anything.")

    result = _run(spec["overlay"], tier, markets, models=models)
    summary = H.summarise(result)
    H.save(result, spec["id"])
    _print_summary(summary)

    champion_ref = _read(CHAMPION)
    for warning in champion_drift(champion_ref):
        print(warning)
    comparisons, verdict = [], "NO_CHAMPION"
    if champion_ref:
        try:
            champion = H.load(champion_ref["run"])
        except FileNotFoundError:
            champion = None
            print(f"\nChampion run '{champion_ref['run']}' has no saved rows — "
                  "re-run `23_experiment.py baseline`.")
        if champion is not None:
            noise = _read(NOISE)
            if noise is None:
                print("\nNo noise floor measured — guards fall back to the paired "
                      "standard error, and any AUC/Brier regression trips. Run "
                      "`make noise-floor` to fix that.")
            comparisons = C.compare_all(champion, result, noise=noise)
            print(f"\nAgainst champion '{champion_ref['run']}':\n")
            print(C.format_gate(comparisons))
            verdict = _overall_verdict(comparisons, markets)
    else:
        print("\nNo champion recorded — run `23_experiment.py baseline` first. "
              "Reporting this run's own numbers only.")

    row = {
        "id": spec["id"], "kind": "experiment", "tier": tier,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git": git_state(), "overlay": spec["overlay"], "note": spec["note"],
        "feature_hash": result["meta"]["feature_hash"],
        "seed": result["meta"]["seed"], "summary": summary,
        "champion": (champion_ref or {}).get("run"),
        "comparisons": comparisons, "verdict": verdict,
    }
    append_ledger(row)
    print(f"VERDICT: {verdict}")
    if tier == "screen" and verdict in ("PROMOTED", "GUARD_TRIPPED"):
        print("A screen cannot promote. Re-run as `gate` before acting on this.")
    elif verdict == "PROMOTED":
        print("Adopt the overlay into config/settings.yaml, `make train`, then "
              f"`make lock ID=... NOTE=\"{spec['note']}\"` and `make promote`.")
    elif verdict == "GUARD_TRIPPED":
        print("Top-1 improved but a guard regressed. Promote only with "
              "`--verdict KEPT_WITH_JUSTIFICATION --justification \"...\"`, which "
              "puts the reason in the version manifest.")
    return 0


def _overall_verdict(comparisons: list[dict], markets) -> str:
    """The verdict for the models each market actually serves.

    A change that helps a model nobody serves has not helped. Only the
    production model per market decides, and the worst outcome across them wins.
    """
    decisive = [c for c in comparisons
                if c["model"] == production_model(c["market"])
                and c["market"] in markets]
    if not decisive:
        return "NO_PRODUCTION_PAIR"
    order = ["REJECTED", "GUARD_TRIPPED", "PROMOTED"]
    return min((c["verdict"] for c in decisive), key=order.index)


def cmd_screen(a) -> int:
    return _experiment(a, "screen")


def cmd_gate(a) -> int:
    return _experiment(a, "gate")


def cmd_noise_floor(a) -> int:
    """Measure what the random seed alone is worth.

    Without this number there is no scale on which to read a 0.4-point
    difference, and every guard band in the gate is a guess.
    """
    markets = (a.market,) if a.market else H.MARKETS
    base_seed = get_config()["model"]["seed"]
    seeds = [base_seed] + [base_seed + i for i in range(1, a.seeds)]
    results = []
    for seed in seeds:
        run_id = f"{a.id}-seed{seed}"
        try:
            # Re-running a seed that is already on disk buys nothing and costs
            # minutes. Deleting output/experiments/<id> forces a fresh one.
            result = H.load(run_id)
            print(f"\n=== seed {seed}: reusing saved run '{run_id}' ===")
        except FileNotFoundError:
            print(f"\n=== seed {seed} ({len(results)+1} of {len(seeds)}) ===")
            result = _run({}, "noise floor", markets, seed=seed)
            H.save(result, run_id)
        results.append(result)

    # The base-seed run is the current config scored over the folds, which is
    # exactly what a champion is. Recording it here saves a duplicate six-minute
    # run, and a champion is required before any experiment can be compared.
    champion_run = f"{a.id}-seed{base_seed}"
    if a.set_champion or _read(CHAMPION) is None:
        _write(CHAMPION, {
            "run": champion_run,
            "version": (_read("CURRENT.json", {}) or {})
            .get("anytime_td", {}).get("version"),
            "recorded": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        append_ledger({
            "id": champion_run, "kind": "baseline", "tier": "gate",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "git": git_state(), "overlay": {},
            "note": f"Champion reference run (seed {base_seed}), from the noise "
                    f"floor measurement.",
            "feature_hash": results[0]["meta"]["feature_hash"],
            "seed": base_seed, "summary": H.summarise(results[0]),
            "verdict": "CHAMPION", "comparisons": [],
        })
        print(f"\nChampion set to '{champion_run}'.")

    floor = C.noise_floor(results)
    path = _write(NOISE, {"measured": datetime.now(timezone.utc)
                          .isoformat(timespec="seconds"),
                          "seeds": seeds, "git": git_state(), "spread": floor})
    print("\nSeed-to-seed standard deviation (the band a guard must clear):")
    for market, models in floor.items():
        print(f"\n{market}")
        for model, s in models.items():
            print(f"  {model:10s} Top-1 {s['top1']*100:5.2f}pp  "
                  f"Top-3 {s['top3']*100:5.2f}pp  AUC {s['auc']:.5f}  "
                  f"Brier {s['brier']:.5f}")
    print(f"\nSaved {path}  <- commit this")
    print("Any claimed gain below these numbers is the seed, not the change.")
    return 0


def cmd_compare(a) -> int:
    champion, candidate = H.load(a.a), H.load(a.b)
    rows = C.compare_all(champion, candidate, noise=_read(NOISE))
    print(f"{a.a} (champion)  ->  {a.b} (candidate)\n")
    print(C.format_gate(rows))
    return 0


def cmd_ledger(a) -> int:
    rows = read_ledger()
    if not rows:
        print("Ledger is empty.")
        return 0
    print(f"{'when':17s} {'tier':9s} {'verdict':16s} {'id':30s} note")
    print("-" * 110)
    for r in rows[-a.limit:]:
        print(f"{r['timestamp'][:16]:17s} {r.get('tier', '-'):9s} "
              f"{r.get('verdict', '-'):16s} {r['id']:30s} {r.get('note', '')}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("baseline", help="score the current config as the champion")
    p.add_argument("--id", required=True)
    p.add_argument("--note", default="Champion reference run.")
    p.add_argument("--market", choices=H.MARKETS, default=None)
    p.set_defaults(fn=cmd_baseline)

    for name, fn, helptext in (
        ("screen", cmd_screen, "fast tier: production model, one market"),
        ("gate", cmd_gate, "full tier: every model, both markets"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("experiment", help="path to the experiment YAML")
        p.add_argument("--market", choices=H.MARKETS, default=None)
        p.set_defaults(fn=fn)

    p = sub.add_parser("noise-floor", help="measure the seed-to-seed spread")
    p.add_argument("--seeds", type=int, default=5)
    p.add_argument("--id", default="noise-floor")
    p.add_argument("--market", choices=H.MARKETS, default=None)
    p.add_argument("--set-champion", action="store_true",
                   help="point CHAMPION.json at the base-seed run (done "
                        "automatically when no champion exists)")
    p.set_defaults(fn=cmd_noise_floor)

    p = sub.add_parser("compare", help="compare two saved runs")
    p.add_argument("a")
    p.add_argument("b")
    p.set_defaults(fn=cmd_compare)

    p = sub.add_parser("ledger", help="what has been tried")
    p.add_argument("--limit", type=int, default=40)
    p.set_defaults(fn=cmd_ledger)

    a = ap.parse_args()
    try:
        return a.fn(a)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
