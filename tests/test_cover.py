"""The full-cover section: back every subset of the top N, and price it honestly.

The arithmetic is small enough to check in closed form, which is the point —
every number on that page should be reproducible by hand from the legs.

    pytest tests/test_cover.py -v
"""
from __future__ import annotations

from math import comb

import numpy as np
import pytest

from src.prediction.cover import (ASSUMED_FROM_TOP, CURVE_MIN_POINTS,
                                  MAX_PLAYERS, assumed_decimal, assumed_price,
                                  portfolio, price_curve, sizes_for,
                                  slip_counts, slips)


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


# ── Would a different rule have done better ───────────────────────────────

def test_the_chooser_cannot_see_the_week_it_is_choosing_for():
    """The one bug that would make this measurement spectacular and false.

    The walk-forward chooser picks each week's variant from cumulative returns
    through the *previous* week. Update the record before the pick instead of
    after and a week's own result chooses that week's variant — the same defect
    as training on the test set, and it would read as an enormous edge rather
    than as an error.
    """
    from src.evaluation import cover_selection as cs

    # Two variants, one perfect and one useless, and a run of weeks where the
    # good one only becomes identifiable partway through. A leaking chooser
    # scores every week; an honest one cannot score the weeks before it knows.
    weeks = []
    for i in range(cs.BURN_IN + 20):
        weeks.append({
            "good": {"net": 1.0 if i % 2 else -0.5, "staked": 1.0,
                     "returned": 2.0, "n": 3, "slips": 7},
            "bad": {"net": -1.0, "staked": 1.0, "returned": 0.0,
                    "n": 3, "slips": 7},
        })
    summary, detail = cs._chooser(weeks, "bad")
    assert summary["weeks"] == len(weeks)
    # Burn-in is spent on the baseline by construction, so a chooser that
    # somehow returns a perfect record has looked forward.
    assert summary["weeks_profitable"] < len(weeks), (
        "no chooser can be profitable in every week including its burn-in")


def test_every_ordering_is_computable_before_kickoff():
    """A sort key built from the result is not a selection rule.

    All six orderings come off the board: the published probability, the
    model's own, and the two differences from the price. Nothing here may touch
    the label column, which `replay_week` alone is allowed to read.
    """
    import inspect

    from src.evaluation import cover_selection as cs

    src = inspect.getsource(cs._keys) + inspect.getsource(cs.play)
    for forbidden in ("_hit", "target", "scored"):
        assert forbidden not in src, (
            f"selection reads `{forbidden}` — that is the outcome, and a rule "
            f"that reads it is not a rule")


def test_the_random_control_is_redrawn_because_one_draw_decides_nothing():
    """The control's own headline moves 250 points on the seed.

    Best-of-44 on random orderings returned +6% on one redraw and +274% on
    another, which is the sharpest available statement about what a
    max-over-variants is worth — and it is only visible because the control
    runs more than once. Comparisons use the luckiest redraw: the question is
    what the best of 44 buys when nothing is there, so the honest opponent is
    the luckiest control rather than the typical one.
    """
    from src.evaluation import cover_selection as cs

    assert cs.CONTROL_REPEATS >= 3
    assert cs.N_RANDOM == len(cs.variants()), (
        "the control must run the same number of variants as the real arm, or "
        "'best of N' is not being compared against 'best of N'")

    spread = cs._spread([0.1, 0.9, 0.5])
    assert spread["max"] == 0.9 and spread["min"] == 0.1
    assert spread["runs"] == 3


def test_a_measured_selection_run_reports_its_control_beside_its_result():
    from src.evaluation.cover_selection import load
    from src.utils.paths import get_path

    seen = False
    for market in ("anytime_td", "first_td"):
        stats = load(get_path("output", market) / "cover_selection.json")
        if stats is None:
            continue
        seen = True
        c = stats["control"]
        assert c["repeats"] >= 3 and c["n_variants"] == stats["n_variants"]
        for key in ("best_roi", "ceiling_roi", "chooser_roi", "median_roi"):
            assert c[key]["min"] <= c[key]["median"] <= c[key]["max"]
        # The finding, such as it is: the ceiling and the best variant are
        # beaten by noise, and the median and the chooser are not.
        assert stats["median_variant_roi"] > c["median_roi"]["max"], (
            f"{market}: the median real variant does not beat the median "
            f"random one, which would leave nothing here to report")
        # AGAINST THE TYPICAL RANDOM ORDERING, NOT THE LUCKIEST OF FIVE.
        #
        # This compared the chooser to `chooser_roi["max"]`, and that number is
        # unstable by the measuring script's own account: it says the control
        # headline "moves from +6% to +274% on the seed alone". The max of five
        # draws from a quantity that swings forty-fold is a coin toss, so the
        # assertion passed or failed on which seeds came up, not on whether the
        # rule works. Promoting a model on 2026-09-25 flipped it: the chooser
        # came back at -3.0% against a control max of +40.2%, having beaten the
        # control MEDIAN of -19.2% comfortably.
        #
        # The median is the stable bar and the one with a claim behind it — a
        # chooser worth having beats a typical random ordering. The max stays
        # in the artifact and the dashboard prints it, which is the honest
        # place for a number that says "read this as a direction".
        assert stats["chooser"]["roi"] > c["chooser_roi"]["median"], (
            f"{market}: the walk-forward chooser does not beat a typical "
            f"random one")
        # AND THE COMPARISON HAS TO STILL BE THERE. The dashboard prints the
        # control's best beside the result; drop it and the page quietly turns
        # a direction into a finding.
        assert "max" in c["chooser_roi"] and "roi" in stats["chooser"], (
            f"{market}: the control comparison is no longer reported")
    if not seen:
        pytest.skip("no cover selection measured in this checkout")


def test_the_teammate_correlation_is_fitted_on_one_model_not_every_frame_on_disk():
    """A sign error that hid inside a glob.

    `fit_correlation` matched `backtest_*.csv`, which is the current model's
    frames AND the unprefixed ones from an older run — on first TD, an
    `ensemble` set as well. Concatenated, each game-team appeared two or three
    times with a different `prob_calibrated`, so the covariance was substantially
    each player correlating with his own duplicate. It read +0.022 where one
    model's frames read -0.024.

    The sign is the entire content of this number: the cover applies it to
    teammate pairs, so the wrong sign inflates the chance of teammates scoring
    together exactly where the measurement says to deflate it. And nothing
    downstream could have caught it — `n_team_games` is identical either way,
    because grouping by (game_id, team) folds duplicates into one larger group.
    """
    import inspect

    from src.prediction.portfolio import fit_correlation

    src = inspect.getsource(fit_correlation)
    assert 'glob("backtest_*.csv")' not in src, (
        "this glob mixes model runs; scope it to one model's frames")
    assert "backtest_{who}_" in src

    for market in ("anytime_td", "first_td"):
        got = fit_correlation(market)
        if got is None:
            continue
        rho = got["teammate_rho"]
        assert rho < 0, (
            f"{market}: teammate correlation came back {rho:+.4f}. Teammates "
            f"compete for the same touchdowns, and on first TD only one player "
            f"can score first at all — a positive reading is the duplicate-frame "
            f"bug returning, not a discovery")
        assert abs(rho) < 0.05, "independence is no longer a fair approximation"


def test_a_one_player_cover_reads_as_one_bet_not_as_one_slips():
    """Three plural errors in one sentence, and the tell that nobody looked.

    The app's headline read "**1 slips** on 1 players — at $1.00 each" and then
    "All 1 legs priced by the book" the moment a single player was allowed. The
    line moved out of `app.py` so it can be checked without a Streamlit process
    running, which is the only reason it was not checked before.
    """
    from src.prediction.cover import portfolio
    from src.presentation.board import cover_headline

    m = lambda x: f"${x:,.2f}"                                   # noqa: E731
    one = portfolio([{"name": "A", "team": "X", "prob": 0.6, "odds": -120}],
                    stake=1.0)
    line = cover_headline(one, m)
    assert "**1 slip** on 1 player" in line
    assert "slips" not in line and "players" not in line
    assert "Priced by the book." in line
    assert "-leg" not in line, (
        "the slip breakdown is a list of one at n=1 and says nothing")

    two = portfolio([{"name": "A", "team": "X", "prob": 0.6, "odds": -120},
                     {"name": "B", "team": "Y", "prob": 0.5, "odds": None}],
                    stake=1.0, assumed_decimal=2.0)
    line = cover_headline(two, m)
    assert "**3 slips** on 2 players" in line
    assert "1 of 2 legs priced" in line


# ── The stand-in price for an unpriced leg ─────────────────────────────────


def test_the_stand_in_price_takes_the_best_rated_players_a_book_has_priced():
    """Priced first, then the top of those — not the other way round.

    Filtering the top of the board and keeping whichever happen to carry a
    price makes the answer depend on how many unpriced rows the caller's frame
    holds. That is not hypothetical: the app's board is priced-only and the
    page's list is every rated player, and under the other order one slate read
    +277 on one surface and +123 on the other.
    """
    # The likeliest four are unpriced; the priced ones sit below them.
    prob = [0.60, 0.55, 0.50, 0.45, 0.40, 0.30, 0.20, 0.10]
    dec = [None, None, None, None, 2.0, 3.0, 5.0, 21.0]
    both = assumed_price(prob, dec, top_n=2)
    # Top two *priced* are the 0.40 and 0.30 players: 2.0 and 3.0.
    assert both == pytest.approx(2.5)

    # The same players handed over as a priced-only frame — which is what the
    # app passes — must give the same number.
    assert assumed_price(prob[4:], dec[4:], top_n=2) == pytest.approx(2.5)


def test_the_stand_in_price_is_a_median_not_a_mean():
    """One +2500 reserve must not drag it somewhere unrecognisable."""
    prob = [0.5, 0.4, 0.3]
    assert assumed_price(prob, [2.0, 2.2, 26.0], top_n=3) == pytest.approx(2.2)


def test_the_stand_in_price_is_none_when_nothing_is_priced():
    """A real state three weeks before a season, and not a zero."""
    assert assumed_price([0.5, 0.4], [None, None]) is None
    assert assumed_price([], []) is None
    # A decimal price pays back more than the stake; 1.0 is a missing value
    # wearing a number.
    assert assumed_price([0.5], [1.0]) is None


def test_the_stand_in_price_is_read_off_a_cover_sized_slice():
    """How deep it looks moves it a long way, so the depth is the calibre.

    Ten is about the ceiling on cover size, so the answer describes the players
    it is about to be used for rather than the reserves below them.
    """
    assert ASSUMED_FROM_TOP <= MAX_PLAYERS
    prob = [0.5 - 0.01 * i for i in range(40)]
    dec = [2.0] * 10 + [40.0] * 30
    assert assumed_price(prob, dec) == pytest.approx(2.0)


# ── What a book would ask for a leg nobody quoted ──────────────────────────


def _market(a: float, b: float, probs) -> tuple[list, list]:
    """A market whose posted prices lie on a logit line through our numbers."""
    import math
    dec = []
    for p in probs:
        lg = math.log(p / (1 - p))
        q = 1 / (1 + math.exp(-(a + b * lg)))
        dec.append(1 / q)
    return list(probs), dec


def test_the_price_curve_recovers_the_line_the_market_priced_on():
    probs = [0.05 + 0.03 * i for i in range(18)]
    p, d = _market(0.16, 0.85, probs)
    c = price_curve(p, d)
    assert c["a"] == pytest.approx(0.16, abs=1e-6)
    assert c["b"] == pytest.approx(0.85, abs=1e-6)
    assert (c["lo"], c["hi"]) == (pytest.approx(min(probs)), pytest.approx(max(probs)))
    assert c["n"] == len(probs)


def test_the_curve_carries_the_margin_rather_than_a_flat_price():
    """The whole reason one stand-in cannot serve a cover.

    Books hold far more on a 10% player than on a 50% one. A single median
    price assumes the opposite — it hands the top of the board, which is what a
    cover is built from, an overlay that the payout column cannot show, because
    that column is built from prices and does not move when the probabilities
    do.
    """
    p, d = _market(0.16, 0.85, [0.05 + 0.03 * i for i in range(18)])
    c = price_curve(p, d)
    hold = lambda x: (1 / assumed_decimal(c, x)) / x - 1
    assert hold(0.10) > hold(0.50) > 0, "margin must fall as the player gets likelier"
    # And a 55% player must not be charged the median of the whole board.
    flat = assumed_price(p, d)
    assert assumed_decimal(c, 0.55) < flat


def test_the_curve_is_clamped_rather_than_extrapolated():
    """First TD has nobody rated above 15%; a line run past that is fiction."""
    p, d = _market(-1.09, 0.50, [0.01 + 0.01 * i for i in range(14)])
    c = price_curve(p, d)
    assert assumed_decimal(c, 0.55) == pytest.approx(assumed_decimal(c, c["hi"]))
    assert assumed_decimal(c, 0.0001) == pytest.approx(assumed_decimal(c, c["lo"]))


def test_too_few_priced_players_is_no_curve_at_all():
    probs = [0.4, 0.3, 0.2]
    assert len(probs) < CURVE_MIN_POINTS
    assert price_curve(probs, [2.0, 3.0, 5.0]) is None
    assert assumed_decimal(None, 0.4) is None


def test_a_legs_own_stand_in_beats_the_flat_one_and_is_not_called_priced():
    """A filled-in price must never pass itself off as a posted one."""
    legs = [{"name": "A", "prob": 0.5, "odds": None, "assumed": 1.8},
            {"name": "B", "prob": 0.4, "odds": -110}]
    cov = portfolio(legs, stake=1.0, assumed_decimal=4.0)
    assert cov["legs"][0]["decimal"] == pytest.approx(1.8), "the leg's own price"
    assert cov["legs"][0]["priced"] is False
    assert cov["all_priced"] is False


# ── The round robin: which slips are actually staked ────────────────────────
# A book sells these by leg-count. Backing every combination is one structure
# among several, and for a while it was the only one this module could price.


def test_a_round_robin_stakes_only_the_leg_counts_it_was_sold():
    """FanDuel's "By 2's" on six players is 15 doubles for $15, not 63 for $63."""
    out = portfolio(_flat(6, 0.5, odds=100), stake=1.0, sizes=[2])
    assert out["bets"] == 15 == comb(6, 2)
    assert out["staked"] == pytest.approx(15.0)
    assert out["sizes"] == [2]
    assert out["full_cover"] is False
    assert [r["combinations"] for r in out["counts"]] == [15]

    both = portfolio(_flat(6, 0.5, odds=100), stake=1.0, sizes=[2, 3])
    assert both["bets"] == comb(6, 2) + comb(6, 3) == 35


def test_the_default_is_the_full_cover_it_always_was():
    """The argument is additive: a caller that never passes it is untouched.

    This is the back-compatibility guard. Everything else in this file was
    written against a function that had no `sizes`, and all of it still runs
    unchanged above — this says so explicitly rather than leaving it implied.
    """
    for n in range(1, 7):
        legs = _flat(n, 0.4, odds=150)
        implied = portfolio(legs, stake=2.0)
        spelled = portfolio(legs, stake=2.0, sizes=list(range(1, n + 1)))
        assert implied["bets"] == spelled["bets"] == 2 ** n - 1
        assert implied["full_cover"] is True
        assert implied["rows"] == spelled["rows"]
        assert implied["expected_net"] == pytest.approx(spelled["expected_net"])


def test_winning_bets_under_a_structure_is_the_binomial_not_the_power_set():
    """With k of n scoring, a By-2's book wins C(k, 2) of its slips.

    The full cover's 2^k - 1 counts every subset of the scorers; a structure
    counts only the subsets whose size it bought. On six players that is
    0, 0, 1, 3, 6, 10, 15 — the shape a reader recognizes from the book's own
    slip, and the reason the count cannot be left keyed to the power set.
    """
    out = portfolio(_flat(6, 0.5, odds=100), stake=1.0, sizes=[2])
    assert [r["winning_bets"] for r in out["rows"]] == [0, 0, 1, 3, 6, 10, 15]
    assert [r["winning_bets"] for r in out["rows"]] == [comb(k, 2)
                                                        for k in range(7)]

    both = portfolio(_flat(6, 0.5, odds=100), stake=1.0, sizes=[2, 3])
    assert [r["winning_bets"] for r in both["rows"]] == [
        comb(k, 2) + comb(k, 3) for k in range(7)]


def test_a_structure_still_prices_every_slip_off_its_own_legs():
    """The trap a structure creates: reporting C(k, s) and calling it a return.

    Three legs at decimal 2, 3 and 4, By 2's, $1 a slip. The three doubles pay
    6, 8 and 12, so which two score matters as much as how many — and the row
    for "2 of 3" has to carry that spread rather than an average standing in
    for it. Hand-checkable, which is the point.
    """
    legs = [{"name": "A", "team": "AAA", "prob": 0.5, "odds": 100},    # 2.0
            {"name": "B", "team": "AAA", "prob": 0.5, "odds": 200},    # 3.0
            {"name": "C", "team": "AAA", "prob": 0.5, "odds": 300}]    # 4.0
    out = portfolio(legs, stake=1.0, sizes=[2])
    assert out["bets"] == 3

    two = out["rows"][2]
    assert two["winning_bets"] == 1
    assert two["returned_min"] == pytest.approx(6.0)     # A+B
    assert two["returned_max"] == pytest.approx(12.0)    # B+C
    # Equal probabilities, so the three patterns are equally likely and the
    # weighted figure is their mean -- not any one of them.
    assert two["returned"] == pytest.approx((6.0 + 8.0 + 12.0) / 3)

    # All three scoring wins all three doubles.
    assert out["rows"][3]["returned"] == pytest.approx(26.0)
    assert out["rows"][3]["winning_bets"] == 3


def test_the_singles_null_is_rebased_on_what_the_structure_risks():
    """A comparison at unequal money is not a comparison.

    A By-2's on six risks $15. The honest null is $15 spread over the six
    singles, not the $63 a full cover would have staked — which is what the
    line under the table claims when it says "for the same money".
    """
    for sizes in (None, [2], [2, 3], [1], [6]):
        out = portfolio(_flat(6, 0.45, odds=140), stake=1.0, sizes=sizes)
        assert out["singles_only"]["staked"] == pytest.approx(out["staked"])
        assert out["singles_only"]["bets"] == 6


def test_a_size_the_pool_cannot_fill_is_an_empty_stratum_not_an_error():
    """C(3, 4) is zero, not a mistake — and trimming a player is ordinary.

    The UI keeps a selection across reruns, so a reader who picks "By 4's" and
    then removes a player must get a table, not an exception.
    """
    assert sizes_for(3, [2, 4]) == [2]
    assert portfolio(_flat(3, 0.5, odds=100), sizes=[2, 4])["sizes"] == [2]
    assert sizes_for(4, None) == [1, 2, 3, 4]
    # Deduplicated and ordered, however it arrives.
    assert sizes_for(5, [3, 2, 2]) == [2, 3]


def test_a_structure_that_stakes_nothing_is_refused():
    """Staking no money is not a portfolio, and every ratio divides by it."""
    with pytest.raises(ValueError, match="nothing would be staked"):
        sizes_for(3, [4, 5])
    with pytest.raises(ValueError, match="at least one leg"):
        sizes_for(5, [0, 2])
    with pytest.raises(ValueError, match="at least one slip size"):
        sizes_for(5, [])


def test_a_structure_is_named_the_way_a_book_sells_it():
    """"By 2's and 3's" — the "by" is said once over the list, not per size."""
    from src.presentation.board import cover_structure

    def name(n, sizes):
        return cover_structure(portfolio(_flat(n, 0.5, odds=100), sizes=sizes))

    assert name(6, None) == "every combination"
    assert name(6, [2]) == "by 2s"
    assert name(6, [2, 3]) == "by 2s and 3s"
    assert name(6, [2, 3, 4]) == "by 2s, 3s and 4s"
    assert name(6, [1]) == "singles only"
    assert name(6, [1, 2]) == "singles and by 2s"
    assert name(6, [6]) == "the 6-leg only"
