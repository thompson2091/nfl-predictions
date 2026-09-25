"""Where a game sits in a team's week, and what its coach has done before.

The angles a handicapper reaches for first: prime time, a short week, a team
off a bye, a coach's record against the spread. Tested one at a time on
2,853 games not one of them clears the vig, and every interval is four to
nine points wide — which is what a 171-game bucket buys you and is the reason
this file does not ship any of them as a rule.

They are FEATURES, not rules. A univariate split asks whether one slice beats
52.38% on its own; a model asks whether the information helps once everything
else is known. Those are different questions and the second is the one worth
asking, because it pools the sample instead of cutting it.

**ASKED, AND THE ANSWER WAS NO.** Ablated in `game_model.walk_forward` over
seven seasons, adding all thirteen moved margin MAE by +0.077 and total MAE by
-0.066 — both a fraction of their own standard error — and the betting test at
a 3-point disagreement went 55.2% -> 56.0% on totals and 53.7% -> 53.1% on
spreads, inside +/-3.0 either way. That is a wash.

The importances say something the ablation does not, and it is worth keeping:

    coach_ats_rate_prior          rank   6 of 174
    coach_win_rate_prior          rank  22
    rest_diff                     rank 122
    is_prime_slot                 rank 159
    is_short_week                 rank 168
    is_off_bye                    rank 173
    opp_off_bye                   rank 174

The coach history is used HARD and changes nothing out of sample, which is
what fitting noise looks like from the inside. The slot and rest flags are the
four least-used features in the model. Both halves are worth knowing before
anyone adds more of the same: the handicapper's situational list is not being
ignored here for lack of trying, it has been measured twice, two ways.


**Every history here is as-of.** A coach's cover rate is computed from the
games before the one being scored, never including it, via a shifted cumulative
sum. Computed the natural way — a group-by over the whole season — it would
carry the result of the game it is about to predict, and the model would read
it as skill. That is the same failure `game_model.leaky_columns` was written
to catch after it turned a shutout into a 72.8% hit rate.
"""
from __future__ import annotations

import polars as pl

#: A week shorter than this is a short week. Thursday off a Sunday is four
#: days; anything at or under it had no ordinary practice week.
SHORT_WEEK_DAYS = 4

#: A bye is a week off, so the rest gap runs to roughly a fortnight. Teams
#: coming off one sit at 13-14 days where a normal week is 6-7.
BYE_REST_DAYS = 13

#: Below this many prior games a coach's rate is noise wearing a number. It is
#: not a filter — the rate is still computed — it is carried beside it so a
#: model can learn to distrust a thin one, and so the page can refuse to print
#: "69.4% in prime time" off 36 games without saying 36.
MIN_COACH_GAMES = 20


def _haversine_miles(lat1, lon1, lat2, lon2) -> pl.Expr:
    """Great-circle distance, for how far the away side travelled."""
    r = 3958.8
    p1, p2 = lat1 * 3.14159265 / 180, lat2 * 3.14159265 / 180
    dp = (lat2 - lat1) * 3.14159265 / 180
    dl = (lon2 - lon1) * 3.14159265 / 180
    a = ((dp / 2).sin() ** 2
         + p1.cos() * p2.cos() * (dl / 2).sin() ** 2)
    return 2 * r * a.sqrt().arcsin()


def build_situational_features(schedules: pl.DataFrame) -> pl.DataFrame:
    """Per team-game: the slot it sits in, the rest around it, and coach form.

    One row per (game_id, team). Returns only the new columns plus the keys,
    so the caller decides what to join and nothing here can quietly replace an
    existing column.
    """
    from src.features.stadium_coords import STADIUM_COORDS

    s = (schedules.filter(pl.col("game_type") == "REG")
         .drop_nulls(["gameday", "gametime"]))
    if s.is_empty():
        return pl.DataFrame()

    s = s.with_columns([
        pl.col("gameday").str.to_date().alias("_date"),
        pl.col("gametime").str.slice(0, 2).cast(pl.Int32).alias("kick_hour"),
    ])
    s = s.with_columns([
        pl.col("_date").dt.weekday().alias("dow"),
        # Prime time is the slot, not the day: a Sunday 20:20 kickoff is prime
        # time and a Sunday 13:00 is not, while Thursday and Monday always are.
        (pl.col("_date").dt.weekday().is_in([1, 4])
         | ((pl.col("_date").dt.weekday() == 7) & (pl.col("kick_hour") >= 20))
         ).cast(pl.Int8).alias("is_prime_slot"),
    ])

    # Graded against the spread, from the home side's view. `result` is home
    # minus away and `spread_line` is positive when the home team is favoured,
    # both verified against the schedule rather than assumed.
    s = s.with_columns(
        (pl.col("result") - pl.col("spread_line")).alias("_ats_home"))

    home = s.select([
        "game_id", "season", "week", "_date", "dow", "kick_hour",
        "is_prime_slot",
        pl.col("home_team").alias("team"),
        pl.col("home_coach").alias("coach"),
        pl.col("home_rest").alias("rest"),
        pl.col("away_rest").alias("opp_rest"),
        pl.lit(1, dtype=pl.Int8).alias("at_home"),
        (pl.col("_ats_home") > 0).cast(pl.Int8).alias("covered"),
        (pl.col("_ats_home") == 0).alias("_push"),
        (pl.col("result") > 0).cast(pl.Int8).alias("won"),
        pl.col("stadium"),
    ])
    away = s.select([
        "game_id", "season", "week", "_date", "dow", "kick_hour",
        "is_prime_slot",
        pl.col("away_team").alias("team"),
        pl.col("away_coach").alias("coach"),
        pl.col("away_rest").alias("rest"),
        pl.col("home_rest").alias("opp_rest"),
        pl.lit(0, dtype=pl.Int8).alias("at_home"),
        (pl.col("_ats_home") < 0).cast(pl.Int8).alias("covered"),
        (pl.col("_ats_home") == 0).alias("_push"),
        (pl.col("result") < 0).cast(pl.Int8).alias("won"),
        pl.col("stadium"),
    ])
    tg = pl.concat([home, away], how="vertical_relaxed")

    tg = tg.with_columns([
        (pl.col("rest") - pl.col("opp_rest")).alias("rest_diff"),
        (pl.col("rest") <= SHORT_WEEK_DAYS).cast(pl.Int8).alias("is_short_week"),
        (pl.col("opp_rest") <= SHORT_WEEK_DAYS).cast(pl.Int8).alias("opp_short_week"),
        (pl.col("rest") >= BYE_REST_DAYS).cast(pl.Int8).alias("is_off_bye"),
        (pl.col("opp_rest") >= BYE_REST_DAYS).cast(pl.Int8).alias("opp_off_bye"),
    ])
    tg = _coach_history(tg)
    return tg.drop(["_date", "_push", "covered", "won", "coach", "stadium",
                    "rest", "opp_rest"], strict=False)


def _coach_history(tg: pl.DataFrame) -> pl.DataFrame:
    """A coach's record BEFORE each game, never including it.

    `cum_sum().shift()` over a date-sorted frame, per coach. The shift is the
    whole point: without it the rate carries the outcome of the row it is
    attached to, and a model reads "this coach covers 100% of the time" off a
    single game it is being asked to predict.

    Pushes are excluded from the cover rate and from its denominator. A push
    is not a cover and is not a loss, and counting it either way biases every
    coach by however often lines land on the number.
    """
    tg = tg.sort(["_date", "game_id"])
    graded = pl.col("covered").is_not_null() & ~pl.col("_push")
    one = pl.when(graded).then(1).otherwise(0)
    cov = pl.when(graded).then(pl.col("covered")).otherwise(0)
    prime = pl.when(graded & (pl.col("is_prime_slot") == 1)).then(1).otherwise(0)
    prime_cov = pl.when(graded & (pl.col("is_prime_slot") == 1)) \
        .then(pl.col("covered")).otherwise(0)

    over = ["coach"]
    tg = tg.with_columns([
        one.cum_sum().over(over).shift(1).over(over).alias("coach_games_prior"),
        cov.cum_sum().over(over).shift(1).over(over).alias("_cov_prior"),
        pl.col("won").cum_sum().over(over).shift(1).over(over).alias("_won_prior"),
        prime.cum_sum().over(over).shift(1).over(over).alias("coach_prime_games_prior"),
        prime_cov.cum_sum().over(over).shift(1).over(over).alias("_prime_cov_prior"),
    ])
    n = pl.col("coach_games_prior")
    pn = pl.col("coach_prime_games_prior")
    return tg.with_columns([
        pl.col("coach_games_prior").fill_null(0),
        pl.col("coach_prime_games_prior").fill_null(0),
        # Null, not 0.5, when there is no history. A coach with no prior games
        # has no rate; inventing one hands the model a fact that is really an
        # absence, and LightGBM handles a null natively.
        pl.when(n > 0).then(pl.col("_cov_prior") / n)
          .otherwise(None).alias("coach_ats_rate_prior"),
        pl.when(n > 0).then(pl.col("_won_prior") / n)
          .otherwise(None).alias("coach_win_rate_prior"),
        pl.when(pn >= MIN_COACH_GAMES).then(pl.col("_prime_cov_prior") / pn)
          .otherwise(None).alias("coach_prime_ats_rate_prior"),
    ]).drop(["_cov_prior", "_won_prior", "_prime_cov_prior"])
