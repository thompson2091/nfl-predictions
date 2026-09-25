"""Offence against defence: as-of, and honest about what is missing."""
import polars as pl
import pytest

from src.models import matchup_stats as ms


def test_every_rate_is_built_from_games_before_this_one():
    """Computed over the whole season, a page about an unplayed game reports
    its result. The filter is `week < week`, which is the same guarantee as a
    shift and easier to see."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "src/models/matchup_stats.py").read_text()
    body = src[src.index("def _totals_through"):src.index("def _rates")]
    assert 'pl.col("week") < week' in body


def test_totals_exclude_the_target_week():
    g = pl.DataFrame({"season": [2026] * 3, "week": [1, 2, 3],
                      "team": ["GB"] * 3, "plays": [10, 20, 40],
                      "early_n": [5, 5, 5], "early_k": [1, 2, 4]})
    t = ms._totals_through(g, 3)
    assert t["c_plays"][0] == 30, "week 3 must not be in its own figure"
    assert t["games"][0] == 2


def test_a_week_with_nothing_before_it_produces_nothing():
    """Week 1 has no prior games, and an invented 0% is worse than a blank."""
    g = pl.DataFrame({"season": [2026], "week": [1], "team": ["GB"],
                      "plays": [10], "early_n": [5], "early_k": [2]})
    assert ms._totals_through(g, 1).is_empty()


def test_rates_are_ratios_of_sums_not_means_of_ratios():
    """Averaging per-game rates weights a 40-play game like a 75-play one."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "src/models/matchup_stats.py").read_text()
    body = src[src.index("def _per_game"):src.index("def _totals_through")]
    assert ".sum()" in body and ".mean()" not in body, (
        "per-game aggregation must count, so the as-of figure can be a ratio "
        "of sums")


def test_the_edge_flips_sign_where_lower_is_better():
    """Sack rate is a rate you want LOW. An offence beating the defence's sack
    rate is being sacked more often than that defence usually manages, which is
    bad — and a single sign for every metric would paint it green."""
    stats = {"GB": {"games": 3, "off": {"sack_rate": 0.10,
                                        "early_down_success": 0.50},
                    "def": {"sack_rate": 0.05, "early_down_success": 0.40}},
             "ATL": {"games": 3, "off": {"sack_rate": 0.04,
                                         "early_down_success": 0.42},
                     "def": {"sack_rate": 0.06, "early_down_success": 0.45}}}
    rows = ms.matchup({"home": "GB", "away": "ATL"}, stats)
    sack = [r for r in rows if r["key"] == "sack_rate"][0]
    gb = [p for p in sack["sides"] if p["offense"] == "GB"][0]
    # GB's offence is sacked 10% against a defence that manages 6%: worse.
    assert gb["edge"] < 0
    early = [r for r in rows if r["key"] == "early_down_success"][0]
    gbe = [p for p in early["sides"] if p["offense"] == "GB"][0]
    assert gbe["edge"] > 0


def test_both_halves_of_the_matchup_are_returned():
    """A matchup has two, and showing one is showing half a game."""
    stats = {t: {"games": 3, "off": {"epa_play": 0.1},
                 "def": {"epa_play": 0.0}} for t in ("GB", "ATL")}
    rows = ms.matchup({"home": "GB", "away": "ATL"}, stats)
    assert len(rows[0]["sides"]) == 2
    assert {p["offense"] for p in rows[0]["sides"]} == {"GB", "ATL"}


def test_a_proxy_is_declared_a_proxy():
    """Sack rate is not pressure rate: it counts pressure that SUCCEEDED, and
    a line generating constant pressure against a quick release looks
    identical to one generating none."""
    by_key = {m[0]: m for m in ms.METRICS}
    assert "PROXY" in by_key["sack_rate"][3]
    stats = {t: {"games": 3, "off": {"sack_rate": 0.06},
                 "def": {"sack_rate": 0.05}} for t in ("GB", "ATL")}
    rows = ms.matchup({"home": "GB", "away": "ATL"}, stats)
    assert rows[0]["proxy"] is True


def test_what_could_not_be_built_is_named_with_its_reason():
    """A gap has to read as a gap rather than as an oversight — especially the
    blitz split, which was asked for and whose field is empty for 2026."""
    assert ms.MISSING
    blurb = " ".join(w + y for w, y in ms.MISSING)
    assert "number_of_pass_rushers" in blurb
    assert "2026" in blurb
    for what, why in ms.MISSING:
        assert what and why, "a named gap must say why"


def test_a_team_with_no_history_is_skipped_rather_than_half_rendered():
    assert ms.matchup({"home": "GB", "away": "ATL"}, {"GB": {"games": 1}}) is None
