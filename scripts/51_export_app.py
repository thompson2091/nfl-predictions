"""Build site/v2 — the same board as an installable app.

    python scripts/51_export_app.py [--out site/v2] [--brand "Pick Six"]

Three files, and they go up together: `index.html`, `manifest.webmanifest`
and `sw.js`. The worker has to sit beside the page it serves — its scope is
the directory it is fetched from — so uploading two of the three gives an app
that loads and never works offline, silently.

The payload is `scripts/47_export_site.py:build`, unchanged and unforked. v1
and v2 are the same numbers; what differs is the shell around them. See
`src/export/pwa.py`.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, ".")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="site/v2",
                    help="directory to write the three files into")
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--brand", default="Pick Six")
    a = ap.parse_args()

    spec = importlib.util.spec_from_file_location(
        "site_export", Path(__file__).with_name("47_export_site.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    print("building the app ...", file=sys.stderr)
    payload = mod.build(a.season, a.week, a.brand)

    from src.export.pwa import render
    files = render(payload)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    # Stale week files are REMOVED before writing. A market that loses a week
    # — a re-run that finds its play-by-play incomplete, a market dropped from
    # the export — would otherwise leave its old file on disk, and the page,
    # which asks the index rather than the directory, would never fetch it
    # again while a future upload shipped it forever.
    data_dir = out / "data"
    if data_dir.exists():
        keep = {out / n for n in files}
        for old_file in data_dir.glob("h-*.json"):
            if old_file not in keep:
                old_file.unlink()

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
        print(f"  {out / 'data'}/  ({len(side)} week files, {total:,.0f} KB, "
              f"fetched on demand)", file=sys.stderr)
    print(f"\nupload {', '.join(n for n, _ in top)}"
          + (f" AND the data/ folder" if side else "")
          + " to the same directory.\n"
          f"the worker's scope is where it is served from, so a page without "
          f"its sw.js beside it never goes offline and never says so."
          + (f"\nwithout data/, every past week is empty — the page loads and "
             f"the picker still lists them." if side else ""),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
