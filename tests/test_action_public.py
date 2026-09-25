"""Ticket AND money splits, and the moneyline the other feed does not have."""
from __future__ import annotations

import importlib

import polars as pl
import pytest

AP = importlib.import_module("src.ingest.action_public")


def _state(tickets=11, money=46, odds=205):
    """One game, shaped as the page's `__NEXT_DATA__` shapes it."""
    return {"props": {"pageProps": {"scoreboardResponse": {"games": [{
        "home_team_id": 147, "away_team_id": 151,
        "start_time": "2026-09-25T20:15:00Z",
        "teams": [{"id": 147, "abbr": "GB"}, {"id": 151, "abbr": "ATL"}],
        "markets": {AP.PERCENT_BOOK: {"event": {
            "moneyline": [
                {"side": "away", "team_id": 151, "odds": odds,
                 "bet_info": {"tickets": {"percent": tickets},
                              "money": {"percent": money}}},
                {"side": "home", "team_id": 147, "odds": -250,
                 "bet_info": {"tickets": {"percent": 100 - tickets},
                              "money": {"percent": 100 - money}}},
            ],
            # Published as zero on both sides: the feed declining, not a
            # market nobody bet.
            "total": [
                {"side": "over", "odds": -110,
                 "bet_info": {"tickets": {"percent": 0},
                              "money": {"percent": 0}}},
                {"side": "under", "odds": -110,
                 "bet_info": {"tickets": {"percent": 0},
                              "money": {"percent": 0}}},
            ],
        }}},
    }]}}}}


def test_the_moneyline_split_is_captured():
    """The market Sportsbook Review publishes nothing on, on any game."""
    df = AP.parse(_state(), "2026-09-25T12:00:00Z")
    ml = df.filter(pl.col("market") == "moneyline")
    assert ml.height == 2, df
    atl = ml.filter(pl.col("side") == "ATL").to_dicts()[0]
    assert atl["tickets_pct"] == 11.0 and atl["money_pct"] == 46.0
    assert atl["odds"] == 205
    assert atl["game_id"] == "ATL_GB", "away_home, as the boards key games"


def test_money_and_tickets_are_both_kept():
    """TICKETS COUNT BETS; MONEY COUNTS DOLLARS.

    A side with 11% of the tickets and 46% of the money is a few large bets,
    which is a different fact from a crowd. Keeping only one of the two
    throws away the only public-betting signal with a story behind it.
    """
    df = AP.parse(_state(), "2026-09-25T12:00:00Z")
    assert {"tickets_pct", "money_pct"} <= set(df.columns)
    assert df["money_pct"].null_count() == 0


def test_a_zero_on_both_sides_is_absent_not_zero():
    """A 0% share is a claim, and it would be false.

    Sportsbook Review's moneyline is 0 on every game because the feed
    declines to publish it. The same shape appears here on individual
    outcomes and is dropped for the same reason.
    """
    df = AP.parse(_state(), "2026-09-25T12:00:00Z")
    assert df.filter(pl.col("market") == "total").is_empty(), (
        "an outcome published as 0/0 must not be archived as a real 0%")


def test_jacksonville_is_spelled_the_way_the_schedule_spells_it():
    st = _state()
    g = st["props"]["pageProps"]["scoreboardResponse"]["games"][0]
    g["teams"] = [{"id": 147, "abbr": "JAC"}, {"id": 151, "abbr": "ATL"}]
    df = AP.parse(st, "2026-09-25T12:00:00Z")
    assert df["game_id"][0] == "ATL_JAX", df["game_id"][0]


def test_one_book_only():
    """Percentages differ by book because the customers differ.

    Mixing them makes the archive's week-over-week drift meaningless — a
    change would be the page listing a different book first, not the money
    moving.
    """
    st = _state()
    g = st["props"]["pageProps"]["scoreboardResponse"]["games"][0]
    g["markets"]["999"] = {"event": {"moneyline": [
        {"side": "away", "team_id": 151, "odds": 300,
         "bet_info": {"tickets": {"percent": 80}, "money": {"percent": 80}}}]}}
    df = AP.parse(st, "2026-09-25T12:00:00Z")
    assert df.filter(pl.col("odds") == 300).is_empty(), "a second book leaked in"


def test_the_page_is_read_not_the_undocumented_api():
    """robots.txt permits `/nfl/public-betting`; the API's stance is unknown.

    `api.actionnetwork.com/robots.txt` answers 403 through their CDN, so
    there is nothing to read consent from. The page carries the identical
    payload in `__NEXT_DATA__` for the same single request.
    """
    import inspect

    src = inspect.getsource(AP)
    assert "www.actionnetwork.com/nfl/public-betting" in src
    assert "api.actionnetwork.com" not in AP.URL
    assert "__NEXT_DATA__" in src, (
        "parse the server-rendered state, not HTML: a missing key raises "
        "where a stale selector returns nothing and looks like a quiet week")


def test_a_changed_page_raises_rather_than_returning_nothing():
    """The failure this project keeps having is silence, not a crash."""
    import inspect

    src = inspect.getsource(AP._fetch)
    assert "raise RuntimeError" in src and "has changed" in src


def test_the_view_reports_the_gap_between_money_and_tickets():
    """The gap is the number the page shows; it must not be recomputed there."""
    import inspect

    assert '"gap"' in inspect.getsource(AP.week_view)
