import json
import pickle
from pathlib import Path
import numpy as np
import polars as pl
from src.utils.config import get_config, production_model
from src.utils.paths import get_path
from src.models.trainer import get_feature_cols, prepare_data, _filter_low_activity
from src.models.registry import get_model, ensure_registered


def _rank_bucket_lines(target_type: str, model_name: str = None):
    """Return rank bucket accuracy breakdown lines."""
    ensure_registered()
    cfg = get_config()
    if model_name is None:
        model_name = production_model(target_type)
    model_dir = get_path("models", target_type)

    df = pl.read_parquet(get_path("processed", target_type) / "features.parquet")
    df = df.filter(pl.col("target").is_not_null())

    feat_cols_path = model_dir / "feature_cols.pkl"
    if not feat_cols_path.exists():
        return []
    with open(feat_cols_path, "rb") as f:
        feature_cols = pickle.load(f)

    test_season = cfg["splits"]["test_season"]
    test_df = df.filter(pl.col("season") == test_season)

    if test_df.shape[0] == 0:
        return []

    X_test, _ = prepare_data(test_df, feature_cols)

    if model_name == "ensemble":
        weights_path = model_dir / "ensemble_weights.pkl"
        if not weights_path.exists():
            return []
        with open(weights_path, "rb") as f:
            weights = pickle.load(f)
        raw_probs = np.zeros(X_test.shape[0])
        for name, w in weights.items():
            sub = get_model(name).load(model_dir / f"{name}.pkl")
            sub.feature_names = feature_cols
            raw_probs += w * sub.predict_proba(X_test)
    else:
        model_cls = get_model(model_name)
        model = model_cls.load(model_dir / f"{model_name}.pkl")
        model.feature_names = feature_cols
        raw_probs = model.predict_proba(X_test)

    eval_df = test_df.with_columns(pl.Series("prob", raw_probs))
    eval_df = eval_df.with_columns(
        pl.col("prob").rank(descending=True, method="ordinal")
        .over("game_id").alias("pred_rank")
    )
    actual = eval_df.filter(pl.col("target") == 1)
    ranks = actual["pred_rank"].to_list()
    n_games = len(ranks)

    buckets = [(1, 1, "1"), (2, 3, "2-3"), (4, 5, "4-5"),
               (6, 10, "6-10"), (11, 20, "11-20"), (21, 9999, "21+")]

    lines = []
    lines.append(f"Model Accuracy — {model_name} Rank Buckets ({test_season} Test, {n_games} games)")
    lines.append(f"{'=' * 40}")
    lines.append(f"{'Rank':<10} {'Count':>6}  {'Pct':>7}  {'Cumul':>7}")
    lines.append(f"{'-' * 40}")

    cumul = 0
    for lo, hi, label in buckets:
        count = sum(1 for r in ranks if lo <= r <= hi)
        pct = count / n_games * 100
        cumul += pct
        lines.append(f"{label:<10} {count:>4}    {pct:5.1f}%   {cumul:5.1f}%")

    lines.append("")
    return lines


def _game_pick_lines(result: pl.DataFrame, top_n: int = 5):
    """Return formatted top-N picks per game as lines."""
    lines = []
    lines.append(f"Week Predictions — Top {top_n} per Game")
    lines.append(f"{'=' * 52}")

    for game_id in sorted(result.select("game_id").unique()["game_id"].to_list()):
        game = result.filter(pl.col("game_id") == game_id)
        label = game["game_label"][0]
        lines.append("")
        lines.append(f"{label}")
        for row in game.head(top_n).iter_rows(named=True):
            pct = row["probability"] * 100
            lines.append(f"  {row['rank']:>2}. {row['player_name']:25s} {row['team']:3s}  {pct:5.1f}%")

    lines.append("")
    return lines


def blend_weight_needs_fit(stored: dict | None, eligible: int, min_rows: int,
                           first_clean: int,
                           last_clean: int | None = None) -> bool:
    """Should the blend weight be refitted, given what is already stored.

    Refitting replays the whole odds archive through the model, so it should
    happen when the eligible rows have grown or the eligibility rule has moved,
    and not otherwise.

    The comparison has to be like for like, and it was not. `eligible` counts
    the archive rows going *in*; the stored `n_rows` counts what survived the
    join with model predictions, which is always fewer — 6,985 of 7,624 on
    anytime TD. Comparing the two made the condition permanently true, so every
    `make predict` replayed the entire archive and rewrote `blend_weight.json`.
    The weight it landed on differed only in the eleventh decimal, so nothing
    looked wrong; it just did the most expensive step in prediction every time,
    and made the served artifacts impossible to match against a locked version.

    Artifacts written before `eligible_rows` existed fall back to `n_rows`, so
    they refit exactly once and then settle.

    `last_clean` moves once a year, when a season finishes. An artifact fitted
    under the old window has to be refitted under the new one, and an artifact
    written before the cap existed carries no `max_season` at all — both read
    as a changed rule here, which is the same test `min_season` already gets.
    """
    if eligible < min_rows:
        return False
    if stored is None or stored.get("source") != "fitted":
        return True
    if int(stored.get("min_season", -1)) != first_clean:
        return True
    if last_clean is not None and int(stored.get("max_season", -1)) != last_clean:
        return True
    return int(stored.get("eligible_rows", stored.get("n_rows", 0))) < eligible


def _anchor_to_market(result: pl.DataFrame, week_df: pl.DataFrame,
                      model_dir, cfg: dict, season: int, week: int,
                      target_type: str = "anytime_td",
                      model_name: str | None = None,
                      persist: bool = True) -> pl.DataFrame:
    """Level-calibrate anytime-TD probabilities, then blend with the market."""
    from src.models.market_prior import load_prior, expected_scorers
    from src.prediction.blend import (
        calibrate_level, devig_market, blend, fit_blend_weight,
        load_blend_weight, save_blend_weight,
    )

    bcfg = cfg.get("blend", {})
    if not bcfg.get("enabled", True):
        return result.with_columns(pl.col("raw_prob").alias("probability"))

    prior = load_prior(model_dir / "scorer_rate_prior.json")
    if prior is None:
        print("  No scorer-rate prior found — run `make train` to fit one. "
              "Falling back to raw probabilities.")
        return result.with_columns(pl.col("raw_prob").alias("probability"))

    # Expected scorers for each game, from its betting lines.
    games = week_df.group_by("game_id").agg([
        pl.col("total_line").first(), pl.col("spread_line").first(),
    ])
    expected = expected_scorers(prior, games)
    print(f"  Expected scorers/game (fitted prior): "
          f"{expected['expected_scorers'].mean():.2f}")

    # Load the market first: the level calibration below needs to know who was
    # priced. Roughly five candidates a game never are, and they account for
    # well under 1% of actual scorers, so normalizing the total across all of
    # them hands ~10% of the probability mass to players who essentially never
    # score and leaves every priced player short.
    market = _load_market(week_df, expected, season, week, target_type)
    if market is not None and market.height > 0:
        result = result.with_columns(
            _norm_name_expr("player_name").alias("player_name_norm")
        ).join(
            market.select(["game_id", "player_name_norm", "market_prob"]),
            on=["game_id", "player_name_norm"], how="left",
        )
    else:
        result = result.with_columns(pl.lit(None, dtype=pl.Float64).alias("market_prob"))
        print("  No cached sportsbook prices — publishing model-only probabilities.")

    # Joint structure: the team rate sets the level, the model sets the shares,
    # and P = 1 - exp(-lambda * share). Expected touchdowns sum to lambda by
    # construction, so there is no level to anchor afterwards and nothing for
    # the blend to undo. Falls back to the log-odds shift when the team rate
    # has not been fitted, so an older model directory still predicts.
    from src.models.joint import (UNPRICED_COL, apply_joint, load_conversion,
                                  load_team_rate)
    team_model = load_team_rate(model_dir / "team_td_rate.json")
    conversion = load_conversion(model_dir / "td_conversion.json")

    # Which rows the split conversion level applies to.
    #
    # The split serves unpriced rows at ~0.07 against ~0.94, so a board whose
    # market join has quietly failed would be deflated thirteenfold. "Some row
    # matched" is not enough of a check: loading a past week matched 50 of 500
    # rows and published a board summing to 1.10 expected scorers a game
    # against a true 4.15. The guard is `min_priced_share`, fitted in
    # `trainer.refit_conversion` as the weakest priced share any week in the
    # fit actually had (0.736 over 44 weeks, median 0.822). A real week does
    # not go under what real weeks have gone under; a broken join goes far
    # under it.
    #
    # Below the floor the column is simply not set, which `combine` treats as
    # "all priced" — the behavior before the split existed. Loud, because a
    # board served without it is the old over-predicting board and nothing else
    # would say so.
    conv = conversion or {}
    # MEASURED OVER GAMES STILL TO COME. A started game's prices leave the
    # live cache at kickoff, so by Sunday night the slate reads mostly
    # "unpriced" and the floor below tripped: every row was served at the
    # priced level, and an unpriced player's 7% became 94% (Kyren Williams
    # read 100% on 2026-10-19). Started games are served from the freeze.
    share_rows = result
    try:
        from src.export.prediction_freeze import started_games
        live = started_games(season, week)
        if live and "game_id" in result.columns:
            ahead = result.filter(~pl.col("game_id").is_in(list(live)))
            if ahead.height:
                share_rows = ahead
    except Exception:                                            # noqa: BLE001
        pass
    priced_share = (float(share_rows["market_prob"].is_not_null().mean())
                    if share_rows.height else 0.0)
    floor = conv.get("min_priced_share")
    if conv.get("unpriced_level") is None:
        pass
    elif floor is not None and priced_share < float(floor):
        print(f"  !! Market join looks broken: only {100 * priced_share:.1f}% "
              f"of candidates carry a price, against a fitted floor of "
              f"{100 * float(floor):.1f}% (half the median real week).")
        print(f"     Serving ONE conversion level to every row rather than "
              f"deflating {int((1 - priced_share) * result.height)} of "
              f"{result.height} of them. The board will over-predict in "
              f"aggregate, which is the lesser error.")
    else:
        result = result.with_columns(
            pl.col("market_prob").is_null().alias(UNPRICED_COL))
        n_un = int(result[UNPRICED_COL].sum())
        print(f"  Unpriced players: {n_un} of {result.height} "
              f"({100 * priced_share:.1f}% priced) served at conversion level "
              f"{conv.get('unpriced_level')}")

    if team_model is not None:
        result = apply_joint(result, week_df, team_model,
                             score_col="raw_prob", out_col="prob_calibrated",
                             conversion=conversion)
        print(f"  Joint model: team rate {team_model['mean_team_tds']:.2f} "
              f"TDs/team-game x model share")
    else:
        share = float(prior.get("priced_share", 1.0))
        result = result.with_columns(
            pl.col("market_prob").is_not_null().alias("is_priced"))
        if result["is_priced"].any():
            result = calibrate_level(
                result, "raw_prob",
                expected.with_columns(pl.col("expected_scorers") * share),
                out_col="prob_calibrated", mask_col="is_priced",
            )
            print(f"  Level anchored over priced players (share {share:.3f})")
        else:
            result = calibrate_level(result, "raw_prob", expected,
                                     out_col="prob_calibrated")

    # The positional correction exists because one per-game log-odds shift
    # cannot fix a bias that varies by rank within that game. The joint model
    # does not have that problem — the team rate sets the level and the shares
    # carry the within-game shape — and stacking the two is destructive. Its
    # per-rank deltas are additive and not monotone in rank (rank 4 corrected
    # by +0.115 against rank 1's +0.040), so the order-preserving clamp
    # collapses the top ranks into ties and ordinal tie-breaking then picks
    # among them arbitrarily. Measured on 2025 that took AUC from 0.862 to
    # 0.497 and Top-1 from 52.3% to 11.7%.
    from src.models.rank_calibration import apply_rank_calibration, load as load_rank
    rank_calib = None if team_model is not None else load_rank(
        model_dir / "rank_calibration.json")
    if rank_calib:
        result = apply_rank_calibration(
            result, rank_calib, "prob_calibrated", out_col="prob_calibrated"
        )
        print(f"  Rank calibration applied "
              f"({len(rank_calib.get('deltas', {}))} ranks, order preserved)")

    # Weight: fitted from graded history when we have enough, else the declared
    # bootstrap from config.
    #
    # `load_graded_history` returns prices and outcomes but no model
    # predictions, and `fit_blend_weight` needs all three — so passing it
    # straight through returned None on every run and the blend sat on its
    # bootstrap 0.50 forever, across 32,194 graded player-games. The archive has
    # to go back through the production path first; that is what
    # `build_blend_training_frame` is for, and it was written for this and then
    # never wired in here.
    from src.ingest.odds_history import load_graded_history
    from src.prediction.blend import build_blend_training_frame

    weight_path = model_dir / "blend_weight.json"
    graded = load_graded_history(target_type)
    min_rows = bcfg.get("min_history_rows", 500)

    # Only seasons this model neither trained on nor early-stopped against can
    # say how much it needs the market. Fitting over the whole archive asked a
    # model about its own homework: on anytime TD that returned w=0.21 where
    # the clean seasons say 0.60 — roughly twice as much trust in the model as
    # the evidence supports. See build_blend_training_frame's docstring.
    first_clean = int(cfg["splits"]["val_season"]) + 1
    # AND NOT THE SEASON BEING BET. `first_clean` keeps the model's own
    # homework out; this keeps out the season whose board this weight is about
    # to price. Without it the weight was fitted on 2025-2026 and refitted
    # itself whenever another week graded — a served constant moving weekly on
    # live results, with no promotion point, which is the one thing the
    # improvement loop says never to do.
    last_clean = int(cfg["seasons"]["end"])
    eligible = (0 if graded is None
                else graded.filter((pl.col("season") >= first_clean)
                                   & (pl.col("season") <= last_clean)).height)

    # Refitting replays the archive through the model, so do it only when the
    # eligible rows have grown or the eligibility rule itself has moved. Both
    # halves matter: comparing against the *whole* archive instead would refit
    # on every single run, because the eligible count is permanently smaller.
    stored = None
    if weight_path.exists():
        try:
            stored = json.loads(weight_path.read_text())
        except Exception:
            stored = None
    # `persist` also gates the refit, not just the save. Refitting writes back
    # into `model_dir`, and when that is a locked version snapshot the write
    # edits the record itself — the manifest's hashes would stop describing the
    # files they name.
    needs_fit = persist and blend_weight_needs_fit(
        stored, eligible, min_rows, first_clean, last_clean)
    if needs_fit:
        print(f"  Fitting blend weight on {eligible:,} graded player-games from "
              f"{first_clean} to {last_clean} "
              f"(replaying the archive through the model)...")
        history = build_blend_training_frame(target_type, model_name,
                                             min_season=first_clean,
                                             max_season=last_clean)
        fitted = fit_blend_weight(history, min_rows=min_rows)
        if fitted is not None:
            fitted["min_season"] = first_clean
            fitted["max_season"] = last_clean
            fitted["eligible_rows"] = eligible
            save_blend_weight(fitted, weight_path)
            print(f"  Blend weight FITTED on {fitted['n_rows']:,} graded "
                  f"player-games: market={fitted['market_weight']:.2f}")
    weight = load_blend_weight(weight_path, bcfg.get("bootstrap_market_weight"))
    if weight.get("source") == "bootstrap":
        n = 0 if graded is None else graded.height
        print(f"  Blend weight BOOTSTRAP (market={weight['market_weight']:.2f}) — "
              f"{eligible:,} of {n:,} archived rows are from {first_clean} to "
              f"{last_clean}; {min_rows:,} needed before a weight can be "
              f"fitted.")

    result = blend(result, "prob_calibrated", "market_prob", weight,
                   out_col="probability")
    return result


def _first_td_market_blend(result: pl.DataFrame, week_df: pl.DataFrame,
                           model_dir, cfg: dict, season: int, week: int,
                           model_name: str, persist: bool) -> pl.DataFrame:
    """First TD: the model's within-game number, moved toward the book's.

    The model's own number is kept as `prob_model` (it becomes the
    `prob_calibrated` the shared select below exports under that name) and
    `probability` becomes the blend, the same split anytime TD serves. See
    `blend.blend_first_td` for why the blend is geometric within the game and
    why unpriced players cannot be moved by it.

    The weight is fitted from walk-forward backtests on the odds-covered
    seasons and written once; delete `blend_weight.json` to refit it.
    """
    from src.prediction.blend import (blend_first_td, first_td_blend_frame,
                                      fit_first_td_blend, load_blend_weight,
                                      save_blend_weight)

    result = result.with_columns(pl.col("probability").alias("prob_calibrated"))
    weight_path = model_dir / "blend_weight.json"
    if not weight_path.exists() and persist:
        from src.models.trainer import _odds_covered_seasons
        seasons = [s for s in _odds_covered_seasons("first_td") if s < season]
        fitted = fit_first_td_blend(first_td_blend_frame(seasons, model_name))
        if fitted is not None:
            save_blend_weight(fitted, weight_path)
            print(f"  First-TD blend weight FITTED on {fitted['n_games']:,} "
                  f"walk-forward games: market={fitted['market_weight']:.2f}")
    if not weight_path.exists():
        print("  No first-TD blend weight — publishing the model's number.")
        return result
    weight = load_blend_weight(weight_path)

    # One first scorer a game. The level is irrelevant to the blend, which
    # uses only each side's within-game shares, but `devig_market` needs one.
    expected = week_df.select("game_id").unique().with_columns(
        pl.lit(1.0).alias("expected_scorers"))
    market = _load_market(week_df, expected, season, week, "first_td")
    if market is None or market.height == 0:
        print("  No cached first-TD prices — publishing the model's number.")
        return result
    result = result.with_columns(
        _norm_name_expr("player_name").alias("player_name_norm")
    ).join(market.select(["game_id", "player_name_norm", "market_prob"])
           .unique(subset=["game_id", "player_name_norm"], keep="first"),
           on=["game_id", "player_name_norm"], how="left")
    result = blend_first_td(result, "prob_calibrated", "market_prob", weight,
                            out_col="probability")
    print(f"  First-TD blend: market weight {weight['market_weight']:.2f}, "
          f"{int(result['has_market_price'].sum())} of {result.height} priced")
    return result


def _norm_name_expr(col: str) -> pl.Expr:
    e = pl.col(col).str.to_lowercase().str.strip_chars()
    for suffix in [" jr.", " sr.", " ii", " iii", " iv", " jr", " sr"]:
        e = e.str.replace(rf"{suffix}$", "")
    return e.str.replace_all(r"\.", "").str.strip_chars()


def _load_market(week_df: pl.DataFrame, expected: pl.DataFrame,
                 season: int, week: int,
                 target_type: str = "anytime_td") -> pl.DataFrame | None:
    """De-vigged market probabilities for this slate.

    Reads the odds cache directly rather than relying on `sbook_*` columns baked
    into features.parquet — prices move every week, and rebuilding the full
    feature history just to refresh them is both slow and easy to forget.
    """
    from src.prediction.blend import devig_market

    market = _market_from_cache(season, week, target_type)
    if market is None and "sbook_anytime_td_implied" in week_df.columns:
        market = (
            week_df.select(["game_id", "player_name", "sbook_anytime_td_implied"])
            .filter(pl.col("sbook_anytime_td_implied") > 0)
            .rename({"sbook_anytime_td_implied": "implied_prob"})
            .with_columns(_norm_name_expr("player_name").alias("player_name_norm"))
        )
    if market is None or market.height == 0:
        return None

    # Only de-vig the players this week's board will actually contain. The
    # one-sided normalization divides by sum(implied), so quoting extra deep
    # longshots drags every favorite down — see devig_market's docstring.
    candidates = week_df.select([
        _norm_name_expr("player_name").alias("player_name_norm"), "game_id",
    ]).unique()
    scored = market.join(candidates, on=["game_id", "player_name_norm"],
                         how="inner")
    if scored.height >= 5:
        market = scored
    return devig_market(market, expected)


def _market_from_cache(season: int, week: int,
                       target_type: str = "anytime_td") -> pl.DataFrame | None:
    """Sportsbook prices for one market, keyed to this week's game_ids.

    `target_type` used to be absent and the anytime-TD list read unconditionally,
    so the First TD board was built on anytime-TD prices: the same 75 players at
    the same odds, with Marquez Valdes-Scantling quoted +1000 to score first and
    +1000 to score at all. The de-vig hid it — it rescales whatever it is given
    to the market's expected scorer count, so `market_prob` came out plausibly
    small for first TD while the American price underneath was wrong.

    Everything downstream inherited it: the Odds column, Bookmaker says, the
    edge, the highlight labels, EV and Kelly. Only the live board was affected;
    the backtests read `load_graded_history(target_type)`, which filters by
    market properly, which is why the two never disagreed on anything that would
    have exposed it.
    """
    try:
        from src.ingest.odds_api import load_cached_odds
        from src.features.odds_features import TEAM_ABBREV
    except Exception:
        return None

    odds = load_cached_odds()
    if not odds:
        return None

    schedules = pl.read_parquet(get_path("raw") / "schedules.parquet")
    sched = schedules.filter(
        (pl.col("season") == season) & (pl.col("week") == week)
    ).select(["game_id", "home_team", "away_team"])
    key = {(h, a): g for g, h, a in zip(
        sched["game_id"], sched["home_team"], sched["away_team"])}

    rows = []
    for game in odds.values():
        gid = key.get((TEAM_ABBREV.get(game.get("home_team", "")),
                       TEAM_ABBREV.get(game.get("away_team", ""))))
        if gid is None:
            continue
        for p in game.get(target_type, []):
            rows.append({
                "game_id": gid,
                "player_name_norm": p["player"],
                # The American price is what you're actually paid — bets.py needs
                # it for EV and Kelly, so it must survive this hop.
                "odds": p.get("odds"),
                "implied_prob": p["implied_prob"],
                "fair_prob": p.get("fair_prob"),
            })
    if not rows:
        return None
    return pl.DataFrame(rows).with_columns(
        _norm_name_expr("player_name_norm").alias("player_name_norm")
    )


def check_distribution_shift(week_df: pl.DataFrame, train_df: pl.DataFrame,
                             feature_cols: list[str], threshold: float = 0.5,
                             top_n: int = 15,
                             is_live: bool = True) -> list[str]:
    """Warn when predict-time feature *values* sit far from their training range.

    The nullness check below catches features that vanish. It is blind to the
    opposite failure, which is the one that actually happened: carry-forward
    filled week 1 of the predict season with the previous season's state, so
    nine features arrived *more* populated than in any training week and with
    means up to twice what the model had ever seen. Nothing was null, nothing
    warned, and the board quietly scored rows from a distribution it had never
    been fitted on.

    Shift is measured in training standard deviations, which makes one threshold
    meaningful across features on wildly different scales. Nulls are filled with
    zero on both sides first, because that is what `prepare_data` feeds the
    model — comparing the non-null values only would describe a matrix nobody
    scores.
    """
    if train_df is None or train_df.height == 0 or week_df.height == 0:
        return []

    # A season or week index shifts by definition — 2026 is always further from
    # the mean than 2020, and week 1 is always further than week 9. Flagging
    # them every single run is what teaches you to skim the list.
    time_indices = {"season", "season_right", "week", "week_num"}

    shifted = []
    for c in feature_cols:
        if c in time_indices:
            continue
        if c not in week_df.columns or c not in train_df.columns:
            continue
        try:
            a = train_df[c].cast(pl.Float64).fill_null(0.0)
            b = week_df[c].cast(pl.Float64).fill_null(0.0)
        except Exception:
            continue
        sd = a.std()
        if sd is None or sd == 0 or a.mean() is None or b.mean() is None:
            continue
        z = abs(b.mean() - a.mean()) / sd
        if z > threshold:
            shifted.append((c, float(a.mean()), float(b.mean()), float(z)))

    if shifted:
        print(f"\n  !! DISTRIBUTION SHIFT: {len(shifted)} feature(s) sit more than "
              f"{threshold} training SDs from where the model was fitted.")
        if is_live:
            print("     This is the board you would bet. Nothing downstream will "
                  "fail; the model will simply score rows unlike anything it was")
            print("     fitted on. Explain each family below before trusting the "
                  "output.")
        else:
            print("     This is a replay of a past week, so some drift is normal "
                  "— but it is not automatically noise. The last time these were")
            print("     waved through, the cause was carry-forward filling week 1 "
                  "of the predict season and no other season.")

        # Grouped by family rather than listed one by one. Seventeen individual
        # lines read as noise; "every personnel feature at once" reads as a
        # broken join, which is what it usually is.
        families: dict[str, list] = {}
        for c, was, now, z in shifted:
            fam = c.rsplit("_szn", 1)[0].rsplit("_avg_", 1)[0]
            fam = fam.rsplit("_", 1)[0] if "_" in fam else fam
            families.setdefault(fam, []).append((c, was, now, z))
        ranked = sorted(families.items(), key=lambda kv: -max(x[3] for x in kv[1]))
        for fam, items in ranked[:top_n]:
            worst = max(items, key=lambda x: x[3])
            extra = f"  (+{len(items) - 1} more in this family)" if len(items) > 1 else ""
            print(f"       {fam:38s} worst {worst[3]:.1f} SD: "
                  f"{worst[1]:.3f} -> {worst[2]:.3f}{extra}")
        if len(ranked) > top_n:
            print(f"       ... and {len(ranked) - top_n} more families")
    return [c for c, _, _, _ in shifted]


def check_feature_skew(week_df: pl.DataFrame, feature_cols: list[str],
                       model_dir, threshold: float = 0.35) -> list[str]:
    """Warn when predict-time features are far more null than they were in training.

    This is the check that would have caught the 2025 weekly-stats gap: a whole
    block of player_* features silently went 100% null at predict time while the
    model had been trained on populated values, and `prepare_data` turned them
    into 0.0 without complaint. Probabilities inflated ~2.7x with no error raised.

    Only catches features going *missing*. For values drifting while staying
    populated, see `check_distribution_shift` — the two failures are different
    and this one is blind to the second.
    """
    path = model_dir / "train_null_rates.pkl"
    if not path.exists():
        return []
    with open(path, "rb") as f:
        train_nulls = pickle.load(f)

    degraded = []
    for c in feature_cols:
        if c not in week_df.columns or c not in train_nulls:
            continue
        now = float(week_df[c].is_null().mean())
        if now - train_nulls[c] > threshold:
            degraded.append((c, train_nulls[c], now))

    if degraded:
        print(f"\n  !! FEATURE SKEW: {len(degraded)} feature(s) far more null than in training.")
        print("     These become 0.0 and push probabilities off-distribution:")
        for c, was, now in sorted(degraded, key=lambda r: r[2] - r[1], reverse=True)[:15]:
            print(f"       {c:45s} train={was:.2f} -> now={now:.2f}")
        if len(degraded) > 15:
            print(f"       ... and {len(degraded) - 15} more")
    return [c for c, _, _ in degraded]


# Statuses a player can be on and still take a snap this week. ACT is obvious;
# DEV is the practice squad, which is kept deliberately — a team may elevate up
# to two practice-squad players per game and pre-kickoff there is no way to know
# which, so dropping them would remove players who do play. Everything else the
# feed emits (CUT, RES, RET, EXE, INA, PUP, the TR* trade codes, the E** and W**
# exempt/waiver codes) means unavailable for this game.
_AVAILABLE_STATUSES = frozenset({"ACT", "DEV"})


def _filter_unavailable(week_df: pl.DataFrame, season: int, week: int) -> pl.DataFrame:
    """Drop players the roster says cannot play — for a live board only.

    This is an availability rule, not a modeling one, and the distinction is
    the reason it is here rather than in `_filter_low_activity`. That filter is
    applied identically in training and at serve time because changing it on one
    side only is train/serve skew. This one is applied to the board you would
    bet and to nothing else: removing unavailable players from a *played* week
    would strip true negatives out of every backtest denominator and quietly
    move reported accuracy, so historical scoring runs keep the full pool.

    Rows whose player_id does not appear in the roster feed are KEPT, not
    dropped. Team DEF/ST candidates have no roster row by construction, and a
    week whose rosters have not been ingested yet joins to null for everyone —
    in both cases the safe reading of "no status" is "no evidence of absence".
    An unavailable player scored is a bet you cannot place; a player wrongly
    removed is a bet you never see.
    """
    from src.utils.paths import get_path

    roster_path = get_path("raw") / "rosters.parquet"
    if not roster_path.exists():
        return week_df

    status = (
        pl.read_parquet(roster_path, columns=["player_id", "season", "week", "status"])
        .filter((pl.col("season") == season) & (pl.col("week") == week))
        .unique(subset=["player_id"], keep="last")
        .select(["player_id", "status"])
    )
    if status.height == 0:
        print(f"  !! No roster rows for {season} week {week} — availability "
              f"unchecked. Run `make ingest` before betting this board.")
        return week_df

    before = week_df.height
    joined = week_df.join(status, on="player_id", how="left")
    dropped = joined.filter(
        pl.col("status").is_not_null()
        & ~pl.col("status").is_in(list(_AVAILABLE_STATUSES))
    )
    if dropped.height == 0:
        return week_df

    counts = (dropped.group_by("status").agg(pl.len())
              .sort("len", descending=True))
    summary = ", ".join(f"{r['status']} {r['len']}" for r in counts.to_dicts())
    print(f"Filtered {before} -> {before - dropped.height} candidates "
          f"(unavailable: {summary})")

    return (joined.filter(
        pl.col("status").is_null()
        | pl.col("status").is_in(list(_AVAILABLE_STATUSES))
    ).drop("status"))


def _keep_started(result: pl.DataFrame, csv_path, season: int,
                  week: int) -> pl.DataFrame:
    """The new board, with every started game's rows taken from the old file.

    This CSV had one unconditional writer, and every run after kickoff
    rewrote games already being played: the live odds cache holds no price
    for a game under way, so `has_market_price` went false and week 4 of 2026
    went from a full slate to 47 priced players of 515. A started game's rows
    are a record of what was predicted; only games still to come are rebuilt.
    Kickoff is `prediction_freeze.started_games`, the same gate the freezes
    use. A game with no old rows takes the new ones — a late board beats none.
    """
    from pathlib import Path

    p = Path(csv_path)
    if not p.exists() or "game_id" not in result.columns:
        return result
    try:
        from src.export.prediction_freeze import started_games

        live = started_games(season, week)
    except Exception:                                            # noqa: BLE001
        return result
    if not live:
        return result
    try:
        old = pl.read_csv(p, infer_schema_length=0)
    except Exception:                                            # noqa: BLE001
        return result
    if "game_id" not in old.columns:
        return result
    held = old.filter(pl.col("game_id").is_in(list(live)))
    have = set(held["game_id"].unique().to_list())
    if not have:
        return result
    cols = [c for c in result.columns if c in held.columns]
    # Read back as text, so each column is cast to the new board's type.
    # A boolean is spelled `true`/`false` in the CSV and polars will not cast
    # that string directly.
    held = held.select(cols).with_columns(
        [(pl.col(c).str.to_lowercase() == "true")
         if result.schema[c] == pl.Boolean
         else pl.col(c).cast(result.schema[c], strict=False) for c in cols])
    fresh = result.filter(~pl.col("game_id").is_in(list(have)))
    print(f"  kept {held.height} rows for {len(have)} started games from the "
          f"previous board rather than rebuilding them")
    return pl.concat([fresh, held], how="diagonal_relaxed").select(result.columns)


def predict(season: int, week: int, model_name: str = None,
            target_type: str = None, model_dir=None,
            persist: bool = True) -> pl.DataFrame | None:
    """Generate predictions for a given season/week.

    `model_dir` loads from somewhere other than `models/<target_type>/` — a
    locked version snapshot, so the app can show what an earlier version would
    have said without promoting it.

    `persist=False` makes this read-only. It must be passed whenever
    `model_dir` points at a snapshot: prediction otherwise writes the week's
    CSV and TXT over the published ones, and the blend-weight refit writes back
    into the model directory, which would edit a locked snapshot and leave its
    manifest describing files that no longer exist.
    """
    ensure_registered()
    cfg = get_config()
    if target_type is None:
        target_type = cfg["target"]["type"]
    if model_name is None:
        model_name = production_model(target_type)

    model_dir = Path(model_dir) if model_dir else get_path("models", target_type)
    feat_cols_path = model_dir / "feature_cols.pkl"
    if not feat_cols_path.exists():
        print(f"No trained model for target_type={target_type}")
        return None
    with open(feat_cols_path, "rb") as f:
        feature_cols = pickle.load(f)

    df = pl.read_parquet(get_path("processed", target_type) / "features.parquet")
    week_df = df.filter((pl.col("season") == season) & (pl.col("week") == week))

    if week_df.shape[0] == 0:
        print(f"No data for {season} week {week}")
        return None

    # Filter out low-activity candidates (same filter used in training)
    before = week_df.shape[0]
    week_df = _filter_low_activity(week_df)
    if week_df.shape[0] < before:
        print(f"Filtered {before} -> {week_df.shape[0]} candidates (removed low-activity)")

    # Availability, live boards only — see `_filter_unavailable`. Applied before
    # the skew and shift checks below so those diagnostics describe the board
    # actually served rather than a pool containing players who cannot play.
    is_live = (season == cfg["seasons"].get("predict_season"))
    if is_live:
        week_df = _filter_unavailable(week_df, season, week)

    check_feature_skew(week_df, feature_cols, model_dir)
    # Training rows are already in memory from the read above, so comparing
    # against them costs nothing and cannot go stale the way a pickled summary
    # written at training time can.
    # Baseline is the *same week* in earlier seasons, not every week. Season-to-
    # date features are null or thin in week 1 by construction, so comparing
    # week 1 against a season average flags a dozen families every run for a
    # reason that is not a defect. Week-matched, the same check went from 17
    # families to 6 — and those 6 were the real ones.
    prior = df.filter((pl.col("season") < season) & (pl.col("week") == week))
    if prior.height < 200:
        prior = df.filter(pl.col("season") < season)
    check_distribution_shift(
        week_df, prior, feature_cols,
        is_live=is_live,
    )

    X, _ = prepare_data(week_df, feature_cols)

    # Through src.models.scoring.score. This used to load the models and apply
    # their calibrators inline, which made the serving path a private copy of
    # the one that module exists to centralise — and copies drift silently.
    # It did: the copy never picked up the tie-break that separates players
    # sharing an isotonic step, so the board resolved a quarter of games'
    # headline picks by row order while the backtest measuring that board did
    # not. Anything added to `score` has to reach here without being
    # remembered.
    from src.models.scoring import score as _score
    probs = _score(model_name, X, feature_cols, model_dir,
                   active_models=cfg["models"]["active"])

    id_cols = ["game_id", "player_id", "player_name", "team"]
    result = week_df.select(id_cols).with_columns(pl.Series("raw_prob", probs))

    # For first_td: normalize within game (exactly one scorer, probs sum to 100%)
    # For anytime_td: anchor the level to the fitted scorer-rate prior, then
    # blend with the de-vigged market. See src/prediction/blend.py.
    if target_type == "first_td":
        result = result.with_columns(
            (pl.col("raw_prob") / pl.col("raw_prob").sum().over("game_id"))
            .alias("probability")
        )
        if cfg.get("first_td", {}).get("use_market_blend", False):
            result = _first_td_market_blend(result, week_df, model_dir, cfg,
                                            season, week, model_name, persist)
    else:
        result = _anchor_to_market(result, week_df, model_dir, cfg,
                                   season=season, week=week,
                                   target_type=target_type,
                                   model_name=model_name, persist=persist)

    result = result.with_columns(
        pl.col("probability")
        .rank(descending=True, method="ordinal")
        .over("game_id")
        .alias("rank")
    )

    result = result.sort(["game_id", "rank"])

    schedules = pl.read_parquet(get_path("raw") / "schedules.parquet")
    game_labels = schedules.select([
        "game_id",
        (pl.col("away_team") + " @ " + pl.col("home_team")).alias("game_label"),
    ])
    result = result.join(game_labels, on="game_id", how="left")

    # `prob_model` is the pre-blend view, carried alongside the published
    # probability so closing-line value stays measurable. `probability` is
    # blended with the market price, and scoring that against how the market
    # then moves asks whether the price predicts itself — worth 4.4 points of
    # imaginary skill when measured. Betting analysis ranks on this column too,
    # for the reason in src/evaluation/rank_economics.py.
    # `player_id` is the join key for the injury report. Without it the
    # board's `status_for` merge never ran: on 2026 week 6 every one of 413
    # rows read blocked=False, and 19 players listed Out were priced.
    keep = ["game_id", "game_label", "player_id", "player_name", "team",
            "probability", "rank"]
    if "prob_calibrated" in result.columns:
        result = result.with_columns(pl.col("prob_calibrated").alias("prob_model"))
        keep.append("prob_model")
    # Whether a bookmaker priced this player at all. `blend` already computes
    # it and this select used to drop it, which is why every consumer could
    # only ever see the priced half of a slate: `build_board` inner-joins to
    # the market, so a player nobody quoted simply vanished, with nothing
    # distinguishing "we have no view" from "no book has posted yet". Three
    # weeks before a season opens that is most of the card.
    if "has_market_price" in result.columns:
        keep.append("has_market_price")
    result = result.select(keep)

    if not persist:
        # A read-only score: the caller is looking at a version other than the
        # one being served, and the published CSV/TXT describe the served one.
        # Overwriting them would leave `make bets` and the exported site
        # quoting numbers from a model nobody promoted.
        return result

    output_dir = get_path("output", target_type)
    csv_path = output_dir / f"predictions_{season}_week{week}.csv"
    # THE FILE KEEPS STARTED GAMES; THE RETURN VALUE DOES NOT. Callers that
    # score the model — `parity.check` above all — need what this run
    # computed, and handing them last week's rows back would disarm the one
    # test that compares the served path with the evaluated one.
    written = _keep_started(result, csv_path, season, week)
    written.write_csv(csv_path)
    from src.export.run_manifest import append as _manifest

    _manifest(target_type, season, week, model=model_name, rows=written.height,
              priced=(int(written["has_market_price"].cast(pl.Boolean).sum())
                      if "has_market_price" in written.columns else None))

    report_lines = []
    report_lines.append(f"NFL TD Predictions ({target_type}) — {season} Week {week} (model: {model_name})")
    report_lines.append(f"{'=' * 60}")
    report_lines.append("")

    report_lines.extend(_rank_bucket_lines(target_type, model_name))
    report_lines.extend(_game_pick_lines(result))

    report = "\n".join(report_lines)

    txt_path = output_dir / f"predictions_{season}_week{week}.txt"
    with open(txt_path, "w") as f:
        f.write(report)

    print(report)
    print(f"Saved: {csv_path}")
    print(f"Saved: {txt_path}")

    return result
