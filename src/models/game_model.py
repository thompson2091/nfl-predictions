"""A game-outcome model that never sees the betting line.

Every other model here is allowed to read the market. `joint.fit_team_rate` is
a Poisson regression OF team touchdowns ON `implied_team_total`, `total_line`
and `abs_spread` — its job is to turn the market's number into touchdowns, not
to form a view about it. That makes it useless for the one question a matchup
page wants to ask: is the posted total right?

So this model is built from the team's own history and its opponent's, with
`spread_line`, `total_line`, `implied_team_total` and `moneyline_implied_prob`
removed. It predicts POINTS PER TEAM-GAME; a game's margin and total are the
difference and the sum of its two teams' predictions.

**It is not better than the market and is not claimed to be.** On seven
walk-forward seasons it sits at 10.6 MAE on margin against the market's 9.8,
and 10.8 on totals against 10.4. What it is, is INDEPENDENT — and a second
opinion that is worse on average can still disagree usefully, which is the
only thing worth testing and what `evaluate` measures.

MISSINGNESS WAS THE WHOLE GAME HERE, AND IT NEARLY SHIPPED AS AN EDGE.

The first honest-looking version beat the closing total (MAE 10.04 against
10.36) and turned that into 72.8% hit rates on large disagreements. It was
reading nulls. Twenty features -- every `team_rz_*` rate and every
`opp_tds_allowed_to_*` -- go null exactly when the denominator they need is
missing, and the denominator is missing when nobody scored. A team whose
`team_rz_td_pct_avg_5g` is null scored SEVENTEEN POINTS BELOW ITS OWN SEASON
AVERAGE in that game. The model had learned to read "this column is absent" as
"this game was a shutout", which it was, and which it could not have known.

`leaky_columns` is that screen, and it is measured within team and season so
that team quality cannot masquerade as the effect. Anything whose absence
predicts underperformance in the same game is dropped.
"""
from __future__ import annotations

import polars as pl

#: Columns that ARE the market. The whole point is to exclude them.
VEGAS_COLS = ("spread_line", "total_line", "implied_team_total",
              "moneyline_implied_prob")

#: Prefixes that describe a team or its opponent rather than one player. The
#: feature matrix is player-level and these repeat across every player on a
#: side, which is what makes a team-game frame recoverable from it at all.
TEAM_PREFIXES = ("team_", "opp_", "wx", "wxi", "coach_", "ix_")
TEAM_SCALARS = ("is_home", "is_dome", "is_outdoor", "rest_days",
                "is_divisional", "is_primetime", "surface_turf")

#: How far below its own season mean a team may score, in the games where a
#: column is absent, before that column is treated as a marker of the result
#: rather than a fact about the past. Two thirds of a field goal: small enough
#: to catch the 20 real offenders, large enough that ordinary noise on a few
#: dozen rows does not trip it.
LEAK_GAP_PTS = -1.5

#: Below this many missing rows a column cannot be screened, because the mean
#: it would be screened on is noise.
LEAK_MIN_ROWS = 25

#: Weeks 1-3 are excluded from the screen. A rolling feature is legitimately
#: absent early in a season, and that absence says nothing about the game.
LEAK_FROM_WEEK = 4


def team_games(target_type: str = "anytime_td") -> pl.DataFrame:
    """One row per team per game: its features, and the points it scored.

    Recovered from the player-level feature matrix by taking the team-level
    columns and de-duplicating, which is sound only because those columns are
    constant across a side's players — asserted here rather than assumed.
    """
    from src.utils.paths import get_path

    lf = pl.scan_parquet(get_path("processed", target_type) / "features.parquet")
    cols = lf.collect_schema().names()
    keys = ["season", "week", "game_id", "team"]
    feats = [c for c in cols
             if c not in VEGAS_COLS and c not in keys
             and (c.startswith(TEAM_PREFIXES) or c in TEAM_SCALARS)]
    tg = (lf.select(keys + feats).collect()
            .unique(subset=keys, keep="first"))

    sched = (pl.read_parquet(get_path("raw") / "schedules.parquet")
             .filter(pl.col("game_type") == "REG")
             .drop_nulls(["home_score", "away_score"]))
    long = pl.concat([
        sched.select(["game_id", pl.col("home_team").alias("team"),
                      pl.col("home_score").alias("points"),
                      pl.lit(1).alias("home")]),
        sched.select(["game_id", pl.col("away_team").alias("team"),
                      pl.col("away_score").alias("points"),
                      pl.lit(0).alias("home")])])
    out = tg.join(long, on=["game_id", "team"], how="inner")
    # Every game must carry both sides, or a "total" is one team's score and
    # the model appears to disagree with the line by thirty points and be right.
    per = out.group_by("game_id").agg(pl.len().alias("n"))
    assert per.filter(pl.col("n") != 2).is_empty(), (
        "some games do not have exactly two team rows")
    return out


def feature_columns(d: pl.DataFrame) -> list[str]:
    """Numeric feature columns, excluding keys, the target and the vegas set."""
    skip = {"season", "week", "game_id", "team", "points", "home", *VEGAS_COLS}
    return [c for c in d.columns if c not in skip and d[c].dtype.is_numeric()]


def leaky_columns(d: pl.DataFrame, cols: list[str] | None = None) -> list[str]:
    """Columns whose ABSENCE predicts the result of the game they are absent in.

    Measured against each team's own season mean, so that a column which is
    simply missing more often for bad offences is not mistaken for one that
    knows the score. See this module's docstring for what it caught.
    """
    cols = cols or feature_columns(d)
    w = (d.with_columns(pl.col("points").mean()
                        .over(["season", "team"]).alias("_tm"))
          .with_columns((pl.col("points") - pl.col("_tm")).alias("_vs"))
          .filter(pl.col("week") >= LEAK_FROM_WEEK))
    out = []
    for c in cols:
        s = w.filter(pl.col(c).is_null())
        if s.height < LEAK_MIN_ROWS:
            continue
        if float(s["_vs"].mean()) < LEAK_GAP_PTS:
            out.append(c)
    return out


def walk_forward(d: pl.DataFrame | None = None, first: int = 2019,
                 drop_leaks: bool = True) -> pl.DataFrame:
    """Predict each season with a model that trained only on earlier ones.

    One row per game: the model's margin and total beside the market's and
    the result. `drop_leaks=False` reproduces the version that read nulls,
    which is what the test uses to prove the screen still bites.
    """
    import lightgbm as lgb

    from src.utils.paths import get_path

    d = team_games() if d is None else d
    feats = feature_columns(d)
    if drop_leaks:
        feats = [c for c in feats if c not in set(leaky_columns(d, feats))]

    # The market, joined for comparison only — never for training.
    mkt = (pl.scan_parquet(get_path("processed", "anytime_td")
                           / "features.parquet")
           .select(["game_id", "team", "spread_line", "total_line"]).collect()
           .unique(subset=["game_id", "team"], keep="first"))
    d = d.join(mkt, on=["game_id", "team"], how="left")

    parts = []
    for season in sorted(s for s in d["season"].unique() if s >= first):
        tr = d.filter(pl.col("season") < season)
        te = d.filter(pl.col("season") == season)
        if te.is_empty() or tr.height < 500:
            continue
        m = lgb.LGBMRegressor(n_estimators=400, learning_rate=0.05,
                              num_leaves=31, min_child_samples=40,
                              subsample=0.8, colsample_bytree=0.6,
                              random_state=0, verbose=-1)
        m.fit(tr.select(feats).to_numpy(), tr["points"].to_numpy())
        te = te.with_columns(
            pl.Series("pred", m.predict(te.select(feats).to_numpy())))
        home, away = pl.col("home") == 1, pl.col("home") == 0
        parts.append(te.group_by("game_id").agg([
            pl.col("season").first().alias("season"),
            pl.col("week").first().alias("week"),
            (pl.col("pred").filter(home).first()
             - pl.col("pred").filter(away).first()).alias("margin_model"),
            pl.col("pred").sum().alias("total_model"),
            (pl.col("points").filter(home).first()
             - pl.col("points").filter(away).first()).alias("margin_actual"),
            pl.col("points").sum().alias("total_actual"),
            pl.col("spread_line").filter(home).first().alias("margin_market"),
            pl.col("total_line").first().alias("total_market"),
        ]).drop_nulls())
    return pl.concat(parts) if parts else pl.DataFrame()


def _wilson(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    import math

    if n == 0:
        return (0.0, 1.0)
    p = hits / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - half), min(1.0, c + half))


#: Break-even at -110, which is what a spread or a total is quoted at.
BREAK_EVEN = 0.5238


def disagreements(g: pl.DataFrame, market: str = "total",
                  thresholds=(1, 3, 5, 8)) -> list[dict]:
    """Back the model wherever it disagrees with the line by N or more.

    MAE IS NOT MONEY. A model can sit closer to the truth on average and lose
    every bet, and this one is FURTHER from the truth on average and still
    wins these — which is why the only reported number is the one settled
    against the closing line. Pushes are dropped: a push is not a loss.

    Read `n` and the interval before anything else. Seven seasons is about
    150 qualifying bets a year, so a season swings ten points on noise alone,
    and one of the seven sits below break-even.
    """
    mdl, mkt, act = (f"{market}_model", f"{market}_market", f"{market}_actual")
    out = []
    for thr in thresholds:
        s = g.filter((pl.col(mdl) - pl.col(mkt)).abs() >= thr)
        over = pl.col(mdl) > pl.col(mkt)
        s = (s.with_columns([
                pl.when(over).then(pl.col(act) > pl.col(mkt))
                  .otherwise(pl.col(act) < pl.col(mkt)).alias("_won"),
                (pl.col(act) == pl.col(mkt)).alias("_push")])
              .filter(~pl.col("_push")))
        n = s.height
        if n == 0:
            continue
        hits = int(s["_won"].sum())
        lo, hi = _wilson(hits, n)
        rate = hits / n
        out.append({
            "market": market, "threshold": thr, "n": n, "hits": hits,
            "hit_rate": rate, "lo": lo, "hi": hi,
            # Flat stake at -110, which is what these are quoted at.
            "roi_pct": (rate * (100 / 110) - (1 - rate)) * 100,
            "clears": lo > BREAK_EVEN,
        })
    return out
