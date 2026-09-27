"""The schedules that drive every capture, kept where they can be recovered.

`data/archive/` cannot be re-bought — The Odds API serves current markets only
and neither public-split feed publishes history — so the jobs that write it are
the most load-bearing configuration in this repo. They live in
`~/Library/LaunchAgents/`, which no backup of this project covers.
"""
from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
COMMITTED = REPO / "config" / "launchd"
INSTALLED = Path.home() / "Library" / "LaunchAgents"

#: Every job this project relies on. A new one belongs here the day it is
#: written, not the day someone notices it was never committed.
JOBS = ("nfl-odds-open", "nfl-odds-close", "nfl-inactives",
        "nfl-public-money", "nfl-week-rollover", "nfl-sharp-gate",
        "nfl-sunday-wrap")


def _path(name: str) -> Path:
    return COMMITTED / f"com.mthompson.{name}.plist"


@pytest.mark.parametrize("job", JOBS)
def test_every_job_has_a_committed_schedule(job):
    """Three of these were installed and never committed, while a memory note
    claimed all of them were. A schedule that exists only on one laptop is one
    disk failure from being reconstructed by guesswork."""
    assert _path(job).exists(), (
        f"{job} has no committed plist. Copy it from {INSTALLED}.")


@pytest.mark.parametrize("job", JOBS)
def test_every_committed_schedule_parses_and_names_its_program(job):
    """A plist that does not parse is not a schedule, and launchd says so only
    at load time."""
    d = plistlib.loads(_path(job).read_bytes())
    assert d.get("Label") == f"com.mthompson.{job}"
    args = d.get("ProgramArguments") or []
    assert args, f"{job} runs nothing"
    prog = Path(args[0])
    assert prog.exists(), f"{job} points at {prog}, which is not on disk"
    assert prog.stat().st_mode & 0o111, f"{prog} is not executable"


@pytest.mark.parametrize("job", JOBS)
def test_every_schedule_fires_at_some_point(job):
    """`StartCalendarInterval` missing entirely is a job that never runs, and
    launchd loads it without complaint."""
    d = plistlib.loads(_path(job).read_bytes())
    cal = d.get("StartCalendarInterval")
    assert cal, f"{job} has no StartCalendarInterval — it would never fire"
    entries = cal if isinstance(cal, list) else [cal]
    for e in entries:
        assert "Hour" in e, f"{job} has an entry with no Hour: {e}"


def test_the_sharp_gate_runs_on_monday_only():
    """The one day a week when a week's open, its splits and its close are all
    on disk and all belong to the same week: Sunday's last close capture lands
    at 19:50 and the rollover runs on Tuesday."""
    d = plistlib.loads(_path("nfl-sharp-gate").read_bytes())
    days = {e.get("Weekday") for e in d["StartCalendarInterval"]}
    assert days == {1}, f"sharp gate fires on {days}, expected Monday only"


def test_no_schedule_carries_a_credential():
    """launchd plists are committed, so anything in one is public to whoever
    can read this repo."""
    import re

    bad = re.compile(r"<string>[^<]*(password|secret|token|apikey|api_key)",
                     re.I)
    for job in JOBS:
        text = _path(job).read_text()
        assert not bad.search(text), f"{job} looks like it carries a secret"
        assert "EnvironmentVariables" not in text, (
            f"{job} sets environment variables inline — keep them in .env")


def test_the_job_list_is_the_directory():
    """GUARD THE GUARD. Every check in this file is parametrized over `JOBS`,
    so a schedule that is never added to that tuple is not tested by any of
    them — and the file still reports twenty passing tests. The failure is
    silent in both directions: a job committed and untested, or a name left
    in the list after its plist was deleted.
    """
    on_disk = {p.stem.replace("com.mthompson.", "")
               for p in COMMITTED.glob("com.mthompson.*.plist")}
    assert on_disk == set(JOBS), (
        f"committed but untested: {sorted(on_disk - set(JOBS))}; "
        f"listed but missing: {sorted(set(JOBS) - on_disk)}")


def test_the_sunday_wrap_runs_after_the_late_games_and_again_after():
    """One attempt is not enough and the script knows it.

    The late games settle around 23:30 ET and nflverse publishes their
    play-by-play some time after that, so the first run often lands before the
    data does. Every run is a no-op unless a new final appeared since the
    last, which is what makes scheduling several of them cheap.
    """
    d = plistlib.loads(_path("nfl-sunday-wrap").read_bytes())
    ci = d["StartCalendarInterval"]
    ci = [ci] if isinstance(ci, dict) else ci
    assert len(ci) >= 2, "one attempt cannot outlast a publishing delay"
    # The first sits on Sunday, after the late window.
    sun = [c for c in ci if c.get("Weekday") == 0]
    assert sun and max(c["Hour"] for c in sun) >= 22, (
        "the Sunday attempt has to be after the late games, not during them")
    # And at least one lands on Monday, for data published overnight.
    assert any(c.get("Weekday") == 1 for c in ci), (
        "nothing picks up play-by-play that publishes after midnight")
