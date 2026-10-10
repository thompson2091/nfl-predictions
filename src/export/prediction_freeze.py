"""The player board a game kicked off with, because nothing else keeps it.

**THE THIRD FREEZE, AND THE ONE THAT WAS MISSING.**
`projection_freeze` keeps a game's numbers and `story_freeze` keeps its
words. Nothing kept the players, and the players are the product: one
unconditional writer at `predict.py:753` puts the week's board in
`output/<market>/predictions_<season>_week<week>.csv`, and every later run
overwrites it.

**WHAT THAT COST.** `has_market_price` is a PREDICT-TIME artifact — it records
whether a book had posted a price at the moment the board was built. Rebuild
the board after the games and the live odds cache no longer carries prices
for a finished week, so the flag comes back false for almost everybody. Week
4 of 2026 was rewritten at 00:14 on the Monday, after every Sunday game, by
the HTML export calling `app.load_board` with `persist=True`. The board went
from a full slate to **47 priced players of 515**; week 3 to **24 of 498**.
Both weeks are still that way on disk, and nothing regenerates them, because
the thing that was lost is what a bookmaker was offering on a Sunday morning.

**KEYED PER GAME, GATED ON KICKOFF.** Per week would freeze Sunday's fifteen
games when the Thursday game kicked off and leave Monday's frozen two days
early. On a final it would not freeze at all until the next morning's
rollover, which is the bug `projection_freeze` was carrying — see its
docstring. So each game freezes alone, the moment it starts.

**THE PRICE IS KEPT, NOT JUST THE FLAG.** `odds` is what the book offered and
`book` is that de-vigged — and `book` is re-derived today from a population
that keeps growing, so a favorite's "fair" number has been watched drifting
41% to 49% as the field around it filled in. A probability compared against a
number that moves after the fact is not a comparison.

**AND IT LIVES IN GIT**, for the reason the other two give: what is not
regenerable stays in the repository. About 48 KB a week a market.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

from src.export.projection_freeze import started as _started_card  # noqa: F401

ROOT = Path(__file__).resolve().parents[2] / "archive" / "predictions"

#: One row of a frozen board. `player_name` and `team` are the join key the
#: rest of the project grades on; the rest is what the board showed.
FIELDS: tuple[str, ...] = (
    "player_name", "team", "probability", "prob_model", "rank",
    "has_market_price", "odds", "book", "source", "version",
)

#: The four over/under markets, which had no freeze at all until 2026-10-09.
#: Their board is rebuilt from the archived odds and TODAY's model every time
#: anything asks (`week_history.ou_week`), so the Record page graded weeks 1-4
#: on a model those weeks never saw. A row here is one line as it stood before
#: kickoff: both sides' prices, the model before and after the blend, and the
#: side each rule took — so a forward record can be graded later without
#: asking any of today's code what it would have said.
OU_MARKETS: tuple[str, ...] = ("receptions", "receiving_yards",
                               "rushing_yards", "passing_yards")
OU_FIELDS: tuple[str, ...] = (
    "player_name", "team", "point", "proj", "lo", "hi",
    "model_only", "ours", "fair_prob", "n_books",
    "price_over", "price_under",
    "model_side", "gap_side", "gap_edge_pp", "gap_threshold_pp",
    # Set only on a board recovered from an old deploy: which build, so the
    # recovery can be checked against the file it came from.
    "source",
    # The model that scored the board (`run_manifest.served_version`), so a
    # promotion starts a new population on the forward record instead of
    # being averaged into the old one. Absent on recovered boards.
    "version",
)


def fields_for(market: str) -> tuple[str, ...]:
    return OU_FIELDS if market in OU_MARKETS else FIELDS


def _order(r: dict) -> tuple:
    """Board order: most likely first on a touchdown market, and on an
    over/under the line itself, so a diff of one player's alternates reads
    top to bottom."""
    if r.get("probability") is not None:
        return (-(r.get("probability") or 0), r.get("player_name") or "", 0.0)
    return (0, r.get("player_name") or "", float(r.get("point") or 0.0))

_CACHE: dict[int, dict] = {}
_DIRTY: set[int] = set()


def path(season: int) -> Path:
    """One file per season, so a diff shows one season's worth of change."""
    return ROOT / f"{season}.json"


def load(season: int) -> dict:
    """`{week: {market: {game_id: [row, ...]}}}`, empty when nothing is kept."""
    if season in _CACHE:
        return _CACHE[season]
    p = path(season)
    try:
        _CACHE[season] = json.loads(p.read_text()) if p.exists() else {}
    except Exception:                                            # noqa: BLE001
        # A corrupt file must not take the export down with it: the board is
        # the product and this is a fidelity improvement on part of it.
        _CACHE[season] = {}
    return _CACHE[season]


def flush() -> list[Path]:
    """Write every season touched since the last flush."""
    out = []
    for season in sorted(_DIRTY):
        p = path(season)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(_CACHE[season], indent=1, sort_keys=True) + "\n")
        out.append(p)
    _DIRTY.clear()
    return out


def started_games(season: int, week: int, now: datetime | None = None) -> set:
    """Which games of this week have kicked off.

    The same rule `projection_freeze.started` applies to a card, asked of a
    `game_id` instead: kickoff, on the Eastern clock, read from the one
    schedule reader in `tracked_rules.kickoffs`. A game whose kickoff cannot
    be read counts as not started, so nothing is frozen on a guess.
    """
    from src.evaluation.tracked_rules import kickoffs

    at = now or datetime.now()
    return {gid for gid, kick in kickoffs(season, week).items() if at >= kick}


def frozen(season: int, week: int, market: str) -> dict:
    """`{game_id: [row, ...]}` for everything kept on this week's board."""
    return ((load(int(season)).get(str(int(week))) or {}).get(market) or {})


def record(rows: list[dict], season: int, week: int, market: str,
           now: datetime | None = None) -> int:
    """Keep the board as it stands for every game still to kick off.

    Returns how many games were written. Rows are grouped by `game_id`, so a
    game freezes the moment it starts and the rest of the slate keeps moving.
    """
    if not (season and week) or not rows:
        return 0
    by_game: dict = {}
    keep = fields_for(market)
    try:
        from src.export.run_manifest import served_version

        ver = served_version(market)
    except Exception:                                            # noqa: BLE001
        ver = None
    for r in rows:
        gid = r.get("game_id")
        if gid:
            row = {f: r.get(f) for f in keep if r.get(f) is not None}
            if ver and "version" not in row:
                row["version"] = ver
            by_game.setdefault(gid, []).append(row)
    live = started_games(season, week, now)
    store = load(int(season))
    # NOT `setdefault` UNTIL THERE IS SOMETHING TO PUT IN IT. A week where
    # every game has already kicked off would otherwise leave an empty
    # `{"3": {"anytime_td": {}}}` behind, which reads in a diff as a week
    # somebody froze and got nothing from.
    wk = (store.get(str(int(week))) or {}).get(market) or {}
    wrote = 0
    for gid, got in by_game.items():
        if gid in live:
            continue                      # already begun: this is not a board
        got = sorted(got, key=_order)
        if wk.get(gid) != got:
            if not wrote:
                wk = store.setdefault(str(int(week)), {}).setdefault(
                    market, wk)
            wk[gid] = got
            _DIRTY.add(int(season))
            wrote += 1
    return wrote


def recover(rows: list[dict], season: int, week: int, market: str,
            source: str) -> int:
    """Keep a board recovered from a build deployed before kickoff.

    `scripts/68_recover_boards.py` is the only caller. It has already checked
    that `source` was built before each game's kickoff, so this does not ask
    the clock — but it never replaces a board the freeze already holds,
    because that one was recorded live. Returns how many games were written.
    """
    if not (season and week) or not rows:
        return 0
    keep = fields_for(market)
    by_game: dict = {}
    for r in rows:
        gid = r.get("game_id")
        if gid:
            row = {f: r.get(f) for f in keep if r.get(f) is not None}
            row["source"] = source
            by_game.setdefault(gid, []).append(row)
    store = load(int(season))
    have = (store.get(str(int(week))) or {}).get(market) or {}
    wrote = 0
    for gid, got in by_game.items():
        if gid in have:
            continue
        store.setdefault(str(int(week)), {}).setdefault(market, {})[gid] = \
            sorted(got, key=_order)
        _DIRTY.add(int(season))
        wrote += 1
    return wrote


def missing(season: int, week: int, market: str,
            now: datetime | None = None) -> list[str]:
    """Started games with no frozen board, which are showing a rebuilt one.

    Said out loud by the caller, because the fallback is invisible on the
    page: a week nobody froze looks exactly like a week nobody priced.
    """
    kept = frozen(season, week, market)
    return sorted(gid for gid in started_games(season, week, now)
                  if gid not in kept)


def settle(rows: list[dict], season: int, week: int, market: str,
           now: datetime | None = None) -> tuple[list[dict], int, int]:
    """Serve the frozen board on a started game; record it on one still to come.

    Returns `(rows, served, recorded)`. A started game with nothing frozen
    keeps whatever was rebuilt — a late board beats no board — and the count
    of those is `missing`, which the caller reports.
    """
    if not (season and week) or not rows:
        return (list(rows or []), 0, 0)
    recorded = record(rows, season, week, market, now)
    kept = frozen(season, week, market)
    live = started_games(season, week, now)
    out, served, replaced = [], 0, set()
    for r in rows:
        gid = r.get("game_id")
        if gid in live and gid in kept:
            if gid not in replaced:
                replaced.add(gid)
                served += 1
                for k in kept[gid]:
                    # DEEP COPY on the way out, so an in-place edit downstream
                    # cannot write back through into `_CACHE` and from there
                    # onto disk. `projection_freeze` learned this one.
                    row = copy.deepcopy(k)
                    row["game_id"] = gid
                    out.append(row)
            continue
        out.append(r)
    return (out, served, recorded)
