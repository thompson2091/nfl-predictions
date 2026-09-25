"""Regression tests for the team-level view.

    pytest tests/test_team_outlook.py -v
"""
from __future__ import annotations

import polars as pl
import pytest

from src.presentation import team_outlook as T


def _preds(rows: list[tuple]) -> pl.DataFrame:
    return pl.DataFrame(
        [{"game_id": g, "team": t, "player_name": n, "probability": p}
         for g, t, n, p in rows])


def test_first_td_shares_sum_to_one_per_game():
    """Exactly one team scores first, so the two must add up.

    The per-player numbers are published against the whole candidate pool, so a
    thin pool would otherwise hand back two shares summing to something
    arbitrary — and a reader would have no way to see it.
    """
    preds = _preds([
        ("g1", "KC", "a", 0.10), ("g1", "KC", "b", 0.06),
        ("g1", "BUF", "c", 0.05), ("g1", "BUF", "d", 0.03),
    ])
    # min_candidates=1 isolates the normalization from the thin-roster guard,
    # which is tested separately below.
    out = T.first_td_share(preds, min_candidates=1)
    assert out["first_td_pct"].sum() == pytest.approx(1.0)
    kc = out.filter(pl.col("team") == "KC")["first_td_pct"][0]
    assert kc == pytest.approx(0.16 / 0.24)


def test_first_td_shares_are_per_game_not_global():
    preds = _preds([
        ("g1", "KC", "a", 0.20), ("g1", "BUF", "b", 0.05),
        ("g2", "SF", "c", 0.02), ("g2", "SEA", "d", 0.02),
    ])
    out = T.first_td_share(preds, min_candidates=1)
    for game in ("g1", "g2"):
        s = out.filter(pl.col("game_id") == game)["first_td_pct"].sum()
        assert s == pytest.approx(1.0), f"{game} shares sum to {s}"
    assert out.filter(pl.col("game_id") == "g2")["first_td_pct"].to_list() == \
        pytest.approx([0.5, 0.5])


def test_expected_scorers_counts_players_not_touchdowns():
    """The sum of P(scores at least one) is an expected count of scorers.

    A player who scores twice contributes one here and two to the scoreboard,
    which is why the measured figure runs ~2.1 against ~2.4 actual touchdowns
    per team-game. Labeling this "expected touchdowns" would be wrong by
    exactly that gap.
    """
    preds = _preds([("g", "KC", "a", 0.5), ("g", "KC", "b", 0.4),
                    ("g", "KC", "c", 0.3)])
    out = T.expected_scorers(preds)
    assert out["expected_scorers"][0] == pytest.approx(1.2)


def test_shutout_risk_is_poisson_zero():
    lam = pl.DataFrame({"game_id": ["g", "g"], "team": ["KC", "BUF"],
                        "team_lambda": [2.4, 1.5]})
    out = T.team_scoring_rate(lam)
    assert out.filter(pl.col("team") == "KC")["shutout_pct"][0] == \
        pytest.approx(0.0907, abs=1e-4)
    assert out.filter(pl.col("team") == "BUF")["shutout_pct"][0] > \
        out.filter(pl.col("team") == "KC")["shutout_pct"][0], \
        "the weaker offense must carry the higher shut-out risk"


def test_build_omits_what_it_cannot_compute():
    """A blank is honest; a zero is a claim.

    The app can be pointed at a week where one market has been scored and the
    other has not.
    """
    preds = _preds([("g", "KC", "a", 0.1), ("g", "BUF", "b", 0.1)])
    only_first = T.build(preds, None, None)
    assert "first_td_pct" in only_first.columns
    assert "expected_scorers" not in only_first.columns

    assert T.build(None, None, None).is_empty()


def test_build_joins_both_markets_on_the_team_game():
    # Both sides need at least MIN_CANDIDATES or the thin-roster guard fires.
    first = _preds([("g", "KC", f"a{i}", 0.02) for i in range(6)]      # 0.12
                   + [("g", "BUF", f"b{i}", 0.01) for i in range(8)])  # 0.08
    anytime = _preds([("g", "KC", "a", 0.55), ("g", "KC", "x", 0.40),
                      ("g", "BUF", "b", 0.45)])
    lam = pl.DataFrame({"game_id": ["g", "g"], "team": ["KC", "BUF"],
                        "team_lambda": [2.6, 2.0]})
    out = T.build(first, anytime, lam)
    assert out.height == 2
    kc = out.filter(pl.col("team") == "KC")
    assert kc["first_td_pct"][0] == pytest.approx(0.6)  # 0.12 of 0.20
    assert kc["expected_scorers"][0] == pytest.approx(0.95)
    assert kc["expected_tds"][0] == pytest.approx(2.6)


def test_top_scorer_names_the_number():
    preds = _preds([("g", "KC", "Kelce", 0.30), ("g", "KC", "Pacheco", 0.55),
                    ("g", "BUF", "Cook", 0.40)])
    out = T.top_scorer_per_team(preds)
    kc = out.filter(pl.col("team") == "KC")
    assert kc["top_player"][0] == "Pacheco"
    assert kc["top_player_pct"][0] == pytest.approx(0.55)


def test_a_thin_roster_does_not_publish_a_confident_split():
    """A team with no offensive candidates is a data outage, not a 99% read.

    Arizona in 2026 week 1 has exactly one candidate — the DEF/ST placeholder —
    which normalizes to its opponent scoring first 99.2% of the time. The
    opponent's number is exactly as corrupted, since one is one minus the other,
    so both are withheld rather than just the thin side's.

    2015 has 83 such team-weeks and the 2026 pre-season has 513, because next
    season's rosters are not published yet. The 2016-2025 evaluation range is
    clean, so this is a display guard rather than a modeling one.
    """
    rows = [("g", "ARI", "DEF/ST", 0.01)]
    rows += [("g", "LAC", f"p{i}", 0.10) for i in range(12)]
    out = T.first_td_share(_preds(rows))
    assert out["first_td_pct"].null_count() == 2, (
        "both sides of a thin game must be withheld, not just the thin one"
    )
    assert out.filter(pl.col("team") == "ARI")["candidates"][0] == 1

    healthy = [("h", "KC", f"a{i}", 0.10) for i in range(10)]
    healthy += [("h", "BUF", f"b{i}", 0.10) for i in range(10)]
    ok = T.first_td_share(_preds(healthy))
    assert ok["first_td_pct"].null_count() == 0
    assert ok["first_td_pct"].sum() == pytest.approx(1.0)


# ── The bookmaker's own split ──────────────────────────────────────────────


def _market(rows: list[tuple]) -> pl.DataFrame:
    return pl.DataFrame(
        [{"game_id": g, "team": t, "player_name": n, "market_prob": p}
         for g, t, n, p in rows])


def test_the_book_split_is_the_same_arithmetic_on_their_prices():
    """Both columns are shares of one game, so both add to one."""
    first = _preds([("g", "KC", f"a{i}", 0.03) for i in range(6)]      # 0.18
                   + [("g", "BUF", f"b{i}", 0.01) for i in range(6)])  # 0.06
    market = _market([("g", "KC", f"a{i}", 0.02) for i in range(6)]    # 0.12
                     + [("g", "BUF", f"b{i}", 0.02) for i in range(6)])
    out = T.build(first, None, None, market)
    assert out["first_td_pct"].to_list() == pytest.approx([0.25, 0.75])
    assert out["book_first_td_pct"].to_list() == pytest.approx([0.5, 0.5])


def test_the_book_split_needs_a_priced_game_and_says_nothing_otherwise():
    """A game the book has not priced gets a blank, not our number twice."""
    first = _preds([("g", "KC", f"a{i}", 0.03) for i in range(6)]
                   + [("g", "BUF", f"b{i}", 0.01) for i in range(6)])
    thin = _market([("g", "KC", "a0", 0.2), ("g", "BUF", "b0", 0.2)])
    out = T.build(first, None, None, thin)
    assert out["first_td_pct"].null_count() == 0
    assert out["book_first_td_pct"].null_count() == 2


def test_without_a_market_there_is_no_book_column_at_all():
    first = _preds([("g", "KC", f"a{i}", 0.03) for i in range(6)]
                   + [("g", "BUF", f"b{i}", 0.01) for i in range(6)])
    assert "book_first_td_pct" not in T.build(first, None, None).columns
