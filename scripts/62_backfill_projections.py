#!/usr/bin/env python3
"""Recover pre-kickoff projections from the builds still on the server.

Every deploy leaves a dated copy of the page under `/var/www/html/bets/`, and
each of those carries the whole payload — including, for a game that had not
kicked off yet, the projection the board was showing for it. That is exactly
what `projection_freeze` would have written down had it existed, so it can be
reconstructed for any week still in that archive.

    python scripts/62_backfill_projections.py            # report only
    python scripts/62_backfill_projections.py --write    # write the archive

WHAT IT CANNOT RECOVER. Weeks whose builds carry no game cards at all: 2026
weeks 1 and 2 were played before anything captured a spread for them, so the
games board was backfilled afterwards and no build ever showed a projection
for them. Those stay empty, and the export says so on every run.

Never overwrites an existing entry. The live export records the real thing;
this is for the gap before it existed.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.export import projection_freeze as PF  # noqa: E402

HOST = "root@squarespro.com"
KEY = Path.home() / ".ssh" / "id_ed25519_squarespro"

#: Runs on the server, where the builds are. Emits one line per card that had
#: no final in that build, which is the definition of "still a forecast".
REMOTE = r'''
import glob, json, os, re
for p in sorted(glob.glob("/var/www/html/bets/*.html")):
    try:
        blob = open(p, encoding="utf-8", errors="replace").read()
    except Exception:
        continue
    m = re.search(r'<script[^>]*id="payload"[^>]*>(.*?)</script>', blob, re.S)
    if not m:
        continue
    try:
        D = json.loads(m.group(1))
    except Exception:
        continue
    G = D.get("games") or {}
    for c in G.get("cards") or []:
        if c.get("model_win_home") is None:
            continue
        if c.get("final_home") is not None and c.get("final_away") is not None:
            continue
        print(json.dumps({"file": os.path.basename(p), "season": D.get("season"),
                          "week": D.get("week"), "card": c}))
'''


def _order(name: str) -> tuple[int, int]:
    """`20260925.v10` sorts after `20260925.v2`, which lexical order does not."""
    m = re.match(r"(\d+)\.v(\d+)\.html", name)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def fetch() -> list[dict]:
    if not KEY.exists():
        raise SystemExit(f"no deploy key at {KEY}")
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-i", str(KEY), HOST, "python3 -"],
        input=REMOTE, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"remote scan failed: {r.stderr[:400]}")
    return [json.loads(x) for x in r.stdout.splitlines() if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="write the recovered entries (default: report only)")
    a = ap.parse_args()

    rows = sorted(fetch(), key=lambda x: _order(x["file"]))
    print(f"{len(rows)} pre-kickoff cards across the archived builds")

    # LAST ONE WINS, which is the last build made before that game kicked off.
    best: dict[tuple[int, int, str], dict] = {}
    for r in rows:
        s, w, c = r["season"], r["week"], r["card"]
        if not (s and w and c.get("game_id")):
            continue
        best[(int(s), int(w), c["game_id"])] = r

    added = skipped = 0
    for (s, w, gid), r in sorted(best.items()):
        store = PF.load(s)
        wk = store.setdefault(str(w), {})
        if gid in wk:
            skipped += 1
            continue
        snap = {f: r["card"][f] for f in PF.FIELDS
                if r["card"].get(f) is not None}
        if not snap:
            continue
        print(f"  {s} wk{w} {gid:<10} from {r['file']:<22} "
              f"spread {snap.get('model_spread')}")
        if a.write:
            wk[gid] = snap
            PF._DIRTY.add(s)
        added += 1

    print(f"\n{added} recoverable, {skipped} already recorded")
    if a.write:
        for p in PF.flush():
            print(f"wrote {p}")
    else:
        print("nothing written; re-run with --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
