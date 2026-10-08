#!/usr/bin/env python3
"""Build site/v3 or site/v4 — the same numbers, for someone who does not bet much.

    python scripts/52_export_v3.py [--out site/v3] [--no-ai]
    python scripts/52_export_v3.py --app v4          # -> site/v4

The payload is `scripts/47_export_site.py:build`, unchanged and unforked, plus
one thing v2 does not carry: `notes`, the per-game explanations. Those are
selected by `src.analysis.game_notes` and phrased by Claude, cached under a
hash of their facts so a rebuild whose numbers have not moved makes no API
call. `--no-ai` skips the phrasing entirely and ships the template sentences,
which is what happens anyway with no key.

**ONE BUILDER, TWO APPS, AND `--app` IS THE ONLY DIFFERENCE.** Everything
below — the freshness gate, the notes, the stories, the ask briefs, the
history split, the stale-file prune and the three-file check — is identical
for v3 and v4, because they render the same payload. Copying it into a
`53_export_v4.py` would have made two scripts that drift, and the thing that
actually differs is one import. The file keeps its name: `58_deploy.py` and
`scripts/week_rollover.sh` both reach for it by path, and three tests read
its source.
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
    ap.add_argument("--app", default="v3", choices=["v3", "v4"],
                    help="which look to render; v4 is the Hashmark design")
    ap.add_argument("--out", default=None,
                    help="output directory (default: site/<app>)")
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--brand", default="Pick Six")
    ap.add_argument("--no-ai", action="store_true",
                    help="ship the template sentences; make no API call")
    ap.add_argument("--force", action="store_true",
                    help="publish even when artifacts predate the served model")
    a = ap.parse_args()
    # Derived from --app rather than defaulted in argparse, so `--app v4`
    # alone lands in site/v4 and nobody has to pass the directory twice.
    if a.out is None:
        a.out = f"site/{a.app}"

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

    print(f"building {a.app} ...", file=sys.stderr)
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

    # HOW EACH GAME IS LIKELY TO GO, in four paragraphs, under the notes that
    # support it. Same split as the notes and the same guards: the facts are
    # computed here, the prose is written around them, and a story whose
    # numbers, names or directions do not check out falls back to its
    # template rather than being printed.
    from src.analysis import game_story
    stories = game_story.build(payload, use_ai=not a.no_ai)
    payload["stories"] = stories
    wrote = sum(1 for s in stories.values() if s.get("written"))
    print(f"  {len(stories)} stories, {wrote} written, "
          f"{len(stories) - wrote} on the template", file=sys.stderr)
    for s in stories.values():
        why = s.get("rejected") or (
            "a number was not in the facts" if s.get("unsourced") else None)
        if why:
            print(f"    held back: {why}", file=sys.stderr)

    # One brief per game for the Ask box. Written as separate files, never
    # inlined: the browser sends a game id and the SERVER loads the brief, so
    # nothing a reader types can become context. See `askctx`.
    from src.export.askctx import build as ask_briefs
    briefs = ask_briefs(payload)

    # OUT OF THE PAYLOAD BEFORE IT IS RENDERED. The whole record is about
    # 1.6 MB and the page already loads 4.6; it is written per market and
    # fetched when a reader opens a player, the same way a past week is.
    full = payload.pop("_pastlines_full", None) or {}
    # The same arrangement one level up: 413 KB of team record against 22 KB
    # inlined, written here and fetched when a reader opens a team.
    teams = payload.pop("_teamlines_full", None) or {}

    # THE ONE LINE THAT DIFFERS BETWEEN THE TWO APPS.
    if a.app == "v4":
        from src.export.v4 import render
    else:
        from src.export.v3 import render
    files = render(payload)
    if teams:
        files["data/tlines.json"] = json.dumps(
            teams, separators=(",", ":"), allow_nan=False)
        print(f"  team line record "
              f"({len(files['data/tlines.json']) / 1024:,.0f} KB)",
              file=sys.stderr)
    if full:
        per: dict = {}
        for name, markets in full.items():
            for mkt, rows in markets.items():
                per.setdefault(mkt, {})[name] = rows
        for mkt, rows in per.items():
            files[f"data/hist-{mkt}.json"] = json.dumps(
                rows, separators=(",", ":"), allow_nan=False)
        print(f"  {len(per)} history files "
              f"({sum(len(files['data/hist-' + m + '.json']) for m in per) / 1024:,.0f} KB)",
              file=sys.stderr)
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
                + list(data_dir.glob("hist-*.json")) \
                + list(data_dir.glob("tlines.json")) \
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
