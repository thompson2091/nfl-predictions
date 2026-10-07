"""A count model must be scored on the matrix it was fitted on.

Two bugs met on the first receptions board and both produced a confident,
plausible-looking number rather than a crash.

The first was representation. Training builds its matrix with a bare
`to_numpy()`, so a null usage feature reaches XGBoost as NaN and takes the
missing-value branch the trees learned. Serving went through
`trainer.prepare_data`, which ends in `np.nan_to_num(X, nan=0.0)` because the
touchdown models want it there. A rookie with no recorded target therefore
arrived as a 91%-snap listed starter who is never thrown to, and the model
priced him at 8.52 expected receptions — above the best receiver in the league.

The second was time. Every duplicate in this project is resolved by keeping the
newest capture, and the Sunday slots cannot all be pre-kickoff at once, so
"newest" quietly meant "furthest into the fourth quarter" for the early window.

    pytest tests/test_count_serving.py -v
"""
from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from src.ingest.odds_history import LIVE_LAG_HOURS, drop_in_play
from src.models.count import design_matrix


def test_a_null_feature_stays_missing_instead_of_becoming_zero():
    """0.0 is a value. Null is the absence of one, and they are not the same.

    Falsified by replacing `to_numpy()` with a `fill_null(0)`: the NaN check
    below fails, which is the only thing standing between "no history" and
    "measured at zero".
    """
    df = pl.DataFrame({"a": [1.0, None, 3.0], "b": [None, 5.0, 6.0]})
    X = design_matrix(df, ["a", "b"])

    assert np.isnan(X[1, 0]), "a null usage feature must reach the model as NaN"
    assert np.isnan(X[0, 1])
    assert X[0, 0] == 1.0 and X[2, 1] == 6.0
    assert (X == 0.0).sum() == 0, "nothing in this frame is zero"


def test_a_feature_the_matrix_does_not_carry_is_unknown_not_zero():
    """A model asking for a column the frame lacks is asking about the unknown."""
    df = pl.DataFrame({"a": [1.0, 2.0]})
    X = design_matrix(df, ["a", "absent"])

    assert X.shape == (2, 2)
    assert np.isnan(X[:, 1]).all(), "an absent feature is null, not 0.0"


def test_column_order_follows_the_model_not_the_frame():
    """Feature order is part of the model. The frame's order is an accident."""
    df = pl.DataFrame({"b": [9.0], "a": [1.0]})
    assert design_matrix(df, ["a", "b"]).tolist() == [[1.0, 9.0]]


def test_zero_filling_a_no_history_row_is_what_inflated_the_count():
    """The failure end to end, on a model fitted to the same shape of data.

    Training holds three kinds of row: a player with measured usage catches
    about `0.7 * usage`, a player measured at exactly zero usage is a
    goal-line back who is fed anyway and catches about 8, and a player with no
    history at all catches about 1.2. Those last two are the ones that matter,
    because zero-filling a null turns the third into the second.

    The assertion is deliberately directional rather than a point estimate.
    XGBoost does not give a missing value its own leaf — it learns which way to
    send it at each split — so a NaN row lands somewhere between the
    populations it could belong to, near the global mean here. What it must not
    do is land in the zero pocket, and 0.0 puts it there by construction.

    Falsified by pointing the serving call back at `nan_to_num`: `as_trained`
    then equals `as_zero_filled` and the split below collapses. That is the
    board bug in miniature — a rookie with no recorded target scored at 8.52
    expected receptions, above the best receiver in the league.
    """
    from src.models.count import XGBCountModel

    rng = np.random.default_rng(0)
    n = 6000
    kind = rng.integers(0, 3, n)                  # 0 measured, 1 zero, 2 unknown
    usage = np.where(kind == 0, rng.uniform(1, 12, n), 0.0)
    usage = np.where(kind == 2, np.nan, usage)
    lam = np.where(kind == 0, np.clip(usage * 0.7, 0.05, None),
                   np.where(kind == 1, 8.0, 1.2))
    y = rng.poisson(np.nan_to_num(lam, nan=1.2)).astype(float)

    df = pl.DataFrame({"usage": usage, "noise": rng.normal(size=n)})
    X = design_matrix(df, ["usage", "noise"])
    m = XGBCountModel()
    m.feature_names = ["usage", "noise"]
    m.fit(X[:4500], y[:4500], X[4500:], y[4500:],
          {"n_estimators": 120, "max_depth": 4, "seed": 0})

    row = pl.DataFrame({"usage": [None], "noise": [0.0]},
                       schema={"usage": pl.Float64, "noise": pl.Float64})
    M = design_matrix(row, m.feature_names)
    as_trained = float(m.predict_mu(M)[0])
    as_zero_filled = float(m.predict_mu(np.nan_to_num(M, nan=0.0))[0])

    assert as_trained < 5.0, (
        f"told the usage is unknown, the model must not answer with the "
        f"zero-usage pocket, got {as_trained}")
    assert as_zero_filled > 5.0, (
        f"told the usage is zero, it answers with the zero-usage pocket "
        f"instead — {as_zero_filled}. This is the direction the real board "
        f"failed in, and it is why the two paths must build one matrix")


def test_a_price_quoted_after_kickoff_is_not_a_closing_price(tmp_path, monkeypatch):
    """The Ayomanor row: one book, fourth quarter, filed under `close`.

    Falsified by removing the `drop_in_play` call from any consumer — the
    in-play row is both the newest and the most extreme, so it wins the
    keep-last dedupe and then wins whatever the consumer is measuring.
    """
    import src.ingest.odds_history as oh

    sched = pl.DataFrame({
        "game_id": ["2026_01_NYJ_TEN"],
        "gameday": ["2026-09-13"],
        "gametime": ["13:00"],          # 17:00 UTC
    })
    sched.write_parquet(tmp_path / "schedules.parquet")
    monkeypatch.setattr(oh, "get_path", lambda *a: tmp_path)

    df = pl.DataFrame({
        "game_id": ["2026_01_NYJ_TEN"] * 3,
        "player_name_norm": ["elic ayomanor"] * 3,
        "odds": [-205, 235, -210],
        "book_last_update": [
            "2026-09-13T16:31:23Z",     # three hours before kickoff
            "2026-09-13T19:36:07Z",     # fourth quarter
            "2026-09-13T16:59:00Z",     # one minute before kickoff, still valid
        ],
    })
    kept = drop_in_play(df)
    assert kept["odds"].to_list() == [-205, -210], (
        "only the in-play quote should go, and the one a minute before "
        "kickoff is a price you could still have taken")
    assert kept.columns == df.columns, "the filter must not reshape the frame"


def test_a_backfill_written_months_later_is_not_in_play(tmp_path, monkeypatch):
    """The trap in the fallback, and the reason it is bounded.

    Backfilled seasons carry the August 2026 ingestion time in `captured_at`,
    which is after every 2023 kickoff. An unbounded comparison would delete the
    entire historical archive — 277,782 rows that cost real money and cannot be
    re-fetched — while reporting nothing.
    """
    import src.ingest.odds_history as oh

    pl.DataFrame({"game_id": ["2023_01_HOU_BAL"], "gameday": ["2023-09-10"],
                  "gametime": ["13:00"]}).write_parquet(tmp_path / "schedules.parquet")
    monkeypatch.setattr(oh, "get_path", lambda *a: tmp_path)

    df = pl.DataFrame({
        "game_id": ["2023_01_HOU_BAL"] * 2,
        "odds": [-150, 120],
        "captured_at": [
            "2026-08-10T21:59:29+00:00",   # a backfill, three years later
            "2023-09-10T18:30:00+00:00",   # genuinely in-play
        ],
    })
    kept = drop_in_play(df)
    assert kept["odds"].to_list() == [-150], (
        "the backfill must survive and the in-play quote must not")
    assert LIVE_LAG_HOURS < 24, (
        "the bound only separates a live capture from a backfill while it is "
        "shorter than the gap between a game and its ingestion")


def test_resolving_a_player_id_binds_to_the_frame_it_was_built_from():
    """`_resolve_player_id` is length-bound, and the app assumed it was not.

    It looks like a `pl.Expr` and its signature says so, but it materialises
    against the frame handed to it. `h.unique().with_columns(_resolve_player_id(h))`
    therefore attaches a column as long as the *original* frame to a shorter
    deduplicated one, which raised ShapeError on every single load of the
    receptions "Posted lines" table — 1,594 values onto 476 rows. `guarded`
    printed the exception where the table should have been, and because nobody
    was watching that page it stayed broken.

    Falsified by resolving before deduplicating, which is the fix: the lengths
    then agree and the assertion below has to be inverted to fail.
    """
    from src.ingest.odds_history import _resolve_player_id

    df = pl.DataFrame({
        "season": [2026, 2026, 2026],
        "player_name_norm": ["a b", "a b", "c d"],
        "player_name_raw": ["A B", "A B", "C D"],
    })
    resolved = df.with_columns(_resolve_player_id(df))
    assert resolved.height == df.height

    shorter = df.unique(subset=["player_name_norm"], keep="last")
    assert shorter.height < df.height
    with pytest.raises(Exception):
        # The shape of the bug: a mapping built over `df`, attached to `shorter`.
        shorter.with_columns(_resolve_player_id(df))


def test_a_frame_with_its_own_kickoff_needs_no_schedule_join(tmp_path,
                                                             monkeypatch):
    """THE SILENT NO-OP. A filter that matches nothing reports nothing.

    `game_lines.parquet` files its rows as `ATL_GB`; the schedule keys on
    `2026_03_ATL_GB`. So the join found no kickoff, every `_kick` came back
    null, and `drop_in_play` handed the frame straight back — measured
    2026-10-07 it dropped 0 of 41,000 2026 rows while 1,750 of them, 4.27%,
    had been quoted after kickoff.

    Nothing could have caught that from the outside: dropping nothing is
    exactly what a clean archive looks like, and the three backfilled
    seasons really do hold no in-play rows.

    So a frame carrying `commence_time` is filtered on its own row. The API
    puts the kickoff there, it cannot drift from the id format, and there is
    no join to match.
    """
    import src.ingest.odds_history as oh

    # A schedule that CANNOT match, which is the live archive's situation.
    pl.DataFrame({"game_id": ["2026_03_ATL_GB"], "gameday": ["2026-09-27"],
                  "gametime": ["13:00"]}).write_parquet(
                      tmp_path / "schedules.parquet")
    monkeypatch.setattr(oh, "get_path", lambda *a: tmp_path)

    df = pl.DataFrame({
        "game_id": ["ATL_GB"] * 3,
        "market": ["spreads"] * 3,
        "point": [-6.0, -5.5, -6.5],
        "commence_time": ["2026-09-27T17:00:00Z"] * 3,
        "book_last_update": [
            "2026-09-27T16:40:00Z",     # twenty minutes before kickoff
            "2026-09-27T19:12:00Z",     # second half
            "2026-09-27T16:59:30Z",     # thirty seconds before, still a bet
        ],
    })
    kept = drop_in_play(df)
    assert kept["point"].to_list() == [-6.0, -6.5], (
        "the in-play quote survived, which means the row's own kickoff was "
        "not used and the schedule join matched nothing")
    assert kept.columns == df.columns, "the filter must not reshape the frame"


def test_the_graded_line_is_one_somebody_could_have_taken():
    """`season_scorecard` grades against a consensus of archived quotes, so
    an in-play price in that median is a number nobody could have bet."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "src/evaluation/season_scorecard.py").read_text()
    i = src.index("def _book_lines(")
    body = src[i:src.index("\ndef ", i + 10)]
    assert "drop_in_play(gl)" in body, (
        "the book's consensus is taken over every archived quote, in-play "
        "ones included")
    assert body.index("drop_in_play(gl)") < body.index('"spreads"'), (
        "the in-play rows must go before any median is taken over them")
