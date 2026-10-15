"""The board's display rules, tested without standing up Streamlit.

These decide what the app is allowed to claim about a row — which tier it
falls into, whether a set of plays is worth totalling up, how a return is
phrased. All of it used to live inside app.py where nothing could reach it.

Fixtures mirror the real shape of `output/<market>/rank_economics.json`; the
key names here were read off that artifact rather than invented.
"""
import pandas as pd
import pytest

from src.presentation import board as bp


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def tiers() -> dict:
    """A fitted highlight rule, shaped like the real artifact."""
    return {
        "edge_cut": 0.01,
        "max_rank": 5,
        "big_edge": 0.10,
        "exclude_below_odds": -200,
        "tiers": [
            {"tier": "strong", "n": 778, "roi": 30.0, "lo": 18.8, "hi": 41.6,
             "roi_ex_top10": 4.2, "hit_pct": 44.6, "bets_per_week": 6.0,
             "verdict": "positive", "concentration": 0.31,
             "per_season": [{"season": 2024, "roi": 37.3},
                            {"season": 2025, "roi": 27.8}]},
            {"tier": "standard", "n": 900, "roi": 8.0, "lo": 1.0, "hi": 15.0,
             "roi_ex_top10": -1.0, "hit_pct": 38.0, "bets_per_week": 11.0,
             "verdict": "positive", "concentration": 0.2,
             "per_season": [{"season": 2024, "roi": 9.0},
                            {"season": 2025, "roi": 7.0}]},
        ],
        "fade": {"tier": "fade", "n": 1226, "edge_at_most": -0.10,
                 "implied_pct": 33.7, "actual_pct": 10.1, "bets_per_week": 18.9},
    }


@pytest.fixture
def rule(tiers) -> dict:
    return {"edge_cut": 0.01, "tiers": tiers, "games": 1130, "span": "2023-2025"}


@pytest.fixture
def frame() -> pd.DataFrame:
    """One row per tier the rule can assign, plus two that must stay blank."""
    return pd.DataFrame([
        # strong: rank ok, edge over big_edge, price above the floor
        {"bet_rank": 1, "model_edge_pp": 15.0, "odds": 175, "edge_pp": 9.0,
         "game_rank": 1, "ev_model_pct": 20.0, "prob_bet": 0.44},
        # standard: over edge_cut, under big_edge
        {"bet_rank": 3, "model_edge_pp": 5.0, "odds": 120, "edge_pp": 3.0,
         "game_rank": 3, "ev_model_pct": 6.0, "prob_bet": 0.38},
        # fade: far below the book
        {"bet_rank": 9, "model_edge_pp": -18.0, "odds": 150, "edge_pp": -11.0,
         "game_rank": 9, "ev_model_pct": -30.0, "prob_bet": 0.10},
        # blank: rank too deep for a backing tier
        {"bet_rank": 8, "model_edge_pp": 15.0, "odds": 175, "edge_pp": 9.0,
         "game_rank": 8, "ev_model_pct": 20.0, "prob_bet": 0.30},
        # blank: price shorter than the floor
        {"bet_rank": 2, "model_edge_pp": 15.0, "odds": -250, "edge_pp": 9.0,
         "game_rank": 2, "ev_model_pct": 20.0, "prob_bet": 0.70},
    ])


# ── Money formatting ────────────────────────────────────────────────────────
#
# The regression that motivated splitting these apart: they were both called
# `_money`, the second definition replaced the first at import, and the file
# was correct only because of where the call sites happened to sit.


def test_the_two_money_formatters_are_not_interchangeable():
    """Same input, two different and both-correct readings. Hence two names."""
    assert bp.signed_money(12.0) == "+\\$12.00"
    assert bp.roi_money(12.0) == "\\$112 back on every \\$100 staked"
    assert bp.signed_money(12.0) != bp.roi_money(12.0)


def test_signed_money_puts_the_sign_outside_the_symbol():
    assert bp.signed_money(-7.5) == "-\\$7.50"
    assert bp.signed_money(0.0) == "+\\$0.00"
    assert bp.signed_money(1234.5, 0) == "+\\$1,234"
    # A metric value is plain text, where the markdown escape would print.
    assert bp.signed_money(12.0, 0, escape=False) == "+$12"


def test_roi_money_translates_a_percentage_into_a_stake():
    assert bp.roi_money(-25.0) == "\\$75 back on every \\$100 staked"
    assert bp.roi_money(None) == "—"


def test_american_prices():
    assert bp.american(175) == "+175"
    assert bp.american(-115) == "-115"
    assert bp.american(None) == "—"
    assert bp.american(float("nan")) == "—"


# ── Row verdicts ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("edge_pp,expected", [
    (0.0, "Matches book"), (1.5, "Matches book"), (2.0, "Matches book"),
    (-2.0, "Matches book"),
    (3.0, "Leans"), (5.0, "Leans"),
    (9.0, "Strong call"),
    (-3.0, "Veto"), (-9.0, "Veto"),
])
def test_confidence_labels_the_gap_not_the_certainty(edge_pp, expected):
    assert bp.confidence(edge_pp, lo=0.02, hi=0.05) == expected


def test_a_gap_below_the_price_is_a_refusal_and_not_a_call():
    """It used to be symmetric, and that put a bet on a player to avoid.

    -9pp and +9pp are the same size of disagreement and opposite instructions.
    Two measurements say the down side is the sharper one — the closing line
    moves our way when we are lower and stands still when we are higher, and
    the head-to-head on big disagreements is far stronger on the players we
    rate down — and these markets only sell the Yes side, so there is nothing
    to bet there. A row that reads "Strong call" on one of them is the single
    most expensive label this board could carry.
    """
    assert bp.confidence(7.0, 0.02, 0.05) == "Strong call"
    assert bp.confidence(-7.0, 0.02, 0.05) == "Veto"
    # And a slip inherits it: one leg we rate under its price is the leg that
    # ends the slip, whatever the others read.
    assert bp.combo_read(["Strong call", "Veto"]) == "Veto"
    assert bp.READ_ORDER[0] == "Veto"


# ── The verdict is gated on the money ───────────────────────────────────────


def test_a_disagreement_that_does_not_pay_is_not_a_call():
    """THE BUG. `lo` and `hi` are a spread, and a spread is not a price.

    They are the 33rd and 66th percentiles of how far this model usually sits
    from the market — the right way to say "unusually far" and silent on
    whether the bet pays. First touchdown's 66th percentile is 1.44pp and
    anytime's is 2.19pp, neither of them near what it takes to clear the vig
    on a longshot. Measured on the live board 2026-10-07: 84 of 166 rows
    reading "Strong call" lost money per $100, and 75 of 112 "Leans".

    Jahmyr Gibbs's first touchdown read "Strong call" at +300 while returning
    -$28.50 per $100. Both numbers were right. The verdict had simply never
    been asked about the price.
    """
    # The real row: +1.9pp of disagreement, -$28.50 per $100.
    assert bp.confidence(1.9, 0.0063, 0.0144) == "Strong call", (
        "the percentile is unchanged and still clears the fitted cut")
    assert bp.confidence(1.9, 0.0063, 0.0144, -28.5) == "Pass"
    # A Leans that does not pay is a Pass too, not a smaller call.
    assert bp.confidence(1.0, 0.0063, 0.0144, -34.1) == "Pass"


def test_a_disagreement_that_does_pay_keeps_its_label():
    """The gate is a floor on the money, not a second opinion about the edge."""
    assert bp.confidence(7.0, 0.02, 0.05, 12.4) == "Strong call"
    assert bp.confidence(3.0, 0.02, 0.05, 4.1) == "Leans"


def test_a_row_with_no_price_is_labelled_the_way_it_always_was():
    """`ev_pct` is optional because an unpriced row has no EV to clear.

    Defaulting it to zero would turn every player no book is quoting into a
    Pass, which reads as a refusal where the truth is that there is nothing
    to refuse.
    """
    assert bp.confidence(7.0, 0.02, 0.05, None) == "Strong call"
    assert bp.confidence(7.0, 0.02, 0.05) == "Strong call"


def test_the_gate_never_touches_a_veto_or_a_match():
    """A veto is the opposite instruction and has no EV to clear: these
    markets only sell the Yes side, so there is no bet whose price could
    disqualify it. A match is already "not a bet"."""
    assert bp.confidence(-7.0, 0.02, 0.05, -50.0) == "Veto"
    assert bp.confidence(-7.0, 0.02, 0.05, 50.0) == "Veto"
    assert bp.confidence(0.5, 0.02, 0.05, -50.0) == "Matches book"


def test_a_pass_leg_is_what_a_slip_containing_it_reads():
    """Weakest leg wins, and `Pass` sits between the refusal and the shrug:
    a leg whose price kills it is not a bet, which says more than having no
    opinion and less than being told to take the other side."""
    assert bp.combo_read(["Strong call", "Pass"]) == "Pass"
    assert bp.combo_read(["Pass", "Matches book"]) == "Pass"
    assert bp.combo_read(["Pass", "Veto"]) == "Veto"
    assert bp.READ_ORDER.index("Pass") == 1


def test_both_rendered_copies_of_read_order_know_the_new_label():
    """READ_ORDER exists three times — here, in `dashboard.py`'s JavaScript
    and in `page.py`'s. A label the JavaScript does not know scores -1 in
    `indexOf`, and `READ_ORDER[-1]` is `undefined`: the slip's read goes
    blank rather than wrong, which is how a missing label hides.
    """
    import inspect

    from src.export import dashboard, page

    for mod in (dashboard, page):
        line = [ln for ln in inspect.getsource(mod).splitlines()
                if "READ_ORDER = [" in ln]
        assert line, f"{mod.__name__} no longer declares READ_ORDER"
        assert "'Pass'" in line[0], (
            f"{mod.__name__} READ_ORDER is missing Pass: {line[0].strip()}")


def test_the_board_hands_confidence_the_money_and_ships_both_bases():
    """`ev_pct` is optional, so forgetting it at the call site is silent.

    It is optional for a reason — an unpriced row has no EV — which means the
    gate is only a gate on the one path that passes it, and a call site is a
    thing a merge reverts without failing anything.

    The second half is the other half of the same fault: `diff` is Adjusted
    minus Book while `ev` is the raw model against the raw price. Handed one
    of each, a reader cannot reconcile them. `bets.py` computes both already.
    """
    from pathlib import Path

    src = Path("scripts/34_export_dashboard.py").read_text()
    assert "bp.confidence(" in src, "the board no longer labels a row at all"
    # The call wraps across lines, so read a window from it rather than one
    # line. Wide enough for the wrap, narrow enough that it cannot reach the
    # next `ev_model_pct` in the file — the `"ev"` field, 4 lines further on.
    for i in (m for m in range(len(src)) if src.startswith("bp.confidence(", m)):
        assert "ev_model_pct" in src[i:i + 140], (
            "the verdict is not being asked about the price: "
            + src[i:i + 140])
    assert '"ev_adj": _f(r.get("ev_pct"))' in src, (
        "the blend's own per-$100 is not shipped beside the model's")


# ── Tier assignment ─────────────────────────────────────────────────────────


def test_highlight_tier_assigns_each_row_its_measured_tier(frame, rule):
    assert list(bp.highlight_tier(frame, rule)) == [
        "Strong", "Standard", "Fade", "", "",
    ]


def test_price_floor_excludes_short_favourites(frame, rule):
    """A -250 favorite with a big edge is still not a backing tier."""
    assert bp.highlight_tier(frame, rule).iloc[4] == ""
    del rule["tiers"]["exclude_below_odds"]
    assert bp.highlight_tier(frame, rule).iloc[4] == "Strong"


def test_fade_ignores_rank_and_price(rule):
    """The clearest fades sit well down our own list, so no rank filter."""
    deep = pd.DataFrame([{"bet_rank": 40, "model_edge_pp": -25.0, "odds": -400}])
    assert bp.highlight_tier(deep, rule).iloc[0] == "Fade"


def test_a_tier_that_stops_clearing_its_bar_stops_being_marked(frame, rule):
    rule["tiers"]["tiers"] = [t for t in rule["tiers"]["tiers"]
                              if t["tier"] != "strong"]
    marks = bp.highlight_tier(frame, rule)
    assert "Strong" not in set(marks)
    # Standard is defined as a disagreement *between* edge_cut and big_edge, so
    # a big-edge row does not fall back into it — it goes unmarked. Withdrawing
    # a tier withdraws its rows rather than demoting them into a weaker claim.
    assert marks.iloc[0] == ""
    assert marks.iloc[1] == "Standard"


def test_no_fitted_tiers_marks_nothing(frame):
    assert bp.highlight_tier(frame, {"tiers": None}) == ""
    assert bp.highlight_tier(frame, {"tiers": {"tiers": [], "fade": None}}) == ""


# ── Pre-blend column decision ───────────────────────────────────────────────


def test_preblend_columns_are_drawn_only_when_they_differ(frame):
    assert bp.preblend_columns_differ(frame) is True


def test_an_unblended_market_hides_the_duplicate_pair():
    """First TD is not blended, so Bet # is # and Bet edge is Difference."""
    same = pd.DataFrame([{"bet_rank": 1, "game_rank": 1,
                          "model_edge_pp": 4.0, "edge_pp": 4.0}])
    assert bp.preblend_columns_differ(same) is False


def test_missing_columns_are_not_a_difference():
    assert bp.preblend_columns_differ(pd.DataFrame([{"bet_rank": 1}])) is False


# ── Slate arithmetic ────────────────────────────────────────────────────────


def test_slate_expectation_totals_the_marked_plays(frame, rule):
    text = bp.slate_expectation(frame, rule)
    # Strong + Standard only — the fade and the two blanks are not plays.
    assert "each of the 2 marked plays" in text
    assert "\\$200 staked" in text
    assert bp.signed_money(26.0) in text          # 20.0 + 6.0
    assert "We expect **0.8 of the 2**" in text   # 0.44 + 0.38


def test_a_player_ruled_out_is_a_settled_loss_not_a_bad_bet(frame, rule):
    frame["is_blocked"] = [True, False, False, False, False]
    text = bp.slate_expectation(frame, rule)
    assert "each of the 1 marked play" in text
    assert "Excludes 1 marked player ruled out by the injury report." in text


def test_no_marked_plays_is_a_result_not_a_gap(rule):
    quiet = pd.DataFrame([{"bet_rank": 1, "model_edge_pp": 0.0, "odds": 100,
                           "ev_model_pct": 0.0, "prob_bet": 0.1}])
    assert "Nothing on this week's board clears the bar" in \
        bp.slate_expectation(quiet, rule)


def test_no_rule_means_nothing_to_total(frame):
    assert bp.slate_expectation(frame, None) is None
    assert bp.slate_expectation(frame.drop(columns=["ev_model_pct"]), {}) is None


# ── Legend and prose ────────────────────────────────────────────────────────


def test_tier_legend_is_built_from_the_fitted_rule(rule):
    legend = bp.tier_legend(rule)
    assert list(legend["Label"]) == ["Strong", "Standard", "Fade", "(blank)"]
    # Thresholds quoted, not written out.
    assert "10 points or more" in legend.iloc[0]["What earns it"]
    assert "Bet # 5 or better" in legend.iloc[0]["What earns it"]
    assert "priced +-200 or longer" in legend.iloc[0]["What earns it"]


def test_the_blank_row_is_included_deliberately(rule):
    """Reading a blank as "we don't like him" is wrong for three of four cases."""
    blank = bp.tier_legend(rule).iloc[-1]
    assert blank["Label"] == "(blank)"
    assert "four different things" in blank["What it means"]


def test_ex_top10_is_the_honest_companion_to_the_headline(tiers):
    strong = tiers["tiers"][0]
    assert bp.ex_top10(strong) == "$104 per $100"
    assert bp.ex_top10({"roi_ex_top10": None}) == "—"


def test_no_tiers_means_no_legend():
    assert bp.tier_legend(None) is None
    assert bp.tier_legend({"tiers": {"tiers": [], "fade": None}}) is None


def test_tier_summary_names_every_tier(rule):
    s = bp.tier_summary(rule)
    assert "**Strong**" in s and "**Standard**" in s and "**Fade**" in s
    assert "a warning, not a bet" in s


def test_tier_help_quotes_the_measurement(rule):
    h = bp.tier_help(rule)
    assert "1,130 games in 2023-2025" in h
    assert "**Bet #** 5 or better" in h
    # The bar the whole tab exists to keep honest.
    assert "not a recommendation to bet" in h


def test_tier_help_says_so_when_nothing_is_marked():
    assert bp.tier_help(None) == \
        "Measured profitability. Nothing is marked on this market."


def test_tier_help_flags_a_season_below_its_own_interval(rule):
    rule["tiers"]["tiers"][0]["per_season"][-1]["roi"] = -5.0   # under lo=18.8
    assert "The most recent season is below the range" in bp.tier_help(rule)


# ── ROI tables ──────────────────────────────────────────────────────────────


def test_roi_rows_translates_the_verdict_into_plain_words():
    rows = [{"top_n": 1, "n": 849, "hit_pct": 55.0, "breakeven_pct": 52.5,
             "median_odds": -115.0, "roi": 6.9, "lo": -0.2, "hi": 13.6,
             "verdict": "indistinguishable from zero", "thin": False}]
    out = bp.roi_rows(rows, "top_n", "Top N")
    assert out.iloc[0]["Verdict"] == "Too close to call"
    assert out.iloc[0]["95% interval"] == "-0.2% to +13.6%"
    assert out.iloc[0]["ROI"] == pytest.approx(0.069)


def test_too_few_bets_overrides_the_verdict():
    rows = [{"top_n": 9, "n": 3, "hit_pct": 66.7, "breakeven_pct": 50.0,
             "median_odds": 100.0, "roi": 33.0, "lo": None, "hi": None,
             "verdict": "positive", "thin": True}]
    out = bp.roi_rows(rows, "top_n", "Top N")
    assert out.iloc[0]["Verdict"] == "Too few bets to say"
    assert out.iloc[0]["95% interval"] == "—"


# ── Guidance ────────────────────────────────────────────────────────────────


def _econ(verdict: str) -> dict:
    return {
        "headline": {"verdict": verdict, "roi": 15.0},
        "games": 1130,
        "by_rank": [{"rank": 1, "verdict": "positive"},
                    {"rank": 2, "verdict": "positive"},
                    {"rank": 3, "verdict": "negative"}],
        "by_odds_bucket": [{"bucket": "+300 or longer", "roi": -22.0}],
        "by_season": [{"season": 2024, "verdict": "positive"},
                      {"season": 2025, "verdict": "positive"}],
        "blend_comparison": [
            {"ranked_by": "model only (pre-blend)", "top_n": 3, "roi": 15.0},
            {"ranked_by": "blended (published)", "top_n": 3, "roi": 7.0},
        ],
    }


def test_guidance_quotes_the_measured_depth_and_the_blend_cost():
    do, dont = bp.bet_guidance(_econ("positive"), 3)
    assert any("Ranks 1 to 2 each held up" in line for line in do)
    assert any("costs about 8 points of return" in line for line in do)
    assert any("Do not chase the big prices" in line for line in dont)


def test_an_unproven_market_is_told_not_to_bet():
    do, _ = bp.bet_guidance(_econ("indistinguishable from zero"), 3)
    assert "Do not bet this market yet" in do[0]


def test_a_pooled_positive_built_on_one_good_season_is_called_out():
    econ = _econ("positive")
    econ["by_season"][1]["verdict"] = "negative"
    do, _ = bp.bet_guidance(econ, 3)
    assert any("Be skeptical of the headline" in line for line in do)
    assert any("only profitable in 1 season out of 2" in line for line in do)


# ── Verdicts on a combination ──────────────────────────────────────────────


def test_a_slip_reads_as_its_weakest_leg():
    assert bp.combo_read(["Strong call", "Matches book"]) == "Matches book"
    assert bp.combo_read(["Strong call", "Leans"]) == "Leans"
    assert bp.combo_read(["Strong call", "Strong call"]) == "Strong call"


def test_a_slip_with_no_reads_says_nothing():
    assert bp.combo_read([]) == ""
    assert bp.combo_read(["something else"]) == ""


def test_backing_spells_out_each_legs_tier():
    assert bp.combo_backing(["Strong", "Standard"]) == "Strong + Standard"
    assert bp.combo_backing(["Strong", "Standard", "Strong"]) == \
        "Strong + Standard + Strong"


def test_an_unmarked_leg_reads_as_a_dash_rather_than_a_gap():
    """"Strong + \u2014" cannot be misread as a one-leg slip; "Strong +" can."""
    assert bp.combo_backing(["Strong", ""]) == "Strong + \u2014"
    assert bp.combo_backing(["", "Standard"]) == "\u2014 + Standard"


def test_a_slip_with_nothing_marked_says_nothing():
    assert bp.combo_backing(["", "", ""]) == ""


def test_a_fade_leg_is_named_like_any_other():
    """It needs no special case: "Strong + Fade" says exactly what it is."""
    assert bp.combo_backing(["Strong", "Fade"]) == "Strong + Fade"


# --------------------------------------------------------------------------
# A verdict needs a fitted rule behind it
# --------------------------------------------------------------------------

def test_a_betting_verdict_requires_a_fitted_rule():
    """The Gaps discipline, applied to the touchdown board.

    `lo` and `hi` are percentiles of our own disagreement, which say how
    unusual a gap is and nothing about whether it pays. The over/under
    markets already have the honest version — `prop_edge.fit_threshold` fits
    a cut on past seasons by return, with a floor on bets, saved with
    provenance. The touchdown equivalent, `rank_economics.fit_edge_rule`, is
    stricter still and returns None on both markets: every band of the
    2023-2025 edge curve is negative or indistinguishable from zero.

    The board already fell back to the percentile labels when no rule was
    fitted. What it did not do was change what they SAY, so 87 live rows read
    "Strong call" on a market whose own economics verdict is `negative`.
    """
    from src.presentation import board as B

    # Same row, same numbers; only whether a rule exists differs.
    assert B.confidence(9.0, 0.02, 0.05, 20.0, rule_fitted=True) == "Strong call"
    assert B.confidence(9.0, 0.02, 0.05, 20.0, rule_fitted=False) == B.WELL_ABOVE
    assert B.confidence(3.0, 0.02, 0.05, 20.0, rule_fitted=True) == "Leans"
    assert B.confidence(3.0, 0.02, 0.05, 20.0, rule_fitted=False) == B.ABOVE

    # The instructions that are NOT claims about our own edge are untouched.
    # Veto is a refusal, carried by its own measurement; Pass is the money
    # gate; Matches book is having no opinion.
    for fitted in (True, False):
        assert B.confidence(-9.0, 0.02, 0.05, 0.0, rule_fitted=fitted) == B.VETO
        assert B.confidence(9.0, 0.02, 0.05, -5.0, rule_fitted=fitted) == B.PASS
        assert B.confidence(0.5, 0.02, 0.05, 5.0,
                            rule_fitted=fitted) == "Matches book"

    # Defaulting to True keeps every other caller as it was.
    assert B.confidence(9.0, 0.02, 0.05, 20.0) == "Strong call"


def test_the_descriptive_tiers_rank_below_the_betting_ones():
    """A slip takes the weakest read among its legs, so the order matters.

    "Above book" is a weaker statement than "Leans": it says our number is
    higher and declines to call it a bet. If it sorted above, a slip of
    unproven legs would inherit a betting verdict none of them carries.
    """
    from src.presentation import board as B

    o = B.READ_ORDER
    assert o.index(B.ABOVE) < o.index("Leans")
    assert o.index(B.WELL_ABOVE) < o.index("Strong call")
    assert o.index(B.ABOVE) < o.index(B.WELL_ABOVE)
    assert o.index("Matches book") < o.index(B.ABOVE)
    # And a mixed slip still takes the weakest leg.
    assert B.combo_read([B.WELL_ABOVE, "Strong call"]) == B.WELL_ABOVE
    assert B.combo_read([B.ABOVE, B.PASS]) == B.PASS
