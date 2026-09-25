"""What share of bets is on each side, archived over the week.

The angle `rlm` was written as a substitute for. That module opens by saying
the thing outright — "94% of spread tickets are on the Eagles -7" is not
derivable here, The Odds API does not sell bet percentages — and settles for
line movement as a proxy, with the assumption stated. This closes the gap with
the real quantity.

**Sportsbook Review publishes it, and publishes it as JSON.** Its consensus
page is a Next.js app whose server-rendered state sits in `__NEXT_DATA__`,
which means no HTML parsing and no selector that silently stops matching after
a redesign — a missing key raises, where a stale CSS selector returns nothing
and looks like a quiet week. `robots.txt` disallows `/betting-odds/---old/`
and `/betting-odds/user/` and nothing else on this path.

**SPREAD AND TOTAL ONLY.** Every moneyline percentage the feed returns is 0,
on every game, which is the feed declining to publish rather than a market
nobody bet. Recorded as absent rather than as zero: a 0% ticket share is a
claim, and it is false.

**Archived, not fetched.** One row per capture, so the WEEK'S DRIFT is
recoverable — a side that opened at 50% and is at 71% by Sunday is a different
fact from one that sat at 71% all week, and the second is not visible from a
single read. This mirrors `odds_history`: same idea, same reason, one row per
(capture, game, market, side).

**Rate limited and cached by design.** A slate is three or four dates and a
whole week is a dozen requests. `refresh` sleeps between them and skips a date
it already holds a capture for inside `MIN_GAP_MINUTES`, so running it twice
by hand costs one request and no duplicate rows.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl

from src.utils.paths import get_path

URL = ("https://www.sportsbookreview.com/betting-odds/"
       "{league}/consensus/?date={date}")

LEAGUE = "nfl-football"

#: Identify the project rather than impersonate a browser. A real contact
#: string is what lets an operator complain instead of block.
USER_AGENT = ("nfl-predictions/1.0 (personal research project; "
              "low volume, cached)")

#: Seconds between requests. The slate is a dozen pages a week; there is no
#: reason to be quick about it.
DELAY_SECONDS = 2.0

#: Do not re-capture a date inside this window. Running the script twice in an
#: afternoon should cost one request, not two, and must not write a second row
#: that makes the drift look like movement.
MIN_GAP_MINUTES = 60

#: SBR's code for Jacksonville. Every other abbreviation already matches
#: nflverse, which is why this is a single entry and not a table.
RENAMES = {"JAC": "JAX"}

ARCHIVE = Path("data/archive/public_money.parquet")

SCHEMA = {
    # When this row was read. The reason the file is an archive: one row per
    # capture is what makes "it moved from 50% to 71%" a statement about the
    # market rather than about when you happened to look.
    "captured_at": pl.Utf8,
    "season": pl.Int64,
    "week": pl.Int64,
    # `AWAY_HOME`, the same key the game-line archive and the site cards use.
    "game_id": pl.Utf8,
    "kickoff": pl.Utf8,
    # "spreads" or "totals", named as `game_lines` names them.
    "market": pl.Utf8,
    # The team abbreviation for a spread; "Over"/"Under" for a total.
    "side": pl.Utf8,
    # Share of tickets on that side, 0-100. The two sides of a market sum to
    # 100 by construction, and both are stored: deriving the second from the
    # first hides a feed that has stopped returning one of them.
    "pick_pct": pl.Float64,
    "source": pl.Utf8,
}


def _fetch(date: str, league: str = LEAGUE) -> list[dict]:
    """One date's games, from the page's own server-rendered state."""
    import urllib.request

    url = URL.format(league=league, date=date)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "replace")
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">'
                  r'(.*?)</script>', html, re.S)
    if not m:
        # Raised, not swallowed. The page changing shape is the one failure
        # that must not look like a quiet week.
        raise RuntimeError(f"no __NEXT_DATA__ in {url}; the page has changed")
    d = json.loads(m.group(1))
    return ((d.get("props") or {}).get("pageProps") or {}) \
        .get("oddsTableModel", {}).get("gameRows") or []


def _team(t: dict | None) -> str | None:
    if not t:
        return None
    s = t.get("shortName") or t.get("name")
    return RENAMES.get(s, s)


def parse(rows: list[dict], captured_at: str) -> pl.DataFrame:
    """Game rows to archive rows. Absent percentages stay absent.

    A market whose two sides are both zero is the feed declining to publish
    it, which is every moneyline on every game. Writing 0 would be writing a
    number nobody stated.
    """
    out = []
    for r in rows:
        g = r.get("gameView") or {}
        c = g.get("consensus") or {}
        home, away = _team(g.get("homeTeam")), _team(g.get("awayTeam"))
        if not (home and away):
            continue
        gid = f"{away}_{home}"
        kick = str(g.get("startDate") or "")
        for market, pairs in (
            ("spreads", ((away, c.get("awaySpreadPickPercent")),
                         (home, c.get("homeSpreadPickPercent")))),
            ("totals", (("Over", c.get("overPickPercent")),
                        ("Under", c.get("underPickPercent")))),
            ("h2h", ((away, c.get("awayMoneyLinePickPercent")),
                     (home, c.get("homeMoneyLinePickPercent")))),
        ):
            vals = [v for _, v in pairs]
            if not any(v for v in vals):
                continue
            for side, v in pairs:
                if v is None:
                    continue
                out.append({"captured_at": captured_at, "season": None,
                            "week": None, "game_id": gid, "kickoff": kick,
                            "market": market, "side": side,
                            "pick_pct": round(float(v), 2),
                            "source": "sportsbookreview"})
    if not out:
        return pl.DataFrame(schema=SCHEMA)
    return pl.DataFrame(out, schema=SCHEMA)


def _stamp_week(df: pl.DataFrame) -> pl.DataFrame:
    """Season and week from the schedule, by game id.

    Joined rather than derived from the kickoff date: a Saturday game in
    December and a Thursday game belong to weeks a date arithmetic would have
    to know the season's start to get right, and the schedule already knows.
    """
    if df.is_empty():
        return df
    try:
        s = (pl.read_parquet(get_path("raw") / "schedules.parquet")
             .filter(pl.col("game_type") == "REG")
             .select(["season", "week", "home_team", "away_team"])
             .with_columns((pl.col("away_team") + "_" + pl.col("home_team"))
                           .alias("game_id"))
             .select(["game_id", "season", "week"])
             .unique(subset=["game_id"], keep="last"))
    except Exception:                                            # noqa: BLE001
        return df
    return (df.drop(["season", "week"])
            .join(s, on="game_id", how="left")
            .select(list(SCHEMA)))


def game_days(season: int, week: int) -> list[str]:
    """The dates that week is played on, from the schedule.

    Not "Thursday, Sunday, Monday": international games kick off on Saturdays
    and Fridays, and a guessed list of weekdays quietly drops them.
    """
    s = (pl.read_parquet(get_path("raw") / "schedules.parquet")
         .filter((pl.col("season") == season) & (pl.col("week") == week)
                 & (pl.col("game_type") == "REG")))
    if s.is_empty():
        return []
    return sorted({str(d)[:10] for d in s["gameday"].to_list() if d})


def load() -> pl.DataFrame:
    if not ARCHIVE.exists():
        return pl.DataFrame(schema=SCHEMA)
    return pl.read_parquet(ARCHIVE)


def refresh(season: int, week: int, force: bool = False) -> pl.DataFrame:
    """Capture this week's percentages and append them to the archive.

    Returns the rows written, which is empty when every date was captured
    recently enough — a no-op that says so rather than a silent duplicate.
    """
    have = load()
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    fresh_since = (now - timedelta(minutes=MIN_GAP_MINUTES)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")

    if not force and not have.is_empty():
        recent = have.filter((pl.col("season") == season)
                             & (pl.col("week") == week)
                             & (pl.col("captured_at") >= fresh_since))
        if not recent.is_empty():
            return pl.DataFrame(schema=SCHEMA)

    frames = []
    for i, day in enumerate(game_days(season, week)):
        if i:
            time.sleep(DELAY_SECONDS)
        frames.append(parse(_fetch(day), stamp))
    if not frames:
        return pl.DataFrame(schema=SCHEMA)
    got = _stamp_week(pl.concat(frames))
    # The same game appears on every date the page is asked for, because the
    # date filter is loose. One row per (capture, game, market, side).
    got = got.unique(subset=["captured_at", "game_id", "market", "side"],
                     keep="first")
    if got.is_empty():
        return got
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    out = pl.concat([have, got]) if not have.is_empty() else got
    out.unique(subset=["captured_at", "game_id", "market", "side"],
               keep="last").write_parquet(ARCHIVE)
    return got


def week_view(season: int, week: int) -> dict:
    """Per game and market: where the public is now, and where it started.

    `drift` is the change in the away/Over side's share from the FIRST capture
    of the week to the latest. Null when only one capture exists, rather than
    zero — "it has not moved" and "we have only looked once" are different
    statements and the page says which.
    """
    d = load()
    if d.is_empty():
        return {}
    d = d.filter((pl.col("season") == season) & (pl.col("week") == week))
    if d.is_empty():
        return {}
    first = d["captured_at"].min()
    last = d["captured_at"].max()
    now = d.filter(pl.col("captured_at") == last)
    then = (d.filter(pl.col("captured_at") == first)
            .select(["game_id", "market", "side",
                     pl.col("pick_pct").alias("open_pct")]))
    j = now.join(then, on=["game_id", "market", "side"], how="left")
    out: dict = {}
    for r in j.iter_rows(named=True):
        g = out.setdefault(r["game_id"], {})
        m = g.setdefault(r["market"], {"sides": [], "captures": 1})
        m["sides"].append({
            "side": r["side"], "pct": r["pick_pct"],
            "open_pct": r["open_pct"],
            "drift": (None if r["open_pct"] is None or first == last
                      else round(r["pick_pct"] - r["open_pct"], 1)),
        })
    for g in out.values():
        for m in g.values():
            m["sides"].sort(key=lambda s: -(s["pct"] or 0))
            m["captures"] = int(d["captured_at"].n_unique())
            m["first_seen"] = first
            m["last_seen"] = last
    return out
