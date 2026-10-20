.PHONY: all ingest targets candidates features train predict clean parity-frame \ books
	docker-build docker-up docker-down docker-logs docker-shell \
	docker-pipeline docker-prod docker-prod-down docker-build-amd64 \
	backtest walkforward longshot economics clusters evaluate wager wager-report \
	odds-open odds-close odds-schedule odds-schedule-on odds-schedule-off \
	odds-schedule-status rollover rollover-force rollover-on \
	rollover-off rollover-status \
	decay shop site combos publish dashboard \
	lock versions version-show promote rollback version-diff version-verify \
	champion screen gate settle noise-floor experiments diagnose version-prune \
	families ablate retention settle-overlay line-movement filter-sweep \
	shortlist shortlist-backtest betlog positions market-shape \
	cover-backtest cover-selection rehearse lay-sheet freeze prop-picks \
	backup-odds backup-on backup-off

# The interpreter, resolved once. Every recipe used to call a bare `python`,
# which does not exist on a machine where the venv is not activated — this is
# not hypothetical, `make clv` failed on it. A Makefile that only works from an
# already-activated shell is a trap during a live week, when the thing running
# it may be launchd or a fresh terminal rather than the shell you developed in.
# Prefer the project venv, fall back to whatever python3 resolves to.
PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; \
	else command -v python3 2>/dev/null || echo python; fi)

# Defaults so the evaluation targets run without arguments. Override per call:
#   make backtest SEASON=2024 TARGET=first_td
TARGET ?= anytime_td
SEASON ?= 2025
SEEDS ?= 5

all: ingest targets candidates features train

ingest:
	$(PYTHON) scripts/01_ingest.py

targets:
	$(PYTHON) scripts/02_targets.py

candidates:
	$(PYTHON) scripts/03_candidates.py

# The parity frames follow the matrix: a frame older than it fails
# test_served_path_matches_the_evaluated_path. About 5 seconds.
features:
	$(PYTHON) scripts/04_features.py
	$(MAKE) parity-frame

train:
	$(PYTHON) scripts/05_train.py

predict:
	$(PYTHON) scripts/06_predict.py

# Snapshot sportsbook prices into the append-only archive. Run weekly in season —
# unarchived weeks can never be used to calibrate model vs market.
# Usage: make odds WEEK=1
odds:
	$(PYTHON) scripts/07_odds.py --week $(WEEK)

# Closing-line value needs both ends of the market. Run `open-line` once when
# the week's board first goes up (usually Tuesday) and `odds` again near
# kickoff; scripts/13_clv.py then measures whether the market moved toward the
# players we rated above the opening price. That is the only evidence available
# within one season that an edge survives contact with money — bet outcomes are
# far too few and too skewed to settle it. Usage: make open-line WEEK=1
open-line:
	$(PYTHON) scripts/07_odds.py --week $(WEEK) --snapshot open --force-refresh

clv:
	$(PYTHON) scripts/13_clv.py

# Which book is slow, and which is generous — they are not the same
# book. Reads the per-book archive the odds capture has been writing
# for three seasons.
books:
	$(PYTHON) scripts/59_book_speed.py

# What survives every measurement, for one week: the side these markets sell,
# the disagreement sizes closing-line value has not moved against, priced at
# the best number any archived book posted. Most weeks it is empty, and it says
# which measurement emptied it. Usage: make shortlist WEEK=1
# Keep this week's player boards, all six markets, for every game not yet
# started. `weekly_odds.sh` runs it after every capture; run it by hand before
# a kickoff when a capture slot was missed. Usage: make freeze [WEEK=5]
freeze:
	$(PYTHON) scripts/66_freeze.py $(if $(WEEK),--week $(WEEK))

# Record the over/under rules' picks before kickoff. Usage: make prop-picks WEEK=5
prop-picks:
	$(PYTHON) scripts/64_prop_picks.py --week $(WEEK)

shortlist:
	$(PYTHON) scripts/39_shortlist.py --week $(WEEK) $(if $(TARGET),--target $(TARGET))

# Grade the shortlist rule itself: replayed week by week, staked flat at the
# archived close, with its one threshold fitted walk-forward. Four arms, so
# each filter has to beat the simpler thing above it.
# Usage: make shortlist-backtest  ·  make shortlist-backtest TARGET=first_td
shortlist-backtest:
	$(PYTHON) scripts/41_shortlist_backtest.py $(if $(TARGET),--target $(TARGET))

# What each position scores, what it is charged, and what we say about it.
# Reference for reading any board here. Usage: make positions
positions:
	$(PYTHON) scripts/42_position_rates.py $(if $(TARGET),--target $(TARGET))

# Why every return here is negative, without reference to the model: the book's
# own error, its margin, and what the two cost — by decile of its own number.
# Usage: make market-shape
market-shape:
	$(PYTHON) scripts/43_market_shape.py $(if $(TARGET),--target $(TARGET))

# Drive the whole Sunday chain end to end against a scratch record: capture
# checked, shortlist run, picks recorded, a paper bet on each side logged and
# scored. Touches nothing under data/. Usage: make rehearse  ·  KEEP=1 to keep
# the scratch directory around.
rehearse:
	$(PYTHON) scripts/44_rehearse.py $(if $(WEEK),--week $(WEEK)) $(if $(KEEP),--keep)

# What a No price has to be for the fade to be worth taking, player by player,
# plus a CSV with blank columns to fill in at an exchange. The only open
# question about the fade is the venue, and no backtest can reach it.
# Usage: make lay-sheet WEEK=1  ·  COMMISSION=0.02
lay-sheet:
	$(PYTHON) scripts/45_lay_sheet.py --week $(WEEK) $(if $(TARGET),--target $(TARGET)) $(if $(COMMISSION),--commission $(COMMISSION))

# Bets you actually placed, scored against the closing line — the only figure
# here that says whether an edge exists before the bankroll does.
# Usage: make betlog  ·  see scripts/40_betlog.py --add for logging one.
betlog:
	$(PYTHON) scripts/40_betlog.py

# Actionable bet card: model vs de-vigged market, ranked by EV, Kelly-staked.
# Needs cached prices — run `make odds WEEK=n` first. Usage: make bets WEEK=1
bets:
	$(PYTHON) scripts/08_bets.py --week $(WEEK)

# ── Evaluation ────────────────────────────────────────────────────────────
# These read the odds archive and the backtest frames. Re-run them after any
# retrain: the app reads their output, so leaving them stale makes the board
# and the evidence behind it disagree about the same model.

# Replay a season through the production path. Needs an odds archive.
# Usage: make backtest SEASON=2025 TARGET=anytime_td
backtest:
	$(PYTHON) scripts/10_backtest.py --season $(SEASON) --target $(TARGET)

# Retrain per test season and score each on data it never saw. The honest
# accuracy numbers on the Model performance tab come from here.
walkforward:
	$(PYTHON) scripts/11_walkforward.py --target $(TARGET)

# Does our ranking beat the book inside the longshot band?
longshot:
	$(PYTHON) scripts/12_longshot.py --target $(TARGET)

# Does being right pay? Rank/price profitability and the fitted edge rule that
# the board's "Worth backing" column reads.
economics:
	$(PYTHON) scripts/14_rank_economics.py --target $(TARGET)

# What kinds of player, and what kinds of bet, are these? Fits both groupings on
# the training seasons and scores them on the seasons after. The Player types tab
# reads the JSON this writes; leaving it stale makes the tab describe roles fitted
# from a feature set that no longer exists.
clusters:
	$(PYTHON) scripts/21_clusters.py --target $(TARGET)

# What combinations of the board's top players actually did: replays the
# section's own rule over every graded backtest week and grades each slip on
# whether every leg scored. Needs the backtest CSVs (make evaluate) — until it
# has run, the app says in as many words that nothing in that table has been
# backtested, which is the truth.
combos:
	$(PYTHON) scripts/29_combos.py --target $(TARGET)

# The third target type: a count market, graded per (player, line). Trains the
# count model, grades it against 21k archived closing lines, and records that
# the market prices it better than we do — which the app's receptions page
# quotes rather than hides.
receptions:
	$(PYTHON) scripts/30_receptions.py

# The same comparison, re-made every week on the season being played, against
# the prices that were actually on offer before kickoff. Exits 2 when the model
# is AHEAD of the market — which is not good news here: every previous time
# that happened it was a leak. `-` so a 2 does not stop a chained make.
receptions-forward:
	-$(PYTHON) scripts/46_receptions_forward.py

# Everything the app reads, rebuilt in dependency order, for both markets.
# Run this after `make train` or the app will quote a model that no longer exists.
# --walk-forward retrains on earlier seasons before scoring each one. Without
# it the backtest refuses any season at or before splits.val_season, because
# scoring those with models/ measures the model against its own training data —
# which silently doubled every profitability figure in this project.
evaluate:
	@for t in anytime_td first_td; do \
		for s in 2023 2024 2025; do \
			$(PYTHON) scripts/10_backtest.py --season $$s --target $$t --walk-forward; \
		done; \
		$(PYTHON) scripts/14_rank_economics.py --target $$t; \
		$(PYTHON) scripts/11_walkforward.py --target $$t; \
		$(PYTHON) scripts/21_clusters.py --target $$t; \
		$(PYTHON) scripts/13_clv.py --target $$t; \
		$(PYTHON) scripts/29_combos.py --target $$t; \
		$(PYTHON) scripts/37_cover_backtest.py --target $$t; \
		$(PYTHON) scripts/38_cover_selection.py --target $$t; \
	done
	$(PYTHON) scripts/12_longshot.py --target anytime_td
	$(MAKE) parity-frame

# The frame `evaluation.parity` compares against, and the reason it is separate.
#
# Everything above runs the backtest with --walk-forward, whose folds retrain
# from scratch on earlier seasons. That is the honest out-of-sample number and
# it is NOT the production model, so comparing it to what the app serves asks
# whether two different models agree — which they do not, by 0.0147 mean on
# anytime TD against 1.9e-9 for a frame built on the production weights.
#
# The two cannot share a filename without silently overwriting each other's
# answer, so parity gets its own. Rebuilt here because it goes stale the moment
# the feature matrix moves, and a stale one makes the check skip.
parity-frame:
	@for t in anytime_td first_td; do \
		$(PYTHON) scripts/10_backtest.py --season $(shell $(PYTHON) -c "from src.utils.config import get_config; print(get_config()['splits']['test_season'])") \
			--target $$t --out-name parity_$(shell $(PYTHON) -c "from src.utils.config import get_config; print(get_config()['splits']['test_season'])").csv; \
	done

# ── Experiments ───────────────────────────────────────────────────────────
# An experiment is a config overlay in a YAML file, scored on the same folds
# the walk-forward uses and compared to the champion PER GAME — pooled Top-1
# carries +/-1.5% and cannot resolve the changes worth making.
# See docs/MODEL_ITERATION.md.
#
# Run `make champion` once before the first experiment: comparison needs the
# champion's per-game rows, which a version manifest does not carry.
#   make screen EXP=experiments/depth4.yaml     # minutes, never promotes
#   make gate   EXP=experiments/depth4.yaml     # both markets, every model
champion:
	$(PYTHON) scripts/23_experiment.py baseline --id $(ID)

screen:
	$(PYTHON) scripts/23_experiment.py screen $(EXP) $(if $(MARKET),--market $(MARKET))

gate:
	$(PYTHON) scripts/23_experiment.py gate $(EXP) $(if $(MARKET),--market $(MARKET))

# Settle a close call the seed cannot be ruled out of: run the same overlay at
# N seeds, average each game's outcome across them, then pair on the averages.
# Both models come from the same run, so folds and features are identical on
# each side and the model is the only difference. This is the test that decided
# first TD's production model, which was done by hand and so was never repeatable.
#   make settle EXP=experiments/x.yaml MODEL=ensemble AGAINST=xgb SEEDS=5
settle:
	$(PYTHON) scripts/23_experiment.py settle $(EXP) --model $(MODEL) \
		--against $(AGAINST) --seeds $(SEEDS) $(if $(MARKET),--market $(MARKET))

# Settle a CONFIG change rather than a model choice. `settle` compares two
# models inside one run, which cannot judge an overlay — both sides of a
# feature-set experiment carry the same model name. This pairs the overlay
# against the champion recipe at matched seeds, baseline side reused from the
# noise-floor runs.
#   make settle-overlay EXP=experiments/lean-25-families.yaml SEEDS=5
settle-overlay:
	$(PYTHON) scripts/23_experiment.py settle-overlay $(EXP) \
		--seeds $(SEEDS) $(if $(MARKET),--market $(MARKET))

# What is the random seed alone worth? Every guard band in the gate is this
# number. Without it, a 0.4-point difference has no scale to be read on.
noise-floor:
	$(PYTHON) scripts/23_experiment.py noise-floor --seeds $(SEEDS)

# What has been tried, and what came of it.
experiments:
	$(PYTHON) scripts/23_experiment.py ledger

# Where is Top-1 actually lost? Headroom against the book, whether the misses
# are the wrong team or the wrong player on the right team, how many games were
# coin flips, and what the candidate pool cannot reach. Changes nothing — it
# exists to order the model work by evidence rather than by hunch.
# Writes a dated snapshot to diagnostics/, which is committed.
diagnose:
	$(PYTHON) scripts/24_diagnose.py --target $(TARGET) $(if $(REUSE),--reuse)

# ── Feature-set size ──────────────────────────────────────────────────────
# Two directions on the same question, and they do not answer each other.
#
#   ablate     drop one family, retrain, see what is missed
#   retention  keep only the top K families, retrain, see what is gained
#
# Ablation cannot tell you whether the feature set is too big: families are
# redundant, so dropping one lets a correlated survivor cover for it. Only
# retention builds up. Both are paired per game against the full set, and both
# discard their saved rows when the feature matrix hash moves — a half-current
# table reads as one measurement and is worse than none.
#
# `families` records which builder produced each column and must be re-run
# after any change to a build_* function; the other two are ordered by it.
families:
	$(PYTHON) scripts/26_feature_families.py $(if $(SHOW),--show)

ablate:
	$(PYTHON) scripts/27_ablate.py --market $(TARGET) \
		$(if $(FAMILY),--family $(FAMILY)) $(if $(SHOW),--show)

retention:
	$(PYTHON) scripts/31_retention.py --market $(TARGET) $(if $(SHOW),--show)

# Does open-to-close movement say anything the closing price does not?
# Measured 2026-08-19: no, on both markets. Kept runnable because the archive
# grows every week and a rejection should stay checkable, not become folklore.
# See docs/MODEL_ITERATION.md 3j.
line-movement:
	$(PYTHON) scripts/32_line_movement.py --market $(TARGET)

# Does trimming the candidate pool help? Swept on 2026-08-13 and rejected, but
# on the leaked matrix — the same vintage that made the ablation table wrong in
# sign. Re-runnable for that reason, and because the pool moves Top-1 through
# two channels the 99.9% ceiling does not cover: the model refits on the
# survivors, and within-team share normalization rescales teammates.
filter-sweep:
	$(PYTHON) scripts/36_filter_sweep.py --market $(TARGET) $(if $(SHOW),--show)

# Grade the full-cover section against results. Everything that section shows
# is a product of five estimates and five prices, and a product compounds
# whatever is wrong with each term — so what it projects and what it returned
# is the sharpest reading of calibration on the board.
cover-backtest:
	$(PYTHON) scripts/37_cover_backtest.py --target $(TARGET) $(if $(SHOW),--show)

# And whether a different rule would have done better: 44 selections, the
# hindsight ceiling above them, a walk-forward chooser among them, and the same
# machinery on random orderings — because a best-of-44 and a hindsight ceiling
# are both beaten by noise here, and only the control shows it.
cover-selection:
	$(PYTHON) scripts/38_cover_selection.py --target $(TARGET) $(if $(SHOW),--show)

# ── Model versions ────────────────────────────────────────────────────────
# `models/` holds one state and every `make train` overwrites it. Lock a state
# you like and it survives; promote a version and it is what the app serves;
# roll back and you are on the previous one. Manifests under models/registry/
# are committed, the weights under models/versions/ are not.
# See docs/MODEL_ITERATION.md.
#   make lock ID=2026.08.12-baseline NOTE="baseline lock"
lock:
	$(PYTHON) scripts/22_version.py lock $(ID) --note "$(NOTE)"

versions:
	$(PYTHON) scripts/22_version.py list

version-show:
	$(PYTHON) scripts/22_version.py show $(ID)

# Make a version the default the app and pipeline read. Per-market with
# MARKET=first_td; both markets otherwise.
promote:
	$(PYTHON) scripts/22_version.py promote $(ID) $(if $(MARKET),--market $(MARKET))

rollback:
	$(PYTHON) scripts/22_version.py rollback $(if $(MARKET),--market $(MARKET))

version-diff:
	$(PYTHON) scripts/22_version.py diff $(A) $(B)

# Retire duplicate weight snapshots. Two versions can differ in every way that
# matters to the record — config, metrics, why they exist — and still carry
# byte-identical weights; a config-only change does exactly that. Manifests are
# never touched, so provenance and metrics survive in git. Dry run by default:
#   make version-prune          # show what would go
#   make version-prune APPLY=1  # delete it
version-prune:
	$(PYTHON) scripts/22_version.py prune $(if $(APPLY),--apply)

# Does models/ actually hold what CURRENT.json claims? Run after any retrain.
version-verify:
	$(PYTHON) scripts/22_version.py verify

# ── Betting ───────────────────────────────────────────────────────────────
# Log a bet you actually placed, at the price you actually got. The only
# measurement of what the backtest's assumptions cost in practice.
#   make wager ARGS="--season 2026 --week 1 --player 'Blake Corum' --odds 125 --stake 1"
wager:
	$(PYTHON) scripts/15_wager.py add $(ARGS)

wager-report:
	$(PYTHON) scripts/15_wager.py report

# Is the edge still there? Run after every completed week. Exits non-zero when
# the recent numbers fall below what the backtest says to expect — a model that
# stops working does not announce it.
decay:
	$(PYTHON) scripts/17_decay.py --target $(TARGET)

# What the best available price is worth against the consensus we modelled on.
# Needs per-book quotes, which only exist for weeks captured since 2026-08-11.
# Usage: make shop WEEK=1
shop:
	$(PYTHON) scripts/18_shop.py --week $(WEEK) --target $(TARGET)

# ── Publishing ────────────────────────────────────────────────────────────
# One self-contained site/index.html, for sending to someone who does not have
# the repo. It runs app.py against a recording Streamlit, so it always matches
# what the live app would show — but only at the moment you build it. Rebuild
# after `make predict` or `make odds`, or the board goes stale silently.
site:
	$(PYTHON) scripts/20_export_html.py

# One self-contained site/dashboard.html: both markets, on whatever version
# CURRENT.json says each one is serving. Unlike `site` it does not run app.py —
# it reads the same src/ functions the app calls, so it can show what the app
# has no widget for: Top-1 through Top-10, unpriced players beside priced ones
# in one table, and a combination search that runs in the browser.
# Usage: make dashboard  ·  make dashboard WEEK=2  ·  make dashboard OPEN=--open
#
# SEASON is forwarded only when you pass it on the command line. The `SEASON ?=
# 2025` default at the top of this file is the backtest's test season, and
# forwarding it unconditionally pinned the published page to 2025 while the
# exporter's own `current_slate` was sitting there ready to find the live one —
# so `make dashboard` quietly published last season and said nothing.
dashboard:
	$(PYTHON) scripts/34_export_dashboard.py $(if $(WEEK),--week $(WEEK)) $(if $(filter command line,$(origin SEASON)),--season $(SEASON)) $(OPEN)

# One self-contained site/site.html: the same data as `dashboard`, under the
# design in design/, as four pages instead of nine tabs. This is what the
# weekly rollover now builds. `dashboard` still works and is worth keeping
# until this has been read on a few real slates — the two draw from one payload
# builder, so they cannot disagree about the numbers, only about the shape.
# Usage: make board  ·  make board WEEK=3  ·  make board OPEN=--open
board:
	$(PYTHON) scripts/47_export_site.py $(if $(WEEK),--week $(WEEK)) $(if $(filter command line,$(origin SEASON)),--season $(SEASON)) $(OPEN)

# The same page, written to public/index.html and nothing else.
#
# Serving site/ does NOT serve this board: that directory also holds
# index.html, which is the Streamlit recording from `make site`, and a web
# server hands out index.html by default. Upload public/ instead and the only
# thing in it is the board, under the name every host looks for.
#
# `public/` is disposable and rebuilt each time. Nothing else should be put
# there, because the point of the directory is that its contents are
# unambiguous.
BRAND ?= Pick Six
launch:
	@rm -rf public && mkdir -p public
	$(PYTHON) scripts/47_export_site.py --out public/index.html --brand "$(BRAND)" $(if $(WEEK),--week $(WEEK))
	@echo
	@echo "public/ is ready to upload. It holds one file:"
	@ls -la public/
	@echo
	@echo "Open it locally with:  open public/index.html"

# ── v2: the same board, installable ───────────────────────────────────────
# Three files into site/v2, and they go up together. The service worker's
# scope is the directory it is served from, so a page uploaded without its
# sw.js beside it loads, works, and never goes offline — silently, which is
# the failure this target's message exists to prevent.
#
# Same payload as `launch`, same models, same numbers. What differs is the
# shell: a manifest, a worker, and the CSS that a window with no browser
# chrome needs. See src/export/pwa.py.
app:
	$(PYTHON) scripts/51_export_app.py --out site/v2 --brand "$(BRAND)" $(if $(WEEK),--week $(WEEK))
	@echo
	@ls -la site/v2/
	@echo
	@echo "upload all three to the same directory."

# Both pages, in one go. WHEN to run this, in order of how wrong the page is
# if you do not:
#
#   1. After `make evaluate`. That is the natural trigger — every artifact the
#      pages read is fresh by construction, so the gate below passes.
#   2. After a promote. Promotion swaps the weights and nothing else, so the
#      published page describes the PREVIOUS model until it is rebuilt.
#      `make promote` now prints exactly what it invalidated.
#   3. Weekly, after the close-odds capture: the board's prices move even in a
#      week the model does not.
#
# Not on a timer independent of the pipeline. That is how a page ends up
# confidently showing last month's model to whoever opens it.
#
# Both exporters refuse when any artifact they read predates the model being
# served (src/evaluation/freshness.export_blockers). `--force` overrides, and
# exists so the gate gets respected rather than deleted.
publish:
	$(PYTHON) scripts/20_export_html.py $(if $(FORCE),--force)
	$(PYTHON) scripts/34_export_dashboard.py $(if $(FORCE),--force)
	@echo
	@echo "Published site/index.html and site/dashboard.html"

# ── Weekly odds capture ───────────────────────────────────────────────────
# The week number is derived from the schedule, so these take no arguments.
# Run `odds-open` when the week's board goes up and `odds-close` before the
# Sunday slate — closing-line value needs both ends.
odds-open:
	./scripts/weekly_odds.sh open

odds-close:
	./scripts/weekly_odds.sh close

# Scheduling is via launchd, not cron: macOS blocks `crontab` behind Full Disk
# Access and it hangs rather than failing, and launchd runs a missed job on wake
# where cron would skip it.
#
# The capture times are DERIVED from the season's kickoffs, not written down —
# a single Sunday-noon close cannot reach the 33 of 272 games that kick off
# earlier, and those prices are unbuyable afterwards. Re-run `odds-schedule` any
# time `make ingest` refreshes the schedule.
odds-schedule:
	$(PYTHON) scripts/25_odds_schedule.py

odds-schedule-on:
	$(PYTHON) scripts/25_odds_schedule.py --write --load

odds-schedule-off:
	@for l in com.mthompson.nfl-odds-open com.mthompson.nfl-odds-close; do \
		launchctl bootout "gui/$$UID/$$l" 2>/dev/null; \
		launchctl disable "gui/$$UID/$$l"; \
		echo "disabled $$l"; \
	done

odds-schedule-status:
	@launchctl list | grep nfl-odds || echo "not loaded"
	@launchctl print-disabled "gui/$$UID" 2>/dev/null | grep nfl-odds || true

# Build next week's board as soon as nflverse publishes its weekly roster.
#
# The candidate pool inner-joins the schedule to the weekly roster, so until
# that roster exists the upcoming week has 32 rows — one DEF/ST per team — and
# no players. Nothing errors, so the only signal is a board with nobody on it.
# This job watches for the roster and builds when it lands; it has to win the
# race against the opening odds capture, which records the tracked rules at the
# opening price.
#
# Guarded and idempotent — exits in seconds when there is nothing to do.
rollover:
	./scripts/week_rollover.sh

rollover-force:
	FORCE_ROLLOVER=1 ./scripts/week_rollover.sh

rollover-on:
	@cp config/launchd/com.mthompson.nfl-week-rollover.plist \
		$$HOME/Library/LaunchAgents/
	@launchctl bootout "gui/$$UID/com.mthompson.nfl-week-rollover" 2>/dev/null; \
		launchctl enable "gui/$$UID/com.mthompson.nfl-week-rollover"; \
		launchctl bootstrap "gui/$$UID" \
			"$$HOME/Library/LaunchAgents/com.mthompson.nfl-week-rollover.plist" \
		&& echo "loaded com.mthompson.nfl-week-rollover"

rollover-off:
	@launchctl bootout "gui/$$UID/com.mthompson.nfl-week-rollover" 2>/dev/null; \
		launchctl disable "gui/$$UID/com.mthompson.nfl-week-rollover"; \
		echo "disabled com.mthompson.nfl-week-rollover"

rollover-status:
	@launchctl list | grep nfl-week-rollover || echo "not loaded"
	@ls -1t logs/rollover_*.log 2>/dev/null | head -1 | xargs -r tail -20

test:
	$(PYTHON) -m pytest tests/ -q

# Deletes only what can be regenerated for free. data/archive/ is NEVER touched —
# it holds purchased historical odds that the API sells once and cannot be
# re-downloaded without paying again.
clean:
	rm -rf data/raw/*.parquet data/processed/*.parquet models/*.pkl output/*.json output/*.csv output/plots/*.png

# Timestamped copies of everything that cannot be bought or rebuilt. Run
# before anything risky.
#
# IT USED TO COPY ONE FILE OF THREE. An audit on 2026-10-06 found the two it
# left out were the two worth most:
#
#   odds_books.parquet    32 MB, 2.2M rows, and the ONLY file carrying a
#                         `side` column — every under price we hold is in
#                         here and nowhere else
#   tracked_picks.csv     the only append-only record of what a rule said
#                         BEFORE kickoff, with the price available at the
#                         time. 284 rows that no rerun can reproduce
#
# Both are gitignored (`data/`), so a timestamped sibling is the only copy
# that exists. That protects against a bad write, NOT against losing the
# disk — see `nfl-predictions-moving-off-the-laptop`.
BACKUP_FILES := data/archive/odds_history.parquet \
                data/archive/odds_books.parquet \
                data/archive/game_lines.parquet \
                data/archive/action_public.parquet \
                data/archive/public_money.parquet \
                data/archive/line_history.parquet \
                data/tracked_picks.csv

# How many copies of each file to keep. A copy identical to the newest one is
# skipped, so this counts real changes, not runs: two byte-identical copies
# 22 seconds apart were sitting in the folder on 2026-10-09. `game_lines` and
# the three public-money archives were added the same day — `game_lines` is
# the only game-line archive there is, and it was never backed up.
BACKUP_KEEP ?= 14

backup-odds:
	@mkdir -p data/archive/backups
	@stamp=$$(date +%Y%m%d_%H%M%S); n=0; same=0; \
	for f in $(BACKUP_FILES); do \
		if [ -f "$$f" ]; then \
			base=$$(basename "$$f"); name=$${base%.*}; ext=$${base##*.}; \
			last=$$(ls -1t data/archive/backups/$${name}_*.$${ext} 2>/dev/null | head -1); \
			if [ -n "$$last" ] && cmp -s "$$f" "$$last"; then \
				same=$$((same+1)); \
			else \
				cp -p "$$f" "data/archive/backups/$${name}_$${stamp}.$${ext}"; \
				n=$$((n+1)); \
			fi; \
			ls -1t data/archive/backups/$${name}_*.$${ext} 2>/dev/null \
				| tail -n +$$(($(BACKUP_KEEP)+1)) | xargs -r rm -f; \
		else \
			echo "  missing, not backed up: $$f"; \
		fi; \
	done; \
	echo "Backed up $$n file(s) to data/archive/backups/ at $$stamp ($$same unchanged, kept the last $(BACKUP_KEEP) of each)"

# Nightly `backup-odds` at 03:15. Usage: make backup-on · make backup-off
backup-on:
	@cp config/launchd/com.mthompson.nfl-backup.plist $$HOME/Library/LaunchAgents/
	@launchctl bootout "gui/$$UID/com.mthompson.nfl-backup" 2>/dev/null; \
		launchctl enable "gui/$$UID/com.mthompson.nfl-backup"; \
		launchctl bootstrap "gui/$$UID" \
			"$$HOME/Library/LaunchAgents/com.mthompson.nfl-backup.plist" \
		&& echo "loaded com.mthompson.nfl-backup"

backup-off:
	@launchctl bootout "gui/$$UID/com.mthompson.nfl-backup" 2>/dev/null; \
		launchctl disable "gui/$$UID/com.mthompson.nfl-backup"; \
		echo "disabled com.mthompson.nfl-backup"

# Site deploy on request: weekly_odds.sh touches logs/.deploy_requested and
# this job runs scripts/site_deploy.sh. Usage: make deploy-on · make deploy-off
deploy-on:
	@cp config/launchd/com.mthompson.nfl-deploy.plist $$HOME/Library/LaunchAgents/
	@launchctl bootout "gui/$$UID/com.mthompson.nfl-deploy" 2>/dev/null; \
		launchctl enable "gui/$$UID/com.mthompson.nfl-deploy"; \
		launchctl bootstrap "gui/$$UID" \
			"$$HOME/Library/LaunchAgents/com.mthompson.nfl-deploy.plist" \
		&& echo "loaded com.mthompson.nfl-deploy"

deploy-off:
	@launchctl bootout "gui/$$UID/com.mthompson.nfl-deploy" 2>/dev/null; \
		launchctl disable "gui/$$UID/com.mthompson.nfl-deploy"; \
		echo "disabled com.mthompson.nfl-deploy"

test-ingest:
	$(PYTHON) scripts/01_ingest.py --test-mode

# ── Docker ──────────────────────────────────────────────────────────────────

IMAGE ?= nfl-td-predict
TAG ?= latest

docker-build:
	docker compose build

docker-up:
	docker compose up

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f app

docker-shell:
	docker compose run --rm app shell

# Override the stage: make docker-pipeline STAGE=predict
STAGE ?= all
docker-pipeline:
	docker compose --profile pipeline run --rm pipeline $(STAGE)

# Serve the baked image with no bind mounts — what Fargate will actually run.
#
# A CHECK, NOT A SERVICE. Run it to verify a build before pushing to ECR, then
# stop it. Because it has no mounts it serves whatever artifacts were baked in,
# so it goes stale the moment you retrain or re-evaluate — and a second
# dashboard on :8502 quietly disagreeing with the live one on :8501 is how you
# read last month's accuracy and believe it is this month's. Left running, it
# was 20+ hours behind and needed rebuilding twice in one day just to stop it
# contradicting the dev app.
#
#   make docker-prod        # foreground; Ctrl-C when you have seen enough
#   make docker-prod-down   # if you started it detached
docker-prod:
	docker compose --profile prod up --build prod

docker-prod-down:
	docker compose --profile prod down prod

# Fargate runs linux/amd64 (unless the task is configured for ARM64).
docker-build-amd64:
	docker buildx build --platform linux/amd64 -t $(IMAGE):$(TAG) --load .
