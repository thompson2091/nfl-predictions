"""Over/under settlement, the served blend weight, and the edge-threshold rule."""
from __future__ import annotations

import json

import polars as pl

from src.evaluation import prop_edge as E
from src.evaluation.prop_settlement import settle_rows

PRICES = pl.DataFrame({
    "game_id": ["G1", "G1", "G1", "G1"],
    "player_name_norm": ["a b", "a b", "c d", "c d"],
    "market": ["receptions"] * 4,
    "point": [2.5, 2.5, 4.5, 4.5],
    "side": ["yes", "no", "yes", "no"],
    "odds": [130.0, -160.0, -110.0, -110.0],
    "n_books": [5, 5, 5, 5],
})


def _row(name, side, line=2.5, actual=None, odds=130, won=None):
    return {"player_name": name, "game_id": "G1", "line": line, "side": side,
            "odds": odds, "actual": actual, "won": won}


def test_an_under_is_paid_at_the_unders_price_not_the_overs():
    got = settle_rows(2026, "receptions", [_row("A B", "under", actual=1, won=True)],
                      prices=PRICES, played={("G1", "a b"): 40})
    assert got[0]["odds"] == -160.0
    assert got[0]["odds_over"] == 130
    assert got[0]["won"] is True


def test_an_over_keeps_its_price():
    got = settle_rows(2026, "receptions", [_row("A B", "over", actual=3, won=True)],
                      prices=PRICES, played={("G1", "a b"): 40})
    assert got[0]["odds"] == 130


def test_a_player_who_played_and_recorded_nothing_is_graded_at_zero():
    got = settle_rows(2026, "receptions", [_row("A B", "under")],
                      prices=PRICES, played={("G1", "a b"): 22})
    assert got[0]["actual"] == 0.0 and got[0]["won"] is True and not got[0]["void"]


def test_a_player_who_did_not_play_is_void():
    got = settle_rows(2026, "receptions", [_row("A B", "under")],
                      prices=PRICES, played={})
    assert got[0]["void"] and got[0]["won"] is None


def test_a_stat_line_proves_he_played_even_if_snap_counts_miss_his_name():
    got = settle_rows(2026, "receptions", [_row("A B", "over", actual=4, won=True)],
                      prices=PRICES, played={})
    assert not got[0]["void"] and got[0]["won"] is True


def test_an_under_with_no_archived_under_price_is_not_priced_at_the_over():
    got = settle_rows(2026, "receptions", [_row("X Y", "under", actual=1, won=True)],
                      prices=PRICES, played={("G1", "x y"): 30})
    assert got[0]["odds"] is None


def test_the_input_rows_are_not_modified():
    r = _row("A B", "under", actual=1, won=True)
    settle_rows(2026, "receptions", [r], prices=PRICES, played={("G1", "a b"): 1})
    assert r["odds"] == 130 and "void" not in r


def test_one_line_per_player_game_is_the_one_nearest_his_median():
    d = pl.DataFrame({"season": [1] * 3, "week": [1] * 3, "game_id": ["G"] * 3,
                      "player_key": ["p"] * 3, "point": [199.5, 220.5, 240.5]})
    assert E.main_lines(d)["point"].to_list() == [220.5]


def test_the_rule_takes_the_side_the_edge_points_to_at_that_sides_price():
    d = pl.DataFrame({"p_blend": [0.60, 0.40, 0.52], "fair_prob": [0.50, 0.50, 0.50],
                      "price_over": [-110.0, -110.0, -110.0],
                      "price_under": [-120.0, -125.0, -110.0]})
    b = E.select(d, 5.0)
    assert b["side"].to_list() == ["over", "under"]
    assert b["price"].to_list() == [-110.0, -125.0]
    assert [round(x, 6) for x in b["edge_pp"].to_list()] == [10.0, 10.0]


def test_the_threshold_respects_its_floor_on_bets():
    d = pl.DataFrame({"p_blend": [0.9] * 10 + [0.55] * 200,
                      "fair_prob": [0.5] * 210, "y_over": [1.0] * 10 + [0.0] * 200,
                      "price_over": [-110.0] * 210, "price_under": [-110.0] * 210})
    got = E.fit_threshold([d], min_bets=150)
    # Ten certain winners at a 40pp edge would win an unfloored fit.
    assert got["threshold_pp"] is not None and got["fit_n"] >= 150


def test_the_served_blend_sits_between_live_and_validation(tmp_path):
    from src.prediction.receptions import load_blend as receptions_blend
    from src.prediction.yards import load_blend

    (tmp_path / "market_blend.json").write_text(json.dumps({"weight": 0.17}))
    assert load_blend("rushing_yards", tmp_path) == 0.17
    assert receptions_blend(tmp_path) == 0.17
    (tmp_path / "market_blend_served.json").write_text(json.dumps({"weight": 0.21}))
    assert load_blend("rushing_yards", tmp_path) == 0.21
    assert receptions_blend(tmp_path) == 0.21
    (tmp_path / "market_blend_live.json").write_text(json.dumps({"weight": 0.30}))
    assert load_blend("rushing_yards", tmp_path) == 0.30
    assert receptions_blend(tmp_path) == 0.30


# ── the prop edge rule, recorded and graded ─────────────────────────────

def test_a_void_is_not_a_loss():
    """A player who did not play is money back, not a lost bet. Graded as a
    loss he drags a rule's return down by his full stake, which is how a
    rule that never fired on him comes to look worse than it was."""
    from src.evaluation.prop_settlement import settle_rows

    rows = [{"player_name": "Did Not Play", "game_id": "2026_05_A_B",
             "line": 3.5, "side": "under", "odds": -110,
             "actual": None, "won": True}]
    got = settle_rows(2026, "receptions", rows, prices=None,
                      played={})[0]
    assert got["void"] is True
    assert got["won"] is None, "a void must not settle either way"


def test_an_under_is_paid_at_the_under_s_own_price():
    """The archive's one price is the OVER's. Paid at it, an under is
    settled at a number nobody offered — the defect this module exists for."""
    import polars as pl

    from src.evaluation.prop_settlement import settle_rows

    prices = pl.DataFrame({
        "game_id": ["2026_05_A_B"], "player_name_norm": ["real player"],
        "market": ["receptions"], "side": ["no"], "point": [3.5],
        "odds": [-145.0]})
    rows = [{"player_name": "Real Player", "game_id": "2026_05_A_B",
             "line": 3.5, "side": "under", "odds": -110,
             "actual": 2.0, "won": True}]
    got = settle_rows(2026, "receptions", rows, prices=prices,
                      played={("2026_05_A_B", "real player"): True})[0]
    assert got["odds"] == -145.0, "the under took the over's price"
    assert got["odds_over"] == -110, "the over's price is kept, not lost"
    # And with no archived under price the bet drops out rather than
    # borrowing the over's number.
    bare = settle_rows(2026, "receptions", rows, prices=prices.clear(),
                       played={("2026_05_A_B", "real player"): True})[0]
    assert bare["odds"] is None


def test_a_pick_on_a_game_that_has_not_finished_is_not_graded():
    """The Monday-night trap, in the market that just gained a rule. A week
    is not a game: `tracked_rules.unfinished` is the one definition of what
    has finished and the prop rule has to read it too."""
    import polars as pl

    from src.evaluation import tracked_rules as TR

    ids, labels = TR.unfinished(2026, 5)
    if not labels:
        pytest.skip("week 5 is complete")
    picks = TR.load().filter((pl.col("season") == "2026")
                             & (pl.col("week") == "5")
                             & (pl.col("rule") == "prop edge over threshold"))
    if picks.is_empty():
        pytest.skip("no prop picks recorded for week 5 yet")
    # Every week-5 pick sits on a game that has not kicked off, so none of
    # them can be settled yet — and the label on the pick has to be the same
    # shape `unfinished` returns, or the check silently matches nothing.
    games = set(picks["game"].to_list())
    assert games <= labels, (
        f"{sorted(games - labels)} are not labels `unfinished` would "
        f"produce — a pick whose game cannot be matched grades early")
