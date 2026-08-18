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

from src.ingest.odds_api import (API_BASE, DEFAULT_REGIONS, SPORT, MARKET_SPECS,
                                 SPEC_BY_MARKET, _get_api_key,
                                 parse_event_markets, specs_for)
from src.ingest.odds_history import (HISTORY_PATH, LEGACY_REGIONS,
                                     append_book_quotes, append_snapshot)
from src.features.odds_features import TEAM_ABBREV, _normalize_name
from src.utils.paths import get_path

#: Credits are billed per market, so pulling only the market you actually bet
#: is the difference between a backfill you can afford and one you cannot.
#: Values are archive market names; `specs_for` turns them into API keys, which
#: is also where an unknown one is refused.
MARKET_SETS: dict[str, tuple[str, ...]] = {
    "anytime": ("anytime_td",),
    "first": ("first_td",),
    "both": ("anytime_td", "first_td"),
    "rush": ("rush_td",),
    "reception": ("reception_td",),
    # The two new touchdown-type markets, which are over/under rather than
    # yes/no. See odds_api.MARKET_SPECS for why that distinction is declared
    # rather than inferred.
    "td_types": ("rush_td", "reception_td"),
    "receptions": ("receptions",),
    "all": tuple(sp.market for sp in MARKET_SPECS),
}
#: Default region set. See odds_api.DEFAULT_REGIONS for what `us` alone was
#: costing us — briefly, four books, the deepest longshot coverage on the
#: board, and the only two-sided anytime-TD price anyone posts. Overridable per
#: run because credits are billed markets x regions.
REGIONS = DEFAULT_REGIONS
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


def _already_archived(market_names: list[str], snapshot: str = "close",
                      regions: str | None = None) -> set[str]:
    """Games already archived *for every market being requested*.

    Keyed by market, snapshot phase and region set, not just game_id. A first
    pass for anytime-TD would otherwise make a later first-TD pass skip every
    game as "done", a closing-line backfill would make an opening-line pass
    skip everything it has never fetched — and a `us` backfill would make a
    `us,us2` top-up skip all 855 games while adding none of the four books it
    was run to collect.
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
    if regions is not None:
        if "regions" not in hist.columns:
            hist = hist.with_columns(pl.lit(LEGACY_REGIONS).alias("regions"))
        hist = hist.filter(pl.col("regions") == regions)

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


def _parse_event_odds(payload: dict, specs, game_id: str | None = None):
    """Consensus median per player per line per market, plus every book behind it.

    The parsing itself lives in `odds_api.parse_event_markets`, shared with the
    live fetch. This module used to carry its own copy — identical down to the
    `side not in ("yes", "no")` filter that silently drops every over/under
    outcome — and this is the copy that spends the credits.

    It also used to return the consensus alone and drop the per-book detail on
    the floor. That detail arrives in the same response for no extra credits,
    is what line shopping is measured from, and the historical endpoint will
    not sell the snapshot a second time — so a backfill that discards it is
    paying full price for a fraction of the data. The live fetch has archived
    it since `BOOKS_PATH` existed; this path never did.
    """
    event = payload.get("data") or {}
    consensus, book_rows = parse_event_markets(event, specs, game_id=game_id)
    for row in consensus:
        row["player_name_norm"] = _normalize_name(row["player_name_raw"])
        row.pop("game_id", None)
    for row in book_rows:
        row["player_name_norm"] = _normalize_name(row["player_name_raw"])
    return consensus, book_rows


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
    ap.add_argument("--regions", default=REGIONS,
                    help="Bookmaker regions, comma separated. Credits are "
                         "billed markets x regions, so widening this widens "
                         "the bill in proportion.")
    ap.add_argument("--markets", choices=sorted(MARKET_SETS), default="anytime",
                    help="Which prop markets to archive. Credits are billed per "
                         "market, so 'anytime' costs half what 'both' costs.")
    args = ap.parse_args()
    market_names = list(MARKET_SETS[args.markets])
    specs = specs_for(market_names)
    markets = ",".join(sp.key for sp in specs)
    n_markets = len(specs)

    games = _games(args.seasons)
    done = _already_archived(market_names, args.snapshot, args.regions)
    todo = [r for r in games.iter_rows(named=True) if r["game_id"] not in done]

    # Props only exist in the archive after PROPS_AVAILABLE_FROM.
    todo = [r for r in todo if (_kickoff(r) or PROPS_AVAILABLE_FROM) >= PROPS_AVAILABLE_FROM]

    if args.limit:
        todo = todo[:args.limit]
    n = len(todo)
    print(f"Seasons {args.seasons}: {games.height} scheduled games, "
          f"{len(done)} already archived, {n} to fetch.")
    n_regions = len([r for r in args.regions.split(",") if r.strip()])
    # The estimate used to assume one region and quietly halve the bill the
    # moment a second one was asked for.
    lo = n_markets * n_regions
    hi = lo * 10                          # docs disagree on the 10x multiplier
    print(f"Markets: {markets} ({n_markets})  "
          f"Regions: {args.regions} ({n_regions})")
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
            {"apiKey": _get_api_key(), "date": snapshot, "regions": args.regions,
             "markets": markets, "oddsFormat": "american"},
            budget,
        )
        if not payload:
            skipped += 1
            time.sleep(args.sleep)
            continue

        rows, book_rows = _parse_event_odds(payload, specs, row["game_id"])
        if not rows:
            skipped += 1
            print(f"  [{i}/{n}] {row['game_id']}: no TD props in snapshot")
            time.sleep(args.sleep)
            continue

        snap = pl.DataFrame(rows).with_columns(pl.lit(row["game_id"]).alias("game_id"))
        append_snapshot(snap, season=row["season"], week=row["week"],
                        snapshot=args.snapshot, regions=args.regions)
        # Same response, no extra credits, unbuyable afterwards.
        append_book_quotes(book_rows, season=row["season"], week=row["week"],
                           snapshot=args.snapshot, regions=args.regions)
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
