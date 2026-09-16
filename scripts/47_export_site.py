#!/usr/bin/env python3
"""Build site/site.html — the five-page board, as one self-contained file.

Reads the same payload `scripts/34_export_dashboard.py` builds, because the
data behind both pages is identical and a second builder would drift from the
first within a week. What it adds is the three things the new design needs and
the old one had no use for:

  * `pos` per player, so the board can be filtered to running backs. Position
    is one-hot in the feature matrix (WR is the reference level and has no
    column of its own), so it is reconstructed rather than read.
  * `results`, so a parlay saved on Wednesday settles on Sunday. Only weeks
    that have actually been graded appear; a leg the map does not carry stays
    pending rather than being assumed missed.
  * `season` and `week` at the top level, because the page scopes everything it
    remembers to them and the markets can in principle disagree.

    python scripts/47_export_site.py
    python scripts/47_export_site.py --week 3 --open
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, ".")

import polars as pl

from src.utils.paths import get_path

#: One-hot position columns in the feature matrix, and the level they encode.
#: WR is deliberately absent: it is the reference level, so a player with a
#: zero in every column below is a receiver. Reading that as "unknown" would
#: put the largest position group behind an "Any position" filter it never
#: matches.
POSITION_COLS = {"position_QB": "QB", "position_RB": "RB", "position_TE": "TE",
                 "position_FB": "FB", "position_DEFST": "DEF/ST"}
POSITION_DEFAULT = "WR"


def positions(season: int, week: int) -> dict[str, str]:
    """player_name -> position, for one week of the feature matrix."""
    path = get_path("processed", "anytime_td") / "features.parquet"
    if not Path(path).exists():
        return {}
    have = [c for c in POSITION_COLS if c in pl.scan_parquet(path).collect_schema().names()]
    if not have:
        return {}
    df = (pl.scan_parquet(path)
          .filter((pl.col("season") == season) & (pl.col("week") == week))
          .select(["player_name"] + have).collect())
    out = {}
    for row in df.iter_rows(named=True):
        hit = next((POSITION_COLS[c] for c in have if row.get(c) == 1), POSITION_DEFAULT)
        out[row["player_name"]] = hit
    return out


def results(season: int, week: int) -> dict[str, str]:
    """Leg id -> "hit" or "miss", for a week that has been graded.

    Keyed by the id the page builds a leg from (`<market>|<player>`), so
    settling is a lookup rather than a name match performed twice in two
    languages.

    The join is on `player_id`, not on a name. The targets files record
    touchdowns as play-by-play writes them — `C.Lamb`, `Bi.Robinson` — and the
    board carries `CeeDee Lamb`, so a name match here would silently settle
    almost nothing and report every parlay as a loss. The feature matrix holds
    both for the week and is what bridges them.

    An ungraded week contributes nothing at all, which leaves saved parlays
    pending. That is the right default: a slip reading Lost because a join
    failed is worse than one reading Pending for another hour.
    """
    feats = get_path("processed", "anytime_td") / "features.parquet"
    if not Path(feats).exists():
        return {}
    pool = (pl.scan_parquet(feats)
            .filter((pl.col("season") == season) & (pl.col("week") == week))
            .select(["player_id", "player_name"]).collect().unique(subset=["player_id"]))
    if pool.height == 0:
        return {}

    out: dict[str, str] = {}
    for key, target in (("any", "anytime_td"), ("first", "first_td")):
        path = get_path("processed", target) / f"tds_{target}.parquet"
        if not Path(path).exists():
            continue
        td = (pl.scan_parquet(path)
              .filter((pl.col("season") == season) & (pl.col("week") == week))
              .select("td_player_id").collect())
        if td.height == 0:
            # No touchdowns recorded is not the same as no data. A week with a
            # feature matrix and an empty targets file has not been extracted
            # yet, and calling every player a miss would settle every parlay
            # as a loss on the strength of a missing file.
            continue
        scorers = set(td["td_player_id"].drop_nulls().to_list())
        for pid, name in pool.iter_rows():
            out[f"{key}|{name}"] = "hit" if pid in scorers else "miss"
    return out


def build(season: int | None, week: int | None, brand: str) -> dict:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "dash_export", Path(__file__).with_name("34_export_dashboard.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    payload = mod.build(season, week)
    mk = payload.get("markets") or []
    s = season if season is not None else (mk[0].get("season") if mk else None)
    w = week if week is not None else (mk[0].get("week") if mk else None)

    pos = positions(s, w) if s and w else {}
    for m in mk:
        for p in m.get("players") or []:
            if p.get("player") in pos:
                p["pos"] = pos[p["player"]]
        for bucket in ("rows", "vetoes"):
            for r in (m.get("shortlist") or {}).get(bucket) or []:
                if r.get("player") in pos:
                    r["pos"] = pos[r["player"]]

    payload["brand"] = brand
    payload["season"] = s
    payload["week"] = w
    payload["results"] = results(s, w) if s and w else {}
    return mod.clean(payload)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="site/site.html")
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--brand", default="SquaresPro",
                    help="What the header says. Placeholder from the design.")
    ap.add_argument("--json", action="store_true",
                    help="write the payload as JSON beside --out and stop")
    ap.add_argument("--force", action="store_true",
                    help="publish even when artifacts predate the served model")
    ap.add_argument("--open", dest="open_after", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "dash_export", Path(__file__).with_name("34_export_dashboard.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not mod._gate(args.force):
        return 0

    print("building site ...", file=sys.stderr)
    sink = io.StringIO()
    with contextlib.nullcontext() if args.verbose else contextlib.redirect_stdout(sink):
        payload = build(args.season, args.week, args.brand)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.json:
        p = out.with_suffix(".json")
        p.write_text(json.dumps(payload, indent=1, allow_nan=False))
        print(f"wrote {p} ({p.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)
        return 0

    from src.export.site import render
    out.write_text(render(payload), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)
    if args.open_after:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
