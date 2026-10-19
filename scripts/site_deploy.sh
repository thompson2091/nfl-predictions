#!/bin/bash
# Deploy the site when a capture asks for it, in a launchd job of its own.
#
# `weekly_odds.sh` used to run the deploy itself, after the capture, and on
# 2026-10-18 that cost three closing captures. The Mac slept all Sunday on
# battery, waking for 20-40 seconds every ~16 minutes; the 09:00 capture took
# seven seconds and the deploy behind it crawled through those wakes until
# 21:03. launchd will not start a job whose last instance is alive, so the
# 12:30, 15:35 and 19:50 closes never ran. A price not captured cannot be
# bought back; a deploy can always be run again.
#
# So the capture now touches `logs/.deploy_requested` and exits, and this job
# (com.mthompson.nfl-deploy, WatchPaths on that file) does the slow part.
#
# THE TWO MAY NOT OVERLAP. The v3 build runs the site export, which records
# frozen boards; `prediction_freeze.flush` writes the whole season file from
# its own in-memory copy, so whichever of two overlapping writers finishes
# second silently drops the other's records. Hence:
#   - this waits while a capture is running, and
#   - a capture that starts while this is running stops it first
#     (`weekly_odds.sh`), then asks for a fresh deploy when it is done.
# The capture never waits for the deploy. That is the whole point.
#
#   ./scripts/site_deploy.sh            # what launchd runs
#   touch logs/.deploy_requested        # ask for one by hand
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
LOG_DIR="logs"
TRIGGER="$LOG_DIR/.deploy_requested"
mkdir -p "$LOG_DIR"

# WatchPaths fires on the trigger being removed as well as touched, and this
# script removes it. No trigger, nothing asked for.
[ -f "$TRIGGER" ] || exit 0

LOG="$LOG_DIR/site_deploy_$(date +%Y%m%d_%H%M%S).log"
PY=".venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

say() { echo "$@" | tee -a "$LOG"; }

say "=== $(date -u +%FT%TZ) site deploy, requested $(stat -f %Sm -t %FT%T "$TRIGGER") ==="

# Let a running capture finish first. Bounded, so a wedged capture cannot
# hold this forever; the next capture asks again anyway.
#
# Matched on the process actually running the script — launchd starts it as
# `<repo>/scripts/weekly_odds.sh <snapshot>`, a hand run as `bash <path>` —
# not on any command line that merely mentions it, which an editor or a
# `tail` on its log would.
capturing() {
    pgrep -f '^(/bin/bash |bash )?[^ ]*scripts/weekly_odds\.sh( |$)' >/dev/null
}
for _ in $(seq 1 120); do
    capturing || break
    sleep 30
done
if capturing; then
    say "  a capture has been running for an hour — leaving the request for the next run"
    exit 0
fi

# Taken now, so a request made while this runs survives it and fires again.
rm -f "$TRIGGER"

if [ ! -f "$HOME/.ssh/id_ed25519_squarespro" ]; then
    say "  deploy skipped: no deploy key at ~/.ssh/id_ed25519_squarespro"
    exit 0
fi

if "$PY" scripts/58_deploy.py >> "$LOG" 2>&1; then
    say "  $(grep -h 'deploying as' "$LOG" | tail -1 | sed 's/^ *//')"
else
    say "  deploy failed (exit $?) — see $LOG"
fi
say "=== $(date -u +%FT%TZ) done ==="

ls -1t "$LOG_DIR"/site_deploy_*.log 2>/dev/null | tail -n +31 | xargs -r rm -f
exit 0
