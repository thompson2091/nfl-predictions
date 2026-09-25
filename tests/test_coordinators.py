"""Coordinator ingest: the title map, the parser, and what it must refuse."""
import polars as pl

from src.ingest import coordinators as co


def test_relocations_resolve_to_the_name_the_team_had_then():
    """An article title built from today's name returns a missing page.

    Which reads as "no coordinator listed", not as an error — so a franchise
    would quietly carry nulls for every season before it moved.
    """
    cases = [
        ("LV", "Las Vegas Raiders", 2018, "2018 Oakland Raiders season"),
        ("LV", "Las Vegas Raiders", 2021, "2021 Las Vegas Raiders season"),
        ("LAC", "Los Angeles Chargers", 2015, "2015 San Diego Chargers season"),
        ("LA", "Los Angeles Rams", 2014, "2014 St. Louis Rams season"),
        ("WAS", "Washington Commanders", 2018, "2018 Washington Redskins season"),
        ("WAS", "Washington Commanders", 2020,
         "2020 Washington Football Team season"),
        ("WAS", "Washington Commanders", 2023,
         "2023 Washington Commanders season"),
    ]
    for abbr, name, season, want in cases:
        assert co.article_title(abbr, name, season) == want


def test_the_staff_list_is_read_and_prose_is_not():
    """Most articles keep the coordinator in a list, not the infobox.

    Parsing only the infobox returned 0% for the season being played and about
    half of the rest. Parsing loosely is worse: the 2023 Cardinals article says
    a "defensive coordinator [[Jonathan Gannon]]" was hired as their HEAD
    COACH, away from another team. Matched as their own coordinator it is
    wrong about the job and the team.
    """
    assert co._value("| off_coach = [[Matt Nagy]]", "off_coach") == "Matt Nagy"
    assert co._value("*Offensive coordinator – [[Drew Petzing]]",
                     "off_coach") == "Drew Petzing"
    assert co._value("*Defensive coordinator – [[Bobby Babich]]",
                     "def_coach") == "Bobby Babich"
    # The piped display name, not the disambiguated article title.
    assert co._value(
        "*Offensive coordinator – [[Joe Brady (American football coach)|Joe Brady]]",
        "off_coach") == "Joe Brady"
    # Prose, and it must not match.
    assert co._value(
        "hired defensive coordinator [[Jonathan Gannon]] as the team's new "
        "head coach.", "def_coach") is None


def test_two_codes_for_one_franchise_do_not_overwrite_each_other():
    """nflverse carries LA and LAR, SD and LAC, OAK and LV.

    Keyed by article title, two codes resolving to one page overwrite each
    other and a franchise disappears — LA did, leaving 31 teams in a league of
    32, which is the sort of number nobody counts.
    """
    titles = {}
    for abbr, name in (("LA", "Los Angeles Rams"), ("LAR", "Los Angeles Rams")):
        titles.setdefault(co.article_title(abbr, name, 2026), []).append(abbr)
    assert any(len(v) > 1 for v in titles.values()), (
        "expected these two codes to collide; if they no longer do, the "
        "grouping in `fetch` may be unnecessary")


def test_saved_file_covers_every_team_in_the_seasons_it_holds():
    """90% is usable; a season at 34% is not, and the difference is silent."""
    d = co.load()
    if d.is_empty():
        return
    live = d.filter(~pl.col("team").is_in(co.DEFUNCT))
    per = live.group_by("season").agg(
        pl.len().alias("teams"),
        pl.col("oc").is_not_null().mean().alias("oc"))
    recent = per.filter(pl.col("season") >= 2015)
    assert not recent.is_empty()
    assert recent["teams"].min() >= 32, (
        f"a season is short of teams: {recent.sort('teams').head(3).to_dicts()}")
    thin = recent.filter(pl.col("oc") < 0.7)
    assert thin.is_empty(), (
        f"seasons with under 70% coverage: {thin.to_dicts()}")
