import nfl_data_py as nfl
import polars as pl
from src.utils.config import get_config
from src.utils.paths import get_path
from src.utils.team_mappings import normalize_teams


def _safe_load(name, fn, *args, **kwargs):
    """Try loading data, return None on failure."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        print(f"  WARNING: {name} failed: {e}")
        return None


def load_pbp(seasons: list[int]) -> pl.DataFrame:
    print(f"Loading PBP for {seasons[0]}-{seasons[-1]}...")
    df = pl.from_pandas(nfl.import_pbp_data(seasons))
    df = normalize_teams(df, ["posteam", "defteam", "td_team"])
    path = get_path("raw") / "pbp.parquet"
    df.write_parquet(path)
    print(f"  PBP: {df.shape[0]:,} rows -> {path}")
    return df


def load_weekly_stats(seasons: list[int]) -> pl.DataFrame:
    print(f"Loading weekly stats for {seasons[0]}-{seasons[-1]}...")
    # Load per-season to handle missing years gracefully
    dfs = []
    for s in seasons:
        pdf = _safe_load(f"weekly_stats {s}", nfl.import_weekly_data, [s])
        if pdf is not None:
            dfs.append(pl.from_pandas(pdf))
            print(f"    {s} done ({len(pdf):,} rows)")
    df = pl.concat(dfs, how="diagonal_relaxed")
    df = normalize_teams(df, ["recent_team"])
    path = get_path("raw") / "weekly_stats.parquet"
    df.write_parquet(path)
    print(f"  Weekly stats: {df.shape[0]:,} rows -> {path}")
    return df


def load_rosters(seasons: list[int]) -> pl.DataFrame:
    print(f"Loading rosters for {seasons[0]}-{seasons[-1]}...")
    dfs = []
    for s in seasons:
        try:
            pdf = nfl.import_weekly_rosters([s])
            pdf = pdf.reset_index(drop=True)
            dfs.append(pl.from_pandas(pdf))
            print(f"    {s} done ({len(pdf):,} rows)")
        except Exception as e:
            print(f"    {s} FAILED: {e}")
    df = pl.concat(dfs, how="diagonal_relaxed")
    df = normalize_teams(df, ["team"])
    path = get_path("raw") / "rosters.parquet"
    df.write_parquet(path)
    print(f"  Rosters: {df.shape[0]:,} rows -> {path}")
    return df


def load_schedules(seasons: list[int]) -> pl.DataFrame:
    print(f"Loading schedules for {seasons[0]}-{seasons[-1]}...")
    df = pl.from_pandas(nfl.import_schedules(seasons))
    df = normalize_teams(df, ["home_team", "away_team"])
    path = get_path("raw") / "schedules.parquet"
    df.write_parquet(path)
    print(f"  Schedules: {df.shape[0]:,} rows -> {path}")
    return df


def load_snap_counts(seasons: list[int]) -> pl.DataFrame:
    print(f"Loading snap counts for {seasons[0]}-{seasons[-1]}...")
    dfs = []
    for s in seasons:
        pdf = _safe_load(f"snap_counts {s}", nfl.import_snap_counts, [s])
        if pdf is not None:
            dfs.append(pl.from_pandas(pdf))
            print(f"    {s} done ({len(pdf):,} rows)")
    df = pl.concat(dfs, how="diagonal_relaxed")
    df = normalize_teams(df, ["team"])
    path = get_path("raw") / "snap_counts.parquet"
    df.write_parquet(path)
    print(f"  Snap counts: {df.shape[0]:,} rows -> {path}")
    return df


def load_ngs_receiving(seasons: list[int]) -> pl.DataFrame:
    print(f"Loading NGS receiving for {seasons[0]}-{seasons[-1]}...")
    dfs = []
    for s in seasons:
        pdf = _safe_load(f"ngs_receiving {s}", nfl.import_ngs_data, "receiving", [s])
        if pdf is not None:
            dfs.append(pl.from_pandas(pdf))
            print(f"    {s} done ({len(pdf):,} rows)")
    if not dfs:
        print("  WARNING: No NGS receiving data loaded")
        return pl.DataFrame()
    df = pl.concat(dfs, how="diagonal_relaxed")
    # Filter out season aggregates (week 0)
    df = df.filter(pl.col("week") >= 1)
    df = normalize_teams(df, ["team_abbr"])
    path = get_path("raw") / "ngs_receiving.parquet"
    df.write_parquet(path)
    print(f"  NGS receiving: {df.shape[0]:,} rows -> {path}")
    return df


def load_ngs_rushing(seasons: list[int]) -> pl.DataFrame:
    print(f"Loading NGS rushing for {seasons[0]}-{seasons[-1]}...")
    dfs = []
    for s in seasons:
        pdf = _safe_load(f"ngs_rushing {s}", nfl.import_ngs_data, "rushing", [s])
        if pdf is not None:
            dfs.append(pl.from_pandas(pdf))
            print(f"    {s} done ({len(pdf):,} rows)")
    if not dfs:
        print("  WARNING: No NGS rushing data loaded")
        return pl.DataFrame()
    df = pl.concat(dfs, how="diagonal_relaxed")
    df = df.filter(pl.col("week") >= 1)
    df = normalize_teams(df, ["team_abbr"])
    path = get_path("raw") / "ngs_rushing.parquet"
    df.write_parquet(path)
    print(f"  NGS rushing: {df.shape[0]:,} rows -> {path}")
    return df


def load_injuries(seasons: list[int]) -> pl.DataFrame:
    print(f"Loading injuries for {seasons[0]}-{seasons[-1]}...")
    dfs = []
    for s in seasons:
        pdf = _safe_load(f"injuries {s}", nfl.import_injuries, [s])
        if pdf is not None:
            dfs.append(pl.from_pandas(pdf))
            print(f"    {s} done ({len(pdf):,} rows)")
    if not dfs:
        print("  WARNING: No injury data loaded")
        return pl.DataFrame()
    df = pl.concat(dfs, how="diagonal_relaxed")
    df = normalize_teams(df, ["team"])
    path = get_path("raw") / "injuries.parquet"
    df.write_parquet(path)
    print(f"  Injuries: {df.shape[0]:,} rows -> {path}")
    return df


def load_depth_charts(seasons: list[int]) -> pl.DataFrame:
    print(f"Loading depth charts for {seasons[0]}-{seasons[-1]}...")
    old_dfs = []
    new_dfs = []
    for s in seasons:
        pdf = _safe_load(f"depth_charts {s}", nfl.import_depth_charts, [s])
        if pdf is not None:
            df_s = pl.from_pandas(pdf)
            # 2025+ uses a different format (dt, pos_rank instead of season, week, depth_team)
            if "depth_team" in df_s.columns:
                old_dfs.append(df_s)
                print(f"    {s} done ({len(pdf):,} rows, old format)")
            elif "pos_rank" in df_s.columns:
                new_dfs.append(df_s)
                print(f"    {s} done ({len(pdf):,} rows, new format)")
            else:
                print(f"    {s} skipped (unknown format)")

    # Save old-format depth charts
    if old_dfs:
        df_old = pl.concat(old_dfs, how="diagonal_relaxed")
        df_old = normalize_teams(df_old, ["club_code"])
        path = get_path("raw") / "depth_charts.parquet"
        df_old.write_parquet(path)
        print(f"  Depth charts (old): {df_old.shape[0]:,} rows -> {path}")
    else:
        df_old = pl.DataFrame()

    # Save new-format depth charts separately
    if new_dfs:
        df_new = pl.concat(new_dfs, how="diagonal_relaxed")
        df_new = normalize_teams(df_new, ["team"])
        path_new = get_path("raw") / "depth_charts_new.parquet"
        df_new.write_parquet(path_new)
        print(f"  Depth charts (new): {df_new.shape[0]:,} rows -> {path_new}")

    return df_old


def ingest_all(test_mode: bool = False):
    cfg = get_config()
    start = cfg["seasons"]["start"]
    end = cfg["seasons"]["end"]
    predict_season = cfg["seasons"].get("predict_season")

    if test_mode:
        seasons = [end]
        print(f"TEST MODE: only loading {end}")
    else:
        seasons = list(range(start, end + 1))

    load_pbp(seasons)
    load_weekly_stats(seasons)
    load_rosters(seasons)

    # Schedules & rosters: also load predict_season if set
    sched_seasons = seasons[:]
    if predict_season and predict_season not in sched_seasons:
        sched_seasons.append(predict_season)

    load_schedules(sched_seasons)
    load_snap_counts(seasons)
    load_depth_charts(seasons)

    # NGS data (available 2016+)
    ngs_seasons = [s for s in seasons if s >= 2016]
    if ngs_seasons:
        load_ngs_receiving(ngs_seasons)
        load_ngs_rushing(ngs_seasons)

    load_injuries(seasons)

    # Load predict season rosters separately if available
    if predict_season and predict_season not in seasons:
        print(f"\nLoading {predict_season} rosters for prediction...")
        try:
            pdf = nfl.import_weekly_rosters([predict_season])
            pdf = pdf.reset_index(drop=True)
            pred_rosters = pl.from_pandas(pdf)
            pred_rosters = normalize_teams(pred_rosters, ["team"])
            # Append to existing rosters
            existing = pl.read_parquet(get_path("raw") / "rosters.parquet")
            combined = pl.concat([existing, pred_rosters], how="diagonal_relaxed")
            combined.write_parquet(get_path("raw") / "rosters.parquet")
            print(f"  Added {predict_season} rosters: {pred_rosters.shape[0]:,} rows")
        except Exception as e:
            print(f"  WARNING: {predict_season} rosters not available: {e}")

    print("Ingestion complete.")
