"""The "Guys I like" pane, exercised in node against a stub DOM.

This pane is JavaScript inside a generated file, so the rest of this suite
cannot see it at all. What it does — a list kept per season/week/market, a
parlay over that list, every combination of it priced — has three failure modes
that already happened once while it was being written, and each is silent:

  * both parlay builders shared their legs, because the picker reached for
    `S.cover` directly rather than the state it was handed;
  * a saved player the board no longer carries has to keep a labelled row,
    because a row that vanishes looks exactly like one never added;
  * on first TD, two players from one game cannot both score first, so those
    combinations are impossible rather than merely correlated.

The payload here is synthetic and tiny. Building the real one runs six scoring
passes, and none of the behaviour above depends on a real slate — what it needs
is two markets, a same-game pair, and a player with no price.

    pytest tests/test_liked_list.py -v
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HARNESS = REPO / "tests" / "js" / "liked_list.js"


def _player(name, team, game, ours, dec=None, **kw):
    """One row of the board, with the keys the columns actually read."""
    priced = dec is not None
    row = {
        "player": name, "team": team, "game": game, "ours": ours,
        "priced": priced, "dec": dec, "model_only": ours,
        "book": (1.0 / dec if priced else None),
        "odds": ("+%d" % round((dec - 1) * 100) if priced else None),
        "odds_num": (round((dec - 1) * 100) if priced else None),
        "rank": 1, "priced_rank": 1 if priced else None, "at_rank": None,
        "diff": None, "read": "Leans", "bet_rank": 1, "bet_edge": None,
        "ev": None, "blocked": False, "best": None, "best_book": None,
        "status": None, "backing": None,
    }
    row.update(kw)
    return row


def _market(key, label, players):
    return {
        "key": key, "label": label, "season": 2026, "week": 2,
        "players": players,
        "topk": {"blended": True},
        "cover": {"max_players": 12, "rho": 0.0, "assumed_dec": 2.0,
                  "price_curve": None},
        "min_edge": 3,
        "longshot": None,
    }


PAYLOAD = {
    "built": "2026-09-16T00:00:00Z",
    "markets": [
        _market("anytime_td", "Anytime TD", [
            _player("Alpha Back", "AAA", "AAA @ BBB", 0.45, 2.20),
            _player("Bravo Back", "CCC", "CCC @ DDD", 0.40, 2.50),
            _player("Charlie End", "EEE", "EEE @ FFF", 0.30, 3.40),
            # Same fixture as Alpha, so the same-game rules have something to
            # act on; and unpriced, so a slip touching it has no price.
            _player("Delta Wide", "BBB", "AAA @ BBB", 0.25, None),
        ]),
        _market("first_td", "First TD", [
            _player("Alpha Back", "AAA", "AAA @ BBB", 0.14, 7.00),
            _player("Delta Wide", "BBB", "AAA @ BBB", 0.09, 11.0),
        ]),
    ],
}


@pytest.fixture(scope="module")
def page_js(tmp_path_factory) -> Path:
    """The page's script, assembled exactly as `render` assembles it."""
    from src.export import dashboard as d

    js = "\n".join([d.JS, d.JS_PLAYERS, d.JS_COMBOS, d.JS_TEAMS,
                    d.JS_SHORTLIST, d.JS_LIKED, d.JS_SHELL])
    p = tmp_path_factory.mktemp("liked") / "page.js"
    p.write_text(js)
    return p


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_page_script_parses(page_js):
    """A syntax error here publishes a blank page with one console message."""
    r = subprocess.run(["node", "--check", str(page_js)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_guys_i_like(page_js, tmp_path):
    payload = tmp_path / "payload.json"
    payload.write_text(json.dumps(PAYLOAD))
    r = subprocess.run(
        ["node", str(HARNESS), str(payload), str(page_js)],
        capture_output=True, text=True, cwd=str(REPO))
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")
