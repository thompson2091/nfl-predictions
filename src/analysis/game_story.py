"""How one game is likely to go, chosen by code and phrased by Claude.

The same division of labour `game_notes` sets out, at the length of a preview
rather than a caption:

    CODE decides which facts the story is allowed to be about, and computes
    every number in it. CLAUDE writes the paragraphs between them.

**WHY THERE ARE NO INVENTED SCORELINES.** The preview this was modeled on
reads "something like Buffalo 10-7 after the first quarter wouldn't surprise
me", and that sentence cannot be written here. `_numbers_are_sourced` requires
every figure in the prose to appear in the brief, so a quarter-by-quarter
score the model made up fails the check and the whole story falls back to its
template. That guard is the one thing making generated text safe to print
beside real money, and a story is a longer opportunity to invent than a note
is, not a shorter one. So the narrative says how the game goes in words, and
every number in it — the projected final included — was computed before the
model saw it.

**THE SCORELINE IS THE BLEND'S, DERIVED THE WAY THE ODDS TAB DERIVES IT.**
`v3Projection` splits the adjusted total by the adjusted spread to get a
score, and this does the same arithmetic from the same `card["blend"]`. Two
derivations would put one number on the Odds tab and a different one in the
story, both labeled "our number", and a reader would be right to trust
neither. `test_the_story_scoreline_matches_the_projection_card` holds them
together.

**EVERY STORY WORKS WITH NO API KEY.** `fallback` is a complete narrative
built from the same facts. With no key, no network, or a response that fails
the number check, the page is plainer and equally correct.

Cached on disk under a hash of the brief AND the prompt, for the reason
`game_notes` documents: a key that omits half of what determines the output
leaves old wording on the live board after the rules that produced it change.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from src.analysis.game_notes import (
    CACHE_DIR as NOTES_CACHE,
    _client,
    _numbers_are_sourced,
)
# MOVED OUT, NOT COPIED. `game_notes` needs these too and imports this module's
# dependency rather than this module, so the shared checks live one level down
# where neither caller owns them. See `prose_checks` for what each one is for
# and which real failure it came from.
from src.analysis.prose_checks import (  # noqa: F401
    NAME_ALLOW,
    _DERIVES,
    _RUN,
    _SENT,
    _SIGNED,
    _names_are_sourced,
    _token,
    claims_are_safe,
)

#: Where phrased stories are kept between builds. Beside the notes cache but
#: not in it: the two are keyed differently and a story landing under a note's
#: hash would be served as a note.
CACHE_DIR = NOTES_CACHE.parent / "game_story_cache"

#: How many paragraphs a story runs to. Four is the length the preview this
#: was modeled on settles at, and it is about as much as fits on a phone
#: without the fold the caveats use.
PARAS = 4

#: An injury worth a sentence. A full report lists a dozen rested starters and
#: a story that names all of them is a list, not a story.
PRACTICE_OUT = ("Did not practice",)

#: Matchup rows worth naming, by absolute edge. The table has twenty and the
#: story is not the table.
TOP_EDGES = 3

#: How many players per market travel with the story, by projection. The
#: preview this was modeled on ends on player stat lines, which is the part a
#: reader carries away, and 220 passing rows is not a story.
TOP_PLAYERS = 3

#: The yardage markets, board key to the words a person uses. `receptions` is
#: kept separate in the payload and is added alongside.
PLAYER_MARKETS = (("passing_yards", "passing yards"),
                  ("receiving_yards", "receiving yards"),
                  ("rushing_yards", "rushing yards"))

#: A ticket share far enough from even to be worth a sentence, in points.
#: Below this the public is split and saying so is noise on every game.
MIN_PUBLIC_PP = 8.0

#: Line movement worth reporting, in points. `game_notes` uses the same floor
#: in probability terms and for the same reason: under it is book noise.
MIN_LINE_MOVE = 0.5

#: Below this many prior games a coach's rate is noise wearing a number.
#: `game_notes.MIN_COACH_GAMES` sets it and says why; borrowed rather than
#: re-picked so the two cannot drift apart.
MIN_COACH_GAMES = 20

#: Code to full name, inverted from the map `odds_features` already keeps for
#: reading book feeds. Inverted rather than retyped: a second list of thirty-two
#: team names is a second thing to be wrong, and this one is already exercised
#: by every odds import.
#:
#: IT IS IN THE BRIEF SO THE MODEL MAY USE IT. Without the names, "the Browns"
#: is a proper noun the facts never carried, and `_names_are_sourced` cannot
#: tell that from an invented one.
def _team_names() -> dict:
    from src.features.odds_features import TEAM_ABBREV  # noqa: PLC0415
    out: dict = {}
    for full, code in TEAM_ABBREV.items():
        # The longest spelling wins where a code has several; "Pittsburgh
        # Steelers" carries both the city and the nickname and so sources both.
        if code not in out or len(full) > len(out[code]):
            out[code] = full
    return out


def _f(x, nd=1):
    """A float rounded for printing, or None. Every number in a brief goes
    through here, so the brief and the page round identically — a figure the
    page shows as 21.5 and the brief carries as 21.4499 fails its own check."""
    return None if x is None else round(float(x), nd)


def scoreline(card: dict) -> dict | None:
    """Our projected final, from the blend, split the way `v3Projection` does.

    `hh = total/2 - spread/2` for the home side and `aa = total/2 + spread/2`
    for the road one — the spread is positive when the AWAY team is favored,
    which is the convention the card carries and the one the Odds tab reads.
    """
    b = card.get("blend") or {}
    sp, tot = b.get("spread"), b.get("total")
    if sp is None or tot is None:
        return None
    home = float(tot) / 2 - float(sp) / 2
    away = float(tot) / 2 + float(sp) / 2
    return {"home": card.get("home"), "away": card.get("away"),
            "home_pts": _f(home), "away_pts": _f(away),
            "spread": _f(sp), "total": _f(tot),
            "lead": card.get("away") if away >= home else card.get("home")}


def _injuries(card: dict) -> dict:
    """Who did not practice, per side, with the designation where there is one.

    THE PRACTICE REPORT, NOT ONLY THE DESIGNATION. `47_export_site` documents
    why at length: filtering on `report_status` alone leaves eight players
    across sixteen games, all of them in the Thursday fixture, because the
    final report is filed the day before kickoff. A receiver who did not
    practice on Wednesday is the earliest real signal there is.
    """
    out: dict = {}
    for side in ("away", "home"):
        team = card.get(side)
        rows = (card.get("injuries") or {}).get(team) or []
        named = []
        for r in rows:
            if r.get("rest"):
                continue
            if r.get("status") in ("Out", "Doubtful") \
                    or r.get("practice") in PRACTICE_OUT:
                named.append({"player": r.get("player"), "pos": r.get("pos"),
                              "injury": r.get("injury"),
                              "status": r.get("status")})
        out[team] = named
    return out


def _form(payload: dict, card: dict) -> dict:
    """Each side's last games: what it scored and allowed against expectation.

    `team_form` computes both, and the expectation is the point — 27 against a
    defense expected to concede 23 and 27 against one expected to concede 31
    are opposite weeks.
    """
    tf = payload.get("teamform") or {}
    teams = tf.get("teams") or {}
    out: dict = {}
    for side in ("away", "home"):
        team = card.get(side)
        rows = teams.get(team) or []
        if not rows:
            continue
        pf = [r[4] for r in rows if r[4] is not None]
        pa = [r[5] for r in rows if r[5] is not None]
        ef = [r[6] for r in rows if r[6] is not None]
        ea = [r[7] for r in rows if r[7] is not None]
        if not pf:
            continue
        out[team] = {
            "games": len(rows),
            "pf": _f(sum(pf) / len(pf)), "pa": _f(sum(pa) / len(pa)) if pa else None,
            "exp_for": _f(sum(ef) / len(ef)) if ef else None,
            "exp_against": _f(sum(ea) / len(ea)) if ea else None,
        }
    return out


def _records(payload: dict, card: dict) -> dict:
    """Each side's record against the spread, the total and the moneyline.

    From `team_lines`, which is the panel on the Odds tab — so the story and
    that table cannot disagree about what a team has done. A push is counted
    out rather than folded into either column, for the reason that module
    gives: calling it a loss understates every record in the direction that
    flatters a bet.
    """
    tl = payload.get("teamlines") or {}
    teams = tl.get("teams") or {}
    idx = {"ats": 8, "ou": 9, "ml": 10}
    out: dict = {}
    for side in ("away", "home"):
        team = card.get(side)
        rows = teams.get(team) or []
        if not rows:
            continue
        rec: dict = {"games": len(rows)}
        for name, i in idx.items():
            w = sum(1 for r in rows if r[i] == 1)
            l = sum(1 for r in rows if r[i] == -1)
            p = sum(1 for r in rows if r[i] == 0)
            rec[name] = {"w": w, "l": l, "p": p}
        out[team] = rec
    return out


def _edges(card: dict) -> list[dict]:
    """The matchup rows where the two sides are furthest apart.

    `matchup_stats` labels what is a proxy as a proxy, and that label travels:
    a story that presents a pressure proxy as a measured pressure rate is the
    kind of confident wrong sentence this project keeps finding.
    """
    m = card.get("matchup") or {}
    if m.get("thin"):
        return []
    rows = m.get("rows") or []
    scored = []
    for r in rows:
        sides = r.get("sides") or []
        if not sides:
            continue
        best = max(sides, key=lambda s: abs(s.get("edge") or 0))
        if not best.get("edge"):
            continue
        scored.append({
            "label": r.get("label"), "proxy": bool(r.get("proxy")),
            "offense": best.get("offense"), "defense": best.get("defense"),
            # ROUNDED TO ITS SIZE. "better by 4.667 plays a game" is a
            # count printed as a rate; "better by 0.2" on an EPA
            # differential has thrown the figure away. The threshold
            # is the unit boundary, not a preference.
            "edge": _f(best.get("edge"),
                       1 if abs(best.get("edge") or 0) >= 1 else 3),
        })
    scored.sort(key=lambda s: abs(s["edge"]), reverse=True)
    return scored[:TOP_EDGES]


_DIV_CACHE: dict = {}


def _divisional(card: dict) -> bool | None:
    """Whether the schedule calls this a divisional game, or None if unknown.

    Read once per process from `schedules.parquet`, which carries `div_game`
    for every fixture. A story that calls a cross-conference game a division
    rivalry is wrong in a way no number check would notice, and it is the kind
    of thing prose reaches for unprompted.
    """
    if not _DIV_CACHE:
        try:
            import polars as pl

            from src.utils.paths import get_path
            s = pl.read_parquet(get_path("raw") / "schedules.parquet")
            if "div_game" in s.columns:
                for r in s.select(["away_team", "home_team", "season",
                                   "div_game"]).iter_rows():
                    _DIV_CACHE[f"{r[0]}_{r[1]}_{r[2]}"] = bool(r[3])
            _DIV_CACHE.setdefault("_loaded", True)
        except Exception:                                        # noqa: BLE001
            _DIV_CACHE["_loaded"] = True
    for k, v in _DIV_CACHE.items():
        if k.startswith(f"{card.get('away')}_{card.get('home')}_"):
            return v
    return None


def _players(payload: dict, card: dict) -> list[dict]:
    """The biggest projected stat lines in this game, per market.

    THE PART A READER CARRIES AWAY. The preview this was modeled on ends on
    player numbers, and a game story without them is about two logos.

    ONE ROW PER PLAYER PER MARKET. Books post alternate lines, so the same man
    appears three times at 202.5, 209.5 and 215.5 with one projection; three
    rows of him would be the whole list. The line kept is the one closest to
    our projection, which is the one the comparison is actually about.
    """
    gid = card.get("game_id") or ""
    out: list[dict] = []
    blocks = [(payload.get("yards") or {}).get(k) for k, _ in PLAYER_MARKETS]
    labels = [lab for _, lab in PLAYER_MARKETS]
    rec = payload.get("receptions")
    if rec:
        blocks.append(rec)
        labels.append("receptions")
    for block, label in zip(blocks, labels):
        rows = (block or {}).get("rows") or []
        best: dict = {}
        for r in rows:
            if not str(r.get("game_id") or "").endswith(gid):
                continue
            # `proj` ON THE YARDAGE BOARDS, `mu` ON RECEPTIONS, which is the
            # same fallback `rowsFor` makes when it builds a row. Reading only
            # `proj` returned no receptions at all for a game that had 35 rows
            # of them, and an empty market looks exactly like a market with
            # nothing to say.
            name = r.get("player_name")
            proj = r.get("proj") if r.get("proj") is not None else r.get("mu")
            line = r.get("point")
            if not name or proj is None or line is None:
                continue
            gap = abs(float(proj) - float(line))
            if name not in best or gap < best[name]["_gap"]:
                best[name] = {"player": name, "team": r.get("team"),
                              "market": label, "proj": _f(proj),
                              "line": _f(line), "_gap": gap}
        top = sorted(best.values(), key=lambda x: -(x["proj"] or 0))[:TOP_PLAYERS]
        for x in top:
            x.pop("_gap", None)
        out += top
    return out


def _money(payload: dict, card: dict) -> dict:
    """Where the tickets are, and where the line went.

    BOTH HALVES OR NEITHER. A ticket share on its own says the public likes a
    side; the share WITH the move is the only version that distinguishes the
    crowd being right from the crowd being faded, which is the whole reason
    `public_money` records four times a day rather than once.
    """
    gid = card.get("game_id")
    games = payload.get("games") or {}
    pub = (games.get("public") or {}).get(gid) or {}
    lines = (games.get("lines") or {}).get(gid) or {}
    out: dict = {"public": [], "moves": []}
    for market, rows in pub.items():
        for s in (rows or {}).get("sides") or []:
            pct, side = s.get("pct"), s.get("side")
            if pct is None or side is None:
                continue
            if abs(float(pct) - 50.0) < MIN_PUBLIC_PP:
                continue
            out["public"].append({
                "market": market, "side": side, "pct": _f(pct),
                "open_pct": _f(s.get("open_pct")),
                "drift": _f(s.get("drift")),
            })
    for market, d in lines.items():
        now, opened = (d or {}).get("now"), (d or {}).get("open")
        if now is None or opened is None:
            continue
        if abs(float(now) - float(opened)) < MIN_LINE_MOVE:
            out["moves"].append({"market": market, "open": _f(opened),
                                 "now": _f(now), "still": True})
        else:
            out["moves"].append({"market": market, "open": _f(opened),
                                 "now": _f(now), "still": False})
    return out


def _coaches(card: dict) -> list[dict]:
    """Each coach, and his record only where there is enough of it.

    `game_notes.MIN_COACH_GAMES` exists so "69.4% in prime time" cannot be
    printed off 36 games without the 36 beside it. A coach under the floor is
    named and carries no rate at all, which is the honest version of a number
    nobody should read.
    """
    out = []
    for side in ("away", "home"):
        name = card.get(f"coach_{side}")
        if not name:
            continue
        n = card.get(f"{side}_coach_games_prior")
        row = {"team": card.get(side), "coach": name, "games": n}
        if n and int(n) >= MIN_COACH_GAMES:
            row["ats"] = _f((card.get(f"{side}_coach_ats_rate_prior") or 0) * 100)
            row["wins"] = _f((card.get(f"{side}_coach_win_rate_prior") or 0) * 100)
        out.append(row)
    return out


def _script(card: dict) -> list[dict]:
    """Which player markets here swing hardest with the way the game goes.

    `script_risk` measures how much each market moves with the final margin
    and `score_dist` says how likely that margin is; a row is worth a sentence
    only where both are true. The same floor the board uses.
    """
    out = []
    for key, hit in (card.get("script") or {}).items():
        if not isinstance(hit, dict) or (hit.get("p") or 0) < 0.12:
            continue
        team, pos, market = (key.split("|") + ["", ""])[:3]
        out.append({"team": team, "pos": pos, "market": market,
                    "band": hit.get("band"),
                    "lower_pct": _f((1 - (hit.get("mult") or 1)) * 100),
                    "chance_pct": _f((hit.get("p") or 0) * 100)})
    out.sort(key=lambda x: -(x["lower_pct"] or 0))
    return out[:3]


def _angles(payload: dict, card: dict) -> list[dict]:
    """The spread patterns each side carries here, with their real records.

    SHIPPED WITH THE VERDICT ATTACHED. `angles` measures every one of these
    together and not one clears the vig at the lower bound on a large enough
    sample — so an angle travels with `clears`, and a story that presented one
    as an edge would be making a claim the project has measured and rejected.
    """
    A = payload.get("angles") or {}
    mine = (A.get("week") or {}).get(card.get("game_id")) or []
    rows = {r.get("id"): r for r in (A.get("rows") or [])}
    out = []
    for item in mine:
        if not (isinstance(item, list) and len(item) >= 2):
            continue
        team, aid = item[0], item[1]
        r = rows.get(aid)
        if not r:
            continue
        a = r.get("all") or {}
        if not a.get("n"):
            continue
        pct = _f((a.get("pct") or 0) * 100)
        # BY HOW FAR FROM EVEN, NOT BY SAMPLE SIZE. Sorted by `n` the three
        # biggest splits on a game were "Outdoors" and "On grass" at exactly
        # 50.0% over four thousand games — true, enormous, and with nothing in
        # them. The floor keeps a 20-game curiosity out; the ordering picks the
        # ones that have actually diverged.
        if (a.get("n") or 0) < 200:
            continue
        out.append({"team": team, "label": r.get("label"),
                    "w": a.get("w"), "l": a.get("l"), "n": a.get("n"),
                    "pct": pct, "clears": bool(a.get("clears"))})
    out.sort(key=lambda x: -abs((x["pct"] or 50) - 50))
    return out[:3]


def facts(payload: dict, card: dict) -> dict:
    """Everything the story is allowed to be about, computed.

    Absent rather than empty where the payload cannot answer: a story built on
    a card with no distribution says nothing about the distribution instead of
    saying it was even.
    """
    u = card.get("unfold") or {}
    head = u.get("headline") or {}
    names = _team_names()
    f: dict = {
        "game": f"{card.get('away')} at {card.get('home')}",
        "away": card.get("away"), "home": card.get("home"),
        "kick": " ".join(x for x in (card.get("kick_day"),
                                     card.get("kick_et")) if x),
        "prime": bool(card.get("prime")),
        # BOTH SPELLINGS OF EACH SIDE, so "the Browns" is a fact rather than
        # a proper noun `_names_are_sourced` has never seen.
        "names": {card.get("away"): names.get(card.get("away")),
                  card.get("home"): names.get(card.get("home"))},
        # Divisional is a claim a story will make unprompted and get wrong.
        # It is on the schedule, so it is given rather than guessed.
        "divisional": _divisional(card),
        # REST IS A CLAIM A STORY REACHES FOR UNPROMPTED. A Thursday game is
        # a short week and a preview will say so whether or not it was told;
        # the card knows, so it is given. Same reasoning as `divisional`.
        "rest": {t: {"short_week": bool(card.get(f"{s}_is_short_week")),
                     "off_bye": bool(card.get(f"{s}_is_off_bye"))}
                 for s, t in (("away", card.get("away")),
                              ("home", card.get("home")))},
        "spread": _f(card.get("spread")), "total": _f(card.get("total")),
        "model_spread": _f(card.get("model_spread")),
        "model_total": _f(card.get("model_total")),
        "win_home": _f((card.get("win_home") or 0) * 100),
        "model_win_home": _f((card.get("model_win_home") or 0) * 100)
        if card.get("model_win_home") is not None else None,
        "scoreline": scoreline(card),
        "injuries": _injuries(card),
        "form": _form(payload, card),
        "records": _records(payload, card),
        "edges": _edges(card),
        # ALL OF THE GAME, not only the two teams. The board already knows
        # where the tickets are, where the line went, who the coaches are,
        # which markets swing with the script, which patterns each side
        # carries and what every player is projected for — and a preview
        # written without them is a preview of a different, thinner game.
        "players": _players(payload, card),
        "money": _money(payload, card),
        "coaches": _coaches(card),
        "script": _script(card),
        "angles": _angles(payload, card),
    }
    if not u.get("thin") and head:
        f["shape"] = {
            "n": u.get("n"), "dog": u.get("dog"), "fav": u.get("fav"),
            "upset": _f((head.get("upset") or {}).get("pct")),
            "one_score": _f((head.get("one_score") or {}).get("pct")),
            "shootout": _f((head.get("shootout") or {}).get("pct")),
            "grind": _f((head.get("grind") or {}).get("pct")),
        }
    return f


def _cmp(a, b, more: str = "above", less: str = "below",
         same: str = "level with") -> str:
    """Which of two figures is larger, in words.

    **THE BRIEF RESOLVES EVERY COMPARISON AND EVERY SIGN, AND THIS IS WHY.**
    The first draft handed the model signed edges and bare records and let it
    do the comparing. It came back with four sentences that passed the number
    check and were wrong anyway: a negative edge read as "Pittsburgh counters
    with a slight edge", a 5-5 over/under record read as "unders have hit more
    often", two scores "added together" to a total that was a different figure
    entirely, and two rows called proxies that were measured directly.

    Every one of those was the model DERIVING a claim rather than restating
    one. `_numbers_are_sourced` cannot catch it: it checks where a digit came
    from, not what was asserted about it. So the derivation happens here, in
    Python, where it is testable, and the model is left with nothing to infer.
    """
    if a is None or b is None:
        return ""
    if abs(a - b) < 0.05:
        return same
    return more if a > b else less


def _brief(f: dict) -> str:
    """The facts as the model sees them, with nothing left to work out.

    Flat text rather than JSON, because the number check reads this exact
    string — a figure that reaches the model but not the brief would be
    rejected in its own answer.

    NUMBERS APPEAR UNSIGNED. A minus sign is the single most misread character
    here, so a direction is stated in words and the magnitude beside it is
    absolute. `_claims_are_safe` then rejects any answer that reintroduces a
    sign the brief never carried.
    """
    L = []
    L.append(f"Game: {f['game']}" + (f", {f['kick']}" if f["kick"] else "")
             + (", prime time" if f["prime"] else ""))
    for code, full in (f.get("names") or {}).items():
        if full:
            L.append(f"{code} is the {full}.")
    for team, r in (f.get("rest") or {}).items():
        if r["off_bye"]:
            L.append(f"{team} is coming off a bye week.")
        elif r["short_week"]:
            L.append(f"{team} is on a short week.")
        else:
            L.append(f"{team} is on normal rest, neither a short week nor "
                     f"coming off a bye.")
    if f.get("divisional") is True:
        L.append("These two are in the same division.")
    elif f.get("divisional") is False:
        L.append("These two are not in the same division, so this is not a "
                 "division game or a rivalry game.")
    if f["spread"] is not None and f["total"] is not None:
        fav = f["away"] if f["spread"] > 0 else f["home"]
        dog = f["home"] if f["spread"] > 0 else f["away"]
        L.append(f"The book makes {fav} the favorite by {abs(f['spread'])} "
                 f"points and {dog} the underdog, with the total at "
                 f"{f['total']}.")
    s = f.get("scoreline")
    if s:
        # THE TOTAL IS GIVEN, NOT LEFT TO BE ADDED. The two rounded halves sum
        # to 40.3 where the adjusted total is 40.4, so a reader doing the
        # addition gets a different number from the one we hold. Stating it
        # removes both the discrepancy and the invitation.
        L.append(f"Our own adjusted number, which is the one to quote: "
                 f"{s['away']} {s['away_pts']} and {s['home']} "
                 f"{s['home_pts']}. That comes from an adjusted total of "
                 f"{s['total']} and a margin of {abs(s['spread'])} points to "
                 f"{s['lead']}. Do not add the two scores together.")
    if f["model_total"] is not None and f["total"] is not None:
        where = _cmp(f["model_total"], f["total"], "higher-scoring than",
                     "lower-scoring than", "in line with")
        L.append(f"Before it is blended with the book, our model on its own "
                 f"would set the total at {f['model_total']}, which is "
                 f"{where} the book's {f['total']}. This is a separate figure "
                 f"from our adjusted number above and is not its total.")
    sh = f.get("shape")
    if sh:
        L.append(f"In {sh['n']} past games priced like this one, {sh['dog']} "
                 f"won outright {sh['upset']}% of the time, {sh['one_score']}% "
                 f"finished within one score, {sh['shootout']}% were "
                 f"shootouts and {sh['grind']}% were grinds. These are games "
                 f"that have already happened, not a forecast of this one.")
    for team, rows in (f.get("injuries") or {}).items():
        if not rows:
            L.append(f"{team} has nobody who missed practice.")
            continue
        who = "; ".join(
            f"{r['player']} ({r['pos']}, {r['injury']}"
            + (f", listed {r['status']}" if r.get("status") else "") + ")"
            for r in rows[:6])
        L.append(f"{team} had these players miss practice: {who}.")
    for team, g in (f.get("form") or {}).items():
        off = _cmp(g["pf"], g["exp_for"])
        dfn = _cmp(g["pa"], g["exp_against"])
        L.append(
            f"{team} has scored {g['pf']} a game over its last {g['games']}, "
            f"against an expected {g['exp_for']} — {off} what the market "
            f"asked of its offense. It has allowed {g['pa']} against an "
            f"expected {g['exp_against']} — {dfn} what was asked of its "
            f"defense, so its defense has played "
            + ("better than" if dfn == "below" else
               "worse than" if dfn == "above" else "level with")
            + " expectation.")
    for team, r in (f.get("records") or {}).items():
        a, o, m = r["ats"], r["ou"], r["ml"]
        ou = ("the over and the under have landed equally often"
              if o["w"] == o["l"] else
              f"the over has landed more often" if o["w"] > o["l"]
              else "the under has landed more often")
        L.append(
            f"{team} in those {r['games']} games: it covered the spread "
            f"{a['w']} times and failed to cover {a['l']}. The game went over "
            f"the total {o['w']} times and under it {o['l']} — {ou}. It won "
            f"{m['w']} and lost {m['l']}.")
    for e in (f.get("edges") or []):
        better = e["edge"] > 0
        L.append(
            f"On {e['label']}, {e['offense']}'s offense is "
            + ("better" if better else "worse")
            + f" than {e['defense']}'s defense by {abs(e['edge'])}."
            + (" This is a proxy rather than a direct measurement."
               if e["proxy"] else ""))
    for c in (f.get("coaches") or []):
        if "ats" in c:
            L.append(f"{c['team']} is coached by {c['coach']}, who has won "
                     f"{c['wins']}% and covered {c['ats']}% across "
                     f"{c['games']} previous games. A record like that does "
                     f"not beat the bookmaker's cut by itself.")
        else:
            L.append(f"{c['team']} is coached by {c['coach']}, who has too "
                     f"few previous games for a meaningful record.")
    m = f.get("money") or {}
    for s in (m.get("public") or []):
        where = _cmp(s["pct"], s["open_pct"], "more", "less", "the same as")
        L.append(
            f"On the {s['market']}, {s['pct']}% of tickets are on {s['side']}, "
            f"against {s['open_pct']}% when it opened — {where} than it "
            f"started with. This is the count of bets placed, not the money "
            f"behind them.")
    for mv in (m.get("moves") or []):
        if mv["still"]:
            L.append(f"The {mv['market']} line has not moved from {mv['open']}.")
        else:
            way = _cmp(mv["now"], mv["open"], "up to", "down to", "level at")
            L.append(f"The {mv['market']} line opened at {mv['open']} and has "
                     f"moved {way} {mv['now']}.")
    for s in (f.get("script") or []):
        L.append(
            f"{s['team']}'s {s['pos']} {s['market']} is script-dependent: in "
            f"the {s['band']} case it is about {s['lower_pct']}% lower, and "
            f"that case has roughly a {s['chance_pct']}% chance of happening.")
    for a in (f.get("angles") or []):
        L.append(
            f"{a['team']} carries the pattern \"{a['label']}\", which has gone "
            f"{a['w']}-{a['l']} in {a['n']} graded games, {a['pct']}%. "
            + ("It clears break-even at the lower bound of its interval."
               if a["clears"] else
               "It does NOT clear break-even at the lower bound of its "
               "interval, so it is a record and not an edge."))
    for pl in (f.get("players") or []):
        side = _cmp(pl["proj"], pl["line"], "above", "below", "level with")
        L.append(
            f"{pl['player']} ({pl['team']}) is projected for {pl['proj']} "
            f"{pl['market']} against a posted line of {pl['line']}, which is "
            f"{side} it.")
    return "\n".join(L)


def _edge_polarity_is_kept(text: str, f: dict) -> bool:
    """A matchup edge must not be restated with its better/worse word flipped.

    The brief resolves the direction into a word and `_SIGNED` stops a minus
    coming back, but nothing stopped "better" being written where the facts
    said "worse" — the digits would still be sourced and the sentence would
    still be wrong, which is the whole family of bug this module is about.

    **IT ONLY JUDGES WHAT IT CAN PARSE.** Audited over the sixteen stories of
    one real week, 30 of 46 edge statements matched this shape and none of
    them was flipped; the other 16 were phrased in ways this does not read,
    and they pass. A check that guessed at those would reject correct prose,
    and a guard that fires on good work is a guard that gets deleted.
    """
    names = f.get("names") or {}

    def spellings(code):
        full = names.get(code) or ""
        return [code] + [w for w in full.split() if len(w) > 3]

    for e in (f.get("edges") or []):
        mag = str(abs(e["edge"]))
        if mag not in text:
            continue
        o, d = spellings(e["offense"]), spellings(e["defense"])
        both = "|".join(re.escape(x) for x in o + d)
        m = re.search(
            rf"({both})(?:'s|’s)?[^.]{{0,70}}?\b(better|worse)\b"
            rf"[^.]{{0,70}}?({both})[^.]{{0,60}}?{re.escape(mag)}",
            text, re.I)
        if not m:
            continue
        subject, word = m.group(1), m.group(2).lower()
        on_offense = subject.lower() in [x.lower() for x in o]
        want = ("better" if e["edge"] > 0 else "worse") if on_offense \
            else ("worse" if e["edge"] > 0 else "better")
        if word != want:
            return False
    return True


def _claims_are_safe(text: str, f: dict, brief: str) -> str | None:
    """What is wrong with this prose, or None.

    The shared checks in `prose_checks`, which `game_notes` runs over its own
    output too, plus the one that belongs to this module: a matchup edge needs
    the edge facts to know which way round it should read, and nothing else in
    the project has them.
    """
    why = claims_are_safe(
        text, brief,
        proxies=any(e["proxy"] for e in (f.get("edges") or [])))
    if why:
        return why
    if not _edge_polarity_is_kept(text, f):
        return "it restates a matchup edge the wrong way round"
    return None


PROMPT = """You write a short game preview for a sports betting app read by
people who do not bet much. A model has already decided which facts you may
use and computed every number in them.

Write {paras} short paragraphs saying how this game is likely to go: what each
side is trying to do, where the game turns, and what the most likely shape of
it is. Plain English, the voice of someone who watches football and respects
the reader.

RULES, all of them hard:
- Use ONLY the numbers in the facts below. Never introduce a number that is
  not there, and never round one that is. This includes scores: do NOT invent
  a quarter-by-quarter scoreline, a halftime score, or any margin that is not
  given. If you want to say a game stays close, say so in words.
- Do NOT calculate. Never add, subtract, average or otherwise derive a figure
  from the facts, and never describe one number as the result of combining
  others. Every number you write must already appear in the facts, meaning
  exactly what the facts say it means.
- The facts state every direction in words and every quantity without a sign.
  Restate those words. Never write "negative", never write a minus sign, and
  never decide for yourself which side an edge favors — the facts say which.
- Call something a proxy only where the facts call it a proxy.
- The projected final is rendered separately beneath your text. Do not repeat
  it as a prediction of your own and do not contradict it.
- Never advise, and never tell anyone what to bet. Explain how the game is
  likely to unfold; the reader decides.
- A number from comparable past games is what happened in them, not a forecast
  of this one. Say so when you use it.
- A fact marked a proxy is not a direct measurement. Do not present it as one.
- Write football, not a list. At most two paragraphs should lead with
  figures; the others should read as someone explaining the game, using a
  number only where it carries the point. Do not walk through the facts in
  the order they are given.
- You are given far more than fits. SELECT. Use the facts that make this
  game's story and leave the rest out; a preview that mentions everything
  mentions nothing. Finish on the players, who are what a reader remembers.
- A pattern's record is a record. Where the facts say it does not clear
  break-even, do not present it as an edge or a reason.
- No exclamation marks, no hype, no "smash", "lock" or "value play".
- AMERICAN SPELLING THROUGHOUT: favorite, defense, offense, color, behavior,
  analyze, center.

Facts:
{brief}

Reply with JSON only: {{"paras": ["...", "...", "...", "..."]}}"""


def fallback(f: dict) -> list[str]:
    """A complete narrative from the same facts, for no key and no network.

    Plainer than the written one and no less correct, which is the standard
    `game_notes` sets: with no key the page loses wording, never substance.
    """
    out: list[str] = []
    s, sh = f.get("scoreline"), f.get("shape")
    if f["spread"] is not None:
        fav = f["away"] if f["spread"] > 0 else f["home"]
        out.append(f"The book makes {fav} favored by {abs(f['spread'])} on a "
                   f"total of {f['total']}."
                   + (f" Our own number is {s['away']} {s['away_pts']}, "
                      f"{s['home']} {s['home_pts']}." if s else ""))
    if sh:
        out.append(f"In {sh['n']} games priced like this one, {sh['dog']} won "
                   f"outright {sh['upset']}% of the time and "
                   f"{sh['one_score']}% finished within one score. "
                   f"{sh['shootout']}% turned into shootouts against "
                   f"{sh['grind']}% that became grinds. Those are the games "
                   f"that have happened, not a forecast of this one.")
    inj = [(t, r) for t, r in (f.get("injuries") or {}).items() if r]
    if inj:
        bits = []
        for team, rows in inj:
            who = ", ".join(f"{r['player']} ({r['pos']})" for r in rows[:3])
            bits.append(f"{team} did not practice {who}")
        out.append("; ".join(bits) + ".")
    for team, g in (f.get("form") or {}).items():
        out.append(f"{team} has scored {g['pf']} a game over its last "
                   f"{g['games']} against an expected {g['exp_for']}, and "
                   f"allowed {g['pa']} against an expected "
                   f"{g['exp_against']}.")
    return out[:PARAS] or ["There is not enough on this game yet to say how "
                           "it is likely to go."]


def phrase(f: dict, use_cache: bool = True, use_ai: bool = True) -> dict:
    """The story, written or templated, never raising and never half-written.

    ALL FOUR PARAGRAPHS OR NONE. A story whose third paragraph failed the
    number check and fell back to a template sentence reads as two voices
    arguing, and the pair was never reviewed together. The check is on the
    whole answer.
    """
    brief = _brief(f)
    story = {"brief": brief, "scoreline": f.get("scoreline"),
             "paras": fallback(f), "written": False}
    # `--no-ai` ships the template and makes no call, which is also what a
    # missing key does. One code path for "the page is plainer", not two.
    if not use_ai:
        return story
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(
        json.dumps([PROMPT, PARAS, brief], sort_keys=True).encode()
    ).hexdigest()[:20]
    path = CACHE_DIR / f"{key}.json"
    got = None
    if use_cache and path.exists():
        try:
            got = json.loads(path.read_text())
        except json.JSONDecodeError:
            got = None
    if got is None:
        client = _client()
        if client is None:
            return story
        try:
            resp = client.messages.create(
                model="claude-sonnet-4-5-20250929", max_tokens=1200,
                messages=[{"role": "user", "content": PROMPT.format(
                    paras=PARAS, brief=brief)}])
            text = resp.content[0].text.strip()
            text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
            got = json.loads(text)
        except Exception:                                        # noqa: BLE001
            return story
        if use_cache:
            path.write_text(json.dumps(got, indent=1))
    paras = got.get("paras") if isinstance(got, dict) else None
    if not (isinstance(paras, list) and paras
            and all(isinstance(p, str) and p.strip() for p in paras)):
        return story
    if not all(_numbers_are_sourced(p, brief) for p in paras):
        story["unsourced"] = True
        return story
    # AND THAT THE SENTENCES AROUND THEM HOLD. Sourced digits are not a true
    # story: the first real one cited a total of 47.0 as the sum of 21.4 and
    # 18.9, and every figure in that sentence came from the brief.
    for p in paras:
        why = _claims_are_safe(p, f, brief)
        if why:
            story["rejected"] = why
            return story
    story["paras"] = [p.strip() for p in paras]
    story["written"] = True
    return story


def build(payload: dict, limit: int | None = None,
          use_cache: bool = True, use_ai: bool = True) -> dict[str, dict]:
    """A story for every game on the card, keyed by game id.

    FROZEN AT KICKOFF. A played game serves the story it kicked off with and
    is never written about again — `story_freeze` says at length why a fresh
    preview of a finished game is worse than no preview at all, and skipping
    the call is also what stops a Sunday-night rebuild costing sixteen of
    them. A played game with nothing recorded gets no story rather than a late
    one, which is the same choice `projection_freeze` makes in reverse and for
    the same reason: a late projection is still a number, and a late preview
    is a forecast of something that has happened.
    """
    from src.export import story_freeze as SF

    cards = (payload.get("games") or {}).get("cards") or []
    season, week = payload.get("season"), payload.get("week")
    out: dict[str, dict] = {}
    for card in cards[:limit]:
        gid = card["game_id"]
        # STARTED, NOT FINISHED. A final only lands once the game is over,
        # so between kickoff and the whistle `played` is still False and a
        # rebuild would write a fresh preview of a game in progress.
        if SF.started(card):
            kept = SF.frozen(gid, season, week)
            if kept:
                out[gid] = dict(kept, frozen=True)
            continue
        f = facts(payload, card)
        story = phrase(f, use_cache=use_cache, use_ai=use_ai)
        # THE BRIEF DOES NOT SHIP. It is the model's input and it is three
        # times the length of the story; the page needs the prose and the
        # scoreline, and nothing reads the facts it was built from.
        story.pop("brief", None)
        SF.record(gid, story, season, week)
        out[gid] = story
    SF.flush()
    return out
