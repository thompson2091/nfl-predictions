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
    different question, and it is labelled as one. What it must not do is
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


def test_the_betting_tiles_are_hidden_only_for_a_real_preview(source):
    """`from_version` is the flag that hides them; it must mean 'another model'."""
    strip = source[source.index("def render_accuracy_strip("):]
    strip = strip[:strip.index("\n@st.cache_data")]
    assert 'acc.get("from_version")' in strip, (
        "the suppression must key off the previewed-version marker")
    for tile in ("vs bookmaker", "Closer — backable", "Closer — fade"):
        assert tile in strip, f"the {tile!r} tile is gone from the strip"
