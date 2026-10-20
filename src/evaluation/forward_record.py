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
    ("model confident", "Our model, 75%+ sure"),
    ("model under", "Our model's unders, catches and rushing"),
)

#: The two selection rules are subsets of `model side`. Where each was found
#: decides the first week that can test it — see `tracked_rules.RULES`.
#: "model under" was read off weeks 2-4, so week 5 is its first unseen week,
#: and its picks were recorded before those games. It started at 6, which
#: dropped the one week that pulls its interval across zero (audit
#: 2026-10-19: week 6 alone +0.49 [+0.16, +0.82]; with week 5 +0.21
#: [-0.04, +0.46]).
SINCE = {"model confident": 2, "model under": 5}
UNDER_MARKETS = ("receptions", "rushing_yards")

#: The stat each market settles against, in `weekly_stats`.
STAT = {"receptions": "receptions", "receiving_yards": "receiving_yards",
        "rushing_yards": "rushing_yards", "passing_yards": "passing_yards"}


def _actuals(season: int, week: int, market: str):
    """(name, player_id) -> stat, by id first; see `prop_settlement.stat_lookup`."""
    from src.evaluation.prop_settlement import stat_lookup

    return stat_lookup(season, week, STAT[market])


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
                            "source": r.get("source"),
                            "player_id": r.get("player_id")}
                    ms = r.get("model_side")
                    price = r.get("price_over") if ms == "over" else r.get("price_under")
                    if ms and price is not None:
                        pick = dict(base, rule="model side", side=ms, odds=price,
                                    version=r.get("version"))
                        out.append(pick)
                        m = r.get("model_only")
                        if (m is not None and max(m, 1 - m) >= 0.75
                                and int(wk) >= SINCE["model confident"]):
                            out.append(dict(pick, rule="model confident"))
                        if (ms == "under" and market in UNDER_MARKETS
                                and int(wk) >= SINCE["model under"]):
                            out.append(dict(pick, rule="model under"))
                    gs = r.get("gap_side")
                    gp = r.get("price_over") if gs == "over" else r.get("price_under")
                    if gs and gp is not None:
                        # The version too, as the model-side picks carry it:
                        # without it every Gaps pick fell into one "None"
                        # group and a promotion could not be told apart.
                        out.append(dict(base, rule="prop edge over threshold",
                                        side=gs, odds=gp,
                                        edge_pp=r.get("gap_edge_pp"),
                                        version=r.get("version")))
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
            got = acts(r["player"], r.get("player_id"))
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
                        "recovered": bool(r.get("source")),
                        "version": r.get("version")
                                   or ("recovered" if r.get("source") else None)})
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
        # PER MODEL VERSION, so a promotion is judged on its own bets. A
        # recovered board predates the stamp and is its own population.
        by_version = {}
        for v in sorted({str(r.get("version")) for r in mine}):
            by_version[v] = _row([r for r in mine if str(r.get("version")) == v])
        out["rules"].append({"rule": rule, "label": label,
                             "since": SINCE.get(rule),
                             "markets": markets,
                             "all": _row(mine) if mine else None,
                             "by_week": by_week, "by_version": by_version})
    out["clv"] = clv(season)
    return out


# ── CLOSING-LINE VALUE: the signal that arrives before the results ─────────

def _close_fair(season: int) -> dict:
    """(game_id, normalized player, market, line) -> de-vigged P(over) at the
    close: the newest pre-kickoff close capture, in-play quotes dropped."""
    from src.ingest.odds_history import (HISTORY_PATH, SCHEMA, _conform,
                                         drop_in_play, resolve_game_ids)

    if not HISTORY_PATH.exists():
        return {}
    h = _conform(pl.read_parquet(HISTORY_PATH), SCHEMA)
    h = resolve_game_ids(h).filter(
        (pl.col("season") == season) & (pl.col("snapshot") == "close")
        & pl.col("market").is_in(list(STAT)) & pl.col("point").is_not_null()
        & pl.col("fair_prob").is_not_null())
    if h.height == 0:
        return {}
    h = (drop_in_play(h).sort("captured_at")
         .unique(subset=["game_id", "player_name_norm", "market", "point"],
                 keep="last"))
    return {(r["game_id"], r["player_name_norm"], r["market"], float(r["point"])):
            float(r["fair_prob"]) for r in h.iter_rows(named=True)}


def clv(season: int, picks: pl.DataFrame | None = None) -> dict:
    """How far the close moved toward each logged pick, in points of de-vigged
    probability, with the market's own open-to-close drift taken out.

    Read from `tracked_picks.csv`, NOT the frozen boards: a frozen board is
    the last board before kickoff, priced at the close, so its CLV is zero by
    construction. A logged pick carries the fair price when it was first
    seen and the moment (`recorded_at`), which is what CLV and the timing
    question both need.

    THE DRIFT IS SUBTRACTED. On every over/under market the de-vigged over
    rises from open to close regardless of any opinion (`ou_shortlist.drift`);
    left in, it credits every over with ~0.3pp of skill and charges every
    under the same. See `nfl-predictions-ou-markets-drift`.

    Positive means the market moved our way after we took it.
    """
    from src.evaluation.ou_shortlist import drift, pairs
    from src.evaluation.prop_settlement import _norm
    from src.evaluation.tracked_rules import load

    p = load() if picks is None else picks
    if p.is_empty() or "recorded_at" not in p.columns:
        return {}
    p = p.filter((pl.col("season").cast(pl.Utf8) == str(season))
                 & pl.col("market").is_in(list(STAT))
                 & pl.col("rule").is_in([r for r, _ in RULES]))
    if p.is_empty():
        return {}
    close = _close_fair(season)
    # THE RECENT MARKET'S DRIFT, NOT THE ARCHIVE'S. It is not stationary:
    # on receptions it ran +0.93pp in 2023, +0.34 in 2024, +0.02 in 2025 and
    # +0.06 in 2026, so the pooled +0.355 subtracted 2023's market from 2026's
    # picks, and 73% of the "model under" rule's CLV was that correction.
    # The season being graded and the one before it.
    def _recent(m):
        pr = pairs(m)
        if pr is None or pr.is_empty() or "season" not in pr.columns:
            return drift(pr)
        return drift(pr.filter(pl.col("season").cast(pl.Int64) >= int(season) - 1))
    dr = {m: _recent(m) for m in STAT}
    rows = p.to_dicts()
    names = _norm([r["player"] or "" for r in rows])
    got = []
    for r, n in zip(rows, names):
        try:
            book, line = float(r["book"]), float(r["line"])
        except (TypeError, ValueError):
            continue
        away, _, home = (r.get("game") or "").partition(" @ ")
        gid = f"{season}_{int(r['week']):02d}_{away}_{home}"
        c = close.get((gid, n, r["market"], line))
        if c is None or r.get("side") not in ("over", "under"):
            continue
        # A rule counts from its own first week, here as in its win-loss
        # record: "model under" had 135 week-5 picks in its CLV and none in
        # its record.
        if int(r["week"]) < SINCE.get(r["rule"], 0):
            continue
        s = 1 if r["side"] == "over" else -1
        got.append({"rule": r["rule"], "market": r["market"], "game": gid,
                    "clv": s * ((c - book) * 100 - dr[r["market"]]),
                    "raw": s * (c - book) * 100,
                    "recorded_at": r.get("recorded_at")})
    out = {}
    for rule, label in RULES:
        mine = [g for g in got if g["rule"] == rule]
        if not mine:
            continue
        by_game = defaultdict(list)
        for g in mine:
            by_game[g["game"]].append(g["clv"])
        mean, lo, hi = _cluster_ci(by_game)
        out[rule] = {"label": label, "n": len(mine), "mean": mean,
                     "lo": lo, "hi": hi,
                     # The move before the drift came out, so a reader can
                     # see how much of the figure is the correction.
                     "raw_mean": round(st.mean(g["raw"] for g in mine), 3),
                     "drift": {m: round(dr[m], 3) for m in
                               sorted({g["market"] for g in mine})},
                     "markets": {m: round(st.mean(g["clv"] for g in mine
                                                  if g["market"] == m), 3)
                                 for m in sorted({g["market"] for g in mine})}}
    return out
