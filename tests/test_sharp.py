"""Separating money from tickets, and what the measurement refuses to say.

The archive it reads began on 2026-09-25 and holds one capture, so every
number this module can produce today is withheld. These drive the machinery on
made-up rows instead, because the alternative is that the first real week is
also the first time the code has ever run to a number.
"""
from __future__ import annotations

import polars as pl
import pytest

from src.evaluation import sharp


def _split(game, market, side, tix, money, cap="2026-09-22T12:00:00Z",
           season=2026, week=4):
    return {"captured_at": cap, "season": season, "week": week,
            "game_id": game, "kickoff": "", "market": market, "side": side,
            "odds": -110, "tickets_pct": float(tix), "money_pct": float(money),
            "source": "test"}


def _line(game, market, outcome, prob, snapshot, at, season=2026, week=4):
    return {"captured_at": at, "book_last_update": None, "commence_time": None,
            "game_id": game, "home_team": None, "away_team": None,
            "bookmaker": "bk", "market": market, "outcome": outcome,
            "outcome_raw": outcome, "point": None, "odds": -110,
            "implied_prob": float(prob), "season": season, "week": week,
            "snapshot": snapshot}


@pytest.fixture
def wire(tmp_path, monkeypatch):
    """Point both archives at rows a test writes."""
    def go(splits, lines):
        p = tmp_path / "game_lines.parquet"
        pl.DataFrame(lines).write_parquet(p)
        monkeypatch.setattr("src.ingest.game_lines.LINES_PATH", p)
        monkeypatch.setattr("src.ingest.action_public.load",
                            lambda: pl.DataFrame(splits))
    return go


def test_the_ratio_is_dollars_per_ticket_not_the_raw_gap(wire):
    """THE STATISTIC THIS MODULE EXISTS FOR.

    Money share minus ticket share is capped by the ticket share: a side on
    89% of tickets can gain at most 11 points however large its bets are, so
    ranking by the gap ranks by unpopularity. Dollars per ticket is symmetric
    and says what it means — the average bet on this side against the average
    bet on the other.
    """
    wire([_split("A_B", "moneyline", "A", 11, 46),
          _split("A_B", "moneyline", "B", 89, 54)], [_line("A_B", "h2h", "A",
                                                          0.3, "open", "x")])
    out = sharp.splits().sort("side")
    got = dict(zip(out["side"].to_list(), out["ratio"].to_list()))
    # 46/11 against 54/89.
    assert got["A"] == pytest.approx(6.89, abs=0.01)
    # And it is reciprocal, which the gap is not: the gap is +35 and -35.
    assert got["A"] * got["B"] == pytest.approx(1.0, abs=1e-9)


def test_a_heavily_backed_side_can_still_be_the_sharp_one(wire):
    """A gap ranking would bury this. 89% of tickets AND 96% of the money is
    a bigger average bet than the other side, and the ratio says so."""
    wire([_split("A_B", "moneyline", "A", 89, 96),
          _split("A_B", "moneyline", "B", 11, 4)],
         [_line("A_B", "h2h", "A", 0.3, "open", "x")])
    out = sharp.splits()
    got = dict(zip(out["side"].to_list(), out["ratio"].to_list()))
    assert got["A"] > 2.0, "a popular side with the money behind it"


def test_a_market_with_one_side_is_dropped_not_compared_to_nothing(wire):
    """The ratio needs the other side. A market the feed published half of
    would otherwise divide by a partial denominator and report a number."""
    wire([_split("A_B", "moneyline", "A", 11, 46)],
         [_line("A_B", "h2h", "A", 0.3, "open", "x")])
    assert sharp.splits().is_empty()


def test_a_split_read_after_the_close_cannot_have_predicted_it(wire):
    """THE TIMING TRAP. Keeping a capture taken after the line closed would
    score the archive's own lateness as foresight — which is exactly the
    situation the live archive is in today."""
    lines = [_line("A_B", "h2h", "A", 0.30, "open", "2026-09-22T10:00:00Z"),
             _line("A_B", "h2h", "A", 0.40, "close", "2026-09-24T10:00:00Z"),
             _line("A_B", "h2h", "B", 0.70, "open", "2026-09-22T10:00:00Z"),
             _line("A_B", "h2h", "B", 0.60, "close", "2026-09-24T10:00:00Z")]
    late = [_split("A_B", "moneyline", "A", 11, 46, cap="2026-09-25T10:00:00Z"),
            _split("A_B", "moneyline", "B", 89, 54, cap="2026-09-25T10:00:00Z")]
    wire(late, lines)
    assert sharp.paired().is_empty(), "a late capture must not be scored"

    early = [_split("A_B", "moneyline", "A", 11, 46, cap="2026-09-23T10:00:00Z"),
             _split("A_B", "moneyline", "B", 89, 54, cap="2026-09-23T10:00:00Z")]
    wire(early, lines)
    p = sharp.paired()
    assert p.height == 2
    a = p.filter(pl.col("side") == "A")
    # The market went from 30% to 40% on A, which is +10pp in A's favor.
    assert a["move_pp"][0] == pytest.approx(10.0, abs=1e-6)


def test_the_move_is_signed_in_each_side_s_own_favor(wire):
    """A single number cannot mean "toward the favorite" and "toward this
    side" at once. B's line went the other way and must read negative."""
    lines = [_line("A_B", "h2h", "A", 0.30, "open", "2026-09-22T10:00:00Z"),
             _line("A_B", "h2h", "A", 0.40, "close", "2026-09-24T10:00:00Z"),
             _line("A_B", "h2h", "B", 0.70, "open", "2026-09-22T10:00:00Z"),
             _line("A_B", "h2h", "B", 0.60, "close", "2026-09-24T10:00:00Z")]
    wire([_split("A_B", "moneyline", "A", 11, 46, cap="2026-09-23T10:00:00Z"),
          _split("A_B", "moneyline", "B", 89, 54, cap="2026-09-23T10:00:00Z")],
         lines)
    p = sharp.paired()
    got = dict(zip(p["side"].to_list(), p["move_pp"].to_list()))
    assert got["A"] == pytest.approx(10.0, abs=1e-6)
    assert got["B"] == pytest.approx(-10.0, abs=1e-6)


def test_the_market_names_are_translated_between_the_two_archives(wire):
    """The scrapers were written apart and neither name is wrong. A mismatch
    joins nothing, which reads on the page as a quiet week rather than a bug,
    so it is asserted here."""
    assert sharp.MARKET_MAP == {"moneyline": "h2h", "spread": "spreads",
                                "total": "totals"}
    lines = [_line("A_B", "totals", "Over", 0.48, "open", "2026-09-22T10:00:00Z"),
             _line("A_B", "totals", "Over", 0.52, "close", "2026-09-24T10:00:00Z"),
             _line("A_B", "totals", "Under", 0.52, "open", "2026-09-22T10:00:00Z"),
             _line("A_B", "totals", "Under", 0.48, "close", "2026-09-24T10:00:00Z")]
    wire([_split("A_B", "total", "Over", 21, 39, cap="2026-09-23T10:00:00Z"),
          _split("A_B", "total", "Under", 79, 61, cap="2026-09-23T10:00:00Z")],
         lines)
    assert sharp.paired().height == 2, "totals did not join"


def test_a_thin_band_reports_its_count_and_withholds_the_rest(wire):
    """A pattern measured on six sides looks like a system and is a coin
    flip. The count is printed because it is the reason nothing else is."""
    splits, lines = [], []
    for i in range(6):
        g = f"G{i}_H"
        splits += [_split(g, "moneyline", "A", 11, 46, cap="2026-09-23T10:00:00Z"),
                   _split(g, "moneyline", "B", 89, 54, cap="2026-09-23T10:00:00Z")]
        lines += [_line(g, "h2h", "A", 0.30, "open", "2026-09-22T10:00:00Z"),
                  _line(g, "h2h", "A", 0.40, "close", "2026-09-24T10:00:00Z"),
                  _line(g, "h2h", "B", 0.70, "open", "2026-09-22T10:00:00Z"),
                  _line(g, "h2h", "B", 0.60, "close", "2026-09-24T10:00:00Z")]
    wire(splits, lines)
    rows = sharp.evaluate()
    assert rows, "nothing evaluated at all"
    assert all("move_pp" not in r for r in rows), "reported on twelve sides"
    text = sharp.format_report(rows)
    assert "too few sides" in text


def test_the_whole_path_produces_a_table_once_there_is_enough(wire):
    """THE POINT OF THIS FILE. The live archive cannot reach a number yet, so
    without this the first real week would be the first run to completion.

    Built so the money is right: the side carrying the larger average bet is
    the side the market moves toward.
    """
    splits, lines = [], []
    for i in range(60):
        g = f"G{i}_H"
        sharp_side_wins = i % 2 == 0
        close_a = 0.40 if sharp_side_wins else 0.20
        splits += [_split(g, "moneyline", "A", 11, 46, cap="2026-09-23T10:00:00Z"),
                   _split(g, "moneyline", "B", 89, 54, cap="2026-09-23T10:00:00Z")]
        lines += [_line(g, "h2h", "A", 0.30, "open", "2026-09-22T10:00:00Z"),
                  _line(g, "h2h", "A", close_a, "close", "2026-09-24T10:00:00Z"),
                  _line(g, "h2h", "B", 0.70, "open", "2026-09-22T10:00:00Z"),
                  _line(g, "h2h", "B", 1 - close_a, "close", "2026-09-24T10:00:00Z")]
    wire(splits, lines)
    rows = sharp.evaluate()
    reported = [r for r in rows if "move_pp" in r]
    assert reported, f"every band withheld: {rows}"
    for r in reported:
        assert 0.0 <= r["toward"] <= 1.0
        assert r["lo"] <= r["toward"] <= r["hi"]
    text = sharp.format_report(rows)
    assert "too few sides" not in text or len(reported) < len(rows)
    assert "%" in text


def test_the_bands_are_cut_from_the_data_not_declared_in_the_file():
    """No threshold decides what counts as sharp — that is the question. The
    cuts are quantiles, so they move with the season rather than with this
    file."""
    r = pl.Series("ratio", [1.0, 1.5, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0])
    cuts = sharp.bands(r, n=4)
    assert cuts == sorted(cuts) and len(cuts) == 3
    assert min(cuts) >= 1.0 and max(cuts) <= 64.0
    # A constant column has no quantile worth cutting on and must not produce
    # duplicate edges, which would make an empty band.
    assert sharp.bands(pl.Series("ratio", [2.0] * 10), n=4) in ([], [2.0])


def test_the_live_archive_refuses_rather_than_printing_noise():
    """One capture, taken after the week-3 close. It must say so."""
    text = sharp.report()
    if sharp.paired().is_empty():
        assert "before a close" in text
