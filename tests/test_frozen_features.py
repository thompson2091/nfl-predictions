"""A feature that stops moving in the season being predicted.

Non-null rates cannot see this. In 2026 every Next Gen Stats feature was
2025's final value carried forward all season — non-null on 27.5% of rows
against 28.8%, so the coverage checks passed — while 0% of players varied
week to week against 51% in 2025. This compares within-player variation in
the predict season with the season before.
"""
from __future__ import annotations

import polars as pl
import pytest

from src.utils.paths import get_path

#: Known and accepted: participation-only features with no in-season source.
#: nflverse publishes participation a season behind and FTN does not chart
#: personnel or man/zone. They carry each team's last full-season value.
STALE_BY_SOURCE = ("team_personnel_", "opp_man_coverage_")


def test_no_feature_is_silently_frozen_in_the_predict_season():
    path = get_path("processed", "anytime_td") / "features.parquet"
    if not path.exists():
        pytest.skip("no feature matrix")
    f = pl.scan_parquet(path)
    cur = int(f.select(pl.col("season").max()).collect().item())
    weeks = f.filter((pl.col("season") == cur) & pl.col("target").is_not_null()) \
             .select(pl.col("week").max()).collect().item()
    if not weeks or weeks < 4:
        pytest.skip("too few weeks of the season to compare")
    from src.models.trainer import excluded_columns

    # Columns no model reads are not checked, nor are yes/no flags: a flag
    # such as `wx_is_cold` is honestly constant through September.
    skip = excluded_columns() | {"target"}
    prev = f.filter(pl.col("season") == cur - 1).collect()
    cols = [c for c, t in f.collect_schema().items()
            if t.is_numeric() and c not in skip and prev[c].n_unique() > 3]
    def variation(season):
        d = f.filter((pl.col("season") == season)
                     & pl.col("week").is_between(2, weeks)).collect()
        out = {}
        for c in cols:
            g = d.drop_nulls(c).group_by("player_id").agg(pl.col(c).n_unique().alias("u"))
            if g.height > 50:
                out[c] = float((g["u"] > 1).mean())
        return out
    now, before = variation(cur), variation(cur - 1)
    frozen = sorted(c for c, v in now.items()
                    if v < 0.02 and before.get(c, 0) > 0.2
                    and not c.startswith(STALE_BY_SOURCE))
    assert not frozen, f"frozen in {cur} but moving in {cur - 1}: {frozen}"
