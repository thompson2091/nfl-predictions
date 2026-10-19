"""The alternate ladders are archived beside the main lines and never inside them.

Every reader of the odds cache finds its file by globbing `td_props_*` and
taking the newest name, and `load_cached_odds` feeds the touchdown model's
prices that way. An alternates cache under the same prefix, written the same
day, could be the file it picks — or the file whose book quotes get archived
twice while its own are never archived at all.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingest import odds_api as oa  # noqa: E402


def test_alternates_have_their_own_names():
    assert not set(oa.ALT_MARKETS) & set(oa.DEFAULT_MARKETS)
    for m in oa.ALT_MARKETS:
        assert oa.SPEC_BY_MARKET[m].shape == "over_under"
        assert m.endswith("_alt"), "main-line readers filter on the exact name"


def test_an_alternates_cache_is_invisible_to_the_main_readers(tmp_path, monkeypatch):
    monkeypatch.setattr(oa, "CACHE_DIR", tmp_path)
    day = "2099-01-01"
    main = oa._cache_path(day)
    alt = oa._cache_path(day, oa.ALT_MARKETS)
    assert main.name.startswith("td_props_") and alt.name.startswith("alt_props_")

    for cache, market in ((main, "anytime_td"), (alt, "receptions_alt")):
        cache.write_text(json.dumps({}))
        cache.with_name(cache.stem + "_books.json").write_text(
            json.dumps([{"market": market}]))

    assert oa._prop_caches() == [main]
    assert oa.load_cached_book_quotes() == [{"market": "anytime_td"}]
    assert oa.load_book_quotes_for(oa.ALT_MARKETS, week_start=day) == [
        {"market": "receptions_alt"}]
    assert oa.load_book_quotes_for(week_start=day) == [{"market": "anytime_td"}]
