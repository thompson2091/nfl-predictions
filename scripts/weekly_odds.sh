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

{
    echo "=== $(date -u +%FT%TZ)  week=$WEEK  snapshot=$SNAPSHOT ==="
    if [ -z "${ODDS_API_KEY:-}" ]; then
        echo "ODDS_API_KEY is not set — is .env present and readable by cron?"
        exit 1
    fi
    "$PY" scripts/07_odds.py --week "$WEEK" --snapshot "$SNAPSHOT" ${FORCE:+--force-refresh}
} 2>&1 | tee -a "$LOG"

STATUS=${PIPESTATUS[0]}
echo "$(date -u +%FT%TZ) exit=$STATUS" | tee -a "$LOG"

# Keep the last 40 logs; this runs twice a week forever.
ls -1t "$LOG_DIR"/odds_*.log 2>/dev/null | tail -n +41 | xargs -r rm -f
exit "$STATUS"
