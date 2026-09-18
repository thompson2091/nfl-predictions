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
    for name, body in files.items():
        (out / name).write_text(body)
        print(f"  {out / name}  ({len(body) / 1024:,.0f} KB)", file=sys.stderr)
    print(f"\nupload all three of {', '.join(files)} to the same directory.\n"
          f"the worker's scope is where it is served from, so a page without "
          f"its sw.js beside it never goes offline and never says so.",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
