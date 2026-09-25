"""What a defense and its return units actually do, and how loosely the other
side holds the ball.

Phase 2 measured why DEF/ST cannot be ranked: of 319 features only 44 are
non-null and varying on DEF/ST rows, a model trained on those rows alone reaches
AUC 0.5045, and "nothing describes takeaway ability, return units, or the
opponent's turnover-proneness". Every one of those three is sitting in
`pbp.parquet` and has been the whole time — `interception`, `fumble_lost`,
`sack`, `qb_hit`, `return_touchdown`, `safety`, `punt_blocked` are ~97%
populated across all eleven seasons, with no coverage cliff to work around.

The gap is structural, not incidental. `build_team_features` describes a team's
**offense** and joins on `team`; `build_opponent_features` describes what a
defense **allows** and joins on `opponent`. So a DEF/ST candidate for team T
carries T's offensive tendencies and the *other* team's defensive record, and
nothing at all about T's own defense. This module fills that hole from both
sides:

- `build_defense_features` — what T's defense and return units produce, joined
  on `team`. This is the row a DEF/ST candidate needs.
- `build_giveaway_features` — how often the opposing offense gives the ball
  away, joined on `opponent`. A defensive touchdown needs a turnover first, so
  the opponent's carelessness is arguably the stronger half of the pair, and
  nothing in the feature set encoded it.

Both follow the same leakage discipline as `team_features.py`: aggregate to
game-team, sort, `shift(1)` so a game never sees itself, then roll within team.

A caution the numbers demand: 864 return touchdowns exist across eleven seasons,
about 79 a season over ~272 games. These are rare events, and rare-event rates
computed over five games are mostly noise — which is why the season-to-date
column matters more here than the short window, and why this is expected to help
Top-5 and calibration rather than Top-1. Phase 3f showed defenses earn their
place in the candidate pool by being present, not by being ranked well.
"""
from __future__ import annotations

import polars as pl

from src.utils.config import get_config


def _rolling(frame: pl.DataFrame, key: str, stat_cols: list[str],
             prefix: str) -> pl.DataFrame:
    """Shift-then-roll within `key`, matching team_features.py exactly.

    The shift must happen inside the `over` so a team's first game does not
    inherit the previous team's last one. Sorting by (key, season, week) is what
    makes the window mean "this team's previous games" rather than "whatever row
    came before".
    """
    cfg = get_config()
    short = cfg["rolling_windows"]["short"]
    medium = cfg["rolling_windows"]["medium"]

    frame = frame.sort([key, "season", "week"])
    exprs = []
    for col in stat_cols:
        shifted = pl.col(col).shift(1)
        for window, label in ((short, f"{short}g"), (medium, f"{medium}g")):
            exprs.append(
                shifted.rolling_mean(window, min_samples=3)
                .over(key).alias(f"{prefix}_{col}_avg_{label}")
            )
        exprs.append(
            (shifted.cum_sum().over(key) / shifted.cum_count().over(key))
            .alias(f"{prefix}_{col}_szn_avg")
        )
    return (frame.with_columns(exprs)
            .select(["game_id", "season", "week", key]
                    + [e.meta.output_name() for e in exprs]))


def build_defense_features(pbp: pl.DataFrame) -> pl.DataFrame:
    """What team T's defense and return units produce. Joins on `team`.

    Takeaways are counted from the defending side: an interception on a play is
    a takeaway for whoever is on defense, and `fumble_lost` is recorded from the
    offense's point of view, so on a play where T is `defteam` a lost fumble is
    T's recovery.

    Scores are attributed with `td_team`, not with `posteam`. On a pick-six or a
    punt return the scoring side is the one that was *defending* the play, so
    reading `posteam` would credit every defensive touchdown to the offense that
    turned the ball over.
    """
    needed = {"defteam", "game_id", "season", "week"}
    missing = needed - set(pbp.columns)
    if missing:
        raise ValueError(f"pbp is missing {sorted(missing)}")

    def col(name: str, default=0):
        return (pl.col(name).fill_null(default) if name in pbp.columns
                else pl.lit(default))

    scored = (col("td_team") == pl.col("defteam")) if "td_team" in pbp.columns \
        else pl.lit(False)

    game_def = (
        pbp.filter(pl.col("defteam").is_not_null())
        .group_by(["game_id", "season", "week", "defteam"])
        .agg([
            col("interception").sum().alias("interceptions"),
            col("fumble_lost").sum().alias("fumbles_recovered"),
            (col("interception") + col("fumble_lost")).sum().alias("takeaways"),
            col("fumble_forced").sum().alias("fumbles_forced"),
            col("sack").sum().alias("sacks"),
            col("qb_hit").sum().alias("qb_hits"),
            col("safety").sum().alias("safeties"),
            col("punt_blocked").sum().alias("punts_blocked"),
            # The event this whole module exists to predict.
            (col("return_touchdown") * scored.cast(pl.Int32)).sum()
            .alias("return_tds"),
            (col("touchdown") * scored.cast(pl.Int32)).sum().alias("defst_tds"),
        ])
    )

    stat_cols = ["interceptions", "fumbles_recovered", "takeaways",
                 "fumbles_forced", "sacks", "qb_hits", "safeties",
                 "punts_blocked", "return_tds", "defst_tds"]
    return (_rolling(game_def, "defteam", stat_cols, "def")
            .rename({"defteam": "team"}))


def build_giveaway_features(pbp: pl.DataFrame) -> pl.DataFrame:
    """How loosely an offense holds the ball. Joins on `opponent`.

    A defensive touchdown needs a turnover before it needs a defense, so on a
    DEF/ST row this describes the other half of the event. Counted from the
    offense's side — `posteam` throws the interception and loses the fumble —
    and then joined against `opponent` so a candidate's row carries the
    carelessness of the offense its defense is facing.
    """
    if "posteam" not in pbp.columns:
        raise ValueError("pbp is missing posteam")

    def col(name: str, default=0):
        return (pl.col(name).fill_null(default) if name in pbp.columns
                else pl.lit(default))

    game_off = (
        pbp.filter(pl.col("posteam").is_not_null())
        .group_by(["game_id", "season", "week", "posteam"])
        .agg([
            col("interception").sum().alias("ints_thrown"),
            col("fumble_lost").sum().alias("fumbles_lost"),
            (col("interception") + col("fumble_lost")).sum().alias("giveaways"),
            col("sack").sum().alias("sacks_allowed"),
        ])
    )

    stat_cols = ["ints_thrown", "fumbles_lost", "giveaways", "sacks_allowed"]
    return (_rolling(game_off, "posteam", stat_cols, "oppoff")
            .rename({"posteam": "opponent"}))
