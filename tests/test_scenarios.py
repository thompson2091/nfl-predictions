"""Roster scenarios: weighted back over the game's odds, they are the projection."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import scenarios as S  # noqa: E402


def fits():
    cells = {c: {"mult": 1.0, "h1": 0.5, "n": 500} for c in S.CELLS}
    cells["won big|over"] = {"mult": 1.3, "h1": 0.45, "n": 500}
    cells["lost big|under"] = {"mult": 0.7, "h1": 0.56, "n": 500}
    cells["lost big|over"] = {"mult": 0.7, "h1": 0.56, "n": 500}
    return {"RB|rushing_yards": {"cells": cells, "h1": 0.5, "n": 9000}}


def test_the_weighted_scenarios_return_the_projection(monkeypatch):
    probs = {"won big|over": 0.2, "close|under": 0.5, "lost big|under": 0.3}
    monkeypatch.setattr(S, "cell_probabilities", lambda card, hist=None: probs)
    got = S.for_card({"home": "SF", "away": "WAS"}, fits())
    for team in ("SF", "WAS"):
        f = got["teams"][team]["RB|rushing_yards"]
        avg = sum(c["p"] * m[0] for c, m in zip(got["cells"], f["cells"]))
        assert avg == pytest.approx(1.0, abs=1e-3), f"{team}'s scenarios drift from Props"


def test_the_away_side_reads_the_home_band_flipped(monkeypatch):
    """SF winning big is WAS losing big: its backs take the 0.7, not the 1.3."""
    probs = {"won big|over": 0.5, "lost big|under": 0.5}
    monkeypatch.setattr(S, "cell_probabilities", lambda card, hist=None: probs)
    got = S.for_card({"home": "SF", "away": "WAS"}, fits())
    keys = [c["key"] for c in got["cells"]]
    sf = got["teams"]["SF"]["RB|rushing_yards"]["cells"][keys.index("won big|over")]
    was = got["teams"]["WAS"]["RB|rushing_yards"]["cells"][keys.index("won big|over")]
    assert sf[0] > 1 > was[0]
    assert was[1] == 0.56, "the away side took the home side's first-half share"
