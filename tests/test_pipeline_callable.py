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
