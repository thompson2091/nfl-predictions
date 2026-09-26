#!/bin/bash
# Ask whether the big money beat the closing line, once a week, unattended.
#
# IT STAYS QUIET UNTIL IT HAS SOMETHING TO SAY.
#
# `scripts/60_sharp.py` refuses to report until a split capture sits BEFORE a
# close on enough games, which is the honest state for every week so far: the
# split archive opened on 2026-09-25 and week 3's lines had already closed. A
# job that mailed a refusal every Monday would train you to ignore it, so this
# writes the refusal to the log and says nothing else. The first time the gate
# returns an actual table it raises a desktop notification and leaves a marker
# file, and does that once per verdict rather than every week afterwards.
#
#   ./scripts/sharp_gate.sh          # run it now
#   ./scripts/sharp_gate.sh --force  # notify even if the verdict is unchanged
#
# Monday, because Sunday's last close capture lands at 19:50 and the week
# rollover is Tuesday. That window is the only one where a week's open, its
# splits and its close are all on disk and all belong to the same week.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

LOG_DIR="logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/sharp_gate_$(date +%Y%m%d_%H%M%S).log"
MARKER="$LOG_DIR/.sharp_last_verdict"

# launchd gets a near-empty environment; nothing here may rely on a profile.
PY=".venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
[ -x "$PY" ] || { echo "no python found" >&2; exit 1; }

OUT="$("$PY" scripts/60_sharp.py 2>&1)"
status=$?
printf '%s\n' "$OUT" >>"$LOG"

# A REFUSAL IS NOT A FAILURE. The gate returning "no split capture yet sits
# before a close" is it working: the data is not there, and saying so is the
# whole design. Logged, never notified.
if printf '%s' "$OUT" | grep -q 'before a close'; then
    echo "$(date -u +%FT%TZ) gate still waiting on data" >>"$LOG"
    exit 0
fi

if [ $status -ne 0 ]; then
    echo "$(date -u +%FT%TZ) sharp gate FAILED (exit $status), see $LOG" >&2
    exit $status
fi

# There is a verdict. Notify once per distinct one — a table that has not
# changed since last Monday is not news.
SIG="$(printf '%s' "$OUT" | shasum | cut -d' ' -f1)"
if [ "${1:-}" != "--force" ] && [ -f "$MARKER" ] && [ "$SIG" = "$(cat "$MARKER")" ]; then
    echo "$(date -u +%FT%TZ) verdict unchanged, not notifying" >>"$LOG"
    exit 0
fi
printf '%s' "$SIG" >"$MARKER"

printf '%s\n' "$OUT"
osascript -e 'display notification "The sharp-money gate has a verdict. See logs/sharp_gate_*.log" with title "Pick Six"' 2>/dev/null

# Keep a season of logs and no more.
find "$LOG_DIR" -name 'sharp_gate_*.log' -type f -mtime +120 -delete 2>/dev/null
exit 0
