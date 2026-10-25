#!/usr/bin/env python3
"""Fill the frozen game record back to week 1, without inventing a forecast.

TWO GAPS. Weeks 1 and 2 have no frozen entry at all (`fill_empty_weeks`);
weeks 3 and 4 lack only the adjusted win chance, below.

The adjusted win chance for frozen weeks that predate it.

`blend.win_home` was first frozen in week 5 of 2026. Weeks 3 and 4 have the
adjusted SPREAD frozen at kickoff, and the win chance is nothing more than that
spread read off the score-history win curve (`game_blend.blend_win`). So it can
be written down after the fact without recomputing anything that was a
forecast: the frozen spread goes in, and the curve is fitted only on games
played before that week, which is what the curve would have been at kickoff.

    python scripts/63_backfill_blend_win.py            # check and report
    python scripts/63_backfill_blend_win.py --write    # write the archive

THE CHECK. The same method is run on the weeks that DID freeze a win chance,
and the run stops if it does not reproduce them. A method that cannot match
the recorded weeks has no business filling the unrecorded ones.

Never overwrites a recorded `win_home`. Each one written carries
`win_home_backfilled` with the date, so it is never mistaken for a number
that was on the board before kickoff.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import polars as pl  # noqa: E402

from src.export import projection_freeze as PF  # noqa: E402
from src.models.game_blend import blend_win  # noqa: E402
from src.models.score_dist import history, win_curve  # noqa: E402

#: Largest disagreement with a recorded win chance the check accepts. The
#: curve is refitted as games are added, so it moves a little week to week.
TOL = 0.005


def curve_before(season: int, week: int, hist: pl.DataFrame) -> dict:
    """The win curve as it stood before `week` kicked off."""
    return win_curve(hist.filter((pl.col("season") < season)
                                 | ((pl.col("season") == season)
                                    & (pl.col("week") < week))))


def fill_empty_weeks(season: int, store: dict, write: bool) -> None:
    """Weeks with no frozen entry at all, frozen now from the export's cards.

    2026 weeks 1 and 2 were played before anything froze a projection, and no
    build on the server ever showed one (`62_backfill_projections.py`). The
    board has shown a number for them on every build since, recomputed each
    time. What it computes is as close to point-in-time as can be had: the
    game model trains on seasons before this one, the blend and model-win
    weights on completed seasons only. It is frozen here once, marked
    `backfilled`, so it stops moving and is never read as a kickoff number.

    OUR MODEL'S NUMBERS ONLY, NOT THE ADJUSTED ONE. Fitted on completed
    seasons, the blend fails its out-of-sample check and is served at weight
    zero (2026-10-20), so today's adjusted spread IS the book's. Frozen into
    weeks 1 and 2 it would put 32 of the book's picks into the Record under
    "Adjusted". Those weeks had no adjusted number, and still do not.
    """
    import importlib.util

    first = min((int(w) for w, g in store.items() if g), default=None)
    if not first or first <= 1:
        return
    spec = importlib.util.spec_from_file_location(
        "export_site", Path(__file__).resolve().parent / "47_export_site.py")
    ex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ex)
    past = ex.games_past(season, first)
    today = date.today().isoformat()
    for wk in range(1, first):
        cards = (past.get(str(wk)) or {}).get("cards") or []
        n = 0
        for c in cards:
            snap = {f: c[f] for f in PF.FIELDS if c.get(f) is not None}
            if "model_spread" not in snap:
                continue
            snap.pop("blend", None)
            snap["backfilled"] = today
            n += 1
            if write:
                store.setdefault(str(wk), {})[c["game_id"]] = snap
                PF._DIRTY.add(season)
            else:
                # Seen by the blend step below without being written.
                store.setdefault(str(wk), {}).setdefault(c["game_id"], snap)
        print(f"week {wk}: {n} of {len(cards)} games frozen from today's "
              f"computation{'' if write else ' (not written)'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    store = PF.load(a.season)
    hist = history()
    fill_empty_weeks(a.season, store, a.write)

    worst, n_checked = 0.0, 0
    todo = []
    for wk, games in sorted(store.items(), key=lambda kv: int(kv[0])):
        curve = curve_before(a.season, int(wk), hist)
        for gid, snap in games.items():
            b = snap.get("blend") or {}
            if b.get("spread") is None:
                continue
            got = blend_win(b, curve)
            if got is None:
                continue
            if b.get("win_home") is not None:
                if not b.get("win_home_backfilled"):
                    worst = max(worst, abs(got - b["win_home"]))
                    n_checked += 1
                continue
            todo.append((wk, gid, b, got))

    print(f"check: {n_checked} recorded win chances, "
          f"largest difference {worst:.4f} (tolerance {TOL})")
    if not n_checked or worst > TOL:
        print("the method does not reproduce the recorded weeks; nothing written")
        return 1

    for wk, gid, b, got in todo:
        print(f"  wk{wk} {gid:<8} adjusted spread {b['spread']:>6}  "
              f"home win {got:.4f}")
        if a.write:
            b["win_home"] = got
            b["win_home_backfilled"] = date.today().isoformat()
            PF._DIRTY.add(a.season)
    print(f"\n{len(todo)} to fill")
    if a.write:
        for p in PF.flush():
            print(f"wrote {p}")
    else:
        print("nothing written; re-run with --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
