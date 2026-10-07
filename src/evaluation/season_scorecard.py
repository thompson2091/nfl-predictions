"""How the model has actually done, week by week, against the price offered.

**AGAINST THE BOOK, NOT AGAINST ZERO.** "We said 57% and he scored" is not a
result; a coin that says 57% about favorites is right most of the time too.
Everything here is scored beside the book's own number on the same games.

**TWO KINDS OF EVIDENCE, NEVER POOLED.** The game markets come from
`archive/projections`, which freezes at kickoff — those rows are a record of
what was on the card. The player markets have no frozen board before week 5,
so they are rebuilt from today's model against archived prices: a backtest on
weeks the model did not serve, not a betting record. The page says which is
which on every section, because averaging them would quietly upgrade the
weaker claim.

**WEEKS 1 AND 2 HAVE NO GAME RECORD AND CANNOT GET ONE.** Nothing wrote a
projection before those games and the number cannot be reconstructed: the
feature matrix is rebuilt from current raw data, so recomputing a past week
gives today's model, which is a different model. Measured 2026-10-06, week 3
recomputed today disagrees with the book by 3.60 points a game where the
frozen copy disagreed by 2.32.

**ONE BET PER PLAYER-GAME.** The archive quotes alternate lines — passing
yards carried SEVENTEEN per player-game in 2026 — and counting each as a bet
turns one opinion about one quarterback into seventeen wins. Pooled over
weeks 1-4 that inflated the player edge from +0.30% to +6.89%. Only the line
closest to the player's own median survives.

**EVERY CONTIGUOUS WEEK RANGE IS PRECOMPUTED.** The page has a picker and no
arithmetic: it looks up `ranges["3-4"]`. Intervals are closed form — Wilson
for a win rate, cluster-robust by game for a return — so a range costs
nothing to add and no number on the page is computed twice in two languages.
"""
from __future__ import annotations

import math
import re
import statistics as st
from collections import defaultdict

import polars as pl

#: Touchdown markets, which have a de-vigged book price per player.
TD_MARKETS: tuple[tuple[str, str], ...] = (
    ("anytime_td", "Any touchdown"), ("first_td", "First touchdown"),
)

#: Over/under player markets, in the words a reader uses.
OU_MARKETS: tuple[tuple[str, str], ...] = (
    ("receptions", "Catches"), ("receiving_yards", "Receiving yards"),
    ("rushing_yards", "Rushing yards"), ("passing_yards", "Passing yards"),
)

#: A coin flip priced at -110 needs this to break even.
BREAK_EVEN = 0.5238


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """A win rate's interval. Wilson rather than normal, because at 16 games
    the normal approximation runs off both ends of the scale."""
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    ctr = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, ctr - half), min(1.0, ctr + half))


def _cluster_ci(by_game: dict, z: float = 1.96) -> tuple[float, float, float]:
    """Mean return and its interval, with games as the cluster.

    **THESE ARE NOT INDEPENDENT BETS.** Every receiver in one game shares a
    game script; if it turns into a shootout they all go over together. Taken
    as independent, a thousand player bets over sixteen games claim the
    precision of a thousand coin flips and have roughly the precision of
    sixteen. Cluster-robust rather than bootstrapped so a range costs nothing
    to add and the same inputs always give the same interval.
    """
    rows = [x for v in by_game.values() for x in v]
    n = len(rows)
    if n == 0:
        return (0.0, 0.0, 0.0)
    mean = sum(rows) / n
    if len(by_game) < 2:
        return (mean, mean, mean)
    # CR0: the variance of the per-game sums of the centered returns.
    ss = sum((sum(v) - len(v) * mean) ** 2 for v in by_game.values())
    g = len(by_game)
    se = math.sqrt(ss * (g / max(g - 1, 1))) / n
    return (mean, mean - z * se, mean + z * se)


def _payout(odds: float) -> float:
    return (odds / 100.0) if odds > 0 else (100.0 / abs(odds))


def _implied(odds: float) -> float:
    return (100 / (odds + 100)) if odds > 0 else (abs(odds) / (abs(odds) + 100))


# ── the games: what was frozen before kickoff ────────────────────────────

def _book_lines(season: int) -> dict:
    """The book's consensus spread, total and de-vigged home win chance."""
    out: dict = {}
    try:
        gl = pl.read_parquet("data/archive/game_lines.parquet").filter(
            pl.col("season") == season)
    except Exception:                                            # noqa: BLE001
        return out
    if gl.is_empty():
        return out
    gl = gl.with_columns(
        pl.when(pl.col("game_id").str.contains(r"^\d{4}_"))
        .then(pl.col("game_id").str.replace(r"^\d{4}_\d{2}_", ""))
        .otherwise(pl.col("game_id")).alias("pair"))
    sp = (gl.filter(pl.col("market") == "spreads")
          .with_columns(pl.when(pl.col("outcome") == pl.col("home_team"))
                        .then(pl.col("point")).otherwise(-pl.col("point"))
                        .alias("hs"))
          .group_by("pair").agg(pl.col("hs").median().alias("spread")))
    to = (gl.filter(pl.col("market") == "totals")
          .group_by("pair").agg(pl.col("point").median().alias("total")))
    h = (gl.filter((pl.col("market") == "h2h")
                   & pl.col("implied_prob").is_not_null())
         .with_columns((pl.col("outcome") == pl.col("home_team")).alias("ih"))
         .group_by(["pair", "ih"]).agg(pl.col("implied_prob").median().alias("p")))
    hw = h.filter(pl.col("ih")).select(["pair", pl.col("p").alias("a")])
    aw = h.filter(~pl.col("ih")).select(["pair", pl.col("p").alias("b")])
    ml = (hw.join(aw, on="pair", how="inner")
          .with_columns((pl.col("a") / (pl.col("a") + pl.col("b"))).alias("win")))
    for df, key in ((sp, "spread"), (to, "total"), (ml, "win")):
        for r in df.iter_rows(named=True):
            out.setdefault(r["pair"], {})[key] = r[key]
    return out


def game_rows(season: int) -> list[dict]:
    """One row per played game that has a FROZEN pre-kickoff projection."""
    from src.export import projection_freeze as PF
    from src.utils.paths import get_path

    store = PF.load(season)
    if not store:
        return []
    try:
        sched = (pl.read_parquet(get_path("raw") / "schedules.parquet")
                 .filter((pl.col("game_type") == "REG")
                         & (pl.col("season") == season)
                         & pl.col("home_score").is_not_null()))
    except Exception:                                            # noqa: BLE001
        return []
    fin = {f"{r['away_team']}_{r['home_team']}":
           (r["week"], r["home_score"] - r["away_score"],
            r["home_score"] + r["away_score"])
           for r in sched.iter_rows(named=True)}
    book = _book_lines(season)
    out = []
    for wk, games in store.items():
        for gid, snap in games.items():
            got, bk = fin.get(gid), book.get(gid)
            if not got or not bk:
                continue
            if bk.get("spread") is None or bk.get("total") is None:
                continue
            out.append({
                "week": int(wk), "game_id": gid,
                "margin": got[1], "total_actual": got[2],
                "book_spread": bk["spread"], "book_total": bk["total"],
                "book_win": bk.get("win"),
                "model_spread": snap.get("model_spread"),
                "model_total": snap.get("model_total"),
                "model_win": snap.get("model_win_home"),
                "blend_spread": (snap.get("blend") or {}).get("spread"),
                "blend_total": (snap.get("blend") or {}).get("total"),
                # Frozen only from week 5 on. Older snapshots lack them and
                # the rows below read None as "not recorded", never recompute.
                "blend_win": (snap.get("blend") or {}).get("win_home"),
                "model_total_centered": snap.get("model_total_centered"),
                "blend_total_centered":
                    (snap.get("blend") or {}).get("total_centered"),
            })
    return out


def _side_record(rows, pick_key, line_key, result_key, sign=1):
    """Wins, losses and pushes for the side a number picks against a line."""
    w = l = push = 0
    for r in rows:
        if r.get(pick_key) is None:
            continue
        edge = sign * (r[pick_key] - r[line_key])
        res = sign * (r[result_key] - r[line_key])
        if abs(edge) < 1e-9:
            continue
        if abs(res) < 1e-9:
            push += 1
            continue
        if (edge > 0) == (res > 0):
            w += 1
        else:
            l += 1
    lo, hi = _wilson(w, w + l)
    return {"w": w, "l": l, "push": push, "n": w + l,
            "pct": (w / (w + l)) if (w + l) else None, "lo": lo, "hi": hi}


def _mae(rows, key, actual_key, sign=1):
    vals = [abs(sign * r[key] - r[actual_key]) for r in rows
            if r.get(key) is not None]
    return (sum(vals) / len(vals)) if vals else None


def games_block(rows: list[dict]) -> dict | None:
    if not rows:
        return None
    n = len(rows)
    ml_rows = [r for r in rows if r.get("model_win") is not None
               and r.get("book_win") is not None]

    def straight(key):
        w = sum(1 for r in ml_rows if (r[key] > 0.5) == (r["margin"] > 0))
        lo, hi = _wilson(w, len(ml_rows))
        return {"w": w, "l": len(ml_rows) - w, "n": len(ml_rows),
                "pct": (w / len(ml_rows)) if ml_rows else None,
                "lo": lo, "hi": hi}

    dis = [r for r in ml_rows if (r["model_win"] > 0.5) != (r["book_win"] > 0.5)]
    dw = sum(1 for r in dis if (r["model_win"] > 0.5) == (r["margin"] > 0))
    dlo, dhi = _wilson(dw, len(dis))
    brier = lambda k: (sum((r[k] - (1 if r["margin"] > 0 else 0)) ** 2
                           for r in ml_rows) / len(ml_rows)) if ml_rows else None

    # The blended win chance is frozen only from week 5, so it is scored on
    # its own rows, with the book beside it on exactly those games. Sharing
    # `ml_rows` would compare it against a book record over different games.
    bl_rows = [r for r in ml_rows if r.get("blend_win") is not None]
    bw = sum(1 for r in bl_rows if (r["blend_win"] > 0.5) == (r["margin"] > 0))
    blo, bhi = _wilson(bw, len(bl_rows))
    brier_on = lambda k: (sum((r[k] - (1 if r["margin"] > 0 else 0)) ** 2
                              for r in bl_rows) / len(bl_rows)) if bl_rows else None

    # Spread: a home-signed number against a home-signed line, so the side
    # picked is whichever way the two disagree. `-margin` is the result in
    # the same frame as the line.
    for r in rows:
        r["_res_spread"] = -r["margin"]
    spread = {
        "model": _side_record(rows, "model_spread", "book_spread", "_res_spread", -1),
        "blend": _side_record(rows, "blend_spread", "book_spread", "_res_spread", -1),
        "mae_model": _mae(rows, "model_spread", "_res_spread"),
        "mae_blend": _mae(rows, "blend_spread", "_res_spread"),
        "mae_book": _mae(rows, "book_spread", "_res_spread"),
        "mae_book_blend": _mae([r for r in rows if r.get("blend_spread") is not None],
                               "book_spread", "_res_spread"),
    }
    total = {
        "model": _side_record(rows, "model_total", "book_total", "total_actual"),
        "blend": _side_record(rows, "blend_total", "book_total", "total_actual"),
        "mae_model": _mae(rows, "model_total", "total_actual"),
        "mae_blend": _mae(rows, "blend_total", "total_actual"),
        "mae_book": _mae(rows, "book_total", "total_actual"),
        "mae_book_blend": _mae([r for r in rows if r.get("blend_total") is not None],
                               "book_total", "total_actual"),
        "over": sum(1 for r in rows if r.get("model_total") is not None
                    and r["model_total"] > r["book_total"]),
        # The model with its weekly level removed (`game_blend`), beside the
        # raw one rather than instead of it.
        "centered": _side_record(rows, "model_total_centered", "book_total",
                                 "total_actual"),
        "blend_centered": _side_record(rows, "blend_total_centered",
                                       "book_total", "total_actual"),
        "mae_centered": _mae(rows, "model_total_centered", "total_actual"),
        "mae_blend_centered": _mae(rows, "blend_total_centered", "total_actual"),
        "mae_book_centered": _mae(
            [r for r in rows if r.get("model_total_centered") is not None],
            "book_total", "total_actual"),
        "over_centered": sum(1 for r in rows
                             if r.get("model_total_centered") is not None
                             and r["model_total_centered"] > r["book_total"]),
    }
    return {
        "n": n, "weeks": sorted({r["week"] for r in rows}),
        "moneyline": {
            "ours": straight("model_win"), "book": straight("book_win"),
            "disagree": {"w": dw, "l": len(dis) - dw, "n": len(dis),
                         "pct": (dw / len(dis)) if dis else None,
                         "lo": dlo, "hi": dhi},
            "brier_ours": brier("model_win"), "brier_book": brier("book_win"),
            "blend": {"w": bw, "l": len(bl_rows) - bw, "n": len(bl_rows),
                      "pct": (bw / len(bl_rows)) if bl_rows else None,
                      "lo": blo, "hi": bhi},
            "brier_blend": brier_on("blend_win"),
            "brier_book_blend": brier_on("book_win"),
        },
        "spread": spread, "total": total,
    }


# ── the players: rebuilt, and labeled as such ───────────────────────────

def _one_per_player(rows: list[dict]) -> list[dict]:
    """The line nearest that player's median, so one opinion is one bet.

    The archive quotes alternates — passing yards carried seventeen lines per
    player-game in 2026 — and counting each as its own bet turned one view of
    one quarterback into seventeen wins. Chosen on the line alone, before any
    edge is read, so a threshold cannot shop among them.
    """
    per: dict = defaultdict(list)
    for r in rows:
        if r.get("won") is None or r.get("odds") is None:
            continue
        per[(r.get("game_id"), r.get("player_name"))].append(r)
    keep = []
    for rs in per.values():
        med = st.median([x["line"] for x in rs])
        keep.append(min(rs, key=lambda x: (abs(x["line"] - med),
                                           -abs(x.get("edge") or 0))))
    return keep


def _model_only_side(rows: list[dict]) -> list[dict]:
    """The same rows with the side the UNBLENDED model would have taken.

    `ou_week` sets `side` from `ours` — the served number, which on these
    markets is already pulled toward the price. `model` on the same row is
    `model_only`. Re-deriving `side` and `won` from it is the only way to put
    the model and the card's adjusted number side by side on one set of
    games; settlement then runs over it unchanged, so the under still pays at
    the under's price and a man who did not play is still void.
    """
    out = []
    for r in rows:
        r = dict(r)
        m, line, got = r.get("model"), r.get("line"), r.get("actual")
        if m is None or line is None:
            r["side"] = None
            r["won"] = None
        else:
            r["side"] = "over" if m >= 0.5 else "under"
            r["won"] = (None if got is None or float(got) == float(line)
                        else (float(got) > float(line)) == (r["side"] == "over"))
        out.append(r)
    return out


def _rule_side(rows: list[dict], sides: dict, want: str | None = None
               ) -> list[dict]:
    """The rows the shortlist takes, on the side IT takes rather than ours.

    `want` narrows to one side, which is what Fades is: on a two-sided line a
    fade is not a separate population but the shortlist's under picks, so it
    is a SUBSET of the shortlist and the card says so.

    `won` is re-derived here because the side changed. A line the rule bets
    under and we bet over is one bet with two possible results, and carrying
    our result under the rule's name is how a filter starts reporting the
    board's record.
    """
    out = []
    for r in rows:
        side = sides.get((r.get("player_name"), r.get("line")))
        if side is None or (want is not None and side != want):
            continue
        r = dict(r)
        r["side"] = side
        got, line = r.get("actual"), r.get("line")
        r["won"] = (None if got is None or line is None
                    or float(got) == float(line)
                    else (float(got) > float(line)) == (side == "over"))
        out.append(r)
    return out


def _with_streak(rows: list[dict], flags: dict, week: int,
                 market: str) -> list[dict]:
    """Only the bets on a player the streak rule flagged that week.

    A FILTER ON PLAYERS, NOT ON LINES, which is why it narrows the bets
    already chosen rather than picking its own. A streak is not a side until
    something bets one — the board flags the player and the bet is still
    whichever side our number took — so the shape here is the board's shape
    and the return is our return on a flagged man.
    """
    return [r for r in rows
            if flags.get((week, market, r.get("player_name"))) is not None]


def ou_rows(season: int, weeks) -> dict:
    """One bet per player-game per market, for each week. Cached by caller.

    Carries every view the players board offers, each as its own set of bets
    rather than as a flag on one set, because two of them do not bet the same
    line or the same side. See `board_views`.
    """
    from src.evaluation import board_views as BV
    from src.evaluation.prop_edge import qualifying
    from src.evaluation.prop_settlement import (participation, settle_rows,
                                                side_prices)
    from src.evaluation.week_history import ou_week

    # SETTLED THE WAY A BOOK SETTLES. `ou_week` carries one price, the
    # over's, so an under used to be paid at the over's number; and a man
    # who played and recorded nothing had no stat row and dropped out, which
    # was usually a winning under. Over weeks 3-4 of 2026 the two together
    # showed +$0.23 per $100 where book settlement gives -$6.47. A man who
    # did not play is void.
    prices, played = side_prices(season), participation(season)
    out: dict = {}
    # The streak flags for every week at once, because the baseline each one
    # is judged against is a pass over the whole population and there is no
    # reason to make it four.
    boards: dict = {}
    for mk, _ in OU_MARKETS:
        for wk in weeks:
            try:
                boards[(mk, wk)] = ou_week(season, wk, mk) or []
            except Exception:                                    # noqa: BLE001
                boards[(mk, wk)] = []
    try:
        streak = BV.streak_flags(
            season, weeks,
            {r.get("player_name") for v in boards.values() for r in v},
            [mk for mk, _ in OU_MARKETS])
    except Exception:                                            # noqa: BLE001
        streak = {}
    for mk, _ in OU_MARKETS:
        for wk in weeks:
            try:
                raw = boards[(mk, wk)]
                got = settle_rows(season, mk, raw, prices=prices, played=played)
                # AND THE RAW MODEL'S OWN SIDE. `ou_week` picks its side from
                # `ours`, which is the SERVED number — already blended toward
                # the market. So the row the card has always shown is the
                # adjusted model, not the model, and there was no way to see
                # what the model alone would have done. `model_only` is the
                # unblended number; re-deriving the side and the result from
                # it gives the two a like-for-like comparison.
                mo = settle_rows(season, mk, _model_only_side(raw),
                                 prices=prices, played=played)
            except Exception:                                    # noqa: BLE001
                raw, got, mo = [], [], []
            out[(mk, wk)] = _one_per_player(got)
            out[("model", mk, wk)] = _one_per_player(mo)
            # The pre-registered edge rule (`prop_edge`): only the bets whose
            # blended edge clears the fitted threshold, at the side's own price.
            try:
                out[("edge", mk, wk)] = [r for r in qualifying(season, mk, raw)
                                         if r.get("won") is not None]
            except Exception:                                    # noqa: BLE001
                out[("edge", mk, wk)] = []
            # THE SHORTLIST, ON ALL ITS LINES AND THEN REDUCED TO ONE.
            #
            # The rule is applied to every line, which is the population it
            # was fitted on — `_attach_ou_shortlists` is explicit that a
            # board already narrowed to one line per player is a different
            # population. Only after it has picked are the picks reduced to
            # one bet per player-game, because passing yards had the rule
            # taking EIGHT lines on one quarterback in week 3 and counting
            # those as eight bets is the same inflation that once turned a
            # +0.30% player edge into +6.89%.
            try:
                sides = BV.shortlist_sides(raw, mk)
            except Exception:                                    # noqa: BLE001
                sides = {}
            for key, want in (("short", None), ("fade", "under")):
                picks = settle_rows(season, mk, _rule_side(raw, sides, want),
                                    prices=prices, played=played)
                out[(key, mk, wk)] = _one_per_player(picks)
            # Streaks narrows the bets already chosen, on both sides, so the
            # filter is comparable with the unfiltered rows above it.
            out[("streak", mk, wk)] = _with_streak(out[(mk, wk)], streak,
                                                   wk, mk)
            out[("streak_model", mk, wk)] = _with_streak(
                out[("model", mk, wk)], streak, wk, mk)
            # And stamped on the rows the per-leg table reads, so section 06
            # can mark a flagged player without a second lookup in the page.
            for key in ((mk, wk), ("model", mk, wk)):
                for r in out[key]:
                    r["streak"] = streak.get((wk, mk, r.get("player_name")))
    return out


def _series(cache: dict, weeks, kind: str | None,
            price_key: str = "odds") -> tuple[list, dict]:
    """One set of bets per market, pooled over a week range.

    `kind` picks which set: None is the card's adjusted number, "model" the
    unblended one, "edge" the pre-registered rule. All three are settled the
    same way and priced at the side actually taken, so the three rows on the
    card are a like-for-like comparison rather than three different
    accountings.
    """
    out, grand = [], defaultdict(list)
    for mk, label in OU_MARKETS:
        key = (lambda w: (mk, w)) if kind is None else (lambda w: (kind, mk, w))
        rows = [r for w in weeks for r in cache.get(key(w), [])]
        if not rows:
            out.append({"key": mk, "label": label, "bets": 0})
            continue
        by_game = defaultdict(list)
        for r in rows:
            ret = _payout(r[price_key]) if r["won"] else -1.0
            by_game[r["game_id"]].append(ret)
            grand[r["game_id"]].append(ret)
        roi, lo, hi = _cluster_ci(by_game)
        row = {"key": mk, "label": label, "bets": len(rows),
               "hit": sum(1 for r in rows if r["won"]) / len(rows),
               "be": st.mean([_implied(r[price_key]) for r in rows]),
               "roi": roi, "lo": lo, "hi": hi}
        if kind == "edge":
            row["threshold_pp"] = rows[0].get("threshold_pp")
        out.append(row)
    return out, grand


def players_block(cache: dict, weeks, td_by_week: dict) -> dict:
    # THREE ROWS, ONE SET OF GAMES. `ou_week` picks its side from the SERVED
    # number, so what the card has always shown under "player bets" is the
    # adjusted model. The model's own side is a separate series, and the
    # book is the break-even column rather than a row — a sportsbook does
    # not pick a side, and grading "always take the favorite" would be a
    # strategy nobody runs.
    ou, grand = _series(cache, weeks, None)
    model, mgrand = _series(cache, weeks, "model")
    edge, egrand = _series(cache, weeks, "edge", price_key="price")
    roi, lo, hi = _cluster_ci(grand)
    mroi, mlo, mhi = _cluster_ci(mgrand)
    eroi, elo, ehi = _cluster_ci(egrand)
    td = []
    for mk, label in TD_MARKETS:
        got = [td_by_week[(mk, w)] for w in weeks if td_by_week.get((mk, w))]
        if not got:
            continue
        n = sum(x["n"] for x in got)
        if not n:
            continue
        sm = ([x for x in got if x.get("said_model") is not None]
              if all(x.get("said_model") is not None for x in got) else [])
        td.append({"key": mk, "label": label, "rows": n,
                   "said": sum(x["said"] * x["n"] for x in got) / n,
                   "said_model": (sum(x["said_model"] * x["n"] for x in sm) / n
                                  if sm else None),
                   "actual": sum(x["actual"] * x["n"] for x in got) / n})
    # ── THE BOARD'S OWN FOUR VIEWS ──────────────────────────────────────
    #
    # Everyone, Shortlist, Fades and Streaks, each scored on ITS OWN BETS.
    # Not a flag on one set of bets: the shortlist picks its own line and its
    # own side, so a flag would report our record under the rule's name. See
    # `board_views`.
    #
    # Shortlist and Fades carry one series, because the rule picks the side.
    # Everyone and Streaks carry two, ours and the adjusted one, since there
    # the side is still ours to take.
    views: dict = {"all": {"ou": ou, "all": {
                       "bets": sum(len(v) for v in grand.values()),
                       "roi": roi, "lo": lo, "hi": hi},
                   "model": model, "model_all": {
                       "bets": sum(len(v) for v in mgrand.values()),
                       "roi": mroi, "lo": mlo, "hi": mhi},
                   "sides": 2}}
    for key, kinds in (("short", ("short", None)),
                       ("fade", ("fade", None)),
                       ("streak", ("streak", "streak_model"))):
        blk: dict = {"sides": 2 if kinds[1] else 1}
        s, g = _series(cache, weeks, kinds[0])
        r2, l2, h2 = _cluster_ci(g)
        blk["ou"] = s
        blk["all"] = {"bets": sum(len(v) for v in g.values()),
                      "roi": r2, "lo": l2, "hi": h2}
        if kinds[1]:
            s2, g2 = _series(cache, weeks, kinds[1])
            r3, l3, h3 = _cluster_ci(g2)
            blk["model"] = s2
            blk["model_all"] = {"bets": sum(len(v) for v in g2.values()),
                                "roi": r3, "lo": l3, "hi": h3}
        views[key] = blk
    return {"weeks": sorted(weeks), "ou": ou, "td": td, "views": views,
            # `ou` is the ADJUSTED model — `ou_week` sides on the served
            # number — and `model` is the same bets sided on the unblended
            # one. Named for what they are rather than for which came first.
            "all": {"bets": sum(len(v) for v in grand.values()),
                    "roi": roi, "lo": lo, "hi": hi},
            "model": model,
            "model_all": {"bets": sum(len(v) for v in mgrand.values()),
                          "roi": mroi, "lo": mlo, "hi": mhi},
            "edge": edge,
            "edge_all": {"bets": sum(len(v) for v in egrand.values()),
                         "roi": eroi, "lo": elo, "hi": ehi}}



#: One bet per player-game-market, shipped per week rather than per range.
#:
#: EVERY OTHER NUMBER ON THE RECORD PAGE IS PRECOMPUTED PER RANGE, and this
#: one cannot be. There are 153 contiguous ranges in an 18-week season, so a
#: per-player table precomputed for each would ship the same bet about a
#: hundred and fifty times. Shipped per week it is linear, and the page adds
#: up the weeks the reader picked.
#:
#: THE ADDITION IS THE ONLY THING THE PAGE DOES. Every per-leg number — the
#: side taken, whether it won, what it returned — is computed here, by the
#: same `_payout` the pooled rows use, and `tests/js/v3app.js` sums the legs
#: back up and checks the total against `players.all.roi`. So the page is
#: not a second implementation of the accounting; it is a sum over numbers
#: this module produced.
#:
#: Compact on purpose. Names go in a table and legs are positional arrays,
#: because the obvious shape — a dict per leg with eight string keys — was
#: 3.4x the bytes for the same information, on a payload already past 5 MB.
#:
#: A leg is:
#:
#:     [market, line, actual, adj_side, adj_ret, model_side, model_ret,
#:      edge_ret, streak, adj_price, model_price, edge_price]
#:
#: where `market` indexes `markets`, a side is 1 for over and 0 for under,
#: and a return is per $1 staked — positive means it won, so `won` is not
#: stored twice. `edge_ret` is null unless the pre-registered rule took this
#: leg, and is priced at that side's own price, which is why it is not
#: `adj_ret` with a flag.
#:
#: `streak` is 1 where the player was running over, 2 under, null otherwise,
#: as of THAT WEEK — see `streaks`. It is a flag rather than a return because
#: a streak is a filter on players and bets no line of its own. The
#: shortlist and the fades are NOT flags here for the opposite reason: they
#: pick their own line and their own side, so they are separate bets and live
#: in `players_block`'s `views`.
#: THE PRICE PAID, PER SERIES, rather than one price per leg. The three
#: series do not always take the same side — over weeks 3-4 the model and
#: the card disagreed on 9 of the edge rule's 77 picks — and an under is
#: paid at the under's own number, so one price would be the wrong one for
#: whichever series took the other side. Not derived from the return
#: either: a loser returns exactly -1 whatever it was priced at, so the
#: price is simply gone unless it is carried.
BET_FIELDS = ("market", "line", "actual", "adj_side", "adj_ret",
              "model_side", "model_ret", "edge_ret", "streak",
              "adj_price", "model_price", "edge_price")


def _ret(row, price_key="odds"):
    """What one leg returned per $1. Positive means it won."""
    if row is None or row.get("won") is None:
        return None
    return round(_payout(row[price_key]) if row["won"] else -1.0, 6)


def bets_block(cache: dict, weeks) -> dict:
    """Every graded leg, grouped by week and then by player-game.

    Grouped by PLAYER-GAME rather than by player, because that is the shape
    the correlation lives in: over weeks 3-4, 464 player-games carried two
    or more legs and 222 of them — 48% — had every leg land the same way. A
    receiver who clears his catches number has almost always cleared his
    yards number, so six legs on one man is nearer one and a half opinions
    than six. A per-player total alone cannot show that; this can.
    """
    from src.evaluation.prop_settlement import _norm

    names: dict[str, int] = {}
    mkeys = [mk for mk, _ in OU_MARKETS]
    # (week, game_id, player_key) -> market -> leg, filled from the UNION of
    # the three series rather than from the card's rows alone.
    #
    # THE UNION, BECAUSE THE EDGE RULE REACHES PLAYERS THE CARD'S ROWS DO
    # NOT, and a leg dropped here is a leg this section reports and the
    # totals above it do not. Built from the card's rows only, over weeks
    # 3-4 of 2026, this returned 65 of the 69 edge bets at +11.65% against
    # the published +13.36%.
    #
    # Keyed on the CANONICAL normalised name for the same reason. All four
    # of those missing bets were one join: `prop_edge` keys on
    # `prop_settlement._norm`, which strips punctuation and the generational
    # suffix, and a local `.strip().lower()` does not — so "J.K. Dobbins"
    # and "jk dobbins", "Michael Penix Jr." and "michael penix", "Kenneth
    # Walker III" and "kenneth walker" each failed to meet.
    acc: dict = defaultdict(dict)
    shown: dict = {}
    team_of: dict = {}
    for mi, mk in enumerate(mkeys):
        for w in weeks:
            series = {k: cache.get(key, []) for k, key in
                      (("adj", (mk, w)), ("model", ("model", mk, w)),
                       ("edge", ("edge", mk, w)))}
            keyed: dict = {}
            for which, rows in series.items():
                raw = [r.get("player_name") or "" for r in rows]
                for r, n in zip(rows, _norm(raw)):
                    if r.get("won") is None:
                        continue
                    k = (r["game_id"], n)
                    keyed.setdefault(k, {})[which] = r
                    shown.setdefault(k, r.get("player_name") or n)
                    if r.get("team"):
                        team_of.setdefault(k, r["team"])
            for k, got in keyed.items():
                r, m, e = got.get("adj"), got.get("model"), got.get("edge")
                any_ = r or m or e
                names.setdefault(shown[k], len(names))
                st = (r or m or {}).get("streak")
                acc[(w,) + k][mi] = [
                    mi,
                    (r or e or m).get("line", (e or {}).get("point")),
                    any_.get("actual"),
                    None if not r else (1 if r.get("side") == "over" else 0),
                    _ret(r),
                    None if not m else (1 if m.get("side") == "over" else 0),
                    _ret(m),
                    _ret(e, "price"),
                    1 if st == "over" else 2 if st == "under" else None,
                    None if not r else r.get("odds"),
                    None if not m else m.get("odds"),
                    None if not e else e.get("price"),
                ]
    out: dict = defaultdict(list)
    teams: dict = {}
    for (w, gid, key), legs in sorted(acc.items()):
        # The club is a fact about the player-game, not about a leg, so it
        # rides on the entry rather than on each of its three lines.
        tm = team_of.get((gid, key))
        if tm and tm not in teams:
            teams[tm] = len(teams)
        out[str(w)].append([names[shown[(gid, key)]], gid,
                            [legs[i] for i in sorted(legs)],
                            teams.get(tm) if tm else None])
    return {"players": [n for n, _ in sorted(names.items(), key=lambda x: x[1])],
            "teams": [n for n, _ in sorted(teams.items(), key=lambda x: x[1])],
            "markets": [lb for _, lb in OU_MARKETS],
            "market_keys": mkeys,
            "weeks": dict(out)}


def _td_week(season: int, week: int, market: str) -> dict | None:
    from src.evaluation.week_history import week_board

    try:
        b = week_board(season, week, market)
    except Exception:                                            # noqa: BLE001
        return None
    if b.is_empty() or not {"probability", "book", "scored"} <= set(b.columns):
        return None
    d = b.filter(pl.col("book").is_not_null() & pl.col("scored").is_not_null()
                 & pl.col("probability").is_not_null())
    if d.is_empty():
        return None
    # `probability` is the served number, which becomes the market blend on
    # any week served with one (first TD, behind `use_market_blend`). The
    # raw model is kept beside it, so the row never turns into the blend
    # without saying so.
    said_model = (float(d["prob_model"].mean())
                  if "prob_model" in d.columns
                  and d["prob_model"].null_count() == 0 else None)
    return {"n": d.height, "said": float(d["probability"].mean()),
            "said_model": said_model,
            "actual": float(d["scored"].mean())}


def build(season: int) -> dict:
    """Every contiguous week range, each with both halves of the evidence."""
    from src.evaluation.week_history import played_weeks

    played = sorted(played_weeks(season))
    grows = game_rows(season)
    gweeks = sorted({r["week"] for r in grows})
    cache = ou_rows(season, played)
    td_by_week = {(mk, w): _td_week(season, w, mk)
                  for mk, _ in TD_MARKETS for w in played}

    ranges: dict = {}
    for i, a in enumerate(played):
        for b in played[i:]:
            sel = [w for w in played if a <= w <= b]
            g = [r for r in grows if a <= r["week"] <= b]
            ranges[f"{a}-{b}"] = {
                "weeks": sel,
                "games": games_block(g),
                "players": players_block(cache, sel, td_by_week),
            }
    # Weeks a game record cannot exist for, said once rather than per range.
    missing = [{"week": w,
                "why": "nothing recorded a projection before these games, and "
                       "the feature matrix is rebuilt from current data, so "
                       "there is no honest way to reconstruct one"}
               for w in played if w not in gweeks]
    return {
        "season": season, "played": played,
        "game_weeks": gweeks, "player_weeks": played,
        "ranges": ranges,
        "default": f"{gweeks[0]}-{played[-1]}" if gweeks
                   else (f"{played[0]}-{played[-1]}" if played else ""),
        "missing": missing,
        "break_even": BREAK_EVEN,
        # Per week, not per range — see `bets_block`. The page adds up the
        # weeks the picker is showing.
        "bets": bets_block(cache, played),
    }
