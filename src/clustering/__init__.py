"""Unsupervised grouping of players and of bets, behind the Player types tab.

Two lenses, both fitted on the training seasons and measured on the ones after:

    archetypes  — what kind of player is this? Clusters usage and role within
                  each position, so the answer is not "he is a running back".
    bet_shapes  — what kind of bet is this? Clusters the shape of the wager
                  itself: our number against the price, how far down the board
                  it sits, and the game it lives in.

`core` holds what they share. Nothing here decides how many groups exist — see
`core.choose_k` and the `clustering:` block in config/settings.yaml.
"""
from src.clustering import archetypes, bet_shapes, core  # noqa: F401
from src.clustering.core import CLUSTER_VERSION, load, profile, settings  # noqa: F401
