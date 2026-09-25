"""Empirical scoring-rate prior, fit from historical data.

The model outputs a probability per candidate, but nothing constrains how many
touchdowns it thinks a game will produce. When features degrade (a new season, a
player with no history) those probabilities drift upward together and the whole
slate inflates.

This module fits the constraint from data rather than asserting it: how many
distinct candidates actually score in a game, as a function of the game's betting
lines. It is refit on every training run, so it tracks league scoring environment
year to year with no hand-set numbers.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

# Design matrix columns, in order. Kept explicit so the saved coefficients stay
# interpretable and a stale artifact fails loudly instead of silently misaligning.
DESIGN_COLS = ["total_line", "abs_spread"]


def _design_matrix(df: pl.DataFrame) -> np.ndarray:
    """[1, total_line, |spread_line|] — game scoring environment."""
    total = df["total_line"].fill_null(strategy="mean").to_numpy()
    spread = df["spread_line"].fill_null(0.0).abs().to_numpy()
    return np.column_stack([np.ones(len(total)), total, spread])


def _fit_priced_share(features: pl.DataFrame, train_seasons: list[int]) -> float:
    """Share of a game's scorers who were priced by a sportsbook.

    Returns 1.0 when there is no odds archive to measure against, which makes
    the level calibration behave exactly as it did before — normalizing across
    every candidate. That is the honest default: without prices we have no
    evidence about which candidates a book would have quoted.
    """
    try:
        from src.ingest.odds_history import load_graded_history
        graded = load_graded_history("anytime_td")
    except Exception:
        return 1.0
    if graded is None or graded.height == 0:
        return 1.0

    priced = graded.select(["game_id", "player_id"]).unique().with_columns(
        pl.lit(True).alias("_priced")
    )
    d = features.filter(pl.col("target").is_not_null()).join(
        priced, on=["game_id", "player_id"], how="left"
    ).with_columns(pl.col("_priced").fill_null(False))
    # Only games the archive actually covers; elsewhere "unpriced" just means
    # "we never bought that week", which says nothing about the market.
    d = d.filter(pl.col("game_id").is_in(priced["game_id"].unique()))
    total = d["target"].sum()
    if total == 0:
        return 1.0
    on_priced = d.filter(pl.col("_priced"))["target"].sum()
    return float(min(max(on_priced / total, 0.5), 1.0))


def fit_scorer_rate_prior(features: pl.DataFrame, train_seasons: list[int]) -> dict:
    """Fit E[distinct scorers per game] ~ total_line + |spread|.

    Uses the labeled candidate pool so the count is on exactly the same scope
    the model predicts over — not a league-wide TD average that would include
    scorers who were never candidates.
    """
    df = features.filter(
        pl.col("season").is_in(train_seasons) & pl.col("target").is_not_null()
    )
    per_game = df.group_by("game_id").agg([
        pl.col("target").sum().alias("n_scorers"),
        pl.col("total_line").first(),
        pl.col("spread_line").first(),
        pl.col("season").first(),
    ]).drop_nulls("n_scorers")

    if per_game.height < 100:
        raise ValueError(
            f"Not enough labeled games to fit the scorer-rate prior "
            f"({per_game.height} found, need 100+)."
        )

    X = _design_matrix(per_game)
    y = per_game["n_scorers"].to_numpy().astype(float)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)

    fitted = X @ coef
    resid = y - fitted

    return {
        "kind": "scorer_rate_prior",
        "design_cols": DESIGN_COLS,
        "coef": coef.tolist(),           # [intercept, total_line, abs_spread]
        "seasons_used": sorted(train_seasons),
        "n_games": int(per_game.height),
        "mean_scorers_per_game": float(y.mean()),
        "rmse": float(np.sqrt((resid ** 2).mean())),
        # Guard rails for prediction time, derived from the fit — not chosen.
        "min_expected": float(np.percentile(y, 1)),
        "max_expected": float(np.percentile(y, 99)),
        # What fraction of a game's scorers are players a sportsbook priced.
        # The level calibration used to spread the full expected count across
        # every candidate, but roughly five candidates a game are never priced
        # and they account for well under 1% of scorers — so ~10% of the
        # model's probability mass was being parked on players who essentially
        # never score, leaving it short on the ones that matter. Measured, not
        # assumed, and refitted whenever the archive grows.
        "priced_share": _fit_priced_share(features, train_seasons),
        "fit_date": date.today().isoformat(),
        "source": "labels derived from nflverse play-by-play (see docs/DATA_SOURCES.md)",
    }


def expected_scorers(prior: dict, games: pl.DataFrame) -> pl.DataFrame:
    """Apply a fitted prior to games. Returns game_id + expected_scorers."""
    if prior.get("design_cols") != DESIGN_COLS:
        raise ValueError(
            f"Prior was fit with design {prior.get('design_cols')}, code expects "
            f"{DESIGN_COLS}. Refit with `make train`."
        )
    X = _design_matrix(games)
    pred = X @ np.array(prior["coef"])
    pred = np.clip(pred, prior["min_expected"], prior["max_expected"])
    return games.select("game_id").with_columns(
        pl.Series("expected_scorers", pred)
    )


def save_prior(prior: dict, path: Path) -> None:
    path.write_text(json.dumps(prior, indent=2))


def load_prior(path: Path) -> dict | None:
    if not Path(path).exists():
        return None
    return json.loads(Path(path).read_text())
