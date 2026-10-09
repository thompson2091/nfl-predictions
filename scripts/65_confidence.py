#!/usr/bin/env python3
"""Does the model's own certainty sort the prop book? ONE COMMAND.

    python scripts/65_confidence.py                 # this season, every
                                                    # graded week
    python scripts/65_confidence.py --season 2024 --weeks 1-9
    python scripts/65_confidence.py --season 2026 --weeks 1-18

Measures return per $100 by how sure the unblended model was, in bands, with
intervals clustered by game — and the paired within-game difference, which is
the strongest form available because it removes game script rather than
controlling for it.

**WHY THIS IS A SCRIPT AND NOT A FEATURE.** Over 2024-25 the gradient was
monotone from -7.31 per $100 to +9.07 and the paired test came in at
p=0.000005. Over 2026 weeks 1-4 it is flat. 64 games is about a third of the
power needed to see a +8 effect, so that is neither a confirmation nor a
refutation — it is a reading that has to be taken again when the season is
long enough, and this is the command that takes it. The answer to date is in
`src/evaluation/confidence.py`'s docstring and in the memory
`nfl-predictions-model-confidence-sorts-the-prop-book`.

Nothing here is fitted, nothing is published, and no threshold is emitted.
Before anything bets on this it has to be fitted with provenance the way
`ou_shortlist`'s floors are.

**IT IS SLOW AND THAT IS INHERENT.** `ou_week` rebuilds a board per market
per week, so a full season is seventy-two board builds. Expect minutes, not
seconds, and run it when a season has ended rather than on a loop.
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

#: The record so far, printed beside a new reading so it lands in context
#: rather than as a number on its own. `(label, paired diff, p, games)`.
REFERENCE: tuple[tuple[str, float, float, int], ...] = (
    ("2024 backtest, full", 6.51, 0.018, 284),
    ("2024 ou_rows, weeks 1-9", 6.36, 0.089, 138),
    ("2025 backtest, full", 10.44, 0.00004, 285),
    ("2026 ou_rows, weeks 1-4", 0.96, 0.878, 64),
)


def _weeks(spec: str) -> list[int]:
    """`1-18`, `3`, or `1,3,5` — whichever a reader reaches for."""
    out: list[int] = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=None,
                    help="default: the season the config is serving")
    ap.add_argument("--weeks", default="1-18",
                    help="1-18, 3, or 1,3,5 (default 1-18; "
                         "unplayed weeks contribute nothing)")
    a = ap.parse_args()

    from src.evaluation import confidence as C

    season = a.season
    if season is None:
        from src.utils.config import get_config
        season = int(get_config()["season"])
    weeks = _weeks(a.weeks)

    print(f"building {season} weeks {weeks[0]}-{weeks[-1]} ... "
          f"(a board per market per week; this takes a while)",
          file=sys.stderr)
    rows = C.legs(season, weeks)
    if not rows:
        print(f"no graded over/under bets for {season} in those weeks.")
        return 0

    p = C.power(rows)
    print(f"\n{season}, weeks {weeks[0]}-{weeks[-1]}: {p['n']:,} bets over "
          f"{p['games']} games")
    print(f"  whole book {p['roi'] * 100:+.2f} per $100  "
          f"[{p['ci_lo'] * 100:+.2f}, {p['ci_hi'] * 100:+.2f}] "
          f"clustered by game")
    # SAID BEFORE THE RESULT, not after it. A flat gradient from a test that
    # could only have found something enormous is not a flat gradient.
    print(f"  clustered SE {p['se'] * 100:.2f} points, so this reading can "
          f"see {p['detects'] * 100:.1f} points at 80% power")

    print("\n  how sure the model was        n  games   per $100"
          "            interval")
    for b in C.gradient(rows):
        head = f"  {b['lo']:.2f} to {b['hi']:.2f}  {b['n']:>18,}{b['games']:>7}"
        if "roi" not in b:
            print(f"{head}   too few to report")
            continue
        print(f"{head}{b['roi'] * 100:>+11.2f}"
              f"  [{b['ci_lo'] * 100:+7.2f},{b['ci_hi'] * 100:+7.2f}]")

    d = C.paired(rows)
    if d is None:
        print("\n  too few games carry both groups to difference them.")
    else:
        print(f"\n  paired within game, over {C.HI:.2f} minus under "
              f"{C.LO:.2f}: {d['diff'] * 100:+.2f} per $100 "
              f"over {d['games']} games, p={d['p']:.5f}")

    print("\n  the record so far, for context:")
    print(f"    {'season':<26}{'paired':>9}{'p':>10}{'games':>8}")
    for label, diff, pv, g in REFERENCE:
        print(f"    {label:<26}{diff:>+9.2f}{pv:>10.5f}{g:>8}")
    print("\n  nothing is fitted here and no threshold is published; see "
          "`src/evaluation/confidence.py`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
