"""Injury/availability features from NFL injury reports."""
import polars as pl


def build_injury_features(
    injuries: pl.DataFrame,
    starters: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Build player-level and team-context injury features.

    `starters` is the normalised frame from
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
        # The Wed/Thu/Fri practice report, which this builder ignored until
        # 2026-09-21 while reading only the game-status column beside it.
        #
        # It is the denser of the two by a long way: `practice_status` is set
        # on 61,175 of 61,221 rows and `report_status` on 32,055 — so **29,163
        # rows carry a practice report and no game status at all**, and every
        # one of them is currently invisible to the model. 2,949 of those are
        # "Did Not Participate" and 3,560 "Limited", which is a real injury
        # signal reaching the matrix as nothing.
        #
        # It also discriminates INSIDE a status. "Questionable" covers 3,195
        # player-weeks who practised fully and 2,581 who did not practise at
        # all; today those are the same number to the model.
        (pl.col("practice_status").cast(pl.Utf8).str.strip_chars()
         if "practice_status" in injuries.columns
         else pl.lit(None, dtype=pl.Utf8)).alias("practice_status"),
    ]).filter(pl.col("player_id").is_not_null())

    # --- Player-level injury status ---
    # Three indicators rather than one ordinal: the gap between full and
    # limited is not the gap between limited and DNP, and a tree should not be
    # told it is. All three are 0 where a practice report exists and says
    # otherwise, and null where none exists — never zero-filled here, because
    # on a sparse frame "no report" and "practised fully" are opposite claims
    # and `prepare_data` will collapse them if this builder does it first.
    dnp = pl.col("practice_status").str.starts_with("Did Not Participate")
    lim = pl.col("practice_status").str.starts_with("Limited Participation")
    full = pl.col("practice_status").str.starts_with("Full Participation")
    known = pl.col("practice_status").is_not_null() & (dnp | lim | full)
    player_inj = inj.with_columns([
        (pl.col("report_status") == "Out").cast(pl.Float64).alias("is_out"),
        pl.col("report_status").is_in(["Questionable", "Doubtful"]).cast(pl.Float64).alias("is_questionable"),
        pl.when(known).then(dnp.cast(pl.Float64)).alias("practice_dnp"),
        pl.when(known).then(lim.cast(pl.Float64)).alias("practice_limited"),
        pl.when(known).then(full.cast(pl.Float64)).alias("practice_full"),
    ]).select(["player_id", "season", "week", "team", "position", "is_out",
               "is_questionable", "practice_dnp", "practice_limited",
               "practice_full"])

    # Deduplicate (player may appear multiple times per week)
    player_inj = player_inj.unique(subset=["player_id", "season", "week"], keep="last")

    # Player-level output
    player_feats = player_inj.select(["player_id", "season", "week", "is_out",
                                      "is_questionable", "practice_dnp",
                                      "practice_limited", "practice_full"])

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
