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

from src.evaluation import clv as CLV  # noqa: E402
from src.evaluation import compare as C  # noqa: E402
from src.evaluation import harness as H  # noqa: E402
from src.models.versioning import (  # noqa: E402
    current_path, git_state, registry_root)
from src.utils.config import get_config, production_model  # noqa: E402

LEDGER = "ledger.jsonl"
CHAMPION = "CHAMPION.json"
NOISE = "noise_floor.json"


def _noise_bands():
    """The per-(market, model) seed spread, in the shape `compare` reads.

    The file wraps the bands in a "spread" key alongside its provenance, and
    the gate used to hand `compare_all` the whole file. Every lookup then
    missed: `noise["anytime_td"]` is None when the bands live at
    `noise["spread"]["anytime_td"]`. Nothing failed loudly — the guards just
    silently fell back, Top-3/Top-5 to the paired standard error (far wider, so
    too permissive) and AUC/Brier to zero (so ANY regression tripped them,
    however many decimal places down). Every gate verdict that turned on an
    AUC or Brier guard was decided by that zero.
    """
    raw = _read(NOISE)
    if raw is None:
        return None
    return raw.get("spread", raw)


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
    # `keep_rows` because closing-line value is measured per player-game, not
    # per game, and the per-player probability is not recoverable from the
    # outcomes frame. Every experiment before this one was saved without it,
    # so none of them can be re-judged on CLV without re-running — which is the
    # whole reason it is on by default here rather than behind a flag. The cost
    # is about 3 MB of parquet per saved run.
    return H.run(overlay, markets=markets, models=models, seed=seed,
                 keep_rows=True)


def _print_clv(champion: dict | None, candidate: dict,
               comparisons: list[dict]) -> list[dict]:
    """Paired closing-line value beside the Top-K gate, on the same pairs.

    Reported, not gated. Top-1 stays the promotion rule; this is a second
    reading with roughly fifteen times the observations, which is what makes it
    worth printing next to a metric that cannot resolve a half-point. Where the
    two disagree, that is information about the change rather than a tie to be
    broken by whichever number is larger.
    """
    if champion is None:
        return []
    rows = []
    for c in comparisons:
        row = CLV.paired_clv(champion, candidate, market=c["market"],
                             model=c["model"], against=c.get("against"))
        if row is not None:
            rows.append(row)
    if not rows:
        print("\nClosing-line value: not measurable for this run — no "
              "open/close pairs overlap the folds it scored.")
        return []

    # A model the overlay did not touch scores identically on both sides, so
    # its row is all zeros. Those rows are a useful check that the pairing is
    # exact — and printing eight of them buries the two that changed. Counted
    # instead, which says the same thing in one line.
    moved = [r for r in rows if r["discordant"]]
    unchanged = len(rows) - len(moved)

    print("\nClosing-line value (reported, not gated):\n")
    last_market = None
    for row in sorted(moved, key=lambda r: (r["market"], r["model"])):
        if row["market"] != last_market:
            print(f"  {row['market']}")
            last_market = row["market"]
        print(CLV.format_clv(row))
    if unchanged:
        print(f"\n  {unchanged} model(s) scored identically on both sides — "
              "untouched by this overlay, and paired exactly.")
    if not moved:
        print("  Nothing moved.")
    return rows


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
    comparisons, verdict, clv_rows = [], "NO_CHAMPION", []
    if champion_ref:
        try:
            # `markets=` is the point: a champion recorded on an older feature
            # matrix compares as though the difference were the experiment. It
            # happened — 2026.08.17-champion-clv was gated against on
            # 2026-08-19 and reported -4.69pp on anytime Top-1, all of which
            # was the existence leak the champion still had and the candidate
            # did not.
            champion = H.load(champion_ref["run"], markets=tuple(markets))
        except H.StaleRun as stale:
            champion = None
            print(f"\nChampion is not comparable: {stale}\n"
                  "Re-record it with `make champion ID=<new-id>`; gating "
                  "against it would attribute the matrix change to this "
                  "experiment.")
        except FileNotFoundError:
            champion = None
            print(f"\nChampion run '{champion_ref['run']}' has no saved rows — "
                  "re-run `23_experiment.py baseline`.")
        if champion is not None:
            noise = _noise_bands()
            if noise is None:
                print("\nNo noise floor measured — guards fall back to the paired "
                      "standard error, and any AUC/Brier regression trips. Run "
                      "`make noise-floor` to fix that.")
            comparisons = C.compare_all(champion, result, noise=noise)
            print(f"\nAgainst champion '{champion_ref['run']}':\n")
            print(C.format_gate(comparisons))
            verdict = _overall_verdict(comparisons, markets)
            clv_rows = _print_clv(champion, result, comparisons)
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
        "comparisons": comparisons, "clv": clv_rows, "verdict": verdict,
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


def _overall_verdict(comparisons: list[dict], markets,
                     decisive_on: str = "model") -> str:
    """The verdict for the models each market actually serves.

    A change that helps a model nobody serves has not helped. Only the
    production model per market decides, and the worst outcome across them wins.

    `decisive_on` names which side of the comparison has to be the production
    model. A gate asks "is the served model better under this overlay", so the
    candidate's own name decides. A settle asks "should this replace what we
    serve", so the *champion* side is the served model and the candidate is by
    definition something else — reading `model` there finds no production pair
    at all and reports NO_PRODUCTION_PAIR for a run that decided something.
    """
    def _decides(c) -> bool:
        if c["market"] not in markets:
            return False
        prod = production_model(c["market"])
        if c[decisive_on] == prod:
            return True
        # An overlay that introduces a NEW model produces a row whose candidate
        # side is that model and whose champion side is the one being served.
        # That row is the decision — "should this replace what we serve" — and
        # reading only `model == prod` drops it. With the served model itself
        # reported UNCHANGED (the overlay does not alter it), the whole gate
        # then collapsed to NO_CHANGE and a tested-and-rejected model read as
        # though nothing had been tried.
        return (decisive_on == "model"
                and c.get("against") == prod and c["model"] != prod)

    decisive = [c for c in comparisons if _decides(c)]
    if not decisive:
        return "NO_PRODUCTION_PAIR"

    # A market the overlay never reached is excluded rather than counted as a
    # failure. Worst-of across markets is right when every market is under
    # test; applied to a per-market experiment it lets an untouched market veto
    # a real improvement, which is how lean-25-families read REJECTED while
    # promoting the model it targeted.
    scored = [c for c in decisive if c["verdict"] != "UNCHANGED"]
    if not scored:
        return "NO_CHANGE"
    order = ["REJECTED", "GUARD_TRIPPED", "PROMOTED"]
    return min((c["verdict"] for c in scored), key=order.index)


def cmd_screen(a) -> int:
    return _experiment(a, "screen")


def cmd_gate(a) -> int:
    return _experiment(a, "gate")


def cmd_settle(a) -> int:
    """Decide a close call by averaging each game's outcome across seeds.

    A single paired run cannot separate a real few-tenths gain from the seed.
    This runs the same overlay at N seeds, averages each game's hit indicator
    across them, and pairs on the averages — the test that settled first TD's
    production model, which was done by hand and therefore never again.

    Both models come from the *same* run, so folds, features and seed are
    identical on each side and the only difference is the model.
    """
    spec = load_experiment(a.experiment)
    markets = (a.market,) if a.market else H.MARKETS
    base_seed = get_config()["model"]["seed"]
    seeds = [base_seed + i for i in range(a.seeds)]

    runs = []
    for seed in seeds:
        run_id = f"{spec['id']}-seed{seed}"
        try:
            runs.append(H.load(run_id, markets=tuple(markets)))
            print(f"seed {seed}: reusing saved run '{run_id}'")
        except FileNotFoundError:
            print(f"\n=== seed {seed} ({len(runs) + 1} of {len(seeds)}) ===")
            result = _run(spec["overlay"], "settle", markets, seed=seed)
            H.save(result, run_id)
            runs.append(result)

    rows = [C.seed_gate(runs, market=m, model=a.model, against=a.against)
            for m in markets]
    print("\nSeed-averaged paired comparison:\n")
    print(C.format_seed_gate(rows))

    append_ledger({
        "id": spec["id"], "kind": "experiment", "tier": "settle",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git": git_state(), "overlay": spec["overlay"],
        "note": f"{a.model} vs {a.against}, {a.seeds} seeds, seed-averaged: "
                + spec.get("note", ""),
        "seed": seeds, "summary": {},
        "verdict": _overall_verdict(rows, markets, decisive_on="against"),
        "comparisons": [{k: v for k, v in r.items() if k != "top_k"}
                        | {"top1": {kk: vv for kk, vv in r["top_k"][1].items()
                                    if kk != "per_seed"}} for r in rows],
    })
    return 0


def cmd_settle_overlay(a) -> int:
    """Settle an overlay against the champion recipe, seed by matched seed.

    `settle` compares two MODELS inside one run, which cannot judge a config
    change — both sides of a feature-set experiment carry the same model name.
    This runs the overlay at N seeds and pairs each against the champion recipe
    at the SAME seed, then averages per game before pairing.

    The baseline side is the noise-floor runs, which are the champion config at
    seeds 42..46 and already on disk. That is the point: a change worth
    promoting has to beat the recipe it replaces at every seed, not at the one
    seed a single gate happened to use. lean-25-families read +1.33pp on Top-1
    against a seed band of 0.64pp, which is suggestive and not settled.
    """
    spec = load_experiment(a.experiment)
    markets = (a.market,) if a.market else H.MARKETS
    base_seed = get_config()["model"]["seed"]
    seeds = [base_seed + i for i in range(a.seeds)]

    baseline, candidate = [], []
    for seed in seeds:
        base_id = f"{a.baseline}-seed{seed}"
        try:
            baseline.append(H.load(base_id, markets=tuple(markets)))
        except FileNotFoundError as missing:
            raise SystemExit(
                f"{missing}\nThe baseline side must exist at every seed. Run "
                f"`make noise-floor SEEDS={a.seeds}` first.") from None

        run_id = f"{spec['id']}-settle-seed{seed}"
        try:
            candidate.append(H.load(run_id, markets=tuple(markets)))
            print(f"seed {seed}: reusing saved run '{run_id}'")
        except FileNotFoundError:
            print(f"\n=== seed {seed} ({len(candidate) + 1} of {len(seeds)}) ===")
            result = _run(spec["overlay"], "settle-overlay", markets, seed=seed)
            H.save(result, run_id)
            candidate.append(result)

    rows = []
    for market in markets:
        model = production_model(market)
        rows.append(C.seed_gate(candidate, market=market, model=model,
                                against=model, against_runs=baseline))
    print("\nSeed-averaged, overlay vs champion recipe at matched seeds:\n")
    print(C.format_seed_gate(rows))

    append_ledger({
        "id": spec["id"], "kind": "experiment", "tier": "settle-overlay",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git": git_state(), "overlay": spec["overlay"],
        "note": f"overlay vs '{a.baseline}' recipe, {a.seeds} seeds, "
                f"seed-averaged: " + spec.get("note", ""),
        "seed": seeds, "summary": {},
        "verdict": _overall_verdict(rows, markets, decisive_on="model"),
        "comparisons": [{k: v for k, v in r.items() if k != "top_k"}
                        | {"top1": {kk: vv for kk, vv in r["top_k"][1].items()
                                    if kk != "per_seed"}} for r in rows],
    })
    return 0


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
            # minutes — but only while the matrix it was measured on is still
            # the current one. `markets=` makes that a check rather than an
            # assumption: this reused its 2026-08-12 runs on 2026-08-19 and
            # reprinted the leaked matrix's bands as a fresh measurement.
            result = H.load(run_id, markets=tuple(markets))
            print(f"\n=== seed {seed}: reusing saved run '{run_id}' ===")
        except H.StaleRun as stale:
            print(f"\n=== seed {seed}: re-measuring, saved run is stale ===\n"
                  f"    {stale}")
            result = _run({}, "noise floor", markets, seed=seed)
            H.save(result, run_id)
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
    # Neither side has to be current — comparing two archived runs to each
    # other is legitimate. They do have to match EACH OTHER: a pairing across
    # two feature matrices attributes the matrix change to whatever else
    # differs, which is how a leaked champion read as -4.69pp on 2026-08-19.
    champion, candidate = H.load(a.a), H.load(a.b)
    ha = champion["meta"].get("feature_hash") or {}
    hb = candidate["meta"].get("feature_hash") or {}
    clash = sorted(m for m in set(ha) & set(hb) if ha[m] != hb[m])
    if clash or not (ha and hb):
        detail = ", ".join(f"{m}: {ha[m]} vs {hb[m]}" for m in clash) or \
            "one or both runs recorded no feature hash"
        print(f"WARNING: these runs were not measured on the same feature "
              f"matrix ({detail}). Every difference below includes that one.\n")
    rows = C.compare_all(champion, candidate, noise=_noise_bands())
    print(f"{a.a} (champion)  ->  {a.b} (candidate)\n")
    print(C.format_gate(rows))
    # Silently absent for runs saved before `keep_rows` was on by default,
    # which is every run up to 2026-08-17 — those have outcomes but no
    # per-player probability, and CLV cannot be reconstructed from a per-game
    # hit indicator. Re-run the experiment to get it.
    _print_clv(champion, candidate, rows)
    return 0


def cmd_note(a) -> int:
    """Record the WRITTEN verdict for a line of experiments.

    The ground rule in docs/MODEL_ITERATION.md is that REJECTED "stays in the
    ledger so nobody retries it blind" — and a row of numbers does not stop
    anyone. It says a thing did not work; it does not say why, and the why is
    the part that decides whether the next person should try a variant or drop
    the idea.

    The runs log themselves. This logs the reading of them, against the run ids
    it covers, so `ledger` shows the conclusion beside the evidence rather than
    in someone's memory.
    """
    covers = [x.strip() for x in (a.covers or "").split(",") if x.strip()]
    known = {r["id"] for r in read_ledger()}
    unknown = [c for c in covers if c not in known]
    if unknown:
        # A note pointing at runs that do not exist is worse than no note: it
        # reads as evidence and is not.
        raise SystemExit(
            f"these ids are not in the ledger: {unknown}. A written verdict "
            f"has to reference runs that happened.")

    text = a.text
    if a.text_file:
        text = Path(a.text_file).read_text().strip()
    if not text:
        raise SystemExit("a written verdict needs text; pass --text or --text-file")

    row = {
        "id": a.id, "kind": "note", "tier": "note",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git": git_state(),
        "verdict": a.verdict,
        "note": a.summary,
        "covers": covers,
        "doc": a.doc,
        "text": text,
    }
    append_ledger(row)
    print(f"Recorded {a.verdict} for {a.id}")
    if covers:
        print(f"  covering: {', '.join(covers)}")
    if a.doc:
        print(f"  written up in: {a.doc}")
    print()
    print(text)
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

    p = sub.add_parser(
        "settle", help="decide a close call by averaging outcomes across seeds")
    p.add_argument("experiment", help="path to the experiment YAML")
    p.add_argument("--model", required=True,
                   help="the candidate model within each run, e.g. ensemble")
    p.add_argument("--against", required=True,
                   help="what to pair it against, e.g. xgb")
    p.add_argument("--seeds", type=int, default=5)
    p.add_argument("--market", choices=H.MARKETS, default=None)
    p.set_defaults(fn=cmd_settle)

    p = sub.add_parser("settle-overlay",
                       help="seed-averaged overlay vs champion recipe")
    p.add_argument("experiment")
    p.add_argument("--market", choices=H.MARKETS)
    p.add_argument("--seeds", type=int, default=5)
    p.add_argument("--baseline", default="noise-floor",
                   help="run-id prefix of the baseline side (default: the "
                        "noise-floor runs, which are the champion recipe)")
    p.set_defaults(fn=cmd_settle_overlay)

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

    p = sub.add_parser(
        "note", help="record the written verdict for a line of experiments")
    p.add_argument("--id", required=True)
    p.add_argument("--verdict", required=True,
                   choices=["REJECTED", "PROMOTED", "KEPT_WITH_JUSTIFICATION",
                            "INCONCLUSIVE"])
    p.add_argument("--summary", required=True, help="one line, shown by `ledger`")
    p.add_argument("--covers", default="",
                   help="comma-separated run ids this verdict reads")
    p.add_argument("--doc", default=None, help="where it is written up in full")
    p.add_argument("--text", default=None)
    p.add_argument("--text-file", default=None,
                   help="read the written verdict from a file")
    p.set_defaults(fn=cmd_note)

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
