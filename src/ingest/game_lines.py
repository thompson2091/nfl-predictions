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

#: The game-level markets, and the shape of each one's outcomes.
#:
#: `h2h` and `spreads` name a TEAM as the outcome; `totals` names Over/Under.
#: Getting that wrong does not raise — it archives an empty market after the
#: credits are spent — which is why it is declared here rather than inferred.
#:
#: **THE HALF AND QUARTER LINES WERE ADDED 2026-10-06 FOR HISTORY, NOT FOR A
#: FEATURE.** Nothing reads them yet. A game-script view wants to condition on
#: how a game stood at the half, and that cannot be asked of a week nobody
#: captured — the provider sells the current slate and a week that passes
#: uncaptured is gone. So the cost is paid now and the reading comes later.
#:
#: Which keys exist was PROBED against the provider rather than assumed, on
#: 2026-10-06, because nothing in this repo documented them and a wrong key
#: archives an empty market silently. Book coverage on one week-5 event:
#:
#:     h2h_h1 6 · spreads_h1 8 · totals_h1 8      <- taken
#:     h2h_q1 7 · spreads_q1 7 · totals_q1 7      <- taken
#:     h2h_h2 2 · spreads_h2 2 · totals_h2 2      <- left out, too thin
#:     spreads_q2 3 · q3 3 · q4 2                 <- left out, too thin
#:
#: Two or three books is not a consensus, and a median across them is a
#: number that will move for reasons that are not the market's.
#:
#: Cost: six more markets at two regions over ~16 events and ~17 firings a
#: week is roughly 3,300 credits a week against a 5,000,000 monthly quota, of
#: which October had spent 1,402 when this was added.
GAME_MARKETS: dict[str, str] = {
    "h2h": "team",
    "spreads": "team",
    "totals": "over_under",
    "h2h_h1": "team",
    "spreads_h1": "team",
    "totals_h1": "over_under",
    "h2h_q1": "team",
    "spreads_q1": "team",
    "totals_q1": "over_under",
}

#: The full-game three, for anything that means "the line" and not "a line".
#: Every existing consumer of this archive predates the half markets and
#: filters on `market == "spreads"`, which keeps working; this names the set
#: so a new consumer does not have to rediscover it.
FULL_GAME_MARKETS: tuple[str, ...] = ("h2h", "spreads", "totals")

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

    ONE CAPTURE CANNOT BE BOTH ENDS OF A WEEK, and that is the single
    exception. 2026 week 4 was archived with a 7-book capture written twice —
    identical in every field but the label, once as the open and once as the
    close — nine days before kickoff. Nothing errored, and the consequences
    were downstream and silent: the week HAD a close, so `matchups.board`
    priced it off that instead of off the 21-book open captured a week later,
    and dropped every outcome below `MIN_BOOKS` until the moneyline survived
    on one game of sixteen. A week's movement table was all zeroes for the
    same reason, which reads as a market that did not move.

    Refused rather than relabeled: which end a capture belongs to is the
    caller's to know, and guessing here would put a wrong answer in an
    append-only file that cannot be corrected later.
    """
    p = path or LINES_PATH
    df = pl.DataFrame(rows).with_columns([
        pl.lit(int(season)).alias("season"),
        pl.lit(int(week)).alias("week"),
        pl.lit(snapshot).alias("snapshot"),
    ])
    if p.exists():
        prior = pl.read_parquet(p)
        df = _drop_other_end(df, prior, season, week, snapshot)
        if df.is_empty():
            print(f"  Game lines: nothing to add for {season} week {week} "
                  f"{snapshot}")
            return prior
        df = pl.concat([prior, df], how="diagonal_relaxed")
    p.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename, as `odds_history` does. This is the only game-line
    # archive there is and every capture rewrites the whole file, so a crash
    # mid-write used to leave nothing at all.
    tmp = p.with_suffix(".parquet.tmp")
    df.write_parquet(tmp)
    tmp.replace(p)
    print(f"  Game lines: {df.height:,} rows -> {p}")
    return df


def _drop_other_end(df: pl.DataFrame, prior: pl.DataFrame, season: int,
                    week: int, snapshot: str) -> pl.DataFrame:
    """Drop rows from a capture this week already holds under the other label.

    Keyed on `captured_at`, which is stamped once per fetch, so the test is
    "has this exact capture already been filed as the other end" and not
    "does this look like something we have seen". A genuine re-run under the
    SAME label still appends, because a price standing for three hours is
    three observations and the archive is where that is recorded.
    """
    if prior.is_empty() or "captured_at" not in prior.columns:
        return df
    clash = (prior.filter((pl.col("season") == int(season))
                          & (pl.col("week") == int(week))
                          & (pl.col("snapshot") != snapshot))
                  .select("captured_at").unique().to_series().to_list())
    if not clash:
        return df
    keep = df.filter(~pl.col("captured_at").is_in(clash))
    if keep.height < df.height:
        other = (prior.filter((pl.col("season") == int(season))
                              & (pl.col("week") == int(week))
                              & (pl.col("snapshot") != snapshot))
                      .select("snapshot").unique().to_series().to_list())
        print(f"  Game lines: refused {df.height - keep.height:,} rows for "
              f"{season} week {week} — this capture is already archived as "
              f"{'/'.join(sorted(other))}. One fetch is one end of a week.")
    return keep


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
