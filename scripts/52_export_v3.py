#!/usr/bin/env python3
"""Build site/v3 — the same numbers, for someone who does not bet much.

    python scripts/52_export_v3.py [--out site/v3] [--no-ai]

The payload is `scripts/47_export_site.py:build`, unchanged and unforked, plus
one thing v2 does not carry: `notes`, the per-game explanations. Those are
selected by `src.analysis.game_notes` and phrased by Claude, cached under a
hash of their facts so a rebuild whose numbers have not moved makes no API
call. `--no-ai` skips the phrasing entirely and ships the template sentences,
which is what happens anyway with no key.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="site/v3")
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--brand", default="Pick Six")
    ap.add_argument("--no-ai", action="store_true",
                    help="ship the template sentences; make no API call")
    ap.add_argument("--force", action="store_true",
                    help="publish even when artifacts predate the served model")
    a = ap.parse_args()

    spec = importlib.util.spec_from_file_location(
        "site_export", Path(__file__).with_name("47_export_site.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # THE SAME GATE THE OTHER EXPORTS PASS THROUGH.
    #
    # This calls `build` directly, and the freshness refusal lives in the
    # exports' `main` rather than in `build` — so v3 walked straight past it.
    # On 2026-09-27 that meant the LIVE site carried a model promoted on the
    # 25th beside closing-line and longshot figures measured on the 22nd,
    # while the v1 pages the gate does cover had been refusing for five days.
    # The one export that reaches the public was the one not checked.
    gspec = importlib.util.spec_from_file_location(
        "dash_export", Path(__file__).with_name("34_export_dashboard.py"))
    gmod = importlib.util.module_from_spec(gspec)
    gspec.loader.exec_module(gmod)
    if not gmod._gate(a.force):
        return gmod.EXPORT_REFUSED

    print("building v3 ...", file=sys.stderr)
    payload = mod.build(a.season, a.week, a.brand)

    from src.analysis import game_notes
    cards = (payload.get("games") or {}).get("cards") or []
    notes = {}
    for card in cards:
        picked = game_notes.select(payload, card)
        if not picked:
            continue
        notes[card["game_id"]] = (picked if a.no_ai
                                  else game_notes.phrase(picked, card))
    payload["notes"] = notes
    print(f"  {sum(len(v) for v in notes.values())} notes across "
          f"{len(notes)} games", file=sys.stderr)

    # One brief per game for the Ask box. Written as separate files, never
    # inlined: the browser sends a game id and the SERVER loads the brief, so
    # nothing a reader types can become context. See `askctx`.
    from src.export.askctx import build as ask_briefs
    briefs = ask_briefs(payload)

    from src.export.v3 import render
    files = render(payload)
    for gid, brief in briefs.items():
        files[f"data/ask/{gid}.json"] = json.dumps(brief, separators=(",", ":"),
                                                   allow_nan=False)
    if briefs:
        print(f"  {len(briefs)} ask briefs "
              f"({sum(len(files['data/ask/' + g + '.json']) for g in briefs) / 1024:,.0f} KB)",
              file=sys.stderr)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    # Stale week files are removed before writing: the page asks the index
    # rather than the directory, so an orphan would ship forever unread.
    data_dir = out / "data"
    if data_dir.exists():
        keep = {out / n for n in files}
        for old in list(data_dir.glob("h-*.json")) \
                + list((data_dir / "ask").glob("*.json")):
            if old not in keep:
                old.unlink()

    top, side = [], []
    for name, body in sorted(files.items()):
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        (side if "/" in name else top).append((name, len(body)))
    for name, n in top:
        print(f"  {out / name}  ({n / 1024:,.0f} KB)", file=sys.stderr)
    if side:
        total = sum(n for _, n in side) / 1024
        print(f"  {out / 'data'}/  ({len(side)} week files, {total:,.0f} KB)",
              file=sys.stderr)
    # NAMED, not derived from what was written. Deriving the instruction from
    # the output means that if `render` ever stops emitting one of them, the
    # message stops asking for it too and the upload is quietly incomplete —
    # a page that loads, never installs and never goes offline.
    need = ["index.html", "manifest.webmanifest", "sw.js"]
    missing = [n for n in need if n not in files]
    if missing:
        print(f"  !! render() did not produce {', '.join(missing)}",
              file=sys.stderr)
        return 1
    print(f"\nupload {', '.join(need)} AND the data/ folder to the same "
          f"directory.\nthe worker's scope is where it is served from, so a "
          f"page without its sw.js beside it never goes offline and never "
          f"says so.\nwithout data/, every past week is empty — the page "
          f"loads and the picker still lists them.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
