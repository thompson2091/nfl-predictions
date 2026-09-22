#!/usr/bin/env python3
"""Backfill historical moneyline, spread and total into the game-line archive.

    python scripts/55_backfill_game_lines.py --seasons 2023 2024 2025 --dry-run
    python scripts/55_backfill_game_lines.py --seasons 2023 2024 2025 --max-credits 20000

The live endpoints serve only current markets, so a week not captured is gone.
The HISTORICAL endpoint is not — it sells snapshots on a 5-minute grid, and the
2023-2025 player-prop archive was built from it. Game lines go back further
than props do and cost far less, for one structural reason: the bulk odds
endpoint returns EVERY game at a timestamp in one call, where props need a call
per event. A week of closes costs a handful of calls rather than sixteen.

That is what makes reverse line movement measurable now rather than in a month.
RLM needs an open and a close on the same line, and waiting for the live
captures to accumulate them would mean a bets page whose every hit rate reads
n=1 until December.

Open is taken 72h before kickoff and close 5 minutes before, the same offsets
the prop backfill settled on. Games are grouped by kickoff so a Sunday early
window is not priced with a Sunday night snapshot.

Safe to interrupt and re-run: a (season, week, snapshot) already in the archive
is skipped.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

import polars as pl
import requests

from src.ingest.game_lines import GAME_MARKETS, LINES_PATH, append_snapshot
from src.ingest.odds_api import API_BASE, SPORT, _american_to_implied, _get_api_key
from src.features.odds_features import TEAM_ABBREV
from src.utils.paths import get_path

#: The Odds API publishes historical snapshots every 5 minutes.
CLOSE_OFFSET = timedelta(minutes=5)
#: Far enough out that the line is up and settled, matching the prop backfill.
OPEN_OFFSET = timedelta(hours=72)


class Budget:
    def __init__(self, limit=None):
        self.limit, self.used, self.remaining = limit, 0, None

    def charge(self, r):
        used = r.headers.get("x-requests-used")
        rem = r.headers.get("x-requests-remaining")
        if rem is not None:
            self.remaining = rem
        self.used += 1
        return used

    def exhausted(self):
        return self.limit is not None and self.used >= self.limit


def _get(path, params, budget, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(f"{API_BASE}{path}", params=params, timeout=30)
        except requests.RequestException as e:
            print(f"      network error ({e}); retrying")
            time.sleep(2 ** attempt)
            continue
        budget.charge(r)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (404, 422):
            return None
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 401:
            raise SystemExit("401 Unauthorized — check ODDS_API_KEY, or the "
                             "plan may not include historical access.")
        print(f"      HTTP {r.status_code}: {r.text[:160]}")
        time.sleep(2 ** attempt)
    return None


def _kickoff(day: str, tm: str | None) -> datetime | None:
    """UTC kickoff from a schedule row. `gametime` is US Eastern."""
    if not day:
        return None
    try:
        naive = datetime.strptime(f"{day} {tm or '13:00'}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    # Eastern is UTC-4 in season; the 5-minute grid absorbs the DST edge.
    return naive.replace(tzinfo=timezone.utc) + timedelta(hours=4)


def _already(season: int, week: int, snapshot: str) -> bool:
    if not LINES_PATH.exists():
        return False
    d = pl.scan_parquet(LINES_PATH).filter(
        (pl.col("season") == season) & (pl.col("week") == week)
        & (pl.col("snapshot") == snapshot)).select(pl.len()).collect().item()
    return d > 0


def _rows_from(payload, season, week, allowed, snapshot) -> list[dict]:
    """Flatten one historical snapshot, keeping only games in `allowed`.

    `allowed` is the set of kickoff instants (to the minute) that belong to the
    week being written. The bulk endpoint returns EVERY game live at that
    timestamp, not just the next one — an open snapshot taken 72h before week
    1 also carries weeks 2 and 3, already posted. Without this filter week 1
    wrote 5,422 quotes against a normal week's 1,678 and the surplus was other
    weeks' games filed under week 1, which nothing downstream would have
    questioned.
    """
    captured = payload.get("timestamp")
    out = []
    for ev in payload.get("data", []):
        ct = ev.get("commence_time")
        if allowed is not None and (not ct or ct[:16] not in allowed):
            continue
        h = TEAM_ABBREV.get(ev.get("home_team", ""))
        a = TEAM_ABBREV.get(ev.get("away_team", ""))
        for bk in ev.get("bookmakers", []):
            for m in bk.get("markets", []):
                if m.get("key") not in GAME_MARKETS:
                    continue
                for o in m.get("outcomes", []):
                    price = o.get("price")
                    if price is None:
                        continue
                    out.append({
                        "captured_at": captured,
                        "book_last_update": m.get("last_update"),
                        "commence_time": ct,
                        "game_id": f"{a}_{h}" if a and h else None,
                        "home_team": h, "away_team": a,
                        "bookmaker": bk.get("key"), "market": m.get("key"),
                        "outcome": TEAM_ABBREV.get(o.get("name"), o.get("name")),
                        "outcome_raw": o.get("name"),
                        "point": o.get("point"), "odds": price,
                        "implied_prob": _american_to_implied(price),
                    })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seasons", type=int, nargs="+", default=[2023, 2024, 2025])
    ap.add_argument("--snapshots", nargs="+", default=["open", "close"],
                    choices=["open", "close"])
    ap.add_argument("--regions", default="us,us2")
    ap.add_argument("--max-credits", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.3)
    a = ap.parse_args()

    sched = (pl.read_parquet(get_path("raw") / "schedules.parquet")
             .filter(pl.col("season").is_in(a.seasons) & (pl.col("game_type") == "REG"))
             .select(["season", "week", "gameday", "gametime"])
             .drop_nulls("gameday"))

    # One call per distinct kickoff time, not per game: the bulk endpoint
    # returns every game live at that instant.
    slots = []
    for r in sched.iter_rows(named=True):
        k = _kickoff(str(r["gameday"])[:10], r.get("gametime"))
        if k:
            slots.append((int(r["season"]), int(r["week"]), k))
    slots = sorted(set(slots))
    by_week: dict[tuple, list] = {}
    for s, w, k in slots:
        by_week.setdefault((s, w), []).append(k)

    calls = sum(len(set(v)) for v in by_week.values()) * len(
        [x for x in a.snapshots if x == "close"]) + len(by_week) * len(
        [x for x in a.snapshots if x == "open"])
    cost = calls * len(GAME_MARKETS) * len(a.regions.split(","))
    print(f"{len(by_week)} season-weeks, {calls} snapshot calls, "
          f"~{cost:,} credits at {len(GAME_MARKETS)} markets x "
          f"{len(a.regions.split(','))} regions")
    if a.dry_run:
        return 0

    budget, key, wrote = Budget(a.max_credits), _get_api_key(), 0
    for (season, week), kicks in sorted(by_week.items()):
        for snap in a.snapshots:
            if _already(season, week, snap):
                continue
            if budget.exhausted():
                print("credit limit reached — stopping"); return 0
            rows = []
            times = sorted(set(kicks)) if snap == "close" else [min(kicks)]
            for k in times:
                at = (k - CLOSE_OFFSET) if snap == "close" else (k - OPEN_OFFSET)
                data = _get(f"/historical/sports/{SPORT}/odds",
                            {"apiKey": key, "regions": a.regions,
                             "markets": ",".join(GAME_MARKETS),
                             "oddsFormat": "american",
                             "date": at.strftime("%Y-%m-%dT%H:%M:%SZ")}, budget)
                time.sleep(a.sleep)
                if not data:
                    continue
                # A close is filed against its own kickoff; an open is taken
                # once for the week and must accept every kickoff in it.
                allowed = ({k.strftime("%Y-%m-%dT%H:%M:%SZ")[:16]}
                           if snap == "close"
                           else {t.strftime("%Y-%m-%dT%H:%M:%SZ")[:16]
                                 for t in kicks})
                rows += _rows_from(data, season, week, allowed, snap)
            if rows:
                append_snapshot(rows, season=season, week=week, snapshot=snap)
                wrote += len(rows)
            print(f"  {season} wk{week:>2} {snap:<5} {len(rows):>6,} quotes"
                  f"   (credits remaining {budget.remaining})")
    print(f"\nDone. {wrote:,} quotes written to {LINES_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
