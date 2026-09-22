#!/usr/bin/env python3
"""Schedule the inactives re-check, derived from the season's own kickoffs.

    python scripts/57_inactives_schedule.py               # show the slots
    python scripts/57_inactives_schedule.py --write --load

Inactives land about 90 minutes before kickoff and the board is built four
hours before it, so there is a window in which a shortlist can name a player
who cannot play. This job fires inside that window.

The times are DERIVED, not written down — the same rule `25_odds_schedule.py`
follows and for the same reason: the league flexes games between windows all
season, and a hand-written Sunday afternoon slot is wrong the first time a game
moves. Both schedules come from one `kickoff_waves`, at different leads.

75 minutes rather than 90. The designation is published *about* 90 minutes out
and the exact moment varies by team; firing at the nominal time would catch the
teams that are punctual and miss the rest. Fifteen minutes of slack costs
nothing here — the check is a roster read, not a paid API call.
"""
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, ".")

_spec = importlib.util.spec_from_file_location(
    "odds_schedule", Path(__file__).with_name("25_odds_schedule.py"))
_os = importlib.util.module_from_spec(_spec)
sys.modules["odds_schedule"] = _os
_spec.loader.exec_module(_os)

LABEL = "com.mthompson.nfl-inactives"
#: Minutes before the earliest kickoff in a wave. See the module docstring.
LEAD_MINUTES = 75
AGENTS = Path.home() / "Library" / "LaunchAgents"
ROOT = Path(__file__).resolve().parents[1]


def plist(slots: dict[str, list[str]]) -> str:
    intervals = "\n".join(
        f"    <dict><key>Weekday</key><integer>{_os.WEEKDAYS[day]}</integer>"
        f"<key>Hour</key><integer>{int(t[:2])}</integer>"
        f"<key>Minute</key><integer>{int(t[3:])}</integer></dict>"
        for day, times in slots.items() for t in times)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{ROOT / '.venv' / 'bin' / 'python'}</string>
    <string>{ROOT / 'scripts' / '56_inactives.py'}</string>
    <string>--refresh</string>
  </array>
  <key>WorkingDirectory</key><string>{ROOT}</string>
  <key>StandardOutPath</key><string>{ROOT / 'logs' / 'launchd_inactives.out'}</string>
  <key>StandardErrorPath</key><string>{ROOT / 'logs' / 'launchd_inactives.err'}</string>
  <key>StartCalendarInterval</key>
  <array>
{intervals}
  </array>
</dict>
</plist>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--load", action="store_true")
    a = ap.parse_args()

    slots = _os.kickoff_waves(lead=LEAD_MINUTES)
    total = sum(len(v) for v in slots.values())
    print(f"Inactives re-check, {LEAD_MINUTES} minutes before each kickoff wave:")
    for day, times in slots.items():
        print(f"  {day:<10} {'  '.join(times)}")
    print(f"\n{total} slots a week. Each one re-reads the roster and reports "
          f"tracked picks that are no longer active; it spends no API credits.")
    if not a.write:
        print("\nDry run. Re-run with --write to install, --write --load to "
              "install and activate.")
        return 0

    AGENTS.mkdir(parents=True, exist_ok=True)
    path = AGENTS / f"{LABEL}.plist"
    path.write_text(plist(slots))
    print(f"\nwrote {path}")
    if a.load:
        subprocess.run(["launchctl", "bootout", f"gui/{os_uid()}/{LABEL}"],
                       capture_output=True)
        r = subprocess.run(["launchctl", "bootstrap", f"gui/{os_uid()}",
                            str(path)], capture_output=True, text=True)
        print("loaded" if r.returncode == 0 else f"load failed: {r.stderr.strip()}")
    return 0


def os_uid() -> int:
    import os
    return os.getuid()


if __name__ == "__main__":
    raise SystemExit(main())
