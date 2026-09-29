"""The projection a game kicked off with, and that it stays that one."""
from __future__ import annotations

import json

import pytest

from src.export import projection_freeze as PF


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Never touch the real archive. It is the only copy of what it holds."""
    monkeypatch.setattr(PF, "ROOT", tmp_path / "projections")
    PF._CACHE.clear()
    PF._DIRTY.clear()
    yield
    PF._CACHE.clear()
    PF._DIRTY.clear()


def card(**kw):
    base = {"model_spread": -3.7, "model_total": 44.0, "model_home": 23.8,
            "model_away": 20.2, "model_win_home": 0.602, "model_win_n": 522,
            "blend": {"spread": -5.1, "total": 45.0},
            "final_home": None, "final_away": None}
    base.update(kw)
    return base


def test_an_unplayed_game_is_recorded_and_keeps_moving():
    """While it is still a forecast the projection SHOULD move: the line
    moves, the injury report lands, another week of form arrives."""
    cards = {"ATL_GB": card()}
    served, recorded = PF.settle(cards, 2026, 3)
    assert (served, recorded) == (0, 1)
    assert cards["ATL_GB"]["model_spread"] == -3.7

    # A later build with a different number overwrites the entry and is shown.
    cards = {"ATL_GB": card(model_spread=-5.2)}
    served, recorded = PF.settle(cards, 2026, 3)
    assert (served, recorded) == (0, 1)
    assert cards["ATL_GB"]["model_spread"] == -5.2
    assert PF.load(2026)["3"]["ATL_GB"]["model_spread"] == -5.2


def test_once_it_has_a_final_the_projection_stops_moving():
    """The whole point. `predict_week` runs at export time, so an archived
    week was scored by whatever the feature matrix was the day somebody
    rebuilt the site — ATL at GB ranged from -5.2 to +4.6 after it was
    played 14-35."""
    PF.settle({"ATL_GB": card(model_spread=-5.2)}, 2026, 3)

    # The same game, rebuilt after it finished, with a number that wandered.
    after = {"ATL_GB": card(model_spread=4.6, model_win_home=0.3264,
                            blend={"spread": -4.8, "total": 47.0},
                            final_home=35, final_away=14)}
    served, recorded = PF.settle(after, 2026, 3)
    assert (served, recorded) == (1, 0), "a played game must not be recorded"
    assert after["ATL_GB"]["model_spread"] == -5.2
    assert after["ATL_GB"]["model_win_home"] == 0.602
    # AND EVERYTHING DERIVED FROM IT. Freezing the model spread and letting
    # the blend be recomputed leaves a card whose adjusted number disagrees
    # with the model number it was adjusted from.
    assert after["ATL_GB"]["blend"] == {"spread": -5.1, "total": 45.0}
    # The book's own figures are NOT frozen: they come from the odds archive.
    assert "spread" not in PF.FIELDS and "win_home" not in PF.FIELDS


def test_a_later_rebuild_cannot_overwrite_what_kicked_off():
    """Two rebuilds after the fact must not walk the entry forward one step
    at a time, which is what an unconditional write would do."""
    PF.settle({"A_B": card(model_spread=-1.0)}, 2026, 3)
    for spread in (2.0, -9.0, 5.5):
        PF.settle({"A_B": card(model_spread=spread, final_home=20,
                               final_away=17)}, 2026, 3)
    assert PF.load(2026)["3"]["A_B"]["model_spread"] == -1.0


def test_a_frozen_projection_is_not_the_result_in_disguise():
    """A number recorded only once a game is final would be the result with
    extra steps. The entry has to exist BEFORE the final does."""
    played = {"A_B": card(final_home=35, final_away=14)}
    served, recorded = PF.settle(played, 2026, 9)
    assert (served, recorded) == (0, 0), (
        "a played game with nothing recorded must not record one now")
    assert PF.load(2026).get("9", {}) == {}
    # And it is reported rather than passing silently, because the fallback
    # is invisible on the page.
    assert PF.missing(played, 2026, 9) == ["A_B"]


def test_a_card_with_no_model_never_wipes_the_entry():
    """Absent is not the same as zero. A build where the game model failed
    would otherwise erase what the last good build recorded."""
    PF.settle({"A_B": card(model_spread=-1.0)}, 2026, 3)
    blank = {"A_B": {f: None for f in PF.FIELDS}}
    blank["A_B"].update({"final_home": None, "final_away": None})
    PF.settle(blank, 2026, 3)
    assert PF.load(2026)["3"]["A_B"]["model_spread"] == -1.0


def test_nothing_is_written_when_nothing_changed():
    """Rebuilding the site half a dozen times an evening must not produce
    half a dozen commits to an archive that did not move."""
    PF.settle({"A_B": card()}, 2026, 3)
    assert PF.flush(), "the first record has to be written"
    PF.settle({"A_B": card()}, 2026, 3)
    assert PF.flush() == [], "an unchanged archive was rewritten"


def test_it_survives_a_round_trip_to_disk():
    PF.settle({"A_B": card(model_spread=-2.5)}, 2026, 3)
    PF.flush()
    PF._CACHE.clear()
    assert PF.load(2026)["3"]["A_B"]["model_spread"] == -2.5
    text = PF.path(2026).read_text()
    assert json.loads(text), "the file is not valid JSON"
    # Sorted and indented, so a commit shows which game changed rather than
    # one reordered line.
    assert text.count("\n") > 3, "the archive is written as one line"


def test_a_corrupt_archive_does_not_take_the_export_down():
    PF.path(2026).parent.mkdir(parents=True, exist_ok=True)
    PF.path(2026).write_text("{not json")
    PF._CACHE.clear()
    assert PF.load(2026) == {}
    cards = {"A_B": card()}
    assert PF.settle(cards, 2026, 3) == (0, 1)


def test_the_export_freezes_after_the_blend():
    """Order matters: the blend is derived from the model spread, so freezing
    one before the other is computed leaves the two disagreeing."""
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1]
            / "scripts" / "47_export_site.py").read_text()
    blend = text.index("_attach_blend(cards)")
    freeze = text.index("_freeze_projections(cards, season, week)")
    assert blend < freeze, (
        "the projection is frozen before the blend it is blended into")


def test_the_archive_is_in_git():
    """`.gitignore` says what is not regenerable stays in the repository, and
    this is the only copy: 2026 weeks 1 and 2 have no entry because nothing
    recorded one at the time, and nothing can now."""
    import subprocess
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    r = subprocess.run(["git", "check-ignore", "-q", "archive/projections"],
                       cwd=repo)
    assert r.returncode != 0, "the projection archive is gitignored"


def test_the_training_window_is_every_prior_season():
    """Measured on 2026-09-29 and closed: recency loses.

    Walk-forward from 2019 over 1,918 games, paired per game against every
    prior season unweighted — the two most recent seasons alone were worse by
    0.266 MAE on margin (t=+2.63) and 0.555 on total (t=+5.33), and every
    exponential decay from a 1.5-season half-life to a 6-season one was
    indistinguishable from no decay at all. Monotone in the wrong direction.

    `scripts/63_recency_window.py` is the experiment. Re-run it before
    narrowing the window or adding weights; this test is here so that
    narrowing it quietly is not possible.
    """
    import inspect

    from src.models import game_model as G

    for fn in (G.walk_forward, G.predict_week):
        src = inspect.getsource(fn)
        assert 'pl.col("season") < season' in src, (
            f"{fn.__name__} no longer trains on every prior season")
        assert "sample_weight" not in src, (
            f"{fn.__name__} weights its training rows; the experiment says "
            "recency does not pay")
    assert ">= season - 2" not in inspect.getsource(G), (
        "a two-season window is back; it was measured worse on both margin "
        "and total")
