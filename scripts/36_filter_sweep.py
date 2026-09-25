#!/usr/bin/env python3
"""Does trimming the candidate pool help? Swept on the clean matrix.

Phase 3f swept these thresholds on 2026-08-13 and rejected all of them
(`diagnostics/filter_sweep_anytime_td.json`). That is the same vintage that
made the 33-family ablation table wrong in both magnitude and SIGN — one family
read -2.74pp (p=0.006) before the leaks were closed and +1.50pp after — so
every verdict from that window is evidence about a matrix that no longer
exists. The condlogit re-test was run on the same grounds and confirmed its
original rejection; this asks the same of the filter.

**What the pool can and cannot do.** `make diagnose` on the clean matrix put
the ceiling at 99.9% of scored games: of 1,139 anytime-TD games, 8 have no
scorer in the pool and 1 had its scorer filtered out. So trimming cannot raise
the ceiling. It can still move Top-1 through two channels:

  - the model is refitted on the surviving rows, changing what it learns;
  - `joint.player_shares` normalizes within TEAM-GAME, so removing a player
    rescales his teammates by a common factor. That is monotone and cannot
    reorder teammates — it only moves cross-team comparisons, which is 51.5%
    of games (the other 48.5% have both top candidates on one team).

Both are real, and both are why this is worth re-running rather than assuming
the ceiling settles it.

Training already filters: `train_all` applies `_filter_low_activity` to train,
val and test alike, taking the pool from 48.6 to 29.2 candidates a game while
keeping 98.0% of actual scorers. So this sweeps a TIGHTER filter than the one
in place, not the introduction of one.

    python scripts/34_filter_sweep.py --market anytime_td
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation import compare as C  # noqa: E402
from src.evaluation import harness as H  # noqa: E402
from src.utils.config import production_model  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

#: The settings swept in Phase 3f, plus two the pool diagnosis suggests are
#: worth asking about now: a depth-chart cut, and usage tighter than either
#: 2026-08-13 value.
SWEEP = {
    "no-defst-pool": {"keep_defst": False},
    "usage-gt-0.5": {"min_usage": 0.5},
    "usage-gt-1.0": {"min_usage": 1.0},
    "usage-gt-2.0": {"min_usage": 2.0},
    "snap-gt-10pct": {"min_snap_pct": 0.1},
    "snap-gt-25pct": {"min_snap_pct": 0.25},
    "depth-rank-1": {"max_depth_chart_rank": 1},
}


def out_path(market: str) -> Path:
    return ROOT / "diagnostics" / f"filter_sweep_{market}.json"


def baseline_run(market: str, model: str):
    """The served filter, which every variant is paired against."""
    run_id = f"filter-baseline-{market}"
    try:
        result = H.load(run_id, markets=(market,))
        print(f"Baseline: reusing '{run_id}'")
        return result
    except FileNotFoundError:
        print(f"Baseline: running the served filter for {market}/{model}")
        result = H.run({}, markets=(market,), models=[model])
        H.save(result, run_id)
        return result


def variant(market: str, model: str, name: str, cfg: dict):
    run_id = f"filter-{market}-{name}"
    try:
        return H.load(run_id, markets=(market,))
    except FileNotFoundError:
        result = H.run({"candidate_filter": cfg}, markets=(market,), models=[model])
        H.save(result, run_id)
        return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", default="anytime_td", choices=H.MARKETS)
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()

    path = out_path(a.market)
    saved = json.loads(path.read_text()) if path.exists() else {}
    if a.show:
        report(saved, a.market)
        return 0

    current = H.feature_matrix_hash(a.market)
    # The 2026-08-13 file is a bare mapping with no hash, which is exactly the
    # shape that let a stale table read as current for five days.
    if saved and saved.get("feature_hash") != current:
        print(f"Feature matrix changed ({saved.get('feature_hash') or 'unrecorded'}"
              f" -> {current}); discarding "
              f"{len(saved.get('variants', saved))} row(s) measured on the old one.")
        saved = {}
    saved.setdefault("variants", {})
    saved["feature_hash"] = current

    model = production_model(a.market)
    base = baseline_run(a.market, model)
    noise = json.loads(
        (ROOT / "models" / "registry" / "noise_floor.json").read_text())["spread"]

    for i, (name, cfg) in enumerate(SWEEP.items(), 1):
        if name in saved["variants"]:
            print(f"[{i}/{len(SWEEP)}] {name}: already measured, skipping")
            continue
        print(f"\n[{i}/{len(SWEEP)}] {name}  {cfg}")
        result = variant(a.market, model, name, cfg)
        row = C.gate(C.compare(base, result, market=a.market, model=model,
                               noise=noise))
        t1 = row["top_k"][1]
        saved["variants"][name] = {
            "cfg": cfg, "top1_delta": t1["delta"], "se": t1["se"],
            "p_value": t1["p_value"], "wins": t1["wins"], "losses": t1["losses"],
            "top3_delta": row["top_k"][3]["delta"],
            "top5_delta": row["top_k"][5]["delta"],
            "verdict": row["verdict"],
        }
        saved["market"], saved["model"] = a.market, model
        saved["measured"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        path.write_text(json.dumps(saved, indent=2) + "\n")
        print(f"      Top-1 {t1['delta']*100:+.2f}pp ({t1['se_multiple']:+.2f} se, "
              f"p={t1['p_value']:.3f})  {row['verdict']}")

    report(saved, a.market)
    return 0


def report(saved: dict, market: str) -> None:
    rows = saved.get("variants") or {}
    if not rows:
        print(f"No filter sweep recorded for {market}.")
        return
    print(f"\nCandidate filter sweep — {market}/{saved.get('model')}, "
          f"measured {saved.get('measured')}")
    print("Paired per game against the SERVED filter. Negative = tighter is worse.\n")
    print(f"{'variant':16} {'d_top1':>8} {'se':>6} {'p':>6} {'d_top3':>8} "
          f"{'d_top5':>8}  verdict")
    for name, v in sorted(rows.items(), key=lambda kv: -kv[1]["top1_delta"]):
        print(f"{name:16} {v['top1_delta']*100:+8.2f} {v['se']*100:6.2f} "
              f"{v['p_value']:6.3f} {v['top3_delta']*100:+8.2f} "
              f"{v['top5_delta']*100:+8.2f}  {v['verdict']}")
    best = max(rows.values(), key=lambda v: v["top1_delta"])
    if best["verdict"] == "REJECTED":
        print("\nNothing beats the served filter. The pool ceiling is 99.9% of "
              "scored games, so there was little to win here — this rules out "
              "the two channels that could still have moved it.")


if __name__ == "__main__":
    raise SystemExit(main())
