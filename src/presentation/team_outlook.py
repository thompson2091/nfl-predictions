"""Team-level view of a game: who scores first, and how much scoring is coming.

The board answers "which player", one row at a time. The question underneath it —
which *team* — is never shown, even though the model has an opinion and that
opinion is measurably good.

Three numbers per team, each chosen because it carries information. Measured on
four walk-forward folds, 2,278 team-games:

**First-TD share.** The team's players' first-TD probabilities, summed and
normalised within the game. Exactly one team scores first, so this is a true
50/50 question, and the model beats a coin flip on it: AUC 0.674, Brier 0.2213
against 0.25. It is calibrated across the range — 5.6% predicted against 5.5%
actual at the bottom, 94.4% against 94.5% at the top, 45.4% against 49.0% in the
middle. This is the number worth putting on screen.

**Expected touchdowns.** The team rate itself — lambda from the fitted Poisson
on the betting lines. It spans roughly 1.5 to 2.7 across teams, so it separates
games; P(at least one touchdown) does not, and that is why it is not here.

**Shut-out risk.** P(no offensive touchdown) = exp(-lambda). A team scores at
least once in 92.3% of team-games, so "will they score" is nearly always yes —
but the model does discriminate the exceptions, at AUC 0.918. Framed as the risk
rather than the near-certainty, it says something; framed the other way it reads
93% for everybody.

Deliberately absent: P(team scores at least one anytime touchdown). It is 92.3%
for almost every team in almost every game. Putting a number on screen that is
always the same teaches a reader to ignore that column.
"""
from __future__ import annotations

import numpy as np
import polars as pl


#: A team with fewer candidates than this has a roster problem, not a scoring
#: problem, and its share describes the feed rather than the football.
#:
#: A healthy team carries 13 to 30 candidates after `_filter_low_activity`. The
#: floor exists because the roster feed genuinely fails: 2015 has 83 team-weeks
#: below it (the earliest season's rosters are thin) and the 2026 pre-season has
#: 513, because next year's rosters are not published yet. Arizona in 2026 week
#: 1 has exactly one candidate — the DEF/ST placeholder — which normalises to
#: its opponent scoring first 99.2% of the time. That number is not a
#: prediction, and publishing it unmarked is how a data outage gets read as
#: football.
MIN_CANDIDATES = 5


def first_td_share(predictions: pl.DataFrame, prob_col: str = "probability",
                   team_col: str = "team", game_col: str = "game_id",
                   min_candidates: int = MIN_CANDIDATES) -> pl.DataFrame:
    """Each team's chance of scoring the game's first touchdown.

    Summed within the team and normalised within the game, because exactly one
    team scores first and the two must therefore add to one. Normalising is not
    cosmetic: the per-player probabilities are published against the whole
    candidate pool, and a game whose pool is thin would otherwise return two
    numbers that do not sum to anything in particular.

    A game where either side is below `min_candidates` returns a null share for
    both — the split is a statement about the roster feed, and the *opponent's*
    number is exactly as corrupted as the thin team's, since one is one minus
    the other.
    """
    team = (predictions.group_by([game_col, team_col])
            .agg([pl.col(prob_col).sum().alias("_p"),
                  pl.len().alias("candidates")]))
    thin = (team.group_by(game_col)
            .agg((pl.col("candidates").min() < min_candidates).alias("_thin")))
    return (
        team.join(thin, on=game_col, how="left")
        .with_columns(
            pl.when(pl.col("_thin"))
            .then(None)
            .otherwise(pl.col("_p") / pl.col("_p").sum().over(game_col))
            .alias("first_td_pct"))
        .drop(["_p", "_thin"]).sort([game_col, team_col])
    )


def expected_scorers(predictions: pl.DataFrame, prob_col: str = "probability",
                     team_col: str = "team",
                     game_col: str = "game_id") -> pl.DataFrame:
    """How many distinct players the team is expected to get into the endzone.

    The sum of per-player P(scores at least one), which is an expected count of
    *scorers* rather than of touchdowns — a player who scores twice contributes
    one to this and two to the scoreboard. Measured, it runs about 2.1 against
    2.4 actual touchdowns per team-game, and that gap is the multi-touchdown
    games rather than a miscalibration.
    """
    return (predictions.group_by([game_col, team_col])
            .agg(pl.col(prob_col).sum().alias("expected_scorers"))
            .sort([game_col, team_col]))


def team_scoring_rate(team_lambda: pl.DataFrame,
                      lambda_col: str = "team_lambda") -> pl.DataFrame:
    """Expected touchdowns and shut-out risk, from the fitted team rate.

    `exp(-lambda)` is P(zero touchdowns) under the Poisson the rate was fitted
    as. Averaged it lands near 8.8% against an actual shut-out rate of 7.7%,
    which is close enough to publish and not close enough to call exact.
    """
    return team_lambda.with_columns([
        pl.col(lambda_col).alias("expected_tds"),
        (-pl.col(lambda_col)).exp().alias("shutout_pct"),
    ])


def build(first_td_preds: pl.DataFrame | None,
          anytime_preds: pl.DataFrame | None,
          team_lambda: pl.DataFrame | None = None) -> pl.DataFrame:
    """One row per team-game, with whichever of the three numbers are available.

    Every input is optional because the app can be pointed at a week where one
    market has been scored and the other has not. A column that cannot be
    computed is absent rather than filled with a placeholder — a blank is
    honest, a zero is a claim.
    """
    frames = []
    if first_td_preds is not None and first_td_preds.height:
        frames.append(first_td_share(first_td_preds))
    if anytime_preds is not None and anytime_preds.height:
        frames.append(expected_scorers(anytime_preds))
    if team_lambda is not None and team_lambda.height:
        frames.append(team_scoring_rate(team_lambda)
                      .select(["game_id", "team", "expected_tds", "shutout_pct"]))
    if not frames:
        return pl.DataFrame()

    out = frames[0]
    for f in frames[1:]:
        out = out.join(f, on=["game_id", "team"], how="full", coalesce=True)
    return out.sort(["game_id", "team"])


def top_scorer_per_team(predictions: pl.DataFrame, prob_col: str = "probability",
                        name_col: str = "player_name") -> pl.DataFrame:
    """The single likeliest scorer on each team, to name the number.

    A team-level probability with no player attached invites the reader to
    supply their own, which is usually the most famous name on the roster
    rather than the one the model is actually pointing at.
    """
    return (predictions.sort(prob_col, descending=True)
            .group_by(["game_id", "team"])
            .agg([pl.col(name_col).first().alias("top_player"),
                  pl.col(prob_col).first().alias("top_player_pct")])
            .sort(["game_id", "team"]))
