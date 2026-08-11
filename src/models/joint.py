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
        # defence, not to this team's touchdown production.
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
# 1. Team rate: how many touchdowns will this offence score
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


def player_shares(rates: np.ndarray, df: pl.DataFrame) -> pl.DataFrame:
    """Normalise per-player touchdown rates to shares within each team-game.

    The share model does not have to be calibrated in absolute terms — only
    correctly ordered and correctly proportioned within a team, because the
    level comes from the team rate. That is a strictly easier thing to learn
    than a calibrated probability, and it is the half of the problem a usage
    model is actually good at.
    """
    out = df.with_columns(pl.Series("_rate", np.maximum(rates, 1e-9)))
    return out.with_columns(
        (pl.col("_rate") / pl.col("_rate").sum().over(["game_id", "team"]))
        .alias("share")
    ).drop("_rate")


def combine(df: pl.DataFrame, share_col: str = "share",
            lambda_col: str = "team_lambda",
            out_col: str = "probability",
            conversion: dict | None = None) -> pl.DataFrame:
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
    least one is correspondingly higher. Modelling the count as
    Binomial(r, mu/r) spans the range — r = 1 is a single all-or-nothing shot,
    r -> infinity recovers Poisson — and `r` is fitted rather than assumed.

    `level` corrects the scoring environment drifting away from the seasons the
    team rate was fitted on; it multiplies mu before the conversion.

    With both fitted (level 0.90, dispersion 1.15) the favourites band went from
    6.7 points low to 1.0 high on held-out 2025, and the published probabilities
    summed to 4.04 per game against 4.04 actual.
    """
    mu = pl.col(lambda_col) * pl.col(share_col)
    if conversion:
        mu = mu * float(conversion.get("level", 1.0))
        r = float(conversion.get("dispersion", 0.0))
        if r > 0:
            q = (mu / r).clip(0.0, 1.0 - 1e-12)
            return df.with_columns((1.0 - (1.0 - q) ** r).alias(out_col))
    return df.with_columns((1.0 - (-mu).exp()).alias(out_col))


def fit_conversion(df: pl.DataFrame, mu_col: str, target_col: str = "target") -> dict:
    """Fit the level and dispersion that turn expected touchdowns into P(>=1).

    Two parameters, both with a physical reading, fitted by log loss on games
    the model did not train on. Needs no odds — only the model's own expected
    counts and what happened.
    """
    mu = df[mu_col].to_numpy()
    y = df[target_col].to_numpy().astype(float)

    def nll(level: float, r: float) -> float:
        q = np.clip(level * mu / r, 0.0, 1.0 - 1e-12)
        p = np.clip(1.0 - (1.0 - q) ** r, 1e-7, 1 - 1e-7)
        return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))

    best = (1.0, 1e6, nll(1.0, 1e6))
    for level in np.arange(0.70, 1.31, 0.02):
        for r in np.arange(1.0, 4.01, 0.05):
            v = nll(float(level), float(r))
            if v < best[2]:
                best = (round(float(level), 2), round(float(r), 2), v)
    level, r, ll = best
    return {
        "kind": "td_conversion",
        "level": level,
        "dispersion": r,
        "log_loss": ll,
        "poisson_log_loss": nll(1.0, 1e6),
        "n": int(len(y)),
        "fit_date": date.today().isoformat(),
    }


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
    games = features.group_by(["game_id", "team"]).agg([
        pl.col("implied_team_total").first(),
        pl.col("total_line").first(),
        pl.col("spread_line").first(),
    ])
    # A week with no posted lines yet (early preseason) still has to produce a
    # number, so fall back to the league mean rather than dropping the game.
    games = games.with_columns([
        pl.col("implied_team_total").fill_null(
            games["implied_team_total"].mean()),
        pl.col("total_line").fill_null(games["total_line"].mean()),
        pl.col("spread_line").fill_null(0.0),
    ])

    out = player_shares(df[score_col].to_numpy(), df)
    out = out.join(team_rate(model, games), on=["game_id", "team"], how="left")
    out = out.with_columns(
        pl.col("team_lambda").fill_null(model["mean_team_tds"])
    )
    return combine(out, out_col=out_col, conversion=conversion)


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
