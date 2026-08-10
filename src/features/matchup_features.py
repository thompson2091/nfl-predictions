"""Matchup interaction features: computed AFTER all joins in assembler."""
import polars as pl


def build_matchup_interaction_features(df: pl.DataFrame) -> pl.DataFrame:
    """Add matchup-specific interaction features. Call AFTER all joins."""

    interactions = []

    # is_starter x opp_tds_allowed_to_{position}
    for pos in ["rb", "wr", "te"]:
        opp_col = f"opp_tds_allowed_to_{pos}_szn_avg"
        if "is_starter" in df.columns and opp_col in df.columns:
            interactions.append(
                (pl.col("is_starter").fill_null(0) * pl.col(opp_col).fill_null(0))
                .alias(f"ix_starter_x_opp_td_{pos}")
            )

    # snap_pct x opp_tds_allowed_to_{position}
    for pos in ["rb", "wr", "te"]:
        opp_col = f"opp_tds_allowed_to_{pos}_szn_avg"
        if "snap_pct" in df.columns and opp_col in df.columns:
            interactions.append(
                (pl.col("snap_pct").fill_null(0) * pl.col(opp_col).fill_null(0))
                .alias(f"ix_snap_x_opp_td_{pos}")
            )

    # implied_team_total x td_market_share
    if "implied_team_total" in df.columns and "player_td_market_share_szn_avg" in df.columns:
        interactions.append(
            (pl.col("implied_team_total").fill_null(0) * pl.col("player_td_market_share_szn_avg").fill_null(0))
            .alias("ix_itt_x_td_mkt_share")
        )

    # moneyline_implied_prob x rush_share
    if "moneyline_implied_prob" in df.columns and "player_rush_share_szn_avg" in df.columns:
        interactions.append(
            (pl.col("moneyline_implied_prob").fill_null(0) * pl.col("player_rush_share_szn_avg").fill_null(0))
            .alias("ix_ml_prob_x_rush_share")
        )

    if interactions:
        df = df.with_columns(interactions)

    return df
