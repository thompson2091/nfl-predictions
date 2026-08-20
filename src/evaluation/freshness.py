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

Artifacts written *downstream* of training are excluded from the model's
timestamp — `blend_weight.json`, refit during prediction, and the two cluster
files, refit by `make clusters`. Counting them inverts the comparison: the first
run of this check reported every evaluation artifact as stale, including ones
regenerated seconds earlier, because the clustering script had touched the model
directory. A warning that fires on everything at once is a warning that gets
ignored.
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
    ("combo_backtest.json", "make combos TARGET={market}",
     "how combinations have actually done"),
    # Added 2026-08-19. These three were missing, and they are the ones that
    # actually broke: promoting the 24-family model left the backtest frames
    # and the served predictions describing the previous one, and the only
    # thing that noticed was `test_served_path_matches_the_evaluated_path`
    # finding that the served probability matched NO stage of the evaluated
    # path. The list above covers what the app *quotes*; these are what it
    # *ranks from*, which is a worse thing to have stale.
    ("backtest_2025.csv", "make evaluate",
     "every hit-rate band and the market head-to-head"),
    ("clv.json", "python scripts/13_clv.py --target {market}",
     "closing-line value"),
    # Added 2026-08-20 with `cover_selection.json`. `cover_backtest.json` had
    # been readable by both surfaces for a day without being tracked, which is
    # the same shape of gap as the three above: the page quotes it, so a
    # retrain that leaves it behind makes the page grade one model's rule with
    # another model's results.
    ("cover_backtest.json", "make cover-backtest TARGET={market}",
     "what the full-cover rule actually returned"),
    ("cover_selection.json", "make cover-selection TARGET={market}",
     "whether a different cover rule would have done better"),
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
DOWNSTREAM_ARTIFACTS = frozenset(RUNTIME_ARTIFACTS)


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


def export_blockers(markets=("anytime_td", "first_td")) -> list[str]:
    """Reasons a page must not be published right now, in plain sentences.

    An export is the one place a mislabelled number leaves this machine.
    Everything else is read in context, by someone who knows what was just run;
    a published page is read by whoever opens it, with no way to tell what it
    was built from. 2026-08-19 produced six separate instances of an artifact
    describing a model other than the one it claimed, so the export is gated
    rather than trusted.

    Two independent checks, because they catch different things: artifacts
    older than the model that produced them (`stale_artifacts`), and artifacts
    older than the promotion that changed what is served (`stale_derived`).
    A promote updates the model directory too, so they overlap — but only the
    second knows about the served *version*, and only the first is per-market.
    """
    from src.models.versioning import stale_derived

    out = []
    for market in markets:
        for row in stale_artifacts(market):
            out.append(
                f"{market}: {row['artifact']} predates the model it describes "
                f"({row.get('describes', 'the page')}) — run "
                f"`{row['command'].format(market=market)}`")
    for row in stale_derived(tuple(markets)):
        out.append(
            f"{row['market']}: {row['artifact']} predates the promotion of "
            f"{row['version']} — run `{row['fix']}`")
    return out
