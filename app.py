"""NFL TD Prediction Dashboard — Streamlit app."""
import sys
sys.path.insert(0, ".")

import json
import pickle
from pathlib import Path

import numpy as np
import polars as pl
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

from src.utils.config import get_config
from src.utils.paths import get_path
from src.models.trainer import get_feature_cols, prepare_data, _filter_low_activity
from src.models.registry import get_model, ensure_registered
from src.models.calibration import TemperatureScaler
from src.ingest.odds_api import fetch_week_td_props, load_cached_odds
from src.analysis.game_analyst import analyze_edges
from src.prediction.ai_adjustments import get_ai_adjustments, apply_adjustments
from src.features.definitions import get_definition


ensure_registered()

st.set_page_config(page_title="NFL TD Predictions", layout="wide")

cfg = get_config()
active_models = cfg["models"]["active"]
production_model = cfg["models"]["production"]

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
    default_model = production_model if production_model in model_options else model_options[0]
    selected_model = st.selectbox(
        "Model",
        model_options,
        index=model_options.index(default_model),
    )

st.title("First TD Scorer" if target_type == "first_td" else "Anytime TD Scorer")

tab1, tab2, tab3 = st.tabs(["Predictions", "Model Performance", "Parlay Builder"])


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
            player_odds = {}
            for p in data.get(market_key, []):
                norm = _normalize_name(p["player"])
                player_odds[norm] = {
                    "odds": p["odds"],
                    "implied_prob": p["implied_prob"],
                    "bookmaker": p.get("bookmaker", ""),
                }
            return player_odds

    return {}


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
    vegas_prob = vegas_info["implied_prob"]
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
                cal = TemperatureScaler.load(cal_path)
                p = cal.calibrate(p)
            probs += w * p
    else:
        model = get_model(model_name).load(model_dir / f"{model_name}.pkl")
        model.feature_names = feature_cols
        probs = model.predict_proba(X)
        cal_path = model_dir / f"{model_name}_calibrator.pkl"
        if cal_path.exists():
            cal = TemperatureScaler.load(cal_path)
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
        result = result.with_columns(
            pl.col("raw_prob").alias("probability")
    )
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


def build_edges(result, odds_data, target_type, df_features=None, season=None, week=None):
    """Build edge data and situational context from predictions + odds.

    Returns (all_edges, games_for_adj, sit_lookup).
    """
    # Load situational data if features available
    sit_lookup = {}
    sit_cols = [
        "is_new_team", "is_revenge_game", "is_role_change",
        "weeks_since_last_game", "career_seasons",
        "rest_advantage", "is_post_bye", "is_season_opener",
    ]
    if df_features is not None and season is not None and week is not None:
        week_feats = df_features.filter(
            (pl.col("season") == season) & (pl.col("week") == week)
        )
        available_sit_cols = [c for c in sit_cols if c in week_feats.columns]
        if available_sit_cols:
            for row in week_feats.select(
                ["player_id"] + available_sit_cols
            ).iter_rows(named=True):
                sit_lookup[row["player_id"]] = {
                    k: row[k] for k in available_sit_cols if row[k] is not None
                }

    game_ids = sorted(result.select("game_id").unique()["game_id"].to_list())
    all_edges = []
    games_for_adj = {}

    for gid in game_ids:
        game = result.filter(pl.col("game_id") == gid)
        label = game["game_label"][0] if "game_label" in game.columns else gid
        game_odds = match_odds_to_game(odds_data, label, target_type) if odds_data else {}

        players_ctx = []
        for idx, row in enumerate(game.head(15).iter_rows(named=True)):
            norm = _normalize_name(row["player_name"])
            vi = game_odds.get(norm)
            sit = sit_lookup.get(row.get("player_id", ""), {})

            p_data = {
                "player_name": row["player_name"],
                "team": row["team"],
                "probability": row["probability"],
                "vegas_odds": vi["odds"] if vi else None,
                "vegas_implied": vi["implied_prob"] if vi else None,
                **sit,
            }
            players_ctx.append(p_data)

            if vi and idx < 10:
                edge_pct = (row["probability"] - vi["implied_prob"]) * 100
                if abs(edge_pct) > 3:
                    all_edges.append({
                        "player_name": row["player_name"],
                        "team": row["team"],
                        "game_label": label,
                        "model_prob": row["probability"],
                        "vegas_prob": vi["implied_prob"],
                        "edge_pct": edge_pct,
                        "situational": sit,
                    })

        games_for_adj[gid] = {"label": label, "players": players_ctx}

    return all_edges, games_for_adj, sit_lookup


def render_edge_table(all_edges, key_prefix=""):
    """Render the edge table and AI explain UI. Returns None."""
    if not all_edges:
        return

    sorted_edges = sorted(all_edges, key=lambda x: abs(x["edge_pct"]), reverse=True)

    edge_rows = []
    for e in sorted_edges:
        sit_flags = []
        sit = e.get("situational", {})
        if sit.get("is_new_team"): sit_flags.append("New Team")
        if sit.get("is_revenge_game"): sit_flags.append("Revenge")
        if sit.get("is_role_change"): sit_flags.append("Role Change")
        if sit.get("is_post_bye"): sit_flags.append("Post-Bye")
        if sit.get("is_season_opener"): sit_flags.append("Wk 1")

        direction = "VALUE" if e["edge_pct"] > 0 else "FADE"
        edge_rows.append({
            "Player": e["player_name"],
            "Team": e["team"],
            "Game": e["game_label"],
            "Model": f"{e['model_prob']*100:.1f}%",
            "Vegas": f"{e['vegas_prob']*100:.1f}%",
            "Edge": f"{e['edge_pct']:+.1f}pp",
            "Type": direction,
            "Flags": ", ".join(sit_flags) if sit_flags else "",
        })

    st.dataframe(edge_rows, use_container_width=True, hide_index=True)

    # Select edges to explain
    edge_labels = [
        f"{e['player_name']} ({e['team']}) — {e['edge_pct']:+.1f}pp"
        for e in sorted_edges
    ]
    selected_edge_labels = st.multiselect(
        "Select edges to explain",
        edge_labels,
        key=f"{key_prefix}selected_edges",
        placeholder="Pick one or more edges for Claude to analyze...",
    )

    if selected_edge_labels:
        selected_indices = [edge_labels.index(l) for l in selected_edge_labels]
        selected_edges_data = [sorted_edges[i] for i in selected_indices]

        if st.button(
            f"Explain {len(selected_edges_data)} Edge{'s' if len(selected_edges_data) != 1 else ''}",
            type="primary",
            key=f"{key_prefix}explain_edges",
        ):
            with st.spinner("Claude is analyzing selected edges..."):
                # Get season/week from the first edge's game context
                edge_analysis = analyze_edges(
                    selected_edges_data, target_type,
                    st.session_state.get(f"{key_prefix}season", 2025),
                    st.session_state.get(f"{key_prefix}week", 1),
                )
                st.session_state[f"{key_prefix}edge_analysis"] = edge_analysis

    if f"{key_prefix}edge_analysis" in st.session_state:
        st.markdown("---")
        st.markdown(st.session_state[f"{key_prefix}edge_analysis"])


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


# ── Tab 1: Predictions (merged with AI Insights) ──────────────────────────

with tab1:
    df = load_features(target_type)
    if df is None:
        st.warning(f"No features.parquet found for {target_type}. Run the pipeline first.")
    elif week is None:
        st.info("Select a season and week in the sidebar.")
    else:
        with st.spinner("Running predictions..."):
            result = run_prediction(season, week, selected_model, target_type)
        if result is None:
            st.info("No predictions available for this week.")
        else:
            # Load Vegas odds
            odds_data = load_odds()
            has_odds = bool(odds_data)

            if has_odds:
                col_refresh, col_info = st.columns([1, 3])
                with col_refresh:
                    if st.button("Refresh Odds"):
                        try:
                            odds_data = fetch_week_td_props(force_refresh=True)
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error fetching odds: {e}")
                with col_info:
                    n_games_with_odds = sum(
                        1 for d in odds_data.values()
                        if d.get("first_td") or d.get("anytime_td")
                    )
                    st.caption(f"Vegas odds loaded for {n_games_with_odds} games")

            view = st.radio("View", ["By Game", "All Players"], horizontal=True, key="pred_view")

            if view == "All Players":
                all_sorted = result.sort("probability", descending=True)
                top_n = st.slider("Show top N", 10, 100, 30, step=10, key="all_top_n")
                top_all = all_sorted.head(top_n)

                bar_max = 100.0 if target_type == "anytime_td" else 20.0
                rows = []
                for row in top_all.iter_rows(named=True):
                    game_label = row.get("game_label", "")
                    vegas_info = get_vegas_info(odds_data, row["player_name"], game_label, target_type)
                    edge_val = ""
                    vegas_str = ""
                    if vegas_info:
                        diff = row["probability"] - vegas_info["implied_prob"]
                        edge_val = "VALUE" if diff > 0.02 else ("FADE" if diff < -0.02 else "")
                        vegas_str = format_vegas(vegas_info)
                    rows.append({
                        "Player": row["player_name"],
                        "Team": row["team"],
                        "Game": game_label,
                        "Prob": row["probability"] * 100,
                        "Vegas": vegas_str,
                        "Edge": edge_val,
                    })

                st.dataframe(
                    rows,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Prob": st.column_config.ProgressColumn(
                            "Probability",
                            min_value=0.0,
                            max_value=bar_max,
                            format="%.1f%%",
                        ),
                    },
                )
            else:
                game_ids = sorted(result.select("game_id").unique()["game_id"].to_list())
                bar_max = 100.0 if target_type == "anytime_td" else 20.0

                for idx, game_id in enumerate(game_ids):
                    game = result.filter(pl.col("game_id") == game_id)
                    label = game["game_label"][0] if "game_label" in game.columns else game_id

                    game_odds = match_odds_to_game(odds_data, label, target_type) if has_odds else {}

                    with st.expander(f"{label}", expanded=(idx == 0)):
                        top = game.head(10)
                        rows = []
                        for row in top.iter_rows(named=True):
                            norm = _normalize_name(row["player_name"])
                            vegas_info = game_odds.get(norm)
                            edge_val = ""
                            vegas_str = ""
                            if vegas_info:
                                diff = row["probability"] - vegas_info["implied_prob"]
                                edge_val = "VALUE" if diff > 0.02 else ("FADE" if diff < -0.02 else "")
                                vegas_str = format_vegas(vegas_info)
                            rows.append({
                                "Rank": row["rank"],
                                "Player": row["player_name"],
                                "Team": row["team"],
                                "Prob": row["probability"] * 100,
                                "Vegas": vegas_str,
                                "Edge": edge_val,
                            })
                        st.dataframe(
                            rows,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "Prob": st.column_config.ProgressColumn(
                                    "Probability",
                                    min_value=0.0,
                                    max_value=bar_max,
                                    format="%.1f%%",
                                ),
                            },
                        )

            # ── AI Edge Analysis (inline) ──
            if has_odds:
                st.markdown("---")
                st.subheader("Model vs Vegas Edges")
                st.caption("Players where model and Vegas disagree by >3pp")

                all_edges, games_for_adj, _ = build_edges(
                    result, odds_data, target_type, df, season, week,
                )

                if all_edges:
                    render_edge_table(all_edges, key_prefix="pred_")
                else:
                    st.info("No significant edges (>3pp) this week.")

                # AI Adjustments toggle
                ai_enabled = cfg.get("ai_context", {}).get("enabled", False)
                enable_adjustments = st.checkbox(
                    "Enable AI Adjustments",
                    value=False,
                    disabled=not ai_enabled,
                    help="Apply Claude-generated probability adjustments (bounded +/-10%).",
                    key="ai_adj_toggle",
                )

                if enable_adjustments:
                    st.markdown("---")
                    st.markdown("### AI Probability Adjustments")

                    if st.button("Generate Adjustments", key="ai_gen_adj"):
                        adj_by_game = {}
                        progress = st.progress(0, text="Generating adjustments...")

                        for i, (gid, gdata) in enumerate(games_for_adj.items()):
                            progress.progress(
                                (i + 1) / len(games_for_adj),
                                text=f"Analyzing {gdata['label']}...",
                            )
                            adj = get_ai_adjustments(
                                game_id=gid,
                                game_label=gdata["label"],
                                players=gdata["players"],
                                season=season,
                                week=week,
                                target_type=target_type,
                            )
                            if adj:
                                adj_by_game[gid] = adj

                        progress.empty()
                        st.session_state["ai_adjustments"] = adj_by_game
                        n_adjusted = sum(len(v) for v in adj_by_game.values())
                        st.success(f"Generated adjustments for {n_adjusted} players across {len(adj_by_game)} games.")

                    if "ai_adjustments" in st.session_state and st.session_state["ai_adjustments"]:
                        adj_by_game = st.session_state["ai_adjustments"]
                        adjusted_result = apply_adjustments(result, adj_by_game)
                        adjusted_only = adjusted_result.filter(
                            pl.col("ai_reason") != ""
                        ).sort("ai_adjusted_prob", descending=True)

                        if adjusted_only.shape[0] > 0:
                            for row in adjusted_only.iter_rows(named=True):
                                raw = row["probability"] * 100
                                adj_val = row["ai_adjusted_prob"] * 100
                                diff = adj_val - raw
                                lbl = row.get("game_label", "")

                                col_a, col_b, col_c = st.columns([3, 2, 5])
                                with col_a:
                                    st.markdown(f"**{row['player_name']}** ({row['team']})")
                                    st.caption(lbl)
                                with col_b:
                                    st.metric(
                                        "Probability",
                                        f"{adj_val:.1f}%",
                                        delta=f"{diff:+.1f}pp",
                                        delta_color="normal" if diff > 0 else "inverse",
                                    )
                                with col_c:
                                    st.caption(row["ai_reason"])
                        else:
                            st.info("No adjustments applied — Claude found no clear situational signals.")


# ── Tab 2: Model Performance ──────────────────────────────────────────────

with tab2:
    metrics = load_metrics(target_type)
    df = load_features(target_type)
    model_dir = get_path("models", target_type)

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
                                "Rank": rank,
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
                        st.dataframe(bucket_rows, hide_index=True, use_container_width=True, height=400)

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
                            st.plotly_chart(fig, use_container_width=True)

        # --- Calibration curves ---
        if df is not None and model_dir.exists():
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
                    st.plotly_chart(fig, use_container_width=True)

        # --- Feature Importance (all features with definitions) ---
        if model_dir.exists():
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
                        use_container_width=True,
                        hide_index=True,
                        height=600,
                    )
                    st.caption(f"{len(imp_table)} total features")

        # --- Evaluation Metrics (bottom) ---
        if metrics:
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
            st.dataframe(rows, use_container_width=True, hide_index=True)


# ── Tab 3: Parlay Builder ────────────────────────────────────────────────────

with tab3:
    st.subheader("Parlay Builder")
    st.caption("Add players to build a parlay. Combined probability assumes independent events.")

    df = load_features(target_type)
    if df is None:
        st.warning("No features found. Run the pipeline first.")
    elif week is None:
        st.info("Select a season and week in the sidebar.")
    else:
        # Store for edge explain callbacks
        st.session_state["parlay_season"] = season
        st.session_state["parlay_week"] = week

        with st.spinner("Running predictions..."):
            result = run_prediction(season, week, selected_model, target_type)

        if result is None:
            st.info("No predictions available.")
        else:
            # Build player list keyed by player_id for persistence across model switches
            all_players = result.sort("probability", descending=True)
            id_to_row = {}
            id_to_label = {}
            for row in all_players.iter_rows(named=True):
                pid = row["player_id"]
                pct = row["probability"] * 100
                label = f"{row['player_name']} ({row['team']}) — {row.get('game_label', '')} — {pct:.1f}%"
                id_to_row[pid] = row
                id_to_label[pid] = label

            player_options = list(id_to_label.values())
            label_to_id = {v: k for k, v in id_to_label.items()}

            if "parlay_saved_ids" not in st.session_state:
                st.session_state["parlay_saved_ids"] = []

            default_labels = [
                id_to_label[pid]
                for pid in st.session_state["parlay_saved_ids"]
                if pid in id_to_label
            ]

            col_sel, col_clear = st.columns([5, 1])
            with col_sel:
                selected = st.multiselect(
                    "Select players for parlay",
                    player_options,
                    default=default_labels,
                    key="parlay_players",
                )
            with col_clear:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("Clear", key="parlay_clear"):
                    st.session_state["parlay_saved_ids"] = []
                    st.rerun()

            st.session_state["parlay_saved_ids"] = [
                label_to_id[l] for l in selected if l in label_to_id
            ]

            if selected:
                parlay_prob = 1.0
                parlay_rows = []
                odds_data = load_odds()

                for label in selected:
                    pid = label_to_id[label]
                    row = id_to_row[pid]
                    prob = row["probability"]
                    parlay_prob *= prob
                    vegas_info = get_vegas_info(
                        odds_data, row["player_name"],
                        row.get("game_label", ""), target_type,
                    ) if odds_data else None
                    parlay_rows.append({**row, "_vegas": vegas_info})

                # ── Leg breakdown table (edge style) ──
                st.markdown("---")
                st.markdown("### Your Parlay")

                leg_table = []
                for i, pr in enumerate(parlay_rows, 1):
                    model_pct = pr["probability"] * 100
                    vegas = pr["_vegas"]
                    if vegas:
                        vegas_pct = vegas["implied_prob"] * 100
                        edge_pp = model_pct - vegas_pct
                        direction = "VALUE" if edge_pp > 0 else "FADE"
                        leg_table.append({
                            "Leg": i,
                            "Player": f"{pr['player_name']} ({pr['team']})",
                            "Game": pr.get("game_label", ""),
                            "Model": f"{model_pct:.1f}%",
                            "Vegas": f"{vegas_pct:.1f}%",
                            "Edge": f"{edge_pp:+.1f}pp",
                            "Signal": direction,
                        })
                    else:
                        leg_table.append({
                            "Leg": i,
                            "Player": f"{pr['player_name']} ({pr['team']})",
                            "Game": pr.get("game_label", ""),
                            "Model": f"{model_pct:.1f}%",
                            "Vegas": "",
                            "Edge": "",
                            "Signal": "",
                        })

                st.dataframe(leg_table, use_container_width=True, hide_index=True)

                # ── Summary metrics ──
                n_legs = len(parlay_rows)
                parlay_pct = parlay_prob * 100
                fair_odds = _prob_to_american(parlay_prob)
                payout_mult = 1.0 / parlay_prob if parlay_prob > 0 else 0

                bet_amount = st.number_input(
                    "Bet amount ($)", min_value=1, value=10, step=5, key="parlay_bet",
                )

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric(
                        f"{n_legs}-Leg Parlay Chance",
                        f"{parlay_pct:.2f}%" if parlay_pct >= 0.01 else f"{parlay_pct:.4f}%",
                        help="Probability all legs hit (assumes independent events)",
                    )
                with col2:
                    st.metric(
                        "Fair Odds",
                        fair_odds,
                        help="What a sportsbook should offer with no house edge built in",
                    )
                with col3:
                    if payout_mult > 0:
                        win_amount = bet_amount * payout_mult
                        st.metric(
                            f"Fair Payout (${bet_amount} bet)",
                            f"${win_amount:,.2f}",
                            help="What you'd win if the sportsbook had no house edge",
                        )

                # ── Vegas comparison ──
                vegas_parlay = 1.0
                has_all_vegas = True
                for pr in parlay_rows:
                    if pr["_vegas"]:
                        vegas_parlay *= pr["_vegas"]["implied_prob"]
                    else:
                        has_all_vegas = False

                if has_all_vegas and parlay_rows:
                    vegas_pct = vegas_parlay * 100
                    edge_pct = (parlay_prob - vegas_parlay) * 100
                    vegas_odds = _prob_to_american(vegas_parlay)

                    st.markdown("---")
                    st.markdown("### Model vs Vegas")

                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Our Probability", f"{parlay_pct:.2f}%")
                        st.metric("Our Fair Odds", fair_odds)
                    with col2:
                        st.metric("Vegas Probability", f"{vegas_pct:.2f}%")
                        st.metric("Vegas Odds", vegas_odds)
                    with col3:
                        if edge_pct > 0:
                            verdict = "Model likes this MORE than Vegas"
                            delta_color = "normal"
                        elif edge_pct < 0:
                            verdict = "Vegas likes this MORE than model"
                            delta_color = "inverse"
                        else:
                            verdict = "Model and Vegas agree"
                            delta_color = "off"
                        st.metric(
                            "Edge",
                            f"{edge_pct:+.2f}pp",
                            delta=verdict,
                            delta_color=delta_color,
                        )
                elif odds_data and not has_all_vegas:
                    st.caption("Vegas odds not available for all legs — comparison unavailable.")

            # ── AI Edge Analysis on Parlay page ──
            odds_data_parlay = load_odds()
            if odds_data_parlay:
                st.markdown("---")
                st.subheader("All Edges This Week")
                st.caption("Find value plays to add to your parlay")

                all_edges_parlay, _, _ = build_edges(
                    result, odds_data_parlay, target_type, df, season, week,
                )

                if all_edges_parlay:
                    render_edge_table(all_edges_parlay, key_prefix="parlay_")
                else:
                    st.info("No significant edges (>3pp) this week.")
