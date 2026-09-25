#!/bin/bash
# Capture the public split, unattended, several times a day.
#
# THE SPLIT IS EASY; THE DRIFT IS THE PART THAT CANNOT BE BOUGHT BACK.
#
# Anyone can read Sunday's percentage off a website. A side that opened at 50%
# and sat at 71% by kickoff is a different fact from one that was at 71% all
# week, and the second is invisible from a single read. Neither feed publishes
# history, so the only copy of the week's drift is the one this makes — and a
# Tuesday that nobody captured is gone the same way an unsnapshotted odds week
# is gone.
#
# Two feeds, both archived by the Python: Sportsbook Review for the spread and
# total ticket shares, Action Network for the moneyline and for the share of
# the MONEY as well as of the bets.
#
#   ./scripts/public_money.sh           # capture now, or no-op if recent
#
# Safe to run as often as you like. `refresh` is a no-op inside its own
# MIN_GAP_MINUTES, so a firing that lands too soon after the last one writes
# nothing and costs one request.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

LOG_DIR="logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/public_money_$(date +%Y%m%d_%H%M%S).log"

# launchd gets a near-empty environment, so nothing here may rely on a shell
# profile having run.
PY=".venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
[ -x "$PY" ] || { echo "no python found" >&2; exit 1; }

# The week comes from the schedule inside the script, not from an argument, so
# an unattended run cannot archive a capture under the wrong week.
"$PY" scripts/57_public_money.py >>"$LOG" 2>&1
status=$?

# Keep a season of logs and no more. Each is a few kilobytes; the point of the
# prune is that a job running four times a day for five months does not leave
# six hundred files behind.
find "$LOG_DIR" -name 'public_money_*.log' -type f -mtime +120 -delete 2>/dev/null

if [ $status -ne 0 ]; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) public money capture FAILED, see $LOG" >&2
fi
exit $status
