"""Does being right actually pay? Profitability by model rank and by price.

Top-N accuracy and profit are different questions, and this project has spent a
lot of effort answering the first while assuming the second followed. It does
not. Measured over three seasons of real closing prices:

    anytime TD   rank 1 hits 56.4% against a 54.4% breakeven  ->  +5.5%
                 rank 5 hits 28.2% against a 33.7% breakeven  -> -13.7%

A model can be right 94.7% of the time about "one of these five scores" and
still lose money backing all five, because the fifth is priced above what it
does. That is the whole point of this module: accuracy is a claim about the
model, profitability is a claim about the model *and* the price, and only the
second is worth betting on.

Every figure carries a game-clustered bootstrap interval rather than a standard
error. Two reasons, both learned the hard way here. Per-bet returns are wildly
skewed — a +3000 winner pays 30u against a 1u loss — so the normal
approximation does not hold. And two bets in one game share a defence, a game
script and a final score, so they are not independent draws. Naive standard
errors on this data are roughly half what they should be.

`concentration` is the companion warning: the share of profit carried by the ten
largest winners. When that is most of it, the "rate" is a handful of coin flips
and the interval, however wide, still flatters it.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from src.utils.paths import get_path

#: Which column to rank by when asking "what would we have bet".
#:
#: `prob_calibrated` is our own view: model, calibrator and joint structure, but
#: *before* the blend with the market. `final` is what the board publishes,
#: after blending. For accuracy the blend helps — the market carries real
#: information and blending improves Brier. For betting it hurts, and by a lot,
#: because a bet is a disagreement with the price and blending is the act of
#: giving that disagreement up. Measured on anytime TD, backing our top 3:
#:
#:     model only (pre-blend)   +12.0%  [ +7.3, +16.7]
#:     blended (published)       +3.6%  [ -0.4,  +7.8]
#:     market only              -10.6%  [-14.7,  -6.7]
#:
#: So the published probability is the right answer to "will he score" and the
#: wrong one to "should I bet him". They are different questions.
BET_RANK_COL = "prob_calibrated"
PUBLISHED_COL = "final"

#: Price bands. Chosen to split the market at points where behaviour changes —
#: odds-on favourites, the +100-300 core, and the longshot tail — not tuned for
#: returns.
ODDS_BUCKETS = [
    (-10_000, 100, "<+100"),
    (100, 300, "+100-300"),
    (300, 700, "+300-700"),
    (700, 1500, "+700-1500"),
    (1500, 10_000_000, "+1500up"),
]

#: Below this a cell is reported but flagged: with a 10% hit rate, 50 bets is
#: five events and any ROI computed from it is noise wearing a number.
MIN_BETS = 50


def clustered_roi(pnl: np.ndarray, games: np.ndarray,
                  draws: int = 2000, seed: int = 0) -> dict:
    """Flat-stake ROI with a game-clustered bootstrap interval.

    Resamples whole games, not individual bets, because bets inside a game
    share their outcome drivers. Also returns what share of the profit the ten
    largest winners account for — when that is most of it, treat the ROI as a
    description of those ten results rather than a rate.
    """
    n = len(pnl)
    if n == 0:
        return {"n": 0, "roi": None, "lo": None, "hi": None,
                "concentration": None, "verdict": "no bets"}

    uniq = np.unique(games)
    idx = {g: np.flatnonzero(games == g) for g in uniq}
    rng = np.random.default_rng(seed)
    boot = np.array([
        pnl[np.concatenate([idx[uniq[i]]
                            for i in rng.choice(len(uniq), len(uniq), True)])].mean()
        for _ in range(draws)
    ]) * 100

    total = pnl.sum()
    concentration = (float(np.sort(pnl)[-10:].sum() / total)
                     if total > 0 and n > 10 else None)
    lo, hi = float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))
    return {
        "n": int(n),
        "roi": float(pnl.mean() * 100),
        "lo": lo,
        "hi": hi,
        "concentration": concentration,
        "verdict": ("positive" if lo > 0 else
                    "negative" if hi < 0 else "indistinguishable from zero"),
    }


def backtest_files(target_type: str, model: str | None = None) -> list:
    """Backtest frames for one model, or the production ones if untagged.

    The app lets you switch models. Before these were tagged, every evaluation
    read whichever backtest ran last, so selecting `lr` on the board left the
    profitability tables describing `xgb` with nothing saying so.
    """
    out_dir = get_path("output", target_type)
    if model:
        tagged = sorted(out_dir.glob(f"backtest_{model}_*.csv"))
        if tagged:
            return tagged
        return []
    # Untagged files are the production model's copy.
    return sorted(p for p in out_dir.glob("backtest_*.csv")
                  if p.stem.count("_") == 1)


def load_bets(target_type: str,
              rank_by: str = BET_RANK_COL,
              model: str | None = None) -> pl.DataFrame | None:
    """Every backtested bet, with rank, payout and profit attached.

    Reads the walk-forward backtest frames, so this describes the production
    path — calibrator, joint model, de-vig and blend all applied — rather than
    raw model output.
    """
    frames = []
    for path in backtest_files(target_type, model):
        season = int(path.stem.rsplit("_", 1)[-1])
        d = pl.read_csv(path)
        if not {"final", "dec", "scored", "game_id"} <= set(d.columns):
            continue
        frames.append(d.with_columns(pl.lit(season).alias("season")))
    if not frames:
        return None

    df = pl.concat(frames, how="diagonal_relaxed")
    rank_col = rank_by if rank_by in df.columns else PUBLISHED_COL
    return df.with_columns([
        pl.col(rank_col).rank(descending=True, method="ordinal")
        .over("game_id").alias("rank"),
        # Profit on a 1u flat stake: win the payout minus the stake, or lose it.
        (pl.col("scored") * (pl.col("dec") - 1) - (1 - pl.col("scored")))
        .alias("pnl"),
        # The hit rate this bet must clear to break even at its own price.
        (1.0 / pl.col("dec")).alias("breakeven"),
    ]).with_columns(
        pl.when(pl.col("odds") < 100).then(pl.lit("<+100"))
        .when(pl.col("odds") < 300).then(pl.lit("+100-300"))
        .when(pl.col("odds") < 700).then(pl.lit("+300-700"))
        .when(pl.col("odds") < 1500).then(pl.lit("+700-1500"))
        .otherwise(pl.lit("+1500up")).alias("bucket")
    )


def _row(sub: pl.DataFrame, **label) -> dict:
    stats = clustered_roi(sub["pnl"].to_numpy(), sub["game_id"].to_numpy())
    stats.update(label)
    stats.update({
        "hit_pct": float(sub["scored"].mean() * 100),
        "breakeven_pct": float(sub["breakeven"].mean() * 100),
        "median_odds": float(sub["odds"].median()),
        "thin": sub.height < MIN_BETS,
    })
    return stats


def by_rank(df: pl.DataFrame, max_rank: int = 8) -> list[dict]:
    """Profitability of the Nth-rated player in a game, for each N."""
    return [_row(df.filter(pl.col("rank") == r), rank=r)
            for r in range(1, max_rank + 1)
            if df.filter(pl.col("rank") == r).height > 0]


def by_odds_bucket(df: pl.DataFrame) -> list[dict]:
    """Profitability by the price the book asked, ignoring our ranking."""
    out = []
    for _, _, name in ODDS_BUCKETS:
        sub = df.filter(pl.col("bucket") == name)
        if sub.height:
            out.append(_row(sub, bucket=name))
    return out


def by_rank_and_odds(df: pl.DataFrame, max_rank: int = 5) -> list[dict]:
    """The intersection: our rank crossed with the book's price.

    Where an edge hides that neither view shows alone — a rank the market
    underrates only at certain prices. Cells are reported with a `thin` flag
    rather than dropped, because silently hiding small cells is how a table
    starts implying more coverage than it has.
    """
    out = []
    for r in range(1, max_rank + 1):
        for _, _, name in ODDS_BUCKETS:
            sub = df.filter((pl.col("rank") == r) & (pl.col("bucket") == name))
            if sub.height:
                out.append(_row(sub, rank=r, bucket=name))
    return out


def top_n_strategies(df: pl.DataFrame, max_n: int = 5) -> list[dict]:
    """Back every player ranked N or better, for each N. The PRD's core question.

    This is the one that decides whether the feature has a foundation. If these
    intervals span zero, high Top-N accuracy has not translated into money and
    no allocation scheme on top of it will change that — sizing cannot rescue a
    negative edge, it only changes how fast you find out.
    """
    return [_row(df.filter(pl.col("rank") <= n), top_n=n)
            for n in range(1, max_n + 1)]


#: Candidate cut-offs for the edge rule, in probability points. Fitted rather
#: than declared: `fit_edge_rule` picks from these by measurement, so a new
#: season re-fits the number instead of inheriting one somebody typed once.
EDGE_GRID = [0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10]

#: Ranks the edge rule is allowed to reach. Bounded because the deeper it goes
#: the more it drifts into the longshot band, where the book's premium is
#: largest and our sorting skill is least convertible into money.
EDGE_MAX_RANK = 5


def edge_curve(df: pl.DataFrame, max_rank: int = EDGE_MAX_RANK) -> list[dict]:
    """Profitability by how far our number sits from the de-vigged price.

    The most theory-driven cut in this module, and the reason it earns its
    place: profit is a claim about edge against a price, and rank enters that
    claim nowhere. If the model is calibrated, return should rise with edge —
    so this is a prediction the maths makes in advance, not a pattern found by
    looking. It comes out monotone, which is the main reason to believe it.

    Edge is measured pre-blend (`prob_calibrated` against `market_prob`). The
    published probability is already pulled toward the price, so its apparent
    edge is roughly 60% of the real one and shrinks exactly where it matters.
    """
    sub = df.filter(pl.col("rank") <= max_rank)
    if "prob_calibrated" not in sub.columns or "market_prob" not in sub.columns:
        return []
    sub = sub.with_columns(
        (pl.col("prob_calibrated") - pl.col("market_prob")).alias("model_edge")
    )
    out = []
    for lo, hi in zip(EDGE_GRID, EDGE_GRID[1:] + [1.0]):
        cell = sub.filter((pl.col("model_edge") >= lo) & (pl.col("model_edge") < hi))
        if cell.height:
            row = _row(cell, edge_from=lo, edge_to=(hi if hi <= 1.0 else None))
            out.append(row)
    return out


def fit_edge_rule(df: pl.DataFrame, max_rank: int = EDGE_MAX_RANK) -> dict | None:
    """The smallest edge cut-off that separates a paying set from a losing one.

    Three conditions, all required, because any one alone is easy to satisfy by
    chance across ten candidate thresholds:

    1. Bets **at or above** the cut-off turned a profit whose clustered interval
       excludes zero.
    2. Bets **below** it did not — they lost money, or could not be told from
       zero. A threshold that merely skims the best bets out of a set that was
       already profitable has found nothing; a threshold worth applying is one
       that also identifies bets worth *skipping*.
    3. The kept set was profitable in **every season separately**. This is the
       condition that does the real work: a threshold fitted to noise will
       almost always lean on one good year.

    The smallest qualifying cut-off wins, so the rule keeps as many bets as the
    evidence allows rather than shrinking to whatever slice looks best. That
    direction matters for a second reason: theory says the boundary belongs at
    zero edge, since positive expected value starts the moment our number
    exceeds the vig-free price. A rule that lands near zero is the data
    agreeing with the maths. One that lands far from it is a fitted parameter
    wearing a theory's clothes, and should be trusted accordingly.
    """
    sub = df.filter(pl.col("rank") <= max_rank)
    if "prob_calibrated" not in sub.columns or "market_prob" not in sub.columns:
        return None
    sub = sub.with_columns(
        (pl.col("prob_calibrated") - pl.col("market_prob")).alias("model_edge")
    )

    for cut in EDGE_GRID:
        if cut <= 0:
            continue
        keep = sub.filter(pl.col("model_edge") >= cut)
        drop = sub.filter(pl.col("model_edge") < cut)
        if keep.height < MIN_BETS or drop.height < MIN_BETS:
            continue
        kept = _row(keep, cut=cut)
        dropped = _row(drop, cut=cut)
        if kept["verdict"] != "positive" or dropped["verdict"] == "positive":
            continue
        seasons = sorted(keep["season"].unique().to_list())
        per_season = [_row(keep.filter(pl.col("season") == s), season=int(s))
                      for s in seasons]
        if not all((r["roi"] or 0) > 0 for r in per_season):
            continue
        return {
            "edge_cut": cut,
            "max_rank": max_rank,
            "kept": kept,
            "dropped": dropped,
            "per_season": per_season,
            "bets_per_week": (keep.height /
                              max(keep.select(["season", "week"]).n_unique(), 1)),
        }
    return None


#: Quantile of |edge| above which a disagreement counts as large. Not a tuned
#: parameter: it is the same top-decile cut the head-to-head accuracy figure
#: uses, so "big disagreement" means one thing across the whole project.
BIG_DISAGREEMENT_Q = 0.90

#: Odds-on favourites are excluded from the highlights. An edge measured in
#: probability points buys less return the shorter the price — five points on a
#: 55% favourite is a far smaller edge *proportionally* than five points on a
#: 20% shot — and the sub-+100 band measured near zero on its own. The exclusion
#: is still tested rather than assumed; see `fit_highlight_tiers`.
SHORT_PRICE = 100


def fit_highlight_tiers(df: pl.DataFrame) -> dict | None:
    """Which rows on the board are worth marking, and how strongly.

    Two tiers rather than a letter grade. A grade beside a player's name reads
    as a promise about that player, and none of this is: roughly half of even
    the strongest tier loses. Two levels carry the one distinction the data
    actually supports — a large disagreement pays about twice a small one — and
    nothing finer.

    Both tiers must clear the same bar the headline strategy does: a clustered
    interval excluding zero *and* a profit in every season separately. The
    short-price exclusion is applied only if it earns its place on the same
    test, so a future season where favourites start paying will drop it.

    Returns None when the market has no fitted edge rule to build on, which is
    what keeps an unproven market unmarked.
    """
    rule = fit_edge_rule(df)
    if rule is None:
        return None

    d = df.with_columns(
        (pl.col("prob_calibrated") - pl.col("market_prob")).alias("_edge")
    )
    big = float(np.quantile(d["_edge"].abs().to_numpy(), BIG_DISAGREEMENT_Q))
    cut, max_rank = rule["edge_cut"], rule["max_rank"]

    def qualifies(sub: pl.DataFrame) -> tuple[bool, dict, list[dict]]:
        if sub.height < MIN_BETS:
            return False, {}, []
        stats = _row(sub)
        seasons = sorted(sub["season"].unique().to_list())
        per = [_row(sub.filter(pl.col("season") == s), season=int(s))
               for s in seasons]
        ok = (stats["verdict"] == "positive"
              and all((p["roi"] or 0) > 0 for p in per))
        return ok, stats, per

    base = d.filter((pl.col("_edge") >= cut) & (pl.col("rank") <= max_rank))
    # Test the exclusion rather than assuming it: keep it only if it both
    # qualifies and beats the unfiltered version.
    kept_short = base.filter(pl.col("odds") >= SHORT_PRICE)
    ok_short, s_short, _ = qualifies(kept_short)
    ok_all, s_all, _ = qualifies(base)
    exclude_short = bool(ok_short and ok_all
                         and s_short["roi"] > s_all["roi"])
    if exclude_short:
        base = kept_short

    tiers = []
    for name, sub in (("strong", base.filter(pl.col("_edge") >= big)),
                      ("standard", base.filter(pl.col("_edge") < big))):
        ok, stats, per = qualifies(sub)
        if not ok:
            continue
        weeks = max(sub.select(["season", "week"]).n_unique(), 1)
        tiers.append({
            "tier": name,
            **stats,
            "per_season": per,
            "bets_per_week": sub.height / weeks,
            # Season-over-season slope, in points of ROI per year. The strongest
            # tier has been halving annually; a highlight that does not say so
            # is quoting a three-year average of something that is fading.
            "trend": (round((per[-1]["roi"] - per[0]["roi"]) / max(len(per) - 1, 1), 1)
                      if len(per) > 1 else None),
        })
    if not tiers:
        return None

    return {
        "edge_cut": cut,
        "max_rank": max_rank,
        "big_edge": big,
        "exclude_below_odds": SHORT_PRICE if exclude_short else None,
        "tiers": tiers,
    }


def by_season(df: pl.DataFrame, top_n: int = 3) -> list[dict]:
    """The headline strategy, season by season. Stability is the real test."""
    return [_row(df.filter((pl.col("rank") <= top_n) & (pl.col("season") == s)),
                 season=int(s))
            for s in sorted(df["season"].unique().to_list())]


def measure(target_type: str, headline_n: int = 3,
            model: str | None = None) -> dict | None:
    """Everything above, plus a single honest verdict.

    `headline_n` is declared up front rather than chosen after seeing results.
    Scanning five strategies and reporting the best one guarantees a winner:
    on anytime TD, top-4 reads [+1.2%, +8.5%] while the other four all span
    zero, which is what one-in-five looks like. The headline is fixed so the
    verdict cannot be fitted to the data.
    """
    df = load_bets(target_type, rank_by=BET_RANK_COL, model=model)
    if df is None or df.height == 0:
        return None

    strategies = top_n_strategies(df)

    # The comparison that decides which column to bet on. Reported rather than
    # assumed, so if the blend ever stops costing edge the table will say so.
    comparison = []
    for col, label in [(BET_RANK_COL, "model only (pre-blend)"),
                       (PUBLISHED_COL, "blended (published)"),
                       ("market_prob", "market only")]:
        alt = load_bets(target_type, rank_by=col, model=model)
        if alt is None or col not in alt.columns:
            continue
        for n in (1, headline_n):
            row = _row(alt.filter(pl.col("rank") <= n), top_n=n)
            row["ranked_by"] = label
            comparison.append(row)
    headline = next((s for s in strategies if s.get("top_n") == headline_n), None)
    return {
        "target_type": target_type,
        "model": model,
        "seasons": sorted(int(s) for s in df["season"].unique().to_list()),
        "games": int(df["game_id"].n_unique()),
        "bets": int(df.height),
        "headline_n": headline_n,
        "headline": headline,
        "verdict": headline["verdict"] if headline else "no bets",
        "by_rank": by_rank(df),
        "by_odds_bucket": by_odds_bucket(df),
        "by_rank_and_odds": by_rank_and_odds(df),
        "top_n": strategies,
        "by_season": by_season(df, headline_n),
        "ranked_by": BET_RANK_COL,
        "blend_comparison": comparison,
        "edge_curve": edge_curve(df),
        "edge_rule": fit_edge_rule(df),
        "highlight_tiers": fit_highlight_tiers(df),
    }


def profitable_region(stats: dict | None) -> dict | None:
    """How deep into a game's list the measured edge actually reached.

    This is what lets the board mark rows without overclaiming, so it is
    deliberately hard to satisfy.

    Returns None unless the market itself cleared its prices. If the headline
    strategy's interval spans zero there is no region to mark, and marking rows
    anyway would dress an unproven market as a proven one.

    Within a proven market the region is the *unbroken* run of ranks from 1 that
    each turned a profit whose interval excludes zero. It stops at the first
    rank that does not, rather than reaching for the deepest positive rank
    anywhere in the table: a profitable rank 6 sitting behind an unprofitable
    rank 5 is the signature of noise, not of depth.
    """
    if not stats:
        return None
    headline = stats.get("headline")
    if not headline or headline.get("verdict") != "positive":
        return None

    depth = 0
    for row in sorted(stats.get("by_rank") or [], key=lambda r: r["rank"]):
        if row["rank"] != depth + 1 or row["verdict"] != "positive":
            break
        depth = row["rank"]
    if depth == 0:
        return None

    seasons = stats.get("seasons") or []
    return {
        "max_rank": depth,
        "roi": headline["roi"],
        "lo": headline["lo"],
        "hi": headline["hi"],
        "hit_pct": headline["hit_pct"],
        "top_n": stats.get("headline_n"),
        "games": stats.get("games"),
        "span": f"{seasons[0]}-{seasons[-1]}" if seasons else "",
    }


def save(stats: dict, path: Path) -> None:
    Path(path).write_text(json.dumps(stats, indent=2))


def load(path: Path) -> dict | None:
    if not Path(path).exists():
        return None
    return json.loads(Path(path).read_text())
