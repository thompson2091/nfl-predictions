#!/bin/bash
# Build next week's board as soon as the data to build it exists.
#
# The candidate pool is an inner join of the schedule to the WEEKLY roster
# (src/targets/candidates.py), and nflverse publishes a week's roster during the
# week it is played. So on Monday night the upcoming week has 32 rows — one
# DEF/ST per team, manufactured from the schedule — and no players at all.
# Nothing errors; `make features` succeeds and the board is simply empty of
# people.
#
# That matters because of what runs on a clock afterwards. `weekly_odds.sh open`
# archives the week's opening prices and then records the tracked rules at those
# prices, and a rule recorded later is recorded at a worse number. So the board
# has to exist BEFORE the first open capture, which means this job cannot wait
# for someone to notice that rosters landed.
#
#   ./scripts/week_rollover.sh          # build if the data is there, else exit
#   FORCE_ROLLOVER=1 ./scripts/...      # build even if the board looks done
#
# Safe to run repeatedly: it exits without work when the board is already built
# and when the rosters are not published yet.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
LOG_DIR="logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/rollover_$(date +%Y%m%d_%H%M%S).log"

PY=".venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

say() { echo "$@" | tee -a "$LOG"; }

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

say "=== $(date -u +%FT%TZ) week rollover ==="

# What week are we building, and is it buildable? One python call answers both,
# because both questions read the same schedule.
#
# Exit 0 = build it. 3 = already built. 4 = rosters not published. 1 = unknown,
# and unknown means stop rather than guess: this writes the board that the
# opening capture then prices.
STATE=$("$PY" - <<'PYEOF' 2>>"$LOG"
import sys
from datetime import datetime, timezone

import polars as pl

from src.utils.paths import get_path

sched = pl.read_parquet(get_path("raw") / "schedules.parquet")
season = int(sched["season"].max())
cur = sched.filter(pl.col("season") == season).with_columns(
    pl.col("gameday").cast(pl.Utf8).str.slice(0, 10).alias("_d"))
today = datetime.now(timezone.utc).date()
ahead = cur.filter(pl.col("_d") >= str(today)).sort("_d")
if ahead.height == 0:
    print("season-over 0 0")
    sys.exit(1)
week = int(ahead["week"][0])

# Is the board already built? A real pool is players plus DEF/ST; 32 rows is
# DEF/ST alone, which is the empty case this job exists to fix.
built = 0
feat = get_path("processed", "anytime_td") / "features.parquet"
if feat.exists():
    built = (pl.scan_parquet(feat)
             .filter((pl.col("season") == season) & (pl.col("week") == week))
             .select(pl.len()).collect().item())
# FEATURE ROWS ARE NOT A BOARD. The Sunday wrap runs the same chain through
# features, so once the rosters are up it fills the week's rows without
# predicting it. On 2026-10-27 the rollover's ingest broke on a dropped
# download, the wrap built week 8's rows an hour later, and every slot after
# that called week 8 built with no predictions behind it.
pred = get_path("output", "anytime_td") / f"predictions_{season}_week{week}.csv"
if not pred.exists():
    built = 0

print(f"{season} {week} {built}")
PYEOF
)
RC=$?
if [ "$RC" -ne 0 ] || [ -z "${STATE:-}" ]; then
    say "  could not determine the upcoming week — stopping rather than guessing"
    exit 1
fi

read -r SEASON WEEK BUILT <<<"$STATE"
say "  season $SEASON, upcoming week $WEEK, candidate rows on disk: $BUILT"

# 32 is one DEF/ST per team and nothing else. Anything under a couple of hundred
# is not a slate.
if [ -z "${FORCE_ROLLOVER:-}" ] && [ "$BUILT" -gt 200 ]; then
    say "  week $WEEK is already built — nothing to do"
    exit 0
fi

# Has nflverse published the roster this week needs? Asking upstream rather than
# ingesting first: the ingest pulls a 140MB play-by-play file, and doing that on
# a loop every hour to discover the answer is no is the wrong shape.
"$PY" - "$SEASON" "$WEEK" <<'PYEOF' >>"$LOG" 2>&1
import sys
import warnings

warnings.filterwarnings("ignore")
import nfl_data_py as nfl

season, week = int(sys.argv[1]), int(sys.argv[2])
try:
    d = nfl.import_weekly_rosters([season])
except Exception as e:
    print(f"  could not reach nflverse ({type(e).__name__}) — will retry")
    sys.exit(4)
weeks = sorted(d["week"].unique().tolist()) if len(d) else []
print(f"  nflverse weekly rosters for {season}: weeks {weeks or 'none'}")
sys.exit(0 if week in weeks else 4)
PYEOF
GUARD=$?
# The probe writes only to the log; surface its one line on the way past.
tail -1 "$LOG"
if [ "$GUARD" -eq 4 ]; then
    say "  week $WEEK rosters not published yet — exiting, will try again"
    exit 0
fi
if [ "$GUARD" -ne 0 ]; then
    say "  roster probe failed (exit $GUARD) — stopping"
    exit 1
fi

say "  rosters are up. Building week $WEEK."

# Each step's own log, so a failure is readable without unpicking one long file.
DATE=$(date +%F)
run() {
    local name="$1"; shift
    say "  -> $name"
    "$@" > "$LOG_DIR/${name}_${DATE}.log" 2>&1
    local rc=$?
    if [ $rc -ne 0 ]; then
        say "     FAILED (exit $rc) — see $LOG_DIR/${name}_${DATE}.log"
        return 1
    fi
}

# Order matters. `targets` extracts the TDs from the play-by-play the ingest
# just pulled, which is what makes the finished week gradeable; `features` then
# folds those results into the rolling windows the new week is scored on.
run ingest    "$PY" scripts/01_ingest.py    || exit 1
run targets   "$PY" scripts/02_targets.py   || exit 1
run candidates "$PY" scripts/03_candidates.py || exit 1
# THE FORECASTS FIRST. Nothing scheduled refreshed them: the last fetch was
# 2026-10-14 and every week after it got the dome fill. Never fatal — a
# missed forecast leaves the previous one, which is better than no board.
run weather "$PY" scripts/28_weather.py --fetch --current || echo "  weather fetch failed; features use the last forecast"
run features  "$PY" scripts/04_features.py  || exit 1
# The parity frames are scored on the matrix just built. A rebuilt matrix
# leaves them older than it, and the served-vs-evaluated parity test then
# had nothing current to compare and skipped, every week (audit 2026-10-19).
# About 5 seconds; never fatal, the board does not depend on it.
run parity make PYTHON="$PY" parity-frame \
    || say "     parity frames not rebuilt — run \`make parity-frame\`"

for TT in anytime_td first_td; do
    run "predict_${TT}" "$PY" scripts/06_predict.py \
        --season "$SEASON" --week "$WEEK" --target "$TT" || exit 1
done

# EITHER JOB MAY GET HERE FIRST, AND BETWEEN THEM THE PICKS GET RECORDED.
#
# The shortlist needs prices. When this runs before the open capture there are
# none, it fails here, and `weekly_odds.sh open` records them when the snapshot
# lands. When the capture runs first — which is what happens whenever
# nflverse publishes the week's rosters late — that job finds no board and
# says "picks not recorded", and this step records them instead, off the open
# snapshot already in the cache.
#
# 2026 week 4 went the second way: rosters landed between 10:00 and 13:00, the
# 12:00 capture recorded nothing, and the 13:00 rollover wrote all 42. Not
# fatal in either order, which is the point of having it in both places.
for TT in anytime_td first_td; do
    run "shortlist_${TT}" "$PY" scripts/39_shortlist.py \
        --week "$WEEK" --target "$TT" \
        || say "     (expected before the open capture archives prices)"
done

# AND THE FOUR OVER/UNDER MARKETS, which never had a recording step at all.
# The prop edge rule is tracked from week 5; nothing in tracked_picks.csv can
# say what these markets would have bet before that, because nothing asked.
#
# Run on EVERY rollover, not once. The over/under board is thin early — week
# 5 held 29 receptions rows on the Tuesday against the hundreds it carries by
# Sunday — so a single early run would record a fraction of the week.
# `record` is idempotent on (season, week, market, rule, player), so the
# first sighting of a player is the one kept and later runs only add players
# the board did not hold before.
run "prop_picks" "$PY" scripts/64_prop_picks.py --week "$WEEK" \
    || say "     (expected before the open capture archives prices)"

# Re-measure receptions against the closes now that another week has settled.
# Not fatal either way, and deliberately loud on the GOOD result: exit 2 means
# the count model is ahead of the market, which on this market has meant a leak
# every previous time. Exit 3 is "nothing settled yet", the normal state.
"$PY" scripts/46_receptions_forward.py > "$LOG_DIR/receptions_forward_${DATE}.log" 2>&1
case $? in
  0) say "  -> receptions_forward (market better, as expected)" ;;
  2) say "  -> receptions_forward: THE MODEL IS AHEAD OF THE MARKET — see" \
         "$LOG_DIR/receptions_forward_${DATE}.log. On this market that has" \
         "meant a leak every previous time. Investigate before believing it." ;;
  3) say "  -> receptions_forward (nothing settled yet)" ;;
  *) say "  -> receptions_forward failed — see $LOG_DIR/receptions_forward_${DATE}.log" ;;
esac

export_or_stop board "$PY" scripts/47_export_site.py  || exit 1
export_or_stop site  "$PY" scripts/20_export_html.py  || exit 1

# THE LIVE SITE IS THE POINT OF THE REBUILD.
#
# Everything above this line leaves a new board on THIS LAPTOP. Without a
# deploy the site kept serving the previous week until someone remembered,
# which is the failure that is hardest to notice: the page loads, it is
# internally consistent, and it is a week old.
#
# Its own build rather than `--no-build`: the steps above write the v1 site,
# and `site/v3` comes from `52_export_v3.py`, which only the deploy runs.
#
# ONLY WITH THE DEPLOY KEY IN PLACE. Without it ssh falls through to asking
# for a password, and there is nobody at the keyboard at 07:00 on a Tuesday —
# on macOS that can raise a dialog against an empty desktop instead of
# failing. Not fatal either way: the board is built and local, and the deploy
# is one command away.
if [ -f "$HOME/.ssh/id_ed25519_squarespro" ]; then
    run deploy "$PY" scripts/58_deploy.py \
        || say "     deploy failed — the board is built; run" \
               "\`python scripts/58_deploy.py\` when you can"
else
    say "  -> deploy skipped: no deploy key at ~/.ssh/id_ed25519_squarespro"
fi

say "  week $WEEK board built."

# THE TUESDAY READ: the forward record per market, with each one marked a
# candidate or not yet. A report, not a lever — nothing here changes a
# threshold. See `nfl-predictions-weekly-improvement-loop`.
"$PY" scripts/67_forward_report.py 2>>"$LOG" | tee -a "$LOG"

# Freeze the new week's boards for every game not yet started, so the first
# board of the week is kept even if no capture slot runs before Thursday.
"$PY" scripts/66_freeze.py --week "$WEEK" >>"$LOG" 2>&1 \
    || say "  freeze failed — run \`make freeze WEEK=$WEEK\`"

say "=== $(date -u +%FT%TZ) done ==="

# Keep the last 20 rollover logs.
ls -1t "$LOG_DIR"/rollover_*.log 2>/dev/null | tail -n +21 | xargs -r rm -f
exit 0
