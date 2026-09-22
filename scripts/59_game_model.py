"""The vegas-blind game model: how close it gets, and where it disagrees.

    python scripts/59_game_model.py

Prints the walk-forward accuracy against the closing line and the record of
backing the model wherever it disagrees. Nothing here is served to the page
yet — see `src/models/game_model` for what it is and what nearly shipped.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")


def main() -> int:
    import polars as pl

    from src.models.game_model import (BREAK_EVEN, disagreements, leaky_columns,
                                       team_games, walk_forward)

    d = team_games()
    leaks = leaky_columns(d)
    print(f"team-games {d.height:,}   dropped {len(leaks)} columns whose "
          f"absence leaks the result")

    g = walk_forward(d)
    if g.is_empty():
        print("no walk-forward rows")
        return 1
    mae = lambda a, b: float((g[a] - g[b]).abs().mean())   # noqa: E731
    print(f"\n{g.height:,} games, {g['season'].min()}-{g['season'].max()}")
    print(f"  {'':8}{'model':>7}{'market':>8}   (mean absolute error)")
    print(f"  {'margin':8}{mae('margin_model','margin_actual'):7.2f}"
          f"{mae('margin_market','margin_actual'):8.2f}")
    print(f"  {'total':8}{mae('total_model','total_actual'):7.2f}"
          f"{mae('total_market','total_actual'):8.2f}")
    print("\n  The model is WORSE than the market on both. That is expected: "
          "it cannot\n  see the line. The question is whether it disagrees "
          "usefully.\n")
    for market in ("total", "margin"):
        print(f"  backing the model when it differs from the {market} line by:")
        print(f"  {'by':>5}{'bets':>7}{'hit':>8}{'ROI':>8}   95% interval")
        for r in disagreements(g, market):
            print(f"  {r['threshold']:5.0f}{r['n']:7d}{100*r['hit_rate']:7.1f}%"
                  f"{r['roi_pct']:+7.1f}%   [{100*r['lo']:.1f}, {100*r['hi']:.1f}]"
                  f"{'  clears' if r['clears'] else ''}")
        print()
    print(f"  break-even at -110 is {100*BREAK_EVEN:.2f}%")
    print("  Nothing here is served. Seven seasons is ~150 qualifying bets a")
    print("  year and one of the seven sits below break-even.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
