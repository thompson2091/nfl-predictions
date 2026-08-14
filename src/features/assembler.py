import polars as pl
from src.utils.config import get_config
from src.utils.paths import get_path
from src.features.player_features import build_player_rolling_features
from src.features.spine import player_week_spine
from src.features.team_features import build_team_features, build_opponent_features
from src.features.game_features import build_game_features
from src.features.context_features import build_snap_features, build_depth_chart_features
from src.features.target_history_features import build_player_target_history, build_team_target_tendency
from src.features.redzone_features import build_player_redzone_features, build_team_redzone_features
from src.features.opponent_position_features import build_opponent_position_features
from src.features.vegas_features import build_vegas_features
from src.features.player_share_features import build_player_share_features
from src.features.goalline_features import build_goalline_features
from src.features.opening_drive_features import build_opening_drive_features
from src.features.first_half_features import build_first_half_features
from src.features.qb_features import build_qb_features
from src.features.interaction_features import build_interaction_features
from src.features.td_proxy_features import build_td_proxy_features
from src.features.receiver_features import build_receiver_features
from src.features.rushing_efficiency_features import build_rushing_efficiency_features
from src.features.matchup_features import build_matchup_interaction_features
from src.features.injury_features import build_injury_features
from src.features.pace_features import build_pace_features
from src.features.score_first_features import build_score_first_features
from src.features.td_streak_features import build_td_streak_features
from src.features.opp_target_features import build_opp_target_features
from src.features.coach_features import build_coach_features
# TODO(oc-features): re-enable once data/raw/oc_mapping.csv is generated
# dynamically rather than hand-maintained. See build_oc_features docstring.
# from src.features.oc_features import build_oc_features
from src.features.odds_features import build_odds_features
from src.features.situational_features import build_situational_features
from src.features.coverage_features import build_coverage_features
from src.features.momentum_features import build_momentum_features
from src.features.personnel_features import build_personnel_features
from src.features.box_features import build_box_features


def _build_game_context_features(schedules: pl.DataFrame) -> pl.DataFrame:
    """Extract game context features from schedules.

    Returns one row per game_id + team (both sides of the game).
    - is_dome: 1 if roof is "dome" or "closed", 0 otherwise
    - is_divisional: 1 if div_game == 1, 0 otherwise
    - surface_turf: 1 if surface contains "turf" or "fieldturf" (case insensitive), 0 otherwise
    """
    df = schedules.select(["game_id", "home_team", "away_team", "roof", "div_game", "surface"]).unique()

    # Create home and away rows separately
    home = df.with_columns(pl.lit("home").alias("_side")).rename({"home_team": "team"}).drop("away_team")
    away = df.with_columns(pl.lit("away").alias("_side")).rename({"away_team": "team"}).drop("home_team")

    game_context = pl.concat([home, away], how="diagonal_relaxed")

    # Create features
    game_context = game_context.with_columns([
        (
            (pl.col("roof").str.to_lowercase() == "dome")
            | (pl.col("roof").str.to_lowercase() == "closed")
        ).cast(pl.Int8).alias("is_dome"),

        (pl.col("div_game") == 1).cast(pl.Int8).alias("is_divisional"),

        (
            (pl.col("surface").str.to_lowercase().str.contains("turf"))
            | (pl.col("surface").str.to_lowercase().str.contains("fieldturf"))
        ).cast(pl.Int8).alias("surface_turf"),
    ])

    # Select only the features we need
    return game_context.select(["game_id", "team", "is_dome", "is_divisional", "surface_turf"])


def _carry_forward(feats: pl.DataFrame, key_col: str,
                   predict_season: int) -> pl.DataFrame:
    """Give week 1 of *every* season the prior season's last known state.

    Carry-forward used to run for the predict season only, which made week 1
    mean something different when serving than it ever meant in training. The
    opening-drive features are the clearest case: only the team that receives
    the kickoff has a row, so a played season's week 1 covers 16 teams, while a
    projected week 1 covered all 32. Nine features drifted more than half a
    standard deviation between the two, and the model had never seen the
    combination it was being asked to score. Applying the projection to every
    season's week 1 makes the two identical by construction.

    No leakage: the value stamped onto week 1 of season S comes from season
    S-1, which is over before the row it labels is played. That is the same
    information a person has on opening weekend.

    Real rows always win. A key with a genuine week-1 row keeps it, and the
    projection only fills the gaps — otherwise this would overwrite measured
    values with stale ones and fan out every downstream join.
    """
    if feats.height == 0 or "season" not in feats.columns:
        return feats

    seasons = sorted(feats["season"].unique().to_list())
    # Every season that could have a week 1 needing a fill, including the
    # predict season, which has no rows of its own yet.
    targets = [s for s in seasons + [predict_season] if (s - 1) in seasons]
    if not targets:
        return feats

    sort_cols = [key_col, "week"]
    projections = []
    for season in sorted(set(targets)):
        last = (
            feats.filter(pl.col("season") == season - 1)
            .sort(sort_cols)
            .group_by(key_col)
            .last()
            .with_columns([
                pl.lit(season).alias("season").cast(feats["season"].dtype),
                pl.lit(1).alias("week").cast(feats["week"].dtype),
            ])
        )
        if last.height:
            projections.append(last)
    if not projections:
        return feats

    proj = pl.concat(projections, how="diagonal_relaxed")
    # game_id belongs to the season it came from and must not travel forward.
    if "game_id" in proj.columns:
        proj = proj.drop("game_id")

    # A real row wins over the projection *value by value*, not wholesale.
    #
    # Preferring the whole real row worked for feature families whose week-1
    # rows simply do not exist — opening-drive stats, where only the receiving
    # team has a row. It silently did nothing for families where the week-1 row
    # exists with null values: personnel groupings, box counts and coverage
    # rates are season-to-date, so week 1 is null by construction and the
    # projection was deduped away behind it.
    #
    # The result was the same skew this function exists to remove, inverted:
    # those 17 features were 100% null in week 1 of every season 2015-2025 and
    # 0% null in the predict season, because only the predict season had no
    # week-1 rows to lose the tie-break against. Coalescing fills the nulls
    # instead, so week 1 means one thing everywhere.
    keys = [key_col, "season", "week"]
    value_cols = [c for c in feats.columns if c not in keys]

    existing = feats.join(proj.select(keys), on=keys, how="semi")
    if existing.height:
        filled = feats.join(proj, on=keys, how="left", suffix="_proj")
        filled = filled.with_columns([
            pl.coalesce([pl.col(c), pl.col(f"{c}_proj")]).alias(c)
            for c in value_cols if f"{c}_proj" in filled.columns
        ]).select(feats.columns)
    else:
        filled = feats

    # Whole rows the projection adds that were not there at all.
    missing = proj.join(feats.select(keys), on=keys, how="anti")
    if missing.height == 0:
        return filled
    return pl.concat([filled, missing], how="diagonal_relaxed")


def _carry_forward_player(player_feats: pl.DataFrame, predict_season: int) -> pl.DataFrame:
    return _carry_forward(player_feats, "player_id", predict_season)


def _carry_forward_team(team_feats: pl.DataFrame, predict_season: int,
                        team_col: str) -> pl.DataFrame:
    return _carry_forward(team_feats, team_col, predict_season)


def _load_optional_parquet(name: str) -> pl.DataFrame:
    """Load a parquet file, returning empty DataFrame if missing."""
    path = get_path("raw") / f"{name}.parquet"
    try:
        return pl.read_parquet(path)
    except Exception:
        print(f"  WARNING: {path} not found, skipping {name} features")
        return pl.DataFrame()


def assemble_features() -> pl.DataFrame:
    """Join all features onto candidates. No leakage."""
    cfg = get_config()
    target_type = cfg["target"]["type"]
    predict_season = cfg["seasons"].get("predict_season")

    candidates = pl.read_parquet(get_path("processed", target_type) / "candidates.parquet")
    weekly_stats = pl.read_parquet(get_path("raw") / "weekly_stats.parquet")
    pbp = pl.read_parquet(get_path("raw") / "pbp.parquet")
    schedules = pl.read_parquet(get_path("raw") / "schedules.parquet")
    snap_counts = pl.read_parquet(get_path("raw") / "snap_counts.parquet")
    depth_charts = pl.read_parquet(get_path("raw") / "depth_charts.parquet")
    rosters = pl.read_parquet(get_path("raw") / "rosters.parquet")

    # New raw data (optional — may not exist if ingest hasn't been re-run)
    ngs_receiving = _load_optional_parquet("ngs_receiving")
    ngs_rushing = _load_optional_parquet("ngs_rushing")
    injuries = _load_optional_parquet("injuries")

    print("Building features...")

    # Dense player-week spine. Usage frames are sparse — a row exists only for
    # weeks a player actually had that usage — so joining them raw makes
    # "feature is not null" mean "this player had a goal-line touch in the game
    # we're predicting". Densifying against the candidate pool (roster + schedule,
    # both known pre-kickoff) makes absence a real zero. See src/features/spine.py.
    spine = player_week_spine(candidates)
    print(f"  Player-week spine: {spine.height:,} rows")

    # === Core features ===
    player_feats = build_player_rolling_features(weekly_stats, spine)
    team_feats = build_team_features(pbp)
    opp_feats = build_opponent_features(pbp)


    game_feats = build_game_features(schedules)

    snap_feats = build_snap_features(snap_counts, rosters)
    snap_feats = snap_feats.with_columns((pl.col("week") + 1).alias("week"))

    dc_feats = build_depth_chart_features(depth_charts)

    # Load new-format depth charts for 2025+ if available
    dc_new_path = get_path("raw") / "depth_charts_new.parquet"
    try:
        dc_new = pl.read_parquet(dc_new_path)
        if not dc_new.is_empty():
            from src.features.context_features import _build_dc_new_format
            dc_new_feats = _build_dc_new_format(dc_new)
            dc_feats = pl.concat([dc_feats, dc_new_feats], how="diagonal_relaxed")
            dc_feats = dc_feats.unique(subset=["player_id", "season", "week"], keep="last")
            print(f"  Depth charts (combined): {dc_feats.shape}")
    except Exception:
        pass

    # === Target-specific features ===
    player_ftd_feats = build_player_target_history(target_type)
    team_ftd_feats = build_team_target_tendency(target_type)
    print(f"  Target player features: {player_ftd_feats.shape}")
    print(f"  Target team features: {team_ftd_feats.shape}")

    # === Red zone features ===
    player_rz_feats = build_player_redzone_features(pbp, spine)
    team_rz_feats = build_team_redzone_features(pbp)
    print(f"  Red zone player features: {player_rz_feats.shape}")
    print(f"  Red zone team features: {team_rz_feats.shape}")

    # === Opponent position-specific features ===
    opp_pos_feats = build_opponent_position_features(pbp, rosters)
    print(f"  Opponent position features: {opp_pos_feats.shape}")

    # === Vegas & environment features ===
    vegas_feats = build_vegas_features(schedules, pbp)
    print(f"  Vegas features: {vegas_feats.shape}")

    # === Game context features from schedules ===
    game_context_feats = _build_game_context_features(schedules)
    print(f"  Game context features: {game_context_feats.shape}")

    # === Player share features ===
    player_share_feats = build_player_share_features(weekly_stats, spine)
    print(f"  Player share features: {player_share_feats.shape}")

    # === Goal line features ===
    goalline_feats = build_goalline_features(pbp, spine)
    print(f"  Goal line features: {goalline_feats.shape}")

    # === Opening drive features ===
    od_team_feats, od_player_feats = build_opening_drive_features(pbp, spine)
    print(f"  Opening drive team features: {od_team_feats.shape}")
    print(f"  Opening drive player features: {od_player_feats.shape}")

    # === First-half features ===
    h1_feats = build_first_half_features(pbp, spine)
    print(f"  First-half features: {h1_feats.shape}")

    # === QB features ===
    qb_feats = build_qb_features(pbp)
    print(f"  QB features: {qb_feats.shape}")

    # === NEW Round 2: TD proxy features ===
    td_proxy_feats = build_td_proxy_features(schedules)
    print(f"  TD proxy features: {td_proxy_feats.shape}")

    # === NEW Round 2: Receiver profile features (NGS) ===
    receiver_feats = build_receiver_features(ngs_receiving)
    print(f"  Receiver features: {receiver_feats.shape}")

    # === NEW Round 2: Rushing efficiency features (NGS) ===
    rushing_eff_feats = build_rushing_efficiency_features(ngs_rushing)
    print(f"  Rushing efficiency features: {rushing_eff_feats.shape}")

    # === NEW Round 2: Injury features ===
    injury_player_feats, injury_team_feats = build_injury_features(injuries, depth_charts)
    print(f"  Injury player features: {injury_player_feats.shape}")
    print(f"  Injury team features: {injury_team_feats.shape}")

    # === NEW Round 2: Pace features ===
    pace_feats = build_pace_features(pbp)
    print(f"  Pace features: {pace_feats.shape}")


    # === NEW Round 2: Score-first features ===
    score_first_feats = build_score_first_features(schedules)
    print(f"  Score-first features: {score_first_feats.shape}")

    # === NEW Round 2: TD streak features ===
    td_streak_feats = build_td_streak_features(weekly_stats)
    print(f"  TD streak features: {td_streak_feats.shape}")

    # === NEW Round 2: Opponent target features ===
    opp_ftd_feats = build_opp_target_features(target_type)
    print(f"  Opponent target features: {opp_ftd_feats.shape}")

    # === NEW Round 2: Coach features ===
    coach_feats = build_coach_features(schedules, pbp, target_type)
    print(f"  Coach features: {coach_feats.shape}")

    # === OC features ===
    # TODO(oc-features): disabled — requires hand-maintained data/raw/oc_mapping.csv
    # (season, team, oc_name). Re-enable once that mapping is derived dynamically.
    # oc_feats = build_oc_features(schedules, pbp, target_type)
    # print(f"  OC features: {oc_feats.shape}")

    # === Sportsbook TD prop features ===
    odds_feats = build_odds_features(schedules)
    if not odds_feats.is_empty():
        print(f"  Sportsbook odds features: {odds_feats.shape}")
    else:
        print("  Sportsbook odds features: none (no cached odds data)")

    # === Situational features ===
    sit_player_feats, sit_game_feats = build_situational_features(
        rosters, schedules, depth_charts, weekly_stats,
    )
    print(f"  Situational player features: {sit_player_feats.shape}")
    print(f"  Situational game features: {sit_game_feats.shape}")

    # === Coverage features (man/zone opponent tendency) ===
    coverage_feats = build_coverage_features(pbp)
    print(f"  Coverage features: {coverage_feats.shape}")

    # === Momentum features (touch share trend) ===
    momentum_feats = build_momentum_features(weekly_stats)
    print(f"  Momentum features: {momentum_feats.shape}")

    # === Personnel grouping features (11/12/21/heavy rates) ===
    personnel_feats = build_personnel_features(pbp)
    print(f"  Personnel features: {personnel_feats.shape}")

    # === Box count features (stacked/light box opponent tendency) ===
    box_feats = build_box_features(pbp)
    print(f"  Box count features: {box_feats.shape}")

    # === Carry forward into week 1 of every season, predict season included ===
    # Gated on predict_season only because that is the caller's signal that a
    # full build is happening; the projection itself now covers all seasons, so
    # training rows and serving rows are constructed the same way.
    if predict_season:
        player_feats = _carry_forward_player(player_feats, predict_season)
        player_ftd_feats = _carry_forward_player(player_ftd_feats, predict_season)
        player_rz_feats = _carry_forward_player(player_rz_feats, predict_season)
        player_share_feats = _carry_forward_player(player_share_feats, predict_season)
        goalline_feats = _carry_forward_player(goalline_feats, predict_season)
        od_player_feats = _carry_forward_player(od_player_feats, predict_season)
        h1_feats = _carry_forward_player(h1_feats, predict_season)

        # Round 2 player features carry-forward
        if not receiver_feats.is_empty():
            receiver_feats = _carry_forward_player(receiver_feats, predict_season)
        if not rushing_eff_feats.is_empty():
            rushing_eff_feats = _carry_forward_player(rushing_eff_feats, predict_season)
        if not td_streak_feats.is_empty():
            td_streak_feats = _carry_forward_player(td_streak_feats, predict_season)
        # NOTE: sit_player_feats and sit_game_feats do NOT need carry-forward.
        # They're built from rosters/schedules which already include the predict season,
        # and carry-forward would overwrite correct 2026 values with stale 2025 values.

        momentum_feats = _carry_forward_player(momentum_feats, predict_season)
        coverage_feats = _carry_forward_team(coverage_feats, predict_season, "opponent")
        personnel_feats = _carry_forward_team(personnel_feats, predict_season, "team")
        box_feats = _carry_forward_team(box_feats, predict_season, "opponent")

        team_feats = _carry_forward_team(team_feats, predict_season, "team")
        opp_feats = _carry_forward_team(opp_feats, predict_season, "opponent")
        team_ftd_feats = _carry_forward_team(team_ftd_feats, predict_season, "team")
        team_rz_feats = _carry_forward_team(team_rz_feats, predict_season, "team")
        opp_pos_feats = _carry_forward_team(opp_pos_feats, predict_season, "opponent")
        od_team_feats = _carry_forward_team(od_team_feats, predict_season, "team")
        qb_feats = _carry_forward_team(qb_feats, predict_season, "team")

        # Round 2 team features carry-forward
        pace_feats = _carry_forward_team(pace_feats, predict_season, "team")
        score_first_feats = _carry_forward_team(score_first_feats, predict_season, "team")
        coach_feats = _carry_forward_team(coach_feats, predict_season, "team")
        # TODO(oc-features): re-enable with build_oc_features
        # oc_feats = _carry_forward_team(oc_feats, predict_season, "team")
        opp_ftd_feats = _carry_forward_team(opp_ftd_feats, predict_season, "opponent")
        # Vegas/td_proxy: no carry-forward needed (comes from schedules, available for predict season)

        # Carry forward snaps — but override with depth chart for predict season
        # Raw carry-forward: last known snap_pct from prior season
        last_snaps = (
            snap_feats.filter(pl.col("season") == predict_season - 1)
            .sort(["player_id", "week"]).group_by("player_id").last()
            .with_columns([
                pl.lit(predict_season).alias("season").cast(snap_feats["season"].dtype),
                pl.lit(1).alias("week").cast(snap_feats["week"].dtype),
            ])
        )

        # Use the predict-season depth chart to correct stale snap_pct for
        # players whose role changed — but only where the chart actually has an
        # opinion. Absence from the chart is missing data, not evidence that a
        # player won't play: the previous version zeroed anyone not among the
        # ~144 listed starters, which wiped snap_pct for ~1,600 players
        # including genuine starters, and snap_pct is a top-10 feature.
        dc_pred = dc_feats.filter(pl.col("season") == predict_season)
        dc_starters = dc_pred.filter(pl.col("is_starter") == 1).select("player_id").unique()
        dc_listed = dc_pred.select("player_id").unique()

        # The depth chart may only CONFIRM a starter, never zero anyone out.
        # "Listed below rank 1" is not evidence of no playing time — a WR2 or RB2
        # plays most snaps — and "absent from the chart" is missing data, not a
        # benching. The old version zeroed everyone not among the ~145 listed
        # rank-1 players, wiping snap_pct (a top-10 feature) for ~1,600 players
        # including genuine starters like Xavier Worthy, which is what produced
        # the huge phantom fades against the market in Week 1.
        kept = last_snaps.filter(pl.col("snap_pct") > 0).height
        print(f"  Snap carry-forward: {last_snaps.height} players, "
              f"{kept} with non-zero snap_pct "
              f"({dc_starters.height} confirmed by the {predict_season} depth chart, "
              f"{dc_listed.height} listed)")
        if dc_listed.height < 300:
            print(f"    NOTE: only {dc_listed.height} players on the {predict_season} "
                  f"depth chart — too sparse to judge roles, so carried-forward "
                  f"snap_pct stands. Re-run `make ingest` closer to kickoff.")

        snap_feats = pl.concat([snap_feats, last_snaps], how="diagonal_relaxed")

    # === Deduplicate all feature tables to prevent fan-out ===
    player_feats = player_feats.unique(subset=["player_id", "season", "week"], keep="last")
    player_ftd_feats = player_ftd_feats.unique(subset=["player_id", "season", "week"], keep="last")
    player_rz_feats = player_rz_feats.unique(subset=["player_id", "season", "week"], keep="last")
    player_share_feats = player_share_feats.unique(subset=["player_id", "season", "week"], keep="last")
    goalline_feats = goalline_feats.unique(subset=["player_id", "season", "week"], keep="last")
    od_player_feats = od_player_feats.unique(subset=["player_id", "season", "week"], keep="last")
    h1_feats = h1_feats.unique(subset=["player_id", "season", "week"], keep="last")
    team_feats = team_feats.unique(subset=["season", "week", "team"], keep="last")
    team_ftd_feats = team_ftd_feats.unique(subset=["season", "week", "team"], keep="last")
    team_rz_feats = team_rz_feats.unique(subset=["season", "week", "team"], keep="last")
    od_team_feats = od_team_feats.unique(subset=["season", "week", "team"], keep="last")
    qb_feats = qb_feats.unique(subset=["season", "week", "team"], keep="last")
    opp_feats = opp_feats.unique(subset=["season", "week", "opponent"], keep="last")
    opp_pos_feats = opp_pos_feats.unique(subset=["season", "week", "opponent"], keep="last")
    snap_feats = snap_feats.unique(subset=["player_id", "season", "week"], keep="last")
    vegas_feats = vegas_feats.unique(subset=["game_id", "team"], keep="last")
    game_context_feats = game_context_feats.unique(subset=["game_id", "team"], keep="last")

    # Round 2 dedup
    if not receiver_feats.is_empty():
        receiver_feats = receiver_feats.unique(subset=["player_id", "season", "week"], keep="last")
    if not rushing_eff_feats.is_empty():
        rushing_eff_feats = rushing_eff_feats.unique(subset=["player_id", "season", "week"], keep="last")
    if not injury_player_feats.is_empty():
        injury_player_feats = injury_player_feats.unique(subset=["player_id", "season", "week"], keep="last")
    if not injury_team_feats.is_empty():
        injury_team_feats = injury_team_feats.unique(subset=["player_id", "season", "week"], keep="last")
    if not td_streak_feats.is_empty():
        td_streak_feats = td_streak_feats.unique(subset=["player_id", "season", "week"], keep="last")
    td_proxy_feats = td_proxy_feats.unique(subset=["game_id", "team"], keep="last")
    pace_feats = pace_feats.unique(subset=["season", "week", "team"], keep="last")
    score_first_feats = score_first_feats.unique(subset=["season", "week", "team"], keep="last")
    coach_feats = coach_feats.unique(subset=["season", "week", "team"], keep="last")
    # TODO(oc-features): re-enable with build_oc_features
    # oc_feats = oc_feats.unique(subset=["season", "week", "team"], keep="last")
    opp_ftd_feats = opp_ftd_feats.unique(subset=["season", "week", "opponent"], keep="last")
    sit_player_feats = sit_player_feats.unique(subset=["player_id", "season", "week"], keep="last")
    sit_game_feats = sit_game_feats.unique(subset=["game_id", "team"], keep="last")
    momentum_feats = momentum_feats.unique(subset=["player_id", "season", "week"], keep="last")
    if not coverage_feats.is_empty():
        coverage_feats = coverage_feats.unique(subset=["season", "week", "opponent"], keep="last")
    if not personnel_feats.is_empty():
        personnel_feats = personnel_feats.unique(subset=["season", "week", "team"], keep="last")
    if not box_feats.is_empty():
        box_feats = box_feats.unique(subset=["season", "week", "opponent"], keep="last")

    # === Assemble ===
    df = candidates.clone()

    # Player rolling stats
    df = df.join(player_feats, on=["player_id", "season", "week"], how="left")

    # Player first TD features
    df = df.join(player_ftd_feats, on=["player_id", "season", "week"], how="left")

    # Player red zone features
    df = df.join(player_rz_feats, on=["player_id", "season", "week"], how="left")

    # Player share features
    df = df.join(player_share_feats, on=["player_id", "season", "week"], how="left")

    # Goal line features
    df = df.join(goalline_feats, on=["player_id", "season", "week"], how="left")

    # Opening drive player features
    df = df.join(od_player_feats, on=["player_id", "season", "week"], how="left")

    # First-half features
    df = df.join(h1_feats, on=["player_id", "season", "week"], how="left")

    # Round 2: Receiver features (NGS)
    if not receiver_feats.is_empty():
        df = df.join(receiver_feats, on=["player_id", "season", "week"], how="left")

    # Round 2: Rushing efficiency features (NGS)
    if not rushing_eff_feats.is_empty():
        df = df.join(rushing_eff_feats, on=["player_id", "season", "week"], how="left")

    # Round 2: Injury player features
    if not injury_player_feats.is_empty():
        df = df.join(injury_player_feats, on=["player_id", "season", "week"], how="left")

    # Round 2: Injury team features (teammate boost)
    if not injury_team_feats.is_empty():
        df = df.join(injury_team_feats, on=["player_id", "season", "week"], how="left")

    # Round 2: TD streak features
    if not td_streak_feats.is_empty():
        df = df.join(td_streak_feats, on=["player_id", "season", "week"], how="left")

    # Situational player features
    df = df.join(sit_player_feats, on=["player_id", "season", "week"], how="left")

    # Momentum features (touch share trend)
    df = df.join(momentum_feats, on=["player_id", "season", "week"], how="left")

    # Team offensive stats
    df = df.join(
        team_feats, on=["season", "week", "team"], how="left", suffix="_tf",
    )
    if "game_id_tf" in df.columns:
        df = df.drop("game_id_tf")

    # Team first TD tendency
    df = df.join(
        team_ftd_feats, on=["season", "week", "team"], how="left", suffix="_ftd",
    )
    if "game_id_ftd" in df.columns:
        df = df.drop("game_id_ftd")

    # Team red zone stats
    df = df.join(team_rz_feats, on=["season", "week", "team"], how="left")

    # Opening drive team features
    df = df.join(
        od_team_feats, on=["season", "week", "team"], how="left", suffix="_od",
    )
    if "game_id_od" in df.columns:
        df = df.drop("game_id_od")

    # QB features
    df = df.join(
        qb_feats, on=["season", "week", "team"], how="left", suffix="_qb",
    )
    if "game_id_qb" in df.columns:
        df = df.drop("game_id_qb")

    # Round 2: Pace features
    df = df.join(pace_feats, on=["season", "week", "team"], how="left")

    # Round 2: Score-first features
    df = df.join(score_first_feats, on=["season", "week", "team"], how="left")

    # Round 2: Coach features
    df = df.join(coach_feats, on=["season", "week", "team"], how="left")

    # OC features
    # TODO(oc-features): re-enable with build_oc_features
    # df = df.join(oc_feats, on=["season", "week", "team"], how="left")

    # Vegas & environment features
    df = df.join(vegas_feats, on=["game_id", "team"], how="left")

    # Game context features (dome, divisional, surface)
    df = df.join(game_context_feats, on=["game_id", "team"], how="left")

    # Situational game features (rest advantage, post-bye, season opener)
    df = df.join(sit_game_feats, on=["game_id", "team"], how="left")

    # Round 2: TD proxy features (moneyline)
    df = df.join(td_proxy_feats, on=["game_id", "team"], how="left", suffix="_tdp")
    # Drop duplicate season/week cols if created
    for col in ["season_tdp", "week_tdp"]:
        if col in df.columns:
            df = df.drop(col)

    # Game context (is_home, opponent, primetime, divisional)
    df = df.join(
        game_feats.select(["game_id", "team", "opponent",
                           "is_home", "is_primetime", "is_divisional"]),
        on=["game_id", "team"], how="left", suffix="_gf",
    )
    if "is_home_gf" in df.columns:
        df = df.drop("is_home").rename({"is_home_gf": "is_home"})

    # Opponent defensive stats
    df = df.join(opp_feats, left_on=["season", "week", "opponent"],
                 right_on=["season", "week", "opponent"], how="left")

    # Opponent position-specific TD features
    df = df.join(opp_pos_feats, on=["season", "week", "opponent"], how="left")

    # Round 2: Opponent first-TD features
    df = df.join(opp_ftd_feats, on=["season", "week", "opponent"], how="left")

    # Coverage features (opponent man/zone tendency)
    if not coverage_feats.is_empty():
        df = df.join(coverage_feats, on=["season", "week", "opponent"], how="left")

    # Personnel features (team offensive personnel grouping rates)
    if not personnel_feats.is_empty():
        df = df.join(personnel_feats, on=["season", "week", "team"], how="left")

    # Box count features (opponent defensive box tendency)
    if not box_feats.is_empty():
        df = df.join(box_feats, on=["season", "week", "opponent"], how="left")

    # Snap counts
    df = df.join(snap_feats, left_on=["player_id", "season", "week", "team"],
                 right_on=["player_id", "season", "week", "team"], how="left")

    # Depth chart
    df = df.join(dc_feats, left_on=["player_id", "season", "week", "team"],
                 right_on=["player_id", "season", "week", "team"], how="left")

    # === Depth chart rank from new-format depth charts ===
    try:
        dc_new_raw = pl.read_parquet(get_path("raw") / "depth_charts_new.parquet")
    except Exception:
        dc_new_raw = pl.DataFrame()
    if not dc_new_raw.is_empty():
        skill_positions = {"RB", "WR", "TE", "QB", "FB"}
        dc_rank = (
            dc_new_raw
            .filter(pl.col("pos_abb").is_in(skill_positions))
            .filter(pl.col("gsis_id").is_not_null())
            .with_columns(
                pl.col("dt").str.slice(0, 10).str.to_date("%Y-%m-%d").alias("_dt_date")
            )
            .with_columns(
                # Match context_features.py: month >= 3 = current year's season
                # (offseason depth charts from March-August represent upcoming season)
                pl.when(pl.col("_dt_date").dt.month() >= 3)
                .then(pl.col("_dt_date").dt.year())
                .otherwise(pl.col("_dt_date").dt.year() - 1)
                .cast(pl.Int64)
                .alias("season")
            )
            .group_by(["gsis_id", "team", "season"])
            .agg(pl.col("pos_rank").min().alias("depth_chart_rank"))
        )
        df = df.join(
            dc_rank,
            left_on=["player_id", "team", "season"],
            right_on=["gsis_id", "team", "season"],
            how="left",
        )
        print(f"  Depth chart rank: {dc_rank.shape[0]:,} player-team-seasons, "
              f"non-null in candidates: {df['depth_chart_rank'].is_not_null().sum():,}/{df.shape[0]:,}")

    # One-hot encode position
    if "position" in df.columns:
        # Save position before dummifying for WR derivation
        df = df.with_columns(pl.col("position").alias("_position_raw"))
        df = df.with_columns(pl.col("position").cast(pl.Categorical))
        df = df.to_dummies(columns=["position"], drop_first=True)
        # Derive _is_wr from original position (drop_first drops DEFST, not WR)
        df = df.with_columns(
            (pl.col("_position_raw") == "WR").cast(pl.Int8).alias("_is_wr")
        )
        df = df.drop("_position_raw")

    # Week as numeric
    df = df.with_columns(pl.col("week").cast(pl.Float64).alias("week_num"))

    # === Usage tier features: sharper starter/backup differentiation ===
    # These fill nulls with 0 so low-usage players get penalized
    if "player_carries_avg_5g" in df.columns and "player_targets_avg_5g" in df.columns:
        total_touches = (
            pl.col("player_carries_avg_5g").fill_null(0)
            + pl.col("player_targets_avg_5g").fill_null(0)
        )
        df = df.with_columns([
            total_touches.alias("total_touches_avg"),
            (total_touches > 10).cast(pl.Int8).alias("is_high_usage"),
            (total_touches > 5).cast(pl.Int8).alias("is_med_usage"),
            (total_touches == 0).cast(pl.Int8).alias("is_zero_usage"),
        ])

    # Snap pct with null -> 0 (unknown snap = likely low usage)
    if "snap_pct" in df.columns:
        df = df.with_columns([
            pl.col("snap_pct").fill_null(0.0).alias("snap_pct_filled"),
            (pl.col("snap_pct").fill_null(0.0) > 0.5).cast(pl.Int8).alias("is_high_snap"),
        ])

    # TD scorer history: has this player ever scored a TD?
    if "player_target_count" in df.columns:
        df = df.with_columns([
            (pl.col("player_target_count").fill_null(0) > 0).cast(pl.Int8).alias("has_scored_td"),
        ])

    # Recent TD scoring rate (non-null indicator)
    if "player_total_tds_avg_5g" in df.columns:
        df = df.with_columns([
            pl.col("player_total_tds_avg_5g").fill_null(0.0).alias("recent_td_rate"),
        ])

    # === Sportsbook odds features (join by game_id + normalized player name) ===
    if not odds_feats.is_empty() and "player_name" in df.columns:
        from src.features.odds_features import _normalize_name as _odds_norm
        df = df.with_columns(
            pl.col("player_name").map_elements(_odds_norm, return_dtype=pl.Utf8)
            .alias("_player_name_norm")
        )
        df = df.join(
            odds_feats,
            left_on=["game_id", "_player_name_norm"],
            right_on=["game_id", "player_name_norm"],
            how="left",
        )
        df = df.drop("_player_name_norm")

    # === Interaction features (after all joins) ===
    df = build_interaction_features(df)

    # === Round 2: Matchup interaction features ===
    df = build_matchup_interaction_features(df)

    # === Round 2: TD proxy interaction (needs both vegas + player share joined) ===
    if "implied_team_total" in df.columns and "player_td_market_share_szn_avg" in df.columns:
        df = df.with_columns(
            ((pl.col("implied_team_total").fill_null(0) / 7)
             * pl.col("player_td_market_share_szn_avg").fill_null(0))
            .alias("implied_player_tds")
        )
    if "moneyline_implied_prob" in df.columns and "player_td_market_share_szn_avg" in df.columns:
        df = df.with_columns(
            (pl.col("moneyline_implied_prob").fill_null(0)
             * pl.col("player_td_market_share_szn_avg").fill_null(0))
            .alias("win_prob_x_td_share")
        )

    # Drop helper columns not meant as features
    if "_is_wr" in df.columns:
        df = df.drop("_is_wr")

    path = get_path("processed", target_type) / "features.parquet"
    df.write_parquet(path)

    print(f"\nFinal feature set: {df.shape[0]:,} rows x {df.shape[1]} columns -> {path}")

    # Coverage check for predict season
    if predict_season:
        pred = df.filter(pl.col("season") == predict_season)
        if pred.shape[0] > 0:
            player_cols = [c for c in df.columns if c.startswith("player_") and "_avg_" in c][:3]
            if player_cols:
                non_null = pred.select([pl.col(c).is_not_null().mean().alias(c) for c in player_cols])
                print(f"  {predict_season} candidates: {pred.shape[0]:,}, feature coverage: {non_null}")

    return df
