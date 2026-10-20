"""Opening drive features: team TD rate and player touch share on drive 1."""
import polars as pl
from src.utils.config import get_config
from src.features.spine import densify


def build_opening_drive_features(pbp: pl.DataFrame, spine: pl.DataFrame,
                                 schedules: pl.DataFrame | None = None):
    """Team and player opening-drive features. Returns two DataFrames merged.

    No row may depend on the game it labels — not its values, and not whether
    it exists. The team side used to aggregate drive 1 per (game, posteam) and
    shift within that frame, so a team had a row only in games where it
    RECEIVED the kickoff. Joined to the matrix, the features were null exactly
    when the team kicked off: a same-game fact (audit 2026-10-19: 46% null on
    2024-25, first-TD rate 1.52% on null rows vs 2.24% on present ones, and in
    both TD models).

    So the rates are computed over receiving games, INCLUDING each one, and
    every scheduled team-game reads the latest of them strictly before it.
    A receiving game sees the same games it saw before (the previous receiving
    games), a kicking game now sees them too, and an unplayed game gets its
    value without the carry-forward. `schedules` supplies the team-games;
    without it the frame falls back to the pbp's own (game, team) pairs, which
    serves tests that build from play-by-play alone.
    """
    cfg = get_config()
    medium = cfg["rolling_windows"]["medium"]

    # Filter to first drive of each game
    d1 = pbp.filter(
        (pl.col("fixed_drive") == 1)
        & pl.col("posteam").is_not_null()
    )

    # --- Team-level opening drive stats ---
    team_d1 = (
        d1.group_by(["game_id", "season", "week", "posteam"])
        .agg([
            pl.len().alias("od_plays"),
            pl.col("touchdown").sum().alias("od_tds"),
            (pl.col("touchdown").sum() + pl.col("field_goal_attempt").sum()).clip(upper_bound=1).alias("od_scored"),
        ])
        .rename({"posteam": "team"})
        .with_columns(
            pl.col("od_tds").clip(upper_bound=1).alias("od_td_flag"),
        )
        .sort(["team", "season", "week"])
    )

    # Unshifted: each receiving game's rate INCLUDES itself, and is read only
    # by games strictly after it (the as-of join below).
    team_rolling = []
    for col, name in [("od_td_flag", "opening_drive_td_rate"),
                      ("od_scored", "opening_drive_score_rate"),
                      ("od_plays", "opening_drive_plays_avg")]:
        c = pl.col(col)
        team_rolling.extend([
            c.rolling_mean(medium, min_samples=3).over("team").alias(f"team_{name}_avg_{medium}g"),
            (c.cum_sum().over("team") / c.cum_count().over("team")).alias(f"team_{name}_szn_avg"),
        ])
    names = [e.meta.output_name() for e in team_rolling]
    order = (pl.col("season").cast(pl.Int64) * 100 + pl.col("week").cast(pl.Int64)).alias("_ord")
    measured = (team_d1.with_columns(team_rolling).with_columns(order)
                .select(["team", "_ord"] + names).sort("_ord"))

    if schedules is not None:
        sched = schedules.select("game_id", "season", "week", "home_team", "away_team")
        team_games = pl.concat([
            sched.select("game_id", "season", "week", pl.col("home_team").alias("team")),
            sched.select("game_id", "season", "week", pl.col("away_team").alias("team")),
        ])
    else:
        team_games = team_d1.select("game_id", "season", "week", "team")
        team_games = pl.concat([
            team_games,
            pbp.filter(pl.col("defteam").is_not_null())
               .select("game_id", "season", "week", pl.col("defteam").alias("team")),
        ])
    team_games = (team_games.unique(subset=["game_id", "team"])
                  .with_columns(pl.col("season").cast(team_d1["season"].dtype),
                                pl.col("week").cast(team_d1["week"].dtype))
                  .with_columns(order).sort("_ord"))

    team_result = (
        team_games.join_asof(measured, on="_ord", by="team",
                             strategy="backward", allow_exact_matches=False,
                             check_sortedness=False)  # sorted on _ord above
        .select(["game_id", "season", "week", "team"] + names)
        .sort(["team", "season", "week"])
    )

    # --- Player-level opening drive touches ---
    # Rushes on drive 1
    rush_d1 = (
        d1.filter(pl.col("rusher_player_id").is_not_null())
        .group_by(["season", "week", "posteam", "rusher_player_id"])
        .agg(pl.len().alias("od_carries"))
        .rename({"rusher_player_id": "player_id", "posteam": "team"})
    )
    # Targets on drive 1
    recv_d1 = (
        d1.filter(pl.col("receiver_player_id").is_not_null())
        .group_by(["season", "week", "posteam", "receiver_player_id"])
        .agg(pl.len().alias("od_targets"))
        .rename({"receiver_player_id": "player_id", "posteam": "team"})
    )

    player_d1 = rush_d1.join(
        recv_d1, on=["season", "week", "team", "player_id"],
        how="full", coalesce=True,
    ).with_columns([
        pl.col("od_carries").fill_null(0),
        pl.col("od_targets").fill_null(0),
    ]).with_columns(
        (pl.col("od_carries") + pl.col("od_targets")).alias("od_touches"),
    )

    # Touch share = player touches / team plays on drive 1
    player_d1 = player_d1.join(
        team_d1.select(["season", "week", "team", "od_plays"]),
        on=["season", "week", "team"], how="left",
    ).with_columns(
        (pl.col("od_touches") / pl.col("od_plays").cast(pl.Float64).clip(lower_bound=1))
        .alias("od_touch_share")
    ).drop("od_plays")

    # Densify: absence must mean "available, no opening-drive touch" rather than
    # silently encoding current-game involvement. See src/features/spine.py.
    player_d1 = densify(
        player_d1, spine,
        zero_cols=["od_carries", "od_targets", "od_touches", "od_touch_share"],
    )

    player_rolling = []
    for col in ["od_touches", "od_touch_share"]:
        shifted = pl.col(col).shift(1)
        player_rolling.extend([
            shifted.rolling_mean(medium, min_samples=3).over("player_id").alias(f"player_{col}_avg_{medium}g"),
            (shifted.cum_sum().over("player_id") / shifted.cum_count().over("player_id")).alias(f"player_{col}_szn_avg"),
        ])

    player_result = (
        player_d1.with_columns(player_rolling)
        .select(["player_id", "season", "week"]
                + [e.meta.output_name() for e in player_rolling])
    )

    return team_result, player_result
