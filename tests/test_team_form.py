"""Recent form: the scores, and what was expected of them."""

import polars as pl

from src.evaluation import team_form as TF


def _sched() -> pl.DataFrame:
    """Two teams, four played weeks, one unplayed, one still to come."""
    rows = []
    for wk, (hs, as_) in enumerate([(30, 27), (3, 20), (20, 13), (24, 24)], 1):
        rows.append({"season": 2026, "week": wk, "home_team": "PIT",
                     "away_team": "CLE", "home_score": hs, "away_score": as_,
                     # PIT favored by 3 at home: positive is the home side.
                     "spread_line": 3.0, "total_line": 45.0})
    rows.append({"season": 2026, "week": 5, "home_team": "PIT",
                 "away_team": "CLE", "home_score": None, "away_score": None,
                 "spread_line": 2.0, "total_line": 40.0})
    return pl.DataFrame(rows)


def test_a_week_is_read_against_the_total_the_market_posted_for_it():
    """The two sides' implied totals are the posted total, split by the spread.

    They must sum back to it: any other pair is a formula that drifted, and
    both halves of a wrong one still look like points.
    """
    got = TF.rows_for(2026, 5, schedule=_sched())
    for team in ("PIT", "CLE"):
        for r in got[team]:
            assert round(r[6] + r[7], 1) == 45.0, (team, r)

    # Favored at home by 3 on a 45 total: 24 for the home side, 21 for the
    # road one. Backwards here is the bug `vegas_features` documents, where
    # teams flagged as favorites won 34.9% of their games.
    assert got["PIT"][0][6] == 24.0
    assert got["CLE"][0][6] == 21.0


def test_the_week_being_previewed_is_not_part_of_its_own_form():
    """Strictly before, so a preview never reports the game it previews."""
    got = TF.rows_for(2026, 3, schedule=_sched())
    weeks = [r[1] for r in got["PIT"]]
    assert weeks == [2, 1], weeks


def test_an_unplayed_game_is_not_a_game():
    got = TF.rows_for(2026, 9, schedule=_sched())
    assert [r[1] for r in got["PIT"]] == [4, 3, 2, 1]


def test_points_allowed_is_the_other_sides_points():
    got = TF.rows_for(2026, 5, schedule=_sched())
    # Week 4 was 24-24, week 2 was 3-20 with PIT at home.
    pit = {r[1]: (r[4], r[5]) for r in got["PIT"]}
    cle = {r[1]: (r[4], r[5]) for r in got["CLE"]}
    assert pit[2] == (3, 20) and cle[2] == (20, 3)


def test_the_window_is_games_not_weeks():
    """Ten of them, however many seasons that reaches back through.

    A season is three games in week 4, and it is three games every September.
    """
    assert TF.LAST == 10
    big = pl.concat([_sched().with_columns(pl.lit(s).alias("season"))
                     for s in (2024, 2025, 2026)])
    got = TF.rows_for(2026, 5, schedule=big)
    assert len(got["PIT"]) == 10
    # Four played weeks a season, so ten games reaches through three of them.
    assert {r[0] for r in got["PIT"]} == {2026, 2025, 2024}, \
        "it stopped at a season boundary instead of counting games"
    assert got["PIT"][0][:2] == [2026, 4], "newest first"


def test_the_form_block_rides_in_the_page_rather_than_being_fetched():
    """32 teams x 10 games is small; the player record at 1.6 MB was not."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "se", Path(__file__).resolve().parents[1] / "scripts/47_export_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    payload: dict = {}
    mod._team_form_block(payload, 2026, 4)
    assert "teamform" in payload, "the page is handed no form to draw"
    tf = payload["teamform"]
    assert tf["last"] == TF.LAST
    assert len(tf["teams"]) == 32, len(tf["teams"])

    import json
    kb = len(json.dumps(tf)) / 1024
    assert kb < 120, f"{kb:.0f} KB inlined — this wants to be a fetched file"


def test_a_week_with_no_posted_line_keeps_its_score():
    """A bar with no tick, rather than a row dropped for want of a line."""
    s = _sched().with_columns(
        pl.when(pl.col("week") == 2).then(None)
          .otherwise(pl.col("total_line")).alias("total_line"))
    got = TF.rows_for(2026, 5, schedule=s)
    wk2 = [r for r in got["PIT"] if r[1] == 2]
    assert wk2, "the week was dropped"
    assert wk2[0][4] == 3 and wk2[0][6] is None
