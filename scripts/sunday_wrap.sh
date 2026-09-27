#!/bin/bash
# Put the finished week on the site, the evening it finishes.
#
# The Sunday jobs CAPTURE and nothing else: odds close, inactives and the
# public split all write to `data/` and stop there. The board on the server is
# whatever was last exported, so from the final whistle until Tuesday's
# rollover the site showed a slate of games with no results on it — every
# score ungraded, every prop row still reading as a live bet.
#
# This pulls the results and republishes. It does NOT touch the odds API:
# `01_ingest.py` reads nflverse, which is free, and nothing here captures a
# price. So it is safe to run more than once, and it is scheduled more than
# once on purpose — the late games settle around 23:30 ET and nflverse
# publishes their play-by-play some time after that, so the first attempt
# often lands before the data does and the second picks it up.
#
#   ./scripts/sunday_wrap.sh          # ingest results, rebuild, deploy
#
# Monday night's game is NOT covered here, and does not need to be: Tuesday's
# `week_rollover.sh` runs the same ingest before it builds the next board.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
LOG_DIR="logs"
mkdir -p "$LOG_DIR"
DATE="$(date +%Y%m%d_%H%M%S)"
LOG="$LOG_DIR/sunday_wrap_$DATE.log"

PY=".venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

say() { echo "$@" | tee -a "$LOG"; }

run() {
    local name="$1"; shift
    say "  -> $name"
    if ! "$@" >> "$LOG" 2>&1; then
        say "     FAILED (exit $?) — see $LOG"
        return 1
    fi
}

# A REFUSAL IS NOT A CRASH, AND NEITHER IS IT SUCCESS.
#
# Exit 3 means the export declined because its artifacts describe a model
# other than the one being served. That is a chore, not a bug: the board is
# fine, the evaluation numbers beside it are not, and publishing anyway would
# put one model's predictions next to another's record. Say which, and stop
# before the deploy rather than shipping past it.
export_or_stop() {
    local name="$1"; shift
    say "  -> $name"
    "$@" >> "$LOG" 2>&1
    local rc=$?
    case $rc in
      0) return 0 ;;
      3) say "     REFUSED: artifacts predate the served model. Nothing was"
         say "     published. Run \`make evaluate\` (and \`make longshot\`),"
         say "     then re-run this. See $LOG for the list."
         return 3 ;;
      *) say "     FAILED (exit $rc) — see $LOG"
         return 1 ;;
    esac
}

say "=== $(date -u +%FT%TZ) sunday wrap ==="

# ONLY PUBLISH WHEN THERE IS SOMETHING NEW TO SHOW.
#
# Scheduled at several times so that one of them lands after nflverse has the
# late games, which means most of these runs have nothing to add. Republishing
# an identical site every hour would bury a real change in a list of no-ops.
BEFORE="$("$PY" - <<'PYEOF' 2>>"$LOG"
import sys
sys.path.insert(0, ".")
try:
    import polars as pl
    from src.utils.paths import get_path
    s = pl.read_parquet(get_path("raw") / "schedules.parquet")
    s = s.filter((pl.col("game_type") == "REG")
                 & pl.col("home_score").is_not_null())
    print(s.height)
except Exception as e:                      # noqa: BLE001
    print("ERR", e, file=sys.stderr)
    print(-1)
PYEOF
)"

# THE WHOLE CHAIN, EVERY TIME, and only the publish is conditional.
#
# The first version of this ran ingest and targets and then decided whether to
# go on. That left the pipeline INCONSISTENT on the runs that stopped: new
# play-by-play on disk, and a candidate matrix still saying nobody scored in
# the week it covers. `test_an_unplayed_game_is_not_a_game_where_nobody_scored`
# caught it within the minute — a week with play-by-play must have produced
# labels from it, and half the chain cannot satisfy that.
#
# All four are idempotent and none of them spends an odds credit, so running
# them on a night with nothing new costs CPU and nothing else. The deploy is
# the step worth gating, and it is gated below.
run ingest     "$PY" scripts/01_ingest.py     || exit 1
run targets    "$PY" scripts/02_targets.py    || exit 1
run candidates "$PY" scripts/03_candidates.py || exit 1
run features   "$PY" scripts/04_features.py   || exit 1

AFTER="$("$PY" - <<'PYEOF' 2>>"$LOG"
import sys
sys.path.insert(0, ".")
try:
    import polars as pl
    from src.utils.paths import get_path
    s = pl.read_parquet(get_path("raw") / "schedules.parquet")
    s = s.filter((pl.col("game_type") == "REG")
                 & pl.col("home_score").is_not_null())
    print(s.height)
except Exception as e:                      # noqa: BLE001
    print("ERR", e, file=sys.stderr)
    print(-1)
PYEOF
)"

say "  graded games: $BEFORE -> $AFTER"
if [ "$BEFORE" = "$AFTER" ] && [ "${1:-}" != "--force" ]; then
    say "  no new finals since the last run — nothing to publish"
    say "=== $(date -u +%FT%TZ) done ==="
    exit 0
fi

export_or_stop board "$PY" scripts/47_export_site.py  || exit 1
export_or_stop site  "$PY" scripts/20_export_html.py  || exit 1

# Same guard as the rollover: without the key ssh falls through to asking for
# a password, and there is nobody at the keyboard at midnight.
if [ -f "$HOME/.ssh/id_ed25519_squarespro" ]; then
    run deploy "$PY" scripts/58_deploy.py \
        || say "     deploy failed — the board is built; run" \
               "\`python scripts/58_deploy.py\` when you can"
else
    say "  -> deploy skipped: no deploy key at ~/.ssh/id_ed25519_squarespro"
fi

say "=== $(date -u +%FT%TZ) done ==="

# Keep the last 20.
ls -1t "$LOG_DIR"/sunday_wrap_*.log 2>/dev/null | tail -n +21 | xargs -r rm -f
exit 0
