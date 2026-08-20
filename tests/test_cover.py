"""The full-cover section: back every subset of the top N, and price it honestly.

The arithmetic is small enough to check in closed form, which is the point —
every number on that page should be reproducible by hand from the legs.

    pytest tests/test_cover.py -v
"""
from __future__ import annotations

from math import comb

import numpy as np
import pytest

from src.prediction.cover import MAX_PLAYERS, portfolio, slip_counts, slips


def _flat(n, p, odds=None, decimal=2.0):
    return [{"name": f"P{i}", "team": "AAA", "prob": p, "odds": odds}
            for i in range(n)]


def test_the_bet_count_is_the_power_set_minus_the_empty_slip():
    """5 players is 31 bets: 5 + 10 + 10 + 5 + 1."""
    assert [r["combinations"] for r in slip_counts(5)] == [5, 10, 10, 5, 1]
    assert sum(r["combinations"] for r in slip_counts(5)) == 31
    for n in range(1, 9):
        assert len(slips(n)) == 2 ** n - 1 == sum(comb(n, k) for k in range(1, n + 1))


def test_winning_bets_when_k_score_is_two_to_the_k_minus_one():
    """A slip pays only if every leg is among the scorers.

    So with k of n scoring, the slips that win are exactly the non-empty
    subsets of those k — 1, 3, 7, 15, 31 for k = 1..5, independent of n.
    """
    out = portfolio(_flat(5, 0.5), stake=1.0, assumed_decimal=1.5)
    assert [r["winning_bets"] for r in out["rows"]] == [0, 1, 3, 7, 15, 31]


def test_returns_match_the_closed_form_for_equal_prices():
    """With every leg at decimal d, k scorers return (1+d)^k - 1 per unit.

    This is the row a hand-written table gets wrong: the empty subset is not a
    bet, so the -1 belongs there. Backing five at 1.5 returns 96.66 on a
    five-timer week, not 97.66.
    """
    d, stake = 1.5, 1.0
    out = portfolio(_flat(5, 0.5), stake=stake, assumed_decimal=d)
    for k, row in enumerate(out["rows"]):
        assert row["returned"] == pytest.approx(stake * ((1 + d) ** k - 1)), k
    assert out["rows"][5]["returned"] == pytest.approx(96.65625)
    assert out["staked"] == 31.0
    assert out["rows"][0]["net"] == pytest.approx(-31.0)


def test_whether_a_cover_beats_its_singles_turns_on_the_sign_of_the_edge():
    """The claim the section exists to make visible — and it is conditional.

    Write a leg's edge as `e`, so decimal odds times true probability is 1 + e.
    Per dollar a single returns `e` and a k-fold returns `(1 + e)^k - 1`. So a
    cover AMPLIFIES a real edge and amplifies a negative one just as hard; it
    is leverage, not alchemy.

    This test exists because the module's first docstring claimed the dominance
    was unconditional — "a full cover is dominated by backing the N singles" —
    and it is not. At p=0.60 into decimal 1.70 the cover returns +5.27% against
    the singles' +2.00%.
    """
    # Negative edge: 0.5 * 1.5 = 0.75, so e = -0.25. The cover must be worse.
    losing = portfolio(_flat(5, 0.5), stake=1.0, assumed_decimal=1.5)
    assert losing["expected_roi"] < losing["singles_only"]["expected_roi"]

    # Positive edge: 0.6 * 1.7 = 1.02, so e = +0.02. The cover must be better.
    winning = portfolio(_flat(5, 0.6), stake=1.0, assumed_decimal=1.7)
    assert winning["expected_roi"] > winning["singles_only"]["expected_roi"], (
        "with a real edge on every leg a parlay compounds it; a cover that "
        "could not beat its singles here would mean the pricing is wrong")

    # And the magnitude follows (1 + e)^k - 1 exactly on the five-fold.
    e = 0.6 * 1.7 - 1
    five = portfolio(_flat(5, 0.6), stake=1.0, assumed_decimal=1.7)
    fivefold_ev = (1 + e) ** 5 - 1
    assert fivefold_ev == pytest.approx(0.1040808, abs=1e-6)
    assert five["expected_roi"] > e, "the cover must sit above the single's edge"


def test_a_fair_price_makes_both_break_even_which_is_the_control():
    """At the true price, every slip is a coin flip and EV is zero either way.

    Without this the dominance test above could be passing on a bug that always
    returns a negative number.
    """
    p = 0.5
    out = portfolio(_flat(5, p), stake=1.0, assumed_decimal=1 / p)
    assert out["expected_roi"] == pytest.approx(0.0, abs=1e-9)
    assert out["singles_only"]["expected_roi"] == pytest.approx(0.0, abs=1e-9)


def test_pattern_probabilities_are_a_distribution_and_keep_their_marginals():
    """Enumerating 2^n patterns is only worth doing if it stays a distribution."""
    from src.prediction.cover import _pattern_probs

    p = np.array([0.46, 0.40, 0.33, 0.33, 0.28])
    for rho in (0.0, 0.022, -0.05):
        probs = _pattern_probs(p, rho, ["A"] * 5)
        assert probs.sum() == pytest.approx(1.0)
        assert (probs >= 0).all()
    # Independence must reproduce the marginals exactly.
    probs = _pattern_probs(p, 0.0, ["A"] * 5)
    bits = ((np.arange(32)[:, None] >> np.arange(5)) & 1)
    assert np.allclose((probs[:, None] * bits).sum(axis=0), p)


def test_correlation_applies_between_teammates_and_not_across_games():
    """`fit_correlation` measures a TEAM-GAME effect.

    Applying it to every pair inflated the tail of a cross-game cover — a
    Chargers receiver and a Bears one were being correlated on the strength of
    a number measured about two backs sharing goal-line carries.
    """
    p = [{"name": f"P{i}", "prob": 0.4, "team": t}
         for i, t in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE"])]
    indep = portfolio(p, rho=0.0, assumed_decimal=2.0)
    corr = portfolio(p, rho=0.05, assumed_decimal=2.0)
    assert corr["rows"][5]["probability"] == pytest.approx(
        indep["rows"][5]["probability"]), "different games must stay independent"

    mates = [{**x, "team": "AAA"} for x in p]
    corr_mates = portfolio(mates, rho=0.05, assumed_decimal=2.0)
    assert corr_mates["rows"][5]["probability"] > indep["rows"][5]["probability"], (
        "positive teammate correlation must fatten the all-score tail")


def test_heterogeneous_prices_are_not_collapsed_into_an_average():
    """Which k score matters, not only how many.

    Three cheap legs and three dear ones return very different amounts, so the
    per-count row has to carry the spread rather than pretend there is one
    number.
    """
    legs = [{"name": "a", "team": "A", "prob": 0.5, "odds": -300},
            {"name": "b", "team": "B", "prob": 0.5, "odds": -300},
            {"name": "c", "team": "C", "prob": 0.5, "odds": +600}]
    out = portfolio(legs, stake=1.0)
    two = out["rows"][2]
    assert two["returned_min"] < two["returned_max"], (
        "two of three can be the two short legs or one short and the long one; "
        "a single number for the row hides that")
    assert two["returned_min"] <= two["returned"] <= two["returned_max"]


def test_an_unpriced_leg_needs_a_stated_assumption_and_is_flagged():
    """A board with no market price still answers, but never silently."""
    legs = _flat(3, 0.5, odds=None)
    with pytest.raises(ValueError, match="no price"):
        portfolio(legs, stake=1.0)

    out = portfolio(legs, stake=1.0, assumed_decimal=2.0)
    assert out["all_priced"] is False
    assert out["assumed_decimal"] == 2.0
    assert all(leg["priced"] is False for leg in out["legs"])


def test_the_pool_size_is_bounded():
    with pytest.raises(ValueError):
        portfolio(_flat(MAX_PLAYERS + 1, 0.5), assumed_decimal=2.0)
    with pytest.raises(ValueError):
        slips(0)


def test_the_scaling_ladder_reproduces_the_hand_worked_table():
    """Checked against a table worked by hand at decimal 1.667 (+67).

    N players is 2^N - 1 slips, and k scorers return (1+d)^k - 1 per unit, so
    every figure here is reproducible without the code.
    """
    from src.prediction.cover import ladder

    rows = {r["players"]: r for r in ladder(1.6667, max_n=10)}
    assert [rows[n]["bets"] for n in (1, 4, 5, 7, 10)] == [1, 15, 31, 127, 1023]
    assert [rows[n]["need"] for n in range(1, 11)] == [1, 2, 3, 3, 4, 5, 5, 6, 7, 8]
    assert rows[5]["all_return"] == pytest.approx(133.86, abs=0.02)
    assert rows[7]["all_profit"] == pytest.approx(831.00, abs=0.05)


def test_the_hit_rate_needed_is_not_monotone_in_pool_size():
    """The finding the ladder exists to surface.

    The outlay doubles with each player while the return multiplies by (1 + d),
    so a pool sometimes lands just below the point where one fewer scorer
    starts paying — and a whole scorer comes off the requirement. At d = 1.667
    that makes 4 and 7 more forgiving than the sizes either side.

    Asserted as a shape rather than a fixed answer, because WHICH sizes are
    forgiving moves with the price: the section recomputes it instead of
    printing a remembered table.
    """
    from src.prediction.cover import easiest, ladder

    rows = ladder(1.6667, max_n=10)
    rates = [r["need_rate"] for r in rows]
    assert rates[3] < rates[2] and rates[3] < rates[4], "N=4 must dip"
    assert rates[6] < rates[5] and rates[6] < rates[7], "N=7 must dip"
    assert easiest(rows) == [7]

    # A different price moves the pattern, which is why it is computed.
    other = ladder(2.5, max_n=10)
    assert [r["need"] for r in other] != [r["need"] for r in rows], (
        "the requirement must depend on the price; a fixed table would be "
        "right at one price and quietly wrong at every other")


def test_the_ladder_can_say_how_likely_the_requirement_is():
    """"You need 4 of 5" is not a decision until you know how often that lands."""
    from src.prediction.cover import ladder

    probs = [0.62, 0.48, 0.47, 0.40, 0.36]
    rows = ladder(2.0, max_n=5, probs=probs)
    for r in rows:
        assert 0.0 <= r["p_need"] <= 1.0
        assert r["p_all"] <= r["p_need"], (
            "reaching the requirement must be at least as likely as everyone "
            "scoring")
    assert rows[4]["p_all"] == pytest.approx(
        probs[0] * probs[1] * probs[2] * probs[3] * probs[4], rel=1e-9)


def test_the_exporter_knows_every_widget_the_cover_section_uses():
    """A widget the export cannot draw takes the whole publish down.

    `make publish` failed with "The export's fake Streamlit has no
    `segmented_control`" the first time this section was published, because the
    exporter supports a fixed widget set and the section reached outside it.
    The failure is loud and its message names the fix, which is the right
    design — this test just moves the discovery earlier than a publish.
    """
    import re
    from pathlib import Path

    from src.export.capture import Capture

    root = Path(__file__).resolve().parents[1]
    src = (root / "app.py").read_text()
    start = src.index("# ── Cover the field ")
    end = src.index("# ── By team ", start)
    used = set(re.findall(r"\b(?:st|_kbar)\.(\w+)\(", src[start:end]))

    cap = Capture()
    for name in sorted(used):
        assert hasattr(cap, f"_el_{name}") or hasattr(cap, name), (
            f"the cover section calls `{name}` and the exporter cannot draw "
            f"it — add an `_el_{name}` to src/export/capture.py")


def test_multi_select_segmented_control_is_refused_rather_than_collapsed():
    """A static page cannot publish one answer to a control offering several."""
    import pytest as _pytest

    from src.export.capture import Capture

    cap = Capture()
    with _pytest.raises(NotImplementedError, match="multi-select"):
        cap._el_segmented_control(cap.main, "Modes", ["a", "b"],
                                  selection_mode="multi")


def test_a_graded_cover_reports_an_interval_not_only_a_point_estimate():
    """The number that made this necessary.

    First TD's three-player cover replayed at +52.7% — off ten profitable weeks
    in sixty, with the single best week supplying 35.5% of everything returned.
    A point estimate on that shape is an anecdote. The week-clustered bootstrap
    puts it at [-23.4%, +156.9%], which is the honest reading.
    """
    from src.evaluation.cover_backtest import load
    from src.utils.paths import get_path

    seen = False
    for market in ("anytime_td", "first_td"):
        rec = load(get_path("output", market) / "cover_backtest.json")
        if rec is None:
            continue
        seen = True
        for s in rec["sizes"]:
            assert s["roi_lo"] <= s["roi"] <= s["roi_hi"], (
                f"{market} N={s['n']}: the point estimate must sit inside its "
                f"own interval")
            assert 0.0 <= s["top_week_share"] <= 1.0
            assert s["roi_beats_zero"] == (s["roi_lo"] > 0), (
                "profitable must mean the interval clears zero, not that the "
                "point estimate happens to be positive")
        assert rec["any_profitable"] == any(
            s["roi_beats_zero"] for s in rec["sizes"])
    if not seen:
        pytest.skip("no graded cover backtest in this checkout")


def test_the_replay_grades_a_slip_only_when_every_leg_scored():
    """One wrong leg is the same as all of them wrong — that is the whole point."""
    import pandas as pd

    from src.evaluation.cover_backtest import replay_week

    # Three legs at +100 (decimal 2.0); two score. Winning slips are the two
    # singles and the one double between them: 2 + 4 = $6 back on $7 staked.
    board = pd.DataFrame({
        "game_id": ["g1", "g2", "g3"],
        "_p": [0.6, 0.5, 0.4],
        "_hit": [1.0, 1.0, 0.0],
        "odds": [100, 100, 100],
    })
    out = replay_week(board, 3, stake=1.0)
    assert out["slips"] == 7 and out["staked"] == 7.0
    assert out["won"] == 3, "two singles and one double"
    assert out["returned"] == pytest.approx(2.0 + 2.0 + 4.0)
    assert out["scorers"] == 2
    assert out["net"] == pytest.approx(1.0)


def test_the_replay_takes_one_player_per_game():
    """A single game's top N are usually teammates, which guts the tail."""
    import pandas as pd

    from src.evaluation.cover_backtest import replay_week

    board = pd.DataFrame({
        "game_id": ["g1", "g1", "g1", "g2"],
        "_p": [0.9, 0.8, 0.7, 0.6],
        "_hit": [1.0, 1.0, 1.0, 0.0],
        "odds": [100, 100, 100, 100],
    })
    # Only two distinct games, so a three-player cover cannot be formed.
    assert replay_week(board, 3, stake=1.0) is None
    out = replay_week(board, 2, stake=1.0)
    assert out["scorers"] == 1, "the second leg must come from the other game"
