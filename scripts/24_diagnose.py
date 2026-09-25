#!/usr/bin/env python3
"""Where is Top-1 lost? Measure it, then let that order the work.

Changes nothing. Runs the walk-forward folds, keeps the per-player rows, and
asks five questions of them — headroom against the sportsbook, which half of
the team x share factorisation is wrong, how many games were winnable at all,
where the misses concentrate, and what the candidate pool cannot reach.

    python scripts/24_diagnose.py --target anytime_td
    python scripts/24_diagnose.py --target first_td --reuse

`--reuse` scores from a saved harness run instead of retraining, which makes
re-reading the diagnosis instant. The snapshot is written to `diagnostics/`
and committed, so the diagnosis can be compared against itself later — the
point is to watch these numbers move as Phase 3 lands.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import polars as pl  # noqa: E402

from src.evaluation import diagnose as D  # noqa: E402
from src.evaluation import harness as H  # noqa: E402
from src.utils.config import get_config, production_model  # noqa: E402
from src.utils.paths import PROJECT_ROOT, get_path  # noqa: E402

SNAPSHOT_DIR = PROJECT_ROOT / "diagnostics"


def _load_or_run(target_type: str, run_id: str, reuse: bool,
                 first_test: int, last_test: int) -> dict:
    if reuse:
        # A diagnosis read off a stale matrix sends the model work after
        # problems the current one may not have.
        result = H.load(run_id, markets=(target_type,))
        if result.get("players") is None:
            raise SystemExit(
                f"Saved run '{run_id}' has no per-player rows — it predates "
                "them. Re-run without --reuse.")
        print(f"Reusing saved run '{run_id}'.")
        return result
    result = H.run({}, markets=(target_type,), first_test=first_test,
                   last_test=last_test, keep_rows=True)
    H.save(result, run_id)
    return result


def main(target_type: str, model_name: str, reuse: bool,
         first_test: int, last_test: int) -> int:
    run_id = f"diagnose-{target_type}"
    result = _load_or_run(target_type, run_id, reuse, first_test, last_test)

    players = result["players"].filter(pl.col("model") == model_name)
    outcomes = result["outcomes"].filter(pl.col("model") == model_name)
    seasons = sorted(players["test_season"].unique().to_list())

    from src.models.trainer import _filter_low_activity
    feats = pl.read_parquet(
        get_path("processed", target_type) / "features.parquet")
    labeled = feats.filter(pl.col("season").is_in(seasons)
                            & pl.col("target").is_not_null())

    try:
        from src.ingest.odds_history import load_graded_history
        graded = load_graded_history(target_type)
    except Exception as e:                                  # noqa: BLE001
        graded = None
        print(f"Odds archive unavailable ({e})")

    report = {
        "target_type": target_type, "model": model_name,
        "seasons": seasons, "generated": date.today().isoformat(),
        "pool": D.pool_ceiling(labeled, _filter_low_activity(labeled)),
        "winnability": D.winnability(outcomes),
        "team_vs_player": D.team_vs_player(players),
        "slices": D.slices(players, outcomes),
        "market": (D.market_benchmark(players, graded) if graded is not None
                   else {"available": False, "reason": "no odds archive"}),
        "positions": (D.by_position_vs_market(players, graded)
                      if graded is not None
                      else {"available": False, "reason": "no odds archive"}),
    }

    _print(report)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    out = SNAPSHOT_DIR / f"{report['generated']}-{target_type}.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"\nSaved {out}  <- commit this")
    return 0


def _print(r: dict) -> None:
    print(f"\n{'=' * 78}")
    print(f"DIAGNOSIS — {r['target_type']} / {r['model']}  "
          f"(seasons {min(r['seasons'])}-{max(r['seasons'])})")
    print("=" * 78)

    m = r["market"]
    print("\n1. HEADROOM — us against the sportsbook, same games, same players")
    if not m.get("available"):
        print(f"   unavailable: {m.get('reason')}")
    else:
        print(f"   {m['games']} games where the book priced "
              f"{m['min_priced_per_game']}+ players and one of them scored "
              f"({m['games_dropped_thin']} games too thinly priced to compare)")
        for k in (1, 3, 5):
            e = m[f"top{k}"]
            lead = "we lead" if e["delta"] > 0 else "book leads"
            print(f"   Top-{k}  book {e['market']:.1%}   model {e['model']:.1%}   "
                  f"{e['delta']*100:+.1f}pp ({e['se_multiple']:+.1f} se) — {lead}")
        e = m["top1"]
        print(f"          Top-1 disagreements: we won {e['model_wins']}, "
              f"book won {e['market_wins']}")

    t = r["team_vs_player"]
    print("\n2. WHICH HALF IS WRONG — team rate, or the share within it")
    print(f"   {t['hit_share']:.1%} hit.  Of the {t['games'] - t['hit']} misses: "
          f"{t['of_misses_right_team']:.1%} right team wrong player, "
          f"{t['of_misses_wrong_team']:.1%} wrong team")

    w = r["winnability"]
    print("\n3. HOW WINNABLE — where the scorer ranked")
    hist = "  ".join(f"#{h['rank']}:{h['games']}" for h in w["rank_histogram"][:8])
    print(f"   {hist}   (median {w['median_rank']:.0f})")
    print(f"   coin flips (top two within a point): {w['coin_flip_share']:.1%} "
          f"of games")
    if w["top1_in_coin_flips"] is not None:
        print(f"   Top-1 in coin flips {w['top1_in_coin_flips']:.1%} vs "
              f"{w['top1_in_decided']:.1%} in decided games")

    q = r["positions"]
    print("\n4. BY POSITION — every number beside the book's, on the same games")
    if not q.get("available"):
        print(f"   unavailable: {q.get('reason')}")
    else:
        print(f"   {'pos':8s} {'pick share':>21s} {'mass vs actual':>21s} "
              f"{'within-position AUC':>23s}")
        print(f"   {'':8s} {'ours':>10s} {'book':>10s} "
              f"{'pred':>10s} {'actual':>10s} {'ours':>11s} {'book':>11s}")
        for d in q["positions"]:
            auc = (f"{d['our_auc_within']:>11.4f} {d['book_auc_within']:>11.4f}"
                   if d["our_auc_within"] is not None else f"{'-':>11s} {'-':>11s}")
            print(f"   {d['position']:8s} {d['our_pick_share']:>10.1%} "
                  f"{d['book_pick_share']:>10.1%} {d['predicted_mass']:>10.1%} "
                  f"{d['actual_win_share']:>10.1%} {auc}")
        print("   Pick share SHOULD exceed win share — one lead back outranks four")
        print("   receivers splitting the same mass, and a Top-1 optimiser takes him.")
        print("   Over-valuation shows up in mass vs actual, not in pick share.")
        print(f"\n   Top-1 in games won by each position:")
        for d in q["top1_by_scorer_position"]:
            gap = d["ours"] - d["book"]
            note = "" if abs(gap) < 0.02 else ("  <-- we lead" if gap > 0
                                               else "  <-- book leads")
            print(f"     {d['position']:8s} ours {d['ours']:>6.1%}   "
                  f"book {d['book']:>6.1%}   ({d['games']} games){note}")

    s = r["slices"]
    print("\n5. WHERE ELSE THE MISSES ARE")
    for label, key in (("scorer position", "by_scorer_position"),
                       ("our pick's position", "by_pick_position"),
                       ("side backed", "by_side"), ("game total", "by_total")):
        parts = "  ".join(
            f"{d[list(d)[0]]}: {d['top1']:.1%} ({d['games']})"
            for d in s[key][:6])
        print(f"   by {label:20s} {parts}")

    p = r["pool"]
    print("\n6. WHAT THE POOL CANNOT REACH")
    print(f"   {p['played_games']} played, {p['games_with_no_scorer_anywhere']} "
          f"with no scorer in the pool at all (excluded), "
          f"{p['games_whose_scorer_the_filter_removed']} whose scorer the filter "
          f"removed (counted as misses)")
    print(f"   ceiling {p['ceiling']:.1%} of scored games, "
          f"{p['pool_per_game']:.0f} candidates a game")


if __name__ == "__main__":
    cfg = get_config()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", default=cfg["target"]["type"],
                    choices=list(H.MARKETS))
    ap.add_argument("--model", default=None)
    ap.add_argument("--reuse", action="store_true",
                    help="score from the saved run instead of retraining")
    ap.add_argument("--first-test", type=int,
                    default=cfg["splits"]["test_season"] - 3)
    ap.add_argument("--last-test", type=int, default=cfg["splits"]["test_season"])
    a = ap.parse_args()
    sys.exit(main(a.target, a.model or production_model(a.target), a.reuse,
                  a.first_test, a.last_test))
