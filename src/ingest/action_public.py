"""Ticket AND money splits, on all three markets, from Action Network.

`ingest/public_money` reads Sportsbook Review, which gives TICKETS ONLY and
publishes nothing at all on the moneyline — every moneyline percentage it
returns is 0 on every game, checked again against the live feed on
2026-09-25: 0 of 14 games carried one while all 14 carried a spread split.

This reads the other half of the question, and the half that is worth more:

  * **The moneyline**, which the other feed does not have at all.
  * **Money as well as tickets.** Tickets count bets; money counts dollars.
    The two disagreeing is the only public-betting signal with a real story
    behind it — a side taking 11% of the tickets and 46% of the money is a
    small number of large bets, and that is a different fact from a crowd.
    ATL at Green Bay in week 3 read exactly that.

**From the page, not from the internal API.** The same data sits in
`api.actionnetwork.com/web/v2/scoreboard/publicbetting/nfl`, which is cleaner
and faster and undocumented. `www.actionnetwork.com/robots.txt` permits
`/nfl/public-betting`, and that page carries the whole payload in
`__NEXT_DATA__`, so the robots-sanctioned route costs one request and gives
the same numbers. One request a capture, either way.

**`__NEXT_DATA__` rather than HTML.** Same reason as the other scraper: a
missing key raises, where a stale CSS selector returns nothing and looks like
a quiet week.

**Absent is not zero.** An outcome whose tickets and money are both 0 is the
feed declining to publish it, not a side nobody backed. Dropped rather than
recorded, exactly as the other scraper drops SBR's empty moneylines. A 0%
share is a claim and it would be false.

**One book.** The page carries seven, and the percentages differ between
them because they are different customer bases. `PERCENT_BOOK` is the one the
site's own config uses for the percentages it displays, so the archive holds
one comparable series rather than a mixture that changes with whoever the
page happened to list first.

**Archived per capture**, so the week's drift is recoverable. Same shape and
same reason as `public_money`: one row per (capture, game, market, side).
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl

#: The page robots.txt permits. Its server-rendered state holds the payload.
URL = "https://www.actionnetwork.com/nfl/public-betting"

#: Identifies the caller, as the other scraper's does.
USER_AGENT = ("nfl-predictions/1.0 (personal research project; "
              "contact via repository)")

#: Seconds between requests, when more than one is ever made.
DELAY_SECONDS = 2.0

#: Don't capture again inside this, so running it twice by hand is one
#: request and no duplicate rows.
MIN_GAP_MINUTES = 60

#: The book the site's own `percentage_book_id` points at. Percentages differ
#: by book; mixing them would make the archive's drift meaningless.
PERCENT_BOOK = "15"

#: The markets worth archiving. `core_bet_type_6_team_score` is a team-total
#: ladder, which is a different question and not this one.
MARKETS = ("moneyline", "spread", "total")

#: nflverse spells Jacksonville JAX.
RENAMES = {"JAC": "JAX"}

ARCHIVE = Path("data/archive/action_public.parquet")

SCHEMA = {
    "captured_at": pl.Utf8, "season": pl.Int32, "week": pl.Int32,
    "game_id": pl.Utf8, "kickoff": pl.Utf8, "market": pl.Utf8,
    "side": pl.Utf8, "odds": pl.Int64,
    "tickets_pct": pl.Float64, "money_pct": pl.Float64, "source": pl.Utf8,
}


def _fetch(url: str = URL) -> dict:
    """The page's server-rendered state, or an error naming what changed."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "replace")
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">'
                  r'(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError(f"no __NEXT_DATA__ in {url}; the page has changed")
    return json.loads(m.group(1))


def _team(t: dict | None) -> str | None:
    if not t:
        return None
    a = (t.get("abbr") or "").upper()
    return RENAMES.get(a, a) or None


def _pct(bet_info: dict | None, key: str) -> float | None:
    """A percentage the feed actually published, or None."""
    blk = (bet_info or {}).get(key) or {}
    v = blk.get("percent")
    return None if v is None else float(v)


def parse(state: dict, captured_at: str) -> pl.DataFrame:
    """Page state to archive rows. Unpublished percentages stay absent."""
    games = (((state.get("props") or {}).get("pageProps") or {})
             .get("scoreboardResponse") or {}).get("games") or []
    out = []
    for g in games:
        by_id = {t.get("id"): t for t in (g.get("teams") or [])}
        home = _team(by_id.get(g.get("home_team_id")))
        away = _team(by_id.get(g.get("away_team_id")))
        if not (home and away):
            continue
        gid = f"{away}_{home}"
        kick = str(g.get("start_time") or "")
        ev = ((g.get("markets") or {}).get(PERCENT_BOOK) or {}).get("event") or {}
        for market in MARKETS:
            for o in (ev.get(market) or []):
                tickets = _pct(o.get("bet_info"), "tickets")
                money = _pct(o.get("bet_info"), "money")
                # Both zero is the feed declining to publish this outcome.
                if not tickets and not money:
                    continue
                side = o.get("side")
                # Moneyline and spread name a team; a total names a direction.
                if market == "total":
                    label = str(side or "").capitalize()
                else:
                    label = (home if side == "home"
                             else away if side == "away"
                             else _team(by_id.get(o.get("team_id"))))
                if not label:
                    continue
                out.append({
                    "captured_at": captured_at, "season": None, "week": None,
                    "game_id": gid, "kickoff": kick, "market": market,
                    "side": label,
                    "odds": None if o.get("odds") is None else int(o["odds"]),
                    "tickets_pct": tickets, "money_pct": money,
                    "source": "actionnetwork",
                })
    return pl.DataFrame(out, schema=SCHEMA) if out else pl.DataFrame(schema=SCHEMA)


def _stamp_week(df: pl.DataFrame) -> pl.DataFrame:
    """Attach the season and week each game belongs to, from the schedule."""
    if df.is_empty():
        return df
    from src.utils.paths import get_path

    sched = pl.read_parquet(get_path("raw") / "schedules.parquet")
    keys = (sched.select(["season", "week", "home_team", "away_team"])
                 .with_columns((pl.col("away_team") + "_" + pl.col("home_team"))
                               .alias("game_id"))
                 .select(["game_id", "season", "week"])
                 .unique(subset=["game_id"], keep="last"))
    # Season and week are REPLACED from the schedule rather than filled, so a
    # column that arrives null cannot survive as null.
    return (df.drop(["season", "week"])
              .join(keys, on="game_id", how="left")
              .with_columns([pl.col("season").cast(pl.Int32),
                             pl.col("week").cast(pl.Int32)]))


def load() -> pl.DataFrame:
    if not ARCHIVE.exists():
        return pl.DataFrame(schema=SCHEMA)
    return pl.read_parquet(ARCHIVE)


def refresh(season: int, week: int, force: bool = False) -> pl.DataFrame:
    """Capture the current splits and append them to the archive.

    Returns the rows written, empty when a recent capture already exists —
    a no-op that says so rather than a silent duplicate.
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

    got = _stamp_week(parse(_fetch(), stamp))
    if got.is_empty():
        return got
    got = got.unique(subset=["captured_at", "game_id", "market", "side"],
                     keep="first")
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    out = (pl.concat([have, got], how="diagonal_relaxed")
           if not have.is_empty() else got)
    out = out.unique(subset=["captured_at", "game_id", "market", "side"],
                     keep="last").sort(["captured_at", "game_id", "market"])
    # Write-then-rename: the whole archive is rewritten on every capture.
    tmp = ARCHIVE.with_suffix(".parquet.tmp")
    out.write_parquet(tmp)
    tmp.replace(ARCHIVE)
    return got


def dollars_per_ticket(tickets: float | None, money: float | None) -> float | None:
    """Money share over ticket share, or None if either is missing.

    The average bet on a side, in units of the average bet overall. It is only
    meaningful against the other side of the same market — see `ratio`.
    """
    if tickets is None or money is None or tickets <= 0:
        return None
    return money / tickets


def ratio(tickets: float | None, money: float | None,
          other_tickets: float | None, other_money: float | None) -> float | None:
    """How much bigger the average bet on this side is than on the other.

    **THE RAW GAP IS THE WRONG STATISTIC AND IT FLATTERS UNDERDOGS.** Money
    share minus ticket share is capped by the ticket share: a side already
    holding 89% of the tickets can gain at most 11 points however large its
    bets are, while a side on 11% has 89 points to play with. Ranking on the
    gap therefore ranks on how unpopular a side is, not on how big its money
    is. Carolina at 89% of tickets and 96% of the money is the case that
    exposes it — a 7-point gap, and three times the average bet.

    Reciprocal between the two sides rather than equal and opposite, which is
    what makes it readable as "2x the average bet" from either end.

    One definition, used by `week_view` for the page and by
    `evaluation.sharp` for the measurement, so the number on screen and the
    number being graded cannot drift apart.
    """
    a = dollars_per_ticket(tickets, money)
    b = dollars_per_ticket(other_tickets, other_money)
    if a is None or b is None or b <= 0:
        return None
    return a / b


def week_view(season: int, week: int) -> dict:
    """The latest capture per side, plus how far it has drifted this week.

    Shaped like `public_money.week_view` so the page reads one thing: a dict
    of game id to market to `{sides: [...]}`, each side carrying its ticket
    share, its money share, and the gap between them.
    """
    have = load()
    if have.is_empty():
        return {}
    from src.ingest.public_money import pre_kickoff

    # Before each game's own kickoff: 93% of the "latest" rows shown were
    # captured during the game. See `public_money.pre_kickoff`.
    d = pre_kickoff(have.filter((pl.col("season") == season)
                                & (pl.col("week") == week)), season, week)
    if d.is_empty():
        return {}
    first = (d.sort("captured_at")
              .unique(subset=["game_id", "market", "side"], keep="first")
              .select(["game_id", "market", "side",
                       pl.col("tickets_pct").alias("open_tickets"),
                       pl.col("money_pct").alias("open_money")]))
    last = (d.sort("captured_at")
             .unique(subset=["game_id", "market", "side"], keep="last")
             .join(first, on=["game_id", "market", "side"], how="left"))
    captures = d.select(pl.col("captured_at").n_unique()).item()
    out: dict = {}
    for r in last.iter_rows(named=True):
        blk = out.setdefault(r["game_id"], {}).setdefault(
            r["market"], {"captures": captures, "sides": []})
        t, m = r["tickets_pct"], r["money_pct"]
        blk["sides"].append({
            "side": r["side"], "odds": r["odds"],
            "tickets": t, "money": m,
            # THE WHOLE POINT. Money above tickets is fewer, larger bets on
            # that side; below is the crowd without the money behind it.
            "gap": None if (t is None or m is None) else round(m - t, 1),
            # And the same fact as a ratio, which is what actually ranks: the
            # gap is bounded by the ticket share, so it sorts by unpopularity.
            # Filled in below, once both sides of the market are known.
            "ratio": None,
            "drift_tickets": (None if (t is None or r["open_tickets"] is None)
                              else round(t - r["open_tickets"], 1)),
            "drift_money": (None if (m is None or r["open_money"] is None)
                            else round(m - r["open_money"], 1)),
        })
    for game in out.values():
        for blk in game.values():
            sides = blk["sides"]
            # The ratio needs the other side, so it is filled once the market
            # is complete. A market the feed published half of keeps None
            # rather than being compared against a partial denominator.
            if len(sides) == 2:
                for one, other in ((sides[0], sides[1]), (sides[1], sides[0])):
                    r = ratio(one["tickets"], one["money"],
                              other["tickets"], other["money"])
                    one["ratio"] = None if r is None else round(r, 2)
            # THE NAME BREAKS THE TIE. A total split 50/50 leaves both
            # sides equal on the only key, so their order came out however
            # the sort happened to leave them and flipped between builds —
            # which reads on the page as the heavier side having changed.
            sides.sort(key=lambda s: (-(s["tickets"] or 0), s["side"] or ""))
    return out
