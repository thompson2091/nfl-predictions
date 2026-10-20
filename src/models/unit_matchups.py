"""Position group against position group: receivers against the secondary,
backs against the front, line against line.

**BY WHO GOT THE BALL, NOT BY WHO COVERED HIM.** Play-by-play records the
target and the ball carrier; it does not record the defender. So "receivers
against the secondary" is how a team's throws to its wide receivers have gone,
set beside what the opponent's defense has allowed on throws to wide
receivers. Coverage assignments live in the NFL's participation feed, which
nflverse publishes a season behind; when 2026's arrives this can read it.

**FTN's charting supplies the line.** Sack rate alone cannot tell a line that
wins one-on-one from a defense that blitzed to get there. FTN charts how many
rushed, so the four-or-fewer split separates the two. It is published daily
in season (`loader.load_ftn_charting`).

**AS-OF, LIKE `matchup_stats`.** Every rate sums only the games played before
the week being shown, through the same `_totals_through`.

**DIFFERENTIALS.** Each row pairs one side's unit with the other side's, and
`edge` is the offense's advantage in the metric's own units.
"""
from __future__ import annotations

import polars as pl

from src.models.matchup_stats import MIN_GAMES, _totals_through
from src.utils.paths import get_path

#: (unit key, offense label, defense label, note, metrics). Each metric is
#: (key, label, numerator, denominator, higher is better for the offense).
UNITS = [
    ("wr", "Receivers", "the secondary",
     "Throws to wide receivers, and what this defense has allowed on them.",
     [("wr_epa", "EPA per target", "wr_epa", "wr_n", True),
      ("wr_succ", "Success rate", "wr_s", "wr_n", True)]),
    ("te", "Tight ends", "linebackers and safeties",
     "Throws to tight ends, and what this defense has allowed on them.",
     [("te_epa", "EPA per target", "te_epa", "te_n", True),
      ("te_succ", "Success rate", "te_s", "te_n", True)]),
    ("rbp", "Backs as receivers", "linebackers",
     "Throws to running backs, and what this defense has allowed on them.",
     [("rbp_epa", "EPA per target", "rbp_epa", "rbp_n", True),
      ("rbp_succ", "Success rate", "rbp_s", "rbp_n", True)]),
    ("run", "Backs running", "the run defense",
     "Running back carries, and what this defense has allowed to backs.",
     [("run_epa", "EPA per carry", "run_epa", "run_n", True),
      ("run_succ", "Success rate", "run_s", "run_n", True),
      ("run_stuff", "Stuffed at or behind the line", "run_stuff", "run_n", False)]),
    ("line", "Offensive line", "defensive line",
     "Sacks and hits on the quarterback. Sacks are pressure that got home, "
     "not all pressure; the four-or-fewer row comes from FTN's charting and "
     "is the one a blitz cannot explain.",
     [("sack", "Sack rate", "sack_k", "drop_n", False),
      ("hit", "QB hit rate", "hit_k", "drop_n", False),
      ("sack4", "Sack rate, four or fewer rushing", "sack4_k", "drop4_n", False)]),
]


def _positions(season: int, week: int | None = None) -> pl.DataFrame:
    """gsis id to position, the player's latest listing up to `week`.

    As of the week shown, so a past week does not read a move made later.
    """
    r = (pl.scan_parquet(get_path("raw") / "rosters.parquet")
         .filter(pl.col("season") == season)
         .select(["gsis_id", "position", "week"]).collect())
    if week is not None and "week" in r.columns:
        early = r.filter(pl.col("week").is_null() | (pl.col("week") <= week))
        if early.height:
            r = early
    if "week" in r.columns:
        r = r.sort("week", nulls_last=False)
    return (r.drop_nulls("gsis_id").group_by("gsis_id")
             .agg(pl.col("position").last()))


def _plays(season: int, week: int | None = None) -> pl.DataFrame:
    want = ["season", "week", "game_id", "play_id", "posteam", "defteam",
            "play_type", "pass", "sack", "qb_hit", "epa", "success",
            "yards_gained", "receiver_player_id", "rusher_player_id",
            "qb_scramble", "season_type"]
    d = pl.scan_parquet(get_path("raw") / "pbp.parquet")
    have = d.collect_schema().names()
    d = (d.select([c for c in want if c in have])
          .filter((pl.col("season") == season) & pl.col("posteam").is_not_null()
                  & pl.col("defteam").is_not_null()))
    if "season_type" in have:
        d = d.filter(pl.col("season_type") == "REG")
    d = d.collect()
    pos = _positions(season, week)
    d = (d.join(pos.rename({"gsis_id": "receiver_player_id", "position": "rec_pos"}),
                on="receiver_player_id", how="left")
          .join(pos.rename({"gsis_id": "rusher_player_id", "position": "rush_pos"}),
                on="rusher_player_id", how="left"))
    ftn_path = get_path("raw") / "ftn_charting.parquet"
    if ftn_path.exists():
        f = (pl.read_parquet(ftn_path).filter(pl.col("season") == season)
             .select(["game_id", "play_id", "n_pass_rushers", "n_blitzers"]))
        d = d.join(f.with_columns(pl.col("play_id").cast(d["play_id"].dtype)),
                   on=["game_id", "play_id"], how="left")
    else:
        d = d.with_columns(pl.lit(None, pl.Int64).alias("n_pass_rushers"),
                           pl.lit(None, pl.Int64).alias("n_blitzers"))
    return d


def _per_game(d: pl.DataFrame, by: str) -> pl.DataFrame:
    """Numerators and denominators per team-game, for one side of the ball."""
    tgt = (pl.col("play_type") == "pass") & pl.col("receiver_player_id").is_not_null()
    car = ((pl.col("play_type") == "run") & (pl.col("rush_pos") == "RB")
           & (pl.col("qb_scramble").fill_null(0) == 0))
    run = (pl.col("play_type") == "run") & (pl.col("qb_scramble").fill_null(0) == 0)
    drop = (pl.col("pass") == 1) | (pl.col("sack") == 1)
    charted = drop & pl.col("n_pass_rushers").is_not_null()
    four = charted & (pl.col("n_pass_rushers") <= 4)
    succ = pl.col("success") == 1

    def group(pos, tag):
        m = tgt & (pl.col("rec_pos") == pos)
        return [m.sum().alias(f"{tag}_n"),
                (m & succ).sum().alias(f"{tag}_s"),
                pl.when(m).then(pl.col("epa")).otherwise(None).sum().alias(f"{tag}_epa")]

    return d.group_by(["season", "week", by]).agg(
        group("WR", "wr") + group("TE", "te") + group("RB", "rbp") + [
            car.sum().alias("run_n"),
            (car & succ).sum().alias("run_s"),
            pl.when(car).then(pl.col("epa")).otherwise(None).sum().alias("run_epa"),
            (car & (pl.col("yards_gained") <= 0)).sum().alias("run_stuff"),
            run.sum().alias("runs_n"),
            drop.sum().alias("drop_n"),
            (pl.col("sack") == 1).sum().alias("sack_k"),
            (pl.col("qb_hit") == 1).sum().alias("hit_k"),
            four.sum().alias("drop4_n"),
            (four & (pl.col("sack") == 1)).sum().alias("sack4_k"),
            pl.lit(1).alias("game_n"),
        ]).rename({by: "team"})


def build(season: int, week: int) -> dict:
    """{team: {"games": n, "off": {metric: (rate, n)}, "def": {...}}}."""
    d = _plays(season, week)
    if d.is_empty():
        return {}
    out: dict = {}
    for side, by in (("off", "posteam"), ("def", "defteam")):
        t = _totals_through(_per_game(d, by), week)
        if t.is_empty():
            continue
        for r in t.iter_rows(named=True):
            team = out.setdefault(r["team"], {"games": int(r["games"] or 0)})
            vals = {}
            for _k, _o, _d, _n, metrics in UNITS:
                for key, _lab, num, den, _hi in metrics:
                    n = r.get(f"c_{den}") or 0
                    vals[key] = ((round(float(r[f"c_{num}"]) / n, 4) if n else None),
                                 int(n))
            team[side] = vals
    return out


def matchup(card: dict, stats: dict) -> list[dict] | None:
    """Per unit, each metric with both directions: away unit against home's,
    and the reverse."""
    home, away = card.get("home"), card.get("away")
    if not (home and away) or home not in stats or away not in stats:
        return None
    units = []
    for ukey, olab, dlab, note, metrics in UNITS:
        rows = []
        for key, label, _num, _den, higher in metrics:
            pair = []
            for o, dt in ((away, home), (home, away)):
                a = (stats[o].get("off") or {}).get(key)
                b = (stats[dt].get("def") or {}).get(key)
                if not a or not b or a[0] is None or b[0] is None:
                    continue
                pair.append({"offense": o, "defense": dt,
                             "off_val": a[0], "def_val": b[0],
                             "off_n": a[1], "def_n": b[1],
                             "edge": round((a[0] - b[0]) if higher
                                           else (b[0] - a[0]), 4)})
            if pair:
                rows.append({"key": key, "label": label,
                             "higher_is_better": higher, "sides": pair})
        if rows:
            units.append({"key": ukey, "label": f"{olab} against {dlab}",
                          "note": note, "rows": rows})
    return units or None


def thin(card: dict, stats: dict) -> bool:
    return any((stats.get(t) or {}).get("games", 0) < MIN_GAMES
               for t in (card.get("home"), card.get("away")))
