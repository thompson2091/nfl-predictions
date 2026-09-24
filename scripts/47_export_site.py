#!/usr/bin/env python3
"""Build site/site.html — the five-page board, as one self-contained file.

Reads the same payload `scripts/34_export_dashboard.py` builds, because the
data behind both pages is identical and a second builder would drift from the
first within a week. What it adds is the three things the new design needs and
the old one had no use for:

  * `pos` per player, so the board can be filtered to running backs. Position
    is one-hot in the feature matrix (WR is the reference level and has no
    column of its own), so it is reconstructed rather than read.
  * `results`, so a parlay saved on Wednesday settles on Sunday. Only weeks
    that have actually been graded appear; a leg the map does not carry stays
    pending rather than being assumed missed.
  * `season` and `week` at the top level, because the page scopes everything it
    remembers to them and the markets can in principle disagree.

    python scripts/47_export_site.py
    python scripts/47_export_site.py --week 3 --open
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, ".")

import numpy as np
import polars as pl

from src.utils.paths import get_path

#: One-hot position columns in the feature matrix, and the level they encode.
#: WR is deliberately absent: it is the reference level, so a player with a
#: zero in every column below is a receiver. Reading that as "unknown" would
#: put the largest position group behind an "Any position" filter it never
#: matches.
POSITION_COLS = {"position_QB": "QB", "position_RB": "RB", "position_TE": "TE",
                 "position_FB": "FB", "position_DEFST": "DEF/ST"}
POSITION_DEFAULT = "WR"


def positions(season: int, week: int) -> dict[str, str]:
    """player_name -> position, for one week of the feature matrix."""
    path = get_path("processed", "anytime_td") / "features.parquet"
    if not Path(path).exists():
        return {}
    have = [c for c in POSITION_COLS if c in pl.scan_parquet(path).collect_schema().names()]
    if not have:
        return {}
    df = (pl.scan_parquet(path)
          .filter((pl.col("season") == season) & (pl.col("week") == week))
          .select(["player_name"] + have).collect())
    out = {}
    for row in df.iter_rows(named=True):
        hit = next((POSITION_COLS[c] for c in have if row.get(c) == 1), POSITION_DEFAULT)
        out[row["player_name"]] = hit
    return out


def qualified_name(name: str | None, team: str | None) -> str:
    """A player's name, made unique where the source does not make it so.

    Every team's defence is called "DEF/ST". The board builds a leg id from
    `<market>|<player>` and the settlement map is keyed the same way, so all
    32 of them collapsed onto one id and one outcome.

    Used by BOTH sides of that lookup — the board and the results map — from
    here, because qualifying one and not the other is worse than qualifying
    neither: the leg would look right, settle against nothing, and read
    Pending for ever.
    """
    if name == "DEF/ST" and team:
        return f"{team} DEF/ST"
    return name or ""


def results(season: int, week: int) -> dict[str, str]:
    """`<week>|<market>|<player>` -> "hit" or "miss", for this week and last.

    Two weeks, not one, and the reason is a timing trap rather than a
    preference. The slate holds a finished week until the next one's roster
    lands (`src/evaluation/slate.py`), and the rollover that builds the next
    week is the *same run* that extracts the finished week's touchdowns. So
    the only export that could settle week 2 is the one that has already
    become week 3. Keyed to one week, a saved parlay would read Pending until
    its storage key stopped being read, and the status dots, the Won/Lost
    filters and the net figure would be furniture.

    The week is in the key because the markets are not unique across weeks:
    `any|Derrick Henry` is a different bet in week 2 than in week 3, and
    collapsing them would settle a live parlay from a result it never had.

    Keyed by the id the page builds a leg from (`<market>|<player>`), so
    settling is a lookup rather than a name match performed twice in two
    languages.

    The join is on `player_id`, not on a name. The targets files record
    touchdowns as play-by-play writes them — `C.Lamb`, `Bi.Robinson` — and the
    board carries `CeeDee Lamb`, so a name match here would silently settle
    almost nothing and report every parlay as a loss. The feature matrix holds
    both for the week and is what bridges them.

    An ungraded week contributes nothing at all, which leaves saved parlays
    pending. That is the right default: a slip reading Lost because a join
    failed is worse than one reading Pending for another hour.
    """
    feats = get_path("processed", "anytime_td") / "features.parquet"
    if not Path(feats).exists():
        return {}

    out: dict[str, str] = {}
    for wk in (w for w in (week - 1, week) if w and w > 0):
        # `team` only where the matrix carries it. It always does in
        # production and a missing column here must not crash the export —
        # `qualified_name` leaves a name alone when it has no team to qualify
        # it with, which is the same answer as before this existed.
        have = pl.scan_parquet(feats).collect_schema().names()
        cols = ["player_id", "player_name"] + (["team"] if "team" in have else [])
        pool = (pl.scan_parquet(feats)
                .filter((pl.col("season") == season) & (pl.col("week") == wk))
                .select(cols).collect()
                .unique(subset=["player_id"]))
        if "team" not in pool.columns:
            pool = pool.with_columns(pl.lit(None, dtype=pl.Utf8).alias("team"))
        if pool.height == 0:
            continue
        out.update(_week_results(season, wk, pool))
    return out


def _week_results(season: int, week: int, pool: pl.DataFrame) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, target in (("any", "anytime_td"), ("first", "first_td")):
        path = get_path("processed", target) / f"tds_{target}.parquet"
        if not Path(path).exists():
            continue
        td = (pl.scan_parquet(path)
              .filter((pl.col("season") == season) & (pl.col("week") == week))
              .select("td_player_id").collect())
        if td.height == 0:
            # No touchdowns recorded is not the same as no data. A week with a
            # feature matrix and an empty targets file has not been extracted
            # yet, and calling every player a miss would settle every parlay
            # as a loss on the strength of a missing file.
            continue
        scorers = set(td["td_player_id"].drop_nulls().to_list())
        for pid, name, team in pool.iter_rows():
            out[f"{week}|{key}|{qualified_name(name, team)}"] = (
                "hit" if pid in scorers else "miss")
    return out


def opening_prices(season: int, week: int) -> dict[str, dict]:
    """`<market>|<normalised name>` -> the first price of the week, per market.

    The board is priced at the close, which is the price you could actually
    take. The open is the other end of the same measurement, and the gap
    between them is the one thing on this page that is evidence rather than
    opinion: it is the market moving, and `shortlist.floor` is fitted on
    whether it moves toward our number or away from it.

    It is also, early in the week, more coverage rather than less. On the
    Wednesday of week 2 the close held 19 first-TD players and 7 receptions
    lines, because the Sunday captures have not fired; the open held 437 and
    68. A board with no price on it is not the same as a market with no
    opinion.

    Earliest capture wins, and the market is part of the key — the same player
    is quoted in three of them.
    """
    from src.ingest.odds_history import (HISTORY_PATH, drop_in_play,
                                         resolve_game_ids)
    if not Path(HISTORY_PATH).exists():
        return {}
    h = drop_in_play(resolve_game_ids(pl.read_parquet(HISTORY_PATH))).filter(
        (pl.col("season") == season) & (pl.col("week") == week)
        & (pl.col("snapshot") == "open"))
    if h.height == 0:
        return {}
    h = h.sort("captured_at").unique(
        subset=["market", "player_name_norm", "point"], keep="first")
    # One row per player per market: the line the market opened AT, which is
    # the one the most books drew, ties going to the line nearest the median.
    #
    # This used to take the lowest line, which is right for a yes/no market
    # (there is only one) and nearly harmless for receptions, where books
    # agree — a median of 1 distinct line per player, 26% of player-weeks
    # carrying more than one, and the lowest sitting 0.18 below the median.
    #
    # It is not harmless on a yardage market. Measured over the archive:
    #
    #     market            lines/player   multi-line   lowest below median
    #     receptions             1            26%             0.18
    #     rushing yards          3            74%             1.43
    #     receiving yards        3            75%             1.68
    #     passing yards          4            89%             4.91
    #
    # Taking the lowest of a quarterback's four opening lines hands the over a
    # five-yard head start, and every number derived from it inherits that: the
    # Open column reports line dispersion as market movement, and a row with no
    # close gets priced against the most over-friendly number on the board —
    # in the same direction the model already leans.
    n_books = pl.col("n_books").fill_null(0)
    med = pl.col("point").median().over(["market", "player_name_norm"])
    h = (h.with_columns([
            n_books.alias("_nb"),
            (pl.col("point") - med).abs().fill_null(0.0).alias("_off")])
          .sort(["_nb", "_off"], descending=[True, False])
          .unique(subset=["market", "player_name_norm"], keep="first")
          .drop(["_nb", "_off"]))
    out = {}
    for r in h.iter_rows(named=True):
        # `implied_prob`, not `fair_prob`. A touchdown market is quoted one
        # side only at the open, so there is nothing to de-vig against and
        # `fair_prob` is null on every one of those rows. The implied figure
        # is always there, and comparing it to the board's implied price is
        # like for like — both carry the book's margin, so the difference is
        # the market moving rather than the margin changing.
        # `fair` and `n_books` are carried for the over/under markets only,
        # where they exist. An over/under book posts BOTH sides at the open, so
        # unlike a touchdown prop it has a real two-way de-vig — and that is
        # the number the model gets blended toward when a row is falling back
        # to the opening line. Null on the touchdown markets, which is correct
        # rather than missing: there is no second side to remove a margin with.
        out[f"{r['market']}|{r['player_name_norm']}"] = {
            "odds": r.get("odds"), "point": r.get("point"),
            "prob": r.get("implied_prob"),
            "fair": r.get("fair_prob"), "n_books": r.get("n_books"),
        }
    return out


def _attach_opens(payload: dict, season: int, week: int) -> None:
    from src.prediction.predict import _norm_name_expr

    opens = opening_prices(season, week)
    if not opens:
        return

    def norm(names):
        if not names:
            return {}
        df = (pl.DataFrame({"p": list(names)})
              .with_columns(_norm_name_expr("p").alias("n")))
        return dict(zip(df["p"].to_list(), df["n"].to_list()))

    for key, m in zip(("anytime_td", "first_td"), payload.get("markets") or []):
        players = m.get("players") or []
        keys = norm({p.get("player") for p in players if p.get("player")})
        for p in players:
            o = opens.get(f"{key}|{keys.get(p.get('player'), '')}")
            if o:
                p["open_odds"] = o["odds"]
                p["open_implied"] = o["prob"]

    blocks = [("receptions", payload.get("receptions") or {})]
    blocks += [(mk, blk) for mk, blk in (payload.get("yards") or {}).items()]
    for market, blk in blocks:
        _attach_open_rows(market, blk.get("rows") or [], opens, norm)


def _attach_open_rows(market: str, rows: list, opens: dict, norm) -> None:
    keys = norm({r.get("player_name") for r in rows if r.get("player_name")})
    for r in rows:
        o = opens.get(f"{market}|{keys.get(r.get('player_name'), '')}")
        if o:
            r["open_point"] = o["point"]
            r["open_odds"] = o["odds"]
            r["open_implied"] = o["prob"]
            r["open_fair"] = o.get("fair")
            r["open_books"] = o.get("n_books")


def yards(market: str, season: int | None, week: int | None) -> dict:
    """One yardage board, in the shape the page already reads for receptions.

    The same two blocks and the same column names, because the page's `ou`
    board is written once and these are four markets through it rather than
    four boards. What differs underneath is the model — a fitted quantile
    curve rather than a mean and a dispersion — and the page never needs to
    know that; it gets a projection, a floor, a ceiling and three
    probabilities either way.

    Every candidate gets a row, not only the ones a book has quoted. Books post
    yardage lines late, so a board built from posted lines alone is thin for
    most of the week — the same reason `_receptions_projections` exists.
    """
    from src.prediction.yards import MARKETS, board_for_week, load_model

    out = {"season": season, "week": week, "rows": [], "problem": "",
           "market": market, "label": MARKETS[market]["label"],
           "model": load_model(market) is not None, "blend": None}
    if season is None or week is None:
        out["problem"] = "no slate to show"
        return out

    board, msg = board_for_week(market, season, week)
    out["problem"] = msg
    keep = ["player_name", "team", "game_id", "proj", "lo", "hi", "point",
            "odds", "implied_prob", "overround", "fair_prob", "model_only",
            "ours", "edge_pp", "ev", "n_books", "thin"]
    priced: set[str] = set()
    if board is not None and board.height:
        out["rows"] = board.select([c for c in keep if c in board.columns]).to_dicts()
        priced = {r["player_name"] for r in out["rows"]}
        out["blend"] = board["blend_weight"][0]

    # The graded verdict, so no screen has to infer which claim is being made.
    # Carried as the numbers rather than a sentence: `beats_market` here is the
    # significance-tested flag from `scripts/49_yards.py:compare`, not a raw
    # log-loss comparison, and the first version of that comparison said True
    # on a coin flip.
    summary = get_path("output", market) / "summary.json"
    if summary.exists():
        try:
            sm = json.loads(summary.read_text())
            out["graded"] = {
                "beats_market": sm.get("beats_market"),
                "blend_beats_market": sm.get("blend_beats_market"),
                "seasons": [{"season": r["season"], "n": r["n"],
                             "model": r["model"]["log_loss"],
                             "market": r["market"]["log_loss"],
                             "blend": (r.get("blend") or {}).get("log_loss"),
                             "in_sample": (r.get("blend") or {}).get("in_sample"),
                             "vs_market": r.get("vs_market")}
                            for r in sm.get("seasons") or []],
            }
        except Exception:                                        # noqa: BLE001
            pass
    return out


def _yards_projections(payload: dict, market: str, season: int, week: int) -> None:
    """Add a row for every candidate on a yardage board, not only the quoted ones."""
    from src.prediction.yards import expected_quantiles
    from src.models.yards import interval, quantile_at

    blk = (payload.get("yards") or {}).get(market) or {}
    got = _YARD_Q.get(market) or expected_quantiles(market, season, week)
    if got is None:
        return
    ids, q = got
    lo, hi = interval(q)
    med = quantile_at(q, 0.5)
    eligible = {p.get("player") for m in payload.get("markets") or []
                for p in m.get("players") or []}
    priced = {r.get("player_name") for r in blk.get("rows") or []}
    extra = []
    for i, row in enumerate(ids.iter_rows(named=True)):
        name = row["player_name"]
        if name in priced:
            continue
        if eligible and name not in eligible:
            continue
        extra.append({
            "player_name": name, "team": row["team"],
            "game_id": row.get("game_id"),
            "proj": float(med[i]), "lo": float(lo[i]), "hi": float(hi[i]),
            "point": None, "odds": None, "fair_prob": None, "ours": None,
            "model_only": None, "edge_pp": None, "n_books": 0, "thin": False,
        })
    blk["rows"] = (blk.get("rows") or []) + sorted(
        extra, key=lambda r: -r["proj"])
    blk["priced_rows"] = len(priced)


def _mark_consensus_lines(payload: dict) -> None:
    """Which of a player's posted lines is the one to lead with.

    A yardage board carries one row per (player, line), and books scatter: on
    2026 week 2 that is 4.4 rows per quarterback on passing yards, 2.7 per
    receiver, 2.5 per back — Jaxson Dart six times at six different numbers.
    Receptions never does this, at 1.0 rows per player, which is why the board
    was built without a view for it.

    They are not duplicates. Each is a real bet at a real number, and most of
    them are one book deep: Dart's six read 210.5(1) 212.5(1) 213.5(2)
    214.5(2) 215.5(1) 217.5(3). But a board that prints a player six times and
    leads with whichever row happens to sort highest is a board where the
    biggest disagreement is an artefact of which single book drew the friendliest
    number.

    So one row per player is flagged as the consensus — the line the most books
    drew, ties to the one nearest that player's median, which is the same rule
    `opening_prices` uses. The others keep every figure they had and the page
    hides them by default behind a control that says how many there are.
    """
    import statistics

    blocks = [payload.get("receptions") or {}]
    blocks += list((payload.get("yards") or {}).values())
    for blk in blocks:
        rows = [r for r in (blk.get("rows") or [])
                if r.get("point") is not None or r.get("open_point") is not None]
        by_player: dict = {}
        for r in rows:
            by_player.setdefault(r.get("player_name"), []).append(r)
        for group in by_player.values():
            def line_of(r):
                return r["point"] if r.get("point") is not None else r["open_point"]
            med = statistics.median([line_of(r) for r in group])
            best = max(group, key=lambda r: ((r.get("n_books") or 0),
                                             -abs(line_of(r) - med)))
            for r in group:
                r["best_line"] = r is best
                r["n_lines"] = len(group)


def _price_open_fallback(payload: dict) -> None:
    """Give the rows that fall back to the opening line a probability.

    `board_for_week` prices a row only where a CLOSING line joined it, and for
    most of the week almost nothing has one — on the Wednesday of 2026 week 2
    the close held 7 receptions lines and the open held 67. The board already
    showed the opening line on those 60 rows, and their odds, and nothing else:
    no model number, no book number, no edge, no EV.

    That is worse than an empty cell, because the Combinations page multiplies
    these together. A pool of 67 "priced" rows of which 60 carry no probability
    produces `p *= null` for almost every slip, and the All hit column fills
    with NaN — a board that looks populated and answers nothing.

    So a row showing the opening line is priced against the opening line, by
    the same three steps the close gets: the count model's own number from the
    fitted distribution, the book's with its margin removed, and the blend
    between them. An over/under posts both sides at the open, so the de-vig is
    real here rather than the one-sided normalisation a touchdown prop needs.
    Where a book somehow posted only one side, `blend_to_market` returns the
    model alone rather than reading a missing price as a 50% opinion.
    """
    from src.models.count import blend_to_market

    blocks = [("receptions", payload.get("receptions") or {})]
    blocks += [(mk, blk) for mk, blk in (payload.get("yards") or {}).items()]
    for market, blk in blocks:
        rows = [r for r in (blk.get("rows") or [])
                if r.get("point") is None and r.get("open_point") is not None]
        if not rows:
            continue
        got = _open_probs(market, rows)
        if got is None:
            continue
        raw, w = got
        book = np.array([float(r["open_fair"]) if r.get("open_fair") is not None
                         else np.nan for r in rows], dtype=float)
        ours = raw if w is None else blend_to_market(raw, book, w)
        for i, r in enumerate(rows):
            r["model_only"] = float(raw[i])
            r["ours"] = float(ours[i])
            if np.isfinite(book[i]):
                r["fair_prob"] = float(book[i])
                r["edge_pp"] = float((ours[i] - book[i]) * 100)
            nb = r.get("open_books")
            if nb is not None:
                r["n_books"] = int(nb)
                r["thin"] = bool(int(nb) < 3)
        blk["open_priced_rows"] = len(rows)


def _open_probs(market: str, rows: list) -> tuple | None:
    """Our chance of the over at the opening line, by whichever model serves it.

    The two families are asked the same question and answer it differently:
    receptions reads a line off a fitted negative binomial, the three yardage
    markets off a fitted quantile curve. Only this function knows that.
    """
    line = np.array([float(r["open_point"]) for r in rows], dtype=float)

    if market == "receptions":
        from src.models.count import fair_two_way, prob_over
        from src.prediction.receptions import load_blend, load_model
        art = load_model()
        if art is None or any(r.get("mu") is None for r in rows):
            return None
        mu = np.array([float(r["mu"]) for r in rows], dtype=float)
        over, push = prob_over(mu, line, float(art["dispersion"]))
        return fair_two_way(over, push), load_blend()

    from src.models.yards import prob_over as q_over
    from src.prediction.yards import expected_quantiles, load_blend

    art = _YARD_Q.get(market)
    if art is None:
        return None
    ids, q = art
    ix = {n: i for i, n in enumerate(ids["player_name"].to_list())}
    if any(r.get("player_name") not in ix for r in rows):
        return None
    qq = q[[ix[r["player_name"]] for r in rows]]
    over, push = q_over(qq, line)
    return np.clip(over / np.clip(1.0 - push, 1e-9, None), 0.0, 1.0), load_blend(market)


#: Fitted quantile curves for this week, cached across the three passes that
#: need them. Scoring 800 rows through a 21-level booster three times over is
#: the kind of waste that only shows up as a slow build.
_YARD_Q: dict = {}


def _receptions_projections(payload: dict, season: int, week: int) -> None:
    """Add a row for every candidate, not only the ones a book has quoted.

    Books post receptions lines far later than touchdown props — in week 2 that
    was seven players out of five hundred — so a board built from posted lines
    alone is empty for most of the week and then mostly empty after that. The
    model has a number for everyone on a roster the whole time, which is the
    view the old app led with and the one worth carrying through.

    An unpriced row keeps `mu` and drops `point`, `odds` and everything derived
    from them. It is deliberately not given a line to be measured against: the
    projection is what the model says, and inventing a 4.5 to score it against
    would be the page making up the market it is missing.
    """
    rec = payload.get("receptions") or {}
    if not rec.get("model") or not season or not week:
        return
    try:
        from src.models.count import count_interval
        from src.prediction.receptions import expected_counts, load_model
        art = load_model()
        mus = expected_counts(season, week, art)
    except Exception:                                            # noqa: BLE001
        return
    if mus is None or mus.height == 0:
        return

    # Floor and ceiling, off the same fitted distribution the probabilities
    # come from. A mean alone cannot be read: 4.2 from a target hog and 4.2
    # from a deep threat are different bets, and the dispersion is what knows.
    lo, hi = count_interval(mus["mu"].to_numpy(), float(art["dispersion"]))
    mus = mus.with_columns([pl.Series("lo", lo), pl.Series("hi", hi)])

    # Held to the same population the touchdown board shows, which has already
    # had the low-activity and availability filters applied. Without it this is
    # the raw feature matrix: 811 rows including one DEF/ST per team, each
    # carrying a projected reception count, which is noise wearing a number.
    eligible = {p.get("player") for m in payload.get("markets") or []
                for p in m.get("players") or []}
    rng = {r["player_name"]: (float(r["lo"]), float(r["hi"]))
           for r in mus.iter_rows(named=True)}
    for r in rec.get("rows") or []:
        got = rng.get(r.get("player_name"))
        if got:
            r["lo"], r["hi"] = got
    priced = {r.get("player_name") for r in rec.get("rows") or []}
    extra = []
    for row in mus.sort("mu", descending=True).iter_rows(named=True):
        if row["player_name"] in priced:
            continue
        if eligible and row["player_name"] not in eligible:
            continue
        extra.append({
            "player_name": row["player_name"], "team": row["team"],
            "game_id": row.get("game_id"), "mu": row["mu"],
            "lo": float(row["lo"]), "hi": float(row["hi"]),
            "point": None, "odds": None, "fair_prob": None, "ours": None,
            "model_only": None, "edge_pp": None, "n_books": 0, "thin": False,
            "games_observed": row.get("games_observed"),
        })
    rec["rows"] = (rec.get("rows") or []) + extra
    rec["priced_rows"] = len(priced)


#: Where each over/under board lives in the payload, and which fitted artifact
#: belongs to it. Receptions is a block of its own; the three yardage boards
#: are entries under one.
OU_BLOCKS = (("receptions", ("receptions",)),
             ("rushing_yards", ("yards", "rushing_yards")),
             ("receiving_yards", ("yards", "receiving_yards")),
             ("passing_yards", ("yards", "passing_yards")))


#: Decimal places kept on every float in the payload.
#:
#: A probability reaches the page as 0.5796356935535429 and is rendered as
#: "58%". The seventeen significant figures are what a float prints as, not
#: what anything means: 18,438 of them carry 169KB of tail, which is 10% of a
#: payload a phone has to download and parse before it can draw anything.
#:
#: Six is chosen against what the page actually shows, with room to spare —
#: probabilities render to one decimal place of a percent, yardage to two, and
#: the odds columns are integers. Nothing on screen can move.
PAYLOAD_DP = 6


def _shrink(o):
    """Round every float in the payload, in place where it can be."""
    if isinstance(o, float):
        return round(o, PAYLOAD_DP)
    if isinstance(o, dict):
        return {k: _shrink(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_shrink(v) for v in o]
    return o


def _attach_ou_shortlists(payload: dict) -> None:
    """Narrow each over/under board to what its fitted rule would take.

    Runs after the opening-line fallback and before the consensus line is
    marked, and that order is not arbitrary. After the fallback, because a row
    showing only an opening line is a bet the rule can take and has no
    probabilities to take it on until the fallback has priced it. Before the
    narrowing, because the rule is fitted per (player, line) and a board that
    has already picked one line per player is a different population from the
    one it was measured on.

    A market with no fitted artifact gets an empty shortlist carrying the
    reason, never a missing key — the page reads the reason and says so, which
    is the difference between "the rule found nothing" and "the rule was never
    run".
    """
    from src.evaluation import ou_shortlist as ous

    for market, path in OU_BLOCKS:
        blk = payload
        for k in path:
            blk = (blk or {}).get(k) or {}
        if not isinstance(blk, dict):
            continue
        blk["shortlist"] = ous.apply_to_board(blk.get("rows") or [],
                                              ous.load(market))


def _enrich_lines(book_rows: list[dict], moves: dict | None = None,
                  season: int | None = None, week: int | None = None
                  ) -> tuple:
    """De-vig every line, price its EV, and summarise each fixture.

    Shared by the live week and by every archived one, so a past week
    cannot drift into showing a different set of numbers from the week it
    will become. Returns `(rows, cards)`.
    """
    moves = moves or {}
    def _pairkey(r):
        if r["market"] == "spreads" and r["point"] is not None:
            return (r["game_id"], "spreads", abs(r["point"]))
        return (r["game_id"], r["market"], r["point"])

    totals_by_key: dict = {}
    for r in book_rows:
        k = _pairkey(r)
        totals_by_key.setdefault(k, []).append(r)

    def _profit(american):
        """Profit on a $100 stake, which is what an American price means."""
        if american is None:
            return None
        a = float(american)
        return a if a > 0 else 10000.0 / -a

    rows = []
    for r in book_rows:
        k = (r["game_id"], r["market"], str(r["outcome"]), r["point"])
        m = moves.get(k)
        pair = totals_by_key.get(_pairkey(r), [])
        # Only a genuine two-sided pair can be de-vigged. A line quoted by
        # enough books on one side and not the other is left with no fair
        # number rather than being given its vigged one, which would read as
        # an edge that is entirely the margin.
        fair = None
        if len(pair) == 2:
            tot = sum(x["consensus_prob"] for x in pair)
            if tot > 0:
                fair = r["consensus_prob"] / tot
        # EV of $100 at the BEST price, taking the de-vigged consensus as
        # truth. That assumption is the whole caveat and the page states it:
        # this measures beating the median book, not beating the market. It is
        # also why it can go negative — a favourite whose best price is still
        # short of fair is a bet that shopping does not rescue.
        pb = _profit(r["best_odds"])
        pc = _profit(r["consensus_odds"])
        ev = None if (fair is None or pb is None) else fair * pb - (1 - fair) * 100
        rows.append({
            "fair": fair,
            "ev100": ev,
            # The same gain in money rather than probability points. "+2.74pp"
            # is not a quantity anyone can act on; "+$56 per $100" is.
            "shop": None if (pb is None or pc is None) else pb - pc,
            "game_id": r["game_id"], "home": r["home_team"],
            "away": r["away_team"], "market": r["market"],
            "outcome": str(r["outcome"]), "point": r["point"],
            "consensus": r["consensus_odds"], "consensus_prob": r["consensus_prob"],
            "best": r["best_odds"], "best_book": r["best_book"],
            "gap_pp": r["gap_pp"], "n_books": r["n_books"],
            # Null, not zero, when the week holds one end only. A week being
            # played has no close yet and "did not move" is a different claim
            # from "cannot be known".
            "move_pp": (m or {}).get("move_pp"),
            "open_odds": (m or {}).get("open_odds"),
        })
    # One summary per fixture: the market's own projected score and each
    # team's chance of winning, which is what a matchup card is actually for.
    #
    # The score is ARITHMETIC, not a model. A total of 47.5 with the home side
    # favoured by 8.5 is the two numbers T/2 +/- S/2, and it is the market's
    # projection restated rather than a second opinion about it. Labelled as
    # the market's on the page, and the slot a no-vegas model would fill.
    cards = {}
    by_game: dict = {}
    for r in rows:
        by_game.setdefault(r["game_id"], []).append(r)
    for gid, rs in by_game.items():
        a = rs[0]
        # The MAIN line of each market is the one the most books quote. An
        # alternate total of 33.5 exists on some games and would otherwise be
        # as likely to be picked as the real one.
        def _main(mkt):
            sel = [x for x in rs if x["market"] == mkt and x["point"] is not None]
            return max(sel, key=lambda x: x["n_books"]) if sel else None

        tot, spr = _main("totals"), _main("spreads")
        total_pt = abs(tot["point"]) if tot else None
        # Signed toward the HOME side, which is the convention the rest of the
        # project uses for `spread_line`.
        home_spread = None
        if spr:
            home_spread = (spr["point"] if spr["outcome"] == a["home"]
                           else -spr["point"])
        ph = pa = None
        if total_pt is not None and home_spread is not None:
            ph = round(total_pt / 2 - home_spread / 2, 1)
            pa = round(total_pt / 2 + home_spread / 2, 1)
        wins = {x["outcome"]: x["fair"] for x in rs
                if x["market"] == "h2h" and x["fair"] is not None}
        cards[gid] = {
            "game_id": gid, "home": a["home"], "away": a["away"],
            "total": total_pt, "spread": home_spread,
            "proj_home": ph, "proj_away": pa,
            "win_home": wins.get(a["home"]), "win_away": wins.get(a["away"]),
        }
    _attach_finals(cards, season, week)
    _attach_model(cards, season, week)
    return rows, [cards[k] for k in sorted(cards)]


def games(season: int | None, week: int | None) -> dict:
    """This week's games as the market prices them — and no model column.

    **There is deliberately no projection beside a spread or a total.** The
    only thing in this project that speaks to a game's scoring level is
    `joint.fit_team_rate`, and that is a Poisson regression OF team touchdowns
    ON `implied_team_total`, `total_line` and `abs_spread`. Its job is to turn
    the market's number into touchdowns, not to form a second opinion about
    it, so printing its output next to the posted total would print the total
    twice and label the second copy a prediction. `src/evaluation/matchups`
    carries the longer version of this note.

    What is real here is the disagreement. The best moneyline beats the
    consensus by a median 1.23pp, which is return available for holding more
    than one account and needs no model at all.
    """
    if not (season and week):
        return {}
    try:
        from src.evaluation.matchups import MIN_BOOKS, board, movement
    except Exception as e:                                       # noqa: BLE001
        print(f"  games unavailable ({e})", file=sys.stderr)
        return {}

    b = board(season, week)
    if b.is_empty():
        print(f"  no game lines for {season} week {week}", file=sys.stderr)
        return {}

    mv = movement(season, week)
    moves = {}
    if not mv.is_empty():
        for r in mv.iter_rows(named=True):
            moves[(r["game_id"], r["market"], str(r["outcome"]),
                   r["point"])] = r

    # Two snapshots are not two ENDS. Week 3 of 2026 archived its open and its
    # close four minutes apart — `weekly_odds.sh open` had not run, so the
    # backfill wrote the same market state twice — and 202 of its 204 lines
    # came back bit-identical. Rendered naively that reads "nothing moved",
    # which is a claim about the market rather than about the capture.
    #
    # The gate is `MIN_MOVE_PP`, borrowed from `rlm` rather than invented here:
    # that module already defines it as the point below which a difference is
    # book rounding. If not one line in the week cleared it, there is nothing
    # to show and the reason is the capture, not the market.
    from src.evaluation.rlm import MIN_MOVE_PP

    real = [m for m in moves.values() if abs(m["move_pp"] or 0) >= MIN_MOVE_PP]
    gap_h = None
    stale_close = False
    try:
        import polars as pl

        from src.ingest.game_lines import LINES_PATH
        d = (pl.read_parquet(LINES_PATH)
             .filter((pl.col("season") == season) & (pl.col("week") == week)))
        # The LATEST of each, not the earliest. A week can hold several
        # captures per end, and what decides whether a close exists is the
        # newest one — see `stale_close` below.
        ends = {k: v for k, v in
                d.group_by("snapshot").agg(pl.col("captured_at").max().alias("t"))
                .iter_rows()}
        ts = {k: v for k, v in
              d.group_by("snapshot").agg(pl.col("captured_at").min().alias("t"))
              .iter_rows()}
        # A close that predates the newest open is not a close. Week 3 held a
        # pair captured four minutes apart while a real open landed the next
        # day, and the four-minute pair still differed by a point or two on
        # five lines — not because the market moved but because the set of
        # books quoting them changed, which shifts a median. Requiring "some
        # line moved" passed that; requiring the close to come AFTER the open
        # does not, and needs no threshold to say so.
        if "open" in ends and "close" in ends:
            stale_close = ends["close"] < ends["open"]
        if "open" in ts and "close" in ts:
            from datetime import datetime
            fmt = "%Y-%m-%dT%H:%M:%SZ"
            gap_h = round((datetime.strptime(ts["close"], fmt)
                           - datetime.strptime(ts["open"], fmt)).total_seconds()
                          / 3600.0, 2)
    except Exception:                                            # noqa: BLE001
        pass

    # De-vig, so the page can print a probability rather than a price.
    #
    # The two sides of a line sum to more than 1 — that excess IS the book's
    # margin — and the fair number is each side's share of the total. The three
    # markets pair their sides DIFFERENTLY, which is the only subtle part:
    # a moneyline has one null point, a total has Over and Under on the same
    # point, and a spread has SF -8.5 against ARI +8.5, whose points are
    # negatives of each other. Grouping all three on `point` would pair a total
    # correctly, leave a moneyline alone, and silently fail to pair any spread
    # at all — every spread would then read as fair at its vigged price.
    book_rows = b.to_dicts()
    rows, cards = _enrich_lines(book_rows, moves, season, week)


    return {"season": season, "week": week, "rows": rows,
            "cards": cards,
            "min_books": MIN_BOOKS,
            "games": int(b["game_id"].n_unique()),
            # Not `bool(moves)`: a week holding two copies of the same capture
            # has a full movement table of zeroes. See above.
            "moved": bool(real) and not stale_close,
            "capture_gap_hours": gap_h,
            "stale_close": stale_close,
            "min_move_pp": MIN_MOVE_PP,
            # Stated on the page rather than left for the reader to wonder at.
            "no_model": ("The team-rate model is a regression ON the total and "
                         "the spread, so it cannot second-guess them. What is "
                         "shown is the market, the spread between books, and "
                         "which way it moved.")}


def _attach_finals(cards: dict, season: int | None, week: int | None) -> None:
    """The score, where THIS week's game has been played.

    Keyed on season and week as well as the teams. Keyed on the pair alone it
    matched any previous meeting of those two, so the upcoming week 3 card for
    ARI @ SF carried a 15-16 "final" from an earlier season — a finished score
    on a game that has not kicked off, which is worse than showing none.
    """
    import polars as pl

    from src.utils.paths import get_path

    if not (season and week):
        return
    try:
        s = (pl.read_parquet(get_path("raw") / "schedules.parquet")
             .filter((pl.col("game_type") == "REG")
                     & (pl.col("season") == season) & (pl.col("week") == week))
             .drop_nulls(["home_score", "away_score"])
             .select(["home_team", "away_team", "home_score", "away_score"]))
    except Exception:                                            # noqa: BLE001
        return
    by = {(r["away_team"], r["home_team"]): r for r in s.iter_rows(named=True)}
    for c in cards.values():
        r = by.get((c["away"], c["home"]))
        if r:
            c["final_home"] = int(r["home_score"])
            c["final_away"] = int(r["away_score"])


def _attach_model(cards: dict, season: int | None = None,
                  week: int | None = None) -> None:
    """The vegas-blind model's score, where it can be produced.

    **This is the one modelled number on the page and it is not validated.**
    `game_model` is worse than the market on both margin and totals, by
    design — it cannot see the line — and its only positive result is a
    disagreement signal that has not survived a clean-room test. It is shown
    because a second opinion is the point of the page and hidden numbers help
    nobody, and it is labelled unproven everywhere it appears.

    Absent rather than wrong when the model cannot be built: a card with no
    model block reads as "no second opinion", which is true.
    """
    if not (season and week):
        return
    try:
        from src.models.game_model import predict_week
    except Exception:                                            # noqa: BLE001
        return
    try:
        # ONE fit, not the seven `walk_forward` does. That function refits per
        # season and takes minutes; it belongs in evaluation, not in an export
        # that runs every time the board is rebuilt.
        g = predict_week(season, week)
    except Exception as e:                                       # noqa: BLE001
        print(f"  game model unavailable ({e})", file=sys.stderr)
        return
    if g is None or g.is_empty():
        return
    import polars as pl

    from src.utils.paths import get_path

    # `walk_forward` is keyed by the nflverse game id; the cards are keyed by
    # the team pair the odds archive uses. Joined through the schedule rather
    # than by reformatting either, so a change to one id scheme cannot quietly
    # stop matching the other.
    try:
        sched = (pl.read_parquet(get_path("raw") / "schedules.parquet")
                 .select(["game_id", "home_team", "away_team"]))
    except Exception:                                            # noqa: BLE001
        return
    g = g.join(sched, on="game_id", how="inner")
    for r in g.iter_rows(named=True):
        c = cards.get(f"{r['away_team']}_{r['home_team']}")
        if not c:
            continue
        tot, mar = r.get("total_model"), r.get("margin_model")
        if tot is None or mar is None:
            continue
        c["model_total"] = round(float(tot), 1)
        # Signed toward the home side, like `spread`, so the two can be
        # compared without the reader working out which way each points.
        c["model_spread"] = round(-float(mar), 1)
        c["model_home"] = round((float(tot) + float(mar)) / 2, 1)
        c["model_away"] = round((float(tot) - float(mar)) / 2, 1)


def games_past(season: int | None, current: int | None) -> dict:
    """Earlier weeks of game lines, with the result attached to every side.

    A different set of weeks from the board's history. That one asks for
    play-by-play (`week_history`); this one asks whether the LINES were
    archived, and the two diverge — 2026 weeks 1 and 2 were played long before
    anything captured a spread for them, and had to be backfilled. Offering
    the board's week list here would have shown weeks with nothing in them.

    `won` is the fact this view exists for: not what the market thought, but
    which side actually cashed. Null on a push, which is not a side losing.
    """
    if not season:
        return {}
    try:
        import polars as pl

        from src.evaluation.matchups import board
        from src.evaluation.rlm import graded
    except Exception as e:                                       # noqa: BLE001
        print(f"  past game lines unavailable ({e})", file=sys.stderr)
        return {}

    try:
        g = graded([season])
    except Exception as e:                                       # noqa: BLE001
        print(f"  grading unavailable ({e})", file=sys.stderr)
        return {}
    if g.is_empty():
        return {}

    out: dict = {}
    for wk in sorted(int(w) for w in g["week"].unique()):
        if current is not None and wk >= int(current):
            continue
        b = board(season, wk)
        if b.is_empty():
            continue
        won = {(r["game_id"], r["market"], str(r["outcome"]), r["point"]):
               bool(r["won"])
               for r in g.filter(pl.col("week") == wk).iter_rows(named=True)}
        # Enrich from the RAW board columns, exactly as the live week does,
        # then attach the result. Renaming first and enriching second put the
        # two views on different key names and the shared helper on a
        # `best_odds` that no longer existed.
        rows, cards = _enrich_lines(b.to_dicts(), None, season, wk)
        for r in rows:
            k = (r["game_id"], r["market"], str(r["outcome"]), r["point"])
            # Absent, not false, on a push or an ungraded line: a push is not
            # a side losing, and counting it as one would drag every archived
            # week's record down by however often lines land on the number.
            r["won"] = won.get(k)
        if rows:
            out[str(wk)] = {"rows": rows, "cards": cards}
    return out


def bets(season: int | None) -> dict:
    """Bet definitions, each scored against the price it would be taken at.

    **Not against a flat break-even**, which is the mistake this table exists
    to avoid repeating: the first version compared every definition to 52.38%
    and reported "moneyline moved toward this side" as clearing at 62.3%.
    Those sides are favourites priced at 56.8%; beating a coin flip is not
    beating them. Every row carries its n, its interval and the price it is
    measured against, because a hit rate without those three manufactures
    exactly the belief the rest of this project spends its tests guarding
    against.
    """
    try:
        from src.evaluation.rlm import MIN_MOVE_PP, evaluate
    except Exception as e:                                       # noqa: BLE001
        print(f"  bet definitions unavailable ({e})", file=sys.stderr)
        return {}
    try:
        rows = evaluate()
    except Exception as e:                                       # noqa: BLE001
        print(f"  bet definitions unavailable ({e})", file=sys.stderr)
        return {}
    rows = [r for r in rows if r.get("n")]
    if not rows:
        return {}
    seasons = []
    try:
        import polars as pl

        from src.ingest.game_lines import LINES_PATH
        if LINES_PATH.exists():
            d = pl.read_parquet(LINES_PATH)
            seasons = sorted(int(x) for x in d["season"].unique())
    except Exception:                                            # noqa: BLE001
        pass
    return {"rows": rows, "min_move_pp": MIN_MOVE_PP, "seasons": seasons,
            "clearing": sum(1 for r in rows if r.get("clears")),
            "losing": sum(1 for r in rows if r.get("loses"))}


def build(season: int | None, week: int | None, brand: str) -> dict:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "dash_export", Path(__file__).with_name("34_export_dashboard.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    payload = mod.build(season, week)
    mk = payload.get("markets") or []
    s = season if season is not None else (mk[0].get("season") if mk else None)
    w = week if week is not None else (mk[0].get("week") if mk else None)

    # Every team's defence is on the touchdown board under the single name
    # "DEF/ST", so all 32 of them share the id `any|DEF/ST`. Starring one stars
    # them all, a saved leg cannot say which one was meant, and the settlement
    # map keyed on that name resolves 32 rows to one result. Qualified by team
    # here, where it fixes the identity and the label at once.
    for m in mk:
        for pl_ in m.get("players") or []:
            pl_["player"] = qualified_name(pl_.get("player"), pl_.get("team"))

    pos = positions(s, w) if s and w else {}
    for m in mk:
        for p in m.get("players") or []:
            if p.get("player") in pos:
                p["pos"] = pos[p["player"]]
        # Shortlist and veto rows take every FIGURE from the board, so the two
        # views cannot disagree with the table they filter. The name is the
        # exception, because the name is the join key: `qualified_name` rewrote
        # the board's "DEF/ST" to "DEF/ST (BUF)" and left these bare, so a
        # defence on either list matched nothing and dropped out of Shortlist
        # and Fades without emptying them — the failure looks like a short week.
        for key in ("rows", "vetoes"):
            for r in (m.get("shortlist") or {}).get(key) or []:
                r["player"] = qualified_name(r.get("player"), r.get("team"))

    _receptions_projections(payload, s, w)

    # The three yardage boards. Built here rather than in
    # `34_export_dashboard.py` because only site.html reads them.
    from src.prediction.yards import MARKETS as YARD_MARKETS
    payload["yards"] = {}
    for mk in sorted(YARD_MARKETS):
        print(f"  {mk}: {s} week {w}", file=sys.stderr)
        payload["yards"][mk] = yards(mk, s, w)
        if s and w:
            from src.prediction.yards import expected_quantiles
            got = expected_quantiles(mk, s, w)
            if got is not None:
                _YARD_Q[mk] = got
            _yards_projections(payload, mk, s, w)

    _attach_opens(payload, s, w)
    # After the opens are attached, because it prices against them.
    _price_open_fallback(payload)
    # And after THAT, because a row showing only an opening line is a bet the
    # rule can take, and it has no probabilities to take it on until the
    # fallback has priced it.
    _attach_ou_shortlists(payload)
    # And after that, because a row showing only an opening line is a line
    # like any other and belongs in the count.
    _mark_consensus_lines(payload)
    payload["brand"] = brand
    payload["season"] = s
    payload["week"] = w
    payload["results"] = results(s, w) if s and w else {}

    # The game-level market and the bet definitions. Both read the game-line
    # archive rather than the player board, and both are absent rather than
    # empty when it has not been captured for the week — a games tab showing
    # sixteen blank fixtures is worse than a tab that says why it is not there.
    payload["games"] = games(s, w)
    if payload["games"]:
        # Earlier weeks, keyed by week number. Gated on ARCHIVED LINES
        # rather than on play-by-play: the board's week list and this
        # one genuinely differ, and offering the board's here would
        # show weeks holding no prices at all.
        payload["games"]["past"] = games_past(s, w)
    payload["bets"] = bets(s)

    # Earlier weeks, so the board can be looked back at. Only weeks whose
    # play-by-play is on disk: an unplayed week carries `target = 0` on every
    # candidate rather than null, so grading one reads as every pick losing —
    # which is not a bad week, it is no week. See `week_history`.
    #
    # Top 100 per week rather than the whole board: 540 rows x 18 weeks would
    # add roughly 780KB to a 1.6MB payload to carry a tail nobody scrolls to.
    if s:
        try:
            from src.evaluation.week_history import ou_payload
            from src.evaluation.week_history import payload as week_payload
            payload["history"] = {
                mk: week_payload(s, mk) for mk in ("anytime_td", "first_td")}
            # And the four over/under boards, which store no per-week file and
            # are rebuilt from the archived odds instead. Without these, four
            # of the six markets offered a week selector that led nowhere.
            for mk in ("receptions", "receiving_yards", "rushing_yards",
                       "passing_yards"):
                payload["history"][mk] = ou_payload(s, mk)
        except Exception as e:                                   # noqa: BLE001
            print(f"  week history unavailable ({e})", file=sys.stderr)
            payload["history"] = {}
    return _shrink(mod.clean(payload))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="site/site.html")
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--brand", default="Pick Six",
                    help="What the header says.")
    ap.add_argument("--json", action="store_true",
                    help="write the payload as JSON beside --out and stop")
    ap.add_argument("--force", action="store_true",
                    help="publish even when artifacts predate the served model")
    ap.add_argument("--open", dest="open_after", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "dash_export", Path(__file__).with_name("34_export_dashboard.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not mod._gate(args.force):
        return 0

    print("building site ...", file=sys.stderr)
    sink = io.StringIO()
    with contextlib.nullcontext() if args.verbose else contextlib.redirect_stdout(sink):
        payload = build(args.season, args.week, args.brand)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.json:
        p = out.with_suffix(".json")
        p.write_text(json.dumps(payload, indent=1, allow_nan=False))
        print(f"wrote {p} ({p.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)
        return 0

    from src.export.site import render
    out.write_text(render(payload), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)
    if args.open_after:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
