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
        pool = (pl.scan_parquet(feats)
                .filter((pl.col("season") == season) & (pl.col("week") == wk))
                .select(["player_id", "player_name"]).collect()
                .unique(subset=["player_id"]))
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
        for pid, name in pool.iter_rows():
            out[f"{week}|{key}|{name}"] = "hit" if pid in scorers else "miss"
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
        })
    rec["rows"] = (rec.get("rows") or []) + extra
    rec["priced_rows"] = len(priced)


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

    pos = positions(s, w) if s and w else {}
    for m in mk:
        for p in m.get("players") or []:
            if p.get("player") in pos:
                p["pos"] = pos[p["player"]]
        # Shortlist and veto rows need no enrichment: the page reads them as a
        # set of names and takes every figure from the board, so the two views
        # cannot disagree with the table they filter.

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
    # And after that, because a row showing only an opening line is a line
    # like any other and belongs in the count.
    _mark_consensus_lines(payload)
    payload["brand"] = brand
    payload["season"] = s
    payload["week"] = w
    payload["results"] = results(s, w) if s and w else {}
    return mod.clean(payload)


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
