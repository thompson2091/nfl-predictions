"""What the model said about a past week, and what happened.

Feeds a week selector: pick an earlier week and see the board as it was rated,
with each pick marked hit or miss.

**Two things could be meant by "what we predicted", and they are not the same.**

  * What the model says NOW about week 3. Reproducible from the feature matrix
    and the current weights, and it is what this module returns.
  * What was actually published at the time. Only `data/tracked_picks.csv`
    preserves that — it records the shortlist's picks at the price they were
    recorded at and is idempotent on (season, week, market, rule, player), so a
    re-run cannot rewrite history.

The per-week CSVs in `output/` are NOT the second thing, even though they look
like it. `predict` overwrites them, and the week-1 and week-2 files were
rewritten on 2026-09-21 when the conversion changed. A week view built on them
answers "how does today's model score a past week", which is a fair question
and a different one. It is labeled as such rather than implied to be a record.

**Unplayed weeks must be excluded by the SCHEDULE, not by the label.** A week
that has not kicked off carries `target = 0` on every candidate, not null — the
candidate pool is densified — so grading against it reads as every pick losing.
Week 3 of 2026 has 812 rows and 0 scorers for exactly that reason. `_played_weeks`
in `tracked_rules` is the gate, and it asks play-by-play rather than the label.
"""
from __future__ import annotations

import sys

import polars as pl

#: How many rows a week keeps. `None` is all of them.
#:
#: It was 100, because the history was inlined in the page and a full season
#: across six markets measured 20MB — a ten-fold page, in a single file
#: uploaded by hand. The cap was the wrong half of that trade: 98% of the rows
#: it threw away were real posted lines with a settled result.
#:
#: The history is now one file per market and week, fetched when a week is
#: opened (`pwa._split_history`), so the page carries an index and a week
#: costs about 60KB when you actually look at it. There is no longer a reason
#: to drop a line that existed.
TOP_N = None


def played_weeks(season: int) -> list[int]:
    """Weeks with play-by-play on disk, in order."""
    from src.evaluation.tracked_rules import _played_weeks

    return sorted(_played_weeks(season))


def _unplayed_games(season: int, week: int) -> set[str]:
    """`game_id` for every fixture this week with no final on the schedule.

    The schedule is the authority on what has finished. Read there rather
    than inferred from the feature matrix, because the matrix is exactly what
    gets it wrong: a row exists for a game that has not been played and its
    label is a truthful 0 about plays that do not exist yet.

    DELEGATED, not re-read. `tracked_rules.unfinished` owns the question and
    answers it for both callers at once — this one wants `game_id`, the pick
    log wants `"AWAY @ HOME"`, and the two reading the schedule separately is
    how the same week came to be graded two different ways.
    """
    from src.evaluation.tracked_rules import unfinished

    return unfinished(season, week)[0]


def week_board(season: int, week: int, target_type: str = "anytime_td",
               top_n: int | None = TOP_N) -> pl.DataFrame:
    """The top of the board for one week, with outcomes where they exist.

    `scored` is null for a week that has not been played, never 0 — the
    difference between "did not score" and "has not happened" is the whole
    reason this function exists.
    """
    from src.utils.paths import get_path

    pred = (get_path("output", target_type)
            / f"predictions_{season}_week{week}.csv")
    if not pred.exists():
        return pl.DataFrame()

    df = pl.read_csv(pred)
    keep = [c for c in ("game_id", "player_name", "team", "probability",
                        "prob_model", "rank", "has_market_price")
            if c in df.columns]
    df = df.select(keep).sort("probability", descending=True)
    if top_n is not None:
        df = df.head(top_n)

    # WHAT THE BOOK CHARGED, ATTACHED BEFORE THE FREEZE, so the frozen row
    # carries the price it was judged against rather than one re-derived
    # later from a deeper archive. See `_with_book` for how far that moves.
    df = _with_book(df, season, week, target_type)
    df = _freeze_board(df, season, week, target_type)

    if week not in set(played_weeks(season)):
        return df.with_columns(pl.lit(None, dtype=pl.Int8).alias("scored"))

    feats = (pl.scan_parquet(get_path("processed", target_type) / "features.parquet")
             .filter((pl.col("season") == season) & (pl.col("week") == week))
             .select(["player_name", "team", "target"])
             .collect()
             .unique(subset=["player_name", "team"], keep="last"))
    before = df.height
    out = df.join(feats, on=["player_name", "team"], how="left")
    assert out.height == before, (
        f"week board join fanned out: {before} -> {out.height}")
    out = out.with_columns(
        pl.col("target").cast(pl.Int8).alias("scored")).drop("target")

    # A WEEK IS NOT A GAME, AND THIS FUNCTION'S WHOLE POINT IS THE DIFFERENCE.
    #
    # The gate above asks whether the WEEK has play-by-play, which on a Monday
    # is true the moment Sunday is over — so every Monday-night player is
    # joined to a feature matrix built from plays that have not happened, his
    # label comes back 0, and the board shows him as having failed to score in
    # a game that kicks off in five hours. On 2026-10-05 that was all 34 ATL
    # and NO players, Bijan Robinson at 57.2% among them, live on the site.
    #
    # `scored` is null for a game without a final, never 0. The docstring
    # above has always said so; it was the week-level test that did not.
    unplayed = _unplayed_games(season, week)
    if unplayed and "game_id" in out.columns:
        out = out.with_columns(
            pl.when(pl.col("game_id").is_in(list(unplayed)))
              .then(None).otherwise(pl.col("scored"))
              .cast(pl.Int8).alias("scored"))

    # WHAT THEY ACTUALLY HAD, beside the tick or the cross. A green row that
    # will not say whether it was one touchdown or three is the question the
    # board most obviously invites and never answered.
    got = _td_actuals(season, week, target_type)
    if not got.is_empty():
        out = out.join(got, on=["player_name", "team"], how="left")
        # TWO SOURCES FOR ONE FACT, RECONCILED OUT LOUD. `scored` comes from
        # the feature matrix and the count from the touchdown table. They are
        # built from the same plays, so they agree — but if a rebuild ever
        # moves one and not the other, a row saying "2 TDs" beside a cross is
        # a visible lie, where a row saying nothing is merely quiet. On
        # disagreement the count is dropped and the grade, which is what the
        # record is scored on, stands.
        hit = (pl.col("td_order") == 1) if target_type == "first_td" \
            else (pl.col("td_count") > 0)
        agrees = (pl.col("scored").is_null()) | (hit.fill_null(False)
                                                 == (pl.col("scored") == 1))
        out = out.with_columns([
            pl.when(agrees).then(pl.col("td_count")).alias("td_count"),
            pl.when(agrees).then(pl.col("td_order")).alias("td_order")])
    return out


def _freeze_board(df: pl.DataFrame, season: int, week: int,
                  target_type: str) -> pl.DataFrame:
    """The board a game kicked off with, kept and served back.

    `predictions_<season>_week<week>.csv` has one unconditional writer and
    every later run overwrites it, so a board rebuilt after the games keeps
    none of what it showed before them. `has_market_price` is the visible
    casualty — it is a predict-time flag and the live odds cache has no
    prices for a finished week — and weeks 3 and 4 of 2026 are on disk
    listing 24 of 498 and 47 of 515 priced players because of it.

    Recording is cheap and happens on every build; serving only begins once
    a game has kicked off. See `src.export.prediction_freeze`.
    """
    try:
        from src.export import prediction_freeze as PF
    except Exception as e:                                       # noqa: BLE001
        print(f"  prediction freeze unavailable ({e})", file=sys.stderr)
        return df
    rows, served, recorded = PF.settle(df.to_dicts(), season, week,
                                       target_type)
    PF.flush()
    # SAID OUT LOUD, because the fallback is invisible: a started game with
    # nothing frozen shows a board rebuilt today, which is the exact thing
    # this exists to stop.
    late = PF.missing(season, week, target_type)
    if late:
        print(f"  week {week} {target_type}: {len(late)} started games have "
              f"no frozen board and are showing a rebuilt one "
              f"({', '.join(late[:4])}{'...' if len(late) > 4 else ''})",
              file=sys.stderr)
    if served or recorded:
        print(f"  week {week} {target_type}: {served} boards served frozen, "
              f"{recorded} recorded", file=sys.stderr)
    if not rows:
        return df
    return pl.DataFrame(rows).select(
        [c for c in df.columns if c in rows[0]])



def _td_actuals(season: int, week: int, target_type: str) -> pl.DataFrame:
    """How many touchdowns each candidate actually scored, and which was first.

    **Counted from the play-by-play, under the same filter the target uses.**
    `td_extractor.extract_tds` selects touchdown plays carrying a scorer and
    then DEDUPLICATES to one row per player per game, because the anytime
    board only ever asks whether someone scored. Counting off that table
    silently caps every hat-trick at one: Saquon Barkley's three against
    Philadelphia in 2024 week 1 read as "1 TD". So the count comes from
    `pbp.parquet` under the identical predicate, and the dedup is the only
    thing not reproduced.

    Not from `weekly_stats` either. Rushing plus receiving touchdowns out of
    the box score is a SECOND definition of one number, and the two disagree
    on exactly the plays worth looking at — a lateral, a lineman falling on
    one in the end zone, a return. A row reading "had 1" beside a red cross
    is worse than a row that says nothing.

    Names cannot be the key. The play-by-play abbreviates them (`D.Henry`),
    the board spells them out (`Derrick Henry`), so the join goes through
    `candidates.parquet`, which holds both along with `player_id`.

    Returns `player_name`, `team`, `td_count` and `td_order` — the latter the
    rank of that player's earliest touchdown among all of the game's, so 1
    means they scored first. Empty when the week has no stored candidates.
    """
    from src.utils.paths import get_path

    pbp_path = get_path("raw") / "pbp.parquet"
    tds_path = get_path("processed", target_type) / f"tds_{target_type}.parquet"
    cand_path = get_path("processed", target_type) / "candidates.parquet"
    empty = pl.DataFrame(schema={"player_name": pl.Utf8, "team": pl.Utf8,
                                 "td_count": pl.Int32, "td_order": pl.Int32})
    if not (pbp_path.exists() and tds_path.exists() and cand_path.exists()):
        return empty

    cand = (pl.scan_parquet(cand_path)
            .filter((pl.col("season") == season) & (pl.col("week") == week))
            .select(["game_id", "player_id", "player_name", "team", "position"])
            .collect())
    if cand.is_empty():
        return empty

    # ONE MAN PER NAME. `week_board` joins its rows on player_name and team,
    # so two players sharing a display name inside one team-week would grade
    # one against the other's touchdowns. `ou_week` drops ambiguous names for
    # the same reason: a wrong number is worse than a missing one, because
    # only the missing one is visible.
    dupes = (cand.group_by(["player_name", "team"]).agg(pl.len().alias("_n"))
             .filter(pl.col("_n") > 1).select(["player_name", "team"]))

    # The predicate is `extract_tds`'s, character for character, minus the
    # dedup. If that filter ever changes, this is the line that has to follow.
    tds = (pl.scan_parquet(pbp_path)
           .filter((pl.col("season") == season) & (pl.col("week") == week)
                   & (pl.col("touchdown") == 1)
                   & pl.col("td_player_id").is_not_null()
                   & (pl.col("td_player_id") != ""))
           .select(["game_id", "play_id", "td_player_id", "td_team"])
           .collect())
    if tds.is_empty():
        return empty

    # WHO COUNTS AS A DEFENSIVE SCORE is decided by the target's own table
    # rather than re-derived here, so the DEF/ST rows cannot drift away from
    # what `build_candidates` marked. A play-by-play scorer absent from it is
    # left unclassified and drops out of the DEF/ST tally instead of being
    # guessed at either way.
    flags = (pl.scan_parquet(tds_path)
             .filter((pl.col("season") == season) & (pl.col("week") == week))
             .select(["game_id", "td_player_id", "is_offensive_td"])
             .collect()
             .unique(subset=["game_id", "td_player_id"], keep="first"))
    tds = tds.join(flags, on=["game_id", "td_player_id"], how="left")

    # ORDER IS OVER EVERY TOUCHDOWN IN THE GAME, counted once per play. A
    # player's second score must not renumber anyone, so this ranks plays and
    # then takes each scorer's earliest.
    tds = tds.with_columns(
        pl.col("play_id").rank("ordinal").over("game_id").cast(pl.Int32)
        .alias("_order"))

    scored_off = (tds.group_by(["game_id", "td_player_id"])
                  .agg([pl.len().cast(pl.Int32).alias("td_count"),
                        pl.col("_order").min().alias("td_order")])
                  .rename({"td_player_id": "player_id"}))
    # A DEF/ST candidate is one row for a whole unit, so its touchdowns are
    # the team's non-offensive ones — the same rule `build_candidates` uses.
    dst = tds.filter(~pl.col("is_offensive_td").fill_null(True))
    scored_dst = (dst.group_by(["game_id", "td_team"])
                  .agg([pl.len().cast(pl.Int32).alias("_dc"),
                        pl.col("_order").min().alias("_do")])
                  .rename({"td_team": "team"}))

    out = (cand.join(scored_off, on=["game_id", "player_id"], how="left")
           .join(scored_dst, on=["game_id", "team"], how="left")
           .with_columns([
               pl.when(pl.col("position") == "DEFST").then(pl.col("_dc"))
               .otherwise(pl.col("td_count")).alias("td_count"),
               pl.when(pl.col("position") == "DEFST").then(pl.col("_do"))
               .otherwise(pl.col("td_order")).alias("td_order")])
           # A candidate absent from the touchdown plays did not score. That
           # is a real zero and not a missing value: the week was played, and
           # every touchdown in it is in that table.
           .with_columns(pl.col("td_count").fill_null(0).cast(pl.Int32))
           .join(dupes, on=["player_name", "team"], how="anti")
           .select(["player_name", "team", "td_count", "td_order"])
           .unique(subset=["player_name", "team"], keep="first"))
    return out


def _with_book(df: pl.DataFrame, season: int, week: int,
               target_type: str) -> pl.DataFrame:
    """Attach what the book charged, de-vigged, for that week.

    The stored per-week file holds only our two numbers — `probability` and
    `prob_model` — so a past week could show what we thought and never what we
    thought it ABOUT.

    **De-vigged by `blend.devig_market`, not by anything written here.** A
    touchdown board is a one-sided many-way market: every price is divided by
    `sum(implied) / expected_scorers`, so a favorite's fair number depends on
    how many OTHER players the book happened to quote. That function's
    docstring records what happened when the population moved — archive depth
    fell from 52 priced players a game to 26.8, and a -100 favorite's "fair"
    probability drifted from 41% to 49% while its true rate stayed near 52%.
    A second de-vig invented here would put a different number beside the same
    player on two screens.

    So the whole week is de-vigged together and the board's rows are selected
    afterwards. Narrowing first would shrink the denominator and inflate every
    price on the page.
    """
    from src.features.odds_features import _normalize_name
    from src.ingest.odds_history import BOOKS_PATH, resolve_game_ids
    from src.models.market_prior import expected_scorers, load_prior
    from src.prediction.blend import devig_market
    from src.utils.paths import get_path

    none_col = pl.lit(None, dtype=pl.Float64).alias("book")
    if not BOOKS_PATH.exists():
        return df.with_columns(none_col)
    o = (pl.scan_parquet(BOOKS_PATH)
         .filter((pl.col("season") == season) & (pl.col("week") == week)
                 & (pl.col("market") == target_type)
                 & pl.col("implied_prob").is_not_null()
                 & pl.col("game_id").is_not_null())
         # `resolve_game_ids` needs the season and week to find the schedule
         # row, so they are carried through rather than projected away.
         .select(["season", "week", "game_id", "player_name_norm",
                  "implied_prob", "captured_at"])
         .collect())
    if o.is_empty():
        return df.with_columns(none_col)
    # The archive holds TWO game-id formats at once: backfilled seasons carry
    # the nflverse id and live captures carry whatever the odds payload said,
    # which for these rows is "Dallas Cowboys @ New York Giants". Joining on it
    # raw matched nothing and returned a null price for every player on the
    # board — silently, because a missing price is a legitimate state.
    o = resolve_game_ids(o)

    # `expected_scorers` reads the prior fitted at train time and needs each
    # game's own lines — the count it expects is a function of the total and
    # the spread, not a league average.
    try:
        prior = load_prior(get_path("models", target_type)
                           / "scorer_rate_prior.json")
        if prior is None:
            return df.with_columns(none_col)
        lines = (pl.scan_parquet(get_path("processed", target_type)
                                 / "features.parquet")
                 .filter((pl.col("season") == season) & (pl.col("week") == week))
                 .select(["game_id", "total_line", "spread_line"])
                 .unique(subset=["game_id"]).collect())
        # The archive's own `week` is the label the capture was filed under,
        # and on live captures it does not always match the game's real week:
        # week 1 of 2026 carried quotes for THIRTY games against a sixteen-game
        # slate. Keeping the archive's word for it left half the board with no
        # price, which reads as "the book did not quote him".
        o = o.filter(pl.col("game_id").is_in(lines["game_id"]))
        if o.is_empty():
            return df.with_columns(none_col)
        # Median across books, on the games this week actually holds. Pooling
        # every capture of the week would average a Tuesday market with a
        # Sunday one and call the result a consensus.
        o = (o.sort("captured_at")
              .group_by(["game_id", "player_name_norm"])
              .agg(pl.col("implied_prob").median().alias("implied_prob")))
        exp = expected_scorers(prior, lines)
        fair = devig_market(o, exp)
    except Exception as e:                                       # noqa: BLE001
        print(f"  book prices unavailable for week {week}: {e}")
        return df.with_columns(none_col)
    if "market_prob" not in fair.columns:
        return df.with_columns(none_col)

    df = df.with_columns(
        pl.col("player_name").map_elements(_normalize_name, return_dtype=pl.Utf8)
        .alias("player_name_norm"))
    before = df.height
    out = (df.join(fair.select(["player_name_norm",
                                pl.col("market_prob").alias("book")])
                   .unique(subset=["player_name_norm"], keep="first"),
                   on="player_name_norm", how="left")
           .drop("player_name_norm"))
    assert out.height == before, "book join fanned out"
    return out



def payload(season: int, target_type: str = "anytime_td",
            top_n: int | None = TOP_N) -> dict:
    """Every played week, keyed by week number, for a week selector.

    Returns `{"weeks": {...}, "played": [...]}`. The current week is NOT here —
    the board already carries it in full, and duplicating it would put two
    copies of the same numbers on one page with nothing keeping them equal.
    """
    weeks, hits = {}, {}
    for w in played_weeks(season):
        b = week_board(season, w, target_type, top_n)
        if b.is_empty():
            continue
        rows = b.to_dicts()
        weeks[str(w)] = rows
        graded = [r for r in rows if r.get("scored") is not None]
        if graded:
            hits[str(w)] = {
                "n": len(graded),
                "hit": int(sum(r["scored"] for r in graded)),
                # What the model expected of exactly these rows. Printed beside
                # the hit count because "34 of 100" means nothing without it.
                "expected": round(sum(r["probability"] for r in graded), 1),
            }
    return {"weeks": weeks, "played": sorted(int(k) for k in weeks),
            "accuracy": hits, "top_n": top_n}

#: The stat each over/under market settles against, in `weekly_stats`.
OU_STAT = {"receptions": "receptions",
           "receiving_yards": "receiving_yards",
           "rushing_yards": "rushing_yards",
           "passing_yards": "passing_yards"}


def ou_week(season: int, week: int, market: str,
            top_n: int | None = TOP_N) -> list[dict]:
    """One over/under market, one played week, with the line settled.

    Rebuilt rather than read back. There are no stored per-week files for
    these markets — only the touchdown boards write one — so the row is
    reconstructed from the archived odds and the current model, which makes it
    "how today's model rates that week" and not a record of what was served.
    Same caveat the touchdown view carries, and for a stronger reason here.

    `won` is graded on the side the MODEL would have taken, not on the over:
    a line is not a bet until something picks a side, and grading every row as
    an over would report the market's own coin flip as our record.
    """
    import importlib.util
    from pathlib import Path

    from src.utils.paths import get_path

    spec = importlib.util.spec_from_file_location(
        "site_export", Path(__file__).resolve().parents[2]
        / "scripts/47_export_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if market == "receptions":
        # Receptions is built by the dashboard exporter, not by `yards`, so it
        # is reached through its own `board_for_week`. Calling
        # `_receptions_projections` here returned nothing at all: it decorates
        # rows that something else has already put in the payload.
        import importlib.util as _il

        spec2 = _il.spec_from_file_location(
            "dash_export", Path(__file__).resolve().parents[2]
            / "scripts/34_export_dashboard.py")
        dash = _il.module_from_spec(spec2)
        spec2.loader.exec_module(dash)
        blk = dash.receptions(season, week)
    else:
        blk = mod.yards(market, season, week)
    rows = (blk or {}).get("rows") or []
    if not rows:
        return []

    stat = OU_STAT.get(market)
    ws = (pl.scan_parquet(get_path("raw") / "weekly_stats.parquet")
          .filter((pl.col("season") == season) & (pl.col("week") == week))
          .select(["player_display_name", stat])
          .rename({"player_display_name": "player_name", stat: "actual"})
          .collect())
    # Two players can share a display name in one week — "Byron Young" and
    # "Marcus Harris" both appear twice in 2026 week 1. `dict(zip(...))` keeps
    # whichever came last and grades one man against the other's stat line,
    # silently. An ambiguous name is left ungraded instead: a wrong result is
    # worse than a missing one, because only the missing one is visible.
    dupes = (ws.group_by("player_name").agg(pl.len().alias("_n"))
             .filter(pl.col("_n") > 1)["player_name"].to_list())
    actual = {k: v for k, v in zip(ws["player_name"].to_list(),
                                   ws["actual"].to_list())
              if k not in set(dupes)}

    out = []
    for r in rows:
        line = r.get("point") if r.get("point") is not None else r.get("open_point")
        if line is None:
            continue
        got = actual.get(r.get("player_name"))
        ours = r.get("ours")
        # The side our number implies, then whether that side landed. A row
        # we had no opinion on is carried with `won` null rather than dropped:
        # the week's board included it, and hiding it would flatter the record.
        side = None if ours is None else ("over" if ours >= 0.5 else "under")
        won = None
        if got is not None and side is not None and float(got) != float(line):
            won = (float(got) > float(line)) == (side == "over")
        out.append({
            "player_name": r.get("player_name"), "game_id": r.get("game_id"),
            "line": line, "side": side,
            "ours": ours, "model": r.get("model_only"), "book": r.get("fair_prob"),
            "proj": r.get("proj") if r.get("proj") is not None else r.get("mu"),
            "lo": r.get("lo"), "hi": r.get("hi"),
            "odds": r.get("odds"), "edge": r.get("edge_pp"),
            "actual": got, "won": won,
        })
    # By how far our number sits from the book's, which is what a week view is
    # read for — the disagreements, not the alphabet.
    out.sort(key=lambda r: -(abs(r["edge"]) if r.get("edge") is not None else -1))
    return out if top_n is None else out[:top_n]


def ou_payload(season: int, market: str,
               top_n: int | None = TOP_N) -> dict:
    """Every played week of one over/under market, keyed by week number.

    Shaped like `payload` so the page can render either from one code path.
    `accuracy` counts the side our number took, and prints the count it was
    taken from — "47 of 95" means nothing without the 95.
    """
    weeks, acc = {}, {}
    for w in played_weeks(season):
        rows = ou_week(season, w, market, top_n)
        if not rows:
            continue
        weeks[str(w)] = rows
        graded = [r for r in rows if r.get("won") is not None]
        if graded:
            acc[str(w)] = {"n": len(graded),
                           "hit": sum(1 for r in graded if r["won"]),
                           # No expectation printed here. On a two-sided line
                           # our own probability IS the expectation, and
                           # summing it would compare the rule to itself.
                           "expected": None}
    return {"weeks": weeks, "played": sorted(int(k) for k in weeks),
            "accuracy": acc, "top_n": top_n, "kind": "ou"}
