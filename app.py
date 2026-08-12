"""NFL TD Prediction Dashboard — Streamlit app."""
import sys
from pathlib import Path

# The app's own directory, not the working directory. `streamlit run` can be
# invoked from anywhere, and `"."` silently resolved to whatever shell the
# container happened to start in.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import functools
import json
import pickle

import numpy as np
import pandas as pd
import polars as pl
import plotly.graph_objects as go
import streamlit as st

from src.utils.config import get_config
from src.utils.paths import get_path
from src.models.trainer import prepare_data, _filter_low_activity
from src.models.registry import get_model, ensure_registered
from src.models.scoring import score
from src.features.definitions import get_definition
from src.presentation import board as bp


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
        key="sidebar_target_type",
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
        key="sidebar_model",
    )

    # Every artifact on this page is read through `st.cache_data`, which has no
    # expiry — deliberately, because a mixture of TTLs would leave the board
    # fresh while the accuracy strip above it still described the old model.
    # Retraining under a running server therefore needs one explicit,
    # all-at-once invalidation rather than several staggered ones.
    if st.button("Reload artifacts", icon=":material/refresh:",
                 key="reload_artifacts",
                 help="Re-read models, backtests and fitted rules from disk. "
                      "Needed after `make train` or `make evaluate` while the "
                      "app is running — otherwise it serves what it loaded at "
                      "startup."):
        st.cache_data.clear()
        st.rerun()

st.title("First TD Scorer" if target_type == "first_td" else "Anytime TD Scorer")

# Two tabs. The goal is the most accurate probability for every player, not a
# hunt for mispriced ones — so there is one board showing everybody, and one
# place to check how well the model actually ranks. Separate Bets / Fades /
# Parlay tabs were three filtered views of this same table, which invited the
# reading that the filtered rows were the answer and the rest were noise.
#
# "Player types" answers a question none of the others do: not how good the
# number is, but what kind of thing it is about. Named in plain words like the
# rest of them — it is a clustering underneath, which is not what anyone is
# looking for when they open a tab.
#
# `on_change="rerun"` makes the tabs lazy. By default Streamlit runs every
# tab's body on every rerun, so typing one character into the board's player
# search also re-ran Weekly results, Model performance, Betting reality and
# Player types — five tabs of work for one keystroke, four of them not on
# screen. Each body is now guarded by `if tab.open:`.
tab_board, tab_results, tab2, tab_bet, tab_clusters = st.tabs(
    ["Full board", "Weekly results", "Model performance", "Betting reality",
     "Player types"],
    on_change="rerun",
)


# ── Helpers ─────────────────────────────────────────────────────────────────


def guarded(fn):
    """Turn a section's loader into one that returns `(value, error)`.

    A swallowed exception used to remove a whole panel from the page with
    nothing said, which is indistinguishable from "this market has no data" and
    sends you looking in the wrong place. The first version of this fix wrote
    the message into a module-level dict, which was wrong three ways: the dict
    was defined ~850 lines below its earliest writer, so the `except` branch
    raised `NameError` and took the page down instead of reporting; it was
    written *inside* `@st.cache_data` functions, so on a cache hit the message
    was never re-recorded and the section went quiet again; and being module
    state on a shared server, one visitor's error rendered on another's page.

    Returning the message alongside the value fixes all three: it is cached
    with the result it belongs to, it exists wherever the value does, and it
    travels with the call rather than with the process.

    Wrap *under* `@st.cache_data` so the tuple is what gets cached.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs), None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"
    return wrapper


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


# ── Removed: the app's own odds path ──────────────────────────────────────
# `load_odds`, `match_odds_to_game`, `get_vegas_info`, `format_vegas`,
# `_normalize_name`, `_scored_per_game`, `_scored_rows` and a hand-copied
# 34-team abbreviation map lived here, alongside `run_prediction` and
# `load_schedules`. Nothing called any of them: the board gets its prices and
# its de-vigging from `board_for_week`, and its predictions from the same
# scoring path the backtest uses. They were a second, older implementation of
# both — the kind that drifts silently because no page renders it.


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


# `edge_color` lived here: it painted a row green or red at a hand-picked
# +/-2pp. It had no callers — `confidence_cuts` replaced it and reads the
# thresholds off the backtest instead, so "unusually far from the market" means
# unusually far *for this model* rather than for a number someone typed.


def _load_and_predict(model_name, feature_cols, X, model_dir):
    """Calibrated probabilities, through the one shared scoring path.

    This was a hand-rolled copy of src.models.scoring.score — load each model,
    apply its calibrator, weight and sum. Copies of that path have drifted
    before, which is why the module exists, and this one drifted again: it
    never picked up the tie-break that separates players landing on the same
    isotonic step, so the app ordered a quarter of games' top picks by row
    order while the backtest it quotes did not.
    """
    return score(model_name, X, feature_cols, model_dir,
                 active_models=active_models)


def get_available_weeks(df, season):
    """Return sorted list of weeks available for a season."""
    weeks = (
        df.filter(pl.col("season") == season)
        .select("week").unique()
        .sort("week")["week"].to_list()
    )
    return weeks


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

    # No bankroll control, even though the board is now denominated in dollars.
    # Everything on screen is quoted per $100 flat, which is a unit rather than
    # a stake — it makes rows comparable without implying a plan. Kelly sizing
    # still exists in src/prediction/bets.py for the CLI, where it reads the
    # config value; putting a bankroll box here would turn a unit into a
    # recommendation, and the sizing evidence lives in Betting reality.


# ── The board ─────────────────────────────────────────────────────────────


@st.cache_data(show_spinner="Pricing this week's board...", max_entries=32)
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

        # The two directional figures were buried in a banner. They are the most
        # informative numbers the model produces and they belong beside the rest
        # of the track record — particularly because they disagree so sharply
        # that quoting only their average misleads.
        hi, lo = h2h.get("disagree_higher_pct"), h2h.get("disagree_lower_pct")
        if hi is not None:
            strip.metric(
                "Closer — backable", f"{hi:+.0f}%",
                delta=f"{h2h.get('disagree_higher_n', 0):,} players",
                delta_color="off",
                help=f"On the tenth of players we differ from the book on most, "
                     f"taking only those we rate **higher** — the direction "
                     f"these markets let you bet. The percentage by which our "
                     f"average squared miss is *smaller* than the book's across "
                     f"{h2h['span']}. **0% would mean we match the book**, so "
                     f"this is a win; it is not a win rate and there is no 50% "
                     f"baseline.")
        if lo is not None:
            strip.metric(
                "Closer — fade", f"{lo:+.0f}%",
                delta=f"{h2h.get('disagree_lower_n', 0):,} players",
                delta_color="off",
                help=f"The same comparison for players we rate **lower** than "
                     f"the book — again, how much smaller our average squared "
                     f"miss is, against a 0% break-even. This is the model's "
                     f"sharpest skill by a wide "
                     f"margin — and there is no way to bet it, because these "
                     f"markets only sell the Yes side. Useful as a veto: a big "
                     f"disagreement downward is a player to leave alone. The "
                     f"**vs bookmaker** figure blends this with the backable "
                     f"half, which is why it reads higher than what you can "
                     f"actually act on.")


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
        # "Thin" used to mean "under 5%", a number nobody measured. The
        # bootstrap already answers the question it was standing in for: an
        # interval touching zero means we cannot tell ourselves apart from the
        # bookmaker, whatever the point estimate reads.
        if h2h.get("overall_lo") is not None and h2h["overall_lo"] <= 0:
            parts.append(
                f"\n:material/warning: **That margin is not established.** The "
                f"range around it is {h2h['overall_lo']:+.1f}% to "
                f"{h2h['overall_hi']:+.1f}%, which includes zero — on this "
                f"market we cannot be told apart from the bookmaker. Treat "
                f"these as a second opinion, not an edge.\n"
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
        # The season is read from config rather than written here: it said
        # "2025" while rank_hit_rates has always used splits.test_season, so it
        # was correct only until that config changed.
        help=f"What actually happened to players in this slot across the whole "
             f"{cfg['splits']['test_season']} season. A second opinion on the "
             f"row: if our estimate sits well above or below it, the model may "
             f"be running hot or cold at this rank rather than knowing "
             f"something specific about this player.",
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
    "EV": st.column_config.NumberColumn(
        # Plain "$" here, escaped "\\$" in `help` — a column label is drawn as
        # text in the grid, but help is markdown, where Streamlit reads a
        # matched pair of dollar signs as LaTeX.
        "Expected on $100", format="$%+.2f", width="medium",
        help="What a flat \\$100 bet on this player returns **on average**, if "
             "our number is right — \\$100 risked, won at the price in "
             "**Odds**.\n\n"
             "This is the column that separates a good estimate from a good "
             "bet, because probability points and money are not the same "
             "thing. A +3 point **Bet edge** at -185 still loses: you risk "
             "\\$185 to win \\$100, so 43% has to clear a 65% break-even. The "
             "same +3 points at +170 makes money. Both rows look identical in "
             "**Difference**.\n\n"
             "Measured on our number *before* the blend, like **Bet edge**, "
             "but paid at the raw price, because that is what a book actually "
             "pays. It is what the model **expects**, not what it has "
             "**returned** — for the second, see **Betting reality**.",
    ),
    "Best": st.column_config.TextColumn(
        "Best price", width="small",
        help="The best price across the books we archived this week, against "
             "the consensus in **Odds**. Nobody can bet a consensus — this is "
             "what you could actually take. Every profitability figure in this "
             "app is measured at the consensus, so it understates a shopped "
             "price by whatever this gap is worth."),
    "BestBook": st.column_config.TextColumn("at", width="small",
        help="Which book was offering it when we snapshotted."),
    "Status": st.column_config.TextColumn(
        "Injury", width="small",
        help="This week's designation. **Out** or **Doubtful** means the "
             "model's number is meaningless rather than merely pessimistic — "
             "do not back them. **Questionable** is worth checking rather than "
             "avoiding. A blank means the player is not on the report; if no "
             "report has been published yet the column does not appear at all, "
             "because that is no information rather than a clean bill of "
             "health."),
    "InRange": st.column_config.TextColumn(
        "Worth backing", width="small",
        help=bp.tier_help(region),
    ),
    }


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

    The gate is the fitted edge rule: a cut-off that both pays and identifies
    bets worth skipping, in every season separately. It lives in
    src/evaluation/rank_economics.py so it can be tested without standing up
    Streamlit — it decides what the board is allowed to claim.

    It used to *also* require the headline top-N strategy to be profitable.
    That asked the wrong question. "Would backing our top three blindly have
    made money" is not the same as "is there a validated rule here", and on
    first TD the answer is no to the first (+0.8%, spanning zero) and yes to
    the second (+15.5% [+1.2, +30.1], positive every season). Gating on the
    blunt version suppressed a rule that had already passed the sharper test.

    Returns None when no rule qualifies, and the board then marks nothing.
    """
    econ = rank_economics(tt, model)
    if econ is None:
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


@st.cache_data(show_spinner=False, max_entries=32)
@guarded
def best_prices(tt: str, season: int, week: int) -> pd.DataFrame | None:
    """Best available price per player, from the per-book archive."""
    from src.evaluation.line_shopping import best_vs_consensus
    d = best_vs_consensus(season, week, tt)
    return d.to_pandas() if d is not None and d.height else None


@st.cache_data(show_spinner=False, max_entries=32)
@guarded
def injury_status(tt: str, season: int, week: int) -> pd.DataFrame | None:
    """This week's injury designations, or None when no report exists yet."""
    from src.prediction.availability import status_for
    d = status_for(season, week)
    return d.to_pandas() if d is not None and d.height else None


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
        Odds=frame["odds"].map(bp.american),
        Rank=ranks,
        Ours=frame["probability"] * 100,
        AtRank=ranks.map(lambda r: rates.get(int(r), float("nan")) * 100),
        Confidence=frame["edge_pp"].map(lambda e: bp.confidence(e, lo, hi)),
        Book=frame["market_prob"] * 100,
    )
    # Typical at # -> Our estimate -> Bookmaker says -> Difference -> Our read.
    # The two probabilities sit side by side so the comparison is a glance
    # rather than a scan, the gap between them follows immediately, and the
    # verdict reads last. "Typical at #" leads as the baseline the estimate is
    # departing from.
    cols = ["Player", "team", "Game", "Odds", "Rank", "AtRank", "Ours",
            "Book", "edge_pp", "Confidence"]

    # Best available price sits beside the consensus, because the consensus is
    # the one number on this board nobody can actually bet.
    if "best_odds" in frame.columns and frame["best_odds"].notna().any():
        show = show.assign(
            Best=frame["best_odds"].map(lambda o: bp.american(o) if pd.notna(o) else ""),
            BestBook=frame["best_book"].fillna(""),
        )
        cols = cols[:4] + ["Best", "BestBook"] + cols[4:]

    # Availability last, so a ruled-out player is the final thing read on the row.
    if "report_status" in frame.columns and frame["report_status"].notna().any():
        show = show.assign(Status=frame["report_status"].fillna(""))
        cols = cols + ["Status"]

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
    # Only where the pre-blend view actually differs. First TD is not blended,
    # so its Bet # is its # and its Bet edge is its Difference — two columns
    # repeating two others, which reads as a distinction the market does not
    # have. Anytime TD blends, so there they genuinely disagree.
    # Two separate decisions. The labels apply wherever a rule was fitted; the
    # pre-blend pair only where it says something the columns to its left do
    # not. Gating both on the second hid the labels on a market that has them.
    if rule:
        if bp.preblend_columns_differ(frame):
            show = show.assign(BetRank=frame["bet_rank"],
                               BetEdge=frame["model_edge_pp"])
            cols = cols + ["BetRank", "BetEdge"]
        # EV last before the label, because it is the column the label is
        # really about: "worth backing" is a claim about money, and until now
        # the board made it without ever showing the money. `ev_model_pct` is a
        # percentage of stake, which is dollars per $100 with no conversion.
        if "ev_model_pct" in frame.columns:
            show = show.assign(EV=frame["ev_model_pct"])
            cols = cols + ["EV"]
        show = show.assign(InRange=bp.highlight_tier(frame, rule))
        cols = cols + ["InRange"]

    st.dataframe(show[cols], hide_index=True,
                 column_config=board_columns(market_headtohead(tt, model), rule))


def week_board(season, week, tt: str, model: str):
    """(board, we're-higher, we're-lower, problems) for one season/week.

    Takes its inputs rather than reading the sidebar out of module scope: the
    globals made this function untestable and pinned every tab to one file.
    `problems` carries anything that failed to load, so a missing column can be
    explained on the page instead of just not appearing.
    """
    if week is None:
        st.info("Select a season and week in the sidebar.")
        return None, None, None, []
    board, msg = load_board(season, week, tt, model)
    if board is None:
        st.info(msg or "Nothing to show for this week.")
        st.caption("Players appear here once a bookmaker has posted a price for them.")
        return None, None, None, []
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
    # Best available price, where the per-book archive has this week. The
    # board's own `odds` is a consensus nobody can bet; this is the price you
    # could actually take, and the gap is riskless edge that needs no model.
    problems = []
    shop, shop_err = best_prices(tt, season, week)
    if shop_err:
        problems.append(f"Best available price: `{shop_err}`")
    if shop is not None and "player_name_norm" in board.columns:
        board = board.merge(
            shop[["player_name_norm", "best_odds", "best_book", "n_books"]],
            on="player_name_norm", how="left")

    # Injury designations. A recommendation for a player who is out is not a
    # bad bet, it is a guaranteed loss, and nothing else on this board knows.
    inj, inj_err = injury_status(tt, season, week)
    if inj_err:
        problems.append(f"Injury report: `{inj_err}`")
    if inj is not None and "player_id" in board.columns:
        board = board.merge(
            inj[["player_id", "report_status", "is_blocked"]],
            on="player_id", how="left")

    rank_src = "prob_model" if "prob_model" in board.columns else "probability"
    board["bet_rank"] = (
        board.groupby("game_label")[rank_src]
        .rank(ascending=False, method="first").astype(int)
    )
    floor = float(cfg.get("betting", {}).get("min_edge_pp", 2.0))
    higher = board[(board["edge_pp"] >= floor) & (board["ev_pct"] > 0)]
    lower = board[board["edge_pp"] <= -floor].sort_values("edge_pp")
    return board, higher, lower, problems


if tab_board.open:
    with tab_board:
        render_accuracy_strip(target_type, selected_model)
        board, backing, overvalued, problems = week_board(
            season, week, target_type, selected_model)
        for _problem in problems:
            # A column that is absent because something broke reads exactly like a
            # column that is absent because there is no data. Say which.
            st.warning(f"**{_problem}** — this column is missing because something "
                       f"broke, not because the data does not exist.",
                       icon=":material/error:")
        if board is not None:
            h2h = market_headtohead(target_type, selected_model)
            if h2h and h2h["disagree_better_pct"] > 0:
                # The numbers themselves now sit in the strip above as metrics.
                # What a banner can add is the reading of them, which is not
                # obvious: the headline figure averages two halves that point in
                # opposite directions for a bettor.
                _hi = h2h.get("disagree_higher_pct")
                _lo = h2h.get("disagree_lower_pct")
                if _hi is not None and _lo is not None:
                    st.success(
                        f"**Where we disagree with the bookmaker is where this "
                        f"model is worth reading.** On the tenth of players we "
                        f"differ from the book on most across {h2h['span']}, our "
                        f"estimate landed **{h2h['disagree_better_pct']:.0f}% "
                        f"closer** to what actually happened.\n\n"
                        f"Read that in two halves. Where we rate a player **lower** "
                        f"than the book we are **{_lo:.0f}% closer** — our sharpest "
                        f"skill, and not something these markets let you bet. Where "
                        f"we rate one **higher** we are **{_hi:.0f}% closer**, and "
                        f"that is the half you can back.",
                        icon=":material/trending_up:",
                    )
                    # "Closer" is doing a lot of unexplained work. It is a Brier
                    # skill score, so 0% is the break-even point and both halves
                    # above are wins -- without saying so, 17% reads like a loss
                    # against an imagined 50% coin flip.
                    with st.expander("What does “closer” mean here?"):
                        st.markdown(
                            f"Both our estimate and the book's are probabilities, "
                            f"and the player either scored or did not. Square the "
                            f"miss for each, average over the players, and compare. "
                            f"**“Closer” is the percentage by which our "
                            f"average squared miss is *smaller* than the book's.**\n\n"
                            f"- **0% would mean we match the book.** Anything above "
                            f"zero means we beat it, so both halves above are wins "
                            f"— {_lo:.0f}% is simply a much bigger one than "
                            f"{_hi:.0f}%.\n"
                            f"- It is **not** a win rate. There is no 50% baseline "
                            f"here, and it does not count how often we were nearer "
                            f"— one badly wrong call costs more than two "
                            f"near-misses, which is the point of squaring.\n"
                            f"- Each half is measured **only on the players where we "
                            f"disagree with the book in that direction**, and only "
                            f"on the tenth of players we disagree with most. "
                            f"Agreement is not skill, so it is excluded.\n\n"
                            f"The gap between the two halves is the honest story: "
                            f"we are far better at spotting who **will not** score "
                            f"than who will. That is the more useful skill and the "
                            f"one you cannot bet, because these books do not post a "
                            f"“no” price on touchdown props."
                        )
                else:
                    st.success(
                        f"**Where we disagree with the bookmaker is where this "
                        f"model is worth reading.** On the players we differed from "
                        f"the book on most across {h2h['span']}, our estimate "
                        f"landed **{h2h['disagree_better_pct']:.0f}% closer** to "
                        f"what actually happened.",
                        icon=":material/trending_up:",
                    )

            _rule = betting_rule(target_type, selected_model)
            _preblend = bp.preblend_columns_differ(board)
            if _rule and _preblend:
                st.caption(
                    f":material/payments: The last three columns answer a different "
                    f"question from the rest of the table. Everything to their left "
                    f"is our best guess at **who scores**, blended with the "
                    f"bookmaker because that predicts better. **Bet #** and **Bet "
                    f"edge** are strictly our own view, unblended, because backing "
                    f"someone only makes sense where we disagree with the price. "
                    f"**Worth backing** carries the labels fitted across "
                    f"{_rule['games']:,} games in {_rule['span']}"
                    + bp.tier_summary(_rule)
                    + " Roughly half of even the backed bets lose — open **What "
                      "the labels mean** below, or see **Betting reality**."
                )
                _legend = bp.tier_legend(_rule)
                if _legend is not None:
                    with st.expander("What the labels mean"):
                        st.dataframe(_legend, hide_index=True, column_config={
                            "Label": st.column_config.TextColumn(width="small"),
                            "Historically": st.column_config.TextColumn(
                                "Historically",
                                help="Measured on real closing prices across the "
                                     "seasons named above. A description of the "
                                     "group, not a forecast for any one player."),
                            "About": st.column_config.TextColumn("How often", width="small"),
                        })
                        st.caption(
                            "Every threshold here is fitted from the backtest, not "
                            "chosen — re-running the evaluation moves them. A tier "
                            "that stops paying in any season stops being shown at "
                            "all, which is why **First TD** has no labels."
                        )
            elif _rule:
                _t = (_rule.get("tiers") or {})
                _names = [t["tier"] for t in (_t.get("tiers") or [])]
                _has_fade = bool(_t.get("fade"))
                st.caption(
                    f":material/payments: **Worth backing** carries the labels "
                    f"fitted across {_rule['games']:,} games in {_rule['span']}"
                    + bp.tier_summary(_rule) +
                    " There is no separate **Bet #** or **Bet edge** on this "
                    "market: it is not blended with the bookmaker, so the number "
                    "on the board already *is* our own view. See **Betting "
                    "reality**."
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
            pick = filters.selectbox("Game", games, key="board_game")
            query = filters.text_input(
                "Search player", placeholder="e.g. Barkley",
                help="Type any part of a player's name.",
                key="board_search",
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
                key="board_depth",
            )
            only_calls = filters.checkbox(
                "Only where we differ",
                help="Hide players we price the same as the bookmaker, measured on "
                     "**Bet edge** — our own number, before the blend. What is left "
                     "is where the model is expressing an opinion, and that is the "
                     "ground the accuracy figures above are measured on. Filtering "
                     "on **Difference** instead would use a number already pulled "
                     "toward the price it is being compared against.",
                key="board_only_calls",
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
                key="board_longshots",
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
                diff_col = ("model_edge_pp" if "model_edge_pp" in shown.columns
                            else "edge_pp")
                shown = shown[shown[diff_col].abs() >= floor]
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
                    # The same walk-forward-or-fall-back source the strip at the top
                    # of the page uses, and that the "Show per game" help quotes.
                    # Reading `historical_accuracy` directly here put two different
                    # numbers for one claim on one screen: picking Top 5 on anytime
                    # TD said 94.9% in the tooltip (pooled, 1,130 games) and 96.1%
                    # in this caption (the held-out season alone, 284 games).
                    acc = (walkforward_accuracy(target_type, selected_model)
                           or historical_accuracy(target_type, selected_model))
                    n = int(depth.split()[-1])
                    key = {1: "top1", 3: "top3", 5: "top5"}[n]
                    if acc:
                        where = (f"{acc['games']:,} games in {acc['span']}"
                                 if acc.get("pooled")
                                 else f"the {acc['games']} games of {acc.get('season')}")
                        st.caption(
                            f":material/insights: Across {where}, at least one of a "
                            f"game's top {n} scored **{acc[key]:.1%}** of the time. "
                            f"These are that same top {n}, for this week."
                        )

            agree = len(board) - len(backing) - len(overvalued)
            st.caption(
                f"Showing {len(shown)} of {len(board)} priced players, most likely first. "
                f"We're higher than the bookmaker on {len(backing)}, lower on "
                f"{len(overvalued)}, and close to them on {agree}."
            )

            # The whole week's marked plays as one wager, because that is how they
            # get placed. Reads the full board rather than `shown` on purpose.
            _slate = bp.slate_expectation(board, betting_rule(target_type, selected_model))
            if _slate:
                st.info(_slate, icon=":material/functions:")

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


@st.cache_data(show_spinner="Scoring the week...", max_entries=32)
def _score_week(season: int, week: int, tt: str, model: str):
    from src.evaluation.weekly_review import score_week
    return score_week(season, week, tt, model)


@st.cache_data(show_spinner=False)
def _played(season: int, tt: str):
    from src.evaluation.weekly_review import played_weeks
    return played_weeks(season, tt)


@st.cache_data(show_spinner=False, max_entries=32)
@guarded
def _week_money(tt: str, season: int, week: int, model: str, tiers: dict | None):
    """Expected vs realised money for the plays this week's board would mark.

    `tiers` is passed in rather than looked up so the cache key includes it: a
    rebuilt rule has to invalidate this, or the page grades one week's bets
    against another rule's selection.
    """
    from src.evaluation.rank_economics import week_pnl
    return week_pnl(tt, season, week, tiers or {}, model=model)


if tab_results.open:
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
                key="results_week",
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

                # Accuracy and money are different questions, so they get different
                # sections. Everything above grades the probability; this grades the
                # bet — the same plays the Full board marks, at the prices it showed,
                # against what they actually paid.
                st.markdown("**And did the money follow?**")
                _rule = betting_rule(target_type, selected_model)
                money, money_err = _week_money(target_type, season, wk,
                                               selected_model,
                                               (_rule or {}).get("tiers"))
                if money_err:
                    st.warning(
                        f"**Settling this week's plays failed.** `{money_err}` — "
                        f"this section is missing because something broke, not "
                        f"because the week has no prices.",
                        icon=":material/error:",
                    )
                elif money is None:
                    st.caption(
                        "No graded prices for this week, so there is nothing to "
                        "settle. This needs a backtest frame — `make backtest` "
                        "builds one per season, so the current season only appears "
                        "here once its prices have been archived and rebuilt."
                        if _rule else
                        "This market has no fitted betting rule, so there is no set "
                        "of plays to settle. Run `scripts/14_rank_economics.py`."
                    )
                else:
                    w, ytd = money["week_stats"], money["to_date"]
                    if w["bets"] == 0:
                        st.caption(
                            f"The rule marked nothing in week {wk} — no stake, no "
                            f"result. Season to date it has backed "
                            f"{ytd['bets']} plays for "
                            f"{bp.signed_money(ytd['actual_profit'])} against "
                            f"{bp.signed_money(ytd['expected_profit'])} expected."
                        )
                    else:
                        gap = w["actual_profit"] - w["expected_profit"]
                        m = st.container(horizontal=True)
                        m.metric(
                            "Plays", w["bets"],
                            help=f"Players the fitted rule would have backed in week "
                                 f"{wk}, at a flat \\$100 each. Same rule that draws "
                                 f"**Worth backing** on the Full board.",
                        )
                        m.metric("Staked", f"${w['staked']:,.0f}")
                        m.metric(
                            "Expected", bp.signed_money(w["expected_profit"], 0, escape=False),
                            help="What our own numbers said these bets were worth "
                                 "before they were settled — the total of the "
                                 "board's **Expected on \\$100** column.",
                        )
                        m.metric(
                            "Actual", bp.signed_money(w["actual_profit"], 0, escape=False),
                            delta=f"{bp.signed_money(gap, 0, escape=False)} vs expected",
                            delta_color="off",
                            help="What they returned at the closing price.",
                        )
                        m.metric(
                            "Winners", f"{w['actual_winners']} of {w['bets']}",
                            help=f"We expected {w['expected_winners']:.1f}.",
                        )
                        st.caption(
                            f":material/functions: Season to date, the rule has "
                            f"backed **{ytd['bets']} plays** across "
                            f"{ytd.get('weeks', 0)} weeks for "
                            f"**{bp.signed_money(ytd['actual_profit'], 0)}** on "
                            f"\\${ytd['staked']:,.0f} staked, against "
                            f"**{bp.signed_money(ytd['expected_profit'], 0)}** expected.\n\n"
                            f"Read the week as an anecdote and the season as a "
                            f"sketch. A dozen bets at these prices is a handful of "
                            f"coin flips: one +700 winner swings a week by more "
                            f"than the whole edge is worth, so expected and actual "
                            f"are supposed to disagree here. What the gap is good "
                            f"for is direction over many weeks — if actual keeps "
                            f"landing below expected, the model is overconfident "
                            f"and the board's EV column is quoting a price it "
                            f"cannot pay. The only figures with intervals around "
                            f"them are in **Betting reality**."
                        )


# ── Tab 2: Model Performance ──────────────────────────────────────────────

if tab2.open:
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
                key="perf_show_dev",
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


@st.cache_data(show_spinner=False)
@guarded
def clv_by_rank(tt: str) -> list[dict] | None:
    """Line movement by our rank. Needs paired open/close snapshots."""
    from src.evaluation.clv import by_rank
    return by_rank(tt)


@st.cache_data(show_spinner=False, max_entries=8)
@guarded
def allocation_backtest(tt: str, top_n: int, bankroll: float) -> list[dict]:
    """Replay every game under each staking rule. Cached — it is a full walk.

    `max_entries` because `bankroll` is a number_input the visitor can set to
    any of ~2,000 values, and every distinct one is a fresh ~1s replay held in
    memory for the life of the process.
    """
    from src.prediction.portfolio import backtest_allocation
    return backtest_allocation(tt, top_n=top_n, bankroll=bankroll)


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


if tab_bet.open:
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
                    f"same small amount on each returned {bp.roi_money(h['roi'])}. That "
                    f"held up in every season separately, so it is unlikely to be "
                    f"one lucky year.",
                    icon=":material/trending_up:",
                )
            elif h:
                st.warning(
                    f"**We cannot show this market makes money.** Backing our top "
                    f"{n} in each game came out at {bp.roi_money(h['roi'])} over "
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

            do, dont = bp.bet_guidance(econ, n)
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
            st.dataframe(bp.roi_rows(econ["top_n"], "top_n", "Top N"),
                         hide_index=True, column_config=_ROI_COLS)

            st.markdown("##### By our rank")
            st.caption(
                "Backing only the Nth-favourite player in each game, every week. "
                "Where this stops making money is where a card should stop — it is "
                "the honest answer to \"how many should I take?\""
            )
            st.dataframe(bp.roi_rows(econ["by_rank"], "rank", "Rank"),
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
                     "Verdict": bp.VERDICT_PLAIN.get(k["verdict"], k["verdict"])},
                    {"Group": f"Below {rule['edge_cut'] * 100:.0f} pts (skip these)",
                     "Bets": d["n"], "Hit": d["hit_pct"] / 100,
                     "Break-even": d["breakeven_pct"] / 100, "Odds": d["median_odds"],
                     "ROI": d["roi"] / 100,
                     "95% interval": f"{d['lo']:+.1f}% to {d['hi']:+.1f}%",
                     "Verdict": bp.VERDICT_PLAIN.get(d["verdict"], d["verdict"])},
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
                        "Verdict": bp.VERDICT_PLAIN.get(r["verdict"], r["verdict"]),
                    } for r in econ["edge_curve"]]), hide_index=True,
                        column_config=_ROI_COLS)

            st.markdown("##### By price")
            st.caption(
                "Ignoring our ranking entirely — what happens if you just back "
                "everyone at a given price. Every band loses, which is the "
                "bookmaker's cut showing up as a number. Long prices are not "
                "\"value\"; they are where the cut is largest."
            )
            st.dataframe(bp.roi_rows(econ["by_odds_bucket"], "bucket", "Price band"),
                         hide_index=True, column_config=_ROI_COLS)

            _bc = econ.get("blend_comparison") or []
            _by = {}
            for _r in _bc:
                _by.setdefault(_r["ranked_by"], {})[_r["top_n"]] = round(_r["roi"], 4)
            # If the published number *is* the model number, the two rows are the
            # same row and the section's whole premise — that blending costs you
            # money — does not apply to this market.
            _blends = _by.get("model only (pre-blend)") != _by.get("blended (published)")
            if _bc and _blends:
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

            elif _bc and not _blends:
                st.markdown("##### Which of our numbers should you bet on?")
                st.caption(
                    "Only one, on this market. Anytime TD publishes a number "
                    "blended with the bookmaker's, so it has a separate pre-blend "
                    "view worth betting instead. This market is not blended — the "
                    "number on the board *is* the model's own — so there is no "
                    "choice to make here. For contrast, simply believing the "
                    "bookmaker returned "
                    f"{_by.get('market only', {}).get(n, 0):+.1f}% over the same games."
                )

            st.markdown(f"##### Top {n}, season by season")
            st.caption(
                "One good season is not a strategy — it is a coincidence with a "
                "large sample size. This is the check that matters most."
            )
            st.dataframe(bp.roi_rows(econ["by_season"], "season", "Season"),
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

            clv, clv_err = clv_by_rank(target_type)
            if clv_err:
                st.warning(
                    f"**Line-movement check could not run.** "
                    f"`{clv_err}` — this section is "
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
                key="bet_bankroll",
            )

            alloc, alloc_err = allocation_backtest(target_type, n, bankroll)
            if alloc_err:
                st.warning(
                    f"**Staking comparison could not run.** "
                    f"`{alloc_err}` — this section is "
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


# ── Tab: Player types — what kind of player, and what kind of bet? ────────────
#
# Every other tab asks how good the number is. This one asks what it is about.
# Players are grouped by usage and role within their position, bets by the shape
# of the wager, and each group is then scored against what actually happened —
# how often it scored, how far off we were, how far off the book was, and what
# backing it would have returned.
#
# The grouping is fitted by scripts/21_clusters.py on the training seasons and
# read here as JSON; the app assigns and renders, it does not cluster. Two
# reasons. A segmentation scored on the rows it was drawn from will always find
# a group with a striking number attached, because it drew the boundary around
# one — so fitting and scoring live on opposite sides of the split, and the tab
# says so on screen. And the default render then costs nothing: no k-means, no
# bootstrap, just a file, exactly like rank_economics.json.
#
# Note `_money` here is the Betting reality one (a return phrased as dollars
# back per $100), not the signed-amount `_money` defined earlier in the file.


@st.cache_data(show_spinner=False)
@guarded
def cluster_model(tt: str, lens: str) -> dict | None:
    """The fitted grouping: centroids, the curve that chose k, the names."""
    from src.clustering import archetypes, bet_shapes, core
    path = (archetypes.artifact_path(tt) if lens == "player"
            else bet_shapes.artifact_path(tt))
    return core.load(path)


@st.cache_data(show_spinner=False)
@guarded
def cluster_report(tt: str, lens: str, model: str) -> dict | None:
    """What each group did on the seasons the grouping never saw.

    Keyed on the model as well as the market: the model selector is global, and
    a report tagged to a different model describes different bets. Falling back
    to the untagged file is deliberate — that one is the production model's, and
    the caller warns when the two disagree rather than quietly swapping.
    """
    import json
    from src.clustering import archetypes, bet_shapes
    mod = archetypes if lens == "player" else bet_shapes
    for path in (mod.report_path(tt, model), mod.report_path(tt)):
        if path.exists():
            return json.loads(path.read_text())
    return None


@st.cache_data(show_spinner="Refitting these groups...", max_entries=12)
@guarded
def cluster_explore(tt: str, stratum: str, k: int, features: tuple[str, ...],
                    seed: int) -> list[dict] | None:
    """An exploratory refit. Never persisted, never the served grouping.

    `features` is a tuple because st.cache_data cannot hash a list, and
    `max_entries` because the visitor picks that tuple — the key space is every
    subset of the feature list, and each entry is a k-means refit held for the
    life of the process.
    """
    from src.clustering import archetypes, core
    art, _ = cluster_model(tt, "player")
    if art is None:
        return None
    return archetypes.explore(tt, art, stratum, k, list(features), seed,
                              core.settings()["explore_max_rows"])


def _span(seasons: list[int]) -> str:
    if not seasons:
        return "—"
    return (str(seasons[0]) if len(seasons) == 1
            else f"{seasons[0]}–{seasons[-1]}")


def cluster_split_note(art: dict, rep: dict) -> str:
    """The honesty banner, built from the artifact rather than typed."""
    return (
        f"The groups below were fitted on **{_span(art['seasons_used'])}** — the "
        f"seasons the model trains on — using **{art['n_rows_fit']:,}** rows that "
        f"passed the same activity filter production uses. Everything measured "
        f"about them is measured on **{_span(rep['report_seasons'])}**, "
        f"**{rep['n_rows']:,}** rows the grouping never saw. Fitting and scoring "
        f"on the same rows is how a segmentation invents a pattern."
    )


def _cluster_rows(rep: dict, strata: list[str] | None = None) -> pd.DataFrame:
    """Report rows as a table, biggest group first.

    Ordered by size on purpose: sorted by return, a sixty-row group with one
    lucky longshot in it leads the page.
    """
    rows = [r for r in rep["rows"]
            if strata is None or r["stratum"] in strata]
    return pd.DataFrame([{
        "Type": r["label"],
        "Position": r["stratum"],
        "What makes it one": r["profile"],
        "Player-games": r["n"],
        "Scored": r.get("td_rate"),
        "We said": r.get("our_mean_prob"),
        "Book said": r.get("market_mean_prob"),
        "We were out by": r.get("our_gap_pp"),
        "They were out by": r.get("market_gap_pp"),
        "Bets": r.get("n_bets", 0),
        "ROI": r["roi"] / 100 if r.get("roi") is not None else None,
        "95% interval": (f"{r['lo']:+.1f}% to {r['hi']:+.1f}%"
                         if r.get("lo") is not None else "—"),
        "Verdict": ("Too few bets to say" if r.get("thin")
                    else bp.VERDICT_PLAIN.get(r.get("verdict"), r.get("verdict"))),
    } for r in rows])


_CLUSTER_COLS = {
    "Type": st.column_config.TextColumn(
        "Type", width="medium",
        help="Named after the feature this group departs furthest from its "
             "position's average on. The departures themselves are in the next "
             "column, so the name can be checked against them."),
    "What makes it one": st.column_config.TextColumn(
        "What makes it one", width="large",
        help="How far this group sits from the average player at its position, "
             "in standard deviations. This is the evidence for the name."),
    "Player-games": st.column_config.NumberColumn(
        "Player-games", format="%d",
        help="On the reporting seasons only — not the seasons it was fitted on."),
    "Scored": st.column_config.NumberColumn(
        "Actually scored", format="percent",
        help="How often these players really did score a touchdown."),
    "We said": st.column_config.NumberColumn(
        "We said", format="percent",
        help="Our average probability for this group, over the players a "
             "bookmaker priced."),
    "Book said": st.column_config.NumberColumn(
        "Book said", format="percent",
        help="The de-vigged market probability for the same players."),
    "We were out by": st.column_config.NumberColumn(
        "We were out by", format="%+.1f pts",
        help="Our average estimate minus what actually happened. Positive means "
             "we were too high on this kind of player."),
    "They were out by": st.column_config.NumberColumn(
        "They were out by", format="%+.1f pts",
        help="The same measure for the bookmaker. Where this is larger than the "
             "column to its left, we described this group better than the price "
             "did."),
    "Bets": st.column_config.NumberColumn(
        "Bets", format="%d",
        help="Players in this group a bookmaker actually priced. Returns are "
             "computed on these, not on every player-game."),
    "ROI": _ROI_COLS["ROI"],
    "95% interval": _ROI_COLS["95% interval"],
    "Verdict": st.column_config.TextColumn("Verdict", width="small"),
}


def cluster_how_to_read(art: dict, rep: dict, lens: str) -> str:
    """Prose generated from the artifact, so it cannot drift from the numbers."""
    strata = art["strata"]
    ks = ", ".join(f"{name} {s['k']}" for name, s in strata.items())
    unresolved = [n for n, s in strata.items() if s["k_unresolved"]]
    n_feat = {n: len(s["features"]) for n, s in strata.items()}
    dropped = {n: len(s.get("dropped", [])) for n, s in strata.items()}

    out = [
        f"**Where the groups come from.** Every player-game from "
        f"{_span(art['seasons_used'])} that passed production's activity filter "
        f"was placed in the space its own position defines — "
        + ", ".join(f"{n} on {v} features ({dropped[n]} candidates pruned)"
                    for n, v in n_feat.items())
        + f" — and k-means drew the boundaries. The number of groups is not set "
        f"by hand: it is chosen by the {art['criterion'].replace('_', ' ')} "
        f"within {art['k_range'][0]}–{art['k_range'][1]}, which gave {ks}.",

        f"**Why within a position rather than across the league.** Clustered as "
        f"one pool, the data splits into running backs, receivers and players "
        f"with no usage — the position column with extra steps. The section at "
        f"the top of this tab shows that result rather than hiding it. Position "
        f"is therefore the thing we group *inside*, so what is left to find is "
        f"which backs are goal-line backs.",

        f"**What the numbers are measured on.** {_span(rep['report_seasons'])}, "
        f"{rep['n_rows']:,} player-games and {rep['n_priced_rows']:,} priced "
        f"bets that the grouping never saw. The seasons it was fitted on appear "
        f"nowhere in any figure on this page.",

        f"**What a return here is and is not.** A group's profit column "
        f"describes what happened to those particular bets. It is not a rate to "
        f"expect. Where the ten biggest winners carry most of the profit the "
        f"tab says so, and where the interval includes zero the verdict reads "
        f"*Too close to call*, which means exactly that and not *slightly good*.",

        f"**And there are {rep['n_cells']} groups on this page.** At a 95% "
        f"interval roughly one in twenty excludes zero for no reason at all, so "
        f"one group standing out is the weakest kind of evidence available "
        f"here. The ones worth anything hold up season by season — that split "
        f"is in each group's expander.",
    ]
    if unresolved:
        out.append(
            f"**One caveat on {', '.join(unresolved)}.** The criterion did not "
            f"settle inside the range it is allowed: the measure was still "
            f"improving at the largest number of groups permitted, so that "
            f"number is the edge of the range rather than a resolved answer. "
            f"The groups are still real; how many there should be is not "
            f"something this data has told us."
        )
    return "\n\n".join(out)


if tab_clusters.open:
    with tab_clusters:
        render_accuracy_strip(target_type, selected_model)

        _art, _art_err = cluster_model(target_type, "player")
        _rep, _rep_err = cluster_report(target_type, "player", selected_model)
        _err = _art_err or _rep_err

        if _err:
            st.error(f"Could not read the fitted groups: {_err}",
                     icon=":material/error:")
        elif _art is None or _rep is None:
            st.info(
                "Not fitted yet. Run `python scripts/21_clusters.py --target "
                f"{target_type}` (or `make clusters TARGET={target_type}`), which "
                "fits the groups on the training seasons and scores them on the "
                "seasons after.",
                icon=":material/info:",
            )
        else:
            st.caption(cluster_split_note(_art, _rep))
            if _rep.get("model") and _rep["model"] != selected_model:
                st.warning(
                    f"These groups were scored on **{_rep['model']}**, not the "
                    f"**{selected_model}** you have selected. Re-run "
                    f"`python scripts/21_clusters.py --target {target_type} "
                    f"--model {selected_model}` to measure them on that model.",
                    icon=":material/warning:",
                )

            # ── The negative result, shown rather than filed away ──────────────
            _pooled = _art.get("pooled_evidence") or {}
            if _pooled.get("composition"):
                with st.container(border=True):
                    st.markdown("##### :material/insights: Why types are found "
                                "inside each position")
                    _left, _right = st.columns([3, 2])
                    with _left:
                        _best = _pooled["silhouette_best_k"]
                        _comp = _pooled["composition"]
                        _lines = []
                        for c in _comp:
                            _tops = ", ".join(
                                f"{p['position']} {p['share']:.0%}"
                                for p in c["top_positions"])
                            _lines.append(f"- **{c['n']:,} players** — {_tops}")
                        st.markdown(
                            f"The obvious thing to try is clustering everyone "
                            f"together and seeing what falls out. Done here, the "
                            f"standard measure of how well-separated groups are "
                            f"prefers **{_best}** of them, and they are:\n\n"
                            + "\n".join(_lines) +
                            f"\n\nThat is the position column, rediscovered and "
                            f"presented as a finding. So position is the thing "
                            f"these groups are found *inside* instead — which "
                            f"leaves an actual question: which backs are goal-line "
                            f"backs, and which receivers are the ones their offence "
                            f"throws to near the end zone."
                        )
                    with _right:
                        _sil = _pooled.get("selection") or []
                        if _sil:
                            _fig = go.Figure()
                            _fig.add_trace(go.Scatter(
                                x=[r["k"] for r in _sil],
                                y=[r["silhouette"] for r in _sil],
                                mode="lines+markers", name="Separation"))
                            _fig.add_vline(x=_pooled["silhouette_best_k"],
                                           line_dash="dot")
                            _fig.update_layout(
                                title="Clustering the whole league at once",
                                xaxis_title="Number of groups",
                                yaxis_title="How separated they are",
                                height=400, showlegend=False)
                            st.plotly_chart(_fig)

            # A radio rather than st.segmented_control: the static export in
            # src/export/capture.py implements a fixed set of widgets, and a control
            # it does not know about takes the whole page down rather than
            # degrading. Nothing here needs the newer widget.
            _lens = st.radio("View", ["Player types", "Bet types"],
                             horizontal=True, key="cluster_lens")

            # ── Lens A: player archetypes ─────────────────────────────────────
            if _lens != "Bet types":
                _strata = list(_art["strata"].keys())
                with st.container(horizontal=True):
                    _pos = st.selectbox("Position", ["All"] + _strata,
                                        key="cluster_position")
                _pick = None if _pos == "All" else [_pos]

                _frame = _cluster_rows(_rep, _pick)
                if _frame.empty:
                    st.info("No groups to show for that position.",
                            icon=":material/info:")
                else:
                    st.dataframe(_frame, hide_index=True,
                                 column_config=_CLUSTER_COLS)
                    st.caption(
                        f"Biggest group first. Sorted by return instead, a group of "
                        f"sixty with one lucky longshot in it would lead the page.")

                    # Are we right about each type — us and the book on one picture.
                    _cal = [r for r in _rep["rows"]
                            if (_pick is None or r["stratum"] in _pick)
                            and r.get("our_mean_prob") is not None]
                    if _cal:
                        _fig = go.Figure()
                        _fig.add_trace(go.Scatter(
                            x=[0, max(r["hit_pct"] / 100 for r in _cal) * 1.1],
                            y=[0, max(r["hit_pct"] / 100 for r in _cal) * 1.1],
                            mode="lines", line=dict(dash="dash", color="gray"),
                            name="Perfect", hoverinfo="skip"))
                        _fig.add_trace(go.Scatter(
                            x=[r["our_mean_prob"] for r in _cal],
                            y=[r["hit_pct"] / 100 for r in _cal],
                            mode="markers", name="Us",
                            text=[r["label"] for r in _cal],
                            marker=dict(size=[8 + (r["n_bets"] ** 0.5) / 4
                                              for r in _cal]),
                            hovertemplate="%{text}<br>we said %{x:.1%}"
                                          "<br>actually %{y:.1%}<extra></extra>"))
                        _fig.add_trace(go.Scatter(
                            x=[r["market_mean_prob"] for r in _cal],
                            y=[r["hit_pct"] / 100 for r in _cal],
                            mode="markers", name="Bookmaker",
                            text=[r["label"] for r in _cal],
                            marker=dict(symbol="circle-open",
                                        size=[8 + (r["n_bets"] ** 0.5) / 4
                                              for r in _cal]),
                            hovertemplate="%{text}<br>book said %{x:.1%}"
                                          "<br>actually %{y:.1%}<extra></extra>"))
                        _fig.update_layout(
                            title="Are we right about each type?",
                            xaxis_title="Probability said beforehand",
                            yaxis_title="How often it actually happened",
                            xaxis_tickformat=".0%", yaxis_tickformat=".0%",
                            height=400)
                        st.plotly_chart(_fig)
                        st.caption(
                            "On the dashed line, the probability matched what "
                            "happened. Above it, the type scored more often than "
                            "either of us said; below it, less. Filled markers are "
                            "ours, hollow ones the bookmaker's — where a hollow "
                            "marker sits further from the line than the filled one "
                            "beside it, we described that type better than the "
                            "price did.")

                # Per-type detail.
                for _name in (_pick or _strata):
                    _s = _art["strata"][_name]
                    _rows_by_id = {r["cluster"]: r for r in _rep["rows"]
                                   if r["stratum"] == _name}
                    with st.expander(f"{_name} — {_s['k']} types, "
                                     f"{_s['n']:,} player-games used to find them"):
                        if _s["k_unresolved"]:
                            st.warning(
                                f"How many types there are did not settle: "
                                f"{_s['k_reason']}. The groups below are real; the "
                                f"number of them is the edge of the range we allow, "
                                f"not an answer the data gave.",
                                icon=":material/warning:")
                        else:
                            st.caption(f"Number of types chosen by "
                                       f"{_s['k_reason']}.")

                        _cards = st.columns(2)
                        for _i, _c in enumerate(_s["clusters"]):
                            _r = _rows_by_id.get(_c["id"])
                            with _cards[_i % 2]:
                                with st.container(border=True):
                                    st.markdown(f"**{_c['label']}**")
                                    if _c["label_source"] == "generated":
                                        st.caption(
                                            "Named automatically — this group is "
                                            "defined by being *below* average, "
                                            "which has no natural short name.")
                                    _strip = st.container(horizontal=True)
                                    _strip.metric("Fitted on",
                                                  f"{_s['sizes'][_c['id']]:,}")
                                    if _r:
                                        _strip.metric("Scored", f"{_r['td_rate']:.1%}")
                                        if _r.get("roi") is not None:
                                            _strip.metric("Per \\$100",
                                                          f"{100 + _r['roi']:,.0f}")
                                    _fig = go.Figure(go.Bar(
                                        x=[t["z"] for t in _c["top_features"]][::-1],
                                        y=[t["definition"]
                                           for t in _c["top_features"]][::-1],
                                        orientation="h"))
                                    _fig.update_layout(
                                        height=400,
                                        xaxis_title="Standard deviations from the "
                                                    "average player at this position",
                                        margin=dict(l=10, r=10, t=10, b=10))
                                    st.plotly_chart(
                                        _fig, key=f"z_{_name}_{_c['id']}")
                                    if _c.get("examples"):
                                        st.caption(
                                            "Closest examples: " + ", ".join(
                                                f"{e['player_name']} "
                                                f"{e['season']} wk{e['week']}"
                                                for e in _c["examples"]))
                                    if _r and _r.get("outlier_share", 0) > 0.25:
                                        st.warning(
                                            f"{_r['outlier_share']:.0%} of recent "
                                            f"players in this group sit outside "
                                            f"where it was fitted. The role may "
                                            f"have moved since "
                                            f"{_art['seasons_used'][-1]}.",
                                            icon=":material/warning:")
                                    if _r and _r.get("concentration") and \
                                            _r["concentration"] > 0.5:
                                        st.warning(
                                            f"The ten biggest winners carry "
                                            f"{_r['concentration']:.0%} of this "
                                            f"group's profit. Read the return as a "
                                            f"description of those results, not a "
                                            f"rate.",
                                            icon=":material/warning:")
                                    if _r and _r.get("per_season"):
                                        st.caption(" · ".join(
                                            f"{p['season']}: "
                                            + (f"{p['roi']:+.0f}%"
                                               if p.get("roi") is not None else "—")
                                            for p in _r["per_season"]))

                        with st.container(border=True):
                            st.markdown("**Why this many types?**")
                            _sel = _s["selection"]
                            _fig = go.Figure()
                            _fig.add_trace(go.Scatter(
                                x=[r["k"] for r in _sel],
                                y=[r.get("gap") for r in _sel],
                                error_y=dict(type="data",
                                             array=[r.get("gap_se", 0)
                                                    for r in _sel]),
                                mode="lines+markers",
                                name="Structure beyond noise"))
                            _fig.add_trace(go.Scatter(
                                x=[r["k"] for r in _sel],
                                y=[r.get("silhouette") for r in _sel],
                                mode="lines+markers", yaxis="y2",
                                name="Separation (not used to choose)"))
                            _fig.add_vline(x=_s["k"], line_dash="dot")
                            _fig.update_layout(
                                xaxis_title="Number of types",
                                yaxis_title="Structure beyond noise",
                                yaxis2=dict(title="Separation", overlaying="y",
                                            side="right"),
                                height=400,
                                legend=dict(orientation="h", y=-0.25))
                            st.plotly_chart(_fig, key=f"sel_{_name}")
                            st.caption(
                                "The solid measure is how much better the grouping "
                                "does than it would on pure noise of the same "
                                "shape; the dotted line marks the number chosen. "
                                "The second measure — how cleanly separated the "
                                "groups are — is shown but deliberately not used "
                                "to choose: on this data it always prefers the "
                                "coarsest possible split, which is how you end up "
                                "rediscovering the position column.")
                            st.dataframe(pd.DataFrame([{
                                "Types": r["k"],
                                "Structure beyond noise": r.get("gap"),
                                "±": r.get("gap_se"),
                                "Separation": r.get("silhouette"),
                                "Agreement between halves": r.get("split_half_ari"),
                                "Smallest group": r.get("smallest_cluster"),
                            } for r in _sel]), hide_index=True, column_config={
                                "Agreement between halves": st.column_config.NumberColumn(
                                    format="%.2f",
                                    help="Split the data in two, group each half "
                                         "separately, and see whether they agree. "
                                         "Low agreement means the number of types "
                                         "is describing this sample rather than "
                                         "the league."),
                                "Smallest group": st.column_config.NumberColumn(
                                    format="%d",
                                    help="A number of types that leaves a group too "
                                         "small to measure anything about is "
                                         "rejected before the choice is made."),
                            })

            # ── Lens B: bet shapes ────────────────────────────────────────────
            else:
                _bart, _bart_err = cluster_model(target_type, "bet")
                _brep, _brep_err = cluster_report(target_type, "bet", selected_model)
                if _bart_err or _brep_err:
                    st.error(
                        f"Could not read the fitted bet types: "
                        f"{_bart_err or _brep_err}", icon=":material/error:")
                elif _bart is None or _brep is None:
                    st.info(
                        "Bet types are not fitted for this market. They need "
                        "backtest frames with real prices — run `make evaluate`, "
                        f"then `make clusters TARGET={target_type}`.",
                        icon=":material/info:")
                else:
                    st.caption(cluster_split_note(_bart, _brep))
                    if len(_bart["seasons_used"]) == 1:
                        st.warning(
                            f"Fitted on **{_bart['seasons_used'][0]} alone** — "
                            f"{_bart['n_rows_fit']:,} priced players. Real odds "
                            f"history does not reach further back than the training "
                            f"split, so there is only one season of board shapes to "
                            f"learn from. That is thin, and it is stated rather "
                            f"than fixed by reaching across the split.",
                            icon=":material/warning:")

                    _brows = sorted(_brep["rows"], key=lambda r: -r["n"])
                    _bframe = pd.DataFrame([{
                        "Bet type": r["label"],
                        "What makes it one": r["profile"],
                        "Bets": r["n_bets"],
                        "Hit": r["hit_pct"] / 100,
                        "Break-even": r["breakeven_pct"] / 100,
                        "Odds": r["median_odds"],
                        "ROI": r["roi"] / 100 if r["roi"] is not None else None,
                        "95% interval": (f"{r['lo']:+.1f}% to {r['hi']:+.1f}%"
                                         if r["lo"] is not None else "—"),
                        "Verdict": ("Too few bets to say" if r["thin"]
                                    else bp.VERDICT_PLAIN.get(r["verdict"],
                                                            r["verdict"])),
                    } for r in _brows])
                    st.dataframe(_bframe, hide_index=True, column_config={
                        **_ROI_COLS,
                        "Bet type": st.column_config.TextColumn(
                            "Bet type", width="medium",
                            help="Named after what makes this kind of wager "
                                 "distinctive — our confidence, the price, the game "
                                 "it sits in."),
                        "What makes it one": st.column_config.TextColumn(
                            "What makes it one", width="large"),
                        "Bets": st.column_config.NumberColumn("Bets", format="%d"),
                    })

                    _fig = go.Figure(go.Bar(
                        x=[r["label"] for r in _brows],
                        y=[r["roi"] for r in _brows],
                        error_y=dict(
                            type="data", symmetric=False,
                            array=[r["hi"] - r["roi"] for r in _brows],
                            arrayminus=[r["roi"] - r["lo"] for r in _brows]),
                    ))
                    _fig.add_hline(y=0)
                    _fig.update_layout(
                        title="What each kind of bet returned",
                        yaxis_title="Profit per \\$100 staked (%)",
                        height=400, xaxis_tickangle=-30)
                    st.plotly_chart(_fig)
                    st.caption(
                        "The bars are what happened; the whiskers are what luck "
                        "alone could have produced. A bar whose whiskers cross zero "
                        "is not evidence of anything — which is why this chart is "
                        "drawn with them and would be misleading without them.")

                    for _r in _brows:
                        with st.expander(f"{_r['label']} — {_r['n_bets']:,} bets, "
                                         f"season by season"):
                            st.caption(_r["profile"])
                            if _r.get("per_season"):
                                st.dataframe(pd.DataFrame([{
                                    "Season": p["season"],
                                    "Bets": p["n"],
                                    "ROI": (p["roi"] / 100
                                            if p.get("roi") is not None else None),
                                    "95% interval": (
                                        f"{p['lo']:+.1f}% to {p['hi']:+.1f}%"
                                        if p.get("lo") is not None else "—"),
                                } for p in _r["per_season"]]), hide_index=True,
                                    column_config={
                                        "ROI": _ROI_COLS["ROI"],
                                        "95% interval": _ROI_COLS["95% interval"]})
                            st.caption(
                                "A return worth anything holds up in each season "
                                "separately. One good year inside a pooled figure "
                                "is usually one good year.")

            # ── Exploratory refit ─────────────────────────────────────────────
            _explore = st.toggle(
                "Refit these groups myself",
                value=False,
                key="cluster_explore_toggle",
                help="Change how many groups there are and which features they are "
                     "built from. Exploratory: nothing you produce here is the "
                     "grouping described above.")
            if _explore:
                st.warning(
                    "**Exploratory. Not the served grouping.** Nothing here is "
                    "saved, and none of it feeds the board. The seasons are not a "
                    "dial: a refit still learns on the fitted seasons and is still "
                    "measured on the ones after, because that is the only reason "
                    "any of these numbers mean anything. Search enough "
                    "combinations and one will look profitable — that is what "
                    "searching does.",
                    icon=":material/science:")
                _cfg = get_config().get("clustering") or {}
                _strata = list(_art["strata"].keys())
                with st.container(horizontal=True):
                    _xs = st.selectbox("Position", _strata, key="explore_stratum")
                    _xk = st.slider("Number of types",
                                    int(_cfg.get("k_min", 2)),
                                    int(_cfg.get("k_max", 8)),
                                    int(_art["strata"][_xs]["k"]),
                                    key="explore_k")
                _xf = st.multiselect(
                    "Features", _art["strata"][_xs]["features"],
                    default=_art["strata"][_xs]["features"], key="explore_features")

                if len(_xf) < 3:
                    st.info("Pick at least three features.", icon=":material/info:")
                else:
                    _xrows, _xerr = cluster_explore(target_type, _xs, _xk,
                                                    tuple(_xf), int(_art["seed"]))
                    if _xerr:
                        st.error(f"Refit failed: {_xerr}", icon=":material/error:")
                    elif _xrows:
                        st.dataframe(
                            _cluster_rows({"rows": sorted(_xrows,
                                                          key=lambda r: -r["n"])}),
                            hide_index=True, column_config=_CLUSTER_COLS)
                        _served = _art["strata"][_xs]["k"]
                        st.caption(
                            f"{_xk} groups from {len(_xf)} features, against the "
                            f"{_served} the fitted grouping uses. Same table, same "
                            f"seasons, same intervals — so the two are comparable.")

            with st.expander("How to read this — and how the groups are built"):
                st.markdown(cluster_how_to_read(_art, _rep, "player"))
