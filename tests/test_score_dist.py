"""The final-score distribution: empirical, and honest about what it cannot say."""
import polars as pl
import pytest

from src.models import score_dist as sd


def _hist():
    """A tiny archive with a known answer, so the arithmetic is checkable."""
    return pl.DataFrame({
        "season": [2024] * 6, "week": list(range(1, 7)),
        "home_team": ["GB"] * 6, "away_team": ["ATL"] * 6,
        "home_score": [27, 24, 20, 31, 17, 27],
        "away_score": [24, 20, 23, 21, 24, 24],
        "spread_line": [6.5, 6.0, 7.0, 6.5, 6.5, 6.5],
        "total_line": [44.5, 45.0, 44.0, 44.5, 44.5, 44.5],
    }).with_columns([
        (pl.col("home_score") - pl.col("away_score")).alias("margin"),
        (pl.col("home_score") + pl.col("away_score")).alias("total")])


def test_the_site_spread_is_flipped_exactly_once():
    """The card signs the spread NEGATIVE when home is favoured; the schedule
    signs it positive. Getting it backwards mirrors the whole distribution and
    produces a confident, exactly wrong answer.
    """
    h = _hist()
    card = {"home": "GB", "away": "ATL", "spread": -6.5, "total": 44.5}
    got = sd.for_card(card, h)
    assert got["n"] == 6, "the flip failed and nothing matched"
    # GB won four of the six in the fixture.
    assert got["home_win"]["n"] == 4


def test_exact_scores_are_counted_not_rated():
    """A scoreline seen four times in three hundred is not a probability.

    They carry their counts so a reader can see the sample; the margin bands
    pool dozens of games each and are the numbers that carry weight.
    """
    got = sd.for_card({"home": "GB", "away": "ATL", "spread": -6.5,
                       "total": 44.5}, _hist())
    top = got["scores"][0]
    assert top["n"] == 2 and top["home"] == 27 and top["away"] == 24
    assert "n" in top, "an exact scoreline without its count invites pricing"
    # And the bands carry intervals, which the scorelines deliberately do not.
    assert all("lo" in m and "hi" in m for m in got["margins"])
    assert all("lo" not in s for s in got["scores"])


def test_a_thin_window_says_so_rather_than_drawing_a_chart():
    """A distribution over 40 games is anecdotes with percentages on them."""
    got = sd.for_card({"home": "GB", "away": "ATL", "spread": -6.5,
                       "total": 44.5}, _hist())
    assert got["thin"] is True and got["n"] < sd.MIN_COMPARABLES


def test_the_ladder_is_monotone_because_it_is_a_survival_curve():
    """More points cleared can never be MORE likely than fewer.

    A sorting or sign error shows up here and nowhere else: the percentages
    would still look plausible one row at a time.
    """
    lad = sd.ladders_for_card({"home": "GB", "away": "ATL", "spread": -6.5,
                               "total": 44.5}, _hist())
    for t in lad["teams"]:
        pcts = [r["pct"] for r in t["rows"]]
        assert pcts == sorted(pcts, reverse=True), (
            f"{t['team']} ladder is not monotone: {pcts}")
    for key in ("total", "spread"):
        pcts = [r["pct"] for r in lad[key]["rows"]]
        assert pcts == sorted(pcts, reverse=True), f"{key}: {pcts}"


def test_every_ladder_row_carries_its_own_count():
    """So a threshold out in the tail is visibly thin rather than quietly wrong."""
    lad = sd.ladders_for_card({"home": "GB", "away": "ATL", "spread": -6.5,
                               "total": 44.5}, _hist())
    rows = [r for t in lad["teams"] for r in t["rows"]] + lad["total"]["rows"]
    assert rows and all("n" in r for r in rows)


@pytest.mark.skipif(not sd.history().height, reason="no schedule archive")
def test_it_finds_a_real_sample_on_a_real_line():
    """The tolerances are round numbers, not fitted ones — but they have to
    actually reach a usable sample on an ordinary game."""
    got = sd.for_card({"home": "GB", "away": "ATL", "spread": -6.5,
                       "total": 44.5})
    assert got["n"] >= sd.MIN_COMPARABLES, (
        f"only {got['n']} comparable games at a bog-standard line")


def test_the_scenarios_partition_rather_than_overlap():
    """A list of overlapping scenarios reads as a ranking and cannot be one.

    "One-score 50%, shootout 31%, upset 28%" adds to more than everything that
    can happen, and nothing on screen says which of them overlap. The cells
    are margin band crossed with over/under, so they are exclusive and
    exhaustive and the column can be read straight down.
    """
    sc = sd.scenarios_for_card({"home": "GB", "away": "ATL", "spread": -6.5,
                                "total": 44.5}, _hist())
    total = sum(c["n"] for c in sc["cells"])
    assert total == sc["n"], (
        f"cells cover {total} of {sc['n']} games; the partition leaks")
    assert abs(sum(c["pct"] for c in sc["cells"]) - 100) < 0.5


def test_the_favourite_is_named_rather_than_called_home():
    """"Home by 8-14" is a sentence a reader has to translate."""
    sc = sd.scenarios_for_card({"home": "GB", "away": "ATL", "spread": -6.5,
                                "total": 44.5}, _hist())
    assert sc["fav"] == "GB" and sc["dog"] == "ATL"
    assert any("GB" in c["label"] for c in sc["cells"])
    assert not any("Home" in c["label"] for c in sc["cells"])
    # And it follows the spread rather than the venue.
    away_fav = sd.scenarios_for_card({"home": "GB", "away": "ATL",
                                      "spread": 6.5, "total": 44.5}, _hist())
    assert away_fav["fav"] == "ATL"


def test_the_headline_numbers_are_labelled_as_overlapping():
    """They do overlap, which is why they are separate from the partition."""
    sc = sd.scenarios_for_card({"home": "GB", "away": "ATL", "spread": -6.5,
                                "total": 44.5}, _hist())
    assert set(sc["headline"]) == {"one_score", "blowout", "upset",
                                   "shootout", "grind"}
    assert all("lo" in v and "hi" in v for v in sc["headline"].values())
