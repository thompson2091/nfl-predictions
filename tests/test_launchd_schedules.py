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
        "nfl-public-money", "nfl-week-rollover", "nfl-sharp-gate")


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
