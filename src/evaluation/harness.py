"""Run a recipe over the walk-forward folds and return per-game results.

An **experiment** is a config overlay. The harness merges it over
`settings.yaml`, retrains from scratch once per fold, scores each fold's
held-out season through the same path production serves, and returns one row
per game — never a percentage. Percentages are derived; the paired comparison
in `src/evaluation/compare.py` needs the rows.

Folds are the ones `scripts/11_walkforward.py` has always used:

    train <= T-2   ·   early-stop on T-1   ·   score T,   T in first..last

so nothing scores a season it trained or early-stopped on.

**Two tiers**, though the gap turned out to be smaller than expected: a fold
costs about 13 seconds per model on this data, so a full gate — two markets,
four folds, three models plus the ensemble — runs in a few minutes. Screen
while iterating; gate before promoting. There is no budget reason to skip the
gate.

    screen   one market, the production model, four folds
    gate     both markets, every model, four folds

**What an overlay can and cannot change.** Anything read from config at train
or score time: hyperparameters, `models.active`, calibration settings, the
seed, splits, filters. It cannot change the feature matrix, which is built by
`scripts/04_features.py` and read from disk — a feature experiment has to
rebuild that first, and the harness records the feature-set hash so a
comparison across different matrices is at least visible.

Nothing here writes to `models/`, `config/settings.yaml`, or anything the app
reads. Each fold trains into a scratch directory that is deleted afterwards.
"""
from __future__ import annotations

import hashlib
import json
import pickle
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from src.evaluation.ranking import game_universe, per_game_outcomes, row_metrics
from src.models.trainer import _filter_low_activity
from src.utils.config import config_overlay, get_config, production_model
from src.utils.paths import get_path

MARKETS = ("first_td", "anytime_td")


def fold_splits(first_test: int, last_test: int,
                played: list[int] | None = None) -> list[dict]:
    """The train/validate/score windows, one per test season."""
    out = []
    for test in range(first_test, last_test + 1):
        if played is not None and test not in played:
            continue
        out.append({"train_end": test - 2, "val_season": test - 1,
                    "test_season": test})
    return out


def played_seasons(target_type: str) -> list[int]:
    feats = _features(target_type)
    return sorted(feats.filter(pl.col("target").is_not_null())["season"]
                  .unique().to_list())


_FEATURE_CACHE: dict[str, pl.DataFrame] = {}


def _features(target_type: str) -> pl.DataFrame:
    """The feature matrix, read once per process.

    Read repeatedly it dominates a 13-second fold; the frame is ~59 MB per
    market and both fit comfortably alongside training.
    """
    if target_type not in _FEATURE_CACHE:
        path = get_path("processed", target_type) / "features.parquet"
        if not path.exists():
            raise FileNotFoundError(
                f"No features.parquet for {target_type} — run `make features`.")
        _FEATURE_CACHE[target_type] = pl.read_parquet(path)
    return _FEATURE_CACHE[target_type]


def feature_matrix_hash(target_type: str) -> str:
    """Identifies the matrix a result was measured on.

    Two experiments run against different feature matrices are not comparable,
    however similar their configs look. Recording this makes that visible
    rather than leaving it to be remembered.
    """
    df = _features(target_type)
    payload = f"{df.height}|{'|'.join(sorted(df.columns))}".encode()
    return hashlib.sha256(payload).hexdigest()[:16]


#: Player-level columns kept when `keep_rows` is on. Enough to decompose an
#: error — whose team, which position, what the game looked like — without
#: carrying 319 feature columns into every saved run.
ROW_COLS = ("game_id", "season", "week", "player_id", "player_name", "team",
            "is_home", "spread_line", "total_line", "implied_team_total",
            "position_QB", "position_WR", "position_TE", "position_FB",
            "position_DEFST")


def _apply_anytime_prior(scored: pl.DataFrame, target_type: str,
                         model_dir: Path, companion_dir: Path | None,
                         model_name: str, active_models: list[str],
                         val_season: int | None) -> pl.DataFrame:
    """Blend first-TD scores with the anytime model, at a weight fitted on val.

    The weight is fitted on the fold's validation season and applied to the
    held-out one, so the number this returns was never chosen by looking at the
    season it is scored on. Fitting on the test season instead would reproduce
    the measured curve's peak and mean nothing.
    """
    from src.prediction import cross_market as X

    if target_type != "first_td" or companion_dir is None or val_season is None:
        return scored
    if not get_config().get("first_td", {}).get("use_anytime_prior"):
        return scored

    val = _filter_low_activity(_features(target_type).filter(
        (pl.col("season") == val_season) & pl.col("target").is_not_null()))
    if val.height == 0:
        return scored

    from src.models.scoring import score as _score
    from src.models.trainer import prepare_data

    feature_cols = pickle.loads((Path(model_dir) / "feature_cols.pkl").read_bytes())
    Xv, _ = prepare_data(val, feature_cols)
    val = val.select(["game_id", "player_id", "target"]).with_columns([
        pl.Series("prob", _score(model_name, Xv, feature_cols, model_dir,
                                 active_models=active_models)),
        pl.Series("any_prob", X.anytime_probs(val, companion_dir, model_name,
                                              active_models)),
    ])
    fitted = X.fit_weight(val)

    return scored.with_columns(
        pl.Series("prob", X.blend(
            scored["prob"].to_numpy(),
            X.anytime_probs(scored, companion_dir, model_name, active_models),
            fitted["weight"]))
    )


def score_fold(target_type: str, model_dir: Path, test_season: int,
               model_name: str, active_models: list[str],
               keep_rows: bool = False, companion_dir: Path | None = None,
               val_season: int | None = None) -> tuple[pl.DataFrame, dict, pl.DataFrame | None]:
    """Score one fold's held-out season through the path production serves.

    The universe is built from the **unfiltered** labelled frame, so the
    denominator does not move when the candidate filter does. See
    `src/evaluation/ranking`.
    """
    from src.models.joint import apply_joint, load_conversion, load_team_rate
    from src.models.registry import ensure_registered
    from src.models.scoring import score
    from src.models.trainer import _filter_low_activity, prepare_data

    ensure_registered()
    feature_cols = pickle.loads((Path(model_dir) / "feature_cols.pkl").read_bytes())

    labelled = _features(target_type).filter(
        (pl.col("season") == test_season) & pl.col("target").is_not_null())
    if labelled.height == 0:
        raise ValueError(f"No played games in {test_season} for {target_type}")
    universe = game_universe(labelled)

    scored = _filter_low_activity(labelled)
    X, _ = prepare_data(scored, feature_cols)
    probs = score(model_name, X, feature_cols, model_dir,
                  active_models=active_models)
    scored = scored.with_columns(pl.Series("prob", probs))
    scored = _apply_anytime_prior(scored, target_type, model_dir, companion_dir,
                                  model_name, active_models, val_season)

    team_model = load_team_rate(Path(model_dir) / "team_td_rate.json")
    if target_type != "first_td" and team_model is not None:
        # This fold's own conversion, not production's — otherwise the harness
        # scores a pipeline nobody runs.
        scored = apply_joint(
            scored, scored, team_model, score_col="prob", out_col="prob",
            conversion=load_conversion(Path(model_dir) / "td_conversion.json"))

    outcomes = per_game_outcomes(scored, universe).with_columns([
        pl.lit(test_season).alias("test_season"),
        pl.lit(model_name).alias("model"),
        pl.lit(target_type).alias("target_type"),
    ])
    rows = row_metrics(scored)
    rows.update({"test_season": test_season, "model": model_name,
                 "target_type": target_type,
                 "label_gap_games": int(universe.height
                                        - scored.filter(pl.col("target") == 1)
                                        ["game_id"].n_unique())})

    player_rows = None
    if keep_rows:
        keep = [c for c in ROW_COLS if c in scored.columns]
        player_rows = scored.select([*keep, "prob", "target"]).with_columns([
            pl.col("prob").rank(descending=True, method="ordinal")
            .over("game_id").alias("rank"),
            pl.lit(model_name).alias("model"),
            pl.lit(target_type).alias("target_type"),
            pl.lit(test_season).alias("test_season"),
        ])
    return outcomes, rows, player_rows


def run(overlay: dict | None = None, *, markets=MARKETS,
        first_test: int | None = None, last_test: int | None = None,
        models: list[str] | None = None, seed: int | None = None,
        keep_rows: bool = False, progress=print) -> dict:
    """Train and score every (market, fold, model) and return the per-game rows.

    `models` restricts what is *trained*; the ensemble is scored additionally
    whenever more than one model is active, because that is what
    `models.production_by_target` may select.
    """
    from src.models.trainer import train_all

    cfg = get_config()
    first_test = first_test if first_test is not None else cfg["splits"]["test_season"] - 3
    last_test = last_test if last_test is not None else cfg["splits"]["test_season"]

    base_overlay = dict(overlay or {})
    if models is not None:
        base_overlay = {**base_overlay,
                        "models": {**base_overlay.get("models", {}),
                                   "active": list(models)}}
    if seed is not None:
        base_overlay = {**base_overlay,
                        "model": {**base_overlay.get("model", {}), "seed": seed}}

    started = datetime.now(timezone.utc)
    all_outcomes, all_rows, all_players = [], [], []
    folds_run: list[int] = []

    with config_overlay(base_overlay) as effective:
        # Inside the overlay: an experiment is allowed to move the splits, and
        # folds derived from the un-overlaid config would silently score a
        # different window than the one under test.
        active = list(effective["models"]["active"])
        to_score = active + (["ensemble"] if len(active) > 1 else [])

        # Fold outer, market inner, so both markets of one fold are trained
        # into the same scratch directory. First TD can then be scored with the
        # anytime model *from its own fold* — a companion trained on any other
        # window would be scoring the held-out season with knowledge of it.
        needs = list(markets)
        if (effective.get("first_td", {}).get("use_anytime_prior")
                and "first_td" in needs and "anytime_td" not in needs):
            needs.append("anytime_td")

        folds = fold_splits(first_test, last_test, played_seasons(needs[0]))
        if not folds:
            raise ValueError(f"No played seasons in {first_test}..{last_test}")
        folds_run = [f["test_season"] for f in folds]

        for fold in folds:
            scratch = Path(tempfile.mkdtemp(prefix="harness_"))
            try:
                trained: dict[str, Path] = {}
                for market in needs:
                    progress(f"  {market} fold: train <={fold['train_end']} "
                             f"val {fold['val_season']} score "
                             f"{fold['test_season']} ({', '.join(active)})")
                    train_all(market, splits=fold,
                              model_dir=scratch / market / "models",
                              output_dir=scratch / market / "output")
                    trained[market] = scratch / market / "models"

                for market in markets:
                    companion = (trained.get("anytime_td")
                                 if market == "first_td" else None)
                    for name in to_score:
                        outcomes, rows, players = score_fold(
                            market, trained[market], fold["test_season"],
                            name, active, keep_rows=keep_rows,
                            companion_dir=companion,
                            val_season=fold["val_season"])
                        all_outcomes.append(outcomes)
                        all_rows.append(rows)
                        if players is not None:
                            all_players.append(players)
            finally:
                shutil.rmtree(scratch, ignore_errors=True)

    return {
        "outcomes": pl.concat(all_outcomes, how="diagonal_relaxed"),
        "players": (pl.concat(all_players, how="diagonal_relaxed")
                    if all_players else None),
        "row_metrics": all_rows,
        "meta": {
            "started": started.isoformat(timespec="seconds"),
            "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "markets": list(markets),
            "folds": folds_run,
            "seed": seed if seed is not None else get_config()["model"]["seed"],
            "feature_hash": {m: feature_matrix_hash(m) for m in markets},
            "overlay": base_overlay,
        },
    }


def summarise(result: dict) -> dict:
    """Pooled Top-K per market and model, plus the row metrics beside them."""
    from src.evaluation.ranking import pooled

    outcomes, out = result["outcomes"], {}
    for market in sorted(outcomes["target_type"].unique().to_list()):
        per_model = {}
        for model in sorted(
                outcomes.filter(pl.col("target_type") == market)["model"]
                .unique().to_list()):
            sub = outcomes.filter((pl.col("target_type") == market)
                                  & (pl.col("model") == model))
            stats = pooled(sub)
            rows = [r for r in result["row_metrics"]
                    if r["target_type"] == market and r["model"] == model]
            total = sum(r["rows"] for r in rows) or 1
            for key in ("auc", "brier"):
                stats[key] = sum(r[key] * r["rows"] for r in rows) / total
            stats["rows"] = total
            per_model[model] = stats
        out[market] = per_model
    return out


def save(result: dict, experiment_id: str) -> Path:
    """Per-game rows to disk, so a later comparison never has to re-run this."""
    directory = get_path("output") / "experiments" / experiment_id
    directory.mkdir(parents=True, exist_ok=True)
    result["outcomes"].write_parquet(directory / "outcomes.parquet")
    if result.get("players") is not None:
        result["players"].write_parquet(directory / "players.parquet")
    (directory / "meta.json").write_text(json.dumps(
        {**result["meta"], "row_metrics": result["row_metrics"],
         "summary": summarise(result)}, indent=2) + "\n")
    return directory


def load(experiment_id: str) -> dict:
    """A saved run, in the shape `run` returned it."""
    directory = get_path("output") / "experiments" / experiment_id
    path = directory / "outcomes.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"No saved outcomes for '{experiment_id}' at {path}")
    meta = json.loads((directory / "meta.json").read_text())
    players = directory / "players.parquet"
    return {"outcomes": pl.read_parquet(path),
            "players": pl.read_parquet(players) if players.exists() else None,
            "row_metrics": meta.get("row_metrics", []),
            "meta": meta}


def screen_models(market: str) -> list[str]:
    """What a screen trains: the one model this market actually serves.

    The ensemble cannot be screened alone — it is an average of the others, so
    screening it means training them all, which is the gate.
    """
    name = production_model(market)
    return list(get_config()["models"]["active"]) if name == "ensemble" else [name]
