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

#: How far before kickoff the "game week" starts. Seven days: the number the
#: schedule itself uses, and a line posted eight days out is answering a
#: different question from one posted on the Wednesday.
WEEK_OPEN_DAYS = 7

#: A spread or total is quoted near even money on both sides. An entry priced
#: beyond this is not that market: `bet_rivers_co` posted `homeSpread: 0` at
#: -334 on NYJ at DET, which is a moneyline in the spread history, and taking
#: it as the current line turned a Detroit -6.5 into a pick'em and reported a
#: 7.5-point move that never happened.
MAX_LINE_ODDS = 200

#: Do not re-capture a date inside this window. Running the script twice in an
#: afternoon should cost one request, not two, and must not write a second row
#: that makes the drift look like movement.
MIN_GAP_MINUTES = 60

#: SBR's code for Jacksonville. Every other abbreviation already matches
#: nflverse, which is why this is a single entry and not a table.
RENAMES = {"JAC": "JAX"}

ARCHIVE = Path("data/archive/public_money.parquet")

#: The opening and current line, from the SAME request. Sportsbook Review
#: ships a timestamped price history per book — 47 spread entries on an
#: ordinary game, back to the day the line went up — so a true opening number
#: costs nothing extra once the consensus page has been fetched.
#:
#: This is strictly better than the two-snapshot `game_lines` archive for the
#: one question it answers: that one has an "open" only if the capture script
#: ran early enough, and on week 3 of 2026 it did not — its open and close
#: were four minutes apart. See `games()` in the exporter.
LINES = Path("data/archive/line_history.parquet")

LINE_SCHEMA = {
    "captured_at": pl.Utf8, "season": pl.Int64, "week": pl.Int64,
    "game_id": pl.Utf8, "market": pl.Utf8,
    # The EARLIEST and LATEST price this feed holds, across every book it
    # lists, with the time each was posted.
    # TWO OPENS, because they are different facts. `open_*` is the earliest
    # price the feed holds, which on this board is a LOOKAHEAD line posted in
    # May; `wk_*` is the earliest inside the game week. A three-point move
    # since May is a season's worth of news and says nothing about what money
    # did this week, which is what reverse line movement is about.
    "open_at": pl.Utf8, "open_point": pl.Float64, "open_home_odds": pl.Int64,
    "open_away_odds": pl.Int64,
    "wk_at": pl.Utf8, "wk_point": pl.Float64, "wk_home_odds": pl.Int64,
    "wk_away_odds": pl.Int64,
    "now_at": pl.Utf8, "now_point": pl.Float64, "now_home_odds": pl.Int64,
    "now_away_odds": pl.Int64,
    "books": pl.Int64, "source": pl.Utf8,
}

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


def parse_lines(rows: list[dict], captured_at: str) -> pl.DataFrame:
    """Opening and current line per game and market, across all books.

    The open is the EARLIEST timestamp any book posted, not the first entry of
    the first book: books come up at different times and taking the first
    listed one would make the "opening line" depend on the order the feed
    happens to return.
    """
    out = []
    for r in rows:
        g = r.get("gameView") or {}
        home, away = _team(g.get("homeTeam")), _team(g.get("awayTeam"))
        if not (home and away):
            continue
        gid = f"{away}_{home}"
        views = [v for v in ((r.get("oddsViews") or [])
                             + (r.get("openingLineViews") or [])) if v]
        for market, key, pt in (("spreads", "spreadHistory", "homeSpread"),
                                ("totals", "totalHistory", "total"),
                                ("h2h", "moneyLineHistory", None)):
            odds = ("overOdds", "underOdds") if market == "totals" \
                else ("homeOdds", "awayOdds")
            pts = []
            for v in views:
                for e in (v.get(key) or []):
                    if not e.get("oddsDate"):
                        continue
                    pts.append(e)
            if not pts:
                continue
            if market != "h2h":
                pts = [e for e in pts
                       if all(abs(_int(e.get(o)) or 110) <= MAX_LINE_ODDS
                              for o in odds if e.get(o) is not None)]
            if not pts:
                continue
            pts.sort(key=lambda e: e["oddsDate"])
            first, last = pts[0], pts[-1]
            # The earliest price inside the game week. Falls back to the
            # overall open when the feed holds nothing that recent, which is
            # visible because `wk_at` then equals `open_at`.
            kick = str(g.get("startDate") or "")[:10]
            wk = first
            if kick:
                from datetime import date, timedelta
                try:
                    cut = (date.fromisoformat(kick)
                           - timedelta(days=WEEK_OPEN_DAYS)).isoformat()
                    inside = [e for e in pts if e["oddsDate"][:10] >= cut]
                    if inside:
                        wk = inside[0]
                except ValueError:
                    pass
            out.append({
                "captured_at": captured_at, "season": None, "week": None,
                "game_id": gid, "market": market,
                "open_at": first["oddsDate"],
                "open_point": (float(first[pt]) if pt and first.get(pt) is not None
                               else None),
                "open_home_odds": _int(first.get(odds[0])),
                "open_away_odds": _int(first.get(odds[1])),
                "wk_at": wk["oddsDate"],
                "wk_point": (float(wk[pt]) if pt and wk.get(pt) is not None
                             else None),
                "wk_home_odds": _int(wk.get(odds[0])),
                "wk_away_odds": _int(wk.get(odds[1])),
                "now_at": last["oddsDate"],
                # THE MEDIAN OF EACH BOOK'S LATEST, not the single most recent
                # row anywhere. One book's bad entry then moves the reported
                # line by itself, which is exactly how a -334 "spread" became
                # the current number on a game everyone else had at -6.5.
                "now_point": _consensus_now(views, key, pt, odds),
                "now_home_odds": _int(last.get(odds[0])),
                "now_away_odds": _int(last.get(odds[1])),
                "books": len([v for v in views if v.get(key)]),
                "source": "sportsbookreview",
            })
    if not out:
        return pl.DataFrame(schema=LINE_SCHEMA)
    return pl.DataFrame(out, schema=LINE_SCHEMA)


def _consensus_now(views: list, key: str, pt: str | None,
                   odds: tuple) -> float | None:
    """The median of each book's most recent posting for this market."""
    if not pt:
        return None
    latest = []
    for v in views:
        rows = [e for e in (v.get(key) or [])
                if e.get("oddsDate") and e.get(pt) is not None
                and all(abs(_int(e.get(o)) or 110) <= MAX_LINE_ODDS
                        for o in odds if e.get(o) is not None)]
        if rows:
            rows.sort(key=lambda e: e["oddsDate"])
            latest.append(float(rows[-1][pt]))
    if not latest:
        return None
    latest.sort()
    n = len(latest)
    return (latest[n // 2] if n % 2
            else round((latest[n // 2 - 1] + latest[n // 2]) / 2, 2))


def _int(v):
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


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
    # The CALLER's columns, not a hard-coded list. This selected
    # `list(SCHEMA)` — the ticket schema — so stamping the line-history frame
    # would have silently dropped every column the line history adds.
    cols = df.columns
    return (df.drop(["season", "week"])
            .join(s, on="game_id", how="left")
            .select(cols))


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

    frames, lines = [], []
    for i, day in enumerate(game_days(season, week)):
        if i:
            time.sleep(DELAY_SECONDS)
        raw = _fetch(day)
        frames.append(parse(raw, stamp))
        lines.append(parse_lines(raw, stamp))
    if not frames:
        return pl.DataFrame(schema=SCHEMA)
    _write_lines(lines, stamp)
    got = _stamp_week(pl.concat(frames))
    # The same game appears on every date the page is asked for, because the
    # date filter is loose. One row per (capture, game, market, side).
    got = got.unique(subset=["captured_at", "game_id", "market", "side"],
                     keep="first")
    if got.is_empty():
        return got
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    # `diagonal_relaxed`: this schema has grown once already (the game-week
    # open was added beside the lookahead one) and an archive that refuses to
    # widen forces a choice between losing history and losing the new column.
    out = (pl.concat([have, got], how="diagonal_relaxed")
           if not have.is_empty() else got)
    # Write-then-rename: the whole archive is rewritten on every capture.
    tmp = ARCHIVE.with_suffix(".parquet.tmp")
    out.unique(subset=["captured_at", "game_id", "market", "side"],
               keep="last").write_parquet(tmp)
    tmp.replace(ARCHIVE)
    return got


def _write_lines(frames: list, stamp: str) -> None:
    """Archive the opening and current line, from the same fetch.

    Failures here do NOT fail the capture: the ticket percentages are the
    thing this script exists for, and losing them because a price history
    changed shape would be trading the certain for the incidental.
    """
    try:
        got = _stamp_week(pl.concat([f for f in frames if not f.is_empty()]))
    except Exception as e:                                       # noqa: BLE001
        print(f"  line history not captured ({e})")
        return
    if got.is_empty():
        return
    got = got.unique(subset=["captured_at", "game_id", "market"], keep="first")
    LINES.parent.mkdir(parents=True, exist_ok=True)
    have = pl.read_parquet(LINES) if LINES.exists() else pl.DataFrame(
        schema=LINE_SCHEMA)
    # `diagonal_relaxed`: this schema has grown once already (the game-week
    # open was added beside the lookahead one) and an archive that refuses to
    # widen forces a choice between losing history and losing the new column.
    out = (pl.concat([have, got], how="diagonal_relaxed")
           if not have.is_empty() else got)
    tmp = LINES.with_suffix(".parquet.tmp")
    out.unique(subset=["captured_at", "game_id", "market"],
               keep="last").write_parquet(tmp)
    tmp.replace(LINES)


def line_view(season: int, week: int) -> dict:
    """Per game and market: where the line opened and where it is now.

    `move` is signed toward the HOME side on a spread and toward the OVER on
    a total, matching how the cards sign everything else.
    """
    if not LINES.exists():
        return {}
    d = pl.read_parquet(LINES).filter(
        (pl.col("season") == season) & (pl.col("week") == week))
    if d.is_empty():
        return {}
    d = d.sort("captured_at").unique(subset=["game_id", "market"], keep="last")
    out: dict = {}
    for r in d.iter_rows(named=True):
        blk = out.setdefault(r["game_id"], {})
        move = (None if r["wk_point"] is None or r["now_point"] is None
                else round(r["now_point"] - r["wk_point"], 1))
        season_move = (None if r["open_point"] is None or r["now_point"] is None
                       else round(r["now_point"] - r["open_point"], 1))
        blk[r["market"]] = {
            # `open` is the GAME WEEK's open, because that is the one a move
            # is measured from. The lookahead number is kept beside it rather
            # than instead of it.
            "open": r["wk_point"], "now": r["now_point"], "move": move,
            "lookahead": r["open_point"], "lookahead_move": season_move,
            "open_at": (r["wk_at"] or "")[:10],
            "lookahead_at": (r["open_at"] or "")[:10],
            "books": r["books"],
            "open_odds": [r["open_home_odds"], r["open_away_odds"]],
            "now_odds": [r["now_home_odds"], r["now_away_odds"]],
        }
    return out


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
