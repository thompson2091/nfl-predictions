"""Where is Top-1 actually lost?

Phase 3 of docs/MODEL_ITERATION.md is a list of things that might raise Top-1.
Working through it in the order they were thought of is how effort goes into the
half of the problem that was already fine. This measures which half is broken,
so the list gets ordered by evidence.

Five questions, each answerable from the walk-forward's per-game and per-player
rows plus the odds archive. None of them change the model.

1. **How much headroom is there?** Rank the same games by the sportsbook's
   de-vigged price and compare, paired. If the book is well ahead there is
   accuracy to win; if we are level or ahead, the ceiling is close and the
   honest report says so.
2. **Right team, wrong player — or wrong team?** Anytime TD is factored exactly
   that way (`team_lambda` x `share`), so this splits the error into "the
   market-driven Poisson rate is wrong" and "the usage model is wrong". Those
   have completely different fixes and there is no point guessing which.
3. **How many games were winnable?** The rank the actual scorer landed on, and
   the share of games whose top two are within a point — coin flips, which cap
   what is available.
4. **Where do the misses concentrate?** By scorer position, favourite or
   underdog, game total, week. `stage2.py` already documents a 9.2-point
   quarterback miss; this is where that kind of thing surfaces.
5. **What can the pool not reach?** Games whose scorer the filter removed, and
   games with no scorer in the pool at all.
"""
from __future__ import annotations

import numpy as np
import polars as pl

#: A book that priced only a handful of players in a game is not offering a
#: ranking to compare against — it is offering a shortlist. Below this the game
#: is excluded from the market benchmark and the exclusion is reported.
MIN_PRICED_PER_GAME = 8

POSITIONS = {"position_QB": "QB", "position_WR": "WR", "position_TE": "TE",
             "position_FB": "FB", "position_DEFST": "DEF/ST"}


def _position(df: pl.DataFrame) -> pl.Series:
    """Position from the one-hot columns, with RB as the baseline.

    `with_columns` rather than `select`, so a frame carrying none of the
    one-hot columns broadcasts the baseline to its full height instead of
    returning a single row.
    """
    expr = pl.lit("RB")
    for col, name in POSITIONS.items():
        if col in df.columns:
            expr = pl.when(pl.col(col) == 1).then(pl.lit(name)).otherwise(expr)
    return df.with_columns(expr.alias("_position"))["_position"]


# --------------------------------------------------------------------------
# 1. Headroom: can the sportsbook rank these games better than we can?
# --------------------------------------------------------------------------

def market_benchmark(players: pl.DataFrame, graded: pl.DataFrame) -> dict:
    """Model against the book, over the players the book actually priced.

    Both sides rank the **same player set** in the **same games**: the priced
    ones. Anything else compares a ranking over 33 candidates with a ranking
    over 27 and calls the difference skill.

    Ordering is taken from `fair_prob` where the book posted both sides, and
    from `implied_prob` otherwise. The one-sided de-vig is a per-game scalar,
    so it cannot reorder a game — only the two-sided fair price can, and that
    is used where it exists.

    Paired, because the two rank the same games: the information is in the
    games where they disagree.
    """
    priced = (
        graded.select(["game_id", "player_id", "implied_prob", "fair_prob"])
        .unique(subset=["game_id", "player_id"])
        .with_columns(
            pl.coalesce([pl.col("fair_prob"), pl.col("implied_prob")])
            .alias("market_prob"))
    )
    joined = players.join(priced, on=["game_id", "player_id"], how="inner")
    if joined.height == 0:
        return {"available": False,
                "reason": "no overlap between scored players and the odds archive"}

    counts = joined.group_by("game_id").agg(pl.len().alias("n_priced"))
    deep = counts.filter(pl.col("n_priced") >= MIN_PRICED_PER_GAME)
    joined = joined.join(deep.select("game_id"), on="game_id", how="inner")

    # A game the book cannot win either — nobody it priced scored — measures
    # nothing about ranking, so both sides are scored over games where the
    # priced set contains a scorer.
    winnable = (joined.filter(pl.col("target") == 1)
                .select("game_id").unique())
    joined = joined.join(winnable, on="game_id", how="inner")
    if joined.height == 0:
        return {"available": False, "reason": "no priced game had a priced scorer"}

    ranked = joined.with_columns([
        pl.col("prob").rank(descending=True, method="ordinal")
        .over("game_id").alias("rank_model"),
        pl.col("market_prob").rank(descending=True, method="ordinal")
        .over("game_id").alias("rank_market"),
    ])
    per_game = ranked.filter(pl.col("target") == 1).group_by("game_id").agg([
        pl.col("rank_model").min().alias("best_model"),
        pl.col("rank_market").min().alias("best_market"),
    ])

    out = {"available": True, "games": per_game.height,
           "min_priced_per_game": MIN_PRICED_PER_GAME,
           "games_dropped_thin": int(counts.height - deep.height)}
    for k in (1, 3, 5):
        a = (per_game["best_market"] <= k).to_numpy().astype(int)
        b = (per_game["best_model"] <= k).to_numpy().astype(int)
        d = b - a
        se = float(d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 else 0.0
        out[f"top{k}"] = {
            "market": float(a.mean()), "model": float(b.mean()),
            "delta": float(d.mean()), "se": se,
            "se_multiple": float(d.mean() / se) if se else 0.0,
            "model_wins": int(((a == 0) & (b == 1)).sum()),
            "market_wins": int(((a == 1) & (b == 0)).sum()),
        }
    return out


# --------------------------------------------------------------------------
# 2. Which half of the factorisation is wrong
# --------------------------------------------------------------------------

def team_vs_player(players: pl.DataFrame) -> dict:
    """Of the games we miss, how many did we at least pick the right team for?

    Three outcomes per game:

      * **hit** — the top-ranked player scored.
      * **right team, wrong player** — somebody on the top pick's team scored,
        but not our pick. The team rate was right and the share was wrong.
      * **wrong team** — nobody on that team scored at all.

    The split says which factor to work on. A model that is nearly always on the
    right team has a usage problem; one that picks the wrong team has a scoring
    rate problem, and the rate is driven by the betting lines rather than by
    anything the player model can fix.
    """
    top1 = (players.filter(pl.col("rank") == 1)
            .select(["game_id", "team", "player_id", "target"])
            .rename({"team": "pick_team", "player_id": "pick_player",
                     "target": "pick_scored"}))
    scoring_teams = (players.filter(pl.col("target") == 1)
                     .select(["game_id", "team"]).unique()
                     .with_columns(pl.lit(True).alias("_team_scored")))

    joined = (top1.join(scoring_teams,
                        left_on=["game_id", "pick_team"],
                        right_on=["game_id", "team"], how="left")
              .with_columns(pl.col("_team_scored").fill_null(False)))

    n = joined.height
    hit = int(joined.filter(pl.col("pick_scored") == 1).height)
    right_team = int(joined.filter((pl.col("pick_scored") != 1)
                                   & pl.col("_team_scored")).height)
    wrong_team = n - hit - right_team
    misses = max(n - hit, 1)
    return {
        "games": n, "hit": hit,
        "right_team_wrong_player": right_team,
        "wrong_team": wrong_team,
        "hit_share": hit / n if n else 0.0,
        "of_misses_right_team": right_team / misses,
        "of_misses_wrong_team": wrong_team / misses,
    }


# --------------------------------------------------------------------------
# 3. How winnable were the games
# --------------------------------------------------------------------------

def winnability(outcomes: pl.DataFrame) -> dict:
    """Where the scorer ranked, and how many games were coin flips.

    A game whose top two probabilities sit within a point is a coin flip by the
    model's own reckoning. Reading Top-1 on those separately from the decided
    games says how much of the remaining gap is even available: if the coin
    flips already land at 50% the model is not losing them, it is being asked an
    unanswerable question.
    """
    n = outcomes.height
    ranked = outcomes.filter(pl.col("best_rank").is_not_null())
    dist = (ranked.group_by("best_rank").len()
            .sort("best_rank").head(10).rows())

    flips = outcomes.filter(pl.col("top_gap") < 0.01)
    decided = outcomes.filter(pl.col("top_gap") >= 0.01)
    return {
        "games": n,
        "rank_histogram": [{"rank": int(r), "games": int(c)} for r, c in dist],
        "median_rank": float(ranked["best_rank"].median()) if ranked.height else None,
        "coin_flip_games": flips.height,
        "coin_flip_share": flips.height / n if n else 0.0,
        "top1_in_coin_flips": float(flips["hit1"].mean()) if flips.height else None,
        "top1_in_decided": float(decided["hit1"].mean()) if decided.height else None,
    }


# --------------------------------------------------------------------------
# 4. Where the misses concentrate
# --------------------------------------------------------------------------

def slices(players: pl.DataFrame, outcomes: pl.DataFrame) -> dict:
    """Top-1 cut by things a model could plausibly be systematically wrong about."""
    top1 = players.filter(pl.col("rank") == 1)
    top1 = top1.with_columns(_position(top1).alias("pick_position"))

    scorers = players.filter(pl.col("target") == 1)
    scorers = scorers.with_columns(_position(scorers).alias("scorer_position"))

    hits = outcomes.select(["game_id", "hit1"])

    # By the position of whoever actually scored: where does the ranking fail to
    # see it coming?
    by_scorer_pos = (
        scorers.select(["game_id", "scorer_position"]).unique()
        .join(hits, on="game_id", how="inner")
        .group_by("scorer_position")
        .agg([pl.col("hit1").mean().alias("top1"), pl.len().alias("games")])
        .sort("games", descending=True)
    )

    # By the position we backed: which picks do we get paid on?
    by_pick_pos = (
        top1.select(["game_id", "pick_position"])
        .join(hits, on="game_id", how="inner")
        .group_by("pick_position")
        .agg([pl.col("hit1").mean().alias("top1"), pl.len().alias("games")])
        .sort("games", descending=True)
    )

    # Favourite or underdog, from the picked player's team's point of view.
    #
    # `spread_line` in the feature table has already been flipped into each
    # team's own perspective, and is **positive when that team is favoured** —
    # `vegas_features` defines `is_favorite` as `spread_line > 0`. Reading it
    # the other way round is not hypothetical: this project shipped that exact
    # inversion once, and `tests/test_leakage.py::test_favourite_flag_is_not_
    # inverted` exists because teams marked favourite were winning 34.9% of
    # their games. Taking the value from the top-1 row is therefore right: it
    # is that pick's team's spread, not the home team's.
    context = top1.select(["game_id", "spread_line", "total_line"]).unique(
        subset=["game_id"])
    ctx = (context.join(hits, on="game_id", how="inner")
           .with_columns([
               pl.when(pl.col("spread_line") >= 3).then(pl.lit("pick on favourite"))
               .when(pl.col("spread_line") <= -3).then(pl.lit("pick on underdog"))
               .otherwise(pl.lit("close game")).alias("side"),
               pl.when(pl.col("total_line") >= 48).then(pl.lit("high total"))
               .when(pl.col("total_line") <= 41).then(pl.lit("low total"))
               .otherwise(pl.lit("mid total")).alias("total_band"),
           ]))

    def group(df, col):
        return (df.group_by(col)
                .agg([pl.col("hit1").mean().alias("top1"), pl.len().alias("games")])
                .sort("games", descending=True).to_dicts())

    return {
        "by_scorer_position": by_scorer_pos.to_dicts(),
        "by_pick_position": by_pick_pos.to_dicts(),
        "by_side": group(ctx, "side"),
        "by_total": group(ctx, "total_band"),
    }


# --------------------------------------------------------------------------
# 5. What the pool cannot reach
# --------------------------------------------------------------------------

def pool_ceiling(labelled: pl.DataFrame, filtered: pl.DataFrame) -> dict:
    """Games the ranking cannot win however good it gets.

    `labelled` is the unfiltered candidate pool for the scored seasons;
    `filtered` is what survived `_filter_low_activity`.
    """
    played = labelled["game_id"].n_unique()
    with_scorer = labelled.filter(pl.col("target") == 1)["game_id"].n_unique()
    reachable = filtered.filter(pl.col("target") == 1)["game_id"].n_unique()
    return {
        "played_games": played,
        "games_with_a_scorer_in_pool": with_scorer,
        "games_with_no_scorer_anywhere": played - with_scorer,
        "games_whose_scorer_the_filter_removed": with_scorer - reachable,
        "ceiling": reachable / with_scorer if with_scorer else 0.0,
        "pool_per_game": filtered.height / max(played, 1),
    }
