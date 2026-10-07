"""Who has gone one way five weeks running, as of a given week.

**THE RULE LIVED IN THE PAGE AND THAT IS WHY IT MOVED.** `v3Streak` read the
history inlined in the payload and counted back from whatever "now" happened
to be, so a question about a past week got today's answer: "how did the streak
picks do in week 3" quietly changed every time a later week landed, and
nothing anywhere recorded which players the filter had actually shown. A rule
that cannot be asked about the past cannot be scored, which is the whole point
of the Record page.

So the count is as-of. For a bet in week W the window is the player's last
five GRADED weeks strictly before W — which crosses the season boundary,
because `player_history.history` is one record per player and five weeks into
2026 does not exist yet.

**WHICHEVER DIRECTION IS THE MARKET'S OWN NORM IS NOT A STREAK.** Measured on
the week the JS rule was written, "did not score in 4 of his last 5" was true
of 385 of the 398 players eligible on first touchdown. That is not a fact
about a player; it is what a touchdown market looks like, and a tag drawn on
97% of rows is a label for the market wearing a player's name. So the cut is
read off the board: whichever direction covers more than half the players a
market can even count is that market's default and is not flagged. Nothing is
hardcoded per market, so a season where unders stop being the norm on
receptions starts showing them without anyone editing this.

The baseline is as-of too, for the same reason the streak is.

**THIS IS RECENT FORM, NOT AN EDGE.** Nothing here is filtered on price and
this project has not measured it into one. It is published so a reader
scanning a board can see it; the Record page scores it so that claim can be
checked rather than assumed.
"""
from __future__ import annotations

from collections import defaultdict

#: How many graded weeks the window is, and how many have to run one way.
#: These are the numbers `v3Streak` served — kept rather than refitted, so
#: the move into Python is a port and not a new rule. Any change to them is a
#: change to what the board has been showing and belongs in its own commit.
OF = 5
MIN = 4

#: Where each field sits in a `player_history.history` row:
#: `[season, week, opp, home, line, odds, did, played, other]`.
I_SEASON, I_WEEK, I_LINE, I_DID = 0, 1, 4, 6


def _window(rows, season: int, week: int):
    """The player's last `OF` graded weeks strictly before (season, week).

    `history` is newest first, so this is a prefix — but only after dropping
    the weeks that had not happened yet, which is the whole as-of question.
    """
    before = [r for r in rows
              if (r[I_SEASON], r[I_WEEK]) < (season, week)]
    return before[:OF]


def direction(rows, season: int, week: int, yesno: bool) -> str | None:
    """`"over"`, `"under"`, or None where there is no streak to report.

    Silent rather than approximate on a short or ragged record: every one of
    the `OF` weeks has to carry a result, and a line too on a market that has
    one. A player with three graded weeks is not on a two-week streak.
    """
    w = _window(rows, season, week)
    if len(w) < OF:
        return None
    hit = known = 0
    for r in w:
        did = r[I_DID]
        line = r[I_LINE]
        if did is None:
            continue
        if not yesno and line is None:
            continue
        known += 1
        if (did == 1) if yesno else (did > line):
            hit += 1
    if known < OF:
        return None
    miss = known - hit
    if hit >= MIN:
        return "over"
    if miss >= MIN:
        return "under"
    return None


def detail(rows, season: int, week: int, yesno: bool) -> dict | None:
    """`{"dir", "ran", "of"}` — the direction and how many weeks ran it.

    What the board's tag says ("4 of 5 over"), so nothing downstream has to
    count the window a second time. None where `direction` is None.
    """
    d = direction(rows, season, week, yesno)
    if d is None:
        return None
    w = _window(rows, season, week)
    hit = 0
    for r in w:
        did, line = r[I_DID], r[I_LINE]
        if did is None or (not yesno and line is None):
            continue
        if (did == 1) if yesno else (did > line):
            hit += 1
    return {"dir": d, "ran": hit if d == "over" else len(w) - hit,
            "of": len(w)}


def is_yesno(market: str) -> bool:
    """Whether a market has a line to beat. One lookup, declared once."""
    from src.evaluation.player_history import MARKETS

    return any(m[0] == market and m[2] == "yesno" for m in MARKETS)


def baseline(per_player: dict, season: int, week: int, yesno: bool) -> dict:
    """What share of the eligible players ran each way, as of that week.

    `per_player` is `{player: rows}` for ONE market. Returns
    `{"over": f, "under": f}`, and `{"over": 1.0, "under": 1.0}` where there
    is nothing to measure — with no population, nothing is rare, so nothing
    is flagged. That is the same answer `v3StreakBase` gives and it is the
    safe one: a baseline of zero would flag the entire board.
    """
    n = up = dn = 0
    for rows in per_player.values():
        d = direction(rows, season, week, yesno)
        if len(_window(rows, season, week)) < OF:
            continue
        n += 1
        if d == "over":
            up += 1
        elif d == "under":
            dn += 1
    if not n:
        return {"over": 1.0, "under": 1.0}
    return {"over": up / n, "under": dn / n}


def flags(history: dict, season: int, weeks, markets=None) -> dict:
    """`{(week, market, player): "over" | "under"}` for the flagged players.

    `history` is `player_history.history()` — `{market: {player: rows}}`,
    keyed by the normalised name that function keys on. Only the players whose
    direction is NOT their market's own norm are present, so membership of the
    returned mapping is the flag itself.
    """
    from src.evaluation.player_history import MARKETS

    kinds = {mk: kind for mk, _l, kind, _u, _s in MARKETS}
    out: dict = {}
    for mk, per in history.items():
        if markets is not None and mk not in markets:
            continue
        yesno = kinds.get(mk) == "yesno"
        for w in weeks:
            base = baseline(per, season, w, yesno)
            for player, rows in per.items():
                d = direction(rows, season, w, yesno)
                if d is None:
                    continue
                # The market's own default is not a finding about a player.
                if base[d] > 0.5:
                    continue
                out[(w, mk, player)] = d
    return out


def counts(flags_map: dict) -> dict:
    """How many players each (week, market) flagged, for a note on the page."""
    n: dict = defaultdict(int)
    for (w, mk, _p) in flags_map:
        n[(w, mk)] += 1
    return dict(n)
