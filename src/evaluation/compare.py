"""Decide whether a candidate actually beats the champion.

Pooled Top-1 carries a binomial standard error of +/-1.5% over 1,130 anytime-TD
games and +/-1.1% over 1,131 first-TD games. Almost every change worth making
is worth one to two points. Subtracting two pooled percentages therefore cannot
resolve the changes this project exists to make, and comparing them that way is
how a real improvement gets discarded and a noise spike gets promoted.

Two variants score **the same games** and agree on nearly all of them. The
information about which is better lives entirely in the games where they
disagree, and testing only those is far more powerful:

    pooled     51.2% vs 50.9%, +/-1.5% each      -> indistinguishable
    paired     of 1,130 games, 47 differ, 29-18  -> delta +1.0pp, se 0.6pp

So Top-K is compared per game — the paired difference of the hit indicators,
with McNemar's exact test on the discordant games — and AUC and Brier are
compared against the measured seed-to-seed noise, because a difference smaller
than what the random seed produces on its own is not a difference.

`gate` implements the promotion rule agreed for this project:

    paired Top-1 improvement >= 1 standard error of the paired difference,
    AND no guard metric (Top-3, Top-5, AUC, Brier) worse by more than its
    own noise band.

A tripped guard is reported, not auto-rejected: a candidate can still be
promoted as KEPT_WITH_JUSTIFICATION, which forces the reason into the version
manifest. Nothing degrades silently, and nothing is rejected by a rule that
cannot see the whole picture.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from src.evaluation.ranking import TOP_K

#: Metrics a candidate must not quietly give up to buy its Top-1 gain. Sign is
#: +1 where higher is better.
GUARDS = {"top3": +1, "top5": +1, "auc": +1, "brier": -1}

#: How many standard errors of paired improvement a candidate needs on Top-1.
PROMOTION_SE = 1.0


def paired_top_k(champion: pl.DataFrame, candidate: pl.DataFrame,
                 k: int = 1) -> dict:
    """Per-game paired comparison of Top-K between two runs of the same folds.

    Joins on game id, so a game missing from either side is dropped rather than
    counted as a win for whoever has it. `n_compared` reports what survived; a
    number well below the fold's game count means the two runs did not score
    the same seasons and the comparison is not the one you think it is.
    """
    col = f"hit{k}"
    joined = (
        champion.select(["game_id", col]).rename({col: "_a"})
        .join(candidate.select(["game_id", col]).rename({col: "_b"}),
              on="game_id", how="inner")
    )
    a = joined["_a"].to_numpy().astype(int)
    b = joined["_b"].to_numpy().astype(int)
    n = len(a)
    if n == 0:
        return {"k": k, "n_compared": 0, "delta": 0.0, "se": 0.0,
                "champion": 0.0, "candidate": 0.0, "wins": 0, "losses": 0,
                "p_value": 1.0, "se_multiple": 0.0}

    d = b - a
    delta = float(d.mean())
    se = float(d.std(ddof=1) / np.sqrt(n)) if n > 1 else 0.0
    wins = int(((a == 0) & (b == 1)).sum())     # candidate right, champion wrong
    losses = int(((a == 1) & (b == 0)).sum())

    # McNemar, exact: under the null the discordant games split evenly.
    p_value = 1.0
    if wins + losses > 0:
        from scipy.stats import binomtest
        p_value = float(binomtest(wins, wins + losses, 0.5).pvalue)

    return {
        "k": k, "n_compared": n,
        "champion": float(a.mean()), "candidate": float(b.mean()),
        "delta": delta, "se": se,
        "se_multiple": (delta / se) if se > 0 else (0.0 if delta == 0 else float("inf")),
        "wins": wins, "losses": losses, "discordant": wins + losses,
        "p_value": p_value,
    }


def _outcomes_for(result: dict, market: str, model: str) -> pl.DataFrame:
    return result["outcomes"].filter(
        (pl.col("target_type") == market) & (pl.col("model") == model))


def _pooled_metric(result: dict, market: str, model: str, key: str) -> float | None:
    rows = [r for r in result["row_metrics"]
            if r["target_type"] == market and r["model"] == model]
    total = sum(r["rows"] for r in rows)
    if not total:
        return None
    return sum(r[key] * r["rows"] for r in rows) / total


def compare(champion: dict, candidate: dict, *, market: str, model: str,
            noise: dict | None = None) -> dict:
    """Every metric for one (market, model), paired where pairing is possible."""
    a = _outcomes_for(champion, market, model)
    b = _outcomes_for(candidate, market, model)

    out = {
        "market": market, "model": model,
        "top_k": {k: paired_top_k(a, b, k) for k in TOP_K},
        "row": {},
    }
    band = (noise or {}).get(market, {}).get(model, {})
    for key in ("auc", "brier"):
        pa, pb = (_pooled_metric(champion, market, model, key),
                  _pooled_metric(candidate, market, model, key))
        if pa is None or pb is None:
            continue
        out["row"][key] = {
            "champion": pa, "candidate": pb, "delta": pb - pa,
            "noise_band": band.get(key),
        }
    for k in TOP_K:
        out["top_k"][k]["noise_band"] = band.get(f"top{k}")
    return out


def gate(comparison: dict) -> dict:
    """Apply the promotion rule to one (market, model) comparison.

    Returns the verdict plus every number behind it, because a verdict without
    its evidence is exactly the kind of claim this project keeps having to
    re-derive.
    """
    top1 = comparison["top_k"][1]
    wins_top1 = top1["se"] > 0 and top1["delta"] >= PROMOTION_SE * top1["se"]

    tripped = []
    for key, sign in GUARDS.items():
        if key in ("top3", "top5"):
            entry = comparison["top_k"][int(key[-1])]
            delta = entry["delta"]
            # A guard's noise band is the measured seed spread when we have it,
            # and the paired standard error when we do not. Without either,
            # nothing can be called "materially worse" and any regression trips.
            band = entry.get("noise_band") or entry["se"]
        else:
            entry = comparison["row"].get(key)
            if entry is None:
                continue
            delta = entry["delta"]
            band = entry.get("noise_band") or 0.0
        worse_by = -sign * delta          # positive means worse
        if worse_by > band:
            tripped.append({"metric": key, "delta": delta, "band": band,
                            "worse_by": worse_by})

    if wins_top1 and not tripped:
        verdict = "PROMOTED"
    elif wins_top1:
        verdict = "GUARD_TRIPPED"       # promotable only with a justification
    else:
        verdict = "REJECTED"

    return {
        "market": comparison["market"], "model": comparison["model"],
        "verdict": verdict,
        "top1": top1,
        "top_k": comparison["top_k"],
        "guards_tripped": tripped,
        "row": comparison["row"],
        "rule": f"paired Top-1 >= {PROMOTION_SE} se, no guard worse than its "
                f"noise band",
    }


def compare_all(champion: dict, candidate: dict,
                noise: dict | None = None) -> list[dict]:
    """Every (market, model) both runs share, gated."""
    def pairs(result):
        return set(map(tuple, result["outcomes"]
                       .select(["target_type", "model"]).unique().rows()))

    shared = sorted(pairs(champion) & pairs(candidate))
    return [gate(compare(champion, candidate, market=m, model=mod, noise=noise))
            for m, mod in shared]


def noise_floor(results: list[dict]) -> dict:
    """The spread across identical runs that differ only in the random seed.

    Any claimed gain below this is noise, and this is what the gate uses as
    each guard's "materially worse" band. Measuring it is not optional: without
    it there is no scale on which to read a 0.4-point difference.

    Reported as the standard deviation across seeds, per market, model and
    metric.
    """
    from src.evaluation.harness import summarise

    summaries = [summarise(r) for r in results]
    out: dict = {}
    markets = set().union(*[set(s) for s in summaries])
    for market in sorted(markets):
        out[market] = {}
        models = set().union(*[set(s.get(market, {})) for s in summaries])
        for model in sorted(models):
            values: dict[str, list[float]] = {}
            for s in summaries:
                stats = s.get(market, {}).get(model)
                if not stats:
                    continue
                for key in ("top1", "top3", "top5", "auc", "brier"):
                    values.setdefault(key, []).append(float(stats[key]))
            out[market][model] = {
                key: float(np.std(v, ddof=1)) if len(v) > 1 else 0.0
                for key, v in values.items()
            }
            out[market][model]["n_seeds"] = len(summaries)
    return out


def format_gate(rows: list[dict]) -> str:
    """The comparison table a decision gets made from."""
    lines = []
    for r in rows:
        t1 = r["top1"]
        lines.append(f"{r['market']} / {r['model']}: {r['verdict']}")
        lines.append(
            f"    Top-1  {t1['champion']:.1%} -> {t1['candidate']:.1%}  "
            f"{t1['delta']*100:+.2f}pp  ({t1['se_multiple']:+.2f} se, "
            f"p={t1['p_value']:.3f})")
        lines.append(
            f"           {t1['discordant']} of {t1['n_compared']} games differ: "
            f"{t1['wins']} won, {t1['losses']} lost")
        for k in TOP_K:
            if k == 1:
                continue
            e = r["top_k"][k]
            lines.append(
                f"    Top-{k}  {e['champion']:.1%} -> {e['candidate']:.1%}  "
                f"{e['delta']*100:+.2f}pp  ({e['se_multiple']:+.2f} se)")
        for key, entry in r["row"].items():
            band = entry.get("noise_band")
            band_s = f", noise {band:.5f}" if band else ""
            lines.append(f"    {key:6s} {entry['champion']:.5f} -> "
                         f"{entry['candidate']:.5f}  {entry['delta']:+.5f}{band_s}")
        for g in r["guards_tripped"]:
            lines.append(f"    GUARD {g['metric']}: worse by {g['worse_by']:.5f}, "
                         f"band {g['band']:.5f}")
        lines.append("")
    return "\n".join(lines)
