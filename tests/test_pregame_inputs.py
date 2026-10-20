"""Inputs that must be knowable before kickoff, in value AND in existence.

Three fixes from the 2026-10-19 re-audit, each a case where a row's presence
or placement said something about the game it labels:

  - opening-drive team rates existed only when the team received the kickoff;
  - snap share after a bye landed on the bye week, so the next game read null;
  - a backup who starts read `is_starter = 0` because the chart still listed
    the injured starter.
"""
from __future__ import annotations

import polars as pl

from src.features.assembler import _to_next_game
from src.features.injury_features import build_projected_starter_features
from src.features.opening_drive_features import build_opening_drive_features


def _drive1(game, week, posteam, defteam, td):
    return {"game_id": game, "season": 2025, "week": week, "posteam": posteam,
            "defteam": defteam, "fixed_drive": 1.0, "touchdown": float(td),
            "field_goal_attempt": 0.0, "rusher_player_id": None,
            "receiver_player_id": None}


def _od_frame():
    # A receives in weeks 1, 2, 4 and 5 and kicks off in week 3 (B receives).
    rows = [
        _drive1("g1", 1, "A", "X", 1),
        _drive1("g2", 2, "A", "Y", 0),
        _drive1("g3", 3, "B", "A", 1),
        _drive1("g4", 4, "A", "Z", 1),
        _drive1("g5", 5, "A", "W", 1),
    ]
    pbp = pl.DataFrame(rows, schema_overrides={"rusher_player_id": pl.Utf8,
                                               "receiver_player_id": pl.Utf8})
    sched = pl.DataFrame({
        "game_id": ["g1", "g2", "g3", "g4", "g5", "g6"],
        "season": [2025] * 6, "week": [1, 2, 3, 4, 5, 6],
        "home_team": ["A", "A", "B", "A", "A", "A"],
        "away_team": ["X", "Y", "A", "Z", "W", "V"],
    }).with_columns(pl.col("season").cast(pl.Int32), pl.col("week").cast(pl.Int32))
    pbp = pbp.with_columns(pl.col("season").cast(pl.Int32), pl.col("week").cast(pl.Int32))
    spine = pl.DataFrame(schema={"player_id": pl.Utf8, "season": pl.Int32,
                                 "week": pl.Int32})
    return pbp, sched, spine


def test_opening_drive_rate_exists_whether_or_not_the_team_received():
    pbp, sched, spine = _od_frame()
    team, _ = build_opening_drive_features(pbp, spine, sched)
    a = team.filter(pl.col("team") == "A").sort("week")
    # A row for every scheduled game, kicking (week 3) and unplayed (week 6)
    # included — existence no longer tells the model who got the ball.
    assert a["week"].to_list() == [1, 2, 3, 4, 5, 6]
    szn = dict(zip(a["week"], a["team_opening_drive_td_rate_szn_avg"]))
    assert szn[1] is None                 # nothing before the first game
    assert szn[2] == 1.0                  # g1 only
    assert szn[3] == 0.5                  # g1, g2: the kicking game sees them
    assert szn[4] == 0.5                  # g3 was B's drive, not A's
    assert abs(szn[6] - 0.75) < 1e-12     # g1, g2, g4, g5: the next game


def test_opening_drive_rate_never_reads_its_own_game():
    pbp, sched, spine = _od_frame()
    base, _ = build_opening_drive_features(pbp, spine, sched)
    # Flip the week-4 result: only rows AFTER week 4 may move.
    flipped = pbp.with_columns(
        pl.when(pl.col("game_id") == "g4").then(0.0)
        .otherwise(pl.col("touchdown")).alias("touchdown"))
    moved, _ = build_opening_drive_features(flipped, spine, sched)
    col = "team_opening_drive_td_rate_szn_avg"
    j = base.join(moved, on=["team", "season", "week"], suffix="_m").filter(
        pl.col("team") == "A")
    changed = j.filter(pl.col(col).fill_null(-1) != pl.col(f"{col}_m").fill_null(-1))
    assert changed["week"].min() == 5


def test_snap_share_after_a_bye_lands_on_the_next_game():
    sched = pl.DataFrame({
        "season": [2025] * 3, "week": [4, 6, 7],
        "home_team": ["A", "A", "A"], "away_team": ["X", "Y", "Z"],
    })
    snaps = pl.DataFrame({"player_id": ["p", "p", "p"], "season": [2025] * 3,
                          "week": [4, 6, 7], "team": ["A", "A", "A"],
                          "snap_pct": [0.9, 0.8, 0.7]})
    out = _to_next_game(snaps, sched).sort("week")
    # Week 5 is the bye: week 4's share belongs to week 6, not week 5.
    assert out["week"].to_list() == [6, 7]
    assert out["snap_pct"].to_list() == [0.9, 0.8]


def _chart(rows):
    return pl.DataFrame(rows, schema=["season", "week", "club_code", "gsis_id",
                                      "depth_team", "position"], orient="row")


def test_backup_is_projected_qb1_when_the_starter_is_out():
    chart = _chart([
        (2025, 6, "PHI", "starter", "1", "QB"),
        (2025, 6, "PHI", "backup", "2", "QB"),
        (2025, 7, "PHI", "starter", "1", "QB"),
        (2025, 7, "PHI", "backup", "2", "QB"),
    ])
    injuries = pl.DataFrame({"gsis_id": ["starter"], "season": [2025],
                             "week": [6.0], "report_status": ["Out"]})
    sched = pl.DataFrame(schema={"season": pl.Int64})
    got = build_projected_starter_features(chart, None, sched, injuries)
    q = {(r["player_id"], r["week"]): r["is_projected_qb1"]
         for r in got.iter_rows(named=True)}
    assert q[("starter", 6)] == 0 and q[("backup", 6)] == 1
    assert q[("starter", 7)] == 1 and q[("backup", 7)] == 0


def test_questionable_starter_stays_projected():
    chart = _chart([
        (2025, 6, "PHI", "starter", "1", "QB"),
        (2025, 6, "PHI", "backup", "2", "QB"),
    ])
    injuries = pl.DataFrame({"gsis_id": ["starter"], "season": [2025],
                             "week": [6.0], "report_status": ["Questionable"]})
    got = build_projected_starter_features(
        chart, None, pl.DataFrame(schema={"season": pl.Int64}), injuries)
    assert got.filter(pl.col("is_projected_qb1") == 1)["player_id"].to_list() == ["starter"]


def test_unplayed_games_have_no_target():
    from src.targets.candidates import null_unplayed

    cands = pl.DataFrame({"game_id": ["played", "scored_no_pbp", "future"],
                          "target": [0, 0, 0]}).with_columns(pl.col("target").cast(pl.Int8))
    sched = pl.DataFrame({"game_id": ["played", "scored_no_pbp", "future"],
                          "home_score": [24, 17, None]})
    out = null_unplayed(cands, sched, pl.Series(["played"]))
    assert out["target"].to_list() == [0, None, None]
