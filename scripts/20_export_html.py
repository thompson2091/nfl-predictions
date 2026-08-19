#!/usr/bin/env python3
"""Freeze the dashboard into one publishable HTML file.

    python scripts/20_export_html.py                 # -> site/index.html
    python scripts/20_export_html.py --open
    python scripts/20_export_html.py --full           # keep the app's long form

The app is the source of truth. This runs app.py against a recording Streamlit
(src/export/capture.py) and lays the captured numbers and prose out for a reader
who has no sidebar and no reruns — so there is nothing to keep in sync when the
board's columns, the tier thresholds or any sentence in the app changes.

Both markets go into the one file behind a switch, each on the model config
names as its production choice. The output has no external requests: open the
file anywhere, or copy it to any static host.

By default the page is the trimmed version of the app: no expanders, no `help=`
tooltips, and each run of prose cut to the sentence it opens with — src/export/
simplify.py has the reasoning. `--full` publishes the app's own long form.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, ".")

from src.export.capture import run_app
from src.export.page import build_page
from src.utils.config import get_config, production_model

APP = "app.py"

#: The tabs that make sense to publish, as (pane id, the app's tab label).
#: Weekly results and Betting reality are deliberately out: one is a graded
#: replay that is empty until games are played, and the other is betting advice
#: that should not be the thing a stranger lands on.
#:
#: "Player types" is in because it answers a question the other two cannot —
#: not how good the number is, but what kind of player and what kind of bet it
#: is about. Its grouping is fitted on the training seasons and scored on the
#: held-out ones (`scripts/21_clusters.py`), so it publishes a real measurement
#: rather than a description of the rows it was drawn from. Its "View" control
#: offers Player types and Bet types; an export captures one value, and this
#: publishes the first.
PANES = [("board", "Full board"), ("model", "Model performance"),
         ("clusters", "Player types")]

MARKETS = [
    ("anytime_td", "Anytime TD"),
    ("first_td", "First TD"),
]

DEK = ("A model that prices every player's chance of scoring, alongside the "
       "bookmaker's own number for the same player — and an honest account of "
       "how often it has been right.")


def capture(target_type: str, quiet: bool):
    """Run the app for one market, with the pipeline's chatter kept out of the way."""
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink) if quiet else contextlib.nullcontext():
        cap = run_app(APP, {"Target Type": target_type})
    return cap


def _record(target_type: str) -> dict:
    """The graded combination replay, if it has been run.

    Carried into the page so the strip above the combinations table answers for
    whatever its controls currently say, rather than for the one setting that
    happened to be captured. Empty is fine: the section then reads as it does
    in the app before `make combos`.
    """
    from src.evaluation.combo_backtest import load
    from src.utils.paths import get_path
    stats = load(get_path("output", target_type) / "combo_backtest.json")
    if not stats:
        return {}
    # Rounded on the way in: five decimals is far past what a tile prints, and
    # the raw floats were most of the page's weight.
    def _tidy(row: dict) -> dict:
        return {k: (round(v, 5) if isinstance(v, float) else v)
                for k, v in row.items()}

    return {"span": stats.get("span", ""),
            "rows": [_tidy(r) for r in stats["rows"]]}


def _meta(cap, target_type: str) -> list[str]:
    """The sidebar selections, restated on the page — the sidebar is gone."""
    picked = {w["label"]: w["value"] for w in cap.widgets}
    season, week = picked.get("Season"), picked.get("Week")
    cfg = get_config()
    bits = []
    if season and week:
        bits.append(f"<b>{season}</b> week <b>{week}</b>")
    bits.append(f"model <b>{picked.get('Model') or production_model(target_type)}</b>")
    bits.append(f"accuracy measured on <b>{cfg['splits']['test_season']}</b> "
                f"and earlier held-out seasons")
    return bits


def main(out_dir: str, open_after: bool, quiet: bool, simple: bool) -> int:
    markets = []
    for key, label in MARKETS:
        print(f"capturing {key} ...", file=sys.stderr)
        cap = capture(key, quiet)
        tabs = [c for c in cap.root["children"]
                if c["t"] == "group" and c["kind"] == "tabs"]
        if not tabs:
            print(f"  app.py drew no tabs for {key} — nothing to export.",
                  file=sys.stderr)
            return 1
        have = {t["label"] for t in tabs[0]["children"]}
        missing = [lbl for _, lbl in PANES if lbl not in have]
        if missing:
            # A renamed tab would otherwise export as a silently missing
            # section, which reads as "this market has no board".
            print(f"  app.py has no tab named {missing!r}. Its tabs are "
                  f"{sorted(have)!r} — update PANES in this script.",
                  file=sys.stderr)
            return 1
        markets.append({"key": key, "label": label, "capture": cap,
                        "meta": _meta(cap, key), "record": _record(key)})

    built = datetime.now(timezone.utc).astimezone().strftime("%-d %B %Y")
    page = build_page(markets, panes=PANES, built=built,
                      title="NFL Touchdown Predictions", dek=DEK, simple=simple)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "index.html"
    path.write_text(page, encoding="utf-8")

    print(f"\n{path}  ({len(page.encode()) / 1024:.0f} KB, self-contained)")
    if open_after:
        webbrowser.open(path.resolve().as_uri())
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default="site", help="directory for index.html")
    p.add_argument("--open", action="store_true", help="open it when done")
    p.add_argument("--full", action="store_true",
                   help="publish the app's long form: expanders, tooltips, "
                        "and every paragraph of its explanations")
    p.add_argument("--verbose", action="store_true",
                   help="let the pipeline's own stdout through")
    a = p.parse_args()
    raise SystemExit(main(a.out, a.open, not a.verbose, not a.full))
