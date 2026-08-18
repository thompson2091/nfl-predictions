"""Trim the captured tree to the version of itself a page can hold.

app.py explains itself at length because it is a tool you sit with: every
column carries a `help=`, every claim has an expander under it arguing the
point. On a page there is no sitting with it — the reader scrolls once. So the
export keeps the numbers, the tables and the sentence each block opens with,
and drops the apparatus around them.

Three cuts, all structural rather than by length, so nothing gets clipped
mid-thought when the app's wording changes:

* expanders go, whole — they are always the long-form argument,
* the tooltips behind `help=` go, on tiles, columns and filters alike,
* a run of prose keeps its headings and its opening block; the paragraphs
  after that are the elaboration and stay in the app.

What survives is then read once more for pointers to the expanders that just
went — "open **What the labels mean** below" is worse than useless on a page
that has no such panel.

Nothing here reads the app's numbers, so a simplified page and a full one are
the same figures either way.
"""
from __future__ import annotations

import re

#: Text nodes whose body is several blocks of prose, so the lede rule applies.
#: A caption is one block however long it runs, and code is not prose at all —
#: both still get read for dangling pointers.
PROSE = ("markdown", "write")

#: Sentence boundary, near enough for the app's prose: a full stop, question
#: mark or exclamation, then a space.
SENTENCE = re.compile(r"(?<=[.!?])\s+")


def lede(text: str) -> str:
    """Headings, plus the first block of prose under them.

    Blocks are separated by a blank line, which is how app.py writes them. A
    block of nothing but `#` lines is a heading for what follows, so it does
    not count as the block that ends the lede.
    """
    kept: list[str] = []
    for block in re.split(r"\n\s*\n", str(text).strip()):
        block = block.strip()
        if not block:
            continue
        kept.append(block)
        heading = all(ln.strip().startswith("#") for ln in block.split("\n")
                      if ln.strip())
        if not heading:
            break
    return "\n\n".join(kept)


def expander_labels(nodes: list[dict]) -> set[str]:
    """Every expander in the tree, by label — the panels the page will not have."""
    found: set[str] = set()
    for node in nodes:
        if node["t"] != "group":
            continue
        if node["kind"] == "expander" and node.get("label"):
            found.add(str(node["label"]))
        found |= expander_labels(node["children"])
    return found


def scrub(text: str, labels: set[str]) -> str:
    """Take out the pointers to panels this page does not carry.

    A pointer trailing an em dash is an aside on a sentence that stands without
    it, so only the aside goes and the claim in front of it — usually the
    honest caveat the sentence was written for — survives. A pointer that is
    the whole sentence has nothing to keep, so the sentence goes with it.
    """
    if not labels:
        return text
    out = []
    for sentence in SENTENCE.split(text):
        hit = next((l for l in labels if l in sentence), None)
        if hit is None:
            out.append(sentence)
            continue
        head = sentence[:sentence.index(hit)]
        cut = max(head.rfind("\u2014"), head.rfind(" - "))
        if cut <= 0:
            continue
        kept = head[:cut].rstrip()
        out.append(kept if kept.endswith((".", "!", "?")) else kept + ".")
    return " ".join(s for s in out if s.strip())


def _columns(cols: list[dict]) -> list[dict]:
    return [dict(c, help=None) for c in cols]


def simplify(nodes: list[dict], dropped: set[str] | None = None) -> list[dict]:
    """A copy of the captured nodes with the apparatus taken out."""
    if dropped is None:
        dropped = expander_labels(nodes)
    out: list[dict] = []
    for node in nodes:
        kind = node["t"]

        if kind == "group":
            if node["kind"] == "expander":
                continue
            kids = simplify(node["children"], dropped)
            if not kids:
                # An emptied panel or column would publish as a stray border.
                continue
            out.append(dict(node, children=kids))
            continue

        if kind == "text":
            if node["kind"] != "code":
                body = node["body"]
                body = scrub(lede(body) if node["kind"] in PROSE else body, dropped)
                if not body.strip():
                    continue
                node = dict(node, body=body)
            out.append(node)
            continue

        if kind == "callout":
            out.append(dict(node, body=scrub(lede(node["body"]), dropped)))
        elif kind == "metric":
            out.append(dict(node, help=None))
        elif kind == "widget":
            out.append(dict(node, help=None))
        elif kind == "table":
            out.append(dict(node, columns=_columns(node["columns"])))
        else:
            out.append(node)

    return out
