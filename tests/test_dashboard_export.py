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


def test_combinations_default_to_the_whole_slate():
    """Priced-only was answering "what can I bet on" under the other question.

    Four games of sixteen carry a price three weeks before a season opens, so a
    priced-only default hides three quarters of the slate from a section whose
    whole job is which players go together.
    """
    from src.export import dashboard
    state = dashboard.JS.split("const S = {", 1)[1].split("\n};", 1)[0]
    assert "priced: 'all'" in state, "combinations must open on every player"
    assert "metric: 'likely'" in state, (
        "expected value can only order slips that carry a price, so it cannot be "
        "the ranking a whole-slate table opens on"
    )


def test_expected_value_is_never_invented_for_an_unpriced_slip():
    """A blank is the absence of a quote. A number would be a claim."""
    js = _js()
    assert "ev: priced ? (mo * dec - 1) * 100 : null," in js
    assert "book: priced ? book : null," in js
    assert "dec: priced ? dec : null," in js


def test_expected_value_ranking_searches_the_two_populations_separately():
    """One blended ordering would make both halves approximate.

    The truncation that keeps the search tractable is only sound within a single
    metric: the best-value slip can be built from long-priced legs that rank
    nowhere on likelihood, so ordering one pool by a mixture would silently drop
    it. Priced slips are searched under value, the rest under likelihood.
    """
    js = _js()
    assert "rank(priced, p => p.model_only * p.dec)" in js
    assert "rank(all, p => p.ours)" in js
    assert "found.filter(r => !r.priced)" in js, (
        "the likelihood pass must not re-emit slips the value pass already ranked"
    )


def test_a_slip_is_only_as_strong_as_the_leg_nobody_priced():
    """One priced leg's "Strong call" must not become a whole slip's verdict."""
    js = _js()
    assert "const readable = r.ps.every(p => READ_ORDER.indexOf(p.read) >= 0);" in js
    assert "read: readable ?" in js


def test_the_graded_replay_is_only_quoted_over_the_rows_it_measured():
    """It settles against closing prices, so it describes priced slips only."""
    js = _js()
    rec = js.split("function comboRecord()", 1)[1].split("\n}", 1)[0]
    assert "if (c.priced !== 'yes') return null;" in rec


def test_the_named_scorers_come_from_the_market_being_built():
    """A first-TD table must not name the anytime-TD leader.

    "Most likely to score at some point" and "most likely to open the scoring"
    are different players with percentages several times apart, and the column
    sat beside `Scores first` where the confusion is hardest to catch.
    """
    src = SCRIPT.read_text()
    fn = src[src.index("def teams("):]
    fn = fn[:fn.index("\n# \u2500\u2500 One market")] if "\n# \u2500\u2500 One market" in fn else fn
    assert "ap = preds.get(target_type)" in fn, (
        "the two named scorers must come from the market being built, not from "
        "whichever one happens to supply another column"
    )
    assert "def teams(season: int, week: int, target_type: str)" in src
    assert "tm = teams(season, week, target_type)" in src


def test_the_longshot_filter_does_not_promise_an_edge_the_interval_denies():
    """The same claim `app.py` retired must not reappear on this surface.

    The band's sorting gap is measured and moves; on the 24-family model its
    95% interval covers zero. A second page still calling it an edge is exactly
    the drift that makes two surfaces disagree about one measurement.
    """
    from src.export import dashboard
    js = dashboard.JS_PLAYERS
    assert "largest gap anywhere on this board" not in js, (
        "an unconditional superlative about a measurement that changes"
    )
    assert "m.longshot.auc_gap_lo <= 0" in js, (
        "the copy must branch on whether the measured gap clears zero"
    )
    assert "not distinguishable from the price" in js


def test_the_threshold_slider_is_not_destroyed_by_its_own_drag():
    """Re-rendering on `input` removed the element the pointer was dragging.

    The drag then moved one step and died — a control that looks broken rather
    than one that is slow. The slider is built once and moving it repaints only
    what depends on it.
    """
    from src.export import dashboard
    js = dashboard.JS_PANES
    hits = js.split("function paneHits()", 1)[1]
    assert "slider.oninput = () => { cut = parseFloat(slider.value); S.cut[m.key] = cut; paintCut(); };" in hits
    assert "render(true)" not in hits, (
        "a full re-render on slider input is exactly the bug this guards"
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


def test_the_dashboard_cover_is_pinned_to_the_same_closed_forms_as_the_python():
    """Two implementations of one payout formula, checked against a third thing.

    The page lets the reader choose the legs, so no precomputed portfolio could
    cover the space and the arithmetic has to run in JavaScript. That is the one
    place this project duplicates a calculation on purpose. The protection is
    that both sides are pinned to closed forms rather than to each other:

        k scorers win 2^k - 1 slips
        at a flat price d they return (1+d)^k - 1 per unit staked

    `tests/test_cover.py` holds the Python to those. This holds the JavaScript
    to the same ones by reading them out of the shipped page, so the two cannot
    drift without one of the two tests failing.
    """
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] /
           "src" / "export" / "dashboard.py").read_text()
    fn = src[src.index("function coverPortfolio("):src.index("function paneCover(")]

    # Every non-empty subset is a slip, and a slip pays when its legs are all in.
    assert "for (let mask = 1; mask < N; mask++)" in fn, (
        "slips must enumerate masks from 1, not 0 — the empty subset is not a "
        "bet, and counting it is exactly the error that made a hand-worked "
        "table read $97.66 where the answer is $96.66")
    assert "(m & mask) === mask" in fn, (
        "a slip wins only when every one of its legs scored")

    # Correlation is a teammate effect and must be gated on the team.
    assert "legs[i].team === legs[j].team" in fn, (
        "the measured correlation is residual covariance inside a team-game; "
        "applying it across fixtures inflates the all-score tail")

    # The singles comparison has to exist, or the page cannot say what the
    # cover is being judged against.
    assert "singles_roi" in fn and "dec[i] * p[i] - 1" in fn


def test_the_shipped_dashboard_carries_the_cover_tab():
    from pathlib import Path

    page = Path(__file__).resolve().parents[1] / "site" / "dashboard.html"
    if not page.exists():
        pytest.skip("dashboard not exported in this checkout")
    html = page.read_text()
    assert "Cover the field" in html
    assert "coverPortfolio" in html, "the page must carry the calculation"
