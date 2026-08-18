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

from itertools import chain, combinations

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

    df = frame.copy()
    # Where each row sat in the board handed in, kept through every filter and
    # sort below so a caller can map a slip back to its legs — which is what
    # grading one against results needs. Positional rather than the index,
    # because a board arrives from several merges and its labels need not be
    # unique.
    df["_row"] = np.arange(len(df))
    df = df.dropna(subset=["odds", "probability", "market_prob"])
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
                                  "edge_pp", "EV", "SameGame", "Legs", "_legs"])
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
    keys = cand["_row"].to_numpy()
    p_pub = cand["probability"].astype(float).to_numpy()
    p_bet = cand["bet_prob"].astype(float).to_numpy()
    p_book = cand["market_prob"].astype(float).to_numpy()
    dec = cand["decimal_odds"].astype(float).to_numpy()

    # Every combination at once, as an index matrix. Four legs from a 54-player
    # candidate list is 316,000 of them: cheap as four array multiplications
    # and prohibitive as a Python loop building a dict per row, which is what
    # this was — a four-leg board took half a minute to draw and the backtest
    # took twelve.
    idx = np.fromiter(chain.from_iterable(combinations(range(len(cand)), legs)),
                      dtype=np.int64)
    idx = idx.reshape(-1, int(legs))

    game_code = pd.factorize(pd.Series(games))[0]
    codes = game_code[idx]
    # Two legs from one game, for any pair of leg positions.
    same_game = np.zeros(len(idx), dtype=bool)
    for a in range(legs):
        for b in range(a + 1, legs):
            same_game |= codes[:, a] == codes[:, b]
    if single_winner:
        keep_rows = ~same_game
        if not keep_rows.any():
            return empty
        idx, same_game = idx[keep_rows], same_game[keep_rows]

    d = np.prod(dec[idx], axis=1)
    ours = np.prod(p_pub[idx], axis=1)
    book = np.prod(p_book[idx], axis=1)
    bet = np.prod(p_bet[idx], axis=1)
    ev = (bet * d - 1.0) * 100
    score = ev if metric == "ev" else ours

    # Materialise the top of the table only: the names, the game labels and the
    # American prices are the expensive part, and 316,000 of them are thrown
    # away. Ties at the cut-off come along so the tie-break below picks from
    # all of them rather than from wherever the partition happened to slice.
    take = min(int(top_k), len(idx))
    cut = np.partition(score, -take)[-take]
    shown = np.flatnonzero(score >= cut)
    # Stable, so identical scores stay in combination order before the
    # name tie-break in the sort below.
    shown = shown[np.argsort(-score[shown], kind="stable")]

    rows = []
    for r in shown:
        legs_idx = idx[r]
        legs_games = {games[i] for i in legs_idx}
        rows.append({
            "Players": " + ".join(names[i] for i in legs_idx),
            "Game": (next(iter(legs_games)) if len(legs_games) == 1
                     else f"{len(legs_games)} games"),
            "Odds": decimal_to_american(float(d[r])),
            "Ours": float(ours[r]) * 100,
            "Book": float(book[r]) * 100,
            "edge_pp": (float(ours[r]) - float(book[r])) * 100,
            # Judged on our pre-blend number and paid at the product of the
            # posted prices, which is the same pairing the board's own EV uses.
            "EV": float(ev[r]),
            "SameGame": bool(same_game[r]),
            "Legs": int(legs),
            # Which rows of the board this slip is, for anyone grading it —
            # in the order `Players` names them, so a caller can line per-leg
            # labels up against the names a reader is looking at. Sorting
            # these was silently pairing the first name with whichever leg had
            # the lower row number.
            "_legs": tuple(int(keys[i]) for i in legs_idx),
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
