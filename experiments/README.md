# Experiments

One YAML file per idea. The file *is* the experiment — an overlay merged over
`config/settings.yaml` for the length of a run, never written to it.

```yaml
id: 2026.08.13-depth4        # dated, slugged; becomes the ledger row and run directory
note: "xgb max_depth 6 -> 4" # one line, says what changed
overlay:
  model:
    xgb:
      max_depth: 4
```

```bash
make champion ID=2026.08.12-baseline-run     # once, before the first experiment
make screen EXP=experiments/depth4.yaml      # fast: production model, one market
make gate   EXP=experiments/depth4.yaml      # both markets, every model
make experiments                             # the ledger: what has been tried
```

A screen never promotes. A gate produces a verdict against the champion, paired
per game, and appends it to `models/registry/ledger.jsonl` whether it won or
lost — a rejected idea is worth recording, or it gets retried blind.

`PROMOTED` means: adopt the overlay into `config/settings.yaml`, `make train`,
then `make lock` and `make promote`. The harness never changes what is served.

**An overlay can only change what is read from config at train or score time** —
hyperparameters, `models.active`, the seed, splits, calibration settings,
filters. It cannot change the feature matrix, which is built by
`scripts/04_features.py` and read from disk. A feature experiment rebuilds that
first; the ledger records the feature-matrix hash, so a comparison across
different matrices is at least visible.

See [`docs/MODEL_ITERATION.md`](../docs/MODEL_ITERATION.md) for the promotion
gate and the phased plan.
