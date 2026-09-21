"""Refit the count -> probability conversion without retraining the model.

    python scripts/52_refit_conversion.py [--target anytime_td]

The conversion describes how the trained ranker's expected touchdown counts
become published probabilities. Nothing about it requires the ranker to be
refitted, and it is the one artifact in the joint model that can be wrong while
every metric the ranker reports stays right: it is fitted by log loss, which
the thousands of near-zero rows dominate, so a systematic level error costs
almost nothing to the number being optimised.

That is what happened. Fitted on priced players and served to everyone, the
board summed to 4.60 expected scorers a game against 4.28 actual over 570
held-out games — all of it from the players no book quoted, who were published
at 4.8% each against a true 0.41%.

Re-run after `make odds` adds a season of coverage. Calls the same function
`make train` does, so the two cannot disagree.
"""
from __future__ import annotations

import argparse
import sys

import polars as pl

sys.path.insert(0, ".")

from src.models.joint import load_team_rate                      # noqa: E402
from src.models.trainer import get_feature_cols, refit_conversion  # noqa: E402
from src.utils.config import get_config                          # noqa: E402
from src.utils.paths import get_path                             # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", default="anytime_td")
    args = ap.parse_args()

    cfg = get_config()
    splits = cfg["splits"]
    model_dir = get_path("models", args.target)
    team_model = load_team_rate(model_dir / "team_td_rate.json")
    if team_model is None:
        print(f"No team_td_rate.json in {model_dir} — run `make train` first.")
        return 1

    df = pl.read_parquet(get_path("processed", args.target) / "features.parquet")
    feature_cols = get_feature_cols(df, args.target)
    train_seasons = list(range(cfg["seasons"]["start"], splits["train_end"] + 1))

    print(f"Refitting the {args.target} conversion on train "
          f"{train_seasons[0]}-{train_seasons[-1]} + val {splits['val_season']}, "
          f"against the model already on disk.")
    refit_conversion(df, train_seasons, splits, feature_cols, model_dir,
                     args.target, team_model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
