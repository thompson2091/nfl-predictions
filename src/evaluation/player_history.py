"""What a player's line has done before, which is a fact rather than a finding.

**THIS IS DELIBERATELY NOT A PATTERN BOARD.** Measuring whether a player-prop
pattern beats its price needs three things this does not: a usage model, because
one player-game in nine is a man who barely played and every one of those goes
under; a 7% house cut to clear, against 4.5% on a spread; and a baseline that
holds playing time constant. See `fade_unders` for the first of those, which is
the best writeup in this repo of how the obvious fix -- filter on what he
actually did -- replaces a scratch artifact with a look-ahead one.

None of that is needed to say what happened. A line, what he did against it, and
the date are three facts, and a reader can see a zero for themselves. So there
are no percentages against a price here, no expectation, no interval and no
color that means good: those are the machinery of a claim, and this makes none.

WHAT IT IS FOR is the question people actually open a player to ask -- is 6.5
high for him? -- which the board cannot answer because the board prices one
week.
"""
from __future__ import annotations

import re

import polars as pl

from src.utils.paths import get_path

#: The six markets, their shape, and where the answer lives.
#:
#: `kind` decides how a week is drawn. A LINE market has a number to beat, so
#: the honest picture is what he did MINUS the line: his line moves week to week
#: and the raw count is not comparable across weeks while the margin is. A YESNO
#: market has no line, so the picture is the price he was quoted and whether it
#: landed.
MARKETS: tuple[tuple[str, str, str, str, str | None], ...] = (
    ("receptions", "Receptions", "line", "catches", "receptions"),
    ("receiving_yards", "Receiving yards", "line", "yards", "receiving_yards"),
    ("rushing_yards", "Rushing yards", "line", "yards", "rushing_yards"),
    ("passing_yards", "Passing yards", "line", "yards", "passing_yards"),
    ("anytime_td", "Anytime touchdown", "yesno", "", None),
    ("first_td", "First touchdown", "yesno", "", None),
)

ARCHIVE = "data/archive/odds_history.parquet"


def _norm(c: pl.Expr) -> pl.Expr:
    """The project's normalization, plus the two things books do to a name.

    THE BASE RULES MUST MATCH `odds_history._norm_expr` and a test asserts they
    do: two normalizations differing by one punctuation rule fail on a handful
    of players and look exactly like a thin archive rather than a bug.

    THE TWO ADDITIONS ARE BOTH REAL AND BOTH WERE COSTING REAL PLAYERS.

    A CURLY APOSTROPHE. One book writes "Ja\u2019Marr Chase" and another writes
    "Ja'Marr Chase", and U+2019 is not U+0027, so the two never met. That is the
    player in every mock of this feature.

    A TEAM IN BRACKETS. Some books disambiguate with "Trey McBride (ARI)" and
    "Michael Thomas (NO)", which no roster ever carries.
    """
    e = (c.str.replace_all("\u2019", "'")
         .str.replace_all(r"\s*\([^)]*\)\s*$", "")
         .str.to_lowercase().str.strip_chars())
    for suffix in (" jr.", " sr.", " ii", " iii", " iv", " jr", " sr"):
        e = e.str.replace(rf"{suffix}$", "")
    return e.str.replace_all(r"\.", "").str.strip_chars()


def _ids() -> pl.DataFrame:
    """Every spelling of a name a roster has ever carried, mapped to one id.

    NAMES DO NOT MATCH AND IDS DO. A book writes "Kenneth Gainwell" and the
    weekly stats write "Kenny Gainwell"; so do "Chigoziem" and "Chig" Okonkwo,
    and "Andrew" and "Drew" Ogletree. Joining on the name lost all three, which
    reads as a player with no history rather than as a join that missed.

    PER SEASON FIRST, because two men can share a name in different eras and a
    single map would hand one of them the other's record. The all-time map is
    the fallback and only for names that belong to exactly one player across
    the whole archive, which is what makes it safe.
    """
    r = pl.read_parquet(get_path("raw") / "rosters.parquet")
    col = "player_name" if "player_name" in r.columns else "full_name"
    # A BLANK ID IS NOT A SECOND PERSON. The roster carries unsigned and
    # practice-squad rows with `player_id` empty rather than null, and counting
    # those as another man made 152 names look shared when almost none were --
    # Quinshon Judkins has one real id and one blank row listed at DL.
    base = (r.select(["season", col, "player_id"]).drop_nulls()
            .filter(pl.col("player_id").str.strip_chars() != "")
            .with_columns(_norm(pl.col(col)).alias("nm")))
    by_season = base.unique(subset=["season", "nm"], keep="first").select(
        ["season", "nm", "player_id"])
    counted = base.group_by("nm").agg(
        pl.col("player_id").n_unique().alias("k"),
        pl.col("player_id").first().alias("any_id"))
    once = counted.filter(pl.col("k") == 1).select(["nm", "any_id"])
    # TWO MEN, ONE NAME, AND THE BOARD PRINTS THE NAME. There are two Michael
    # Carters, a back and a corner; the per-season lookup hands whichever it
    # meets first to both, so one man's chart carried the other's weeks -- five
    # weeks with two games in them, which is not a thing that happens. Neither
    # the page nor a reader can tell them apart, so the honest answer is to
    # show neither rather than to pick one and be wrong half the time.
    both = counted.filter(pl.col("k") > 1).select("nm")
    return by_season, once, both


def _closing() -> pl.DataFrame:
    """One archived price per player, week and market.

    THE CLOSING PRICE, and never one taken after kickoff. A price captured
    in-play is not the number anyone could have bet and would make the history
    a record of what the market knew once it was happening.
    """
    from src.ingest.odds_history import drop_in_play

    h = pl.read_parquet(ARCHIVE)
    if "snapshot" in h.columns:
        close = h.filter(pl.col("snapshot") == "close")
        if close.height:
            h = close
    h = drop_in_play(h)
    # NORMALIZE BEFORE DEDUPING, or the dedupe does not dedupe. Keying on the
    # book's own spelling left Joe Burrow twice in one week because one book
    # writes "Joe Burrow" and another "Joe Burrow (CIN)", and the id has the
    # same problem: this season's rows arrive as `CIN_PIT` where every other
    # season and the weekly stats say `2026_03_CIN_PIT`, so a join on it
    # dropped the only weeks anybody is looking at -- silently, as three rows
    # missing out of sixty-five.
    h = h.with_columns([
        _norm(pl.col("player_name_norm")).alias("nm"),
        pl.when(pl.col("game_id").str.contains(r"^\d{4}_"))
        .then(pl.col("game_id"))
        .otherwise(pl.format("{}_{}_{}", pl.col("season"),
                             pl.col("week").cast(pl.Utf8).str.pad_start(2, "0"),
                             pl.col("game_id")))
        .alias("game_id"),
    ])
    # THE MAIN LINE, NOT WHICHEVER ALTERNATE SORTED LAST. Books hang several
    # points on one player -- Chase at 2.5 for -200 as well as at 7.5 -- and
    # taking the newest capture picked among them arbitrarily, which printed a
    # line nobody was looking at as "his line that week". The main line is the
    # one priced nearest a coin flip; ties go to the latest capture.
    h = (h.with_columns(
            (pl.col("implied_prob") - 0.5).abs().fill_null(9.0).alias("_mid"))
         .sort(["_mid", "captured_at"], descending=[False, True])
         .unique(subset=["season", "week", "game_id", "nm", "market"],
                 keep="first")
         .drop("_mid"))
    by_season, once, both = _ids()
    return (h.join(both, on="nm", how="anti")
            .join(by_season, on=["season", "nm"], how="left")
            .join(once, on="nm", how="left")
            .with_columns(pl.coalesce([pl.col("player_id"),
                                       pl.col("any_id")]).alias("pid"))
            .drop(["player_id", "any_id"]))


def _weekly() -> pl.DataFrame:
    w = pl.read_parquet(get_path("raw") / "weekly_stats.parquet")
    keep = ["game_id", "season", "week", "team", "opponent_team",
            "receptions", "receiving_yards", "rushing_yards", "passing_yards",
            "receiving_tds", "rushing_tds"]
    have = [c for c in keep if c in w.columns]
    return (w.select(have + ["player_id"])
            .rename({"player_id": "pid"})
            # One stat line per man per game. A duplicate would turn one bet
            # into two rows.
            .unique(subset=["game_id", "pid"], keep="first"))


def _first_td() -> pl.DataFrame:
    f = pl.read_parquet(get_path("processed") / "first_tds.parquet")
    return (f.select(["game_id", "td_player_id"])
            .drop_nulls()
            .rename({"td_player_id": "pid"})
            .unique()
            .with_columns(pl.lit(1, dtype=pl.Int64).alias("first")))


def _roster(wk: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Who is a real, matchable player in a season, and which games were played.

    THE TWO FRAMES THAT MAKE A ZERO TELLABLE FROM A TYPO. A quoted man with no
    row in a played game either did not play -- which is a result, and the one
    this table most needs to show -- or is a name the join cannot resolve,
    which is nothing. The difference is whether that name resolves ANYWHERE
    that season. It also throws out the market's own entries: `anytime_td`
    carries "no touchdown" and `first_td` carries "no scorer", and neither is
    a person.
    """
    ros = (wk.group_by(["season", "pid"])
           .agg(pl.col("team").mode().first().alias("team")))
    played = wk.select("game_id").unique()
    return ros, played


def _american(p: pl.Expr) -> pl.Expr:
    """An implied probability as an American price, the way the odds API does.

    Same arithmetic as `odds_api._prob_to_american`, as an expression: a
    favorite is `-100p/(1-p)` and a dog `100(1-p)/p`, rounded. It is here
    rather than imported because that one takes a float and this runs over a
    column, and the shape of the formula is the part worth keeping identical.
    """
    return (pl.when(p >= 0.5)
              .then(-100.0 * p / (1.0 - p))
              .otherwise(100.0 * (1.0 - p) / p)).round(0)


def history(last: int | None = None, players: list[str] | None = None) -> dict:
    """`{market: {player: [[season, week, opp, home, line, odds, did, played,
    other]]}}`.

    `other` is the OPPOSITE side's price — the Under on a line, the No on a
    touchdown — in American odds, or null where the archive never held it.

    Newest first, so a cap keeps the recent weeks rather than the old ones.

    UNGRADED WEEKS ARE DROPPED. A line with no result is not history, and this
    week's own line is on the board already -- it does not belong in the record
    of what has happened.

    A MAN WHO DID NOT PLAY IS A ZERO, NOT A GAP. Joining prices to stat lines
    and keeping the matches silently deletes every week somebody was quoted and
    then sat out -- which is one player-game in nine on receptions, and every
    one of them went under. Deleting them would make this table show a rosier
    record than the one that happened, in exactly the direction that flatters
    a reader into a bet. So a known player, in a played game, with no stat row,
    records nothing: zero catches, zero yards, no touchdown.
    """
    odds = _closing()
    if players is not None:
        odds = odds.filter(pl.col("nm").is_in(players))
    wk = _weekly()
    ftd = _first_td()
    ros, played = _roster(wk)
    # Only real people, only played games. What is left is gradeable whether or
    # not he took a snap.
    odds = (odds.filter(pl.col("pid").is_not_null())
            .join(played, on="game_id", how="inner")
            .join(ros, on=["season", "pid"], how="inner"))
    out: dict = {}
    for mkt, _label, kind, _unit, stat in MARKETS:
        m = odds.filter(pl.col("market") == mkt)
        if m.is_empty():
            continue
        # A MARKER COLUMN, BECAUSE A ZERO AND A VOID ARE NOT THE SAME BET.
        #
        # The fill below is right for the record — a man who did not play
        # recorded nothing, and deleting those weeks would show a rosier
        # history than the one that happened. It is wrong for money: a book
        # voids an anytime-touchdown bet on a player who is inactive and hands
        # the stake back. Counting that as a losing $100 understates the
        # return by exactly the weeks the reader most wants excluded, and
        # nothing downstream could tell the two apart from a zero alone.
        j = m.join(wk.drop("team").with_columns(
                       pl.lit(1, dtype=pl.Int8).alias("_played")),
                   on=["game_id", "pid"], how="left", suffix="_w")
        if j.is_empty():
            continue
        if kind == "line":
            did = pl.col(stat).cast(pl.Float64).fill_null(0.0)
        elif mkt == "anytime_td":
            # A passing touchdown is not an anytime touchdown: the market is
            # who reaches the end zone, not who threw it there.
            did = ((pl.col("receiving_tds").fill_null(0)
                    + pl.col("rushing_tds").fill_null(0)) > 0).cast(pl.Int64)
        else:
            j = j.join(ftd, on=["game_id", "pid"], how="left")
            did = pl.col("first").fill_null(0)
        # FROM THE FIXTURE, NOT THE STAT LINE, which reads AWAY_HOME. A man
        # who did not play has no stat row and still has an opponent.
        sides = pl.col("game_id").str.split("_")
        home_team = sides.list.last()
        away_team = sides.list.get(2)
        home = (home_team == pl.col("team")).cast(pl.Int64)
        opp = pl.when(home_team == pl.col("team")).then(away_team) \
                .otherwise(home_team)
        # THE OTHER SIDE, RECOVERED RATHER THAN ASSUMED.
        #
        # The archive stores one price per player-week — the Yes, or the Over
        # — and for a long time that was the whole story: "what if you had
        # faded him" was a question it could not answer. But `odds_api` writes
        # `overround` as p_yes + p_no, taken from the median of the books
        # that posted BOTH sides, so the other side's implied probability is
        # `overround - implied_prob` exactly. Not a house edge assumed and
        # split; the number the books were actually showing.
        #
        # Null where no book posted the other side, which is most of the
        # touchdown market and almost none of the yardage ones. A null here
        # means no bet rather than a bet at a guessed price.
        #
        # ONLY WHERE THE OTHER SIDE IS A REAL QUOTE. Measured over the whole
        # archive, the recovered probability has a median of 0.556 on
        # receptions and 0.535 on the yardage markets — a two-way line, which
        # is what those are. On anytime touchdown it is 0.996 and on first
        # touchdown 1.000: nobody is posting "will not score" at -999900, and
        # that number is the complement of a longshot rather than a price.
        # Pricing a fade off it would show a 99% win rate for a cent a bet.
        #
        # So the other side exists on the line markets and nowhere else, and
        # the sanity bound catches the handful of two-way rows that went the
        # same way — 25 across 181,000.
        other_p = ((pl.col("overround") - pl.col("implied_prob"))
                   if kind == "line" else pl.lit(None, dtype=pl.Float64))
        j = (j.with_columns([did.alias("did"), home.alias("home"),
                             opp.alias("opp"),
                             pl.col("_played").fill_null(0).cast(pl.Int8)
                               .alias("played"),
                             pl.when(other_p.is_null() | (other_p <= 0.02)
                                     | (other_p >= 0.98))
                               .then(None)
                               .otherwise(_american(other_p))
                               .alias("other_odds")])
             .filter(pl.col("did").is_not_null())
             .sort(["season", "week"], descending=True))
        # ONE MAN PLAYS ONE GAME A WEEK. Six players are left quoted in two
        # fixtures in the same week -- a name the roster does not record as
        # shared, resolving to one id for two people -- and there is no way to
        # say which game was his. The week goes; the rest of his record stays.
        dup = (j.group_by(["nm", "season", "week"])
               .agg(pl.col("game_id").n_unique().alias("g"))
               .filter(pl.col("g") > 1).drop("g"))
        if dup.height:
            j = j.join(dup, on=["nm", "season", "week"], how="anti")
        if last is not None:
            j = j.group_by("nm", maintain_order=True).head(last)
        rows: dict = {}
        for r in j.iter_rows(named=True):
            rows.setdefault(r["nm"], []).append([
                int(r["season"]), int(r["week"]), r["opp"],
                int(r["home"]),
                None if r["point"] is None else float(r["point"]),
                None if r["odds"] is None else int(r["odds"]),
                float(r["did"]) if kind == "line" else int(r["did"]),
                int(r["played"]),
                None if r["other_odds"] is None else int(r["other_odds"]),
            ])
        out[mkt] = rows
    return out


def active(since_season: int, since_week: int) -> list[str]:
    """Players quoted recently enough to be on a board a reader is looking at.

    The inline copy carries these and nobody else. A man quoted twice in 2023
    and never since has a history and no row to hang it on.
    """
    o = _closing()
    return sorted(o.filter((pl.col("season") > since_season)
                           | ((pl.col("season") == since_season)
                              & (pl.col("week") >= since_week)))
                  ["nm"].unique().to_list())


def market_meta() -> list[dict]:
    """What the page needs to draw each market without hardcoding it."""
    return [{"key": k, "label": lab, "kind": kind, "unit": unit}
            for k, lab, kind, unit, _ in MARKETS]


def match_rate() -> dict:
    """How much of the archive found an actual, per market.

    A silent join failure here would empty the section rather than break it,
    which is the shape of bug this project keeps finding. The number is
    asserted in tests rather than printed and forgotten.
    """
    odds = _closing()
    wk = _weekly()
    ros, played = _roster(wk)
    out = {}
    for mkt, _l, _k, _u, _s in MARKETS:
        m = odds.filter(pl.col("market") == mkt)
        if m.is_empty():
            out[mkt] = None
            continue
        hit = (m.filter(pl.col("pid").is_not_null())
               .join(played, on="game_id", how="inner")
               .join(ros, on=["season", "pid"], how="inner").height)
        out[mkt] = hit / m.height
    return out


def for_board(names, last: int | None = 10) -> dict:
    """History keyed by the NAME THE BOARD PRINTS, not by a normalized one.

    The page looks a player up with `row.player`, exactly as it looks up an
    injury. Normalising on the page would mean the same rules written twice --
    once here where a test holds them and once in JavaScript where nothing
    does -- and a rule that drifted would empty the section for a handful of
    players and look like a thin archive.

    So the mapping is done here: every board name is normalized once, matched,
    and the result filed back under the spelling the board uses.
    """
    keys = {}
    for n in names:
        if not n:
            continue
        k = (pl.DataFrame({"n": [n]})
             .select(_norm(pl.col("n")).alias("k"))["k"][0])
        keys.setdefault(k, []).append(n)
    if not keys:
        return {}
    h = history(last=last, players=sorted(keys))
    out: dict = {}
    for mkt, per in h.items():
        for k, rows in per.items():
            for shown in keys.get(k, ()):
                out.setdefault(shown, {})[mkt] = rows
    return out
