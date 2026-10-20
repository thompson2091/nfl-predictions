"""The vegas-blind game model, and the leak it nearly shipped as an edge."""
import polars as pl

from src.models import game_model as gm


def test_the_market_is_not_among_the_features():
    """The whole point of this model is that it cannot see the line."""
    d = gm.team_games()
    feats = set(gm.feature_columns(d))
    for c in gm.VEGAS_COLS:
        assert c not in feats, f"{c} is the market and must not be a feature"
    # And nothing that merely renames it, either.
    for c in feats:
        assert "spread" not in c and "moneyline" not in c, c
        assert not c.endswith("total_line"), c


def test_every_game_carries_both_teams():
    """A game with one side makes its "total" that side's score alone.

    The model would then appear to disagree with the posted total by thirty
    points and be right, every time, on exactly those rows.
    """
    d = gm.team_games()
    per = d.group_by("game_id").agg(pl.len().alias("n"))
    assert per.filter(pl.col("n") != 2).is_empty()


def test_columns_whose_absence_knows_the_score_are_dropped():
    """The screen must still catch the twenty that produced a fake edge.

    `team_rz_*` and `opp_tds_allowed_to_*` go null when the denominator they
    need is missing, and it is missing when nobody scored. A team whose
    `team_rz_td_pct_avg_5g` was null scored ~17 points below its own season
    average in that game, and the model read the absence as the result.
    """
    d = gm.team_games()
    leaks = set(gm.leaky_columns(d))
    # Both families are now densified at the source (every game a team
    # played has a row), so the screen has nothing left to catch in them.
    # It still has to fire on a column built the old way: see
    # `test_a_column_missing_at_random_is_not_called_a_leak` for the other
    # side, and the synthetic check below for this one.
    assert not {c for c in leaks if c.startswith(("team_rz_", "opp_tds_allowed"))}, (
        f"a densified family leaks again: {sorted(leaks)}")
    leaky = d.with_columns(pl.when(pl.col("points") < 10).then(None)
                           .otherwise(pl.lit(1.0)).alias("_built_from_scores"))
    assert "_built_from_scores" in set(gm.leaky_columns(
        leaky, gm.feature_columns(d) + ["_built_from_scores"])), "screen went quiet"


def test_a_column_missing_at_random_is_not_called_a_leak():
    """The screen must not fire on ordinary missingness.

    Otherwise it quietly eats real features every time a source has a gap.
    """
    d = gm.team_games().head(2000)
    import numpy as np

    rng = np.random.default_rng(0)
    mask = rng.random(d.height) < 0.2
    d = d.with_columns(
        pl.when(pl.Series(mask)).then(None)
          .otherwise(pl.col("team_points_scored_avg_5g"))
          .alias("_random_holes"))
    assert "_random_holes" not in gm.leaky_columns(d, ["_random_holes"])


def test_the_model_does_not_beat_the_market_on_average():
    """If it ever does, suspect the screen before celebrating.

    A model with no access to the line beating the closing line outright is
    the single most likely symptom of leakage in this file, and it is exactly
    what the first version appeared to do.
    """
    g = gm.walk_forward()
    mae = lambda a, b: float((g[a] - g[b]).abs().mean())   # noqa: E731
    assert mae("total_model", "total_actual") > mae("total_market", "total_actual")
    assert mae("margin_model", "margin_actual") > mae("margin_market", "margin_actual")
