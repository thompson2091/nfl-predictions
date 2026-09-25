"""Same-game correlation: the model, its fit, and the page agreeing with it."""
from __future__ import annotations

import importlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

CO = importlib.import_module("src.models.correlation")
REPO = Path(__file__).resolve().parents[1]

#: A card whose band partition is explicit, so the arithmetic is checkable by
#: hand rather than only against itself.
CARD = {"game_id": "CIN_PIT", "home": "PIT", "away": "CIN",
        "spread": -3.5, "total": 44.5,
        "bands": {"won big": 0.22, "won": 0.20, "close": 0.24,
                  "lost": 0.18, "lost big": 0.16}}

#: The shape `script_risk.fit` returns, with a swing like a real RB rushing
#: line (0.73 in a blowout loss, 1.24 in a blowout win).
FITS = {"RB|rushing_yards": {"mult": {"won big": 1.2355, "won": 1.127,
                                      "close": 1.0112, "lost": 0.8637,
                                      "lost big": 0.73}}}


def _joint(legs, strength=1.0):
    return CO.joint(legs, CARD, FITS, hist=_BANDS, strength=strength)


class _Bands:
    """Stands in for the history frame: `joint` only asks for the partition."""


_BANDS = None


@pytest.fixture(autouse=True)
def _stub_bands(monkeypatch):
    monkeypatch.setattr(CO, "band_probabilities",
                        lambda card, team, hist=None: card.get("bands"))


def test_two_opposing_backs_land_together_less_often_than_the_product():
    """THE DIRECTION IS THE WHOLE POINT.

    The record says so: over 930,346 same-game leg pairs, two running backs
    on opposite sides rushing hit together at 0.945 of the product (-5.1 se).
    One team runs the clock out while the other abandons the run.
    """
    r = _joint([{"team": "PIT", "pos": "RB", "market": "rushing_yards", "p": 0.5},
                {"team": "CIN", "pos": "RB", "market": "rushing_yards", "p": 0.5}])
    assert r["lift"] < 1.0, r
    assert r["joint"] < r["independent"]


def test_two_backs_on_the_same_side_land_together_more_often():
    """And same-team pairs lift: 1.016 over 431,300 pairs (+5.3 se)."""
    r = _joint([{"team": "PIT", "pos": "RB", "market": "rushing_yards", "p": 0.5},
                {"team": "PIT", "pos": "RB", "market": "rushing_yards", "p": 0.5}])
    assert r["lift"] > 1.0, r


def test_the_single_leg_number_never_moves():
    """CONDITIONING CHANGES THE JOINT AND NOTHING ELSE.

    Each leg is rescaled by its own expected multiplier, so summing its
    conditionals over the bands returns the board's number exactly. Without
    that the slip would quietly disagree with the board about one player.
    """
    probs = CARD["bands"]
    for p in (0.2, 0.5, 0.73):
        c = CO._conditional(p, FITS["RB|rushing_yards"]["mult"], probs)
        back = sum(probs[b] * c[b] for b in probs)
        assert back == pytest.approx(p, abs=1e-12), (p, back)


def test_a_leg_with_no_fitted_multiplier_is_carried_not_dropped():
    """An unfitted market makes that leg independent, which is honest.

    Dropping it would silently price a two-leg slip as a one-leg slip.
    """
    r = _joint([{"team": "PIT", "pos": "RB", "market": "rushing_yards", "p": 0.5},
                {"team": "PIT", "pos": "K", "market": "field_goals", "p": 0.4}])
    assert r["legs_unfitted"] == 1
    assert r["independent"] == pytest.approx(0.2)
    assert r["lift"] == pytest.approx(1.0, abs=1e-12), (
        "an unfitted leg cannot correlate with anything")


def test_a_probability_cannot_leave_its_range():
    """A heavy multiplier on a near-certain leg would otherwise exceed one."""
    c = CO._conditional(0.95, FITS["RB|rushing_yards"]["mult"], CARD["bands"])
    assert all(0.0 <= v <= 1.0 for v in c.values()), c


def test_one_leg_is_not_a_parlay():
    assert _joint([{"team": "PIT", "pos": "RB", "market": "rushing_yards",
                    "p": 0.5}]) is None


def test_the_strength_is_fitted_and_carries_its_provenance():
    """No hardcoded correction. `k` comes from the measured pair record."""
    import inspect

    src = inspect.getsource(CO.fit_strength)
    assert "measure_pairs" in src and "log" in src
    for field in ("seasons_used", "fit_date", "n"):
        assert field in src, field


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_page_and_the_model_agree(tmp_path):
    """ONE NUMBER, TWO IMPLEMENTATIONS, CHECKED.

    The slip recomputes as legs are added, so the arithmetic has to exist in
    the page as well as in Python. That is the shape of defect this project
    has been bitten by before — the touchdown shortlist disagreeing with its
    own board — so both are run on the same card and the same legs.
    """
    from src.export import site as v1
    from src.export import v3js

    # Assembled exactly as `v3.render` assembles it, or the page under test
    # is not the page that ships.
    js = "\n".join([v1.JS_CORE, v1.JS_SHARED, v1.JS_SLIPVIEW, v1.JS_WEEK,
                    v1.JS_COMBOS, v1.JS_SAVED, v1.JS_LADDER, v1.JS_MODEL,
                    v3js.js()])

    payload = {
        "brand": "Pick Six", "season": 2026, "week": 3,
        "markets": [], "yards": {}, "receptions": {}, "results": {},
        "injuries": {}, "bets": {}, "models": {}, "history": {}, "notes": {},
        "games": {"cards": [dict(CARD)], "rows": [], "public": {}, "lines": {},
                  "script_fits": FITS, "correlation": {"k": 1.0}},
    }
    legs = [{"gameId": "CIN_PIT", "team": "PIT", "pos": "RB", "key": "rush",
             "kind": "ou", "ours": 0.5},
            {"gameId": "CIN_PIT", "team": "CIN", "pos": "RB", "key": "rush",
             "kind": "ou", "ours": 0.5}]

    p = tmp_path / "payload.json"
    p.write_text(json.dumps(payload))
    j = tmp_path / "page.js"
    j.write_text(js)
    spec = tmp_path / "legs.json"
    spec.write_text(json.dumps({"gid": "CIN_PIT", "legs": legs}))

    r = subprocess.run(["node", str(REPO / "tests" / "js" / "correlation.js"),
                        str(p), str(j), str(spec)],
                       capture_output=True, text=True, cwd=str(REPO))
    assert r.returncode == 0, r.stdout + r.stderr
    from_js = json.loads(r.stdout)["lift"]
    assert from_js is not None, "the page computed nothing"

    from_py = _joint(
        [{"team": "PIT", "pos": "RB", "market": "rushing_yards", "p": 0.5},
         {"team": "CIN", "pos": "RB", "market": "rushing_yards", "p": 0.5}],
        strength=1.0)["lift"]
    assert from_js == pytest.approx(from_py, rel=1e-9), (from_js, from_py)
