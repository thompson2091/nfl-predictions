"""Alternate-ladder rungs priced as near-certain, and whether any of them pay.

Matt's examples, all from one London game: Trevor Lawrence over 150 passing
yards (over in 47 of his last 50), Jakobi Meyers 15+ receiving and Nico Collins
40+. Legs like these are priced near-certain too — the backfilled ladders put
Dak Prescott's over 149.5 at -1740 — so "it usually hits" is not the question.
The question is whether OUR estimate of the hit rate is better than the price's,
and three candidates are tested side by side:

  - history: the player's own rate over that rung in his last games,
  - model:   the yardage / catches model's distribution, read at the rung,
  - both:    the lower of the two, so a leg needs both to agree.

Each raw estimate is recalibrated on 2024 and judged on 2025. Raw history at
47/50 is a 94% claim from fifty games of a role that may have changed; the
model's raw probabilities are ~5x too extreme in log-odds
(memory: ou-models-overconfident). Neither is trusted uncalibrated.

**SETTLEMENT IS THE BOOK'S, NOT `weekly_stats`'.** That table has no row for a
player who played and recorded nothing, which is the losing over on exactly
these legs; dropping him flatters every over. A player with an offensive snap
and no stat line is graded at zero, and one with neither is void — the rule in
`prop_settlement`, applied the same way here.

The threshold ("nearly sure" = 90%) lives in `config/safe_legs.yaml`. Callers
may override any value for one run; nothing writes the file back.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl
import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "safe_legs.yaml"

#: What the file must define, and the type each value has to be.
REQUIRED = {"min_prob": float, "min_edge": float, "report_thresholds": list,
            "history_games": int, "history_min_games": int}

#: Alternate market -> the weekly_stats column it settles on.
ALT_STAT = {"passing_yards_alt": "passing_yards",
            "receiving_yards_alt": "receiving_yards",
            "rushing_yards_alt": "rushing_yards",
            "receptions_alt": "receptions"}

APPROACHES = ("history", "model", "both")


def settings(path: Path = CONFIG_PATH, **overrides) -> dict:
    """The file's values with any non-None `overrides` on top, validated."""
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    cfg.update({k: v for k, v in overrides.items() if v is not None})
    for key, kind in REQUIRED.items():
        if key not in cfg:
            raise KeyError(f"{path.name} is missing {key}")
        if kind is float and isinstance(cfg[key], int):
            cfg[key] = float(cfg[key])
        if not isinstance(cfg[key], kind):
            raise TypeError(f"{key} must be {kind.__name__}, got {cfg[key]!r}")
    if not 0.5 <= cfg["min_prob"] < 1.0:
        raise ValueError(f"min_prob must be in [0.5, 1.0), got {cfg['min_prob']}")
    if not all(0.5 <= t < 1.0 for t in cfg["report_thresholds"]):
        raise ValueError("report_thresholds must all be in [0.5, 1.0)")
    return cfg


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------

#: No real over is priced beyond this. Fliff posted -999905 on a 2025 rung.
MAX_ABS_ODDS = 20000


def book_ladders(seasons: list[int], snapshot: str = "close") -> pl.DataFrame:
    """Per-book over quotes, with every BROKEN LADDER removed whole.

    Priced from `odds_books`, not the consensus archive, because the consensus
    cannot see a broken feed. On 2025 week 1 ESPN Bet's Josh Allen ladder read
    +100 at 49.5, +800 at 99.5, +120 at 124.5 and +1600 at 199.5 while six
    books had 199.5 at -260 to -350. Where a rung had only that book, its
    garbage WAS the median, and a model at 91% read it as a 43-point edge.

    A ladder is the same claim at rising lines, so its probability can only
    fall as the line rises. A book whose ladder for a player rises anywhere is
    not quoting that market, and all of it goes — not only the rung that
    exposed it.
    """
    from src.ingest.odds_history import BOOKS_PATH, drop_in_play

    b = (pl.scan_parquet(BOOKS_PATH)
         .filter(pl.col("market").is_in(list(ALT_STAT)) & (pl.col("snapshot") == snapshot)
                 & (pl.col("side") == "yes") & pl.col("season").is_in(seasons)
                 & pl.col("point").is_not_null() & pl.col("odds").is_not_null())
         .collect())
    b = drop_in_play(b)
    key = ["game_id", "player_name_norm", "market", "bookmaker"]
    b = (b.sort("captured_at").unique([*key, "point"], keep="last")
          .filter(pl.col("odds").abs() <= MAX_ABS_ODDS)
          .sort([*key, "point"]))
    rises = (pl.col("implied_prob").diff().over(key) > 1e-9).any().over(key)
    return b.filter(~rises)


def rungs(seasons: list[int], snapshot: str = "close") -> pl.DataFrame:
    """Every alternate rung: the median and best clean over price across books.

    Carries the player's gsis id, resolved from the book's name through that
    season's roster. A name the roster cannot place is dropped here rather
    than matched later by spelling; see `game_logs` for what spelling cost.
    """
    from src.ingest.odds_history import _resolve_player_id

    b = book_ladders(seasons, snapshot)
    k = ["season", "week", "game_id", "player_name_norm", "market", "point"]
    r = (b.group_by(k).agg(
                pl.col("player_name_raw").first(),
                pl.col("implied_prob").median().alias("implied_prob"),
                pl.col("implied_prob").min().alias("best_implied"),
                pl.col("odds").sort_by("implied_prob").first().alias("best_odds"),
                pl.col("bookmaker").n_unique().alias("n_books"))
             .with_columns(_american(pl.col("implied_prob")).alias("odds")))
    return r.with_columns(_resolve_player_id(r)).filter(pl.col("player_id").is_not_null())


def _american(p: pl.Expr) -> pl.Expr:
    """American odds for a probability, so a median price is a payable number."""
    return (pl.when(p >= 0.5).then(-100 * p / (1 - p))
              .otherwise(100 * (1 - p) / p)).round(0)


def game_logs() -> pl.DataFrame:
    """Every game a player took an offensive snap or recorded a stat, all seasons.

    A snap with no stat line is a real zero; see the module docstring.

    **KEYED BY PLAYER ID, NEVER BY NAME.** The first version joined box scores
    to snap counts by normalized name. The box score calls him "Kenny
    Gainwell", the snap counts and every book "Kenneth Gainwell", so none of
    his 2025 carries matched: his snaps filled in zeros, his last ten games
    read 0 rushing yards, and every under on him was "missed in 10 of 10" and
    graded a winner. Over 2024-25 that faked +55 per $100 on main-line unders.
    The zero fill has to be keyed by an id, because a zero that should not be
    there is graded rather than dropped. Snap counts carry a PFR id, mapped to
    gsis through the roster; a snap the roster cannot map is left out.
    """
    from src.utils.paths import get_path

    raw = get_path("raw")
    cols = list(dict.fromkeys(ALT_STAT.values()))
    ws = (pl.scan_parquet(raw / "weekly_stats.parquet")
          .select(["season", "week", "game_id", "player_id", *cols]).collect())
    pfr = (pl.scan_parquet(raw / "rosters.parquet")
           .select(pl.col("pfr_id"), pl.col("gsis_id").alias("player_id"))
           .drop_nulls().unique("pfr_id").collect())
    sn = (pl.scan_parquet(raw / "snap_counts.parquet")
          .filter(pl.col("offense_snaps") > 0)
          .select(["season", "week", "game_id", pl.col("pfr_player_id").alias("pfr_id")])
          .collect()
          .join(pfr, on="pfr_id", how="inner").drop("pfr_id")
          .with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64))
          .unique(["game_id", "player_id"]))
    ws = ws.with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64))
    zero_only = sn.join(ws.select(["game_id", "player_id"]),
                        on=["game_id", "player_id"], how="anti")
    zero_only = zero_only.with_columns([pl.lit(0.0).alias(c) for c in cols])
    out = pl.concat([ws.with_columns([pl.col(c).cast(pl.Float64) for c in cols]),
                     zero_only.select(ws.columns)], how="vertical")
    return (out.with_columns([pl.col(c).fill_null(0.0) for c in cols])
               .unique(["game_id", "player_id"], keep="first")
               .sort(["player_id", "season", "week"]))


def settle(r: pl.DataFrame, logs: pl.DataFrame) -> pl.DataFrame:
    """Attach the result. Void (no snap, no stat) and push rows are dropped."""
    long = logs.unpivot(index=["game_id", "player_id"],
                        on=list(dict.fromkeys(ALT_STAT.values())),
                        variable_name="stat", value_name="actual")
    r = r.with_columns(pl.col("market").replace_strict(ALT_STAT).alias("stat"))
    j = r.join(long, on=["game_id", "player_id", "stat"], how="inner")
    return (j.filter(pl.col("actual") != pl.col("point"))
             .with_columns((pl.col("actual") > pl.col("point")).cast(pl.Int8).alias("hit")))


def history_rates(r: pl.DataFrame, logs: pl.DataFrame, n_games: int,
                  min_games: int) -> pl.DataFrame:
    """Per rung: the player's hit count and games over his last `n_games`.

    Strictly before the rung's (season, week), and across season boundaries,
    because 47-of-50 is a two-and-a-half-season window.
    """
    by_player: dict[str, tuple[np.ndarray, dict]] = {}
    for (name,), g in logs.group_by(["player_id"]):
        key = (g["season"] * 100 + g["week"]).to_numpy()
        by_player[name] = (key, {c: g[c].to_numpy() for c in set(ALT_STAT.values())})

    hits = np.full(r.height, -1, dtype=np.int32)
    games = np.zeros(r.height, dtype=np.int32)
    names = r["player_id"].to_list()
    keys = (r["season"] * 100 + r["week"]).to_numpy()
    stats = r["stat"].to_list()
    points = r["point"].to_numpy()
    for i in range(r.height):
        got = by_player.get(names[i])
        if got is None:
            continue
        key, vals = got
        end = np.searchsorted(key, keys[i], side="left")
        window = vals[stats[i]][max(0, end - n_games):end]
        games[i] = len(window)
        if len(window) >= min_games:
            hits[i] = int((window > points[i]).sum())
    return r.with_columns(pl.Series("hist_hits", hits), pl.Series("hist_games", games))


def model_probs(r: pl.DataFrame) -> pl.DataFrame:
    """The served models' P(over) at every rung, push mass removed.

    Yardage: the quantile model, trained <= 2023 with 2024 as its early-stopping
    season, so 2025 is the clean test. Catches: the count model, same split.
    """
    from src.models import count, yards as ymod
    from src.prediction import receptions as rec, yards as yp

    arts = {m: yp.load_model(m) for m in ("passing_yards", "receiving_yards",
                                          "rushing_yards")}
    rart = rec.load_model()
    parts = []
    for (season, week), g in r.group_by(["season", "week"]):
        for market, stat in ALT_STAT.items():
            sub = g.filter(pl.col("market") == market)
            if sub.height == 0:
                continue
            if stat == "receptions":
                ex = rec.expected_counts(season, week, rart)
                if ex is None:
                    continue
                j = sub.join(ex.select(["game_id", "player_id", "mu"]),
                             on=["game_id", "player_id"], how="inner")
                if j.height == 0:
                    continue
                over, push = count.prob_over(j["mu"].to_numpy(), j["point"].to_numpy(),
                                             rart["dispersion"])
                j = j.drop("mu")
            else:
                got = yp.expected_quantiles(stat, season, week, arts[stat])
                if got is None:
                    continue
                ids, q = got
                ids = ids.with_row_index("_q")
                j = sub.join(ids.select(["game_id", "player_id", "_q"]),
                             on=["game_id", "player_id"], how="inner")
                if j.height == 0:
                    continue
                over, push = ymod.prob_over(q[j["_q"].to_numpy()], j["point"].to_numpy(),
                                            tuple(arts[stat].get("levels")
                                                  or ymod.QUANTILE_LEVELS))
                j = j.drop("_q")
            p = np.clip(over / np.clip(1.0 - push, 1e-9, None), 0.0, 1.0)
            parts.append(j.select(["game_id", "player_id", "market", "point"])
                          .with_columns(pl.Series("p_model_raw", p)))
    m = pl.concat(parts).unique(["game_id", "player_id", "market", "point"])
    return r.join(m, on=["game_id", "player_id", "market", "point"], how="left")


# --------------------------------------------------------------------------
# Calibration and selection
# --------------------------------------------------------------------------

def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def fit_platt(p: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """(slope, intercept) on logit(p), by logistic regression. No penalty."""
    from sklearn.linear_model import LogisticRegression

    lr = LogisticRegression(C=1e6, max_iter=1000)
    lr.fit(_logit(p).reshape(-1, 1), y)
    return float(lr.coef_[0, 0]), float(lr.intercept_[0])


def apply_platt(p: np.ndarray, ab: tuple[float, float]) -> np.ndarray:
    a, b = ab
    return 1.0 / (1.0 + np.exp(-(a * _logit(p) + b)))


def profit(odds: np.ndarray, hit: np.ndarray) -> np.ndarray:
    """Profit per $1 staked at American `odds`."""
    odds = np.asarray(odds, dtype=float)
    win = np.where(odds > 0, odds / 100.0, 100.0 / np.abs(odds))
    return np.where(hit == 1, win, -1.0)


def summarize(d: pl.DataFrame, n_boot: int = 2000, seed: int = 0) -> dict:
    """Hit rate, price, and profit per $100 with a game-clustered 95% interval."""
    if d.height == 0:
        return {"n": 0}
    pr = profit(d["odds"].to_numpy(), d["hit"].to_numpy())
    games = d["game_id"].to_numpy()
    uniq, inv = np.unique(games, return_inverse=True)
    sums = np.bincount(inv, weights=pr)
    cnts = np.bincount(inv)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(uniq), size=(n_boot, len(uniq)))
    boot = sums[draws].sum(1) / cnts[draws].sum(1)
    return {"n": d.height, "games": len(uniq),
            "hit_rate": float(d["hit"].mean()),
            "price_implied": float(d["implied_prob"].mean()),
            "per_100": float(100 * pr.mean()),
            "ci95": [float(100 * np.percentile(boot, 2.5)),
                     float(100 * np.percentile(boot, 97.5))]}


def best_rung(d: pl.DataFrame, est_col: str) -> pl.DataFrame:
    """One leg per player, market and game: the qualifying rung with most edge."""
    return (d.with_columns((pl.col(est_col) - pl.col("implied_prob")).alias("_e"))
             .sort("_e", descending=True)
             .unique(["game_id", "player_id", "market"], keep="first")
             .drop("_e"))
