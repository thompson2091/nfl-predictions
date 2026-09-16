"""The dashboard's JavaScript panes, exercised in node against a stub DOM.

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
        "served": {
            "version": "2026.01.01-test", "model": "xgb",
            "note": "A test version.", "created": "2026-01-01T00:00:00+00:00",
            "verdict": "PROMOTED", "git": "8a49943",
            "recorded": {"top1": 0.5, "top3": 0.8, "top5": 0.9,
                         "games": 1000, "top1_se": 0.015},
            "problems": [], "dirty": False,
        },
        "recipe": {
            "n_features": 5, "n_families": 2,
            "families": [
                # Beta is listed first and is worth less, so a table sorted
                # by worth has to reorder them.
                {"name": "build_beta_features", "n": 1, "cols": ["b_one"],
                 "worth_top1": -0.4, "p_value": 0.62, "wins": 60, "losses": 55},
                {"name": "build_alpha_features", "n": 3,
                 "cols": ["a_one", "a_two", "a_three"],
                 "worth_top1": 2.5, "p_value": 0.0004, "wins": 40, "losses": 90},
            ],
            "unattributed": ["loose_one"],
            "ablation": {"measured": "2026-01-01T00:00:00+00:00",
                         "model": "xgb", "fresh": True},
            "seasons": [
                {"season": 2024, "games": 280, "top1": 0.48, "top3": 0.79,
                 "top5": 0.90, "auc": 0.79, "brier": 0.095},
                {"season": 2025, "games": 285, "top1": 0.51, "top3": 0.83,
                 "top5": 0.92, "auc": 0.80, "brier": 0.093},
            ],
            "source": "models/x/feature_cols.pkl",
        },
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
    # The count market's payload is a different shape from a TD market's and
    # deliberately so: a player, a line, and the same player again at another
    # book's line. `thin` is what a one-book consensus is marked with, and the
    # fixture carries one because "shown but marked" is the behaviour under
    # test — dropping it would hide the only price there is.
    "receptions": {
        "season": 2026, "week": 2, "problem": "", "model": True,
        "rows": [
            {"player_name": "Echo Slot", "team": "AAA", "game_id": "g1",
             "mu": 5.5, "point": 4.5, "odds": -105, "fair_prob": 0.478,
             "ours": 0.591, "edge_pp": 11.3, "ev": 15.4, "n_books": 6,
             "thin": False},
            {"player_name": "Foxtrot Tight", "team": "BBB", "game_id": "g1",
             "mu": 3.9, "point": 3.5, "odds": 120, "fair_prob": 0.583,
             "ours": 0.522, "edge_pp": -6.1, "ev": -8.0, "n_books": 6,
             "thin": False},
            {"player_name": "Golf Wide", "team": "CCC", "game_id": "g2",
             "mu": 2.4, "point": 1.5, "odds": 150, "fair_prob": 0.331,
             "ours": 0.661, "edge_pp": 32.9, "ev": 40.1, "n_books": 1,
             "thin": True},
        ],
        "forward": {
            "season": 2026, "pushes": 0,
            "pooled": {"n": 283, "over_rate": 0.477,
                       "model_log_loss": 0.7030, "market_log_loss": 0.6769,
                       "model_brier": 0.2540, "market_brier": 0.2422},
            "weeks": [{"week": 1, "n": 283, "over_rate": 0.477,
                       "model_log_loss": 0.7030, "market_log_loss": 0.6769,
                       "model_brier": 0.2540, "market_brier": 0.2422}],
            "beats_market": False,
            "note": "Log loss, lower is better.",
        },
    },
}


@pytest.fixture(scope="module")
def page_js(tmp_path_factory) -> Path:
    """The page's script, assembled exactly as `render` assembles it."""
    from src.export import dashboard as d

    js = "\n".join([d.JS, d.JS_PLAYERS, d.JS_COMBOS, d.JS_TEAMS,
                    d.JS_SHORTLIST, d.JS_LIKED, d.JS_LADDER,
                    d.JS_RECEPTIONS, d.JS_SERVED, d.JS_SHELL])
    p = tmp_path_factory.mktemp("liked") / "page.js"
    p.write_text(js)
    return p


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_page_script_parses(page_js):
    """A syntax error here publishes a blank page with one console message."""
    r = subprocess.run(["node", "--check", str(page_js)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _run(script: str, page_js: Path, tmp_path: Path):
    payload = tmp_path / "payload.json"
    payload.write_text(json.dumps(PAYLOAD))
    return subprocess.run(
        ["node", str(REPO / "tests" / "js" / script), str(payload), str(page_js)],
        capture_output=True, text=True, cwd=str(REPO))


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_guys_i_like(page_js, tmp_path):
    r = _run("liked_list.js", page_js, tmp_path)
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_served(page_js, tmp_path):
    """The Model tab is provenance, and provenance that is wrong is worse than
    absent — it is the page vouching for something it did not check."""
    r = _run("served.js", page_js, tmp_path)
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_ladder(page_js, tmp_path):
    """The ladder reads nothing from the payload — it prices a shape.

    Which is exactly why it needs pinning: there is no board to disagree with
    it, so a wrong multiplier or a missing caveat would look entirely
    reasonable on screen.
    """
    r = _run("ladder.js", page_js, tmp_path)
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_receptions(page_js, tmp_path):
    """The one tab whose job is to talk the reader out of the numbers on it.

    Receptions is the market this project is measurably worse at than the
    book, and the failure mode is not an exception — it is a column of positive
    disagreements rendering as though it were a bet card. So the framing is
    asserted the same way the arithmetic is.
    """
    r = _run("receptions.js", page_js, tmp_path)
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")
