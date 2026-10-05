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


#: Built frames, by (target type, played_only). Reading and de-duplicating the
#: player matrix is most of the cost, and an export builds the live week plus
#: every archived one — which paid for it once per board.
_FRAMES: dict = {}

#: Fitted models, by season trained up to.
_FITS: dict = {}


def team_games(target_type: str = "anytime_td",
               played_only: bool = True) -> pl.DataFrame:
    """One row per team per game: its features, and the points it scored.

    Recovered from the player-level feature matrix by taking the team-level
    columns and de-duplicating, which is sound only because those columns are
    constant across a side's players — asserted here rather than assumed.

    `played_only=False` keeps games with no score yet, which is the only way
    to predict one: the default inner join drops the upcoming week entirely,
    so a card for a game that has not kicked off had no model row and showed
    no model — silently, since a missing second opinion is a legitimate state.
    """
    from src.utils.paths import get_path

    key = (target_type, played_only, "sit+co")
    if key in _FRAMES:
        return _FRAMES[key]

    lf = pl.scan_parquet(get_path("processed", target_type) / "features.parquet")
    cols = lf.collect_schema().names()
    keys = ["season", "week", "game_id", "team"]
    feats = [c for c in cols
             if c not in VEGAS_COLS and c not in keys
             and (c.startswith(TEAM_PREFIXES) or c in TEAM_SCALARS)]
    tg = (lf.select(keys + feats).collect()
            .unique(subset=keys, keep="first"))

    sched_all = pl.read_parquet(get_path("raw") / "schedules.parquet")
    sched = sched_all.filter(pl.col("game_type") == "REG")
    if played_only:
        sched = sched.drop_nulls(["home_score", "away_score"])
    long = pl.concat([
        sched.select(["game_id", pl.col("home_team").alias("team"),
                      pl.col("home_score").alias("points"),
                      pl.lit(1).alias("home")]),
        sched.select(["game_id", pl.col("away_team").alias("team"),
                      pl.col("away_score").alias("points"),
                      pl.lit(0).alias("home")])])
    out = tg.join(long, on=["game_id", "team"], how="inner")

    # The situational family: slot, rest, and the coach's record BEFORE this
    # game. Joined here rather than built into the player matrix because it is
    # a property of the fixture, and because the player matrix already carries
    # `rest_days`, `is_primetime` and `is_divisional` — the rest of it has
    # nowhere else to live.
    try:
        from src.features.situational_features import \
            build_situational_features

        sit = build_situational_features(sched_all)
        if not sit.is_empty():
            before = out.height
            out = out.join(sit.drop(["season", "week"], strict=False),
                           on=["game_id", "team"], how="left")
            assert out.height == before, "situational join fanned out"
    except Exception as e:                                       # noqa: BLE001
        print(f"  situational features unavailable ({e})")

    # And the coordinators, which are a level below the head coach the
    # schedule already carries. Same as-of discipline: the cumulative runs
    # over the PERSON, so a coordinator's record follows him between clubs.
    try:
        from src.features.coordinator_features import \
            build_coordinator_features

        co = build_coordinator_features(sched_all)
        if not co.is_empty():
            before = out.height
            out = out.join(co, on=["game_id", "team"], how="left")
            assert out.height == before, "coordinator join fanned out"
    except Exception as e:                                       # noqa: BLE001
        print(f"  coordinator features unavailable ({e})")
    # Every game must carry both sides, or a "total" is one team's score and
    # the model appears to disagree with the line by thirty points and be right.
    per = out.group_by("game_id").agg(pl.len().alias("n"))
    assert per.filter(pl.col("n") != 2).is_empty(), (
        "some games do not have exactly two team rows")
    _FRAMES[key] = out
    return out


def feature_columns_cached(d: pl.DataFrame, _cache: dict = {}) -> list[str]:
    """`feature_columns` minus `leaky_columns`, computed once per process.

    The screen walks every column against every null subset and costs a few
    seconds. Paid once in an export that rebuilds several boards, rather than
    once per board.
    """
    key = (d.height, len(d.columns))
    if key not in _cache:
        feats = feature_columns(d)
        _cache[key] = [c for c in feats if c not in set(leaky_columns(d, feats))]
    return _cache[key]


def feature_columns(d: pl.DataFrame) -> list[str]:
    """Numeric feature columns, excluding keys, the target and the vegas set."""
    skip = {"season", "week", "game_id", "team", "points", "home", *VEGAS_COLS}
    return [c for c in d.columns if c not in skip and d[c].dtype.is_numeric()]


def leaky_columns(d: pl.DataFrame, cols: list[str] | None = None) -> list[str]:
    """Columns whose ABSENCE predicts the result of the game they are absent in.

    Measured against each team's own season mean, so that a column which is
    simply missing more often for bad offenses is not mistaken for one that
    knows the score. See this module's docstring for what it caught.
    """
    cols = cols or feature_columns(d)
    w = (d.with_columns(pl.col("points").mean()
                        .over(["season", "team"]).alias("_tm"))
          .with_columns((pl.col("points") - pl.col("_tm")).alias("_vs"))
          .filter(pl.col("week") >= LEAK_FROM_WEEK)
          # Only the columns the screen reads. It used to filter the WHOLE
          # frame once per column — 300 columns copied 160 times — which cost
          # 38 seconds and put that on every export.
          .select(cols + ["_vs"]))
    if w.height == 0:
        return []
    # One pass: per column, how many rows it is null on and the mean deviation
    # across exactly those rows. `mean` over a null-masked column ignores the
    # nulls, so the deviation is masked by the column rather than filtered by it.
    agg = w.select([
        e for c in cols for e in (
            pl.col(c).is_null().sum().alias(f"n::{c}"),
            pl.when(pl.col(c).is_null()).then(pl.col("_vs"))
              .otherwise(None).mean().alias(f"g::{c}"))
    ]).row(0, named=True)
    return [c for c in cols
            if (agg[f"n::{c}"] or 0) >= LEAK_MIN_ROWS
            and agg[f"g::{c}"] is not None
            and agg[f"g::{c}"] < LEAK_GAP_PTS]


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


def predict_week(season: int, week: int, d: pl.DataFrame | None = None
                 ) -> pl.DataFrame:
    """One fit on everything before this season, then predict one week.

    Separate from `walk_forward`, which refits per season and takes minutes —
    fine for measuring, far too slow to sit inside an export that runs every
    time the board is rebuilt.

    Trains on seasons strictly before `season`, so a week served in September
    is scored by a model that has seen no game from the season it is
    predicting. Returns one row per game with the model's margin and total.
    """
    import lightgbm as lgb

    # Unplayed games included, or the week being predicted is not in the frame.
    d = team_games(played_only=False) if d is None else d
    # The screen needs OUTCOMES to measure missingness against, so it is run on
    # the played rows only — the unplayed ones have no score to compare to.
    feats = feature_columns_cached(d.filter(pl.col("points").is_not_null()))
    tr = d.filter((pl.col("season") < season) & pl.col("points").is_not_null())
    te = d.filter((pl.col("season") == season) & (pl.col("week") == week))
    if te.is_empty() or tr.height < 500:
        return pl.DataFrame()

    # One fit per season, not per week, and PERSISTED. Every week of a season
    # trains on the same rows — everything before it — and the fit itself is
    # 43 seconds, which an export that rebuilds the live week and every
    # archived one was paying repeatedly. Saved beside the other models and
    # reloaded, so a rebuild costs a load.
    m = _FITS.get(season)
    if m is None:
        m = _load_fit(season, feats)
    if m is None:
        m = lgb.LGBMRegressor(n_estimators=400, learning_rate=0.05,
                              num_leaves=31, min_child_samples=40,
                              subsample=0.8, colsample_bytree=0.6,
                              random_state=0, verbose=-1)
        m.fit(tr.select(feats).to_numpy(), tr["points"].to_numpy())
        _save_fit(season, feats, m)
    _FITS[season] = m
    te = te.with_columns(
        pl.Series("pred", m.predict(te.select(feats).to_numpy())))
    home, away = pl.col("home") == 1, pl.col("home") == 0
    return te.group_by("game_id").agg([
        (pl.col("pred").filter(home).first()
         - pl.col("pred").filter(away).first()).alias("margin_model"),
        pl.col("pred").sum().alias("total_model"),
    ])


def _fit_path(season: int):
    from src.utils.paths import get_path

    return get_path("models") / "game_model" / f"points_{season}.pkl"


def _load_fit(season: int, feats: list[str]):
    """The saved model, or None if it was fitted on different columns.

    The feature list is stored WITH the booster and checked on load. A model
    reloaded against a changed feature matrix predicts from columns that have
    silently moved — the trap `leaky_columns` exists to catch would come back
    through the back door, with no error anywhere.
    """
    import pickle

    path = _fit_path(season)
    if not path.exists():
        return None
    try:
        blob = pickle.loads(path.read_bytes())
    except Exception:                                            # noqa: BLE001
        return None
    if blob.get("features") != list(feats):
        return None
    return blob.get("model")


def _save_fit(season: int, feats: list[str], model) -> None:
    import pickle

    path = _fit_path(season)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps({"features": list(feats), "model": model,
                                   "season": season}))


#: Where the measured comparison against the closing line is kept.
VS_MARKET_PATH_NAME = "vs_market.json"


def vs_market_path():
    from src.utils.paths import get_path

    return get_path("models") / "game_model" / VS_MARKET_PATH_NAME


def vs_market(refresh: bool = False) -> dict | None:
    """Mean absolute error against the closing line, measured not asserted.

    **THIS NUMBER WAS A LITERAL ON THE PAGE.** `47_export_site.py` shipped
    `{"margin": [10.73, 9.85], "total": [10.81, 10.37]}` as if it had been
    measured on the day you read it. It had been measured once, and the
    matrix has been rebuilt many times since: re-run on 2026-10-05 the same
    walk-forward gives margin 10.667 against 9.813 and total 10.909 against
    10.364. Not far off, which is the problem — a stale number that is
    obviously wrong gets fixed, and one that is nearly right does not.

    Cached, because the walk-forward is about half a minute and the export
    runs several times a day. The cache carries `measured_on`, `n_games` and
    `seasons` so the page can say how old it is instead of implying it is
    current.
    """
    import json
    from datetime import date

    p = vs_market_path()
    if not refresh and p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:                                        # noqa: BLE001
            pass
    try:
        w = walk_forward()
    except Exception:                                            # noqa: BLE001
        return None
    if w.is_empty():
        return None
    out: dict = {}
    n = 0
    for k in ("margin", "total"):
        d = w.drop_nulls([f"{k}_model", f"{k}_market", f"{k}_actual"])
        if d.is_empty():
            return None
        n = d.height
        out[k] = [
            round(float((d[f"{k}_model"] - d[f"{k}_actual"]).abs().mean()), 4),
            round(float((d[f"{k}_market"] - d[f"{k}_actual"]).abs().mean()), 4),
        ]
    out["n_games"] = n
    out["seasons"] = sorted({int(s) for s in w["season"].to_list()})
    out["measured_on"] = date.today().isoformat()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    return out
