#!/usr/bin/env python3
"""Which builder produced each feature? Provenance for family-level ablation.

319 model features come from ~35 builder modules, and ablating them one column
at a time answers the wrong question: columns within a family are correlated by
construction — `player_carries_avg_3g` and `player_carries_avg_5g` cover for
each other — so dropping either alone measures nothing while dropping the family
measures something. Phase 3e in docs/MODEL_ITERATION.md.

Static analysis cannot produce this map. Only 49 of 319 columns are named by a
literal `alias("...")`; the rest are built programmatically inside loops over
stat names and window widths, so their names exist only at runtime.

So the map is recorded by running the assembler once with every `build_*`
wrapped. Two shapes have to be handled: builders that return a frame (or a tuple
of frames) to be joined, and builders that take the assembled frame and return
it with columns added — for those the family is the *difference*, not the
output.

    python scripts/26_feature_families.py            # rebuild the map
    python scripts/26_feature_families.py --show     # read the saved one

Writes diagnostics/feature_families.json, which is committed: it changes only
when a builder changes, and an ablation run should not have to rebuild every
feature to know what it is dropping.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import polars as pl  # noqa: E402

from src.utils.paths import get_path  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "diagnostics" / "feature_families.json"

#: Join keys and identifiers appear in nearly every builder's output and belong
#: to no family. Recording them would make every family look enormous and
#: overlapping.
KEYS = {"player_id", "game_id", "season", "week", "team", "opponent",
        "player_name", "player_name_norm", "home_team", "away_team",
        "gameday", "gametime", "target", "position"}


def record_provenance() -> dict[str, list[str]]:
    """Run the assembler with every builder wrapped; return column -> family."""
    from src.features import assembler

    produced: dict[str, set[str]] = defaultdict(set)

    def wrap(name, fn):
        def wrapped(*args, **kwargs):
            before = set()
            for a in args:
                if isinstance(a, pl.DataFrame):
                    before = set(a.columns)
                    break
            out = fn(*args, **kwargs)
            frames = out if isinstance(out, tuple) else (out,)
            for frame in frames:
                if not isinstance(frame, pl.DataFrame):
                    continue
                cols = set(frame.columns)
                # A builder that takes the assembled frame and returns it with
                # columns added owns only the difference. Recording `cols` would
                # give it every feature assembled up to that point.
                new = cols - before if before and before <= cols else cols
                for c in new - KEYS:
                    produced[c].add(name)
            return out
        return wrapped

    patched = []
    for attr in dir(assembler):
        if attr.startswith("build_") or attr.startswith("_build_"):
            fn = getattr(assembler, attr)
            if callable(fn):
                setattr(assembler, attr, wrap(attr, fn))
                patched.append(attr)
    print(f"Wrapped {len(patched)} builders; assembling...")

    try:
        assembler.assemble_features()
    finally:
        pass

    return {c: sorted(v) for c, v in produced.items()}


def build() -> dict:
    provenance = record_provenance()
    families: dict[str, list[str]] = defaultdict(list)

    for market in ("anytime_td", "first_td"):
        path = get_path("models", market) / "feature_cols.pkl"
        if path.exists():
            model_features = pickle.loads(path.read_bytes())
            break
    else:
        raise SystemExit("no feature_cols.pkl — train a model first")

    # Every column any builder produced, not only the ones the current model
    # happens to train on. The map's job is to say what a family CONTAINS, and
    # a lean model's `feature_cols.pkl` cannot answer that: after the 24-family
    # lock it lists 236 of 318 columns, so a map built from it would omit the
    # families that were dropped and could never be used to add one back. New
    # families arrive the same way — nothing has trained on weather yet, so
    # nothing would record it.
    #
    # `unattributed` still measures the model's own columns, because that is
    # the number that matters: those reach the model without a family, and
    # `get_feature_cols` keeps them unconditionally.
    for col, owners in provenance.items():
        # A column claimed by several builders belongs to the one that made it
        # first; later ones are re-joining it. Sorted for determinism.
        families[owners[0]].append(col)
    unattributed = [c for c in model_features if not provenance.get(c)]

    payload = {
        "n_features": len(model_features),
        "n_columns_mapped": sum(len(v) for v in families.values()),
        "n_families": len(families),
        "unattributed": sorted(unattributed),
        "families": {k: sorted(v) for k, v in sorted(families.items())},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def show(payload: dict) -> None:
    print(f"{payload['n_features']} model features in "
          f"{payload['n_families']} families\n")
    rows = sorted(payload["families"].items(), key=lambda kv: -len(kv[1]))
    for name, cols in rows:
        print(f"  {len(cols):4d}  {name}")
    if payload["unattributed"]:
        print(f"\n  {len(payload['unattributed']):4d}  (unattributed) — "
              f"e.g. {', '.join(payload['unattributed'][:6])}")
        print("  These reach the model without passing through a wrapped "
              "builder; they are assembled inline or renamed after the join.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--show", action="store_true",
                    help="print the saved map without rebuilding it")
    a = ap.parse_args()
    if a.show:
        if not OUT.exists():
            raise SystemExit(f"{OUT} does not exist; run without --show first")
        show(json.loads(OUT.read_text()))
        return 0
    payload = build()
    show(payload)
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
