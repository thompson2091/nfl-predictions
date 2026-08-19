#!/usr/bin/env python3
"""Drop one feature family at a time and see what the model misses.

Phase 3e in docs/MODEL_ITERATION.md. 319 features come from 33 builder modules,
and the question this answers is not "which features matter" — importance
scores answer that, badly — but "which families does the model still rank as
well without". Those two differ because a family the model leans on heavily can
still be replaceable: retrained without it, correlated survivors take over. Only
retraining measures that, which is why this ablates rather than permutes.

Every family is scored on the same folds as the champion and compared **per
game**, because pooled Top-1 carries +/-1.5% and cannot resolve a family worth
half a point. A family whose removal changes nothing is a family to consider
dropping: fewer features is variance reduction even at equal Top-1, and it is
one less thing to build, cache and go stale.

    python scripts/27_ablate.py --market anytime_td
    python scripts/27_ablate.py --market anytime_td --family build_qb_features
    python scripts/27_ablate.py --show

Each family is one full walk-forward of the production model, so a whole market
is roughly 33 of those. Results are written per family, so an interrupted run
resumes rather than restarting.
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
FAMILIES = ROOT / "diagnostics" / "feature_families.json"


def out_path(market: str) -> Path:
    return ROOT / "diagnostics" / f"ablation_{market}.json"


def load_families() -> dict[str, list[str]]:
    if not FAMILIES.exists():
        raise SystemExit(
            f"{FAMILIES} does not exist. Run `python "
            "scripts/26_feature_families.py` first — it records which builder "
            "produced each column, which cannot be recovered from the names.")
    return json.loads(FAMILIES.read_text())["families"]


def _full_set(market: str) -> dict:
    """Overlay that restores every family, whatever config currently serves.

    An ablation asks "what does dropping this family from the FULL set cost".
    Once a lean set is adopted in `config/settings.yaml` the baseline would
    otherwise be that lean set, and each ablated run would drop a family from
    it — a different question, silently substituted, and one whose answer
    cannot order a retention curve built from the full set.

    An empty LIST, not an empty dict: `config_overlay` deep-merges, so `{}`
    merges to nothing and leaves the allow-list in place.
    """
    return {"models": {"include_feature_families_by_target": {market: []},
                       "include_feature_families": []}}


def baseline_run(market: str, model: str):
    """The full-feature run every ablation is paired against.

    Re-run rather than reused from the champion: the champion may have been
    recorded under a different config, and a comparison is only paired if both
    sides saw the same folds under the same settings.
    """
    run_id = f"ablation-baseline-{market}"
    try:
        result = H.load(run_id, markets=(market,))
        print(f"Baseline: reusing '{run_id}'")
        return result
    except FileNotFoundError:
        print(f"Baseline: running full feature set for {market}/{model}")
        result = H.run(_full_set(market), markets=(market,), models=[model])
        H.save(result, run_id)
        return result


def ablate(market: str, family: str, model: str):
    run_id = f"ablation-{market}-{family}"
    try:
        return H.load(run_id, markets=(market,)), True
    except FileNotFoundError:
        overlay = _full_set(market)
        overlay["models"]["exclude_feature_families"] = [family]
        result = H.run(overlay, markets=(market,), models=[model])
        H.save(result, run_id)
        return result, False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", default="anytime_td", choices=H.MARKETS)
    ap.add_argument("--family", default=None,
                    help="ablate one family instead of all of them")
    ap.add_argument("--show", action="store_true",
                    help="print saved results without running anything")
    a = ap.parse_args()

    path = out_path(a.market)
    saved = json.loads(path.read_text()) if path.exists() else {"families": {}}

    if a.show:
        report(saved, a.market)
        return 0

    # Rows measured on an older feature matrix are not comparable to rows
    # measured now, and a half-old table is worse than no table because it
    # reads as one measurement. Start over when the matrix moves.
    current = H.feature_matrix_hash(a.market)
    if saved.get("families") and saved.get("feature_hash") != current:
        print(f"Feature matrix changed ({saved.get('feature_hash') or 'unrecorded'}"
              f" -> {current}); discarding {len(saved['families'])} rows "
              "measured on the old one.")
        saved = {"families": {}}
    saved["feature_hash"] = current

    families = load_families()
    todo = [a.family] if a.family else sorted(families)
    if a.family and a.family not in families:
        raise SystemExit(f"unknown family {a.family!r}; known: {sorted(families)}")

    model = production_model(a.market)
    base = baseline_run(a.market, model)
    noise = json.loads((ROOT / "models" / "registry" / "noise_floor.json").read_text())["spread"]

    for i, family in enumerate(todo, 1):
        if family in saved["families"]:
            print(f"[{i}/{len(todo)}] {family}: already measured, skipping")
            continue
        print(f"\n[{i}/{len(todo)}] ablating {family} "
              f"({len(families[family])} columns)")
        result, cached = ablate(a.market, family, model)
        # Champion = full features, candidate = without this family. A NEGATIVE
        # delta therefore means the family was carrying something.
        row = C.gate(C.compare(base, result, market=a.market, model=model,
                               noise=noise))
        t1 = row["top_k"][1]
        saved["families"][family] = {
            "columns": len(families[family]),
            "top1_delta": t1["delta"], "top1_se": t1["se"],
            "p_value": t1["p_value"], "wins": t1["wins"], "losses": t1["losses"],
            "top3_delta": row["top_k"][3]["delta"],
            "top5_delta": row["top_k"][5]["delta"],
            "verdict": row["verdict"],
        }
        saved["market"] = a.market
        saved["model"] = model
        saved["measured"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(saved, indent=2) + "\n")
        print(f"      Top-1 {t1['delta']*100:+.2f}pp ({t1['se_multiple']:+.2f} se, "
              f"p={t1['p_value']:.3f})")

    report(saved, a.market)
    return 0


def report(saved: dict, market: str) -> None:
    rows = saved.get("families", {})
    if not rows:
        print("Nothing measured yet.")
        return
    print(f"\nDropping each family from {market} "
          f"({saved.get('model', '?')}), paired per game.")
    print("A NEGATIVE Top-1 delta means removing the family HURT — it was "
          "carrying something.\n")
    print(f"  {'family':38s} {'cols':>5s} {'Top-1':>9s} {'se':>7s} {'p':>7s} "
          f"{'Top-3':>8s}")
    print("  " + "-" * 82)
    for name, r in sorted(rows.items(), key=lambda kv: kv[1]["top1_delta"]):
        se_mult = r["top1_delta"] / r["top1_se"] if r["top1_se"] else 0.0
        print(f"  {name:38s} {r['columns']:5d} {r['top1_delta']*100:+8.2f}pp "
              f"{se_mult:+7.2f} {r['p_value']:7.3f} "
              f"{r['top3_delta']*100:+7.2f}pp")
    import numpy as np
    t1 = np.array([r["top1_delta"] for r in rows.values()])
    t3 = np.array([r["top3_delta"] for r in rows.values()])
    print(f"\n  Top-1 negative in {int((t1 < 0).sum())}/{len(t1)}, "
          f"Top-3 negative in {int((t3 < 0).sum())}/{len(t3)}. "
          f"Mean Top-3 {t3.mean() * 100:+.2f}pp.")
    print("""
READ THE SIGN PATTERN, NOT THE RANKING.

One seed per family means each row on its own is noise-dominated: the spread of
these Top-1 deltas is barely wider than the seed-to-seed band, and with this many
families a couple will read p<0.05 by chance. Ranking them is over-reading.

What the aggregate says is solid, because seed noise is *symmetric* — paired
deltas between two runs differing only in seed come out positive about as often
as negative — while ablation deltas do not. A column of same-signed deltas is
therefore evidence even when each one individually is not.""")


if __name__ == "__main__":
    sys.exit(main())
