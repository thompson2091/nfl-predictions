"""Refreshing one season must not delete the others.

This has happened twice, a year apart, for the same reason and with the same
silence. `load_rosters` replaced 2015-2026 with 2026 alone and grading the
odds archive went to 0% across 44,000 closing prices — reported only as
"grading will be sparse". It was fixed in that one loader, as a paragraph of
comment, and `load_injuries` did it again: 61,221 rows to 692.

Nothing fails when it happens. The current week still resolves, so the board,
the candidates and every check carry on. What breaks is everything keyed on an
older season, which nobody looks at until a rebuild.
"""
import re
from pathlib import Path

import polars as pl
import pytest

SRC = Path(__file__).resolve().parents[1] / "src/ingest/loader.py"

#: Files whose rows are keyed by season and are therefore destroyable by a
#: single-season refresh.
#:
#: `schedules.parquet` was left OUT of this list on the reasoning that it is
#: always loaded whole. That reasoning was wrong within the hour: fetching one
#: game's final score meant `load_schedules([2026])`, and 3,300 rows became
#: 272. "This one is always called with every season" is a claim about every
#: caller that will ever exist, which is not a claim anyone can make — so the
#: list is now every season-keyed file, with no exceptions and no judgement.
SEASON_KEYED = ["rosters.parquet", "pbp.parquet", "weekly_stats.parquet",
                "snap_counts.parquet", "injuries.parquet",
                "schedules.parquet"]


def test_every_season_keyed_loader_merges_rather_than_replaces():
    """The check that would have caught it the second time.

    Falsified by any loader writing one of these files without passing it
    through `_keep_other_seasons` — which is the exact shape of the bug, twice.
    """
    src = SRC.read_text()
    for name in SEASON_KEYED:
        for m in re.finditer(re.escape(f'"{name}"'), src):
            line = src[src.rfind("\n", 0, m.start()) + 1:
                       src.find("\n", m.start())]
            if "_write(" not in line:
                continue
            assert "_keep_other_seasons" in line, (
                f"{name} is written without merging:\n    {line.strip()}\n"
                f"a single-season refresh will delete every other season and "
                f"nothing will fail")


def test_the_merge_keeps_seasons_it_was_not_asked_for(tmp_path, monkeypatch):
    """Behaviour, not just wiring: the helper itself has to do it."""
    from src.ingest import loader

    monkeypatch.setattr(loader, "get_path", lambda k: tmp_path)
    prior = pl.DataFrame({"season": [2024, 2024, 2025], "x": [1, 2, 3]})
    prior.write_parquet(tmp_path / "thing.parquet")

    fresh = pl.DataFrame({"season": [2026], "x": [9]})
    out = loader._keep_other_seasons(fresh, "thing.parquet")
    assert sorted(out["season"].unique().to_list()) == [2024, 2025, 2026]
    assert out.height == 4


def test_a_refreshed_season_is_replaced_not_duplicated(tmp_path, monkeypatch):
    """Merging must not turn a re-run into two copies of the same week."""
    from src.ingest import loader

    monkeypatch.setattr(loader, "get_path", lambda k: tmp_path)
    pl.DataFrame({"season": [2025, 2026], "x": [1, 99]}).write_parquet(
        tmp_path / "thing.parquet")
    fresh = pl.DataFrame({"season": [2026], "x": [5]})
    out = loader._keep_other_seasons(fresh, "thing.parquet")
    assert out.height == 2
    assert out.filter(pl.col("season") == 2026)["x"].to_list() == [5], (
        "the refreshed season must be the NEW rows, not both")


def test_a_missing_file_is_not_an_error(tmp_path, monkeypatch):
    from src.ingest import loader

    monkeypatch.setattr(loader, "get_path", lambda k: tmp_path)
    fresh = pl.DataFrame({"season": [2026], "x": [1]})
    assert loader._keep_other_seasons(fresh, "nope.parquet").height == 1


def test_a_frame_with_no_season_column_passes_through(tmp_path, monkeypatch):
    from src.ingest import loader

    monkeypatch.setattr(loader, "get_path", lambda k: tmp_path)
    d = pl.DataFrame({"x": [1]})
    assert loader._keep_other_seasons(d, "thing.parquet").height == 1


@pytest.mark.parametrize("name", SEASON_KEYED)
def test_the_files_on_disk_still_hold_their_history(name):
    """A guard on the artifact, not only the code that writes it.

    Cheap, and it is the check that would have said something out loud the
    morning after either incident.
    """
    from src.utils.paths import get_path

    path = get_path("raw") / name
    if not path.exists():
        pytest.skip(f"{name} not built")
    seasons = (pl.scan_parquet(path).select("season").collect()["season"]
               .unique().to_list())
    assert len(seasons) >= 2, (
        f"{name} holds only {sorted(seasons)} — a single-season refresh has "
        f"replaced the file rather than merging into it")
