"""What the exported dashboard must not get wrong, checked without a browser.

Three failures here are silent by nature, which is why they are pinned:

  * **A payload that is valid Python and invalid JSON.** `NaN` round-trips
    through `json.dumps` happily and `JSON.parse` rejects it, so the page loads
    to a blank screen with one console error nobody sees. Missing figures
    arrive from pandas constantly.
  * **A second copy of the head-to-head measurement.** The "vs bookmaker" and
    "Closer" tiles moved into `src/evaluation/market_parity.py` so the app and
    the dashboard could not drift apart; a re-implementation in either is the
    thing this project keeps finding after the fact.
  * **A combination search that reads as exhaustive while being bounded.** The
    truncation is safe only while the candidate pool exceeds `show + legs`, and
    where it does not the page has to say so.

    pytest tests/test_dashboard_export.py -v
"""
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "34_export_dashboard.py"
APP = ROOT / "app.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("export_dashboard", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── The payload has to survive the browser ────────────────────────────────

def test_clean_removes_values_json_cannot_carry(mod):
    dirty = {"a": float("nan"), "b": [float("inf"), 1.5],
             "c": {"d": float("-inf")}, "e": "fine"}
    out = mod.clean(dirty)
    assert out == {"a": None, "b": [None, 1.5], "c": {"d": None}, "e": "fine"}
    # The point of the exercise: it must serialise with allow_nan off, which is
    # what makes it parseable by JSON.parse in the page.
    json.dumps(out, allow_nan=False)


def test_clean_converts_numpy_scalars(mod):
    np = pytest.importorskip("numpy")
    out = mod.clean({"i": np.int64(3), "f": np.float64(1.25), "b": np.bool_(True),
                     "arr": np.array([1.0, np.nan])})
    assert out == {"i": 3, "f": 1.25, "b": True, "arr": [1.0, None]}
    assert isinstance(out["i"], int) and isinstance(out["b"], bool)
    json.dumps(out, allow_nan=False)


def test_f_rejects_non_finite_and_rounds(mod):
    assert mod._f(float("nan")) is None
    assert mod._f(float("inf")) is None
    assert mod._f(None) is None
    assert mod._f("not a number") is None
    assert mod._f(0.1234567) == 0.123457


def test_american_formats_a_price_or_nothing(mod):
    assert mod._american(-132) == "-132"
    assert mod._american(475.0) == "+475"
    assert mod._american(None) is None
    assert mod._american(float("nan")) is None


# ── One implementation of the bookmaker comparison ────────────────────────

def test_head_to_head_is_not_reimplemented():
    """Both surfaces must call `market_parity`, not carry their own copy.

    The de-vigging and the joint path are the two places this project has most
    often ended up with a second, drifting version. `brier_score_loss` appearing
    outside the shared module is the tell.
    """
    app = APP.read_text()
    script = SCRIPT.read_text()
    for name, src in (("app.py", app), ("34_export_dashboard.py", script)):
        assert "brier_score_loss" not in src, (
            f"{name} is scoring the bookmaker comparison itself — call "
            f"src.evaluation.market_parity.compare instead, or the two "
            f"surfaces will quietly report different numbers for one claim"
        )
    assert "market_parity" in app and "market_parity" in script


def test_shared_module_exposes_every_tile_the_pages_draw():
    from src.evaluation import market_parity
    assert callable(market_parity.compare)
    # The de-vig target is fitted, not typed. First TD is exactly one scorer;
    # anytime TD reads the prior saved at training time.
    assert market_parity.expected_scorers("first_td") == 1.0


# ── The page's own claims about its combination search ────────────────────

def _js() -> str:
    from src.export import dashboard
    return dashboard.JS_COMBOS


def test_combination_search_is_capped_per_leg_count():
    """The cap has to shrink as slips get longer, or the browser stalls.

    C(n, legs) is the whole problem: 128 eligible players is 10.7 million
    four-leg slips. Each cap is chosen so the search stays under about a
    million combinations.
    """
    js = _js()
    assert "LEG_CAP" in js
    caps = {}
    body = js.split("LEG_CAP = {", 1)[1].split("}", 1)[0]
    for part in body.split(","):
        k, v = part.split(":")
        caps[int(k.strip())] = int(v.strip())
    assert set(caps) == {2, 3, 4}
    for legs, n in caps.items():
        assert math.comb(n, legs) < 1_500_000, (
            f"{legs} legs from {n} candidates is {math.comb(n, legs):,} "
            f"combinations — too many to search in a page"
        )
    assert caps[2] > caps[3] > caps[4]


def test_bounded_search_says_so():
    """A silent cap reads as "these are all of them"."""
    js = _js()
    assert "bounded" in js
    assert "The search was bounded here" in js


def test_expected_value_never_ranks_an_unpriced_slip():
    """There is no price to pay an unpriced leg at, so EV cannot exist for it."""
    js = _js()
    assert "const includeUnpriced = c.unpriced && !ev;" in js, (
        "the unpriced toggle must be ignored under expected-value ranking"
    )


# ── The rendered file is self-contained ───────────────────────────────────

def test_render_produces_one_file_with_no_external_requests():
    from src.export.dashboard import render
    payload = {"built": "2026-01-01T00:00:00+00:00", "markets": [
        {"key": "anytime_td", "label": "Anytime TD", "season": 2026, "week": 1,
         "served": {"version": "v", "model": "xgb"}, "model": "xgb",
         "players": [], "teams": [], "problems": [], "topk": None,
         "h2h": None, "selectivity": None, "walkforward": None,
         "rank_rates": {}, "rule": None, "tier_legend": None, "econ": None,
         "longshot": None, "combo_record": None, "conf_cuts": [2, 5],
         "min_edge": 2.0, "test_season": 2025, "measured_on": None},
    ]}
    html = render(payload)
    for scheme in ("http://", "https://"):
        # A data: URI favicon is fine; a fetched one is not — the file has to
        # open from a thumb drive with no network.
        for line in html.splitlines():
            if scheme in line and "www.w3.org" not in line:
                assert "claude" not in line  # placeholder-free
                assert "src=" not in line and "href=\"http" not in line, line
    assert "<script id=\"payload\" type=\"application/json\">" in html
    assert "JSON.parse" in html


def test_payload_cannot_close_its_own_script_tag():
    """A player named with `</script>` would end the tag and dump the rest as text."""
    from src.export.dashboard import render
    payload = {"built": "x", "markets": [
        {"key": "k", "label": "L", "season": 1, "week": 1,
         "served": {"version": None, "model": "m"}, "model": "m",
         "players": [{"player": "</script><b>x", "ours": 0.5}], "teams": [],
         "problems": [], "topk": None, "h2h": None, "selectivity": None,
         "walkforward": None, "rank_rates": {}, "rule": None,
         "tier_legend": None, "econ": None, "longshot": None,
         "combo_record": None, "conf_cuts": [2, 5], "min_edge": 2.0,
         "test_season": 2025, "measured_on": None},
    ]}
    html = render(payload)
    assert "</script><b>x" not in html
    assert "<\\/script>" in html
