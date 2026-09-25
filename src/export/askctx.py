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

#: How many priced players per market travel with the brief. Twenty covers
#: "who is worth backing" and "is my guy on here" without carrying a board.
TOP_PLAYERS = 20

#: Markets worth including, board key to a human name.
MARKETS = [("any", "anytime touchdown"), ("first", "first touchdown"),
           ("recyds", "receiving yards"), ("rush", "rushing yards"),
           ("passyds", "passing yards"), ("rec", "receptions")]


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
        out["matchup_edges"] = {
            "games_played": mk.get("games"),
            "full_game": [
                {"metric": r["label"],
                 "sides": [f"{p['offense']} offence {p['off_val']} vs "
                           f"{p['defense']} defence {p['def_val']} "
                           f"(edge {p['edge']:+})" for p in r["sides"]]}
                for r in (mk.get("rows") or [])],
            "not_available": [x["what"] for x in (mk.get("missing") or [])],
        }
    if card.get("coach_home") or card.get("coach_away"):
        out["coaches"] = {card.get("home"): card.get("coach_home"),
                          card.get("away"): card.get("coach_away")}

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


def _players(payload: dict, key: str, gid: str) -> list:
    """The best-priced rows for one market in one game."""
    if key in ("any", "first"):
        want = "anytime_td" if key == "any" else "first_td"
        mk = next((m for m in payload.get("markets") or []
                   if m.get("key") == want), None)
        rows = [p for p in ((mk or {}).get("players") or [])
                if _game_key(p.get("game_id") or "") == gid and p.get("priced")]
        rows.sort(key=lambda p: -(p.get("ev") or -1e9))
        return [{"player": p["player"], "odds": p.get("odds_num"),
                 "our_pct": _round((p.get("model_only") or p.get("ours")), 3),
                 "book_pct": _round(p.get("book"), 3),
                 "ev_per_100": _round(p.get("ev"), 1)}
                for p in rows[:TOP_PLAYERS]]
    stat = {"recyds": "receiving_yards", "rush": "rushing_yards",
            "passyds": "passing_yards", "rec": "receptions"}[key]
    ym = (payload.get("yards") or {}).get(stat) or {}
    rows = [r for r in (ym.get("rows") or [])
            if _game_key(r.get("game_id") or "") == gid
            and r.get("point") is not None]
    rows.sort(key=lambda r: -(r.get("ev") or -1e9))
    return [{"player": r["player_name"], "line": r.get("point"),
             "odds": r.get("odds"), "we_project": _round(r.get("proj"), 1),
             "our_pct": _round(r.get("ours"), 3),
             "book_pct": _round(r.get("fair_prob"), 3),
             "ev_per_100": _round(r.get("ev"), 1)}
            for r in rows[:TOP_PLAYERS]]


def build(payload: dict) -> dict[str, dict]:
    """One brief per game on the board, keyed by game id."""
    cards = (payload.get("games") or {}).get("cards") or []
    return {c["game_id"]: for_game(payload, c) for c in cards}
