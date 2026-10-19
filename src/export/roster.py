"""Each game's depth chart, slot by slot, with what the model projects for it.

QB1, RB1-3, WR1-5 and TE1-2 for both teams. The PLAYERS come from the ESPN
depth chart; the ORDER inside a position comes from our own projections,
because ESPN ranks receivers within formation slots — San Francisco's chart
lists Aiyuk at rank 10 and Cooks at 3 — so its numbering is not an order.
A team that is not that deep gets an empty slot rather than a shorter list,
so the same row means the same position on every card.

Every join is on player_id. The board's rows carry names as the book spells
them, and a name join is what once graded Kenneth Gainwell against nothing.

The depth chart is read as of each game's kickoff: a game already played
keeps the chart it was played under, not the one ESPN published afterward.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import polars as pl

from src.utils.paths import get_path

#: Slot groups in display order: position, slots shown, and the projection
#: that orders the group. QB keeps the depth chart's order — a backup's
#: projection is a function of the starter's, not a ranking of the two.
SLOTS = [("QB", 1, None), ("RB", 3, "rush_yds"),
         ("WR", 5, "rec_yds"), ("TE", 2, "rec_yds")]

#: Projection key to the yardage board it is read from.
_YARDS = {"pass_yds": "passing_yards", "rush_yds": "rushing_yards",
          "rec_yds": "receiving_yards"}

ET = ZoneInfo("America/New_York")

#: Injury designations that move a player below the active ones. The same
#: pair `availability` treats as not playing.
BLOCKING = ("Out", "Doubtful")


def charts(kicks: dict[str, datetime]) -> dict[str, pl.DataFrame]:
    """The depth chart each game was (or will be) played under, by game_id.

    The newest snapshot at or before kickoff. A game with no earlier snapshot
    gets none rather than a later one.
    """
    path = get_path("raw") / "depth_charts_new.parquet"
    if not path.exists() or not kicks:
        return {}
    d = (pl.read_parquet(path)
         .filter(pl.col("gsis_id").is_not_null()
                 & pl.col("pos_abb").is_in([s[0] for s in SLOTS])))
    if d.height == 0:
        return {}
    snaps = sorted(d["dt"].unique().to_list())
    out = {}
    for gid, kick in kicks.items():
        k = kick.replace(tzinfo=ET).astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        before = [s for s in snaps if s <= k]
        if before:
            out[gid] = d.filter(pl.col("dt") == before[-1])
    return out


def feature_ids(season: int, week: int) -> dict[tuple, str]:
    """(team, player_name) to player_id, from the week's feature matrix.

    The touchdown boards are served from frozen CSVs that carry no id, but
    their names are the feature matrix's own, so this is the same spelling
    on both sides. A pair two ids share is left out.
    """
    try:
        f = (pl.scan_parquet(get_path("processed", "anytime_td") / "features.parquet")
             .filter((pl.col("season") == season) & (pl.col("week") == week))
             .select(["team", "player_name", "player_id"]).unique().collect())
    except Exception:                                            # noqa: BLE001
        return {}
    g = f.group_by(["team", "player_name"]).agg(
        pl.col("player_id").n_unique().alias("n"), pl.col("player_id").first())
    return {(r["team"], r["player_name"]): r["player_id"]
            for r in g.filter(pl.col("n") == 1).iter_rows(named=True)}


def projections(payload: dict, ids: dict | None = None) -> dict[str, dict]:
    """Every projection on the payload, keyed by player_id.

    Per market: the projection, and where a book has priced it, the line,
    the price and the board's three estimates — `_model` (the model with no
    sight of the price), `_book` (the de-vigged price) and `_adj` (the
    blend). The same three, under the same names, the Props board shows.

    A yardage board carries a row per (player, line); only the one
    `_mark_consensus_lines` flagged is used, so this tab and Props quote the
    same line. A touchdown row without an id is resolved through `ids`; any
    other row without one is skipped rather than matched by name.
    """
    out: dict[str, dict] = {}
    ids = ids or {}

    def num(v, d=3):
        return round(float(v), d) if v is not None else None

    def put(pid, key, val, r=None, line=None, book=None):
        if not pid:
            return
        p = out.setdefault(pid, {})
        if val is not None:
            p[key] = num(val)
        if r is None:
            return
        got = {"_line": line, "_odds": r.get("odds_num", r.get("odds")),
               "_model": r.get("model_only"), "_book": book,
               "_adj": r.get("ours")}
        for suf, v in got.items():
            if isinstance(v, (int, float)):
                p[key + suf] = num(v, 4)

    def ou(rows, key, val_col):
        for r in rows or []:
            line = r.get("point") if r.get("point") is not None else r.get("open_point")
            # One line per player: the consensus where there are several.
            priced = line is not None and r.get("best_line") is not False
            put(r.get("player_id"), key, r.get(val_col),
                r if priced else None, line, r.get("fair_prob"))

    for key, mk in _YARDS.items():
        ou(((payload.get("yards") or {}).get(mk) or {}).get("rows"), key, "proj")
    ou((payload.get("receptions") or {}).get("rows"), "rec", "mu")
    for m in payload.get("markets") or []:
        key = {"anytime_td": "td", "first_td": "ftd"}.get(m.get("key"))
        if not key:
            continue
        for r in m.get("players") or []:
            pid = r.get("player_id") or ids.get((r.get("team"), r.get("player")))
            put(pid, key, r.get("ours"), r, None, r.get("book"))
    return out


def _status(season: int, week: int) -> dict[str, str]:
    try:
        from src.prediction.availability import status_for
        d = status_for(season, week)
    except Exception:                                            # noqa: BLE001
        return {}
    if d is None or d.height == 0:
        return {}
    pid = "player_id" if "player_id" in d.columns else "gsis_id"
    return {a: b for a, b in d.select([pid, "report_status"]).iter_rows()
            if a and b}


def team_slots(chart: pl.DataFrame, team: str, proj: dict,
               status: dict) -> list[dict]:
    """One team's slots, in display order, with None for an empty one."""
    d = (chart.filter(pl.col("team") == team)
         .group_by(["gsis_id", "pos_abb"])
         .agg(pl.col("player_name").first(), pl.col("pos_rank").min()))
    out = []
    for pos, n, by in SLOTS:
        g = d.filter(pl.col("pos_abb") == pos).to_dicts()
        # Projected players first, by their projection; the rest after, in
        # the chart's order. Out and Doubtful go below everyone who is
        # expected to play: the model still projects them, and on 2026 week
        # 6 an Out back was ranked RB1.
        g.sort(key=lambda r: (
            status.get(r["gsis_id"]) in BLOCKING,
            by is None or proj.get(r["gsis_id"], {}).get(by) is None,
            -(proj.get(r["gsis_id"], {}).get(by) or 0) if by else 0,
            r["pos_rank"]))
        # The numbered slots are who is expected to play. Out and Doubtful
        # players follow the group, unnumbered and marked, rather than
        # falling off the end of it: on 2026 week 6 that hid two starters.
        live = [r for r in g if status.get(r["gsis_id"]) not in BLOCKING]
        held = [r for r in g if status.get(r["gsis_id"]) in BLOCKING]

        def row(slot, r):
            x = {"slot": slot, "pos": pos}
            if r:
                x.update({"player": r["player_name"],
                          "player_id": r["gsis_id"],
                          "status": status.get(r["gsis_id"]),
                          **proj.get(r["gsis_id"], {})})
            return x

        for i in range(n):
            out.append(row(f"{pos}{i + 1}", live[i] if i < len(live) else None))
        out.extend(row(pos, r) for r in held)
    return out


def build(payload: dict, season: int | None, week: int | None) -> dict:
    """{game_id: {team: [slot, ...]}} for every card on this week's board."""
    if not season or not week:
        return {}
    from src.evaluation.tracked_rules import kickoffs

    cards = (payload.get("games") or {}).get("cards") or []
    if not cards:
        return {}
    chart = charts(kickoffs(season, week))
    if not chart:
        return {}
    proj = projections(payload, feature_ids(season, week))
    status = _status(season, week)
    out = {}
    for c in cards:
        # Cards are keyed "AWAY_HOME"; the schedule's id carries the week.
        gid = c.get("game_id") or ""
        ch = chart.get(gid) or chart.get(f"{season}_{int(week):02d}_{gid}")
        if ch is None:
            continue
        out[c["game_id"]] = {t: team_slots(ch, t, proj, status)
                             for t in (c.get("away"), c.get("home")) if t}
    return out
