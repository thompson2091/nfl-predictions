"""Sunday night is a part-played week, and three things broke on it (2026-10-26).

The Monday game has no result yet, a night can judge games and find no legs,
and a publish that crashes after ingesting the finals must be retried by the
next run rather than forgotten.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_a_week_with_monday_unplayed_grades_the_games_that_were(tmp_path, monkeypatch):
    from src.evaluation import weekly_review as wr

    feats = pl.DataFrame({
        "season": [2026] * 4, "week": [7] * 4,
        "game_id": ["SUN", "SUN", "MON", "MON"],
        "player_id": ["a", "b", "c", "d"], "player_name": ["A", "B", "C", "D"],
        "team": ["X"] * 4, "target": [1, 0, None, None],
    })
    (tmp_path / "anytime_td").mkdir()
    feats.write_parquet(tmp_path / "anytime_td" / "features.parquet")
    (tmp_path / "anytime_td" / "feature_cols.pkl").write_bytes(__import__("pickle").dumps([]))

    class Model:
        feature_names = None

        def predict_proba(self, X):
            return np.full(len(X), 0.3)

    class Spec:
        def load(self, path):
            return Model()

    monkeypatch.setattr(wr, "ensure_registered", lambda: None)
    monkeypatch.setattr(wr, "get_config", lambda: {})
    monkeypatch.setattr(wr, "get_path", lambda *parts: tmp_path.joinpath(*parts[1:]))
    monkeypatch.setattr(wr, "_filter_low_activity", lambda d: d)
    monkeypatch.setattr(wr, "get_model", lambda name: Spec())
    monkeypatch.setattr(wr, "prepare_data", lambda d, cols: (d, None))
    monkeypatch.setattr(wr, "_market_for", lambda *a: None)

    out = wr.score_week(2026, 7, "anytime_td", "xgb")
    assert out["games"] == 1 and out["players"] == 2
    assert out["scorers"] == 1 and out["actual_total"] == 1.0


def _safe_legs_script():
    spec = importlib.util.spec_from_file_location(
        "safe_legs_forward", ROOT / "scripts" / "70_safe_legs_forward.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_header_only_record_reads_as_no_legs(tmp_path):
    mod = _safe_legs_script()
    path = tmp_path / "forward.csv"
    assert mod.load_record(path) is None
    path.write_text("rule,season,week,game_id,odds,implied_prob,hit\n")
    assert mod.load_record(path) is None
    path.write_text(path.read_text() + "model,2026,7,G,-330,0.77,1\n")
    assert mod.load_record(path)["hit"].dtype.is_integer()


def _wrap(tmp_path, count: int, fail_site: bool, *args):
    """Run the wrap with every step stubbed: the count is the graded games."""
    stub = tmp_path / "py"
    stub.write_text(f"""#!/bin/sh
if [ "$1" = "-" ]; then cat >/dev/null; echo {count}; exit 0; fi
echo "$@" >> "{tmp_path}/calls"
case "$1" in scripts/20_export_html.py) exit {1 if fail_site else 0};; esac
exit 0
""")
    stub.chmod(0o755)
    env = {**os.environ, "WRAP_PY": str(stub), "WRAP_LOG_DIR": str(tmp_path / "logs"),
           "HOME": str(tmp_path)}  # no deploy key, so the deploy is skipped
    done = subprocess.run(["bash", str(ROOT / "scripts" / "sunday_wrap.sh"), *args],
                          env=env, capture_output=True, text=True)
    assert done.returncode == (1 if fail_site else 0), done.stdout
    calls = (tmp_path / "calls").read_text() if (tmp_path / "calls").exists() else ""
    (tmp_path / "calls").unlink(missing_ok=True)
    return "scripts/47_export_site.py" in calls


def test_a_failed_publish_is_retried_by_the_next_run(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / ".wrap_published").write_text("2988\n")
    assert _wrap(tmp_path, 3001, fail_site=True)        # new finals; export crashes
    assert (tmp_path / "logs" / ".wrap_published").read_text().strip() == "2988"
    assert _wrap(tmp_path, 3001, fail_site=False)       # same count, still publishes
    assert (tmp_path / "logs" / ".wrap_published").read_text().strip() == "3001"
    assert not _wrap(tmp_path, 3001, fail_site=False)   # now nothing new


def test_force_publishes_with_nothing_new(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / ".wrap_published").write_text("3001\n")
    assert _wrap(tmp_path, 3001, False, "--force")
