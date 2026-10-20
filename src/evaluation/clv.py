"""Closing-line value: does the market move toward us after we disagree?

Every returns figure in this project is untrustworthy for the same reason —
touchdown props pay out rarely and unevenly, so a season of bets is a handful
of effective observations and the interval swamps the estimate. Waiting for
enough bets to settle that question takes years.

Closing-line value answers a nearby question with far more statistical power.
Instead of asking "did this bet win", it asks "did the price move our way
before kickoff". Every priced player contributes an observation whether or not
they scored, and the market's own movement is the judgment of everyone else's
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

from src.utils.paths import get_path
from src.ingest.odds_history import (HISTORY_PATH, SCHEMA, _conform,
                                     market_for_target)

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

#: Below this many scored player-games the answer is not worth printing. It is
#: a floor on the *measurement*, not on the archive: a run that scores only one
#: season still clears it easily, while a join that has silently gone wrong
#: does not, which is how the season/week key bug above was caught.
MIN_ROWS = 50


def line_movement(target_type: str = "anytime_td") -> pl.DataFrame | None:
    """Opening and closing price for every player-game holding both."""
    if not HISTORY_PATH.exists():
        return None
    hist = pl.read_parquet(HISTORY_PATH)
    if "snapshot" not in hist.columns:
        return None
    hist = _conform(hist, SCHEMA)
    # Live captures write `AWAY_HOME`; backfilled seasons hold the nflverse id.
    # Every join below is keyed on game_id, so without this the backfilled
    # seasons match and every live one is dropped without a word — which is how
    # this reported three seasons all through 2026. See `resolve_game_ids`.
    from src.ingest.odds_history import drop_in_play, resolve_game_ids
    hist = resolve_game_ids(hist)

    hist = hist.filter(pl.col("market") == market_for_target(target_type))

    # `point` joins the key so an open and a close are only ever compared at
    # the same line. Without it, a book moving a receptions line from 4.5 to
    # 3.5 would read as a huge price move rather than a different bet. Null for
    # yes/no markets, where it changes nothing.
    # `regions` joins the key for the same reason `point` does. A 7-book `us`
    # open differenced against an 11-book `us,us2` close would report the
    # change in who was quoting as though it were the market moving — and
    # manufacture closing-line value out of a top-up. Only compare an open and
    # a close drawn from the same set of books.
    keys = ["season", "week", "game_id", "player_name_norm", "point", "regions"]
    opens = (
        hist.filter(pl.col("snapshot") == "open")
        .sort("captured_at").unique(subset=keys, keep="first")
        .select(keys + [pl.col("implied_prob").alias("open_prob"),
                        pl.col("odds").alias("open_odds")])
    )
    closes = (
        # An in-play close is not a close. Leaving it in credits the model with
        # movement the game itself caused, which is the opposite of what CLV
        # claims to measure. See `odds_history.drop_in_play`.
        drop_in_play(hist.filter(pl.col("snapshot") == "close"))
        .sort("captured_at").unique(subset=keys, keep="last")
        .select(keys + [pl.col("implied_prob").alias("close_prob"),
                        pl.col("odds").alias("close_odds")])
    )
    if opens.height == 0 or closes.height == 0:
        return None

    # `nulls_equal` because `point` is null for every yes/no market, and a
    # polars join drops null keys by default — which silently returned zero
    # rows for anytime and first TD the moment `point` entered the key.
    both = opens.join(closes, on=keys, how="inner", nulls_equal=True)
    if both.height == 0:
        return None

    # One row per player-game per line, not per region set. A `us` pair and a
    # `us,us2` pair for the same player-game are the same event seen through
    # different books, not two observations: keeping both fans the CLV join out,
    # counts every player-game twice in the headline, and shrinks the standard
    # error on evidence that was never independent.
    #
    # The widest set wins, because it is the one with the most books behind both
    # ends. Ranking on the region count keeps that deterministic rather than
    # alphabetical, which would prefer "us" over "us,us2".
    both = (both
            .with_columns(pl.col("regions").str.count_matches(",").alias("_n_reg"))
            .sort(["_n_reg", "regions"], descending=[True, False])
            .unique(subset=[k for k in keys if k != "regions"], keep="first")
            .drop("_n_reg"))

    return both.with_columns(
        (pl.col("close_prob") - pl.col("open_prob")).alias("move")
    )


def hit_rows(predictions: pl.DataFrame, target_type: str = "anytime_td",
             prob_col: str = CLEAN_PROB_COL) -> pl.DataFrame | None:
    """One row per scored player-game: did we call the line's direction?

    Split out of `measure` so two runs can be *paired* on it. A pooled
    agreement rate compares two numbers; pairing compares the same player-games
    scored twice, which is the same reason `paired_top_k` exists and the
    difference between "these two rates differ" and "this change is an
    improvement". Every caller that only wants the headline should keep using
    `measure`.
    """
    moves = line_movement(target_type)
    if moves is None:
        return None

    # game_id already encodes season and week, so it is the whole key. Joining
    # on season/week as well looks harmless and is not: the backtest frames
    # carry no week, and a null never matches, which silently produced an empty
    # join and a "not enough data" message on 26,758 usable pairs.
    join_on = ["game_id", "player_name_norm"]

    # Deduplicate deterministically, and prefer the walk-forward value.
    #
    # A player-game can carry two different probabilities: one from a published
    # weekly prediction file and one from the backtest frame for the same
    # season. 367 keys do on anytime TD, 48 on first TD. `unique(keep="any")`
    # resolved those arbitrarily, so the headline agreement rate moved between
    # runs on identical inputs — measured at 58.25% and 58.33% on consecutive
    # runs, which is small but fatal for a metric meant to gate promotions.
    #
    # `_src_rank` (set by the caller, 0 = backtest) breaks the tie toward the
    # walk-forward probability, which is the one trained only on earlier
    # seasons and therefore the honest out-of-sample view of a historical week.
    # Sorting on the probability as the final key makes the result reproducible
    # even when no caller supplies a rank.
    rank = "_src_rank" if "_src_rank" in predictions.columns else None
    cols = join_on + [prob_col] + ([rank] if rank else [])
    preds = (predictions.select(cols)
             .sort(by=join_on + ([rank] if rank else []) + [prob_col])
             .unique(subset=join_on, keep="first")
             .select(join_on + [prob_col]))
    j = moves.join(preds, on=join_on, how="inner")
    if j.height < MIN_ROWS:
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
    if j.height < MIN_ROWS:
        return None

    # Sorted on the way out, and not for tidiness. A polars join does not
    # promise row order, so `j` came back ordered differently between runs on
    # identical inputs. Nothing downstream cared until the permutation null,
    # which shuffles `we_are_higher` within each game from a fixed seed — a
    # fixed seed applied to a different starting order is a different shuffle,
    # so the null drifted by ~0.04pp per run and took `edge_pts` with it. A
    # deterministic order makes the whole measurement reproducible, which is
    # the bar for something that gates promotions.
    return j.with_columns([
        (pl.col(prob_col) > pl.col("open_fair")).alias("we_are_higher"),
        (pl.col("move") > 0).alias("market_shortened"),
    ]).with_columns(
        (pl.col("we_are_higher") == pl.col("market_shortened")).alias("hit")
    ).sort(["game_id", "player_name_norm"])


#: How far we sat from the de-vigged opening price, in points, as bucket edges.
#: The last one is open-ended. Chosen to match how the board is read rather
#: than to balance the buckets: 2 points is the betting threshold, 5 is a
#: "Leans", and past 10 is where "Strong call" lives.
EDGE_BUCKETS = (0.0, 2.0, 5.0, 10.0)


def by_edge(rows: pl.DataFrame, prob_col: str = CLEAN_PROB_COL) -> list[dict]:
    """Which way the line went, by how far we were from it and on which side.

    The headline agreement rate is one number over every disagreement, which is
    the right number for gating a promotion and the wrong one for reading a
    pick: it cannot say whether a 12-point disagreement anticipates more
    movement than a 3-point one, and it pools the side you can bet with the
    side you cannot. This splits both ways.

    `moved_our_way` is the share of rows where the close went the direction we
    said. `mean_move_pp` is signed *toward us*, so a positive number means the
    market came our way on average and a negative one means it walked off.

    Read the `higher` rows before backing anything: they are the only side
    these markets sell, and the whole reason this table exists is that the
    pooled number is carried by the other one.
    """
    if rows is None or rows.height == 0:
        return []
    edges = list(EDGE_BUCKETS)
    gap = ((pl.col(prob_col) - pl.col("open_fair")).abs() * 100).alias("_gap")
    # Signed toward whichever side we took, so the two halves are comparable.
    toward = pl.when(pl.col("we_are_higher")).then(pl.col("move")) \
               .otherwise(-pl.col("move"))
    j = rows.with_columns([gap, (toward * 100).alias("_toward")])
    out = []
    for side, higher in (("higher", True), ("lower", False)):
        part = j.filter(pl.col("we_are_higher") == higher)
        for i, lo in enumerate(edges):
            hi = edges[i + 1] if i + 1 < len(edges) else None
            band = part.filter(pl.col("_gap") >= lo)
            if hi is not None:
                band = band.filter(pl.col("_gap") < hi)
            if band.height == 0:
                continue
            out.append({
                "side": side, "lo": float(lo),
                "hi": None if hi is None else float(hi),
                "n": int(band.height),
                "moved_our_way": float(band["hit"].mean()),
                "mean_move_pp": float(band["_toward"].mean()),
                "median_move_pp": float(band["_toward"].median()),
            })
    return out


def _prefer_frozen(rows: list[pl.DataFrame], target_type: str
                   ) -> list[pl.DataFrame]:
    """Swap each frozen game's rows in for the weekly CSV's.

    The CSV is rewritten by every later run, so for a played week it holds a
    board rebuilt after the games, by whatever model is served now — on
    2026-10-19, weeks 1-4 differed from the frozen pre-kickoff board by 1.0-2.4
    points on average, on 1,445 of 2,145 rows. Closing-line value asks what we
    said BEFORE the line moved, which is what the freeze kept
    (`src.export.prediction_freeze`). A game the freeze does not hold keeps the
    CSV's rows, which is the best there is for it.
    """
    try:
        from src.export import prediction_freeze as PF
    except Exception:                                            # noqa: BLE001
        return rows
    out = []
    for d in rows:
        if d.height == 0 or "game_id" not in d.columns:
            out.append(d)
            continue
        season, week = int(d["season"][0]), int(d["week"][0])
        kept = PF.frozen(season, week, target_type)
        got = [dict(r, game_id=gid) for gid, rs in kept.items() for r in rs
               if r.get("prob_model") is not None or r.get("probability") is not None]
        if not got:
            out.append(d)
            continue
        f = (pl.DataFrame(got, infer_schema_length=None)
             .with_columns(pl.coalesce([c for c in ("prob_model", "probability")
                                        if c in {k for r in got for k in r}])
                           .cast(pl.Float64).alias("prob_calibrated"))
             .select([c for c in ("game_id", "player_name", "player_id", "team",
                                  "prob_calibrated") if c in {k for r in got for k in r} | {"prob_calibrated"}])
             .with_columns([pl.lit(season).alias("season"), pl.lit(week).alias("week"),
                            pl.lit(1).alias("_src_rank"), pl.lit(True).alias("frozen")]))
        out.append(d.filter(~pl.col("game_id").is_in(list(kept))))
        out.append(f)
    return out


def published_predictions(target_type: str) -> pl.DataFrame | None:
    """Every published prediction and backtest frame, keyed for the archive.

    Lived in `scripts/13_clv.py` until the shortlist replay needed the same
    frame: a rule graded on one set of probabilities and measured for
    closing-line value on another is two different rules wearing one name.
    """
    import glob
    import re

    rows = []
    for path in sorted(glob.glob(str(get_path("output", target_type) /
                                     "predictions_*_week*.csv"))):
        m = re.search(r"predictions_(\d+)_week(\d+)\.csv", path)
        if not m:
            continue
        d = pl.read_csv(path)
        if "player_name" not in d.columns:
            continue
        # Prefer the pre-blend column. The published `probability` for anytime
        # TD is blended with the closing price and cannot be scored against it.
        src_col = next((c for c in ("prob_model", "prob_calibrated", "probability")
                        if c in d.columns), None)
        if src_col is None:
            continue
        d = d.with_columns(pl.col(src_col).alias("prob_calibrated"))
        rows.append(d.with_columns([
            pl.lit(int(m.group(1))).alias("season"),
            pl.lit(int(m.group(2))).alias("week"),
            # Loses to the backtest frame where both cover a player-game — see
            # the dedup note in clv.hit_rows.
            pl.lit(1).alias("_src_rank"),
        ]))
    rows = _prefer_frozen(rows, target_type)
    from src.features.odds_features import _normalize_name  # noqa

    # Always add the backtest frames alongside any weekly prediction files.
    # The weekly files only cover weeks actually predicted — right now that is
    # the upcoming season, which has no settled line movement at all — while
    # the backtest holds the same published probability for every historical
    # week. Using both is what makes closing-line value answerable now instead
    # of one week at a time from Week 1.
    if True:
        for path in sorted(glob.glob(str(get_path("output", target_type) /
                                         "backtest_*.csv"))):
            season = int(path.rsplit("_", 1)[-1].split(".")[0])
            d = pl.read_csv(path)
            if "prob_calibrated" not in d.columns:
                continue
            rows.append(
                d.select(["game_id", "player_name", "prob_calibrated"])
                 .with_columns([pl.lit(season).alias("season"),
                                pl.lit(0).alias("_src_rank")])
            )
        if not rows:
            return None

    out = pl.concat(rows, how="diagonal_relaxed")
    return out.with_columns(
        pl.col("player_name").map_elements(_normalize_name, return_dtype=pl.Utf8)
        .alias("player_name_norm")
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

    j = hit_rows(predictions, target_type, prob_col)
    if j is None:
        return None
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


# --------------------------------------------------------------------------
# Judging an experiment on closing-line value
# --------------------------------------------------------------------------

def from_players(players: pl.DataFrame | None, *, market: str,
                 model: str) -> pl.DataFrame | None:
    """Harness player rows, keyed the way `hit_rows` needs them.

    `harness.run(keep_rows=True)` already scores every held-out season through
    the production path and keeps the per-player probability. That column is
    the model's own view — the joint model inside it reads the game total and
    spread, which are market numbers, but they are known at the open, and it
    never sees the player's own prop price. So it is the honest input here, and
    it means judging a candidate on closing-line value costs one walk-forward
    rather than a separate scoring path.
    """
    if players is None or players.height == 0:
        return None
    from src.features.odds_features import _normalize_name

    sub = players.filter((pl.col("target_type") == market)
                         & (pl.col("model") == model))
    if sub.height == 0 or "prob" not in sub.columns:
        return None
    return sub.with_columns([
        pl.col("prob").alias(CLEAN_PROB_COL),
        pl.col("player_name").map_elements(_normalize_name, return_dtype=pl.Utf8)
        .alias("player_name_norm"),
    ])


def measure_run(result: dict, *, market: str, model: str) -> dict | None:
    """Closing-line value for one (market, model) of a harness run."""
    preds = from_players(result.get("players"), market=market, model=model)
    if preds is None:
        return None
    return measure(preds, market)


def paired_clv(champion: dict, candidate: dict, *, market: str, model: str,
               against: str | None = None) -> dict | None:
    """Paired closing-line value between two runs of the same folds.

    The reason this exists rather than subtracting two `measure` calls: the two
    runs score the same player-games, so the informative quantity is how often
    they disagree about a line's direction and who was right when they did.
    Pooled rates hide that — two models agreeing on 95% of rows and differing
    on 5% produce almost identical headlines while the paired view shows
    exactly what changed. Same statistic as `paired_top_k`, one row per scored
    player-game instead of one per game.

    `against` names the champion-side model when the candidate introduces one
    the champion does not have.
    """
    against = against or model
    a = from_players(champion.get("players"), market=market, model=against)
    b = from_players(candidate.get("players"), market=market, model=model)
    if a is None or b is None:
        return None

    ra, rb = hit_rows(a, market), hit_rows(b, market)
    if ra is None or rb is None:
        return None

    key = ["game_id", "player_name_norm"]
    j = (ra.select(key + ["hit"]).rename({"hit": "_a"})
         .join(rb.select(key + ["hit"]).rename({"hit": "_b"}),
               on=key, how="inner"))
    if j.height < MIN_ROWS:
        return None

    x = j["_a"].to_numpy().astype(int)
    y = j["_b"].to_numpy().astype(int)
    d = y - x
    n = len(d)
    se = float(d.std(ddof=1) / np.sqrt(n)) if n > 1 else 0.0
    delta = float(d.mean())
    wins = int(((x == 0) & (y == 1)).sum())
    losses = int(((x == 1) & (y == 0)).sum())

    p_value = 1.0
    if wins + losses > 0:
        from scipy.stats import binomtest
        p_value = float(binomtest(wins, wins + losses, 0.5).pvalue)

    return {
        "market": market, "model": model, "against": against,
        "n_compared": n,
        "champion": float(x.mean()), "candidate": float(y.mean()),
        "delta": delta, "se": se,
        "se_multiple": (delta / se) if se > 0 else (0.0 if delta == 0 else float("inf")),
        "wins": wins, "losses": losses, "discordant": wins + losses,
        "p_value": p_value,
    }


def format_clv(row: dict | None) -> str:
    """One block of the gate report, in the same shape as the Top-K lines."""
    if row is None:
        return "    CLV    not measurable — no open/close pairs overlap this run"
    name = (f"{row['model']} vs {row['against']}"
            if row["model"] != row["against"] else row["model"])
    return (
        f"    CLV    {row['champion']:.2%} -> {row['candidate']:.2%}  "
        f"{row['delta']*100:+.2f}pp  ({row['se_multiple']:+.2f} se, "
        f"p={row['p_value']:.3f})  [{name}]\n"
        f"           {row['discordant']:,} of {row['n_compared']:,} player-games "
        f"differ: {row['wins']} won, {row['losses']} lost"
    )


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
