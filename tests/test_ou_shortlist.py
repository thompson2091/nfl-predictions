"""The shortlist rule for the four over/under markets.

The rule itself is `src/evaluation/ou_shortlist.py`. What is asserted here is
the part of it that would otherwise be wrong silently: the market's own
open-to-close drift is removed before any band is read, the floor is chosen on
closing-line value rather than on what paid, and a two-sided market has no
veto.
"""
from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.evaluation import ou_shortlist as ous


def frame(n=800, drift_pp=0.40, skill_pp=0.0, seed=0) -> pl.DataFrame:
    """A market that drifts, priced by a model with `skill_pp` of real edge.

    Every row is its own fixture unless said otherwise, the book opens at a
    coin flip, and the close moves by the drift plus noise. With `skill_pp` at
    zero the model knows nothing: where it sits relative to the open is pure
    noise, and any band that reads as informative is reading the drift.
    """
    rng = np.random.default_rng(seed)
    open_fair = np.full(n, 0.50)
    p_model = np.clip(open_fair + rng.normal(0, 0.09, n), 0.01, 0.99)
    # The close drifts UP on every row, whatever the model thinks, plus noise.
    # Skill, where asked for, moves the close toward the model's side.
    toward = np.sign(p_model - open_fair) * (skill_pp / 100.0)
    close_fair = np.clip(open_fair + drift_pp / 100.0 + toward
                         + rng.normal(0, 0.01, n), 0.01, 0.99)
    return pl.DataFrame({
        "season": np.full(n, 2024),
        "game_id": [f"g{i}" for i in range(n)],
        "player_name_norm": [f"p{i}" for i in range(n)],
        "point": np.full(n, 50.5),
        "open_fair": open_fair, "close_fair": close_fair,
        "over_imp": np.full(n, 0.524), "under_imp": np.full(n, 0.524),
        "overround": np.full(n, 1.048),
        "n_books": np.full(n, 5),
        "p_model": p_model,
        "won_over": rng.integers(0, 2, n),
    })


def test_the_market_drift_comes_out_before_any_band_is_read():
    """The close sits above the open on nearly every row, and it is not ours.

    De-vigged, the over's probability rises from open to close across the whole
    archive — +0.24pp on rushing yards, +0.34 on receiving, +0.16 on
    receptions. Measured raw, that hands every over we like a free +0.3pp of
    apparent closing-line value and charges every under the same, so an
    uncentered fit concludes our overs anticipate the market on all four
    markets and our unders are wrong on all four.

    Falsified by dropping the `- market_drift` / `+ market_drift` terms in
    `bands`: the model below has no skill at all, and every over band turns
    positive while every under band turns negative — which is the fit
    discovering the market's own drift and putting our name on it.
    """
    rows = frame(drift_pp=0.40, skill_pp=0.0)
    d = ous.drift(rows)
    assert d == pytest.approx(0.40, abs=0.06), (
        "the drift is measured over every pair with no reference to the model")

    bs = ous.bands(rows, d)
    assert bs, "the bands must be measured, not skipped"
    for b in bs:
        assert abs(b["mean_move_pp"]) < 0.12, (
            f"{b['side']} {b['lo']}: a model with no skill must not read as "
            f"{b['mean_move_pp']:+.3f}pp of closing-line value")

    # And the same frame read raw, which is the bug. Both sides, one sign each.
    raw = ous.bands(rows, 0.0)
    over = [b for b in raw if b["side"] == "over"]
    under = [b for b in raw if b["side"] == "under"]
    assert over and under
    assert all(b["mean_move_pp"] > 0.2 for b in over), (
        "uncentered, every over is credited with the market's drift")
    assert all(b["mean_move_pp"] < -0.2 for b in under), (
        "and every under is charged the same amount")


def test_real_skill_still_reads_as_skill_once_the_drift_is_out():
    """Centering must not be a way of measuring nothing.

    The correction subtracts a constant, so a model that genuinely anticipates
    the close has to survive it. Falsified by subtracting the drift twice: the
    skill below goes to zero and this fails while the test above still passes,
    which is the pair that pins the correction to the right size.
    """
    rows = frame(drift_pp=0.40, skill_pp=0.50, seed=3)
    bs = ous.bands(rows, ous.drift(rows))
    assert bs
    assert all(b["mean_move_pp"] > 0.25 for b in bs), (
        "half a point of real movement toward us must survive the centering")


def test_the_floor_is_chosen_on_movement_and_never_on_what_paid():
    """Eight bands per market; the best-paying one is a coin flip's winner.

    Picking the band with the highest return would find one at 5% about once
    per market by construction, and the scan would BE the finding. The floor is
    chosen on closing-line value, which has an observation for every priced row
    rather than only the settled ones, and the return is reported over whatever
    that choice produced.

    Falsified by ranking `floor_for` on `roi`: the band below pays best and
    moves worst, and the assertion picks it up.
    """
    bs = [
        {"side": "over", "lo": 0.0, "hi": 2.0, "n": 500,
         "mean_move_pp": -0.30, "roi": +40.0},     # pays best, moves against us
        {"side": "over", "lo": 2.0, "hi": 5.0, "n": 500,
         "mean_move_pp": +0.10, "roi": -12.0},     # the honest answer
        {"side": "over", "lo": 5.0, "hi": None, "n": 20,
         "mean_move_pp": +9.90, "roi": +90.0},     # too few rows to mean anything
    ]
    f = ous.floor_for(bs, "over")
    assert f is not None and f["lo"] == 2.0, (
        "the smallest band with non-negative movement and enough rows")
    assert ous.floor_for(bs, "under") is None, (
        "no band on a side is a real answer, and the one first TD gives")


def test_a_band_too_thin_to_mean_anything_cannot_become_the_floor():
    """`MIN_BAND_N` is a floor on the measurement, not on the archive."""
    thin = [{"side": "under", "lo": 0.0, "hi": 2.0,
             "n": ous.MIN_BAND_N - 1, "mean_move_pp": +5.0, "roi": +50.0}]
    assert ous.floor_for(thin, "under") is None


def test_an_over_under_board_has_no_veto_only_a_side():
    """A touchdown prop sells Yes; a line sells both.

    So a player we rate below the price is not an opinion you cannot act on,
    it is a bet on the under — and the rule picks a side per row rather than
    throwing half the board away. Falsified by dropping the `under` branch in
    `apply_to_board`: every row below sits under its price and the shortlist
    empties.
    """
    art = {"floors": {"over": {"lo": 2.0, "hi": None},
                      "under": {"lo": 2.0, "hi": None}},
           "graded": []}
    rows = [
        {"player_name": "Low Ball", "point": 40.5, "fair_prob": 0.60,
         "open_point": 40.5, "open_fair": 0.60,
         "model_only": 0.40, "n_books": 5},          # 20pp under
        {"player_name": "High Ball", "point": 70.5, "fair_prob": 0.40,
         "open_point": 70.5, "open_fair": 0.40,
         "model_only": 0.60, "n_books": 5},          # 20pp over
    ]
    out = ous.apply_to_board(rows, art)
    got = {r["player_name"]: r["side"] for r in out["rows"]}
    assert got == {"Low Ball": "under", "High Ball": "over"}


def test_a_line_with_no_open_at_that_number_is_not_measured_against_the_current_price():
    """The floors were fitted on the gap to the open AT THE SAME LINE. A row
    whose open sat on another number, or that has none, is a different
    population; it is dropped and counted, never measured against the close."""
    art = {"floors": {"over": {"lo": 2.0, "hi": None},
                      "under": {"lo": 2.0, "hi": None}}, "graded": []}
    rows = [
        {"player_name": "Moved", "point": 41.5, "open_point": 39.5,
         "open_fair": 0.50, "fair_prob": 0.50, "model_only": 0.70, "n_books": 5},
        {"player_name": "No Open", "point": 41.5, "fair_prob": 0.50,
         "model_only": 0.70, "n_books": 5},
        {"player_name": "Same", "point": 41.5, "open_point": 41.5,
         "open_fair": 0.50, "fair_prob": 0.45, "model_only": 0.70, "n_books": 5},
    ]
    out = ous.apply_to_board(rows, art)
    assert [r["player_name"] for r in out["rows"]] == ["Same"]
    assert out["rows"][0]["gap_pp"] == pytest.approx(20.0)
    step = next(d for d in out["dropped"] if "opening price" in d["filter"])
    assert step["dropped"] == 2


def test_a_line_one_book_drew_is_not_a_line_the_rule_takes():
    """The depth gate the fit was made under, applied when it is served.

    On the yardage markets the model's apparent gain over the book is +0.0057
    at one book, -0.0143 at two and -0.0245 at three or more: the edge is an
    artifact of thin quotes. Serving without the gate serves a different rule
    from the one that was graded.
    """
    art = {"floors": {"over": {"lo": 2.0, "hi": None}}, "graded": []}
    rows = [{"player_name": "Thin", "point": 40.5, "fair_prob": 0.40,
             "model_only": 0.60, "n_books": 1}]
    out = ous.apply_to_board(rows, art)
    assert out["rows"] == []
    step = [d for d in out["dropped"] if "books" in d["filter"]]
    assert step and step[0]["dropped"] == 1, (
        "and the funnel says which measurement emptied it")


def test_an_unfitted_market_says_so_rather_than_showing_an_empty_list():
    """"The rule found nothing" and "the rule was never run" are not the same."""
    out = ous.apply_to_board([{"player_name": "A", "point": 1.5,
                               "fair_prob": 0.5, "model_only": 0.9,
                               "n_books": 9}], None)
    assert out["rows"] == []
    assert "50_ou_shortlist" in out["note"]


def test_the_under_price_is_recovered_from_the_book_and_not_invented():
    """`overround` is `p_over + p_under` as the book posted them.

    So the under's own implied probability is exactly what is left after the
    over comes out, and a graded return on the under side is settled at a
    price a book actually offered. Falsified by pricing the under at the
    over's number: the return below moves, because the two sides of a line are
    not quoted symmetrically.
    """
    rows = pl.DataFrame({
        "over_imp": [0.5413], "under_imp": [1.0476 - 0.5413],
        "won_over": [0],
    })
    ret = ous._returns(rows, over=False)
    assert ret[0] == pytest.approx(1.0 / (1.0476 - 0.5413) - 1.0, rel=1e-9)
    assert ous._returns(rows, over=True)[0] == -1.0
