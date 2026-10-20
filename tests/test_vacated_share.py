"""How much of a team's recent work is Out, on every player's row."""
from __future__ import annotations

import sys
from pathlib import Path

import polars as pl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.features.injury_features import build_vacated_share  # noqa: E402


def row(name, pos, rush, tgt, out=None, team="WAS"):
    one = {p: 1 if p == pos else 0 for p in ("RB", "TE", "QB", "FB", "DEFST")}
    return {"season": 2026, "week": 6, "team": team, "player_name": name,
            "is_out": out, "player_rush_share_avg_5g": rush,
            "player_target_share_avg_5g": tgt,
            **{f"position_{p}": v for p, v in one.items()}}


def test_the_healthy_backup_sees_the_out_starters_share():
    """`teammate_out_boost` read null for him: he is not on the report."""
    d = pl.DataFrame([row("Starter", "RB", 0.45, 0.04, out=1.0),
                      row("Backup", "RB", 0.18, 0.06),
                      row("Wideout", "WR", 0.0, 0.25),
                      row("Other team", "RB", 0.5, 0.1, team="SF")])
    g = {r["player_name"]: r for r in build_vacated_share(d).iter_rows(named=True)}
    b = g["Backup"]
    assert b["vac_rush_share"] == pytest.approx(0.45)
    assert b["vac_rush_share_pos"] == pytest.approx(0.45)
    # Split by recent share among those left: 0.45 * 0.18 / 0.55.
    assert b["vac_rush_share_inherit"] == pytest.approx(0.45 * 0.18 / 0.55)
    assert g["Wideout"]["vac_rush_share_pos"] == 0.0, "a back's carries reached a receiver's position"
    assert g["Wideout"]["vac_target_share"] == pytest.approx(0.04)
    assert g["Starter"]["vac_rush_share"] == 0.0, "the Out player counted his own share"
    assert g["Starter"]["vac_rush_share_inherit"] == 0.0
    assert g["Other team"]["vac_rush_share"] == 0.0, "another team's injury leaked"


def test_nobody_out_is_zero_not_null():
    d = pl.DataFrame([row("A", "RB", 0.5, 0.1), row("B", "WR", 0.0, 0.2)])
    got = build_vacated_share(d)
    assert got["vac_rush_share"].null_count() == 0
    assert got["vac_target_share"].to_list() == [0.0, 0.0]
