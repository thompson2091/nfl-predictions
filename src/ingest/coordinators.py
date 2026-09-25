"""Offensive and defensive coordinators, by team and season.

nflverse publishes the head coach on every schedule row and nothing below him.
Pro Football Reference has the full staff and answers automated requests with
403, which is an answer: it is not a source to work around.

Wikipedia's season articles carry the staff in a template whose fields are
`off_coach` and `def_coach`, and its API is documented and intended for this.
Fetched through `action=query`, fifty titles per request, so a full history is
about twenty calls rather than nine hundred.

**THIS SOURCE IS NOT SUFFICIENT, AND NOTHING IS WIRED TO IT.**

It works, and what it returns is right — Fangio, Pees, LeBeau, Spagnuolo all
land where they should. The problem is coverage, and it is fatal in the one
place that matters:

    2021  57% of team-seasons     2024  34%
    2022  51%                     2025   0%
    2023  46%                     2026   0%

The current-season articles carry `coach` and no coordinator fields at all —
2025 Buffalo has Sean McDermott and nothing else, while 2024 Buffalo has Joe
Brady and Bobby Babich. The fields are filled in later, by editors, some of
the time: 2023 Arizona and 2023 Atlanta never got them either. So a feature
built on this would be null for half the training seasons and null for EVERY
row being predicted, which is a mostly-null column pointed at the live board —
the precise shape `game_model.leaky_columns` exists to catch.

Every free source was checked. nflverse publishes the head coach and nothing
below him. Pro Football Reference answers automated requests with 403, which
is a decision on their part and not one to work around. ESPN's public team
endpoint carries no staff at all. What remains is a paid feed with a coaching
endpoint, or a curated file — and a curated file is the reason `load` reads a
CSV rather than this module's own output: drop a correct one at
`data/raw/coordinators.csv` with columns season, team, oc, dc and everything
downstream will use it.

The fetcher is kept because it is correct for the seasons Wikipedia does
cover, and because a partial history is worth having if that curated file ever
needs checking against something.

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
#: the reason the endpoint gets stricter.
PAUSE = 0.5

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
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
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


#: `off_coach = [[Matt Nagy]]`, with the link brackets and any comment after.
_FIELD = r"\|\s*{field}\s*=\s*(.+)"


def _value(wikitext: str, field: str) -> str | None:
    m = re.search(_FIELD.format(field=field), wikitext)
    if not m:
        return None
    raw = m.group(1)
    # Strip the reference tags, templates and comments that follow a name.
    raw = re.split(r"<ref|<!--|\{\{", raw)[0]
    # `[[Matt Nagy]]` and `[[Matt Nagy|Nagy]]` both resolve to the article name.
    links = re.findall(r"\[\[([^\]|]+)", raw)
    name = links[0] if links else re.sub(r"[\[\]']", "", raw)
    name = name.strip().strip("|").strip()
    return name or None


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
    want = {article_title(a, n, s): (a, s) for a, n, s in pairs}
    titles = sorted(want)

    rows = []
    for i in range(0, len(titles), BATCH):
        chunk = titles[i:i + BATCH]
        try:
            got = _fetch(chunk)
        except Exception as e:                                   # noqa: BLE001
            print(f"  batch {i // BATCH + 1} failed ({e}) — skipping")
            got = {}
        for t in chunk:
            abbr, season = want[t]
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
