"""The track record must read the same everywhere it appears.

The board's header and the Model performance tab both show "Top-1". They used to
compute it independently — the header pooled four walk-forward folds, the tab
scored the single held-out season — so one page said 53.4% and the other 50.0%
for the same model, under the same label, with nothing on screen saying which
described what you were looking at.

That is not a display bug. Two numbers under one label is a claim that the model
performs two ways, and whichever the reader remembers is the one they act on.

These tests read `app.py` as text rather than importing it, because importing a
Streamlit script executes the whole page. Same approach as the backtest-call
check in `tests/test_leakage.py`.

    pytest tests/test_headline_parity.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture(scope="module")
def source() -> str:
    return APP.read_text()


def test_one_accessor_defines_the_track_record(source):
    assert source.count("def headline_accuracy(") == 1, (
        "there must be exactly one function producing the track-record figure"
    )
    assert source.count("def render_headline(") == 1, (
        "and exactly one that draws it, or the two places can drift in "
        "formatting even while agreeing on the number"
    )


def test_both_places_render_through_it(source):
    """The board header and the Model performance tab, and nothing in between."""
    assert source.count("render_headline(") >= 3, (
        "expected the definition plus at least two call sites — the board's "
        "accuracy strip and the Model performance tab"
    )
    strip = source.index("def render_accuracy_strip(")
    tab = source.index("if tab2.open:")
    assert "headline_accuracy(" in source[strip:strip + 2000], (
        "the board's strip must take its number from the shared accessor"
    )
    assert "headline_accuracy(" in source[tab:], (
        "the Model performance tab must take its number from the same accessor"
    )


def test_the_tab_does_not_compute_its_own_top_1_for_the_headline(source):
    """The specific regression: a second, private calculation of the same claim.

    The tab is still free to compute a *single season* breakdown — that is a
    different question, and it is labeled as one. What it must not do is
    derive the headline track record itself.
    """
    tab = source[source.index("if tab2.open:"):]
    headline_pos = tab.index("#### Track record")
    # Everything above the "Track record" block is setup; the block itself must
    # not contain arithmetic producing a percentage.
    block = tab[headline_pos:headline_pos + 800]
    assert not re.search(r"top\d_pct\s*=", block), (
        "the headline block computes its own percentage instead of rendering "
        "the shared one"
    )
    assert "render_headline(" in block


def test_the_season_detail_is_labelled_as_a_different_question(source):
    """One season is ~285 games and carries about three points of error.

    Showing it unlabelled beside the pooled figure is how the two got read as
    contradicting each other.
    """
    tab = source[source.index("if tab2.open:"):]
    assert "in detail" in tab, (
        "the single-season block needs a heading that distinguishes it from the "
        "pooled track record"
    )
    assert "standard error" in tab, (
        "and it needs to say why it moves around more"
    )


def test_the_strip_passes_the_selected_version_through(source):
    """A preview must not show the served model's track record.

    Every call site takes the version, so switching version moves the header
    with the board rather than leaving one version's picks beside another
    version's accuracy.
    """
    # `(?<!def )` so the definition's own parameter list is not read as a call.
    call_sites = re.findall(r"(?<!def )render_accuracy_strip\((.*?)\)",
                            source, flags=re.S)
    assert call_sites, "expected the strip to be rendered somewhere"
    for args in call_sites:
        assert "selected_version" in args, (
            f"render_accuracy_strip called without a version: {args!r}"
        )


def test_selecting_the_served_version_is_not_previewing(source):
    """The sidebar defaults the selector to the served version.

    So `version` arrives non-None on an ordinary page load. Treating that as a
    preview cost two things at once: the strip quoted the manifest's metrics as
    recorded at lock time instead of the live walk-forward (53.4% against a
    re-measured 53.5%), and it set `from_version`, which the strip reads as
    "previewing" and uses to hide the bookmaker and Closer tiles. Those tiles
    vanished from the board entirely.

    Hiding them while previewing is right — backtest frames exist only for the
    served model. When the served model IS the selection, there is nothing to
    hide.
    """
    block = source[source.index("def headline_accuracy("):]
    block = block[:block.index("\ndef ")]
    assert "served_version(" in block, (
        "headline_accuracy must compare the selection against what is served, "
        "or an ordinary page load is treated as a preview")
    assert "version = None" in block, (
        "and must fall through to the live walk-forward when they match")


def test_the_market_tiles_follow_the_selected_version(source):
    """They must move with the selector, like the Top-K tiles beside them.

    Two earlier attempts worked around the same root cause instead of fixing
    it: the tiles were hidden during a preview, then shown with a "(served)"
    label. Both existed because `market_headtohead` read production's model
    directory rather than the one on screen. It re-scores the graded odds
    archive through a model directory, so it can follow the selection — there
    was never a reason for these three to sit still.
    """
    strip = source[source.index("def render_accuracy_strip("):]
    strip = strip[:strip.index("\n@st.cache_data")]

    for tile in ("vs bookmaker", "Closer — backable", "Closer — fade"):
        assert tile in strip, f"the {tile!r} tile is gone from the strip"
    assert "h2h = None" not in strip, (
        "the market tiles are being suppressed again; make them follow the "
        "version instead")
    assert "market_headtohead(tt, model, version)" in strip, (
        "the market comparison must be passed the selected version")

    fn = source[source.index("def market_headtohead("):]
    fn = fn[:fn.index("\n@st.cache_data")] if "\n@st.cache_data" in fn else fn
    assert "selected_model_dir(tt, version)" in fn, (
        "market_headtohead must resolve the selected version's model directory")
    assert "model_dir=" in fn, (
        "and must pass it down; without it the tiles score production's weights "
        "under the selected version's name")


def test_the_joint_model_comes_from_the_same_directory_as_the_weights():
    """Mixing them is a third model neither version is.

    This used to be checked as a line of `app.py`. The measurement moved to
    `src/evaluation/market_parity.py` so the exported dashboard could not carry
    a second copy of it — the invariant did not move, so the check follows it
    rather than being dropped along with the line it used to read.
    """
    src = (Path(__file__).resolve().parents[1]
           / "src" / "evaluation" / "market_parity.py").read_text()
    fn = src[src.index("def scored_against_market("):]
    fn = fn[:fn.index("\ndef ")] if "\ndef " in fn[1:] else fn
    assert 'md = model_dir or get_path("models", target_type)' in fn, (
        "one directory decides everything the comparison loads")
    for artifact in ("feature_cols.pkl", "team_td_rate.json", "td_conversion.json"):
        assert f'md / "{artifact}"' in fn, (
            f"{artifact} must be read from the same directory as the weights, "
            f"not from production's")


def test_every_top1_figure_says_which_games_it_was_measured_on():
    """One page, two windows, and until 2026-08-19 nothing saying so.

    The accuracy strip pools every retrained walk-forward fold — 1,131 games
    across 2022-2025. The purpose panel and the market comparison read the
    backtest frames, which only cover the seasons with archived prices — 849
    games across 2023-2025. They reported 49.6% and 51.6% for "Top-1" side by
    side, and the whole difference is the 2022 fold, the weakest of the four at
    45.7%.

    Neither number was wrong. Neither said what it was measured on, which is
    the defect: two figures for the same-sounding quantity are not subtractable
    and a reader has no way to know that.
    """
    from pathlib import Path

    from src.evaluation.hit_rates import top_pick_bands, topk_vs_market

    for fn in (top_pick_bands, topk_vs_market):
        out = fn("anytime_td")
        if out is None:
            pytest.skip("no backtest frames in this checkout")
        assert out.get("span"), (
            f"{fn.__name__} must report the seasons it covers, not only a "
            f"game count — a count cannot tell a reader why two figures differ")
        assert out.get("seasons")

    # Matched on a fragment rather than the whole sentence: the copy is written
    # across wrapped f-string continuations, so no long literal appears
    # contiguously in the source.
    app = (Path(__file__).resolve().parents[1] / "app.py").read_text()
    assert "different window from the accuracy" in app, (
        "the market comparison must say it sits on a narrower window than the "
        "strip above it")
    assert "backtested games" in app


def test_the_dashboard_cannot_show_two_top1s_because_it_shows_none():
    """The gap was fixed by labeling; it is now closed by construction.

    The dashboard carried the same two figures the app did — a walk-forward
    strip over 2022-2025 and a ladder over the priced seasons — and for a while
    the fix was a sentence beside each saying which games it covered. Both
    panes have since gone: `Model vs book` and `How often it is right` scored
    the model rather than the week and opened a page nobody came to read.

    So the copy is gone with them, and this guards the replacement invariant:
    if any Top-1 headline returns to the page, the window it was measured on
    has to return with it. A bare accuracy figure is exactly what produced
    49.6% and 51.6% side by side, both labeled Top-1, neither wrong.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] /
           "src" / "export" / "dashboard.py").read_text()
    if "Top-1" not in src:
        return
    assert "different window from the accuracy strip" in src, (
        "a Top-1 figure is back on the page and must say what it covers")


def test_the_strip_and_the_purpose_panel_report_the_same_top1():
    """One page, one number. This is the check that failed in the wild.

    The accuracy strip read `walkforward.json` — the model's own ranking,
    2022-2025 — while the purpose panel read the backtest frames on the
    PUBLISHED column, 2023-2025. Anytime TD publishes the blended number, so
    the strip was describing an object the board never displays, and the page
    showed 49.6% and 51.6% side by side, both labeled Top-1.

    Both now read `published_topk`, so they agree by construction rather than
    by coincidence.
    """
    from src.evaluation.hit_rates import published_topk, top_pick_bands
    from src.utils.config import production_model

    for market in ("anytime_td", "first_td"):
        strip = published_topk(market, production_model(market))
        panel = top_pick_bands(market)
        if strip is None or panel is None:
            pytest.skip(f"no backtest frames for {market}")
        assert strip["games"] == panel["games"], (
            f"{market}: strip on {strip['games']} games, panel on "
            f"{panel['games']} — same page, different denominators")
        assert strip["top1"] == pytest.approx(panel["overall_hit_rate"]), (
            f"{market}: strip {strip['top1']:.4f} vs panel "
            f"{panel['overall_hit_rate']:.4f}")


def test_a_blended_market_is_measured_on_the_column_it_publishes():
    """Measure what is on screen.

    Anytime TD's blend moves the number by up to 0.289, so scoring the
    unblended ranking answers a question nobody asked. First TD's blend leaves
    it identical to the last decimal, which is why `blended` is decided by
    effect rather than by the column being named `final`.
    """
    from src.evaluation.hit_rates import published_topk
    from src.utils.config import production_model

    anytime = published_topk("anytime_td", production_model("anytime_td"))
    first = published_topk("first_td", production_model("first_td"))
    if anytime is None or first is None:
        pytest.skip("no backtest frames")

    assert anytime["column"] == "final"
    assert anytime["blended"] is True, (
        "anytime TD blends; a strip on the unblended column describes "
        "something the board does not show")
    assert first["blended"] is False, (
        "first TD's blend does not move the number — calling it blended would "
        "narrow its window for nothing")
