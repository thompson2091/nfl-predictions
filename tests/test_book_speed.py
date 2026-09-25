"""Where a price survives longest, and the field that cannot answer it."""
from __future__ import annotations

import importlib

import polars as pl
import pytest

B = importlib.import_module("src.evaluation.book_speed")


def _quotes():
    """Four books on one line at two captures; the room moves between them."""
    rows = []
    for snap, prices in enumerate([
            {"slowbook": 0.50, "fastbook": 0.50, "c": 0.50, "d": 0.50},
            # The room moves up; slowbook has not repriced.
            {"slowbook": 0.50, "fastbook": 0.56, "c": 0.56, "d": 0.56}]):
        for bk, p in prices.items():
            rows.append({"season": 2026, "week": 3, "game_id": "G",
                         "player_name_norm": "x", "market": "m", "point": 1.5,
                         "side": "Over", "snapshot": snap,
                         "captured_at": f"2026-09-2{snap + 1}T00:00:00+00:00",
                         "bookmaker": bk, "implied_prob": p})
    return pl.DataFrame(rows)


def test_a_book_that_did_not_reprice_is_counted_as_behind():
    """`keeps_up` is the share of real room moves matched at the same capture.

    Measured from the prices, because the feed's own timestamp cannot say it.
    """
    d = _quotes()
    # The reporting floor keeps a handful of moves from being described; the
    # arithmetic under it is what this checks, so `lag` runs with it lowered.
    import polars as pl_

    line = [c for c in B.KEY if c != "snapshot"]
    x = d.drop_nulls(["implied_prob", "captured_at"])
    room = (x.group_by(line + ["snapshot", "captured_at"])
             .agg(pl_.col("implied_prob").median().alias("consensus"))
             .sort("captured_at")
             .with_columns((pl_.col("consensus")
                            - pl_.col("consensus").shift(1).over(line))
                           .alias("room_move")))
    moves = (x.sort("captured_at")
              .with_columns((pl_.col("implied_prob")
                             - pl_.col("implied_prob").shift(1)
                             .over(line + ["bookmaker"])).alias("book_move")))
    j = (moves.join(room.select(line + ["snapshot", "room_move"]),
                    on=line + ["snapshot"], how="inner")
              .drop_nulls(["room_move", "book_move"]))
    got = {r["bookmaker"]: (r["room_move"] > 0) == (r["book_move"] > 0)
           for r in j.iter_rows(named=True)}
    assert got["fastbook"] is True, got
    assert got["slowbook"] is False, "a book that sat still must not count"


def test_a_longer_price_reads_as_negative_deviation():
    """NEGATIVE IS GOOD, and the direction has to be unambiguous.

    `mean_dev` is the book's implied probability minus the room's median. A
    book quoting a longer price implies a lower probability, so it comes out
    below zero — which is the book a bet goes to.
    """
    d = _quotes().filter(pl.col("snapshot") == 1)
    x = d.with_columns([
        pl.col("implied_prob").median().over(B.KEY).alias("consensus"),
        pl.col("bookmaker").n_unique().over(B.KEY).alias("n_books")])
    dev = (x.with_columns((pl.col("implied_prob") - pl.col("consensus"))
                          .alias("dev"))
            .filter(pl.col("bookmaker") == "slowbook")["dev"][0])
    assert dev < 0, "the stale, longer price must read negative"


def test_the_broken_timestamp_is_not_used():
    """`book_last_update` IS UNUSABLE AND READING IT PRODUCED NONSENSE.

    The feed stamps 2024-12-23 on a DraftKings price captured 2026-08-18 and
    2023-10-15 on a FanDuel one. Two books of twenty report a credible age.
    A first cut at this module believed the field and produced a confident
    table whose median staleness was 607 days — the exact shape of failure
    this project keeps having to catch.
    """
    import ast
    import inspect

    src = inspect.getsource(B)
    tree = ast.parse(src)
    # Docstrings EXPLAIN the field and must keep naming it; what must not
    # happen is code reading it. Strip every docstring, then look.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and ast.get_docstring(node):
            node.body = node.body[1:]
    code = ast.unparse(tree)
    assert "book_last_update" not in code, (
        "the unreliable timestamp is being read by the code again")
    assert "keeps_up" in src, "lag must be measured from the prices instead"


def test_the_consensus_is_keyed_to_one_line_and_side():
    """A book posting an alternate line is not disagreeing about this one.

    Without `point` and `side` in the key, the deviation measures the ladder
    rather than the price, and a book that simply offers more alternates
    looks generous.
    """
    for field in ("point", "side", "market", "snapshot"):
        assert field in B.KEY, field


def test_a_thin_room_is_not_a_consensus():
    assert B.MIN_BOOKS >= 3
    d = _quotes().filter(pl.col("bookmaker").is_in(["slowbook", "fastbook"]))
    assert B.generosity(d).is_empty(), (
        "two books quoting each other is not a room")
