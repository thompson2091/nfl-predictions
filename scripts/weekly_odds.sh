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

    # The alternate ladders — every line a book sells on the four over/under
    # stats, not only its main one. Last, for the reason game lines come after
    # the props: nothing reads them yet, and their own call means a failure
    # here cannot cost a market something does read. 4 markets x 2 regions,
    # ~110 credits a firing. Added 2026-10-19; see odds_api.ALT_MARKETS.
    if ! run_capped "$PY" scripts/07_odds.py --week "$WEEK" --snapshot "$SNAPSHOT" \
            --markets passing_yards_alt receiving_yards_alt rushing_yards_alt receptions_alt \
            ${FORCE:+--force-refresh}; then
        echo "  alternate lines failed (exit $?) — main props are archived"
    fi
} 2>&1 | tee -a "$LOG"

STATUS=${PIPESTATUS[0]}
echo "$(date -u +%FT%TZ) exit=$STATUS" | tee -a "$LOG"

# IS THE WEEK BUILT YET? The capture does not care; everything after it does.
#
# Tuesday's 12:00 open lands an hour before the 13:00 rollover, and on a week
# the rosters are late it lands before any rollover at all. The prices are
# worth taking regardless — that is the opening line — but the shortlist,
# freeze and prop picks below would run against a feature matrix holding the
# 28-odd DEF/ST rows of a week nobody has built. On 2026-10-13 that printed
# "No players could be matched to a sportsbook price" and "shortlist failed"
# for both markets, and recorded a 28-row board as the frozen week 6.
#
# Nothing is lost by skipping: `week_rollover.sh` runs the shortlist, the prop
# picks and the freeze itself when it builds the week, against the open this
# run just archived. Same threshold as the rollover's own "already built".
#
# Unknown is NOT unbuilt. If the check itself fails, the steps run as they
# always did, because a noisy log is cheaper than a week with no picks.
BUILT=$("$PY" - "${SEASON:-}" "$WEEK" <<'PYEOF' 2>/dev/null
import sys

import polars as pl

from src.utils.paths import get_path

season, week = int(sys.argv[1]), int(sys.argv[2])
feat = get_path("processed", "anytime_td") / "features.parquet"
n = 0
if feat.exists():
    n = (pl.scan_parquet(feat)
         .filter((pl.col("season") == season) & (pl.col("week") == week))
         .select(pl.len()).collect().item())
print(n)
PYEOF
)
# A DEPLOY STILL RUNNING IS STOPPED, NOT WAITED FOR. The steps below write the
# frozen boards, and so does the v3 build inside a deploy; the freeze file is
# written whole from each writer's own copy, so overlapping them drops records.
# The capture has already landed above; the deploy is asked for again at the
# end. See scripts/site_deploy.sh.
DEPLOY_JOB="gui/$(id -u)/com.mthompson.nfl-deploy"
STOPPED_DEPLOY=0
if launchctl print "$DEPLOY_JOB" 2>/dev/null | grep -q "state = running"; then
    launchctl kill TERM "$DEPLOY_JOB" 2>/dev/null && STOPPED_DEPLOY=1
    echo "  stopped a deploy in progress; it is re-requested below" | tee -a "$LOG"
fi

WEEK_READY=1
if [[ "${BUILT:-}" =~ ^[0-9]+$ ]] && [ "$BUILT" -le 200 ]; then
    WEEK_READY=0
    echo "  week $WEEK is not built yet ($BUILT candidate rows) — skipping" \
         "picks and freeze; week_rollover.sh records both when it builds" \
         "the week" | tee -a "$LOG"
fi

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
if [ "$STATUS" -eq 0 ] && [ "$SNAPSHOT" = "open" ] && [ "$WEEK_READY" -eq 1 ]; then
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
# Only when the capture actually fetched: the window guard at
# the top exits before this on a slot with no kickoff in range, so reaching
# here means a real snapshot landed. `site/v2` is rebuilt alongside `site/`
# because the two are the same payload and a stale one of them is worse than
# neither — that is the failure the `--out` pairing exists to prevent.
#
# Never allowed to fail the capture, for the reason above it: the prices are
# the irreplaceable half, and a board is one `make board` away.
#
# The open rebuilds too, since 2026-10-16: the site prices over/under boards
# off the open until a close exists, and the deploy below ships what this
# writes. Only for a built week, which the Tuesday open usually is not.
if [ "$STATUS" -eq 0 ] && [ "$WEEK_READY" -eq 1 ]; then
    {
        echo "--- rebuilding the board on the $SNAPSHOT prices"
        "$PY" scripts/47_export_site.py \
            || echo "  board rebuild failed (exit $?) — prices are archived, run \`make board\`"
        "$PY" scripts/51_export_app.py --out site/v2 --brand "${BRAND:-Pick Six}" \
            || echo "  v2 rebuild failed (exit $?) — run \`make app\`"
    } 2>&1 | tee -a "$LOG"
fi

# Keep the last 40 logs; this runs twice a week forever.
# FREEZE AND RECORD AFTER EVERY CAPTURE, open or close. These slots are the
# only scheduled runs in front of each kickoff window, and both steps keep
# only games that have not started, so running them on every slot is what
# makes the last pre-kickoff board the one that is kept. After the close
# rebuild above, so the frozen board is the one priced on the newest capture.
if [ "$STATUS" -eq 0 ] && [ "$WEEK_READY" -eq 1 ]; then
    {
        echo "--- freezing week $WEEK's boards and recording prop picks"
        "$PY" scripts/66_freeze.py --week "$WEEK" \
            || echo "  freeze failed (exit $?) — run \`make freeze\` before kickoff"
        "$PY" scripts/64_prop_picks.py --week "$WEEK" \
            || echo "  prop picks failed (exit $?) — run it by hand before kickoff"
    } 2>&1 | tee -a "$LOG"
fi

# PUT THE NEW PRICES ON THE LIVE SITE — by asking, not by doing it here.
#
# Until 2026-10-16 nothing here deployed, so the live app showed whatever the
# Tuesday rollover or a manual run had last shipped; on 2026-10-15 that hid
# all 22 of the night's Gaps picks. The first fix ran the deploy right here,
# and on 2026-10-18 it held this job for twelve hours on a sleeping Mac and
# cost three closing captures. So this touches a file and exits;
# com.mthompson.nfl-deploy watches it and runs scripts/site_deploy.sh.
#
# Also asked for when a deploy was stopped above, whatever else happened, so
# stopping one never quietly cancels it.
if { [ "$STATUS" -eq 0 ] && [ "$WEEK_READY" -eq 1 ]; } || [ "$STOPPED_DEPLOY" -eq 1 ]; then
    touch "$LOG_DIR/.deploy_requested"
    echo "--- deploy requested (com.mthompson.nfl-deploy)" | tee -a "$LOG"
fi

ls -1t "$LOG_DIR"/odds_*.log 2>/dev/null | tail -n +41 | xargs -r rm -f
exit "$STATUS"
