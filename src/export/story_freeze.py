"""The story a game kicked off with, written down because it cannot be rebuilt.

**A PREVIEW OF A GAME THAT HAS ALREADY HAPPENED IS NOT A PREVIEW.** `game_story`
runs at export time from the facts on the day of the build, so without this a
Sunday-night rebuild would write fifteen fresh previews of fifteen finished
games — in the future tense, about results everybody already knows, from an
injury report and a public split that have both moved on. The text would be
new, fluent, checked, and absurd.

`projection_freeze` makes the identical argument one level down and this is
that argument applied to the words: while a game is unplayed its story SHOULD
be rewritten, because the line moves and the injury report lands; once it has
a final the story is what it was and is never written again.

**AND IT LIVES IN GIT**, for the reason `projection_freeze` gives: what is not
regenerable stays in the repository. A projection can at least be recomputed
from a frozen feature matrix. A paragraph cannot be recomputed at all — the
same facts through the same prompt come back worded differently — so this file
is the only copy there will ever be.

**IT ALSO STOPS THE BILL.** Phrasing is skipped entirely for a played game, so
the Sunday-night rebuild that used to cost sixteen calls costs one.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "archive" / "stories"

_CACHE: dict[int, dict] = {}
_DIRTY: set[int] = set()


def path(season: int) -> Path:
    """One file per season, so a diff shows one season's worth of change."""
    return ROOT / f"{season}.json"


def load(season: int) -> dict:
    """`{week: {game_id: story}}`, empty when nothing is recorded."""
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


def played(card: dict) -> bool:
    """The same test `projection_freeze` uses, so the two cannot disagree
    about which games are over."""
    return (card.get("final_home") is not None
            and card.get("final_away") is not None)


def started(card: dict, now=None) -> bool:
    """Whether this game is past the point where a preview is still a preview.

    **A FINAL IS TOO LATE.** `played` asks whether a result has landed, and
    the schedule only carries one once the game is over — so between kickoff
    and the whistle a rebuild would write a fresh "preview" of a game being
    played, and overwrite the frozen one with it. On a Sunday with a rebuild
    at 14:00 that is every early game.

    So the line is KICKOFF, which is what `projection_freeze` says in words
    and what this says in code. `kick_sort` is the card's own sortable
    timestamp and it is in the stadium's Eastern clock, which is also what
    this machine and every launchd slot in the project run on; a build from
    another zone would freeze early or late by the offset, and that is worth
    one comparison rather than a timezone database.
    """
    if played(card):
        return True
    when = str(card.get("kick_sort") or "").strip()
    if len(when) < 16:
        # No kickoff to compare against: fall back to the result, which is
        # the old behavior and never freezes a game that has not happened.
        return False
    from datetime import datetime

    try:
        kick = datetime.strptime(when[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return False
    return (now or datetime.now()) >= kick


def frozen(gid: str, season: int | None, week: int | None) -> dict | None:
    """What was written before this game kicked off, if anything was."""
    if not (season and week):
        return None
    return (load(int(season)).get(str(int(week))) or {}).get(gid)


def record(gid: str, story: dict, season: int | None, week: int | None) -> bool:
    """Keep this story as the one that was live. True when it changed anything.

    Only the parts a reader sees. The brief is the model's input and is not
    kept: it is three times the length of the story and nothing reads it back.
    """
    if not (season and week) or not story or not story.get("paras"):
        return False
    keep = {k: story[k] for k in ("paras", "scoreline", "written")
            if k in story}
    store = load(int(season))
    wk = store.setdefault(str(int(week)), {})
    if wk.get(gid) == keep:
        return False
    wk[gid] = keep
    _DIRTY.add(int(season))
    return True


def missing(cards: list, season: int | None, week: int | None) -> list[str]:
    """Played games with no frozen story, which will therefore show none.

    Said out loud by the caller rather than left silent: a game whose story
    vanished when it kicked off looks exactly like a game the writer skipped.
    """
    if not (season and week):
        return []
    wk = load(int(season)).get(str(int(week)), {})
    return sorted(c.get("game_id") for c in cards
                  if played(c) and c.get("game_id") not in wk)
