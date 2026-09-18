"""Fit and grade a shortlist rule for the four over/under markets.

    python scripts/50_ou_shortlist.py [--market receptions]

Writes `output/<market>/shortlist.json`, which `scripts/47_export_site.py`
reads to narrow this week's board. See `src/evaluation/ou_shortlist.py` for
why the rule is not the touchdown one — a two-sided market has no veto, the
line is part of the bet, and the market's own open-to-close drift has to come
out before any of it means anything.

The result, on the four markets as they stand, is that the floors fit and
nothing they pick clears zero: every held-out interval spans it. That is the
answer rather than a failure to find one, and it is why the artifact carries
the interval and the page prints it.
"""
from __future__ import annotations

import argparse
import json
import sys

sys.path.insert(0, ".")

from src.evaluation import ou_shortlist as ous
from src.utils.paths import get_path

MARKETS = ("receptions", "rushing_yards", "receiving_yards", "passing_yards")


def show(art: dict) -> None:
    mk = art["market"]
    print(f"\n=== {mk} ===")
    if art.get("problem"):
        print(f"  {art['problem']}")
        return
    print(f"  {art['n_pairs']:,} archived lines hold an open and a close at the "
          f"same number")
    print(f"  market drift {art['drift_pp']:+.3f}pp open to close — every band "
          f"below is centered on it")
    for side in ("over", "under"):
        f = (art.get("floors") or {}).get(side)
        if not f:
            print(f"  {side:5s}: no band where the close came our way")
            continue
        hi = "+" if f.get("hi") is None else f"-{f['hi']:.0f}"
        print(f"  {side:5s}: take from {f['lo']:.0f}{hi}pp  "
              f"(fitted on {f['n']} lines, {f['mean_move_pp']:+.3f}pp toward us)")
    for g in art.get("graded") or []:
        if g.get("roi") is None:
            print(f"    {g['season']:>9s}: the rule picked nothing")
            continue
        print(f"    {g['season']:>9s}: {g['n']:4d} bets over {g.get('fixtures', 0):3d} "
              f"fixtures   {g['roi']:+6.2f}%  CI[{g['roi_lo']:+6.2f}, {g['roi_hi']:+6.2f}]"
              + ("  clears zero" if (g["roi_lo"] > 0 or g["roi_hi"] < 0)
                 else "  (spans zero)"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--market", action="append", choices=MARKETS,
                    help="fit one market; repeatable. Default is all four.")
    a = ap.parse_args()

    rc = 0
    for mk in (a.market or list(MARKETS)):
        art = ous.fit(mk)
        show(art)
        if art.get("problem"):
            rc = 1
            continue
        out = get_path("output", mk) / "shortlist.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(art, indent=2))
        print(f"  wrote {out}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
