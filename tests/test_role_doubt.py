"""The market refusing to quote our lead passer is a contradiction, not a view.

Our number being far from the posted line is normal and is usually us being
right: over 67,518 graded rows a 50-100% gap comes in at 60.2% against 51.6%
where the two nearly agree. So the gap is not the signal, and a badge on it
would mark our best rows.

What is not normal is the books declining to price the passer we have leading
a team while pricing someone we rate below him. On 2026-09-28 Chicago showed
Caleb Williams at 219 projected yards with no quote anywhere, and Case Keenum,
projected 90, quoted at 166 — our Keenum number was built on him being third
choice, and left alone it published a 76-yard "edge" on the under.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "site_export", REPO / "scripts" / "47_export_site.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _pay(rows):
    return {"yards": {"passing_yards": {"rows": rows}}}


def test_an_unquoted_lead_passer_casts_doubt_on_the_one_they_do_quote(mod):
    p = _pay([
        {"player_name": "Lead", "team": "CHI", "proj": 219.3, "point": None},
        {"player_name": "Backup", "team": "CHI", "proj": 90.3, "point": 166.5},
    ])
    mod._flag_role_doubt(p, "passing_yards")
    got = {r["player_name"]: r.get("role_doubt", False)
           for r in p["yards"]["passing_yards"]["rows"]}
    assert got["Backup"] is True, "the quoted backup was not flagged"
    assert got["Lead"] is False, "the unquoted player is not the bet"


def test_a_team_the_market_agrees_with_is_left_alone(mod):
    """The ordinary case, which is nearly every team every week."""
    p = _pay([
        {"player_name": "Starter", "team": "PHI", "proj": 240.0, "point": 230.5},
        {"player_name": "Backup", "team": "PHI", "proj": 30.0, "point": None},
    ])
    mod._flag_role_doubt(p, "passing_yards")
    assert not any(r.get("role_doubt")
                   for r in p["yards"]["passing_yards"]["rows"])


def test_a_big_gap_on_its_own_is_not_flagged(mod):
    """THE MEASURED POINT. A 50-100% gap between our number and the line runs
    60.2% for us. If this fired on gap size it would mark our best work."""
    p = _pay([
        {"player_name": "Starter", "team": "SF", "proj": 90.0, "point": 230.5},
        {"player_name": "Backup", "team": "SF", "proj": 20.0, "point": None},
    ])
    mod._flag_role_doubt(p, "passing_yards")
    assert not any(r.get("role_doubt")
                   for r in p["yards"]["passing_yards"]["rows"]), (
        "a large gap was flagged; the gap is not the signal")


def test_an_unquoted_player_we_rate_lower_is_not_a_contradiction(mod):
    """Backups go unquoted constantly. Only an unquoted LEADER says anything."""
    p = _pay([
        {"player_name": "Starter", "team": "KC", "proj": 250.0, "point": 245.5},
        {"player_name": "Third", "team": "KC", "proj": 15.0, "point": None},
        {"player_name": "Second", "team": "KC", "proj": 40.0, "point": 38.5},
    ])
    mod._flag_role_doubt(p, "passing_yards")
    assert not any(r.get("role_doubt")
                   for r in p["yards"]["passing_yards"]["rows"])


@pytest.mark.parametrize("market", ["rushing_yards", "receiving_yards",
                                    "receptions"])
def test_it_does_not_touch_the_markets_where_it_would_fire_on_noise(mod, market):
    """A team has one passer, so an unpriced leader is a strong statement.
    Backs and receivers split work many ways and go unquoted for ordinary
    reasons; the same rule there marks healthy rows."""
    p = {"yards": {market: {"rows": [
        {"player_name": "Lead", "team": "CHI", "proj": 90.0, "point": None},
        {"player_name": "Other", "team": "CHI", "proj": 40.0, "point": 55.5},
    ]}}}
    mod._flag_role_doubt(p, market)
    assert not any(r.get("role_doubt") for r in p["yards"][market]["rows"])


def test_the_badge_reaches_the_row(mod):
    """A flag nothing renders is a flag nobody sees."""
    from src.export import site, v3js

    assert "role_doubt" in site.JS_SHARED or "role_doubt" in site.JS_CORE, (
        "the v3 row mapping drops the flag before the page sees it")
    assert "role_doubt" in v3js.js(), "no badge is rendered for it"
