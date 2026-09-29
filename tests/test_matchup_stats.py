"""Offense against defense: as-of, and honest about what is missing."""
import polars as pl
import pytest

from src.models import matchup_stats as ms


def test_every_rate_is_built_from_games_before_this_one():
    """Computed over the whole season, a page about an unplayed game reports
    its result. The filter is `week < week`, which is the same guarantee as a
    shift and easier to see."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "src/models/matchup_stats.py").read_text()
    body = src[src.index("def _totals_through"):src.index("def _rates")]
    assert 'pl.col("week") < week' in body


def test_totals_exclude_the_target_week():
    g = pl.DataFrame({"season": [2026] * 3, "week": [1, 2, 3],
                      "team": ["GB"] * 3, "plays": [10, 20, 40],
                      "early_n": [5, 5, 5], "early_k": [1, 2, 4]})
    t = ms._totals_through(g, 3)
    assert t["c_plays"][0] == 30, "week 3 must not be in its own figure"
    assert t["games"][0] == 2


def test_a_week_with_nothing_before_it_produces_nothing():
    """Week 1 has no prior games, and an invented 0% is worse than a blank."""
    g = pl.DataFrame({"season": [2026], "week": [1], "team": ["GB"],
                      "plays": [10], "early_n": [5], "early_k": [2]})
    assert ms._totals_through(g, 1).is_empty()


def test_rates_are_ratios_of_sums_not_means_of_ratios():
    """Averaging per-game rates weights a 40-play game like a 75-play one."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "src/models/matchup_stats.py").read_text()
    body = src[src.index("def _per_game"):src.index("def _totals_through")]
    assert ".sum()" in body and ".mean()" not in body, (
        "per-game aggregation must count, so the as-of figure can be a ratio "
        "of sums")


def test_the_edge_flips_sign_where_lower_is_better():
    """Sack rate is a rate you want LOW. An offense beating the defense's sack
    rate is being sacked more often than that defense usually manages, which is
    bad — and a single sign for every metric would paint it green."""
    # Nested by SPLIT: the module builds full game, first half and second
    # half from one read, and `matchup` takes which one to report.
    stats = {"GB": {"games": 3, "full": {
                        "off": {"sack_rate": 0.10, "early_down_success": 0.50},
                        "def": {"sack_rate": 0.05, "early_down_success": 0.40}}},
             "ATL": {"games": 3, "full": {
                        "off": {"sack_rate": 0.04, "early_down_success": 0.42},
                        "def": {"sack_rate": 0.06, "early_down_success": 0.45}}}}
    rows = ms.matchup({"home": "GB", "away": "ATL"}, stats)
    sack = [r for r in rows if r["key"] == "sack_rate"][0]
    gb = [p for p in sack["sides"] if p["offense"] == "GB"][0]
    # GB's offense is sacked 10% against a defense that manages 6%: worse.
    assert gb["edge"] < 0
    early = [r for r in rows if r["key"] == "early_down_success"][0]
    gbe = [p for p in early["sides"] if p["offense"] == "GB"][0]
    assert gbe["edge"] > 0


def test_both_halves_of_the_matchup_are_returned():
    """A matchup has two, and showing one is showing half a game."""
    stats = {t: {"games": 3, "full": {"off": {"epa_play": 0.1},
                                      "def": {"epa_play": 0.0}}}
             for t in ("GB", "ATL")}
    rows = ms.matchup({"home": "GB", "away": "ATL"}, stats)
    assert len(rows[0]["sides"]) == 2
    assert {p["offense"] for p in rows[0]["sides"]} == {"GB", "ATL"}


def test_a_proxy_is_declared_a_proxy():
    """Sack rate is not pressure rate: it counts pressure that SUCCEEDED, and
    a line generating constant pressure against a quick release looks
    identical to one generating none."""
    by_key = {m[0]: m for m in ms.METRICS}
    assert "PROXY" in by_key["sack_rate"][3]
    stats = {t: {"games": 3, "full": {"off": {"sack_rate": 0.06},
                                      "def": {"sack_rate": 0.05}}}
             for t in ("GB", "ATL")}
    rows = ms.matchup({"home": "GB", "away": "ATL"}, stats)
    assert rows[0]["proxy"] is True


def test_what_could_not_be_built_is_named_with_its_reason():
    """A gap has to read as a gap rather than as an oversight — especially the
    blitz split, which was asked for and whose field is empty for 2026."""
    assert ms.MISSING
    blurb = " ".join(w + y for w, y in ms.MISSING)
    assert "number_of_pass_rushers" in blurb
    assert "2026" in blurb
    for what, why in ms.MISSING:
        assert what and why, "a named gap must say why"


def test_a_team_with_no_history_is_skipped_rather_than_half_rendered():
    assert ms.matchup({"home": "GB", "away": "ATL"}, {"GB": {"games": 1}}) is None


def test_each_split_is_reported_separately():
    """A first-half number is a different fact from a season-long one: a team
    that scripts its opening drives shows up there and is invisible in the
    total. Same eight rows, three views, not twenty-four rows."""
    stats = {t: {"games": 3,
                 "full": {"off": {"epa_play": 0.10}, "def": {"epa_play": 0.0}},
                 "h1": {"off": {"epa_play": 0.30}, "def": {"epa_play": 0.0}},
                 "h2": {"off": {"epa_play": -0.10}, "def": {"epa_play": 0.0}}}
             for t in ("GB", "ATL")}
    card = {"home": "GB", "away": "ATL"}
    full = ms.matchup(card, stats, "full")[0]["sides"][0]["off_val"]
    h1 = ms.matchup(card, stats, "h1")[0]["sides"][0]["off_val"]
    h2 = ms.matchup(card, stats, "h2")[0]["sides"][0]["off_val"]
    assert (full, h1, h2) == (0.10, 0.30, -0.10)
    assert [h[0] for h in ms.HALVES] == ["full", "h1", "h2"]


def test_overtime_is_in_neither_half():
    """It is a different game with different rules and under 1% of plays;
    folding it into the second half would make that split mean something
    slightly different for the handful of teams who played one."""
    assert [h[2] for h in ms.HALVES] == [None, "Half1", "Half2"]


def test_a_board_holds_only_the_games_that_week_is_played_in():
    """THE ODDS CAPTURE FILES BY WHEN IT RAN, NOT BY WHEN THE GAME IS PLAYED.

    Books post the next week's lines days early, so 2026 week 3 was archived
    with thirty games in it: its own sixteen and fourteen belonging to week 4.
    The board read the file as one week and showed all thirty under "This
    week" — sixteen finished games beside fourteen that had not kicked off —
    and week 3's archived page would have kept the fourteen after the
    rollover.

    The SCHEDULE decides, which is the one source that cannot be wrong about
    which week a game is in.
    """
    import polars as pl
    import pytest

    from src.evaluation.matchups import board
    from src.utils.paths import get_path

    p = get_path("raw") / "schedules.parquet"
    if not p.exists():
        pytest.skip("no schedules on disk")
    sched = pl.read_parquet(p).filter(pl.col("game_type") == "REG")
    season = int(sched["season"].max())
    real = {f'{r["away_team"]}_{r["home_team"]}': r["week"]
            for r in sched.filter(pl.col("season") == season)
                          .iter_rows(named=True)}

    checked = 0
    for week in sorted(sched.filter(pl.col("season") == season)["week"]
                       .unique().to_list()):
        b = board(season, int(week))
        if b.is_empty():
            continue
        checked += 1
        stray = sorted({g for g in b["game_id"].unique().to_list()
                        if real.get(g) is not None and real[g] != week})
        assert not stray, (
            f"the week {week} board carries {len(stray)} games played in "
            f"another week: {', '.join(stray[:6])}")
    assert checked >= 2, f"only {checked} weeks had a board; nothing was tested"
