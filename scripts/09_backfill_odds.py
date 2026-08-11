#!/usr/bin/env python3
"""Backfill historical sportsbook TD props into the odds archive.

The Odds API only serves *current* markets through the normal endpoints — once a
game kicks off those prices are gone. Its historical endpoints expose snapshots
taken every 5 minutes, with player props available from 2023-05-03 onward. This
script walks past NFL seasons, pulls the closing line for each game, and appends
it to `data/raw/odds_history.parquet`.

That archive is the only thing that can falsify the model. Without it, "we beat
the market" is untestable; with it you can fit the model/market blend weight,
measure closing-line value, and backtest the bet card's real ROI.

    # See what it would cost before spending anything
    python scripts/09_backfill_odds.py --seasons 2023 2024 2025 --dry-run

    # Run it, refusing to spend more than 15,000 credits
    python scripts/09_backfill_odds.py --seasons 2023 2024 2025 --max-credits 15000

Safe to interrupt and re-run: events already archived are skipped.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

import polars as pl
import requests

from src.ingest.odds_api import (API_BASE, SPORT, _get_api_key, _median,
                                 _american_to_implied, _prob_to_american)
from src.ingest.odds_history import HISTORY_PATH, append_snapshot
from src.features.odds_features import TEAM_ABBREV, _normalize_name
from src.utils.paths import get_path

#: Credits are billed per market, so pulling only the market you actually bet
#: halves the cost of a backfill.
MARKET_KEYS = {
    "anytime": "player_anytime_td",
    "first": "player_1st_td",
    "both": "player_anytime_td,player_1st_td",
}
REGIONS = "us"
#: Player props exist in the historical archive only from this date.
PROPS_AVAILABLE_FROM = datetime(2023, 5, 3, 5, 30, tzinfo=timezone.utc)
#: Snapshots are published every 5 minutes; ask for the last one before kickoff.
CLOSING_OFFSET = timedelta(minutes=5)
#: Opening snapshot. Probing a 2024 Sunday game, anytime-TD props were absent
#: 120h before kickoff, thin at 96h (3 books, 85 outcomes) and settled by 72h
#: (5 books, 145). 72h is therefore the earliest point with enough books for a
#: stable consensus — an opening line taken from three books is mostly noise.
OPENING_OFFSET = timedelta(hours=72)


class Budget:
    """Track API credits and stop before blowing through the cap."""

    def __init__(self, limit: int | None):
        self.limit = limit
        self.used = 0
        self.remaining_reported: str | None = None

    def charge(self, resp: requests.Response) -> None:
        used = resp.headers.get("x-requests-last")
        self.used += int(used) if used and used.isdigit() else 0
        self.remaining_reported = resp.headers.get("x-requests-remaining")

    def exhausted(self) -> bool:
        return self.limit is not None and self.used >= self.limit


def _get(path: str, params: dict, budget: Budget, retries: int = 3) -> dict | None:
    """GET with retry. Returns None on a 404-style miss (no snapshot at that time)."""
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
            raise SystemExit("401 Unauthorized — check ODDS_API_KEY, or the plan "
                             "may not include historical access.")
        print(f"      HTTP {r.status_code}: {r.text[:160]}")
        time.sleep(2 ** attempt)
    return None


def _games(seasons: list[int]) -> pl.DataFrame:
    """Scheduled games with kickoff times, from the local schedule."""
    sched = pl.read_parquet(get_path("raw") / "schedules.parquet")
    df = sched.filter(pl.col("season").is_in(seasons)).select(
        ["game_id", "season", "week", "gameday", "gametime", "home_team", "away_team"]
    )
    return df.drop_nulls("gameday").sort(["season", "week"])


def _kickoff(row: dict) -> datetime | None:
    """Best-effort UTC kickoff. Schedule times are US Eastern."""
    day, tm = row.get("gameday"), row.get("gametime") or "13:00"
    if not day:
        return None
    try:
        naive = datetime.strptime(f"{day} {tm}", "%Y-%m-%d %H:%M")
    except ValueError:
        try:
            naive = datetime.strptime(str(day), "%Y-%m-%d")
        except ValueError:
            return None
    # Eastern is UTC-4/-5; use -4 and lean on the 5-minute snapshot grid.
    return naive.replace(tzinfo=timezone.utc) + timedelta(hours=4)


def _already_archived(market_names: list[str], snapshot: str = "close") -> set[str]:
    """Games already archived *for every market being requested*.

    Keyed by market and by snapshot phase, not just game_id: otherwise a first
    pass for anytime-TD would make a later first-TD pass skip every game as
    "done", and a closing-line backfill would make an opening-line pass skip
    everything it has never actually fetched.
    """
    if not HISTORY_PATH.exists():
        return set()
    hist = pl.read_parquet(HISTORY_PATH)
    if "game_id" not in hist.columns or "market" not in hist.columns:
        return set()
    # Rows written before the column existed are closing lines by construction.
    if "snapshot" not in hist.columns:
        hist = hist.with_columns(pl.lit("close").alias("snapshot"))
    hist = hist.filter(pl.col("snapshot") == snapshot)

    done: set[str] | None = None
    for m in market_names:
        got = set(hist.filter(pl.col("market") == m)["game_id"].drop_nulls().to_list())
        done = got if done is None else (done & got)
    return done or set()


def _find_event(snapshot: str, home: str, away: str, budget: Budget) -> str | None:
    """Resolve our game to the API's event id at a given snapshot."""
    data = _get(f"/historical/sports/{SPORT}/events",
                {"apiKey": _get_api_key(), "date": snapshot}, budget)
    if not data:
        return None
    for ev in data.get("data", []):
        h = TEAM_ABBREV.get(ev.get("home_team", ""))
        a = TEAM_ABBREV.get(ev.get("away_team", ""))
        if h == home and a == away:
            return ev["id"]
    return None


def _parse_event_odds(payload: dict) -> list[dict]:
    """Consensus median per player per market, with vig removed where possible."""
    event = payload.get("data") or {}
    rows: list[dict] = []
    for market_key, market_name in (("player_anytime_td", "anytime_td"),
                                    ("player_1st_td", "first_td")):
        quotes: dict[str, dict] = {}
        for bk in event.get("bookmakers", []):
            for mkt in bk.get("markets", []):
                if mkt.get("key") != market_key:
                    continue
                for out in mkt.get("outcomes", []):
                    side = str(out.get("name", "")).lower()
                    if side not in ("yes", "no"):
                        continue
                    player = out.get("description")
                    if not player:
                        continue
                    q = quotes.setdefault(player, {"yes": [], "no": [], "odds": []})
                    q[side].append(_american_to_implied(out["price"]))
                    if side == "yes":
                        q["odds"].append(out["price"])

        for player, q in quotes.items():
            if not q["yes"]:
                continue
            p_yes = _median(q["yes"])
            p_no = _median(q["no"]) if q["no"] else None
            rows.append({
                "player_name_raw": player,
                "player_name_norm": _normalize_name(player),
                "market": market_name,
                "odds": _prob_to_american(p_yes),
                "implied_prob": round(p_yes, 4),
                "fair_prob": round(p_yes / (p_yes + p_no), 4) if p_no else None,
                "n_books": len(q["yes"]),
                "overround": round(p_yes + p_no, 4) if p_no else None,
            })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, nargs="+", default=[2023, 2024, 2025])
    ap.add_argument("--snapshot", choices=["open", "close"], default="close",
                    help="Which end of the market to capture. 'close' is 5 min "
                         "before kickoff; 'open' is 72h before, the earliest "
                         "point with enough books to form a consensus. Both "
                         "together make closing-line value measurable.")
    ap.add_argument("--max-credits", type=int, default=None,
                    help="Stop once this many credits have been spent.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Estimate the cost and exit without calling the API.")
    ap.add_argument("--sleep", type=float, default=0.3, help="Seconds between calls.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Only process the first N games. Use for a trial run.")
    ap.add_argument("--markets", choices=sorted(MARKET_KEYS), default="anytime",
                    help="Which prop markets to archive. Credits are billed per "
                         "market, so 'anytime' costs half what 'both' costs.")
    args = ap.parse_args()
    markets = MARKET_KEYS[args.markets]
    n_markets = len(markets.split(","))

    games = _games(args.seasons)
    market_names = ["anytime_td" if k == "player_anytime_td" else "first_td"
                    for k in markets.split(",")]
    done = _already_archived(market_names, args.snapshot)
    todo = [r for r in games.iter_rows(named=True) if r["game_id"] not in done]

    # Props only exist in the archive after PROPS_AVAILABLE_FROM.
    todo = [r for r in todo if (_kickoff(r) or PROPS_AVAILABLE_FROM) >= PROPS_AVAILABLE_FROM]

    if args.limit:
        todo = todo[:args.limit]
    n = len(todo)
    print(f"Seasons {args.seasons}: {games.height} scheduled games, "
          f"{len(done)} already archived, {n} to fetch.")
    lo, hi = n_markets, n_markets * 10   # docs disagree on the 10x multiplier
    print(f"Markets: {markets} ({n_markets})  Regions: {REGIONS} (1)")
    print(f"Cost per game: {lo} credits if billed markets x regions, "
          f"{hi} if the 10x historical multiplier applies.")
    print(f"Estimated total: {n * lo + n:,} - {n * hi + n:,} credits "
          f"(includes ~{n:,} event lookups at 1 each).")
    print(f"Worst case fits a 20,000-credit plan: "
          f"{'YES' if n * hi + n <= 20000 else 'NO — narrow scope or use a bigger plan'}")
    if args.dry_run:
        print("\nDry run — nothing fetched. Re-run without --dry-run to proceed.")
        return 0

    if not _get_api_key():
        print("No ODDS_API_KEY in .env or environment.")
        return 1

    budget = Budget(args.max_credits)
    fetched = skipped = 0

    for i, row in enumerate(todo, 1):
        if budget.exhausted():
            print(f"\nStopping: credit cap of {args.max_credits} reached.")
            break

        ko = _kickoff(row)
        if ko is None:
            skipped += 1
            continue
        offset = OPENING_OFFSET if args.snapshot == "open" else CLOSING_OFFSET
        snapshot = (ko - offset).strftime("%Y-%m-%dT%H:%M:%SZ")

        eid = _find_event(snapshot, row["home_team"], row["away_team"], budget)
        if not eid:
            skipped += 1
            print(f"  [{i}/{n}] {row['game_id']}: no event at {snapshot}")
            time.sleep(args.sleep)
            continue

        payload = _get(
            f"/historical/sports/{SPORT}/events/{eid}/odds",
            {"apiKey": _get_api_key(), "date": snapshot, "regions": REGIONS,
             "markets": markets, "oddsFormat": "american"},
            budget,
        )
        if not payload:
            skipped += 1
            time.sleep(args.sleep)
            continue

        rows = _parse_event_odds(payload)
        if not rows:
            skipped += 1
            print(f"  [{i}/{n}] {row['game_id']}: no TD props in snapshot")
            time.sleep(args.sleep)
            continue

        snap = pl.DataFrame(rows).with_columns(pl.lit(row["game_id"]).alias("game_id"))
        append_snapshot(snap, season=row["season"], week=row["week"],
                        snapshot=args.snapshot)
        fetched += 1
        print(f"  [{i}/{n}] {row['game_id']}: {len(rows)} prices "
              f"(spent {budget.used}, remaining {budget.remaining_reported})")
        time.sleep(args.sleep)

    print(f"\nDone. {fetched} games archived, {skipped} skipped, "
          f"{budget.used} credits spent. Archive: {HISTORY_PATH}")
    print("Next: `make train` refits the blend weight from the graded history.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
