"""What combinations of the board's top players actually did.

The combinations table multiplies probabilities together and prints an expected
return. Multiplying is where a small calibration error stops being small: two
legs each 3 points too high is a slip about a fifth too likely than it should
be, and nothing in this project had ever checked that on results. This module
is that check.

It replays the section's own rule week by week over the graded backtest — take
each game's top N as the board ranked them, build every combination of L legs,
keep the best K by the same metric the app offers — and grades each slip on
whether *every* leg scored. What comes out is four numbers a reader can hold
against each other:

    landed        how often every leg scored
    we said       what we thought that chance was, averaged over the slips
    book said     the same product on the bookmaker's de-vigged prices
    return        what $100 a slip came back with, at the prices in the file
    as singles    what the same $100 came back with, split across the legs
                  as separate bets

`return` is reported twice: once whole, and once with the ten biggest wins
removed, which is how `rank_economics` judges a single-bet tier. A parlay's
profit is concentrated by construction, so the second number is the one to read
when the first looks remarkable.

The last one exists because the fourth reads like a discovery without it. A
parlay's return is roughly the single-bet return compounded — the 25 best
two-leg slips of a week draw on that week's five or six best singles, which
returned about +23% on their own, and 1.23 squared is the +57% the slips
returned. Multiplying an edge multiplies it; it does not find one. The same
arithmetic works on an edge that is not real, which is the whole risk.

`landed` against `we said` is the calibration claim, and it is the one that
matters: a table of expected values built on a probability that runs 20% hot is
a table of fiction. `return` is the money claim, measured rather than expected,
and it is allowed to disagree with the section's EV column — that column says
what the model expects, this says what happened.

**Same prices, same seasons, no refitting.** Every number comes from the
backtest files the rest of the evaluation reads, each season predicted by a
model that never trained on it. The slips are graded at the price in the file,
which is the same price `rank_economics` measures singles at, so a parlay and a
single are being judged on the same terms.

**Nothing here is a recommendation.** A configuration can show a positive
return over a few hundred slips and mean nothing: parlays are high-variance by
construction, and this measures a handful of seasons. The strip in the app
reports the count alongside the rate for exactly that reason.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.prediction import combos
from src.utils.paths import get_path

#: The grid the app can ask about: the same controls the section exposes, so
#: every setting a reader can select has been measured rather than interpolated.
#: Read off `combos.MAX_LEGS` rather than typed, so raising the control's
#: ceiling cannot quietly leave the top of its range ungraded.
#:
#: The long end is worth measuring precisely because of what it will say. A
#: twelve-leg slip lands about once in a hundred thousand, so thousands of them
#: replayed over three seasons settle almost none — and "these have never once
#: landed" is a measurement, not a gap in one.
LEG_COUNTS = tuple(range(2, combos.MAX_LEGS + 1))
METRICS = ("ev", "likely")
POOL_SIZES = (2, 3, 4, 5, 6)
#: `Show` on the section is a 5-50 slider in fives, and the strip has to
#: describe the rows underneath it, so each stop is measured on its own.
SHOW_STOPS = tuple(range(5, 55, 5))

#: What a backtest row is called, mapped to what a board calls it. The replay
#: builds a board-shaped frame rather than a second ranking of its own, so the
#: slips it grades are the slips the app would have shown that week.
COLUMNS = {
    "player_name": "player_name",
    "game_id": "game_label",
    "odds": "odds",
    # `final` is the published, blended number — the board's `Our estimate`.
    "final": "probability",
    # `prob_calibrated` is our own view before the blend, which is what every
    # money figure in this project is judged on.
    "prob_calibrated": "prob_bet",
    "market_prob": "market_prob",
    "dec": "decimal_odds",
}


def backtest_files(target_type: str, model: str) -> list[Path]:
    """The per-season backtest files for one model, newest last.

    Model-specific by name (`backtest_xgb_2025.csv`): the unprefixed files are
    an older run, and mixing the two would grade one model's slips against
    another's probabilities.
    """
    out = get_path("output", target_type)
    return sorted(out.glob(f"backtest_{model}_[0-9][0-9][0-9][0-9].csv"))


def _season(path: Path) -> int:
    return int(re.search(r"(\d{4})\.csv$", path.name).group(1))


def load_weeks(target_type: str, model: str) -> list[dict]:
    """Every graded week, as board-shaped frames ready for `combos.build`.

    Rows without a market price are dropped: a slip needs a price for every
    leg, and the section can only ever show players a book has priced.
    """
    weeks = []
    for path in backtest_files(target_type, model):
        df = pd.read_csv(path)
        have = [c for c in COLUMNS if c in df.columns]
        if "scored" not in df.columns or "week" not in df.columns:
            continue
        if not {"final", "prob_calibrated", "market_prob", "odds"} <= set(have):
            continue
        if "has_market_price" in df.columns:
            df = df[df["has_market_price"].astype(bool)]
        df = df.dropna(subset=["odds", "final", "market_prob", "scored"])
        if df.empty:
            continue
        for week, chunk in df.groupby("week"):
            board = chunk[have].rename(columns=COLUMNS).reset_index(drop=True)
            board["scored"] = chunk["scored"].to_numpy()
            weeks.append({"season": _season(path), "week": int(week),
                          "board": board})
    return weeks


def grade(board: pd.DataFrame, slips: pd.DataFrame) -> pd.DataFrame:
    """Add `landed` and `paid` to a week's slips.

    A slip lands only if every leg scored, which is the whole difference
    between this and the board: one wrong leg is the same as all of them wrong.
    `paid` is profit per unit staked, so -1 is a losing slip and +2.4 is a slip
    that returned $3.40 on $1.
    """
    if slips.empty:
        return slips.assign(landed=pd.Series(dtype=bool),
                            paid=pd.Series(dtype=float),
                            split_paid=pd.Series(dtype=float))
    scored = board["scored"].to_numpy()
    landed = np.array([bool(np.all(scored[list(legs)] == 1))
                       for legs in slips["_legs"]])
    # The price came back from `build` as American; profit per unit is what
    # the decimal form carries, so recover it from the slip's own probability
    # basis rather than re-multiplying the legs.
    from src.prediction.bets import american_to_decimal
    dec = slips["Odds"].astype(float).map(american_to_decimal).to_numpy()

    # The same money, on the same players, staked as separate bets: $50 a leg
    # on a two-leg slip rather than $100 on the slip. Without it a reader has
    # no way to see that a parlay compounds an edge rather than creating one —
    # these returns are close to the single-bet return raised to the number of
    # legs, and so is the way they fall apart if the edge is not real.
    leg_dec = board["decimal_odds"].to_numpy()
    split = np.array([
        float(np.mean(np.where(scored[list(legs)] == 1,
                               leg_dec[list(legs)] - 1.0, -1.0)))
        for legs in slips["_legs"]])
    return slips.assign(landed=landed, paid=np.where(landed, dec - 1.0, -1.0),
                        split_paid=split)


def _ex_top10(pnl: np.ndarray) -> float | None:
    """Return per $100 with the ten biggest wins removed, or None if that is
    all of them."""
    rest = np.sort(pnl)[:-10]
    return float(rest.mean() * 100.0) if len(rest) else None


def summarise(slips: pd.DataFrame) -> dict:
    """The four numbers, plus the count that says how much to trust them."""
    n = len(slips)
    if not n:
        return {"slips": 0}
    return {
        "slips": int(n),
        "landed": float(slips["landed"].mean()),
        "we_said": float(slips["Ours"].mean() / 100.0),
        "book_said": float(slips["Book"].mean() / 100.0),
        # Per unit staked, x100: dollars per $100 on every slip, flat staked.
        "return_per_100": float(slips["paid"].mean() * 100.0),
        # The same picks, same money, as separate single bets.
        "as_singles_per_100": float(slips["split_paid"].mean() * 100.0),
        # The same figure with the ten biggest wins taken out, the way
        # rank_economics judges a tier. A parlay return is concentrated by
        # construction — a two-leg first-TD slip lands about once in eighty —
        # so the headline can be a handful of afternoons, and no confidence
        # interval says so because the interval is wide for the same reason.
        "return_ex_top10": _ex_top10(slips["paid"].to_numpy()),
        "weeks": int(slips["_week"].nunique()),
    }


def replay(weeks: list[dict], *, legs: int, per_game: int, metric: str,
           target_type: str, show: int = max(SHOW_STOPS)) -> pd.DataFrame:
    """Every graded slip for one configuration, week by week."""
    out = []
    for wk in weeks:
        board = wk["board"]
        slips = combos.build(board, legs=legs, per_game=per_game, top_k=show,
                             metric=metric, target_type=target_type,
                             max_candidates=max(24, show + legs))
        if slips.empty:
            continue
        slips = grade(board, slips)
        # Where each slip sat in that week's table, so one replay answers for
        # every `Show` stop: the top 5 are the first five rows of the top 50.
        slips = slips.assign(_rank=np.arange(1, len(slips) + 1),
                             _week=f"{wk['season']}-{wk['week']:02d}",
                             _season=wk["season"])
        out.append(slips)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def measure(target_type: str, model: str) -> dict | None:
    """Replay the whole grid and return the artifact.

    One pass per (legs, pool, metric) at the deepest `Show` stop, then sliced
    by rank for the shallower ones — the top 5 of a week are the first five
    rows of its top 50, so measuring them separately would replay the same
    slips ten times to reach the same answer.
    """
    weeks = load_weeks(target_type, model)
    if not weeks:
        return None

    rows = []
    for legs in LEG_COUNTS:
        for per_game in POOL_SIZES:
            for metric in METRICS:
                graded = replay(weeks, legs=legs, per_game=per_game,
                                metric=metric, target_type=target_type)
                if graded.empty:
                    continue
                for show in SHOW_STOPS:
                    stat = summarise(graded[graded["_rank"] <= show])
                    if not stat["slips"]:
                        continue
                    rows.append({"legs": legs, "per_game": per_game,
                                 "metric": metric, "show": show, **stat})

    if not rows:
        return None
    seasons = sorted({wk["season"] for wk in weeks})
    return {
        "kind": "combo_backtest",
        "target_type": target_type,
        "model": model,
        "seasons": seasons,
        "span": f"{seasons[0]}-{seasons[-1]}" if seasons else "",
        "weeks": len({(wk["season"], wk["week"]) for wk in weeks}),
        "source": [p.name for p in backtest_files(target_type, model)],
        "fit_date": date.today().isoformat(),
        "rows": rows,
    }


def save(stats: dict, path: Path) -> None:
    Path(path).write_text(json.dumps(stats, indent=2))


def load(path: Path) -> dict | None:
    if not Path(path).exists():
        return None
    return json.loads(Path(path).read_text())


def lookup(stats: dict | None, *, legs: int, per_game: int, metric: str,
           show: int) -> dict | None:
    """The measured row for one setting of the section's controls.

    Exact only. An answer for three legs is not an answer for four, and a strip
    that quietly showed the nearest measured setting would be describing a
    different table than the one under it.
    """
    if not stats:
        return None
    for row in stats.get("rows", []):
        if (row["legs"] == legs and row["per_game"] == per_game
                and row["metric"] == metric and row["show"] == show):
            return row
    return None
