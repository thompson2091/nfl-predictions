"""What a settled touchdown row says the player actually had.

The board graded to a tick and a cross and never said whether the tick was
one score or three. These guard the number that fills that in, and every one
of them is a mistake this code actually made.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import polars as pl
import pytest

from src.evaluation import week_history as wh

REPO = Path(__file__).resolve().parents[1]


def _write(tmp_path, tds_rows, cand_rows, pbp_rows, target="anytime_td"):
    """A minimal season on disk, in the three files the helper reads."""
    proc = tmp_path / "processed" / target
    raw = tmp_path / "raw"
    proc.mkdir(parents=True)
    raw.mkdir(parents=True)
    pl.DataFrame(tds_rows).write_parquet(proc / f"tds_{target}.parquet")
    pl.DataFrame(cand_rows).write_parquet(proc / "candidates.parquet")
    pl.DataFrame(pbp_rows).write_parquet(raw / "pbp.parquet")

    def fake(kind, t=None):
        return (tmp_path / "processed" / t) if t else (tmp_path / kind)

    return fake


def _pbp(game_id, play_id, pid, team, season=2026, week=1):
    return {"season": season, "week": week, "game_id": game_id,
            "play_id": float(play_id), "touchdown": 1.0,
            "td_player_id": pid, "td_team": team}


def _td(game_id, pid, team, off=True, season=2026, week=1):
    return {"season": season, "week": week, "game_id": game_id,
            "td_player_id": pid, "is_offensive_td": off}


def _cand(game_id, pid, name, team, pos="RB", season=2026, week=1):
    return {"season": season, "week": week, "game_id": game_id,
            "player_id": pid, "player_name": name, "team": team,
            "position": pos}


def test_a_hat_trick_is_counted_three_times_not_once(tmp_path, monkeypatch):
    """THE BUG THIS WAS WRITTEN FOR.

    `tds_anytime_td.parquet` is deduplicated to one row per player per game,
    because the anytime target only asks whether someone scored. Counting off
    it capped every multi-touchdown game at 1, so Saquon Barkley's three
    against Philadelphia rendered as "1 TD" — a number that is wrong, looks
    right, and settles nothing.
    """
    g = "2026_01_GB_PHI"
    fake = _write(
        tmp_path,
        # The deduplicated table: ONE row, however many he scored.
        [_td(g, "00-0034844", "PHI")],
        [_cand(g, "00-0034844", "Saquon Barkley", "PHI")],
        [_pbp(g, 100, "00-0034844", "PHI"),
         _pbp(g, 200, "00-0034844", "PHI"),
         _pbp(g, 300, "00-0034844", "PHI")],
    )
    monkeypatch.setattr("src.utils.paths.get_path", fake)
    out = wh._td_actuals(2026, 1, "anytime_td")
    assert out["td_count"].to_list() == [3]


def test_order_ranks_every_touchdown_in_the_game_not_every_scorer(
        tmp_path, monkeypatch):
    """A player's second score must not renumber anybody.

    Ranking scorers rather than plays would call the third touchdown of the
    game "the second", which is exactly the number a first-TD row is read
    for.
    """
    g = "2026_01_NO_BAL"
    fake = _write(
        tmp_path,
        [_td(g, "A", "BAL"), _td(g, "B", "BAL")],
        [_cand(g, "A", "First Man", "BAL"), _cand(g, "B", "Second Man", "BAL")],
        [_pbp(g, 10, "A", "BAL"),    # 1st of the game
         _pbp(g, 20, "A", "BAL"),    # 2nd of the game, same man
         _pbp(g, 30, "B", "BAL")],   # 3rd of the game
    )
    monkeypatch.setattr("src.utils.paths.get_path", fake)
    out = wh._td_actuals(2026, 1, "anytime_td").sort("player_name")
    got = dict(zip(out["player_name"].to_list(), out["td_order"].to_list()))
    assert got["First Man"] == 1
    assert got["Second Man"] == 3, "ranked scorers instead of plays"


def test_a_candidate_who_did_not_score_is_zero_not_missing(
        tmp_path, monkeypatch):
    """The week was played and every touchdown in it is in the table, so an
    absent candidate is a real zero. `None` would render as no result at all
    and make a settled loss look ungraded."""
    g = "2026_01_NO_BAL"
    fake = _write(
        tmp_path, [_td(g, "A", "BAL")],
        [_cand(g, "A", "Scorer", "BAL"), _cand(g, "B", "Blanked", "BAL")],
        [_pbp(g, 10, "A", "BAL")],
    )
    monkeypatch.setattr("src.utils.paths.get_path", fake)
    out = wh._td_actuals(2026, 1, "anytime_td").sort("player_name")
    got = dict(zip(out["player_name"].to_list(), out["td_count"].to_list()))
    assert got["Blanked"] == 0
    assert got["Scorer"] == 1


def test_a_shared_name_inside_one_team_is_dropped_rather_than_guessed(
        tmp_path, monkeypatch):
    """`week_board` joins on name and team, so two men with one display name
    would grade each other's touchdowns. A missing number is visible; a wrong
    one is not."""
    g = "2026_01_NO_BAL"
    fake = _write(
        tmp_path, [_td(g, "A", "BAL")],
        [_cand(g, "A", "Byron Young", "BAL"),
         _cand(g, "B", "Byron Young", "BAL"),
         _cand(g, "C", "Someone Else", "BAL")],
        [_pbp(g, 10, "A", "BAL")],
    )
    monkeypatch.setattr("src.utils.paths.get_path", fake)
    out = wh._td_actuals(2026, 1, "anytime_td")
    assert "Byron Young" not in out["player_name"].to_list()
    assert "Someone Else" in out["player_name"].to_list()


def test_a_defensive_unit_counts_its_own_scores_and_not_the_offence_s(
        tmp_path, monkeypatch):
    """A DEF/ST candidate is one row for a whole unit, so its touchdowns are
    the team's non-offensive ones — the rule `build_candidates` uses."""
    g = "2026_01_NO_BAL"
    fake = _write(
        tmp_path,
        [_td(g, "A", "BAL", off=True), _td(g, "D1", "BAL", off=False),
         _td(g, "D2", "BAL", off=False)],
        [_cand(g, "A", "A Runner", "BAL"),
         _cand(g, "BAL_DEFST", "DEF/ST", "BAL", pos="DEFST")],
        [_pbp(g, 10, "A", "BAL"), _pbp(g, 20, "D1", "BAL"),
         _pbp(g, 30, "D2", "BAL")],
    )
    monkeypatch.setattr("src.utils.paths.get_path", fake)
    out = wh._td_actuals(2026, 1, "anytime_td")
    got = dict(zip(out["player_name"].to_list(), out["td_count"].to_list()))
    assert got["DEF/ST"] == 2, "a unit's two scores must both count"
    assert got["A Runner"] == 1


@pytest.mark.skipif(not (REPO / "data" / "raw" / "pbp.parquet").exists(),
                    reason="no play-by-play on disk")
def test_the_count_and_the_grade_never_contradict_each_other_on_real_data():
    """TWO SOURCES FOR ONE FACT. `scored` comes from the feature matrix and
    the count from the play-by-play. They are built from the same plays, so
    every row must agree; a row saying "2 TDs" beside a cross is a visible
    lie."""
    board = wh.week_board(2026, 2, "anytime_td")
    if board.is_empty() or "td_count" not in board.columns:
        pytest.skip("week 2 board unavailable")
    graded = board.filter(pl.col("scored").is_not_null()
                          & pl.col("td_count").is_not_null())
    assert graded.height > 0, "nothing graded to check"
    bad = graded.filter((pl.col("td_count") > 0) != (pl.col("scored") == 1))
    assert bad.is_empty(), f"count contradicts the grade:\n{bad}"


@pytest.mark.skipif(not (REPO / "data" / "raw" / "pbp.parquet").exists(),
                    reason="no play-by-play on disk")
def test_a_real_week_carries_a_multiple_touchdown_game():
    """A guard against the cap coming back. If every count in a full week is
    0 or 1, the deduplicated table is being read again."""
    out = wh._td_actuals(2024, 1, "anytime_td")
    if out.is_empty():
        pytest.skip("2024 week 1 not built")
    assert out["td_count"].max() > 1, "every count capped at one"


def test_a_monday_night_player_is_not_graded_on_sunday_night():
    """A WEEK IS NOT A GAME, and this is the difference.

    `week_board` gated grading on whether the WEEK had play-by-play, which on
    a Monday is true the moment Sunday ends. Every Monday-night player then
    joined a feature matrix built from plays that had not happened, his label
    came back 0, and the board showed him as having failed to score in a game
    kicking off that evening. On 2026-10-05 that was all 34 ATL and NO
    players — Bijan Robinson at 57.2% among them — live on the site.
    """
    import polars as pl

    from src.evaluation.week_history import _unplayed_games, week_board

    unplayed = _unplayed_games(2026, 4)
    if not unplayed:
        pytest.skip("week 4 is complete; nothing left to be early about")
    b = week_board(2026, 4)
    if b.is_empty():
        pytest.skip("no week-4 board on disk")
    late = b.filter(pl.col("game_id").is_in(list(unplayed)))
    assert late.height, "the fixture under test is not on the board"
    assert late["scored"].is_null().all(), (
        f"{late['scored'].is_not_null().sum()} players in an unplayed game "
        f"carry a result")
    # And the rest of the week is still graded: a guard that nulls everything
    # is not a fix, it is the board going blank.
    done = b.filter(~pl.col("game_id").is_in(list(unplayed)))
    assert done.height and done["scored"].is_not_null().all()


def test_a_tracked_pick_is_not_settled_before_its_game_kicks_off():
    """The same mistake as `week_board`'s, in the other grading path.

    `_played_weeks` is week granularity, so from the moment Sunday ends every
    Monday-night pick graded against a target of 0: backs as losses, fades as
    wins. Both rules' headline records moved in their own favor — the fade
    read 95.16% where it had earned 95.08%, and the mid-price rule −8.47%
    where it had earned −7.39%.
    """
    import polars as pl

    from src.evaluation import tracked_rules as TR

    ids, labels = TR.unfinished(2026, 4)
    if not labels:
        pytest.skip("week 4 is complete; nothing left to be early about")
    # Both keys name the same games, which is the point of returning both.
    assert len(ids) == len(labels)

    all_picks = TR.load().filter(pl.col("market") == "anytime_td")
    pending = all_picks.filter((pl.col("season") == "2026")
                               & (pl.col("week") == "4")
                               & pl.col("game").is_in(list(labels)))
    if pending.is_empty():
        pytest.skip("no tracked pick on an unfinished week-4 game")

    s = TR.score("anytime_td") or {}
    checked = 0
    for rule, v in s["rules"].items():
        n_pending = pending.filter(pl.col("rule") == rule).height
        if not n_pending:
            continue
        # Every pick this rule has ever made, LESS the ones whose game has
        # not finished, is the ceiling on what can have been graded. The
        # real count sits right on it, so an off-by-one would show.
        total = all_picks.filter(pl.col("rule") == rule).height
        got = (v.get("graded") or {}).get("picks", 0)
        assert got <= total - n_pending, (
            f"{rule} graded {got} of {total} picks with {n_pending} on a "
            f"game still to kick off")
        checked += 1
    assert checked, "no rule had a pick on the unfinished game"


def test_the_two_grading_paths_cannot_disagree_about_what_has_finished():
    """One definition, because two readings of the schedule is how the same
    week came to be graded two different ways."""
    import inspect

    from src.evaluation import week_history as WH

    src = inspect.getsource(WH._unplayed_games)
    assert "unfinished" in src and "read_parquet" not in src, (
        "week_history reads the schedule itself again instead of delegating "
        "to tracked_rules.unfinished")


def test_a_board_frozen_without_ids_still_voids_players_who_did_not_play():
    """Weeks 1-6 were frozen without player_id, and the void silently skipped:
    207 players with no snap graded as misses."""
    import polars as pl
    from src.evaluation.week_history import week_board

    b = week_board(2026, 5, "anytime_td")
    if b.is_empty() or "scored" not in b.columns:
        import pytest
        pytest.skip("no 2026 week 5 board on disk")
    assert b["scored"].null_count() > 0, "nobody voided: the void did not run"
    d = b.filter(pl.col("player_name") == "DEF/ST")
    assert d["scored"].null_count() == 0, "a defense always plays"
