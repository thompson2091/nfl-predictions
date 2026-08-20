#!/usr/bin/env python3
"""Was the cover rule the problem, or the market?

    python scripts/38_cover_selection.py --target anytime_td

`make cover-backtest` grades one rule: top N by the published column, one per
game, same N every week. This asks whether a different rule would have done
better — 44 of them, each decidable from the board before kickoff — and answers
three questions that are easy to confuse:

  * What was **available**? The hindsight ceiling: best variant each week,
    chosen after the week.
  * What was **reachable**? The walk-forward chooser: each week play whichever
    variant led on cumulative return through the previous week.
  * What does any of it **mean**? The same machinery on random orderings.

The control is the point. Forty-four variants over sixty weeks produce a winner
whether or not skill exists. On anytime TD the best of 44 *random* rules returns
up to +274% against the best real one's +19%, and a random hindsight ceiling of
+429% against the real +319%. Read without the control this looks like a gold
mine; read with it, the ceiling and the best variant say nothing, and what
carries information is the median variant and the chooser — where random
collapses to about -70% on both and the real rules do not.

The control is redrawn five times because its own headline moves from +6% to
+274% on the seed alone, which is the sharpest available statement about what a
best-of-44 is worth.

Requires backtest CSVs (scripts/10_backtest.py) for the model being measured.
Only priced legs are graded: a cover cannot settle without a payout per leg.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.evaluation.cover_selection import load, measure, save  # noqa: E402
from src.utils.config import production_model  # noqa: E402
from src.utils.paths import get_path  # noqa: E402


def _line(label: str, s: dict, note: str = "") -> str:
    return (f"  {label:<26} {s['roi']:>+8.1%}  "
            f"[{s['roi_lo']:>+5.0%},{s['roi_hi']:>+5.0%}]  "
            f"{s['weeks_profitable']:>2}/{s['weeks']:<3} {note}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", default="anytime_td")
    ap.add_argument("--model", default=None,
                    help="Measure a specific model. Omit for the production one.")
    ap.add_argument("--stake", type=float, default=1.0)
    ap.add_argument("--top", type=int, default=8, help="variants to list")
    ap.add_argument("--show", action="store_true",
                    help="print the saved result without re-measuring")
    a = ap.parse_args()

    out = get_path("output", a.target) / "cover_selection.json"
    model = a.model or production_model(a.target)

    stats = load(out) if a.show else measure(a.target, model, a.stake)
    if stats is None:
        print(f"No graded backtest for {model} on {a.target} — run "
              f"scripts/10_backtest.py first.")
        return 1
    if not a.show:
        save(stats, out)

    c, v = stats["control"], stats["verdict"]
    print(f"{a.target} / {model}: {stats['weeks']} weeks, {stats['span']}, "
          f"{stats['n_variants']} variants, ${stats['stake']:.2f} a slip\n")

    print("what a rule returned")
    if stats["baseline_result"]:
        print(_line(f"baseline {stats['baseline']}", stats["baseline_result"]))
    print(_line("walk-forward chooser", stats["chooser"],
                f"{stats['chooser_detail']['switches']} switches"))
    print(_line("best of the 44", stats["best_variant"],
                f"<- best of {stats['n_variants']}, not a rate"))
    print(f"  {'median of the 44':<26} {stats['median_variant_roi']:>+8.1%}")

    print("\nwhat was available, which nobody could play")
    print(_line("best variant each week", stats["ceiling"]))
    print(_line("best size each week", stats["ceiling_size_only"]))

    print(f"\nthe same machinery on {c['n_variants']} random orderings, "
          f"redrawn {c['repeats']}x — each shown worst to best across redraws")
    for label, key in (("random chooser", "chooser_roi"),
                       ("best random variant", "best_roi"),
                       ("median random variant", "median_roi"),
                       ("random ceiling", "ceiling_roi")):
        sp = c[key]
        print(f"  {label:<26} {sp['median']:>+8.1%}  "
              f"[{sp['min']:>+5.0%},{sp['max']:>+5.0%}] across redraws")

    print(f"\ntop {a.top} variants")
    for s in stats["variants"][:a.top]:
        print(_line(s["name"], s, f"~{s['mean_legs']:.1f} legs"))
    print("worst 3")
    for s in stats["variants"][-3:]:
        print(_line(s["name"], s))

    fam = stats["unblended_vs_published"]
    print("\nunblended ordering against the published one, at matched size")
    if fam["identical"]:
        print("  identical at every size — this market's blend does not move "
              "the number, so the two orderings pick the same players. It "
              "checks the plumbing and says nothing about the claim.")
    else:
        for p in fam["sizes"]:
            print(f"  N={p['n']}  published {p['published_roi']:>+7.1%}   "
                  f"model {p['model_roi']:>+7.1%}   "
                  f"gap {p['gap']:>+6.1%}")
        print(f"  unblended ahead at {fam['model_wins']} of "
              f"{len(fam['sizes'])} sizes")

    print()
    if v["any_variant_beats_zero"]:
        print("At least one variant's interval clears zero.")
    else:
        print("No variant's interval clears zero, and neither does the "
              "chooser's.")
    if not v["best_beats_control_best"]:
        print(f"The best real variant ({v['best_variant_roi']:+.1%}) does not "
              f"beat the best random one ({v['control_best_roi']:+.1%}) — "
              f"which is the point of running the control, not a failure of "
              f"the model.")
    print(f"The chooser returned {v['chooser_roi']:+.1%} against a random "
          f"chooser's {v['control_chooser_roi']:+.1%}, and a baseline of "
          f"{v['baseline_roi']:+.1%}.")

    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
