"""Fetch player TD props from The Odds API and cache locally."""
import json
import time
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from typing import Iterable, Sequence

import requests

from src.utils.devig import two_way
from src.utils.paths import get_path

API_BASE = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"
CACHE_DIR = get_path("raw") / "odds_cache"

#: (connect, read) seconds for every call to the API. Not a tuning knob — the
#: absence of this argument cost the 2026 Week 1 opening capture.
#:
#: `requests` defaults to no timeout at all, so a socket that dies without an
#: RST blocks the process forever. That is the normal outcome when a laptop
#: sleeps mid-request, which is the normal outcome for a job launchd fires at
#: noon on a Wednesday. On 2026-09-02 the unattended `open` capture established
#: two connections to the API and sat on them for six days.
#:
#: The damage is not the one lost capture. `com.mthompson.nfl-odds-close` is a
#: single launchd job carrying fifteen StartCalendarInterval entries, and
#: launchd will not start a job whose previous instance has not exited — so one
#: hung firing silently swallows every remaining close slot of the week, and
#: closing prices cannot be re-bought at any price.
#:
#: Generous rather than tight: the asymmetry in this whole module is that a
#: missed capture is unrecoverable while a slow one merely costs seconds. Worst
#: case is one events call plus one per event, so ~17 x 40s ~= 11 minutes,
#: which still lands inside the 30-minute lead before kickoff.
HTTP_TIMEOUT = (10, 30)

#: How many times a timed-out request is retried before the game is given up on.
#: A timeout is usually transient, and the per-event call is the one that
#: carries the actual prices — letting a single slow response drop a game would
#: swap a hang for a silent hole in the archive, which is the harder failure to
#: notice.
HTTP_RETRIES = 2


@dataclass(frozen=True)
class MarketSpec:
    """A market the API serves, and how to read it."""

    #: The Odds API market key, as sent in the `markets` query parameter.
    key: str
    #: What it is archived as. Equals the target type by convention — see
    #: odds_history.MARKET_BY_TARGET.
    market: str
    #: "yes_no" or "over_under". Not cosmetic: see MARKET_SPECS.
    shape: str


#: Every market this project knows how to read, with the shape of its outcomes.
#:
#: The shape has to be declared rather than assumed, because getting it wrong
#: does not raise. First and anytime TD publish Yes/No outcomes with no line.
#: Rushing and reception touchdowns publish **Over/Under** outcomes carrying a
#: `point`, even though the line is nearly always 0.5 and the proposition is
#: identical. Pointed at those markets, a yes/no reader matches no outcome,
#: skips every one of them, and archives an empty market — silently, and after
#: the credits have been spent. The historical endpoint sells each snapshot
#: once, so that is not a mistake you get to make twice.
MARKET_SPECS: tuple[MarketSpec, ...] = (
    MarketSpec("player_1st_td", "first_td", "yes_no"),
    MarketSpec("player_anytime_td", "anytime_td", "yes_no"),
    MarketSpec("player_rush_tds", "rush_td", "over_under"),
    MarketSpec("player_reception_tds", "reception_td", "over_under"),
    MarketSpec("player_receptions", "receptions", "over_under"),
    # The yardage markets. Archived under the weekly-stats column name they are
    # graded against, the way `receptions` is, so the label join is the market
    # name and cannot drift.
    #
    # Same over/under shape as receptions and a different market underneath it.
    # Books agree on a receptions line and scatter on a yardage one: measured
    # over four 2026 week-2 events, a player carries a median of 3 distinct
    # lines across the board (up to 6) and each (player, line) cell is quoted
    # by a median of 2 books. So `n_books` on these rows counts the books at
    # THAT line rather than the books pricing the player, and a median across
    # a cell is a median of two. What it costs is a consensus; what it buys is
    # that every archived row is a ticket that existed at a price, which is
    # the unit these get graded on. 91% of cells post both sides, so the
    # two-way de-vig behind `fair_prob` still applies.
    MarketSpec("player_rush_yds", "rushing_yards", "over_under"),
    MarketSpec("player_reception_yds", "receiving_yards", "over_under"),
    MarketSpec("player_pass_yds", "passing_yards", "over_under"),
)
SPEC_BY_MARKET = {s.market: s for s in MARKET_SPECS}

#: Bookmaker regions to ask for. Credits are billed markets x regions, so this
#: is a spending decision — but `us` alone was leaving real data on the table
#: for the entire life of the archive, in three separate ways.
#:
#: Measured on one 2024 game, anytime TD:
#:
#:     us    7 books   betmgm betonlineag betrivers bovada draftkings
#:                     fanduel williamhill_us
#:     us2   4 books   ballybet espnbet fliff hardrockbet
#:
#:   * **Consensus.** The median we de-vig against, and every profitability
#:     figure computed from it, was a median of 7 where 11 were available.
#:   * **Line shopping.** `evaluation/line_shopping.py` is best-of-N by
#:     construction, and N was 4 books short of what we were paying to be able
#:     to see.
#:   * **The longshot tail.** fliff and hardrockbet quote 34-51 players a game
#:     against 21-28 at the majors. That extra depth is precisely the band where
#:     `evaluation/longshot.py` measures our largest edge over the book
#:     (AUC 0.76 against theirs at 0.54) — and we were not pricing most of it.
#:
#: fliff also posts **both sides** of anytime TD, which no `us` book does. That
#: turns `fair_prob` into a real two-sided de-vig for the market we actually
#: bet, instead of the one-sided `expected_scorers` normalization whose own
#: docstring records it moving a favorite from 41% to 49% as book coverage
#: thinned. See blend.devig_market.
DEFAULT_REGIONS: str = "us,us2"

#: What every cache file and every archived row before 2026-08-17 was fetched
#: with. Kept so those files are still addressable, and so nothing written
#: under the narrower set is silently reused under the wider one.
_LEGACY_REGIONS: str = "us"

#: Markets fetched when a caller does not say. Every extra market multiplies
#: the credit cost of a fetch, so this list is a standing weekly bill and not
#: just a default.
#:
#: Markets are added here BEFORE a model reads them, and that is deliberate.
#: The normal endpoints serve only *current* markets, so a week that is not
#: captured has to be bought back from the historical endpoint later at 2
#: credits per market per region per game — affordable now, and not a bill
#: worth incurring to save 6 credits a fetch today. Waiting until a model was
#: finished would have meant paying it for every week the model took.
#:
#: `receptions` was here for weeks before `30_receptions.py` existed. The three
#: yardage markets were added 2026-09-16 on the same rule, with no model behind
#: any of them yet.
#:
#: The standing weekly bill: 6 markets x 2 regions = 12 credits per event call,
#: ~16 events a firing, ~15 close firings a week ~= 2,900 credits a week.
DEFAULT_MARKETS: tuple[str, ...] = ("first_td", "anytime_td", "receptions",
                                   "rushing_yards", "receiving_yards",
                                   "passing_yards")

#: Over/under outcomes are normalized onto the yes/no vocabulary the archive
#: already speaks. "Over" is the side that wins when the player does more,
#: which is exactly what "Yes" means on an anytime-TD ticket, so they share one
#: word and every downstream `side == "yes"` filter keeps working unchanged.
#: Which line the side refers to lives in `point`.
SIDE_ALIASES = {"yes": "yes", "over": "yes", "no": "no", "under": "no"}


def specs_for(markets: Sequence[str]) -> tuple[MarketSpec, ...]:
    """Resolve archive market names to specs, refusing unknown ones."""
    unknown = [m for m in markets if m not in SPEC_BY_MARKET]
    if unknown:
        raise KeyError(
            f"unknown market(s) {unknown}; known markets are "
            f"{sorted(SPEC_BY_MARKET)}. Add a MarketSpec — including its "
            f"outcome shape — before fetching it."
        )
    return tuple(SPEC_BY_MARKET[m] for m in markets)


def parse_event_markets(
    event: dict,
    specs: Iterable[MarketSpec],
    *,
    game_id: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """Consensus prices and per-book quotes for one event payload.

    One reader for both fetch paths. The live fetch and the historical backfill
    used to carry separate copies of this loop, identical down to the
    `side not in ("yes", "no")` filter — so any market shape either one learned,
    the other did not, and only one of them spends five figures of credits.

    Returns `(consensus_rows, book_rows)` in archive vocabulary: consensus is
    one row per (player, line) per market, book rows are one per bookmaker
    behind it. Both carry `point`, null for yes/no markets.
    """
    consensus: list[dict] = []
    book_rows: list[dict] = []

    for spec in specs:
        # (player, point) -> {"yes": [prob], "no": [prob], "odds": [american]}
        #
        # Keyed on the line as well as the player: a book quoting Over 0.5 and
        # a book quoting Over 1.5 are not two opinions about one price, and a
        # median across them describes no bet that exists.
        quotes: dict[tuple[str, float | None], dict] = {}

        for bk in event.get("bookmakers", []):
            for mkt in bk.get("markets", []):
                if mkt.get("key") != spec.key:
                    continue
                for out in mkt.get("outcomes", []):
                    side = SIDE_ALIASES.get(str(out.get("name", "")).lower())
                    player = out.get("description")
                    price = out.get("price")
                    if side is None or not player or price is None:
                        continue
                    point = out.get("point")
                    point = float(point) if point is not None else None
                    if spec.shape == "over_under" and point is None:
                        # An over/under with no line prices nothing. Dropping it
                        # is right; doing so quietly is not.
                        print(f"    WARNING: {spec.key} outcome for {player} "
                              f"has no point; skipped.")
                        continue

                    q = quotes.setdefault((player, point),
                                          {"yes": [], "no": [], "odds": []})
                    q[side].append(_american_to_implied(price))
                    if side == "yes":
                        q["odds"].append(price)
                    book_rows.append({
                        "game_id": game_id,
                        "bookmaker": bk.get("key"),
                        "book_last_update": mkt.get("last_update")
                                            or bk.get("last_update"),
                        "player_name_raw": player,
                        "market": spec.market,
                        "point": point,
                        "side": side,
                        "odds": int(price),
                        "implied_prob": round(_american_to_implied(price), 6),
                    })

        for (player, point), q in quotes.items():
            if not q["yes"]:
                continue
            p_yes = _median(q["yes"])
            p_no = _median(q["no"]) if q["no"] else None
            consensus.append({
                "game_id": game_id,
                "player_name_raw": player,
                "market": spec.market,
                "point": point,
                "odds": _prob_to_american(p_yes),
                # Raw two-way price, vig included.
                "implied_prob": round(p_yes, 4),
                # Vig removed where the book posts both sides. Over/under
                # markets always do, which is why they need none of the
                # one-sided normalization in blend.devig_market.
                #
                # Derived, not raw: `implied_prob` and `overround` below keep
                # both sides, so this column can be recomputed under any method
                # without re-fetching. See src/utils/devig.py for why the
                # default is additive rather than the proportional split this
                # used to hardcode.
                "fair_prob": round(float(two_way(p_yes, p_no)), 4) if p_no else None,
                "n_books": len(q["yes"]),
                "overround": round(p_yes + p_no, 4) if p_no else None,
            })

    return consensus, book_rows


def _get_api_key() -> str:
    """Read API key from .env or environment."""
    import os
    key = os.environ.get("ODDS_API_KEY", "")
    if not key:
        env_path = Path(".env")
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("ODDS_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip("\"'")
                    break
    return key


#: HTTP statuses worth trying again. A 5xx or a 429 is the API failing to
#: answer, not answering — the first cut of this retried neither, on the
#: reasoning that "an HTTP status is an answer", and a single transient 502
#: from the gateway then killed the 2026-09-09 open capture outright. A 4xx is
#: a real answer (401 a bad key, 404 no such event) and retrying it only burns
#: the clock before a kickoff.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

#: Seconds to wait before each retry. Backing off matters for a 502: a gateway
#: that just failed is likelier to fail again immediately than a second later.
RETRY_BACKOFF = (1.0, 3.0, 6.0)


def _redact(text: str) -> str:
    """Strip the API key out of anything on its way to a log.

    `raise_for_status` puts the full request URL in the message, query string
    included, so an unattended failure wrote the key into logs/ in plain text.
    """
    key = _get_api_key()
    return text.replace(key, "***") if key else text


def _get(url: str, params: dict, what: str) -> requests.Response:
    """GET with a timeout and a bounded retry. Never returns without an answer.

    Every request in this module goes through here, because the one that did
    not is the one that hung — see HTTP_TIMEOUT.
    """
    last: Exception | None = None
    for attempt in range(HTTP_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
            if (resp.status_code in RETRY_STATUSES
                    and attempt < HTTP_RETRIES):
                raise requests.HTTPError(
                    f"{resp.status_code} {resp.reason}", response=resp)
            resp.raise_for_status()
            return resp
        except (requests.Timeout, requests.ConnectionError,
                requests.HTTPError) as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            # A real answer: stop, and let the caller see why.
            if status is not None and status not in RETRY_STATUSES:
                raise type(e)(_redact(str(e)), response=e.response) from None
            last = e
            if attempt < HTTP_RETRIES:
                # Say so on the way past: an unattended capture that quietly
                # retried twice and then succeeded looks identical in the
                # archive to one that went straight through, and the
                # difference is worth seeing in the log before a Sunday.
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                print(f"  {what}: {_redact(str(e))[:80]} on attempt "
                      f"{attempt + 1}/{HTTP_RETRIES + 1}, retrying in {wait:g}s")
                time.sleep(wait)
    raise type(last)(_redact(str(last)))  # type: ignore[misc]


def _american_to_implied(price: int) -> float:
    """Convert American odds to implied probability."""
    if price > 0:
        return 100.0 / (price + 100.0)
    else:
        return -price / (-price + 100.0)


def _prob_to_american(p: float) -> int:
    """Convert a probability back to an American price.

    Consensus must be taken in probability space and converted here — never by
    averaging American odds directly. That scale is discontinuous at +/-100
    (there is no such thing as +50 or -50), so the median of books quoting -110
    and +120 lands on an impossible number. Those values silently became payouts
    of 20x or divide-by-zero on ~50% players, which is exactly the population our
    top picks live in.
    """
    p = min(max(float(p), 1e-6), 1 - 1e-6)
    return int(round(-p / (1 - p) * 100)) if p >= 0.5 else int(round((1 - p) / p * 100))


def _median(values: list[float]) -> float:
    """Median of a non-empty sequence.

    Consensus across books rather than whichever bookmaker answered first: a
    single book's price carries its own margin and its own stale lines, and one
    outlier moves a mean far more than it moves a median.
    """
    s = sorted(values)
    n = len(s)
    if n == 0:
        raise ValueError("median of empty sequence")
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


#: How long a cached payload may still be served, per snapshot. Zero means
#: never — always go to the API.
#:
#: An `open` capture is "the price when the week's board went up". Re-running it
#: inside the same afternoon is a retry or a dev loop, and serving the cache is
#: exactly right: it costs nothing and archives the same number. (The Makefile's
#: `open-line` passes --force-refresh anyway, so in practice this only ever
#: caught a hand-run repeat.)
#:
#: A `close` capture is "the price right now, this close to kickoff", and the
#: slots are deliberately spaced at different distances from it. A cache hit
#: there does not save a redundant fetch — it archives an earlier fetch under a
#: fresh `captured_at`. With a flat 6-hour TTL and a key that is only the UTC
#: date, Sunday ran 9:00 fresh -> 12:30 HIT -> 15:35 fresh -> 19:50 HIT: the
#: close for the 1pm wave was the 9:00 price and the close for SNF was the
#: 15:35 price, both stamped with the time they were asked for, both taken
#: before inactives were announced. Nothing errors and the archive looks
#: complete, which is the whole problem. So a close reads no cache; it still
#: writes one, for the open path and for `load_cached_book_quotes`.
CACHE_TTL_HOURS = {"open": 6.0, "close": 0.0}


def _cache_path(week_start: str, markets: Sequence[str] = DEFAULT_MARKETS,
                regions: str = DEFAULT_REGIONS) -> Path:
    """Cache file for a given week (by start date), market set and region set.

    Both are part of the key. Without them, a cache written by a narrower fetch
    would be served to a wider one, which reads as "the book priced nothing in
    those markets" rather than "we never asked" — the same shape of silence
    that hid the us2 books for the life of the archive.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    suffix = ""
    if tuple(markets) != DEFAULT_MARKETS:
        suffix += "__" + "-".join(markets)
    # Unsuffixed means `us` — the region set every cache on disk was written
    # with. The default has since widened to us,us2, and reusing those files
    # under the new default would serve 7-book prices as though they were the
    # 11-book consensus that was asked for.
    if regions != _LEGACY_REGIONS:
        suffix += "__" + regions.replace(",", "+")
    return CACHE_DIR / f"td_props_{week_start}{suffix}.json"


def fetch_week_td_props(week_start: str = None, force_refresh: bool = False,
                        markets: Sequence[str] = DEFAULT_MARKETS,
                        regions: str = DEFAULT_REGIONS,
                        snapshot: str = "close") -> dict:
    """Fetch first TD and anytime TD props for upcoming NFL games.

    Args:
        week_start: Date string (YYYY-MM-DD) to identify the week for caching.
                    If None, uses today's date.
        force_refresh: If True, bypass cache.
        snapshot: Which end of the market this fetch is. Governs the cache TTL
                  via CACHE_TTL_HOURS — a close never reads one. Defaults to
                  "close" so a caller that forgets spends a credit rather than
                  archiving an older price under a fresh timestamp.

    Returns:
        Dict keyed by (home_team, away_team) with player odds:
        {
            "Seattle Seahawks vs New England Patriots": {
                "home_team": "Seattle Seahawks",
                "away_team": "New England Patriots",
                "commence_time": "2026-09-10T00:15:00Z",
                "first_td": [{"player": "...", "odds": 600, "implied_prob": 0.143}, ...],
                "anytime_td": [{"player": "...", "odds": -105, "implied_prob": 0.512}, ...],
            }
        }
    """
    if week_start is None:
        week_start = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    specs = specs_for(markets)
    cache = _cache_path(week_start, markets, regions)
    ttl = CACHE_TTL_HOURS.get(snapshot, CACHE_TTL_HOURS["open"])
    if not force_refresh and ttl and cache.exists():
        age_hours = (time.time() - cache.stat().st_mtime) / 3600
        if age_hours < ttl:
            with open(cache) as f:
                return json.load(f)

    api_key = _get_api_key()
    if not api_key:
        print("No ODDS_API_KEY found. Set it in .env or environment.")
        return {}

    # Step 1: Get events
    resp = _get(
        f"{API_BASE}/sports/{SPORT}/events",
        {"apiKey": api_key},
        "events",
    )
    events = resp.json()

    if not events:
        return {}

    # Find the earliest week of games (group by week)
    events_by_date = {}
    for e in events:
        date = e["commence_time"][:10]
        events_by_date.setdefault(date, []).append(e)

    # Get all games in the upcoming week (first cluster of games)
    sorted_dates = sorted(events_by_date.keys())
    week_events = []
    first_date = sorted_dates[0]
    for date in sorted_dates:
        # NFL weeks span Thu-Mon, so include dates within 5 days of first game
        days_diff = (datetime.strptime(date, "%Y-%m-%d") -
                     datetime.strptime(first_date, "%Y-%m-%d")).days
        if days_diff <= 5:
            week_events.extend(events_by_date[date])
        else:
            break

    print(f"Fetching TD props for {len(week_events)} games...")

    results = {}
    # Per-book quotes, accumulated across every event in the fetch. Written to
    # its own archive by the caller; see odds_history.append_book_quotes.
    book_rows: list[dict] = []
    for event in week_events:
        event_id = event["id"]
        home = event["home_team"]
        away = event["away_team"]
        game_key = f"{away} @ {home}"

        try:
            resp = _get(
                f"{API_BASE}/sports/{SPORT}/events/{event_id}/odds",
                {
                    "apiKey": api_key,
                    "regions": regions,
                    "markets": ",".join(sp.key for sp in specs),
                    "oddsFormat": "american",
                },
                game_key,
            )
            data = resp.json()
        except Exception as e:
            print(f"  Error fetching {game_key}: {e}")
            continue

        game_data = {
            "home_team": home,
            "away_team": away,
            "commence_time": event["commence_time"],
            **{sp.market: [] for sp in specs},
        }

        # Consensus (median across books) is more stable than any single book
        # and is what we de-vig against.
        #
        # Every individual quote is also kept, in `book_rows`. The response
        # already contains them, so this costs no extra API credits — and the
        # detail cannot be bought back later, because the endpoint only sells
        # each snapshot once. See odds_history.BOOKS_PATH for what it is for.
        consensus, quotes = parse_event_markets(data, specs, game_id=game_key)
        book_rows.extend(quotes)

        for row in consensus:
            # `player` rather than `player_name_raw`: this dict is the on-disk
            # cache shape that `build_odds_parquet` has always read, and old
            # cache files are still on disk.
            game_data[row["market"]].append({
                "player": row["player_name_raw"],
                "point": row["point"],
                "odds": row["odds"],
                "implied_prob": row["implied_prob"],
                "fair_prob": row["fair_prob"],
                "n_books": row["n_books"],
                "overround": row["overround"],
            })

        for sp in specs:
            game_data[sp.market].sort(key=lambda x: x["implied_prob"],
                                      reverse=True)

        results[game_key] = game_data

    remaining = resp.headers.get("x-requests-remaining", "?")
    print(f"  API credits remaining: {remaining}")

    # Cache
    with open(cache, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Cached to {cache}")

    # Per-book detail goes to a sibling file rather than into `results`, which
    # every caller iterates as {game_key: game_data} — an extra key there would
    # be read as a game with no teams.
    if book_rows:
        books_cache = cache.with_name(cache.stem + "_books.json")
        with open(books_cache, "w") as f:
            json.dump(book_rows, f)
        print(f"  {len(book_rows):,} individual book quotes -> {books_cache}")

    return results


def _prop_caches() -> list[Path]:
    """Consensus cache files only.

    The per-book sibling written alongside each fetch also matches
    `td_props_*.json`, and it holds a *list* rather than the {game: data} dict
    every consumer expects — so a plain glob made `build_odds_parquet` fail with
    "'list' object has no attribute 'items'" the first time both existed.
    """
    return [p for p in CACHE_DIR.glob("td_props_*.json")
            if not p.name.endswith("_books.json")]


def load_cached_book_quotes() -> list[dict]:
    """Per-book quotes from the most recent fetch, for archiving.

    Returns [] when the newest cache predates per-book capture, so a caller can
    archive what exists without special-casing the transition.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(CACHE_DIR.glob("td_props_*_books.json"), reverse=True)
    if not files:
        return []
    with open(files[0]) as f:
        return json.load(f)


def load_cached_odds() -> dict:
    """Load most recent cached odds without making API calls."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_files = sorted(_prop_caches(), reverse=True)
    if not cache_files:
        return {}
    with open(cache_files[0]) as f:
        return json.load(f)


def build_odds_parquet() -> Path | None:
    """Consolidate all cached odds JSON files into a single parquet for features.

    Output schema: player_name, home_team, away_team, commence_time,
                   first_td_odds, first_td_implied, anytime_td_odds, anytime_td_implied
    """
    import polars as pl

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_files = list(_prop_caches())
    if not cache_files:
        return None

    rows = []
    for f in cache_files:
        with open(f) as fh:
            data = json.load(fh)

        for game_key, game_data in data.items():
            home = game_data["home_team"]
            away = game_data["away_team"]
            commence = game_data.get("commence_time", "")

            # Build player lookup for each market
            first_td_map = {
                p["player"]: p for p in game_data.get("first_td", [])
            }
            anytime_td_map = {
                p["player"]: p for p in game_data.get("anytime_td", [])
            }

            # Union all player names from both markets
            all_players = set(first_td_map.keys()) | set(anytime_td_map.keys())
            for player in all_players:
                ftd = first_td_map.get(player)
                atd = anytime_td_map.get(player)
                rows.append({
                    "odds_player_name": player,
                    "odds_home_team": home,
                    "odds_away_team": away,
                    "commence_time": commence,
                    "first_td_odds": ftd["odds"] if ftd else None,
                    "first_td_implied": ftd["implied_prob"] if ftd else None,
                    "anytime_td_odds": atd["odds"] if atd else None,
                    "anytime_td_implied": atd["implied_prob"] if atd else None,
                })

    if not rows:
        return None

    df = pl.DataFrame(rows)
    out_path = get_path("raw") / "player_td_odds.parquet"
    df.write_parquet(out_path)
    print(f"Player TD odds: {df.shape[0]} rows -> {out_path}")
    return out_path
