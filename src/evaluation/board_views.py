"""The three filters the players board offers, asked about a PAST week.

Everyone, Shortlist, Fades and Streaks are tabs on the players board. Until
now none of them could be scored: the shortlist was applied to the live board
only, and the streak rule was evaluated in the page from whatever history the
payload happened to carry, so "how did the streak picks do in week 3" got
today's answer and changed as later weeks landed.

**WHAT EACH ONE IS, IN THE WORDS THE BOARD USES.**

  * **Shortlist** — the lines the fitted rule would take. `ou_shortlist`
    gates on book depth, then keeps a disagreement whose size falls in the
    band that market has historically come our way in, on either side.
  * **Fades** — the shortlist's UNDER picks. On a two-sided line a fade is
    not a separate population: it is the lines where our number says the
    posted over is too expensive, so `Fades` is a SUBSET of `Shortlist` and
    not a fourth disjoint group. The board says so and so does the card.
  * **Streaks** — four of the player's last five graded weeks one way,
    against the line he was quoted each week, in whichever direction is not
    that market's own norm. See `streaks`. Recent form, not an edge, and
    nothing here is filtered on price.

**THE SHORTLIST FLOORS ARE OUT OF SAMPLE ON 2026.** Every one of the four
artifacts records `val_season: 2024` and `held_out: [2025, 2026]`, so
applying them to a 2026 week is a genuine test and not a replay of the fit.
Checked rather than assumed — a rule fitted through the week it is scored on
would read as an edge and be an echo.

**WHAT THIS IS NOT.** It is still a rebuild. `ou_week` reconstructs the board
from the archived odds and today's model, so these are the picks the rule
WOULD have taken, not a record of picks anyone saw. The page says so for the
whole player section and this inherits it.
"""
from __future__ import annotations

#: The names the Record page shows, in board order. `all` carries no filter.
VIEWS: tuple[tuple[str, str], ...] = (
    ("all", "Everyone"), ("short", "Shortlist"), ("fade", "Fades"),
    ("streak", "Streaks"),
)


_OPENS: dict = {}


def week_opens(season: int, week: int) -> dict:
    """`<market>|<normalized name>` -> that week's opening line and price.

    The live board's own lookup (`47_export_site.opening_prices`), loaded
    the way `week_history.ou_board` loads that script, so a past week is
    measured against the same open the board measured it against.
    """
    if (season, week) not in _OPENS:
        import importlib.util
        from pathlib import Path

        spec = importlib.util.spec_from_file_location(
            "site_export", Path(__file__).resolve().parents[2]
            / "scripts/47_export_site.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _OPENS[(season, week)] = mod.opening_prices(season, week) or {}
    return _OPENS[(season, week)]


def shortlist_sides(board_rows: list[dict], market: str,
                    season: int | None = None, week: int | None = None) -> dict:
    """`{(player_name, line): side}` for the lines the fitted rule takes.

    `board_rows` are `week_history.ou_week` rows, whose names differ from the
    board's own — `model` is `model_only` and `book` is `fair_prob` — so they
    are mapped back before the rule sees them. Mapped rather than
    reimplemented: `apply_to_board` holds the book-depth gate and the fitted
    bands, and a local copy of either would be a second rule wearing the
    first one's name.

    **AND GIVEN THE WEEK'S OPEN.** The rule measures the gap to the opening
    price at the same line and drops a row with no open (2026-10-20). The
    live board attaches the open before the rule runs; `ou_week` rows carry
    none, so without `season` and `week` every past row was dropped and the
    Record's Shortlist and Fades were empty from deploy 20261020.v5 on.
    """
    from src.evaluation import ou_shortlist as ous

    art = ous.load(market)
    if art is None:
        return {}
    opens: dict = {}
    if season is not None and week is not None:
        from src.evaluation.prop_settlement import _norm

        got = week_opens(season, week)
        names = [r.get("player_name") or "" for r in board_rows]
        opens = {n: got.get(f"{market}|{k}") for n, k in zip(names, _norm(names))}
    mapped = []
    for r in board_rows:
        o = opens.get(r.get("player_name") or "") or {}
        mapped.append({"player_name": r.get("player_name"),
                       "point": r.get("line"),
                       "model_only": r.get("model"),
                       "fair_prob": r.get("book"),
                       "n_books": r.get("n_books"),
                       "open_point": o.get("point"),
                       "open_fair": o.get("fair")})
    got = ous.apply_to_board(mapped, art)
    return {(r["player_name"], r["point"]): r["side"]
            for r in (got.get("rows") or [])
            if r.get("player_name") is not None}


def streak_flags(season: int, weeks, names, markets) -> dict:
    """`{(week, market, player_name): "over" | "under"}`, as of each week.

    Keyed by the name the BOARD prints, because that is what the bet rows
    carry. `player_history.for_board` already owns that mapping — it
    normalises once, matches, and files the result back under the spelling it
    was given — so this does not invent a second normaliser. Doing so is how
    four edge bets went missing from the per-player tables earlier today.
    """
    from src.evaluation import player_history as PH
    from src.evaluation import streaks

    want = sorted({n for n in names if n})
    if not want:
        return {}
    full = PH.for_board(want, last=None)
    by_market: dict = {}
    for player, per in full.items():
        for mk, rows in per.items():
            by_market.setdefault(mk, {})[player] = rows
    return streaks.flags(by_market, season, sorted(set(weeks)),
                         markets=set(markets))


def tag(rows: list[dict], sides: dict, streak: dict, week: int,
        market: str) -> None:
    """Mark each row in place with the views it belongs to.

    `on_short` is the rule taking that line at all; `on_fade` is it taking
    the under. `streak` is the player's direction or None, and `streak_with`
    says whether it agrees with the side this bet actually took — the thing
    worth knowing, since a streak is not a side until something bets one.
    """
    for r in rows:
        side = sides.get((r.get("player_name"), r.get("line")))
        r["on_short"] = side is not None
        r["on_fade"] = side == "under"
        d = streak.get((week, market, r.get("player_name")))
        r["streak"] = d
        r["streak_with"] = None if d is None or not r.get("side") \
            else (d == r.get("side"))


def edge_picks(board_rows: list[dict], season: int, market: str) -> dict:
    """What the pre-registered price rule takes from a LIVE board.

    `{"threshold_pp": t, "picks": [{player_name, point, side, edge_pp,
    price}]}`, or an empty `picks` with the reason where the rule cannot run.

    **THE SELECTION IS DECIDED HERE AND NOT IN THE PAGE**, for the reason
    `streaks` gives at length: a rule evaluated in the browser is a second
    copy of it, and the board and the Record page would be free to disagree
    about which bets the rule took. `prop_edge.qualifying` is the function
    section 05 is scored with, so the filter shows exactly the bets the card
    reports a return on.

    **ONE LINE PER PLAYER-GAME, CHOSEN BEFORE THE GAP IS READ.** `qualifying`
    owns that too. It matters more on a live board than in the archive: week
    5 was carrying four rushing-yards lines for Jalon Daniels and five
    passing-yards lines for one quarterback, and a filter that kept whichever
    cleared would be shopping among them — the same inflation that once
    turned a +0.30% player edge into +6.89%.

    Rows arrive in the board's own names and are mapped to `ou_week`'s, the
    same adaptation `shortlist_sides` makes and for the same reason.
    """
    from src.evaluation.prop_edge import load_threshold, qualifying

    t = load_threshold(market)
    out: dict = {"threshold_pp": t, "picks": [], "note": ""}
    if t is None:
        out["note"] = f"no fitted threshold for {market}"
        return out
    mapped = []
    for r in board_rows:
        point = r.get("point") if r.get("point") is not None \
            else r.get("open_point")
        mapped.append({
            "player_name": r.get("player_name"), "game_id": r.get("game_id"),
            "line": point, "side": None,
            # `ours` is the blend, which is what the rule thresholds — see
            # `prop_edge`'s docstring on why the pre-blend number is the
            # wrong one to measure a disagreement with the price from.
            "ours": r.get("ours"), "model": r.get("model_only"),
            "book": r.get("fair_prob"), "odds": r.get("odds"),
            # No result on an unplayed week, which is the point of a forward
            # filter. `qualifying` grades `won` as None and still selects.
            "actual": None,
        })
    try:
        got = qualifying(season, market, mapped, threshold_pp=t)
    except Exception as e:                                       # noqa: BLE001
        out["note"] = f"could not price the sides: {str(e)[:120]}"
        return out
    out["picks"] = [{"player_name": r.get("player_name"),
                     "point": r.get("point"),
                     "side": r.get("side"),
                     "edge_pp": r.get("edge_pp"),
                     "price": r.get("price")}
                    for r in got if r.get("side")]
    return out
