"""Checks on prose a model wrote about numbers somebody else computed.

**`_numbers_are_sourced` VALIDATES PROVENANCE, NOT PREDICATION.** It asks where
a digit came from. It cannot ask what was claimed about it, and the difference
is not academic — the first generated game story in this project was fluent,
had every figure correctly sourced, and asserted four things that were false:

  - "a total of 47.0 when you add those numbers together", where the two
    scores it was adding sum to 40.3 and the 47.0 was a different figure
    entirely;
  - "both proxies for how the teams match up", of two directly measured rows;
  - "Pittsburgh counters with a slight edge at negative 0.14", where a
    negative edge means Pittsburgh is the WORSE side there;
  - "unders have hit more often for each side", of a team that went 5-5.

A later one invented "Tyler Wylan Wallace" from an injury report that said
Tylan Wallace: two fabricated tokens around one real surname, on a page about
money.

These are the checks that close those holes, and they live here rather than in
either caller because `game_notes` and `game_story` both need them and the
first imports from the second.

**EVERY ONE OF THEM IS NARROW ON PURPOSE.** None is a proof of truthfulness and
none pretends to be. Each closes a shape of failure that actually occurred, and
each was measured against the 103 notes of one real week before being switched
on: a guard that fires on correct work is a guard that gets deleted rather than
fixed. That audit rejected seven good notes on its first run — "ESPN Bet"
against a brief that wrote the book as "espnbet", "C.J. Stroud" cut at the
internal dot, "the Over" read as a surname — and the fixes for all seven are
in the code below, with the cases in `tests/test_prose_checks.py`.
"""
from __future__ import annotations

import re

#: Proper nouns a story may use that no brief would carry. Deliberately tiny:
#: anything longer is a list of excuses for the check not to fire.
NAME_ALLOW = {"NFL", "AFC", "NFC", "EPA", "I",
              # The two sides of a line, capitalized the way a bet is written.
              # "the Over may be favorable" names the market, not a person.
              "Over", "Under", "Yes", "No"}


#: Phrases that assert a number was worked out rather than given. Narrow on
#: purpose: each one is a failure that actually happened, not a guess at what
#: might. "when you add those numbers together" produced a total of 47.0 from
#: two scores that sum to 40.3.
_DERIVES = re.compile(
    r"\badd(?:ing|ed)?\s+(?:th(?:ose|ese|em)|the two|up)\b"
    r"|\bsum(?:med)?\s+(?:of|to|together)\b"
    r"|\bwhen you add\b|\badds? up to\b|\bcombined (?:for|to)\b", re.I)

#: A sign the brief never carries. Every magnitude in a brief is absolute and
#: every direction is a word, so "negative 0.14" is the model reintroducing a
#: sign — which is how an edge against a team became an edge for it.
_SIGNED = re.compile(r"\bnegative\s+\d|\bminus\s+\d|(?<![\w.])-\d")


#: A run of consecutive capitalized words — a name, as written. Split on
#: WHITESPACE rather than on word boundaries: "C.J. Stroud" is two tokens, and
#: a boundary-based pattern cut it at the internal dot into "C." and "J.",
#: neither of which appears in a brief that spells him correctly. Three of the
#: seven existing notes this check first rejected failed on exactly that.
_RUN = re.compile(r"[A-Z][A-Za-z'’.\-]*(?:\s+[A-Z][A-Za-z'’.\-]*)*")
_SENT = re.compile(r"(?:^|[.!?]\s+)([A-Z][A-Za-z'’.\-]*)")

#: A trailing possessive, in either apostrophe.
_POSS = re.compile(r"['’]s?$")


def _token(w: str) -> str:
    """One word, comparable on both sides of the name check.

    TWO BUGS LIVED HERE AND BOTH PASSED A CASUAL READING. `rstrip("'’s")`
    strips a CHARACTER SET, so it took the final s off any word — "Jenkins"
    became "Jenkin" and failed against a brief that spelled it correctly. And
    the brief's own tokens kept their trailing periods, so "Browns." never
    matched "Browns". Between them the check rejected every real name it was
    built to pass, which is the failure mode that gets a guard deleted rather
    than fixed.
    """
    return _POSS.sub("", w.strip(".-'’")).lower()


def _names_are_sourced(text: str, brief: str) -> bool:
    """Every proper noun in the prose must appear in the facts.

    **THE CHECK THE NUMBERS ONE DOES NOT COVER.** A real story named "Tyler
    Wylan Wallace" where the report said Tylan Wallace — two invented tokens
    around one real surname, every digit in the paragraph correctly sourced,
    and a fabricated person on a page about money. Names are facts, and
    `_numbers_are_sourced` reads digits.

    Sentence-initial capitals are skipped, because "Both defenses" says
    nothing about anybody. Everything else capitalized mid-sentence is a
    proper noun, and the brief carries every one a story may use: both team
    codes, both full names, the players, the day. `NAME_ALLOW` is the handful
    of league words no brief would carry.
    """
    have = {_token(w) for w in re.findall(r"[A-Za-z][A-Za-z'’.\-]*", brief)}
    have |= {_token(w) for w in NAME_ALLOW}
    have.discard("")
    starts = {m.group(1) for m in _SENT.finditer(text)}

    def known(bare: str) -> bool:
        # A plural or possessive of something the facts carry is the same
        # noun: "the Browns' defense" against "Cleveland Browns".
        return bool(bare) and (bare in have
                               or (bare.endswith("s") and bare[:-1] in have))

    def sourced(w: str) -> bool:
        """One written word, as a proper noun question.

        A HYPHENATED COMPOUND IS CHECKED ON ITS CAPITALIZED PARTS ONLY. The
        first story this rejected in production said "the Payton-coached
        offense" of a brief that names Sean Payton — one token, so the whole
        of it was looked up and none of it matched. This check exists to
        catch an invented PROPER NOUN; "coached" is ordinary English and
        carries no claim about anybody, so only the parts that are
        capitalized have to be sourced. "Wylan-Wallace" still fails on
        "Wylan", which is the case that matters.
        """
        if known(_token(w)):
            return True
        if "-" not in w:
            return False
        parts = [p for p in w.split("-") if p[:1].isupper()]
        return bool(parts) and all(known(_token(p)) for p in parts)

    for run in _RUN.finditer(text):
        words = run.group(0).split()
        # THE WHOLE RUN COLLAPSED, FIRST. A book the facts write as one word
        # gets written as two by anyone with an eye: "espnbet" in the brief
        # against "ESPN Bet" in the note. That was four of the seven existing
        # notes this check rejected on its first run over real work.
        if known("".join(_token(w) for w in words)):
            continue
        for w in words:
            # A SENTENCE OPENER SAYS NOTHING ABOUT ANYBODY — "Both defenses"
            # is not a claim — and a run can cross a sentence boundary, so the
            # opener is not always the run's first word: "...on the Over. If
            # you have..." is one run, and `If` sits second in it. Checked by
            # membership rather than by position for that reason.
            #
            # The cost is that a one-word invention that also opens some other
            # sentence is let through. A name of two or more tokens still
            # fails on the rest, which is how "Tyler Wylan Wallace" is caught.
            if w in starts:
                continue
            if not sourced(w):
                return False
    return True


def claims_are_safe(text: str, brief: str, *, proxies: bool = False,
                    vocab: str = "") -> str | None:
    """What is wrong with this prose, or None.

    `brief` is the facts the writer was given. `vocab` is extra wording it may
    legitimately use that the brief does not spell — the teams' full names,
    for instance, where a brief carries only their codes. `proxies` says
    whether any fact it was given was marked as a proxy measurement.
    """
    source = brief + " " + vocab
    if _DERIVES.search(text):
        return "it works a number out instead of restating one"
    if _SIGNED.search(text) and not _SIGNED.search(source):
        return "it reintroduces a sign the facts did not carry"
    if re.search(r"\bprox(?:y|ies)\b", text, re.I) and not proxies:
        return "it calls a measured figure a proxy"
    if not _names_are_sourced(text, source):
        return "it names somebody the facts do not"
    return None
