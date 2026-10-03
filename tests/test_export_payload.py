"""Build-only payload keys, and the four renderers that must not ship them.

`_pastlines_full` is the whole player record. `52_export_v3` pops it before
rendering and writes it to its own fetched file, and that pop was the only
thing keeping it out of a page — so the three paths that do not pop it inlined
it. Measured on the 1 October 2026 build: 1,906 KB of `site/site.html`'s 9,660,
and 1,906 KB of `site/v2/index.html`'s 7,386. A quarter of the v2 page was a
key whose own comment says it must never reach one.

Nothing looked wrong, which is why these tests are here rather than a note: the
pages loaded, drew every number correctly, and were a megabyte and a half
heavier than they claimed.
"""

import json

from src.export.payload import build_only, for_page


def test_a_leading_underscore_is_not_shipped():
    p = {"games": {"cards": []}, "_pastlines_full": {"a": [1, 2, 3]}}
    out = for_page(p)
    assert "games" in out
    assert "_pastlines_full" not in out


def test_the_caller_still_holds_the_whole_payload():
    """Non-mutating: the full dict is what writes the fetched files."""
    p = {"keep": 1, "_drop": {"big": True}}
    for_page(p)
    assert "_drop" in p, "trimming the copy emptied the original"


def test_the_rule_is_the_name_rather_than_a_list():
    """A list would have to be edited by whoever adds the next working key,
    which is exactly the edit that did not happen the first time."""
    p = {"_pastlines_full": 1, "_teamlines_full": 2, "_whatever_comes_next": 3,
         "real": 4}
    assert build_only(p) == ["_pastlines_full", "_teamlines_full",
                             "_whatever_comes_next"]
    assert list(for_page(p)) == ["real"]


def _payload_with_working_keys() -> dict:
    return {
        "brand": "Pick Six", "season": 2026, "week": 4, "built": "2026-10-02",
        "games": {"cards": []},
        "_pastlines_full": {"A Player": {"anytime_td": [[2026, 1, "X", 1]]}},
        "_teamlines_full": {"GB": [[2026, 1, "X", 1, 24, 17]]},
    }


def test_every_renderer_strips_them():
    """All three serializers, not just the one that remembered to pop.

    The payload goes through `json.dumps` in `site.py`, `pwa.py` and `v3.py`.
    This asserts the shape each of them sends rather than rendering a whole
    page per test: a renderer that stopped calling `for_page` would put the
    key back into the string it builds.
    """
    import inspect

    from src.export import pwa, site, v3

    for mod in (site, pwa, v3):
        src = inspect.getsource(mod)
        assert "for_page(payload)" in src, \
            f"{mod.__name__} serializes the payload without trimming it"
        assert "json.dumps(payload" not in src, \
            f"{mod.__name__} still dumps the untrimmed payload somewhere"


def test_the_trimmed_payload_is_smaller_by_the_working_keys():
    p = _payload_with_working_keys()
    whole = len(json.dumps(p))
    shipped = len(json.dumps(for_page(p)))
    assert shipped < whole
    for k in ("_pastlines_full", "_teamlines_full"):
        assert k not in json.dumps(for_page(p))


def test_the_keys_the_build_actually_sets_are_build_only():
    """The exporter's own two, read off the script rather than assumed.

    If one of them is ever renamed without its underscore, it starts shipping
    in every page and this is the test that says so.
    """
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "scripts/47_export_site.py").read_text()
    carried = set(re.findall(r'payload\["(_[A-Za-z0-9_]+)"\]\s*=', src))
    assert carried == {"_pastlines_full", "_teamlines_full"}, carried
    # And the v3 exporter pops every one of them, so the fetched files are
    # written and nothing is left for `for_page` to catch as a backstop.
    v3src = (Path(__file__).resolve().parents[1]
             / "scripts/52_export_v3.py").read_text()
    for key in carried:
        assert f'payload.pop("{key}"' in v3src, \
            f"{key} is set by the build and never written to a file"
