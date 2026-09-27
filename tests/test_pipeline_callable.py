"""Every pipeline entry point can actually be called the way its caller calls it.

On 2026-09-24 `build_situational_features` was rewritten for the game model —
one argument, one frame — under a name `assembler.py` was already importing
and calling with four arguments for two frames. Nothing complained. The only
thing that runs the assembler is `04_features.py`; that week's rollover found
the board already built and exited before reaching it; and the break sat for
three days until a Sunday job happened to run the chain.

A `TypeError` on a call that no test makes is invisible until the night the
pipeline needs it. These bind the arguments without running the work, which is
cheap enough to sit in the normal suite.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _calls_of(module_path: Path, func: str) -> list[ast.Call]:
    tree = ast.parse(module_path.read_text())
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", None) == func]


def test_the_assembler_calls_situational_features_the_way_it_is_defined():
    """The exact break, pinned by name rather than by symptom."""
    from src.features import situational_features as sf

    calls = _calls_of(REPO / "src" / "features" / "assembler.py",
                      "build_roster_situational_features")
    assert calls, "the assembler no longer calls it; update this test"
    sig = inspect.signature(sf.build_roster_situational_features)
    for c in calls:
        # Binding raises TypeError on an arity mismatch without doing any work.
        sig.bind(*[None] * len(c.args),
                 **{k.arg: None for k in c.keywords})


def test_the_game_model_calls_situational_features_the_way_it_is_defined():
    from src.features import situational_features as sf

    calls = _calls_of(REPO / "src" / "models" / "game_model.py",
                      "build_situational_features")
    assert calls, "the game model no longer calls it; update this test"
    sig = inspect.signature(sf.build_situational_features)
    for c in calls:
        sig.bind(*[None] * len(c.args),
                 **{k.arg: None for k in c.keywords})


def test_the_two_situational_builders_are_not_the_same_function():
    """They answer different questions and sharing one name was the fault.

    One is per team-game from the schedule; the other is per player-week from
    the rosters. A future edit that collapses them back into one name puts the
    original break straight back.
    """
    from src.features import situational_features as sf

    assert sf.build_situational_features is not \
        sf.build_roster_situational_features
    a = inspect.signature(sf.build_situational_features).parameters
    b = inspect.signature(sf.build_roster_situational_features).parameters
    assert len(a) != len(b), (
        "the two builders now take the same arguments, which is how one "
        "silently stood in for the other")


@pytest.mark.parametrize("script", ["01_ingest", "02_targets", "03_candidates",
                                    "04_features"])
def test_every_step_the_sunday_wrap_runs_imports(script):
    """The wrap runs these four unattended and deploys after them.

    An import-time error in any of them is a silent Sunday: the job fails, the
    site keeps last week's board, and nothing says so until someone looks.
    """
    import importlib.util

    p = REPO / "scripts" / f"{script}.py"
    assert p.exists(), f"{script}.py is gone but the wrap still runs it"
    # Parse rather than exec: these scripts do the work at module level.
    ast.parse(p.read_text())


# ── The freshness gate has to be visible to the things that run it ─────────


def test_a_refusal_does_not_look_like_success():
    """Exit 0 on a refusal is a gate nobody downstream can see.

    On 2026-09-27 the v1 site had been declining to publish for five days
    while every job that ran it reported a clean run — and the deploy that now
    follows would have shipped past it.
    """
    from src.evaluation.freshness import EXPORT_REFUSED

    assert EXPORT_REFUSED not in (0, 1), (
        "0 reads as success and 1 reads as a crash; a refusal is neither")
    for name in ("34_export_dashboard.py", "47_export_site.py",
                 "20_export_html.py", "52_export_v3.py"):
        src = (REPO / "scripts" / name).read_text()
        assert "EXPORT_REFUSED" in src, (
            f"{name} can refuse but not say so in its exit code")


def test_every_export_that_publishes_passes_the_gate():
    """INCLUDING THE ONE THAT REACHES THE PUBLIC.

    `52_export_v3.py` calls `47_export_site.build` directly, and the refusal
    lives in `main` rather than in `build` — so for as long as it existed, the
    only export anyone outside this machine reads was the one export not
    checked. It carried a model promoted on the 25th beside closing-line
    figures measured on the 22nd.
    """
    src = (REPO / "scripts" / "52_export_v3.py").read_text()
    assert "_gate(" in src, (
        "the v3 export publishes to the live site without a freshness check")
    tree = ast.parse(src)
    gate_line = next(
        (n.lineno for n in ast.walk(tree)
         if isinstance(n, ast.Call)
         and getattr(n.func, "attr", None) == "_gate"), None)
    build_line = next(
        (n.lineno for n in ast.walk(tree)
         if isinstance(n, ast.Call)
         and getattr(n.func, "attr", None) == "build"), None)
    assert gate_line and build_line and gate_line < build_line, (
        "the gate has to run before the payload is built, not after")


@pytest.mark.parametrize("job", ["sunday_wrap.sh", "week_rollover.sh"])
def test_the_scheduled_jobs_stop_on_a_refusal_rather_than_deploying(job):
    """Both of these deploy at the end, so 'kept going' means 'published'."""
    src = (REPO / "scripts" / job).read_text()
    assert "export_or_stop" in src, (
        f"{job} runs an export without distinguishing a refusal from a pass")
    # And the deploy must come after, so a refusal can prevent it.
    assert src.index("export_or_stop") < src.index("58_deploy.py"), (
        f"{job} deploys before the export it is meant to gate on")


# ── A published probability has to be one the calibration could support ───


def test_no_calibrator_can_publish_a_certainty():
    """0% and 100% are isotonic artifacts, not findings.

    Isotonic sets its top bin to 1.0 whenever every calibration sample in it
    happened to be a positive — on a thin tail that is a handful of games. On
    2026-09-27 the anytime-TD curve stepped from 0.722 straight to 1.000, and
    a player a thousandth over that line was published at 100% to score a
    touchdown, with a +36pp edge and a "Good value" tag computed from it.
    """
    import pickle

    import numpy as np

    from src.models.calibration import IsotonicCalibrator
    from src.utils.paths import get_path

    seen = False
    for market in ("anytime_td", "first_td"):
        for name in ("xgb_calibrator.pkl", "lgbm_calibrator.pkl",
                     "lr_calibrator.pkl"):
            p = get_path("models", market) / name
            if not p.exists():
                continue
            with open(p, "rb") as f:
                if pickle.load(f).get("iso") is None:
                    continue
            c = IsotonicCalibrator.load(p)
            seen = True
            grid = np.linspace(0.0, 1.0, 501)
            out = c.calibrate(grid)
            assert out.max() < 1.0, (
                f"{market}/{name} publishes a certainty: "
                f"max={out.max():.9f}")
            assert out.min() > 0.0, (
                f"{market}/{name} publishes an impossibility: "
                f"min={out.min():.9f}")
            # And the bound has to come from the fit, not from a constant: a
            # curve that resolved to 0.72 must not be reporting 0.999999.
            lo, hi = c._resolved()
            assert out.max() <= hi + 1e-12 and out.min() >= lo - 1e-12, (
                f"{market}/{name} publishes past what its knots resolved")
    if not seen:
        pytest.skip("no isotonic calibrator on disk")
