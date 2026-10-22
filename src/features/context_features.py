import polars as pl
from src.utils.paths import get_path


def build_snap_features(snap_counts: pl.DataFrame, rosters: pl.DataFrame) -> pl.DataFrame:
    """Snap count percentage from previous week (shifted in assembler).

    Snap counts use player names and pfr_player_id, not GSIS IDs.
    We map via rosters' pfr_id -> player_id (GSIS ID).
    """
    # Build pfr_id -> player_id mapping from rosters
    pfr_mapping = (
        rosters.select(["player_id", "pfr_id"])
        .filter(pl.col("pfr_id").is_not_null() & pl.col("player_id").is_not_null())
        .unique(subset=["pfr_id"], keep="last")
    )

    snaps = snap_counts.select([
        "pfr_player_id", "season", "week", "team", "offense_pct",
    ])

    # Map pfr_player_id -> player_id via rosters
    snaps = snaps.join(
        pfr_mapping, left_on="pfr_player_id", right_on="pfr_id", how="left"
    ).filter(
        pl.col("player_id").is_not_null()
    ).select([
        "player_id", "season", "week", "team",
        pl.col("offense_pct").alias("snap_pct"),
    ])

    return snaps


def build_depth_chart_features(depth_charts: pl.DataFrame,
                               schedules: pl.DataFrame | None = None) -> pl.DataFrame:
    """Starter flag from depth charts. Handles both old (2015-2024) and new (2025+) formats."""

    # Old format has: season, week, club_code, gsis_id, depth_team, formation
    # New format has: dt, team, gsis_id, pos_abb, pos_rank (no season/week)
    if "depth_team" in depth_charts.columns:
        return _build_dc_old_format(depth_charts)
    elif "pos_rank" in depth_charts.columns:
        return _build_dc_new_format(depth_charts, schedules)
    else:
        # Empty fallback
        return pl.DataFrame(schema={
            "player_id": pl.Utf8, "season": pl.Int64,
            "week": pl.Int64, "team": pl.Utf8, "is_starter": pl.Int8,
        })


def _build_dc_old_format(depth_charts: pl.DataFrame) -> pl.DataFrame:
    """Old depth chart format (2015-2024): has season, week, depth_team."""
    dc = depth_charts.select([
        "season", "week", "club_code", "gsis_id",
        "depth_team", "formation",
    ]).rename({"club_code": "team", "gsis_id": "player_id"}).with_columns(
        pl.col("week").cast(pl.Int64),
        pl.col("season").cast(pl.Int64),
    )

    # Starter = depth_team == 1
    dc = dc.with_columns(
        (pl.col("depth_team").cast(pl.Int32, strict=False) == 1).cast(pl.Int8).alias("is_starter")
    ).filter(
        pl.col("player_id").is_not_null()
    )

    # Take most recent depth chart entry per player/season/week
    dc = dc.sort(["player_id", "season", "week"]).unique(
        subset=["player_id", "season", "week"], keep="last"
    )

    return dc.select(["player_id", "season", "week", "team", "is_starter"])


#: Skill positions the candidate pool is drawn from. The new feed also carries
#: line and defense; nothing downstream asks about a starting guard.
_OFF_POSITIONS = ("QB", "RB", "WR", "TE", "FB")


def dc_new_weekly(depth_charts: pl.DataFrame,
                  schedules: pl.DataFrame | None = None) -> pl.DataFrame:
    """New-format (2025+) snapshots placed on the week they were current for.

    The 2025 feed replaced season/week with a `dt` timestamp and publishes a
    fresh chart most days — 136 distinct dates across the 2025 regular season,
    all 32 teams on each. It carries no week of its own, so one has to be
    assigned, and *how* decides whether the column means anything.

    This takes, for each team-week, the last chart published **strictly
    before** that team's own kickoff. Strictly, because a chart stamped on
    game day may already reflect the inactives list, and a starter flag that
    knows who dressed is a leak. Kickoff comes from the schedule per team-week
    rather than from a fixed weekday, so byes, Thursday and Monday games and
    the international slate all land on the right chart instead of an assumed
    one.

    The previous version derived the season from the snapshot's month and
    stamped `week = 1` on every row, then deduplicated to one chart per player
    per season. That collapsed all of 2025 to a single preseason snapshot:
    `is_starter` went 95% null and the three `ix_starter_x_*` interactions
    fell by a factor of 24 against 2024. The column existed, and described
    August.

    Weeks with no chart before kickoff stay unmatched rather than borrowing a
    later one, which is why this returns fewer rows than the pool for any
    season the feed does not cover.
    """
    if depth_charts.is_empty() or "pos_rank" not in depth_charts.columns:
        return pl.DataFrame(schema={
            "player_id": pl.Utf8, "season": pl.Int64, "week": pl.Int64,
            "team": pl.Utf8, "position": pl.Utf8, "depth_rank": pl.Int32,
        })
    if schedules is None or schedules.is_empty():
        raise ValueError(
            "New-format depth charts carry no season/week; they can only be "
            "placed against a schedule. Pass `schedules`.")

    snaps = (
        depth_charts
        .filter(pl.col("gsis_id").is_not_null())
        .filter(pl.col("pos_abb").is_in(_OFF_POSITIONS))
        .with_columns(
            pl.col("dt").str.slice(0, 10).str.to_date("%Y-%m-%d").alias("snap_date"))
        .filter(pl.col("snap_date").is_not_null())
    )

    # One row per team-week, carrying that team's own kickoff.
    kickoff = (
        pl.concat([
            schedules.select(["season", "week", "gameday",
                              pl.col("home_team").alias("team")]),
            schedules.select(["season", "week", "gameday",
                              pl.col("away_team").alias("team")]),
        ])
        .with_columns(pl.col("gameday").str.to_date("%Y-%m-%d").alias("kickoff"))
        .drop("gameday")
        .filter(pl.col("kickoff").is_not_null())
        .with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64))
        .unique(subset=["season", "week", "team"])
        .sort("kickoff")
    )

    # Which published chart each team-week should read. Done on dates alone so
    # the as-of join stays one row per team-week; the roster is joined back
    # after, which is what makes the fan-out below countable.
    link = kickoff.join_asof(
        snaps.select(["team", "snap_date"]).unique().sort("snap_date"),
        left_on="kickoff", right_on="snap_date", by="team",
        strategy="backward", allow_exact_matches=False,
    ).filter(pl.col("snap_date").is_not_null())

    out = (
        link.join(snaps, on=["team", "snap_date"], how="inner")
        .select([
            pl.col("gsis_id").alias("player_id"),
            "season", "week", "team",
            pl.col("pos_abb").alias("position"),
            pl.col("pos_rank").cast(pl.Int32).alias("depth_rank"),
        ])
        # A player can appear under two position groups on one chart; keep his
        # best listing so the join back onto the spine stays one row per
        # player-week.
        .sort("depth_rank")
        .unique(subset=["player_id", "season", "week"], keep="first")
    )
    return out


def starter_slots(depth_charts_old: pl.DataFrame | None) -> dict[str, int]:
    """How many players the old feed called first team at each position.

    The two formats do not mean the same thing by "starter". The old feed's
    `depth_team == 1` is a first-team *unit*, so a team lists 2-3 receivers and
    sometimes two backs; the new feed's `pos_rank == 1` is the top of a
    position group, exactly one name. Taking `pos_rank == 1` as the starter
    flag therefore redefines the column halfway through the data — `is_starter`
    averaged 0.44 through 2024 and 0.24 from 2025, on a model trained entirely
    on the first meaning.

    So the cut-off is measured off the old feed rather than assumed: the median
    number of first-team offensive players per team-week, per position. It
    comes out QB/RB/TE/FB 1 and WR 2, stable in every season from 2015 to 2023,
    and it is recomputed from whatever history is passed rather than pinned, so
    a league that starts three receivers moves the number on its own.
    """
    default = {"QB": 1, "RB": 1, "WR": 2, "TE": 1, "FB": 1}
    if (depth_charts_old is None or depth_charts_old.is_empty()
            or "depth_team" not in depth_charts_old.columns):
        return default
    counts = (
        depth_charts_old
        .filter(pl.col("depth_team").cast(pl.Utf8).is_in(["1", "1.0"]))
        .filter(pl.col("formation") == "Offense")
        .filter(pl.col("position").is_in(_OFF_POSITIONS))
        .filter(pl.col("week").is_not_null())
        .group_by(["season", "week", "club_code", "position"])
        .agg(pl.len().alias("n"))
        .group_by("position")
        .agg(pl.col("n").median().alias("slots"))
    )
    fitted = {r["position"]: max(1, int(round(r["slots"])))
              for r in counts.iter_rows(named=True)}
    return {**default, **fitted}


def _build_dc_new_format(depth_charts: pl.DataFrame,
                         schedules: pl.DataFrame | None = None,
                         slots: dict[str, int] | None = None) -> pl.DataFrame:
    """New depth chart format (2025+): starter flag, on real weeks."""
    weekly = dc_new_weekly(depth_charts, schedules)
    if weekly.is_empty():
        return pl.DataFrame(schema={
            "player_id": pl.Utf8, "season": pl.Int64,
            "week": pl.Int64, "team": pl.Utf8, "is_starter": pl.Int8,
        })
    slots = slots or {"QB": 1, "RB": 1, "WR": 2, "TE": 1, "FB": 1}
    cutoff = pl.col("position").replace_strict(
        slots, default=1, return_dtype=pl.Int32)
    return weekly.select([
        "player_id", "season", "week", "team",
        (pl.col("depth_rank") <= cutoff).cast(pl.Int8).alias("is_starter"),
    ])


def starter_lookup(depth_charts_old: pl.DataFrame | None,
                   depth_charts_new: pl.DataFrame | None = None,
                   schedules: pl.DataFrame | None = None,
                   slots: dict[str, int] | None = None) -> pl.DataFrame:
    """Who the listed starter was, per season-week-team-position, both formats.

    One frame so `build_injury_features` cannot disagree with
    `build_depth_chart_features` about who started. It used to be handed the
    old-format file alone, which stops at 2024, so `starter_out_at_position`
    was a hard 0.0 for every 2025 row and null for all of 2026 — a feature the
    model trained on and could never see fire at predict time.
    """
    frames = []
    if (depth_charts_old is not None and not depth_charts_old.is_empty()
            and "depth_team" in depth_charts_old.columns):
        frames.append(
            depth_charts_old
            .filter(pl.col("depth_team").cast(pl.Utf8).is_in(["1", "1.0"]))
            .select([
                pl.col("gsis_id").alias("starter_id"),
                pl.col("season").cast(pl.Int64),
                pl.col("week").cast(pl.Int64),
                pl.col("club_code").alias("team"),
                pl.col("position").cast(pl.Utf8),
            ])
        )
    if (depth_charts_new is not None and not depth_charts_new.is_empty()
            and "pos_rank" in depth_charts_new.columns):
        weekly = dc_new_weekly(depth_charts_new, schedules)
        if not weekly.is_empty():
            # Every first-team name, not just the top one, so the dedup below
            # chooses among the same candidate set it does for the old feed.
            # Definitional parity only — it barely moves the rate (0.128 to
            # 0.126 on 2025). The gap against 2024's 0.083 is not a schema
            # artifact at all: 2025 carried 1,396 "Out" designations to 2024's
            # 1,116, and the starter-out rate genuinely rose from 0.035 to
            # 0.058. The feature is reporting a real season, not a bug.
            cut = pl.col("position").replace_strict(
                slots or {}, default=1, return_dtype=pl.Int32)
            # IN AN ORDER OF ITS OWN. `weekly` comes out of a join, whose row
            # order changes between runs, so "last in file order" picked a
            # different starter on ~550 team-week positions each rebuild
            # (2026-10-21). Sorted so the last row is the top-ranked name,
            # ties to the lower id: the same starter every run, and the one
            # the chart puts first.
            frames.append(
                weekly.filter(pl.col("depth_rank") <= cut)
                .sort(["season", "week", "team", "position", "depth_rank",
                       "player_id"],
                      descending=[False, False, False, False, True, True])
                .select([
                    pl.col("player_id").alias("starter_id"),
                    "season", "week", "team", "position",
                ])
            )
    if not frames:
        return pl.DataFrame(schema={
            "starter_id": pl.Utf8, "season": pl.Int64, "week": pl.Int64,
            "team": pl.Utf8, "position": pl.Utf8,
        })
    # A team-week can list two names at one position. "Last wins" was already
    # the rule; carrying an explicit ordinal makes it mean "last in file
    # order" every run instead of whatever `unique` happened to return, which
    # moved 0.6% of starter rows between runs on identical inputs.
    return (pl.concat([f.with_row_index("_ord") for f in frames],
                      how="vertical_relaxed")
            .filter(pl.col("starter_id").is_not_null())
            .sort("_ord")
            .unique(subset=["season", "week", "team", "position"], keep="last")
            .drop("_ord"))
