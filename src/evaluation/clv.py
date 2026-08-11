"""Closing-line value: does the market move toward us after we disagree?

Every returns figure in this project is untrustworthy for the same reason —
touchdown props pay out rarely and unevenly, so a season of bets is a handful
of effective observations and the interval swamps the estimate. Waiting for
enough bets to settle that question takes years.

Closing-line value answers a nearby question with far more statistical power.
Instead of asking "did this bet win", it asks "did the price move our way
before kickoff". Every priced player contributes an observation whether or not
they scored, and the market's own movement is the judgement of everyone else's
money. If the players we rate above the opening price are systematically the
ones the market then shortens, our disagreement is finding something real. If
the line drifts the other way, we are on the wrong side of the flow and any
backtest profit was luck.

It is a proxy, not a bank statement: beating the close does not put money in
your pocket, and a book that will not take your bet at the opening price makes
it moot. But it is the only evidence available in one season rather than ten.

Needs both an "open" and a "close" snapshot per player-game — see
scripts/07_odds.py --snapshot.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from src.ingest.odds_history import HISTORY_PATH

#: Columns that already contain the closing price, and so cannot be scored
#: against it. `final` is `blend(prob_calibrated, market_prob)` and market_prob
#: is the de-vigged *closing* line, so asking whether it anticipates the close
#: is asking whether the close predicts itself. Measured, that circularity is
#: worth 4.4 points of apparent skill: the blended column scores +9.3 against
#: its null where the honest pre-blend column scores +4.9.
MARKET_CONTAMINATED = {"final", "market_prob", "prob_blended"}

#: The model's own view, before any market information enters. The team rate
#: inside it reads the game total and spread, which are market numbers, but
#: those are known at the open too — the circularity that matters is with the
#: player's own closing prop price, and this column has none of it.
CLEAN_PROB_COL = "prob_calibrated"


def line_movement(target_type: str = "anytime_td") -> pl.DataFrame | None:
    """Opening and closing price for every player-game holding both."""
    if not HISTORY_PATH.exists():
        return None
    hist = pl.read_parquet(HISTORY_PATH)
    if "snapshot" not in hist.columns:
        return None

    market = "anytime_td" if target_type == "anytime_td" else "first_td"
    hist = hist.filter(pl.col("market") == market)

    keys = ["season", "week", "game_id", "player_name_norm"]
    opens = (
        hist.filter(pl.col("snapshot") == "open")
        .sort("captured_at").unique(subset=keys, keep="first")
        .select(keys + [pl.col("implied_prob").alias("open_prob"),
                        pl.col("odds").alias("open_odds")])
    )
    closes = (
        hist.filter(pl.col("snapshot") == "close")
        .sort("captured_at").unique(subset=keys, keep="last")
        .select(keys + [pl.col("implied_prob").alias("close_prob"),
                        pl.col("odds").alias("close_odds")])
    )
    if opens.height == 0 or closes.height == 0:
        return None

    both = opens.join(closes, on=keys, how="inner")
    if both.height == 0:
        return None
    return both.with_columns(
        (pl.col("close_prob") - pl.col("open_prob")).alias("move")
    )


def measure(predictions: pl.DataFrame, target_type: str = "anytime_td",
            prob_col: str = CLEAN_PROB_COL) -> dict | None:
    """Did the market move toward the players we rated above the opening price?

    `predictions` needs season, week, game_id, player_name_norm and `prob_col`.

    The headline is the share of our disagreements the market later confirmed.
    50% is coin-flip: our opinion carries no information the market had not
    already priced by kickoff.
    """
    if prob_col in MARKET_CONTAMINATED:
        raise ValueError(
            f"'{prob_col}' is blended with the closing price, so scoring it "
            f"against closing-line movement measures the price predicting "
            f"itself. Use '{CLEAN_PROB_COL}' — the model's own view, formed "
            f"before any prop price enters."
        )

    moves = line_movement(target_type)
    if moves is None:
        return None

    # game_id already encodes season and week, so it is the whole key. Joining
    # on season/week as well looks harmless and is not: the backtest frames
    # carry no week, and a null never matches, which silently produced an empty
    # join and a "not enough data" message on 26,758 usable pairs.
    join_on = ["game_id", "player_name_norm"]
    preds = predictions.select(join_on + [prob_col]).unique(subset=join_on)
    j = moves.join(preds, on=join_on, how="inner")
    if j.height < 50:
        return None

    # Two corrections without which this measures the wrong thing.
    #
    # De-vig the opening price before asking whether we are above it. Raw
    # implied probability carries the book's margin, so we sit below it on 73%
    # of players purely by construction — that is the vig, not an opinion.
    # Against the de-vigged open it is 40%, which is a real disagreement rate.
    #
    # Drop prices that never moved. A price that closes where it opened says
    # nothing about who was right, and counting it as agreement inflated the
    # result by treating 14% of rows as free wins.
    expected = 1.0 if target_type == "first_td" else _expected_scorers()
    j = j.with_columns(
        (pl.col("open_prob") / pl.col("open_prob").sum().over("game_id") * expected)
        .alias("open_fair")
    ).filter(pl.col("move") != 0)
    if j.height < 50:
        return None

    j = j.with_columns([
        (pl.col(prob_col) > pl.col("open_fair")).alias("we_are_higher"),
        (pl.col("move") > 0).alias("market_shortened"),
    ])
    hit = (j["we_are_higher"] == j["market_shortened"]).to_numpy()
    n = len(hit)

    # Permutation null: shuffle which players we like, within game. The market
    # drifts longer overall, so a constant "we are lower" call already scores
    # 55% — the question is whether *which* players we pick beats that.
    rng = np.random.default_rng(0)
    null = []
    for _ in range(200):
        sh = j.with_columns(
            pl.col("we_are_higher").shuffle(seed=int(rng.integers(1_000_000_000)))
            .over("game_id").alias("_f")
        )
        null.append(float((sh["_f"] == sh["market_shortened"]).mean()))
    null = np.array(null)

    higher = j.filter(pl.col("we_are_higher"))
    lower = j.filter(~pl.col("we_are_higher"))
    return {
        "target_type": target_type,
        "n": n,
        "seasons": sorted(j["season"].unique().to_list()),
        "agree_pct": float(hit.mean()),
        "agree_se": float(np.sqrt(0.25 / n)),
        "null_pct": float(null.mean()),
        "null_lo": float(np.percentile(null, 2.5)),
        "null_hi": float(np.percentile(null, 97.5)),
        "edge_pts": float(hit.mean() - null.mean()) * 100,
        "we_higher_pct": float(j["we_are_higher"].mean()),
        "move_when_higher": float(higher["move"].mean()) if higher.height else None,
        "move_when_lower": float(lower["move"].mean()) if lower.height else None,
        "n_higher": higher.height,
        "n_lower": lower.height,
    }


def _expected_scorers() -> float:
    """Scorers per game from the fitted prior, for de-vigging the open."""
    import json
    from src.utils.paths import get_path
    path = get_path("models", "anytime_td") / "scorer_rate_prior.json"
    if path.exists():
        return float(json.loads(path.read_text())["mean_scorers_per_game"])
    return 4.3


def by_rank(target_type: str = "anytime_td", max_n: int = 5,
            prob_col: str = CLEAN_PROB_COL) -> list[dict] | None:
    """How the price moves on the players we rank highest, versus the field.

    The sharpest form of the closing-line-value test, because it asks for a
    dose-response rather than a single number: if our ranking carries
    information the market has not yet priced, the players we rank higher
    should hold their price better, in order. A flat profile would mean the
    aggregate result was coming from somewhere other than our ordering.

    Read the `vs_field` column, not `mean_move`. The whole board drifts longer
    between the 72-hour open and kickoff — there are five books quoting at open
    and seven at close, and the wider set changes the overround — so the
    absolute level is a property of the archive, not of anyone's opinion.
    """
    import glob

    from src.utils.paths import get_path

    moves = line_movement(target_type)
    if moves is None:
        return None
    moves = moves.filter(pl.col("move") != 0)

    frames = []
    for path in sorted(glob.glob(str(get_path("output", target_type)
                                     / "backtest_*.csv"))):
        d = pl.read_csv(path)
        if prob_col not in d.columns or "player_name" not in d.columns:
            continue
        frames.append(
            d.with_columns(
                pl.col(prob_col).rank(descending=True, method="ordinal")
                .over("game_id").alias("rank")
            ).select(["game_id", "player_name", "rank"])
        )
    if not frames:
        return None

    from src.features.odds_features import _normalize_name

    ranked = pl.concat(frames).with_columns(
        pl.col("player_name")
        .map_elements(_normalize_name, return_dtype=pl.Utf8)
        .alias("player_name_norm")
    )
    j = moves.join(
        ranked.select(["game_id", "player_name_norm", "rank"])
              .unique(subset=["game_id", "player_name_norm"]),
        on=["game_id", "player_name_norm"], how="inner",
    )
    if j.height < 100:
        return None

    field = float(j["move"].mean())
    out = []
    for n in range(1, max_n + 1):
        sub = j.filter(pl.col("rank") <= n)
        if sub.height == 0:
            continue
        out.append({
            "top_n": n,
            "n": sub.height,
            "mean_move": float(sub["move"].mean()),
            "vs_field": float(sub["move"].mean() - field),
            "pct_shortened": float((sub["move"] > 0).mean()),
        })
    out.append({
        "top_n": None, "n": j.height, "mean_move": field, "vs_field": 0.0,
        "pct_shortened": float((j["move"] > 0).mean()),
    })
    return out
