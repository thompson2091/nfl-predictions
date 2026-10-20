"""Injury/availability features from NFL injury reports."""
import polars as pl


def build_injury_features(
    injuries: pl.DataFrame,
    starters: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Build player-level and team-context injury features.

    `starters` is the normalized frame from
    `src.features.context_features.starter_lookup` — season, week, team,
    position, starter_id — covering both depth-chart formats. It used to be the
    raw old-format depth-chart file, which ends at 2024, so the starter join
    came back empty for 2025+ and `fill_null(0.0)` turned the result into a
    hard zero rather than a missing value.

    Returns:
        player_injury_feats: per player-season-week (is_out, is_questionable)
        team_injury_feats: per player-season-week (teammate/starter out boost)
    """
    if injuries.is_empty():
        empty = pl.DataFrame(schema={
            "player_id": pl.Utf8, "season": pl.Int64, "week": pl.Int64,
        })
        return empty, empty

    # Standardize column types
    inj = injuries.select([
        pl.col("gsis_id").alias("player_id"),
        pl.col("season").cast(pl.Int64),
        pl.col("week").cast(pl.Int64),
        pl.col("team").cast(pl.Utf8),
        pl.col("position").cast(pl.Utf8),
        pl.col("report_status").cast(pl.Utf8),
    ]).filter(pl.col("player_id").is_not_null())

    # --- Player-level injury status ---
    player_inj = inj.with_columns([
        (pl.col("report_status") == "Out").cast(pl.Float64).alias("is_out"),
        pl.col("report_status").is_in(["Questionable", "Doubtful"]).cast(pl.Float64).alias("is_questionable"),
    ]).select(["player_id", "season", "week", "team", "position", "is_out",
               "is_questionable"])

    # Deduplicate (player may appear multiple times per week)
    player_inj = player_inj.unique(subset=["player_id", "season", "week"], keep="last")

    # Player-level output
    player_feats = player_inj.select(["player_id", "season", "week", "is_out", "is_questionable"])

    # --- Teammate out boost: count same-position teammates who are OUT ---
    out_players = player_inj.filter(pl.col("is_out") == 1)

    # Count OUTs per team/position/week
    pos_outs = (
        out_players.group_by(["season", "week", "team", "position"])
        .agg(pl.len().alias("pos_out_count"))
    )

    # For each player, how many same-position teammates are out
    # (subtract 1 if the player themselves is out)
    teammate_boost = (
        player_inj.select(["player_id", "season", "week", "team", "position", "is_out"])
        .join(pos_outs, on=["season", "week", "team", "position"], how="left")
        .with_columns(pl.col("pos_out_count").fill_null(0))
        .with_columns(
            (pl.col("pos_out_count") - pl.col("is_out")).clip(lower_bound=0).alias("teammate_out_boost")
        )
    )

    # --- Starter out at position: is the depth chart #1 at this position OUT? ---
    if starters is not None and not starters.is_empty():
        # Check if starter is OUT
        starter_out = starters.join(
            out_players.select(["player_id", "season", "week"]).rename({"player_id": "starter_id"}),
            on=["starter_id", "season", "week"],
            how="inner",
        ).select(["season", "week", "team", "position"]).unique()
        starter_out = starter_out.with_columns(pl.lit(1.0).alias("starter_out_at_position"))

        # Only fill zeros for team-weeks a depth chart actually covers. Filling
        # everywhere is how this became a constant 0.0 across 2025: "no chart"
        # and "starter is playing" are different facts, and collapsing them
        # taught the model a value the live pipeline can never reproduce.
        covered = starters.select(["season", "week", "team"]).unique().with_columns(
            pl.lit(True).alias("_dc_covered"))

        teammate_boost = (
            teammate_boost
            .join(starter_out, on=["season", "week", "team", "position"], how="left")
            .join(covered, on=["season", "week", "team"], how="left")
            .with_columns(
                pl.when(pl.col("_dc_covered").fill_null(False))
                .then(pl.col("starter_out_at_position").fill_null(0.0))
                .otherwise(None)
                .alias("starter_out_at_position")
            )
            .drop("_dc_covered")
        )
    else:
        teammate_boost = teammate_boost.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("starter_out_at_position")
        )

    team_feats = teammate_boost.select([
        "player_id", "season", "week", "teammate_out_boost", "starter_out_at_position",
    ])

    return player_feats, team_feats


#: The workload columns whose Out holders' shares are summed. Lagged rolling
#: means, so a player's own row never sees the game being predicted.
_VACATED = {"vac_rush_share": "player_rush_share_avg_5g",
            "vac_target_share": "player_target_share_avg_5g"}


def build_vacated_share(df: pl.DataFrame) -> pl.DataFrame:
    """How much of the team's recent work is Out this week, on EVERY row.

    `teammate_out_boost` is a COUNT of same-position teammates out, and it is
    only ever filled for players who are on the injury report themselves —
    so the healthy backup who inherits the carries reads null. On 2024-25,
    when a back projected 30+ rushing yards was Out, the backs who played were
    projected 55 a team-game and gained 90; receivers, 118 against 146.

    These say how much left: the summed recent carry and target share of
    teammates listed Out, team-wide and at the player's own position, with
    his own share taken out if he is the one Out. Zero, not null, where
    nobody is Out: the report is published for every game, and "no one out"
    is a fact rather than a gap.
    """
    need = ["season", "week", "team", "is_out", *_VACATED.values()]
    if not all(c in df.columns for c in need):
        return df
    pos = (pl.when(pl.col("position_RB").fill_null(0) == 1).then(pl.lit("RB"))
           .when(pl.col("position_TE").fill_null(0) == 1).then(pl.lit("TE"))
           .when(pl.col("position_QB").fill_null(0) == 1).then(pl.lit("QB"))
           .when(pl.col("position_FB").fill_null(0) == 1).then(pl.lit("FB"))
           .when(pl.col("position_DEFST").fill_null(0) == 1).then(pl.lit("DEF"))
           .otherwise(pl.lit("WR")))
    if not all(c in df.columns for c in
               ("position_RB", "position_TE", "position_QB", "position_FB",
                "position_DEFST")):
        return df
    d = df.with_columns(pos.alias("_vpos"),
                        (pl.col("is_out").fill_null(0) == 1).alias("_vout"))
    out = d.filter(pl.col("_vout"))
    keys = ["season", "week", "team"]
    team = out.group_by(keys).agg(
        [pl.col(c).fill_null(0).sum().alias(f"_t_{k}") for k, c in _VACATED.items()])
    at_pos = out.group_by(keys + ["_vpos"]).agg(
        [pl.col(c).fill_null(0).sum().alias(f"_p_{k}") for k, c in _VACATED.items()])
    d = d.join(team, on=keys, how="left").join(at_pos, on=keys + ["_vpos"], how="left")
    own = lambda c: pl.when(pl.col("_vout")).then(pl.col(c).fill_null(0)).otherwise(0.0)
    d = d.with_columns(
        [(pl.col(f"_t_{k}").fill_null(0) - own(c)).clip(lower_bound=0).alias(k)
         for k, c in _VACATED.items()]
        + [(pl.col(f"_p_{k}").fill_null(0) - own(c)).clip(lower_bound=0).alias(f"{k}_pos")
           for k, c in _VACATED.items()])
    # THE SHARE HE STANDS TO INHERIT, given directly. A tree learns
    # "vacated x own share" slowly from a signal on 5% of rows; counts alone
    # closed about a third of the gap. Split in proportion to recent share
    # among those left: with 45% of the backs' carries vacated, a back who had
    # 18% of the remaining 55% stands to take 0.18 / 0.55 of it.
    for k, c in _VACATED.items():
        left = (1.0 - pl.col(f"{k}_pos")).clip(lower_bound=0.05)
        d = d.with_columns(
            pl.when(pl.col("_vout")).then(0.0)
              .otherwise(pl.col(f"{k}_pos") * pl.col(c).fill_null(0) / left)
              .alias(f"{k}_inherit"))
    return d.drop([c for c in d.columns if c.startswith(("_t_", "_p_"))]
                  + ["_vpos", "_vout"])
