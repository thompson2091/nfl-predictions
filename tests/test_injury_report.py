"""The injury report on the page: free, early, and not crying wolf."""
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "se", REPO / "scripts/47_export_site.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_a_veteran_rest_day_is_not_an_injury(mod):
    """nflverse files it in the same column, worded "Not injury related".

    Treated as a warning it puts a red tag on Christian McCaffrey every
    Wednesday, which is how a flag stops being read at all.
    """
    assert mod._reason("Not injury related - resting player") == "rest day"
    assert mod._reason("Hamstring") == "Hamstring"
    assert mod._reason(None) is None


def test_practice_participation_is_normalised_on_the_verb_not_the_spelling(mod):
    """nflverse writes "Did Not Participate In Practice" and "Full
    Participation in Practice" — different verbs AND different capitalisation,
    so matching one exact string left the other untouched."""
    assert mod._practice("Did Not Participate In Practice") == "Did not practise"
    assert mod._practice("Limited Participation in Practice") == "Limited"
    assert mod._practice("Full Participation in Practice") == "Full"
    assert mod._practice(None) is None


def test_the_report_is_read_before_designations_exist(mod):
    """The final report is filed the DAY BEFORE kickoff.

    Filtering on `report_status` alone returned eight players across sixteen
    games on a Thursday — all of them in the Thursday fixture, which is
    correct and nearly useless midweek. Practice participation is filed by
    every team days earlier and is what the designation gets derived from.
    """
    src = (REPO / "scripts/47_export_site.py").read_text()
    body = src[src.index("def _attach_injuries"):]
    body = body[:body.index("\ndef ")]
    assert 'pl.col("practice_status").is_not_null()' in body, (
        "a midweek build would show only the game being played that night")
    assert "_PRACTICE_ORDER" in src


def test_a_designation_outranks_a_practice_note(mod):
    """Out, Doubtful, Questionable, then whoever missed practice."""
    assert mod._STATUS_ORDER["Out"] < mod._STATUS_ORDER["Doubtful"]
    assert mod._STATUS_ORDER["Questionable"] < 3 + mod._PRACTICE_ORDER[
        "Did not practise"]
    assert (mod._PRACTICE_ORDER["Did not practise"]
            < mod._PRACTICE_ORDER["Limited"] < mod._PRACTICE_ORDER["Full"])


def test_the_board_flag_and_the_roster_status_are_different_questions():
    """`row.status` says whether a player is on the team; the report says
    whether he will play. A Questionable receiver is ACT on the roster and a
    coin flip in a prop, and the flag that matters for a bet is the second."""
    js = (REPO / "src/export/v3js.py").read_text()
    i = js.index("const inj = (DATA.injuries || {})[row.player];")
    block = js[i - 700:i + 900]
    assert "row.status" in block, "both are shown; they answer different things"
    assert "DATA.injuries" in block
