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
import re
import shutil
import subprocess
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
    """Whoever shows the comparison must call `market_parity`, not copy it.

    The de-vigging and the joint path are the two places this project has most
    often ended up with a second, drifting version. `brier_score_loss` appearing
    outside the shared module is the tell.

    The dashboard dropped the pane that drew this and then wanted two of the
    three numbers back on the cover section, so both files are on the hook
    again — which is the point: the second surface is exactly how a private
    copy of the de-vigging gets written.
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

# ── The rendered file is self-contained ───────────────────────────────────

def test_render_produces_one_file_with_no_external_requests():
    from src.export.dashboard import render
    payload = {"built": "2026-01-01T00:00:00+00:00", "markets": [
        {"key": "anytime_td", "label": "Anytime TD", "season": 2026, "week": 1,
         "served": {"version": "v", "model": "xgb"}, "model": "xgb",
         "players": [], "teams": [], "problems": [], "topk": None,
         "rule": None, "longshot": None, "combo_record": None, "min_edge": 2.0},
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
         "problems": [], "topk": None, "rule": None, "longshot": None,
         "combo_record": None, "min_edge": 2.0},
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


def test_the_page_opens_on_the_thing_being_built_not_on_its_own_report_card():
    """Tab order, and the two panes that no longer exist.

    `Model vs book` and `How often it is right` opened the page on how good the
    model is, which is a question the evaluation harness answers and gates on.
    A reader arriving at a dashboard wants this week. Removing them means the
    payload keys that fed them must go too, or the export keeps paying to
    compute a bookmaker comparison and four threshold curves nobody renders.

    The keys are checked rather than the labels: `cover` is the pane, `Parlay`
    is what the strip calls it, and the two are allowed to differ — the key is
    what the state, the tests and any saved link refer to.
    """
    from src.export import dashboard

    tabs = dashboard.JS_SHELL[dashboard.JS_SHELL.index("const TABS = ["):]
    tabs = tabs[:tabs.index("];")]
    order = re.findall(r"\['(\w+)'", tabs)
    assert order == ["cover", "players", "combos", "teams"], order
    assert "tab: 'cover'," in dashboard.JS, "the default tab must be a real tab"

    js = "".join(v for k, v in vars(dashboard).items() if k.startswith("JS"))
    for gone in ("paneModel", "paneHits", "lineChart", "divergingBars"):
        assert gone not in js, f"{gone} survives with nothing calling it"

    script = SCRIPT.read_text()
    for gone in ("selectivity", "head_to_head", "hit_curve", "tier_legend"):
        assert gone not in script, (
            f"{gone} is still computed for a pane that no longer exists")


def test_the_cover_opens_on_five_different_games():
    """The state comment said one per game; the code took the top five overall.

    On a slate where one fixture owns the top of the board that is five
    teammates, whose legs correlate — and the all-score row of the table below
    treats them as independent apart from a single measured rho, so the tail it
    shows would be optimistic on exactly the pick the page chose for you.
    """
    from src.export import dashboard

    js = dashboard.JS_TEAMS
    body = js[js.index("function coverDefault("):js.index("function coverToggle(")]
    assert "r.game || r.player" in body, (
        "a player with no game must not collide with every other such player")
    assert "if (seen[g]) continue;" in body


def test_the_picker_can_reach_a_player_outside_the_top_forty():
    """The old picker rendered `pool.slice(0, 40)` and nothing else.

    Anyone ranked 41st could not be put in a cover at all — not filtered out
    with a reason, simply absent. The grid is capped too, but the search and
    the game filter run over the whole pool before the cap.
    """
    from src.export import dashboard

    js = dashboard.JS_TEAMS
    body = js[js.index("function coverPicker("):js.index("function paneCover(")]
    assert "let rows = pool;" in body
    assert body.index("rows = rows.filter") < body.index("rows.slice(0, 60)"), (
        "the cap must come after the filters, or filtering only ever searches "
        "the top of the board")
    assert "'Showing the '" in body, "a truncated list has to say it is truncated"


def test_the_assumed_price_reads_american_the_way_the_rest_of_the_project_does():
    """The one free-text price on the page, parsed by the page.

    Every price the dashboard displays is American, so a box that took only
    decimals asked the reader to convert the number already in front of them.
    The conversion is small enough that the page does it in the browser — which
    makes it the second implementation of `bets.american_to_decimal`, so this
    runs the shipped parser under node and holds it to the Python.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available to run the page's own parser")

    from src.export import dashboard
    from src.prediction.bets import american_to_decimal

    odds = [-500, -250, -110, -105, 100, 120, 450, 1500]
    typed = [f"+{o}" if o > 0 else str(o) for o in odds]
    driver = (dashboard.JS + "\nconsole.log(JSON.stringify(" +
              json.dumps(typed) + ".map(parsePrice)));")
    out = subprocess.run([node, "-e", driver], capture_output=True, text=True,
                         check=True)
    assert json.loads(out.stdout) == pytest.approx(
        [american_to_decimal(o) for o in odds]), (
        "the page converts American odds differently from src/prediction/bets")

    # Unsigned, the two notations cannot collide: American odds never fall
    # inside ±100 and a decimal price never reaches it. Anything else is not a
    # price and must come back as nothing rather than as a number.
    driver = (dashboard.JS + "\nconsole.log(JSON.stringify(" +
              json.dumps(["850", "2.20", " -250 ", "+50", "-50", "1", "0",
                          "abc", ""]) + ".map(parsePrice)));")
    out = subprocess.run([node, "-e", driver], capture_output=True, text=True,
                         check=True)
    got = json.loads(out.stdout)
    assert got[:3] == pytest.approx([american_to_decimal(850), 2.20,
                                     american_to_decimal(-250)])
    assert got[3:] == [None] * 6, (
        "a half-typed sign, a price inside the dead band and anything "
        "unparseable must all read as no price, not as a silent default")


def test_the_stake_takes_a_dollar_amount_as_anyone_would_write_one():
    """`2.50`, `$2.50`, `1,000` — and the comma is the one that matters.

    `parseFloat` reads `$2.50` as nothing, which is a visible failure, and
    `1,000` as **one**, which is not: the table would go on showing a staked
    total a thousandfold under what was typed, with nothing on screen wrong.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available to run the page's own parser")

    from src.export import dashboard

    good = {"1": 1, "2.50": 2.5, "$2.50": 2.5, "1,000": 1000,
            "$1,250.75": 1250.75, "0.05": 0.05, ".5": 0.5}
    bad = ["0", "-5", "abc", "", "2.", "1e3", "$", "1.2.3"]
    driver = (dashboard.JS + "\nconsole.log(JSON.stringify(" +
              json.dumps(list(good) + bad) + ".map(parseMoney)));")
    out = subprocess.run([node, "-e", driver], capture_output=True, text=True,
                         check=True)
    got = json.loads(out.stdout)
    assert got[:len(good)] == pytest.approx(list(good.values()))
    assert got[len(good):] == [None] * len(bad), (
        "a stake has to be a positive amount; anything else must read as no "
        "amount rather than as a number")

    # And the amounts it produces have to be legible once they get large.
    driver = (dashboard.JS +
              "\nconsole.log(JSON.stringify([usd(38773.25), money(-31), "
              "money(239348.09)]));")
    out = subprocess.run([node, "-e", driver], capture_output=True, text=True,
                         check=True)
    assert json.loads(out.stdout) == ["$38,773.25", "-$31.00", "+$239,348.09"]


def test_a_half_typed_price_does_not_change_the_table_or_fight_the_caret():
    """`decRaw` exists so the box can hold `-` on the way to `-200`.

    Parsing into the field's own value rewrites what someone is in the middle
    of typing. Keeping the text and the price apart means the table goes on
    using the last price that meant something, and says so rather than
    silently answering a different question from the one on screen.
    """
    from src.export import dashboard

    assert "decRaw: '+100'" in dashboard.JS, (
        "the default has to be expressible in the notation the box advertises")
    pane = dashboard.JS_TEAMS
    body = pane[pane.index("function paneCover()"):]
    assert "S.cover.decRaw = v;" in body and "if (d) S.cover.dec = d;" in body, (
        "an unparseable keystroke must leave the price alone")
    assert "S.cover.stakeRaw = v;" in body and "if (x) S.cover.stake = x;" in body
    assert "is not a price" in body, "and the page must say it is being ignored"
    assert "is not an amount" in body

    # `2.` and `-` are the middles of `2.50` and `-200`. A warning box on those
    # shoves the picker down the page between keystrokes, so those two shapes
    # — and only those — are silent. `+50` is a finished thought that happens
    # to be wrong and still gets told.
    assert "const midStake = /^\\$?[0-9,]*\\.$/" in body
    assert "const midPrice = /^[+-]$/" in body


def test_the_picker_shows_the_three_numbers_only_where_three_exist():
    """Model, ours and book on a card — where there are three of them.

    An unpriced player has no book number and no blend, so `ours` IS the
    model's number; printing it twice under two labels would dress one estimate
    up as two that agree. First TD does not blend either, by measurement rather
    than by declaration, so `model only` there is the same column again.
    """
    from src.export import dashboard

    js = dashboard.JS_TEAMS
    body = js[js.index("function coverPicker("):js.index("function paneCover(")]
    assert "if (blended && r.priced && has(r.model_only))" in body, (
        "the model-only figure is only a second opinion on a blended, priced "
        "row; anywhere else it is `ours` under another name")
    assert "if (has(r.book)) det.push" in body

    pane = js[js.index("function paneCover()"):]
    assert "coverPicker(pool, m.topk && m.topk.blended, money2)" in pane, (
        "whether the market blends is measured, not assumed — the picker has "
        "to be told rather than deciding for itself")


def test_the_picker_collapses_without_taking_the_stake_with_it():
    """The section sits above the table it feeds, so its height is the cost.

    Collapsing hides the list and the filters that act on it. The stake and the
    assumed price drive the table below, so they stay — a collapsed picker that
    hid them would make the numbers underneath unadjustable.
    """
    from src.export import dashboard

    js = dashboard.JS_TEAMS
    body = js[js.index("function coverPicker("):js.index("function paneCover(")]
    collapsed = body[body.index("if (!f.open)"):]
    collapsed = collapsed[:collapsed.index("const games =")]
    assert "bar(extra)" in collapsed, "the stake fields must survive the collapse"
    assert "grid" not in collapsed


def test_one_player_is_a_selection_and_not_an_error():
    """2^1 - 1 is one slip, and the table has a 0-of-1 row and a 1-of-1 row.

    Refusing a single made the reader add a second player they did not want in
    order to see the first one's numbers. The k-of-n framing says nothing at
    n=1 though, so the box that reads it is replaced by the two figures that do
    answer a single: what the price demands and what we make it.
    """
    from src.export import dashboard

    pane = dashboard.JS_TEAMS
    pane = pane[pane.index("function paneCover()"):]
    assert "if (chosen.length < 1)" in pane, "one player must be allowed"
    assert "Pick at least one player" in pane
    assert "if (v.n === 1)" in pane and "the price needs" in pane, (
        "a single needs the break-even probability, not a k-of-n breakeven")
    assert "if (v.n > 1) kids.push" in pane, (
        "and the k-of-n box must not also render at n=1")

    # An assumed price against our own probability is not an edge, and at n=1
    # that is the entire content of the box — so it has to say so.
    assert "artefact of that" in pane

    # Singular and plural, because "1 slips on 1 players" is the tell that
    # nobody looked at the case they just enabled.
    assert "const plural = (k, one, many)" in pane


def test_the_graded_verdict_survives_the_table_being_dropped():
    """The ten-column record table is gone; what it concluded is not.

    That table was built because the section had shipped making claims nothing
    had verified. Its job was done the moment the answer was in — and it was
    ten columns of it, directly beneath the projection it qualifies. What has
    to remain is the qualification: the span, the range, and whether any pool
    size cleared zero, read off the artifact rather than typed in.
    """
    from src.export import dashboard

    js = dashboard.JS_TEAMS
    pane = js[js.index("function paneCover()"):]
    assert "cover-record" not in pane, "the record table is meant to be gone"
    assert "roi_beats_zero" in pane, (
        "profitable must be the artifact's own verdict — the interval clearing "
        "zero — and not this page re-deciding it from two numbers")
    for needed in ("rec.weeks", "rec.span", "Math.min.apply", "Math.max.apply"):
        assert needed in pane, f"{needed} is part of the surviving verdict"
    assert "no pool size had an interval clearing zero" in pane
    assert "Nothing in this section has been graded" in pane, (
        "an ungraded section still has to say so")


def test_the_cover_shows_both_halves_of_the_disagreement_and_never_the_blend():
    """`Closer — backable` and `Closer — fade`, apart, with what each one means.

    Most of the model's accuracy on big disagreements comes from rating players
    DOWN, and these markets only sell the Yes side — so the combined figure
    reads as a betting edge when most of it cannot be bet. On a page about
    backing every combination of a handful of players, that mistake compounds
    literally: a cover multiplies whatever edge each leg carries.
    """
    from src.export import dashboard

    js = dashboard.JS_TEAMS
    pane = js[js.index("function paneCover()"):]
    assert "disagree_higher_pct" in pane and "disagree_lower_pct" in pane
    assert "overall_better_pct" not in pane, (
        "the blended figure is the one that misleads here — it is not shipped "
        "to this pane and must not be reconstructed in it")
    assert "Only the backable half is a bet" in pane
    assert "veto" in pane, "the fade tile has to say it cannot be acted on"

    script = SCRIPT.read_text()
    assert '"disagree_higher_pct"' in script and '"players"' in script, (
        "the exporter ships the directional halves, not the whole comparison")


def test_the_shipped_dashboard_carries_the_cover_tab():
    from pathlib import Path

    page = Path(__file__).resolve().parents[1] / "site" / "dashboard.html"
    if not page.exists():
        pytest.skip("dashboard not exported in this checkout")
    html = page.read_text()
    assert "Cover the field" in html
    assert "coverPortfolio" in html, "the page must carry the calculation"
