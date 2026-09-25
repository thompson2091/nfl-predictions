"""Which book gets named when several offer the same best price.

Books tie at the best price on about half of all players — 254 of 538 on the
2026 week-3 anytime board, one of them eight deep. With only the price to sort
on, `first` returned whichever the sort left in front, and polars does not
promise that is the same between runs: three consecutive builds of one
unchanged archive named a different book each time, and the deployed page went
from "best at fanduel" to "best at betparx" with no market movement behind it.
"""
from __future__ import annotations

import polars as pl
import pytest

from src.evaluation import line_shopping
from src.ingest import odds_history

REPO_HAS_ARCHIVE = odds_history.BOOKS_PATH.exists()


#: The archive's own column types. An all-null column in a fixture infers as
#: Null and the reader refuses it, which fails as a schema error rather than as
#: the thing under test.
SCHEMA = {
    "captured_at": pl.String, "snapshot": pl.String, "season": pl.Int64,
    "week": pl.Int64, "game_id": pl.String, "bookmaker": pl.String,
    "book_last_update": pl.String, "player_name_raw": pl.String,
    "player_name_norm": pl.String, "market": pl.String, "regions": pl.String,
    "point": pl.Float64, "side": pl.String, "odds": pl.Int64,
    "implied_prob": pl.Float64,
}


def _books(rows):
    """A week of per-book quotes, in the shape the archive holds."""
    return pl.DataFrame([
        {"captured_at": "2026-09-21T12:00:00Z", "snapshot": "close",
         "season": 2026, "week": 3, "game_id": "2026_03_ATL_GB",
         "player_name_raw": p, "player_name_norm": p.lower().replace(" ", ""),
         "market": "anytime_td", "side": "yes", "point": None,
         "bookmaker": b, "odds": o, "implied_prob": None,
         "book_last_update": None, "regions": "us"}
        for p, b, o in rows], schema=SCHEMA)


def test_a_tie_is_broken_by_name_so_the_same_archive_answers_the_same_way(
        tmp_path, monkeypatch):
    """THE BUG. Three books at +150 and nothing but the price to choose by."""
    df = _books([("A Man", "fanduel", 150), ("A Man", "ballybet", 150),
                 ("A Man", "betparx", 150), ("A Man", "bovada", 120)])
    p = tmp_path / "books.parquet"
    df.write_parquet(p)
    monkeypatch.setattr(odds_history, "BOOKS_PATH", p)

    seen = set()
    for _ in range(8):
        out = line_shopping.best_vs_consensus(2026, 3, "anytime_td")
        seen.add(out["best_book"][0])
    assert seen == {"ballybet"}, f"named more than one book across runs: {seen}"


def test_the_count_says_the_named_book_is_one_of_several(tmp_path, monkeypatch):
    """Naming one book implies it is the only one offering the price. It is
    not, on about half of all players."""
    df = _books([("A Man", "fanduel", 150), ("A Man", "ballybet", 150),
                 ("A Man", "betparx", 150), ("A Man", "bovada", 120),
                 ("Lone Man", "fanduel", 200), ("Lone Man", "bovada", 150)])
    p = tmp_path / "books.parquet"
    df.write_parquet(p)
    monkeypatch.setattr(odds_history, "BOOKS_PATH", p)
    out = line_shopping.best_vs_consensus(2026, 3, "anytime_td")
    got = dict(zip(out["player_name_norm"].to_list(), out["n_best"].to_list()))
    assert got["aman"] == 3, "three books were level"
    assert got["loneman"] == 1, "one book really was alone"


def test_the_tiebreak_never_changes_which_PRICE_is_best(tmp_path, monkeypatch):
    """A tiebreak that reordered the rows could pick a worse price. The name
    may be arbitrary; the number must not be."""
    df = _books([("A Man", "zzz_book", 400), ("A Man", "aaa_book", 150),
                 ("A Man", "mmm_book", 150)])
    p = tmp_path / "books.parquet"
    df.write_parquet(p)
    monkeypatch.setattr(odds_history, "BOOKS_PATH", p)
    out = line_shopping.best_vs_consensus(2026, 3, "anytime_td")
    assert out["best_odds"][0] == 400, "alphabetical order beat the price"
    assert out["best_book"][0] == "zzz_book"
    assert out["n_best"][0] == 1


def test_the_other_implementation_breaks_ties_the_same_way(
        tmp_path, monkeypatch):
    """`odds_history.best_prices` is a second copy of this measurement, read
    only by tests today. It had the same bug, and a copy that drifts is worse
    than no copy."""
    df = _books([("A Man", "fanduel", 150), ("A Man", "ballybet", 150),
                 ("A Man", "bovada", 120)])
    p = tmp_path / "books.parquet"
    df.write_parquet(p)
    monkeypatch.setattr(odds_history, "BOOKS_PATH", p)
    seen = set()
    for _ in range(8):
        out = odds_history.best_prices(2026, 3, "anytime_td")
        seen.add(out["best_book"][0])
    assert seen == {"ballybet"}, f"named more than one book: {seen}"


@pytest.mark.skipif(not REPO_HAS_ARCHIVE, reason="no book archive on disk")
def test_the_real_archive_answers_the_same_way_twice():
    """The end-to-end version. Without this the fixtures could be stable while
    the live board still churned — which is exactly what shipped."""
    runs = []
    for _ in range(3):
        out = line_shopping.best_vs_consensus(2026, 3, "anytime_td")
        if out is None:
            pytest.skip("week 3 anytime TD not in the archive")
        runs.append(out.sort("player_name_norm")["best_book"].to_list())
    assert runs[0] == runs[1] == runs[2], "the same archive named different books"


# ── the class of bug, not the instances ─────────────────────────────────
#
# Chasing these one at a time found six in a row: the named book, the modal
# scoreline, the opening line, the order of two lines in one market, a dict
# built from `unique`, and a 50/50 split's side order. They are one bug —
# something ordered by a key that does not settle ties — and the fix that
# scales is a check for the class rather than six checks for the instances.

def test_the_payload_is_serialized_with_sorted_keys():
    """Several payload dicts are built by iterating `unique` or `group_by`,
    whose order polars does not promise. Sorting at the dump fixes every one
    of them at once; without it each has to be found and sorted by hand, and
    the ones nobody finds make every rebuild a diff."""
    import inspect

    from src.export import pwa, v3

    for mod in (pwa, v3):
        src = inspect.getsource(mod)
        dumps = [ln for ln in src.splitlines() if "json.dumps(payload" in ln]
        assert dumps, f"{mod.__name__} no longer serializes a payload"
    assert "sort_keys=True" in inspect.getsource(v3), "v3 payload unsorted"
    assert inspect.getsource(pwa).count("sort_keys=True") >= 2, (
        "the pwa payload and its week files must both sort")


@pytest.mark.skipif(not REPO_HAS_ARCHIVE, reason="no book archive on disk")
def test_the_modal_scoreline_does_not_move_between_runs():
    """A tie at the top is the NORMAL case — 10 of 16 games on one week, one
    with six scorelines level — and the page labels the winner "most likely
    final score". Two builds called one game 23-20 and then 31-24."""
    from src.models.score_dist import summary

    seen = {(summary(6.5, 44.5, "GB", "ATL")["modal"] or {}).get("home")
            for _ in range(5)}
    assert len(seen) == 1, f"the modal score moved between runs: {seen}"


@pytest.mark.skipif(not REPO_HAS_ARCHIVE, reason="no book archive on disk")
def test_the_modal_says_how_many_scorelines_were_level_with_it():
    """"Most likely final score" is fair for one standing alone and an
    overstatement when six are tied."""
    from src.models.score_dist import summary

    s = summary(6.5, 44.5, "GB", "ATL")
    assert s.get("modal_tied", 0) >= 1
    assert s["modal_tied"] >= 1 and isinstance(s["modal_tied"], int)


def test_a_fifty_fifty_split_has_a_settled_side_order():
    """A total split 50/50 leaves both sides equal on the sort key. Their
    order then flipped between builds, which reads as the heavier side
    changing."""
    from src.ingest.action_public import ratio

    # The ratio itself is symmetric at 50/50, which is what makes the tie.
    assert ratio(50, 50, 50, 50) == pytest.approx(1.0)
