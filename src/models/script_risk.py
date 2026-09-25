"""Which picks hinge on the game going a particular way.

On 2026-09-25 Atlanta won at Green Bay by 21 as a road underdog. The game
model was calibrated — `score_dist.calibration` puts it inside 1.2pp, and the
same build had the outright Atlanta win at 28.5% — but a Green Bay running
back projected on an ordinary afternoon spent the second half three scores
behind, and no number on the page had said that his projection assumed a game
that did not happen.

Two things are needed to say it in advance and this project now has both:

  HOW MUCH a market moves with the score. Fitted here, from every player-game
  since 2015 joined to its team's final margin.

  HOW LIKELY each score is. `score_dist` already answers that from games the
  market priced the same way.

Multiply them together and a pick carries a number saying how much of its
projection is riding on the script.

**MEASURED, AND THE DIRECTION IS NOT UNIFORM.** Normalized to each market's
own mean, by the team's final margin:

    RB rushing yards    won big 1.24   close 1.01   lost big 0.73   swing 0.51
    QB carries          won big 0.96   close 1.07   lost big 0.79   swing 0.40
    RB carries          won big 1.14   close 1.03   lost big 0.78   swing 0.36
    QB passing yards    won big 0.99   close 1.10   lost big 0.78   swing 0.32
    RB targets          won big 0.87   close 1.02   lost big 1.07   swing 0.23
    WR receiving yards  won big 1.04   close 1.05   lost big 0.83   swing 0.22
    WR receptions       won big 0.98   close 1.04   lost big 0.93   swing 0.12

Rushing is where the script lives. Receiving barely moves, and a back's
TARGETS move the other way — a team behind throws to its back. So a blowout
does not simply hurt everyone on the losing side, and a flag that said it did
would be wrong about half the board.

**THIS IS ASSOCIATION, NOT A CAUSAL SCRIPT EFFECT, AND THE DIFFERENCE MATTERS
FOR HOW IT IS READ.** A team that loses by 21 often loses BECAUSE its running
game did nothing; the 0.73 is partly the score changing the play-calling and
partly the rushing failure causing the score. Quarterback passing yards make
that plain — they FALL when losing big, which no game-script story predicts
and which "getting blown out usually means the offense was bad" explains
immediately. So this is a risk flag, not an adjustment: nothing here edits a
projection, because the arrow does not reliably point the way an adjustment
would need it to.

Everything is fitted from the archive rather than typed in, so the numbers
move with the seasons on disk and a new year needs no edit here.
"""
from __future__ import annotations

import polars as pl

from src.utils.paths import get_path

#: Margin bands, in the order a game runs from best to worst for the team.
#: Fourteen points is two scores and four is a field goal plus a point; both
#: are the ordinary boundaries a broadcast uses, not fitted numbers, and
#: nothing below depends on their exact placement.
BANDS = ["won big", "won", "close", "lost", "lost big"]

#: The markets worth measuring, as (position, stat). A market that does not
#: reach `MIN_ROWS` is simply absent rather than estimated thinly.
MARKETS = [
    ("RB", "carries"), ("RB", "rushing_yards"), ("RB", "targets"),
    ("RB", "receiving_yards"), ("RB", "receptions"),
    ("WR", "targets"), ("WR", "receiving_yards"), ("WR", "receptions"),
    ("TE", "targets"), ("TE", "receiving_yards"), ("TE", "receptions"),
    ("QB", "passing_yards"), ("QB", "carries"), ("QB", "rushing_yards"),
]

#: Below this many player-games a multiplier is noise.
MIN_ROWS = 500

#: A swing at or above this is called script-dependent on the page. Chosen so
#: that rushing markets qualify and receiving ones do not, which is what the
#: measurement says rather than what makes a nicer list: the gap between
#: QB passing yards at 0.32 and RB targets at 0.23 is where the data divides.
SCRIPT_DEPENDENT = 0.30


def _team_margins() -> pl.DataFrame:
    """One row per team-game: what the team won or lost by."""
    s = (pl.read_parquet(get_path("raw") / "schedules.parquet")
         .filter(pl.col("game_type") == "REG")
         .drop_nulls(["home_score", "away_score"]))
    home = s.select([pl.col("season"), pl.col("week"),
                     pl.col("home_team").alias("team"),
                     (pl.col("home_score") - pl.col("away_score")).alias("margin")])
    away = s.select([pl.col("season"), pl.col("week"),
                     pl.col("away_team").alias("team"),
                     (pl.col("away_score") - pl.col("home_score")).alias("margin")])
    return pl.concat([home, away])


def _band() -> pl.Expr:
    return (pl.when(pl.col("margin") >= 14).then(pl.lit("won big"))
            .when(pl.col("margin") >= 4).then(pl.lit("won"))
            .when(pl.col("margin") > -4).then(pl.lit("close"))
            .when(pl.col("margin") > -14).then(pl.lit("lost"))
            .otherwise(pl.lit("lost big")))


def fit() -> dict:
    """Production by margin band, normalized to each market's own mean.

    Restricted to player-games with a NON-ZERO value in the stat. Without
    that, every market's "won big" multiplier is dragged up by the reserves
    who only appear once a game is decided, and the number stops being about
    the starters anyone is betting.
    """
    w = pl.read_parquet(get_path("raw") / "weekly_stats.parquet")
    team_col = "recent_team" if "recent_team" in w.columns else "team"
    d = w.join(_team_margins(),
               left_on=["season", "week", team_col],
               right_on=["season", "week", "team"], how="inner")
    if d.is_empty():
        return {}
    d = d.with_columns(_band().alias("script"))
    out: dict = {}
    for pos, stat in MARKETS:
        if stat not in d.columns or "position" not in d.columns:
            continue
        x = d.filter((pl.col("position") == pos)
                     & pl.col(stat).is_not_null() & (pl.col(stat) > 0))
        if x.height < MIN_ROWS:
            continue
        base = float(x[stat].mean())
        if not base:
            continue
        g = x.group_by("script").agg([pl.col(stat).mean().alias("m"),
                                      pl.len().alias("n")])
        mult = {r["script"]: round(r["m"] / base, 4)
                for r in g.iter_rows(named=True)}
        counts = {r["script"]: int(r["n"]) for r in g.iter_rows(named=True)}
        have = [mult[b] for b in BANDS if b in mult]
        if len(have) < len(BANDS):
            continue
        out[f"{pos}|{stat}"] = {
            "pos": pos, "stat": stat, "n": x.height,
            "mult": mult, "band_n": counts,
            "swing": round(max(have) - min(have), 4),
            "script_dependent": (max(have) - min(have)) >= SCRIPT_DEPENDENT,
        }
    return out


def band_probabilities(card: dict, team: str,
                       hist: pl.DataFrame | None = None) -> dict | None:
    """How likely each margin band is FOR THIS TEAM, from comparable games.

    Straight from `score_dist.comparables`, so the two halves of the risk
    number come from the same view of the game rather than from two models
    that might disagree about it.
    """
    from src.models.score_dist import MIN_COMPARABLES, comparables

    sp, tot = card.get("spread"), card.get("total")
    if sp is None or tot is None or not team:
        return None
    # The card signs its spread negative when the HOME side is favored; the
    # schedule signs it the other way. Flipped once, here, as everywhere else.
    c = comparables(-float(sp), float(tot), hist=hist)
    if c.height < MIN_COMPARABLES:
        return None
    # And the margin has to be read from this team's side of it.
    m = (pl.col("margin") if team == card.get("home") else -pl.col("margin"))
    c = c.with_columns(m.alias("margin"))
    g = c.with_columns(_band().alias("script")).group_by("script").agg(
        pl.len().alias("n"))
    total = c.height
    return {r["script"]: r["n"] / total for r in g.iter_rows(named=True)}


def risk(market_key: str, card: dict, team: str, fits: dict,
         hist: pl.DataFrame | None = None) -> dict | None:
    """What this pick's projection is riding on, for this game.

    `tilt` is the expected multiplier: above 1 the script this game is likely
    to take HELPS the market, below 1 it hurts. `spread` is how far the
    multiplier ranges across the outcomes that are actually plausible here —
    a pick can be script-dependent in general and safe in a game with no
    plausible blowout, and this is the number that tells the two apart.

    Returns None rather than a neutral score when either half is missing. A
    fabricated 1.0 would read as "measured and fine".
    """
    f = fits.get(market_key)
    if not f:
        return None
    probs = band_probabilities(card, team, hist=hist)
    if not probs:
        return None
    tilt = sum(probs.get(b, 0.0) * f["mult"][b] for b in BANDS)
    lo = min(f["mult"][b] for b in BANDS if probs.get(b, 0) >= 0.05)
    hi = max(f["mult"][b] for b in BANDS if probs.get(b, 0) >= 0.05)
    # The single worst plausible case, named, because "0.73x if they lose by
    # two scores" is a sentence and a spread of 0.4 is not.
    worst = min((b for b in BANDS if probs.get(b, 0) >= 0.05),
                key=lambda b: f["mult"][b])
    return {
        "market": market_key, "team": team,
        "tilt": round(tilt, 3), "spread": round(hi - lo, 3),
        "worst_band": worst, "worst_mult": f["mult"][worst],
        "worst_p": round(probs.get(worst, 0.0), 3),
        "script_dependent": bool(f["script_dependent"]),
        "swing": f["swing"], "n": f["n"],
    }
