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


def shortlist_sides(board_rows: list[dict], market: str) -> dict:
    """`{(player_name, line): side}` for the lines the fitted rule takes.

    `board_rows` are `week_history.ou_week` rows, whose names differ from the
    board's own — `model` is `model_only` and `book` is `fair_prob` — so they
    are mapped back before the rule sees them. Mapped rather than
    reimplemented: `apply_to_board` holds the book-depth gate and the fitted
    bands, and a local copy of either would be a second rule wearing the
    first one's name.
    """
    from src.evaluation import ou_shortlist as ous

    art = ous.load(market)
    if art is None:
        return {}
    mapped = [{"player_name": r.get("player_name"),
               "point": r.get("line"),
               "model_only": r.get("model"),
               "fair_prob": r.get("book"),
               "n_books": r.get("n_books")}
              for r in board_rows]
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
