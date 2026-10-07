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


def test_kickoff_is_the_gate_not_the_final_score():
    """THE BUG THAT COST WEEK 4 OF 2026.

    A result reaches `schedules.parquet` at the next morning's rollover, so
    on a Sunday evening every one of that afternoon's games still looks
    unplayed. Gated on a final, the freeze therefore rewrote all fifteen
    entries hours after the finals were known — the precise failure it was
    written to prevent, on the one night of the week it mattered. Gated on
    kickoff it does not need anything to have been ingested.
    """
    from datetime import datetime

    kicked = card(kick_sort="2026-10-04 13:00")
    cards = {"ATL_GB": kicked}
    before = datetime(2026, 10, 4, 12, 0)
    after = datetime(2026, 10, 4, 20, 0)

    # Before kickoff it is still a forecast and still moves.
    assert PF.settle(cards, 2026, 4, now=before) == (0, 1)

    # After kickoff, with NO final attached — which is what a Sunday-evening
    # rebuild sees — the frozen number is served and the fresh one discarded.
    cards = {"ATL_GB": card(kick_sort="2026-10-04 13:00", model_spread=99.9)}
    served, recorded = PF.settle(cards, 2026, 4, now=after)
    assert (served, recorded) == (1, 0)
    assert cards["ATL_GB"]["model_spread"] == -3.7
    assert PF.load(2026)["4"]["ATL_GB"]["model_spread"] == -3.7


def test_a_served_card_cannot_write_back_into_the_archive():
    """`blend` is a dict, so `c[f] = kept[f]` hands the card a REFERENCE to
    the stored copy. A later in-place edit anywhere downstream then mutates
    the archive in memory, the season is marked dirty, and the next flush
    writes the mutation to disk over the number that kicked off."""
    PF.settle({"ATL_GB": card()}, 2026, 4)
    PF.flush()

    cards = {"ATL_GB": card(final_home=20, final_away=17, model_spread=99.9)}
    assert PF.settle(cards, 2026, 4) == (1, 0)
    cards["ATL_GB"]["blend"]["spread"] = 404.0

    assert PF.load(2026)["4"]["ATL_GB"]["blend"]["spread"] == -5.1
    assert not PF._DIRTY, "mutating a served card marked the season dirty"


#: Week 4 of 2026, as every game stood when it kicked off. Pinned as a
#: literal rather than as a diff against the commit that broke them, because
#: a guard that depends on a hash in the history stops working at the first
#: rebase and this one has to outlive the season.
WEEK4_2026 = {
    "ARI_NYG": (-3.5, 44.0), "DAL_HOU": (-1.7, 49.4), "DEN_SF": (-4.0, 45.7),
    "DET_CAR": (-3.0, 48.2), "GB_TB": (-3.3, 50.7), "IND_WAS": (-0.2, 52.7),
    "JAX_CIN": (-7.9, 50.5), "KC_LV": (1.5, 42.3), "LAC_SEA": (-5.4, 45.3),
    "LA_PHI": (0.2, 44.8), "MIA_MIN": (-13.5, 39.4), "NE_BUF": (-5.7, 50.6),
    "NYJ_CHI": (-0.1, 43.8), "PIT_CLE": (0.4, 43.4), "TEN_BAL": (-5.2, 49.8),
}


def test_the_real_archive_still_holds_what_week_four_kicked_off_with():
    """These fifteen were overwritten once, by a commit of mine, with numbers
    computed days after the finals. They were recovered from git and they are
    the only copy; nothing regenerates them. ATL at NO is left out on
    purpose — it was still unplayed when the rest were restored, so its entry
    was legitimately still moving.
    """
    from pathlib import Path

    real = Path(__file__).resolve().parents[1] / "archive" / "projections"
    got = json.loads((real / "2026.json").read_text())["4"]
    for gid, (spread, total) in sorted(WEEK4_2026.items()):
        assert gid in got, f"{gid} lost its frozen projection"
        assert (got[gid]["model_spread"], got[gid]["model_total"]) \
            == (spread, total), f"{gid} is not the number it kicked off with"


def test_a_field_added_after_the_freeze_is_absent_not_recomputed():
    """Weeks 3 and 4 of 2026 were frozen before `model_total_centered` and
    `blend.win_home` existed. A rebuild computes both for every card, and on a
    started game that is a number the board never showed — so it is dropped,
    and the page shows nothing rather than today's figure."""
    PF.load(2026)["3"] = {"ATL_GB": {k: v for k, v in card().items()
                                     if k in PF.FIELDS}}
    cards = {"ATL_GB": card(final_home=14, final_away=35,
                            model_total_centered=41.2,
                            blend={"spread": -4.8, "total": 47.0,
                                   "win_home": 0.66})}
    PF.settle(cards, 2026, 3)
    c = cards["ATL_GB"]
    assert "model_total_centered" not in c
    assert c["blend"] == {"spread": -5.1, "total": 45.0}
    assert not PF._DIRTY, "serving a frozen game must not rewrite it"


def test_the_new_fields_are_frozen_for_games_not_yet_played():
    assert "model_total_centered" in PF.FIELDS
    cards = {"ATL_GB": card(model_total_centered=41.2,
                            blend={"spread": -5.1, "total": 45.0,
                                   "win_home": 0.66, "total_centered": 44.1})}
    PF.settle(cards, 2026, 5)
    kept = PF.load(2026)["5"]["ATL_GB"]
    assert kept["model_total_centered"] == 41.2
    assert kept["blend"]["win_home"] == 0.66
