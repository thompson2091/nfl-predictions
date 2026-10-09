"""The over/under picks written down before kickoff, graded once played.

**THE OTHER HALF OF THE RECORD PAGE.** `season_scorecard` regrades every past
week with the model being served today, so its player numbers improve
whenever the model is refit and cannot say whether the model is getting
better. The picks in `tracked_picks.csv` were recorded before each game
started, at the price available then, by the model being served then — so
this is the number the weekly improvement loop reads, and the page shows it
beside the rebuilt one without ever pooling the two.

Two rules are graded: `model side` (the unblended model's side on every
priced line, the Record page's headline population) and `prop edge over
threshold` (the Gaps rule). Settled the way `prop_settlement` settles: the
side's own price, a player with no snap is void, a player who played with no
stat line is graded at zero, a push is no bet.

From week 5 of 2026, the first week the four over/under markets recorded.
"""
from __future__ import annotations

import statistics as st
from collections import defaultdict

import polars as pl

from src.evaluation.season_scorecard import (OU_MARKETS, _cluster_ci,
                                             _implied, _payout)

#: The rules graded here, in the order the page shows them, with the name a
#: reader knows them by.
RULES: tuple[tuple[str, str], ...] = (
    ("model side", "Our model"),
    ("prop edge over threshold", "Gaps"),
)

#: The stat each market settles against, in `weekly_stats`.
STAT = {"receptions": "receptions", "receiving_yards": "receiving_yards",
        "rushing_yards": "rushing_yards", "passing_yards": "passing_yards"}


def _actuals(season: int, week: int, market: str) -> dict:
    """Display name -> stat, leaving out a name two players share that week
    (see `week_history.ou_week` for why a wrong result is worse than none)."""
    from src.utils.paths import get_path

    try:
        ws = (pl.scan_parquet(get_path("raw") / "weekly_stats.parquet")
              .filter((pl.col("season") == season) & (pl.col("week") == week))
              .select(["player_display_name", STAT[market]]).collect())
    except Exception:                                            # noqa: BLE001
        return {}
    names = ws["player_display_name"].to_list()
    dupes = {n for n in names if names.count(n) > 1}
    return {n: v for n, v in zip(names, ws[STAT[market]].to_list())
            if n not in dupes}


def graded(season: int, picks: pl.DataFrame | None = None) -> tuple[list, int]:
    """Every settled forward pick as a dict, and how many are still pending.

    A pick is pending while its own game has no final — per game, not per
    week, so a Monday-night pick is not graded on the Sunday.
    """
    from src.evaluation.prop_settlement import _norm, participation
    from src.evaluation.tracked_rules import load, unfinished

    p = load() if picks is None else picks
    if p.is_empty():
        return [], 0
    want = {r for r, _ in RULES}
    mk = {m for m, _ in OU_MARKETS}
    p = p.filter((pl.col("season").cast(pl.Utf8) == str(season))
                 & pl.col("market").is_in(list(mk))
                 & pl.col("rule").is_in(list(want)))
    if p.is_empty():
        return [], 0
    played = participation(season)
    out, pending = [], 0
    by_wm: dict = defaultdict(list)
    for r in p.iter_rows(named=True):
        by_wm[(int(r["week"]), r["market"])].append(r)
    for (week, market), rows in sorted(by_wm.items()):
        open_ = unfinished(season, week)[1]
        acts = _actuals(season, week, market)
        names = _norm([r["player"] or "" for r in rows])
        for r, n in zip(rows, names):
            if (r.get("game") or "") in open_:
                pending += 1
                continue
            try:
                line, odds = float(r["line"]), float(r["odds"])
            except (TypeError, ValueError):
                continue
            side = r.get("side")
            away, _, home = (r.get("game") or "").partition(" @ ")
            gid = f"{season}_{week:02d}_{away}_{home}"
            got = acts.get(r["player"])
            snapped = (gid, n) in played or got is not None
            if not snapped:
                continue                                  # void
            got = 0.0 if got is None else float(got)
            if got == line or side not in ("over", "under"):
                continue                                  # push
            won = (got > line) == (side == "over")
            out.append({"week": week, "market": market, "rule": r["rule"],
                        "player": r["player"], "game_id": gid, "side": side,
                        "line": line, "odds": odds, "actual": got, "won": won,
                        "ret": _payout(odds) if won else -1.0,
                        "model": r.get("model"),
                        "recorded_at": r.get("recorded_at")})
    return out, pending


def _row(rows: list[dict]) -> dict:
    by_game = defaultdict(list)
    for r in rows:
        by_game[r["game_id"]].append(r["ret"])
    roi, lo, hi = _cluster_ci(by_game)
    return {"bets": len(rows),
            "hit": sum(1 for r in rows if r["won"]) / len(rows),
            "be": st.mean(_implied(r["odds"]) for r in rows),
            "roi": roi, "lo": lo, "hi": hi, "games": len(by_game)}


def block(season: int, picks: pl.DataFrame | None = None) -> dict:
    """The forward record, per rule, per market, and per week.

    `candidate` is the weekly loop's test: a market whose 95% range sits
    wholly above zero per $100. It is a flag for a reader, and nothing reads
    it to change a threshold — the model changes only at the season-end refit.
    """
    rows, pending = graded(season, picks)
    from src.evaluation.tracked_rules import load

    p = load() if picks is None else picks
    weeks = []
    if not p.is_empty():
        q = p.filter((pl.col("season").cast(pl.Utf8) == str(season))
                     & pl.col("rule").is_in([r for r, _ in RULES]))
        weeks = sorted({int(w) for w in q["week"].to_list()})
    out = {"weeks": weeks, "pending": pending, "rules": []}
    for rule, label in RULES:
        mine = [r for r in rows if r["rule"] == rule]
        markets = []
        for mk, ml in OU_MARKETS:
            got = [r for r in mine if r["market"] == mk]
            if got:
                m = _row(got)
                m.update(key=mk, label=ml,
                         candidate=m["games"] > 1 and m["lo"] > 0)
                markets.append(m)
        by_week = {}
        for w in sorted({r["week"] for r in mine}):
            by_week[str(w)] = _row([r for r in mine if r["week"] == w])
        out["rules"].append({"rule": rule, "label": label,
                             "markets": markets,
                             "all": _row(mine) if mine else None,
                             "by_week": by_week})
    return out
