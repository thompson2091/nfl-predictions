"""How each side has actually played, offence against defence, as differentials.

The stats a handicapper reads before a game: does this offence stay ahead of
schedule, does this defence get to the quarterback, who wins the red zone.
Everything here is computed from play-by-play, per team, **from the games
BEFORE the one being shown**.

**AS-OF, VIA `cum_sum().shift(1)`.** Computed the natural way — a group-by
over the season — every number would include the game it is describing, and a
page about an unplayed game would be reporting its result. That is the same
failure `game_model.leaky_columns` exists to catch and the same shift the
coach features needed.

**DIFFERENTIALS, BECAUSE A RAW RATE IS UNREADABLE.** "Cincinnati 48.2% early-
down success" means nothing without knowing that the league sits near 45% and
Pittsburgh's defence allows 44.1%. Each row pairs one side's offence with the
other's defence and reports the gap, which is the number a reader can act on.

**WHAT IS A PROXY IS LABELLED A PROXY.** Sack rate and quarterback-hit rate
are NOT pressure rate: they measure pressure that succeeded, not pressure
applied, and a line that generates constant pressure against a quick release
looks identical to one that generates none. True pressure needs the NFL's
participation feed, and `number_of_pass_rushers` — the field that would also
separate a four-man rush from a blitz — is populated for 2016-2025 and EMPTY
for 2026. So the blitz split this module was asked for is not built rather
than built on last season's numbers, and `MISSING` says so on the page.
"""
from __future__ import annotations

import polars as pl

from src.utils.paths import get_path

#: Metrics this module can honestly produce, and what each one is.
#:
#: `higher_is_better` is from the OFFENCE's point of view; the defensive
#: version of each is the same quantity allowed, so the sign flips there and
#: the page must not assume one direction for both.
METRICS = [
    ("early_down_success", "Early-down success", True,
     "Share of 1st and 2nd down plays that gained enough to stay on schedule."),
    ("first_down_4plus", "4+ yards on 1st down", True,
     "How often first down gains at least four yards."),
    ("second_down_conv", "2nd down conversion", True,
     "How often 2nd down picks up the line to gain."),
    ("rz_td_pct", "Red zone touchdowns", True,
     "Trips inside the 20 that end in a touchdown."),
    ("explosive_rate", "Explosive plays", True,
     "Plays gaining 15 or more yards."),
    ("epa_play", "EPA per play", True,
     "Expected points added per play — the broadest measure of efficiency."),
    ("sack_rate", "Sack rate", False,
     "Dropbacks ending in a sack. A PROXY for pressure: it counts pressure "
     "that succeeded, not pressure applied."),
    ("qb_hit_rate", "QB hit rate", False,
     "Dropbacks where the quarterback was hit. Also a proxy, and a wider one "
     "than sacks."),
]

#: Asked for and NOT built, with the reason. Shown on the page so a gap reads
#: as a gap rather than as an oversight.
MISSING = [
    ("Four-man rush vs blitz pressure",
     "`number_of_pass_rushers` is populated for 2016-2025 and empty for 2026. "
     "Building it would mean showing last season's numbers as this week's."),
    ("True pressure rate",
     "Needs the NFL participation feed's `was_pressure`, which this project's "
     "play-by-play does not carry. Sack and QB-hit rate are shown instead and "
     "are labelled as proxies."),
    ("Pass block and pass rush win rate",
     "ESPN computes these from tracking data and does not publish them."),
]

#: Below this many prior games a team's rate is noise. Not a filter — the rate
#: is still computed — it travels beside it so the page can show how thin it is.
MIN_GAMES = 2


def _plays(seasons: list[int] | None = None) -> pl.DataFrame:
    cols = ["season", "week", "posteam", "defteam", "down", "ydstogo",
            "yards_gained", "yardline_100", "epa", "success", "sack",
            "qb_hit", "pass", "rush", "touchdown", "play_type", "fixed_drive",
            "game_id", "season_type"]
    d = pl.scan_parquet(get_path("raw") / "pbp.parquet")
    have = d.collect_schema().names()
    d = d.select([c for c in cols if c in have])
    if seasons:
        d = d.filter(pl.col("season").is_in(seasons))
    d = d.filter(pl.col("posteam").is_not_null()
                 & pl.col("defteam").is_not_null())
    if "season_type" in have:
        d = d.filter(pl.col("season_type") == "REG")
    return d.collect()


def _per_game(d: pl.DataFrame, by: str) -> pl.DataFrame:
    """Numerators and denominators per team-game, for one side of the ball.

    Counted rather than averaged, because the as-of figure has to be a ratio
    of SUMS over prior games. Averaging per-game rates and then averaging
    those weights a 40-play game the same as a 75-play one.
    """
    is_pass = (pl.col("pass") == 1) if "pass" in d.columns else pl.lit(False)
    early = pl.col("down").is_in([1, 2])
    drop = is_pass | (pl.col("sack") == 1)
    return d.group_by(["season", "week", by]).agg([
        pl.len().alias("plays"),
        early.sum().alias("early_n"),
        (early & (pl.col("success") == 1)).sum().alias("early_k"),
        (pl.col("down") == 1).sum().alias("d1_n"),
        ((pl.col("down") == 1) & (pl.col("yards_gained") >= 4)).sum()
            .alias("d1_k"),
        (pl.col("down") == 2).sum().alias("d2_n"),
        ((pl.col("down") == 2)
         & (pl.col("yards_gained") >= pl.col("ydstogo"))).sum().alias("d2_k"),
        (pl.col("yardline_100") <= 20).sum().alias("rz_n"),
        ((pl.col("yardline_100") <= 20) & (pl.col("touchdown") == 1)).sum()
            .alias("rz_k"),
        (pl.col("yards_gained") >= 15).sum().alias("exp_k"),
        pl.col("epa").sum().alias("epa_sum"),
        pl.col("epa").is_not_null().sum().alias("epa_n"),
        drop.sum().alias("drop_n"),
        (pl.col("sack") == 1).sum().alias("sack_k"),
        (pl.col("qb_hit") == 1).sum().alias("hit_k"),
    ]).rename({by: "team"})


def _totals_through(g: pl.DataFrame, week: int) -> pl.DataFrame:
    """Running totals for every week PLAYED BEFORE `week`.

    An earlier version used `cum_sum().shift(1)` and filtered to the target
    week, which returns nothing for a week that has not been played — and the
    week being bet never has. The shift is unnecessary once the frame is
    filtered first: summing only the games before this one is the same
    guarantee, stated where it is easier to see.
    """
    g = g.filter(pl.col("week") < week)
    if g.is_empty():
        return g
    cols = [c for c in g.columns if c not in ("season", "week", "team")]
    return (g.group_by(["season", "team"])
            .agg([pl.col(c).sum().alias(f"c_{c}") for c in cols]
                 + [pl.len().alias("games")]))


def _rates(g: pl.DataFrame) -> pl.DataFrame:
    if g.is_empty():
        return g
    z = lambda n, d: (pl.when(pl.col(d) > 0)
                      .then(pl.col(n) / pl.col(d)).otherwise(None))
    return g.select([
        "season", "team", pl.col("games").fill_null(0),
        z("c_early_k", "c_early_n").alias("early_down_success"),
        z("c_d1_k", "c_d1_n").alias("first_down_4plus"),
        z("c_d2_k", "c_d2_n").alias("second_down_conv"),
        z("c_rz_k", "c_rz_n").alias("rz_td_pct"),
        z("c_exp_k", "c_plays").alias("explosive_rate"),
        z("c_epa_sum", "c_epa_n").alias("epa_play"),
        z("c_sack_k", "c_drop_n").alias("sack_rate"),
        z("c_hit_k", "c_drop_n").alias("qb_hit_rate"),
    ])


def build(season: int, week: int) -> dict:
    """Offence and defence rates for every team, entering this week."""
    d = _plays([season])
    if d.is_empty():
        return {}
    off = _rates(_totals_through(_per_game(d, "posteam"), week))
    dfn = _rates(_totals_through(_per_game(d, "defteam"), week))
    if off.is_empty() or dfn.is_empty():
        return {}
    keys = [m[0] for m in METRICS]
    out: dict = {}
    for side, frame in (("off", off), ("def", dfn)):
        for r in frame.iter_rows(named=True):
            t = out.setdefault(r["team"], {"games": int(r["games"] or 0)})
            t[side] = {k: (round(float(r[k]), 4) if r[k] is not None else None)
                       for k in keys}
    return out


def matchup(card: dict, stats: dict) -> list[dict] | None:
    """One row per metric: each side's offence against the other's defence.

    Two rows per metric — away offence vs home defence, and the reverse —
    because a matchup has two halves and showing one is showing half a game.
    """
    home, away = card.get("home"), card.get("away")
    if not (home and away) or home not in stats or away not in stats:
        return None
    out = []
    for key, label, higher, note in METRICS:
        pair = []
        for o, dteam in ((away, home), (home, away)):
            a = (stats[o].get("off") or {}).get(key)
            b = (stats[dteam].get("def") or {}).get(key)
            if a is None or b is None:
                continue
            pair.append({"offense": o, "defense": dteam,
                         "off_val": a, "def_val": b,
                         "diff": round(a - b, 4),
                         # An advantage for the OFFENCE. On sack rate, where
                         # a lower offensive number is better, beating the
                         # defence's rate is a bad thing and the sign flips.
                         "edge": round((a - b) if higher else (b - a), 4)})
        if pair:
            out.append({"key": key, "label": label, "note": note,
                        "higher_is_better": higher,
                        "proxy": "PROXY" in note or "proxy" in note,
                        "sides": pair})
    return out or None
