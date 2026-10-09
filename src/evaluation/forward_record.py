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

Read off the frozen boards: recorded live from week 5 of 2026, and for weeks
2-4 recovered from the page deployed before each kickoff
(`scripts/68_recover_boards.py`). Week 1 had no over/under boards on the site.
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


def _picks_from_boards(season: int) -> list[dict]:
    """Both rules' picks, read off the boards frozen before kickoff.

    One line per player-game — the one nearest his median line, ties to the
    lower, which is `prop_edge.main_lines` — chosen before any side is read.
    `model side` takes the unblended model's side at that side's price on
    every priced line; the Gaps rule takes its side where the frozen row
    cleared the margin.
    """
    import statistics

    from src.export import prediction_freeze as PF

    out = []
    for wk, markets in PF.load(int(season)).items():
        for market, games in (markets or {}).items():
            if market not in STAT:
                continue
            for gid, rows in games.items():
                by_player: dict = defaultdict(list)
                for r in rows:
                    if r.get("player_name") and r.get("point") is not None:
                        by_player[r["player_name"]].append(r)
                for player, lines in by_player.items():
                    med = statistics.median(float(x["point"]) for x in lines)
                    r = sorted(lines, key=lambda x: (abs(float(x["point"]) - med),
                                                     float(x["point"])))[0]
                    away, home = gid.split("_")[-2:]
                    base = {"season": season, "week": int(wk), "market": market,
                            "player": player, "game": f"{away} @ {home}",
                            "line": r["point"], "model": r.get("model_only"),
                            "source": r.get("source")}
                    ms = r.get("model_side")
                    price = r.get("price_over") if ms == "over" else r.get("price_under")
                    if ms and price is not None:
                        out.append(dict(base, rule="model side", side=ms, odds=price))
                    gs = r.get("gap_side")
                    gp = r.get("price_over") if gs == "over" else r.get("price_under")
                    if gs and gp is not None:
                        out.append(dict(base, rule="prop edge over threshold",
                                        side=gs, odds=gp,
                                        edge_pp=r.get("gap_edge_pp")))
    return out


def graded(season: int, picks: list[dict] | None = None) -> tuple[list, int]:
    """Every settled forward pick as a dict, and how many are still pending.

    Read off the frozen boards (`prediction_freeze`), which hold each game as
    it stood at kickoff — recorded live from week 5, recovered from the page
    deployed before kickoff for weeks 1-4. A pick is pending while its own
    game has no final, so a Monday-night pick is not graded on the Sunday.
    """
    from src.evaluation.prop_settlement import _norm, participation
    from src.evaluation.tracked_rules import unfinished

    rows_in = _picks_from_boards(season) if picks is None else picks
    if not rows_in:
        return [], 0
    played = participation(season)
    out, pending = [], 0
    by_wm: dict = defaultdict(list)
    for r in rows_in:
        by_wm[(int(r["week"]), r["market"])].append(r)
    for (week, market), rows in sorted(by_wm.items()):
        open_ = unfinished(season, week)[1]
        acts = _actuals(season, week, market)
        names = _norm([r["player"] or "" for r in rows])
        for r, n in zip(rows, names):
            if (r.get("game") or "") in open_:
                if r["rule"] == "model side":
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
                        "model": r.get("model"), "edge_pp": r.get("edge_pp"),
                        "recovered": bool(r.get("source"))})
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


def block(season: int, picks: list[dict] | None = None) -> dict:
    """The forward record, per rule, per market, and per week.

    `candidate` is the weekly loop's test: a market whose 95% range sits
    wholly above zero per $100. It is a flag for a reader, and nothing reads
    it to change a threshold — the model changes only at the season-end refit.
    """
    src = _picks_from_boards(season) if picks is None else picks
    rows, pending = graded(season, src)
    weeks = sorted({int(r["week"]) for r in src})
    recovered = sorted({int(r["week"]) for r in src if r.get("source")})
    out = {"weeks": weeks, "recovered": recovered, "pending": pending,
           "rules": []}
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
