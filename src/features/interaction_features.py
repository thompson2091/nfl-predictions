"""Interaction features: cross-feature products computed after all joins."""
import polars as pl


def build_interaction_features(df: pl.DataFrame) -> pl.DataFrame:
    """Add interaction features to assembled dataframe. Call AFTER all joins."""

    interactions = []

    # implied_team_total x goalline_carry_share
    if "implied_team_total" in df.columns and "player_i5_touch_share_szn_avg" in df.columns:
        interactions.append(
            (pl.col("implied_team_total").fill_null(0) * pl.col("player_i5_touch_share_szn_avg").fill_null(0))
            .alias("ix_itt_x_gl_share")
        )

    # implied_team_total x target_share
    if "implied_team_total" in df.columns and "player_target_share_szn_avg" in df.columns:
        interactions.append(
            (pl.col("implied_team_total").fill_null(0) * pl.col("player_target_share_szn_avg").fill_null(0))
            .alias("ix_itt_x_tgt_share")
        )

    # is_big_favorite x rush_share
    if "is_big_favorite" in df.columns and "player_rush_share_szn_avg" in df.columns:
        interactions.append(
            (pl.col("is_big_favorite").fill_null(0) * pl.col("player_rush_share_szn_avg").fill_null(0))
            .alias("ix_fav_x_rush_share")
        )

    # is_windy x position_RB
    if "is_windy" in df.columns and "position_RB" in df.columns:
        interactions.append(
            (pl.col("is_windy").fill_null(0) * pl.col("position_RB").fill_null(0))
            .alias("ix_windy_x_rb")
        )

    # opp rz defense x rz opportunity share
    if "opp_tds_allowed_szn_avg" in df.columns and "player_rz_touches_szn_avg" in df.columns:
        interactions.append(
            (pl.col("opp_tds_allowed_szn_avg").fill_null(0) * pl.col("player_rz_touches_szn_avg").fill_null(0))
            .alias("ix_opp_def_x_rz_share")
        )

    # opening_drive_td_rate x opening_drive_touch_share
    if "team_opening_drive_td_rate_szn_avg" in df.columns and "player_od_touch_share_szn_avg" in df.columns:
        interactions.append(
            (pl.col("team_opening_drive_td_rate_szn_avg").fill_null(0)
             * pl.col("player_od_touch_share_szn_avg").fill_null(0))
            .alias("ix_od_td_x_od_share")
        )

    # === Position-conditional interactions ===
    # These let the model learn position-specific matchup signals

    # RB: rush_share x opp rush TDs allowed (only matters for RBs)
    if all(c in df.columns for c in ["position_RB", "player_rush_share_szn_avg", "opp_tds_allowed_to_rb_szn_avg"]):
        interactions.append(
            (pl.col("position_RB").fill_null(0)
             * pl.col("player_rush_share_szn_avg").fill_null(0)
             * pl.col("opp_tds_allowed_to_rb_szn_avg").fill_null(0))
            .alias("ix_rb_rush_x_opp_rb_td")
        )

    # WR: target_share x opp WR TDs allowed
    if all(c in df.columns for c in ["_is_wr", "player_target_share_szn_avg", "opp_tds_allowed_to_wr_szn_avg"]):
        interactions.append(
            (pl.col("_is_wr").fill_null(0)
             * pl.col("player_target_share_szn_avg").fill_null(0)
             * pl.col("opp_tds_allowed_to_wr_szn_avg").fill_null(0))
            .alias("ix_wr_tgt_x_opp_wr_td")
        )

    # TE: target_share x opp TE TDs allowed
    if all(c in df.columns for c in ["position_TE", "player_target_share_szn_avg", "opp_tds_allowed_to_te_szn_avg"]):
        interactions.append(
            (pl.col("position_TE").fill_null(0)
             * pl.col("player_target_share_szn_avg").fill_null(0)
             * pl.col("opp_tds_allowed_to_te_szn_avg").fill_null(0))
            .alias("ix_te_tgt_x_opp_te_td")
        )

    # RB: rz_carries x opp first-TD-allowed-to-RB rate
    if all(c in df.columns for c in ["position_RB", "player_rz_carries_szn_avg", "opp_target_allowed_to_rb_szn_avg"]):
        interactions.append(
            (pl.col("position_RB").fill_null(0)
             * pl.col("player_rz_carries_szn_avg").fill_null(0)
             * pl.col("opp_target_allowed_to_rb_szn_avg").fill_null(0))
            .alias("ix_rb_rz_x_opp_target_rb")
        )

    # WR: air_yards_share x opp first-TD-allowed-to-WR rate
    if all(c in df.columns for c in ["_is_wr", "player_air_yards_share_szn_avg", "opp_target_allowed_to_wr_szn_avg"]):
        interactions.append(
            (pl.col("_is_wr").fill_null(0)
             * pl.col("player_air_yards_share_szn_avg").fill_null(0)
             * pl.col("opp_target_allowed_to_wr_szn_avg").fill_null(0))
            .alias("ix_wr_air_x_opp_target_wr")
        )

    # TE: rz_targets x opp first-TD-allowed-to-TE rate
    if all(c in df.columns for c in ["position_TE", "player_rz_targets_szn_avg", "opp_target_allowed_to_te_szn_avg"]):
        interactions.append(
            (pl.col("position_TE").fill_null(0)
             * pl.col("player_rz_targets_szn_avg").fill_null(0)
             * pl.col("opp_target_allowed_to_te_szn_avg").fill_null(0))
            .alias("ix_te_rz_x_opp_target_te")
        )

    # === Tiebreaker features: differentiate within top clusters ===

    # TD momentum: recent TD rate x first TD rate (compound hot-hand signal)
    if "player_total_tds_avg_3g" in df.columns and "player_target_rate_3g" in df.columns:
        interactions.append(
            (pl.col("player_total_tds_avg_3g").fill_null(0)
             * pl.col("player_target_rate_3g").fill_null(0))
            .alias("ix_td_momentum")
        )

    # Usage concentration: carries + targets relative to team (high-volume player signal)
    if "player_carries_szn_avg" in df.columns and "player_targets_szn_avg" in df.columns:
        interactions.append(
            (pl.col("player_carries_szn_avg").fill_null(0) + pl.col("player_targets_szn_avg").fill_null(0))
            .alias("ix_total_usage")
        )

    # Implied opportunity: implied_team_total x (rush_share + target_share) — total expected involvement
    if all(c in df.columns for c in ["implied_team_total", "player_rush_share_szn_avg", "player_target_share_szn_avg"]):
        interactions.append(
            (pl.col("implied_team_total").fill_null(0)
             * (pl.col("player_rush_share_szn_avg").fill_null(0)
                + pl.col("player_target_share_szn_avg").fill_null(0)))
            .alias("ix_itt_x_total_share")
        )

    # First-half dominance x team scores first rate
    if "player_h1_touch_share_szn_avg" in df.columns and "team_team_scored_first_rate_szn" in df.columns:
        interactions.append(
            (pl.col("player_h1_touch_share_szn_avg").fill_null(0)
             * pl.col("team_team_scored_first_rate_szn").fill_null(0))
            .alias("ix_h1_share_x_score_first")
        )

    # Coach tendency x position: coach_first_td_rush_rate x position_RB
    if "coach_target_td_rush_rate_szn_avg" in df.columns and "position_RB" in df.columns:
        interactions.append(
            (pl.col("coach_target_td_rush_rate_szn_avg").fill_null(0)
             * pl.col("position_RB").fill_null(0))
            .alias("ix_coach_rush_x_rb")
        )

    # Coach tendency x position: coach_first_td_pass_rate x (WR + TE)
    if "coach_target_td_pass_rate_szn_avg" in df.columns:
        for pos in ["WR", "TE"]:
            pos_col = f"position_{pos}"
            if pos_col in df.columns:
                interactions.append(
                    (pl.col("coach_target_td_pass_rate_szn_avg").fill_null(0)
                     * pl.col(pos_col).fill_null(0))
                    .alias(f"ix_coach_pass_x_{pos.lower()}")
                )

    # NGS separation x target share (WR/TE differentiation)
    if "ngs_avg_separation_szn_avg" in df.columns and "player_target_share_szn_avg" in df.columns:
        interactions.append(
            (pl.col("ngs_avg_separation_szn_avg").fill_null(0)
             * pl.col("player_target_share_szn_avg").fill_null(0))
            .alias("ix_separation_x_tgt_share")
        )

    # Rushing efficiency x goal line carries (RB differentiation)
    if "ngs_efficiency_szn_avg" in df.columns and "player_gl_carries_szn_avg" in df.columns:
        interactions.append(
            (pl.col("ngs_efficiency_szn_avg").fill_null(0)
             * pl.col("player_gl_carries_szn_avg").fill_null(0))
            .alias("ix_rush_eff_x_gl_carries")
        )

    # Teammate out boost x snap_pct (backup getting opportunity)
    if "teammate_out_boost" in df.columns and "snap_pct" in df.columns:
        interactions.append(
            (pl.col("teammate_out_boost").fill_null(0)
             * pl.col("snap_pct").fill_null(0))
            .alias("ix_teammate_out_x_snap")
        )

    if interactions:
        df = df.with_columns(interactions)

    return df
