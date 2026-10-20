"""What each player's projection becomes if the game goes a particular way.

The roster tab's scenario picker. A scenario is the final margin, in the five
bands `script_risk` uses (from the team's side), crossed with the total going
over or under this game's line: ten cells. For each position and stat, fitted
from play-by-play since 2015:

  - `mult`: production in games that ended in that cell, against the
    position's overall average;
  - `h1`: the share of the game's production that came in the first half.

**ASSOCIATION, AND THAT IS THE RIGHT QUESTION HERE.** `script_risk` refuses
to edit a projection with these numbers because the arrow runs both ways — a
team often loses big BECAUSE its run game failed. A scenario asks a
different question: given the game DID end this way, what did players at the
position produce? That is a conditional average, and association is exactly
what it is.

**IT CANNOT DRIFT FROM PROPS.** Each card's multipliers are divided by their
average over that game's own cell probabilities (from the same comparable
games `score_dist` uses), so weighting the scenarios by how likely they are
returns the projection Props shows.
"""
from __future__ import annotations

import polars as pl

from src.models.script_risk import BANDS, _band
from src.utils.paths import get_path

#: (position, stat) pairs the roster shows.
STATS = [("QB", "passing_yards"), ("QB", "rushing_yards"),
         ("RB", "rushing_yards"), ("RB", "receiving_yards"), ("RB", "receptions"),
         ("WR", "receiving_yards"), ("WR", "receptions"),
         ("TE", "receiving_yards"), ("TE", "receptions")]

SIDES = ["over", "under"]
CELLS = [f"{b}|{s}" for b in BANDS for s in SIDES]

#: Below this many player-games a cell falls back to its margin band alone,
#: then to no shift. Thin cells are where a multiplier is noise.
MIN_CELL = 150


def _player_halves(seasons: list[int] | None) -> pl.DataFrame:
    """Per player-game: each stat by half and in full, with the team."""
    want = ["season", "week", "game_id", "posteam", "game_half", "season_type",
            "two_point_attempt", "rusher_player_id", "rushing_yards",
            "receiver_player_id", "receiving_yards", "complete_pass",
            "passer_player_id", "passing_yards"]
    p = pl.scan_parquet(get_path("raw") / "pbp.parquet").select(want)
    if seasons:
        p = p.filter(pl.col("season").is_in(seasons))
    p = p.filter((pl.col("season_type") == "REG")
                 & (pl.col("two_point_attempt").fill_null(0) == 0)
                 & pl.col("posteam").is_not_null()).collect()
    h1 = pl.col("game_half") == "Half1"

    def agg(pid, cols):
        g = p.filter(pl.col(pid).is_not_null())
        return g.group_by(["season", "week", "game_id", "posteam", pid]).agg(
            [pl.col(src).fill_null(0).sum().alias(name) for name, src in cols]
            + [pl.when(h1).then(pl.col(src).fill_null(0)).otherwise(0).sum()
                 .alias(f"{name}_h1") for name, src in cols]
        ).rename({pid: "player_id"})

    rush = agg("rusher_player_id", [("rushing_yards", "rushing_yards")])
    rec = agg("receiver_player_id", [("receiving_yards", "receiving_yards"),
                                     ("receptions", "complete_pass")])
    pas = agg("passer_player_id", [("passing_yards", "passing_yards")])
    keys = ["season", "week", "game_id", "posteam", "player_id"]
    d = rush.join(rec, on=keys, how="full", coalesce=True).join(
        pas, on=keys, how="full", coalesce=True)
    return d.rename({"posteam": "team"})


def _team_games() -> pl.DataFrame:
    """Per team-game: final margin from the team's side, and over or under."""
    s = (pl.read_parquet(get_path("raw") / "schedules.parquet")
         .filter(pl.col("game_type") == "REG")
         .drop_nulls(["home_score", "away_score", "total_line"]))
    tot = (pl.col("home_score") + pl.col("away_score"))
    side = (pl.when(tot > pl.col("total_line")).then(pl.lit("over"))
            .when(tot < pl.col("total_line")).then(pl.lit("under")))
    home = s.select("game_id", pl.col("home_team").alias("team"),
                    (pl.col("home_score") - pl.col("away_score")).alias("margin"),
                    side.alias("side"))
    away = s.select("game_id", pl.col("away_team").alias("team"),
                    (pl.col("away_score") - pl.col("home_score")).alias("margin"),
                    side.alias("side"))
    return pl.concat([home, away]).drop_nulls("side").with_columns(
        _band().alias("band"))


def _positions() -> pl.DataFrame:
    return (pl.read_parquet(get_path("raw") / "rosters.parquet")
            .select("season", pl.col("gsis_id").alias("player_id"), "position")
            .drop_nulls().unique(["season", "player_id"], keep="last"))


def fit(seasons: list[int] | None = None) -> dict:
    """{"POS|stat": {"cells": {cell: {"mult", "h1", "n"}}, "h1": overall}}."""
    d = (_player_halves(seasons)
         .join(_team_games(), on=["game_id", "team"], how="inner")
         .join(_positions().with_columns(pl.col("season").cast(pl.Int32)),
               on=["season", "player_id"], how="left")
         .with_columns((pl.col("band") + "|" + pl.col("side")).alias("cell")))
    out: dict = {}
    for pos, stat in STATS:
        x = d.filter((pl.col("position") == pos) & (pl.col(stat).fill_null(0) > 0))
        if x.height < MIN_CELL * 4:
            continue
        base = float(x[stat].mean())
        allh1 = float(x[f"{stat}_h1"].sum() / x[stat].sum())

        def cells(by):
            g = x.group_by(by).agg(pl.col(stat).mean().alias("m"),
                                   pl.col(stat).sum().alias("s"),
                                   pl.col(f"{stat}_h1").sum().alias("s1"),
                                   pl.len().alias("n"))
            return {r[by]: r for r in g.iter_rows(named=True)}

        full, band = cells("cell"), cells("band")
        got = {}
        for c in CELLS:
            r = full.get(c)
            if not r or r["n"] < MIN_CELL:
                r = band.get(c.split("|")[0])
            if not r or r["n"] < MIN_CELL:
                got[c] = {"mult": 1.0, "h1": round(allh1, 4), "n": 0}
                continue
            got[c] = {"mult": round(r["m"] / base, 4),
                      "h1": round(r["s1"] / r["s"], 4) if r["s"] else round(allh1, 4),
                      "n": int(r["n"])}
        out[f"{pos}|{stat}"] = {"cells": got, "h1": round(allh1, 4), "n": x.height}
    return out


def cell_probabilities(card: dict, hist: pl.DataFrame | None = None) -> dict | None:
    """P(cell) from the HOME side, from the comparable games `score_dist` uses."""
    from src.models.score_dist import MIN_COMPARABLES, comparables

    sp, tot = card.get("spread"), card.get("total")
    if sp is None or tot is None:
        return None
    # The card signs the spread negative when home is favored; the schedule,
    # positive. Flipped once, as `band_probabilities` does.
    c = comparables(-float(sp), float(tot), hist=hist)
    if c.height < MIN_COMPARABLES:
        return None
    c = c.with_columns(
        _band().alias("band"),
        pl.when(pl.col("total") > float(tot)).then(pl.lit("over"))
          .when(pl.col("total") < float(tot)).then(pl.lit("under")).alias("side")
    ).drop_nulls("side")
    g = c.group_by(["band", "side"]).len()
    n = c.height
    return {f"{r['band']}|{r['side']}": r["len"] / n for r in g.iter_rows(named=True)}


#: The home team's band seen from the away side.
FLIP = {"won big": "lost big", "won": "lost", "close": "close",
        "lost": "won", "lost big": "won big"}


def for_card(card: dict, fits: dict, hist: pl.DataFrame | None = None) -> dict | None:
    """The cells with their probabilities, and per team the normalized
    multiplier and first-half share for each (position, stat) and cell."""
    probs = cell_probabilities(card, hist)
    if not probs or not fits:
        return None
    home, away = card.get("home"), card.get("away")
    cells = [c for c in CELLS if probs.get(c, 0) > 0]
    teams = {}
    for team in (home, away):
        own = (lambda c: c) if team == home else (
            lambda c: f"{FLIP[c.split('|')[0]]}|{c.split('|')[1]}")
        t = {}
        for key, f in fits.items():
            m = {c: f["cells"][own(c)]["mult"] for c in cells}
            tilt = sum(probs[c] * m[c] for c in cells)
            if tilt <= 0:
                continue
            # Normalized so the probability-weighted average is exactly 1:
            # weighted back over this game's odds, a scenario is the Props
            # projection. The first-half share is weighted the same way.
            h1 = sum(probs[c] * m[c] * f["cells"][own(c)]["h1"] for c in cells) / tilt
            t[key] = {"cells": [[round(m[c] / tilt, 4), f["cells"][own(c)]["h1"]]
                                for c in cells],
                      "h1": round(h1, 4)}
        teams[team] = t
    return {"cells": [{"key": c, "p": round(probs[c], 4)} for c in cells],
            "teams": teams}
