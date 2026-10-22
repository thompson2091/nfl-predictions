"""90% floors: the highest line each player clears nine times in ten.

Asked for 2026-10-21 as INFORMATION, not as bets — for fantasy, pick'em and
reference. The safe-legs backtest (`safe_legs`, `scripts/69_safe_legs.py`)
settled the betting question first: the model's near-certain alternate rungs
were well calibrated on 2025 and still lost about $3 per $100 at the book's
price, because an over-only ladder carries the whole vig on one side. So this
is a floor to read, never a leg to buy, and every screen that shows it says so.

**WHAT A FLOOR IS.** For one player, one market and one game: the highest
half-point line L (0.5, 1.5, ... — every rung a book posts is on this grid)
where the CALIBRATED probability of going over L is at least the target
(`config/safe_legs.yaml: min_prob`, 0.90). Read off the same distribution the
board prices with — the quantile curve for yardage, the negative binomial for
catches — so a floor never disagrees with the board's own number for a line.

**WHY NOT THE SERVED CALIBRATION.** `ou_calibration` is a Platt layer fitted at
each player's MEDIAN line, where the raw distribution is about twice too
sharp (slope 0.45-0.56 in the 2026-10-20 fit). Applied in the tail it
flattens everything: at that slope a raw 0.999 calibrates to about 0.98 and a
raw 0.95 to about 0.80, so the 90% line would sit far below where the model's
tail actually lands. The tail is a different region of the same curve and
gets its own two numbers, fitted the same way (`ou_calibration.fit`) on
2024 only, on the lines a floor is read from rather than on the median.
Measured, not argued: `scripts/75_floors.py` reports both.

**HOW IT IS GRADED.** A floor is a claim about every player the board shows,
so the backtest covers every player-game the model priced, not only those a
book posted an alternate ladder for. Settled like a book: a player with an
offensive snap and no stat line is graded at zero, a player with neither is
void (`safe_legs.game_logs`). Half-point lines cannot push.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import polars as pl

#: The four over/under markets, in the order the page shows them.
MARKETS: tuple[str, ...] = ("receptions", "receiving_yards", "rushing_yards",
                            "passing_yards")
LABELS = {"receptions": "Catches", "receiving_yards": "Receiving yards",
          "rushing_yards": "Rushing yards", "passing_yards": "Passing yards"}

#: The highest line each market's grid reaches. No one's 90% floor is near
#: these; they bound the grid, not the answer.
GRID_TOP = {"receptions": 20.5, "receiving_yards": 250.5,
            "rushing_yards": 250.5, "passing_yards": 500.5}

#: Raw over-probabilities a calibration row is taken at, per player-game:
#: the highest line whose raw chance clears each of these. Equal weight per
#: player-game, and all of it in the region a floor is read from.
FIT_LEVELS: tuple[float, ...] = (0.50, 0.60, 0.70, 0.80, 0.85, 0.90, 0.93,
                                 0.95, 0.97, 0.98, 0.99)

#: Where the fitted tail calibration and the backtest are written.
OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "floors"
CAL_FILE = "calibration.json"
BACKTEST_FILE = "backtest.json"

#: The freeze keys: one entry per market, beside that market's own board.
FREEZE_SUFFIX = "_floor"


def target() -> float:
    """The owner's "nearly sure", from `config/safe_legs.yaml`."""
    from src.evaluation.safe_legs import settings

    return float(settings()["min_prob"])


def grid(market: str) -> np.ndarray:
    """Every half-point line from 0.5 to the market's top."""
    return np.arange(0.5, GRID_TOP[market] + 0.5, 1.0)


# --------------------------------------------------------------------------
# The distribution, read at every line
# --------------------------------------------------------------------------

def raw_over_grid(market: str, dist: np.ndarray, lines: np.ndarray,
                  levels=None, dispersion: float | None = None) -> np.ndarray:
    """(n, len(lines)) raw P(over L) for each row's distribution.

    `dist` is the (n, k) quantile matrix for a yardage market, or the (n,)
    expected counts for catches (with `dispersion`). Half-point lines carry no
    push, so this is the over probability the board itself computes.
    Non-increasing along each row by construction; forced so anyway, because
    the floor search below assumes it.
    """
    lines = np.asarray(lines, dtype=float)
    n = len(dist)
    out = np.empty((n, len(lines)), dtype=float)
    if n == 0:
        return out
    if market == "receptions":
        from src.models.count import prob_over
        if dispersion is None:
            raise ValueError("catches need the fitted dispersion")
        mu = np.asarray(dist, dtype=float)
        for j, L in enumerate(lines):
            out[:, j] = prob_over(mu, np.full(n, L), dispersion)[0]
    else:
        from src.models.yards import QUANTILE_LEVELS, prob_over, rearrange
        q = rearrange(np.asarray(dist, dtype=float))
        lv = tuple(levels or QUANTILE_LEVELS)
        for j, L in enumerate(lines):
            out[:, j] = prob_over(q, np.full(n, L), lv)[0]
    return np.minimum.accumulate(out, axis=1)


def floor_index(p: np.ndarray, tgt: float) -> np.ndarray:
    """Per row, the index of the highest line with p >= tgt, or -1 if none.

    `p` is non-increasing along each row, so that is the count of qualifying
    lines minus one.
    """
    p = np.asarray(p, dtype=float)
    return (p >= tgt).sum(axis=1).astype(int) - 1


def floors(p_cal: np.ndarray, lines: np.ndarray, tgt: float
           ) -> tuple[np.ndarray, np.ndarray]:
    """(floor line, calibrated chance at it) per row; NaN where none clears."""
    ix = floor_index(p_cal, tgt)
    has = ix >= 0
    safe = np.where(has, ix, 0)
    rows = np.arange(len(ix))
    line = np.where(has, np.asarray(lines, dtype=float)[safe], np.nan)
    chance = np.where(has, p_cal[rows, safe] if len(ix) else np.nan, np.nan)
    return line, chance


# --------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------

def fit_rows(p_raw: np.ndarray, lines: np.ndarray, actual: np.ndarray,
             levels: tuple[float, ...] = FIT_LEVELS) -> tuple[np.ndarray, np.ndarray]:
    """(raw p, went over) pairs for fitting: one per player-game and level.

    The line for a level is the highest one whose raw chance clears it, so
    each player-game contributes the same number of rows wherever his
    distribution sits, and the rows are the lines a floor would be read from.
    A line repeated across levels counts once.
    """
    xs, ys = [], []
    lines = np.asarray(lines, dtype=float)
    actual = np.asarray(actual, dtype=float)
    for i in range(p_raw.shape[0]):
        seen = set()
        for lv in levels:
            j = int((p_raw[i] >= lv).sum()) - 1
            if j < 0 or j in seen:
                continue
            seen.add(j)
            xs.append(p_raw[i, j])
            ys.append(1.0 if actual[i] > lines[j] else 0.0)
    return np.asarray(xs), np.asarray(ys)


def fit_tail(p_raw: np.ndarray, y: np.ndarray) -> dict:
    """The two-number Platt map, `ou_calibration`'s own fit, on tail rows."""
    from src.models.ou_calibration import fit
    return fit(p_raw, y)


def calibrate(p_raw: np.ndarray, cal: dict | None) -> np.ndarray:
    """`ou_calibration.apply`, which passes the raw number through if unfitted."""
    from src.models.ou_calibration import apply
    return np.asarray(apply(p_raw, cal), dtype=float).reshape(np.shape(p_raw))


def load_calibration(out_dir: Path | None = None) -> dict:
    """`{market: {a, b, ...}}` as `scripts/75_floors.py` wrote it, or {}."""
    p = (out_dir or OUT_DIR) / CAL_FILE
    try:
        got = json.loads(p.read_text())
    except Exception:                                            # noqa: BLE001
        return {}
    return {m: c for m, c in (got.get("markets") or {}).items()
            if isinstance(c, dict) and {"a", "b"} <= set(c) and c["b"] > 0}


def load_backtest(out_dir: Path | None = None) -> dict:
    p = (out_dir or OUT_DIR) / BACKTEST_FILE
    try:
        return json.loads(p.read_text())
    except Exception:                                            # noqa: BLE001
        return {}


# --------------------------------------------------------------------------
# One week's distributions, for every candidate
# --------------------------------------------------------------------------

def week_dists(market: str, season: int, week: int, arts: dict | None = None
               ) -> tuple[pl.DataFrame, np.ndarray, dict] | None:
    """(ids, distribution, meta) for every candidate the served model prices.

    The serving path itself (`expected_quantiles` / `expected_counts`), with
    the vacated-workload adjustment the board applies, so a backtest floor and
    a live one come from the same number.
    """
    arts = arts if arts is not None else {}
    if market == "receptions":
        from src.prediction import receptions as rec
        art = arts.get(market) or rec.load_model()
        if art is None:
            return None
        arts[market] = art
        ex = rec.expected_counts(season, week, art)
        if ex is None or ex.height == 0:
            return None
        return (ex.drop("mu"), ex["mu"].to_numpy(),
                {"dispersion": float(art["dispersion"])})
    from src.prediction import yards as yp
    art = arts.get(market) or yp.load_model(market)
    if art is None:
        return None
    arts[market] = art
    got = yp.expected_quantiles(market, season, week, art)
    if got is None:
        return None
    ids, q = got
    return ids, q, {"levels": tuple(art["levels"])}


def median_of(market: str, dist: np.ndarray, meta: dict) -> np.ndarray:
    """The board's projection: the median, as every over/under board shows."""
    if market == "receptions":
        from src.models.count import count_interval
        return count_interval(np.asarray(dist, dtype=float),
                              meta["dispersion"], 0.5, 0.5)[0]
    from src.models.yards import quantile_at
    return quantile_at(dist, 0.5, meta["levels"])


def week_floors(market: str, season: int, week: int, cal: dict | None,
                tgt: float, arts: dict | None = None) -> pl.DataFrame:
    """One row per candidate with a floor: who, the line, the chance, the median.

    Candidates with no line clearing the target (a backup whose 0.5 is not
    90%) are left out; `n_candidates` on the frame's first row is not kept,
    so a caller that wants the count reads `week_dists` itself.
    """
    got = week_dists(market, season, week, arts)
    if got is None:
        return pl.DataFrame()
    ids, dist, meta = got
    lines = grid(market)
    raw = raw_over_grid(market, dist, lines, meta.get("levels"), meta.get("dispersion"))
    line, chance = floors(calibrate(raw, cal), lines, tgt)
    out = ids.with_columns(pl.Series("floor", line), pl.Series("p_floor", chance),
                           pl.Series("proj", median_of(market, dist, meta)))
    return out.filter(pl.col("floor").is_not_nan())


# --------------------------------------------------------------------------
# Backtest
# --------------------------------------------------------------------------

def settled_dists(market: str, season: int, logs: pl.DataFrame,
                  arts: dict | None = None, weeks: list[int] | None = None
                  ) -> tuple[pl.DataFrame, np.ndarray, dict]:
    """Every priced player-game of a season that was NOT void, with its result.

    Inner join to the snap-backed game log: no snap and no stat is void and
    drops out; a snap with no stat is already a zero there.
    """
    stat = market
    lg = logs.filter(pl.col("season") == season).select(
        ["game_id", "player_id", pl.col(stat).alias("actual")])
    if weeks is None:
        weeks = sorted(logs.filter(pl.col("season") == season)["week"].unique().to_list())
    ids_all, dists, meta = [], [], {}
    for w in weeks:
        got = week_dists(market, season, int(w), arts)
        if got is None:
            continue
        ids, d, meta = got
        ids = ids.with_row_index("_r")
        j = ids.join(lg, on=["game_id", "player_id"], how="inner")
        if j.height == 0:
            continue
        ids_all.append(j.drop("_r"))
        dists.append(np.asarray(d)[j["_r"].to_numpy()])
    if not ids_all:
        return pl.DataFrame(), np.empty((0,)), meta
    return pl.concat(ids_all, how="vertical_relaxed"), np.concatenate(dists), meta


def cluster_rate(hit: np.ndarray, games: np.ndarray, z: float = 1.96) -> dict:
    """Hit rate with a game-clustered 95% interval (CR0, `season_scorecard`'s).

    Every receiver in one game shares its script, so a thousand floors over
    sixteen games carry the precision of sixteen, not a thousand.
    """
    from src.evaluation.season_scorecard import _cluster_ci

    by_game: dict = defaultdict(list)
    for h, g in zip(np.asarray(hit, dtype=float), games):
        by_game[g].append(float(h))
    n = int(len(hit))
    if not n:
        return {"n": 0, "games": 0, "hit": None, "lo": None, "hi": None}
    mean, lo, hi = _cluster_ci(by_game, z)
    return {"n": n, "games": len(by_game), "hit": mean,
            "lo": max(0.0, lo), "hi": min(1.0, hi)}


def grade(floor: np.ndarray, actual: np.ndarray) -> np.ndarray:
    """1 where the stat went over the floor. Half-point lines never push."""
    return (np.asarray(actual, dtype=float) > np.asarray(floor, dtype=float)).astype(float)


def passes(res: dict, tgt: float) -> bool:
    """The ship rule: the interval includes or exceeds the target."""
    return bool(res.get("n")) and res.get("hi") is not None and res["hi"] >= tgt


# --------------------------------------------------------------------------
# The live payload
# --------------------------------------------------------------------------

def book_prices(season: int, week: int) -> dict:
    """`(game_id, player_id, market, point) -> {odds, n_books}` for the week.

    The median clean price across books, alternate ladders first
    (`safe_legs.rungs`, broken ladders removed whole), then the main line.
    Close if captured, else the open. Empty when nothing is archived.
    """
    from src.evaluation.safe_legs import ALT_STAT

    out: dict = {}
    for snap in ("open", "close"):          # close overwrites open
        try:
            from src.evaluation.safe_legs import rungs
            r = rungs([season], snapshot=snap).filter(pl.col("week") == week)
        except Exception:                                        # noqa: BLE001
            continue
        for x in r.iter_rows(named=True):
            k = (x["game_id"], x["player_id"], ALT_STAT[x["market"]], float(x["point"]))
            out[k] = {"odds": None if x["odds"] is None else int(x["odds"]),
                      "n_books": int(x["n_books"] or 0)}
    return out


def payload(season: int | None, week: int | None, eligible: set | None = None,
            out_dir: Path | None = None) -> dict | None:
    """The page's block: per market, the backtest verdict and this week's rows.

    `eligible` is the touchdown board's population (names), the same filter
    every over/under board applies, so the floors list is the board's players.
    """
    if not season or not week:
        return None
    tgt = target()
    cal = load_calibration(out_dir)
    bt = load_backtest(out_dir)
    prices = {}
    try:
        prices = book_prices(int(season), int(week))
    except Exception:                                            # noqa: BLE001
        prices = {}
    arts: dict = {}
    out = {"season": season, "week": week, "target": tgt,
           "loss_per_100": (bt.get("money") or {}).get("per_100"),
           "money_season": (bt.get("money") or {}).get("season"),
           "test_season": bt.get("test_season"),
           "fit_season": bt.get("fit_season"), "markets": []}
    for m in MARKETS:
        res = ((bt.get("markets") or {}).get(m) or {})
        test = res.get("test") or {}
        blk = {"market": m, "label": LABELS[m], "calibrated": m in cal,
               "backtest": test or None,
               "ok": passes(test, tgt) if test else None,
               "median_gap": res.get("median_gap"),
               # Where the market held its average and missed at one end:
               # the projection band whose interval sits wholly below target.
               "weak": [x for x in res.get("strata") or []
                        if x.get("n") and x.get("hi") is not None
                        and x["hi"] < tgt],
               "rows": []}
        # NO CALIBRATION, NO FLOORS. Raw passing floors held 0.82 on 2025;
        # a missing file must read as missing, not as a 90% claim.
        if m not in cal:
            blk["problem"] = ("floors unavailable (no fitted calibration — "
                              "run `python scripts/75_floors.py`)")
            out["markets"].append(blk)
            continue
        try:
            df = week_floors(m, int(season), int(week), cal.get(m), tgt, arts)
        except Exception as e:                                   # noqa: BLE001
            blk["problem"] = f"floors unavailable ({e})"
            out["markets"].append(blk)
            continue
        rows = []
        for r in df.iter_rows(named=True):
            if eligible and r["player_name"] not in eligible:
                continue
            fl = float(r["floor"])
            px = prices.get((r["game_id"], r["player_id"], m, fl)) or {}
            rows.append({"player_name": r["player_name"],
                         "player_id": r["player_id"], "team": r["team"],
                         "game_id": r["game_id"], "floor": fl,
                         "p_floor": round(float(r["p_floor"]), 4),
                         "proj": round(float(r["proj"]), 1),
                         "book_odds": px.get("odds"),
                         "book_n": px.get("n_books")})
        rows.sort(key=lambda r: (-r["floor"], r["player_name"]))
        blk["rows"] = rows
        out["markets"].append(blk)
    return out


# --------------------------------------------------------------------------
# The freeze and the forward record
# --------------------------------------------------------------------------

def freeze_key(market: str) -> str:
    return market + FREEZE_SUFFIX


def eligible_names(season: int, week: int) -> set | None:
    """The touchdown board's population, which every over/under board shows.

    `predict(persist=False)`, the same call the dashboard export rates the
    week with, so a floor frozen by `scripts/66_freeze.py` and one built by the
    site export cover the same players. None when it cannot be built, which
    callers read as "no filter" rather than as "nobody".
    """
    try:
        from src.prediction.predict import predict

        rated = predict(season, week, target_type="anytime_td", persist=False)
    except Exception:                                            # noqa: BLE001
        return None
    if rated is None or rated.height == 0 or "player_name" not in rated.columns:
        return None
    return set(rated["player_name"].to_list())


def freeze(block: dict | None, season: int, week: int, now=None) -> int:
    """Record each market's floors for every game still to kick off.

    Kickoff-gated per game by `prediction_freeze.record`, so a started game
    keeps what it kicked off with. Returns games written across markets.
    """
    from src.export import prediction_freeze as PF

    if not block or not season or not week:
        return 0
    wrote = 0
    for blk in block.get("markets") or []:
        # The over/under market's own model version: a refit of its model or
        # of this file's calibration starts a new population.
        try:
            from src.export.run_manifest import served_version
            ver = served_version(blk["market"])
        except Exception:                                        # noqa: BLE001
            ver = None
        rows = [dict(r, target=block.get("target"),
                     **({"version": ver} if ver else {}))
                for r in blk.get("rows") or [] if not r.get("frozen")]
        wrote += PF.record(rows, season, week, freeze_key(blk["market"]), now)
    return wrote


def serve_frozen(block: dict | None, season: int, week: int, now=None) -> int:
    """Replace a started game's rows with the floors it kicked off with."""
    from src.export import prediction_freeze as PF

    if not block or not season or not week:
        return 0
    live = PF.started_games(season, week, now)
    if not live:
        return 0
    served = 0
    for blk in block.get("markets") or []:
        kept = PF.frozen(season, week, freeze_key(blk["market"]))
        rows = [r for r in blk.get("rows") or [] if r.get("game_id") not in
                (live & set(kept))]
        for gid in sorted(live & set(kept)):
            for r in kept[gid]:
                rows.append(dict(r, game_id=gid, frozen=True))
                served += 1
        rows.sort(key=lambda r: (-(r.get("floor") or 0), r.get("player_name") or ""))
        blk["rows"] = rows
    return served


def forward(season: int, frozen: dict | None = None, unfinished=None,
            actuals=None, played: dict | None = None) -> dict | None:
    """Each market's frozen floors, graded once their games are final.

    One row per (game, player, market) by construction of the freeze; a row
    whose game has no final is PENDING and counted once, separately, never
    graded. Void (no snap, no stat) drops out as a book voids it.
    """
    from src.evaluation.prop_settlement import _norm

    if frozen is None:
        from src.export import prediction_freeze as PF
        frozen = PF.load(int(season))
    if unfinished is None:
        from src.evaluation.tracked_rules import unfinished as _u
        unfinished = _u
    if actuals is None:
        from src.evaluation.forward_record import _actuals as actuals
    if played is None:
        from src.evaluation.prop_settlement import participation
        played = participation(int(season))
    tgt = target()
    graded: dict = {m: [] for m in MARKETS}
    pending: dict = {m: 0 for m in MARKETS}
    weeks: set = set()
    for wk, markets in sorted((frozen or {}).items(), key=lambda kv: int(kv[0])):
        week = int(wk)
        open_ = None
        for m in MARKETS:
            games = (markets or {}).get(freeze_key(m)) or {}
            if not games:
                continue
            if open_ is None:
                open_ = unfinished(season, week)[0]
            acts = actuals(season, week, m)
            for gid, rows in games.items():
                if gid in open_:
                    pending[m] += len(rows)
                    continue
                names = _norm([r.get("player_name") or "" for r in rows])
                for r, n in zip(rows, names):
                    if r.get("floor") is None:
                        continue
                    got = acts(r.get("player_name"), r.get("player_id"))
                    if got is None and (gid, n) not in played:
                        continue                              # void
                    got = 0.0 if got is None else float(got)
                    weeks.add(week)
                    graded[m].append((gid, float(got > float(r["floor"]))))
    if not any(graded.values()) and not any(pending.values()):
        return None
    rows = []
    for m in MARKETS:
        g = graded[m]
        res = cluster_rate(np.array([h for _, h in g]), np.array([x for x, _ in g]))
        res.update({"market": m, "label": LABELS[m], "pending": pending[m]})
        rows.append(res)
    return {"target": tgt, "weeks": sorted(weeks), "markets": rows,
            "pending": sum(pending.values())}


def fmt_rate(res: dict) -> str:
    """For a console line: `0.912 [0.897, 0.926] n=1,234`."""
    if not res or not res.get("n"):
        return "n=0"
    return (f"{res['hit']:.3f} [{res['lo']:.3f}, {res['hi']:.3f}] "
            f"n={res['n']:,} games={res['games']}")


def _isnan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))
