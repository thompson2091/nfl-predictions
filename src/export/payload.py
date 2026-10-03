"""What of the payload is for a page, and what was only for the build.

**A LEADING UNDERSCORE MEANS THE RENDERER MUST NOT SHIP IT.** `build` returns
one payload and four things render it, and some of what it carries is working
material: `_pastlines_full` is the whole player record, written to its own
fetched file by `52_export_v3` and popped there before rendering.

That pop was the only thing keeping it out of a page, and it only ever ran on
one of the four paths. Measured on the 1 October build, `_pastlines_full` was
inlined into `site/site.html` at 1,906 KB of a 9,660 KB page and into
`site/v2/index.html` at 1,906 KB of 7,386 — a quarter of the v2 page was a key
whose own comment says it must never reach one. Neither page has the panel that
reads it, so nothing looked wrong: the pages loaded, drew every number
correctly, and were a megabyte and a half heavier than they said they were.

So the rule is here rather than at the call site, and it is a rule about the
NAME rather than a list of keys. A list would have to be edited by whoever adds
the next working key, which is exactly the edit that did not happen this time.
"""
from __future__ import annotations


def for_page(payload: dict) -> dict:
    """The payload without its build-only keys.

    Shallow and non-mutating: the caller still holds the full dict, which is
    what writes the fetched files, and only the copy handed to `json.dumps`
    is trimmed.
    """
    return {k: v for k, v in payload.items() if not str(k).startswith("_")}


def build_only(payload: dict) -> list[str]:
    """The keys `for_page` would drop, for a build to report or a test to assert."""
    return sorted(k for k in payload if str(k).startswith("_"))
