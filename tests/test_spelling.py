"""American spelling, in the words a reader sees and the code around them.

The board is read by Americans betting on American football. "defence" and
"favourite" are not wrong English, they are the wrong English for this
audience, and they were on the matchup tab of every game page.
"""
from __future__ import annotations

import pathlib
import re

#: British form -> the American one the project uses. Whole words only:
#: a stem rule for the -yse family turns "analysis" into "analyzis", and
#: `metre` without a boundary eats "parameter".
BRITISH = {
    "defence": "defense", "offence": "offense",
    "favour": "favor", "favourite": "favorite", "favourable": "favorable",
    "colour": "color", "behaviour": "behavior", "centre": "center",
    "analyse": "analyze", "organise": "organize", "normalise": "normalize",
    "normalisation": "normalization", "summarise": "summarize",
    "realise": "realize", "recognise": "recognize", "apologise": "apologize",
    "labelled": "labeled", "modelling": "modeling", "cancelled": "canceled",
    "signalled": "signaled", "travelled": "traveled",
    "practise": "practice", "licence": "license",
    "judgement": "judgment", "acknowledgement": "acknowledgment",
    "sceptical": "skeptical", "sceptic": "skeptic",
    "programme": "program", "catalogue": "catalog",
    "whilst": "while", "amongst": "among", "learnt": "learned",
}

#: Ours to spell. `.agents` and `design/` are vendored — someone else's
#: words — and `site/` is build output regenerated from `src/`.
ROOTS = ("src", "scripts", "tests", "docs", "deploy", "config")
EXTS = {".py", ".js", ".md", ".html", ".css", ".php", ".sh", ".yaml", ".yml"}
REPO = pathlib.Path(__file__).resolve().parents[1]


def _offenders():
    pat = re.compile(r"\b(" + "|".join(BRITISH) + r")\b", re.I)
    out = []
    for root in ROOTS:
        for f in (REPO / root).rglob("*"):
            if not f.is_file() or f.suffix not in EXTS:
                continue
            if "__pycache__" in f.parts:
                continue
            # This file lists them on purpose.
            if f.name == "test_spelling.py":
                continue
            for i, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
                for m in pat.finditer(line):
                    out.append((f.relative_to(REPO), i, m.group(0)))
    return out


def test_no_british_spelling_anywhere_we_own():
    """Falsified by one `defence` in a comment or a rendered string.

    Both are checked together on purpose. A comment that says defence beside
    a string that says defense is how the string drifts back.
    """
    bad = _offenders()
    assert not bad, "British spelling:\n" + "\n".join(
        f"  {f}:{i}  {w}  ->  {BRITISH.get(w.lower(), '?')}" for f, i, w in bad[:25])


def test_the_matchup_tab_says_offense_and_defense():
    """The one that was actually on screen, on every game page."""
    from src.export import v3js

    src = v3js.js()
    assert "' offense <i>vs</i> '" in src, "the matchup row is not American"
    assert "defence" not in src and "offence" not in src


def test_the_checker_would_catch_a_regression():
    """A guard that cannot fail is not a guard."""
    pat = re.compile(r"\b(" + "|".join(BRITISH) + r")\b", re.I)
    assert pat.search("the defence allows 4.1 yards")
    assert pat.search("Favourite")
    # And does not fire on words that merely contain one.
    assert not pat.search("a parameter of the analysis")
    assert not pat.search("defensive offensive labels centered")
