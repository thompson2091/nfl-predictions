"""How each side has actually played, offense against defense, as differentials.

The stats a handicapper reads before a game: does this offense stay ahead of
schedule, does this defense get to the quarterback, who wins the red zone.
Everything here is computed from play-by-play, per team, **from the games
BEFORE the one being shown**.

**AS-OF, VIA `cum_sum().shift(1)`.** Computed the natural way — a group-by
over the season — every number would include the game it is describing, and a
page about an unplayed game would be reporting its result. That is the same
failure `game_model.leaky_columns` exists to catch and the same shift the
coach features needed.

**DIFFERENTIALS, BECAUSE A RAW RATE IS UNREADABLE.** "Cincinnati 48.2% early-
down success" means nothing without knowing that the league sits near 45% and
Pittsburgh's defense allows 44.1%. Each row pairs one side's offense with the
other's defense and reports the gap, which is the number a reader can act on.

**WHAT IS A PROXY IS LABELED A PROXY.** Sack rate and quarterback-hit rate
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
#: `higher_is_better` is from the OFFENSE's point of view; the defensive
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
    ("plays_per_game", "Plays per game", True,
     "Offensive snaps. Pace rather than quality — more plays is more chances "
     "for everyone's props, on both sides."),
    ("two_min_success", "Two-minute success", True,
     "Success rate inside the last two minutes of a half. A SMALL sample: "
     "two games in, a team may have twenty such plays."),
    ("two_min_epa", "Two-minute EPA", True,
     "Expected points added per play in the last two minutes of a half."),
    ("late_half_score_rate", "Late-half scoring drives", True,
     "Drives starting inside the last four minutes of a half that end in "
     "points. Read on the defensive side as drives ALLOWED to score."),
    ("sudden_change_success", "After a turnover", True,
     "Success rate on the possession immediately following a takeaway. "
     "Thinner still, and stated as a count rather than leant on."),
]

#: WHAT EACH METRIC IS ABOUT, so twelve rows can be read four at a time.
#:
#: Not offense against defense: every row already carries both directions, so
#: splitting that way would halve nothing. These group by the QUESTION a
#: reader has — can they move it, do they finish, do they get to the
#: quarterback, how fast does the game go — which is what turns one scroll of
#: twelve into a choice between four short lists.
#:
#: Every metric must appear here, and `test_every_matchup_metric_has_a_group`
#: fails if one is added without a home. A metric quietly falling into "other"
#: is a metric nobody finds.
GROUPS = [
    ("move", "Moving", ("epa_play", "early_down_success", "first_down_4plus",
                        "second_down_conv", "explosive_rate")),
    ("score", "Scoring", ("rz_td_pct", "late_half_score_rate")),
    ("rush", "Pressure", ("sack_rate", "qb_hit_rate")),
    ("tempo", "Tempo", ("plays_per_game", "two_min_success", "two_min_epa",
                        "sudden_change_success")),
]

#: `{metric key: group key}`, built from the list above so the two cannot drift.
GROUP_OF = {k: g for g, _lab, keys in GROUPS for k in keys}


#: Asked for and NOT built, with the reason. Shown on the page so a gap reads
#: as a gap rather than as an oversight.
MISSING = [
    ("Success rate after a takeaway",
     "Needs the possession IMMEDIATELY following a turnover, which is a "
     "sequence across drives rather than a filter on plays. Buildable from "
     "`fixed_drive` and `drive_end_transition`; not built yet, and an "
     "approximation from adjacent plays would answer a different question."),
    ("Four-man rush vs blitz pressure",
     "`number_of_pass_rushers` is populated for 2016-2025 and empty for 2026. "
     "Building it would mean showing last season's numbers as this week's."),
    ("True pressure rate",
     "Needs the NFL participation feed's `was_pressure`, which this project's "
     "play-by-play does not carry. Sack and QB-hit rate are shown instead and "
     "are labeled as proxies."),
    ("Pass block and pass rush win rate",
     "ESPN computes these from tracking data and does not publish them."),
]

#: Below this many prior games a team's rate is noise. Not a filter — the rate
#: is still computed — it travels beside it so the page can show how thin it is.
MIN_GAMES = 2

#: The splits offered. Overtime is excluded from both halves rather than
#: folded into the second: it is a different game with different rules and
#: fewer than 1% of plays, and adding it would make "second half" mean
#: something slightly different for the handful of teams who played one.
HALVES = [("full", "Full game", None),
          ("h1", "1st half", "Half1"),
          ("h2", "2nd half", "Half2")]


def _plays(seasons: list[int] | None = None) -> pl.DataFrame:
    cols = ["season", "week", "posteam", "defteam", "down", "ydstogo",
            "yards_gained", "yardline_100", "epa", "success", "sack",
            "qb_hit", "pass", "rush", "touchdown", "play_type", "fixed_drive",
            "game_id", "season_type", "game_half", "half_seconds_remaining",
            "fixed_drive", "fixed_drive_result", "interception",
            "fumble_lost"]
    d = pl.scan_parquet(get_path("raw") / "pbp.parquet")
    have = d.collect_schema().names()
    # De-duplicated, in order. `fixed_drive` was in the list twice after the
    # drive metrics were added, and polars refuses a projection with two
    # columns of one name rather than quietly keeping one.
    seen, want = set(), []
    for c in cols:
        if c in have and c not in seen:
            seen.add(c)
            want.append(c)
    d = d.select(want)
    if seasons:
        d = d.filter(pl.col("season").is_in(seasons))
    d = d.filter(pl.col("posteam").is_not_null()
                 & pl.col("defteam").is_not_null())
    # OFFENSIVE PLAYS ONLY. Kickoffs, punts, extra points and no-plays carry a
    # posteam too, and every rate here was diluted by them: "plays per game"
    # read 80.6 against 60.6 snaps, and red-zone TD% read 13% because extra
    # points counted as red-zone plays. Sacks are `pass` in nflverse, so they
    # stay; kneels and spikes go.
    if "play_type" in have:
        d = d.filter(pl.col("play_type").is_in(["pass", "run"]))
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
    # The last two minutes of EITHER half, which is what "two-minute" means to
    # a coach — not the last two minutes of the game.
    two_min = pl.col("half_seconds_remaining") <= 120
    late_half = pl.col("half_seconds_remaining") <= 240
    scored = pl.col("fixed_drive_result").is_in(
        ["Touchdown", "Field goal"]) if "fixed_drive_result" in d.columns \
        else pl.lit(False)
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
        # TRIPS, NOT PLAYS: a drive that reached the 20 counts once, and
        # counts as a touchdown if it ended in one. "Trips inside the 20 that
        # end in a touchdown" is what the label says; per play it read 13%
        # against a true drive rate near 61%.
        pl.col("fixed_drive").filter(pl.col("yardline_100") <= 20)
          .n_unique().alias("rz_n"),
        pl.col("fixed_drive").filter((pl.col("yardline_100") <= 20)
                                     & (pl.col("fixed_drive_result") == "Touchdown"))
          .n_unique().alias("rz_k"),
        (pl.col("yards_gained") >= 15).sum().alias("exp_k"),
        pl.col("epa").sum().alias("epa_sum"),
        pl.col("epa").is_not_null().sum().alias("epa_n"),
        drop.sum().alias("drop_n"),
        (pl.col("sack") == 1).sum().alias("sack_k"),
        (pl.col("qb_hit") == 1).sum().alias("hit_k"),
        two_min.sum().alias("tm_n"),
        (two_min & (pl.col("success") == 1)).sum().alias("tm_k"),
        pl.when(two_min).then(pl.col("epa")).otherwise(None).sum()
            .alias("tm_epa"),
        (two_min & pl.col("epa").is_not_null()).sum().alias("tm_epa_n"),
        # DRIVES, not plays: a drive is counted once however long it ran, so
        # these are counted on the drive id rather than summed over snaps.
        # `filter`, not `when(...).otherwise(None)`: `n_unique` counts the
        # null as one more value, so every team-game had a phantom drive.
        pl.col("fixed_drive").filter(late_half).n_unique().alias("lh_n"),
        pl.col("fixed_drive").filter(late_half & scored).n_unique().alias("lh_k"),
        pl.lit(1).alias("game_n"),
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
        z("c_plays", "games").alias("plays_per_game"),
        z("c_tm_k", "c_tm_n").alias("two_min_success"),
        z("c_tm_epa", "c_tm_epa_n").alias("two_min_epa"),
        z("c_lh_k", "c_lh_n").alias("late_half_score_rate"),
        # Sudden change needs the possession AFTER a takeaway, which is a
        # sequence rather than a filter and is not built here. Named in
        # MISSING rather than approximated by something adjacent.
        pl.lit(None, dtype=pl.Float64).alias("sudden_change_success"),
    ])


def build(season: int, week: int) -> dict:
    """Offense and defense rates for every team, entering this week.

    Three splits per team — full game, first half, second half — from ONE read
    of the play-by-play. A first-half number is a different fact from a
    season-long one: a team that scripts its opening drives shows up there and
    is invisible in the total.
    """
    d = _plays([season])
    if d.is_empty():
        return {}
    keys = [m[0] for m in METRICS]
    out: dict = {}
    for split, _label, half in HALVES:
        part = d if half is None else d.filter(pl.col("game_half") == half)
        if part.is_empty():
            continue
        off = _rates(_totals_through(_per_game(part, "posteam"), week))
        dfn = _rates(_totals_through(_per_game(part, "defteam"), week))
        if off.is_empty() or dfn.is_empty():
            continue
        for side, frame in (("off", off), ("def", dfn)):
            for r in frame.iter_rows(named=True):
                t = out.setdefault(r["team"], {})
                # `games` is the same whichever split; taken from the full
                # game so a team that never trailed still reads as two games.
                if split == "full":
                    t["games"] = int(r["games"] or 0)
                t.setdefault(split, {})[side] = {
                    k: (round(float(r[k]), 4) if r[k] is not None else None)
                    for k in keys}
    return out


def matchup(card: dict, stats: dict, split: str = "full") -> list[dict] | None:
    """One row per metric: each side's offense against the other's defense.

    Two rows per metric — away offense vs home defense, and the reverse —
    because a matchup has two halves and showing one is showing half a game.
    """
    home, away = card.get("home"), card.get("away")
    if not (home and away) or home not in stats or away not in stats:
        return None
    out = []
    for key, label, higher, note in METRICS:
        pair = []
        for o, dteam in ((away, home), (home, away)):
            a = ((stats[o].get(split) or {}).get("off") or {}).get(key)
            b = ((stats[dteam].get(split) or {}).get("def") or {}).get(key)
            if a is None or b is None:
                continue
            pair.append({"offense": o, "defense": dteam,
                         "off_val": a, "def_val": b,
                         "diff": round(a - b, 4),
                         # An advantage for the OFFENSE. On sack rate, where
                         # a lower offensive number is better, beating the
                         # defense's rate is a bad thing and the sign flips.
                         "edge": round((a - b) if higher else (b - a), 4)})
        if pair:
            out.append({"key": key, "label": label, "note": note,
                        "higher_is_better": higher,
                        # What the metric is about, so twelve rows can be read
                        # four at a time. Shipped rather than guessed on the
                        # page: a metric added upstream with no group is a
                        # metric that quietly stops being findable.
                        "group": GROUP_OF.get(key, "other"),
                        "proxy": "PROXY" in note or "proxy" in note,
                        "sides": pair})
    return out or None
