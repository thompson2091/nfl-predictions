"""Refreshing one season must not delete the others.

`load_rosters` WRITES `rosters.parquet`, and `56_inactives.py --refresh` calls
it with a single season, fifteen times a week. Its first firing replaced the
rosters for 2015-2026 with 2026 alone and nothing failed — the current week
still resolved, so the board, the candidate builder and the inactives check
all carried on. What broke was everything keyed on an older season.
"""
import polars as pl


def test_refreshing_one_season_keeps_the_rest(tmp_path, monkeypatch):
    from src.ingest import loader

    path = tmp_path / "rosters.parquet"
    pl.DataFrame({
        "season": [2023, 2024, 2025],
        "week": [1, 1, 1],
        "player_id": ["a", "b", "c"],
        "player_name": ["A", "B", "C"],
        "team": ["BUF", "KC", "SF"],
    }).write_parquet(path)

    def fake_get_path(kind, *a):
        return tmp_path

    monkeypatch.setattr(loader, "get_path", fake_get_path)
    monkeypatch.setattr(
        loader, "_load",
        lambda name, fn, seasons=None, required=True, **k: pl.DataFrame({
            "season": [2026], "week": [1],
            "player_id": ["z"], "player_name": ["Z"], "team": ["DAL"]}))
    monkeypatch.setattr(loader, "_write",
                        lambda df, name: (df.write_parquet(tmp_path / name), df)[1])

    out = loader.load_rosters([2026])
    seasons = sorted(out["season"].unique().to_list())
    assert seasons == [2023, 2024, 2025, 2026], (
        f"refreshing 2026 dropped the others: {seasons}")

    # And the refreshed season is REPLACED, not duplicated — otherwise every
    # weekly firing would add another copy of the current season.
    assert out.filter(pl.col("season") == 2026).height == 1


def test_the_archive_resolves_to_player_ids_for_every_season_it_holds():
    """0% resolution is reported as "grading will be sparse" and nothing else.

    It is the shape a truncated roster file takes downstream: the current
    season resolves, every older one silently matches nothing.
    """
    from src.ingest.odds_history import (HISTORY_PATH, SCHEMA, _conform,
                                         _resolve_player_id)

    if not HISTORY_PATH.exists():
        return
    h = _conform(pl.read_parquet(HISTORY_PATH), SCHEMA).filter(
        pl.col("market") == "anytime_td")
    if h.height == 0:
        return
    r = h.with_columns(_resolve_player_id(h))
    by = (r.group_by("season")
          .agg(pl.col("player_id").is_not_null().mean().alias("rate"),
               pl.len().alias("n"))
          .filter(pl.col("n") >= 500))
    bad = by.filter(pl.col("rate") < 0.5)
    assert bad.is_empty(), (
        f"seasons resolving under 50%: {bad.to_dicts()} — rosters.parquet "
        f"probably holds only some of the seasons the archive covers")
