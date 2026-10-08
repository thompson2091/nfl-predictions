"""A compact brief per game, for the Ask box to answer from.

The page is static files. An LLM that answers real questions needs the data
beside it, and the data cannot travel with the question: a client that sends
its own context is a client that can send anything, and the endpoint becomes a
free general-purpose model paid for by whoever owns the key.

So the context is BUILT HERE and deployed as one file per game. The browser
sends a game id and a question; the server loads that game's brief by id and
sends it. Nothing the reader types becomes context.

**Compact on purpose.** The full payload for one game runs to tens of
kilobytes of board rows, and most of it answers nothing anyone would ask. This
keeps the numbers a question is likely to touch — the line, both models, the
distribution, the public split, the injuries, the matchup edges and the twenty
best-priced players — which is a few kilobytes and covers the ground.
"""
from __future__ import annotations

#: How many priced players per market travel with the brief, PER ORDERING.
#:
#: "Who is likeliest to score" and "who is best priced" are different
#: questions. One EV-sorted cut answers only the second while looking like it
#: answers both: the CIN at PIT brief opened with Aaron Rodgers at 8% and
#: +1467 because his EV was highest, and the two players the model actually
#: made likeliest sat near the bottom on negative EV. Across the week's
#: sixteen games an EV cut of twenty already dropped a 39% scorer entirely.
#:
#: So each market travels twice, ordered each way. Eight apiece rather than
#: twenty of one, which costs fewer bytes than the single list did.
TOP_PLAYERS = 8

#: Markets worth including, board key to a human name.
MARKETS = [("any", "anytime touchdown"), ("first", "first touchdown"),
           ("recyds", "receiving yards"), ("rush", "rushing yards"),
           ("passyds", "passing yards"), ("rec", "receptions")]


#: The season's coordinators, read once. `ingest/coordinators` owns the file
#: and the parsing; this asks it rather than re-reading the CSV, so there is
#: one definition of who calls the plays.
_COORD_CACHE: dict = {}


def _coordinators(season: int) -> dict:
    """`{team: {"oc": name, "dc": name}}` for one season, or `{}`.

    A missing file is not an error here. The board ships without it and the
    brief simply carries no coordinators, which is what it did before.
    """
    if season in _COORD_CACHE:
        return _COORD_CACHE[season]
    out: dict = {}
    try:
        from src.ingest.coordinators import load

        df = load()
        if df.height and {"season", "team"} <= set(df.columns):
            for r in df.filter(df["season"] == season).to_dicts():
                pair = {k: r.get(k) for k in ("oc", "dc") if r.get(k)}
                if pair:
                    out[r["team"]] = pair
    except Exception:
        out = {}
    _COORD_CACHE[season] = out
    return out


def _edges(rows: list) -> list:
    """One matchup split, as sentences rather than nested numbers."""
    return [{"metric": r["label"],
             "sides": [f"{p['offense']} offense {p['off_val']} vs "
                       f"{p['defense']} defense {p['def_val']} "
                       f"(edge {p['edge']:+})" for p in r["sides"]]}
            for r in (rows or [])]


def _edges_terse(rows: list) -> list:
    """A half, as edges only.

    The full-game block above already carries both sides' rates for every
    metric. Repeating them per half tripled the matchup section for numbers
    the reader can already see; what a half adds is whether the edge moves,
    so that is all a half sends.
    """
    return [r["label"] + ": " + ", ".join(
        f"{p['offense']} {p['edge']:+}" for p in r["sides"])
        for r in (rows or [])]


def _game_key(gid: str) -> str:
    parts = (gid or "").split("_")
    return "_".join(parts[-2:]) if len(parts) >= 2 else gid


def _round(v, nd=3):
    return None if v is None else round(float(v), nd)


def for_game(payload: dict, card: dict) -> dict:
    """Everything the model should know about one game, and nothing else."""
    gid = card["game_id"]
    out = {
        "game": f"{card.get('away')} at {card.get('home')}",
        "game_id": gid,
        "season": payload.get("season"), "week": payload.get("week"),
        "kickoff": " ".join(x for x in (card.get("kick_day"),
                                        card.get("kick_et")) if x),
        "prime_time": bool(card.get("prime")),
        "roster_note": (f"every team below is this player's team in week "
                        f"{payload.get('week')} of {payload.get('season')}, "
                        f"from the roster ingested for this week"),
        "market": {"spread": card.get("spread"), "total": card.get("total"),
                   "home_win_pct": _round(card.get("win_home")),
                   "note": "spread is negative when the HOME team is favored"},
        "our_model": {"spread": card.get("model_spread"),
                      "total": card.get("model_total"),
                      "home_win_pct": _round(card.get("model_win_home")),
                      "note": "built without sight of the betting line"},
        "adjusted": card.get("blend"),
    }
    if card.get("unfold"):
        u = card["unfold"]
        out["how_it_may_go"] = {
            "based_on_games": u.get("n"),
            "headline": {k: v.get("pct") for k, v in (u.get("headline") or {}).items()},
            "shapes": [{"outcome": c["label"], "pct": c["pct"]}
                       for c in (u.get("cells") or [])[:5]],
        }
    if card.get("scores"):
        sc = card["scores"]
        out["score_distribution"] = {
            "based_on_games": sc.get("n"),
            "home_win_pct": (sc.get("home_win") or {}).get("pct"),
            "over_pct": (sc.get("over") or {}).get("pct"),
            "mean_total": sc.get("mean_total"),
            # `p`, the MEASURED rate at that rank, not the scoreline's share
            # of the comparable games. The model that orders this list prices
            # it fourteen times too high, so the number comes from the record.
            "likeliest_scores": [f"{card.get('home')} {x['home']}-{x['away']} "
                                 f"{card.get('away')} ({x.get('p')}%)"
                                 for x in (sc.get("scores") or [])[:5]],
            # And the part a list of near-identical percentages hides.
            "chance_none_of_those_land_pct": (
                None if sc.get("scores_covered") is None
                else round(100 - sc["scores_covered"], 1)),
        }
    pub = ((payload.get("games") or {}).get("public") or {}).get(gid)
    if pub:
        out["public_bets"] = {
            m: {s["side"]: s["pct"] for s in (blk.get("sides") or [])}
            for m, blk in pub.items()}
    lines = ((payload.get("games") or {}).get("lines") or {}).get(gid)
    if lines:
        out["line_movement"] = {
            m: {"opened": b.get("open"), "now": b.get("now"),
                "moved": b.get("move"), "since": b.get("open_at")}
            for m, b in lines.items() if b.get("open") is not None}
    if card.get("injuries"):
        out["injuries"] = {
            t: [f"{r['player']} ({r.get('pos')}) {r.get('status') or 'no practice'}"
                f"{' — ' + r['injury'] if r.get('injury') else ''}"
                for r in rows[:8]]
            for t, rows in card["injuries"].items()}
    if card.get("matchup"):
        mk = card["matchup"]
        sp = mk.get("splits") or {}
        out["matchup_edges"] = {
            "games_played": mk.get("games"),
            "full_game": _edges(sp.get("full") or mk.get("rows")),
            "not_available": [x["what"] for x in (mk.get("missing") or [])],
        }
        # THE HALVES ARE A DIFFERENT MATCHUP, not a smaller sample of the
        # same one. A team that scripts its opening drives shows up in the
        # first half and disappears into the season total.
        for k, label in (("h1", "first_half"), ("h2", "second_half")):
            if sp.get(k):
                out["matchup_edges"][label] = _edges_terse(sp[k])
        if sp.get("h1") or sp.get("h2"):
            out["matchup_edges"]["halves_note"] = (
                "halves carry the EDGE only; the rates behind them are in "
                "full_game. A positive edge favors that team's offense.")
    # WHO IS ON THE SIDELINE, AND WHAT THEY HAVE DONE.
    #
    # The brief carried two head-coach names and nothing else, so a question
    # about the coordinators — who call the plays, and whom this repo already
    # ingests and builds features from — was answered "not in the data
    # provided". The record is here too: an ATS rate over a real number of
    # games is the one coaching claim that is measured rather than asserted.
    coord = _coordinators(payload.get("season"))
    staff = {}
    for side in ("home", "away"):
        team = card.get(side)
        if not team:
            continue
        blk = {}
        if card.get(f"coach_{side}"):
            blk["head_coach"] = card[f"coach_{side}"]
        blk.update(coord.get(team) or {})
        games = card.get(f"{side}_coach_games_prior")
        if games:
            blk["record_before_this_game"] = {
                "games": games,
                "win_pct": _round(card.get(f"{side}_coach_win_rate_prior")),
                "ats_pct": _round(card.get(f"{side}_coach_ats_rate_prior")),
                "prime_time_ats_pct":
                    _round(card.get(f"{side}_coach_prime_ats_rate_prior")),
                "prime_time_games": card.get(f"{side}_coach_prime_games_prior"),
            }
        rest = []
        if card.get(f"{side}_is_off_bye"):
            rest.append("coming off a bye")
        if card.get(f"{side}_is_short_week"):
            rest.append("short week")
        if card.get(f"{side}_rest_diff"):
            rest.append(f"{card[f'{side}_rest_diff']:+} days of rest "
                        f"against the other side")
        if rest:
            blk["rest"] = ", ".join(rest)
        if blk:
            staff[team] = blk
    if staff:
        staff["note"] = ("oc and dc are the offensive and defensive "
                         "coordinators. Rates are the coach's record BEFORE "
                         "this game, never including it.")
        out["coaches"] = staff

    # WHICH PLAYERS THE GAME SCRIPT MOVES, and how likely that script is.
    # Measured, not assumed: a running back's rushing line swings 0.51
    # between a blowout win and a blowout loss, a receiver's receptions
    # barely move. Below a one-in-eight chance the page drops the flag, so
    # the brief does too.
    script = card.get("script") or {}
    tips = []
    for k, v in script.items():
        if (v.get("p") or 0) < 0.12:
            continue
        team, pos, market = (k.split("|") + ["", ""])[:3]
        tips.append(
            f"{team} {pos} {market}: {round((1 - v['mult']) * 100)}% lower if "
            f"the game goes badly for them, and a {round(v['p'] * 100)}% "
            f"chance of that")
    if tips:
        out["script_dependence"] = {
            "note": "fitted on past games in the same spot, by position "
                    "and market",
            "rows": tips,
        }

    out["players"] = {}
    for key, name in MARKETS:
        rows = _players(payload, key, gid)
        if rows:
            out["players"][name] = rows
    notes = (payload.get("notes") or {}).get(gid) or []
    if notes:
        out["our_notes"] = [{"title": n.get("title"), "why": n.get("why")}
                            for n in notes]
    return out


def _two_ways(rows: list, shape, prob) -> dict:
    """The same rows ordered by chance and by price, deduplicated.

    A player at the top of both lists appears once, in `likeliest`, with the
    price still on the row — so the second list stays what it claims to be
    (the best-priced players NOT already named) rather than repeating the
    first for a few hundred bytes.
    """
    by_prob = sorted(rows, key=lambda r: -(prob(r) or -1e9))[:TOP_PLAYERS]
    named = {id(r) for r in by_prob}
    by_ev = [r for r in sorted(rows, key=lambda r: -(r.get("ev") or -1e9))
             if id(r) not in named][:TOP_PLAYERS]
    out = {"likeliest": [shape(r) for r in by_prob]}
    if by_ev:
        out["best_priced_others"] = [shape(r) for r in by_ev]
    return out


def _players(payload: dict, key: str, gid: str) -> dict:
    """One market in one game, ordered by chance and by price."""
    if key in ("any", "first"):
        want = "anytime_td" if key == "any" else "first_td"
        mk = next((m for m in payload.get("markets") or []
                   if m.get("key") == want), None)
        rows = [p for p in ((mk or {}).get("players") or [])
                if _game_key(p.get("game_id") or "") == gid and p.get("priced")]
        return _two_ways(
            rows,
            # TEAM TRAVELS WITH THE PLAYER.
            #
            # Without it the rows are names and prices, so a question about
            # who a player plays for is answered from the model's training
            # rather than from this week's roster — and players change teams.
            lambda p: {"player": p["player"], "team": p.get("team"),
                       "pos": p.get("pos"), "odds": p.get("odds_num"),
                       "our_pct": _round((p.get("model_only")
                                          or p.get("ours")), 3),
                       "book_pct": _round(p.get("book"), 3),
                       "ev_per_100": _round(p.get("ev"), 1)},
            lambda p: p.get("model_only") or p.get("ours"))
    stat = {"recyds": "receiving_yards", "rush": "rushing_yards",
            "passyds": "passing_yards", "rec": "receptions"}[key]
    ym = (payload.get("yards") or {}).get(stat) or {}
    rows = [r for r in (ym.get("rows") or [])
            if _game_key(r.get("game_id") or "") == gid
            and r.get("point") is not None]
    return _two_ways(
        rows,
        lambda r: {"player": r["player_name"], "team": r.get("team"),
                   "line": r.get("point"),
                   "odds": r.get("odds"), "we_project": _round(r.get("proj"), 1),
                   "our_pct": _round(r.get("ours"), 3),
                   "book_pct": _round(r.get("fair_prob"), 3),
                   "ev_per_100": _round(r.get("ev"), 1)},
        lambda r: r.get("ours"))


def build(payload: dict) -> dict[str, dict]:
    """One brief per game on the board, keyed by game id."""
    cards = (payload.get("games") or {}).get("cards") or []
    return {c["game_id"]: for_game(payload, c) for c in cards}


# ──────────────────────────────────────────────────────────────────────────
# SLICES, AND WHY THE BRIEF STOPPED BEING ONE FILE
# ──────────────────────────────────────────────────────────────────────────
#
# `for_game` is a FIXED GUESS at what a question will touch, and the guess was
# wrong in five places at once. Measured 2026-10-08 against what the app
# itself draws for one game:
#
#   every priced player           ~40 a game, 25 KB   brief carried 16
#   best price and books quoting  on every board row   brief carried neither
#   both per-$100 bases           shipped 2026-10-07   brief carried one
#   the Pass/Leans/Strong verdict on every board row   brief carried none
#   this game's angles            12 a game            brief carried none
#   the model's season record     7.5 KB trimmed       brief carried none
#
# The last two cannot be fixed by widening the guess. The whole angles table
# is 1.2 MB and the whole record is 254 KB; neither travels with a question,
# and "how has the model done on Dallas?" is unanswerable from any per-game
# file however fat.
#
# So the model ASKS. `core` is ~2 KB and always sent, and it ends with a menu
# of slices; `deploy/ask.php` exposes a `get_data` tool that resolves a slice
# NAME against the files below. The reader's question never becomes context —
# the model picks from a fixed enum, the server maps it to a path, and an
# unknown name comes back as an error rather than as a file read.
#
# What a reader could in principle steer is WHICH of our own published slices
# the model fetches, which is data already on the site. What they cannot do is
# supply any of it.

#: The slices `get_data` can return, and what each one costs to send.
#:
#: Sizes measured on 2026 week 5. They are in the docstring because the tool's
#: round-trip budget in `ask.php` is set against them: a question that pulls
#: every slice should still fit a sane prompt.
#:
#:     game      ~10 KB   the overview: distribution, matchup edges, public
#:                        money, line movement, coaches, script, our notes
#:     players   ~25 KB   every priced player in every market for this game
#:     angles     ~5 KB   the splits that apply to this fixture, with records
#:     record     ~8 KB   the model's season record, the default week range
#:     team       ~2 KB   the model's prop record on one of these two teams
SLICES: tuple[str, ...] = ("game", "players", "angles", "record", "team")


def core(payload: dict, card: dict) -> dict:
    """The block that travels with every question, and the menu beside it.

    Deliberately small. Everything here answers "what is this game and what
    do the three numbers say", which is what most questions open with — and
    anything a question actually reaches for comes through the tool, so a
    reader who asks about one player does not pay for forty.
    """
    gid = card["game_id"]
    return {
        "game": f"{card.get('away')} at {card.get('home')}",
        "game_id": gid,
        "away": card.get("away"), "home": card.get("home"),
        "season": payload.get("season"), "week": payload.get("week"),
        "kickoff": " ".join(x for x in (card.get("kick_day"),
                                        card.get("kick_et")) if x),
        "prime_time": bool(card.get("prime")),
        "roster_note": (f"every team named in any slice is that player's team "
                        f"in week {payload.get('week')} of "
                        f"{payload.get('season')}, from the roster ingested "
                        f"for this week"),
        "market": {"spread": card.get("spread"), "total": card.get("total"),
                   "home_win_pct": _round(card.get("win_home")),
                   "note": "spread is negative when the HOME team is favored"},
        "our_model": {"spread": card.get("model_spread"),
                      "total": card.get("model_total"),
                      "home_win_pct": _round(card.get("model_win_home")),
                      "note": "built without sight of the betting line"},
        "adjusted": card.get("blend"),
        "you_can_fetch": {
            "game": "this game in detail: the score distribution, the "
                    "matchup unit by unit, what the public is betting, how "
                    "the line has moved, the coaches, and our own notes",
            "players": "every player in this game a book has priced, in "
                       "every market, with our number, the book's, the "
                       "blend, both per-$100 figures, the best price "
                       "available and how many books are quoting",
            "angles": "the historical splits that apply to this fixture — "
                      "road underdog, off a bye, prime time and so on — "
                      "with each one's record and whether it clears the "
                      "rate you need to profit",
            "record": "how our model has actually done this season: games "
                      "against the spread, totals, moneyline, and the prop "
                      "bets by market",
            "team": "our prop record on one of these two teams. Needs "
                    "`team`, one of " + f"{card.get('away')} or "
                    f"{card.get('home')}",
        },
    }


def slice_players(payload: dict, gid: str) -> dict:
    """EVERY priced player in this game, in every market.

    The trimmed cut in `for_game` exists because 25 KB is a lot to send with
    a question nobody asked. It is the right size for a brief and the wrong
    answer to "what are Chris Godwin's numbers" when Godwin is the ninth
    name: the row simply was not there, and the model said so politely about
    a player whose line is printed on the screen the reader is looking at.

    Carries what the BOARD carries, which the brief did not: the best price
    and who has it, how many books are quoting, the verdict, and both
    per-$100 figures. A brief that disagrees with the page a reader is
    looking at is worse than one that is merely thin.
    """
    g = _game_key(gid)
    out: dict = {"game_id": gid, "markets": {}}
    for key, name in MARKETS:
        if key in ("any", "first"):
            want = "anytime_td" if key == "any" else "first_td"
            mk = next((m for m in payload.get("markets") or []
                       if m.get("key") == want), None)
            rows = [p for p in ((mk or {}).get("players") or [])
                    if _game_key(p.get("game_id") or "") == g
                    and p.get("priced")]
            shaped = [{
                "player": p["player"], "team": p.get("team"),
                "pos": p.get("pos"), "odds": p.get("odds_num"),
                "our_pct": _round(p.get("model_only")
                                  if p.get("model_only") is not None
                                  else p.get("ours"), 3),
                "book_pct": _round(p.get("book"), 3),
                "adjusted_pct": _round(p.get("ours"), 3),
                "per_100_model": _round(p.get("ev"), 1),
                "per_100_adjusted": _round(p.get("ev_adj"), 1),
                "best_price": p.get("best"), "best_book": p.get("best_book"),
                "books_level_at_best": p.get("n_best"),
                "our_read": p.get("read"),
            } for p in rows]
            shaped.sort(key=lambda r: -(r["our_pct"] or 0))
        else:
            stat = {"recyds": "receiving_yards", "rush": "rushing_yards",
                    "passyds": "passing_yards", "rec": "receptions"}[key]
            ym = (payload.get("yards") or {}).get(stat) or {}
            rows = [r for r in (ym.get("rows") or [])
                    if _game_key(r.get("game_id") or "") == g
                    and r.get("point") is not None]
            shaped = [{
                "player": r["player_name"], "team": r.get("team"),
                "line": r.get("point"), "odds": r.get("odds"),
                "we_project": _round(r.get("proj"), 1),
                "likely_range": ([_round(r.get("lo"), 1), _round(r.get("hi"), 1)]
                                 if r.get("lo") is not None else None),
                "our_pct": _round(r.get("model_only"), 3),
                "book_pct": _round(r.get("fair_prob"), 3),
                "adjusted_pct": _round(r.get("ours"), 3),
                "per_100_adjusted": _round(r.get("ev"), 1),
                # HOW MANY BOOKS QUOTE THIS LINE, which is the gate the
                # shortlist's floors were fitted under. A yardage "consensus"
                # is a median of two on a typical cell, and a row quoted by
                # one book is a de-vig against that book alone.
                "books_quoting": r.get("n_books"),
            } for r in rows]
            shaped.sort(key=lambda r: -((r["adjusted_pct"] or 0)))
        if shaped:
            out["markets"][name] = shaped
    out["note"] = ("our_pct is the model with no sight of the price, book_pct "
                   "is the price with the book's cut removed, adjusted_pct is "
                   "the two blended. A small positive gap can still lose "
                   "money: per_100 is what clears the cut.")
    return out


def slice_angles(payload: dict, card: dict) -> dict:
    """The historical splits that apply to THIS fixture, with their records.

    `angles.week[game_id]` is `[[team, angle_id], ...]` — which spots the two
    teams are in this week — and `angles.rows` holds each one's definition and
    record. Joined here rather than shipped whole: the full table is 1.2 MB
    and twelve rows of it are about this game.
    """
    a = payload.get("angles") or {}
    gid = card["game_id"]
    pairs = ((a.get("week") or {}).get(gid)
             or (a.get("week") or {}).get(_game_key(gid)) or [])
    defs = {r.get("id"): r for r in (a.get("rows") or [])}
    be = a.get("break_even")
    out = []
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        team, aid = pair[0], pair[1]
        d = defs.get(aid)
        if not d:
            continue
        rec = d.get("all") or {}
        out.append({
            "team": team, "angle": d.get("label"), "category": d.get("cat"),
            "what_it_means": str(d.get("blurb") or "").replace("{team}", team),
            "record": (f"{rec.get('w')}-{rec.get('l')}"
                       if rec.get("w") is not None else None),
            "games": rec.get("n"),
            "cover_pct": _round(rec.get("pct"), 3),
            "range_low_pct": _round(rec.get("lo"), 3),
            "range_high_pct": _round(rec.get("hi"), 3),
            "clears_break_even": bool(rec.get("clears")),
        })
    return {
        "game_id": gid,
        "break_even_pct": be,
        "note": ("cover_pct is how often teams in this spot beat the spread "
                 "since 2015. range_low_pct to range_high_pct is where that "
                 "rate could really sit; a range that straddles "
                 "break_even_pct has shown no edge. These are splits, not "
                 "the model."),
        "angles": out,
    }


def slice_record(payload: dict) -> dict:
    """How the model has actually done, on the range the Record page opens on.

    The whole scorecard is 254 KB, most of it the per-leg detail the page
    needs to let a reader re-cut it by week. One range is 7.5 KB and is the
    one the page shows by default, so this is what a reader asking "how has
    your model done" is looking at.
    """
    sc = payload.get("scorecard") or {}
    ranges = sc.get("ranges") or {}
    key = sc.get("default")
    block = ranges.get(key) if isinstance(key, str) else None
    if block is None and ranges:
        key = sorted(ranges)[-1]
        block = ranges[key]
    return {
        "season": sc.get("season"),
        "weeks": key,
        "weeks_played": sc.get("played"),
        "break_even_pct": sc.get("break_even"),
        "games": (block or {}).get("games"),
        "player_bets": (block or {}).get("players"),
        "note": ("ours/model is our number with no sight of the price, book "
                 "is the de-vigged price, blend/adjusted is the two mixed. "
                 "`pct` is the hit rate and `lo`/`hi` are where it could "
                 "really sit. `roi` is return per unit staked, so -0.06 is "
                 "a loss of $6 per $100. A rate above break_even_pct is "
                 "what profit needs."),
    }


def slice_team(payload: dict, team: str) -> dict:
    """The model's prop record on one team, summed from the graded legs.

    The payload carries no per-team record: the Record page's own per-team
    table is summed in the browser from `scorecard.bets`, which is 182 KB of
    leg detail. The same arithmetic here, so a reader can ask about one of
    the two teams in front of them without the page's whole working.

    `test_the_per_team_record_sums_to_the_pooled_one` is what keeps this from
    drifting away from the figure the page prints.
    """
    b = (payload.get("scorecard") or {}).get("bets") or {}
    teams = b.get("teams") or []
    try:
        idx = teams.index(team)
    except ValueError:
        return {"team": team, "bets": 0,
                "note": f"no graded prop bets on {team} this season"}
    markets = b.get("markets") or []
    per: dict = {}
    n = 0
    model = adj = 0.0
    for wk, entries in (b.get("weeks") or {}).items():
        for e in entries or []:
            if not isinstance(e, (list, tuple)) or len(e) < 4:
                continue
            if e[3] != idx:
                continue
            for leg in e[2] or []:
                if not isinstance(leg, (list, tuple)) or len(leg) < 7:
                    continue
                mkt = markets[leg[0]] if leg[0] is not None \
                    and leg[0] < len(markets) else "?"
                row = per.setdefault(mkt, {"bets": 0, "model_return": 0.0,
                                           "adjusted_return": 0.0})
                row["bets"] += 1
                n += 1
                if leg[6] is not None:
                    row["model_return"] += float(leg[6])
                    model += float(leg[6])
                if leg[4] is not None:
                    row["adjusted_return"] += float(leg[4])
                    adj += float(leg[4])
    for row in per.values():
        row["model_per_100"] = _round(row["model_return"] / row["bets"] * 100, 1) \
            if row["bets"] else None
        row["adjusted_per_100"] = _round(
            row["adjusted_return"] / row["bets"] * 100, 1) if row["bets"] else None
        row.pop("model_return"), row.pop("adjusted_return")
    return {
        "team": team, "bets": n,
        "model_per_100": _round(model / n * 100, 1) if n else None,
        "adjusted_per_100": _round(adj / n * 100, 1) if n else None,
        "by_market": per,
        "note": ("one bet is one player, one game, one market, at the line "
                 "nearest that player's median. per_100 is the average return "
                 "on a $100 stake. Bets in the same game move together, so "
                 "a run of them is fewer independent results than it looks."),
    }


def build_slices(payload: dict) -> dict[str, dict]:
    """Every slice file, keyed by the path under `data/ask/` it is written to.

    One `core/<gid>` and one `game/<gid>` and one `players/<gid>` and one
    `angles/<gid>` per fixture, one `team/<TEAM>` per team playing, and one
    `record/season` for the lot. `deploy/ask.php` resolves a slice name to
    one of these and will not read anything else.
    """
    cards = (payload.get("games") or {}).get("cards") or []
    out: dict[str, dict] = {}
    for c in cards:
        gid = c["game_id"]
        out[f"core/{gid}"] = core(payload, c)
        out[f"game/{gid}"] = for_game(payload, c)
        out[f"players/{gid}"] = slice_players(payload, gid)
        out[f"angles/{gid}"] = slice_angles(payload, c)
    for c in cards:
        for t in (c.get("away"), c.get("home")):
            if t and f"team/{t}" not in out:
                out[f"team/{t}"] = slice_team(payload, t)
    if payload.get("scorecard"):
        out["record/season"] = slice_record(payload)
    return out
