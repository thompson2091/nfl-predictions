"""What a team's coordinators have done before this game.

The head coach is on every schedule row and his record is already a feature —
`coach_ats_rate_prior` ranks 6th of 174 by split gain and improves nothing out
of sample, which is worth remembering before reading anything here as promise.
The argument for going a level down is that a head coach is a manager and a
coordinator is the person calling the plays, so a unit's form should attach to
him rather than to the club.

Sourced from `ingest/coordinators`, which reads Wikipedia's season articles
and the current staff templates: 90% of team-seasons back to 2010 and 100% of
this one.

**THE MODEL PREFERS THEM TO THE HEAD COACH AND IS NO BETTER FOR IT.**

Ablated over seven walk-forward seasons, adding all eight moved margin MAE by
-0.040 and total by +0.047 — both a fraction of their own standard error — and
the betting test at a 3-point disagreement went 56.0% -> 56.5% on totals and
53.1% -> 51.6% on spreads. A wash, the same answer the situational family got.

What the importances show is worth more than the ablation:

    dc_pts_prior          rank   4 of 182
    oc_pts_prior          rank   6
    dc_ats_rate_prior     rank  13
    oc_ats_rate_prior     rank  21
    oc_is_new             rank 165
    dc_is_new             rank 169

and adding them pushed `coach_ats_rate_prior` from 6th to 27th. The model
swaps the head coach for the coordinator the moment it is offered one, which
is the handicapper's claim exactly — the coordinator calls the plays and the
head coach manages the building.

It still generalises no better, and the displacement says why: these are
SUBSTITUTES, not additions. A coordinator's prior points-for is a proxy for
how good his offence is, and the model already holds 160-odd team-form
features that measure the same thing from closer range. Being ranked 4th means
it is a convenient split, not that it carries anything new.

`oc_is_new` and `dc_is_new` are the two least-used of the eight, which is the
part worth being surprised by: a brand-new coordinator is the one situation
where team form genuinely does not carry over, and the model finds nothing
there either.

**Everything is as-of, and the shift is per person, not per team.** A
coordinator carries his record ACROSS clubs — that is the whole reason to
prefer him to the team — so the cumulative runs over his name and a first
season with a new club still knows what his offences did before. Computed the
natural way, over team and season, it would carry the result of the game being
predicted, which is the failure `game_model.leaky_columns` exists to catch.

**A coordinator's record is a season-level fact used at game level.** The
coordinators file says who held the job in a season, not in a week, so a
midseason replacement is attributed to whoever the article names. That is a
real limit and it biases toward the person who finished the year.
"""
from __future__ import annotations

import polars as pl

#: Below this many prior games a coordinator's rate is noise wearing a number.
#: Carried beside the rate rather than used to filter it, so a model can learn
#: to distrust a thin one.
MIN_GAMES = 16


def build_coordinator_features(schedules: pl.DataFrame,
                               coords: pl.DataFrame | None = None
                               ) -> pl.DataFrame:
    """Per team-game: who the coordinators are and what they had done before.

    One row per (game_id, team). Returns the keys plus the new columns only,
    so the caller decides what to join.
    """
    from src.ingest.coordinators import load

    coords = load() if coords is None else coords
    if coords.is_empty():
        return pl.DataFrame()

    s = (schedules.filter(pl.col("game_type") == "REG")
         .drop_nulls(["gameday", "result", "spread_line"]))
    if s.is_empty():
        return pl.DataFrame()
    s = s.with_columns([
        pl.col("gameday").str.to_date().alias("_date"),
        (pl.col("result") - pl.col("spread_line")).alias("_ats"),
    ])

    mk = lambda team, pts, against, cov: s.select([          # noqa: E731
        "game_id", "season", "_date",
        pl.col(team).alias("team"),
        pl.col(pts).alias("_pf"),
        pl.col(against).alias("_pa"),
        cov.alias("_cov"),
        (pl.col("_ats") == 0).alias("_push"),
    ])
    tg = pl.concat([
        mk("home_team", "home_score", "away_score", pl.col("_ats") > 0),
        mk("away_team", "away_score", "home_score", pl.col("_ats") < 0),
    ])

    tg = tg.join(coords.select(["season", "team", "oc", "dc"]),
                 on=["season", "team"], how="left")
    tg = _history(tg, "oc", "_pf", "oc_")
    tg = _history(tg, "dc", "_pa", "dc_")
    # Whether this is a new voice in the building, which is the one thing about
    # a coordinator that is knowable before he has a record at all.
    tg = tg.sort(["team", "season"]).with_columns([
        (pl.col("oc") != pl.col("oc").shift(1).over("team"))
        .cast(pl.Int8).alias("oc_is_new"),
        (pl.col("dc") != pl.col("dc").shift(1).over("team"))
        .cast(pl.Int8).alias("dc_is_new"),
    ])
    return tg.drop(["_date", "_pf", "_pa", "_cov", "_push", "oc", "dc",
                    "season"], strict=False)


def _history(tg: pl.DataFrame, who: str, stat: str, prefix: str
             ) -> pl.DataFrame:
    """Games, points and cover rate for one coordinator BEFORE each game.

    `cum_sum().shift()` over a date-sorted frame, partitioned by the PERSON.
    Partitioning by team instead would reset his record every time he moved,
    which throws away the only thing a coordinator-level feature has that a
    team-level one does not.
    """
    tg = tg.sort(["_date", "game_id"])
    graded = pl.col("_cov").is_not_null() & ~pl.col("_push")
    played = pl.col("_cov").is_not_null()

    # TWO denominators, because the two rates are about different things. A
    # push is not a cover and not a loss, so it leaves the ATS rate alone —
    # but it IS a game in which points were scored, so it belongs in the
    # points average. Summing points over every row and dividing by the
    # non-push count mixes them and inflates points per game by the push rate.
    o = [who]
    tg = tg.with_columns([
        pl.when(graded).then(1).otherwise(0).cum_sum().over(o).shift(1).over(o)
          .alias(prefix + "games_prior"),
        pl.when(played).then(1).otherwise(0).cum_sum().over(o).shift(1).over(o)
          .alias("_played"),
        pl.when(graded).then(pl.col("_cov")).otherwise(0)
          .cum_sum().over(o).shift(1).over(o).alias("_c"),
        pl.when(played).then(pl.col(stat)).otherwise(0)
          .cum_sum().over(o).shift(1).over(o).alias("_p"),
    ])
    n, np_ = pl.col(prefix + "games_prior"), pl.col("_played")
    return tg.with_columns([
        pl.col(prefix + "games_prior").fill_null(0),
        # Null, not a league average, where there is no history. A coordinator
        # in his first game has no rate, and inventing one hands the model a
        # fact that is really an absence.
        pl.when(n >= MIN_GAMES).then(pl.col("_c") / n)
          .otherwise(None).alias(prefix + "ats_rate_prior"),
        pl.when(np_ >= MIN_GAMES).then(pl.col("_p") / np_)
          .otherwise(None).alias(prefix + "pts_prior"),
    ]).drop(["_c", "_p", "_played"])
