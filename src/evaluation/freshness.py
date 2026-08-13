"""Do the numbers on screen describe the model that is being served?

Nothing on the board is computed live. The accuracy strip reads
`output/<market>/walkforward.json`, the head-to-head reads the backtest frames,
and both are produced by commands you have to remember to run. A retrain that
lands without them leaves the page quoting the previous model's accuracy beside
the current model's picks, with nothing saying so.

The Makefile has warned about this in a comment since the evaluation targets
were written — "Re-run them after any retrain: the app reads their output, so
leaving them stale makes the board and the evidence behind it disagree." A
comment is not a guard. This is the guard.

The check is deliberately crude: modification time. It cannot tell you that an
artifact is *wrong*, only that it was written before the model it claims to
describe, which is enough to know it cannot be trusted. Anything subtler would
need to re-run the evaluation, which is the thing being avoided.

`blend_weight.json` is excluded from the model's timestamp. It is refit during
prediction rather than training, so every `make predict` would otherwise make
every evaluation artifact look stale.
"""
from __future__ import annotations

from pathlib import Path

from src.models.versioning import RUNTIME_ARTIFACTS
from src.utils.paths import get_path

#: What the app reads, and the command that regenerates each. Ordered by how
#: visible the number is: the accuracy strip leads the board.
EVALUATION_ARTIFACTS = [
    ("walkforward.json", "make walkforward TARGET={market}",
     "the Top-1/3/5 accuracy strip"),
    ("rank_economics.json", "make economics TARGET={market}",
     "the betting rule and rank economics"),
    ("longshot_skill.json", "make longshot TARGET={market}",
     "the longshot highlight"),
    ("clusters_player_report.json", "make clusters TARGET={market}",
     "the Player types tab"),
]


#: Files that live in `models/` but are written *after* training, by something
#: downstream of it. They must not count toward the model's timestamp or they
#: invert the comparison: running `make clusters` rewrites `clusters_player.json`
#: in the model directory, which made every evaluation artifact — including ones
#: regenerated seconds earlier — report as stale. The first run of this check
#: did exactly that.
#:
#: `blend_weight.json` is here for the same reason from the other direction: it
#: is refit during prediction, so every `make predict` would age the evaluation.
DOWNSTREAM_ARTIFACTS = set(RUNTIME_ARTIFACTS) | {
    "clusters_player.json", "clusters_bet.json",
}


def model_mtime(market: str, model_dir: Path | None = None) -> float | None:
    """When this market's *fitted* artifacts were last written.

    Only what `train_all` produces counts. Anything written downstream of
    training is excluded — see `DOWNSTREAM_ARTIFACTS` — so neither a prediction
    run nor a clustering run makes the evaluation look out of date.
    """
    directory = Path(model_dir) if model_dir else get_path("models", market)
    if not directory.exists():
        return None
    times = [p.stat().st_mtime for p in directory.iterdir()
             if p.is_file() and p.name not in DOWNSTREAM_ARTIFACTS]
    return max(times) if times else None


def stale_artifacts(market: str, model_dir: Path | None = None) -> list[dict]:
    """Evaluation artifacts written before the model they describe.

    Returns one entry per stale artifact with the command that refreshes it,
    so the report is actionable rather than merely alarming. A missing artifact
    is not reported here: the app already handles absence by falling back or
    hiding the panel, and conflating "never built" with "out of date" would
    make a fresh checkout look broken.
    """
    trained = model_mtime(market, model_dir)
    if trained is None:
        return []

    out_dir = get_path("output", market)
    stale = []
    for name, command, describes in EVALUATION_ARTIFACTS:
        path = out_dir / name
        if not path.exists():
            continue
        age = path.stat().st_mtime
        if age < trained:
            stale.append({
                "artifact": name,
                "describes": describes,
                "command": command.format(market=market),
                "written": age,
                "model_written": trained,
                "behind_seconds": trained - age,
            })

    # Backtest frames drive the head-to-head and the money numbers. They are
    # per-season files, so the oldest one governs: a 2025 frame refreshed after
    # a retrain says nothing about a 2023 frame that was not.
    frames = sorted(out_dir.glob("backtest_*.csv"))
    behind = [p for p in frames if p.stat().st_mtime < trained]
    if behind:
        stale.append({
            "artifact": f"{len(behind)} of {len(frames)} backtest frames",
            "describes": "the model-vs-bookmaker comparison and Betting reality",
            "command": f"make evaluate  # or backtest per season, TARGET={market}",
            "written": min(p.stat().st_mtime for p in behind),
            "model_written": trained,
            "behind_seconds": trained - min(p.stat().st_mtime for p in behind),
        })
    return stale
