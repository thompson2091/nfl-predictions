"""Combinations of board rows, priced the way a book prices a parlay.

The board answers "who scores". This answers the question people actually ask
next: what if I put two or three of them on one slip. Every number here is
derived from the board's own columns — nothing is refitted, and nothing new is
claimed about any single player.

**Independence.** A combination's probability is the product of its legs'. That
is a modelling assumption, and it is the one `src/prediction/portfolio.py`
measured rather than assumed: teammate residual correlation is -0.023 and
opponents +0.007 across three seasons, small enough that the correction is
below simulation noise. `portfolio.fit_correlation` re-derives it, and the app
prints what it currently says beside this table rather than quoting these
numbers — if the model changes and the assumption stops holding, the page is
where you find out.

**First touchdown is exempt.** Exactly one player scores a game's first
touchdown, so two legs from the same game have a joint probability of zero, not
the product of theirs. `build` drops those combinations on that market instead
of printing a number for a bet that cannot win.

**Same-game combinations on anytime TD are flagged, not priced by a book.** The
price here is the product of the legs' prices, which is what a book pays for
legs in different games. A same-game parlay is priced by the book's own
correlation model and will come back shorter. The flag says: this row's price
is arithmetic, not a quote.

**The EV column is not backtested.** Every profitability figure elsewhere in
this project was measured on singles at closing prices. Multiplying legs
multiplies the model's calibration error too, and nothing here has been
replayed against results. It is what the model expects, not what it returned.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd

from src.prediction.bets import decimal_to_american

#: Ranking metrics, as the per-leg factor whose product they order. Both are
#: products of positive per-leg numbers, which is what makes the candidate
#: truncation in `build` safe: a combination containing a weak leg cannot
#: outrank the combinations built from strong ones alone.
#:
#: `ev` uses the pre-blend probability, like every other money figure in this
#: project — a bet is a disagreement with the price, and the published blend is
#: the act of conceding it. `likely` uses the published probability, because
#: that is the board's best guess at who actually scores.
METRICS = {
    "ev": ("bet_prob", "decimal_odds"),
    "likely": ("probability",),
}

#: The columns `build` needs from a board, and what it uses each one for.
REQUIRED = ("player_name", "game_label", "odds", "probability", "market_prob")


def _factor(frame: pd.DataFrame, metric: str) -> pd.Series:
    cols = METRICS[metric]
    out = frame[cols[0]].astype(float)
    for c in cols[1:]:
        out = out * frame[c].astype(float)
    return out


def pool(frame: pd.DataFrame, per_game: int) -> pd.DataFrame:
    """Each game's top `per_game` players, by the board's own ranking.

    Ranked on the published probability via `game_rank` when the caller has
    already computed it, so the pool is literally "the top N of each game as
    the board shows them" rather than a second ranking that could disagree.
    """
    missing = [c for c in REQUIRED if c not in frame.columns]
    if missing:
        raise KeyError(f"board is missing {missing}")

    df = frame.dropna(subset=["odds", "probability", "market_prob"]).copy()
    # A player the injury report has ruled out is not a long shot, he is a
    # guaranteed losing leg, and a combination is only as live as its worst one.
    if "is_blocked" in df.columns:
        df = df[~df["is_blocked"].fillna(False).astype(bool)]
    if df.empty:
        return df

    if "game_rank" not in df.columns:
        df["game_rank"] = (df.groupby("game_label")["probability"]
                           .rank(ascending=False, method="first").astype(int))
    if "decimal_odds" not in df.columns:
        from src.prediction.bets import american_to_decimal
        df["decimal_odds"] = df["odds"].astype(float).map(american_to_decimal)
    # `prob_bet` is the number a bet is judged on: our own view, before the
    # board blends it toward the price it is about to be compared against.
    # First TD publishes the model number directly and has no separate column.
    df["bet_prob"] = df["prob_bet"] if "prob_bet" in df.columns else df["probability"]

    return df[df["game_rank"] <= int(per_game)]


def build(frame: pd.DataFrame, *, legs: int = 2, per_game: int = 4,
          top_k: int = 25, metric: str = "ev", target_type: str = "anytime_td",
          max_candidates: int = 24) -> pd.DataFrame:
    """The `top_k` best combinations of `legs` players from each game's top N.

    Returns one row per combination, with the same quantities the board shows
    for one player: the price, our estimate, the bookmaker's, the gap between
    them and what $100 expects to return.

    `max_candidates` bounds the search. Combinations grow as C(n, legs) — a
    16-game slate with four players a game is 635,000 four-leg combinations —
    so the pool is cut to its strongest legs first. That cut cannot change the
    answer as long as `max_candidates` exceeds `top_k + legs`: every metric
    here is a product of positive per-leg factors, so a combination using a leg
    ranked below that cut is beaten by at least `top_k` combinations built from
    the legs above it. `n_candidates` on the result records what was searched.
    """
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {sorted(METRICS)}, got {metric!r}")
    if legs < 2:
        raise ValueError(f"a combination needs at least two legs, got {legs}")

    picked = pool(frame, per_game)
    empty = pd.DataFrame(columns=["Players", "Game", "Odds", "Ours", "Book",
                                  "edge_pp", "EV", "SameGame", "Legs"])
    if len(picked) < legs:
        return empty

    # One leg per game on a market where one player scores: the rest are not
    # long odds, they are impossible, and a product would price them as neither.
    single_winner = target_type == "first_td"

    keep = max(int(max_candidates), int(top_k) + int(legs))
    # Stable, and tie-broken by name: two legs can price to exactly the same
    # factor, and pandas' default sort would then order them by whatever the
    # array size happened to make quicksort do — so the same board rebuilt
    # twice came out in a different order.
    cand = (picked.assign(_f=_factor(picked, metric))
            .sort_values(["_f", "player_name"], ascending=[False, True],
                         kind="mergesort")
            .head(keep)
            .reset_index(drop=True))

    names = cand["player_name"].tolist()
    games = cand["game_label"].tolist()
    p_pub = cand["probability"].astype(float).to_numpy()
    p_bet = cand["bet_prob"].astype(float).to_numpy()
    p_book = cand["market_prob"].astype(float).to_numpy()
    dec = cand["decimal_odds"].astype(float).to_numpy()

    rows = []
    for idx in combinations(range(len(cand)), int(legs)):
        legs_games = {games[i] for i in idx}
        same_game = len(legs_games) < legs
        if single_winner and same_game:
            continue
        d = float(np.prod(dec[list(idx)]))
        ours = float(np.prod(p_pub[list(idx)]))
        book = float(np.prod(p_book[list(idx)]))
        bet = float(np.prod(p_bet[list(idx)]))
        rows.append({
            "Players": " + ".join(names[i] for i in idx),
            "Game": (next(iter(legs_games)) if len(legs_games) == 1
                     else f"{len(legs_games)} games"),
            "Odds": decimal_to_american(d),
            "Ours": ours * 100,
            "Book": book * 100,
            "edge_pp": (ours - book) * 100,
            # Judged on our pre-blend number and paid at the product of the
            # posted prices, which is the same pairing the board's own EV uses.
            "EV": (bet * d - 1.0) * 100,
            "SameGame": same_game,
            "Legs": int(legs),
        })

    if not rows:
        return empty

    out = pd.DataFrame(rows)
    order = "EV" if metric == "ev" else "Ours"
    out = (out.sort_values([order, "Players"], ascending=[False, True],
                           kind="mergesort")
           .head(int(top_k))
           .reset_index(drop=True))
    out.attrs["n_candidates"] = len(cand)
    out.attrs["n_pool"] = len(picked)
    out.attrs["metric"] = metric
    return out
