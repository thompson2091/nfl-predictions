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
             "sides": [f"{p['offense']} offence {p['off_val']} vs "
                       f"{p['defense']} defence {p['def_val']} "
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
        "market": {"spread": card.get("spread"), "total": card.get("total"),
                   "home_win_pct": _round(card.get("win_home")),
                   "note": "spread is negative when the HOME team is favoured"},
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
            "common_scores": [f"{card.get('home')} {x['home']}-{x['away']} "
                              f"{card.get('away')} ({x['pct']}%)"
                              for x in (sc.get("scores") or [])[:5]],
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
                "full_game. A positive edge favours that team's offence.")
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
            lambda p: {"player": p["player"], "odds": p.get("odds_num"),
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
        lambda r: {"player": r["player_name"], "line": r.get("point"),
                   "odds": r.get("odds"), "we_project": _round(r.get("proj"), 1),
                   "our_pct": _round(r.get("ours"), 3),
                   "book_pct": _round(r.get("fair_prob"), 3),
                   "ev_per_100": _round(r.get("ev"), 1)},
        lambda r: r.get("ours"))


def build(payload: dict) -> dict[str, dict]:
    """One brief per game on the board, keyed by game id."""
    cards = (payload.get("games") or {}).get("cards") or []
    return {c["game_id"]: for_game(payload, c) for c in cards}
