#!/usr/bin/env python3
"""What kinds of player, and what kinds of bet, are we actually dealing with?

    python scripts/21_clusters.py --target anytime_td

Fits two unsupervised groupings on the training seasons and scores them on the
seasons after — player archetypes from usage and role, bet shapes from our
number against the price. Writes the artifacts the Player types tab reads.

Read the output before trusting the tab. If a group is not interpretable here,
at a terminal, with its top deviations and three example player-games printed
next to its name, then it will not be interpretable in a table either — it will
just be harder to notice.

Needs features (scripts/04_features.py) and, for bet shapes, backtest frames
(scripts/10_backtest.py) for the seasons you hold prices for.
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from src.clustering import archetypes, bet_shapes, core
from src.utils.config import get_config


def _money(r: dict) -> str:
    if r.get("roi") is None:
        return f"{r.get('n_bets', 0):>5} bets   never priced"
    flag = "  THIN" if r.get("thin") else ""
    conc = ""
    if r.get("concentration") and r["concentration"] > 0.5:
        conc = f"   top-10 winners = {r['concentration']:.0%} of profit"
    return (f"{r['n_bets']:>5} {r['hit_pct']:>6.1f}% {r['breakeven_pct']:>8.1f}% "
            f"{r['median_odds']:>+8.0f} {r['roi']:>+7.1f}% "
            f"[{r['lo']:>+6.1f}, {r['hi']:>+6.1f}]{flag}{conc}")


def _print_pruning(art: dict, name: str) -> None:
    features, transforms, _, _ = core.space(art, name)
    dropped = art["strata"][name].get("dropped", art.get("dropped", []))
    print(f"    features: {len(features)} kept, {len(dropped)} pruned")
    for c in features:
        print(f"      keep  {c:<40} {transforms.get(c, 'none')}")
    for d in dropped:
        print(f"      drop  {d['col']:<40} {d['reason']}")


def _print_selection(name: str, s: dict) -> None:
    print(f"\n  {name} — {s['n']:,} rows")
    print(f"    {'k':>3} {'gap':>8} {'±se':>7} {'silhouette':>11} {'±se':>7} "
          f"{'inertia':>12} {'ARI':>6} {'smallest':>9}")
    for row in s["selection"]:
        star = "  <- chosen" if row["k"] == s["k"] else ""
        print(f"    {row['k']:>3} {row.get('gap', 0):>8.3f} "
              f"{row.get('gap_se', 0):>7.3f} {row.get('silhouette', 0):>11.3f} "
              f"{row.get('silhouette_se', 0):>7.3f} {row.get('inertia', 0):>12,.0f} "
              f"{row.get('split_half_ari', 0):>6.2f} "
              f"{row.get('smallest_cluster', 0):>9,}{star}")
    if s["k_unresolved"]:
        print(f"    !! k NOT RESOLVED: {s['k_reason']}")
    else:
        print(f"    {s['k_reason']}")


def _print_clusters(s: dict, report_rows: list[dict], stratum: str) -> None:
    by_id = {r["cluster"]: r for r in report_rows if r["stratum"] == stratum}
    for c in s["clusters"]:
        r = by_id.get(c["id"])
        size = s["sizes"][c["id"]]
        tag = "" if c["label_source"] == "vocabulary" else "  [generated name]"
        print(f"\n    [{c['id']}] {c['label']}{tag}   {size:,} fit rows")
        print(f"        {core.profile(c['top_features'])}")
        ex = ", ".join(f"{e['player_name']} {e['season']} wk{e['week']}"
                       for e in c.get("examples", []))
        if ex:
            print(f"        e.g. {ex}")
        if not r:
            print("        no reporting rows")
            continue
        if "td_rate" in r:
            print(f"        scored {r['td_rate']:.1%} of {r['n']:,} player-games"
                  f"   we said {r.get('our_mean_prob', float('nan')):.1%}"
                  f"   book said {r.get('market_mean_prob', float('nan')):.1%}")
        if r.get("outlier_share", 0) > 0.25:
            print(f"        !! {r['outlier_share']:.0%} of reporting rows sit "
                  f"beyond where this group was fitted — the role may have moved")
        print(f"        {_money(r)}")


def _lens(title: str, art: dict, rep: dict) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")
    print(f"Fitted on   {art['seasons_used']}   {art['n_rows_fit']:,} rows "
          f"({art['population']})")
    print(f"Measured on {rep['report_seasons']}   {rep['n_rows']:,} rows, "
          f"{rep['n_priced_rows']:,} of them priced")
    print(f"Criterion   {art['criterion']}, k in {art['k_range']}, seed {art['seed']}")

    hdr = (f"{'bets':>5} {'hit':>6} {'breakeven':>9} {'odds':>8} {'ROI':>8} "
           f"{'95% interval':>17}")
    for name, s in art["strata"].items():
        _print_selection(name, s)
        _print_pruning(art, name)
        print(f"\n    {'':>4} {hdr}")
        _print_clusters(s, rep["rows"], name)

    print(f"\n  Looking at {rep['n_cells']} groups at once. At a 95% interval "
          f"about one in twenty\n  excludes zero for nothing, so a single group "
          f"standing out is the weakest\n  kind of evidence available here.")


def main(target: str, lens: str, model: str | None, k_min: int | None,
         k_max: int | None, seed: int | None, report: bool) -> int:
    ran = False

    if lens in ("player", "both"):
        art = archetypes.fit(target, k_min, k_max, seed)
        core.save(art, archetypes.artifact_path(target))
        rep = (archetypes.measure(target, art, model) if report
               else {"report_seasons": [], "n_rows": 0, "n_priced_rows": 0,
                     "n_cells": 0, "rows": []})
        if report:
            core.save(rep, archetypes.report_path(target, model))
        _lens(f"PLAYER ARCHETYPES — {target}", art, rep)

        pooled = art.get("pooled_evidence") or {}
        if pooled.get("composition"):
            print(f"\n  WHY NOT CLUSTER EVERYONE TOGETHER")
            print(f"  Pooled across positions, silhouette prefers k="
                  f"{pooled['silhouette_best_k']}. Those groups are:")
            for c in pooled["composition"]:
                tops = ", ".join(f"{p['position']} {p['share']:.0%}"
                                 for p in c["top_positions"])
                print(f"    cluster {c['cluster']}  {c['n']:>6,} rows   {tops}")
            print(f"  That is the position column with extra steps, which is why "
                  f"position is\n  the stratifier here and k is chosen by the gap "
                  f"statistic instead.")

        print(f"\nSaved: {archetypes.artifact_path(target)}")
        if report:
            print(f"Saved: {archetypes.report_path(target, model)}")
        ran = True

    if lens in ("bet", "both"):
        try:
            art = bet_shapes.fit(target, model, k_min, k_max, seed)
        except (FileNotFoundError, ValueError) as e:
            print(f"\nBet shapes skipped for {target}: {e}")
            return 0 if ran else 1
        core.save(art, bet_shapes.artifact_path(target, model))
        rep = (bet_shapes.measure(target, art, model) if report
               else {"report_seasons": [], "n_rows": 0, "n_priced_rows": 0,
                     "n_cells": 0, "rows": []})
        if report:
            core.save(rep, bet_shapes.report_path(target, model))
        _lens(f"BET SHAPES — {target} — {art['model']}", art, rep)
        if len(art["seasons_used"]) == 1:
            print(f"\n  Fitted on {art['seasons_used'][0]} alone: real odds "
                  f"history does not reach\n  further back than the training "
                  f"split. One season of board shapes is thin,\n  and it is "
                  f"stated rather than fixed by reaching across the split.")
        print(f"\nSaved: {bet_shapes.artifact_path(target, model)}")
        if report:
            print(f"Saved: {bet_shapes.report_path(target, model)}")
        ran = True

    return 0 if ran else 1


if __name__ == "__main__":
    cfg = get_config()
    cl = core.settings()
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=cfg["target"]["type"])
    ap.add_argument("--lens", default="both", choices=["player", "bet", "both"])
    ap.add_argument("--model", default=None,
                    help="Tag bet shapes to a specific model. Omit for production.")
    ap.add_argument("--k-min", type=int, default=cl["k_min"])
    ap.add_argument("--k-max", type=int, default=cl["k_max"])
    ap.add_argument("--seed", type=int, default=cl["seed"])
    ap.add_argument("--no-report", action="store_true",
                    help="Fit only; skip the out-of-fit measurement.")
    a = ap.parse_args()
    sys.exit(main(a.target, a.lens, a.model, a.k_min, a.k_max, a.seed,
                  not a.no_report))
