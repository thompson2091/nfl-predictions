"""Game-level lines — moneyline, spread and total — at every book.

The player-prop path in `odds_api` is built around a player: a row is a person,
a line and a price. A game line has no player. Its outcome is a TEAM (moneyline,
spread) or the words Over and Under (total), and the thing worth archiving is
which book said what and when. So this is a separate reader rather than three
more entries in `MARKET_SPECS`, where they would be silently skipped by a
parser that matches on a player name.

**Book-level rows are the point, not a by-product.** The entire measurable edge
in this archive so far is cross-book dispersion: on anytime TD, across 34,689
player-games with six or more books quoting, the best price beats the consensus
median by 2.31pp, which is worth 15.5% of return and is larger than anything
the models have produced. A consensus written at ingest time throws that away,
and The Odds API sells each snapshot once, so it cannot be recovered later.
That mistake was made once already on the player props and cost the 2023-2025
book-level history.

The same rows answer the question a bets page actually wants: **where did the
line move, and did it move against the tickets?** A total opening at 44.5 and
closing at 46 is a fact about money, and it is the only fact about money
available here — The Odds API does not sell bet percentages, and the services
that do are scraped rather than licensed. Reverse line movement is the
derivable version of the same idea and needs no third-party feed.

Credits: three markets on one events call plus one call per event, the same
shape as the props fetch. Game lines are the cheapest markets the API sells.
"""
from __future__ import annotations

from datetime import datetime, timezone

import polars as pl

from src.ingest.odds_history import ARCHIVE_DIR

#: The three game-level markets, and the shape of each one's outcomes.
#:
#: `h2h` and `spreads` name a TEAM as the outcome; `totals` names Over/Under.
#: Getting that wrong does not raise — it archives an empty market after the
#: credits are spent — which is why it is declared here rather than inferred.
GAME_MARKETS: dict[str, str] = {
    "h2h": "team",
    "spreads": "team",
    "totals": "over_under",
}

#: Where the archive lives. Append-only, like the props archive: a snapshot the
#: API has stopped serving cannot be bought back.
LINES_PATH = ARCHIVE_DIR / "game_lines.parquet"


def fetch_game_lines(regions: str = "us,us2") -> list[dict]:
    """One row per (game, market, book, outcome). Never aggregated here.

    Returns raw rows rather than a frame so the caller decides what to keep;
    `append_snapshot` is what writes them.
    """
    from src.ingest.odds_api import (API_BASE, SPORT, _get, _get_api_key,
                                     _american_to_implied)
    from src.features.odds_features import TEAM_ABBREV

    api_key = _get_api_key()
    if not api_key:
        print("No ODDS_API_KEY found. Set it in .env or environment.")
        return []

    resp = _get(f"{API_BASE}/sports/{SPORT}/events", {"apiKey": api_key},
                "events")
    events = resp.json()
    if not events:
        return []

    # The same week-clustering the props fetch uses: NFL weeks span Thu-Mon, so
    # everything within five days of the first game is this week.
    by_date: dict[str, list] = {}
    for e in events:
        by_date.setdefault(e["commence_time"][:10], []).append(e)
    dates = sorted(by_date)
    first = datetime.strptime(dates[0], "%Y-%m-%d")
    week_events = []
    for d in dates:
        if (datetime.strptime(d, "%Y-%m-%d") - first).days <= 5:
            week_events.extend(by_date[d])
        else:
            break

    print(f"Fetching game lines for {len(week_events)} games...")
    captured = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows: list[dict] = []
    for event in week_events:
        home, away = event["home_team"], event["away_team"]
        h, a = TEAM_ABBREV.get(home), TEAM_ABBREV.get(away)
        label = f"{away} @ {home}"
        try:
            r = _get(
                f"{API_BASE}/sports/{SPORT}/events/{event['id']}/odds",
                {"apiKey": api_key, "regions": regions,
                 "markets": ",".join(GAME_MARKETS), "oddsFormat": "american"},
                label,
            )
            data = r.json()
        except Exception as e:                                   # noqa: BLE001
            print(f"  Error fetching {label}: {e}")
            continue

        for bk in data.get("bookmakers", []):
            for m in bk.get("markets", []):
                if m.get("key") not in GAME_MARKETS:
                    continue
                for o in m.get("outcomes", []):
                    price = o.get("price")
                    if price is None:
                        continue
                    rows.append({
                        "captured_at": captured,
                        # The API's own market clock. `captured_at` means the
                        # ingestion moment and is useless on a backfill, which
                        # is the trap that made a 2023 game look three years
                        # in-play. See odds_history.drop_in_play.
                        "book_last_update": m.get("last_update"),
                        "commence_time": event.get("commence_time"),
                        "game_id": f"{a}_{h}" if a and h else None,
                        "home_team": h, "away_team": a,
                        "bookmaker": bk.get("key"),
                        "market": m.get("key"),
                        # A team abbreviation for h2h and spreads, "Over" or
                        # "Under" for totals. Kept raw as well, because the
                        # abbreviation map silently returns None for a name it
                        # does not know and that would erase the row's meaning.
                        "outcome": TEAM_ABBREV.get(o.get("name"), o.get("name")),
                        "outcome_raw": o.get("name"),
                        "point": o.get("point"),
                        "odds": price,
                        "implied_prob": _american_to_implied(price),
                    })
    print(f"Fetched {len(rows):,} book quotes across {len(week_events)} games")
    return rows


def append_snapshot(rows: list[dict], season: int, week: int,
                    snapshot: str, path=None) -> pl.DataFrame:
    """Append to the archive, stamped with the week and which end it is.

    Append-only and never de-duplicated on write. Two captures of the same
    book at the same price are two observations of a market that did not move,
    which is information; collapsing them here would make it impossible to say
    later how long a price stood.
    """
    p = path or LINES_PATH
    df = pl.DataFrame(rows).with_columns([
        pl.lit(int(season)).alias("season"),
        pl.lit(int(week)).alias("week"),
        pl.lit(snapshot).alias("snapshot"),
    ])
    if p.exists():
        df = pl.concat([pl.read_parquet(p), df], how="diagonal_relaxed")
    p.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(p)
    print(f"  Game lines: {df.height:,} rows -> {p}")
    return df


def consensus(df: pl.DataFrame) -> pl.DataFrame:
    """One row per (game, market, outcome, point): median price and book count.

    A median, computed on READ rather than written at ingest. Nobody can bet a
    median — it exists to say what the market thought, and the book rows it is
    computed from stay on disk so the price you could actually have taken is
    still there.
    """
    return (df.group_by(["season", "week", "snapshot", "game_id", "market",
                         "outcome", "point"])
              .agg([pl.col("odds").median().alias("odds_median"),
                    pl.col("odds").max().alias("odds_best"),
                    pl.col("implied_prob").median().alias("implied_median"),
                    pl.col("implied_prob").min().alias("implied_best"),
                    pl.len().alias("n_books")])
              .sort(["season", "week", "game_id", "market", "outcome"]))
