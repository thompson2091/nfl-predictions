"""Coach form and slot features: as-of, and populated when they are needed.

These shipped untested. Both bugs below were found the first time a page
asked to PRINT one of them rather than feed it to a model, which is the
general lesson: a feature that is quietly null is invisible to the thing
consuming it and obvious to a reader.
"""
import polars as pl

from src.features.situational_features import (build_situational_features,
                                               coach_form, team_game_form)


def _schedule():
    """Two coaches over four games, the last of which has not been played.

    The unplayed game is the whole point. It is the shape of every current
    season: results exist up to this week and stop, and a feature computed
    with a cumulative sum over that column has to survive the discontinuity.
    """
    return pl.DataFrame({
        "game_id": ["g1", "g2", "g3", "g4"],
        "season": [2024, 2024, 2024, 2024],
        "week": [1, 2, 3, 4],
        "game_type": ["REG"] * 4,
        "gameday": ["2024-09-08", "2024-09-15", "2024-09-22", "2024-09-29"],
        "gametime": ["13:00", "20:20", "13:00", "13:00"],
        "home_team": ["GB", "GB", "GB", "GB"],
        "away_team": ["CHI", "CHI", "CHI", "CHI"],
        "home_coach": ["A Coach"] * 4,
        "away_coach": ["B Coach"] * 4,
        "home_rest": [7, 7, 4, 7],
        "away_rest": [7, 13, 7, 7],
        "stadium": ["Lambeau Field"] * 4,
        # g1 won and covered, g2 a push, g3 lost, g4 not played.
        "result": [10.0, 3.0, -7.0, None],
        "spread_line": [3.0, 3.0, 3.0, None],
    })


def test_the_win_rate_survives_an_unplayed_game():
    """`cum_sum` PROPAGATES nulls, and `won` was summed unguarded.

    One unplayed game and every later row for that coach came back null. In
    2026 that was 452 of 544 rows against 4 for the cover rate, which was
    guarded — so the feature was fully populated through training and empty
    at serve time. That is worse than not having it: the model ranked it 22
    of 174 on the data where it existed and got nothing where it was used.
    """
    tg = team_game_form(_schedule())
    last = tg.filter(pl.col("game_id") == "g4")
    assert last.height == 2
    for r in last.iter_rows(named=True):
        assert r["coach_win_rate_prior"] is not None, (
            f"{r['coach']} has no win rate on the game being predicted")


def test_winning_and_covering_count_different_games():
    """A push is a real game that was won or lost; it is not a cover.

    Dividing wins by the graded count excluded every push from the
    denominator and inflated the rate — the same mismatch that put 2,236 bad
    rows through `coordinator_features`.
    """
    tg = team_game_form(_schedule()).filter(pl.col("game_id") == "g4")
    r = tg.filter(pl.col("coach") == "A Coach").row(0, named=True)
    # Three prior games, one of them a push against the spread.
    assert r["coach_played_prior"] == 3
    assert r["coach_games_prior"] == 2, "the push is not a graded cover"
    # Two wins of three played, not two of two.
    assert abs(r["coach_win_rate_prior"] - 2 / 3) < 1e-9


def test_every_record_excludes_the_game_it_is_attached_to():
    """Without the shift, a coach covers 100% of the game being predicted."""
    tg = team_game_form(_schedule()).sort("week")
    first = tg.filter((pl.col("game_id") == "g1")
                      & (pl.col("coach") == "A Coach")).row(0, named=True)
    assert first["coach_games_prior"] == 0
    assert first["coach_ats_rate_prior"] is None, (
        "a coach with no prior games has no rate; inventing one hands the "
        "model an absence dressed as a fact")


def test_prime_time_is_the_slot_and_not_the_day():
    """A Sunday 20:20 kickoff is prime time; a Sunday 13:00 is not."""
    tg = team_game_form(_schedule())
    slots = dict(tg.filter(pl.col("team") == "GB")
                 .select(["week", "is_prime_slot"]).iter_rows())
    assert slots[2] == 1, "Sunday night is prime time"
    assert slots[1] == 0 and slots[3] == 0


def test_rest_flags_read_the_right_side():
    tg = team_game_form(_schedule())
    g3 = tg.filter((pl.col("game_id") == "g3")
                   & (pl.col("team") == "GB")).row(0, named=True)
    assert g3["is_short_week"] == 1, "four days is a short week"
    g2 = tg.filter((pl.col("game_id") == "g2")
                   & (pl.col("team") == "CHI")).row(0, named=True)
    assert g2["is_off_bye"] == 1, "thirteen days is off a bye"


def test_the_model_never_sees_the_coach_name():
    """An identity is not a measurement.

    `coach` is kept for the page and dropped for the model. Handing a model a
    name lets it memorise the person rather than learn from the record.
    """
    cols = build_situational_features(_schedule()).columns
    assert "coach" not in cols
    for gone in ("_date", "_push", "covered", "won", "rest", "opp_rest"):
        assert gone not in cols
    # And the thing the page needs IS there, from the same computation.
    assert "coach" in coach_form(_schedule(), 2024, 4).columns


def test_the_page_and_the_model_share_one_as_of_computation():
    """A second implementation for the page is a second chance to forget the shift.

    Falsified by `coach_form` recomputing anything: both must come out of
    `team_game_form`, so a fix to the as-of logic reaches the page too.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "src/features/situational_features.py").read_text()
    body = src[src.index("def coach_form"):]
    body = body[:body.index("\n\n\n")] if "\n\n\n" in body else body
    assert "team_game_form(" in body
    assert "cum_sum" not in body, "the page must not recompute the history"
