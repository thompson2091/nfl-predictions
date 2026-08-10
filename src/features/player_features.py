import polars as pl
from src.utils.config import get_config
from src.features.carry_forward import build_with_carry_forward


def build_player_rolling_features(weekly_stats: pl.DataFrame,
                                  spine: pl.DataFrame = None) -> pl.DataFrame:
    """Build per-player rolling stats. Shift(1) to prevent leakage."""
    cfg = get_config()
    short = cfg["rolling_windows"]["short"]
    medium = cfg["rolling_windows"]["medium"]

    # Ensure sorted by player and time
    df = weekly_stats.sort(["player_id", "season", "week"])

    # Core stats to roll
    stat_cols = [
        "carries", "rushing_yards", "rushing_tds",
        "targets", "receptions", "receiving_yards", "receiving_tds",
        "fantasy_points_ppr",
        "rushing_epa", "receiving_epa",
        "rushing_first_downs", "receiving_first_downs",
        "rushing_2pt_conversions",
    ]

    # Keep only columns that exist
    available = [c for c in stat_cols if c in df.columns]

    # First TD rate (needs first_tds joined later, use rushing+receiving TDs as proxy)
    if "rushing_tds" in df.columns and "receiving_tds" in df.columns:
        df = df.with_columns(
            (pl.col("rushing_tds") + pl.col("receiving_tds")).alias("total_tds")
        )
        available = available + ["total_tds"]

    def _exprs(lag: int) -> list[pl.Expr]:
        """Rolling exprs. lag=1 excludes the current game (training rows);
        lag=0 includes it (the state to carry into the next, unplayed game)."""
        out = []
        for col in available:
            base = pl.col(col).shift(lag) if lag else pl.col(col)
            for window, label in [(short, f"{short}g"), (medium, f"{medium}g")]:
                out.append(
                    base.rolling_mean(window, min_samples=3)
                    .over("player_id")
                    .alias(f"player_{col}_avg_{label}")
                )
            # Season-to-date mean
            out.append(
                (base.cum_sum().over("player_id") / base.cum_count().over("player_id"))
                .alias(f"player_{col}_szn_avg")
            )
        return out

    return build_with_carry_forward(df, _exprs, spine=spine, zero_cols=available)
