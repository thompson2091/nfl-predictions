"""The shortlist rule, replayed week by week and graded at closing prices.

`shortlist.py` filters a live board on two measurements. This asks the only
question that settles whether that is worth doing: run the same rule over every
graded week and see what it returned.

**The floor is fitted walk-forward, and it has to be.** The rule's one tunable
is the disagreement size below which closing-line value has moved against us.
Fitting it on 2023-2025 and grading it on 2023-2025 measures how well a
threshold fits the data it was chosen from. So each test season gets the floor
that *earlier seasons alone* would have produced: 2024 is screened by 2023's
answer, 2025 by 2023 and 2024's. The first season has nothing before it and is
reported as ungraded rather than quietly folded in.

That matters more here than it usually would, because the thing being fitted is
not stable. On the side these markets sell, closing-line value has decayed
season by season:

    anytime TD, we are higher     2023        2024        2025
      0-2 pts                  +0.55pp     -0.08pp     -0.50pp
      10+ pts                  +1.13pp     +0.37pp     -0.27pp

Some of that is the market: the archive held a median of 2 books a quote in
2023 and 7 to 8 by 2025, and a two-book consensus is both noisier and easier to
beat than an eight-book one. Whichever it is, a rule fitted on 2023 would have
been handed the whole board in 2025, which is exactly the mistake a
walk-forward fit exists to make visible.

**Three arms, so each filter has to earn its place.** Every priced player;
every player we rate above the price; and those the floor also clears. A rule
is only worth having if it beats the arm above it, and the interval has to say
so — `clustered_roi` resamples whole games, because bets inside a game share
their outcome drivers.

**Prices are the archived consensus close.** Line shopping is not available
historically, so every figure here understates a shopped price by roughly the
1pp `line_shopping` measures on a live slate. That is the one direction the
bias runs, and it is stated rather than corrected for.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.evaluation.clv import by_edge, hit_rows, published_predictions
from src.evaluation.combo_backtest import load_weeks
from src.evaluation.rank_economics import clustered_roi
from src.evaluation.shortlist import clv_floor

#: Price improvements to test each arm against, as a *proportion* of the
#: implied probability rather than a flat number of points. Not a measurement —
#: a sensitivity. `line_shopping` puts the best of two books about a point of
#: implied probability better than their consensus on a live slate, and the
#: archive behind these seasons held two to eight books a quote, so the honest
#: question is not "what did shopping return" but "how much better a price
#: would this rule have needed".
#:
#: Proportional because a flat point is not the same bet at both ends of a
#: board. Taking 1.5 points off a 20% player is a price 8% longer; taking it
#: off a 2% first-TD longshot leaves 0.5%, a price four times longer, which is
#: not a shopped quote but an arithmetic accident — and it printed a +554%
#: return the first time this was written the other way. Five percent of a
#: 20.6% price is 1.03 points, which is what shopping actually measured.
SHOPPING_REL = (0.025, 0.05, 0.075, 0.10)

#: The arms, weakest filter first. Each one is the previous one plus a rule, so
#: the returns are directly comparable and the difference between two rows is
#: what that rule bought.
#:
#: The last is not a rule anyone could have followed: it uses the floor fitted
#: on *every* season, including the one being graded. It is here as the
#: hindsight ceiling — the gap between it and the walk-forward shortlist is how
#: much of the screen's apparent value is knowing the answer first, and a
#: selection rule with no such gap is a selection rule that is not selecting.
ARMS = ("all priced", "we rate higher", "shortlist", "shortlist (hindsight)")


def floors_by_season(target_type: str) -> dict[int, dict | None]:
    """The floor each season would have had, from the seasons before it only.

    Only seasons that *have* a history are keyed at all: the first season on
    record cannot be screened by anything and is reported as ungraded rather
    than silently screened by itself.

    A keyed season whose value is `None` is a different thing and an
    informative one — its predecessors say the market moved against every
    disagreement size on the side you can bet, so the rule stands down and bets
    nothing that year. That is first TD in every season on record, and a replay
    that dropped those seasons instead would hide a rule declining to play
    behind a rule with no data.
    """
    rows = hit_rows(published_predictions(target_type), target_type)
    if rows is None or rows.height == 0:
        return {}
    seasons = sorted(rows["season"].unique().to_list())
    out: dict[int, dict | None] = {}
    for s in seasons:
        earlier = rows.filter(rows["season"] < s)
        if earlier.height == 0:
            continue
        out[s] = clv_floor({"by_edge": by_edge(earlier)}, "higher")
    return out


def _bets(board: pd.DataFrame, floor: dict | None,
          hindsight: dict | None = None) -> dict[str, np.ndarray]:
    """Each arm's row mask for one week's board."""
    edge_pp = (board["prob_bet"].astype(float)
               - board["market_prob"].astype(float)) * 100
    higher = (edge_pp > 0).to_numpy()
    masks = {
        "all priced": np.ones(len(board), dtype=bool),
        "we rate higher": higher,
    }
    for name, f in (("shortlist", floor), ("shortlist (hindsight)", hindsight)):
        masks[name] = (higher & (edge_pp.abs() >= float(f["lo"])).to_numpy()
                       if f else np.zeros(len(board), dtype=bool))
    return masks


#: How far below the price a player has to sit to count as a fade. The betting
#: threshold, mirrored: the same distance that would make a bet worth taking on
#: the other side.
FADE_EDGE_PP = 2.0

#: How much stricter the fade can be pushed, as the fraction of the book's own
#: number we have to be under. Reported as a ladder rather than one cut,
#: because the choice is a trade against a real number: a thin prop market
#: carries an embedded spread of roughly 1-4%, so what matters is not the
#: return but how much margin the group can carry — and that rises as the cut
#: tightens while the volume falls.
FADE_RATIOS = (1.0, 2 / 3, 1 / 2, 1 / 3)


def fade_side(weeks: list[dict], min_edge_pp: float = FADE_EDGE_PP,
              band: tuple[float, float] | None = None) -> dict | None:
    """What the half of the model nobody can buy would have been worth.

    Every other measurement here is about players we rate *above* the price,
    because that is the only side these markets sell. This one prices the other
    half: the players we rate well below it, graded on whether they scored.

    The return is what laying them at the de-vigged price would have paid —
    win `1` when he does not score, lose `p/(1-p)` when he does. That price
    does not exist: `bets.build_fade_card` measured 0 of 142 live quotes
    carrying a No side, and a book that posted one would charge margin on it.
    So the number to read is not the return but `margin_capacity`: how much a
    No price could hold back before the edge is gone. Anything a real market
    charges above that turns this from an edge into a loss.

    `exchange` prices the one venue where laying is possible at all, which
    takes commission on winnings rather than margin on the price.
    """
    pnl, scored_all, implied_all, games, ours_all = [], [], [], [], []
    for wk in weeks:
        b = wk["board"]
        if "prob_bet" not in b.columns or b.empty:
            continue
        edge_pp = (b["prob_bet"].astype(float) - b["market_prob"].astype(float)) * 100
        m = (edge_pp <= -float(min_edge_pp)).to_numpy()
        if band is not None:
            # Only where the market's own bias pays for itself. Outside it a
            # veto is still a player to leave out and laying him loses: on the
            # top two deciles the same lay returns -3% to -5%, because there
            # the book is under-pricing rather than over-pricing.
            mp = b["market_prob"].astype(float).to_numpy()
            m = m & (mp >= band[0]) & (mp <= band[1])
        if not m.any():
            continue
        scored = b["scored"].astype(float).to_numpy()[m]
        implied = b["market_prob"].astype(float).to_numpy()[m]
        pnl.append(np.where(scored == 1, -(1.0 - implied) / implied, 1.0))
        scored_all.append(scored)
        implied_all.append(implied)
        ours_all.append(b["prob_bet"].astype(float).to_numpy()[m])
        games.append(b["game_label"].to_numpy()[m])
    if not pnl:
        return None

    pnl = np.concatenate(pnl)
    scored = np.concatenate(scored_all)
    implied = np.concatenate(implied_all)
    ours_all_arr = np.concatenate(ours_all)
    hit, priced = float(scored.mean()), float(implied.mean())
    stat = clustered_roi(pnl, np.concatenate(games))
    fair_no, need_no = 1.0 - priced, 1.0 - hit
    return {
        **stat,
        "min_edge_pp": float(min_edge_pp),
        "band": (None if band is None else
                 [float(band[0]) * 100, float(band[1]) * 100]),
        "scored_pct": hit * 100,
        "priced_pct": priced * 100,
        # The whole answer in one number: how much a No price could charge
        # before this stops being worth anything.
        "margin_capacity_pct": (need_no / fair_no - 1.0) * 100,
        "exchange": [
            {"commission": c,
             "roi": float(((1 - hit) * (1 + (priced / (1 - priced)) * (1 - c)) - 1)
                          * 100)}
            for c in (0.02, 0.05)
        ],
        # The trade the venue forces: tighter cuts carry more margin and fewer
        # bets. A thin prop market embeds roughly 1-4% of spread, so the row to
        # read is `carries_pct` against that, not the return.
        "cuts": _fade_ladder(ours_all_arr, implied, scored, weeks),
    }


def _fade_ladder(ours: np.ndarray, priced: np.ndarray, scored: np.ndarray,
                 weeks: list[dict]) -> list[dict]:
    """The same group at successively stricter cuts."""
    n_weeks = max(1, len({(w["season"], w["week"]) for w in weeks}))
    out = []
    for ratio in FADE_RATIOS:
        m = ours <= priced * ratio
        if m.sum() < 200:
            continue
        hit, price = float(scored[m].mean()), float(priced[m].mean())
        out.append({
            "ratio": float(ratio),
            "n": int(m.sum()),
            "per_week": float(m.sum()) / n_weeks,
            "scored_pct": hit * 100,
            "priced_pct": price * 100,
            "carries_pct": ((1 - hit) / (1 - price) - 1) * 100,
        })
    return out


def _fade_band(target_type: str) -> tuple[float, float] | None:
    """The deciles where laying at the de-vigged price clears zero.

    Read off `market_shape.json` rather than written here: the band is a fact
    about the market and it will move, and a hand-picked one would go on
    describing a market that has changed.
    """
    from src.evaluation.market_shape import load
    from src.utils.paths import get_path

    d = load(get_path("output", target_type) / "market_shape.json") or {}
    b = d.get("fade_band")
    if not b:
        return None
    return (b["book_lo_pct"] / 100.0, b["book_hi_pct"] / 100.0)


def shopped_returns(dec: np.ndarray, won: np.ndarray) -> list[dict]:
    """The same bets at prices a little better than the ones they got.

    Separate from `replay` so it can be checked on its own: the first version
    subtracted a flat number of points from the implied probability, which at
    first-TD prices took a 2% shot to 0.5% and reported a +554% return. A
    proportion cannot do that, and this is where that is guaranteed.
    """
    out = []
    for rel in SHOPPING_REL:
        implied = (1.0 / dec) * (1.0 - rel)
        better = np.where(won == 1, 1.0 / implied - 1.0, -1.0)
        out.append({
            "relative": rel,
            # The same improvement in the units a price is quoted in, at these
            # prices, so it can be read against what line shopping measures.
            "mean_pp": float(np.mean(1.0 / dec) * rel * 100),
            "roi": float(better.mean() * 100),
        })
    return out


def replay(target_type: str, model: str) -> dict | None:
    """Every arm, graded week by week, per season and pooled.

    Profit is per unit staked at the archived closing price: a winner returns
    `decimal - 1` and a loser -1, flat stakes throughout. Flat because a Kelly
    ladder would make the answer depend on a bankroll rule that has never been
    measured either, and the question here is whether the selection is worth
    anything at all.
    """
    weeks = load_weeks(target_type, model)
    if not weeks:
        return None
    floors = floors_by_season(target_type)
    if not floors:
        return None
    # The floor a reader would see on the live screen today: fitted over every
    # season at once, and therefore over the ones it is about to be graded on.
    rows = hit_rows(published_predictions(target_type), target_type)
    hindsight = clv_floor({"by_edge": by_edge(rows)}, "higher") if rows is not None else None

    from src.prediction.bets import american_to_decimal

    graded: list[dict] = []
    skipped: list[int] = []
    for wk in weeks:
        season = wk["season"]
        if season not in floors:
            # No earlier season to fit a floor from. Nothing here is gradable,
            # including the unfiltered arms, because a comparison across a
            # different set of weeks is not a comparison.
            if season not in skipped:
                skipped.append(season)
            continue
        board = wk["board"]
        if "prob_bet" not in board.columns or board.empty:
            continue
        dec = (board["decimal_odds"].astype(float).to_numpy()
               if "decimal_odds" in board.columns
               else board["odds"].astype(float).map(american_to_decimal).to_numpy())
        scored = board["scored"].astype(float).to_numpy()
        pnl = np.where(scored == 1, dec - 1.0, -1.0)
        masks = _bets(board, floors[season], hindsight)
        for arm, m in masks.items():
            if not m.any():
                # A week the rule declined to bet is a week it staked nothing,
                # which is a return of zero rather than a missing observation.
                # Kept out of the pooled arithmetic and counted in `stood_down`
                # below, so "bet nothing" cannot read as "was not measured".
                continue
            graded.append({
                "arm": arm, "season": season, "week": wk["week"],
                "pnl": pnl[m], "won": scored[m],
                "dec": dec[m],
                "game": board["game_label"].to_numpy()[m],
            })

    if not graded:
        return {"kind": "shortlist_backtest", "target_type": target_type,
                "model": model, "arms": [], "seasons": [],
                "skipped_seasons": skipped, "floors": {}, "hindsight_floor": None,
                "priced_at": "archived consensus close",
                "note": "No season had an earlier one to fit a floor from."}

    def _agg(rows: list[dict]) -> dict:
        pnl = np.concatenate([r["pnl"] for r in rows])
        won = np.concatenate([r["won"] for r in rows])
        dec = np.concatenate([r["dec"] for r in rows])
        games = np.concatenate([r["game"] for r in rows])
        stat = clustered_roi(pnl, games)
        hit = float(won.mean() * 100)
        breakeven = float(np.mean(1.0 / dec) * 100)
        # What the same bets return at prices a point or two better. The
        # improvement is applied to the implied probability, which is where a
        # shopped price actually shows up, and never below a floor that would
        # invent a payout no book could post.
        shopped = shopped_returns(dec, won)
        return {**stat,
                "hit_pct": hit,
                "shopped": shopped,
                # How far from paying for itself, in the units a price is
                # quoted in. This is the number that says what would have to
                # change: 2.1 points of implied probability is not a modelling
                # problem, it is roughly twice what line shopping is worth.
                "breakeven_gap_pp": breakeven - hit,
                # What the prices demanded. A hit rate above it is the whole
                # game; the two are printed together so neither can be read
                # without the other.
                "breakeven_pct": breakeven,
                "median_odds": float(np.median(dec)),
                "weeks": len({(r["season"], r["week"]) for r in rows}),
                "return_per_100": float(pnl.mean() * 100),
                "bets_per_week": float(len(pnl) / max(1, len({(r["season"], r["week"])
                                                              for r in rows}))),
                }

    seasons = sorted({r["season"] for r in graded})
    gradable_weeks = {(r["season"], r["week"]) for r in graded}
    arms = []
    for arm in ARMS:
        rows = [r for r in graded if r["arm"] == arm]
        if not rows:
            arms.append({"arm": arm, "pooled": None, "by_season": [],
                         "stood_down_weeks": len(gradable_weeks),
                         "note": "the rule bet nothing in any gradable week"})
            continue
        weeks_bet = {(r["season"], r["week"]) for r in rows}
        entry = {"arm": arm, "pooled": _agg(rows), "by_season": [],
                 "stood_down_weeks": len(gradable_weeks - weeks_bet)}
        for s in seasons:
            part = [r for r in rows if r["season"] == s]
            if part:
                entry["by_season"].append({"season": s, **_agg(part)})
        arms.append(entry)

    return {
        "kind": "shortlist_backtest",
        # The half of the model that measures best and that no book will sell.
        # Graded over every week, not only the ones with a floor: nothing about
        # it depends on a threshold fitted from closing-line value.
        "fade": fade_side(weeks),
        # The same group restricted to the deciles where the market's own bias
        # pays — the list both surfaces actually show. Kept beside the
        # unrestricted number rather than replacing it, because the difference
        # between them is the price band doing work.
        "fade_in_band": fade_side(weeks, band=_fade_band(target_type)),
        "target_type": target_type, "model": model,
        "seasons": seasons, "skipped_seasons": skipped,
        "hindsight_floor": (None if hindsight is None else
                            {"lo": hindsight["lo"], "n": hindsight["n"],
                             "mean_move_pp": hindsight["mean_move_pp"]}),
        "floors": {str(s): (None if f is None else
                            {"lo": f["lo"], "n": f["n"],
                             "mean_move_pp": f["mean_move_pp"]})
                   for s, f in floors.items()},
        "arms": arms,
        "priced_at": "archived consensus close",
        "note": ("Every figure is measured at the consensus close, so a shopped "
                 "price would have returned about a point more per bet."),
    }
