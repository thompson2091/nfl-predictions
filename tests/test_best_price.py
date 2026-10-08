"""The best price has to be a price you could take, not a price with a label.

THE BUG. On 2026-10-07 the live board drew a Best price SHORTER than its own
posted price on 199 of 571 priced rows — 35%. Jahmyr Gibbs's first touchdown
read "+300" as the price and "+270 at fanatics" as the best available, which is
not a thing that can be true.

Two populations, not a sort order. The posted price is the live cache's
consensus median; the best price came from the per-book archive filtered to
`snapshot == "close"`. A week still being PLAYED has no close, and week 5's
only rows under that word were a single 10-book Monday capture taken three
days before its own 13-book open:

    close   fanatics        +270    1 book    Monday
    open    williamhill_us  +305   10 books   Wednesday
    posted  (live cache)    +300

"The price you can actually take" is the newest quote on offer. It is never a
label, and on a live week the label it was asking for does not exist.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import polars as pl
import pytest

from src.evaluation import line_shopping
from src.ingest import odds_history

#: The archive's own column types. An all-null column in a fixture infers as
#: Null and the reader refuses it, which fails as a schema error rather than as
#: the thing under test. Same reason as `test_reproducible_build.SCHEMA`.
SCHEMA = {
    "captured_at": pl.String, "snapshot": pl.String, "season": pl.Int64,
    "week": pl.Int64, "game_id": pl.String, "bookmaker": pl.String,
    "book_last_update": pl.String, "player_name_raw": pl.String,
    "player_name_norm": pl.String, "market": pl.String, "regions": pl.String,
    "point": pl.Float64, "side": pl.String, "odds": pl.Int64,
    "implied_prob": pl.Float64,
}


def _books(rows, tmp_path, monkeypatch):
    """`(book, odds, snapshot, captured_at)` quotes for one player, archived.

    `game_id` is already resolved so `resolve_game_ids` leaves every row alone
    and the snapshot under test is the one the fixture wrote.
    """
    df = pl.DataFrame([
        {"captured_at": at, "snapshot": snap,
         "season": 2026, "week": 5, "game_id": "2026_05_DET_ARI",
         "player_name_raw": "A Man", "player_name_norm": "a man",
         "market": "first_td", "side": "yes", "point": None,
         "bookmaker": b, "odds": o, "implied_prob": None,
         # Null so `drop_in_play` has nothing to act on. What it drops is its
         # own subject and has its own tests.
         "book_last_update": None, "regions": "us"}
        for b, o, snap, at in rows], schema=SCHEMA)
    p = tmp_path / "books.parquet"
    df.write_parquet(p)
    monkeypatch.setattr(odds_history, "BOOKS_PATH", p)
    return p


def test_pooling_every_snapshot_never_returns_a_worse_best(tmp_path,
                                                           monkeypatch):
    """THE BUG, as a fixture. The long price is in the open; the close is thin.

    +305 and +270 are the real numbers off week 5, and `snapshot="close"`
    returning the shorter of the two is what the board drew.
    """
    _books([("fanatics", 270, "close", "2026-10-05T23:45:00Z"),
            ("williamhill_us", 305, "open", "2026-10-07T16:00:00Z"),
            ("courtside", 290, "open", "2026-10-07T16:00:00Z")],
           tmp_path, monkeypatch)

    closed = line_shopping.best_vs_consensus(2026, 5, "first_td")
    pooled = line_shopping.best_vs_consensus(2026, 5, "first_td", snapshot=None)

    assert closed["best_odds"][0] == 270, "the close really does hold only +270"
    assert pooled["best_odds"][0] == 305, (
        "a price on offer at another book is the best price available, "
        "whichever snapshot it was captured under")
    assert pooled["best_book"][0] == "williamhill_us"
    assert pooled["n_books"][0] == 3


def test_a_book_quoting_at_both_ends_contributes_only_its_newest_price(
        tmp_path, monkeypatch):
    """Pooling must not resurrect a stale quote.

    fanatics really did post +300 on the Tuesday and +265 on the Wednesday.
    Pooling the snapshots without the dedupe would offer the +300 back, which
    is a price that no longer exists — the same class of error as the
    `n_books=24 from 13 real books` bug in `odds_history.best_prices`.
    """
    _books([("fanatics", 300, "open", "2026-10-06T16:00:00Z"),
            ("fanatics", 265, "close", "2026-10-07T16:00:00Z")],
           tmp_path, monkeypatch)

    pooled = line_shopping.best_vs_consensus(2026, 5, "first_td", snapshot=None)
    assert pooled["best_odds"][0] == 265, "the withdrawn +300 came back"
    assert pooled["n_books"][0] == 1, "one book counted twice"


def test_a_live_week_with_no_close_still_has_a_best_price(tmp_path,
                                                          monkeypatch):
    """The state every week is in until its games kick off.

    Returning None here is what made the board fall back to whatever the
    archive held under the wrong label.
    """
    _books([("williamhill_us", 305, "open", "2026-10-07T16:00:00Z"),
            ("bovada", 290, "open", "2026-10-07T16:00:00Z")],
           tmp_path, monkeypatch)

    assert line_shopping.best_vs_consensus(2026, 5, "first_td") is None
    pooled = line_shopping.best_vs_consensus(2026, 5, "first_td", snapshot=None)
    assert pooled is not None and pooled["best_odds"][0] == 305


def test_best_prices_pools_the_same_way(tmp_path, monkeypatch):
    """`odds_history.best_prices` is a second copy of this measurement, and a
    copy that drifts is worse than no copy. Same argument as
    `test_reproducible_build.test_the_other_implementation_breaks_ties_the_same_way`."""
    _books([("fanatics", 270, "close", "2026-10-05T23:45:00Z"),
            ("williamhill_us", 305, "open", "2026-10-07T16:00:00Z")],
           tmp_path, monkeypatch)

    assert odds_history.best_prices(2026, 5, "first_td")["best_odds"][0] == 270
    pooled = odds_history.best_prices(2026, 5, "first_td", snapshot=None)
    assert pooled["best_odds"][0] == 305


def test_the_site_asks_for_every_snapshot_and_not_the_close():
    """The fix is only a fix on the path the page actually reads.

    `best_vs_consensus` keeps its `"close"` default so `scripts/18_shop.py` and
    `scripts/39_shortlist.py` go on measuring what they measured. That makes
    the board's call site the whole of the change, and a call site is a thing
    that gets reverted by a merge without failing anything.
    """
    src = Path("scripts/34_export_dashboard.py").read_text()
    calls = [ln.strip() for ln in src.splitlines()
             if "best_vs_consensus(" in ln and "import" not in ln]
    assert calls, "the board no longer asks for a best price at all"
    for ln in calls:
        assert "snapshot=None" in ln, (
            f"the board is asking the archive for one snapshot: {ln}\n"
            "A live week has no close, and the posted price it is drawn "
            "beside comes from the live cache.")


#: The built bundle, if this checkout has one. Tracked rather than generated,
#: so the invariant can be read off the thing that would be deployed.
BUNDLE = Path("site/v3/index.html")


def _american_to_implied(a: float) -> float:
    return 100.0 / (a + 100.0) if a > 0 else -a / (-a + 100.0)


@pytest.mark.skipif(not BUNDLE.exists(), reason="no built bundle in the tree")
def test_no_row_in_the_built_bundle_offers_a_best_price_worse_than_posted():
    """The end-to-end invariant, asserted on the artifact that gets uploaded.

    Every unit test above can pass while the built page still violates this,
    which is exactly what happened: `best_vs_consensus` sorted correctly all
    along and the board drew 199 of 571 rows backwards anyway.

    Read off named keys rather than by position. Two earlier checks in this
    repo scanned a slab of rendered text and matched the wrong thing.
    """
    import json
    import re

    text = BUNDLE.read_text()
    checked = bad = 0
    for m in re.finditer(r'\{"at_rank":[^{}]*\}', text):
        try:
            row = json.loads(m.group(0))
        except ValueError:
            continue
        if not row.get("priced"):
            continue
        best, posted = row.get("best"), row.get("odds_num")
        if best is None or posted is None:
            continue
        # The page renders a minus sign, not a hyphen.
        best = float(str(best).replace("−", "-").replace("+", ""))
        checked += 1
        if _american_to_implied(best) > _american_to_implied(float(posted)):
            bad += 1
    if not checked:
        pytest.skip("the bundle carries no priced board rows")
    assert bad == 0, (
        f"{bad} of {checked} priced rows draw a Best price shorter than the "
        f"price posted beside it. The figure when this was found was 199 of "
        f"571. Rebuild the bundle if the fix landed after it was written.")
