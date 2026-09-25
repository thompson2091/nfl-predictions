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
    """The card signs the spread NEGATIVE when home is favored; the schedule
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


def test_calibration_leaves_the_game_out_of_its_own_prediction():
    """Otherwise the prediction contains its answer and the curve is perfect.

    Falsified by dropping the `j == i` skip: every game would be scored
    against a comparable set that includes it, and a model cannot be wrong
    about a game it has already seen the result of.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "src/models/score_dist.py").read_text()
    body = src[src.index("def calibration"):]
    assert "if j == i:" in body and "continue" in body


@pytest.mark.skipif(sd.history().height < 500, reason="needs the real archive")
def test_the_distribution_is_calibrated_within_a_couple_of_points():
    """A 70% that loses is a 70% behaving correctly, three times in ten.

    This is the check that decides whether a bad result was a bad model. On
    2026-09-25 Atlanta won at Green Bay by 21 as a road dog and every headline
    number looked wrong — while the same page had the outright Atlanta win at
    28.5%.
    """
    c = sd.calibration()
    assert c["n"] > 1000, f"only {c['n']} games had a usable comparable set"
    assert c["mean_gap_pp"] < 4.0, (
        f"predicted and observed differ by {c['mean_gap_pp']}pp on average; "
        f"this model is not calibrated and its probabilities cannot be read "
        f"as probabilities")
    # And no single well-populated bin is wildly off.
    for b in c["bins"]:
        if b["n"] < 50:
            continue
        assert abs(b["happened"] - b["said"]) < 10.0, (
            f"the {b['said']}% bin came in at {b['happened']}% on {b['n']} games")


@pytest.mark.skipif(sd.history().height < 500, reason="needs the real archive")
def test_the_win_curve_is_monotone_in_the_spread():
    """A probability that is not monotone contradicts the score beside it.

    The comparable window is two points wide and its crossover is noisy: at a
    model spread of -0.7 (home favored) it returned 48.5% for the home side,
    and the page printed "our model: PIT by 0.7" next to "CIN 51.5%" — two
    statements from the same model pointing opposite ways on one card.
    """
    c = sd.win_curve()
    assert c and c["b"] > 0, "a bigger home spread must mean a likelier home win"
    last = -1.0
    for sp in range(-14, 15):
        p = sd.win_prob(sp, c)
        assert p > last, f"not monotone at {sp}"
        last = p


@pytest.mark.skipif(sd.history().height < 500, reason="needs the real archive")
def test_the_curve_crosses_even_money_near_a_pick_em():
    """Not exactly at zero — the fit says +0.39, which is a real, small
    property of the archive rather than something to round away — but a
    crossover far from zero would mean the sign convention is inverted."""
    c = sd.win_curve()
    cross = -c["a"] / c["b"]
    assert abs(cross) < 1.5, f"crosses 50% at a spread of {cross:.2f}"
    assert sd.win_prob(-7, c) < 0.35 and sd.win_prob(7, c) > 0.65


@pytest.mark.skipif(sd.history().height < 500, reason="needs the real archive")
def test_the_curve_is_calibrated_too():
    """Smooth and monotone is not the same as right."""
    import polars as pl

    h = sd.history()
    c = sd.win_curve(h)
    d = h.with_columns([
        pl.col("spread_line").map_elements(
            lambda s: sd.win_prob(s, c), return_dtype=pl.Float64).alias("p"),
        (pl.col("margin") > 0).cast(pl.Int8).alias("y")])
    for lo, hi in ((0.0, 0.35), (0.35, 0.5), (0.5, 0.65), (0.65, 1.0)):
        b = d.filter((pl.col("p") >= lo) & (pl.col("p") < hi))
        if b.height < 100:
            continue
        said, got = float(b["p"].mean()), float(b["y"].mean())
        assert abs(got - said) < 0.06, (
            f"{lo}-{hi}: said {said:.3f}, happened {got:.3f} on {b.height}")
