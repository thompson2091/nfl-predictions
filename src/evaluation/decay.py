"""Is the edge still there, or did it stop working and nobody noticed?

Models rarely lose money by being wrong from the start. They lose money by
having been right, and then quietly ceasing to be — a market sharpens, a rule
change moves scoring, a data feed degrades — while a three-season average keeps
reporting the number they used to earn. Nothing in this project watched for
that, which is a strange gap in a system that measures everything else twice.

Two checks, deliberately different in what they need:

  * **By season**, from the backtest. Catches a slow fade across years. Needs a
    completed season to say anything, so it is a post-mortem, not an alarm.
  * **By recent weeks**, from the wager log. Catches a fast break within a
    season, using bets actually placed. Needs a live season's worth of logged
    wagers before it means anything, and says so until then.

Both compare the recent number against the *interval* of the pooled estimate
rather than against a threshold. "Below the bottom of its own confidence range"
is a statement with a meaning; "down more than 5 points" is a number somebody
picked — and the one time this project used a picked threshold here, it fired
on a decline that turned out to be in-sample contamination rather than decay.
"""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from src.utils.paths import get_path

#: Minimum settled bets before the in-season check will speak. With a ~45% hit
#: rate, fewer than this is a handful of coin flips and any "decline" in it is
#: noise wearing a number.
MIN_RECENT_BETS = 60


def by_season(target_type: str = "anytime_td",
              model: str | None = None) -> dict | None:
    """Has the most recent completed season fallen out of the pooled range?

    Runs against whatever the fitted edge rule selects, so it tracks the thing
    the board actually recommends rather than a strategy nobody uses.
    """
    from src.evaluation.rank_economics import (
        load_bets, clustered_roi, fit_edge_rule, BET_RANK_COL,
    )

    df = load_bets(target_type, rank_by=BET_RANK_COL, model=model)
    if df is None or df.height == 0:
        return None
    rule = fit_edge_rule(df)
    if rule is None:
        return None

    sel = df.with_columns(
        (pl.col("prob_calibrated") - pl.col("market_prob")).alias("_edge")
    ).filter((pl.col("_edge") >= rule["edge_cut"])
             & (pl.col("rank") <= rule["max_rank"]))
    if sel.height == 0:
        return None

    pooled = clustered_roi(sel["pnl"].to_numpy(), sel["game_id"].to_numpy())
    seasons = sorted(sel["season"].unique().to_list())
    per = []
    for s in seasons:
        sub = sel.filter(pl.col("season") == s)
        r = clustered_roi(sub["pnl"].to_numpy(), sub["game_id"].to_numpy())
        per.append({"season": int(s), "roi": r["roi"], "lo": r["lo"],
                    "hi": r["hi"], "n": r["n"]})

    latest = per[-1] if per else None
    below = bool(latest and pooled["lo"] is not None
                 and (latest["roi"] or 0) < pooled["lo"])
    return {
        "target_type": target_type, "model": model,
        "rule": {"edge_cut": rule["edge_cut"], "max_rank": rule["max_rank"]},
        "pooled": pooled, "per_season": per, "latest": latest,
        "latest_below_pooled_interval": below,
        "verdict": ("the most recent season is below the pooled range" if below
                    else "the most recent season is inside the pooled range"),
    }


def by_recent_weeks(target_type: str = "anytime_td",
                    window: int = 4) -> dict | None:
    """What the bets you actually placed have done lately.

    Deliberately built on the wager log rather than the backtest: a backtest
    cannot decay, because it is the past. Only real bets at real prices can
    tell you the edge stopped arriving.
    """
    from src.betting import wagers

    graded = wagers.grade(target_type)
    if graded is None or graded.height == 0:
        return None
    settled = graded.filter(pl.col("scored").is_not_null())
    if settled.height == 0:
        return {"target_type": target_type, "n_settled": 0,
                "verdict": "no settled bets yet"}

    settled = settled.sort(["season", "week"])
    weeks = settled.select(["season", "week"]).unique().sort(["season", "week"])
    recent_keys = weeks.tail(window)
    recent = settled.join(recent_keys, on=["season", "week"], how="semi")

    def roi(d: pl.DataFrame) -> float | None:
        staked = float(d["stake"].sum())
        return float(d["pnl"].sum() / staked * 100) if staked else None

    out = {
        "target_type": target_type,
        "window": window,
        "n_settled": int(settled.height),
        "n_recent": int(recent.height),
        "roi_all": roi(settled),
        "roi_recent": roi(recent),
    }
    if settled.height < MIN_RECENT_BETS:
        out["verdict"] = (
            f"only {settled.height} settled bets — too few to judge. This check "
            f"stays quiet until {MIN_RECENT_BETS}."
        )
        return out

    # Compare against the backtested expectation's lower bound, which is the
    # honest "what should we be seeing" figure.
    expected = by_season(target_type)
    floor = (expected or {}).get("pooled", {}).get("lo")
    out["expected_lo"] = floor
    out["below_expectation"] = bool(
        floor is not None and out["roi_recent"] is not None
        and out["roi_recent"] < floor
    )
    out["verdict"] = (
        "recent weeks are below what the backtest says to expect"
        if out["below_expectation"] else "recent weeks are within expectation"
    )
    return out


def report(target_type: str = "anytime_td") -> str:
    """Both checks as a short human-readable block."""
    lines = [f"EDGE DECAY — {target_type}"]
    s = by_season(target_type)
    if s is None:
        lines.append("  by season: no fitted rule to track")
    else:
        p = s["pooled"]
        lines.append(f"  rule: edge >= {s['rule']['edge_cut'] * 100:.0f}pp, "
                     f"rank <= {s['rule']['max_rank']}")
        lines.append(f"  pooled: {p['roi']:+.1f}% [{p['lo']:+.1f}, {p['hi']:+.1f}]")
        for r in s["per_season"]:
            flag = ""
            if r is s["latest"] and s["latest_below_pooled_interval"]:
                flag = "   <-- BELOW the pooled range"
            lines.append(f"    {r['season']}  {r['roi']:+6.1f}%  (n={r['n']}){flag}")
        lines.append(f"  {s['verdict']}")

    w = by_recent_weeks(target_type)
    if w is None:
        lines.append("  recent weeks: no wagers logged")
    else:
        lines.append(f"  recent weeks: {w['verdict']}")
        if w.get("roi_recent") is not None:
            lines.append(f"    last {w['window']} weeks {w['roi_recent']:+.1f}% "
                         f"vs {w['roi_all']:+.1f}% overall "
                         f"({w['n_recent']} of {w['n_settled']} bets)")
    return "\n".join(lines)


def save(stats: dict, path: Path) -> None:
    Path(path).write_text(json.dumps(stats, indent=2))


def load(path: Path) -> dict | None:
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else None
