"""The opening line and the move, from the feed's own price history."""
import polars as pl

from src.ingest import public_money as pm


def _views(entries):
    return [{"gameView": {"homeTeam": {"shortName": "DET"},
                          "awayTeam": {"shortName": "NYJ"},
                          "startDate": "2026-09-27T17:00:00+00:00"},
             "oddsViews": [{"sportsbook": b, "spreadHistory": rows}
                           for b, rows in entries],
             "openingLineViews": []}]


def test_a_moneyline_in_the_spread_history_is_rejected():
    """`bet_rivers_co` posted `homeSpread: 0` at -334 on NYJ at DET.

    A spread is quoted near even money on both sides; -334 is a moneyline in
    the wrong column. Taken as the current line it turned Detroit -6.5 into a
    pick'em and reported a 7.5-point move that never happened.
    """
    rows = pm.parse_lines(_views([
        ("dk", [{"oddsDate": "2026-09-22T12:00:00+00:00", "homeSpread": -7.5,
                 "homeOdds": -110, "awayOdds": -110},
                {"oddsDate": "2026-09-24T18:00:00+00:00", "homeSpread": -6.5,
                 "homeOdds": -110, "awayOdds": -110}]),
        ("rivers", [{"oddsDate": "2026-09-25T02:00:00+00:00", "homeSpread": 0,
                     "homeOdds": -334, "awayOdds": 250}]),
    ]), "now")
    sp = rows.filter(pl.col("market") == "spreads").row(0, named=True)
    assert sp["now_point"] == -6.5, "the -334 row must not set the line"
    assert sp["open_point"] == -7.5


def test_the_current_line_is_the_median_of_each_book_not_the_last_row():
    """One book's late posting should not move the reported line by itself."""
    rows = pm.parse_lines(_views([
        ("a", [{"oddsDate": "2026-09-24T10:00:00+00:00", "homeSpread": -6.5,
                "homeOdds": -110, "awayOdds": -110}]),
        ("b", [{"oddsDate": "2026-09-24T11:00:00+00:00", "homeSpread": -6.5,
                "homeOdds": -110, "awayOdds": -110}]),
        ("c", [{"oddsDate": "2026-09-24T23:00:00+00:00", "homeSpread": -3.5,
                "homeOdds": -110, "awayOdds": -110}]),
    ]), "now")
    sp = rows.filter(pl.col("market") == "spreads").row(0, named=True)
    assert sp["now_point"] == -6.5, "the outlier must not carry the median"


def test_the_game_week_open_is_separate_from_the_lookahead_line():
    """The feed holds lines posted in MAY. A three-point move since then is a
    season of news and says nothing about what money did this week, which is
    the only thing reverse line movement is about."""
    rows = pm.parse_lines(_views([
        ("dk", [{"oddsDate": "2026-05-15T15:00:00+00:00", "homeSpread": -9.5,
                 "homeOdds": -110, "awayOdds": -110},
                {"oddsDate": "2026-09-22T12:00:00+00:00", "homeSpread": -7.5,
                 "homeOdds": -110, "awayOdds": -110},
                {"oddsDate": "2026-09-24T18:00:00+00:00", "homeSpread": -6.5,
                 "homeOdds": -110, "awayOdds": -110}]),
    ]), "now")
    sp = rows.filter(pl.col("market") == "spreads").row(0, named=True)
    assert sp["open_point"] == -9.5 and sp["open_at"].startswith("2026-05")
    assert sp["wk_point"] == -7.5, "the week's open, not May's"
    assert sp["wk_at"].startswith("2026-09-22")


def test_the_week_open_falls_back_visibly():
    """When the feed holds nothing inside the week, `wk_at` equals `open_at`
    rather than the number silently becoming the lookahead line."""
    rows = pm.parse_lines(_views([
        ("dk", [{"oddsDate": "2026-05-15T15:00:00+00:00", "homeSpread": -9.5,
                 "homeOdds": -110, "awayOdds": -110}]),
    ]), "now")
    sp = rows.filter(pl.col("market") == "spreads").row(0, named=True)
    assert sp["wk_at"] == sp["open_at"]


def test_the_archive_can_widen_without_losing_history():
    """This schema has grown once already. An archive that refuses to widen
    forces a choice between losing history and losing the new column."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "src/ingest/public_money.py").read_text()
    assert 'how="diagonal_relaxed"' in src


def test_stamping_the_week_keeps_the_callers_columns():
    """It selected the TICKET schema by name, so stamping the line-history
    frame would have dropped every column the line history adds."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "src/ingest/public_money.py").read_text()
    i = src.index("def _stamp_week(")
    body = src[i:i + src[i:].index("\ndef ")]
    # The CALL, not the word. An earlier version matched "list(SCHEMA)" and
    # failed on the comment explaining why it is no longer used — a test that
    # forbids describing the property it enforces.
    assert ".select(list(SCHEMA))" not in body
    assert "cols = df.columns" in body and ".select(cols)" in body
