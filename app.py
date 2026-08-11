"""NFL TD Prediction Dashboard — Streamlit app."""
import sys
sys.path.insert(0, ".")

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

from src.utils.config import get_config
from src.utils.paths import get_path
from src.models.trainer import get_feature_cols, prepare_data, _filter_low_activity
from src.models.registry import get_model, ensure_registered
from src.models.calibration import IsotonicCalibrator
from src.ingest.odds_api import fetch_week_td_props, load_cached_odds
from src.analysis.game_analyst import analyze_edges
from src.prediction.ai_adjustments import get_ai_adjustments, apply_adjustments
from src.features.definitions import get_definition


ensure_registered()

st.set_page_config(
    page_title="NFL TD Predictions",
    page_icon=":material/sports_football:",
    layout="wide",
)

cfg = get_config()
active_models = cfg["models"]["active"]

# ── Sidebar ────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Settings")
    target_type = st.selectbox(
        "Target Type",
        ["first_td", "anytime_td"],
        format_func=lambda x: "First TD Scorer" if x == "first_td" else "Anytime TD Scorer",
    )

    # Build model options: individual models + ensemble (if >1 active)
    model_options = list(active_models)
    if len(active_models) > 1:
        model_options.append("ensemble")
    # Resolved from the market, not once at import: the two markets are best
    # served by different models (lgbm for anytime, ensemble for first), and a
    # single default meant whichever market lost that argument silently ran on
    # a model that measured fourth-best.
    from src.utils.config import production_model
    preferred = production_model(target_type)
    default_model = preferred if preferred in model_options else model_options[0]
    selected_model = st.selectbox(
        "Model",
        model_options,
        index=model_options.index(default_model),
    )

st.title("First TD Scorer" if target_type == "first_td" else "Anytime TD Scorer")

# Two tabs. The goal is the most accurate probability for every player, not a
# hunt for mispriced ones — so there is one board showing everybody, and one
# place to check how well the model actually ranks. Separate Bets / Fades /
# Parlay tabs were three filtered views of this same table, which invited the
# reading that the filtered rows were the answer and the rest were noise.
tab_board, tab_results, tab2, tab_bet = st.tabs(
    ["Full board", "Weekly results", "Model performance", "Betting reality"]
)


# ── Helpers ─────────────────────────────────────────────────────────────────


@st.cache_data
def load_features(tt: str):
    path = get_path("processed", tt) / "features.parquet"
    if not path.exists():
        return None
    return pl.read_parquet(path)


@st.cache_data
def load_metrics(tt: str):
    path = get_path("output", tt) / "metrics.json"
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


@st.cache_data
def load_schedules():
    path = get_path("raw") / "schedules.parquet"
    if not path.exists():
        return None
    return pl.read_parquet(path)


@st.cache_data(ttl=3600)
def load_odds():
    """Load cached odds (or fetch if none cached)."""
    odds = load_cached_odds()
    if not odds:
        try:
            odds = fetch_week_td_props()
        except Exception:
            odds = {}
    return odds


def _normalize_name(name: str) -> str:
    """Normalize player name for matching: lowercase, strip suffixes."""
    name = name.lower().strip()
    for suffix in [" jr.", " sr.", " ii", " iii", " iv", " jr", " sr"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name


@st.cache_data(show_spinner=False)
def _scored_per_game(tt: str) -> int | None:
    """How many priced players a game's board typically contains.

    Derived from the backtest frames rather than typed in, because it is used
    to decide which prices take part in the de-vig normalisation and a wrong
    constant there silently rescales every probability on the board.
    """
    import glob
    counts = []
    for path in sorted(glob.glob(str(get_path("output", tt) / "backtest_*.csv"))):
        try:
            d = pl.read_csv(path)
        except Exception:
            continue
        if "game_id" in d.columns and d.height:
            counts.append(d.height / d["game_id"].n_unique())
    return int(round(float(np.median(counts)))) if counts else None


def _scored_rows(rows: list[dict], tt: str) -> list[dict] | None:
    """Trim a game's prices to the population the board will score.

    The exact fix — intersecting with this week's candidate pool — is what
    predict.py and the backtest do. The dashboard reaches this code one player
    at a time and has no pool to hand, so it approximates: keep the N most
    likely players, N being how many a scored game usually holds. That removes
    the deep-longshot tail whose presence or absence otherwise rescales every
    favourite on the board.
    """
    n = _scored_per_game(tt)
    if not n or len(rows) <= n:
        return None
    return sorted(rows, key=lambda p: p.get("implied_prob", 0.0), reverse=True)[:n]


def match_odds_to_game(odds_data: dict, game_label: str, target_type: str) -> dict:
    """Match odds data to a game label, return player->odds dict."""
    if not odds_data or not game_label:
        return {}

    market_key = "first_td" if target_type == "first_td" else "anytime_td"

    for game_key, data in odds_data.items():
        home_abbr = game_label.split(" @ ")[1].strip() if " @ " in game_label else ""
        away_abbr = game_label.split(" @ ")[0].strip() if " @ " in game_label else ""

        home_full = data.get("home_team", "")
        away_full = data.get("away_team", "")

        if (_team_matches(home_abbr, home_full) and
                _team_matches(away_abbr, away_full)):
            rows = data.get(market_key, [])
            # De-vig before anyone compares against these numbers. A posted price
            # carries the bookmaker's margin, so the implied percentages for one
            # game sum to ~1.36x what actually happens. Comparing a model
            # probability against the raw figure answers "would this bet profit?"
            # (which is what expected value is for) but understates how far we
            # actually disagree with the book. Every edge shown in the app now
            # uses the de-vigged number so the tabs agree with each other.
            # Normalise over the players this board will show, not every
            # price the book publishes. The scale is expected / sum(implied),
            # so a book that quotes 52 players instead of 27 drags every
            # favourite down by the same factor — which is how a -100
            # favourite's "fair" number read 41% in 2023 and 49% in 2025 while
            # its real rate stayed near 52%. See blend.devig_market.
            rows = _scored_rows(rows, target_type) or rows
            total = sum(p["implied_prob"] for p in rows) or 1.0
            scale = (_expected_scorers(target_type) / total) if total else 1.0
            player_odds = {}
            for p in rows:
                norm = _normalize_name(p["player"])
                player_odds[norm] = {
                    "odds": p["odds"],
                    "implied_prob": p["implied_prob"],          # raw — for payout/EV
                    "fair_prob": min(p["implied_prob"] * scale, 0.999),  # de-vigged
                    "bookmaker": p.get("bookmaker", ""),
                }
            return player_odds

    return {}


@st.cache_data(show_spinner=False)
def longshot_skill(tt: str) -> dict | None:
    """Measured longshot-sorting diagnostics, or None if not yet computed."""
    from src.evaluation.longshot import load
    return load(get_path("output", tt) / "longshot_skill.json")


@st.cache_data(show_spinner=False)
def _conversion(tt: str):
    """Fitted count->probability conversion, or None on an older model dir."""
    from src.models.joint import load_conversion
    return load_conversion(get_path("models", tt) / "td_conversion.json")


@st.cache_data(show_spinner=False)
def _team_rate_model(tt: str):
    """The fitted team touchdown rate, or None on a model dir predating it."""
    from src.models.joint import load_team_rate
    return load_team_rate(get_path("models", tt) / "team_td_rate.json")


@st.cache_data
def _expected_scorers(tt: str) -> float:
    """How many players we expect to score in a game, used to strip the vig.

    Exactly one player scores the first touchdown; for anytime-TD the count is
    read from the prior fitted during training, so it tracks the league's scoring
    environment rather than being pinned to a number someone typed once.
    """
    if tt == "first_td":
        return 1.0
    import json
    path = get_path("models", tt) / "scorer_rate_prior.json"
    if path.exists():
        return float(json.loads(path.read_text())["mean_scorers_per_game"])
    return 4.3


def _team_matches(abbr: str, full_name: str) -> bool:
    """Check if a team abbreviation matches a full team name."""
    mapping = {
        "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons",
        "BAL": "Baltimore Ravens", "BUF": "Buffalo Bills",
        "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
        "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns",
        "DAL": "Dallas Cowboys", "DEN": "Denver Broncos",
        "DET": "Detroit Lions", "GB": "Green Bay Packers",
        "HOU": "Houston Texans", "IND": "Indianapolis Colts",
        "JAX": "Jacksonville Jaguars", "KC": "Kansas City Chiefs",
        "LA": "Los Angeles Rams", "LAC": "Los Angeles Chargers",
        "LAR": "Los Angeles Rams", "LV": "Las Vegas Raiders",
        "MIA": "Miami Dolphins", "MIN": "Minnesota Vikings",
        "NE": "New England Patriots", "NO": "New Orleans Saints",
        "NYG": "New York Giants", "NYJ": "New York Jets",
        "OAK": "Oakland Raiders", "PHI": "Philadelphia Eagles",
        "PIT": "Pittsburgh Steelers", "SEA": "Seattle Seahawks",
        "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers",
        "TEN": "Tennessee Titans", "WAS": "Washington Commanders",
    }
    return mapping.get(abbr, "") == full_name


def get_vegas_info(odds_data: dict, player_name: str, game_label: str, tt: str) -> dict | None:
    """Get Vegas odds info for a player."""
    if not odds_data:
        return None
    player_odds = match_odds_to_game(odds_data, game_label, tt)
    if not player_odds:
        return None
    norm = _normalize_name(player_name)
    return player_odds.get(norm)


def format_vegas(info: dict) -> str:
    """Format Vegas odds as string."""
    odds_val = info["odds"]
    odds_str = f"+{odds_val}" if odds_val > 0 else str(odds_val)
    return f"{odds_str} ({info['implied_prob']*100:.0f}%)"


def edge_color(our_prob: float, vegas_info: dict | None) -> str | None:
    """Return color based on edge: green = value, red = overpriced."""
    if vegas_info is None:
        return None
    vegas_prob = vegas_info.get("fair_prob", vegas_info["implied_prob"])
    diff = our_prob - vegas_prob
    if diff > 0.02:
        return "#2ecc71"
    elif diff < -0.02:
        return "#e74c3c"
    return None


def _prob_to_american(p: float) -> str:
    if p <= 0:
        return "N/A"
    if p >= 0.5:
        return str(int(-p / (1 - p) * 100))
    return f"+{int((1 - p) / p * 100)}"


def _load_and_predict(model_name, feature_cols, X, model_dir):
    """Load model(s), run inference, and return calibrated probabilities."""
    if model_name == "ensemble":
        weights_path = model_dir / "ensemble_weights.pkl"
        if weights_path.exists():
            with open(weights_path, "rb") as f:
                weights = pickle.load(f)
        else:
            weights = {n: 1.0 / len(active_models) for n in active_models}

        probs = np.zeros(X.shape[0])
        for name, w in weights.items():
            m = get_model(name).load(model_dir / f"{name}.pkl")
            m.feature_names = feature_cols
            p = m.predict_proba(X)
            cal_path = model_dir / f"{name}_calibrator.pkl"
            if cal_path.exists():
                cal = IsotonicCalibrator.load(cal_path)
                p = cal.calibrate(p)
            probs += w * p
    else:
        model = get_model(model_name).load(model_dir / f"{model_name}.pkl")
        model.feature_names = feature_cols
        probs = model.predict_proba(X)
        cal_path = model_dir / f"{model_name}_calibrator.pkl"
        if cal_path.exists():
            cal = IsotonicCalibrator.load(cal_path)
            probs = cal.calibrate(probs)
    return probs


def get_available_weeks(df, season):
    """Return sorted list of weeks available for a season."""
    weeks = (
        df.filter(pl.col("season") == season)
        .select("week").unique()
        .sort("week")["week"].to_list()
    )
    return weeks


def run_prediction(season, week, model_name, tt: str):
    """Run model inference and return results DataFrame."""
    model_dir = get_path("models", tt)
    feat_cols_path = model_dir / "feature_cols.pkl"
    if not feat_cols_path.exists():
        return None

    with open(feat_cols_path, "rb") as f:
        feature_cols = pickle.load(f)

    df = load_features(tt)
    if df is None:
        return None

    week_df = df.filter((pl.col("season") == season) & (pl.col("week") == week))
    if week_df.shape[0] == 0:
        return None

    week_df = _filter_low_activity(week_df)
    X, _ = prepare_data(week_df, feature_cols)

    probs = _load_and_predict(model_name, feature_cols, X, model_dir)

    id_cols = ["game_id", "player_id", "player_name", "team"]
    result = week_df.select(id_cols).with_columns(pl.Series("raw_prob", probs))

    if tt == "first_td":
        result = result.with_columns(
            (pl.col("raw_prob") / pl.col("raw_prob").sum().over("game_id"))
            .alias("probability")
        )
    else:
        # Same joint structure predict.py publishes: P = 1 - exp(-lambda*share).
        # This branch used to hand back raw model output untouched, so the board
        # showed a third set of numbers — neither the CLI's nor the backtest's —
        # for the very same players.
        from src.models.joint import apply_joint, load_team_rate
        team_model = load_team_rate(model_dir / "team_td_rate.json")
        if team_model is not None:
            result = apply_joint(result, week_df, team_model,
                                 score_col="raw_prob", out_col="probability",
                                 conversion=_conversion(tt))
        else:
            result = result.with_columns(pl.col("raw_prob").alias("probability"))
    result = result.with_columns(
        pl.col("probability")
        .rank(descending=True, method="ordinal")
        .over("game_id")
        .alias("rank")
    )
    result = result.sort(["game_id", "rank"])

    schedules = load_schedules()
    if schedules is not None:
        game_labels = schedules.select([
            "game_id",
            (pl.col("away_team") + " @ " + pl.col("home_team")).alias("game_label"),
        ]).unique(subset=["game_id"])
        result = result.join(game_labels, on="game_id", how="left")
    else:
        result = result.with_columns(pl.col("game_id").alias("game_label"))

    return result


# ── Sidebar: Season/Week (after helpers are defined) ──────────────────────

with st.sidebar:
    _sidebar_df = load_features(target_type)
    if _sidebar_df is not None:
        _sidebar_seasons = sorted(
            _sidebar_df.select("season").unique()["season"].to_list(), reverse=True
        )
        season = st.selectbox("Season", _sidebar_seasons, key="sidebar_season")
        _sidebar_weeks = get_available_weeks(_sidebar_df, season)
        week = st.selectbox("Week", _sidebar_weeks, key="sidebar_week") if _sidebar_weeks else None
    else:
        season = None
        week = None

    # No bankroll control: the board shows estimates, not stakes. Kelly sizing
    # still exists in src/prediction/bets.py for the CLI, where it reads the
    # config value — but nothing on screen is denominated in dollars, so asking
    # for a bankroll here would be a setting that changes nothing you can see.


# ── The board ─────────────────────────────────────────────────────────────


@st.cache_data(show_spinner="Pricing this week's board...")
def load_board(season: int, week: int, tt: str, model: str):
    """Every priced player for the week, with identical maths for each."""
    from src.prediction.bets import board_for_week
    board, msg = board_for_week(season, week, tt, model)
    return (board.to_pandas() if board.height else None), msg


@st.cache_data(show_spinner=False)
def historical_accuracy(tt: str, model: str) -> dict | None:
    """How often our ranking found a real scorer, on the held-out season.

    Scored over the same candidate pool production actually scores — training,
    metrics.json and predict() all apply _filter_low_activity, and skipping it
    here once reported Top-1 as 10.2% for a model whose true figure was 63.4%.
    """
    df = load_features(tt)
    model_dir = get_path("models", tt)
    fc_path = model_dir / "feature_cols.pkl"
    if df is None or not fc_path.exists():
        return None
    if model != "ensemble" and not (model_dir / f"{model}.pkl").exists():
        return None

    test_season = cfg["splits"]["test_season"]
    test_df = _filter_low_activity(
        df.filter((pl.col("season") == test_season) & pl.col("target").is_not_null())
    )
    if test_df.height == 0:
        return None

    with open(fc_path, "rb") as f:
        feature_cols = pickle.load(f)
    X, _ = prepare_data(test_df, feature_cols)
    probs = _load_and_predict(model, feature_cols, X, model_dir)

    ev = test_df.with_columns(pl.Series("prob", probs))
    # Score the ranking the board actually shows. The joint step multiplies each
    # team's shares by that team's rate, which reorders players *across* the two
    # teams in a game — so measuring accuracy on raw model output would report a
    # Top-1 for a ranking no user ever sees.
    _tm = _team_rate_model(tt)
    if tt != "first_td" and _tm is not None:
        from src.models.joint import apply_joint
        ev = apply_joint(ev, test_df, _tm, score_col="prob", out_col="prob",
                         conversion=_conversion(tt))
    ev = ev.with_columns(
        pl.col("prob").rank(descending=True, method="ordinal")
        .over("game_id").alias("pred_rank")
    )
    best = (
        ev.filter(pl.col("target") == 1).group_by("game_id")
        .agg(pl.col("pred_rank").min().alias("best_rank"))["best_rank"].to_list()
    )
    if not best:
        return None
    n = len(best)
    return {
        "season": test_season,
        "games": n,
        "top1": sum(1 for r in best if r == 1) / n,
        "top3": sum(1 for r in best if r <= 3) / n,
        "top5": sum(1 for r in best if r <= 5) / n,
        "median_rank": float(np.median(best)),
    }


@st.cache_data(show_spinner=False)
def walkforward_accuracy(tt: str, model: str) -> dict | None:
    """Pooled out-of-sample accuracy from scripts/11_walkforward.py.

    Keyed by model as well as market. The first version keyed on market alone,
    so changing the Model selector left every figure in the strip frozen on the
    production model's numbers — the control looked broken because the metrics
    it was supposed to drive never moved.

    Returns None when the artifact is absent, or holds no folds for this model,
    so the app falls back to the single held-out season rather than showing a
    figure for the wrong model.
    """
    path = get_path("output", tt) / "walkforward.json"
    if not path.exists():
        return None
    folds = [f for f in json.loads(path.read_text())
             if f.get("model", model) == model]
    if not folds:
        return None

    total = sum(f["games"] for f in folds)
    out = {
        "games": total,
        "pooled": True,
        "span": f"{min(f['test_season'] for f in folds)}"
                f"-{max(f['test_season'] for f in folds)}",
        "seasons": len(folds),
        "model": model,
    }
    for k in ("top1", "top3", "top5"):
        # Weight by games so a short season does not count as a full one.
        p = sum(f[k] * f["games"] for f in folds) / total
        out[k] = p
        out[f"{k}_se"] = float(np.sqrt(p * (1 - p) / total))
    out["median_rank"] = float(np.median([f.get("median_rank", np.nan)
                                          for f in folds])) \
        if all("median_rank" in f for f in folds) else None
    return out


def render_accuracy_strip(tt: str, model: str):
    """Track record, shown on every page — a number you act on should carry its
    accuracy beside it, not a tab away."""
    # Prefer the pooled walk-forward figure over a single season. One season is
    # ~280 games, so a Top-1 read off it carries about 3 points of standard
    # error — wider than most of the differences anyone would act on, and it
    # swings several points year to year for no reason but noise. The
    # walk-forward retrains once per season and never lets a fold see its own
    # test year, so pooling four of them is the same measurement over four
    # times the games.
    wf = walkforward_accuracy(tt, model)
    acc = wf or historical_accuracy(tt, model)
    if acc is None:
        st.caption("Model performance unavailable — run the pipeline first.")
        return

    pooled = acc.get("pooled", False)
    span = acc.get("span", str(acc.get("season", "")))
    strip = st.container(horizontal=True)
    strip.metric("Games", f"{acc['games']:,}",
                 help=(f"Games across {span}. The model is retrained for each "
                       f"season and never sees the one it is being scored on."
                       if pooled else
                       f"Games in the {acc.get('season')} season, which the "
                       f"model never trained on."))
    for key, label, blurb in [
        ("top1", "Top-1", "How often our highest-rated player in a game actually scored."),
        ("top3", "Top-3", "How often at least one of our top 3 scored."),
        ("top5", "Top-5", "How often at least one of our top 5 scored."),
    ]:
        se = acc.get(f"{key}_se")
        strip.metric(
            label, f"{acc[key]:.1%}",
            delta=(f"+/- {se:.1%}" if se else None), delta_color="off",
            help=blurb + (
                f" Measured over {acc['games']:,} games; the +/- is one standard "
                f"error, so treat anything inside it as noise." if se else ""),
        )
    if acc.get("median_rank") is not None:
        strip.metric("Median rank", f"{acc['median_rank']:.0f}",
                     help="In a typical game, the best-ranked player who actually "
                          "scored sat this high on our list. Lower is better.")

    h2h = market_headtohead(tt, model)
    if h2h:
        spans_zero = h2h["overall_lo"] <= 0 <= h2h["overall_hi"]
        strip.metric(
            "vs bookmaker", f"{h2h['overall_better_pct']:+.1f}%",
            delta=f"{h2h['overall_lo']:+.1f} to {h2h['overall_hi']:+.1f}",
            delta_color="off",
            help=f"How much closer our estimates were to reality than the "
                 f"sportsbook's, across {h2h['players']:,} priced players in "
                 f"{h2h['span']}. The range is a 95% interval from resampling "
                 f"whole games, since players in one game share a defence and a "
                 f"game script. "
                 + ("It includes zero, so on this market we are not measurably "
                    "better than the book. "
                    if spans_zero else
                    "It excludes zero, so the edge is real if small. ")
                 + f"We also rank players better: {h2h['auc_ours']:.3f} against "
                 f"their {h2h['auc_market']:.3f}.",
        )


@st.cache_data(show_spinner=False)
def model_recipe(tt: str) -> dict:
    """The few facts the explainer quotes about how the number is built.

    Read from the artifacts rather than typed into the copy: the feature count
    changes when features are added, the training span moves every September,
    and the scorers-per-game figure is refitted from data each time we train.
    Prose that quotes a number someone typed once goes stale silently.
    """
    fc_path = get_path("models", tt) / "feature_cols.pkl"
    n_features = len(pickle.loads(fc_path.read_bytes())) if fc_path.exists() else None
    tm = _team_rate_model(tt)
    return {
        "n_features": n_features,
        "train_end": cfg["splits"]["train_end"],
        "val_season": cfg["splits"]["val_season"],
        "test_season": cfg["splits"]["test_season"],
        "expected_scorers": _expected_scorers(tt),
        # None on a model directory predating the joint model, which is what the
        # explainer keys on to describe the pipeline that is actually running.
        "team_tds": tm["mean_team_tds"] if tm else None,
    }


def how_to_read(tt: str, h2h: dict | None, acc: dict | None) -> str:
    """The explainer under the board: plain language, live numbers, four steps.

    Every figure comes from the artifacts. An earlier version hardcoded the
    Anytime TD accuracy, so the First TD page quoted a gap it had never
    measured, and a later one still described a level-rescaling step and a
    per-rank correction that the joint model replaced.
    """
    r = model_recipe(tt)
    market = "anytime touchdown" if tt == "anytime_td" else "first touchdown"
    seasons = r["train_end"] - 2015 + 1
    feat = f"about **{r['n_features']}**" if r["n_features"] else "several hundred"
    joint = tt != "first_td" and r.get("team_tds") is not None

    parts = [f"""
#### Reading the table

**Our estimate** is our answer: how likely this player is to score. **Bookmaker
says** is theirs, with their profit margin stripped out so the two are directly
comparable. **Difference** is the gap between them, and **Our read** turns that
gap into a verdict. **Typical at #** is what a player in that ranking slot
normally does, so you can see whether this one is unusual for the slot.

Two different questions live here. *Will it happen?* is **Our estimate** — a
player at 65% is genuinely likely to score, whatever the price says. *Is the
price wrong?* is **Difference** — a player at 15% priced as 10% is undervalued,
and will still fail to score 85% of the time. A big Difference is not a
prediction that something surprising happens; it is a claim the price is off.

#### How the number is built

**1. Learn from {seasons} seasons.** Every play from 2015 through
{r['test_season']} — carries, catches, targets, snaps, injury reports, depth
charts, betting lines. The model studies seasons through {r['train_end']} and is
then tested on ones it has never seen.

**2. Score every player.** We compute {feat} numbers per player per game. What
matters most isn't total yards, it's *where* the work happens — carries inside
the 5-yard line, red-zone targets, opening-drive touches — plus the offence
around him, the specific defence he faces, the point total and spread, weather,
rest, and who's injured.

> Every one of those must have been knowable before kickoff. That is the rule
> everything rests on, and automated tests check it.
"""]

    if joint:
        parts.append(f"""
**3. Split the game in two.** Rather than asking each player an isolated yes/no,
we ask two questions the game actually answers: *how many touchdowns will this
team score* — read from the betting lines, historically **{r['team_tds']:.2f}**
per team per game — and *whose will they be*, from usage and matchup. Multiply
the two. Teammates then compete for the same touchdowns instead of being counted
independently, and a game's numbers add up on their own rather than being
rescaled afterwards.
""")
    else:
        parts.append("""
**3. Share out one touchdown.** Exactly one player scores first, so each player's
number is his share of that single event and a game's numbers add to 100%.
""")

    parts.append("""
**4. Weigh the bookmaker in.** We neither override them nor copy them. A weight
fitted from past results combines both, refitted each week using only games that
had already finished, so it can never peek forward.

#### How well it works
""")

    if acc:
        span = acc.get("span")
        where = (f"across **{acc['games']:,} games** in {span}" if acc.get("pooled")
                 else f"across the {acc['games']} games of {acc.get('season')}")
        se = acc.get("top1_se")
        margin = f" (give or take {se:.0%})" if se and se >= 0.005 else ""
        parts.append(
            f"Scored {where} — each season predicted by a model retrained without "
            f"it — our top-rated player scored **{acc['top1']:.0%}** of the time"
            f"{margin}, and at least one of our top five scored "
            f"**{acc['top5']:.0%}**.\n"
        )
    if h2h:
        parts.append(
            f"\nAgainst the sportsbook on the {h2h['players']:,} {market} prices we "
            f"both quoted across {h2h['span']}, our estimates were "
            f"**{h2h['overall_better_pct']:.1f}% more accurate** overall, and "
            f"**{h2h['disagree_better_pct']:.1f}% more accurate** on the tenth of "
            f"players we disagree with them on most.\n"
        )
        if h2h["disagree_better_pct"] < 5:
            parts.append(
                "\n:material/warning: **That margin is thin.** On this market we are "
                "barely distinguishable from the bookmaker. Treat these as a second "
                "opinion, not an edge.\n"
            )

    parts.append("""
**What this is not.** It is a well-calibrated usage-and-matchup model that agrees
with the bookmaker most of the time and beats them modestly at sorting players.
It is not a money printer, and everything above describes a *replay* at closing
prices — no bet in it was ever actually struck.

**Where the accuracy comes from.** Most of our advantage on big disagreements is
in correctly rating players *down*, which these markets give you no way to back.
The half you can bet is a real but smaller edge, and it has been shrinking season
over season. **Betting reality** has the measured version of all of this.
""")
    return "".join(parts)


def board_columns(h2h: dict | None, region: dict | None = None) -> dict:
    """Column config, with the accuracy claim filled in from live numbers.

    The wording used to hardcode the Anytime TD figures, so the First TD page
    claimed an edge it does not have. Anything asserting how good we are has to
    come from the measurement for the market being displayed.
    """
    # The head-to-head claim now lives in the "Our read" tooltip below, split by
    # direction, because the combined figure reads as a betting signal and is
    # mostly fade accuracy. `h2h` stays in the signature so callers do not
    # change and so a market with no measurement can still be detected.
    return {
    "Player": st.column_config.TextColumn("Player"),
    "team": st.column_config.TextColumn("Team", width="small"),
    "Game": st.column_config.TextColumn("Game"),
    "Odds": st.column_config.TextColumn(
        "Odds", width="small",
        # Escaped: Streamlit reads a matched pair of dollar signs as LaTeX.
        help="The bookmaker's posted price. +250 means a \\$100 bet wins "
             "\\$250; -150 means you must risk \\$150 to win \\$100.",
    ),
    "Rank": st.column_config.NumberColumn(
        "#", width="small",
        help="Where this player sits on our list for their game.",
    ),
    "Ours": st.column_config.NumberColumn(
        "Our estimate", format="%.0f%%",
        help="Our estimated chance this player scores a touchdown. This is the "
             "number the whole model exists to get right.",
    ),
    "AtRank": st.column_config.NumberColumn(
        "Typical at #", format="%.0f%%",
        help="What actually happened to players in this slot across the whole "
             "2025 season. A second opinion on the row: if our estimate sits well "
             "above or below it, the model may be running hot or cold at this "
             "rank rather than knowing something specific about this player.",
    ),
    "Confidence": st.column_config.TextColumn(
        "Our read", width="small",
        help="**Matches book** — we and the bookmaker landed on the same number. "
             "**Leans** — a modest difference. **Strong call** — we're a long "
             "way from their price.\n\n"
             "A strong call is not a warning: on the players we disagree with "
             "the book about most, our estimate lands closer to what actually "
             "happened than theirs. But read it with **Difference**: most of "
             "that accuracy comes from correctly rating players *down*, which "
             "is our sharpest skill and not something these markets let you "
             "bet. A strong call where we are *higher* is the backable one — "
             "and that is what **Worth backing** marks.",
    ),
    "Book": st.column_config.NumberColumn(
        "Bookmaker says", format="%.0f%%",
        help="The bookmaker's own estimate, with their profit margin removed so "
             "both columns measure the same thing.",
    ),
    "edge_pp": st.column_config.NumberColumn(
        "Difference", format="%+.1f pts",
        help="How far our estimate sits above (+) or below (-) the bookmaker's. "
             "A big number is where the value would be — and also where we are "
             "least reliable. Those are the same players.",
    ),
    "BetRank": st.column_config.NumberColumn(
        "Bet #", width="small",
        help="Our ranking *before* we mix the bookmaker's price into it. The "
             "**#** column is the one to read for who is likely to score; this "
             "one is the ranking the money was measured on, because a bet only "
             "makes sense where we disagree with the price. They often differ "
             "by a place or two.",
    ),
    "BetEdge": st.column_config.NumberColumn(
        "Bet edge", format="%+.1f pts", width="small",
        help="The same comparison as **Difference**, but using our number "
             "before it is blended with the bookmaker's. That matters: the "
             "blend pulls our estimate toward the very price it is being "
             "compared against, so **Difference** comes out around 62% the "
             "size — and shrinks most where the disagreement is biggest. This "
             "is the column every profitability figure was measured on.",
    ),
    "InRange": st.column_config.TextColumn(
        "Worth backing", width="small",
        help=_tier_help(region),
    ),
    }


def _tier_summary(rule: dict | None) -> str:
    """One sentence naming each tier and what it returned, for the board caption."""
    h = (rule or {}).get("tiers") or {}
    by = {t["tier"]: t for t in h.get("tiers", [])}
    if not by:
        return "."
    bits = []
    if "strong" in by:
        bits.append(f"**Strong** (\\${100 + by['strong']['roi']:,.0f} per "
                    f"\\$100, ~{by['strong']['bets_per_week']:.0f}/week)")
    if "standard" in by:
        bits.append(f"**Standard** (\\${100 + by['standard']['roi']:,.0f} per "
                    f"\\$100, ~{by['standard']['bets_per_week']:.0f}/week)")
    return ": " + " and ".join(bits) + "."


def _tier_help(region: dict | None) -> str:
    """The tooltip for the highlight column, written from the measured tiers."""
    if not region or not region.get("tiers", {}).get("tiers"):
        return "Measured profitability. Nothing is marked on this market."

    h = region["tiers"]
    by = {t["tier"]: t for t in h["tiers"]}
    lines = [
        f"Marked from a rule fitted to {region['games']:,} games in "
        f"{region['span']} — thresholds measured, not chosen by hand. Both "
        f"tiers need **Bet #** {h['max_rank']} or better and a positive "
        f"**Bet edge**"
        + (f", at a price of +{h['exclude_below_odds']} or longer"
           if h.get("exclude_below_odds") else "") + ".\n",
    ]
    if "strong" in by:
        t = by["strong"]
        lines.append(
            f"**Strong** — bet edge of {h['big_edge'] * 100:.0f} points or "
            f"more. Returned \\${100 + t['roi']:,.0f} per \\$100 staked, about "
            f"{t['bets_per_week']:.0f} a week."
        )
    if "standard" in by:
        t = by["standard"]
        lines.append(
            f"**Standard** — a smaller disagreement. Returned "
            f"\\${100 + t['roi']:,.0f} per \\$100, about "
            f"{t['bets_per_week']:.0f} a week."
        )
    worst = min((t.get("trend") or 0) for t in h["tiers"])
    if worst < -5:
        lines.append(
            f"\n:material/warning: **Fading.** The strongest tier has been "
            f"losing roughly {abs(worst):.0f} points of return a year. Three "
            f"seasons is a small sample and the trend may be noise, but it "
            f"runs one way, so treat the headline as an average of something "
            f"that was better in the past than it is now."
        )
    hit = by.get("strong", by.get("standard", {})).get("hit_pct", 0)
    lines.append(
        f"\n**A fact about the group, not the player.** About {100 - hit:.0f}% "
        f"of even the marked bets lose. This is not a recommendation to bet."
    )
    return "\n\n".join(lines)


@st.cache_data(show_spinner=False)
def market_headtohead(tt: str, model: str) -> dict | None:
    """Us vs the sportsbook on identical players, pooled over every priced season.

    The headline claim of the app, so it gets the same treatment as the
    accuracy strip: every season we hold prices for, not just the held-out one.
    A single season is ~7,000 priced players and the Brier differences involved
    are in the third decimal, so a one-season read swings on noise — this
    reported +2.1% on 2025 and +0.6% on 2024 for the same model.

    It also scores the joint path rather than raw model output. Comparing a
    ranking the board never shows to the bookmaker answered a question nobody
    asked.
    """
    try:
        from sklearn.metrics import brier_score_loss, roc_auc_score

        from src.ingest.odds_history import load_graded_history
    except Exception:
        return None

    graded = load_graded_history(tt)
    df = load_features(tt)
    model_dir = get_path("models", tt)
    fc_path = model_dir / "feature_cols.pkl"
    if graded is None or df is None or not fc_path.exists():
        return None

    seasons = sorted(graded["season"].unique().to_list())
    feature_cols = pickle.loads(fc_path.read_bytes())
    team_model = _team_rate_model(tt)

    parts = []
    for season in seasons:
        d = _filter_low_activity(
            df.filter((pl.col("season") == season) & pl.col("target").is_not_null())
        )
        if d.height == 0:
            continue
        X, _ = prepare_data(d, feature_cols)
        d = d.with_columns(
            pl.Series("mp", _load_and_predict(model, feature_cols, X, model_dir))
        )
        if tt != "first_td" and team_model is not None:
            from src.models.joint import apply_joint
            d = apply_joint(d, d, team_model, score_col="mp", out_col="mp",
                            conversion=_conversion(tt))

        j = d.select(["game_id", "player_id", "mp", "target"]).join(
            graded.filter(pl.col("season") == season)
                  .select(["game_id", "player_id", "implied_prob"]),
            on=["game_id", "player_id"], how="inner",
        )
        if j.height == 0:
            continue
        # De-vig across the joined population only — including prices for
        # players we never score rescales everyone. See blend.devig_market.
        exp = _expected_scorers(tt)
        j = j.with_columns(
            (pl.col("implied_prob") / pl.col("implied_prob").sum().over("game_id") * exp)
            .alias("fair")
        )
        parts.append(j.with_columns(pl.lit(season).alias("season")))

    if not parts:
        return None
    j = pl.concat(parts)
    if j.height < 500:
        return None

    j = j.with_columns((pl.col("mp") - pl.col("fair")).abs().alias("gap"))
    y = j["target"].to_numpy().astype(float)
    ours, mkt = j["mp"].to_numpy(), j["fair"].to_numpy()

    top = j.filter(pl.col("gap") >= float(np.quantile(j["gap"].to_numpy(), 0.9)))
    yt = top["target"].to_numpy().astype(float)
    bo = brier_score_loss(yt, top["mp"].to_numpy())
    bm = brier_score_loss(yt, top["fair"].to_numpy())
    b_all, m_all = brier_score_loss(y, ours), brier_score_loss(y, mkt)

    # Bootstrap the overall improvement by resampling *games*, because two
    # players in the same game share a defence, a game script and a final
    # score. Treating them as independent understates the uncertainty.
    games = j["game_id"].to_numpy()
    uniq = np.unique(games)
    idx = {g: np.flatnonzero(games == g) for g in uniq}
    rng = np.random.default_rng(0)
    boot = []
    for _ in range(400):
        pick = rng.choice(len(uniq), len(uniq), replace=True)
        rows = np.concatenate([idx[uniq[i]] for i in pick])
        yb = y[rows]
        if yb.sum() == 0 or yb.sum() == len(yb):
            continue
        bb = brier_score_loss(yb, ours[rows])
        mb = brier_score_loss(yb, mkt[rows])
        boot.append((mb - bb) / mb * 100)
    boot = np.array(boot) if boot else np.array([0.0])

    return {
        "seasons": seasons,
        "span": f"{seasons[0]}-{seasons[-1]}" if len(seasons) > 1 else str(seasons[0]),
        "players": j.height,
        "games": int(len(uniq)),
        "overall_better_pct": (m_all - b_all) / m_all * 100,
        "overall_lo": float(np.percentile(boot, 2.5)),
        "overall_hi": float(np.percentile(boot, 97.5)),
        "disagree_better_pct": (bm - bo) / bm * 100,
        # Split by direction, because the combined figure is not a betting
        # signal and reads like one. Most of the accuracy on big disagreements
        # comes from correctly rating players *down* — 55% better than the book
        # on that half against 16% on the half you can actually back. Quoting
        # the blend sells fade skill as though it were a bet.
        **_directional_h2h(top),
        "auc_ours": roc_auc_score(y, ours),
        "auc_market": roc_auc_score(y, mkt),
    }


def _directional_h2h(top: pl.DataFrame) -> dict:
    """Accuracy on big disagreements, split into backable and fade."""
    from sklearn.metrics import brier_score_loss

    out = {}
    for name, sub in (("higher", top.filter(pl.col("mp") > pl.col("fair"))),
                      ("lower", top.filter(pl.col("mp") < pl.col("fair")))):
        if sub.height < 100:
            continue
        yy = sub["target"].to_numpy().astype(float)
        if yy.sum() == 0 or yy.sum() == len(yy):
            continue
        b = brier_score_loss(yy, sub["mp"].to_numpy())
        m = brier_score_loss(yy, sub["fair"].to_numpy())
        out[f"disagree_{name}_pct"] = (m - b) / m * 100
        out[f"disagree_{name}_n"] = int(sub.height)
    return out


@st.cache_data(show_spinner=False)
def rank_hit_rates(tt: str, model: str) -> dict[int, float]:
    """What actually happened to the Nth-rated player in a game, historically.

    A second, independent read on each row. The model's own estimate is
    player-specific; this is the empirical rate for that slot across a full
    season. Where the two disagree, the model has a positional bias — measured on
    2025 anytime-TD, the #2 pick runs about 6 points hot and everything from #4
    down runs several points cold.
    """
    df = load_features(tt)
    model_dir = get_path("models", tt)
    fc_path = model_dir / "feature_cols.pkl"
    if df is None or not fc_path.exists():
        return {}
    if model != "ensemble" and not (model_dir / f"{model}.pkl").exists():
        return {}

    test_df = _filter_low_activity(
        df.filter((pl.col("season") == cfg["splits"]["test_season"])
                  & pl.col("target").is_not_null())
    )
    if test_df.height == 0:
        return {}
    feature_cols = pickle.loads(fc_path.read_bytes())
    X, _ = prepare_data(test_df, feature_cols)
    probs = _load_and_predict(model, feature_cols, X, model_dir)
    ev = test_df.with_columns(pl.Series("p", probs))
    # Same joint ranking the board publishes — see historical_accuracy.
    _tm = _team_rate_model(tt)
    if tt != "first_td" and _tm is not None:
        from src.models.joint import apply_joint
        ev = apply_joint(ev, test_df, _tm, score_col="p", out_col="p",
                         conversion=_conversion(tt))
    ev = ev.with_columns(
        pl.col("p").rank(descending=True, method="ordinal")
        .over("game_id").alias("rank")
    )
    agg = ev.group_by("rank").agg([
        pl.col("target").mean().alias("hit"), pl.len().alias("n"),
    ]).filter(pl.col("n") >= 30)
    return {int(r): float(h) for r, h in zip(agg["rank"], agg["hit"])}


@st.cache_data
def confidence_cuts(tt: str) -> tuple[float, float]:
    """Where High/Medium/Low sit, taken from how far we typically differ.

    Read off the backtested season rather than chosen, so the labels mean
    "unusually far from the market *for this model*" instead of reflecting a
    threshold someone picked. Falls back to the current slate if untested.
    """
    path = get_path("output", tt) / f"backtest_{cfg['splits']['test_season']}.csv"
    if path.exists():
        diffs = pl.read_csv(path)["edge"].abs().drop_nulls().to_numpy()
        if len(diffs) > 100:
            return float(np.quantile(diffs, 0.33)), float(np.quantile(diffs, 0.66))
    return 0.02, 0.05


def _confidence(edge_pp: float, lo: float, hi: float) -> str:
    """Label what the model is doing, not how sure it is.

    These read as verdicts, so the wording matters. Calling a large gap "Low
    confidence" said the opposite of what the data shows — on those players our
    estimate has been 12-24% closer to reality than the bookmaker's.
    """
    d = abs(edge_pp) / 100.0
    if d <= lo:
        return "Matches book"
    if d <= hi:
        return "Leans"
    return "Strong call"


def _american(o) -> str:
    try:
        return f"{int(o):+d}"
    except (TypeError, ValueError):
        return "—"


@st.cache_data(show_spinner=False)
def rank_economics(tt: str, model: str | None = None) -> dict | None:
    """Profitability evidence for the model currently selected, if it exists.

    Falls back to the production model's file and says so, rather than
    presenting one model's board beside another model's money. Returns a
    `stale_for` key when that fallback happens so the page can label itself.
    """
    from src.evaluation.rank_economics import load

    out = get_path("output", tt)
    if model:
        tagged = load(out / f"rank_economics_{model}.json")
        if tagged is not None:
            return tagged
    stats = load(out / "rank_economics.json")
    if stats is not None and model and stats.get("model") not in (model, None):
        stats = {**stats, "stale_for": model}
    elif stats is not None and model:
        prod = production_model(tt)
        if prod != model:
            stats = {**stats, "stale_for": model, "measured_on": prod}
    return stats


@st.cache_data(show_spinner=False)
def betting_rule(tt: str, model: str | None = None) -> dict | None:
    """The fitted rule for which rows have a measured edge behind them.

    Two gates, both from measurement rather than from anybody's judgement: the
    market has to have cleared its prices at all, and there has to be an edge
    cut-off that separates a paying set of bets from a losing one in every
    season. Both live in src/evaluation/rank_economics.py so they can be tested
    without standing up Streamlit — they decide what the board is allowed to
    claim, which makes them worth locking down.

    Returns None when either gate fails, and the board then marks nothing.
    """
    econ = rank_economics(tt, model)
    if econ is None:
        return None
    from src.evaluation.rank_economics import profitable_region
    if profitable_region(econ) is None:
        return None
    rule = econ.get("edge_rule")
    if not rule:
        return None

    seasons = econ.get("seasons") or []
    return {**rule, "tiers": econ.get("highlight_tiers"),
            "games": econ.get("games"),
            "span": f"{seasons[0]}-{seasons[-1]}" if seasons else "",
            "stale_for": econ.get("stale_for"),
            "measured_on": econ.get("measured_on")}


#: How each tier reads on the board. Two levels and a blank — no letter grade,
#: because a letter beside a player's name reads as a promise about that player
#: and roughly half of even the strongest tier loses.
_TIER_LABEL = {"strong": "Strong", "standard": "Standard"}


def _highlight_tier(frame, rule: dict):
    """Label each row with the measured tier it falls into, or blank.

    Every threshold comes from `fit_highlight_tiers`, so a re-run on new seasons
    moves the marks rather than leaving them describing a model that no longer
    exists. A tier that stops clearing its bar simply disappears from the file
    and stops being marked here.
    """
    h = rule.get("tiers")
    if not h or not h.get("tiers"):
        return ""

    names = {t["tier"] for t in h["tiers"]}
    edge = frame["model_edge_pp"]
    eligible = ((frame["bet_rank"] <= h["max_rank"])
                & (edge >= h["edge_cut"] * 100))
    floor = h.get("exclude_below_odds")
    if floor is not None:
        eligible &= frame["odds"] >= floor

    big = edge >= h["big_edge"] * 100
    out = pd.Series("", index=frame.index, dtype="object")
    if "standard" in names:
        out[eligible & ~big] = _TIER_LABEL["standard"]
    if "strong" in names:
        out[eligible & big] = _TIER_LABEL["strong"]
    return out


def render_board(frame, tt: str, model: str):
    """Single renderer, so every view describes a player the same way."""
    lo, hi = confidence_cuts(tt)
    rates = rank_hit_rates(tt, model)
    # `game_rank` is assigned once over the whole board in week_board(); ranking
    # here would relabel a filtered view so a search hit looked like the #1 pick.
    ranks = frame["game_rank"]
    show = frame.assign(
        Player=frame["player_name"],
        Game=frame["game_label"],
        Odds=frame["odds"].map(_american),
        Rank=ranks,
        Ours=frame["probability"] * 100,
        AtRank=ranks.map(lambda r: rates.get(int(r), float("nan")) * 100),
        Confidence=frame["edge_pp"].map(lambda e: _confidence(e, lo, hi)),
        Book=frame["market_prob"] * 100,
    )
    # Typical at # -> Our estimate -> Bookmaker says -> Difference -> Our read.
    # The two probabilities sit side by side so the comparison is a glance
    # rather than a scan, the gap between them follows immediately, and the
    # verdict reads last. "Typical at #" leads as the baseline the estimate is
    # departing from.
    cols = ["Player", "team", "Game", "Odds", "Rank", "AtRank", "Ours",
            "Book", "edge_pp", "Confidence"]

    # Betting columns sit together at the right-hand end rather than mixed in.
    # Everything to their left answers "will he score" and is blended with the
    # market because that predicts better; everything from here answers "should
    # you back him" and is strictly pre-blend, because a bet is a disagreement
    # with the price and the blend is the act of conceding it. Two questions,
    # two sets of numbers, and mixing them is what made the original board
    # quietly point at the wrong players.
    #
    # They appear only where a rule was fitted. On a market that has not cleared
    # its prices they would be a tick box implying evidence that does not exist.
    rule = betting_rule(tt, model)
    if rule and {"bet_rank", "model_edge_pp"} <= set(frame.columns):
        show = show.assign(
            BetRank=frame["bet_rank"],
            BetEdge=frame["model_edge_pp"],
            InRange=_highlight_tier(frame, rule),
        )
        cols = cols + ["BetRank", "BetEdge", "InRange"]

    st.dataframe(show[cols], hide_index=True,
                 column_config=board_columns(market_headtohead(tt, model), rule))


def week_board():
    """(board, we're-higher, we're-lower) for the sidebar's season/week."""
    if week is None:
        st.info("Select a season and week in the sidebar.")
        return None, None, None
    board, msg = load_board(season, week, target_type, selected_model)
    if board is None:
        st.info(msg or "Nothing to show for this week.")
        st.caption("Players appear here once a bookmaker has posted a price for them.")
        return None, None, None
    board = board.copy()
    board["game_rank"] = (
        board.groupby("game_label")["probability"]
        .rank(ascending=False, method="first").astype(int)
    )
    # A second ranking, on the pre-blend number. The published probability is
    # blended with the bookmaker's price because that predicts scorers more
    # accurately; ranking on it costs about 8 points of return, because a bet is
    # a disagreement with the price and the blend is the act of conceding it.
    # Both rankings cover only priced players, which is also the population the
    # backtest ranked, so the two are directly comparable.
    rank_src = "prob_model" if "prob_model" in board.columns else "probability"
    board["bet_rank"] = (
        board.groupby("game_label")[rank_src]
        .rank(ascending=False, method="first").astype(int)
    )
    floor = float(cfg.get("betting", {}).get("min_edge_pp", 2.0))
    higher = board[(board["edge_pp"] >= floor) & (board["ev_pct"] > 0)]
    lower = board[board["edge_pp"] <= -floor].sort_values("edge_pp")
    return board, higher, lower


with tab_board:
    render_accuracy_strip(target_type, selected_model)
    board, backing, overvalued = week_board()
    if board is not None:
        h2h = market_headtohead(target_type, selected_model)
        if h2h and h2h["disagree_better_pct"] > 0:
            _hi = h2h.get("disagree_higher_pct")
            _lo = h2h.get("disagree_lower_pct")
            if _hi is not None and _lo is not None:
                st.success(
                    f"**Where we disagree with the bookmaker is where this model "
                    f"is worth reading.** On the tenth of players we differ from "
                    f"the book on most across {h2h['span']}, our estimate landed "
                    f"**{h2h['disagree_better_pct']:.0f}% closer** to what "
                    f"actually happened.\n\n"
                    f"Read that in two halves. Where we rate a player **lower** "
                    f"than the book we are **{_lo:.0f}% closer** — our sharpest "
                    f"skill, and not something these markets let you bet. Where "
                    f"we rate one **higher** we are **{_hi:.0f}% closer**, and "
                    f"that is the half you can back.",
                    icon=":material/trending_up:",
                )
            else:
                st.success(
                    f"**Where we disagree with the bookmaker is where this model "
                    f"is worth reading.** On the players we differed from the "
                    f"book on most across {h2h['span']}, our estimate landed "
                    f"**{h2h['disagree_better_pct']:.0f}% closer** to what "
                    f"actually happened than theirs.",
                    icon=":material/trending_up:",
                )
        st.caption(
            "Every player a bookmaker priced this week. **Our estimate** is the "
            "number we're trying to get right; the bookmaker's is shown beside it "
            "as the best available second opinion."
        )

        _rule = betting_rule(target_type, selected_model)
        if _rule:
            st.caption(
                f":material/payments: The last three columns answer a different "
                f"question from the rest of the table. Everything to their left "
                f"is our best guess at **who scores**, blended with the "
                f"bookmaker because that predicts better. **Bet #** and **Bet "
                f"edge** are strictly our own view, unblended, because backing "
                f"someone only makes sense where we disagree with the price. "
                f"**Worth backing** marks the two tiers that measured "
                f"profitable across {_rule['games']:,} games in "
                f"{_rule['span']}" + _tier_summary(_rule) + " Roughly half of "
                f"even the marked bets lose — see **Betting reality**."
            )
        else:
            st.caption(
                ":material/info: No betting markers on this market. Its "
                "accuracy is measured and real, but backing our picks against "
                "these prices has not been shown to make money — see **Betting "
                "reality**. Marking rows anyway would imply evidence we do not "
                "have."
            )

        filters = st.container(horizontal=True)
        games = ["All games"] + sorted(board["game_label"].dropna().unique().tolist())
        pick = filters.selectbox("Game", games)
        query = filters.text_input(
            "Search player", placeholder="e.g. Barkley",
            help="Type any part of a player's name.",
        )
        # Ties the table to the Top-1/3/5 figures above it: picking "Top 5"
        # shows exactly the players that figure is measured on. The rate is read
        # from the walk-forward file rather than written here — it was hardcoded
        # at 97%, which was a different model's number and had been wrong since.
        _wf = walkforward_accuracy(target_type, selected_model)
        _top5 = f"{_wf['top5']:.0%}" if _wf and _wf.get("top5") else "most"
        depth = filters.selectbox(
            "Show per game", ["Everyone", "Top 5", "Top 3", "Top 1"],
            help=f"Top 5 shows the five players the Top-5 accuracy figure above "
                 f"is measured on — the set that contains a scorer {_top5} of "
                 f"the time.",
        )
        only_calls = filters.checkbox(
            "Only where we differ",
            help="Hide players we price the same as the bookmaker. What's left is "
                 "where the model is expressing an opinion — historically its most "
                 "accurate ground relative to the book.",
        )
        ls = longshot_skill(target_type)
        longshots_only = filters.checkbox(
            "Longshot standouts",
            disabled=ls is None,
            help=(
                f"Players priced at +{ls['min_odds']} or longer that we rate "
                f"highest. Inside that group the bookmaker's own price barely "
                f"sorts scorers from non-scorers (AUC {ls['auc_book']:.2f}) "
                f"while ours does much better ({ls['auc_ours']:.2f}) — the "
                f"largest gap anywhere on this board. It says which longshots "
                f"are live, not which are cheap."
                if ls else
                "Needs the longshot measurement — run scripts/12_longshot.py."
            ),
        )

        shown = board if pick == "All games" else board[board["game_label"] == pick]
        shown = shown.sort_values("probability", ascending=False)
        if query:
            shown = shown[shown["player_name"].str.contains(query, case=False, na=False)]
        if depth != "Everyone":
            n = int(depth.split()[-1])
            shown = shown[shown["game_rank"] <= n]
        if only_calls:
            floor = float(cfg.get("betting", {}).get("min_edge_pp", 2.0))
            shown = shown[shown["edge_pp"].abs() >= floor]
            shown = shown.sort_values(["game_label", "probability"],
                                      ascending=[True, False])

        if longshots_only and ls is not None:
            # Rank within the band rather than filtering on a probability
            # threshold. What was measured is our *ordering* of these players,
            # not the level of our estimate for them.
            shown = shown[shown["odds"].fillna(0) >= ls["min_odds"]]
            shown = shown.sort_values("probability", ascending=False)

        if longshots_only and ls is not None:
            st.info(
                f"**Longshots we rate highest.** Across "
                f"{ls['seasons'][0]}-{ls['seasons'][-1]} we sorted this group far "
                f"better than the price did — **{ls['auc_ours']:.2f}** against the "
                f"book's **{ls['auc_book']:.2f}**, the biggest gap on the board. "
                f"But read it as *which longshots are live*, not *which are good "
                f"value*: this band is priced around "
                f"**{ls['band_price_implied']:.1%}** and only hits "
                f"**{ls['band_actual_rate']:.1%}**, so the bookmaker's margin here "
                f"is enormous. Our best-rated tenth still only came in at "
                f"**{ls['top_decile_actual']:.1%}** against a price implying "
                f"**{ls['top_decile_price_implied']:.1%}** — roughly "
                f"{ls['top_decile_per_week']:.0f} players a week, of whom well "
                f"under one scores.",
                icon=":material/insights:",
            )

        if shown.empty:
            st.info("No players match that filter.")
        else:
            render_board(shown, target_type, selected_model)
            if depth != "Everyone":
                acc = historical_accuracy(target_type, selected_model)
                n = int(depth.split()[-1])
                key = {1: "top1", 3: "top3", 5: "top5"}[n]
                if acc:
                    st.caption(
                        f":material/insights: Across {acc['games']} games in "
                        f"{acc['season']}, at least one of a game's top {n} scored "
                        f"**{acc[key]:.1%}** of the time. These are that same top "
                        f"{n}, for this week."
                    )

        agree = len(board) - len(backing) - len(overvalued)
        st.caption(
            f"Showing {len(shown)} of {len(board)} priced players, most likely first. "
            f"We're higher than the bookmaker on {len(backing)}, lower on "
            f"{len(overvalued)}, and close to them on {agree}."
        )

        with st.expander("How to read this — and how the number is built"):
            st.markdown(
                how_to_read(
                    target_type, h2h,
                    # Same accuracy source the strip at the top uses, so the
                    # explainer cannot quote a different figure than the page.
                    walkforward_accuracy(target_type, selected_model)
                    or historical_accuracy(target_type, selected_model),
                )
            )


# ── Removed: the old Predictions tab ──────────────────────────────────────
# Its per-game browse is now the Full board with a game filter, and its AI
# commentary moved next to the picks it describes. Keeping it would have meant
# a third copy of the same edge table — which is what made the tabs disagree.


# ── Tab: Weekly results — were our numbers right? ─────────────────────────


@st.cache_data(show_spinner="Scoring the week...")
def _score_week(season: int, week: int, tt: str, model: str):
    from src.evaluation.weekly_review import score_week
    return score_week(season, week, tt, model)


@st.cache_data(show_spinner=False)
def _played(season: int, tt: str):
    from src.evaluation.weekly_review import played_weeks
    return played_weeks(season, tt)


with tab_results:
    render_accuracy_strip(target_type, selected_model)
    weeks_done = _played(season, target_type) if season else []

    if not weeks_done:
        st.info(
            f"No {season} weeks have been played yet. Once results are in, this "
            f"page grades our estimates against what actually happened."
        )
        st.caption(
            "The question it answers: when we said 25%, did about 25% of those "
            "players score? That's the test of whether the numbers are right — "
            "ranking well is a different, easier thing."
        )
    else:
        wk = st.selectbox(
            "Week", weeks_done,
            index=len(weeks_done) - 1,
            help="Only weeks with final results appear here.",
        )
        r = _score_week(season, wk, target_type, selected_model)

        if r is None:
            st.info("That week hasn't been graded yet.")
        else:
            top = st.container(horizontal=True)
            top.metric("Games", r["games"])
            top.metric(
                "Scorers", f"{r['actual_total']:.0f}",
                help=f"We predicted {r['predicted_total']:.1f} in total.",
            )
            top.metric(
                "Predicted total", f"{r['predicted_total']:.1f}",
                delta=f"{r['predicted_total'] - r['actual_total']:+.1f} vs actual",
                delta_color="off",
            )
            if r["top1_hit"] is not None:
                top.metric(
                    "Top pick hit", f"{r['top1_hit']:.0%}",
                    help="Share of games where our highest-rated player scored.",
                )

            st.markdown("**When we said X%, did X% of them score?**")
            cal = pl.DataFrame(r["buckets"]).to_pandas()
            st.dataframe(
                cal.assign(
                    we_said=cal["we_said"] * 100,
                    actually=cal["actually"] * 100,
                    gap=cal["gap"] * 100,
                )[["bucket", "players", "we_said", "actually", "gap"]],
                hide_index=True,
                column_config={
                    "bucket": st.column_config.TextColumn("Range"),
                    "players": st.column_config.NumberColumn("Players"),
                    "we_said": st.column_config.NumberColumn("We said", format="%.1f%%"),
                    "actually": st.column_config.NumberColumn("Actually scored", format="%.1f%%"),
                    "gap": st.column_config.NumberColumn(
                        "Off by", format="%+.1f pts",
                        help="Positive means we were too high, negative too low. "
                             "Close to zero is the goal.",
                    ),
                },
            )

            h = r.get("head_to_head")
            if h:
                ours, mkt = h["brier_ours"], h["brier_market"]
                winner = "we were" if ours < mkt else "the bookmaker was"
                st.markdown(
                    f"**Against the bookmaker** — on the {h['players']} players both "
                    f"of us priced, {winner} closer to the truth "
                    f"({ours:.4f} vs {mkt:.4f}, lower is better)."
                )
                st.caption(
                    "This is the benchmark that matters. Sportsbook prices are very "
                    "well calibrated, so beating them — even narrowly, even "
                    "sometimes — is the real test of whether the model knows "
                    "something. A small, repeatable gap is worth far more than one "
                    "big week."
                )
            else:
                st.caption(
                    "No archived bookmaker prices for this week, so there's nothing "
                    "to grade against. Run `make odds WEEK=n` during the week to "
                    "capture them."
                )


# ── Tab 2: Model Performance ──────────────────────────────────────────────

with tab2:
    metrics = load_metrics(target_type)
    df = load_features(target_type)
    model_dir = get_path("models", target_type)

    st.caption(
        f"How the model has performed on **{cfg['splits']['test_season']}** — a "
        f"season it never trained on. Training stops at "
        f"{cfg['splits']['train_end']}, {cfg['splits']['val_season']} is used for "
        f"tuning, and {cfg['splits']['test_season']} is held back entirely so these "
        f"numbers aren't flattering themselves."
    )

    if not metrics and df is None:
        st.warning(f"No data found for {target_type}. Run the pipeline first.")
    else:
        # --- Historical accuracy (rank buckets, weekly chart) ---
        if df is not None:
            st.subheader("Historical Accuracy")

            hist_model = selected_model
            test_season = cfg["splits"]["test_season"]
            test_df = df.filter(
                (pl.col("season") == test_season)
                & pl.col("target").is_not_null()
            )
            # Score the same pool production actually scores. Training, metrics.json
            # and predict() all apply this filter; without it the ranking includes
            # ~9,500 deep-bench rows per season whose null features become 0.0, some
            # of which outrank real starters — which reported Top-1 as 10.2% against
            # the 63.4% in metrics.json for the identical model.
            test_df = _filter_low_activity(test_df)

            if test_df.shape[0] == 0:
                st.info(f"No test data for season {test_season}")
            else:
                feat_cols_path = model_dir / "feature_cols.pkl"
                model_path = model_dir / f"{hist_model}.pkl"

                if not feat_cols_path.exists():
                    st.info("Model files not found. Run training first.")
                elif hist_model != "ensemble" and not model_path.exists():
                    st.info(f"Model file for {hist_model} not found. Run training first.")
                else:
                    with open(feat_cols_path, "rb") as f:
                        feature_cols = pickle.load(f)

                    X_test, y_test = prepare_data(test_df, feature_cols)

                    raw_probs = _load_and_predict(hist_model, feature_cols, X_test, model_dir)

                    eval_df = test_df.with_columns([
                        pl.Series("prob", raw_probs),
                    ])
                    eval_df = eval_df.with_columns(
                        pl.col("prob").rank(descending=True, method="ordinal")
                        .over("game_id").alias("pred_rank")
                    )

                    actual = eval_df.filter(pl.col("target") == 1)
                    n_games = actual["game_id"].n_unique()
                    game_best_ranks = (
                        actual.group_by("game_id")
                        .agg(pl.col("pred_rank").min().alias("best_rank"))
                    )
                    best_ranks = game_best_ranks["best_rank"].to_list()

                    # Summary metrics
                    top1_pct = sum(1 for r in best_ranks if r == 1) / n_games * 100 if n_games else 0
                    top3_pct = sum(1 for r in best_ranks if r <= 3) / n_games * 100 if n_games else 0
                    top5_pct = sum(1 for r in best_ranks if r <= 5) / n_games * 100 if n_games else 0
                    median_rank = float(np.median(best_ranks)) if best_ranks else 0

                    summary_cols = st.columns(5)
                    summary_cols[0].metric("Games", n_games)
                    summary_cols[1].metric("Top-1", f"{top1_pct:.1f}%")
                    summary_cols[2].metric("Top-3", f"{top3_pct:.1f}%")
                    summary_cols[3].metric("Top-5", f"{top5_pct:.1f}%")
                    summary_cols[4].metric("Median Rank", f"{median_rank:.0f}")

                    col_a, col_b = st.columns([1, 2])

                    with col_a:
                        st.markdown(f"**{test_season} — {hist_model}**")
                        bucket_rows = []
                        cumul = 0
                        for rank in range(1, 21):
                            count = sum(1 for r in best_ranks if r == rank)
                            pct = count / n_games * 100 if n_games else 0
                            cumul += pct
                            bucket_rows.append({
                                # Str, not int: the final row is "21+", and a
                                # column mixing int with str fails Arrow
                                # conversion outright — the table rendered as an
                                # exception rather than as data.
                                "Rank": str(rank),
                                "Count": count,
                                "Pct": f"{pct:.1f}%",
                                "Cumul": f"{cumul:.1f}%",
                            })
                        count_21 = sum(1 for r in best_ranks if r > 20)
                        pct_21 = count_21 / n_games * 100 if n_games else 0
                        cumul += pct_21
                        bucket_rows.append({
                            "Rank": "21+",
                            "Count": count_21,
                            "Pct": f"{pct_21:.1f}%",
                            "Cumul": f"{cumul:.1f}%",
                        })
                        st.dataframe(bucket_rows, hide_index=True, height=400)

                    with col_b:
                        actual_with_week = actual.select(["game_id", "season", "week", "pred_rank"])
                        game_best_week = (
                            actual_with_week.group_by(["game_id", "week"])
                            .agg(pl.col("pred_rank").min().alias("best_rank"))
                        )
                        weeks = sorted(game_best_week["week"].unique().to_list())
                        week_stats = []
                        for w in weeks:
                            w_ranks = game_best_week.filter(pl.col("week") == w)["best_rank"].to_list()
                            n = len(w_ranks)
                            if n == 0:
                                continue
                            top1 = sum(1 for r in w_ranks if r == 1) / n * 100
                            top3 = sum(1 for r in w_ranks if r <= 3) / n * 100
                            top5 = sum(1 for r in w_ranks if r <= 5) / n * 100
                            week_stats.append({"Week": w, "Top-1": top1, "Top-3": top3, "Top-5": top5})

                        if week_stats:
                            ws_df = pl.DataFrame(week_stats)
                            fig = go.Figure()
                            for metric, color in [("Top-1", "#e74c3c"), ("Top-3", "#f39c12"), ("Top-5", "#2ecc71")]:
                                fig.add_trace(go.Scatter(
                                    x=ws_df["Week"].to_list(),
                                    y=ws_df[metric].to_list(),
                                    mode="lines+markers",
                                    name=metric,
                                    line=dict(color=color),
                                ))
                            fig.update_layout(
                                title=f"Weekly Accuracy — {hist_model} ({test_season})",
                                xaxis_title="Week", yaxis_title="Accuracy (%)",
                                height=400,
                            )
                            st.plotly_chart(fig)

        # Everything below is for debugging the model, not for placing a bet.
        # Feature importance over 300+ columns and raw metric tables are noise
        # on the way to a wager, so they are opt-in.
        show_dev = st.toggle(
            "Show developer diagnostics",
            value=False,
            help="Calibration curves, feature importance and raw evaluation metrics.",
        )

        # --- Calibration curves ---
        if show_dev and df is not None and model_dir.exists():
            test_season = cfg["splits"]["test_season"]
            test_df = df.filter(
                (pl.col("season") == test_season) & pl.col("target").is_not_null()
            )
            if test_df.shape[0] > 0:
                feat_cols_path = model_dir / "feature_cols.pkl"
                if feat_cols_path.exists():
                    with open(feat_cols_path, "rb") as f:
                        feature_cols = pickle.load(f)
                    X_test, y_test = prepare_data(test_df, feature_cols)

                    st.markdown("---")
                    st.subheader("Calibration Curves")
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=[0, 1], y=[0, 1], mode="lines",
                        line=dict(dash="dash", color="gray"),
                        name="Perfect", showlegend=True,
                    ))
                    for name in active_models:
                        model_path = model_dir / f"{name}.pkl"
                        if not model_path.exists():
                            continue
                        model = get_model(name).load(model_path)
                        model.feature_names = feature_cols
                        probs = model.predict_proba(X_test)
                        from sklearn.calibration import calibration_curve
                        prob_true, prob_pred = calibration_curve(
                            y_test, probs, n_bins=10, strategy="quantile"
                        )
                        fig.add_trace(go.Scatter(
                            x=prob_pred, y=prob_true, mode="lines+markers", name=name,
                        ))
                    fig.update_layout(
                        xaxis_title="Mean Predicted Probability",
                        yaxis_title="Fraction of Positives",
                        height=400,
                    )
                    st.plotly_chart(fig)

        # --- Feature Importance (all features with definitions) ---
        if show_dev and model_dir.exists():
            st.markdown("---")
            st.subheader("Feature Importance")

            imp_model_name = st.selectbox(
                "Show importance for",
                active_models,
                key="imp_model_select",
            )
            model_path = model_dir / f"{imp_model_name}.pkl"
            if model_path.exists():
                model = get_model(imp_model_name).load(model_path)
                feat_cols_path = model_dir / "feature_cols.pkl"
                if feat_cols_path.exists():
                    with open(feat_cols_path, "rb") as f:
                        model.feature_names = pickle.load(f)
                importances = model.feature_importances()
                if importances:
                    sorted_imp = sorted(importances.items(),
                                        key=lambda x: abs(x[1]),
                                        reverse=True)

                    imp_table = []
                    for rank, (fname, fval) in enumerate(sorted_imp, 1):
                        imp_table.append({
                            "Rank": rank,
                            "Feature": fname,
                            "Importance": round(fval, 6),
                            "Definition": get_definition(fname),
                        })

                    st.dataframe(
                        imp_table,
                        hide_index=True,
                        height=600,
                    )
                    st.caption(f"{len(imp_table)} total features")

        # --- Evaluation Metrics (bottom) ---
        if show_dev and metrics:
            st.markdown("---")
            st.subheader("Evaluation Metrics")
            rows = []
            for m in metrics:
                rows.append({
                    "Model": m["model"],
                    "Log Loss": f"{m['log_loss']:.4f}",
                    "ROC AUC": f"{m['roc_auc']:.4f}",
                    "Brier": f"{m['brier_score']:.4f}",
                    "Top-1": f"{m['top_1_accuracy']:.1%}",
                    "Top-3": f"{m['top_3_accuracy']:.1%}",
                    "Top-5": f"{m['top_5_accuracy']:.1%}",
                })
            st.dataframe(rows, hide_index=True)




# ── Tab: Betting reality — does being right actually pay? ─────────────────────
#
# Accuracy and profit are different questions and the app answered only the
# first for a long time. A model can be right 94.7% of the time about "one of
# these five scores" and still lose money backing all five, because the fifth is
# priced above what it does. Everything here carries a game-clustered interval,
# and the verdict says NO EDGE DEMONSTRATED whenever that interval spans zero.


#: Why a section is missing, keyed by section name. A swallowed exception used
#: to remove a whole panel from the page with nothing said, which is
#: indistinguishable from "this market has no data" and sends you looking in the
#: wrong place. Whatever goes wrong now gets shown where the section would be.
_SECTION_ERRORS: dict[str, str] = {}


def _section_error(name: str) -> str | None:
    return _SECTION_ERRORS.get(name)


@st.cache_data(show_spinner=False)
def clv_by_rank(tt: str) -> list[dict] | None:
    """Line movement by our rank. Needs paired open/close snapshots."""
    from src.evaluation.clv import by_rank
    try:
        _SECTION_ERRORS.pop(f"clv:{tt}", None)
        return by_rank(tt)
    except Exception as e:
        _SECTION_ERRORS[f"clv:{tt}"] = f"{type(e).__name__}: {e}"
        return None


@st.cache_data(show_spinner=False)
def allocation_backtest(tt: str, top_n: int, bankroll: float) -> list[dict]:
    """Replay every game under each staking rule. Cached — it is a full walk."""
    from src.prediction.portfolio import backtest_allocation
    try:
        _SECTION_ERRORS.pop(f"alloc:{tt}", None)
        return backtest_allocation(tt, top_n=top_n, bankroll=bankroll)
    except Exception as e:
        _SECTION_ERRORS[f"alloc:{tt}"] = f"{type(e).__name__}: {e}"
        return []


#: The statistician's verdict, said out loud. "Indistinguishable from zero" is
#: precise and means nothing to most readers; "too close to call" means the same
#: thing and survives being read quickly.
_VERDICT_PLAIN = {
    "positive": "Made money",
    "negative": "Lost money",
    "indistinguishable from zero": "Too close to call",
    "no bets": "—",
}


def _roi_rows(rows: list[dict], key: str, label: str) -> pd.DataFrame:
    return pd.DataFrame([{
        label: r.get(key),
        "Bets": r["n"],
        "Hit": r["hit_pct"] / 100,
        "Break-even": r["breakeven_pct"] / 100,
        "Odds": r["median_odds"],
        "ROI": r["roi"] / 100 if r["roi"] is not None else None,
        "95% interval": (f"{r['lo']:+.1f}% to {r['hi']:+.1f}%"
                         if r["lo"] is not None else "—"),
        "Verdict": ("Too few bets to say" if r.get("thin")
                    else _VERDICT_PLAIN.get(r["verdict"], r["verdict"])),
    } for r in rows])


def _money(roi_pct: float | None) -> str:
    """A return, phrased the way someone who does not bet would think about it.

    "+12.0% ROI" is a unit of measurement most people have never used. "$112
    back on every $100" is the same fact and needs no translation.

    Dollar signs are escaped because Streamlit's markdown treats a matched pair
    of them as inline LaTeX, which silently turns "$112 back on every $100" into
    typeset mathematics.
    """
    if roi_pct is None:
        return "—"
    return f"\\${100 + roi_pct:,.0f} back on every \\$100 staked"


def _bet_guidance(econ: dict, n: int) -> tuple[list[str], list[str]]:
    """Plain do / do-not advice, derived from the tables rather than typed out.

    Every line here quotes a number the page also shows, so the advice cannot
    drift away from the evidence when the backtest is re-run on new seasons.
    """
    h = econ["headline"]
    proven = bool(h and h["verdict"] == "positive")
    ranks = econ.get("by_rank") or []
    buckets = econ.get("by_odds_bucket") or []
    seasons = econ.get("by_season") or []

    deepest = max((r["rank"] for r in ranks if r["verdict"] == "positive"),
                  default=0)
    worst_band = min(buckets, key=lambda r: r["roi"]) if buckets else None
    good_seasons = sum(1 for r in seasons if r["verdict"] == "positive")

    comparison = {(r["ranked_by"], r["top_n"]): r
                  for r in econ.get("blend_comparison") or []}
    model_row = comparison.get(("model only (pre-blend)", n))
    blend_row = comparison.get(("blended (published)", n))

    do: list[str] = []
    dont: list[str] = []

    if proven:
        depth_phrase = (
            "Only the top-rated player in a game held up on their own"
            if deepest == 1 else
            f"Ranks 1 to {deepest} each held up on their own"
            if deepest > 1 else
            "No individual rank held up on its own, which is worth knowing"
        )
        do.append(
            f"**Stick to the top of each game.** Backing our top {n} returned "
            f"{_money(h['roi'])}. {depth_phrase}; past that the advantage fades."
        )
        # What "profitable in N of M seasons" means depends entirely on N. The
        # copy used to call any N "the reason to take it seriously", which read
        # as an endorsement of a model that had worked once in three years.
        if good_seasons == len(seasons):
            do.append(
                f"**Treat it as {len(seasons)} seasons of evidence, not a "
                f"promise.** It was profitable in every season separately, "
                f"which is the reason to take it seriously — and still only "
                f"{econ['games']:,} games."
            )
        else:
            season = "season" if good_seasons == 1 else "seasons"
            do.append(
                f"**Be sceptical of the headline.** The pooled figure is "
                f"positive, but it was only profitable in {good_seasons} "
                f"{season} out of {len(seasons)}. A strategy that works in one "
                f"year and not the next is usually one year of luck, not an "
                f"edge — the season-by-season table below is the honest view."
            )
        if model_row and blend_row:
            gap = model_row["roi"] - blend_row["roi"]
            do.append(
                f"**Use the model's own number, not the one on the board.** The "
                f"board blends our estimate with the bookmaker's to be more "
                f"accurate. For betting that costs about {gap:.0f} points of "
                f"return, because agreeing with the price is the opposite of "
                f"having a reason to bet."
            )
        do.append(
            "**Stake small and stake the same each time.** No staking scheme "
            "turns a bad bet good. Sizing only changes how quickly you find out."
        )
    else:
        do.append(
            "**Do not bet this market yet.** Follow it on paper for a season "
            "and see whether the pattern survives. Nothing is lost by waiting."
        )
        do.append(
            "**Look at the other market instead.** The two are measured the "
            "same way and only one of them currently clears its prices."
        )

    if worst_band:
        dont.append(
            f"**Do not chase the big prices.** Every price band loses money "
            f"backed blindly; the longest ones are the worst, at "
            f"{_money(worst_band['roi'])} in the {worst_band['bucket']} band. "
            f"We sort those players well — that is not the same as them being "
            f"good bets."
        )
    dont.append(
        "**Do not bet more because a week went badly.** Long runs of losing "
        "games are normal and mean nothing on their own — the staking section "
        "below shows how long they actually got."
    )
    dont.append(
        "**Do not treat this as income.** It is a small advantage measured at "
        "prices that had already closed. Money you would mind losing does not "
        "belong here."
    )
    return do, dont


_ROI_COLS = {
    "Hit": st.column_config.NumberColumn(
        "Won", format="percent",
        help="How often these bets actually won."),
    "Break-even": st.column_config.NumberColumn(
        "Needed to break even", format="percent",
        help="How often you would have to win, at these prices, just to end "
             "level. The only thing that matters is whether the column to the "
             "left beats this one — winning often on short prices still loses."),
    "Odds": st.column_config.NumberColumn(
        "Typical price", format="%+d",
        help="A +150 price pays \\$150 profit on a \\$100 bet. A -150 price "
             "pays \\$67 on the same \\$100."),
    "ROI": st.column_config.NumberColumn(
        "Profit per \\$100", format="percent",
        help="Profit for every \\$100 staked, betting the same amount on every "
             "one of these. +12% means \\$12 profit per \\$100."),
    "95% interval": st.column_config.TextColumn(
        "Could plausibly be",
        help="The range of results that luck alone could have produced. If it "
             "includes zero, the profit column is not evidence of anything. "
             "Worked out by reshuffling whole games, because two bets in the "
             "same game share a defence and a final score."),
}


with tab_bet:
    render_accuracy_strip(target_type, selected_model)
    econ = rank_economics(target_type, selected_model)

    if econ is None:
        st.info(
            "Not measured yet. Run `python scripts/10_backtest.py --season <yr> "
            f"--target {target_type}` for each season you hold prices for, then "
            f"`python scripts/14_rank_economics.py --target {target_type}`.",
            icon=":material/info:",
        )
    else:
        h = econ["headline"]
        n = econ["headline_n"]
        span = f"{econ['seasons'][0]}-{econ['seasons'][-1]}"

        if econ.get("stale_for"):
            st.warning(
                f"**These figures were not measured on `{econ['stale_for']}`.** "
                f"You have that model selected, but the profitability below was "
                f"measured on `{econ.get('measured_on') or production_model(target_type)}`. "
                f"Run `make backtest TARGET={target_type} MODEL={econ['stale_for']}` "
                f"for each season, then `python scripts/14_rank_economics.py "
                f"--target {target_type} --model {econ['stale_for']}` to measure "
                f"this one. Until then, treat the page as describing a different "
                f"model from the board.",
                icon=":material/warning:",
            )

        st.subheader("The short version")
        if h and h["verdict"] == "positive":
            st.success(
                f"**Backing the {n} players we rate highest in each game made "
                f"money.** Over {econ['games']:,} games in {span}, betting the "
                f"same small amount on each returned {_money(h['roi'])}. That "
                f"held up in every season separately, so it is unlikely to be "
                f"one lucky year.",
                icon=":material/trending_up:",
            )
        elif h:
            st.warning(
                f"**We cannot show this market makes money.** Backing our top "
                f"{n} in each game came out at {_money(h['roi'])} over "
                f"{econ['games']:,} games — but the result is well within what "
                f"chance alone produces, so there is nothing here to act on. "
                f"Being good at predicting is not the same as being good at "
                f"betting.",
                icon=":material/warning:",
            )

        with st.container(border=True):
            st.markdown("#### If you have never bet on this before")
            st.markdown(
                "**You start behind, always.** A bookmaker's prices for a game "
                "add up to more than 100%. The extra is their cut — roughly 10 "
                "to 20% on touchdown markets. It is the reason most people who "
                "bet lose slowly even when their picks are sensible.\n\n"
                "**So being right often is not the target.** If a player is "
                "priced at +150, you win \\$150 on a \\$100 bet, and you need "
                "to be right 40% of the time simply to end level. Right 39% of "
                "the time loses money, even though it sounds almost the same.\n\n"
                "**That makes two different questions.** *Is the model "
                "accurate?* is answered on the **Model performance** tab, and "
                "the answer is yes. *Is it accurate enough to beat the price "
                "the bookmaker set?* is answered on this page, and the answer "
                "is not automatically yes — it has to be measured, market by "
                "market, which is what everything below does."
            )

        do, dont = _bet_guidance(econ, n)
        st.subheader("What we would actually suggest")
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                st.markdown("##### :material/check_circle: Reasonable")
                for line in do:
                    st.markdown(f"- {line}")
        with right:
            with st.container(border=True):
                st.markdown("##### :material/block: Not reasonable")
                for line in dont:
                    st.markdown(f"- {line}")

        st.divider()
        st.subheader("The numbers behind this")
        st.caption(
            f"Everything below is measured on real prices a sportsbook offered "
            f"in {span}, replayed as if we had bet the same small amount every "
            f"time. Each row carries a **95% range** — the spread of results "
            f"chance alone could produce. A range that includes zero means we "
            f"genuinely cannot tell that result apart from luck, however good "
            f"the headline number looks. The top {n} strategy was chosen before "
            f"any of this was run, because picking the best-looking row "
            f"afterwards finds a winner whether or not one exists."
        )

        st.markdown("##### Back everyone we rank N or better")
        st.dataframe(_roi_rows(econ["top_n"], "top_n", "Top N"),
                     hide_index=True, column_config=_ROI_COLS)

        st.markdown("##### By our rank")
        st.caption(
            "Backing only the Nth-favourite player in each game, every week. "
            "Where this stops making money is where a card should stop — it is "
            "the honest answer to \"how many should I take?\""
        )
        st.dataframe(_roi_rows(econ["by_rank"], "rank", "Rank"),
                     hide_index=True, column_config=_ROI_COLS)

        rule = econ.get("edge_rule")
        if rule:
            st.markdown("##### By how far we disagree with the price")
            st.caption(
                "The most useful table on this page, and the only split here "
                "that theory predicted in advance. Profit is a claim about our "
                "number versus the price — where we barely disagree there is "
                "nothing to win, whatever the ranking says. Measured before "
                "the blend, because the published estimate has already been "
                "pulled toward the price it is being compared against."
            )
            k, d = rule["kept"], rule["dropped"]
            st.dataframe(pd.DataFrame([
                {"Group": f"Bet edge {rule['edge_cut'] * 100:.0f} pts or more",
                 "Bets": k["n"], "Hit": k["hit_pct"] / 100,
                 "Break-even": k["breakeven_pct"] / 100, "Odds": k["median_odds"],
                 "ROI": k["roi"] / 100,
                 "95% interval": f"{k['lo']:+.1f}% to {k['hi']:+.1f}%",
                 "Verdict": _VERDICT_PLAIN.get(k["verdict"], k["verdict"])},
                {"Group": f"Below {rule['edge_cut'] * 100:.0f} pts (skip these)",
                 "Bets": d["n"], "Hit": d["hit_pct"] / 100,
                 "Break-even": d["breakeven_pct"] / 100, "Odds": d["median_odds"],
                 "ROI": d["roi"] / 100,
                 "95% interval": f"{d['lo']:+.1f}% to {d['hi']:+.1f}%",
                 "Verdict": _VERDICT_PLAIN.get(d["verdict"], d["verdict"])},
            ]), hide_index=True, column_config=_ROI_COLS)
            st.caption(
                f"Profitable in every season separately — "
                + ", ".join(f"{r['season']} {r['roi']:+.0f}%"
                            for r in rule["per_season"])
                + f" — at about {rule['bets_per_week']:.0f} bets a week. **The "
                f"cut-off is fitted, not chosen**: the code tries ten of them "
                f"and keeps the smallest that both pays and identifies bets "
                f"worth skipping, so next season re-fits the number instead of "
                f"inheriting this one. That it lands near zero is reassuring — "
                f"zero is where the maths says the boundary belongs, since a "
                f"bet is worth making the moment our number beats the vig-free "
                f"price. A rule that had landed at 8 points would be a fitted "
                f"parameter wearing a theory's clothes."
            )

        if econ.get("edge_curve"):
            with st.expander("The full curve, band by band"):
                st.caption(
                    "Why the rule is a single cut-off rather than a sliding "
                    "scale. Pooled, more disagreement pays more. Band by band "
                    "it is noisy — each of these holds only ~200 bets, and "
                    "several individually say nothing. The honest reading is "
                    "that the two ends are real and the middle is not resolved."
                )
                st.dataframe(pd.DataFrame([{
                    "Bet edge": (f"{r['edge_from'] * 100:.0f}-"
                                 f"{r['edge_to'] * 100:.0f} pts" if r.get("edge_to")
                                 else f"{r['edge_from'] * 100:.0f} pts or more"),
                    "Bets": r["n"], "Hit": r["hit_pct"] / 100,
                    "Break-even": r["breakeven_pct"] / 100,
                    "Odds": r["median_odds"], "ROI": r["roi"] / 100,
                    "95% interval": f"{r['lo']:+.1f}% to {r['hi']:+.1f}%",
                    "Verdict": _VERDICT_PLAIN.get(r["verdict"], r["verdict"]),
                } for r in econ["edge_curve"]]), hide_index=True,
                    column_config=_ROI_COLS)

        st.markdown("##### By price")
        st.caption(
            "Ignoring our ranking entirely — what happens if you just back "
            "everyone at a given price. Every band loses, which is the "
            "bookmaker's cut showing up as a number. Long prices are not "
            "\"value\"; they are where the cut is largest."
        )
        st.dataframe(_roi_rows(econ["by_odds_bucket"], "bucket", "Price band"),
                     hide_index=True, column_config=_ROI_COLS)

        if econ.get("blend_comparison"):
            st.markdown("##### Which of our numbers should you bet on?")
            st.caption(
                "The board shows a figure that mixes our estimate with the "
                "bookmaker's, because that mix predicts who scores more "
                "accurately. It is still the wrong number to bet on. A bet only "
                "makes sense when you disagree with the price, and mixing our "
                "view into the price is exactly the act of giving that "
                "disagreement up. \"Market only\" is what you get by simply "
                "believing the bookmaker — it loses money, which is the cut again."
            )
            st.dataframe(pd.DataFrame([{
                "Ranked by": r["ranked_by"], "Top N": r["top_n"], "Bets": r["n"],
                "ROI": r["roi"] / 100,
                "95% interval": f"{r['lo']:+.1f}% to {r['hi']:+.1f}%",
            } for r in econ["blend_comparison"]]), hide_index=True,
                column_config={"ROI": _ROI_COLS["ROI"],
                               "95% interval": _ROI_COLS["95% interval"]})

        st.markdown(f"##### Top {n}, season by season")
        st.caption(
            "One good season is not a strategy — it is a coincidence with a "
            "large sample size. This is the check that matters most."
        )
        st.dataframe(_roi_rows(econ["by_season"], "season", "Season"),
                     hide_index=True, column_config=_ROI_COLS)

        worst = max((r.get("concentration") or 0) for r in econ["top_n"])
        if worst > 1:
            st.warning(
                f"**Take the profit above with a large pinch of salt.** On at "
                f"least one row, the ten biggest wins account for more than all "
                f"of the profit ({worst:.0%}) — remove those ten results and the "
                f"strategy loses money. That is a description of ten lucky "
                f"afternoons, not something to expect again.",
                icon=":material/warning:",
            )
        elif worst > 0.5:
            st.warning(
                f"**A few results are carrying a lot of this.** On at least one "
                f"row above, the ten biggest wins produce {worst:.0%} of the "
                f"profit. The further that is from zero, the more the return "
                f"describes those particular games rather than a rate you can "
                f"count on repeating.",
                icon=":material/warning:",
            )

        with st.expander("How this was worked out, and what it cannot tell you"):
            st.markdown(f"""
**These are real prices, not invented ones.** Every figure comes from prices a
sportsbook genuinely offered in {span}, replayed through exactly the same steps
that produce the board on the first tab. When the replay reached a given week it
was only allowed to use games that had already finished, so nothing here got to
peek at its own answers.

**The same stake on every bet**, deliberately. How much you stake changes how
fast money moves, never which direction — so no sizing scheme could rescue a bad
bet, and allowing one here would only flatter the results.

**Why "could plausibly be" is the column that matters.** Over a few hundred
games, luck alone can produce a run that looks exactly like skill. That column is
the range luck could account for. When it includes zero, the profit figure beside
it is not evidence of anything, however healthy it looks. It is worked out by
reshuffling whole games rather than individual bets, because two bets in the same
game share a defence, a game script and a final score — treating them as separate
would make everything here look about twice as convincing as it is.

**Three things it genuinely cannot tell you.** Whether a bookmaker would accept
these bets, and at what size — accounts that keep winning tend to get restricted.
Whether the price you can actually get resembles the closing price measured here.
And whether the next three seasons will behave like the last three. All three
matter and none of them are in this data.
""")

        clv = clv_by_rank(target_type)
        if not clv and _section_error(f"clv:{target_type}"):
            st.warning(
                f"**Line-movement check could not run.** "
                f"`{_section_error(f'clv:{target_type}')}` — this section is "
                f"missing because something broke, not because the market has "
                f"no signal.",
                icon=":material/error:",
            )
        if clv:
            st.markdown("##### Does the betting market drift toward our picks?")
            st.caption(
                "A different kind of evidence, and the only one that does not "
                "depend on who happened to score. Prices move during the week as "
                "money comes in. If the players we rate highest tend to get "
                "*shorter* — cheaper to back early, dearer later — then the rest "
                "of the market is gradually arriving at the same view we started "
                "with. Because every priced player counts, not just the ones who "
                "scored, this is a far harder number to fluke than a win rate."
            )
            st.dataframe(pd.DataFrame([{
                "Group": (f"Our top {r['top_n']}" if r["top_n"] else "All priced players"),
                "Players": r["n"],
                "Held up vs the field": r["vs_field"] / 100,
                "Price shortened": r["pct_shortened"],
            } for r in clv]), hide_index=True, column_config={
                "Held up vs the field": st.column_config.NumberColumn(
                    format="percent",
                    help="How much better this group's price held than the "
                         "average priced player. The whole board drifts as more "
                         "books come in between the open and kickoff, so this "
                         "comparison is the meaningful one, not the raw move."),
                "Price shortened": st.column_config.NumberColumn(
                    format="percent",
                    help="Share of this group whose price got shorter by "
                         "kickoff — the market coming toward our view."),
            })
            best = clv[0]
            ranked = [r for r in clv if r["top_n"]]
            # A real effect should fade as the group widens. If it does not, or
            # if it is too small to matter, say so rather than narrating a
            # dose-response that is not in the data.
            ordered = all(a["vs_field"] >= b["vs_field"]
                          for a, b in zip(ranked, ranked[1:]))
            meaningful = best["vs_field"] >= 0.002
            if ordered and meaningful:
                st.caption(
                    f":material/insights: **This one lines up.** The higher we "
                    f"rate a player, the better their price holds — in order, "
                    f"with no exceptions. Our top pick gets shorter "
                    f"**{best['pct_shortened']:.0%}** of the time against "
                    f"**{clv[-1]['pct_shortened']:.0%}** for the board at large. "
                    f"In plain terms: the market tends to end up agreeing with "
                    f"us, and it does so most for the players we are most sure "
                    f"about."
                )
            elif meaningful:
                st.caption(
                    f":material/info: Our top picks hold their price better than "
                    f"the board, but the pattern is not tidy — it does not fade "
                    f"smoothly as the group widens, which is what you would "
                    f"expect if our ranking were what the market was responding "
                    f"to. Treat this as weak support rather than confirmation."
                )
            else:
                st.caption(
                    f":material/warning: **Nothing much here.** Our top picks "
                    f"hold their price only "
                    f"**{best['vs_field']*100:+.2f}pp** better than the average "
                    f"priced player, which is close enough to zero to mean the "
                    f"market is not moving toward our view in this market. The "
                    f"supporting evidence that exists elsewhere on this page is "
                    f"absent here."
                )

        # ── Phase 2: what to stake ───────────────────────────────────────
        st.divider()
        st.subheader("How much to put on")

        if not (h and h["verdict"] == "positive"):
            st.info(
                "There is nothing to size here. How much you stake changes how "
                "fast money moves, never which direction — no staking rule turns "
                "a losing bet into a winning one. The comparison below is shown "
                "for completeness, not as a suggestion.",
                icon=":material/info:",
            )
        else:
            st.caption(
                "Below is the same set of bets from the tables above, replayed "
                "four different ways: same amount every time, or varying the "
                "amount by how strongly we like each pick. **This is the part "
                "people get wrong.** Betting more when you feel confident is how "
                "a small advantage turns into a large loss, because feeling "
                "confident and being right are not the same thing."
            )

        bankroll = st.number_input(
            "Money set aside for this (\\$)", min_value=10.0, max_value=100_000.0,
            value=1000.0, step=50.0,
            help="Not your savings — an amount you would be genuinely fine "
                 "losing in full. Every method below is replayed against this "
                 "figure across every game we hold prices for.",
        )

        alloc = allocation_backtest(target_type, n, bankroll)
        if not alloc and _section_error(f"alloc:{target_type}"):
            st.warning(
                f"**Staking comparison could not run.** "
                f"`{_section_error(f'alloc:{target_type}')}` — this section is "
                f"missing because something broke, not because there is nothing "
                f"to compare.",
                icon=":material/error:",
            )
        if alloc:
            kelly = next((r for r in alloc if r["method"] == "kelly"), None)
            if kelly:
                st.markdown("**What a bad patch looks like, with that amount**")
                stats = st.container(horizontal=True)
                stats.metric("Biggest fall along the way",
                             f"-{kelly['max_drawdown_pct']:.1f}%",
                             help="How far the balance dropped from its best "
                                  "point before recovering. This is the number "
                                  "you have to sit through, and it happens to "
                                  "everyone who does this.")
                stats.metric("Longest run of losing games",
                             f"{kelly['longest_losing_streak']} games",
                             help="Consecutive games that lost money. Runs like "
                                  "this are normal and are not a sign anything "
                                  "has stopped working.")
                stats.metric("Typical stake per game",
                             f"${kelly['staked'] / max(kelly.get('games', 1), 1):,.0f}",
                             help="Averaged across every game. Small stakes are "
                                  "the point, not a limitation.")
                st.caption(
                    "If those two numbers would bother you, the honest answer "
                    "is that this is not for you — and that is a perfectly "
                    "sensible conclusion to reach."
                )
                st.markdown("**The four ways of dividing the money**")
            st.dataframe(
                pd.DataFrame([{
                    "Method": {
                        "flat": "Same amount every time",
                        "equal": "Split evenly across the game's picks",
                        "kelly": "Scaled to how strongly we like it (quarter Kelly)",
                        "ev": "Scaled to expected profit",
                    }[r["method"]],
                    "Return per $ staked": (r["roi_on_turnover"] / 100
                                            if r["roi_on_turnover"] is not None else None),
                    "Worst drop": r["max_drawdown_pct"] / 100,
                    "Longest losing run": r["longest_losing_streak"],
                    "Total staked": r["staked"],
                    "Final balance": r["final_bankroll"],
                } for r in alloc]),
                hide_index=True,
                column_config={
                    "Return per $ staked": st.column_config.NumberColumn(
                        format="percent",
                        help="Profit for every dollar you put at risk. This is "
                             "the fair way to compare, because these methods "
                             "risk very different amounts of money."),
                    "Worst drop": st.column_config.NumberColumn(
                        format="percent",
                        help="How far the balance fell from its best point "
                             "before recovering. The number you have to live "
                             "through, not read about."),
                    "Longest losing run": st.column_config.NumberColumn(
                        help="Most games in a row that lost money."),
                    "Total staked": st.column_config.NumberColumn(format="dollar"),
                    "Final balance": st.column_config.NumberColumn(format="dollar"),
                },
            )
            st.caption(
                "**Ignore the final balance column.** It compounds a measured "
                "advantage over hundreds of games, so it balloons if that "
                "advantage is real and collapses if it is a point or two "
                "overstated — it is the least trustworthy number on this page. "
                "The first two columns are the ones that separate the methods."
            )

        with st.expander("What the four methods actually do"):
            st.markdown("""
**Same amount every time** — one fixed stake, win or lose, forever. Boring, and
the benchmark everything else has to beat. Anything that cannot beat it is
complexity for its own sake.

**Split evenly across the game's picks** — decide what a game is worth, then
divide it equally between the players you are backing. Simple, but it ignores
both the price and how strongly we like each one, so it puts as much on a pick
we barely fancy as on one we are sure about.

**Scaled to how strongly we like it (quarter Kelly)** — bet more when the gap
between our estimate and the price is wider, then deliberately bet only a
quarter of what the formula says. There is a well-known formula (Kelly) that
grows money fastest *if your probabilities are exactly right*. Ours are not
exactly right, and betting the full amount on slightly-wrong probabilities is a
reliable way to lose everything. The quarter is the insurance premium for not
being as clever as you think.

**Scaled to expected profit** — bet more where the maths says the profit is
biggest. Sounds obviously correct, and it is the one that hurts most: it piles
money onto long prices, which pay rarely, so the swings are brutal.

**What none of them fix.** Every figure above assumes you can get that exact
price, at that size, at the moment we publish it. In practice bookmakers limit
accounts that keep winning, and the price you see may not be the one measured
here. That assumption is doing more work than any of the maths.
""")
