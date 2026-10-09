#!/usr/bin/env python3
"""Recover weeks 1-4's player boards from the builds deployed before kickoff.

    python scripts/68_recover_boards.py DIR [--season 2026] [--dry-run]

`DIR` holds copies of `/var/www/html/bets/*.html` from the server.

**THE BOARDS WERE NEVER LOST, ONLY NEVER KEPT IN ONE PLACE.** Every deploy
since 2026-08-17 is still on the server, and each page carries its whole
payload: the over/under boards with both prices and the model's numbers,
and the touchdown boards, as they stood when that page was built. So for
every game of weeks 1-4 this takes the LAST build made before that game's
kickoff and writes its board into `prediction_freeze` — which turns the
Record page's player results for those weeks from "rebuilt with today's
model" into the numbers that were actually on the site.

**BUILT BEFORE KICKOFF, BY THE PAYLOAD'S OWN CLOCK.** The server's file
times run about forty minutes behind the `built` stamp each payload carries
(the laptop's clock), and three builds that looked pre-kickoff by file time
were made after the Thursday and Monday games had started. `built` is the
test, with no margin needed because it is the time the numbers were made.

A game the freeze already holds is left alone: that board was recorded live.
Week 1 has touchdown boards only — the over/under boards were not on the
site until week 2.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, ".")

from src.export import prediction_freeze as PF                  # noqa: E402

ET = ZoneInfo("America/New_York")
OU = {"rushing_yards": ("yards", "rushing_yards"),
      "receiving_yards": ("yards", "receiving_yards"),
      "passing_yards": ("yards", "passing_yards"),
      "receptions": ("receptions", None)}


def payload(path: Path) -> dict | None:
    h = path.read_text(errors="replace")
    m = re.search(r'<script id="payload"[^>]*>(.*?)</script>', h, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1).replace("<\\/", "</"))
    except json.JSONDecodeError:
        return None


def built_et(p: dict) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(p["built"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(ET).replace(tzinfo=None)


def _american(prob: float | None) -> float | None:
    if prob is None or not (0 < prob < 1):
        return None
    return round(-100 * prob / (1 - prob)) if prob >= 0.5 \
        else round(100 * (1 - prob) / prob)


def ou_rows(p: dict, market: str) -> list[dict]:
    """The board's lines in the freeze's shape. The under is priced the way
    the page priced it: the overround less the over's implied probability."""
    from src.evaluation.prop_edge import load_threshold

    block, key = OU[market]
    src = (p.get(block) or {})
    rows = ((src.get(key) or {}).get("rows") if key else src.get("rows")) or []
    t = load_threshold(market)
    out = []
    for r in rows:
        line = r.get("point") if r.get("point") is not None else r.get("open_point")
        if line is None or not r.get("game_id"):
            continue
        imp, ovr = r.get("implied_prob"), r.get("overround")
        under = _american(ovr - imp) if imp is not None and ovr is not None else None
        m, ours, book = r.get("model_only"), r.get("ours"), r.get("fair_prob")
        x = dict(r, point=float(line), price_over=r.get("odds"),
                 price_under=under,
                 model_side=None if m is None else ("over" if m >= 0.5 else "under"))
        # The Gaps rule's margin was fitted on 2024-25 only, so applying it
        # to these weeks is out of sample even though it was fitted later.
        if t is not None and ours is not None and book is not None:
            e = (ours - book) * 100
            x.update(gap_side="over" if e > t else ("under" if e < -t else None),
                     gap_edge_pp=round(abs(e), 3), gap_threshold_pp=t)
        out.append(x)
    return out


def td_rows(p: dict, market: str) -> list[dict]:
    for m in p.get("markets") or []:
        if m.get("key") != market:
            continue
        out = []
        for r in m.get("players") or []:
            try:
                odds = int(str(r.get("odds")).replace("+", "")) \
                    if r.get("odds") not in (None, "", "—") else None
            except ValueError:
                odds = None
            out.append({"game_id": r.get("game_id"), "player_name": r.get("player"),
                        "team": r.get("team"), "probability": r.get("ours"),
                        "prob_model": r.get("model_only"), "rank": r.get("rank"),
                        "has_market_price": bool(r.get("priced")), "odds": odds,
                        "book": r.get("book")})
        return out
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dir")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--weeks", default="1,2,3,4")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    from src.evaluation.tracked_rules import kickoffs

    builds = []
    for f in sorted(Path(a.dir).glob("*.html")):
        p = payload(f)
        t = built_et(p) if p else None
        if p and t:
            builds.append((t, f.name, p))
    builds.sort(key=lambda b: b[0])
    print(f"{len(builds)} builds read")

    total = 0
    for week in (int(w) for w in a.weeks.split(",")):
        kicks = kickoffs(a.season, week)
        for market in ("anytime_td", "first_td") + tuple(OU):
            wrote, missed = 0, []
            for gid, kick in sorted(kicks.items(), key=lambda x: x[1]):
                # The newest build before kickoff that carries this game.
                got, src = None, None
                for t, name, p in reversed(builds):
                    if t >= kick:
                        continue
                    if p.get("week") not in (None, week):
                        continue
                    rows = td_rows(p, market) if market.endswith("_td") \
                        else ou_rows(p, market)
                    rows = [r for r in rows if r.get("game_id") == gid]
                    if rows:
                        got, src = rows, f"{name} built {t:%Y-%m-%d %H:%M} ET"
                        break
                if not got:
                    missed.append(gid)
                    continue
                if not a.dry_run:
                    wrote += PF.recover(got, a.season, week, market, src)
            total += wrote
            print(f"  week {week} {market:<16} {wrote:>2} recovered"
                  + (f", {len(missed)} with no pre-kickoff board" if missed else ""))
    if not a.dry_run:
        PF.flush()
    print(f"{total} game boards recovered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
