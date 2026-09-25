# Data Sources

Every input the model consumes, where it comes from, how often it refreshes, and
how it fails. Read this before trusting a number the app shows you.

The governing rule: **no probability, rate, or weight in this project is a
hand-set constant.** Anything that looks like a magic number is fit from the data
below and refit on every training run. Where a starting value is unavoidable
(the blend bootstrap), it is declared in `config/settings.yaml`, labelled as a
bootstrap, and replaced automatically once real data exists.

---

## 0. Known source problems, ranked by what they cost us

| Problem | Impact | Status |
|---|---|---|
| ~~`nfl_data_py` is deprecated~~ | Was the *root cause* of the 2025 weekly-stats gap | ✅ **Migrated to [`nflreadpy`](https://nflreadpy.nflverse.com/)**. Weekly stats went from 54,479 rows stopping at 2024 to **199,865 rows covering 2015–2025**. Returns Polars natively — no pandas round-trip |
| ~~Depth charts stale~~ | Drove the `snap_pct` zeroing bug and the phantom Week-1 fades | ✅ Current-format depth charts now **974,305 rows, refreshed daily** (was 554,215 stale to March). Still re-run ingest close to kickoff |
| ~~No historical odds~~ | Made every market claim unfalsifiable | ✅ **Backfilled 2026-08-10/11 from The Odds API historical endpoint.** `data/archive/odds_history.parquet` now holds **119,320 rows over 2023–2025**, of which **50,281 player-game-market keys carry both an `open` and a `close` price** and 47,248 of those moved |
| **Line movement is not a feature** | Three seasons of open→close revision sit on disk and no model reads them. `src/features/` contains no reference to the archive | Open. This is the one input that is not another summary of on-field events, and the 33 existing feature families do not cover it |
| **`practice_status` unused** | `injuries.parquet` carries the Wed/Thu/Fri DNP / Limited / Full progression back to 2015; `injury_features.py` reads only `report_status` | Open. Four injury features exist where the source supports more |
| Injuries stop at 2025 | Injury features go stale for the predict season | Same migration. Verify coverage populates before week 1 — a block of features going null→0 at predict time is the exact shape of the `is_cold`/`season_right` defect |

**The historical-odds gap was the one worth money, and it is closed.** What
replaced it as the top problem is smaller and free: the archive is bought,
graded and sitting there, and nothing downstream of the blend weight consumes
it.

Two things it now makes possible that were not:

- **Closing-line value is measurable.** `make clv` reads the archive and writes
  `output/<market>/clv.json`. Both markets beat their shuffled null by ~5
  points — anytime 58.3% against 53.1% on 17,589 observations, first TD 61.1%
  against 55.9% on 15,991. The players we rate above the de-vigged open are the
  ones the market then shortens.
- **It is the highest-powered metric here by an order of magnitude.** The Top-1
  walk-forward sees 1,131 games against a ~0.5pp seed band; CLV sees ~16,000
  player-games per market. Feature experiments judged only on Top-1 have been
  rejected at effect sizes that instrument cannot resolve — first TD reads NO
  EDGE DEMONSTRATED on ROI (−2.4%, [−11.2, +6.7]) and +5.3 points on CLV. Read
  both before concluding a candidate is worthless.

---

## 1. nflverse — play-by-play, rosters, snaps, depth charts, schedules

| | |
|---|---|
| Provider | [nflverse](https://github.com/nflverse/nflverse-data), via the `nfl_data_py` package |
| Access | Public, free, no key. Parquet released on GitHub |
| Licence | CC-BY-4.0 |
| Loaded by | `src/ingest/loader.py` |
| Lands in | `data/raw/*.parquet` |
| Refresh | `make ingest`. In-season, nflverse updates within ~24h of a game |
| Coverage | `seasons.start`–`seasons.end` in `config/settings.yaml` (currently 2015–2025) |

Files pulled:

| File | Function | Notes |
|---|---|---|
| `pbp.parquet` | `import_pbp_data` | The spine. Every label and most team/opponent features derive from it |
| `weekly_stats.parquet` | `import_weekly_data` | **Lags — see the trap below** |
| `rosters.parquet` | `import_weekly_rosters` | Also pulled for `predict_season` so upcoming players exist as candidates |
| `schedules.parquet` | `import_schedules` | Includes `spread_line` / `total_line`, which feed the scorer-rate prior |
| `snap_counts.parquet` | `import_snap_counts` | |
| `depth_charts.parquet` | `import_depth_charts` | Stops at 2024; `depth_charts_new.parquet` covers recent seasons |
| `ngs_receiving/rushing.parquet` | `import_ngs_data` | 2016+ only |
| `injuries.parquet` | `import_injuries` | |

### ⚠ The weekly-stats trap

`nfl.import_weekly_data()` **lags the play-by-play feed by a full season**, and
`_safe_load` in `loader.py` swallows the failure with a warning. This silently
produced the worst bug this project has had:

- `weekly_stats.parquet` stopped at 2024 while `pbp.parquet` had 2025.
- Every `player_*` rolling feature (usage, shares, TD history) went **100% null
  for 2025 and 2026**, having been populated 2015–2024.
- `prepare_data` converts null to `0.0`, so the model scored rows unlike anything
  in training. Week 1 2026 probabilities averaged **0.380 against a true base
  rate of ~0.08**, implying **7.6 TD scorers per game when reality is ~4.3**.
- The app reported +40 to +58pp "edges" over Vegas. All of them were artifacts.

**Mitigations now in place:**

1. `backfill_weekly_stats()` (`src/ingest/derive_weekly_stats.py`) reconstructs
   the missing seasons from play-by-play, and `ingest_all` **calls it every run**.
   It was previously written but orphaned — nothing invoked it.
2. `check_feature_skew()` (`src/prediction/predict.py`) compares predict-time
   null rates against the rates recorded at training and prints a loud warning
   when a block of features degrades.

Derived columns are close to but not identical to the official ones — EPA is
summed per play and first downs come from `first_down_rush`/`first_down_pass`.
Coverage differs slightly (derived EPA is non-null for more players than the
official field). Prefer the official feed when it catches up.

---

### ⚠ Sparse usage frames leak the current game

The red-zone, goal-line, opening-drive and first-half frames are built by
aggregating play-by-play, so **a row exists only for a player-week where that
usage occurred**. Left-joined onto candidates, the consequence is that
`player_i10_touches_szn_avg IS NOT NULL` means *"this player touched the ball
inside the 10 in the game being predicted."*

Measured on 2023–2025, nullness alone was worth:

| Feature | P(scored) non-null | P(scored) null | Lift |
|---|---|---|---|
| `player_i10_touches_szn_avg` | 0.513 | 0.033 | **15.5x** |
| `player_rz_touches_szn_avg` | 0.393 | 0.019 | **20.3x** |
| `player_carries_szn_avg` | 0.210 | 0.008 | **26.6x** |

Every rolling *value* was correctly lagged with `shift(1)`, which is why this
survived repeated leakage audits — it was the row's **existence** that leaked.

`src/features/spine.py` fixes it: all such frames are densified against a
player-week spine taken from the candidate pool (rosters + schedule, both known
before kickoff) with usage filled to 0, *before* any shift or rolling. Absence
then means "was available and didn't get a touch", which is what the model
should learn.

**When adding a usage feature, densify it.** If a frame is built by filtering
play-by-play and grouping by player-week, it is sparse by construction and will
leak unless it goes through `densify()`.

---

## 2. The Odds API — sportsbook TD props

| | |
|---|---|
| Provider | [The Odds API](https://the-odds-api.com/) |
| Access | **Paid**, requires `ODDS_API_KEY` in `.env`. Credit-metered |
| Loaded by | `src/ingest/odds_api.py` |
| Lands in | `data/raw/odds_cache/td_props_<date>.json`, consolidated to `player_td_odds.parquet` |
| Refresh | On demand from the app; local cache reused for 6 hours |
| Markets | `player_1st_td`, `player_anytime_td` |

**Prices are consensus, not single-book.** `fetch_week_td_props` takes the median
across every bookmaker quoting a player, which is more stable than whichever book
happened to respond first.

**Vig is removed before use.** A raw "Yes" price embeds the book's margin and
overstates every player. Where a book posts both sides we de-vig exactly
(`p_yes / (p_yes + p_no)`); where only "Yes" is posted we scale the game's prices
to the fitted expected scorer count. Both paths live in `blend.devig_market`.
The raw price is kept as `implied_prob` and the fair one as `fair_prob` — **never
compare model output to `implied_prob`, that comparison is biased by the vig.**

### Odds history (`data/archive/odds_history.parquet`)

The API only serves *current* markets; once kickoff passes those prices are gone
forever. `src/ingest/odds_history.py` snapshots every fetch, append-only, and
grades resolved weeks against play-by-play outcomes.

This archive is the **only** path to a defensible model-vs-market blend weight.
It no longer starts empty: 2023–2025 was backfilled from the paid historical
endpoint on 2026-08-10/11. Until it holds `blend.min_history_rows` graded
player-games, the blend falls back to the declared bootstrap and says so in the
prediction output (`blend_source` column).

| | rows |
|---|---|
| Total | 119,320 (2023: 46,778 · 2024: 37,099 · 2025: 35,277 · 2026: 166) |
| Distinct player-game-market keys | 69,039 |
| With both an `open` and a `close` | 50,281 |
| Where the price moved between them | 47,248 |

`make clean` never touches `data/archive/` — the endpoint sells these once and
re-downloading costs again. `make backup-odds` takes a timestamped copy; run it
before anything that writes here.

**Fetch odds every week even when you aren't betting.** A week not snapshotted is
a week that can never be used to calibrate. The capture is automated
(`make odds-schedule-on`) and guarded by `odds_capture.*` in
`config/settings.yaml` — see the note on `open_window_days` there for why the
opening snapshot needs an eight-day window rather than seven.

---

## 3. Anthropic API — wording, and the Ask box

| | |
|---|---|
| Provider | Anthropic |
| Access | `ANTHROPIC_API_KEY` in `.env` (notes) and `/etc/picksix/anthropic.key` on the web host (Ask box). Optional in both cases |
| Used by | `src/analysis/game_notes.py`, `deploy/ask.php` |

**No probability, edge or line on the board comes from a model call.** The two
uses are wording and answering, and both are fenced.

`game_notes.py` **selects** a note from the payload first — the numbers, the
direction and the pick are decided before any call — and asks only for the
phrasing. Two guards then check what came back:

- `_numbers_are_sourced` compares every figure in the wording **numerically**
  against the payload. A string comparison passed "6.5" beside a payload that
  said 6.50.
- `_direction_is_consistent` checks the wording backs the side the note picks.
  A note about a player priced above our number came back recommending him;
  the payload said avoid.

A note that fails either guard ships in its written phrasing instead.

`ask.php` answers typed questions on the published board against the brief in
`data/ask/<GAME>.json`, with web search available for what the brief cannot
know. Context is chosen by a validated game id on the server, never by the
request. See [DEPLOY.md](DEPLOY.md) for limits and key placement.

Caution: the older `src/prediction/ai_adjustments.py` can still move a
probability by up to `ai_context.max_adjustment` (±0.10) and reads a cache
keyed on `md5(season_week_gameid_targettype)` — which does **not** include the
probabilities, so commentary written against a broken model survives a re-run.
Nothing currently calls it. If you wire it back up, clear
`data/raw/ai_context_cache/` on every model or feature change.

---

## 3b. SBR consensus — public money and line movement

| | |
|---|---|
| Provider | Sportsbook Review, scraped |
| Access | None. Public pages, `DELAY_SECONDS = 2.0` between requests |
| Used by | `src/ingest/public_money.py` |
| Archives | `data/archive/public_money.parquet` (tickets), `data/archive/line_history.parquet` (open and now, per market) |

Two archives, because they answer different questions. Tickets say where the
count of bets is; line history says whether the price moved with them or
against them. Reverse line movement — the line moving **toward** the side
taking fewer tickets — needs both, and neither is recoverable after kickoff.

The consensus is the **median of each book's latest** capture, not a mean over
every row, so a book that posts twice as often does not weight the number.

Traps this feed has already produced:

- **A moneyline in the spread column.** `bet_rivers_co` posted
  `homeSpread: 0` at −334. Anything outside `MAX_LINE_ODDS` (±200) on a
  spread or total is dropped.
- **Captures too close together say nothing.** `MIN_GAP_MINUTES = 60`, and a
  week opens `WEEK_OPEN_DAYS = 7` before kickoff.

Caution: this is a scrape of a page that can change shape without warning. It
feeds context on the board, not a feature any model trains on.

---

## 4. Fitted artifacts (derived, not sourced)

Written by `make train` into `models/<target_type>/`, refit every run.

| Artifact | Fit by | What it holds |
|---|---|---|
| `scorer_rate_prior.json` | `src/models/market_prior.py` | `E[distinct scorers per game] ~ total_line + \|spread\|`, OLS on labelled training games. Carries `seasons_used`, `n_games`, `rmse`, `fit_date` |
| `blend_weight.json` | `src/prediction/blend.py` | Model-vs-market weight from logistic stacking on graded odds history. Absent until enough history exists |
| `train_null_rates.pkl` | `src/models/trainer.py` | Per-feature training null rates, for the skew guard |
| `<model>_calibrator.pkl` | `src/models/calibration.py` | Temperature scaling, fit on the validation season |

The scorer-rate prior tracks league scoring environment automatically: a
higher-scoring era shifts the fit without anyone editing a threshold.

### Clusterings (the Player types tab)

Written by `make clusters` (`scripts/21_clusters.py`), not by `make train`, and
included in `make evaluate`.

| Artifact | Fit by | What it holds |
|---|---|---|
| `models/<target>/clusters_player.json` | `src/clustering/archetypes.py` | Player archetypes: per-position feature set, transforms, fit-set impute medians, scaler, centroids, names, and the full curve that chose `k` |
| `models/<target>/clusters_bet[_<model>].json` | `src/clustering/bet_shapes.py` | The same, for kinds of bet rather than kinds of player |
| `output/<target>/clusters_*_report[_<model>].json` | `measure()` in each | What each group did **out of fit**: TD rate, our calibration against the book's, and returns with a game-clustered interval |

Three things about these are load-bearing and easy to undo by accident.

**They are fitted on the training seasons and scored on the seasons after.** A
segmentation draws its own boundaries; scored on the rows it was drawn from,
every group comes back looking like a discovery. `seasons_used` and
`report_seasons` are disjoint by construction and asserted in
`tests/test_leakage.py`. Reporting also stops at `seasons.end` — the predict
season's rows carry `target == 0` because nothing has happened yet, and left in
they drag every group's touchdown rate below the truth without looking wrong.

**`k` is chosen by the gap statistic, not silhouette, and that is a measured
choice.** Pooled over the league, silhouette peaks at `k=3` and those three
groups are running backs, receivers, and players with no usage — the position
column rediscovered and presented as a finding. So position became the
stratifier rather than the answer, each position is fitted in its own
standardised space, and selection moved to the gap statistic, which is the one
standard criterion tested here with an interior optimum. Silhouette is still
computed and still shown, as a diagnostic beside the gap curve. The evidence
sits in the `clustering:` block of `config/settings.yaml`; do not "fix" the
criterion back without re-deriving it.

**Bet shapes are fitted on one season.** Real odds history begins in 2023 and the
training split ends there, so that lens learns from a single season's board and
is measured on the two after it. Thin, stated on screen, and not something to
resolve by reaching across the split.

---

## Evaluation integrity

`config/settings.yaml` previously set `val_season` and `test_season` both to
2025. The model early-stopped on 2025, the temperature scaler was fit on 2025,
ensemble weights were optimised for top-1 on 2025 — and then accuracy was
*reported* on 2025. The app's "Historical Accuracy 75.4%" was not out-of-sample.

Now: train ≤2023, validate 2024, test 2025 — disjoint.

Also note what Top-1 means for `anytime_td` in `src/evaluation/metrics.py`: it
scores a hit if the single highest-ranked player is **any** of the ~4.3 players
who scored in that game. That is a much easier question than "does this specific
player score", which is what the props table sells. Do not read Top-1 as a
hit rate on individual bets.

---

## Reproducing from scratch

```bash
make ingest                 # nflverse -> data/raw, incl. weekly-stats backfill
python scripts/run_all.py   # targets -> candidates -> features -> train, both targets
make predict                # score the upcoming week
```

`run_all.py` starts at label extraction and assumes `data/raw/` is populated.
