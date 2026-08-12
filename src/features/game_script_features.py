"""Who gets the ball when a team is losing.

The one residual that survived every fix this project made: players on underdog
teams score more often than the model says, and the gap scales with the spread.
Measured on 6,792 backtested bets after the corrected retrain:

    big underdog (7+)   we said 30.0%   actual 34.6%   +4.5pp   significant
    small underdog      we said 33.0%   actual 35.2%   +2.2pp   significant
    small favourite     we said 36.5%   actual 36.4%   -0.2pp
    big favourite (7+)  we said 38.4%   actual 39.4%   +1.0pp

Monotone across four buckets and it persisted through a retrain, so it is not
noise. The cause is not mysterious: teams that fall behind throw more, throw
from further out, and keep throwing in garbage time. More pass attempts is more
chances to score, and the players who absorb them are not the same players who
carry a neutral script.

A second-stage corrector was built and measured against exactly this residual
and it did not beat stage one — it re-learned rank and price and had nothing
left over. The information belongs *inside* the model, as usage split by game
state, which is what this module supplies.

Every feature is shift(1) rolling, so a team's trailing behaviour comes from
games already played. `expected_trailing_share` is fitted from the spread
rather than declared, so it re-fits with the data instead of encoding somebody's
guess about how often a 7-point underdog trails.
"""
from __future__ import annotations

import polars as pl

from src.utils.config import get_config

#: A score gap wide enough to change how a team calls plays. Fitted below rather
#: than trusted: `_fit_script_bands` checks that pass rates actually separate at
#: this boundary and reports it, so a bad split is visible instead of silent.
TRAILING_BY = 7


def _script(diff: pl.Expr) -> pl.Expr:
    """Label a play by the game state the offence was in."""
    return (pl.when(diff <= -TRAILING_BY).then(pl.lit("trailing"))
              .when(diff >= TRAILING_BY).then(pl.lit("leading"))
              .otherwise(pl.lit("neutral")))


def build_game_script_features(pbp: pl.DataFrame) -> pl.DataFrame:
    """Team-level pass tendency and time spent behind, by game state."""
    cfg = get_config()
    medium = cfg["rolling_windows"]["medium"]

    need = {"posteam", "score_differential", "game_id", "season", "week"}
    if not need <= set(pbp.columns):
        return pl.DataFrame(schema={"season": pl.Int64, "week": pl.Int64,
                                    "team": pl.Utf8})

    plays = pbp.filter(
        pl.col("posteam").is_not_null()
        & pl.col("score_differential").is_not_null()
        & ((pl.col("pass_attempt") == 1) | (pl.col("rush_attempt") == 1))
    ).with_columns(_script(pl.col("score_differential")).alias("_script"))

    team_game = (
        plays.group_by(["game_id", "season", "week", "posteam"])
        .agg([
            pl.len().alias("_plays"),
            # How much of the game this team spent behind. A team that is
            # frequently trailing is one whose passing volume is inflated for
            # reasons the spread only partly captures.
            (pl.col("_script") == "trailing").mean().alias("share_trailing"),
            (pl.col("_script") == "leading").mean().alias("share_leading"),
            # Pass rate within each state, so "throws a lot" is separated from
            # "is behind a lot". The first is a tendency, the second is a
            # circumstance, and they need different features.
            pl.col("pass_attempt").filter(pl.col("_script") == "trailing")
              .mean().alias("pass_rate_trailing"),
            pl.col("pass_attempt").filter(pl.col("_script") == "neutral")
              .mean().alias("pass_rate_neutral"),
            pl.col("pass_attempt").filter(pl.col("_script") == "leading")
              .mean().alias("pass_rate_leading"),
        ])
        .rename({"posteam": "team"})
        .with_columns(
            # How much a team leans on the pass specifically when behind. This
            # is the quantity that should matter for an underdog's receivers,
            # and it is not recoverable from an overall pass rate.
            (pl.col("pass_rate_trailing") - pl.col("pass_rate_neutral"))
            .alias("pass_lift_trailing")
        )
        .sort(["team", "season", "week"])
    )

    stat_cols = ["share_trailing", "share_leading", "pass_rate_trailing",
                 "pass_rate_neutral", "pass_rate_leading", "pass_lift_trailing"]
    exprs = []
    for col in stat_cols:
        shifted = pl.col(col).cast(pl.Float64).shift(1)
        exprs.extend([
            shifted.rolling_mean(medium, min_samples=3).over("team")
                   .alias(f"team_{col}_avg_{medium}g"),
            (shifted.cum_sum().over("team") / shifted.cum_count().over("team"))
                   .alias(f"team_{col}_szn_avg"),
        ])

    return (team_game.with_columns(exprs)
            .select(["season", "week", "team"]
                    + [e.meta.output_name() for e in exprs]))


def build_player_script_features(pbp: pl.DataFrame) -> pl.DataFrame:
    """Each player's share of the ball, split by whether the team was behind.

    `script_lift` is the point of the module: how much more of the offence a
    player absorbs when the team is losing than when the game is level. A
    receiver whose share jumps in trailing scripts is precisely the player the
    model under-rates on an underdog, and nothing else in the feature set says
    so — a season-average target share averages the two states together.
    """
    cfg = get_config()
    medium = cfg["rolling_windows"]["medium"]

    need = {"posteam", "score_differential", "game_id", "season", "week"}
    if not need <= set(pbp.columns):
        return pl.DataFrame(schema={"season": pl.Int64, "week": pl.Int64,
                                    "player_id": pl.Utf8})

    plays = pbp.filter(
        pl.col("posteam").is_not_null()
        & pl.col("score_differential").is_not_null()
    ).with_columns(_script(pl.col("score_differential")).alias("_script"))

    # A touch is a target or a carry; both are chances to score.
    touches = pl.concat([
        plays.filter(pl.col("receiver_player_id").is_not_null())
             .select(["game_id", "season", "week", "posteam", "_script",
                      pl.col("receiver_player_id").alias("player_id")]),
        plays.filter(pl.col("rusher_player_id").is_not_null())
             .select(["game_id", "season", "week", "posteam", "_script",
                      pl.col("rusher_player_id").alias("player_id")]),
    ], how="vertical")
    if touches.height == 0:
        return pl.DataFrame(schema={"season": pl.Int64, "week": pl.Int64,
                                    "player_id": pl.Utf8})

    per_state = (touches.group_by(["game_id", "season", "week", "posteam",
                                   "player_id", "_script"])
                 .agg(pl.len().alias("touches")))
    team_state = (per_state.group_by(["game_id", "posteam", "_script"])
                  .agg(pl.col("touches").sum().alias("team_touches")))
    shares = (per_state.join(team_state, on=["game_id", "posteam", "_script"],
                             how="left")
              .with_columns((pl.col("touches")
                             / pl.col("team_touches").cast(pl.Float64)
                             .clip(lower_bound=1)).alias("share")))

    wide = (shares.pivot(values="share", index=["game_id", "season", "week",
                                                "player_id"],
                         on="_script", aggregate_function="first")
            .rename(lambda c: {"trailing": "share_trailing",
                               "neutral": "share_neutral",
                               "leading": "share_leading"}.get(c, c)))
    for c in ("share_trailing", "share_neutral", "share_leading"):
        if c not in wide.columns:
            wide = wide.with_columns(pl.lit(None, dtype=pl.Float64).alias(c))

    wide = wide.with_columns(
        (pl.col("share_trailing") - pl.col("share_neutral")).alias("script_lift")
    ).sort(["player_id", "season", "week"])

    exprs = []
    for col in ("share_trailing", "share_neutral", "share_leading", "script_lift"):
        shifted = pl.col(col).cast(pl.Float64).shift(1)
        exprs.extend([
            shifted.rolling_mean(medium, min_samples=2).over("player_id")
                   .alias(f"player_{col}_avg_{medium}g"),
            (shifted.cum_sum().over("player_id")
             / shifted.cum_count().over("player_id"))
                   .alias(f"player_{col}_szn_avg"),
        ])

    return (wide.with_columns(exprs)
            .select(["season", "week", "player_id"]
                    + [e.meta.output_name() for e in exprs]))


def fit_expected_trailing(pbp: pl.DataFrame, schedules: pl.DataFrame) -> dict:
    """How much of a game a team trails, as a function of the spread.

    Fitted, not assumed. The spread is already a feature, but what the model
    needs is the *game state it implies* — and the mapping from "7-point
    underdog" to "trails for 55% of snaps" is an empirical fact that changes
    with the era's scoring environment. Returns coefficients so a re-run
    re-fits rather than inheriting a number typed once.
    """
    import numpy as np

    need = {"posteam", "score_differential", "game_id"}
    if not need <= set(pbp.columns) or schedules is None:
        return {}

    plays = pbp.filter(
        pl.col("posteam").is_not_null()
        & pl.col("score_differential").is_not_null()
    )
    obs = (plays.group_by(["game_id", "posteam"])
           .agg((pl.col("score_differential") <= -TRAILING_BY).mean()
                .alias("trailing_share"))
           .rename({"posteam": "team"}))

    sched = schedules.select(["game_id", "home_team", "away_team", "spread_line"])
    home = sched.select(["game_id", pl.col("home_team").alias("team"),
                         pl.col("spread_line").alias("spread")])
    away = sched.select(["game_id", pl.col("away_team").alias("team"),
                         (-pl.col("spread_line")).alias("spread")])
    joined = obs.join(pl.concat([home, away]), on=["game_id", "team"],
                      how="inner").drop_nulls(["spread", "trailing_share"])
    if joined.height < 500:
        return {}

    x = joined["spread"].to_numpy()
    y = joined["trailing_share"].to_numpy()
    slope, intercept = np.polyfit(x, y, 1)
    resid = y - (slope * x + intercept)
    return {
        "kind": "expected_trailing",
        "trailing_by": TRAILING_BY,
        "slope": float(slope),
        "intercept": float(intercept),
        "rmse": float(np.sqrt((resid ** 2).mean())),
        "n": int(joined.height),
        # A negative slope is the expected direction: a bigger favourite (higher
        # spread) trails less. If this ever comes out positive the spread's sign
        # convention has flipped again, which has happened twice in this project.
        "direction_ok": bool(slope < 0),
    }
