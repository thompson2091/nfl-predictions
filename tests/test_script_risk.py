"""Which picks hinge on the game going a particular way.

Built after Atlanta won at Green Bay by 21 as a road dog: the game model was
calibrated and the Green Bay backs were still projected on an afternoon that
did not happen. Nothing here adjusts a projection — see the module docstring
for why the association is not clean enough to justify that — it flags.
"""
import polars as pl
import pytest

from src.models import script_risk as sr


@pytest.fixture(scope="module")
def fits():
    f = sr.fit()
    if not f:
        pytest.skip("no weekly stats on disk")
    return f


def test_rushing_moves_with_the_score_and_receiving_barely_does(fits):
    """The measurement, and the reason a blanket blowout flag would be wrong.

    If everything moved together the flag could be per team. It does not:
    rushing swings half its own mean across the margin bands and receptions
    swing a tenth, so a flag that marked every pick on the losing side would
    be wrong about most of the board.
    """
    rush = fits.get("RB|rushing_yards")
    rec = fits.get("WR|receptions")
    assert rush and rec
    assert rush["swing"] > 2 * rec["swing"], (
        f"rushing {rush['swing']}, receptions {rec['swing']}")
    assert rush["script_dependent"] is True
    assert rec["script_dependent"] is False


def test_rushing_falls_when_a_team_is_behind_and_rises_when_ahead(fits):
    """Direction, not just magnitude. A sign error here would flag the safe
    picks and clear the exposed ones, and every number would still look
    plausible."""
    m = fits["RB|rushing_yards"]["mult"]
    assert m["won big"] > m["won"] > m["close"] > m["lost"] > m["lost big"]
    assert m["won big"] > 1.0 > m["lost big"]


def test_a_backs_targets_move_the_other_way(fits):
    """A team behind throws to its running back.

    The reason the model is per MARKET rather than per player: the same man's
    rushing and receiving lines are exposed to opposite scripts.
    """
    t = fits.get("RB|targets")
    if not t:
        pytest.skip("targets not fitted")
    assert t["mult"]["lost"] > t["mult"]["won"]


def test_only_involved_player_games_are_counted():
    """Otherwise every "won big" multiplier is the reserves who only play
    once a game is decided, and the number stops being about the starters
    anyone is betting."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "src/models/script_risk.py").read_text()
    body = src[src.index("def fit("):src.index("def band_probabilities")]
    assert "pl.col(stat) > 0" in body


def test_the_margin_is_read_from_the_named_team_side(monkeypatch):
    """A home/away flip would hand every away pick the home team's risk.

    Both sides of one game must not get the same band probabilities unless
    the game really is a coin flip.
    """
    from src.models import score_dist

    card = {"game_id": "ATL_GB", "home": "GB", "away": "ATL",
            "spread": -6.5, "total": 44.5}
    hist = score_dist.history()
    if hist.height < 500:
        pytest.skip("needs the real archive")
    gb = sr.band_probabilities(card, "GB", hist)
    atl = sr.band_probabilities(card, "ATL", hist)
    assert gb and atl
    assert gb["won big"] > atl["won big"], (
        "the favorite must be likelier to win big than the underdog")
    assert atl["lost big"] > gb["lost big"]


def test_risk_is_absent_rather_than_neutral_when_it_cannot_be_measured(fits):
    """A fabricated 1.0 reads as "measured and fine"."""
    card = {"home": "GB", "away": "ATL", "spread": None, "total": None}
    assert sr.risk("RB|rushing_yards", card, "GB", fits) is None
    assert sr.risk("NOPE|nothing", {"home": "GB", "away": "ATL",
                                    "spread": -6.5, "total": 44.5},
                   "GB", fits) is None


def test_nothing_here_edits_a_projection():
    """It is a flag, not an adjustment.

    The association is not clean: quarterback passing yards FALL when losing
    big, which no game-script story predicts and which "getting blown out
    usually means the offense was bad" explains at once. Using these
    multipliers to move a number would bake that backwards causation in.
    """
    from pathlib import Path

    for f in ("src/models/script_risk.py", "src/export/v3js.py"):
        src = (Path(__file__).resolve().parents[1] / f).read_text()
        for bad in ("proj * ", "proj *= ", "* scr.mult", "*= mult"):
            assert bad not in src, f"{f} applies the multiplier to a projection"
