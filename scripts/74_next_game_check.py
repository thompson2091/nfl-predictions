"""Prove the next-game placeholders on a past season, builder by builder.

    python scripts/74_next_game_check.py [--season 2025] [--through 6]

Cuts the play-by-play after week `--through`, adds the placeholders
`src/features/next_game.py` would add, and runs every team builder twice:
on the cut data, and on the real data. Two things must hold:

  - the next-game row from the cut data equals the row the real plays give,
    feature by feature (the placeholder reaches the game, from the right
    games, and nothing of its own leaks in);
  - every played row is identical with and without the placeholders (no
    training row moves).

A builder whose filters drop the placeholder shows as "no row": it stays on
the old one-game-stale carry, and says so here rather than silently. The coach
builder is not here: it builds from the schedule, which already has a row for
every game, played or not. Coverage and personnel are not either: 2026 has
no participation data for them, so they stay on the carried 2025 rate.
"""
from __future__ import annotations

import argparse
import sys

import polars as pl

sys.path.insert(0, ".")

from src.features.next_game import NOBODY, stubs, with_stubs    # noqa: E402
from src.utils.paths import get_path                             # noqa: E402


def builders(rosters, schedules):
    from src.features.box_features import build_box_features
    from src.features.opponent_position_features import \
        build_opponent_position_features
    from src.features.pace_features import build_pace_features
    from src.features.qb_features import build_qb_features
    from src.features.redzone_features import build_team_redzone_features
    from src.features.team_features import (build_opponent_features,
                                            build_team_features)
    return {
        "team": (build_team_features, "team"),
        "opp": (build_opponent_features, "opponent"),
        "team_rz": (build_team_redzone_features, "team"),
        "opp_pos": (lambda p: build_opponent_position_features(p, rosters), "opponent"),
        "qb": (build_qb_features, "team"),
        "pace": (build_pace_features, "team"),
        "box": (build_box_features, "opponent"),
    }


def _differ(a: pl.DataFrame, b: pl.DataFrame, keys: list, vals: list) -> list:
    """Features on which two frames disagree, row for row. Null equals null
    and NaN equals NaN: 0/0 on a team's first game is NaN on both sides."""
    j = a.join(b, on=keys, suffix="_s")
    out = []
    for c in vals:
        if f"{c}_s" not in j.columns:
            continue
        x, y = pl.col(c).fill_nan(None), pl.col(f"{c}_s").fill_nan(None)
        n = j.select((((x - y).abs() > 1e-9).fill_null(False)
                      | (x.is_null() != y.is_null())).sum()).item()
        if n:
            out.append(c)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=2025)
    ap.add_argument("--through", type=int, default=6)
    a = ap.parse_args()

    raw = get_path("raw")
    pbp = pl.read_parquet(raw / "pbp.parquet").filter(
        pl.col("season").is_between(a.season - 2, a.season))
    schedules = pl.read_parquet(raw / "schedules.parquet")
    rosters = pl.read_parquet(raw / "rosters.parquet")
    cut = pbp.filter((pl.col("season") < a.season) | (pl.col("week") <= a.through))
    stubbed = with_stubs(cut, schedules, a.season)
    nxt = stubs(cut, schedules, a.season).select("season", "week").unique()

    bad = 0
    for name, (build, key) in builders(rosters, schedules).items():
        full, plain, stub = build(pbp), build(cut), build(stubbed)
        keys = [key, "season", "week"]
        if key not in full.columns:
            print(f"  {name:10s} skipped: no `{key}` column")
            continue
        vals = [c for c in full.columns
                if c not in (*keys, "game_id") and full[c].dtype.is_numeric()]
        # 1. Played rows unchanged.
        p = plain.filter(pl.col("season") == a.season).sort(keys)
        s = (stub.join(nxt, on=["season", "week"],
                       how="anti").filter(pl.col("season") == a.season).sort(keys))
        moved = int(p.height != s.height or _differ(p, s, keys, vals) != [])
        # 2. Next-game rows equal the real ones.
        want = full.join(nxt, on=["season", "week"])
        got = stub.join(nxt, on=["season", "week"]).filter(pl.col(key) != NOBODY)
        want = want.join(got.select(keys), on=keys, how="semi")
        if got.height == 0:
            print(f"  {name:10s} NO ROW: the placeholder is filtered out; stays stale")
            bad += 1
            continue
        off = _differ(want, got, keys, vals)
        print(f"  {name:10s} teams {got[key].n_unique():2d}/32  "
              f"features off {len(off):2d}/{len(vals)}  played rows "
              f"{'MOVED' if moved else 'unchanged'}"
              + (f"  ({', '.join(off[:4])})" if off else ""))
        bad += bool(off) or bool(moved)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
