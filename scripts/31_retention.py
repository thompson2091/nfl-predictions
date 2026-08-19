#!/usr/bin/env python3
"""Build the feature set UP from a few families and see where Top-1 peaks.

The companion to `scripts/27_ablate.py`, and the test that script cannot run.
Leave-one-out ablation asks "does the model still rank as well without this
family", and 33 out of 33 answered "yes" — but that is the wrong direction for
the question "would FEWER features score better". Families are redundant with
each other by construction, so dropping one alone lets a correlated survivor
take over and the measurement reads zero however replaceable the family is.
Only building up from a small set measures whether the extra families are
earning their place.

Two curves are run, and the second is the point:

  ranked   the K families whose removal cost the most, from the ablation table
  random   K families drawn by a fixed seed, ignoring the ablation entirely

If the ranked curve does not beat the random one, the ordering carries nothing
and any peak on it is the fold noise being read as a result. This control is
here because Phase 3e was retracted for want of exactly this: 33 same-signed
deltas looked like evidence until injecting pure-noise columns reproduced them.

A second bias is deliberate and cannot be designed away here: the ranking comes
from ablations measured on these same walk-forward folds, so the ranked curve is
optimistically biased by construction. It is a screen for a candidate worth
gating, never a promotion.

    python scripts/31_retention.py --market anytime_td
    python scripts/31_retention.py --market anytime_td --show
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation import compare as C  # noqa: E402
from src.evaluation import harness as H  # noqa: E402
from src.utils.config import production_model  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = ROOT / "diagnostics" / "feature_families.json"

#: How many families to keep at each point on the curve. Dense between 18 and
#: 30, because that is where the curve actually peaked and a single-seed run
#: could not separate K=20 (+1.68pp) from K=25 (+1.33pp); the full 33 is the
#: baseline every point is paired against rather than a point on the curve.
LADDER = (3, 5, 8, 12, 16, 18, 20, 22, 24, 25, 26, 28, 30)
SEED = 20260819


def out_path(market: str) -> Path:
    return ROOT / "diagnostics" / f"retention_{market}.json"


def ranked_families(market: str) -> list[str]:
    """Families ordered by what their removal cost Top-1, dearest first."""
    path = ROOT / "diagnostics" / f"ablation_{market}.json"
    if not path.exists():
        raise SystemExit(
            f"{path} does not exist. Run `python scripts/27_ablate.py "
            f"--market {market}` first — the ranked curve is ordered by it.")
    saved = json.loads(path.read_text())
    current = H.feature_matrix_hash(market)
    if saved.get("feature_hash") != current:
        raise SystemExit(
            f"{path} was measured on feature matrix "
            f"{saved.get('feature_hash') or 'unrecorded'}, current is {current}. "
            f"Re-run `python scripts/27_ablate.py --market {market}`; ordering "
            "by a stale table would select families on a matrix that no longer "
            "exists.")
    rows = saved["families"]
    # Most negative delta = most missed when removed = ranked first.
    return sorted(rows, key=lambda f: rows[f]["top1_delta"])


def _full_set(market: str) -> dict:
    """Overlay that restores every family — the curve's baseline is the FULL set.

    Once a lean set is adopted in config, `H.run({})` trains that lean set, so
    every point would be paired against the answer instead of against the
    question.
    """
    return {"models": {"include_feature_families_by_target": {market: []},
                       "include_feature_families": []}}


def baseline_run(market: str, model: str):
    """The full-feature run every point on both curves is paired against."""
    run_id = f"retention-baseline-{market}"
    try:
        result = H.load(run_id, markets=(market,))
        print(f"Baseline: reusing '{run_id}'")
        return result
    except FileNotFoundError:
        print(f"Baseline: running full feature set for {market}/{model}")
        result = H.run(_full_set(market), markets=(market,), models=[model])
        H.save(result, run_id)
        return result


def keep_run(market: str, model: str, curve: str, k: int, families: list[str]):
    run_id = f"retention-{market}-{curve}-{k:02d}"
    try:
        return H.load(run_id, markets=(market,))
    except FileNotFoundError:
        # The PER-MARKET key, not the flat one. `included_families` reads
        # `include_feature_families_by_target` first, so once that is set in
        # config an overlay on the flat key is ignored outright and every point
        # on this curve would silently measure the adopted set.
        overlay = {"models": {
            "include_feature_families_by_target": {market: families},
            "include_feature_families": families}}
        result = H.run(overlay, markets=(market,), models=[model])
        H.save(result, run_id)
        return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", default="anytime_td", choices=H.MARKETS)
    ap.add_argument("--show", action="store_true",
                    help="print saved results without running anything")
    a = ap.parse_args()

    path = out_path(a.market)
    saved = json.loads(path.read_text()) if path.exists() else {"points": {}}

    if a.show:
        report(saved, a.market)
        return 0

    current = H.feature_matrix_hash(a.market)
    if saved.get("points") and saved.get("feature_hash") != current:
        print(f"Feature matrix changed ({saved.get('feature_hash') or 'unrecorded'}"
              f" -> {current}); discarding {len(saved['points'])} points "
              "measured on the old one.")
        saved = {"points": {}}
    saved["feature_hash"] = current

    order = ranked_families(a.market)
    shuffled = list(order)
    random.Random(SEED).shuffle(shuffled)
    mapping = json.loads(FAMILIES.read_text())["families"]

    model = production_model(a.market)
    base = baseline_run(a.market, model)
    noise = json.loads(
        (ROOT / "models" / "registry" / "noise_floor.json").read_text())["spread"]

    todo = [("ranked", k, order[:k]) for k in LADDER] + \
           [("random", k, shuffled[:k]) for k in LADDER]

    for i, (curve, k, families) in enumerate(todo, 1):
        key = f"{curve}-{k:02d}"
        if key in saved["points"]:
            print(f"[{i}/{len(todo)}] {key}: already measured, skipping")
            continue
        cols = sum(len(mapping[f]) for f in families)
        print(f"\n[{i}/{len(todo)}] {curve} top-{k} families ({cols} columns)")
        result = keep_run(a.market, model, curve, k, families)
        row = C.gate(C.compare(base, result, market=a.market, model=model,
                               noise=noise))
        t1 = row["top_k"][1]
        saved["points"][key] = {
            "curve": curve, "k": k, "families": families, "columns": cols,
            "top1_delta": t1["delta"], "top1_se": t1["se"],
            "p_value": t1["p_value"], "wins": t1["wins"], "losses": t1["losses"],
            "top3_delta": row["top_k"][3]["delta"],
            "top5_delta": row["top_k"][5]["delta"],
            "auc_delta": (row["row"].get("auc") or {}).get("delta"),
            "verdict": row["verdict"],
        }
        saved["market"], saved["model"] = a.market, model
        saved["measured"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(saved, indent=2) + "\n")
        print(f"      Top-1 {t1['delta']*100:+.2f}pp ({t1['se_multiple']:+.2f} se, "
              f"p={t1['p_value']:.3f})  {row['verdict']}")

    report(saved, a.market)
    return 0


def report(saved: dict, market: str) -> None:
    points = saved.get("points", {})
    if not points:
        print(f"No retention curve recorded for {market}.")
        return
    print(f"\nRetention curve — {market}/{saved.get('model')}, "
          f"measured {saved.get('measured')}")
    print("Deltas are against the FULL feature set, paired per game. "
          "Negative = the lean set is worse.\n")
    print(f"{'curve':8s} {'K':>3s} {'cols':>5s} {'d_top1':>8s} {'se':>6s} "
          f"{'p':>6s} {'d_top3':>8s} {'d_auc':>8s}  verdict")
    for curve in ("ranked", "random"):
        for key in sorted(k for k in points if points[k]["curve"] == curve):
            v = points[key]
            auc = f"{v['auc_delta']:+8.4f}" if v.get("auc_delta") is not None else "       -"
            print(f"{curve:8s} {v['k']:3d} {v['columns']:5d} "
                  f"{v['top1_delta']*100:+8.2f} {v['top1_se']*100:6.2f} "
                  f"{v['p_value']:6.3f} {v['top3_delta']*100:+8.2f} {auc}  "
                  f"{v['verdict']}")

    ranked = {v["k"]: v for v in points.values() if v["curve"] == "ranked"}
    rnd = {v["k"]: v for v in points.values() if v["curve"] == "random"}
    shared = sorted(set(ranked) & set(rnd))
    if shared:
        wins = sum(ranked[k]["top1_delta"] > rnd[k]["top1_delta"] for k in shared)
        print(f"\nOrdering control: the ranked curve beats the random one at "
              f"{wins} of {len(shared)} values of K.")
        if wins <= len(shared) / 2:
            print("  Ranking by ablation cost is carrying nothing here. Any "
                  "peak on the ranked curve is fold noise.")


if __name__ == "__main__":
    raise SystemExit(main())
