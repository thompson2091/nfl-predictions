"""The promotion rule, and the instrument it is measured on.

Every case here is a row that actually ran. The numbers come from
`models/registry/ledger.jsonl`, so a change to the rule is scored against
decisions this project really made rather than against invented ones.
"""
from __future__ import annotations

import importlib

C = importlib.import_module("src.evaluation.compare")


def _top1(delta, se, band=0.0064):
    return {"delta": delta, "se": se, "noise_band": band}


def _clv(delta, se):
    return {"delta": delta, "se": se}


def test_line_movement_is_no_longer_rejected_by_an_instrument_that_cannot_see_it():
    """`2026.09.22-add-market-movement`, exactly as it scored.

    CLV +1.03pp at 4.66 se over 18,005 closes, p=3.5e-06 — the strongest
    result in the ledger. Top-1 moved +0.18pp at 0.23 se over 1,131 games,
    which is inside the noise band by construction. The old rule read only
    the second number and returned REJECTED.
    """
    verdict, by = C._decide(_top1(0.0017683, 0.0078121), [],
                            _clv(0.0103305, 0.0022162))
    assert verdict == "PROMOTED", verdict
    assert by == "clv", "Top-1 did not carry this one and must not claim it"


def test_the_practice_report_clears_the_bar_too():
    """`2026.09.22-add-practice-report` at gate: CLV +0.41pp at 2.19 se."""
    verdict, by = C._decide(_top1(0.0070734, 0.0082004), [],
                            _clv(0.0041, 0.00187))
    assert verdict == "PROMOTED" and by == "clv", (verdict, by)


def test_clv_is_not_a_rubber_stamp():
    """Every weather variant scored NEGATIVE CLV and stays rejected.

    A second instrument that promoted everything would not be a second
    instrument. `2026.08.20-weather-24-families` scored CLV -0.46pp at
    -1.95 se, and `2026.08.12-first-td-anytime-prior` -1.56pp at -6.26 se.
    """
    for delta, se in ((-0.0046, 0.0024), (-0.0156, 0.0025)):
        verdict, _ = C._decide(_top1(-0.001, 0.0078), [], _clv(delta, se))
        assert verdict == "REJECTED", (delta, verdict)


def test_clv_cannot_promote_a_candidate_that_wrecks_top_1():
    """CLOSING-LINE VALUE BOUGHT WITH THE BOARD'S OWN ACCURACY IS NOT A WIN.

    The reader looks at Top-1; CLV is evidence the disagreement anticipates
    the market. A candidate that moves the second while losing the first has
    not earned a promotion, so the CLV route requires Top-1 to be no worse
    than its own noise band — not merely no worse than the champion, because
    Top-1 cannot resolve a tenth of a point in either direction.
    """
    strong = _clv(0.0103, 0.0022)
    verdict, _ = C._decide(_top1(-0.02, 0.0078), [], strong)
    assert verdict == "REJECTED", "a 2pp Top-1 loss must not be bought"
    # Just inside the band is still allowed: that is what "not worse" means.
    verdict, by = C._decide(_top1(-0.006, 0.0078), [], strong)
    assert verdict == "PROMOTED" and by == "clv", (verdict, by)


def test_top_1_still_promotes_on_its_own():
    """The CLV route is an addition, not a replacement."""
    verdict, by = C._decide(_top1(0.02, 0.008), [], None)
    assert verdict == "PROMOTED" and by == "top1"
    # And with no CLV measured at all, the old rule is exactly what applies.
    verdict, _ = C._decide(_top1(0.0001, 0.008), [], None)
    assert verdict == "REJECTED"


def test_a_tripped_guard_still_needs_a_justification():
    """Whichever instrument carried it, a regression is not silent."""
    verdict, by = C._decide(_top1(0.0018, 0.0078), [{"metric": "brier"}],
                            _clv(0.0103, 0.0022))
    assert verdict == "GUARD_TRIPPED" and by == "clv", (verdict, by)


def test_regate_leaves_an_untouched_market_alone():
    """An overlay that does not reach a market measured nothing there.

    Re-deciding it on CLV would turn "not scored" into a result.
    """
    rows = [{"market": "first_td", "model": "xgb", "verdict": "UNCHANGED",
             "top1": _top1(0.0, 0.0), "guards_tripped": []}]
    out = C.regate(rows, [{"market": "first_td", "model": "xgb",
                           "delta": 0.02, "se": 0.002}])
    assert out[0]["verdict"] == "UNCHANGED", out[0]


def test_regate_matches_on_the_pair_being_compared():
    """A CLV row for another model must not decide this one's verdict."""
    rows = [{"market": "anytime_td", "model": "xgb", "against": "xgb",
             "verdict": "REJECTED", "top1": _top1(0.0018, 0.0078),
             "guards_tripped": []}]
    # Right market, wrong model: no match, so Top-1's verdict stands.
    out = C.regate(rows, [{"market": "anytime_td", "model": "lgbm",
                           "against": "lgbm", "delta": 0.0103, "se": 0.0022}])
    assert out[0]["verdict"] == "REJECTED", out[0]
    assert out[0]["clv"] is None
    # The right pair flips it.
    out = C.regate(rows, [{"market": "anytime_td", "model": "xgb",
                           "against": "xgb", "delta": 0.0103, "se": 0.0022}])
    assert out[0]["verdict"] == "PROMOTED" and out[0]["decided_by"] == "clv"


def test_the_gate_reads_clv_at_all():
    """Falsifies the defect this rule was written for.

    `grep clv src/evaluation/compare.py` returned nothing: CLV was computed,
    written to the ledger, and played no part in any verdict.
    """
    import inspect

    src = inspect.getsource(C)
    assert "CLV_PROMOTION_SE" in src
    assert "clv" in inspect.getsource(C._decide)


def test_the_experiment_script_measures_clv_before_it_decides():
    """A verdict cannot be read off an instrument measured after it."""
    src = (importlib.import_module("pathlib").Path("scripts/23_experiment.py")
           .read_text())
    body = src[src.index("comparisons = C.compare_all"):]
    order = [body.index(x) for x in ("_clv_rows(", "C.regate(",
                                     "_overall_verdict(")]
    assert order == sorted(order), (
        "CLV must be measured and applied before the overall verdict")


def test_the_gate_checks_that_its_guard_bands_describe_this_matrix():
    """A BAND MEASURED ON ANOTHER FEATURE SET IS NOT A BAND.

    `models/registry/noise_floor.json` was measured 2026-08-19 and recorded a
    date and a git sha and nothing about the matrix. Every AUC and Brier
    guard since — including the one that decided `add-market-movement` on
    anytime TD, AUC worse by 0.00027 against a band of 0.00024 — was read
    against bands describing a different feature set. `settle-overlay`
    refused the same comparison outright, because it compares the saved runs
    and those carry the hash.
    """
    import pathlib

    src = pathlib.Path("scripts/23_experiment.py").read_text()
    assert "def _noise_is_current" in src, "the gate does not check at all"
    # Written, so the next measurement can be checked.
    i = src.index("floor = C.noise_floor(results)")
    assert "feature_hash" in src[i:i + 900], (
        "the noise floor must record the matrix it was measured on")
    # And read, before the verdict is printed.
    j = src.index("noise = _noise_bands()")
    assert "_noise_is_current" in src[j:j + 700], (
        "the check must run where the gate reads the bands")


def test_the_settle_measures_the_instrument_the_gate_promotes_on():
    """THE TWO INSTRUMENTS HAVE TO MEET SOMEWHERE.

    The gate measures CLV but reads Top-1 at one seed. `settle-overlay`
    averaged Top-1 across seeds and measured no CLV at all. So the strongest
    CLV on record — both families on anytime TD, +1.22pp at 5.35 se — was
    rejected by a gate on a Top-1 of -0.62pp that the settle then showed was
    -0.12pp once the seed was averaged out. Neither command could reach the
    right verdict alone.
    """
    import pathlib

    src = pathlib.Path("scripts/23_experiment.py").read_text()
    assert "def _settle_clv" in src, "the settle still measures no CLV"
    i = src.index("def cmd_settle_overlay")
    body = src[i:i + 4000]
    assert "_settle_clv(" in body, "the settle does not call it"
    assert '"clv": clv_rows' in body, (
        "the settle's CLV must reach the ledger, or it cannot be read back")
    # Per seed, because the settle's question is whether a result HOLDS.
    j = src.index("def _settle_clv")
    assert "seeds_ahead" in src[j:j + 3000], (
        "a mean across seeds without the count is the single-seed problem "
        "again, one level up")
