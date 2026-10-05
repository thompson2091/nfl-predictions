"""How the model has actually done this season, against the price it was offered.

**AGAINST THE BOOK, NOT AGAINST ZERO.** "We said 57% and he scored" is not a
result; a coin that says 57% about favorites is right most of the time too.
Every number here is the model's score minus the de-vigged book's score on
the same rows, so the question it answers is the only one worth asking: did
knowing our number beat knowing theirs.

**FILTERED ON `book`, NEVER ON `has_market_price`.** The flag is a
predict-time artifact and a board rebuilt after the games loses it — weeks 3
and 4 of 2026 are on disk claiming 24 and 47 priced players. `book` comes
from the odds archive, which is fixed, so it is the one that still means
something about a week nobody froze. See `src.export.prediction_freeze` for
why those two weeks cannot be repaired.

**AND IT SAYS WHERE EACH WEEK CAME FROM.** A week served from a frozen board
is the board that was live; a week rebuilt is the model as it stands today
scoring a game it has already seen the result of. They are different claims
and the page prints which is which rather than pooling them silently.

**WHAT IS DELIBERATELY NOT HERE.** Weekly ROI, top-1 hit rate and position
splits. At four weeks and a few hundred graded rows those are noise with a
decimal point: a single Sunday moves top-1 by double digits, and a reader
cannot tell that from a trend. Brier and log loss use every row, which is
why they are the two that survive the sample size.
"""
from __future__ import annotations

import math

import polars as pl

#: Markets with a player board and a de-vigged book price to grade against.
MARKETS: tuple[str, ...] = ("anytime_td", "first_td")

#: Calibration bands, as probability percents. Wider at the top because the
#: board thins out there: one bucket of 40%+ says more than four empty ones.
BANDS: tuple[tuple[int, int], ...] = (
    (0, 5), (5, 10), (10, 20), (20, 30), (30, 45), (45, 100),
)

#: Below this a bucket is reported but not read as calibration evidence.
BUCKET_MIN = 25


def _brier(p: list[float], y: list[int]) -> float | None:
    if not p:
        return None
    return sum((a - b) ** 2 for a, b in zip(p, y)) / len(p)


def _log_loss(p: list[float], y: list[int]) -> float | None:
    """Clipped, because one confident miss at p=0 is otherwise infinite and
    takes the whole season's number with it."""
    if not p:
        return None
    eps = 1e-6
    tot = 0.0
    for a, b in zip(p, y):
        a = min(max(a, eps), 1 - eps)
        tot += -(math.log(a) if b else math.log(1 - a))
    return tot / len(p)


def _rows(season: int, week: int, market: str) -> pl.DataFrame:
    """One week's gradable rows: ours, theirs, and what happened."""
    from src.evaluation.week_history import week_board

    b = week_board(season, week, market)
    if b.is_empty():
        return pl.DataFrame()
    need = {"probability", "book", "scored"}
    if not need <= set(b.columns):
        return pl.DataFrame()
    return b.filter(pl.col("book").is_not_null()
                    & pl.col("scored").is_not_null()
                    & pl.col("probability").is_not_null())


def _source(season: int, week: int, market: str) -> str:
    """Whether this week's board is the one that was live or a rebuild."""
    try:
        from src.export import prediction_freeze as PF

        kept = PF.frozen(season, week, market)
        started = PF.started_games(season, week)
        if started and started <= set(kept):
            return "frozen"
        return "mixed" if kept else "rebuilt"
    except Exception:                                            # noqa: BLE001
        return "rebuilt"


def _score(d: pl.DataFrame) -> dict:
    """Ours and theirs on the same rows, and the gap between them."""
    ours = [float(x) for x in d["probability"].to_list()]
    book = [float(x) for x in d["book"].to_list()]
    y = [int(x) for x in d["scored"].to_list()]
    ob, bb = _brier(ours, y), _brier(book, y)
    ol, bl = _log_loss(ours, y), _log_loss(book, y)
    return {
        "n": len(y),
        "brier": ob, "book_brier": bb,
        # Positive is the model ahead. Brier is a LOSS, so the sign flips.
        "brier_edge": None if (ob is None or bb is None) else bb - ob,
        "log_loss": ol, "book_log_loss": bl,
        "log_loss_edge": None if (ol is None or bl is None) else bl - ol,
        # The level, which is the failure a Brier score hides: a board can be
        # well ordered and still say 12.6% where 6.3% happens.
        "said": sum(ours) / len(ours) if ours else None,
        "book_said": sum(book) / len(book) if book else None,
        "actual": sum(y) / len(y) if y else None,
    }


def _buckets(d: pl.DataFrame) -> list[dict]:
    """Said against happened, in bands, which is where a level error shows."""
    out = []
    for lo, hi in BANDS:
        s = d.filter((pl.col("probability") >= lo / 100)
                     & (pl.col("probability") < hi / 100))
        if s.is_empty():
            out.append({"lo": lo, "hi": hi, "n": 0, "said": None,
                        "actual": None, "thin": True})
            continue
        said = float(s["probability"].mean())
        actual = float(s["scored"].mean())
        out.append({"lo": lo, "hi": hi, "n": s.height, "said": said,
                    "actual": actual, "thin": s.height < BUCKET_MIN})
    return out


def _per_game(season: int, week: int, d: pl.DataFrame) -> dict:
    """Expected scorers against actual, per game.

    The one number that catches a level error a bucket chart can hide: the
    board can rank the right players and still expect six scorers in a game
    that produces four, every week, and nothing about the ordering says so.
    """
    if d.is_empty() or "game_id" not in d.columns:
        return {}
    g = d.group_by("game_id").agg([
        pl.col("probability").sum().alias("said"),
        pl.col("scored").sum().alias("actual")])
    return {"games": g.height,
            "said": float(g["said"].mean()),
            "actual": float(g["actual"].mean())}


def for_market(season: int, market: str) -> dict:
    """Every played week of this market, weekly and pooled."""
    from src.evaluation.week_history import played_weeks

    weeks, frames = [], []
    for w in played_weeks(season):
        d = _rows(season, w, market)
        if d.is_empty():
            continue
        row = {"week": w, "source": _source(season, w, market)}
        row.update(_score(d))
        row["per_game"] = _per_game(season, w, d)
        weeks.append(row)
        frames.append(d)
    if not frames:
        return {"weeks": [], "pooled": None, "buckets": [], "per_game": {}}
    allrows = pl.concat(frames, how="diagonal")
    return {
        "weeks": weeks,
        "pooled": _score(allrows),
        "buckets": _buckets(allrows),
        "per_game": _per_game(season, None, allrows),
        # Said plainly, because "pooled over four weeks" and "pooled over a
        # season" are different amounts of evidence and the number looks the
        # same either way.
        "sources": sorted({w["source"] for w in weeks}),
    }


def build(season: int) -> dict:
    """The whole scorecard, one market at a time."""
    out = {"season": season, "markets": {}, "bucket_min": BUCKET_MIN}
    for m in MARKETS:
        try:
            out["markets"][m] = for_market(season, m)
        except Exception as e:                                   # noqa: BLE001
            out["markets"][m] = {"error": str(e), "weeks": [],
                                 "pooled": None, "buckets": []}
    out["omitted"] = [
        "Weekly return on investment — at these sample sizes one Sunday "
        "moves it more than the model does.",
        "Top-1 hit rate — a single game swings it by double digits over "
        "four weeks, and a reader cannot tell that from a trend.",
        "Position splits — the same rows cut four ways, each cut too thin "
        "to mean anything on its own.",
    ]
    return out
