#!/usr/bin/env python3
"""Where the market is wrong, and why its margin eats the difference anyway.

    python scripts/43_market_shape.py --target anytime_td

Splits every priced bet by the bookmaker's own de-vigged number and puts three
columns beside each other: what the book says, what happened, and what the
posted price implied. The first two show a textbook favourite-longshot bias;
the third shows the margin swallowing it whole at every decile.

This is the table that explains every negative return in the project without
reference to the model.
"""
from __future__ import annotations

import argparse
import json
import sys

sys.path.insert(0, ".")

from src.evaluation.market_shape import measure  # noqa: E402
from src.presentation import board as bp  # noqa: E402
from src.utils.config import get_config, production_model  # noqa: E402
from src.utils.paths import get_path  # noqa: E402


def main(target_type: str, model: str) -> int:
    d = measure(target_type, model)
    if d is None:
        print(f"No priced backtest for {model} on {target_type} — run "
              f"scripts/10_backtest.py first.")
        return 1

    out = get_path("output", target_type) / "market_shape.json"
    out.write_text(json.dumps(d, indent=2))

    print(f"MARKET SHAPE — {target_type} / {model}, {d['span']}")
    print(f"  by decile of the book's own de-vigged number\n")
    print(f"  {'dec':<5}{'n':>6}{'book':>8}{'actual':>8}{'book err':>10}"
          f"{'posted':>9}{'margin':>8}{'overpay':>9}{'ROI':>9}")
    for r in d["rows"]:
        print(f"  {r['decile']:<5}{r['n']:>6,}{r['book_pct']:>7.2f}%"
              f"{r['actual_pct']:>7.2f}%{r['book_error_pp']:>+9.2f}pp"
              f"{r['posted_pct']:>8.2f}%{r['margin_pp']:>+7.2f}pp"
              f"{r['overpay_pp']:>+8.2f}pp{r['roi']:>+8.1f}%")
    print("\n  book err  what the bookmaker's opinion gets wrong, before it "
          "charges anything")
    print("  margin    what it charges for that opinion")
    print("  overpay   the two together — what you pay above the truth, and "
          "the reason every row loses")
    print(f"\n  Saved: {out}")
    return 0


if __name__ == "__main__":
    cfg = get_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=cfg["target"]["type"])
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    sys.exit(main(a.target, a.model or production_model(a.target)))
