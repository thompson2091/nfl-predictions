# Improving the Record page

This guide explains how the Record page measures the model, how to read it
each week, and how a model change earns its way onto the site. Follow it to
improve the numbers without the page grading its own fit.

For how a change is built and gated, see
[Model iteration plan](MODEL_ITERATION.md). This guide covers what happens
around that work: the scoreboard, the weekly read, and the promotion
schedule.

## The scoreboard

The Record page shows two kinds of player numbers. Only one of them measures
progress.

| Section | What it is | Use it for |
| --- | --- | --- |
| **Recorded before kickoff** | Each pick as it stood on the site before its game started, at the price on offer then. Never regraded. | Judging whether the model is getting better. |
| **Rebuilt with today's model** | Every past week regraded with the model being served today. | Exploring which slices look promising. |

The rebuilt numbers improve whenever the model is refit, so they can't show
progress. Weeks 2–4 of 2026 show the gap: the forward record for our model's
side is −$4.66 per $100 over 1,487 bets, against −$1.84 for the rebuilt
weeks 3–4.

The two are never added together. The page keeps them in separate blocks.

### Where the forward record comes from

The forward record reads the frozen player boards in
`archive/predictions/<season>.json`:

- **Week 5 onward:** recorded live. `scripts/66_freeze.py` runs after every
  odds capture and at the end of the weekly rollover, and keeps each game's
  board until that game kicks off.
- **Weeks 1–4 of 2026:** recovered from the pages deployed before each
  kickoff. `scripts/68_recover_boards.py` reads the copies of each deploy
  that the server keeps in `/var/www/html/bets/` and takes the last build
  made before each game. Each recovered board names the build it came from
  in its `source` field.

Week 1 has touchdown boards only. The site carried no over/under boards
until week 2.

Game picks start at week 3. The game model was first built after week 2's
games, so weeks 1 and 2 have no game record and never will: a projection
made now would be today's model answering for weeks it never saw. The week
picker still offers them, labeled "players only", and a range that reaches
past week 3 says which weeks each section covers.

Note: Recovery times each build by the `built` stamp inside its payload, not
by the server's file time. The server's clock runs about 40 minutes behind,
and three builds that looked pre-kickoff by file time were built after their
games started.

### Closing-line value

Win/loss needs thousands of bets to say anything. Closing-line value (CLV)
says it in a few hundred: it measures whether the market moved toward a pick
after the price was taken.

- CLV is computed from `data/tracked_picks.csv`, which logs each pick when
  it is first seen, with its fair price and `recorded_at`. A frozen board
  can't be used: its price is the close, so its CLV is zero by construction.
- The market's own open-to-close drift is subtracted. On every over/under
  market the de-vigged over probability rises from open to close regardless
  of any opinion, which would otherwise credit every over and charge every
  under. `src/evaluation/ou_shortlist.drift` measures it per market.
- A positive value means the close moved toward the pick.

### Model versions

Every frozen board carries a `version` field:

- The touchdown markets use the locked version name from
  `models/registry/CURRENT.json`.
- The over/under markets use `files:` plus a hash of the files in
  `models/<market>/`, which changes whenever what is served changes.

The forward record splits by version, so a promoted model is judged on its
own bets. Recovered boards predate the stamp and form their own population.

## The rules being tracked

The forward record grades four rules on the over/under markets. Each is
defined in `src/evaluation/tracked_rules.py`, with where it came from and
the first week that can test it.

| Rule | What it bets | Counts from | Where the rule came from |
| --- | --- | --- | --- |
| Our model | The unblended model's side on every priced line | Week 2 | The baseline |
| Gaps | Where the blended number beats the book's fair price by a fitted margin | Week 2 | Margins fitted on 2024–25 |
| Our model, 75%+ sure | Our model's side where it is at least 75% sure | Week 2 | Top band of a 2024–25 measurement |
| Our model's unders, catches and rushing | Our model's unders on those two markets | Week 6 | Read off weeks 2–4 of 2026 |

A rule found on the weeks that grade it would be grading its own fit. So the
unders rule counts only from week 6, the first week after it was found.

Important: Changing a rule's cut or threshold creates a new rule. Give it a
new name and leave the old one in place, so the old rule's record stays
readable on its own. `test_a_tracked_rule_cannot_be_retuned_without_being_renamed`
enforces this.

## The weekly loop

Every Tuesday, the rollover prints the forward record at the end of its run.
To read it at any other time, run:

```
python scripts/67_forward_report.py
```

The report lists each rule's bets, hit rate, the rate needed to profit, the
return per $100 with its 95% range, and the CLV. Each market is marked
`candidate` or `not yet`.

1. Read the forward record per rule and per market.
2. Treat a market as a candidate for emphasis only once its 95% range clears
   break-even.
3. Read CLV first. It moves weeks before the win/loss record does.
4. Change nothing on the strength of this read. It informs which ideas to
   investigate, not what to ship.

## How a change reaches the site

Model changes ship at fixed promotion points, about every four weeks: next
around week 9, then week 13. A real bug fix can ship at any time, as its own
version.

1. Develop the change against the 2024–25 backtests only.
2. Run it through the gates and version lock described in
   [Model iteration plan](MODEL_ITERATION.md).
3. Promote it at the next promotion point, never mid-week.
4. Judge it on the forward record for its own version, starting with CLV.

Thresholds, bands, and margins are refit once a season, after the last
game, on every completed season including this one. That refit is the only
time the current season's results feed back into the model.

Caution: Never tune a model, threshold, or rule on the current season's
forward record. Every tuning absorbs the failure it was meant to detect, and
the record stops being able to say whether the model is any good.

## Open investigations

Each entry is a diagnosis, not a change. It becomes a change only through
the steps in [How a change reaches the site](#how-a-change-reaches-the-site).

### Receiving yards is overconfident (measured 2026-10-09)

On the forward record, receiving yards is the one market where both sides
lose: −$11.61 per $100 on overs and −$9.08 on unders, weeks 2–4. That points
at the model's probabilities, not at which side it takes.

The 2024–25 backtests (`output/<market>/backtest_<season>.csv`, one line per
player-game, nearest the player's median line) show why:

| Market | Model log loss | Book log loss | Calibration slope, fit on 2024 | Calibrated log loss, 2025 |
| --- | --- | --- | --- | --- |
| Receiving yards | 0.7133 | 0.6932 | 0.18 | 0.6914 (book 0.6933) |
| Rushing yards | 0.7235 | 0.6864 | 0.19 | 0.6914 (book 0.6940) |
| Catches | 0.7005 | 0.6807 | 0.38 | 0.6838 (book 0.6817) |

- The raw probabilities are far too extreme. On receiving yards, a model
  26% over lands 44% of the time, and a model 74% lands 58%.
- A slope of 0.18 means the model's log-odds are about five times too
  confident. Shrunk by a calibration fitted on 2024 alone, the 2025 log loss
  on both yardage markets edges past the book's de-vigged price.
- Low lines (15.5 yards or less) carry most of the over bias: the model
  rates those overs 4.3 points above the book, and they land at the book's
  rate. This matches the earlier finding that thin player history is not
  shrunk.
- Calibrating does not turn the whole book profitable at −110-type prices;
  it changes which picks are worth taking.

**Candidate change for the week-9 promotion:** a per-market calibration
layer on the over/under models, fitted walk-forward on past seasons, with
the Gaps margins and the confidence band re-derived on the calibrated
probabilities. Judge it on 2025 held out, then on its own version of the
forward record, CLV first.

Caution: These backtests leave out a player who played and recorded
nothing, which flatters overs by up to about 5 points. Fix that before
reading any per-$100 figure from them as final.

### Unders beat overs

On weeks 2–4, the model's unders beat its overs on catches and rushing
yards, and the backtests show the same on every market: overs lost 4–6
points per $100 more than unders in 2024–25. The open-to-close drift of the
over price predicts this. It is tracked forward as the "model under" rule
from week 6.

## What is kept, and where

| Artifact | Location | In git |
| --- | --- | --- |
| Frozen player boards, all six markets | `archive/predictions/<season>.json` | Yes |
| Frozen game projections | `archive/projections/<season>.json` | Yes |
| Frozen game stories | `archive/stories/<season>.json` | Yes |
| Run manifest: commit, version, weight hashes, odds capture | `archive/runs/<season>.jsonl` | Yes |
| Picks logged when first seen | `data/tracked_picks.csv` | No; backed up nightly |
| Previous copies of refit weight files | `models/<market>/history/` | Yes |
| Odds, game-line, and public-money archives | `data/archive/*.parquet` | No; backed up nightly |
| Each deployed page | `deploy/history/` locally, `/var/www/html/bets/` on the server | No |

The nightly backup runs `make backup-odds` at 03:15, skips any file that
hasn't changed, and keeps the last 14 copies of each. The copies live on the
same disk, so they protect against a bad write, not a lost laptop.

## Commands

| Task | Command |
| --- | --- |
| Freeze this week's boards now | `make freeze` |
| Log this week's prop picks now | `make prop-picks WEEK=<n>` |
| Print the forward record | `python scripts/67_forward_report.py` |
| Recover boards from saved deploys | `python scripts/68_recover_boards.py <dir of builds>` |
| Back up the archives now | `make backup-odds` |
| Turn the nightly backup on or off | `make backup-on`, `make backup-off` |
