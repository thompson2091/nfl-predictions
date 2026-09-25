"""Offensive and defensive coordinators, by team and season.

nflverse publishes the head coach on every schedule row and nothing below him.
Pro Football Reference has the full staff and answers automated requests with
403, which is an answer: it is not a source to work around.

Wikipedia's season articles carry the staff in a template whose fields are
`off_coach` and `def_coach`, and its API is documented and intended for this.
Fetched through `action=query`, fifty titles per request, so a full history is
about twenty calls rather than nine hundred.

**It took two sources, because neither alone is enough.**

The infobox alone returned 41% overall and ZERO for the season being played,
and I nearly recorded that as "Wikipedia cannot supply this". It was the
parser. Most articles keep the staff in a list rather than the infobox —
`*Offensive coordinator – [[Joe Brady]]` — and reading both takes the
historical seasons to about 90%.

The season being played is still the worst covered by its own article, because
it is written as it happens: 2026 came back 34% that way. `Template:Buffalo
Bills staff`, which the team article transcludes, has no season attached and
is kept current — the right source for exactly the year the board needs and
the wrong one for every other. Merged, with the season article winning
wherever it exists, because it is dated and a template is only ever "now".

    live franchises, 2010-2026:   OC 90%   DC 93%
    2026:                         OC 100%  DC 97%

Two traps, both of which report as a gap in coverage rather than as an error:

  * Team names move, so an article title built from today's name asks for a
    page that never existed. `article_title` holds the four.
  * nflverse carries two codes for three franchises — LA and LAR, SD and LAC,
    OAK and LV. Keyed by article title, the second overwrites the first and a
    franchise disappears; LA did, leaving 31 teams in a league of 32.

Pro Football Reference answers automated requests with 403, which is a
decision on their part and not one to work around. ESPN's public team endpoint
carries no staff. `load` reads `data/raw/coordinators.csv`, so a curated file
can replace all of this without touching anything downstream.

**Team names move.** The Raiders are Oakland to 2019 and Las Vegas after, the
Chargers are San Diego to 2016, the Rams are St. Louis to 2015, and Washington
is the Redskins to 2019, the Football Team for 2020-21 and the Commanders
after. An article title built from today's name returns nothing for the years
before the move — silently, as a missing page, which reads exactly like a
season with no coordinator listed. `article_title` holds those, and a test
pins the four.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request

import polars as pl

from src.utils.paths import get_path

API = "https://en.wikipedia.org/w/api.php"

#: Wikipedia asks for a descriptive agent that identifies the caller. A default
#: urllib agent is refused.
AGENT = "nfl-predictions/1.0 (personal research; contact via repository)"

#: Titles per request. The API caps an anonymous caller at 50.
BATCH = 50

#: Seconds between requests. Wikipedia's etiquette guidance is one call at a
#: time with a pause; at twenty requests this costs seconds and avoids being
#: the reason the endpoint gets stricter. Half a second earned a 429 partway
#: through a full run, so it is two.
PAUSE = 2.0

#: How many times to back off and retry a 429 before giving up on a batch.
#: Doubling from PAUSE, so the last wait is about half a minute.
RETRIES = 4

#: Where a franchise played before it moved, so a season article resolves. The
#: year is the LAST season under the old name.
RENAMES: dict[str, list[tuple[int, str]]] = {
    "LV":  [(2019, "Oakland Raiders")],
    "LAC": [(2016, "San Diego Chargers")],
    "LA":  [(2015, "St. Louis Rams")],
    "WAS": [(2019, "Washington Redskins"), (2021, "Washington Football Team")],
}

COORD_PATH = get_path("raw") / "coordinators.csv"


def article_title(abbr: str, name: str, season: int) -> str:
    """The season article's title, under whatever name the team had then."""
    for last_year, old in RENAMES.get(abbr, []):
        if season <= last_year:
            return f"{season} {old} season"
    return f"{season} {name} season"


def _fetch(titles: list[str]) -> dict[str, str]:
    """Raw wikitext for up to `BATCH` titles, keyed by title."""
    q = urllib.parse.urlencode({
        "action": "query", "format": "json", "prop": "revisions",
        "rvprop": "content", "rvslots": "main", "titles": "|".join(titles),
        "redirects": "1", "formatversion": "2",
    })
    req = urllib.request.Request(f"{API}?{q}", headers={"User-Agent": AGENT})
    # 429 is the endpoint asking for less, not an error to retry immediately.
    delay = PAUSE
    for attempt in range(RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode())
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == RETRIES:
                raise
            print(f"    rate limited, waiting {delay:.0f}s")
            time.sleep(delay)
            delay *= 2
    out = {}
    for page in (data.get("query") or {}).get("pages") or []:
        if page.get("missing"):
            continue
        revs = page.get("revisions") or []
        if not revs:
            continue
        out[page["title"]] = revs[0]["slots"]["main"]["content"]
    # A redirect answers under its target's title; map it back so the caller
    # can find what it asked for.
    for r_ in (data.get("query") or {}).get("redirects") or []:
        if r_.get("to") in out:
            out[r_["from"]] = out[r_["to"]]
    return out


#: `| off_coach = [[Matt Nagy]]` in the infobox.
_FIELD = r"\|\s*{field}\s*=\s*(.+)"

#: `Offensive coordinator – [[Joe Brady]]` in the staff list, which is where
#: most articles actually keep it. Anchored to the start of a line, optionally
#: behind a bullet or a table cell, and requiring the dash — because the same
#: words appear in PROSE and mean something else entirely. The 2023 Cardinals
#: article says a "defensive coordinator [[Jonathan Gannon]]" was hired as
#: their HEAD COACH, from another team; matched loosely, that reads as their
#: own coordinator and is wrong on both counts.
_STAFF = (r"^[\*\|!: ]*{label}\s*(?:coordinator)?\s*[–—\-|]+\s*"
          r"(?:\[\[)?([^\]\n|<{{]+)")


def _clean(raw: str) -> str | None:
    """A name out of wikitext: links resolved, references and templates cut."""
    raw = re.split(r"<ref|<!--|\{\{", raw)[0]
    # `[[Joe Brady (American football coach)|Joe Brady]]` — the piped display
    # name where there is one, else the article title, minus its disambiguator.
    m = re.search(r"\[\[([^\]]+)\]\]", raw)
    if m:
        inner = m.group(1)
        name = inner.split("|")[-1] if "|" in inner else inner
    else:
        name = re.sub(r"[\[\]']", "", raw)
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip().strip("|").strip()
    # A staff line sometimes runs on into the next cell; a coach's name is not
    # eight words long.
    if not name or len(name.split()) > 4:
        return None
    return name


def _value(wikitext: str, field: str) -> str | None:
    """The coordinator, from the infobox if it is there and the staff list if not.

    Both, because neither alone is enough. The infobox covers about half of
    the seasons and none of the current one; the staff list covers the current
    one and much of the rest. Checked in that order only because the infobox
    is unambiguous.
    """
    m = re.search(_FIELD.format(field=field), wikitext)
    if m:
        got = _clean(m.group(1))
        if got:
            return got
    label = "Offensive" if field.startswith("off") else "Defensive"
    m = re.search(_STAFF.format(label=label), wikitext,
                  re.I | re.M)
    return _clean(m.group(1)) if m else None


def fetch(seasons: list[int], teams: pl.DataFrame | None = None) -> pl.DataFrame:
    """One row per team-season: head coach's coordinators, where listed.

    Absent rather than guessed. A season whose article does not carry the
    field comes back null, and the caller can see how much is missing instead
    of being handed a name that was inferred.
    """
    import nflreadpy as nfl

    teams = nfl.load_teams() if teams is None else teams
    pairs = [(r["team_abbr"], r["team_name"], s)
             for s in seasons
             for r in teams.select(["team_abbr", "team_name"]).iter_rows(named=True)]
    # Keyed by (team, season) and NOT by title, because titles collide:
    # nflverse carries `LA` and `LAR` for the Rams, `SD` and `LAC` for the
    # Chargers, `OAK` and `LV` for the Raiders. Two codes resolving to one
    # article overwrite each other in a title-keyed dict and one franchise
    # vanishes — LA did, for every season, and showed up only as 31 teams in
    # a league of 32.
    want = {(a, s): article_title(a, n, s) for a, n, s in pairs}
    titles = sorted(set(want.values()))

    rows = []
    by_title: dict = {}
    for (abbr, season), t in want.items():
        by_title.setdefault(t, []).append((abbr, season))
    for i in range(0, len(titles), BATCH):
        chunk = titles[i:i + BATCH]
        try:
            got = _fetch(chunk)
        except Exception as e:                                   # noqa: BLE001
            print(f"  batch {i // BATCH + 1} failed ({e}) — skipping")
            got = {}
        for t in chunk:
          for abbr, season in by_title[t]:
            wt = got.get(t)
            rows.append({
                "season": season, "team": abbr,
                "oc": _value(wt, "off_coach") if wt else None,
                "dc": _value(wt, "def_coach") if wt else None,
                "found": wt is not None,
            })
        time.sleep(PAUSE)
    return pl.DataFrame(rows)


def save(df: pl.DataFrame) -> None:
    COORD_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.write_csv(COORD_PATH)
    print(f"  Coordinators: {df.height:,} team-seasons -> {COORD_PATH}")


def load() -> pl.DataFrame:
    if not COORD_PATH.exists():
        return pl.DataFrame()
    return pl.read_csv(COORD_PATH)


#: Franchises nflverse still lists under a code that no longer plays: the
#: Oakland Raiders, San Diego Chargers and St. Louis Rams. Their season
#: articles exist for the years they played and not after, so fetching them
#: for a current season asks for a page that cannot exist and reports the
#: miss as a gap in coverage.
DEFUNCT = {"OAK", "SD", "STL", "LAR", "LVR"}


def fetch_current(teams: pl.DataFrame | None = None) -> pl.DataFrame:
    """This season's staff, from the templates the team articles transclude.

    The season articles are written as a season happens, so the one being
    played is the one they cover worst — 2026 came back 34% while 2019-2025
    sat near 90%. `Template:Buffalo Bills staff` has no season attached and is
    kept current, which makes it exactly the right source for the only year
    the board actually needs and the wrong one for every other.

    Returns rows with no season; the caller stamps it.
    """
    import nflreadpy as nfl

    teams = nfl.load_teams() if teams is None else teams
    pairs = [(r["team_abbr"], r["team_name"])
             for r in teams.select(["team_abbr", "team_name"]).iter_rows(named=True)
             if r["team_abbr"] not in DEFUNCT]
    want = {f"Template:{n} staff": a for a, n in pairs}
    titles = sorted(want)
    rows = []
    for i in range(0, len(titles), BATCH):
        chunk = titles[i:i + BATCH]
        try:
            got = _fetch(chunk)
        except Exception as e:                                   # noqa: BLE001
            print(f"  staff batch failed ({e})")
            got = {}
        for t in chunk:
            wt = got.get(t)
            rows.append({"team": want[t],
                         "oc": _value(wt, "off_coach") if wt else None,
                         "dc": _value(wt, "def_coach") if wt else None,
                         "found": wt is not None})
        time.sleep(PAUSE)
    return pl.DataFrame(rows)


def refresh(seasons: list[int], current: int | None = None) -> pl.DataFrame:
    """Season articles for history, staff templates for the season being played.

    Merged so the current season is filled from the templates wherever its own
    article has not been written yet, and left alone where it has.
    """
    hist = fetch(seasons)
    if current is None:
        return hist
    cur = fetch_current()
    if cur.is_empty():
        return hist
    cur = cur.with_columns(pl.lit(current).alias("season"))
    # The season article wins where it exists: it is dated, and a template is
    # only ever "now", which is wrong the moment a coordinator is replaced.
    merged = hist.join(cur.select(["season", "team",
                                   pl.col("oc").alias("_oc"),
                                   pl.col("dc").alias("_dc")]),
                       on=["season", "team"], how="left")
    return (merged.with_columns([
                pl.coalesce(["oc", "_oc"]).alias("oc"),
                pl.coalesce(["dc", "_dc"]).alias("dc")])
            .drop(["_oc", "_dc"]))
