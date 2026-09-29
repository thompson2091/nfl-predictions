"""The projection a game kicked off with, written down because it cannot be rebuilt.

**THE NUMBER ON A PLAYED GAME WAS NEVER THE NUMBER WE SHOWED.**

`_attach_model` calls `predict_week` at export time, so an archived week was
scored by whatever the model and the feature matrix happened to be on the day
somebody rebuilt the site — not by what the board said before kickoff. It
moved a lot. ATL at GB in week 3 of 2026 was rebuilt eighteen times after it
finished and its model spread ranged from -5.2 to +4.6, with the model win
probability between 33% and 68%, on a game that had already been played 14-35.

That is not leakage: the week's own result does not reach its own features,
and `test_a_frozen_projection_is_not_the_result_in_disguise` holds the line.
It is the feature matrix being rebuilt from current raw data, which moves the
inputs for rows that are months old. Either way a board that grades a call
against a number that changes after the fact is not grading a call.

**FROZEN AT KICKOFF, NOT DAILY.**

While a game is unplayed its projection SHOULD move: the line moves, the
injury report lands, another week of form arrives. So the entry is rewritten
on every build until the game has a final, and never again after. What
survives is one number per game — the last one that was still a forecast.

**AND IT LIVES IN GIT**, next to the model registry and the fitted blend
weight, for the reason given in `.gitignore`: what is not regenerable stays in
the repository. This is the only copy. Weeks 1 and 2 of 2026 have no entry
because nothing recorded one at the time, and nothing can now.
"""
from __future__ import annotations

import json
from pathlib import Path

#: What the board shows as OUR number, and everything derived from it. The
#: book's own figures — `spread`, `total`, `win_home`, `proj_home` — are not
#: here: they come from the odds archive, which is already fixed.
FIELDS: tuple[str, ...] = (
    "model_spread", "model_total", "model_home", "model_away",
    "model_win_home", "model_win_n", "blend",
)

ROOT = Path(__file__).resolve().parents[2] / "archive" / "projections"

_CACHE: dict[int, dict] = {}
_DIRTY: set[int] = set()


def path(season: int) -> Path:
    """One file per season, so a diff shows one season's worth of change."""
    return ROOT / f"{season}.json"


def load(season: int) -> dict:
    """`{week: {game_id: {field: value}}}`, empty when nothing is recorded."""
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
        # Sorted and indented, so a commit shows which game changed rather
        # than one reordered line.
        p.write_text(json.dumps(_CACHE[season], indent=1, sort_keys=True) + "\n")
        out.append(p)
    _DIRTY.clear()
    return out


def played(card: dict) -> bool:
    return card.get("final_home") is not None and card.get("final_away") is not None


def settle(cards: dict, season: int | None, week: int | None) -> tuple[int, int]:
    """Serve the frozen projection on a played game; record it on a live one.

    Returns `(served, recorded)`. A played game with nothing recorded keeps
    whatever was computed — the board is more useful with a late number than
    with none — and the count of those is the caller's to report.
    """
    if not (season and week) or not cards:
        return (0, 0)
    store = load(int(season))
    wk = store.setdefault(str(int(week)), {})
    served = recorded = 0
    for gid, c in cards.items():
        if played(c):
            kept = wk.get(gid)
            if kept:
                for f in FIELDS:
                    if f in kept:
                        c[f] = kept[f]
                served += 1
            continue
        snap = {f: c[f] for f in FIELDS if c.get(f) is not None}
        # Nothing to record is not the same as recording nothing: a card with
        # no model block would otherwise wipe the entry it already has.
        if snap and wk.get(gid) != snap:
            wk[gid] = snap
            _DIRTY.add(int(season))
            recorded += 1
    return (served, recorded)


def missing(cards: dict, season: int | None, week: int | None) -> list[str]:
    """Played games with no frozen projection, which are showing a late one."""
    if not (season and week):
        return []
    wk = load(int(season)).get(str(int(week)), {})
    return sorted(gid for gid, c in cards.items()
                  if played(c) and gid not in wk
                  and c.get("model_win_home") is not None)
