"""What is worth saying about one game, chosen by code and phrased by Claude.

The v3 page shows a handful of plain-English notes per game. The division of
labour between this module and the model that writes them is the whole design,
and it is not the obvious one:

    CODE decides which notes exist, and computes every number in them.
    CLAUDE writes the sentence around numbers it is handed.

The alternative — hand Claude forty numbers and ask what is interesting — reads
better and cannot be trusted. A note is a claim about money. If the sentence
and the figure beside it come from the same generated string, then nothing on
the page has checked that they agree, and the failure mode is a confident
sentence citing a number that was never in the data. Here the stat chips render
from `note["stats"]`, which is built from the payload; the generated text is
only ever the prose between them.

**And the prose is checked too.** `_numbers_are_sourced` pulls every numeric
token out of what comes back and requires each one to appear in the brief the
model was given. A note that fails falls back to its template sentence. This is
cheap and it closes the one hole the split above leaves open: Claude writing
"about a touchdown" is fine, Claude writing "by 9.5" when the brief said 6.5 is
not.

**Every note works with no API key.** `fallback` is a complete sentence built
from the same facts. With no key, no network, or a refused response the page is
plainer and equally correct, which is why the tests need neither.

Notes are cached on disk under a hash of their brief. A rebuild whose numbers
have not moved costs nothing; one where a line moved re-writes only the notes
that changed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

#: Where phrased notes are kept between builds, keyed by brief hash.
CACHE_DIR = Path("data/raw/game_notes_cache")

#: How far our number has to sit from the book's before a disagreement is
#: worth a card. Below this the two agree as far as anyone can measure, and a
#: note saying so would be noise on every game every week.
MIN_SPREAD_GAP = 3.0
MIN_TOTAL_GAP = 3.0

#: A price difference between books, in points of implied probability. Under
#: this it is rounding, not a shop worth opening a second account for.
MIN_SHOP_PP = 1.5

#: Line movement worth reporting, in points of implied probability. Borrowed
#: from `rlm.MIN_MOVE_PP` rather than re-picked, because that module already
#: defines where book noise ends.
MIN_MOVE_PP = 1.0

#: The touchdown fade that `fade_unders` measures as bettable on a yardage
#: under, and the projected usage it needs. Both are that module's constants;
#: they are imported lazily so this module can be read without polars.
FADE_CUT = -8.0

#: Target-type name to the key the BOARD uses for the same market. A row id is
#: built from the board's key, so a note pointing at `receiving_yards|...`
#: resolves to nothing and its Add button silently does nothing.
BOARD_KEY = {"receiving_yards": "recyds", "rushing_yards": "rush",
             "passing_yards": "passyds", "receptions": "rec"}

#: Below this many prior games in the slot, a coach's rate is noise wearing a
#: number. `situational_features` defines it and says why in as many words:
#: so "69.4% in prime time" cannot be printed off 36 games without the 36.
MIN_COACH_GAMES = 20

#: A rest gap worth a sentence, in days. Below three it is the ordinary
#: difference between a Sunday and a Monday game.
MIN_REST_GAP = 3

#: Said on every coaching note, because the alternative is a page that implies
#: an edge the project has twice measured and not found. `situational_features`
#: tested thirteen of these on 2,853 games: not one clears the vig, and the
#: coach cover rate is used hard by the model while changing nothing out of
#: sample, which is what fitting noise looks like from the inside.
COACH_CAVEAT = ("Measured across 2,853 past games, a record like this one "
                "does not beat the bookmaker's cut by itself.")


def _money(x):
    """Two decimal places, always. "$39.4" is not how money is written."""
    return f"{float(x):.2f}"


def _num(x, nd=1):
    return None if x is None else round(float(x), nd)


def _pct(p):
    return None if p is None else f"{round(float(p) * 100)}%"


def _sign(x, nd=1):
    v = round(float(x), nd)
    return f"+{v}" if v > 0 else str(v)


def _odds(o):
    if o is None:
        return None
    o = int(o)
    return f"+{o}" if o > 0 else str(o)


def _team_side(card, spread):
    """Which team a home-signed spread favors, and by how much."""
    if spread is None:
        return None, None
    return (card["home"], abs(spread)) if spread < 0 else (card["away"], abs(spread))


def _game_key(gid: str) -> str:
    """Yards rows carry `2026_03_SEA_WAS`; cards carry `SEA_WAS`."""
    parts = (gid or "").split("_")
    return "_".join(parts[-2:]) if len(parts) >= 2 else gid


def select(payload: dict, card: dict) -> list[dict]:
    """Every note this game earns, in the order they should be read.

    Selection is thresholded rather than top-k: a game where nothing disagrees
    gets few notes, which is the honest outcome and reads as one. Padding every
    game to seven cards would mean showing the seventh-most-interesting thing
    about a game that had two.
    """
    gid = card["game_id"]
    notes: list[dict] = []
    notes += _line_notes(payload, card, gid)
    notes += _player_notes(payload, card, gid)
    notes += _coach_notes(card)
    notes += _unfold_note(card)
    for i, n in enumerate(notes):
        n["id"] = f"{gid}:{n['kind']}"
        n["order"] = i
        # Complete at selection, not at phrasing. A note that only becomes
        # renderable once `phrase` has run is a note that renders blank on
        # every path that skips it — no key, a cache miss, a refused call.
        n["title"] = _headline(n)
        n["why"] = n["fallback"]
    return notes


def _headline(n: dict) -> str:
    """The template headline, used until a better one is written for it."""
    return {
        "line_gap": "Our model and the books disagree on this line",
        "total_gap": "Our model and the books disagree on the total",
        "move": "The price has moved since it opened",
        "shop": "One book is paying more than the rest",
        "td_value": "The best-priced touchdown bet in this game",
        "td_fade": "A touchdown price we think is too high",
        "unfold": "How games priced like this one have finished",
    }.get(n["kind"], {
        "fade_under": "A player we rate below his touchdown price",
        "yards_edge": "We project this player above his line",
    }.get(n["kind"].rsplit("_", 2)[0], n["kind"].replace("_", " ").capitalize()))


def _line_notes(payload: dict, card: dict, gid: str) -> list[dict]:
    out = []
    book_sp, mod_sp = card.get("spread"), card.get("model_spread")
    if book_sp is not None and mod_sp is not None \
            and abs(mod_sp - book_sp) >= MIN_SPREAD_GAP:
        bt, bby = _team_side(card, book_sp)
        mt, mby = _team_side(card, mod_sp)
        same = bt == mt
        out.append({
            "kind": "line_gap", "cat": "The line",
            "stats": [{"v": f"{bt} by {_num(bby)}", "l": "sportsbooks"},
                      {"v": f"{mt} by {_num(mby)}", "l": "our model"}],
            "brief": (f"The book has {bt} by {_num(bby)}. Our team model has "
                      f"{mt} by {_num(mby)}, a gap of "
                      f"{_num(abs(mod_sp - book_sp))} points. The model is "
                      f"built without sight of the betting line, so this is a "
                      f"second opinion rather than a version of the same one."),
            "fallback": (f"The book makes it {bt} by {_num(bby)}; our model "
                         f"makes it {mt} by {_num(mby)}."
                         + ("" if same else " They disagree on the winner.")),
            "pick": f"{card['away'] if bt == card['home'] else card['home']} "
                    f"on the spread",
            "model": True,
        })
    book_tot, mod_tot = card.get("total"), card.get("model_total")
    if book_tot is not None and mod_tot is not None \
            and abs(mod_tot - book_tot) >= MIN_TOTAL_GAP:
        higher = mod_tot > book_tot
        out.append({
            "kind": "total_gap", "cat": "The line",
            "stats": [{"v": str(_num(book_tot)), "l": "total, sportsbooks"},
                      {"v": str(_num(mod_tot)), "l": "total, our model"}],
            "brief": (f"The posted total is {_num(book_tot)} points. Our model "
                      f"expects {_num(mod_tot)}, which is "
                      f"{_num(abs(mod_tot - book_tot))} "
                      f"{'higher' if higher else 'lower'}."),
            "fallback": (f"Books set the total at {_num(book_tot)}; our model "
                         f"expects about {_num(mod_tot)}."),
            "pick": f"{'Over' if higher else 'Under'} {_num(book_tot)} points",
            "model": True,
        })

    rows = [r for r in (payload.get("games") or {}).get("rows") or []
            if _game_key(r.get("game_id") or "") == gid]
    moved = [r for r in rows if r.get("market") == "h2h"
             and abs(r.get("move_pp") or 0) >= MIN_MOVE_PP]
    if moved:
        r = max(moved, key=lambda x: abs(x["move_pp"]))
        toward = r["move_pp"] > 0
        out.append({
            "kind": "move", "cat": "The line",
            "stats": [{"v": f"{_odds(r.get('open_odds'))} → "
                            f"{_odds(r.get('consensus'))}",
                       "l": f"{r['outcome']} to win, open → now"}],
            "brief": (f"{r['outcome']}'s moneyline went from "
                      f"{_odds(r.get('open_odds'))} to "
                      f"{_odds(r.get('consensus'))}, moving "
                      f"{'toward' if toward else 'away from'} them by "
                      f"{_num(abs(r['move_pp']))} points of implied chance. "
                      f"Following line moves has not paid in this project's "
                      f"own testing."),
            "fallback": (f"The market has moved "
                         f"{'toward' if toward else 'away from'} "
                         f"{r['outcome']} since it opened."),
            "pick": f"{r['outcome']} to win · {_odds(r.get('best'))}",
        })

    shop = [r for r in rows if (r.get("gap_pp") or 0) >= MIN_SHOP_PP]
    if shop:
        r = max(shop, key=lambda x: x["gap_pp"])
        out.append({
            "kind": "shop", "cat": "The line",
            "stats": [{"v": _odds(r.get("best")), "l": f"best ({r.get('best_book')})"},
                      {"v": _odds(r.get("consensus")), "l": "typical book"}],
            "brief": (f"On {r['outcome']}, {r.get('best_book')} pays "
                      f"{_odds(r.get('best'))} where a typical book pays "
                      f"{_odds(r.get('consensus'))} — worth "
                      f"{_num(r['gap_pp'])} points of implied chance, free, "
                      f"for holding more than one account."),
            "fallback": (f"{r.get('best_book')} is paying more than other "
                         f"books on {r['outcome']}."),
            "pick": f"{r['outcome']} at {r.get('best_book')} · "
                    f"{_odds(r.get('best'))}",
        })
    return out


def _player_notes(payload: dict, card: dict, gid: str) -> list[dict]:
    out = []
    td = next((m for m in payload.get("markets") or []
               if m.get("key") == "anytime_td"), None)
    # `_game_key` on BOTH sides. The touchdown board and the yardage boards
    # both carry `2026_03_ATL_GB` while the cards carry `ATL_GB`, so comparing
    # them raw matched nothing — and matching nothing is indistinguishable
    # from a game with no priced players, which is a state that really occurs.
    here = [p for p in ((td or {}).get("players") or [])
            if _game_key(p.get("game_id") or "") == gid and p.get("priced")]

    # THE VALUE PICK COMES FROM THE SHORTLIST, NOT FROM MAX EV.
    #
    # Ranking this game's priced players by expected value puts the longest
    # price on top almost every time, and `longshot` is unambiguous about what
    # that band is worth: the tail is priced at about 4.8% against a true 2.4%,
    # the book charges a 95% margin there, and our ordering advantage over it
    # is 0.025 of AUC. The first build of this note led with a +2827 player at
    # "4% ours against 3% theirs" and claimed 48 dollars per 100 — a number
    # that is arithmetic on two estimates which are both inside their own
    # noise. The shortlist is the list this project would actually bet, and it
    # already carries the floor, the band and the verdict.
    short = {r["player"] for r in
             ((td or {}).get("shortlist") or {}).get("rows") or []}
    priced = [p for p in here if p.get("ev") is not None
              and p.get("player") in short]
    if priced:
        best = max(priced, key=lambda p: p["ev"])
        if best["ev"] > 0:
            out.append({
                "kind": "td_value", "cat": "Players",
                "stats": [{"v": _pct(best.get("ours")), "l": "our chance"},
                          {"v": _pct(best.get("book")), "l": "books' chance"}],
                "brief": (f"{best['player']} is priced at "
                          f"{_odds(best.get('odds_num'))} to score. We make him "
                          f"{_pct(best.get('ours'))} where the book makes him "
                          f"{_pct(best.get('book'))} — "
                          f"{_num((best.get('ours') or 0) * 100 - (best.get('book') or 0) * 100)}"
                          f" points higher — worth about "
                          f"{_num(best['ev'])} dollars per 100 staked. A $10 "
                          f"bet returns "
                          f"${_money(10 * (abs(best['odds_num']) / 100 if best['odds_num'] > 0 else 100 / abs(best['odds_num'])))}."),
                "fallback": (f"{best['player']} is the best-priced touchdown "
                             f"bet in this game by our numbers."),
                "lean": "back",
                "pick": f"{best['player']} to score · "
                        f"{_odds(best.get('odds_num'))}",
                # `rowsFor` builds a touchdown row id as `key|player`. Built
                # here so the Add button adds the actual leg; a note whose
                # subject is not a board row carries no id and renders no
                # button, rather than a button that does nothing.
                "pick_id": f"any|{best['player']}",
            })
        # The fade is drawn from every priced player, not just the
        # shortlist — being absent from the shortlist is not what makes a
        # player a fade — but the book has to make him a real candidate.
        # Below 10% the "overpriced" verdict is a statement about the tail.
        fadeable = [p for p in here if p.get("ev") is not None
                    and (p.get("book") or 0) >= 0.10]
        worst = min(fadeable, key=lambda p: p["ev"]) if fadeable else None
        if worst is not None and worst["ev"] < -10 and worst is not best:
            out.append({
                "kind": "td_fade", "cat": "Players",
                "stats": [{"v": _pct(worst.get("ours")), "l": "our chance"},
                          {"v": _pct(worst.get("book")), "l": "books' chance"}],
                "brief": (f"{worst['player']} is the most overpriced touchdown "
                          f"bet here. The book makes him "
                          f"{_pct(worst.get('book'))}; we make him "
                          f"{_pct(worst.get('ours'))}, which is "
                          f"{_num((worst.get('book') or 0) * 100 - (worst.get('ours') or 0) * 100)}"
                          f" points lower. This is a player to "
                          f"avoid, not a bet to place — no book posts the other "
                          f"side of a touchdown prop."),
                "fallback": (f"{worst['player']} is priced well above our "
                             f"number. One to leave alone."),
                "lean": "avoid",
                "pick": f"Avoid {worst['player']} to score",
                "avoid": True,
            })

    fades = {p["player"]: p for p in here
             if (p.get("diff") or 0) <= FADE_CUT}
    for market, label, unit in (("receiving_yards", "receiving yards", "rec yds"),
                                ("rushing_yards", "rushing yards", "rush yds"),
                                ("receptions", "catches", "catches")):
        ym = (payload.get("yards") or {}).get(market) or {}
        rows = [r for r in (ym.get("rows") or [])
                if _game_key(r.get("game_id") or "") == gid]
        # `point` must exist. A row with no posted line still carries a
        # projection, and the first build rendered it as "under None" in the
        # headline, the stat chip and the pick — three places, no error.
        hit = [r for r in rows
               if r.get("point") is not None
               and any(r.get("player_name") == n.split(" (")[0] or
                       r.get("player_name") in n for n in fades)]
        if not hit:
            continue
        r = hit[0]
        out.append({
            "kind": f"fade_under_{market}", "cat": "Players",
            "stats": [{"v": f"under {_num(r.get('point'))}", "l": label},
                      {"v": str(_num(r.get("proj"))), "l": "we project"}],
            "brief": (f"Our touchdown model rates {r['player_name']} well "
                      f"below his price to score. Historically that view has "
                      f"carried to his {label} line: players faded this hard, "
                      f"who were projected to see the ball, went under "
                      f"{label} about 60% of the time across 2023-2025. "
                      f"His line is {_num(r.get('point'))} and we project "
                      f"{_num(r.get('proj'))}."),
            "fallback": (f"{r['player_name']} is rated well below his "
                         f"touchdown price, and that has historically pointed "
                         f"to the under on his {label} line."),
            "pick": f"{r['player_name']} under {_num(r.get('point'))} {unit}",
            "measured": True,
        })
        break

    for market, unit in (("receiving_yards", "rec yds"),
                         ("rushing_yards", "rush yds"),
                         ("passing_yards", "pass yds")):
        ym = (payload.get("yards") or {}).get(market) or {}
        rows = [r for r in (ym.get("rows") or [])
                if _game_key(r.get("game_id") or "") == gid
                and r.get("ev") is not None and r.get("point") is not None]
        if not rows:
            continue
        r = max(rows, key=lambda x: x["ev"])
        if r["ev"] <= 0:
            continue
        out.append({
            "kind": f"yards_edge_{market}", "cat": "Players",
            "stats": [{"v": str(_num(r.get("proj"))), "l": "yards we project"},
                      {"v": _pct(r.get("ours")),
                       "l": f"chance of over {_num(r.get('point'))}"}],
            # THE GAP IS COMPUTED HERE, not left to be derived.
            #
            # `_numbers_are_sourced` cannot tell arithmetic from invention: a
            # brief holding 36.5 and 19.5 and a sentence saying "17 yards
            # above the line" is a correct derivation that the guard rejects.
            # 21% of the first build's notes failed this way. Widening the
            # brief is the fix rather than loosening the guard, because the
            # difference is a number the reader wants and code should own.
            "brief": (f"We project {r['player_name']} for "
                      f"{_num(r.get('proj'))} {unit} against a posted line of "
                      f"{_num(r.get('point'))}, which is "
                      f"{_num(abs((r.get('proj') or 0) - (r.get('point') or 0)))}"
                      f" {unit} above it."),
            "fallback": (f"We project {r['player_name']} above his "
                         f"{_num(r.get('point'))} {unit} line."),
            "pick": f"{r['player_name']} over {_num(r.get('point'))} {unit} · "
                    f"{_odds(r.get('odds'))}",
            # An over/under row id is `key|player|point`, where `key` is the
            # BOARD's market key rather than the target-type name.
            "pick_id": (f"{BOARD_KEY[market]}|{r['player_name']}"
                        f"|{r.get('point')}"),
        })
        break
    return out


def _unfold_note(card: dict) -> list[dict]:
    """How the game is likely to go, from games the market priced the same way.

    **The numbers are counted, not reasoned.** Every figure comes from
    `score_dist.scenarios`, which partitions comparable games by margin band
    and over/under, so the column sums to 100 and a reader can go down it.
    The model writes the sentence around them and, as everywhere here, may not
    introduce a figure that is not in the brief.

    Deliberately NOT a prediction of this game. It is the record of games hung
    at this spread and total, which is a weaker claim and a defensible one,
    and the wording has to keep that distinction.
    """
    u = card.get("unfold")
    if not u or u.get("thin") or not u.get("cells"):
        return []
    h = u.get("headline") or {}
    top = u["cells"][:3]
    ways = "; ".join(f"{c['label']} {c['pct']}%" for c in top)
    return [{
        "kind": "unfold", "cat": "How it may go", "counted": True,
        "stats": [{"v": f"{h['one_score']['pct']}%", "l": "within one score"},
                  {"v": f"{h['upset']['pct']}%", "l": f"{u['dog']} wins"},
                  {"v": f"{h['shootout']['pct']}%", "l": "high scoring"}],
        "brief": (
            f"Across {u['n']} past games hung at this spread and total, the "
            f"three commonest shapes were: {ways}. "
            f"{h['one_score']['pct']}% finished within one score, "
            f"{h['blowout']['pct']}% were decided by 17 or more, and "
            f"{u['dog']} won outright {h['upset']['pct']}% of the time. "
            f"Scoring ran at least 7 above the posted total in "
            f"{h['shootout']['pct']}% and at least 7 below in "
            f"{h['grind']['pct']}%. These are counted outcomes of comparable "
            f"games, not a forecast of this one."),
        "fallback": (
            f"In {u['n']} games priced like this one, {h['one_score']['pct']}% "
            f"finished within one score and {u['dog']} won outright "
            f"{h['upset']['pct']}% of the time."),
        "pick": f"{card.get('away')} at {card.get('home')}",
    }]


def _rate(card: dict, side: str, stat: str) -> tuple:
    """A rate and its sample size, or (None, None) when it has no business
    being printed. The two always travel together."""
    n = card.get(f"{side}_coach_{stat}_games_prior"
                 if stat == "prime" else f"{side}_coach_games_prior")
    r = card.get(f"{side}_coach_prime_ats_rate_prior" if stat == "prime"
                 else f"{side}_coach_ats_rate_prior")
    if r is None or not n:
        return (None, None)
    return (r, n)


def _coach_notes(card: dict) -> list[dict]:
    """The handicapper's situational angles, as context and labeled as such.

    **SELECTION IS ON THE SITUATION, NEVER ON THE RECORD.** A note fires
    because the game is in prime time or because one side is on a short week —
    facts about the fixture, fixed before any outcome is looked at. Choosing
    instead to show the games where a coach happens to have a lopsided record
    would manufacture the appearance of signal out of 32 coaches and a
    thousand slices, which is precisely the search this project's own tests
    exist to catch. The record is then reported whatever it says, including
    when it says nothing.
    """
    out = []
    ch, ca = card.get("coach_home"), card.get("coach_away")
    if not (ch and ca):
        return out
    home, away = card.get("home"), card.get("away")

    if card.get("prime_slot"):
        # Only coaches with a real sample in the slot. A prime-time rate off
        # nine games is the number this threshold exists to suppress.
        parts, stats = [], []
        for side, name, team in (("home", ch, home), ("away", ca, away)):
            r, n = _rate(card, side, "prime")
            if r is None or n < MIN_COACH_GAMES:
                continue
            cov = int(round(r * n))
            stats.append({"v": f"{cov}-{n - cov}", "l": f"{name}, prime time"})
            parts.append(f"{name} has covered {cov} of {n} prime-time games "
                         f"({_pct(r)})")
        if parts:
            out.append({
                "kind": "coach_prime", "cat": "Coaching", "context": True,
                "stats": stats,
                "brief": ("This is a prime-time game. " + ". ".join(parts)
                          + ". Covering means the team beat the betting line, "
                          "not merely won. " + COACH_CAVEAT),
                "fallback": ("A prime-time game. " + " ".join(
                    p + "." for p in parts)),
                "pick": f"{away} at {home} on the spread",
            })

    # Rest. One side short or rested and the other not — a fact about the
    # schedule, known months in advance and priced by the book accordingly.
    hs, as_ = card.get("home_is_short_week"), card.get("away_is_short_week")
    hb, ab = card.get("home_is_off_bye"), card.get("away_is_off_bye")
    gap = card.get("home_rest_diff")
    bits, figs = [], []
    if hs and not as_:
        bits.append(f"{home} is on a short week and {away} is not")
    elif as_ and not hs:
        bits.append(f"{away} is on a short week and {home} is not")
    if hb and not ab:
        bits.append(f"{home} is coming off a bye")
    elif ab and not hb:
        bits.append(f"{away} is coming off a bye")
    if has_num(gap) and abs(gap) >= MIN_REST_GAP:
        side, other = (home, away) if gap > 0 else (away, home)
        figs.append({"v": f"{abs(int(gap))} days", "l": f"{side} extra rest"})
        if not bits:
            bits.append(f"{side} has had {abs(int(gap))} more days off "
                        f"than {other}")
    if bits:
        out.append({
            "kind": "rest", "cat": "Coaching", "context": True,
            "stats": figs,
            "brief": (". ".join(b[0].upper() + b[1:] for b in bits)
                      + ". " + COACH_CAVEAT),
            "fallback": ". ".join(b[0].upper() + b[1:] for b in bits) + ".",
            "pick": f"{away} at {home} on the spread",
        })
    return out


def has_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ---------------------------------------------------------------- phrasing


#: Phrases that say a bet is worth taking, and phrases that say it is not.
#: Checked against the note's own `lean`, because a sentence can be perfectly
#: fluent, cite only sourced numbers, and still recommend the opposite of what
#: the numbers say.
#: Patterns rather than literals. A plain list caught "good value" and let
#: "great value" through, which is the same claim with a different adjective —
#: and the generated text is not drawn from a fixed vocabulary.
_SAYS_BACK = re.compile(
    r"\b(?:good|great|solid|strong|nice|real|excellent|clear)\s+value\b"
    r"|\bbargain\b|\bunder-?priced\b|\bworth (?:a )?back\w*\b"
    r"|\bbetter than the price\b|\bprice is too low\b|\bgenerous\b"
    r"|\bunder-?valued\b|\bmore likely than (?:the |his )?price\b"
    r"|\bworth (?:a )?(?:bet|play|look)\b", re.I)
_SAYS_AVOID = re.compile(
    r"\btoo high\b|\bover-?priced\b|\bavoid\b|\bpricey\b|\bexpensive\b"
    r"|\bsteer clear\b|\bleave (?:it |him )?alone\b|\bnot worth\b"
    r"|\bworse than the price\b|\bover-?valued\b|\bstay away\b"
    r"|\bless likely than (?:the |his )?price\b", re.I)


def _direction_is_consistent(text: str, lean: str) -> bool:
    """A note that rates a player ABOVE his price must not call him pricey.

    The failure this exists for, in full: our 22% against the book's 15% came
    back headlined "touchdown price may be too high". Every figure in it was
    sourced and the arithmetic was right; the direction was inverted. In
    betting jargon "the price is too high" means the ODDS are generous, which
    is the opposite of what a casual reader hears, and the card said "good
    value" two lines below its own headline.
    """
    t = text or ""
    if lean == "back":
        return not _SAYS_AVOID.search(t)
    if lean == "avoid":
        return not _SAYS_BACK.search(t)
    return True


_NUM = re.compile(r"\d+(?:\.\d+)?")


def _numbers_are_sourced(text: str, brief: str) -> bool:
    """Every figure in the prose must appear in the facts it was given.

    The one guard that makes generated text safe to print beside real money.
    Without it a fluent sentence can invent a line, a price or a percentage
    and nothing downstream would disagree with it.

    Percent signs and currency are not checked — only the digits — and a
    number the model rounds (6.5 to "about 7") fails, which is the intended
    strictness: a note that rounds is replaced by one that does not.
    """
    # COMPARED AS NUMBERS, NOT AS STRINGS.
    #
    # String equality rejected "a 3-point spread" against a brief that said
    # "3.0" — the same figure, spelled the way a person writes it. Genuine
    # invention still fails, because 9.5 does not equal 6.5 and a rounded 7
    # does not equal 6.5 either; only the notation is forgiven.
    have = {float(n) for n in _NUM.findall(brief)}
    return all(float(n) in have for n in _NUM.findall(text))


def _client():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key and Path(".env").exists():
        for line in Path(".env").read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("\"'")
                break
    if not key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    return anthropic.Anthropic(api_key=key)


PROMPT = """You write one-line explanations for a sports betting app read by
people who do not bet much. A model has already decided which facts matter.
Your only job is the wording.

Game: {game}

For each note below, write:
  "title" — a short headline, under 60 characters, no final period.
  "why"   — one or two sentences saying why it matters to someone deciding
            whether to bet. Plain English. No jargon.

RULES, all of them hard:
- Use ONLY the numbers in that note's facts. Never introduce a number that is
  not there, and never round one that is.
- Never advise. Explain what the number means; the reader decides.
- A note marked model is our own team model's view. State it plainly as our
  number against the book's. Do not hedge it, apologize for it, or call it
  unproven, untested or a lean.
- A note marked avoid is about a bet NOT to place: we rate the player BELOW
  his price. Never call it good value.
- A note marked back means we rate the player ABOVE his price, so the odds are
  generous and the bet is worth considering. NEVER describe it as "priced too
  high", "pricey", "overpriced" or "expensive". Those read to an ordinary
  person as a warning, and this is the opposite of one.
- Say which way the disagreement runs in plain words: "we make him likelier
  than the price does", not "the price is off".
- A note marked measured has real historical backing; it may say so plainly.
- A note marked counted comes from counting real past games, not from
  reasoning. Say so plainly: these are what happened in comparable games, not
  a forecast of this one. Do not write it as a prediction.
- A note marked context is background. Keep the measured figure its facts
  carry, stated as a fact about the angle rather than as an apology.
- No exclamation marks, no hype, no "smash", "lock" or "value play".

Notes:
{notes}

Reply with JSON only: {{"<id>": {{"title": "...", "why": "..."}}, ...}}"""


def phrase(notes: list[dict], card: dict, use_cache: bool = True) -> list[dict]:
    """Attach `title` and `why` to each note, from Claude or from the template.

    Never raises and never leaves a note unphrased. Cache hit, cache miss with
    a key, and no key at all are three quality levels of the same page.
    """
    if not notes:
        return notes
    game = f"{card['away']} at {card['home']}"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(
        json.dumps([[n["id"], n["brief"]] for n in notes],
                   sort_keys=True).encode()).hexdigest()[:20]
    path = CACHE_DIR / f"{key}.json"
    if use_cache and path.exists():
        try:
            got = json.loads(path.read_text())
        except json.JSONDecodeError:
            got = None
        if got:
            return _apply(notes, got)

    client = _client()
    if client is None:
        return notes
    listing = "\n".join(
        f'- id "{n["id"]}": {n["brief"]}'
        + "".join(f" [{f}]" for f in ("model", "avoid", "measured",
                                      "context", "counted") if n.get(f))
        + (f" [{n['lean']}]" if n.get("lean") else "")
        for n in notes)
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-5-20250929", max_tokens=1600,
            messages=[{"role": "user",
                       "content": PROMPT.format(game=game, notes=listing)}])
        text = resp.content[0].text.strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
        got = json.loads(text)
    except Exception:                                            # noqa: BLE001
        return notes
    if use_cache:
        path.write_text(json.dumps(got, indent=1))
    return _apply(notes, got)


def _apply(notes: list[dict], got: dict) -> list[dict]:
    for n in notes:
        w = got.get(n["id"])
        if not isinstance(w, dict):
            continue
        title, why = w.get("title"), w.get("why")
        # Both or neither: a generated headline over a template explanation
        # reads as a mismatch, and the pair is what was reviewed together.
        if not (isinstance(title, str) and isinstance(why, str)):
            continue
        if not (_numbers_are_sourced(title, n["brief"])
                and _numbers_are_sourced(why, n["brief"])):
            n["unsourced"] = True
            continue
        lean = n.get("lean")
        if lean and not (_direction_is_consistent(title, lean)
                         and _direction_is_consistent(why, lean)):
            n["inverted"] = True
            continue
        n["title"], n["why"] = title.strip(), why.strip()
    return notes


def build(payload: dict, limit: int | None = None) -> dict[str, list[dict]]:
    """Notes for every game on the card, keyed by game id."""
    cards = (payload.get("games") or {}).get("cards") or []
    out = {}
    for card in cards[:limit]:
        notes = select(payload, card)
        if notes:
            out[card["game_id"]] = phrase(notes, card)
    return out
