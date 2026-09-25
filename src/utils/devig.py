"""Removing a bookmaker's margin from a two-way price.

A book quoting Over -120 / Under -110 is not stating two probabilities that sum
to 1.09. It is stating one opinion plus a margin, and every edge calculation in
this project is a comparison against that opinion — so how the margin comes off
decides what counts as an edge.

Three methods, all parameter-free per quote:

    proportional  p_over / (p_over + p_under)
                  Splits the margin in proportion to each side's price. The
                  obvious choice, and the one this project used everywhere.

    additive      p_over - (p_over + p_under - 1) / 2
                  Splits the margin equally between the two sides. For a
                  two-outcome market this is numerically indistinguishable from
                  Shin's method (checked across p_over 0.05-0.80: agreement to
                  four decimals at every point), so Shin is not implemented
                  separately.

    power         p_over ** k, with k solved so both sides sum to 1.

They agree near 50/50 and diverge in the tails, which is exactly where the
markets here live. Measured on archived closing prices, log loss against
outcomes, split by season:

    receptions (n=20,271, near 50/50)     proportional .64092   additive .64104
    anytime TD (n=22,889, far from 50/50) proportional .23819   additive .23033

On receptions the three are a tie inside noise — a 0.0001 difference in log
loss decides nothing. On anytime TD, where the probabilities sit far from a
half, additive is ahead by 0.008, and in the direction the favorite-longshot
literature predicts: proportional de-vig under-corrects, leaving favorites
beating their "fair" price and longshots missing it.

The residual by line on receptions says the same thing. Actual minus fair, at
the 0.5 line and the 8.5 line:

    proportional   +0.0833   -0.0627
    additive       +0.0740   -0.0470
    power          +0.0684   -0.0374

Power flattens the tails most and loses on overall log loss in both markets,
which is why the default is `additive` rather than the best tail number.

**What this evidence is not.** The anytime-TD comparison rests on the only
books that ever posted a "No" side — several in 2023, then fliff and
hardrockbet in 2024, and none at all from 2025. So the method is chosen partly
on the margin habits of two books in one season. It is the best evidence
available and it is thin; a `method` argument exists so the choice can be
re-tested rather than inherited.

Nothing here is stored irrecoverably. The archive keeps `implied_prob` (the
over) and `overround` (both sides summed), so the under is always recoverable
and any method can be re-derived without spending an API credit.
"""
from __future__ import annotations

import numpy as np

#: Chosen on the measurement above: at worst noise-equivalent where the methods
#: agree, and clearly better where they diverge.
DEFAULT_METHOD = "additive"

METHODS = ("proportional", "additive", "power")


def _power(over: np.ndarray, under: np.ndarray) -> np.ndarray:
    """Solve p_over**k + p_under**k = 1 for k, per quote."""
    from scipy.optimize import brentq

    out = np.empty_like(over, dtype=float)
    for i, (a, b) in enumerate(zip(over, under)):
        try:
            k = brentq(lambda k: a ** k + b ** k - 1, 0.2, 5.0)
            out[i] = a ** k
        except ValueError:
            # No sign change in the bracket — fall back rather than raise, so a
            # single odd quote cannot take down a whole week's board.
            out[i] = a / (a + b)
    return out


def two_way(p_over, p_under, method: str = DEFAULT_METHOD):
    """Fair probability of the `over` side, with the book's margin removed.

    `p_over` and `p_under` are the raw implied probabilities, vig included, and
    normally sum to something above 1. Accepts scalars or arrays; returns the
    same shape.
    """
    if method not in METHODS:
        raise ValueError(f"unknown de-vig method {method!r}; known: {METHODS}")

    over = np.asarray(p_over, dtype=float)
    under = np.asarray(p_under, dtype=float)
    scalar = over.ndim == 0
    over, under = np.atleast_1d(over), np.atleast_1d(under)

    total = over + under
    with np.errstate(divide="ignore", invalid="ignore"):
        if method == "proportional":
            out = over / total
        elif method == "additive":
            out = over - (total - 1.0) / 2.0
        else:
            out = _power(over, under)

    # A quote that produced nothing usable stays unusable rather than becoming
    # a confident 0 or 1 that something downstream would bet into.
    out = np.where(np.isfinite(out), out, np.nan)
    out = np.clip(out, 1e-6, 1 - 1e-6)
    out = np.where(np.isfinite(total) & (total > 0), out, np.nan)
    return float(out[0]) if scalar else out
