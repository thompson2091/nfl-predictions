"""Would picking different players — or a different number of them — have helped?

`cover_backtest` replays one rule: the top N of the board by the published
column, one per game, every week, same N. It answers "what did that return".
This answers the question that follows, which is not the same one: **was the
rule the problem, or the market?**

Four things are measured. Only two of them are rules anyone could have followed.

  * **Every fixed variant.** Six orderings crossed with six pool sizes, plus a
    version that allows teammates and two that let the week decide how many legs
    it has. Each is decidable from the board before kickoff.
  * **The hindsight ceiling.** Per week, the best of all of them, chosen after
    the week. Nobody can play this.
  * **The walk-forward chooser.** Each week, play whichever variant has the best
    cumulative return through the *previous* week. This is the honest version of
    "we would have changed it week to week": it changes week to week and it uses
    only what was known at the time.
  * **The same three on random orderings.** Pick players at random, one per
    game, and run the identical machinery.

**Why the random control is not optional.** Forty-four variants over sixty weeks
produce a winner whether or not any skill exists, and a hindsight ceiling is a
statement about outcome *variance* rather than available skill. Both intuitions
fail here in the same direction, and only the control shows it. On anytime TD,
against a real ceiling of +319% and a best real variant of +19.0%, five redraws
of the control give:

    random ceiling          +429% median, +294% to +643% across redraws
    best random variant      +72% median,   +6% to +274%
    median random variant    -70% median,  -72% to  -66%
    random chooser           -69% median,  -96% to  -52%

The ceiling and the best variant are beaten by noise. The median variant and the
chooser are not — random collapses to about -70% on both and the real rules do
not. Note the best random variant's own range: +6% to +274% depending only on
the seed. That spread is the clearest statement available about what a
max-over-variants is worth, which is why the control is redrawn rather than
drawn once, and why every comparison against it uses its *luckiest* redraw.

**Orderings.** All six are computable from the board before kickoff:

    published    the blended probability the board shows
    model        the model's own probability, before the blend
    edge         published minus the de-vigged price
    model_edge   the model's own number minus the price — the bet ranking
    ev           published probability times decimal price, minus one
    model_ev     the same on the unblended number

`edge` and `ev` rank by disagreement with the book rather than by likelihood,
which is the ordering a bettor would reach for and a different question from
"who is most likely to score". Both are far worse: full-tilt disagreement buys
longshots, and a slip needing every leg cannot afford them.

Nothing here has produced an interval clearing zero. What it produces is a
direction — see `docs/COVER_SELECTION.md` for the reading.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.evaluation.cover_backtest import SIZES, load_weeks, replay_week

#: How many legs a variable-size week must find before it plays at all. Below
#: three there is nothing to spread.
MIN_LEGS = 3

#: And the most it will take. Past eight a week's outlay dwarfs any bankroll and
#: the tail carries the whole result — the same ceiling `cover_backtest` uses,
#: for the same reason.
MAX_LEGS = 8

#: Weeks played on the baseline before the walk-forward chooser may choose.
#: Under this, "best so far" is one or two weeks of noise, and a chooser that
#: switches on noise measures the switching rather than the choosing.
BURN_IN = 20

#: The variant the chooser falls back to, and the rule the section documents.
BASELINE = "published/5"

#: How many random orderings the control runs. Matched to the number of real
#: variants: the control's job is to show what "best of this many" is worth, so
#: it has to be the same many.
N_RANDOM = 44

#: Fixed, because a control whose verdict moves between runs is not a control.
CONTROL_SEED = 20260820

#: How many times the control is re-drawn. One draw is not enough: the best of
#: 44 random rules moved from +60% to +211% between two seedings of this same
#: measurement, which is the strongest single statement available about what a
#: max-over-variants is worth. A control that unstable needs its own range
#: reported, not a point estimate.
CONTROL_REPEATS = 5

ORDERINGS = ("published", "model", "edge", "model_edge", "ev", "model_ev")


def _keys(board: pd.DataFrame) -> dict[str, np.ndarray]:
    """Every ordering, as a sort key. All are known before kickoff."""
    pub = board["_p"].astype(float).to_numpy()
    n = len(board)
    mkt = (board["market_prob"].astype(float).to_numpy()
           if "market_prob" in board.columns else np.full(n, np.nan))
    mdl = (board["prob_calibrated"].astype(float).to_numpy()
           if "prob_calibrated" in board.columns else pub)
    dec = (board["dec"].astype(float).to_numpy()
           if "dec" in board.columns else np.full(n, np.nan))
    return {
        "published": pub,
        "model": mdl,
        "edge": pub - mkt,
        "model_edge": mdl - mkt,
        "ev": pub * dec - 1.0,
        "model_ev": mdl * dec - 1.0,
    }


def prepared(board: pd.DataFrame) -> pd.DataFrame:
    """The board with every real sort key attached."""
    out = board.copy()
    for name, key in _keys(board).items():
        out[f"_k_{name}"] = key
    return out


def with_random(board: pd.DataFrame, week_seed: int, rep: int) -> pd.DataFrame:
    """The same board with one repeat's worth of random orderings.

    Seeded from the week and the repeat rather than drawn once per run, so the
    control is reproducible and two variants in one week see genuinely
    different draws rather than the same one twice.
    """
    out = board.copy()
    rng = np.random.default_rng(CONTROL_SEED + rep * 1_000_003 + week_seed)
    for i in range(N_RANDOM):
        out[f"_k_rand{i}"] = rng.random(len(board))
    return out


def play(board: pd.DataFrame, order: str, n: int | None, per_game: bool,
         stake: float, rule: str | None = None) -> dict | None:
    """One variant's week.

    `replay_week` does the grading; this only decides which rows go into it.
    Keeping the payout arithmetic in one place is deliberate: the whole exercise
    is comparing selections, and a second copy of the payout would make
    differences in it look like differences in the selection.
    """
    col = f"_k_{order}"
    if col not in board.columns:
        return None
    b = board[np.isfinite(board[col])]
    if b.empty:
        return None
    b = b.sort_values(col, ascending=False)
    if per_game:
        b = b.drop_duplicates(subset=["game_id"], keep="first")

    if rule in ("positive_edge", "positive_ev"):
        gate = "_k_model_edge" if rule == "positive_edge" else "_k_model_ev"
        b = (b[b[gate] > 0] if gate in b.columns else b.iloc[:0]).head(MAX_LEGS)
        if len(b) < MIN_LEGS:
            return None
    else:
        b = b.head(n)
        if len(b) < n:
            return None

    size = len(b)
    # `replay_week` re-sorts by `_p` and re-applies one-per-game, which would
    # undo the selection. Handing it exactly the chosen legs, already unique by
    # game and already in order, makes both of those no-ops.
    chosen = b.assign(_p=np.linspace(1.0, 0.5, size), game_id=range(size))
    return replay_week(chosen, size, stake)


def variants() -> list[dict]:
    """Every rule replayed. Each is decidable from the board before kickoff."""
    out = [{"name": f"{order}/{n}", "order": order, "n": n,
            "per_game": True, "rule": None}
           for order in ORDERINGS for n in SIZES]
    # Teammates allowed, published ordering only: one-per-game is a claim about
    # correlation and should have to earn its place against the version without
    # it rather than being assumed.
    out += [{"name": f"published+teammates/{n}", "order": "published", "n": n,
             "per_game": False, "rule": None} for n in SIZES]
    # And two where the week decides how many legs it has.
    out.append({"name": "positive_edge/auto", "order": "model_edge", "n": None,
                "per_game": True, "rule": "positive_edge"})
    out.append({"name": "positive_ev/auto", "order": "model_ev", "n": None,
                "per_game": True, "rule": "positive_ev"})
    return out


def random_variants() -> list[dict]:
    """The control: the same count, the same sizes, no information."""
    return [{"name": f"rand{i}/{SIZES[i % len(SIZES)]}", "order": f"rand{i}",
             "n": SIZES[i % len(SIZES)], "per_game": True, "rule": None}
            for i in range(N_RANDOM)]


def _interval(rows: list[dict], seed: int = CONTROL_SEED) -> tuple[float, float]:
    """Week-clustered, because the week is the independent unit."""
    if not rows:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    nets = np.array([r["net"] for r in rows], dtype=float)
    stakes = np.array([r["staked"] for r in rows], dtype=float)
    draws = rng.integers(0, len(rows), size=(2000, len(rows)))
    boot = nets[draws].sum(axis=1) / np.maximum(stakes[draws].sum(axis=1), 1e-9)
    return float(np.quantile(boot, 0.05)), float(np.quantile(boot, 0.95))


def _summary(name: str, rows: list[dict]) -> dict:
    staked = sum(r["staked"] for r in rows)
    returned = sum(r["returned"] for r in rows)
    lo, hi = _interval(rows)
    return {
        "name": name, "weeks": len(rows),
        "staked": staked, "returned": returned, "net": returned - staked,
        "roi": (returned - staked) / staked if staked else 0.0,
        "weeks_profitable": sum(1 for r in rows if r["net"] > 0),
        "mean_legs": float(np.mean([r["n"] for r in rows])) if rows else 0.0,
        "roi_lo": lo, "roi_hi": hi, "roi_beats_zero": bool(lo > 0),
        "top_week_share": (max(r["returned"] for r in rows) / returned
                           if returned else None),
    }


def _chooser(played: list[dict[str, dict]], baseline: str) -> tuple[dict, dict]:
    """Play the best variant so far, week by week, using only prior weeks.

    The cumulative record is updated *after* the pick, which is the whole
    difference between this and the hindsight ceiling. Getting that order wrong
    would let a week's own result choose the week's variant, which is the same
    defect as training on the test set and reads as a spectacular edge.
    """
    chosen, picks = [], []
    cum: dict[str, list[float]] = {}
    for i, week in enumerate(played):
        if not week:
            continue
        if i < BURN_IN or not cum:
            pick = baseline if baseline in week else next(iter(week))
        else:
            scored = {k: float(np.mean(v)) for k, v in cum.items()
                      if len(v) >= BURN_IN // 2 and k in week}
            pick = (max(scored, key=lambda k: scored[k]) if scored
                    else (baseline if baseline in week else next(iter(week))))
        chosen.append(week[pick])
        picks.append(pick)
        for k, r in week.items():
            cum.setdefault(k, []).append(r["net"] / r["staked"])
    summary = _summary("walk-forward chooser", chosen)
    detail = {
        "switches": sum(1 for a, b in zip(picks, picks[1:]) if a != b),
        "picks": {k: picks.count(k) for k in sorted(set(picks))},
    }
    return summary, detail


def _arm(boards: list[pd.DataFrame], specs: list[dict], stake: float,
         baseline: str) -> dict:
    """One family of variants: every summary, the ceiling, and the chooser."""
    played: list[dict[str, dict]] = []
    for board in boards:
        row = {}
        for spec in specs:
            r = play(board, spec["order"], spec["n"], spec["per_game"], stake,
                     spec["rule"])
            if r is not None:
                row[spec["name"]] = r
        played.append(row)

    summaries = []
    for spec in specs:
        rows = [w[spec["name"]] for w in played if spec["name"] in w]
        if len(rows) >= 8:
            summaries.append(_summary(spec["name"], rows))
    if not summaries:
        return {}
    summaries.sort(key=lambda s: s["roi"], reverse=True)

    ceiling = [max(w.values(), key=lambda r: r["net"]) for w in played if w]
    chooser, detail = _chooser(played, baseline)
    return {
        "variants": summaries,
        "best": summaries[0],
        "median_roi": float(np.median([s["roi"] for s in summaries])),
        "worst": summaries[-1],
        "n_positive": sum(1 for s in summaries if s["roi"] > 0),
        "n_beating_zero": sum(1 for s in summaries if s["roi_beats_zero"]),
        "ceiling": _summary("hindsight/best each week", ceiling),
        "chooser": chooser,
        "chooser_detail": detail,
    }


def _spread(values: list[float]) -> dict:
    """A control figure is a range over redraws, never a point."""
    arr = np.array(values, dtype=float)
    return {"min": float(arr.min()), "median": float(np.median(arr)),
            "max": float(arr.max()), "runs": len(values)}


def _control_summary(runs: list[dict]) -> dict:
    """The control, aggregated over its redraws.

    Every comparison against the control uses the redraws' **best** run, not
    their average. The question the control answers is "what does the best of
    44 buy you when nothing is there", so the honest opponent is the luckiest
    control, not the typical one.
    """
    if not runs:
        return {}
    return {
        "n_variants": len(runs[0]["variants"]),
        "repeats": len(runs),
        "best_roi": _spread([r["best"]["roi"] for r in runs]),
        "median_roi": _spread([r["median_roi"] for r in runs]),
        "ceiling_roi": _spread([r["ceiling"]["roi"] for r in runs]),
        "chooser_roi": _spread([r["chooser"]["roi"] for r in runs]),
        "n_positive": _spread([float(r["n_positive"]) for r in runs]),
        "n_beating_zero": _spread([float(r["n_beating_zero"]) for r in runs]),
    }


def measure(target_type: str, model: str | None = None,
            stake: float = 1.0) -> dict | None:
    """Every variant, the ceiling above them, the chooser among them — twice.

    Once on the real orderings and once on random ones, because every headline
    number this produces is uninterpretable without the second run.
    """
    weeks = load_weeks(target_type, model)
    if not weeks:
        return None
    weeks = sorted(weeks, key=lambda w: (w["season"], w["week"]))
    boards = [prepared(w["board"]) for w in weeks]
    seeds = [w["season"] * 100 + w["week"] for w in weeks]

    real = _arm(boards, variants(), stake, BASELINE)
    if not real:
        return None

    rand_specs = random_variants()
    control_runs = []
    for rep in range(CONTROL_REPEATS):
        drawn = [with_random(b, s_, rep) for b, s_ in zip(boards, seeds)]
        arm = _arm(drawn, rand_specs, stake, rand_specs[0]["name"])
        if arm:
            control_runs.append(arm)

    by_name = {s["name"]: s for s in real["variants"]}
    base = by_name.get(BASELINE)

    # Size selection on its own, which is the narrower version of the question:
    # same ordering, best N in hindsight.
    fixed_played = []
    for board in boards:
        row = {f"published/{n}": r for n in SIZES
               if (r := play(board, "published", n, True, stake, None))}
        fixed_played.append(row)
    size_ceiling = [max(w.values(), key=lambda r: r["net"])
                    for w in fixed_played if w]

    out = {
        "target_type": target_type, "model": model, "stake": stake,
        "weeks": len(weeks),
        "span": f"{weeks[0]['season']}-{weeks[-1]['season']}",
        "n_variants": len(real["variants"]),
        "burn_in": BURN_IN, "baseline": BASELINE,
        "baseline_result": base,
        "variants": real["variants"],
        "best_variant": real["best"],
        "median_variant_roi": real["median_roi"],
        "ceiling": real["ceiling"],
        "ceiling_size_only": _summary("hindsight/best size each week",
                                      size_ceiling),
        "chooser": real["chooser"],
        "chooser_detail": real["chooser_detail"],
        "control": _control_summary(control_runs),
    }

    # The family comparison, which is the only pattern here that is not a
    # single cell: `model/N` against `published/N` at matched size. One market
    # cannot corroborate it — first TD's blend does not move the number, so its
    # two families are identical to the last decimal, which checks the plumbing
    # and says nothing about the claim.
    pairs = []
    for n in SIZES:
        a, b = by_name.get(f"published/{n}"), by_name.get(f"model/{n}")
        if a and b:
            pairs.append({"n": n, "published_roi": a["roi"],
                          "model_roi": b["roi"], "gap": b["roi"] - a["roi"]})
    out["unblended_vs_published"] = {
        "sizes": pairs,
        "model_wins": sum(1 for p in pairs if p["gap"] > 0),
        "identical": all(abs(p["gap"]) < 1e-12 for p in pairs) if pairs else False,
    }

    ctl = out["control"]
    out["verdict"] = {
        "baseline_roi": base["roi"] if base else None,
        "best_variant_roi": real["best"]["roi"],
        "control_best_roi": ctl["best_roi"]["max"],
        "ceiling_roi": real["ceiling"]["roi"],
        "control_ceiling_roi": ctl["ceiling_roi"]["max"],
        "chooser_roi": real["chooser"]["roi"],
        "control_chooser_roi": ctl["chooser_roi"]["max"],
        "any_variant_beats_zero": real["n_beating_zero"] > 0,
        "chooser_beats_zero": real["chooser"]["roi_beats_zero"],
        "chooser_beats_baseline": bool(
            base and real["chooser"]["roi"] > base["roi"]),
        # The two comparisons that survive the control. A ceiling higher than
        # the control's is not one of them.
        "ceiling_beats_control": (real["ceiling"]["roi"]
                                  > ctl["ceiling_roi"]["max"]),
        "best_beats_control_best": (real["best"]["roi"]
                                    > ctl["best_roi"]["max"]),
    }
    return out


def save(stats: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats, indent=2) + "\n")
    return path


def load(path: Path) -> dict | None:
    if not Path(path).exists():
        return None
    return json.loads(Path(path).read_text())
