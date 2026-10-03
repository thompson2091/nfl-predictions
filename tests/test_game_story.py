"""The game story: computed facts, written prose, and the checks between them.

**EVERY REJECTION TEST HERE IS A SENTENCE A REAL STORY PRODUCED.** The first
run on PIT at CLE came back fluent, with every digit correctly sourced, and
asserted four things that were not true: a total of 47.0 as the sum of 21.4
and 18.9, two measured rows called proxies, a negative edge read as the
favorite's advantage, and a 5-5 over/under record read as the under landing
more often. A later run invented "Tyler Wylan Wallace" from a report that said
Tylan Wallace.

`_numbers_are_sourced` passed all of it, because it checks where a digit came
from and not what was claimed about it. These tests hold the checks that
close that gap.
"""

import pytest

from src.analysis import game_story as GS


@pytest.fixture
def card():
    return {
        "game_id": "PIT_CLE", "away": "PIT", "home": "CLE",
        "kick_day": "Thursday", "kick_et": "8:15 PM ET", "prime": True,
        "spread": 2.5, "total": 37.5,
        "model_spread": 2.8, "model_total": 47.0,
        "win_home": 0.4189, "model_win_home": 0.3871,
        "blend": {"spread": 2.5, "total": 40.4},
        "away_is_short_week": True, "home_is_short_week": True,
        "away_is_off_bye": False, "home_is_off_bye": False,
        "injuries": {
            "PIT": [{"player": "Rico Dowdle", "pos": "RB", "injury": "Toe",
                     "practice": "Did not practice", "rest": False,
                     "status": None},
                    {"player": "A Rested Man", "pos": "T", "injury": "Rest",
                     "practice": "Did not practice", "rest": True,
                     "status": None}],
            "CLE": [{"player": "Tylan Wallace", "pos": "WR", "injury": "Knee",
                     "practice": "Did not practice", "rest": False,
                     "status": None}],
        },
        "matchup": {"thin": False, "rows": [
            {"label": "EPA per play", "proxy": False, "sides": [
                {"offense": "PIT", "defense": "CLE", "edge": -0.14}]},
            {"label": "Plays per game", "proxy": False, "sides": [
                {"offense": "CLE", "defense": "PIT", "edge": 4.667}]},
        ]},
        "unfold": {"thin": False, "n": 127, "dog": "CLE", "fav": "PIT",
                   "headline": {"upset": {"pct": 44.1},
                                "one_score": {"pct": 60.6},
                                "shootout": {"pct": 28.3},
                                "grind": {"pct": 29.1}}},
    }


@pytest.fixture
def payload(card):
    return {
        "games": {"cards": [card]},
        "teamform": {"last": 10, "teams": {
            "PIT": [[2026, 3 - i, "OPP", i % 2, 18, 21, 20.3, 22.0]
                    for i in range(10)],
            "CLE": [[2026, 3 - i, "OPP", i % 2, 17, 21, 16.8, 22.3]
                    for i in range(10)]}},
        "teamlines": {"inline": 10, "teams": {
            # PIT 6-4 ATS, 5-5 over, 6-4 outright. The 5-5 is the record a
            # real story called "unders hit more often".
            "PIT": [[2026, 3 - i, "OPP", i % 2, 20, 17, -2.5, 40.5,
                     1 if i < 6 else -1, 1 if i < 5 else -1,
                     1 if i < 6 else -1, -110, -110, -110, -110, -130, 110]
                    for i in range(10)],
            "CLE": [[2026, 3 - i, "OPP", i % 2, 17, 20, 2.5, 40.5,
                     1 if i < 6 else -1, 1 if i < 4 else -1,
                     1 if i < 5 else -1, -110, -110, -110, -110, 110, -130]
                    for i in range(10)]}},
    }


# ── The scoreline, which two places must agree about ────────────────────

def test_the_scoreline_is_the_blend_split_by_the_spread(card):
    """The same arithmetic `v3Projection` does on the Odds tab.

    A second derivation would put one number under "our number" in the story
    and a different one on the card above it, both correct-looking.
    """
    s = GS.scoreline(card)
    # total 40.4, spread 2.5 to the away side.
    assert s["away"] == "PIT" and s["away_pts"] == 21.4
    assert s["home"] == "CLE" and s["home_pts"] == 18.9
    assert s["lead"] == "PIT"


def test_a_card_with_no_blend_has_no_scoreline(card):
    card["blend"] = {}
    assert GS.scoreline(card) is None


# ── The facts, and what they refuse to guess ────────────────────────────

def test_a_rested_player_is_not_an_injury(card):
    """A full report lists rested starters, and a story that calls one injured
    is wrong about a person."""
    inj = GS._injuries(card)
    assert [r["player"] for r in inj["PIT"]] == ["Rico Dowdle"]


def test_the_brief_states_every_direction_in_words(payload, card):
    """No signs, because a minus is the most misread character here.

    A negative edge reached the model as a number and came back as "Pittsburgh
    counters with a slight edge". Stated in words, there is nothing to invert.
    """
    b = GS._brief(GS.facts(payload, card))
    assert "PIT's offense is worse than CLE's defense by 0.14" in b
    assert "CLE's offense is better than PIT's defense by 4.7" in b
    assert "-0.14" not in b and "negative" not in b


def test_the_brief_resolves_an_even_over_under_record(payload, card):
    """5-5 is even. A real story called it "unders have hit more often"."""
    b = GS._brief(GS.facts(payload, card))
    assert "the over and the under have landed equally often" in b
    assert "the under has landed more often" in b  # CLE, which is 4-6


def test_the_brief_gives_the_total_rather_than_inviting_the_addition(payload,
                                                                    card):
    """21.4 + 18.9 is 40.3 and the adjusted total is 40.4.

    A reader doing the sum gets a different number from the one we hold, so
    the total is stated and the addition is forbidden outright.
    """
    b = GS._brief(GS.facts(payload, card))
    assert "adjusted total of 40.4" in b
    assert "Do not add the two scores together" in b


def test_the_brief_carries_both_spellings_of_each_team(payload, card):
    """So "the Browns" is a fact rather than an unsourced proper noun."""
    b = GS._brief(GS.facts(payload, card))
    assert "PIT is the Pittsburgh Steelers." in b
    assert "CLE is the Cleveland Browns." in b


def test_rest_is_given_because_a_story_will_claim_it(payload, card):
    b = GS._brief(GS.facts(payload, card))
    assert "PIT is on a short week." in b and "CLE is on a short week." in b


# ── The four claims that got through, and now do not ────────────────────

def test_it_rejects_a_number_worked_out_from_the_facts(payload, card):
    f = GS.facts(payload, card)
    b = GS._brief(f)
    bad = ("The model projects a total of 47.0 when you add those numbers "
           "together.")
    assert GS._claims_are_safe(bad, f, b) is not None


def test_it_rejects_a_sign_the_facts_did_not_carry(payload, card):
    f = GS.facts(payload, card)
    b = GS._brief(f)
    bad = "PIT counters with an edge at negative 0.14 on EPA per play."
    assert GS._claims_are_safe(bad, f, b) is not None


def test_it_rejects_calling_a_measured_figure_a_proxy(payload, card):
    f = GS.facts(payload, card)
    b = GS._brief(f)
    assert not any(e["proxy"] for e in f["edges"])
    bad = "Those are both proxies for how the teams match up."
    assert GS._claims_are_safe(bad, f, b) is not None


def test_a_proxy_may_be_called_one_where_the_facts_say_so(payload, card):
    """The check is about sourcing, not about the word."""
    card["matchup"]["rows"][0]["proxy"] = True
    f = GS.facts(payload, card)
    b = GS._brief(f)
    assert "This is a proxy rather than a direct measurement." in b
    assert GS._claims_are_safe("That figure is a proxy.", f, b) is None


def test_it_rejects_a_name_the_facts_do_not_carry(payload, card):
    """"Tyler Wylan Wallace", from a report that said Tylan Wallace.

    Two invented tokens around one real surname, every digit in the paragraph
    sourced, and a fabricated person on a page about money.
    """
    f = GS.facts(payload, card)
    b = GS._brief(f)
    bad = "Cleveland will be without Tyler Wylan Wallace on Thursday."
    assert GS._claims_are_safe(bad, f, b) is not None


@pytest.mark.parametrize("line", [
    "Cleveland will be without Tylan Wallace on Thursday.",
    "The ball moves when the Browns need it to.",
    "It turns on the Steelers' defense holding up.",
    "Both defenses have outperformed expectations lately.",
    "In Pittsburgh this is a different game.",
])
def test_real_names_and_sentence_openers_pass(payload, card, line):
    """The check that rejects everything gets deleted rather than fixed.

    Two bugs made this reject every real name it was built to pass: a
    `rstrip` of a character set took the final s off "Jenkins", and the
    brief's own tokens kept their trailing periods so "Browns." never matched
    "Browns".
    """
    f = GS.facts(payload, card)
    assert GS._claims_are_safe(line, f, GS._brief(f)) is None


def test_an_invented_source_is_a_name_too(payload, card):
    """DVOA and the outlets that publish it are not in this project's data."""
    f = GS.facts(payload, card)
    b = GS._brief(f)
    bad = "They rank 19th in Football Outsiders DVOA against the run."
    assert GS._claims_are_safe(bad, f, b) is not None


# ── What happens when there is no key, and when prose fails ─────────────

def test_a_story_without_a_key_is_complete(payload, card):
    """Plainer, never emptier. The standard `game_notes` sets."""
    f = GS.facts(payload, card)
    st = GS.phrase(f, use_ai=False)
    assert st["written"] is False
    assert len(st["paras"]) >= 2
    assert all(p.strip() for p in st["paras"])
    # And it still carries the number the page prints beneath it.
    assert st["scoreline"]["away_pts"] == 21.4


def test_the_fallback_states_the_comparable_games_are_not_a_forecast(payload,
                                                                     card):
    f = GS.facts(payload, card)
    text = " ".join(GS.fallback(f))
    assert "not a forecast" in text


def test_every_number_in_the_fallback_is_in_its_own_brief(payload, card):
    """The template is held to the check the written version is.

    A fallback that fails it would mean the facts and the sentences built from
    them disagree, which is the bug the check exists to find.
    """
    from src.analysis.game_notes import _numbers_are_sourced
    f = GS.facts(payload, card)
    b = GS._brief(f)
    for para in GS.fallback(f):
        assert _numbers_are_sourced(para, b), para


def test_the_build_drops_the_brief_before_it_ships(payload):
    """It is the model's input, three times the length of the story, and
    nothing on the page reads it."""
    out = GS.build(payload, use_ai=False)
    assert set(out) == {"PIT_CLE"}
    assert "brief" not in out["PIT_CLE"]
    assert out["PIT_CLE"]["paras"]


def test_a_card_with_nothing_on_it_still_answers(payload):
    bare = {"game_id": "X_Y", "away": "X", "home": "Y"}
    payload["games"]["cards"] = [bare]
    out = GS.build(payload, use_ai=False)
    assert out["X_Y"]["paras"], "an empty card produced an empty story"


def test_it_rejects_a_matchup_edge_restated_backwards(payload, card):
    """The digits stay sourced and the sentence inverts.

    Audited over one real week, 30 of 46 edge statements were in a shape this
    reads and none was flipped — so this is a guard against a failure that has
    not happened yet, written because the three that did were all this shape:
    the number was right and the claim about it was not.
    """
    f = GS.facts(payload, card)
    b = GS._brief(f)
    # The facts say PIT's offense is WORSE than CLE's defense by 0.14.
    bad = "PIT's offense is better than CLE's defense by 0.14 on EPA per play."
    assert GS._claims_are_safe(bad, f, b) is not None
    good = "PIT's offense is worse than CLE's defense by 0.14 on EPA per play."
    assert GS._claims_are_safe(good, f, b) is None


def test_the_polarity_check_is_silent_on_phrasings_it_cannot_read(payload,
                                                                  card):
    """A guard that fires on correct prose is a guard that gets deleted.

    Sixteen of the week's forty-six edge statements were phrased in ways this
    does not parse. They must pass, not fail.
    """
    f = GS.facts(payload, card)
    b = GS._brief(f)
    odd = ("Where Cleveland gains ground is tempo, and the 4.667 there is the "
           "margin that matters most late.")
    assert GS._claims_are_safe(odd, f, b) is None


def test_the_story_scoreline_matches_the_projection_card(card):
    """The module docstring names this test; here it is.

    `v3Projection` on the Odds tab derives a score from the adjusted spread
    and total, and so does `scoreline`. Both are labeled "our number" on the
    same game, two sections apart, so a drift between them would show a reader
    two different projections and give them no way to tell which is ours.
    """
    b = card["blend"]
    # The JS, transcribed: hh = tot/2 - sp/2, aa = tot/2 + sp/2.
    want_home = round(b["total"] / 2 - b["spread"] / 2, 1)
    want_away = round(b["total"] / 2 + b["spread"] / 2, 1)
    s = GS.scoreline(card)
    assert (s["home_pts"], s["away_pts"]) == (want_home, want_away)


def test_the_js_and_python_derivations_are_the_same_formula():
    """Read off `v3Projection` rather than remembered, so a change to one
    without the other fails here instead of on the page."""
    from src.export.v3js import js
    src = js()
    assert "const hh = tot / 2 - sp / 2, aa = tot / 2 + sp / 2;" in src, \
        "v3Projection no longer splits the total by the spread this way"


# ── All the game's context, not just the two teams ──────────────────────

def test_receptions_projections_come_from_mu(payload, card):
    """`proj` on the yardage boards, `mu` on receptions.

    Reading only `proj` returned no receptions at all for a game that had 35
    rows of them, and an empty market looks exactly like one with nothing to
    say. `rowsFor` makes the same fallback when it builds a board row.
    """
    payload["receptions"] = {"rows": [
        {"game_id": "2026_04_PIT_CLE", "player_name": "A Receiver",
         "team": "CLE", "mu": 5.1, "point": 3.5},
    ]}
    pl = GS._players(payload, card)
    assert any(x["market"] == "receptions" and x["proj"] == 5.1 for x in pl), pl


def test_one_row_per_player_per_market(payload, card):
    """Books post alternate lines, so the same man arrives three times.

    Three rows of one quarterback would be the whole list. The line kept is
    the one nearest our projection, which is the comparison being made.
    """
    payload["yards"] = {"passing_yards": {"rows": [
        {"game_id": "2026_04_PIT_CLE", "player_name": "A Passer", "team": "PIT",
         "proj": 233.9, "point": p} for p in (202.5, 232.5, 262.5)]}}
    pl = [x for x in GS._players(payload, card) if x["market"] == "passing yards"]
    assert len(pl) == 1, pl
    assert pl[0]["line"] == 232.5, "it kept a line further from the projection"


def test_angles_are_picked_by_divergence_not_by_sample_size(payload, card):
    """Sorted by `n`, the three biggest splits on a real game were "Outdoors"
    and "On grass" at exactly 50.0% over four thousand games — true, enormous,
    and with nothing in them."""
    payload["angles"] = {
        "week": {"PIT_CLE": [["PIT", "outdoors"], ["PIT", "divisional"]]},
        "rows": [
            {"id": "outdoors", "label": "Outdoors",
             "all": {"n": 4090, "w": 2045, "l": 2045, "pct": 0.5,
                     "clears": False}},
            {"id": "divisional", "label": "Second divisional game in a row",
             "all": {"n": 533, "w": 295, "l": 238, "pct": 0.553,
                     "clears": False}},
        ]}
    got = GS._angles(payload, card)
    assert got[0]["label"] == "Second divisional game in a row", got


def test_a_thin_angle_is_left_out(payload, card):
    payload["angles"] = {
        "week": {"PIT_CLE": [["PIT", "tiny"]]},
        "rows": [{"id": "tiny", "label": "A curiosity",
                  "all": {"n": 20, "w": 15, "l": 5, "pct": 0.75,
                          "clears": False}}]}
    assert GS._angles(payload, card) == []


def test_an_angle_travels_with_its_verdict(payload, card):
    """Presented without `clears`, a 55.3% record reads as an edge the
    project has measured and rejected."""
    payload["angles"] = {
        "week": {"PIT_CLE": [["PIT", "d"]]},
        "rows": [{"id": "d", "label": "Divisional",
                  "all": {"n": 533, "w": 295, "l": 238, "pct": 0.553,
                          "clears": False}}]}
    f = GS.facts(payload, card)
    b = GS._brief(f)
    assert "does NOT clear break-even" in b
    assert "it is a record and not an edge" in b


def test_a_coach_under_the_floor_carries_no_rate(payload, card):
    """"69.4% in prime time" off 36 games is noise wearing a number, and
    `game_notes.MIN_COACH_GAMES` is the floor that stops it."""
    card["coach_away"] = "A Veteran"
    card["away_coach_games_prior"] = 144
    card["away_coach_ats_rate_prior"] = 0.5208
    card["away_coach_win_rate_prior"] = 0.5578
    card["coach_home"] = "A Rookie"
    card["home_coach_games_prior"] = 3
    card["home_coach_ats_rate_prior"] = 0.6667
    b = GS._brief(GS.facts(payload, card))
    assert "covered 52.1% across 144 previous games" in b
    assert "too few previous games for a meaningful record" in b
    assert "66.7" not in b, "it printed a rate off three games"


def test_a_split_public_is_not_worth_a_sentence(payload, card):
    """Saying "the public is divided" on every game is noise."""
    payload["games"] = {"cards": [card], "public": {"PIT_CLE": {"spreads": {
        "sides": [{"side": "PIT", "pct": 51.0, "open_pct": 50.0, "drift": 1.0},
                  {"side": "CLE", "pct": 49.0, "open_pct": 50.0,
                   "drift": -1.0}]}}}}
    assert GS._money(payload, card)["public"] == []


def test_a_lopsided_public_carries_where_it_started(payload, card):
    """A share alone says the public likes a side. The share WITH the move is
    what distinguishes the crowd being right from the crowd being faded."""
    payload["games"] = {"cards": [card], "public": {"PIT_CLE": {"spreads": {
        "sides": [{"side": "PIT", "pct": 61.3, "open_pct": 53.7,
                   "drift": 7.6}]}}}}
    b = GS._brief(GS.facts(payload, card))
    assert "61.3% of tickets are on PIT" in b
    assert "against 53.7% when it opened" in b
    assert "not the money behind them" in b


def test_the_story_says_when_a_line_has_not_moved(payload, card):
    """A line that held is a fact about the market, not a missing one."""
    payload["games"] = {"cards": [card],
                        "lines": {"PIT_CLE": {"spreads": {"open": 2.5,
                                                          "now": 2.5}}}}
    b = GS._brief(GS.facts(payload, card))
    assert "has not moved from 2.5" in b
