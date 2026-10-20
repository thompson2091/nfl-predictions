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
            val = r.get(val_col)
            if val is None and key == "rec":
                val = r.get("mu")       # a board built before the median
            put(r.get("player_id"), key, val,
                r if priced else None, line, r.get("fair_prob"))

    for key, mk in _YARDS.items():
        ou(((payload.get("yards") or {}).get(mk) or {}).get("rows"), key, "proj")
    # The median, as Props now shows it for catches.
    ou((payload.get("receptions") or {}).get("rows"), "rec", "proj")
    for m in payload.get("markets") or []:
        key = {"anytime_td": "td", "first_td": "ftd"}.get(m.get("key"))
        if not key:
            continue
        for r in m.get("players") or []:
            pid = r.get("player_id") or ids.get((r.get("team"), r.get("player")))
            put(pid, key, r.get("ours"), r, None, r.get("book"))
    return out


def averages(season: int, week: int) -> dict[str, dict]:
    """Each player's AVERAGE passing and receiving yards, by player_id.

    Not shown per player — the player figures stay the medians Props shows,
    which is what a line is compared with. These exist for the team line:
    medians of skewed yardage add to far less than the total, so a column of
    receiver medians under a quarterback's median looks fifty yards short
    when it is not. Averages add.
    """
    from src.models.yards import mean_of
    from src.prediction.yards import expected_quantiles

    out: dict[str, dict] = {}
    for key, mk in (("pass_avg", "passing_yards"), ("rec_avg", "receiving_yards")):
        try:
            got = expected_quantiles(mk, season, week)
        except Exception:                                        # noqa: BLE001
            got = None
        if got is None:
            continue
        ids, q = got
        for pid, m in zip(ids["player_id"].to_list(), mean_of(q).tolist()):
            if pid:
                out.setdefault(pid, {})[key] = m
    return out


def team_line(slots: list[dict], avg: dict) -> dict | None:
    """The receivers shown, added as averages, beside their QB1's average."""
    live = [s for s in slots if s.get("player_id") and any(ch.isdigit() for ch in s["slot"])]
    qb = next((s for s in live if s["pos"] == "QB"), None)
    rec = [avg.get(s["player_id"], {}).get("rec_avg") for s in live if s["pos"] != "QB"]
    rec = [r for r in rec if r is not None]
    pas = avg.get(qb["player_id"], {}).get("pass_avg") if qb else None
    if not rec or pas is None:
        return None
    return {"rec_avg": round(sum(rec), 1), "pass_avg": round(pas, 1),
            "n": len(rec), "qb": qb["player"]}


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
    avg = averages(season, week)
    try:
        from src.models.score_dist import history
        from src.models.scenarios import fit as scen_fit
        from src.models.scenarios import for_card as scen_card
        sfits, shist = scen_fit(), history()
    except Exception:                                            # noqa: BLE001
        sfits = shist = None
    out = {}
    for c in cards:
        # Cards are keyed "AWAY_HOME"; the schedule's id carries the week.
        gid = c.get("game_id") or ""
        ch = chart.get(gid) or chart.get(f"{season}_{int(week):02d}_{gid}")
        if ch is None:
            continue
        teams = {t: team_slots(ch, t, proj, status)
                 for t in (c.get("away"), c.get("home")) if t}
        # Under `_totals`, a key no team code can be.
        lines = {t: team_line(v, avg) for t, v in teams.items()}
        teams["_totals"] = {t: v for t, v in lines.items() if v}
        # How the game might go, for the scenario picker. See
        # `src/models/scenarios.py`; absent rather than flat when the
        # comparable games are too few.
        sc = scen_card(c, sfits, shist) if sfits else None
        if sc:
            teams["_scen"] = sc
        out[c["game_id"]] = teams
    return out


#: Over/under market -> (projection key, the game-log stat that settles it).
_OU = {"passing_yards": ("pass_yds", "passing_yards"),
       "rushing_yards": ("rush_yds", "rushing_yards"),
       "receiving_yards": ("rec_yds", "receiving_yards"),
       "receptions": ("rec", "receptions")}


def frozen_projections(season: int, week: int) -> dict[str, dict]:
    """A played week's projections, from what was frozen BEFORE kickoff.

    Never recomputed: a past week shows what the board said going in, from
    `prediction_freeze`, so the grade below is of a forecast and not of a
    number rebuilt afterwards. One line per player per market, chosen the way
    the forward record chooses it — nearest his median line, a tie to the
    lower — and the model's side on it.
    """
    import statistics

    from src.export import prediction_freeze as PF

    ids = feature_ids(season, week)
    out: dict[str, dict] = {}

    def pid_of(r):
        return r.get("player_id") or ids.get((r.get("team"), r.get("player_name")))

    for market, (key, _stat) in _OU.items():
        per: dict = {}
        for rows in PF.frozen(season, week, market).values():
            for r in rows:
                pid = pid_of(r)
                if pid and r.get("point") is not None:
                    per.setdefault(pid, []).append(r)
        for pid, rs in per.items():
            med = statistics.median(x["point"] for x in rs)
            r = min(rs, key=lambda x: (abs(x["point"] - med), x["point"]))
            p = out.setdefault(pid, {})
            p[key] = r.get("proj")
            p[key + "_line"] = r["point"]
            for suf, col in (("_model", "model_only"), ("_book", "fair_prob"),
                             ("_adj", "ours")):
                if r.get(col) is not None:
                    p[key + suf] = r[col]
            side = r.get("model_side") or (
                None if r.get("model_only") is None
                else ("over" if r["model_only"] >= 0.5 else "under"))
            p[key + "_side"] = side
            price = r.get("price_over") if side == "over" else r.get("price_under")
            if price is not None:
                p[key + "_odds"] = price
    for market, key in (("anytime_td", "td"), ("first_td", "ftd")):
        for rows in PF.frozen(season, week, market).values():
            for r in rows:
                pid = pid_of(r)
                if not pid:
                    continue
                p = out.setdefault(pid, {})
                p[key] = r.get("probability")
                for suf, col in (("_model", "prob_model"), ("_book", "book"),
                                 ("_odds", "odds"), ("_adj", "probability")):
                    if r.get(col) is not None:
                        p[key + suf] = r[col]
    return out


def actuals(season: int, week: int) -> dict[str, dict]:
    """What each player did, by id: the four stats, and whether he scored.

    Absent for a player with no snap and no stat line — a void at the book,
    so nothing on his row is graded.
    """
    from src.evaluation.safe_legs import game_logs

    out: dict[str, dict] = {}
    logs = game_logs().filter((pl.col("season") == season) & (pl.col("week") == week))
    for r in logs.iter_rows(named=True):
        out[r["player_id"]] = {key: r.get(stat) for key, stat in _OU.values()}
    for key, target in (("td", "anytime_td"), ("ftd", "first_td")):
        path = get_path("processed", target) / f"tds_{target}.parquet"
        if not path.exists():
            continue
        sc = set(pl.scan_parquet(path)
                 .filter((pl.col("season") == season) & (pl.col("week") == week))
                 .select("td_player_id").collect()["td_player_id"].drop_nulls().to_list())
        for pid, a in out.items():
            a[key] = 1 if pid in sc else 0
    return out


def grade(proj: dict, got: dict | None) -> dict:
    """The projection with what happened beside it, and right or wrong.

    A line is graded on the model's own side of it, as the Record grades the
    unblended model; a touchdown chance is graded as scored or not. A tie
    with the line is a push and graded neither way.
    """
    p = dict(proj)
    if not got:
        p["void"] = True
        return p
    for key, _stat in _OU.values():
        a = got.get(key)
        if a is None:
            continue
        p[key + "_actual"] = a
        line, side = p.get(key + "_line"), p.get(key + "_side")
        if line is not None and side and a != line:
            p[key + "_right"] = (a > line) == (side == "over")
    for key in ("td", "ftd"):
        if got.get(key) is not None and p.get(key) is not None:
            p[key + "_actual"] = got[key]
    return p


def build_past(season: int, week: int, cards: list[dict]) -> dict:
    """A played week's roster: the frozen board, graded against the result."""
    from src.evaluation.tracked_rules import kickoffs

    if not cards:
        return {}
    chart = charts(kickoffs(season, week))
    if not chart:
        return {}
    proj = frozen_projections(season, week)
    got = actuals(season, week)
    graded = {pid: grade(p, got.get(pid)) for pid, p in proj.items()}
    status = _status(season, week)
    out = {}
    for c in cards:
        gid = c.get("game_id") or ""
        ch = chart.get(gid) or chart.get(f"{season}_{int(week):02d}_{gid}")
        if ch is None:
            continue
        out[gid] = {t: team_slots(ch, t, graded, status)
                    for t in (c.get("away"), c.get("home")) if t}
    return out
