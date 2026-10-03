"""A team's three markets, and what they did against them.

The sign of the spread is the thing these tests exist for. A cover graded off a
flipped line is not a crash and does not look like a bug: it is a league where
favorites cover 46% of the time, which reads as a finding.
"""

import polars as pl
import pytest

from src.evaluation import team_form as TF
from src.evaluation import team_lines as TL


def _sched() -> pl.DataFrame:
    """Four played weeks, one unplayed, with both sides of all three markets.

    PIT at home every week, favored by 3 on a 45 total. Week by week:
      1  30-27  PIT by 3   — lands exactly on the spread, and 57 is over
      2   3-20  CLE by 17  — PIT does not cover, under
      3  20-13  PIT by 7   — PIT covers, under
      4  24-24  a tie      — a push on the moneyline, and 48 is over
    """
    rows = []
    for wk, (hs, as_) in enumerate([(30, 27), (3, 20), (20, 13), (24, 24)], 1):
        rows.append({"season": 2026, "week": wk, "home_team": "PIT",
                     "away_team": "CLE", "home_score": hs, "away_score": as_,
                     "spread_line": 3.0, "total_line": 45.0,
                     "home_moneyline": -160, "away_moneyline": 140,
                     "home_spread_odds": -110, "away_spread_odds": -108,
                     "over_odds": -105, "under_odds": -115})
    rows.append({"season": 2026, "week": 5, "home_team": "PIT",
                 "away_team": "CLE", "home_score": None, "away_score": None,
                 "spread_line": 2.0, "total_line": 40.0,
                 "home_moneyline": -140, "away_moneyline": 120,
                 "home_spread_odds": -110, "away_spread_odds": -110,
                 "over_odds": -110, "under_odds": -110})
    return pl.DataFrame(rows)


R = {"season": 0, "week": 1, "opp": 2, "home": 3, "pf": 4, "pa": 5,
     "sp": 6, "tot": 7, "ats": 8, "ou": 9, "ml": 10, "sp_odds": 11,
     "sp_odds_opp": 12, "over_odds": 13, "under_odds": 14,
     "ml_odds": 15, "ml_odds_opp": 16}


def test_every_game_has_exactly_one_cover_and_one_non_cover():
    """The symmetry a flipped spread cannot fake.

    One side of a game covers and the other does not, always, unless it is a
    push — in which case neither does. Run over the real archive this is the
    strongest statement available about the sign, and it is the sign that
    `team_games` documents having got backwards once.
    """
    got = TL.rows_for(2026, 4)
    w = l = p = 0
    for rows in got.values():
        for r in rows:
            v = r[R["ats"]]
            if v is None:
                continue
            w += v > 0
            l += v < 0
            p += v == 0
    assert w == l, f"{w} covers against {l} non-covers — the spread is flipped"
    assert p, "no pushes at all in eleven seasons is itself suspicious"


def test_a_game_on_the_number_is_a_push_and_not_a_loss():
    """The stake comes back. Counting it as a loss understates every record.

    Week 1 was 30-27 with PIT favored by exactly 3.
    """
    got = TL.rows_for(2026, 5, schedule=_sched())
    pit = {r[R["week"]]: r for r in got["PIT"]}
    assert pit[1][R["ats"]] == TL.PUSH, pit[1]
    cle = {r[R["week"]]: r for r in got["CLE"]}
    assert cle[1][R["ats"]] == TL.PUSH, "a push is a push from both sides"


def test_the_favorite_covers_by_winning_by_more_than_the_number():
    got = TL.rows_for(2026, 5, schedule=_sched())
    pit = {r[R["week"]]: r for r in got["PIT"]}
    # Favored by 3 and won by 7.
    assert pit[3][R["ats"]] == TL.WON
    # Favored by 3 and lost by 17.
    assert pit[2][R["ats"]] == TL.LOST
    cle = {r[R["week"]]: r for r in got["CLE"]}
    # The dog getting 3 and winning by 17 covers.
    assert cle[2][R["ats"]] == TL.WON


def test_the_spread_is_in_each_teams_own_perspective():
    """Positive is favored, whoever was at home, so a column of them reads."""
    got = TL.rows_for(2026, 5, schedule=_sched())
    assert got["PIT"][0][R["sp"]] == 3.0
    assert got["CLE"][0][R["sp"]] == -3.0


def test_a_tie_is_a_push_on_the_moneyline_and_not_a_loss():
    got = TL.rows_for(2026, 5, schedule=_sched())
    for team in ("PIT", "CLE"):
        r = [x for x in got[team] if x[R["week"]] == 4][0]
        assert r[R["ml"]] == TL.PUSH, (team, r)


def test_both_sides_of_a_game_share_its_over_under():
    """The total belongs to the game, not to a team.

    `ats` and `ml` are opposite for the two sides and `ou` is identical. A
    panel that flipped the total with the perspective would show one team
    going over and its opponent going under in the same game.
    """
    got = TL.rows_for(2026, 5, schedule=_sched())
    for wk in (1, 2, 3, 4):
        pit = [r for r in got["PIT"] if r[R["week"]] == wk][0]
        cle = [r for r in got["CLE"] if r[R["week"]] == wk][0]
        assert pit[R["ou"]] == cle[R["ou"]], wk
    # 30+27 = 57 over 45; 3+20 = 23 under it.
    pit = {r[R["week"]]: r for r in got["PIT"]}
    assert pit[1][R["ou"]] == TL.WON and pit[2][R["ou"]] == TL.LOST


def test_the_price_for_fading_a_team_is_the_other_sides_real_quote():
    """Not a complement and not an assumption — the number the book posted.

    This is the one way this panel is better off than the player one, where
    the archive holds only the Yes and the Over.
    """
    got = TL.rows_for(2026, 5, schedule=_sched())
    pit = got["PIT"][0]
    assert pit[R["ml_odds"]] == -160 and pit[R["ml_odds_opp"]] == 140
    assert pit[R["sp_odds"]] == -110 and pit[R["sp_odds_opp"]] == -108
    cle = got["CLE"][0]
    assert cle[R["ml_odds"]] == 140 and cle[R["ml_odds_opp"]] == -160, \
        "the prices did not swap with the perspective"
    # The over and the under belong to the game and do not swap.
    assert pit[R["over_odds"]] == cle[R["over_odds"]] == -105
    assert pit[R["under_odds"]] == cle[R["under_odds"]] == -115


def test_the_week_being_previewed_is_not_part_of_its_own_record():
    got = TL.rows_for(2026, 3, schedule=_sched())
    assert [r[R["week"]] for r in got["PIT"]] == [2, 1]


def test_an_unplayed_game_is_not_a_game():
    got = TL.rows_for(2026, 9, schedule=_sched())
    assert [r[R["week"]] for r in got["PIT"]] == [4, 3, 2, 1]


def test_a_game_with_no_posted_line_has_no_result_against_it():
    """Null, not a loss. A row that reported LOST for want of a number would
    be a loss the team never took, and it would be counted in the record."""
    s = _sched().with_columns(
        pl.when(pl.col("week") == 2).then(None)
          .otherwise(pl.col("total_line")).alias("total_line"))
    got = TL.rows_for(2026, 5, schedule=s)
    wk2 = [r for r in got["PIT"] if r[R["week"]] == 2][0]
    assert wk2[R["ou"]] is None, "it graded a total that was never posted"
    assert wk2[R["ats"]] == TL.LOST, "the spread result went with it"


def test_the_first_six_fields_are_team_forms_in_order():
    """So the page labels a row with the formatter it already has.

    `v3PastWhen` reads r[0] and r[1]; the vs/at reading is r[3] and r[2]. A
    panel with its own date formatter would be a second place for the playoffs
    to come out numbered as week 22.
    """
    sched = _sched()
    form = TF.rows_for(2026, 5, schedule=sched)
    lines = TL.rows_for(2026, 5, schedule=sched)
    for team in ("PIT", "CLE"):
        for a, b in zip(form[team], lines[team]):
            assert a[:6] == b[:6], (team, a[:6], b[:6])


def test_a_schedule_without_prices_still_answers():
    """A missing price is a row with no money question, not a failure.

    The form fixture carries the four numbers a chart needs and none of the
    six prices, and the three results do not depend on any of them.
    """
    bare = _sched().drop(["home_moneyline", "away_moneyline",
                          "home_spread_odds", "away_spread_odds",
                          "over_odds", "under_odds"])
    got = TL.rows_for(2026, 5, schedule=bare)
    r = got["PIT"][0]
    assert r[R["ats"]] is not None and r[R["ml"]] is not None
    assert r[R["ml_odds"]] is None and r[R["over_odds"]] is None


def test_the_window_is_games_not_weeks():
    big = pl.concat([_sched().with_columns(pl.lit(s).alias("season"))
                     for s in (2024, 2025, 2026)])
    got = TL.rows_for(2026, 5, last=10, schedule=big)
    assert len(got["PIT"]) == 10
    assert {r[R["season"]] for r in got["PIT"]} == {2026, 2025, 2024}
    assert got["PIT"][0][:2] == [2026, 4], "newest first"


def test_the_whole_record_is_priced():
    """A silent join failure would empty the panel rather than break it."""
    cov = TL.coverage()
    assert cov["games"] > 3000, cov
    assert cov["rate"] > 0.99, f"only {cov['rate']:.1%} of games carry prices"


def test_ten_games_ride_in_the_page_and_the_record_is_fetched():
    """22 KB inlined against 413 KB, which is the arrangement the player
    record settled on for the same reason."""
    import importlib.util
    import json
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "se", Path(__file__).resolve().parents[1] / "scripts/47_export_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    payload: dict = {}
    mod._team_lines_block(payload, 2026, 4)
    assert "teamlines" in payload, "the page is handed no record to draw"
    tl = payload["teamlines"]
    assert len(tl["teams"]) == 32, len(tl["teams"])
    assert tl["inline"] == mod.TEAMLINES_INLINE
    assert all(len(r) <= tl["inline"] for r in tl["teams"].values())
    assert [m["key"] for m in tl["markets"]] == ["ats", "ou", "ml"]

    kb = len(json.dumps(tl)) / 1024
    assert kb < 60, f"{kb:.0f} KB inlined — this wants to be a fetched file"

    # And the whole thing is carried out separately, under a key no page ships.
    full = payload["_teamlines_full"]
    assert sum(len(r) for r in full.values()) > 6000, "the record is thin"
    assert any(len(r) > tl["inline"] for r in full.values())


@pytest.mark.parametrize("mk", ["ats", "ou", "ml"])
def test_every_market_the_page_draws_has_a_result_field(mk):
    """`V3TLM` in the JS names a result index per market, and this is the
    Python end of that contract: the field exists and is one of three values."""
    got = TL.rows_for(2026, 4, last=5)
    idx = R[mk]
    seen = {r[idx] for rows in got.values() for r in rows}
    assert seen - {TL.WON, TL.PUSH, TL.LOST, None} == set(), seen
    assert TL.WON in seen and TL.LOST in seen
