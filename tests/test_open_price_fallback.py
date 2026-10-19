"""The site may price an over/under board off the open; the record may not.

Every over/under board read the close and nothing else, so from Tuesday until
thirty minutes before Thursday's kickoff the site showed no over/under prices
at all, with the opens sitting in the archive. `allow_open` lets the site show
them. The record is graded at the close, so the paths that freeze boards and
record picks must never see an opening price — that half is what these guard.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _week_with_only_opens(tmp_path, monkeypatch, market):
    """The newest archived week for `market`, with its closes taken out."""
    from src.ingest import odds_history

    if not Path(odds_history.HISTORY_PATH).exists():
        pytest.skip("no odds archive on disk")
    h = pl.read_parquet(odds_history.HISTORY_PATH)
    opens = h.filter((pl.col("market") == market) & (pl.col("snapshot") == "open"))
    if opens.is_empty():
        pytest.skip(f"no {market} opens archived")
    season, week = (opens.select(["season", "week"]).unique()
                    .sort(["season", "week"]).row(-1))
    trimmed = h.filter(~((pl.col("season") == season) & (pl.col("week") == week)
                         & (pl.col("snapshot") == "close")))
    path = tmp_path / "odds_history.parquet"
    trimmed.write_parquet(path)
    monkeypatch.setattr(odds_history, "HISTORY_PATH", path)
    return int(season), int(week)


@pytest.mark.parametrize("market", ["receiving_yards", "receptions"])
def test_site_board_falls_back_to_the_open_and_says_so(tmp_path, monkeypatch, market):
    season, week = _week_with_only_opens(tmp_path, monkeypatch, market)
    if market == "receptions":
        from src.prediction.receptions import board_for_week

        def build(**kw):
            return board_for_week(season, week, **kw)
    else:
        from src.prediction.yards import board_for_week

        def build(**kw):
            return board_for_week(market, season, week, **kw)

    closed, why = build()
    assert closed.is_empty() and "(close)" in why, (
        "with no close on disk the default board must stay empty")

    board, _ = build(allow_open=True)
    if board.is_empty():
        pytest.skip(f"{season} week {week} has no candidates to price")
    assert set(board["price_snapshot"].unique().to_list()) == {"open"}, (
        "a board priced off the open must say so on every row")


def test_the_record_never_asks_for_the_open():
    """`ou_board` feeds the freeze, the prop picks and the regrade.

    Read from source rather than run, because running it needs a whole
    feature matrix. The default is False as well; this pins the call sites so
    a changed default still cannot reach the record.
    """
    from src.evaluation import week_history

    src = inspect.getsource(week_history.ou_board)
    assert "dash.receptions(season, week, allow_open=False)" in src
    assert "mod.yards(market, season, week, allow_open=False)" in src


def test_only_the_site_build_opts_in():
    root = Path(__file__).resolve().parents[1]
    site = (root / "scripts/47_export_site.py").read_text()
    dash = (root / "scripts/34_export_dashboard.py").read_text()
    assert "yards(mk, s, w, allow_open=True)" in site
    assert "receptions(season, week, allow_open=True)" in dash
    for text in (site, dash):
        assert text.count("allow_open=True") == 1, (
            "a second opt-in to the open; check it is not on a record path")
