"""What the model said about a past week, and what happened.

Feeds a week selector: pick an earlier week and see the board as it was rated,
with each pick marked hit or miss.

**Two things could be meant by "what we predicted", and they are not the same.**

  * What the model says NOW about week 3. Reproducible from the feature matrix
    and the current weights, and it is what this module returns.
  * What was actually published at the time. Only `data/tracked_picks.csv`
    preserves that — it records the shortlist's picks at the price they were
    recorded at and is idempotent on (season, week, market, rule, player), so a
    re-run cannot rewrite history.

The per-week CSVs in `output/` are NOT the second thing, even though they look
like it. `predict` overwrites them, and the week-1 and week-2 files were
rewritten on 2026-09-21 when the conversion changed. A week view built on them
answers "how does today's model score a past week", which is a fair question
and a different one. It is labelled as such rather than implied to be a record.

**Unplayed weeks must be excluded by the SCHEDULE, not by the label.** A week
that has not kicked off carries `target = 0` on every candidate, not null — the
candidate pool is densified — so grading against it reads as every pick losing.
Week 3 of 2026 has 812 rows and 0 scorers for exactly that reason. `_played_weeks`
in `tracked_rules` is the gate, and it asks play-by-play rather than the label.
"""
from __future__ import annotations

import polars as pl

#: How many rows a week keeps. The board is ~540 players and the tail is
#: people no book quoted at 1% — carrying all of them for every week of a
#: season would add roughly 780KB to a payload that is 1.6MB, to show rows
#: nobody scrolls to. The top of the board is the part a week view is for.
TOP_N = 100


def played_weeks(season: int) -> list[int]:
    """Weeks with play-by-play on disk, in order."""
    from src.evaluation.tracked_rules import _played_weeks

    return sorted(_played_weeks(season))


def week_board(season: int, week: int, target_type: str = "anytime_td",
               top_n: int = TOP_N) -> pl.DataFrame:
    """The top of the board for one week, with outcomes where they exist.

    `scored` is null for a week that has not been played, never 0 — the
    difference between "did not score" and "has not happened" is the whole
    reason this function exists.
    """
    from src.utils.paths import get_path

    pred = (get_path("output", target_type)
            / f"predictions_{season}_week{week}.csv")
    if not pred.exists():
        return pl.DataFrame()

    df = pl.read_csv(pred)
    keep = [c for c in ("game_id", "player_name", "team", "probability",
                        "prob_model", "rank", "has_market_price")
            if c in df.columns]
    df = df.select(keep).sort("probability", descending=True).head(top_n)

    if week not in set(played_weeks(season)):
        return df.with_columns(pl.lit(None, dtype=pl.Int8).alias("scored"))

    feats = (pl.scan_parquet(get_path("processed", target_type) / "features.parquet")
             .filter((pl.col("season") == season) & (pl.col("week") == week))
             .select(["player_name", "team", "target"])
             .collect()
             .unique(subset=["player_name", "team"], keep="last"))
    before = df.height
    out = df.join(feats, on=["player_name", "team"], how="left")
    assert out.height == before, (
        f"week board join fanned out: {before} -> {out.height}")
    return out.with_columns(
        pl.col("target").cast(pl.Int8).alias("scored")).drop("target")


def payload(season: int, target_type: str = "anytime_td",
            top_n: int = TOP_N) -> dict:
    """Every played week, keyed by week number, for a week selector.

    Returns `{"weeks": {...}, "played": [...]}`. The current week is NOT here —
    the board already carries it in full, and duplicating it would put two
    copies of the same numbers on one page with nothing keeping them equal.
    """
    weeks, hits = {}, {}
    for w in played_weeks(season):
        b = week_board(season, w, target_type, top_n)
        if b.is_empty():
            continue
        rows = b.to_dicts()
        weeks[str(w)] = rows
        graded = [r for r in rows if r.get("scored") is not None]
        if graded:
            hits[str(w)] = {
                "n": len(graded),
                "hit": int(sum(r["scored"] for r in graded)),
                # What the model expected of exactly these rows. Printed beside
                # the hit count because "34 of 100" means nothing without it.
                "expected": round(sum(r["probability"] for r in graded), 1),
            }
    return {"weeks": weeks, "played": sorted(int(k) for k in weeks),
            "accuracy": hits, "top_n": top_n}
