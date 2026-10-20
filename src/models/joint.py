"""Joint game model: how many touchdowns a team scores x whose they are.

The per-player classifier this replaces asks each player an independent
question — "do you score?" — and then a separate step rescales the game so the
answers add up. Two problems follow from that shape, and both showed up in
measurement rather than in theory.

The level has to be bolted on afterwards. `calibrate_level` shifts a whole
game's log-odds until the total matches a fitted scorers-per-game prior, which
works, but it is a correction applied to a model that had no idea the
constraint existed. And the blend that follows undoes part of it: the model
summed to 4.02 scorers per game against 4.04 actual, then came out at 3.90
after blending, because combining in logit space is not mass-preserving.

Teammates are treated as independent when they are anything but. Two running
backs on one team compete for the same goal-line carries; a touchdown for one
is evidence against the other on that drive. Independent binaries cannot say
that, so the model leans on correlated features to imply it and gets the
dependence approximately right by accident.

This module factors the problem the way the game actually works:

    team touchdowns  N_t ~ Poisson(lambda_t)      driven by the betting market
    whose they are   s_i                          driven by usage and matchup

A Poisson thinned by a share is Poisson, so the anytime-TD probability has a
closed form and needs no rescaling at all:

    P(player i scores at least one) = 1 - exp(-lambda_t * s_i)

Summing expected touchdowns over a team returns lambda_t exactly, by
construction. The constraint is structural, not a patch. Shares are multinomial
within a team, so players genuinely compete for the same touchdowns. And the
first-touchdown market falls out of the same two pieces rather than needing its
own model: if both teams' touchdowns arrive as competing Poisson processes,
the chance team t scores the game's first is lambda_t / (lambda_home +
lambda_away), and the scorer is drawn from that team's shares.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import polars as pl

from src.utils.paths import get_path


def td_counts(seasons: list[int] | None = None) -> pl.DataFrame:
    """Touchdowns per player per game — counts, not a scored/didn't flag.

    Rebuilt from play-by-play rather than read from the targets parquet, which
    is deliberately deduplicated to one row per scorer per game
    (`td_extractor._extract_anytime_td`). That is the right shape for a binary
    label and the wrong one here: it silently collapses every multi-touchdown
    game to a single event, which is exactly the signal a rate model needs.
    """
    pbp = pl.read_parquet(get_path("raw") / "pbp.parquet")
    tds = pbp.filter(
        (pl.col("touchdown") == 1)
        & pl.col("td_player_id").is_not_null()
        & (pl.col("td_player_id") != "")
        & pl.col("posteam").is_not_null()
        # Offensive touchdowns only: the share model runs over a team's
        # offensive candidates, and a pick-six belongs to the other team's
        # defense, not to this team's touchdown production.
        & (pl.col("td_team") == pl.col("posteam"))
    ).select(["game_id", "season", "week", "td_player_id", "td_team"])

    if seasons is not None:
        tds = tds.filter(pl.col("season").is_in(seasons))

    return (
        tds.group_by(["game_id", "season", "week", "td_player_id", "td_team"])
        .len()
        .rename({"td_player_id": "player_id", "td_team": "team", "len": "n_td"})
    )


def team_td_counts(seasons: list[int] | None = None) -> pl.DataFrame:
    """Offensive touchdowns per team per game."""
    return (
        td_counts(seasons)
        .group_by(["game_id", "season", "week", "team"])
        .agg(pl.col("n_td").sum().alias("team_tds"))
    )


# --------------------------------------------------------------------------
# 1. Team rate: how many touchdowns will this offense score
# --------------------------------------------------------------------------

#: Kept deliberately small. The betting market already prices team scoring
#: better than we can, so this model's job is to read the market's number and
#: convert points into touchdowns — not to re-forecast the game from scratch.
#: Every extra free parameter here is a chance to overfit away the market's
#: information.
TEAM_DESIGN = ["intercept", "implied_team_total", "total_line", "abs_spread"]


def _team_design(df: pl.DataFrame) -> np.ndarray:
    return np.column_stack([
        np.ones(df.height),
        df["implied_team_total"].fill_null(strategy="mean").to_numpy(),
        df["total_line"].fill_null(strategy="mean").to_numpy(),
        df["spread_line"].fill_null(0).abs().to_numpy(),
    ])


def fit_team_rate(features: pl.DataFrame, train_seasons: list[int]) -> dict:
    """Poisson regression of team offensive touchdowns on the betting lines.

    Poisson rather than least squares because the response is a small count
    with variance that grows with the mean, and because a log link cannot
    predict a negative touchdown rate — which ordinary least squares will
    happily do for a 34-point underdog.
    """
    teams = (
        features.filter(pl.col("target").is_not_null())
        .group_by(["game_id", "season", "team"])
        .agg([
            pl.col("implied_team_total").first(),
            pl.col("total_line").first(),
            pl.col("spread_line").first(),
        ])
    )
    actual = team_td_counts()
    d = (
        teams.filter(pl.col("season").is_in(train_seasons))
        .join(actual.select(["game_id", "team", "team_tds"]),
              on=["game_id", "team"], how="left")
        .with_columns(pl.col("team_tds").fill_null(0))
        .drop_nulls(["implied_team_total", "total_line"])
    )
    if d.height < 200:
        raise ValueError(f"Not enough team-games to fit a rate ({d.height}).")

    X = _team_design(d)
    y = d["team_tds"].to_numpy().astype(float)
    coef = _poisson_irls(X, y)

    lam = np.exp(X @ coef)
    return {
        "kind": "team_td_rate",
        "design_cols": TEAM_DESIGN,
        "coef": coef.tolist(),
        "seasons_used": sorted(train_seasons),
        "n_team_games": int(d.height),
        "mean_team_tds": float(y.mean()),
        "fitted_mean": float(lam.mean()),
        "rmse": float(np.sqrt(((y - lam) ** 2).mean())),
        "fit_date": date.today().isoformat(),
        "source": "nflverse play-by-play; lines from nflverse schedules",
    }


def _poisson_irls(X: np.ndarray, y: np.ndarray, iters: int = 50) -> np.ndarray:
    """Poisson GLM with a log link, by iteratively reweighted least squares.

    Hand-rolled to avoid adding statsmodels for one regression. IRLS on a
    canonical-link GLM is Newton's method, so convergence is quadratic and a
    few dozen iterations is generous.
    """
    coef = np.zeros(X.shape[1])
    coef[0] = np.log(max(y.mean(), 1e-6))
    for _ in range(iters):
        eta = np.clip(X @ coef, -10, 10)
        mu = np.exp(eta)
        W = np.maximum(mu, 1e-8)
        z = eta + (y - mu) / W
        XtW = X.T * W
        try:
            step = np.linalg.solve(XtW @ X, XtW @ z)
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(XtW @ X, XtW @ z, rcond=None)[0]
        if np.max(np.abs(step - coef)) < 1e-9:
            coef = step
            break
        coef = step
    return coef


def team_rate(model: dict, games: pl.DataFrame) -> pl.DataFrame:
    """Expected offensive touchdowns for each team-game."""
    coef = np.asarray(model["coef"], dtype=float)
    lam = np.exp(np.clip(_team_design(games) @ coef, -10, 10))
    return games.select(["game_id", "team"]).with_columns(
        pl.Series("team_lambda", lam)
    )


# --------------------------------------------------------------------------
# 2. Player share: given a touchdown, whose is it
# --------------------------------------------------------------------------


def _defst_mask(df: pl.DataFrame) -> pl.Expr:
    """Rows that are a team's defense/special teams rather than a player.

    A frame carrying neither identifier has no defenses in it — the joint model
    is exercised on synthetic team-share frames that are all offense — so the
    mask is empty rather than an error. Guessing from a missing column is how a
    unit test starts failing for a reason that has nothing to do with what it
    is testing.
    """
    if "position_DEFST" in df.columns:
        return pl.col("position_DEFST").fill_null(0) == 1
    if "player_id" in df.columns:
        return pl.col("player_id").cast(pl.Utf8).str.ends_with("_DEFST")
    return pl.lit(False)


def player_shares(rates: np.ndarray, df: pl.DataFrame,
                  exclude_defst: bool | None = None) -> pl.DataFrame:
    """Normalize per-player touchdown rates to shares within each team-game.

    The share model does not have to be calibrated in absolute terms — only
    correctly ordered and correctly proportioned within a team, because the
    level comes from the team rate. That is a strictly easier thing to learn
    than a calibrated probability, and it is the half of the problem a usage
    model is actually good at.

    **A defense is not a share of its offense.** `team_lambda` is fitted on
    offensive touchdowns alone — `td_counts` filters `td_team == posteam` and
    contains no DEF/ST rows at all — so normalizing the DEF/ST pseudo-player
    into the same denominator hands it a slice of a rate it cannot contribute
    to. Measured over four walk-forward folds, that published a defense as the
    game's most likely scorer in 131 of 1,131 games at a mean probability of
    **0.908**, against an actual rate of **0.153**. It does damage in both
    directions: the defense is wildly overstated, and every real player on that
    team is understated by whatever share it took.

    With `exclude_defst`, DEF/ST rows are held out of the denominator and given
    a share of zero; `combine` then leaves their probability as the calibrated
    classifier's own, which is what it was before the joint model touched it
    and is well calibrated (0.106 predicted against 0.103 actual over rows
    ranked 11th or worse, where the joint step barely moves them).
    """
    if exclude_defst is None:
        from src.utils.config import get_config
        exclude_defst = bool(
            get_config().get("joint", {}).get("exclude_defst_from_shares", False))

    out = df.with_columns(pl.Series("_rate", np.maximum(rates, 1e-9)))
    if not exclude_defst:
        return out.with_columns(
            (pl.col("_rate") / pl.col("_rate").sum().over(["game_id", "team"]))
            .alias("share")
        ).drop("_rate")

    out = out.with_columns(_defst_mask(out).alias("_is_defst"))
    offensive = pl.when(pl.col("_is_defst")).then(0.0).otherwise(pl.col("_rate"))
    denom = offensive.sum().over(["game_id", "team"])
    return out.with_columns(
        pl.when(pl.col("_is_defst")).then(0.0)
        .otherwise(pl.col("_rate") / pl.when(denom > 0).then(denom).otherwise(1.0))
        .alias("share")
    ).drop("_rate")


#: Marks a row no sportsbook quoted, for the split conversion level. Set by
#: the caller — `predict` knows who was priced because it has just joined the
#: market, and the trainer knows from the graded archive. Absent, every row is
#: treated as priced, which is the behavior before the split existed.
UNPRICED_COL = "_unpriced"


def combine(df: pl.DataFrame, share_col: str = "share",
            lambda_col: str = "team_lambda",
            out_col: str = "probability",
            conversion: dict | None = None,
            score_col: str | None = None) -> pl.DataFrame:
    """P(at least one touchdown) from a player's expected touchdown count.

    The obvious conversion is Poisson: thinning a Poisson process by a fixed
    share leaves a Poisson process, so `1 - exp(-mu)`. Measured against three
    seasons, that is wrong in a specific and costly way — it understates the
    players at the top badly:

        mu 0.567  ->  Poisson 0.428  vs  0.495 actual   (-6.8pp)
        mu 0.328  ->  Poisson 0.279  vs  0.328 actual   (-4.9pp)

    Poisson assumes a player's touchdowns arrive independently. They do not. A
    lead back's goal-line carries are close to guaranteed once the drive gets
    there, so his count is *less* dispersed than Poisson and his chance of at
    least one is correspondingly higher. Modeling the count as
    Binomial(r, mu/r) spans the range — r = 1 is a single all-or-nothing shot,
    r -> infinity recovers Poisson — and `r` is fitted rather than assumed.

    `level` corrects the scoring environment drifting away from the seasons the
    team rate was fitted on; it multiplies mu before the conversion.

    With both fitted (level 0.90, dispersion 1.15) the favorites band went from
    6.7 points low to 1.0 high on held-out 2025, and the published probabilities
    summed to 4.04 per game against 4.04 actual.
    """
    # Stash the incoming score before anything writes over it. Every caller
    # here passes score_col == out_col ("prob" -> "prob"), so reading it back
    # after the formula has run returns the formula's own output — which for a
    # held-out defense is 0, its share being zero. That published every defense
    # at exactly 0.000, and the tell was a DEF/ST AUC of exactly 0.5000: not a
    # weak ranking, an absent one.
    df = df.with_columns(pl.col(score_col).alias("_score_in")) \
        if score_col is not None else df

    mu = pl.col(lambda_col) * pl.col(share_col)
    if conversion:
        # One level for players a book quoted and another for the rest, when
        # the fit produced one and the caller marked the rows. A book declining
        # to quote a man is most of what is known about him: priced players
        # score at 16.1%, unpriced at 0.41%, and serving the priced level to
        # both put ~0.35 phantom scorers a game on the board — the whole of the
        # model's 7.6% aggregate over-prediction. See `fit_conversion`.
        lvl = pl.lit(float(conversion.get("level", 1.0)))
        u = conversion.get("unpriced_level")
        if u is not None and UNPRICED_COL in df.columns:
            lvl = pl.when(pl.col(UNPRICED_COL)).then(pl.lit(float(u))).otherwise(lvl)
        mu = mu * lvl
        r = float(conversion.get("dispersion", 0.0))
        if r > 0:
            q = (mu / r).clip(0.0, 1.0 - 1e-12)
            out = df.with_columns((1.0 - (1.0 - q) ** r).alias(out_col))
        else:
            out = df.with_columns((1.0 - (-mu).exp()).alias(out_col))
    else:
        out = df.with_columns((1.0 - (-mu).exp()).alias(out_col))

    if score_col is not None and "_is_defst" in out.columns:
        # Held out of the offensive share denominator, so its share is zero and
        # this formula would publish it at 0. A defense still scores about 10%
        # of the time; the calibrated classifier already says so, and that is
        # the number to keep — including its ordering, which is the half a flat
        # constant would throw away.
        #
        # AT ITS OWN LEVEL, though. The classifier is fitted over every
        # candidate, where defenses are under 2% of the rows, so nothing in
        # it is about defenses and nothing corrects it as the league moves —
        # and it has moved, from 14-16% a team-game in 2015-2019 to 9.4-11.0%
        # across 2023-2025. `fit_defst_level` fits the one multiplier.
        # Absent, the multiplier is 1.0 and this is what it always was.
        lvl_d = float((conversion or {}).get("defst_level") or 1.0)
        keep = (pl.col("_score_in") * lvl_d).clip(0.0, 1.0) if lvl_d != 1.0 \
            else pl.col("_score_in")
        out = out.with_columns(
            pl.when(pl.col("_is_defst")).then(keep)
            .otherwise(pl.col(out_col)).alias(out_col)
        ).drop("_is_defst")
    return out.drop("_score_in") if "_score_in" in out.columns else out


def mu_headroom(df: pl.DataFrame, mu_col: str,
                season_col: str = "season") -> tuple[float, float, float]:
    """The expected count a conversion has to stay above, and how that is got.

    Returns `(headroom, mu_max, growth)`. `headroom` is the largest expected
    count the fit data holds, raised by the largest season-over-season rise in
    that maximum the same data has shown. Where fewer than two seasons are
    available there is no growth to observe, `growth` is 0.0, and the headroom
    is the observed maximum alone.

    THIS IS NOT A TUNED NUMBER. It is read off the fit population the way
    `min_priced_share` is read off the weekly priced share — every input is
    the data's own, and the answer moves when the data does.
    """
    mu = df[mu_col].to_numpy()
    mu_max = float(np.max(mu)) if len(mu) else 0.0
    growth = 0.0
    if season_col in df.columns:
        per = (df.group_by(season_col).agg(pl.col(mu_col).max().alias("_m"))
                 .sort(season_col)["_m"].to_list())
        rises = [per[i + 1] / per[i] - 1.0
                 for i in range(len(per) - 1) if per[i] > 0]
        if rises:
            growth = max(0.0, max(rises))
    return mu_max * (1.0 + growth), mu_max, growth


def fit_conversion(df: pl.DataFrame, mu_col: str, target_col: str = "target",
                   unpriced: pl.DataFrame | None = None,
                   later_mu_max: float | None = None) -> dict:
    """Fit the level and dispersion that turn expected touchdowns into P(>=1).

    Two parameters, both with a physical reading, fitted by log loss on games
    the model did not train on. Needs no odds — only the model's own expected
    counts and what happened.

    `unpriced`, when given, fits a THIRD parameter: the same level again for
    the players no book quoted. It is a separate number because those players
    are a separate population, and the gap is not small. Measured over
    2023-2025, with the level fitted here on priced players only and served to
    everyone:

        priced players      14,067 rows   2288.4 predicted   2303 actual   -0.6%
        unpriced players     4,145 rows    197.2 predicted     24 actual   +722%

    Priced players are 16.1% to score and unpriced players are 0.41%, and a
    book declining to quote a man is most of what is known about him. Serving
    one level to both put ~0.35 phantom scorers a game on the board, which is
    the whole of its 7.6% aggregate over-prediction. Fitted separately the
    unpriced level comes out at 0.07 against 0.94 by log loss and 0.074 by
    calibration — two methods that do not have to agree, agreeing.

    **The caller must pass only seasons the odds archive covers.** Before 2023
    there are no archived prices at all, so every row reads as unpriced and the
    population means "no data existed" rather than "no book would quote him":
    fitted over 2015-2024 the unpriced group scores at 13.19% and the level
    comes back 0.83, which is the wrong answer to a different question.
    """
    mu = df[mu_col].to_numpy()
    y = df[target_col].to_numpy().astype(float)

    def nll(level: float, r: float) -> float:
        q = np.clip(level * mu / r, 0.0, 1.0 - 1e-12)
        p = np.clip(1.0 - (1.0 - q) ** r, 1e-7, 1 - 1e-7)
        return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))

    # A CONVERSION MAY NOT PUBLISH A CERTAINTY, WHATEVER ITS LOG LOSS.
    #
    # `apply_joint` clips `level * mu / r` at 1 - 1e-12, so any pair where
    # `r <= level * mu` publishes that clip: a probability of exactly 1,
    # asserting the player cannot fail to score. The model is never certain
    # and the number is not a probability, so the pair is inadmissible before
    # its log loss is read. This is a statement about what the output means,
    # not a threshold — nothing here is tuned.
    #
    # It mattered because log loss cannot see it. Fitted on 2023-24 the
    # optimum pinned at r = 1.0, the grid's own floor, where the form reduces
    # to p = level * mu exactly and saturates at mu >= 1/level. It beat
    # r = 1.15 by 0.0003 on the fit window, lost to it by 0.0003 on held-out
    # 2025 + 2026, and the difference is the near-zero bulk: 14,000 long shots
    # where every pair agrees, against the handful at the top where they
    # differ by five points. On 2026-10-14 it put Kyren Williams on the live
    # board at 99.8% against a book at 53.8%, the week's top pick, reading
    # "Strong call" at +45 per $100.
    #
    # The floor is the data's own: the largest expected count the fit holds,
    # raised by the largest season-over-season rise in that maximum the same
    # data has shown, so one season's growth cannot walk the served board
    # into the clip between refits. See `mu_headroom`.
    headroom, mu_max, growth = mu_headroom(df, mu_col)
    # AND THE BOARDS SERVED SINCE. The fit window's largest count is not the
    # largest the model has been asked about: after the 2026-10-19 retrain
    # the window allowed r = 1.0 again, saturating at an expected count of
    # 1.09, while week 5 of 2026 already put Kyren Williams at 1.04.
    # `later_mu_max` is read off pre-kickoff inputs for the seasons after the
    # window — no outcome enters — and raised by the same growth.
    if later_mu_max:
        headroom = max(headroom, float(later_mu_max) * (1.0 + growth))

    def search(constrained: bool):
        best = (1.0, 1e6, nll(1.0, 1e6))
        for level in np.arange(0.70, 1.31, 0.02):
            floor = float(level) * headroom
            for r in np.arange(1.0, 4.01, 0.05):
                if constrained and float(r) <= floor:
                    continue
                v = nll(float(level), float(r))
                if v < best[2]:
                    best = (round(float(level), 2), round(float(r), 2), v)
        return best

    best = search(True)
    free = search(False)
    level, r, ll = best
    out = {
        "kind": "td_conversion",
        "level": level,
        "dispersion": r,
        "log_loss": ll,
        # Provenance for the constraint: what it ruled out, and by how much.
        # A reader who wants the unconstrained answer can see it rather than
        # having to re-derive it, and a later season that moves the headroom
        # shows up here as a changed floor rather than as a silent reselection.
        "max_expected_count": mu_max,
        "headroom_growth": growth,
        "min_dispersion": level * headroom,
        "unconstrained_level": free[0],
        "unconstrained_dispersion": free[1],
        "unconstrained_log_loss": free[2],
        "log_loss_cost_of_the_constraint": ll - free[2],
        "poisson_log_loss": nll(1.0, 1e6),
        "n": int(len(y)),
        "fit_date": date.today().isoformat(),
    }

    # The same level again for the players no book quoted, at the dispersion
    # already fitted above — one free parameter, not three. Too few events to
    # re-fit a shape on: 13 scorers over 3,153 rows in 2023-2024.
    if unpriced is not None and unpriced.height:
        mu_u = unpriced[mu_col].to_numpy()
        y_u = unpriced[target_col].to_numpy().astype(float)

        def nll_u(level_u: float) -> float:
            q = np.clip(level_u * mu_u / r, 0.0, 1.0 - 1e-12)
            p = np.clip(1.0 - (1.0 - q) ** r, 1e-7, 1 - 1e-7)
            return float(-np.mean(y_u * np.log(p) + (1 - y_u) * np.log(1 - p)))

        grid = np.arange(0.01, 1.01, 0.01)
        best_u = min((nll_u(float(L)), float(L)) for L in grid)
        out.update({
            "unpriced_level": round(best_u[1], 3),
            "unpriced_log_loss": best_u[0],
            "unpriced_log_loss_at_priced_level": nll_u(level),
            "unpriced_n": int(len(y_u)),
            "unpriced_events": int(y_u.sum()),
            "unpriced_rate": float(y_u.mean()),
        })
    return out


def _game_lines(features: pl.DataFrame) -> pl.DataFrame:
    """One row per team-game carrying the betting lines the rate model reads."""
    games = features.group_by(["game_id", "team"]).agg([
        pl.col("implied_team_total").first(),
        pl.col("total_line").first(),
        pl.col("spread_line").first(),
    ])
    # A week with no posted lines yet (early preseason) still has to produce a
    # number, so fall back to the league mean rather than dropping the game.
    return games.with_columns([
        pl.col("implied_team_total").fill_null(games["implied_team_total"].mean()),
        pl.col("total_line").fill_null(games["total_line"].mean()),
        pl.col("spread_line").fill_null(0.0),
    ])


def apply_joint_first_td(df: pl.DataFrame, features: pl.DataFrame, model: dict,
                         score_col: str = "raw_prob",
                         out_col: str = "probability") -> pl.DataFrame:
    """First-TD probabilities from the same two pieces as anytime TD.

    The market's structure, rather than a second model of it: if each team's
    touchdowns arrive as competing Poisson processes then the chance team t
    scores the game's first is lambda_t / (lambda_home + lambda_away), and the
    scorer is drawn from that team's shares. Both pieces already exist — the
    fitted team rate and the model's own within-team shares — so this needs no
    extra parameter and nothing to fit.

    Production does not use it. `predict` normalizes raw first-TD scores within
    the game, which preserves whatever ordering the classifier produced and
    cannot express the fact that the *team* likely to score first is a separate
    question from which of its players would score. `first_td_probability` has
    been written and uncalled since the joint model landed; this is the entry
    point that lets it be measured.

    The competing-risks step assumes constant rates through the game, which is
    wrong in detail — trailing teams throw more, and the fourth quarter is not
    the first. Whether that is wrong enough to matter against a classifier
    trained directly on the label is exactly what the gate is for.
    """
    out = player_shares(df[score_col].to_numpy(), df)
    out = out.join(team_rate(model, _game_lines(features)),
                   on=["game_id", "team"], how="left")
    out = out.with_columns(pl.col("team_lambda").fill_null(model["mean_team_tds"]))
    return first_td_probability(out, out_col=out_col)


def apply_joint(df: pl.DataFrame, features: pl.DataFrame, model: dict,
                score_col: str = "raw_prob",
                out_col: str = "probability",
                conversion: dict | None = None) -> pl.DataFrame:
    """Turn per-player scores into probabilities through the joint structure.

    The single entry point for prediction, backtesting and the dashboard. Those
    three had drifted into three different answers for the same player: the
    backtest applied neither the calibrator nor the rank correction, and the
    app skipped the level anchoring entirely and published raw model output.
    One function, called from all three, is the only way that stays fixed.

    `score_col` need only be *proportional* within a team — the level comes
    from the team rate — so any ranker works as the share basis, including the
    existing calibrated ensemble.
    """
    out = player_shares(df[score_col].to_numpy(), df)
    out = out.join(team_rate(model, _game_lines(features)),
                   on=["game_id", "team"], how="left")
    out = out.with_columns(
        pl.col("team_lambda").fill_null(model["mean_team_tds"])
    )
    return combine(out, out_col=out_col, conversion=conversion,
                   score_col=score_col)


def first_td_probability(df: pl.DataFrame, share_col: str = "share",
                         lambda_col: str = "team_lambda",
                         out_col: str = "first_td_prob") -> pl.DataFrame:
    """P(this player scores the game's first touchdown).

    Falls out of the same two pieces rather than needing a separate model. If
    each team's touchdowns arrive as a Poisson process, the chance team t
    scores before the other is lambda_t / (lambda_t + lambda_opp), and given
    that it was team t, the scorer is drawn from that team's shares.

    The competing-risks step assumes constant rates through the game, which is
    wrong in detail — trailing teams throw more, and the fourth quarter is not
    the first. It is a far better starting point than treating the first
    touchdown as an unrelated classification problem.
    """
    # Sum lambda over the two *teams*, not over rows. `sum().over("game_id")`
    # counts a team's rate once per candidate, so a team with eleven listed
    # players contributes eleven times its rate and the probabilities come out
    # far below one.
    per_team = (
        df.group_by(["game_id", "team"])
        .agg(pl.col(lambda_col).first().alias("_lam"))
        .group_by("game_id")
        .agg(pl.col("_lam").sum().alias("_game_lambda"))
    )
    return (
        df.join(per_team, on="game_id", how="left")
        .with_columns(
            (pl.col(lambda_col) / pl.col("_game_lambda") * pl.col(share_col))
            .alias(out_col)
        )
        .drop("_game_lambda")
    )


def save_team_rate(model: dict, path) -> None:
    import json
    from pathlib import Path
    Path(path).write_text(json.dumps(model, indent=2))


def load_team_rate(path) -> dict | None:
    import json
    from pathlib import Path
    if not Path(path).exists():
        return None
    return json.loads(Path(path).read_text())


def fit_defst_level(df: pl.DataFrame, p_col: str,
                    target_col: str = "target") -> dict | None:
    """The level a defense's published probability needs, fitted on its own.

    **A DEFENSE IS A THIRD POPULATION AND IT HAD NO LEVEL.** `combine` holds
    DEF/ST out of the offensive share denominator — a defense is not a share
    of its own offense — and hands back the calibrated classifier's number
    instead. That number is fitted over every candidate in the training
    window, where defenses are 1.8% of the rows, so nothing in it is about
    defenses specifically and nothing corrects it when the league moves.

    The league has moved. Non-offensive touchdowns per team-game ran 14-16%
    from 2015 to 2019 and 9.4-11.0% across 2023-2025; through week 4 of 2026
    the board said 12.6% against 6.3% actual over 126 team-games. The small
    sample is 2026's, but the direction is a decade long and the classifier
    is anchored to the wrong end of it.

    One free parameter, multiplicative on the probability and fitted by log
    loss, which is the form `fit_conversion` already uses for the unpriced
    population and for the same reason: too few events to fit a shape on.
    Returns None when there is nothing to fit, so a caller cannot write a
    level derived from no rows.
    """
    if df is None or df.height == 0 or p_col not in df.columns:
        return None
    pr = np.clip(df[p_col].to_numpy().astype(float), 1e-7, 1 - 1e-7)
    y = df[target_col].to_numpy().astype(float)
    if len(y) == 0 or np.isnan(y).any():
        return None

    def nll(level: float) -> float:
        q = np.clip(level * pr, 1e-7, 1 - 1e-7)
        return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))

    grid = np.arange(0.20, 2.01, 0.01)
    best = min((nll(float(L)), float(L)) for L in grid)
    seasons = (sorted({int(s) for s in df["season"].to_list()})
               if "season" in df.columns else [])
    return {
        "defst_level": round(best[1], 3),
        "defst_log_loss": best[0],
        "defst_log_loss_at_one": nll(1.0),
        "defst_n": int(len(y)),
        "defst_events": int(y.sum()),
        "defst_rate": float(y.mean()),
        "defst_said": float(pr.mean()),
        "defst_seasons": seasons,
        "defst_fit_date": date.today().isoformat(),
    }


def save_conversion(conv: dict, path) -> None:
    import json
    from pathlib import Path
    Path(path).write_text(json.dumps(conv, indent=2))


def load_conversion(path) -> dict | None:
    import json
    from pathlib import Path
    if not Path(path).exists():
        return None
    return json.loads(Path(path).read_text())
