#!/bin/bash
# Archive this week's sportsbook prices. Built to be run by cron, unattended.
#
# The Odds API only serves *current* markets. A week that is not snapshotted is
# gone permanently — it cannot be bought back at any price, and every backtest,
# every blend weight and every profitability figure in this project is built on
# that archive. This is the one job that must not depend on someone remembering.
#
#   ./scripts/weekly_odds.sh            # snapshot at whatever point we are at
#   ./scripts/weekly_odds.sh open       # the Tuesday opening line
#
# Cron installs two calls a week: `open` early, close near kickoff. Both ends are
# needed to measure closing-line value, which is the only evidence of edge that
# does not depend on who scored.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
SNAPSHOT="${1:-close}"
LOG_DIR="logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/odds_$(date +%Y%m%d_%H%M%S)_${SNAPSHOT}.log"

# cron gets a near-empty environment, so the key has to be loaded explicitly
# rather than inherited from a shell profile.
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

PY=".venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

# Which NFL week is it? Derived from the schedule rather than passed in, so an
# unattended run cannot silently archive a week under the wrong number.
WEEK=$("$PY" - <<'PYEOF' 2>/dev/null
import sys
from datetime import datetime, timezone
try:
    import polars as pl
    from src.utils.paths import get_path
    s = pl.read_parquet(get_path("raw") / "schedules.parquet")
    col = "gameday" if "gameday" in s.columns else None
    if col is None:
        sys.exit(1)
    now = datetime.now(timezone.utc).date()
    s = s.with_columns(pl.col(col).cast(pl.Utf8).str.slice(0, 10).alias("_d"))
    season = s["season"].max()
    cur = s.filter(pl.col("season") == season)
    # The week whose games are nearest ahead of now; falls back to the last
    # week already played once the season is over.
    upcoming = cur.filter(pl.col("_d") >= str(now)).sort("_d")
    row = upcoming.head(1) if upcoming.height else cur.sort("_d").tail(1)
    print(int(row["week"][0]))
except Exception:
    sys.exit(1)
PYEOF
)

if [ -z "${WEEK:-}" ]; then
    echo "$(date -u +%FT%TZ) could not determine the NFL week — schedules.parquet missing or unreadable" | tee -a "$LOG"
    exit 1
fi

# Is a kickoff near enough that this snapshot is worth an API credit?
#
# The close slots are generated from the season's kickoff waves and are
# deliberately generous — the league flexes games between windows all season, so
# a slot that is right in September can be empty in December. Rather than
# regenerate the schedule every week, every slot fires and this guard decides.
# Without it, 15 weekly firings would each spend credits to learn there was
# nothing to fetch. Set FORCE_CAPTURE=1 to override, for a manual catch-up.
if [ -z "${FORCE_CAPTURE:-}" ]; then
    "$PY" - "$SNAPSHOT" <<'PYEOF' >>"$LOG" 2>&1
import sys
from src.ingest.capture_window import should_capture

capture, why = should_capture(sys.argv[1])
print(f"  {why}")
sys.exit(0 if capture else 3)
PYEOF
    GUARD=$?
    if [ "$GUARD" -eq 3 ]; then
        tail -1 "$LOG"
        exit 0
    fi
    if [ "$GUARD" -ne 0 ]; then
        echo "  kickoff guard failed (exit $GUARD) — capturing anyway rather " \
             "than risk skipping a week" | tee -a "$LOG"
    fi
fi

# A hard ceiling on one capture, in wall-clock seconds.
#
# The belt to HTTP_TIMEOUT's braces, and it exists because the braces were
# missing once and the cost was not the capture that hung. Both odds jobs are
# single launchd jobs carrying many StartCalendarInterval entries, and launchd
# refuses to start a job whose previous instance is still alive — so a firing
# that never exits does not lose one snapshot, it loses every remaining
# snapshot of the week. On 2026-09-02 an `open` firing held its slot for six
# days on two dead sockets.
#
# So this guards the slot, not the request: whatever wedges the capture —  a
# timeout that does not fire, a DNS resolver that never returns, a filesystem
# stall on the archive write — the job is dead before the next slot needs it.
# 900s clears the ~11-minute worst case of a maximally slow fetch and still
# lands inside the shortest lead before kickoff (30 minutes).
#
# macOS ships no timeout(1), hence the watchdog.
CAPTURE_CAP_SECONDS="${CAPTURE_CAP_SECONDS:-900}"

run_capped() {
    # Job control, purely so each background job becomes a process-group leader
    # and can be signaled as a group. Killing a bare pid is not enough here:
    # a surviving child still holds the inherited stdout, `tee` waits on that
    # pipe, and the job stays alive in launchd's eyes — which is the thing this
    # function exists to prevent. That applies to the watchdog's own `sleep`
    # exactly as much as it does to the capture.
    set -m
    "$@" &
    capture_pid=$!
    (
        sleep "$CAPTURE_CAP_SECONDS"
        kill -0 "$capture_pid" 2>/dev/null || exit 0
        echo "  capture still alive after ${CAPTURE_CAP_SECONDS}s — killing" \
             "process group $capture_pid so the next slot can run"
        # Negative pid: the group. TERM first so Python can unwind, then KILL
        # for whatever ignored it.
        kill -TERM -"$capture_pid" 2>/dev/null || kill -TERM "$capture_pid" 2>/dev/null
        sleep 10
        kill -KILL -"$capture_pid" 2>/dev/null || kill -KILL "$capture_pid" 2>/dev/null
    ) &
    watchdog_pid=$!
    set +m
    wait "$capture_pid"
    capture_rc=$?
    kill -TERM -"$watchdog_pid" 2>/dev/null || kill -TERM "$watchdog_pid" 2>/dev/null
    wait "$watchdog_pid" 2>/dev/null
    return "$capture_rc"
}

# The season the week belongs to. Derived here rather than inside the game-line
# script so both captures file under one answer: `53_game_lines.py` has its own
# fallback that compares against today's date, and every hour of a Monday
# resolves that to the week which is ending.
SEASON=$("$PY" -c "
import polars as pl
from src.utils.paths import get_path
print(int(pl.read_parquet(get_path('raw') / 'schedules.parquet')['season'].max()))
" 2>/dev/null)
if [ -z "${SEASON:-}" ]; then
    echo "could not derive the season — game lines will be skipped"
fi

{
    echo "=== $(date -u +%FT%TZ)  week=$WEEK  snapshot=$SNAPSHOT ==="
    if [ -z "${ODDS_API_KEY:-}" ]; then
        echo "ODDS_API_KEY is not set — is .env present and readable by cron?"
        exit 1
    fi
    run_capped "$PY" scripts/07_odds.py --week "$WEEK" --snapshot "$SNAPSHOT" ${FORCE:+--force-refresh}

    # Game lines on the same firing, and deliberately AFTER the props.
    #
    # The props are the irreplaceable half — a player price the API has stopped
    # serving cannot be bought back, and this project has already lost three
    # seasons of book-level history to a write that threw it away. Game lines
    # are the cheapest markets the API sells and they are far tighter (best
    # price beats consensus by 1.23pp on moneyline against 2.31pp on anytime
    # TD), so they are worth collecting and not worth risking the props for.
    # Failure here is reported and does not change the exit status.
    if [ -n "${SEASON:-}" ]; then
        if ! run_capped "$PY" scripts/53_game_lines.py --snapshot "$SNAPSHOT" \
                --season "$SEASON" --week "$WEEK"; then
            echo "  game lines failed (exit $?) — props are archived, which is what matters"
        fi
    fi
} 2>&1 | tee -a "$LOG"

STATUS=${PIPESTATUS[0]}
echo "$(date -u +%FT%TZ) exit=$STATUS" | tee -a "$LOG"

# Write down what the tracked rules say, at the price that was just captured.
#
# Only on the opening snapshot: the close firings run fifteen times a week and
# this costs a prediction each time. The open is also the right moment — it is
# the price you could actually have acted on, and closing-line value is scored
# against the close that comes later.
#
# Never allowed to fail the capture. The odds are the irreplaceable half: a
# price the API has stopped serving cannot be bought back, while a missed
# recording is one `make shortlist` away.
if [ "$STATUS" -eq 0 ] && [ "$SNAPSHOT" = "open" ]; then
    {
        echo "--- recording tracked picks for week $WEEK"
        for MARKET in anytime_td first_td; do
            "$PY" scripts/39_shortlist.py --week "$WEEK" --target "$MARKET" \
                || echo "  shortlist failed for $MARKET (exit $?) — picks not recorded"
        done
    } 2>&1 | tee -a "$LOG"
fi

# Rebuild the published board after a closing capture.
#
# The market-movement features are null until a closing price exists. Measured
# on `book_last_update`, the archive's two quote times per player-game sit at
# ~72h before kickoff and ~0.3-1.2h before it, with nothing between — so a
# board built on Saturday has the open and nothing else, and every movement
# feature on it is legitimately empty. Only a board built AFTER a close carries
# them.
#
# Close only, and only when the capture actually fetched: the window guard at
# the top exits before this on a slot with no kickoff in range, so reaching
# here means a real snapshot landed. `site/v2` is rebuilt alongside `site/`
# because the two are the same payload and a stale one of them is worse than
# neither — that is the failure the `--out` pairing exists to prevent.
#
# Never allowed to fail the capture, for the reason above it: the prices are
# the irreplaceable half, and a board is one `make board` away.
if [ "$STATUS" -eq 0 ] && [ "$SNAPSHOT" = "close" ]; then
    {
        echo "--- rebuilding the board on the closing prices"
        "$PY" scripts/47_export_site.py \
            || echo "  board rebuild failed (exit $?) — prices are archived, run \`make board\`"
        "$PY" scripts/51_export_app.py --out site/v2 --brand "${BRAND:-Pick Six}" \
            || echo "  v2 rebuild failed (exit $?) — run \`make app\`"
    } 2>&1 | tee -a "$LOG"
fi

# Keep the last 40 logs; this runs twice a week forever.
ls -1t "$LOG_DIR"/odds_*.log 2>/dev/null | tail -n +41 | xargs -r rm -f
exit "$STATUS"
