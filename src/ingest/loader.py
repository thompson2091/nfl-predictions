"""Ingest nflverse data via nflreadpy.

Migrated from `nfl_data_py`, which nflverse has deprecated with no further
maintenance planned. That deprecation was not cosmetic: its weekly-stats feed
had silently stopped at 2024 while play-by-play carried on to 2025, which
blanked every player_* feature for both the test and predict seasons and
inflated Week 1 probabilities by ~2.7x. See docs/DATA_SOURCES.md.

nflreadpy returns Polars natively (no pandas round-trip) and tracks nflverse
releases, so the same class of silent lag is far less likely. Where a feed is
genuinely unavailable we now say so loudly rather than continuing with a hole.
"""
import nflreadpy as nfl
import polars as pl

from src.utils.config import get_config
from src.utils.paths import get_path
from src.utils.team_mappings import normalize_teams


class IngestError(RuntimeError):
    """A required feed could not be loaded."""


def _load(name: str, fn, seasons: list[int] | None = None, required: bool = True,
          **kwargs) -> pl.DataFrame:
    """Call an nflreadpy loader and report what actually came back.

    A feed returning nothing used to be swallowed with a warning. That is how a
    whole season went missing unnoticed, so `required` feeds now raise.
    """
    try:
        df = fn(seasons, **kwargs) if seasons is not None else fn(**kwargs)
    except Exception as e:
        if required:
            raise IngestError(f"{name} failed: {e}") from e
        print(f"  WARNING: {name} unavailable ({e})")
        return pl.DataFrame()

    if df is None or df.height == 0:
        if required:
            raise IngestError(f"{name} returned no rows for seasons={seasons}")
        print(f"  WARNING: {name} returned no rows")
        return pl.DataFrame()
    return df


def _report_coverage(name: str, df: pl.DataFrame, requested: list[int]) -> None:
    """Print per-season coverage and flag any requested season that is empty."""
    if "season" not in df.columns or df.height == 0:
        return
    got = set(df["season"].unique().to_list())
    missing = [s for s in requested if s not in got]
    print(f"  {name}: {df.height:,} rows, seasons {sorted(got)}")
    if missing:
        print(f"    !! MISSING SEASONS: {missing} — downstream features for these "
              f"will be null and silently become 0.0 at predict time.")


def _write(df: pl.DataFrame, filename: str) -> pl.DataFrame:
    path = get_path("raw") / filename
    df.write_parquet(path)
    print(f"    -> {path}")
    return df


#: Columns the coverage / personnel / box feature modules need. `nfl_data_py`
#: folded these into play-by-play; nflreadpy keeps participation separate, so we
#: merge them back rather than lose three feature families.
_PARTICIPATION_COLS = [
    "offense_formation", "offense_personnel", "defense_personnel",
    "defenders_in_box", "number_of_pass_rushers",
    "defense_man_zone_type", "defense_coverage_type",
]


def load_pbp(seasons: list[int]) -> pl.DataFrame:
    print(f"Loading PBP for {seasons[0]}-{seasons[-1]}...")
    df = _load("pbp", nfl.load_pbp, seasons)
    df = normalize_teams(df, ["posteam", "defteam", "td_team"])

    # Participation only exists from 2016; asking for earlier seasons errors out
    # and would silently cost us three feature families.
    #
    # Season by season, and for the same reason `load_injuries` is: `_load`
    # passes the whole list in ONE call, so a range containing a single
    # unavailable season returns an empty frame for all of them. Participation
    # lags play-by-play by a season, so the moment the predict season was added
    # to this range the call started failing with "Season must be between 2016
    # and 2025" and coverage, personnel and box features went empty for
    # 2016-2025 too — a feature loss three families wide, reported as one
    # warning about the season that was never going to have data anyway.
    part_frames = []
    for s in (y for y in seasons if y >= 2016):
        part_s = _load(f"participation {s}", nfl.load_participation, [s],
                       required=False)
        if part_s.height:
            part_frames.append(part_s)
    part = (pl.concat(part_frames, how="diagonal_relaxed")
            if part_frames else pl.DataFrame())
    if part.height:
        keep = ["nflverse_game_id", "play_id"] + [c for c in _PARTICIPATION_COLS if c in part.columns]
        part = part.select(keep).rename({"nflverse_game_id": "game_id"})
        part = part.unique(subset=["game_id", "play_id"], keep="first")
        before = df.height
        df = df.join(part, on=["game_id", "play_id"], how="left")
        if df.height != before:
            raise IngestError(
                f"participation join fanned out PBP: {before} -> {df.height} rows"
            )
        cov = df.filter(pl.col("defense_man_zone_type").is_not_null()).height / max(df.height, 1)
        print(f"  Participation merged: man/zone on {cov:.0%} of plays, "
              f"box counts on {df['defenders_in_box'].is_not_null().mean():.0%}")
    else:
        print("  WARNING: no participation data — coverage/personnel/box features "
              "will be empty.")

    _report_coverage("PBP", df, seasons)
    return _write(_keep_other_seasons(df, "pbp.parquet"), "pbp.parquet")


def load_weekly_stats(seasons: list[int]) -> pl.DataFrame:
    """Weekly player stats — the feed whose absence broke the pipeline.

    nflreadpy calls the team column `team`; downstream code and the PBP-derived
    fallback both expect `recent_team`, so it is aliased here rather than
    touching every consumer.
    """
    print(f"Loading weekly player stats for {seasons[0]}-{seasons[-1]}...")
    df = _load("player_stats", nfl.load_player_stats, seasons, summary_level="week")
    if "recent_team" not in df.columns and "team" in df.columns:
        df = df.with_columns(pl.col("team").alias("recent_team"))
    df = normalize_teams(df, ["recent_team"])
    _report_coverage("Weekly stats", df, seasons)
    return _write(_keep_other_seasons(df, "weekly_stats.parquet"), "weekly_stats.parquet")


def _keep_other_seasons(df: pl.DataFrame, filename: str) -> pl.DataFrame:
    """MERGE, never replace: seasons not asked for survive the write.

    `_write` overwrites. Every loader here can be called with ONE season —
    `56_inactives.py --refresh` does it fifteen times a week — and when it is,
    a plain write deletes every other season in the file while nothing fails:
    the current week still resolves, so the board, the candidates and the
    checks all carry on.

    It has happened twice. `load_rosters` replaced 2015-2026 with 2026 alone
    and grading the odds archive silently went to 0% across 44,000 closing
    prices, reported only as "grading will be sparse". `load_injuries` was
    never given the same fix and did it again: 61,221 rows to 692, for the
    same reason, a year later.

    So it is a shared function rather than a paragraph repeated per loader,
    and `test_every_season_keyed_loader_merges` fails on any loader that calls
    `_write` without it. A caller that wants only the seasons it asked for
    should filter what it READS, not the file everything else reads too.
    """
    if df.is_empty() or "season" not in df.columns:
        return df
    path = get_path("raw") / filename
    if not path.exists():
        return df
    try:
        prior = pl.read_parquet(path)
        if "season" not in prior.columns:
            return df
        fresh = set(df["season"].unique().to_list())
        keep = prior.filter(~pl.col("season").is_in(fresh))
        if keep.height:
            df = pl.concat([keep, df], how="diagonal_relaxed")
    except Exception as e:                                       # noqa: BLE001
        print(f"  WARNING: could not merge existing {filename} ({e}) — "
              f"writing only {sorted(set(df['season'].unique().to_list()))}")
    return df


def load_rosters(seasons: list[int]) -> pl.DataFrame:
    """Weekly rosters where available, season rosters for upcoming seasons.

    `load_rosters_weekly` only covers seasons that have been played, so an
    upcoming season has to fall back to the season-level roster.
    """
    print(f"Loading rosters for {seasons[0]}-{seasons[-1]}...")
    frames = []
    for s in seasons:
        df_s = _load(f"rosters_weekly {s}", nfl.load_rosters_weekly, [s], required=False)
        if df_s.height == 0:
            df_s = _load(f"rosters {s}", nfl.load_rosters, [s], required=False)
            if df_s.height and "week" not in df_s.columns:
                # Season roster has no week; treat it as week 1 so joins line up.
                df_s = df_s.with_columns(pl.lit(1).cast(pl.Int32).alias("week"))
            if df_s.height:
                print(f"    {s}: season roster ({df_s.height:,} rows) — weekly not published yet")
        if df_s.height:
            frames.append(df_s)
    if not frames:
        raise IngestError("no roster data for any requested season")
    df = pl.concat(frames, how="diagonal_relaxed")

    # nflreadpy names these differently to nfl_data_py; downstream code (and the
    # candidate builder in particular) expects player_id / player_name.
    if "player_id" not in df.columns and "gsis_id" in df.columns:
        df = df.with_columns(pl.col("gsis_id").alias("player_id"))
    if "player_name" not in df.columns:
        for alt in ("full_name", "football_name", "display_name"):
            if alt in df.columns:
                df = df.with_columns(pl.col(alt).alias("player_name"))
                break
        else:
            raise IngestError(
                f"rosters have no usable name column; got {df.columns[:15]}"
            )
    df = normalize_teams(df, ["team"])
    _report_coverage("Rosters", df, seasons)
    return _write(_keep_other_seasons(df, "rosters.parquet"),
                  "rosters.parquet")


def load_schedules(seasons: list[int]) -> pl.DataFrame:
    print(f"Loading schedules for {seasons[0]}-{seasons[-1]}...")
    df = _load("schedules", nfl.load_schedules, seasons)
    df = normalize_teams(df, ["home_team", "away_team"])
    _report_coverage("Schedules", df, seasons)
    return _write(_keep_other_seasons(df, "schedules.parquet"),
                  "schedules.parquet")


def load_snap_counts(seasons: list[int]) -> pl.DataFrame:
    print(f"Loading snap counts for {seasons[0]}-{seasons[-1]}...")
    df = _load("snap_counts", nfl.load_snap_counts, seasons)
    df = normalize_teams(df, ["team"])
    _report_coverage("Snap counts", df, seasons)
    return _write(_keep_other_seasons(df, "snap_counts.parquet"), "snap_counts.parquet")


def _load_ngs(stat_type: str, seasons: list[int], filename: str) -> pl.DataFrame:
    print(f"Loading NGS {stat_type} for {seasons[0]}-{seasons[-1]}...")
    df = _load(f"ngs_{stat_type}", nfl.load_nextgen_stats, seasons,
               required=False, stat_type=stat_type)
    if df.height == 0:
        return df
    df = df.filter(pl.col("week") >= 1)          # drop season aggregates
    team_col = "team_abbr" if "team_abbr" in df.columns else "team"
    df = normalize_teams(df, [team_col])
    _report_coverage(f"NGS {stat_type}", df, seasons)
    return _write(df, filename)


def load_ngs_receiving(seasons: list[int]) -> pl.DataFrame:
    return _load_ngs("receiving", seasons, "ngs_receiving.parquet")


def load_ngs_rushing(seasons: list[int]) -> pl.DataFrame:
    return _load_ngs("rushing", seasons, "ngs_rushing.parquet")


def load_injuries(seasons: list[int]) -> pl.DataFrame:
    """Injury reports, per season so one unavailable year cannot empty the rest.

    Called with `fwd`, which includes the predict season. nflverse publishes no
    injury rows for a season until its game-week practice reports start, so the
    upcoming season raises "Season must be between 2009 and YYYY" — and because
    `_load` passes the whole list in one call, that failure used to return an
    empty frame for ALL seasons and leave the previous file in place untouched.
    Loading season by season keeps the training range and lets _report_coverage
    name the predict season as missing, which is the thing worth knowing: the
    four injury features are in the served matrix, so a season with no rows is
    four constants at score time, not a neutral default.
    """
    print(f"Loading injuries for {seasons[0]}-{seasons[-1]}...")
    frames = []
    for s in seasons:
        df_s = _load(f"injuries {s}", nfl.load_injuries, [s], required=False)
        if df_s.height:
            frames.append(df_s)
    df = pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()
    if df.height == 0:
        return df
    df = normalize_teams(df, ["team"])
    _report_coverage("Injuries", df, seasons)
    return _write(_keep_other_seasons(df, "injuries.parquet"), "injuries.parquet")


def load_depth_charts(seasons: list[int]) -> pl.DataFrame:
    """Depth charts, in whichever format nflverse publishes per season.

    Pre-2025 uses (season, week, depth_team); 2025+ uses (dt, pos_rank) with
    dated snapshots. They are written to separate files and recombined in the
    assembler. The new-format feed is the one that matters for an upcoming week —
    it updates through the offseason, so re-run ingest close to kickoff.
    """
    print(f"Loading depth charts for {seasons[0]}-{seasons[-1]}...")
    old, new = [], []
    for s in seasons:
        df_s = _load(f"depth_charts {s}", nfl.load_depth_charts, [s], required=False)
        if df_s.height == 0:
            continue
        if "depth_team" in df_s.columns:
            old.append(df_s)
        elif "pos_rank" in df_s.columns:
            new.append(df_s)
        else:
            print(f"    {s}: unrecognised depth chart format, skipping")

    df_old = pl.DataFrame()
    if old:
        df_old = pl.concat(old, how="diagonal_relaxed")
        team_col = "club_code" if "club_code" in df_old.columns else "team"
        df_old = normalize_teams(df_old, [team_col])
        print(f"  Depth charts (legacy format): {df_old.height:,} rows")
        _write(df_old, "depth_charts.parquet")

    if new:
        df_new = pl.concat(new, how="diagonal_relaxed")
        df_new = normalize_teams(df_new, ["team"])
        newest = df_new["dt"].max()
        print(f"  Depth charts (current format): {df_new.height:,} rows, "
              f"newest snapshot {newest}")
        _write(df_new, "depth_charts_new.parquet")
    else:
        print("  WARNING: no current-format depth charts — role changes for the "
              "predict season will be invisible.")

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

    # Everything that has to cover the season being predicted, not just the
    # training range.
    fwd = seasons + ([predict_season] if predict_season and predict_season not in seasons else [])

    # `fwd`, not `seasons`. Play-by-play is the source of the target labels AND
    # of every team/opponent season-to-date aggregate, so a predict season with
    # no play-by-play is two separate failures that only show up a week apart.
    #
    # Week 1 hides it: carry_forward fills the team features from the previous
    # season, so the board looks right. Week 2 is where it lands — the season
    # average now needs a week-1 observation that was never ingested, and every
    # `*_szn_avg` team and opponent feature goes 100% null and then 0.0.
    # Measured on 2026-09-15: week 1 had 954/954 non-null, week 2 had 0/805,
    # and `team_plays_per_game_szn_avg` scored at 29 SDs from where it was
    # fitted (84.3 -> 0.0). The skew check does fire here, loudly, into a log
    # nobody reads while the pipeline carries on and records picks.
    #
    # The same omission also left `02_targets.py` extracting zero rows for the
    # predict season, so a finished week could not be graded.
    load_pbp(fwd)
    load_weekly_stats(fwd)

    load_rosters(fwd)
    load_schedules(fwd)
    # `fwd`: snap counts publish weekly in season, and `snap_pct` plus the two
    # ix_snap_* interactions are in the served matrix. On the training range
    # alone they were 100% null for week 2 against a 0.39 training rate.
    load_snap_counts(fwd)
    load_depth_charts(fwd)

    ngs_seasons = [s for s in seasons if s >= 2016]   # NGS starts in 2016
    if ngs_seasons:
        load_ngs_receiving(ngs_seasons)
        load_ngs_rushing(ngs_seasons)

    # `fwd`, not `seasons`: four injury features (is_out, is_questionable,
    # teammate_out_boost, starter_out_at_position) are in the served matrix, so
    # the predict season needs its own rows. Passing the training range left
    # them 100% null for every predicted week, and check_feature_skew could not
    # see it — injuries are sparse, so a training null rate of 0.942 makes total
    # absence look like a 0.058 change against a 0.35 threshold.
    load_injuries(fwd)

    # Backstop: if the weekly feed ever lags play-by-play again, rebuild the
    # missing seasons from PBP rather than leaving player_* features null.
    from src.ingest.derive_weekly_stats import backfill_weekly_stats
    print("\nChecking weekly stats against play-by-play coverage...")
    backfill_weekly_stats()

    print("\nIngestion complete.")
