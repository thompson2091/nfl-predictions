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


@st.cache_data(show_spinner=False)
def version_options(tt: str) -> list[dict]:
    """Locked versions with artifacts on disk. Empty when the flag is off."""
    if not cfg.get("app", {}).get("version_selector", False):
        return []
    from src.models.versioning import available_versions
    try:
        # Only versions that would actually score differently. Two of the four
        # locked versions changed config or metrics without retraining, so
        # offering them made the selector look broken.
        return available_versions(tt, distinct_weights=True)
    except Exception:                                        # noqa: BLE001
        return []


def version_scoring_config(version_id: str | None) -> dict:
    """Settings to restore while previewing, or {} for the served version.

    A preview used to restore weights alone, which cannot reproduce a
    config-only change — and two of this project's model changes were exactly
    that. See `versioning.scoring_config` for what is restored and what is
    deliberately left alone.
    """
    if not version_id:
        return {}
    from src.models.versioning import scoring_config
    try:
        return scoring_config(version_id)
    except Exception:                                        # noqa: BLE001
        return {}


def selected_model_dir(tt: str, version_id: str | None):
    """Where to load artifacts from, and whether writing back is allowed.

    Returns (model_dir, persist). `persist` is False for anything but the
    served version: a snapshot is the record of what produced a set of numbers,
    so scoring against one must not rewrite its blend weight, and must not
    overwrite the published predictions with a model nobody promoted.
    """
    from src.models.versioning import market_dir
    if not version_id:
        return None, True
    served = (served_version(tt) or {}).get("id")
    if version_id == served:
        return None, True
    return market_dir(tt, version_id), False


@st.cache_data(show_spinner=False)
def served_version(tt: str) -> dict | None:
    """The locked version this market is serving, or None if nothing is locked.

    Hashes every artifact in the market's model directory, so it is cached like
    everything else here and cleared by the same "Reload artifacts" button —
    which is exactly when it can change.
    """
    from src.models.versioning import current_version
    try:
        return current_version(tt)
    except Exception:                                        # noqa: BLE001
        # A missing or malformed registry must not take the page down; the
        # board is still correct, it is just unlabelled.
        return None


# ── Sidebar ────────────────────────────────────────────────────────────────

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


@st.cache_data(show_spinner=False)
@guarded
def receptions_summary():
    import json as _json
    path = get_path("output", "receptions") / "summary.json"
    return _json.loads(path.read_text()) if path.exists() else None


@st.cache_data(show_spinner=False)
@guarded
def receptions_backtests():
    import glob as _glob
    files = sorted(_glob.glob(str(get_path("output", "receptions") / "backtest_2*.csv")))
    if not files:
        return None
    return pl.concat([pl.read_csv(f) for f in files], how="diagonal_relaxed").to_pandas()


@st.cache_data(show_spinner=False, ttl=60)
@guarded
def derived_staleness():
    """Artifacts on the page that predate the model being served.

    Short TTL rather than none: these clear as soon as the pipeline is re-run,
    and a cached warning that outlives its cause is how a real one stops being
    read.
    """
    from src.models.versioning import stale_derived
    return stale_derived()


@st.cache_data(show_spinner=False)
@guarded
def feature_set_state(tt: str):
    """Which builder families this market trains on, and what that cost.

    Reads the same three files the pipeline does — the config allow-list, the
    column-to-builder map, and the retention curve — so the page cannot drift
    from what is actually trained. Nothing here is recomputed.
    """
    import json as _json
    from pathlib import Path as _Path

    from src.models.trainer import included_families
    from src.utils.config import get_config

    root = _Path(__file__).resolve().parent
    fam = _json.loads((root / "diagnostics" / "feature_families.json").read_text())
    families, unattributed = fam["families"], fam.get("unattributed") or []

    keep = included_families(get_config(), tt)
    on = sorted(families) if keep is None else sorted(
        f for f in families if set(families[f]) <= set(keep))
    off = [f for f in sorted(families) if f not in on]

    ab_path = root / "diagnostics" / f"ablation_{tt}.json"
    ablation = (_json.loads(ab_path.read_text()).get("families", {})
                if ab_path.exists() else {})
    ret_path = root / "diagnostics" / f"retention_{tt}.json"
    retention = _json.loads(ret_path.read_text()) if ret_path.exists() else None

    return {"on": on, "off": off, "all": sorted(families),
            "sizes": {f: len(c) for f, c in families.items()},
            "unattributed": len(unattributed),
            "columns_on": sum(len(families[f]) for f in on) + len(unattributed),
            "columns_all": sum(len(c) for c in families.values()) + len(unattributed),
            "ablation": ablation, "retention": retention}


@st.cache_data(show_spinner=False)
@guarded
def receptions_calibration():
    """When this model says 80%, how often is it right? Measured, by band."""
    from src.evaluation.receptions_hit_rates import calibration
    return calibration()


@st.cache_data(show_spinner=False)
@guarded
def receptions_sweep():
    """Accuracy bought by selectivity, and the coverage it costs."""
    from src.evaluation.receptions_hit_rates import sweep
    return sweep()


@st.cache_data(show_spinner=False, max_entries=8)
@guarded
def receptions_projections(season: int, week: int):
    """Every candidate's projected catches, whether or not a book priced him.

    The lines table can only show players a bookmaker has quoted, and for
    receptions that is nobody until close to kickoff. The model has a number
    for every player on a roster the whole time, so this is the view that does
    not depend on the market existing yet — expected catches, and the chance of
    clearing each standard line, from one fitted distribution.
    """
    from src.models.count import XGBCountModel, prob_over

    model_path = get_path("models", "receptions") / "xgb_count.pkl"
    if not model_path.exists():
        return None
    m = XGBCountModel.load(model_path)
    feats = pl.read_parquet(get_path("processed", "anytime_td") / "features.parquet")
    wk = feats.filter((pl.col("season") == season) & (pl.col("week") == week))
    if wk.height == 0:
        return None
    fcols = [c for c in m.feature_names if c in wk.columns]
    mu = m.predict_mu(wk.select(fcols).to_numpy())
    out = wk.select(["game_id", "player_name", "team"]).with_columns(pl.Series("mu", mu))
    import numpy as _np
    for line in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5):
        over, _ = prob_over(out["mu"].to_numpy(),
                            _np.full(out.height, line), m.dispersion)
        out = out.with_columns(pl.Series(f"p_{line}", over))
    return out.sort("mu", descending=True).to_pandas()


@st.cache_data(show_spinner=False, max_entries=8)
@guarded
def receptions_week_lines(season: int):
    """Posted lines for the predict season, scored by the count model."""
    from src.ingest.odds_history import HISTORY_PATH, SCHEMA, _conform, _resolve_player_id
    from src.models.count import XGBCountModel, fair_two_way, prob_over

    if not HISTORY_PATH.exists():
        return None
    h = _conform(pl.read_parquet(HISTORY_PATH), SCHEMA).filter(
        (pl.col("market") == "receptions") & (pl.col("season") == season)
        & pl.col("point").is_not_null())
    if h.height == 0:
        return None
    h = (h.sort("captured_at").unique(
            subset=["season", "week", "game_id", "player_name_norm", "point"],
            keep="last")
         .with_columns(_resolve_player_id(h)))

    model_path = get_path("models", "receptions") / "xgb_count.pkl"
    if not model_path.exists():
        return h.to_pandas()
    m = XGBCountModel.load(model_path)
    feats = pl.read_parquet(get_path("processed", "anytime_td") / "features.parquet")
    wk = feats.filter(pl.col("season") == season)
    if wk.height == 0:
        return h.to_pandas()
    fcols = [c for c in m.feature_names if c in wk.columns]
    mu = m.predict_mu(wk.select(fcols).to_numpy())
    wk = wk.select(["season", "week", "player_id"]).with_columns(pl.Series("mu", mu))
    j = h.join(wk, on=["season", "week", "player_id"], how="left")
    has = j["mu"].is_not_null().to_numpy()
    import numpy as _np
    p = _np.full(j.height, _np.nan)
    if has.any():
        over, push = prob_over(j["mu"].to_numpy()[has],
                               j["point"].to_numpy()[has], m.dispersion)
        p[has] = fair_two_way(over, push)
    return j.with_columns(pl.Series("p_model", p)).to_pandas()


@st.cache_data(show_spinner=False)
@guarded
def cover_record(tt: str, model: str | None = None):
    """How the full-cover rule has actually done. Absent is a real state."""
    from src.evaluation.cover_backtest import load
    return load(get_path("output", tt) / "cover_backtest.json")


def render_cover_record(tt: str, n: int) -> None:
    """What this rule returned when it was replayed, not what it projects.

    Everything above is a product of estimates and prices, and a product
    compounds whatever is wrong with each term — a model two points
    overconfident per leg is two points wrong on a single and closer to ten on
    a five-fold. So the gap between what a cover projects and what it returned
    is the sharpest calibration reading on the board, and it is the only figure
    here that cannot be argued with: slips either landed or they did not.
    """
    rec, err = cover_record(tt)
    if err or not rec:
        st.caption(
            ":material/warning: **Nothing in this section has been graded.** "
            f"Every figure above is a projection. Run `make cover-backtest "
            f"TARGET={tt}` to replay the rule over the backtested weeks.")
        return

    # One line, not the ten-column table this used to be. That table was the
    # whole grading and it earned its place while nothing here had been
    # measured at all; the answer is short, and it was ten columns of it under
    # the projection it qualifies. `roi_beats_zero` is the artifact's own
    # verdict — profitable means the interval clears zero, not that the point
    # estimate happened to land positive.
    row = next((x for x in rec["sizes"] if x["n"] == n), None)
    rois = [x["roi"] for x in rec["sizes"]]
    worse = [x for x in rec["sizes"] if x["roi"] < x["singles_roi"]]
    clears = [x for x in rec["sizes"] if x.get("roi_beats_zero")]
    st.caption(
        f":material/history: **Graded.** Replayed over {rec['weeks']} weeks "
        f"({rec['span']}) at ${rec['stake']:.2f} a slip on the prices actually "
        f"posted, this rule returned between {min(rois):+.1%} and "
        f"{max(rois):+.1%} depending on pool size, and "
        + (f"**{len(clears)} of {len(rec['sizes'])} sizes had an interval "
           f"clearing zero.** " if clears else
           "**no pool size had an interval clearing zero.** ")
        + (f"{len(worse)} of {len(rec['sizes'])} returned less than the same "
           f"money on the singles — which is what a negative edge per leg does "
           f"when it is multiplied: a k-fold pays the margin k times. "
           if worse else "")
        + (f"At the {n} you have picked it returned **{row['roi']:+.1%}** "
           f"[{row['roi_lo']:.0%}, {row['roi_hi']:.0%}] with "
           f"{row['weeks_profitable']} of {row['weeks']} weeks ahead."
           if row else
           f"{n} players is outside the replayed range, so there is no "
           f"measured figure for it."))
    render_cover_selection(tt)


@guarded
def cover_selection(tt: str):
    """Whether a different cover rule would have done better. Absent is fine."""
    from src.evaluation.cover_selection import load
    return load(get_path("output", tt) / "cover_selection.json")


def render_cover_selection(tt: str) -> None:
    """The one line worth carrying from `make cover-selection`.

    That measurement is 44 variants, a hindsight ceiling, a walk-forward chooser
    and a random control redrawn five times. None of it belongs under a bet
    slip; the single pattern in it that is not one lucky cell does, and it never
    travels without the control. The best of 44 RANDOM orderings reached +274%
    on the same weeks, so a best-of-44 quoted alone is not evidence of anything.
    """
    sel, err = cover_selection(tt)
    if err or not sel:
        return
    fam = sel.get("unblended_vs_published") or {}
    ctl = (sel.get("control") or {}).get("best_roi") or {}
    if fam.get("identical"):
        st.caption(
            f":material/science: **Would a different rule have helped?** Not by "
            f"re-ranking: this market's blend does not move the number, so the "
            f"model's own ordering and the published one pick the same players "
            f"at every size. Of {sel['n_variants']} rules tried over "
            f"{sel['weeks']} weeks, none has an interval clearing zero.")
        return
    pairs = fam.get("sizes") or []
    if not pairs:
        return
    best = max(pairs, key=lambda p: p["gap"])
    st.caption(
        f":material/science: **Would a different rule have helped?** Over the "
        f"same {sel['weeks']} weeks, ranking by the model's own number instead "
        f"of the blended one returned **{best['model_roi']:+.1%}** at "
        f"{best['n']} players against **{best['published_roi']:+.1%}** — ahead "
        f"at {fam.get('model_wins')} of {len(pairs)} sizes. "
        + ("" if (sel.get("verdict") or {}).get("any_variant_beats_zero")
           else "No interval clears zero, ")
        + f"and the best of {sel['n_variants']} *random* orderings reached "
          f"{ctl.get('max', 0):+.0%} on the same weeks — so read this as a "
          f"direction, not a result. Blending pulls our number toward the "
          f"price, which is what makes it better calibrated and also what "
          f"deletes the disagreement a bet lives on.")


def render_cover(cov: dict, tt: str) -> None:
    """What every combination of the selected players returns, by how many score.

    One table, because there is only one question: back all 2^n - 1 slips, and
    what happens at each number of scorers. The legs are not re-listed — they
    are the names just chosen, and the board above already describes them.

    Three things it is careful about, each a way this could read as a
    recommendation it has not earned:

    A breakeven row means nothing without the chance of reaching it, so
    P(k of n) sits in the table rather than under it.

    Returns are a RANGE when the legs are priced differently: two of five can
    be the two short legs or the two long ones. The figure shown is weighted by
    how likely each combination is, and the spread is called out when it is wide.

    And an expected value computed against an ASSUMED price is the model marking
    its own homework, so it says so whenever a leg was unpriced.
    """
    def _m(x: float) -> str:
        """Dollars, escaped: Streamlit reads a matched pair as LaTeX."""
        return f"\\${x:,.2f}"

    n, staked = cov["n"], cov["staked"]
    priced = sum(1 for l in cov["legs"] if l["priced"])
    st.caption(bp.cover_headline(cov, _m))

    rows, wide = [], False
    for r in cov["rows"]:
        wide = wide or (r["returned_max"] - r["returned_min"]) > max(
            0.15 * max(r["returned"], 1e-9), 1e-9)
        rows.append({
            "Players who score": f"{r['scored']} of {n}",
            "Chance of this": r["probability"] * 100,
            "Winning bets": r["winning_bets"],
            "Total returned": r["returned"],
            f"Net on {_m(staked)}": r["net"],
        })
    st.dataframe(
        pd.DataFrame(rows), hide_index=True,
        column_config={
            "Chance of this": st.column_config.NumberColumn(
                format="%.1f%%",
                help="How often exactly this many of the players you picked "
                     "score, on the model's own probabilities."),
            "Total returned": st.column_config.NumberColumn(format="$%.2f"),
            f"Net on {_m(staked)}": st.column_config.NumberColumn(
                format="$%+.2f"),
        })

    be, p_be = cov["breakeven_scored"], cov["p_breakeven"]
    if n == 1:
        # With one leg the k-of-n framing says nothing a bettor wants: the whole
        # question is the price against the probability. So it gets the two
        # numbers that answer it, and says when the price is one you assumed.
        from src.prediction.bets import decimal_to_american
        leg = cov["legs"][0]
        d = float(leg.get("decimal") or cov["assumed_decimal"] or 2.0)
        need, gap = 1.0 / d, (leg["prob"] - 1.0 / d) * 100
        st.success(
            f"**This is a single bet.** At {bp.american(decimal_to_american(d))} "
            f"({d:.2f}) the price needs **{need:.1%}** to break even and we "
            f"make it **{leg['prob']:.1%}** — "
            + (f"an edge of **{gap:+.1f} points**." if gap > 0
               else f"a shortfall of **{abs(gap):.1f} points**.")
            + ("" if leg["priced"] else
               " That is against a price you assumed rather than one a book "
               "has posted, so the edge is an artefact of the assumption, not "
               "a measurement."),
            icon=(":material/target:" if gap > 0 else ":material/block:"))
    elif be is None:
        st.error(
            f"**No number of scorers turns a profit.** Even all {n} landing "
            f"returns {_m(cov['rows'][-1]['returned'])} against "
            f"{_m(staked)} staked.", icon=":material/block:")
    else:
        st.success(
            f"**Breakeven is {be} of {n}** — and that happens **{p_be:.1%}** "
            f"of the time"
            + (f", with the measured teammate correlation of {cov['rho']:+.3f} "
               f"applied" if cov["rho"] else ", treating the legs as independent")
            + ".", icon=":material/target:")

    if wide:
        st.caption(
            ":material/info: Returns vary within a row because the legs are "
            "priced differently — two of five can be the two short legs or the "
            "two long ones. The figure shown is weighted by how likely each "
            "combination is.")

    ev, single = cov["expected_roi"], cov["singles_only"]["expected_roi"]
    if not cov["all_priced"]:
        from src.prediction.bets import decimal_to_american
        # Name the prices the answer actually rests on. One number for all of
        # them is what made this table lie: five legs charged off a curve are
        # five different prices, and the payout column cannot show which,
        # because it is built from prices and does not move when the
        # probabilities do.
        _stand = sorted(float(l["decimal"]) for l in cov["legs"]
                        if not l["priced"])
        _rng = (bp.american(decimal_to_american(_stand[0])) if _stand else "—")
        if _stand and _stand[0] != _stand[-1]:
            _rng += f" to {bp.american(decimal_to_american(_stand[-1]))}"
        st.warning(
            f"**The expected result below is not a measured edge.** "
            f"{len(_stand)} of {cov['n']} legs have no market price, so they "
            f"are charged what this market posts for players we rate that "
            f"highly ({_rng}). That is a reading of a margin curve rather than "
            f"a quote for these players, and the whole table moves with it: "
            f"charge them a price no book would offer and the profit you see "
            f"is the profit in the assumption.", icon=":material/warning:")
    if n == 1:
        st.caption(
            f":material/functions: Expected result "
            f"**{bp.signed_money(cov['expected_net'])}** ({ev:+.1%}) on "
            f"{_m(staked)}. With one leg there is nothing to multiply, so this "
            f"is the edge itself rather than leverage on it — add a second "
            f"player and the same edge is compounded, in both directions.")
        render_cover_record(tt, n)
        return
    st.caption(
        f":material/functions: Expected result **{bp.signed_money(cov['expected_net'])}** "
        f"({ev:+.1%}) against **{bp.signed_money(cov['singles_only']['expected_net'])}** "
        f"({single:+.1%}) for the same {_m(staked)} on the {n} singles alone.\n\n"
        + ("A cover is leverage on the edge in each leg: per dollar a single "
           "returns *e* and a k-fold returns *(1+e)^k − 1*. "
           + ("These prices leave a positive edge, so multiplying them "
              "compounds it — at far higher variance, and on the model's "
              "probabilities rather than a measured result."
              if ev > single else
              "These prices leave a negative edge, so multiplying them pays "
              "the margin once per leg and the cover loses harder than the "
              "singles do. Only a better price or a better probability fixes "
              "that; the structure cannot.")))

    render_cover_record(tt, n)


def render_feature_set(tt: str, version: str | None = None):
    """Which families this market trains on, what it cost, and how to change it.

    The allow-list lives in `config/settings.yaml` and the alternatives live in
    the version registry, so before this panel the only way to know what the
    served model could see was to read a YAML comment. A choice you cannot see
    is not a choice.

    Read-only by design. The controls below build an experiment file; they do
    not retrain, and the reason is in `render_feature_lab`.
    """
    st.markdown("**Feature set — what this model is allowed to see**")
    state, err = feature_set_state(tt)
    if err:
        st.caption(f":material/error: feature set unavailable — `{err}`")
        return
    on, off, sizes = state["on"], state["off"], state["sizes"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Builder families", f"{len(on)} of {len(state['all'])}")
    c2.metric("Feature columns", f"{state['columns_on']} of {state['columns_all']}")
    ret = state["retention"] or {}
    pt = (ret.get("points") or {}).get(f"ranked-{len(on):02d}")
    c3.metric("Top-1 vs the full set",
              f"{pt['top1_delta']*100:+.2f}pp" if pt else "not measured",
              help="Paired per game against training on every family.")

    if not off:
        st.caption("This market trains on every family. `make retention "
                   f"TARGET={tt}` measures whether a smaller set would rank "
                   "better — on anytime TD it did.")
    else:
        rows = []
        for f in off:
            a = (state["ablation"] or {}).get(f) or {}
            rows.append({
                "Family held out": f.replace("build_", "").replace("_features", ""),
                "Columns": sizes.get(f, 0),
                "Cost when dropped alone": (a.get("top1_delta") or 0) * 100,
                "p": a.get("p_value"),
            })
        st.dataframe(
            pd.DataFrame(rows), hide_index=True,
            column_config={
                "Cost when dropped alone": st.column_config.NumberColumn(
                    format="%+.2f%%",
                    help="Top-1 change from removing this family ALONE from the "
                         "full set. Near zero for most: families cover for each "
                         "other, so leave-one-out cannot find a prunable set. "
                         "That is why these were chosen by building up instead."),
                "p": st.column_config.NumberColumn(format="%.3f"),
            })
        st.caption(
            f"Nothing is deleted — all {len(state['all'])} builders still run and "
            f"every column is still in `features.parquet`. These {len(off)} are "
            f"excluded by an allow-list in `config/settings.yaml`, and the "
            f"full-feature model stays locked and switchable: "
            f"`make promote ID=2026.08.19-clean-matrix MARKET={tt}`."
        )


def render_feature_lab(tt: str):
    """Choose a feature set, and get the commands that would test it honestly.

    **Why this does not retrain in the browser.** One walk-forward is minutes,
    and a single seed cannot resolve what it would show: the seed-to-seed band
    on anytime TD Top-1 is 0.64pp, and adjacent points on the retention ladder
    differ by more than that. A button that returns one number after a four
    minute wait would be a slot machine.

    The deeper reason is that picking a feature set by looking at held-out
    accuracy IS fitting to the held-out season, one toggle at a time. Every set
    tried is a comparison, and trying twenty and keeping the best finds roughly
    one 5%-significant result by chance. That is not hypothetical here: 13
    ladder points were measured and the peak read p=0.043, which is about what
    13 tries produce from nothing. It survived only because it was then
    seed-averaged and paired head to head.

    So this builds the experiment file, and the honest path runs outside the
    app where it leaves a ledger row: screen, then settle across seeds, then
    lock. Nothing here can change what is served.
    """
    state, err = feature_set_state(tt)
    if err:
        return
    import json as _json
    from pathlib import Path as _Path

    with st.expander("Build a custom feature set", expanded=False):
        st.caption(
            "Pick families, get a runnable experiment. This never retrains and "
            "never promotes — see below for why that is deliberate.")
        chosen = st.multiselect(
            "Families to train on", state["all"], default=state["on"],
            format_func=lambda f: f"{f.replace('build_', '').replace('_features', '')} "
                                  f"({state['sizes'].get(f, 0)})",
            key=f"lab-{tt}")
        cols = sum(state["sizes"].get(f, 0) for f in chosen) + state["unattributed"]
        st.caption(f"{len(chosen)} families, {cols} of {state['columns_all']} "
                   f"columns (the {state['unattributed']} unattributed columns — "
                   f"position dummies, week number, usage flags — are always kept; "
                   f"no builder claims them and a model without them is broken, "
                   f"not lean).")

        if not chosen:
            st.warning("A set with no families is not a model.", icon=":material/block:")
            return
        if sorted(chosen) == state["on"]:
            st.info("That is the set already being served.", icon=":material/check:")

        slug = f"custom-{tt}-{len(chosen)}"
        body = "\n".join(f"      - {f}" for f in sorted(chosen))
        yaml_text = (
            f"# Built from the app on the Model performance tab.\n"
            f"# {len(chosen)} of {len(state['all'])} families, {cols} of "
            f"{state['columns_all']} columns.\n"
            f"id: {slug}\n"
            f'note: "custom feature set, {len(chosen)} families"\n'
            f"overlay:\n  models:\n"
            f"    include_feature_families_by_target:\n      {tt}:\n{body}\n")
        st.code(yaml_text, language="yaml")
        st.code(
            f"# 1. write it\n"
            f"cat > experiments/{slug}.yaml <<'EOF'\n{yaml_text}EOF\n\n"
            f"# 2. one seed, minutes — never promotes\n"
            f"make screen EXP=experiments/{slug}.yaml MARKET={tt}\n\n"
            f"# 3. the test that decides: five seeds, paired per game\n"
            f"make settle-overlay EXP=experiments/{slug}.yaml SEEDS=5 MARKET={tt}\n\n"
            f"# 4. only if step 3 holds\n"
            f"make train && make lock ID=YYYY.MM.DD-{slug} NOTE=\"...\"\n",
            language="bash")

        # Writing the file and launching the screen, rather than asking the
        # reader to copy four commands into a terminal. The screen is one seed
        # and never promotes; `settle-overlay` stays a deliberate second step
        # because that is the test that separates a real gain from the seed,
        # and collapsing them into one button is how the separation stops
        # being noticed.
        exp_dir = _Path(__file__).resolve().parent / "experiments"
        target = exp_dir / f"{slug}.yaml"
        c1, c2 = st.columns([1, 2])
        if c1.button("Write and screen it", key=f"lab-run-{tt}",
                     disabled=sorted(chosen) == state["on"]):
            import subprocess
            target.write_text(yaml_text)
            log = _Path(__file__).resolve().parent / "logs" / f"screen_{slug}.log"
            log.parent.mkdir(exist_ok=True)
            with open(log, "w") as fh:
                subprocess.Popen(
                    [sys.executable, "scripts/23_experiment.py", "screen",
                     str(target), "--market", tt],
                    stdout=fh, stderr=fh,
                    cwd=str(_Path(__file__).resolve().parent),
                    start_new_session=True)
            st.success(
                f"Wrote `experiments/{slug}.yaml` and started a screen in the "
                f"background — one seed, minutes, never promotes. Output goes "
                f"to `logs/screen_{slug}.log`. When it finishes, settle it "
                f"before believing it:\n\n"
                f"`make settle-overlay EXP=experiments/{slug}.yaml SEEDS=5 "
                f"MARKET={tt}`", icon=":material/play_arrow:")
        c2.caption(
            "The screen runs one seed. It cannot resolve what it shows — the "
            "seed band on anytime TD Top-1 is 0.64pp and adjacent points on "
            "the retention ladder differ by more than that. Treat it as a "
            "filter, not an answer.")

        _log = _Path(__file__).resolve().parent / "logs" / f"screen_{slug}.log"
        if _log.exists():
            _tail = _log.read_text().strip().splitlines()[-14:]
            with st.expander(f"Last screen for this set — `{_log.name}`"):
                st.code("\n".join(_tail) or "(empty)", language="text")

        tried = len(list(exp_dir.glob("*.yaml")))
        st.caption(
            f"{tried} experiment files exist in this repo. Every feature set "
            f"tried is a comparison against the same held-out seasons, so at "
            f"p<0.05 roughly one in twenty will look significant having changed "
            f"nothing. Step 3 is what separates the two: it averages each "
            f"game's outcome over five seeds before pairing, and the served "
            f"K=24 set clears it at p=0.007 while its single-seed ladder point "
            f"read p=0.043.")


def render_receptions_selectivity():
    """The answer to "when we say 80%, how often is that right".

    It is not 80%. On held-out seasons the model claims 85% and lands 69%, and
    the gap widens with the claim, so the top of this board is exactly where
    its stated number is least trustworthy. The panel leads with that rather
    than burying it under a table, because a confidence column that is read at
    face value is worse than no confidence column.

    Confidence is `max(p, 1-p)` on the side taken. A row at P(over)=0.18 is a
    strong under call, not a weak over call, and grading it on the over would
    report a confident correct pick as a miss.
    """
    cal, err = receptions_calibration()
    if err:
        st.caption(f":material/error: calibration unavailable — `{err}`")
        return
    if not cal:
        st.caption("No graded receptions backtests yet — run "
                   "`python scripts/30_receptions.py`.")
        return

    top = max(cal["bands"], key=lambda b: b["lo"])
    st.markdown("**When we say a number, how often is it right?**")
    st.warning(
        f"**The stated confidence runs hot, and worst at the top.** In the "
        f"most confident band this model claims **{top['claimed']:.0%}** and "
        f"lands **{top['measured']:.0%}** "
        f"(90% CI {top['ci_lo']:.0%}–{top['ci_hi']:.0%}, {top['n']:,} graded "
        f"lines). Read the *measured* column, not the model's own number.",
        icon=":material/warning:",
    )

    rows = []
    for b in cal["bands"]:
        mk = b.get("market")
        rows.append({
            "Confidence band": f"{b['lo']:.0%}–{b['hi']:.0%}",
            "Lines graded": b["n"],
            "We said": b["claimed"] * 100,
            "Actually right": b["measured"] * 100,
            "90% CI": f"{b['ci_lo']:.0%}–{b['ci_hi']:.0%}",
            "Gap": b["gap"] * 100,
            "Book said": mk["claimed"] * 100 if mk else None,
            "Book right": mk["measured"] * 100 if mk else None,
        })
    pct = st.column_config.NumberColumn(format="%.1f%%")
    st.dataframe(
        pd.DataFrame(rows), hide_index=True,
        column_config={"We said": pct, "Actually right": pct,
                       "Gap": st.column_config.NumberColumn(format="%+.1f%%"),
                       "Book said": pct, "Book right": pct},
    )
    sw, sw_err = receptions_sweep()
    if not sw_err and sw:
        best = max(sw, key=lambda r: r["measured"])
        st.markdown("**Does being choosier help?**")
        st.dataframe(
            pd.DataFrame([{
                "Act only above": f"{r['threshold']:.0%}",
                "Lines kept": r["n"],
                "Share of board": r["share"] * 100,
                "Actually right": r["measured"] * 100,
                "90% CI": f"{r['ci_lo']:.0%}–{r['ci_hi']:.0%}",
            } for r in sw]),
            hide_index=True,
            column_config={
                "Share of board": st.column_config.NumberColumn(format="%.1f%%"),
                "Actually right": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
        st.caption(
            f"Selectivity buys accuracy up to a point and then stops. The best "
            f"measured cut is **{best['threshold']:.0%}**, right "
            f"**{best['measured']:.1%}** on {best['share']:.1%} of priced "
            f"lines. Tightening further to the top band does not help — it is "
            f"the band whose stated confidence is furthest from the truth, so "
            f"there is nothing left to select on."
        )

    st.caption(
        f"Measured over {cal['rows']:,} graded lines across "
        f"{len(cal['seasons'])} held-out seasons "
        f"({', '.join(str(x) for x in cal['seasons'])}), intervals bootstrapped "
        f"over {cal['games']:,} games rather than lines — a player carries "
        f"several lines and a blowout moves all of them together, so treating "
        f"lines as independent would understate the interval. The book's own "
        f"stated price lands inside its measured rate in every band where it "
        f"quotes one; ours does not. That is the same conclusion as the log "
        f"loss above, seen from the side you would actually act on."
    )


def render_receptions_page():
    """The receptions market: a viewer with a measured second opinion.

    Framed as what the measurement supports and nothing more. This model does
    not beat this market — log loss 0.669 vs the book's 0.644 on 2024, 0.689
    vs 0.673 on 2025, both held out — and the version that appeared to beat it
    by +17-22% ROI is how the NGS existence leak was found. The page says so
    at the top, because the one thing worse than no receptions view is a
    receptions view that implies an edge nobody measured.
    """
    smry, err = receptions_summary()
    if err:
        st.error(f"Receptions summary unavailable — `{err}`")
        return
    if not smry:
        st.info("Run `python scripts/30_receptions.py` to train and grade the model.")
        return

    with st.container(border=True):
        st.markdown(
            "#### The book prices this market better than we do\n\n"
            "One count model prices every line (see the dispersion note below), "
            "and on held-out seasons the market's de-vigged price is closer to "
            "what happened than our number is:"
        )
        cols = st.columns(len(smry["seasons"]) or 1)
        for c, r in zip(cols, smry["seasons"]):
            better = r["model"]["log_loss"] < r["market"]["log_loss"]
            c.metric(
                f"{r['season']} log loss (n={r['n']:,})",
                f"{r['model']['log_loss']:.4f}",
                delta=f"market {r['market']['log_loss']:.4f}",
                delta_color="off",
            )
        st.caption(
            f"Negative binomial dispersion r = {smry['dispersion']:.1f}, fitted on "
            f"{smry['splits']['val_season']} — large r means the residuals are "
            f"nearly Poisson once {smry['n_features']} features have explained the "
            f"mean. Use this page to see the lines and our second opinion, not to "
            f"find edges: the first version that appeared to beat this market "
            f"(+17-22% ROI) is how the NGS data leak was found."
        )

    bt, bt_err = receptions_backtests()
    if bt_err:
        st.caption(f":material/error: backtests unavailable — `{bt_err}`")
    elif bt is not None and len(bt):
        st.markdown("**Calibration by line, held-out seasons**")
        g = (pl.from_pandas(bt).group_by("point").agg([
                pl.len().alias("n"),
                pl.col("y_over").mean().alias("actual"),
                pl.col("p_model").mean().alias("model"),
                pl.col("fair_prob").mean().alias("market"),
             ]).filter(pl.col("n") >= 100).sort("point")).to_pandas()
        g["actual"] *= 100; g["model"] *= 100; g["market"] *= 100
        st.dataframe(
            g.rename(columns={"point": "Line", "n": "Bets graded",
                              "actual": "Over hit", "model": "We said",
                              "market": "Book said"}),
            hide_index=True,
            column_config={
                "Over hit": st.column_config.NumberColumn(format="%.1f%%"),
                "We said": st.column_config.NumberColumn(format="%.1f%%"),
                "Book said": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )

    render_receptions_selectivity()

    season = cfg["seasons"]["predict_season"]

    # Projections first: they exist for every player from the moment the
    # feature matrix is built, where the lines table waits on a bookmaker.
    st.markdown(f"**Projected catches, {season}**")
    _weeks = sorted(pl.read_parquet(
        get_path("processed", "anytime_td") / "features.parquet"
    ).filter(pl.col("season") == season)["week"].unique().to_list())
    _wk_sel = st.selectbox("Week", _weeks, key="receptions_week") if _weeks else None
    proj, proj_err = (receptions_projections(season, _wk_sel)
                      if _wk_sel is not None else (None, None))
    if proj_err:
        st.caption(f":material/error: `{proj_err}`")
    elif proj is None or not len(proj):
        st.info("No feature rows for that week — run the pipeline.")
    else:
        _min = st.slider("Minimum projected catches", 0.0, 6.0, 1.0, 0.5,
                         key="receptions_min_mu")
        show = proj[proj["mu"] >= _min].copy()
        disp = show.assign(
            Player=show["player_name"], Team=show["team"],
            Projected=show["mu"],
            **{f"{ln}+": show[f"p_{ln}"] * 100 for ln in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)},
        )
        cols = ["Player", "Team", "Projected"] + [f"{ln}+" for ln in
                                                  (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)]
        st.dataframe(
            disp[cols], hide_index=True,
            column_config={
                "Projected": st.column_config.NumberColumn(
                    "Projected catches", format="%.2f",
                    help="Expected receptions — the count model's mean."),
                **{f"{ln}+": st.column_config.NumberColumn(
                    f"{ln}+", format="%.0f%%",
                    help=f"Chance of more than {ln} catches, from the same "
                         f"fitted distribution as every other column.")
                   for ln in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)},
            },
        )
        st.caption(
            f"{len(show)} of {len(proj)} players projected at {_min:.1f}+ catches. "
            f"Every column comes from one distribution per player, so they are "
            f"consistent by construction — a player cannot be likelier to clear "
            f"3.5 than 2.5."
        )

    wk, wk_err = receptions_week_lines(season)
    st.markdown(f"**Posted lines, {season}**")
    if wk_err:
        st.caption(f":material/error: `{wk_err}`")
    elif wk is None or not len(wk):
        st.info(
            f"No receptions lines posted for {season} yet — books post these "
            f"much closer to kickoff than TD props. The weekly capture "
            f"(`make odds WEEK=n`) archives them automatically once they appear."
        )
    else:
        show = wk.assign(
            Player=wk["player_name_raw"], Week=wk["week"], Line=wk["point"],
            Odds=wk["odds"].map(bp.american),
            Book=wk["fair_prob"] * 100, Ours=wk["p_model"] * 100,
        ).sort_values(["Week", "Line"])
        st.dataframe(
            show[["Player", "Week", "Line", "Odds", "Book", "Ours"]],
            hide_index=True,
            column_config={
                "Book": st.column_config.NumberColumn(
                    "Book (fair)", format="%.0f%%",
                    help="The de-vigged two-sided price — on held-out data, the "
                         "better predictor."),
                "Ours": st.column_config.NumberColumn(
                    "We say", format="%.0f%%",
                    help="P(over) from the count model. Blank when the player "
                         "is not in this week's feature rows."),
            },
        )


with st.sidebar:
    st.header("Settings")
    target_type = st.selectbox(
        "Target Type",
        ["first_td", "anytime_td", "receptions"],
        format_func=lambda x: {"first_td": "First TD Scorer",
                               "anytime_td": "Anytime TD Scorer",
                               "receptions": "Receptions (over/under)"}[x],
        key="sidebar_target_type",
    )

    # Receptions is a count market, not a scorer market: graded per
    # (player, line), served by one count model rather than the classifier
    # ensemble, with no joint model, no blend and no version registry yet.
    # Everything below this point in the sidebar — versions, model choice —
    # describes the TD machinery, so this market branches to its own page
    # rather than running that machinery against artifacts it does not have.
    if target_type == "receptions":
        st.caption("Count market — its own model, measured on 21k archived lines.")


    if target_type == "receptions":
        selected_version, selected_model = None, "xgb_count"
    # Which locked version is on screen. Without this the board is a number
    # from an unidentified model: `models/` holds one state, every `make train`
    # overwrites it, and nothing on the page said which one you were looking
    # at. The id resolves to a committed manifest carrying the config, the
    # feature-set hash and the walk-forward metrics behind it.
    # Optional version control, off unless `app.version_selector` is set. See
    # the note beside that flag in config/settings.yaml for why it defaults off.
    _versions = [] if target_type == "receptions" else version_options(target_type)
    if target_type != "receptions":
        selected_version = None
    if _versions:
        _ids = [v["id"] for v in _versions]
        _served_id = next((v["id"] for v in _versions if v["served"]), _ids[0])
        selected_version = st.selectbox(
            "Model version", _ids, index=_ids.index(_served_id),
            key="sidebar_version",
            format_func=lambda i: f"{i}  (serving)" if i == _served_id else i,
            help="Price this week against any locked version without promoting "
                 "it. Anything but the served version is read-only — nothing "
                 "is written and no prediction file is republished.")
        _folded = sorted({d for v in _versions for d in v.get("duplicates", [])})
        if _folded:
            st.caption(
                f"{len(_folded)} version(s) not listed — identical weights to "
                f"one above ({', '.join(_folded)}). They differ only in config "
                "or in recorded metrics, so they would score the same board.")

        if selected_version != _served_id:
            # The model selector has not run yet — it is below, and it takes its
            # default from this version — so the number quoted here is the one
            # this version actually served, not whatever is selected.
            from src.utils.config import config_overlay as _overlay
            from src.utils.config import production_model as _prod
            with _overlay(version_scoring_config(selected_version)):
                _version_model = _prod(target_type)
            _preview = next((v for v in _versions if v["id"] == selected_version), {})
            _recorded = (_preview.get("metrics") or {}).get(_version_model)
            st.info(
                f"Previewing **{selected_version}** — board, model choice and "
                f"settings all come from that version, read-only. It served "
                f"**{_version_model}** on this market. Betting comparisons stay "
                f"hidden while previewing: they are computed from backtest "
                f"frames that exist only for the served model.",
                icon=":material/history:")
            if _recorded:
                st.caption(
                    f"Its recorded walk-forward Top-1 for {_version_model}: "
                    f"{_recorded['top1']:.1%} over {_recorded['games']:,} games.")

    _version = None if target_type == "receptions" else served_version(target_type)
    if target_type == "receptions":
        pass
    elif _version is None:
        st.caption("No locked version — `make lock ID=... NOTE=\"...\"`")
    else:
        _dirty = " · uncommitted tree" if _version.get("dirty") else ""
        st.caption(f"Serving **{_version['id']}**"
                   + (f" · `{_version['git']}`{_dirty}" if _version.get("git") else ""))
        if _version.get("problems"):
            # The served weights are not the ones the record claims. Everything
            # below is then being described by a manifest that does not fit it.
            st.warning("Served artifacts do not match the version record:\n\n"
                       + "\n\n".join(f"- {p}" for p in _version["problems"]),
                       icon=":material/warning:")

    # Build model options: individual models + ensemble (if >1 active)
    model_options = ["xgb_count"] if target_type == "receptions" else list(active_models)
    if target_type != "receptions" and len(active_models) > 1:
        model_options.append("ensemble")
    # Resolved from the market AND from the version being viewed. The two
    # markets are best served by different models, and a single default meant
    # whichever market lost that argument silently ran on a model that measured
    # fourth-best. The version matters for the same reason: two of this
    # project's model changes were config-only, and one of them was which model
    # first TD serves — so previewing a version without resolving its model
    # shows that version's weights running the current model's role, which is a
    # state that never existed.
    from src.utils.config import config_overlay, production_model
    if target_type == "receptions":
        preferred = "xgb_count"
    else:
        with config_overlay(version_scoring_config(selected_version)):
            preferred = production_model(target_type)
    default_model = preferred if preferred in model_options else model_options[0]
    selected_model = st.selectbox(
        "Model", model_options, index=model_options.index(default_model),
        key=f"sidebar_model_{selected_version or 'served'}",
        help="Which fitted model produces the numbers. The default is whichever "
             "one the selected version serves for this market.",
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
        # `cache_data` and `cache_resource` are separate stores, and clearing
        # one leaves the other. The feature matrix moved to `cache_resource` so
        # it is held once rather than copied per caller, which quietly took it
        # out of this button's reach — so "Reload artifacts" stopped reloading
        # the largest artifact of all.
        st.cache_resource.clear()
        st.rerun()

st.title({"first_td": "First TD Scorer", "anytime_td": "Anytime TD Scorer",
          "receptions": "Receptions"}[target_type])

if target_type == "receptions":
    render_receptions_page()
    st.stop()

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
(tab_short, tab_board, tab_results, tab2, tab_bet,
 tab_clusters) = st.tabs(
    ["Shortlist", "Full board", "Weekly results", "Model performance",
     "Betting reality", "Player types"],
    on_change="rerun",
)


# ── Helpers ─────────────────────────────────────────────────────────────────


# (guarded is defined near the top of the file: the receptions
# loaders decorate with it before the sidebar runs, and a decorator
# executes at def time — which is how its old position here produced
# a NameError that took the whole page down at import.)


@st.cache_resource(show_spinner=False)
def load_features(tt: str):
    """The feature matrix for one market — one copy, shared everywhere.

    `cache_resource` rather than `cache_data`, and delegating to the harness's
    loader rather than reading the file again. Both halves matter, because this
    frame is 409 MB per market in memory (160,336 rows x ~355 columns):

      * `cache_data` serialises what it caches and hands back a *copy* on every
        call, so the board, the accuracy strip and the performance tab each got
        their own.
      * `src.evaluation.harness` keeps its own module-level cache, which
        `scored_season` started populating when the app's accuracy numbers moved
        onto the shared scorer. That was a second full copy of both markets —
        about 817 MB of pure duplication — sitting alongside the app's.

    One loader, one object, read-only by convention: every consumer filters,
    and a polars filter returns a new frame rather than mutating this one.

    Returns None when the file is absent, which is the contract every caller
    here already expects; the harness raises instead, because a pipeline that
    cannot find its inputs should stop rather than render an empty page.
    """
    from src.evaluation import harness
    try:
        return harness._features(tt)
    except FileNotFoundError:
        return None


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
def _conversion(tt: str, model_dir=None):
    """Fitted count->probability conversion, or None on an older model dir."""
    from src.models.joint import load_conversion
    return load_conversion((model_dir or get_path("models", tt))
                           / "td_conversion.json")


@st.cache_data(show_spinner=False)
def _team_rate_model(tt: str, model_dir=None):
    """The fitted team touchdown rate, or None on a model dir predating it.

    Takes the directory rather than reading production's, so a previewed
    version's bookmaker comparison uses that version's team rate. Scoring one
    version's weights through another's joint model is a third model neither
    of them is.
    """
    from src.models.joint import load_team_rate
    return load_team_rate((model_dir or get_path("models", tt))
                          / "team_td_rate.json")


@st.cache_data
def _expected_scorers(tt: str) -> float:
    """How many players we expect to score in a game, used to strip the vig.

    One implementation, in `market_parity`, because the de-vig target and the
    comparison that consumes it have to agree — they were separate copies of
    the same fitted prior for as long as this lived in the app.
    """
    from src.evaluation.market_parity import expected_scorers
    return expected_scorers(tt)


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
def load_board(season: int, week: int, tt: str, model: str,
               version: str | None = None):
    """Every priced player for the week, with identical maths for each.

    `version` prices the week against a locked snapshot instead of what is
    served. It is part of the cache key on purpose: without it, switching
    version would hand back the served version's board from cache and nothing
    on screen would move.

    A snapshot is scored read-only — see `selected_model_dir`.
    """
    from src.prediction.bets import board_for_week
    from src.utils.config import config_overlay
    model_dir, persist = selected_model_dir(tt, version)
    # The version's own settings, not today's: a config-only change is still a
    # change to what the board says.
    with config_overlay(version_scoring_config(version)):
        board, msg = board_for_week(season, week, tt, model,
                                    model_dir=model_dir, persist=persist)
    return (board.to_pandas() if board.height else None), msg


@st.cache_data(show_spinner="Reading the teams...", max_entries=16)
def team_outlook_frame(season: int, week: int, version: str | None = None):
    """Team-level numbers for the week, from both markets.

    Scored read-only in both markets regardless of which one the sidebar is
    showing: this panel is a view, and a view should not republish the week's
    predictions as a side effect of being looked at.

    Returns None rather than a placeholder when neither market can be scored —
    an empty panel says "not available", a panel of zeros says something false.
    """
    from src.models.joint import _game_lines, load_team_rate, team_rate
    from src.prediction.predict import predict
    from src.presentation import team_outlook as T
    from src.utils.config import config_overlay

    model_dir, _ = selected_model_dir(tt="anytime_td", version_id=version)
    overlay = version_scoring_config(version)

    preds = {}
    for tt in ("first_td", "anytime_td"):
        md, _ = selected_model_dir(tt, version)
        try:
            with config_overlay(overlay):
                preds[tt] = predict(season, week,
                                    model_name=production_model(tt),
                                    target_type=tt, model_dir=md, persist=False)
        except Exception:                                    # noqa: BLE001
            preds[tt] = None

    # The team rate is the market's view of how much scoring is coming, and it
    # is fitted rather than assumed — the same lambda the joint model uses.
    lam = None
    try:
        model = load_team_rate((model_dir or get_path("models", "anytime_td"))
                               / "team_td_rate.json")
        feats = load_features("anytime_td")
        if model is not None and feats is not None:
            wk = feats.filter((pl.col("season") == season) & (pl.col("week") == week))
            if wk.height:
                lam = team_rate(model, _game_lines(wk))
    except Exception:                                        # noqa: BLE001
        lam = None

    # The bookmaker's own first-TD prices, de-vigged, read from the board so
    # the column beside ours is the number the board publishes rather than a
    # second de-vigging that could drift from it. Priced players only, which is
    # the point: `first_td_share` normalises within the game, so what this
    # measures is how the book splits the game between the two sides.
    book = None
    try:
        _fb, _ = load_board(season, week, "first_td",
                            production_model("first_td"), version)
        if _fb is not None and {"game_id", "team", "market_prob"} <= set(_fb.columns):
            book = pl.from_pandas(_fb[["game_id", "team", "market_prob"]])
    except Exception:                                        # noqa: BLE001
        book = None

    out = T.build(preds.get("first_td"), preds.get("anytime_td"), lam, book)
    if out.is_empty():
        return None
    if preds.get("anytime_td") is not None:
        out = out.join(T.top_scorer_per_team(preds["anytime_td"]),
                       on=["game_id", "team"], how="left")
    labels = None
    for p in preds.values():
        if p is not None and "game_label" in p.columns:
            labels = p.select(["game_id", "game_label"]).unique()
            break
    if labels is not None:
        out = out.join(labels, on="game_id", how="left")
    return out.to_pandas()


@st.cache_data(show_spinner=False)
@st.cache_data(show_spinner=False)
def stale_evaluation(tt: str) -> list[dict]:
    """Numbers on screen that were computed before the model serving them.

    Nothing here is live: the strip reads walkforward.json, the head-to-head
    reads the backtest frames, and each is produced by a command someone has to
    remember to run. The Makefile has warned about this in a comment since those
    targets were written. A comment is not a guard.
    """
    from src.evaluation.freshness import stale_artifacts
    try:
        return stale_artifacts(tt)
    except Exception:                                        # noqa: BLE001
        return []


@st.cache_data(show_spinner=False, max_entries=32)
def scored_season(tt: str, model: str, season: int, version: str | None = None):
    """Per-game outcomes for one season, through the path production serves.

    **The single source for every accuracy number on this page.** It calls
    `src.evaluation.harness.score_fold`, which is the same function the
    walk-forward and every gated experiment use — so a change to the served
    pipeline moves the strip, the Model performance tab and the committed
    walk-forward artifact together, or none of them.

    That was not true before. The Model performance tab ranked on raw model
    output and skipped the joint step entirely, making it a fourth private copy
    of the scoring path alongside the three `src/models/scoring.py` was written
    to replace. On anytime TD 2025 it reported Top-1 50.0% for a board showing
    51.4% — the same model, the same season, two answers, and no way to tell
    from the screen which one described what you were looking at.

    Returns None when the artifacts are not present, rather than a zero.
    """
    from src.evaluation.harness import score_fold

    model_dir, _ = selected_model_dir(tt, version)
    model_dir = model_dir or get_path("models", tt)
    if not (model_dir / "feature_cols.pkl").exists():
        return None
    if model != "ensemble" and not (model_dir / f"{model}.pkl").exists():
        return None
    from src.utils.config import config_overlay
    try:
        with config_overlay(version_scoring_config(version)):
            outcomes, _rows, _players = score_fold(
                tt, model_dir, season, model, list(cfg["models"]["active"]))
    except Exception:                                        # noqa: BLE001
        return None
    return outcomes.to_pandas()


@st.cache_data(show_spinner=False)
def historical_accuracy(tt: str, model: str) -> dict | None:
    """How often our ranking found a real scorer, on the held-out season.

    Derived from `scored_season`, so it cannot drift from the tab below it.
    """
    season = cfg["splits"]["test_season"]
    out = scored_season(tt, model, season)
    if out is None or not len(out):
        return None
    ranked = out["best_rank"].dropna()
    return {
        "season": season,
        "games": int(len(out)),
        "top1": float(out["hit1"].mean()),
        "top3": float(out["hit3"].mean()),
        "top5": float(out["hit5"].mean()),
        "median_rank": float(np.median(ranked)) if len(ranked) else float("nan"),
    }


@st.cache_data(show_spinner=False)
def version_accuracy(tt: str, model: str, version: str | None) -> dict | None:
    """A previewed version's own recorded accuracy, from its manifest.

    `output/<market>/walkforward.json` is one global artifact describing
    whatever was last evaluated, which is the served model. Reading it while
    previewing an older version showed that version's board beside the current
    model's accuracy — two different models on one screen, with nothing saying
    so.

    Every manifest records per-market, per-model walk-forward metrics as
    measured when the version was locked, so the honest number is already
    stored and needs no recomputation.
    """
    if not version:
        return None
    from src.models.versioning import load_manifest, VersionError
    try:
        manifest = load_manifest(version)
    except VersionError:
        return None
    stats = ((manifest.get("metrics") or {}).get(tt) or {}).get(model)
    if not stats:
        return None
    folds = stats.get("folds") or []
    return {
        "games": stats["games"], "pooled": True, "model": model,
        "span": f"{min(folds)}-{max(folds)}" if folds else "",
        "seasons": len(folds),
        "top1": stats["top1"], "top3": stats["top3"], "top5": stats["top5"],
        "top1_se": stats.get("top1_se"),
        "top3_se": stats.get("top3_se"), "top5_se": stats.get("top5_se"),
        "median_rank": None,
        "from_version": version,
    }


@st.cache_data(show_spinner=False)
@st.cache_data(show_spinner=False)
def published_accuracy(tt: str, model: str) -> dict | None:
    """The strip's figures, measured on the column the board actually shows.

    `walkforward.json` scores the model's own ranking. Anytime TD does not
    publish that ranking — it publishes `final`, the model blended with the
    price — so the strip was describing an object the board never displays. The
    page carried 49.6% here and 51.6% in the purpose panel, both labelled
    Top-1, and the larger sample was the one measuring the wrong column.

    Preferred only where the blend MOVES the number. It does on anytime TD, by
    up to 0.289; on first TD `final` and `prob_calibrated` are identical to the
    last decimal, so nothing is gained by narrowing to the price era and the
    walk-forward's extra season is kept.

    The window cannot be widened for a blended market: blending needs a price,
    the odds archive starts in 2023, and `10_backtest.py --season 2022` exits
    with "no weeks had both predictions and prices". That is a limit of the
    data, not a choice.

    Used for BOTH markets, blended or not. First TD's blend leaves the number
    untouched, so the walk-forward would be a legitimate wider window for it —
    but then the strip would sit on 1,131 games while the purpose panel below
    sat on 849, and the page would carry two Top-1 figures again for a
    different reason. One source for every figure beats one market's extra
    season. The walk-forward is still reported in Model performance, where it
    is labelled as the longer history rather than as the headline.
    """
    from src.evaluation.hit_rates import published_topk

    return published_topk(tt, model)


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
    from src.evaluation.harness import walkforward_rows

    rows, _ = walkforward_rows(tt)
    folds = [f for f in rows if f.get("model", model) == model]
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


def headline_accuracy(tt: str, model: str, version: str | None = None):
    """**The** track-record figure. Both places that show one call this.

    The board's header and the Model performance tab used to compute their own,
    from different sources and over different populations: the header pooled
    four walk-forward folds while the tab scored the single held-out season, and
    both were labelled "Top-1". Two numbers under one label read as a
    contradiction rather than as two views, and there was no way to tell from
    the screen which described what you were looking at.

    Order of preference, and each step is a real fallback rather than a
    nicety: the previewed version's own recorded metrics, then the walk-forward
    artifact for what is served, then the single held-out season if the
    walk-forward has never been run.

    **Selecting the served version is not previewing.** The sidebar defaults its
    selector to whatever is being served, so `version` arrives non-None on an
    ordinary page load. Treating that as a preview cost two things at once: the
    strip quoted the manifest's metrics as recorded at lock time rather than the
    live walk-forward — 53.4% against a re-measured 53.5% — and it set
    `from_version`, which the strip reads as "previewing" and uses to hide the
    bookmaker and Closer tiles. Those tiles simply disappeared from the board.
    They are hidden while previewing because backtest frames exist only for the
    served model; when the served model *is* the selection there is nothing to
    hide.

    `tests/test_headline_parity.py` asserts that nothing else renders a
    track-record tile.
    """
    served = served_version(tt)
    if version and served and version == served.get("id"):
        version = None
    return (version_accuracy(tt, model, version)
            or published_accuracy(tt, model)
            or walkforward_accuracy(tt, model)
            or historical_accuracy(tt, model))


def render_headline(acc: dict, target) -> None:
    """Render the track-record tiles. One implementation, so one appearance."""
    target.metric("Games", f"{acc['games']:,}",
                  help=(f"Games across {acc.get('span')}. The model is retrained "
                        f"for each season and never sees the one it is scored on."
                        if acc.get("pooled") else
                        f"Games in the {acc.get('season')} season, which the "
                        f"model never trained on."))
    for key, label, blurb in [
        ("top1", "Top-1", "How often our highest-rated player in a game actually scored."),
        ("top3", "Top-3", "How often at least one of our top 3 scored."),
        ("top5", "Top-5", "How often at least one of our top 5 scored."),
    ]:
        se = acc.get(f"{key}_se")
        target.metric(
            label, f"{acc[key]:.1%}",
            delta=(f"+/- {se:.1%}" if se else None), delta_color="off",
            help=blurb + (
                f" Measured over {acc['games']:,} games; the +/- is one standard "
                f"error, so treat anything inside it as noise." if se else ""),
        )


def render_accuracy_strip(tt: str, model: str, version: str | None = None):
    """Track record, shown on every page — a number you act on should carry its
    accuracy beside it, not a tab away."""
    # Prefer the pooled walk-forward figure over a single season. One season is
    # ~280 games, so a Top-1 read off it carries about 3 points of standard
    # error — wider than most of the differences anyone would act on, and it
    # swings several points year to year for no reason but noise. The
    # walk-forward retrains once per season and never lets a fold see its own
    # test year, so pooling four of them is the same measurement over four
    # times the games.
    acc = headline_accuracy(tt, model, version)
    if acc is None:
        st.caption("Model performance unavailable — run the pipeline first.")
        return

    strip = st.container(horizontal=True)
    render_headline(acc, strip)
    if acc.get("median_rank") is not None:
        strip.metric("Median rank", f"{acc['median_rank']:.0f}",
                     help="In a typical game, the best-ranked player who actually "
                          "scored sat this high on our list. Lower is better.")

    if acc.get("from_version"):
        strip.caption(f"as measured for {acc['from_version']}")

    # These follow the selected version, like the Top-K tiles above. They are
    # not read from backtest frames — `market_headtohead` re-scores the graded
    # odds archive through whichever model directory is selected — so there is
    # no reason for them to sit still while everything beside them moves. They
    # were hidden during a preview, then shown with a "(served)" label, and both
    # were working around this function reading production's directory instead
    # of the one on screen.
    h2h = market_headtohead(tt, model, version)
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
    "TeamFirst": st.column_config.NumberColumn(
        "Team scores first", format="%.0f%%", width="small",
        help="How likely this player's team is to score the game's first "
             "touchdown, whoever scores it. The two teams add to 100%. "
             "Measured over 2,278 walk-forward team-games this is calibrated "
             "from 6% to 94% and beats a coin flip (AUC 0.674). Blank when a "
             "team's roster is missing from this week's data.",
    ),
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
    "ModelOnly": st.column_config.NumberColumn(
        "Model only", format="%.0f%%", width="small",
        help="Our number before it is blended with the bookmaker's. Shown "
             "because it is what the model alone believes — but it is not the "
             "better number for picking. Ranked on 849 backtested games, "
             "blending picks the game's scorer 52.7% of the time against "
             "51.0% for the model alone, because the price carries real "
             "information. It is the right column for judging a *bet*, where "
             "the disagreement with the price is the whole point, and the "
             "wrong one for judging who is likely to score.",
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
             "way above their price. **Veto** — we're below it.\n\n"
             "Veto is not a weaker call, it is the opposite instruction. On "
             "the players we disagree with the book about most our estimate "
             "lands closer to what happened than theirs, but almost all of "
             "that skill is in rating players *down*: the closing line moves "
             "about a point our way when we are lower and does not move at all "
             "when we are higher. These markets only sell the Yes side, so "
             "there is nothing to bet on our best signal — a veto is a player "
             "to leave out, of a single and of every slip.",
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


def combo_columns(decimals: int = 1, graded: dict | None = None) -> dict:
    """The combination table, described in the board's own terms.

    Deliberately the same five quantities the board shows for one player —
    price, our estimate, theirs, the gap, and the money — so a slip can be read
    against a single without translating anything.
    """
    return {
    "Players": st.column_config.TextColumn(
        "Players",
        help="Every one of these has to score for the slip to pay. That is the "
             "whole difference between this table and the board above it."),
    "Game": st.column_config.TextColumn(
        "Game", width="small",
        help="A game named here means every leg comes from it — a same-game "
             "slip. The price beside it is this board's two prices multiplied, "
             "which is what a book pays for legs in *different* games; on one "
             "game they price their own correlation in and quote shorter. "
             "**2 games** and up is the arithmetic a book will actually honour."),
    "Odds": st.column_config.TextColumn(
        "Odds", width="small",
        help="The slip's price: the legs' prices multiplied. +300 means a "
             "\\$100 bet wins \\$300."),
    "Ours": st.column_config.NumberColumn(
        "Our estimate", format=f"%.{decimals}f%%",
        help="Our chance that every leg lands — the board's own estimates "
             "multiplied together. What that multiplication assumes, and what "
             "was measured to justify it, is under the table."),
    "Book": st.column_config.NumberColumn(
        "Bookmaker says", format=f"%.{decimals}f%%",
        help="The same multiplication on the bookmaker's numbers, with their "
             "margin removed from each leg first, so both columns measure the "
             "same thing."),
    "edge_pp": st.column_config.NumberColumn(
        "Difference", format=f"%+.{decimals}f pts",
        help="How far our estimate sits above (+) or below (-) theirs on the "
             "whole slip. It compounds with the legs: so does any error in it, "
             "which is why the biggest numbers in this column are the least "
             "trustworthy rows in the table."),
    "Confidence": st.column_config.TextColumn(
        "Our read", width="small",
        help="The **weakest** read among the legs, on the same cuts the board "
             "above uses. Not the average and not the best of them: a slip "
             "needs every leg, so a **Strong call** beside a player we price "
             "exactly where the book does is a slip resting on the book's own "
             "opinion, and it says so. **Veto** anywhere in a slip is the "
             "whole slip: one leg we rate under its own price is the leg that "
             "ends it."),
    "InRange": st.column_config.TextColumn(
        "Worth backing", width="medium",
        help="What the fitted rule would have marked each leg as **on its "
             "own**, in the order the players are named. Per leg, and never "
             "one tier for the slip: those tiers and the returns behind them "
             "were measured on **single** bets at closing prices, and "
             "\\$131 per \\$100 on a Strong single says nothing about two of "
             "them multiplied. What slips like these actually returned is the "
             "strip above the table.\n\n"
             "An em dash is a leg the rule does not mark. **Fade** is a "
             "warning rather than a bet — the book prices that group far above "
             "what it hits, so it is usually the leg that ends the slip."),
    "EV": st.column_config.NumberColumn(
        "Expected on $100", format="$%+.2f",
        help="What a flat \\$100 on this slip returns **on average** if our "
             "numbers are right — judged on our pre-blend number and paid at "
             "the price to its left, the same pairing the board above uses.\n\n"
             + ("This is a forecast, not a record. What slips like these "
                "actually returned is the strip above the table, replayed over "
                f"{graded['slips']:,} graded slips."
                if graded else
                "Unlike the board's, this column has never been backtested. "
                "Every profitability figure in this app was measured on single "
                "bets at closing prices — `scripts/29_combos.py` grades "
                "this one.")),
    }


#: A slip length as a word, for a caption that reads like a sentence.
LEG_WORDS = ("", "one", "two", "three", "four", "five", "six", "seven",
             "eight", "nine", "ten", "eleven", "twelve")


def combo_grid_range(record: dict | None, key: str) -> str:
    """What the graded replay covers on one axis, as `2\u201312`.

    Read off the file rather than repeated from the sweep's own constants: the
    grid is a measurement that exists or does not, and a caption quoting the
    range it was *meant* to have is how a stale file reads as a fresh one.
    """
    vals = sorted({int(r[key]) for r in (record or {}).get("rows", [])
                   if r.get(key) is not None})
    if not vals:
        return "?"
    return f"{vals[0]}" if len(vals) == 1 else f"{vals[0]}\u2013{vals[-1]}"


@st.cache_data(show_spinner=False)
def _sl_tracked_record(tt: str) -> dict | None:
    """How the rules under observation have done since they were written down."""
    from src.evaluation.tracked_rules import score
    try:
        return score(tt)
    except Exception:                                        # noqa: BLE001
        return None


@st.cache_data(show_spinner=False)
def position_rates(tt: str, model: str) -> dict | None:
    """What each position scores, is charged, and is rated at."""
    from src.evaluation.position_rates import load
    d = load(get_path("output", tt) / "position_rates.json")
    return d if d and d.get("model") in (None, model) else None


@st.cache_data(show_spinner=False)
def shortlist_record(tt: str, model: str) -> dict | None:
    """How the shortlist rule has actually done, or None if never graded.

    Written by scripts/41_shortlist_backtest.py. Absent is a meaningful state
    rather than an error: the tab says so and shows the week's list without a
    verdict, which is worse but honest.
    """
    import json
    p = get_path("output", tt) / "shortlist_backtest.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    return d if d.get("model") in (None, model) else None


@st.cache_data(show_spinner=False)
def shortlist_now(season: int, week: int, tt: str, model: str,
                  version: str | None) -> dict | None:
    """This week's shortlist, from the same board the Full board tab draws."""
    import json

    from src.evaluation.line_shopping import best_vs_consensus
    from src.evaluation.shortlist import shortlist
    from src.prediction.bets import board_for_week

    clv_path = get_path("output", tt) / "clv.json"
    if not clv_path.exists():
        return None
    clv = json.loads(clv_path.read_text())
    if not clv.get("by_edge"):
        return None
    econ_path = get_path("output", tt) / "rank_economics.json"
    econ = json.loads(econ_path.read_text()) if econ_path.exists() else None

    board, _ = board_for_week(season, week, tt, model, persist=False)
    if board is None or board.height == 0:
        return None
    try:
        shopped = best_vs_consensus(season, week, tt)
    except Exception:                                        # noqa: BLE001
        shopped = None
    return shortlist(board, target_type=tt, clv=clv, econ=econ, shopped=shopped)


def shortlist_columns() -> dict:
    """The shortlist table, in the same terms as the board it comes from."""
    return {
        "player": st.column_config.TextColumn("Player"),
        "game": st.column_config.TextColumn("Game", width="small"),
        "Ours": st.column_config.NumberColumn(
            "Our estimate", format="%.1f%%",
            help="Our pre-blend number — the one every money figure in this "
                 "app is measured on."),
        "Book": st.column_config.NumberColumn(
            "Bookmaker says", format="%.1f%%",
            help="Their price with the margin removed, so both columns measure "
                 "the same thing."),
        "edge_pp": st.column_config.NumberColumn(
            "Difference", format="%+.1f pts",
            help="How far above their price we sit. Everything on this list "
                 "clears the floor where closing-line value has not moved "
                 "against us."),
        "Price": st.column_config.TextColumn("Price", width="small"),
        "Best": st.column_config.TextColumn(
            "Best posted", width="small",
            help="The best price any archived book posted this week."),
        "best_book": st.column_config.TextColumn("At", width="small"),
        "shopped_pp": st.column_config.NumberColumn(
            "Shop", format="%+.2f pts",
            help="What the best price is worth against the consensus, in "
                 "points of implied probability. The only edge here that does "
                 "not need the model to be right."),
        "band": st.column_config.TextColumn("Price band", width="small"),
        "band_roi": st.column_config.NumberColumn(
            "Band returned", format="%+.0f%%",
            help="What every bet at this price returned across the whole "
                 "population, vetoed players included. Context for the row, "
                 "never the reason it is on the list — see the caption."),
    }


@st.cache_data(show_spinner=False)
def combo_record(tt: str, model: str) -> dict | None:
    """How the combinations table has actually done, or None if never graded.

    Written by scripts/29_combos.py. Absent is a meaningful state rather than
    an error: until it has run, the section says in as many words that nothing
    in it has been backtested, which is true and is what the reader needs.
    """
    from src.evaluation.combo_backtest import load
    return load(get_path("output", tt) / "combo_backtest.json")


@st.cache_data(show_spinner=False)
def leg_correlation(tt: str) -> dict | None:
    """Do teammates' outcomes actually move together? Re-measured, not assumed.

    Multiplying legs is the one modelling assumption the combination table
    makes, so the table quotes what this currently says rather than a number
    written into the page. `fit_correlation` reads the backtest residuals, so a
    retrain that breaks the assumption changes the sentence under the table.
    """
    try:
        from src.prediction.portfolio import fit_correlation
        return fit_correlation(tt)
    except Exception:                                        # noqa: BLE001
        return None


@st.cache_data(show_spinner=False)
def market_headtohead(tt: str, model: str,
                      version: str | None = None) -> dict | None:
    """Us vs the sportsbook on identical players, pooled over every priced season.

    The measurement itself is `src.evaluation.market_parity.compare` — it left
    this file when the exported dashboard needed the same three tiles, because
    the alternative was a second copy of the de-vigging and the joint path and
    every previous copy of either here has drifted. What stays is what is
    genuinely app-shaped: caching, and following the selected version so these
    tiles do not sit still while the Top-K figures beside them move.
    """
    from src.evaluation.market_parity import compare
    version_dir, _ = selected_model_dir(tt, version)
    try:
        return compare(tt, model, load_features(tt),
                       model_dir=version_dir or get_path("models", tt),
                       active_models=active_models)
    except Exception:                                        # noqa: BLE001
        return None


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


@st.cache_data(show_spinner=False)
def measured_on(tt: str, model: str | None) -> str | None:
    """Which model the hit-rate panels actually describe.

    The loaders fall back to production's backtest frames when the selected
    model has none of its own, which is the normal case — only the served
    model is routinely backtested. Falling back is right; doing it silently is
    not, because the panel would then report one model's accuracy under
    another's name. Returns the production model when a fallback happened, and
    None when the numbers really are the selected model's.
    """
    from src.evaluation.hit_rates import _load_backtests
    from src.utils.config import production_model
    if model is None:
        return None
    if _load_backtests(tt, model) is not None:
        return None
    prod = production_model(tt)
    return prod if prod != model else None


@st.cache_data(show_spinner=False)
@guarded
def top_pick_outcomes(tt: str, model: str | None = None):
    """One row per backtested game: the top pick's confidence and what it did.

    Cached whole so the threshold control can be answered without touching disk
    on every drag — the frame is ~850 rows, and the measurement at any cut is a
    filter and a bootstrap over it.
    """
    from src.evaluation.hit_rates import top_pick_frame
    d = top_pick_frame(tt, model) or top_pick_frame(tt)
    return d.to_pandas() if d is not None and d.height else None


@st.cache_data(show_spinner=False)
@guarded
def topk_against_market(tt: str, model: str | None = None):
    """Our Top-K beside the book's own, on identical rows."""
    from src.evaluation.hit_rates import topk_vs_market
    return topk_vs_market(tt, model) or topk_vs_market(tt)


@st.cache_data(show_spinner=False)
@guarded
def any_player_outcomes(tt: str, model: str | None = None):
    """Every priced candidate and what it did — the population of the list."""
    from src.evaluation.hit_rates import any_player_frame
    d = any_player_frame(tt, model) or any_player_frame(tt)
    return d.to_pandas() if d is not None and d.height else None


@st.cache_data(show_spinner=False)
@guarded
def hit_rate_bands(tt: str, model: str | None = None) -> dict | None:
    """Measured hit rate by the confidence a pick carries.

    Answers "how often is this right", which is a different question from
    `rank_economics`' "does this pay". On anytime TD the two currently disagree:
    the top pick is right 49.8% of the time against a 16.2% base rate, while
    backing the top three loses 5.7%. A board read as a shortlist wants the
    first number; a bet card wants the second.

    `@guarded` rather than a bare try/except, and the import sits inside it. The
    first version of this function put the import above the try, so a container
    built before `src/evaluation/hit_rates.py` existed did not lose the panel —
    it took the whole page down with a ModuleNotFoundError. That is the exact
    failure `guarded` was written for: report it beside the section it belongs
    to, rather than swallowing it or crashing the app.
    """
    from src.evaluation.hit_rates import top_pick_bands
    # Model-specific frames where they exist, production's otherwise. Falling
    # back rather than blanking, because a model with no frames of its own is
    # the normal case — only the served one is routinely backtested.
    return top_pick_bands(tt, model) or top_pick_bands(tt)


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


@st.cache_data(show_spinner=False, max_entries=16)
@guarded
def unpriced_board(season: int, week: int, tt: str, model: str,
                   version: str | None = None):
    """Players the model rates that no bookmaker has quoted."""
    from src.prediction.bets import unpriced_for_week
    from src.utils.config import config_overlay
    model_dir, persist = selected_model_dir(tt, version)
    with config_overlay(version_scoring_config(version)):
        d = unpriced_for_week(season, week, tt, model,
                              model_dir=model_dir, persist=persist)
    return d.to_pandas() if d is not None and d.height else None


def render_unpriced(season, week, tt: str, model: str, version: str | None,
                    query: str = ""):
    """The rest of the slate — rated, unpriced, and kept apart from the board.

    Separate table rather than extra rows, because these numbers are not on the
    same footing as the board's. Two differences, both stated on screen:

      * **Unblended.** With no price to blend toward, `blend` leaves the raw
        model probability. Every priced row on the board has been pulled toward
        the bookmaker, which is what makes it better calibrated — so the two
        columns are not comparable at the same value.
      * **Outside every measured claim.** `#`, Top-1/3/5, "Typical at #" and the
        hit-rate bands are all measured on priced players. Extending them to a
        population no book has quoted would be an extrapolation, so this table
        deliberately shows none of them.

    Three weeks before a season opens this is most of the card — four games of
    sixteen were priced when it was written — so the alternative is a board that
    silently answers a narrower question than the one being asked of it.
    """
    d, err = unpriced_board(season, week, tt, model, version)
    if err:
        st.caption(f":material/error: Unpriced players unavailable — `{err}`")
        return
    if d is None or d.empty:
        return

    d = d.copy()
    if query:
        d = d[d["player_name"].str.contains(query, case=False, na=False)]
    if d.empty:
        return

    games = d["game_label"].nunique()
    with st.expander(
        f"{len(d)} rated players across {games} unpriced "
        f"{'game' if games == 1 else 'games'}",
        icon=":material/help_center:",
    ):
        st.warning(
            "**No bookmaker has posted a price for these players yet**, so these "
            "estimates are *unblended* — the model's own view, with nothing pulled "
            "toward a market number. Every figure on the board above is blended, "
            "which makes it better calibrated, so do not compare the two columns "
            "at face value. The accuracy figures above are measured on priced "
            "players and do not describe this table.",
            icon=":material/info:",
        )
        show = d.assign(
            Player=d["player_name"],
            Game=d["game_label"],
            Ours=d["probability"] * 100,
            InGame=d["unpriced_rank"],
        ).sort_values("probability", ascending=False)
        st.dataframe(
            show[["Player", "team", "Game", "InGame", "Ours"]], hide_index=True,
            column_config={
                "team": st.column_config.TextColumn("Team", width="small"),
                "InGame": st.column_config.NumberColumn(
                    "In game", width="small",
                    help="Rank within this game's unpriced players only. It is "
                         "deliberately not the board's #, which is measured on "
                         "priced players.",
                ),
                "Ours": st.column_config.NumberColumn(
                    "Our estimate (unblended)", format="%.0f%%",
                    help="The model's raw probability. Not blended with a market "
                         "price, because there is not one.",
                ),
            },
        )


def render_purpose(tt: str, model: str, version: str | None = None):
    """What this board is for, stated before anything is read off it.

    The page grew up as a bet card — edge, EV, Kelly, "worth backing" — and
    kept that shape after the evidence stopped supporting it. On 2026-08-18 two
    existence leaks were closed and the headline profitability figure inverted
    from +5.9% to -9.6%, while the ranking accuracy survived almost intact.
    Those two facts point at one conclusion: this is a good shortlist and not a
    profitable bet card, in markets that are priced efficiently.

    Saying so at the top is not modesty. A reader who takes the board for a bet
    card will size positions on a number that has been measured as negative,
    and every column further down is easier to read correctly once the purpose
    is fixed.

    Everything here is read from measurements rather than written, so it cannot
    drift away from what the artifacts say the way the prose around the
    longshot panel did.
    """
    acc = headline_accuracy(tt, model, version)
    s, _ = hit_rate_bands(tt, model)
    econ = rank_economics(tt, model)
    fell_back = measured_on(tt, model)
    if not s:
        return

    base = s.get("base_rate")
    overall = s.get("overall_hit_rate")
    best = None
    for c in s.get("cuts", []):
        if c["hit_rate"] >= 0.60 and (best is None or c["threshold"] < best["threshold"]):
            best = c

    with st.container(border=True):
        st.markdown(
            f"#### Who scores, not what to bet\n\n"
            f"This board ranks players by how likely they are to score. "
            f"Its top pick is right **{overall:.1%}** of the time against "
            f"**{base:.1%}** for a candidate drawn at random — about "
            f"**{overall / max(base, 1e-9):.1f}x** the field"
            + (f", over {s['games']:,} backtested games"
               + (f" ({s['span']})" if s.get("span") else "") + "."
               if s.get("games") else ".")
            + (f" Restricted to picks it rates above **{best['threshold']:.2f}** "
               f"it reaches **{best['hit_rate']:.1%}** "
               f"[{best['lo_ci']:.1%}, {best['hi_ci']:.1%}], on "
               f"**{best['share_of_games']:.0%}** of games."
               if best else "")
        )
        # The comparison that decides whether any of this is worth reading.
        # The strip above reports Top-K against an implied baseline of nothing,
        # which reads as "3.2x better than chance" — and nobody picks by
        # chance. Reported as its own block, on its own population, because the
        # strip's figures cover every candidate over 1,131 games and these
        # cover priced players over 849: the two are not subtractable and a
        # shared row would invite exactly that.
        cmp_, cmp_err = topk_against_market(tt, model)
        if cmp_err:
            st.caption(f":material/error: market comparison unavailable — `{cmp_err}`")
        elif cmp_:
            rows = []
            for k in (1, 3, 5):
                o, m = cmp_["ours"].get(k), cmp_["market"].get(k)
                if o is None or m is None:
                    continue
                rows.append({"": f"Top-{k}", "Us": o * 100, "The book": m * 100,
                             "Difference": (o - m) * 100})
            if rows:
                st.markdown(
                    f"**Against the bookmaker, same "
                    f"{cmp_['games']:,} games"
                    + (f" ({cmp_['span']})" if cmp_.get("span") else "")
                    + ".** The honest yardstick — a price, not a coin flip."
                )
                st.caption(
                    f":material/info: **A different window from the accuracy "
                    f"strip above.** That pools every retrained fold; only the "
                    f"seasons with archived prices can be set against a book, "
                    f"so these {cmp_['games']:,} games are a subset. The two "
                    f"Top-1 figures on this page are not the same measurement "
                    f"and are not subtractable.")
                st.dataframe(
                    pd.DataFrame(rows), hide_index=True,
                    column_config={
                        "Us": st.column_config.NumberColumn(format="%.1f%%"),
                        "The book": st.column_config.NumberColumn(format="%.1f%%"),
                        "Difference": st.column_config.NumberColumn(
                            format="%+.1f pp",
                            help="Positive means our ranking put a scorer in the "
                                 "top K more often than the book's price did."),
                    },
                )
                d1 = rows[0]["Difference"] if rows[0][""] == "Top-1" else None
                if d1 is not None and d1 < 0:
                    st.caption(
                        f"We are **behind the book on Top-1** by {abs(d1):.1f} "
                        f"points and ahead on Top-3 and Top-5. Read that as it "
                        f"is: this model brackets the scorer better than the "
                        f"price does and isolates him worse. If you want one "
                        f"name, the book's favourite is still the better single "
                        f"guess; the board earns its keep on the shortlist."
                    )

        if fell_back:
            st.caption(
                f":material/info: These rates are measured on **{fell_back}**, the "
                f"production model — **{model}** has no backtest frames of its own. "
                f"Run `make evaluate` after selecting it to measure it directly."
            )
        if econ and econ.get("headline"):
            h = econ["headline"]
            neg = h.get("roi") is not None and h["roi"] < 0
            st.markdown(
                f"**It is not a bet card.** Backing its top {h.get('top_n', 3)} "
                f"at the prices actually posted returned **{h['roi']:+.1f}%** "
                f"[{h['lo']:+.1f}, {h['hi']:+.1f}] across {econ.get('games', 0):,} "
                f"backtested games"
                + (" — the market is priced ahead of it. Use the ranking to decide "
                   "who is likely to score; do not size a position on the edge "
                   "columns."
                   if neg else
                   ". The betting columns carry their own measurement below.")
            )


def render_selectivity(tt: str, board=None, model: str | None = None):
    """How often the top pick is right, and how selective you must be.

    The board's own probabilities are a claim. This is the outcome: measured on
    backtested seasons, at each level of confidence, with a game-clustered
    interval because two picks in one game share a defence and a final score.

    It is deliberately framed as coverage against accuracy rather than as a
    single headline. Being right 60% of the time on a quarter of games and 50%
    on all of them are both true statements about the same model, and which one
    matters depends on whether you intend to act every week.
    """
    s, err = hit_rate_bands(tt, model)
    if err:
        st.caption(f":material/error: Hit-rate summary unavailable — `{err}`")
        return
    if not s or not s.get("cuts"):
        return

    # The strongest picks, before anything else. "McCaffrey against a
    # bottom-five run defence" weeks are the reason a reader opens this page,
    # and they were living three widgets deep. The bar is the highest measured
    # cut (0.55 -> 64-66% hit rate); when nothing clears it the strip says so
    # against the 0.50 bar instead of showing an empty box.
    if board is not None and len(board):
        frame0, _ = top_pick_outcomes(tt, model)
        for bar in (0.55, 0.50):
            strongest = (board[board["probability"] >= bar]
                         .sort_values("probability", ascending=False))
            if not strongest.empty:
                import polars as _pl0
                from src.evaluation.hit_rates import rate_at as _rate_at
                r0 = (_rate_at(_pl0.from_pandas(frame0), bar)
                      if frame0 is not None and len(frame0) else None)
                names = "  ·  ".join(
                    f"**{r.player_name}** ({r.game_label}) {r.probability:.0%}"
                    for r in strongest.head(6).itertuples())
                rate_txt = (f" — players rated this highly have scored "
                            f"**{r0['hit_rate']:.0%}** of the time"
                            if r0 and not r0.get("too_few") else "")
                st.success(f"**Strongest this week (above {bar:.2f})**: {names}"
                           f"{rate_txt}.", icon=":material/star:")
                break
        else:
            st.caption("No player on this week's priced board clears 0.50 — "
                       "the bar working, not a gap.")

    with st.expander("How often is the top pick right?", icon=":material/target:",
                     expanded=True):
        best = None
        for cut in s["cuts"]:
            if cut["hit_rate"] >= 0.60 and (best is None
                                            or cut["threshold"] < best["threshold"]):
                best = cut
        st.markdown(
            f"Across **{s['games']:,}** backtested games the top pick scores "
            f"**{s['overall_hit_rate']:.1%}** of the time, against a base rate of "
            f"**{s['base_rate']:.1%}** for a candidate picked at random — a "
            f"**{s['overall_hit_rate'] / max(s['base_rate'], 1e-9):.1f}x** lift. "
            + (f"Restricting to picks above **{best['threshold']:.2f}** reaches "
               f"**{best['hit_rate']:.1%}**, on **{best['share_of_games']:.0%}** of games."
               if best else
               "No confidence level reaches 60% as a point estimate — the most "
               "selective cut below is as far as this market goes.")
        )
        # Live threshold. It reports rather than filters: the board keeps every
        # row, and this answers "if I only acted on picks above X, how often
        # would I have been right, and how often would I have acted at all".
        # Those two move in opposite directions, which is the whole trade and
        # the reason a single headline number cannot express it.
        frame, frame_err = top_pick_outcomes(tt, model)
        if frame_err:
            st.caption(f":material/error: threshold detail unavailable — `{frame_err}`")
        elif frame is not None and len(frame):
            import polars as _pl

            from src.evaluation.hit_rates import rate_at
            cut = st.slider(
                "If I only acted on picks above", min_value=0.0, max_value=0.70,
                value=0.50, step=0.01, format="%.2f", key=f"hitrate_cut_{tt}",
            )
            r = rate_at(_pl.from_pandas(frame), cut)
            c1, c2, c3 = st.columns(3)
            if r and r.get("too_few"):
                c1.metric("Hit rate", "—")
                c2.metric("Games it applies to", f"{r['games']}")
                c3.metric("Share of games", f"{r['share_of_games']:.0%}")
                st.caption(
                    f"Only {r['games']} backtested games sit above {cut:.2f} — too "
                    f"few to measure. The rate would be a description of those "
                    f"games rather than an estimate of anything."
                )
            elif r:
                base = s["overall_hit_rate"]
                c1.metric("Hit rate", f"{r['hit_rate']:.1%}",
                          delta=f"{(r['hit_rate'] - base) * 100:+.1f} pts vs every pick")
                c2.metric("Games it applies to", f"{r['games']:,}")
                c3.metric("Share of games", f"{r['share_of_games']:.0%}",
                          delta=f"{(r['share_of_games'] - 1) * 100:+.0f}% coverage",
                          delta_color="inverse")
                st.caption(
                    f"90% interval {r['lo_ci']:.1%}–{r['hi_ci']:.1%}, resampling "
                    f"whole games. Raising the bar makes picks better and rarer "
                    f"at once."
                )

            # This week's players that clear the same bar.
            #
            # Every qualifying player, not just each game's best — and the rate
            # beside it is measured on that same population rather than
            # borrowed from the top-pick table above. The two are close and
            # their ordering is not fixed: at 0.50 the top pick hits 62.7%
            # against 60.5% for any player, and at 0.55 it reverses, 64.7%
            # against 66.0%. Quoting one number over the other list would be
            # wrong by a couple of points in an unpredictable direction.
            anyfr, any_err = any_player_outcomes(tt, model)
            ar = (rate_at(_pl.from_pandas(anyfr), cut)
                  if anyfr is not None and len(anyfr) else None)

            if board is not None and len(board):
                qual = board[board["probability"] >= cut].sort_values(
                    "probability", ascending=False)
                head = f"**Every player above {cut:.2f} this week**"
                if ar and not ar.get("too_few"):
                    head += (f" — players rated this highly have scored "
                             f"**{ar['hit_rate']:.1%}** of the time "
                             f"[{ar['lo_ci']:.1%}, {ar['hi_ci']:.1%}], "
                             f"on {ar['games']:,} backtested picks")
                st.markdown(head)
                if qual.empty:
                    st.caption(
                        f"Nobody on this week's board is rated above {cut:.2f}. "
                        f"An empty list is the bar working, not a missing number."
                    )
                else:
                    q = qual.assign(
                        Player=qual["player_name"], Game=qual["game_label"],
                        Ours=qual["probability"] * 100,
                        Odds=(qual["odds"].map(bp.american)
                              if "odds" in qual.columns else ""),
                        Best=(qual["best_odds"].map(
                                  lambda o: bp.american(o) if pd.notna(o) else "")
                              if "best_odds" in qual.columns else ""),
                    )
                    cols = ["Player", "team", "Game", "Odds"]
                    if "best_odds" in qual.columns and qual["best_odds"].notna().any():
                        cols += ["Best"]
                    cols += ["Ours"]
                    st.dataframe(
                        q[cols], hide_index=True,
                        column_config={
                            "team": st.column_config.TextColumn("Team", width="small"),
                            "Odds": st.column_config.TextColumn("Odds", width="small"),
                            "Best": st.column_config.TextColumn(
                                "Best price", width="small",
                                help="Longest price across the books we archive. "
                                     "The consensus is the one number here nobody "
                                     "can actually bet."),
                            "Ours": st.column_config.NumberColumn(
                                "Our estimate", format="%.0f%%"),
                        },
                    )
                    ngames = qual["game_label"].nunique()
                    st.caption(
                        f"{len(qual)} players across {ngames} "
                        f"{'game' if ngames == 1 else 'games'} — every qualifying "
                        f"player, measured by the any-player rate above."
                    )

        table = pd.DataFrame([
            {"Take picks above": f"{c['threshold']:.2f}",
             "Games": c["games"],
             "Share of games": c["share_of_games"] * 100,
             "Hit rate": c["hit_rate"] * 100,
             "Range": f"{c['lo_ci']:.1%} - {c['hi_ci']:.1%}"}
            for c in s["cuts"]
        ])
        st.dataframe(
            table, hide_index=True,
            column_config={
                "Share of games": st.column_config.NumberColumn(format="%.0f%%"),
                "Hit rate": st.column_config.NumberColumn(format="%.1f%%"),
                "Range": st.column_config.TextColumn(
                    "Range", help="90% interval, resampling whole games rather "
                                  "than individual picks — two picks in one game "
                                  "are not independent evidence."),
            },
        )
        st.caption(
            "Measured on seasons the model never trained on. Being more "
            "selective means acting on fewer weeks, not on better players: the "
            "picks below the cut are still shown, they just carry a rate that "
            "has been measured rather than assumed."
        )


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

    # Pre-blend estimate beside the published one. Only where blending actually
    # moves the number: first TD is not blended, so there the two are identical
    # and a second column would imply a distinction this market does not have —
    # the same rule the Bet #/Bet edge pair follows.
    if bp.blend_moves_the_number(frame):
        show = show.assign(ModelOnly=frame["prob_model"] * 100)
        cols = cols[:7] + ["ModelOnly"] + cols[7:]

    # The team's own chance of striking first, beside the player's. First TD
    # only — see week_board. Placed immediately after Team, so it reads as a
    # property of the team rather than another estimate of the player.
    if "first_td_pct" in frame.columns and frame["first_td_pct"].notna().any():
        show = show.assign(TeamFirst=frame["first_td_pct"] * 100)
        cols = cols[:2] + ["TeamFirst"] + cols[2:]

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


def week_board(season, week, tt: str, model: str,
               version: str | None = None):
    """(board, we're-higher, we're-lower, problems) for one season/week.

    Takes its inputs rather than reading the sidebar out of module scope: the
    globals made this function untestable and pinned every tab to one file.
    `problems` carries anything that failed to load, so a missing column can be
    explained on the page instead of just not appearing.
    """
    if week is None:
        st.info("Select a season and week in the sidebar.")
        return None, None, None, []
    board, msg = load_board(season, week, tt, model, version)
    if board is None:
        st.info(msg or "Nothing to show for this week.")
        st.caption("Players appear here once a bookmaker has posted a price for them.")
        return None, None, None, []
    board = board.copy()
    board["game_rank"] = (
        board.groupby("game_label")["probability"]
        .rank(ascending=False, method="first").astype(int)
    )

    # First TD only: how likely this player's *team* is to score the game's
    # first touchdown. It is the context the player number sits in — a 9%
    # player on a team with a 60% chance of striking first is the focal point of
    # an offence expected to score, and a 9% player on a 30% team is the
    # runaway pick of one that is not. Same number, different bet.
    #
    # Exact rather than approximate on this market: `predict` normalises
    # first-TD probabilities to sum to one within the game, so a team's number
    # is simply its players' summed probability. Anytime TD has no equivalent —
    # there the answer is ~92% for everyone.
    if tt == "first_td":
        teams = team_outlook_frame(season, week, version)
        if teams is not None and "first_td_pct" in getattr(teams, "columns", []):
            board = board.merge(
                teams[["game_id", "team", "first_td_pct"]],
                on=["game_id", "team"], how="left")
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


# ── Shortlist ───────────────────────────────────────────────────────────────
# The board says who scores and the bet card says where we disagree with a
# price. This is the only tab that asks whether either is worth money, and it
# leads with the answer rather than with the list — a card of two plays every
# week trains a reader to take two plays every week.
if tab_short.open:
    with tab_short:
        st.subheader("What survives every measurement")
        _sl_rec = shortlist_record(target_type, selected_model)
        if _sl_rec and _sl_rec.get("arms"):
            _arms = {a["arm"]: a for a in _sl_rec["arms"]}
            _base = (_arms.get("all priced") or {}).get("pooled")
            # Every arm is negative, so the level is not the news — the news is
            # what each filter is worth against the arm above it, and how far
            # the best of them still is from paying for itself. Four red
            # numbers in a row said neither.
            if _base:
                _best = (_arms.get("we rate higher") or {}).get("pooled") or _base
                st.markdown(
                    f"**Backing every priced player returned "
                    f"{_base['roi']:+.1f}% a bet. Taking only the ones we rate "
                    f"above the price returns {_best['roi']:+.1f}% — the "
                    f"model's ordering is worth "
                    f"{_best['roi'] - _base['roi']:.1f} points, and still "
                    f"{_best['breakeven_gap_pp']:.1f} points of implied "
                    f"probability short of breaking even.**")
            _strip2 = st.container(horizontal=True)
            for _name, _label, _help in (
                ("all priced", "Every priced bet",
                 "Flat stakes on every player a book priced, at the archived "
                 "closing price. The market's own answer, and the thing any "
                 "selection has to beat."),
                ("we rate higher", "Only where we're higher",
                 "The same weeks, staking only the players we rate above the "
                 "de-vigged price. This is the veto doing its work: it is the "
                 "one filter here that measurably improves the return."),
                ("shortlist", "This tab's rule",
                 "The same, plus the closing-line-value floor fitted on "
                 "*earlier seasons only*. Where it matches the row above, the "
                 "honestly-fitted floor did not exclude anything — which is a "
                 "result about the rule, not a bug."),
                ("shortlist (hindsight)", "With hindsight",
                 "The same rule with its floor fitted on every season, "
                 "including the ones being graded. Nobody could have followed "
                 "it. It is the ceiling: what the screen would look like if "
                 "you had known the answer first."),
            ):
                _a = _arms.get(_name)
                _p = (_a or {}).get("pooled")
                if _p is None:
                    _strip2.metric(_label, "stood down",
                                   delta="bet nothing", delta_color="off",
                                   help=_help + "\n\nNo week cleared it.")
                    continue
                _delta = (None if _base is None or _name == "all priced" else
                          f"{_p['roi'] - _base['roi']:+.1f} pts vs backing "
                          f"everything")
                _strip2.metric(
                    _label, f"{_p['roi']:+.1f}%",
                    delta=_delta or f"{_p['lo']:+.0f} to {_p['hi']:+.0f}",
                    delta_color="normal" if _delta else "off",
                    help=f"{_help}\n\n{_p['n']:,} bets, hit "
                         f"{_p['hit_pct']:.1f}% where the price needed "
                         f"{_p['breakeven_pct']:.1f}% — short by "
                         f"{_p['breakeven_gap_pp']:.1f} points of implied "
                         f"probability.")
            st.caption(
                f":material/warning: Replayed over {', '.join(str(x) for x in _sl_rec['seasons'])}"
                + (f" ({', '.join(str(x) for x in _sl_rec['skipped_seasons'])} "
                   f"has no earlier season to fit a floor from, so it cannot be "
                   f"screened)" if _sl_rec.get("skipped_seasons") else "")
                + f", flat stakes at the {_sl_rec['priced_at']}. Every arm is "
                f"negative. The list below is what the rule offers this week, "
                f"not a claim that taking it makes money — and the gap between "
                f"the last two figures is how much of this screen's apparent "
                f"value is knowing the answer first.")
        else:
            st.info("This rule has not been graded — run `python "
                    f"scripts/41_shortlist_backtest.py --target {target_type}`.",
                    icon=":material/info:")

        # Reference, not a verdict: the numbers a reader keeps deriving by eye
        # while reading any of these tables. Placed here rather than buried in
        # Model performance because "is 12% good?" is a question you have while
        # looking at a board, not while auditing one.
        _pos = position_rates(target_type, selected_model)
        if _pos:
            # A plain section rather than an expander: `simplify` drops
            # expanders from the published page, and this is four rows of
            # reference that the published page wants most — its reader has no
            # sidebar and no way to ask what a normal percentage looks like.
            with st.container():
                st.subheader("What each position typically does")
                _pf = pd.DataFrame(_pos["rows"])
                _pf["Price"] = _pf["median_odds"].map(bp.american)
                st.dataframe(
                    _pf[["position", "priced_weeks", "scored_pct", "book_pct",
                         "ours_pct", "Price", "all_rated_pct"]],
                    hide_index=True, use_container_width=True,
                    column_config={
                        "position": st.column_config.TextColumn("Position", width="small"),
                        "priced_weeks": st.column_config.NumberColumn(
                            "Player-weeks", format="%d",
                            help="Priced player-weeks behind the row."),
                        "scored_pct": st.column_config.NumberColumn(
                            "Scored", format="%.1f%%",
                            help="How often a priced player at this position "
                                 "actually scored."),
                        "book_pct": st.column_config.NumberColumn(
                            "Book says", format="%.1f%%",
                            help="The de-vigged price they carried, averaged. "
                                 "Beside the realised rate this is the "
                                 "market's own accuracy, position by position."),
                        "ours_pct": st.column_config.NumberColumn(
                            "We say", format="%.1f%%",
                            help="Our own average estimate for the same rows. "
                                 "A model two points hot on one position and "
                                 "two cold on another looks perfect in "
                                 "aggregate and is wrong on every row."),
                        "Price": st.column_config.TextColumn(
                            "Median price", width="small"),
                        "all_rated_pct": st.column_config.NumberColumn(
                            "All rated", format="%.1f%%",
                            help="The same rate over everyone the model rates, "
                                 "priced or not. Far lower, because it counts "
                                 "deep reserves nobody has ever posted a price "
                                 "for — context, not a bet."),
                    })
                st.caption(
                    f":material/insights: Priced players, {_pos['span']}. "
                    f"Read **Scored** against **Book says** for what the "
                    f"market gets right, and against **We say** for what we "
                    f"do — the gap between the last two is where a position "
                    f"the model misreads would show up.")

        _fade = (_sl_rec or {}).get("fade")
        _sl = shortlist_now(season, week, target_type, selected_model,
                            selected_version)
        if _sl is None:
            st.warning("No priced board for this week yet, or no closing-line "
                       "value measured — the shortlist needs both.",
                       icon=":material/warning:")
        else:
            for _d in _sl["dropped"]:
                st.caption(f":material/filter_alt: −{_d['dropped']} {_d['filter']} "
                           f"→ {_d['left']} left")
            if not _sl["rows"]:
                st.success(
                    f"**{_sl['note']}** That is the answer rather than a gap: "
                    f"every filter above is a measurement, and this week they "
                    f"leave nothing.", icon=":material/check:")
            else:
                _slf = pd.DataFrame(_sl["rows"])
                _slf["Ours"] = _slf["ours"] * 100
                _slf["Book"] = _slf["book"] * 100
                _slf["Price"] = _slf["odds"].map(bp.american)
                _slf["Best"] = [bp.american(o) if o else "—"
                                for o in _slf["best_odds"]]
                st.dataframe(
                    _slf[["player", "game", "Ours", "Book", "edge_pp",
                          "Price", "Best", "best_book", "shopped_pp", "band",
                          "band_roi"]],
                    hide_index=True, use_container_width=True,
                    column_config=shortlist_columns())
                st.caption(
                    ":material/info: **Best** is the best price any archived "
                    "book posted, and **Shop** is what that is worth in points "
                    "of implied probability — the one edge here that does not "
                    "need the model to be right. **Band** is what every bet at "
                    "that price returned across the whole population, vetoed "
                    "players included: context for reading a row, never the "
                    "reason it is on the list.")

            # ── Under observation ────────────────────────────────────────
            # Kept out of the list above and labelled on every line: this is a
            # rule that looked good in a slice of three seasons and has one
            # good season and one bad one out of sample. Writing down what it
            # says each week is the only way it can ever be settled — and a
            # rule that is re-tuned instead can never fail, because every
            # failure is absorbed into the next tuning.
            for _rule in (_sl.get("tracked") or []):
                st.subheader(f"Tracked — {_rule['name']}")
                st.warning(
                    f"**{_rule['status'].capitalize()}.** {_rule['found']}. "
                    f"The control: {_rule['control']}. Out of sample: "
                    f"{_rule['out_of_sample']}",
                    icon=":material/science:")
                _tk = _sl_tracked_record(target_type)
                _r = (_tk or {}).get("rules", {}).get(_rule["name"])
                if _r and _r["picks"]:
                    _tbar = st.container(horizontal=True)
                    _tbar.metric("Picks recorded", f"{_r['picks']:,}",
                                 delta=f"{_r['weeks']} weeks",
                                 delta_color="off")
                    _tbar.metric(
                        "Mean CLV",
                        "—" if _r["mean_clv_pp"] is None
                        else f"{_r['mean_clv_pp']:+.2f} pts",
                        help="The price at the time against the price the "
                             "market closed at. Positive means the market "
                             "moved toward these picks after they were "
                             "recorded — readable in dozens, where profit "
                             "needs hundreds.")
                    _tbar.metric(
                        "Beat the close",
                        "—" if _r["beat_close_pct"] is None
                        else f"{_r['beat_close_pct']:.0%}")
                if _rule.get("picks"):
                    _tf = pd.DataFrame(_rule["picks"])
                    _tf["Ours"] = _tf["ours"] * 100
                    _tf["Book"] = _tf["book"] * 100
                    _tf["Price"] = _tf["odds"].map(bp.american)
                    st.dataframe(
                        _tf[["player", "game", "Ours", "Book", "edge_pp", "Price"]],
                        hide_index=True, use_container_width=True)
                    st.caption(
                        f":material/science: Recorded to `data/tracked_picks.csv` "
                        f"every time this page is built, whether or not anyone "
                        f"backs them. Not a recommendation — the point is the "
                        f"record, not the picks.")
                else:
                    st.caption(
                        f":material/science: Nothing on this board matches it "
                        f"this week: it needs {_rule['min_edge_pp']:.0f}+ points "
                        f"between {bp.american(_rule['min_odds'])} and "
                        f"{bp.american(_rule['max_odds'])}. A week with no "
                        f"picks is part of the record.")

            # ── The half that measures best ──────────────────────────────
            # The filters above spend their first step throwing these away.
            # They are also the only group in this project with a positive
            # measured return, which is why they get named rather than counted.
            if _sl.get("vetoes"):
                st.subheader("Fade — the half no book sells")
                if _fade:
                    _fbar = st.container(horizontal=True)
                    _fbar.metric(
                        "They scored", f"{_fade['scored_pct']:.1f}%",
                        delta=f"priced at {_fade['priced_pct']:.1f}%",
                        delta_color="off",
                        help=f"Every player we rated {_fade['min_edge_pp']:.0f}+ "
                             f"points below the de-vigged price, over "
                             f"{_fade['n']:,} bets — graded on whether they "
                             f"actually scored.")
                    _fbar.metric(
                        "Laying at fair", f"{_fade['roi']:+.1f}%",
                        delta=f"{_fade['lo']:+.0f} to {_fade['hi']:+.0f}",
                        delta_color="off",
                        help="What backing the No side at the de-vigged price "
                             "would have returned. The interval clears zero, "
                             "which nothing else in this project does — and "
                             "that price does not exist: a live slate carried "
                             "0 of 142 quotes with a No side.")
                    _fbar.metric(
                        "Margin it can carry",
                        f"{_fade['margin_capacity_pct']:.2f}%",
                        help="How much a No price could hold back before the "
                             "edge is gone. This is the number that decides "
                             "whether the skill is reachable: anything a real "
                             "market charges above it turns this into a loss.")
                    _fbar.metric(
                        "On an exchange, 5% commission",
                        f"{_fade['exchange'][-1]['roi']:+.1f}%",
                        help="An exchange takes commission on winnings rather "
                             "than margin on the price, which is the only "
                             "venue where laying a player is possible at all. "
                             "Assumes a fill at the de-vigged price, which is "
                             "optimistic where the book is thin.")
                _vf = pd.DataFrame(_sl["vetoes"])
                _vf["Ours"] = _vf["ours"] * 100
                _vf["Book"] = _vf["book"] * 100
                _vf["Price"] = _vf["odds"].map(bp.american)
                st.dataframe(
                    _vf[["player", "game", "Ours", "Book", "edge_pp", "Price"]],
                    hide_index=True, use_container_width=True,
                    column_config={
                        "player": st.column_config.TextColumn("Player"),
                        "game": st.column_config.TextColumn("Game", width="small"),
                        "Ours": st.column_config.NumberColumn(
                            "Our estimate", format="%.1f%%"),
                        "Book": st.column_config.NumberColumn(
                            "Bookmaker says", format="%.1f%%"),
                        "edge_pp": st.column_config.NumberColumn(
                            "Difference", format="%+.1f pts",
                            help="How far below their price we sit. This is "
                                 "the direction the model is measurably good "
                                 "at, and the direction you cannot buy."),
                        "Price": st.column_config.TextColumn("Price", width="small"),
                    })
                st.caption(
                    ":material/block: These are **not bets**. They are players "
                    "to leave out — of a single, of a parlay, of a cover. "
                    "Where the two lists disagree with your instinct, this is "
                    "the one with a measurement behind it.")

if tab_board.open:
    with tab_board:
        render_purpose(target_type, selected_model, selected_version)
        render_accuracy_strip(target_type, selected_model,
                              selected_version)

        # The strip above, and several panels below, are read from artifacts
        # rather than computed. Say when one of them predates the model it is
        # describing — otherwise a retrain leaves last week's accuracy sitting
        # beside this week's picks with nothing to distinguish them.
        _stale = stale_evaluation(target_type)
        if _stale:
            _lines = "\n\n".join(
                f"- **{x['describes']}** — {x['artifact']}, "
                f"{x['behind_seconds'] / 3600:.0f}h older than the model. "
                f"Refresh with `{x['command']}`" for x in _stale)
            st.warning(
                f"**Some numbers on this page were computed before the current "
                f"model.**\n\n{_lines}", icon=":material/update:")

        board, backing, overvalued, problems = week_board(
            season, week, target_type, selected_model, selected_version)
        for _problem in problems:
            # A column that is absent because something broke reads exactly like a
            # column that is absent because there is no data. Say which.
            st.warning(f"**{_problem}** — this column is missing because something "
                       f"broke, not because the data does not exist.",
                       icon=":material/error:")
        if board is not None:
            h2h = market_headtohead(target_type, selected_model)
            # Collected under one heading rather than narrated inline. This
            # block used to open with a green "where we disagree is where this
            # model is worth reading" banner, which read as advice to act on
            # the edge columns — and directly contradicted the purpose panel
            # above it, which reports the measured return on doing exactly that
            # as negative. Two panels giving opposite instructions is worse
            # than either one alone, so the betting material now sits in one
            # collapsed place and describes skill rather than recommending it.
            _bet_box = st.expander("Betting view — measured negative on this market",
                                   icon=":material/payments:")
            if h2h and h2h["disagree_better_pct"] > 0:
                # The numbers themselves now sit in the strip above as metrics.
                # What a banner can add is the reading of them, which is not
                # obvious: the headline figure averages two halves that point in
                # opposite directions for a bettor.
                _hi = h2h.get("disagree_higher_pct")
                _lo = h2h.get("disagree_lower_pct")
                if _hi is not None and _lo is not None:
                    _bet_box.info(
                        f"**Where we differ from the bookmaker, our estimate is "
                        f"closer.** On the tenth of players we "
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
                    with _bet_box:
                        st.markdown(
                            f"**What 'closer' means.** "
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
                    _bet_box.info(
                        f"**Where we differ from the bookmaker, our estimate is "
                        f"closer.** On the players we differed from "
                        f"the book on most across {h2h['span']}, our estimate "
                        f"landed **{h2h['disagree_better_pct']:.0f}% closer** to "
                        f"what actually happened.",
                        icon=":material/trending_up:",
                    )

            _rule = betting_rule(target_type, selected_model)
            _preblend = bp.preblend_columns_differ(board)
            if _rule and _preblend:
                _bet_box.caption(
                    f"The last three columns answer a different "
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
                    with _bet_box:
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
                _bet_box.caption(
                    f"**Worth backing** carries the labels "
                    f"fitted across {_rule['games']:,} games in {_rule['span']}"
                    + bp.tier_summary(_rule) +
                    " There is no separate **Bet #** or **Bet edge** on this "
                    "market: it is not blended with the bookmaker, so the number "
                    "on the board already *is* our own view. See **Betting "
                    "reality**."
                )
            else:
                _bet_box.caption(
                    "No betting markers on this market. Its "
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
                    (f"Players priced at +{ls['min_odds']} or longer that we "
                     f"rate highest. Inside that group neither the book's price "
                     f"(AUC {ls['auc_book']:.2f}) nor ours ({ls['auc_ours']:.2f}) "
                     f"sorts scorers from non-scorers by much, and the gap "
                     f"between them is not distinguishable from zero "
                     f"(95% CI {ls['auc_gap_lo']:+.3f} to {ls['auc_gap_hi']:+.3f}). "
                     f"It says which longshots we rate highest, nothing more."
                     if ls["auc_gap_lo"] <= 0 else
                     f"Players priced at +{ls['min_odds']} or longer that we "
                     f"rate highest. Inside that group the book's own price "
                     f"barely sorts scorers from non-scorers (AUC "
                     f"{ls['auc_book']:.2f}) while ours does better "
                     f"({ls['auc_ours']:.2f}), and the gap clears zero "
                     f"(95% CI {ls['auc_gap_lo']:+.3f} to {ls['auc_gap_hi']:+.3f}). "
                     f"It says which longshots are live, not which are cheap.")
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
                _edge = ls["auc_gap_lo"] > 0
                st.info(
                    f"**Longshots we rate highest.** Across "
                    f"{ls['seasons'][0]}-{ls['seasons'][-1]} we order this group "
                    + ("slightly better than the price does"
                       if _edge else
                       "no better than the price does, within measurement error")
                    + f" — **{ls['auc_ours']:.2f}** "
                    f"against the book's **{ls['auc_book']:.2f}**, both close to a "
                    f"coin flip"
                    + ("" if _edge else
                       f" and the gap's 95% interval "
                       f"({ls['auc_gap_lo']:+.3f} to {ls['auc_gap_hi']:+.3f}) "
                       f"contains zero")
                    + f". That gap used to read 0.76 against 0.54 and was "
                    f"described here as the biggest edge on the board; almost all of "
                    f"it was two data leaks telling the model who had actually "
                    f"played, which in a band of deep reserves is most of the answer. "
                    f"Read it as *which longshots are live*, not *which are good "
                    f"value*: this band is priced around "
                    f"**{ls['band_price_implied']:.1%}** and only hits "
                    f"**{ls['band_actual_rate']:.1%}**, so the bookmaker's margin here "
                    f"is enormous. Our best-rated tenth still only came in at "
                    f"**{ls['top_decile_actual']:.1%}** against a price implying "
                    f"**{ls['top_decile_price_implied']:.1%}** — below the price, "
                    f"not above it, at roughly {ls['top_decile_per_week']:.0f} "
                    f"players a week, of whom well under one scores.",
                    icon=":material/insights:",
                )

            if shown.empty:
                st.info("No players match that filter.")
            else:
                render_selectivity(target_type, board, selected_model)
                render_board(shown, target_type, selected_model)
                render_unpriced(season, week, target_type, selected_model,
                                selected_version, query=query)
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

            # ── Combinations ──────────────────────────────────────────────
            # The board prices one player. This is the question it provokes and
            # has never answered: what if two or three of them go on one slip.
            # Nothing here is refitted — every number is the columns above,
            # multiplied out — and the note under the table is the price of
            # doing that multiplication.
            from src.prediction import combos

            st.markdown("#### Combinations")
            _cbar = st.container(horizontal=True)
            _legs = _cbar.selectbox(
                "Legs", list(range(2, combos.MAX_LEGS + 1)), key="combo_legs",
                help="How many players on the slip. Each one you add lengthens "
                     "the price and shortens the chance, and both move faster "
                     "than they look: three 40% legs is a 6% shot, six of them "
                     "is 1 in 244, and twelve is 1 in 59,605. Past four legs "
                     "the table is the best the search found rather than a "
                     "proven best — the caption under it says which.",
            )
            _pool_n = _cbar.slider(
                "From each game's top", min_value=2, max_value=6, value=4,
                key="combo_pool",
                help="Which players are eligible: each game's top N, ranked by "
                     "**#** in the board above. Widening this reaches further "
                     "down every game rather than deeper into one.",
            )
            _rank_by = _cbar.selectbox(
                "Rank by", ["Expected value", "Most likely"], key="combo_rank",
                help="**Expected value** ranks on what \\$100 expects to return, "
                     "measured on our pre-blend number like every other money "
                     "figure here. **Most likely** ranks on the chance the slip "
                     "lands. They are different questions and usually different "
                     "tables — the likeliest slips are short-priced and the best "
                     "value ones are not.",
            )
            _show_n = _cbar.slider(
                "Show", min_value=5, max_value=50, value=25, step=5,
                key="combo_show", help="How many rows to list.",
            )
            # Its own game filter rather than the board's. A slip is the one
            # thing on this page that deliberately spans fixtures, so "these
            # three games and nothing else" is the question it provokes, and a
            # single-game dropdown can only ask it one game at a time. Empty
            # means the whole slate.
            #
            # Seeded once from the board's Game selector, so someone who
            # filtered the board first still lands where they were, and
            # re-checked against this week's slate every run: a game held over
            # from another week is not an option any more, and Streamlit raises
            # on a stored value outside the options rather than dropping it.
            _game_opts = sorted(board["game_label"].dropna().unique().tolist())
            if "combo_games" not in st.session_state:
                st.session_state["combo_games"] = (
                    [] if pick == "All games" else [pick])
            else:
                st.session_state["combo_games"] = [
                    g for g in st.session_state["combo_games"] if g in _game_opts]
            _games = st.multiselect(
                "Games", _game_opts, key="combo_games",
                placeholder="All games",
                help="Which fixtures the legs may come from — pick as many as "
                     "you like, or none for the whole slate. This is the "
                     "combinations' own filter: the **Game** selector above "
                     "narrows the board you read, and picking two games at "
                     "once is a question it cannot ask.",
            )

            # What this configuration has actually done, from the graded
            # replay. It sits above the table rather than below it because it
            # is the context for reading any row: a table of expected values
            # built on a probability that runs hot is a table of fiction, and
            # `landed` against `we said` is the only thing that says which.
            _rec = None
            _record = combo_record(target_type, selected_model)
            if _record:
                from src.evaluation.combo_backtest import lookup
                _rec = lookup(_record, legs=int(_legs), per_game=int(_pool_n),
                              metric=("ev" if _rank_by == "Expected value"
                                      else "likely"), show=int(_show_n))
            if _rec:
                # Enough decimal places that the three chances on this strip
                # stay comparable. At twelve legs the replay says we predicted
                # 1 in 55,000 and none of 1,500 slips landed, which one place
                # prints as "0.0%" against "0.0%" — the same reading a strip
                # gets when the model is perfectly calibrated, from the one
                # setting where it says least.
                _rates = [_rec[k] for k in ("landed", "we_said", "book_said")
                          if _rec.get(k)]
                _rp = 1
                if _rates:
                    _hi = max(_rates) * 100
                    _rp = min(4, max(1, 2 - int(np.floor(np.log10(_hi)))))
                _strip = st.container(horizontal=True)
                _strip.metric(
                    "Slips graded", f"{_rec['slips']:,}",
                    delta=f"{_rec['weeks']} weeks, {_record['span']}",
                    delta_color="off",
                    help=f"Every slip this setting would have shown, replayed "
                         f"week by week over {_record['span']} and graded on "
                         f"results. Each season was predicted by a model that "
                         f"never trained on it, and each slip priced at the "
                         f"same closing prices the single-bet figures use.")
                _strip.metric(
                    "Landed", f"{_rec['landed']:.{_rp}%}",
                    help="How often **every** leg scored. One leg short is the "
                         "same as all of them short, which is the whole "
                         "difference between this and the board's accuracy.")
                _strip.metric(
                    "We said", f"{_rec['we_said']:.{_rp}%}",
                    delta=f"{_rec['landed'] - _rec['we_said']:+.{_rp}%} vs landed",
                    delta_color="off",
                    help="What we thought that chance was, averaged over the "
                         "same slips. This is the number that matters most on "
                         "this strip: multiplying legs multiplies any "
                         "calibration error, so a gap here is the reason to "
                         "distrust every expected value in the table below.")
                _strip.metric(
                    "Book said", f"{_rec['book_said']:.{_rp}%}",
                    help="The same product on the bookmaker's de-vigged "
                         "prices. It sits well below what these slips actually "
                         "landed because they are selected on disagreement — "
                         "we only build from players we rate above the price.")
                _ex = _rec.get("return_ex_top10")
                _strip.metric(
                    "Return per $100", bp.signed_money(_rec["return_per_100"],
                                                       0, escape=False),
                    delta=(f"{bp.signed_money(_ex, 0, escape=False)} without "
                           f"the 10 biggest wins" if _ex is not None else None),
                    delta_color="off",
                    help="What a flat \$100 on every one of these slips came "
                         "back with — measured, not expected. Read it next to "
                         "the figure without the ten biggest wins: a parlay's "
                         "profit is concentrated by construction, and where "
                         "the two disagree sharply the headline is a handful "
                         "of afternoons rather than a strategy.")
                _strip.metric(
                    "As singles", bp.signed_money(_rec["as_singles_per_100"],
                                                  0, escape=False),
                    help="The same players, the same money, staked as separate "
                         "bets instead — \$50 a leg on a two-leg slip. A "
                         "parlay compounds an edge rather than creating one, "
                         "so this is the number the one beside it is built "
                         "out of. It compounds a *wrong* edge exactly as "
                         "eagerly, which is the risk in the whole table.")
            elif _record:
                # Not a stale file: the replay is a fixed grid and the controls
                # reach outside it on purpose. Long slips are the reason — a
                # twelve-leg slip lands about once in a hundred thousand, so
                # replaying three seasons of them grades thousands and settles
                # essentially none, and a measured number for that does not
                # exist rather than being missing. Say which grid, so the way
                # back to a measured setting is on screen.
                st.caption(
                    f":material/warning: **This setting has not been graded.** "
                    f"The replay covers legs "
                    f"{combo_grid_range(_record, 'legs')}, the top "
                    f"{combo_grid_range(_record, 'per_game')} from each game "
                    f"and {combo_grid_range(_record, 'show')} rows. Move back "
                    f"inside that grid to see a measured number, or widen "
                    f"`LEG_COUNTS` in `src/evaluation/combo_backtest.py` and "
                    f"re-run `python scripts/29_combos.py --target "
                    f"{target_type}` — on a slip this long it will mostly "
                    f"measure how rarely one lands.")

            # Only the Games control above filters what is built. Search and
            # depth are left out on purpose: they narrow which rows you are
            # reading, not which bets exist.
            _combo_src = (board if not _games
                          else board[board["game_label"].isin(_games)])
            _combo_metric = "ev" if _rank_by == "Expected value" else "likely"
            _combos = combos.build(
                _combo_src, legs=int(_legs), per_game=int(_pool_n),
                top_k=int(_show_n), metric=_combo_metric,
                target_type=target_type,
            )

            if _combos.empty:
                # What the search actually had, not what the filter selected:
                # the pool drops unpriced and ruled-out players, and a message
                # counting rows the search never saw sends a reader looking for
                # the wrong thing.
                _elig = combos.pool(_combo_src, int(_pool_n))
                _n_games = int(_elig["game_label"].nunique()) if len(_elig) else 0
                if target_type == "first_td" and _n_games < int(_legs):
                    st.info(
                        f"**A {LEG_WORDS[int(_legs)]}-leg slip needs "
                        f"{int(_legs)} different games on this market.** "
                        f"Exactly one player scores a game's first touchdown, "
                        f"so no two legs can come from the same game, and "
                        f"there {'is' if _n_games == 1 else 'are'} "
                        f"{_n_games} to choose from here. Add games above, or "
                        f"shorten the slip.",
                        icon=":material/info:")
                else:
                    st.info(
                        f"**Not enough eligible players here.** A "
                        f"{LEG_WORDS[int(_legs)]}-leg slip needs {int(_legs)} "
                        f"of them and the top {int(_pool_n)} of "
                        f"{'this game' if len(_games) == 1 else 'these games'} "
                        f"leaves {len(_elig)}. Widen **From each game's top**, "
                        f"add games, or shorten the slip.",
                        icon=":material/info:")
            else:
                _cshow = _combos.copy()
                # Grouped, unlike the board's single-player prices: a slip
                # of several legs pays in seven figures and +3237144 is a
                # number you have to count the digits of.
                _cshow["Odds"] = _cshow["Odds"].map(bp.american_long)

                # The board's two verdicts, carried onto a slip. Both are
                # derived per leg and then reduced, rather than recomputed on
                # the slip's own numbers: the cuts behind "Our read" and the
                # thresholds behind "Worth backing" were both fitted on single
                # players, and a slip's edge is a different quantity on a
                # different scale. See bp.combo_read / bp.combo_backing.
                _lo, _hi = confidence_cuts(target_type)
                _leg_read = [bp.confidence(e, _lo, _hi)
                             for e in _combo_src["edge_pp"]]
                _cshow["Confidence"] = [
                    bp.combo_read([_leg_read[i] for i in legs])
                    for legs in _combos["_legs"]]
                _combo_cols = ["Players", "Game", "Odds", "Ours", "Book",
                               "edge_pp", "Confidence", "EV"]

                _combo_rule = betting_rule(target_type, selected_model)
                if _combo_rule:
                    _leg_tier = bp.highlight_tier(_combo_src, _combo_rule)
                    if not isinstance(_leg_tier, str):
                        _leg_tier = list(_leg_tier)
                        _cshow["InRange"] = [
                            bp.combo_backing([_leg_tier[i] for i in legs])
                            for legs in _combos["_legs"]]
                        _combo_cols = _combo_cols + ["InRange"]
                # A first-TD double lands under 1% of the time and a two-leg
                # anytime slip around a fifth of the time. One decimal place
                # prints the first as "0.5%" for everything — and a twelve-leg
                # slip, which lands about once in a hundred thousand, as
                # "0.0%" for every row in the table. Enough places to keep two
                # significant figures on the likeliest row, so the column still
                # separates the rows a reader is being asked to choose between.
                _top = float(_cshow["Ours"].max())
                _dp = (1 if _top >= 5 else
                       min(9, max(2, 2 - int(np.floor(np.log10(_top)))))
                       if _top > 0 else 2)
                st.dataframe(
                    _cshow[_combo_cols],
                    hide_index=True, column_config=combo_columns(_dp, _rec),
                    use_container_width=True)

                _leg_word = LEG_WORDS[int(_legs)]
                _ranked = ("expected value" if _combo_metric == "ev"
                           else "how likely the slip is to land")
                # Named while the list is short enough to read, counted after
                # that: eight game labels inside a sentence is not a sentence.
                if not _games:
                    _where = "every game on the slate"
                elif len(_games) <= 3:
                    _where = (" and ".join(_games) if len(_games) < 3
                              else f"{_games[0]}, {_games[1]} and {_games[2]}")
                else:
                    _where = f"the {len(_games)} games selected"
                # Say when the search was bounded, and which of the two kinds
                # of bound it was — a silent cap reads as "these are all of
                # them", and a cap that cannot carry the proof must not borrow
                # the sentence belonging to one that can.
                _searched = ""
                if _combos.attrs["n_candidates"] < _combos.attrs["n_pool"]:
                    _searched = (
                        f" Built from the {_combos.attrs['n_candidates']} "
                        f"strongest of the {_combos.attrs['n_pool']} eligible "
                        f"players")
                    _searched += (
                        (f", which is enough to find them: every number here "
                         f"is a product of the legs', so a slip using a weaker "
                         f"leg cannot outrank {len(_cshow)} built without it.")
                        if _combos.attrs["exact"] else
                        (f". **That is a bounded search, not an exhaustive "
                         f"one**: proving these are the exact best "
                         f"{int(_show_n)} would take the strongest "
                         f"{int(_show_n) + int(_legs)}, and at {int(_legs)} "
                         f"legs that many candidates is more combinations than "
                         f"anything here can enumerate. Read the table as the "
                         f"best it found, and shorten the slip or ask for "
                         f"fewer rows for an answer that is provably the top "
                         f"of the list."))
                st.caption(
                    f":material/functions: The {len(_cshow)} best {_leg_word}-leg "
                    f"combinations of the top {int(_pool_n)} in {_where}, ranked "
                    f"by {_ranked}.{_searched}"
                )

                # The assumption, re-measured rather than asserted, and the two
                # things this table is not. One paragraph on purpose: it is the
                # small print, and small print that runs to three panels does not
                # get read.
                _rho = leg_correlation(target_type)
                if target_type == "first_td":
                    # The teammate measurement below is beside the point here:
                    # same-game slips are already excluded, so the only thing
                    # being multiplied is one game against another.
                    _independence = (
                        "Legs on this market always come from different games, "
                        "so multiplying them assumes only that separate games "
                        "are independent of each other.")
                elif _rho is None:
                    _independence = (
                        "Legs are multiplied as if independent. The check that "
                        "justifies that — teammates' outcomes moving together in "
                        "the backtest — has not been run here; `make backtest` "
                        "produces what it reads.")
                elif _rho["independence_reasonable"]:
                    _independence = (
                        f"Legs are multiplied as if independent. Re-measured on "
                        f"{_rho['n_team_games']:,} team-games of backtest "
                        f"residuals, teammates' outcomes correlate "
                        f"{_rho['teammate_rho']:+.3f} — sharing a scoring game "
                        f"and competing for the same touchdowns very nearly "
                        f"cancel — so the correction would be smaller than the "
                        f"error in measuring it.")
                else:
                    _independence = (
                        f"**Read these as optimistic.** Legs are multiplied as if "
                        f"independent, but teammates' outcomes correlate "
                        f"{_rho['teammate_rho']:+.3f} across "
                        f"{_rho['n_team_games']:,} team-games of backtest "
                        f"residuals — enough that a product is the wrong "
                        f"arithmetic, most of all on the same-game rows.")

                if target_type == "first_td":
                    _exclusion = (
                        " Same-game slips are left out entirely: one player "
                        "scores a game's first touchdown, so two legs from one "
                        "game cannot both land.")
                elif bool(_cshow["SameGame"].any()):
                    _n_same = int(_cshow["SameGame"].sum())
                    _exclusion = (
                        f" {_n_same} of these rows put more than one leg in the "
                        f"same game — the **Game** column says how many games a "
                        f"slip spans, and a long one nearly always doubles up "
                        f"somewhere. Their price is arithmetic, not a quote: a "
                        f"book prices its own correlation into a same-game "
                        f"parlay and will come back shorter.")
                else:
                    _exclusion = ""

                if _rec:
                    _graded = (
                        f" The strip above is this exact setting replayed over "
                        f"{_record['span']}: {_rec['slips']:,} slips, of which "
                        f"{_rec['landed']:.1%} landed against the "
                        f"{_rec['we_said']:.1%} we said beforehand. The "
                        f"**Expected on $100** column below is still a forecast "
                        f"rather than that measurement.")
                else:
                    _graded = (
                        f" And nothing in this table has been backtested: every "
                        f"profitability figure in this app was measured on "
                        f"single bets at closing prices, and multiplying legs "
                        f"multiplies the model's calibration error along with "
                        f"them. `python scripts/29_combos.py --target "
                        f"{target_type}` grades it.")
                st.caption(
                    f":material/warning: {_independence}{_exclusion}{_graded}"
                )

            # ── Cover the field ───────────────────────────────────────────
            # `Combinations` above picks the slips worth backing. This asks the
            # opposite: pick the players yourself, back EVERY combination of
            # them, and see what has to happen to come out ahead.
            #
            # The selection is the section. There is no table of candidates
            # here because the board above already is one — this takes the
            # names you chose and answers the only question that follows.
            from src.prediction import cover as _cover

            st.markdown("#### Parlay")
            st.caption(
                "Pick players and back **every combination** of them — a full "
                "cover, not one slip. **n** players is **2ⁿ − 1** slips, so "
                "one is a single bet and five is 31. The table below is what "
                "each number of scorers returns.")

            # Whether there is any basis for preferring these numbers to the
            # price, put where the question is being asked. Both halves, never
            # their average: most of the model's accuracy on big disagreements
            # comes from rating players DOWN, and these markets only sell the
            # Yes side, so the blend sells fade skill as though it were a bet.
            # Here that compounds literally — a cover multiplies whatever edge
            # each leg carries, so it multiplies the backable half alone.
            _h2h = market_headtohead(target_type, selected_model,
                                     selected_version)
            _hi = (_h2h or {}).get("disagree_higher_pct")
            _lo = (_h2h or {}).get("disagree_lower_pct")
            if _hi is not None or _lo is not None:
                _ptiles = st.container(horizontal=True)
                if _hi is not None:
                    _ptiles.metric(
                        "Closer — backable", f"{_hi:+.0f}%",
                        delta=f"{_h2h.get('disagree_higher_n', 0):,} players",
                        delta_color="off",
                        help="On the tenth of players we differ from the book "
                             "on most, taking only those we rate **higher** — "
                             "the direction these markets let you bet. The "
                             "percentage by which our average squared miss is "
                             "smaller than the book's. **0% would mean we "
                             "match the book**; it is not a win rate and there "
                             "is no 50% baseline.")
                if _lo is not None:
                    _ptiles.metric(
                        "Closer — fade", f"{_lo:+.0f}%",
                        delta=f"{_h2h.get('disagree_lower_n', 0):,} players",
                        delta_color="off",
                        help="The same comparison for players we rate "
                             "**lower** than the book. This is the model's "
                             "sharpest skill by a wide margin and there is no "
                             "way to bet it — these markets only sell the Yes "
                             "side. Read it as a veto: a big disagreement "
                             "downward is a player to leave out of a cover.")
                st.caption(
                    "Only the backable half is a bet. A cover multiplies "
                    "whatever edge each leg carries, so it multiplies that "
                    "half — not the average of the two, which is higher "
                    "because the fade side is sharper.")

            _cov_src = (shown if pick != "All games" else board)
            _cov_src = _cov_src.sort_values("probability", ascending=False)
            _label_of, _row_of = {}, {}
            for _, r in _cov_src.iterrows():
                _lbl = (f"{r['player_name']} · {r.get('team', '')} · "
                        f"{r['probability']:.0%}"
                        + ("" if pd.isna(r.get("odds")) else
                           f" · {bp.american(r['odds'])}"))
                _label_of[_lbl] = r["player_name"]
                _row_of[_lbl] = r
            _options = list(_label_of)
            _default = _options[:5]

            _picked = st.multiselect(
                "Players", _options, default=_default, key="cover_picked",
                help="Every player on the board above, likeliest first. The "
                     "number you choose sets the number of slips.")

            # Text rather than number_input, because a stake is written `$2.50`
            # or `1,000` and a price is written `+120`. `bets.parse_money` and
            # `bets.parse_price` do the reading, and the exported page's
            # JavaScript copies are held to them by test — see
            # tests/test_dashboard_export.py.
            _cbar2 = st.container(horizontal=True)
            _stake_raw = _cbar2.text_input(
                "Stake per slip", value="1.00", key="cover_stake",
                help="Dollars: 2.50, $2.50, 1,000.")
            # Defaulted per market, and reset when the market changes. One
            # number carried across that switch means opposite things: near
            # the top of this board an anytime-TD leg is odds-on and a
            # first-TD leg pays seven times the stake, so +100 assumed on both
            # flatters one market and damns the other — and the table below
            # says nothing about which, because a payout column built from an
            # assumed price does not move when the probabilities do.
            from src.prediction.cover import assumed_price, price_curve
            from src.prediction.bets import american_to_decimal, decimal_to_american
            _cov_decs = (_cov_src["decimal_odds"] if "decimal_odds" in _cov_src.columns
                         else [None if pd.isna(o) else american_to_decimal(o)
                               for o in _cov_src["odds"]])
            _assumed = assumed_price(_cov_src["probability"], _cov_decs)
            _curve = price_curve(_cov_src["probability"], _cov_decs)
            if st.session_state.get("_cover_price_market") != target_type:
                st.session_state["cover_price"] = ""
                st.session_state["_cover_price_market"] = target_type
            _price_raw = _cbar2.text_input(
                "Price unpriced legs at", key="cover_price",
                placeholder=("this market's curve" if _curve else "+120 or 2.20"),
                help=("Leave it blank and every unpriced leg is charged what "
                      f"this market posts for a player we rate that highly — "
                      f"a line fitted over its {_curve['n']} priced players, "
                      f"which carries the margin curve with it. Books hold far "
                      f"more on a 10% player than on a 50% one, and one flat "
                      f"price assumes the opposite: at the median "
                      f"{bp.american(decimal_to_american(_assumed))} this "
                      f"market posts, a player we rate at 55% is handed a 14% "
                      f"overlay a leg before anyone has been right about "
                      f"anything.\n\nType a price (American +120/-200, or "
                      f"decimal 2.20) to override it for every unpriced leg — "
                      f"a what-if rather than a reading."
                      if _curve else
                      "American (+120, -200) or decimal (2.20), to stand in "
                      "for a leg with no market price. Too few players on this "
                      "market carry a price to fit what a book would ask, so "
                      "there is nothing to fall back on and this defaults to "
                      "+100."))
            from src.prediction.bets import parse_money, parse_price
            _cov_stake = parse_money(_stake_raw)
            _cov_price = parse_price(_price_raw)
            if _cov_stake is None:
                st.warning(f"**{_stake_raw}** is not an amount — type dollars, "
                           f"like 2.50 or $2.50 or 1,000. Using $1.00 a slip.",
                           icon=":material/warning:")
                _cov_stake = 1.0
            if _cov_price is None and _price_raw.strip():
                st.warning(f"**{_price_raw}** is not a price — type American "
                           f"(+120, -200) or decimal (2.20). Pricing the "
                           f"unpriced legs off this market instead.",
                           icon=":material/warning:")
            if _cov_price is None:
                # The flat fallback for a leg the curve cannot price at all.
                _cov_price = float(_assumed or 2.0)

            # One player is allowed: 2^1 - 1 is one slip, and the table still
            # says what it returns. Refusing it made the reader add a second
            # player they did not want in order to see the first one's numbers.
            if len(_picked) < 1:
                st.info("Pick at least one player.", icon=":material/info:")
            elif len(_picked) > _cover.MAX_PLAYERS:
                st.warning(
                    f"{len(_picked)} players is {2 ** len(_picked) - 1:,} "
                    f"slips. {_cover.MAX_PLAYERS} is the most this will "
                    f"enumerate — past there the table stops being readable "
                    f"long before it stops being computable.",
                    icon=":material/warning:")
            else:
                from src.prediction.cover import assumed_decimal
                _rho = (leg_correlation(target_type) or {}).get("teammate_rho", 0.0)
                _legs_in = []
                for _lbl in _picked:
                    r = _row_of[_lbl]
                    _legs_in.append({
                        "name": r["player_name"], "team": r.get("team"),
                        "prob": float(r["probability"]),
                        "odds": (None if pd.isna(r.get("odds"))
                                 else float(r["odds"])),
                        # Blank box means each unpriced leg is charged what
                        # this market asks for a player rated like it; a typed
                        # price overrides that, because someone who types one
                        # is asking a what-if and should get it.
                        "assumed": (None if parse_price(_price_raw) else
                                    assumed_decimal(_curve,
                                                    float(r["probability"]))),
                    })
                _cov = _cover.portfolio(_legs_in, stake=float(_cov_stake),
                                        rho=float(_rho),
                                        assumed_decimal=float(_cov_price))
                render_cover(_cov, target_type)

            # ── By team ───────────────────────────────────────────────────
            # The board answers "which player". This is the question underneath
            # it, which the model has an opinion about and has never shown.
            _teams = team_outlook_frame(season, week, selected_version)
            if _teams is not None and len(_teams):
                st.markdown("#### By team")
                st.caption(
                    "Which side scores first is a true coin-flip question, and "
                    "the model beats the coin: **AUC 0.674** over 2,278 "
                    "walk-forward team-games, calibrated from 6% to 94%. "
                    "**Bookmaker says** is the same split read off their own "
                    "first-TD prices, and it is blank for a game they have not "
                    "priced yet — most of the slate, early in a week. "
                    "Expected touchdowns is the fitted team rate; shut-out risk "
                    "is the chance of no offensive touchdown at all."
                )
                _t = _teams.copy()
                # Its own game selector rather than the board's. This table
                # covers every game on the slate; the board's list is only the
                # games a book has priced, which on an early-week slate is a
                # handful of them — so sharing that selector would offer no way
                # to reach most of the rows below.
                if "game_label" in _t.columns:
                    _tgames = ["All games"] + sorted(
                        _teams["game_label"].dropna().unique().tolist())
                    _tpick = st.container(horizontal=True).selectbox(
                        "Game", _tgames, key="team_game",
                        help="One game is two rows that answer each other: the "
                             "two sides' chances of striking first add to 100%, "
                             "so reading them together is the point.")
                    if _tpick != "All games":
                        _t = _t[_t["game_label"] == _tpick]

                _cols = {}
                if "game_label" in _t.columns:
                    _cols["game_label"] = st.column_config.TextColumn("Game")
                _cols["team"] = st.column_config.TextColumn("Team")
                if "first_td_pct" in _t.columns:
                    _cols["first_td_pct"] = st.column_config.NumberColumn(
                        "Scores first", format="%.0f%%",
                        help="Chance this team scores the game's first "
                             "touchdown. The two teams add to 100%.")
                    _t["first_td_pct"] = _t["first_td_pct"] * 100
                if ("book_first_td_pct" in _t.columns
                        and _t["book_first_td_pct"].notna().any()):
                    _t["book_first_td_pct"] = _t["book_first_td_pct"] * 100
                    _cols["book_first_td_pct"] = st.column_config.NumberColumn(
                        "Bookmaker says", format="%.0f%%",
                        help="The same arithmetic on the bookmaker's own "
                             "first-TD prices, with their margin removed: "
                             "their players' chances summed by team and "
                             "normalised within the game. Same question, their "
                             "answer — which is what makes the gap beside it "
                             "worth reading. Blank where too few of a game's "
                             "players carry a price to split it.")
                    _t["team_first_diff"] = (_t["first_td_pct"]
                                             - _t["book_first_td_pct"])
                    _cols["team_first_diff"] = st.column_config.NumberColumn(
                        "Difference", format="%+.0f pts",
                        help="How far our split sits above (+) or below (-) "
                             "theirs. It is the same number with opposite "
                             "signs on the two sides of a game, because both "
                             "columns add to 100%.")
                if "expected_tds" in _t.columns:
                    _cols["expected_tds"] = st.column_config.NumberColumn(
                        "Expected TDs", format="%.2f",
                        help="The fitted team touchdown rate, driven by the "
                             "betting lines.")
                if "expected_scorers" in _t.columns:
                    _cols["expected_scorers"] = st.column_config.NumberColumn(
                        "Expected scorers", format="%.2f",
                        help="How many different players are expected to score. "
                             "Lower than expected touchdowns because one player "
                             "can score twice.")
                if "shutout_pct" in _t.columns:
                    _cols["shutout_pct"] = st.column_config.NumberColumn(
                        "Shut-out risk", format="%.0f%%",
                        help="Chance of no offensive touchdown. Rare — teams "
                             "score in 92% of games — so this column is only "
                             "interesting when it is high.")
                    _t["shutout_pct"] = _t["shutout_pct"] * 100
                if "top_player" in _t.columns:
                    _cols["top_player"] = st.column_config.TextColumn(
                        "Likeliest scorer",
                        help="So the team number has a name attached.")
                if "top_player_pct" in _t.columns:
                    _cols["top_player_pct"] = st.column_config.NumberColumn(
                        "", format="%.0f%%")
                    _t["top_player_pct"] = _t["top_player_pct"] * 100
                st.dataframe(_t[list(_cols)], hide_index=True,
                             column_config=_cols, use_container_width=True)

                # A blank "scores first" is a roster outage, not a close game.
                # Say so, and name the teams — otherwise the empty cell reads as
                # a rendering glitch and the game quietly gets ignored.
                # Read from the filtered frame: a warning about ARI while you
                # are looking at DAL @ NYG reads as a fault in the rows shown.
                if "candidates" in _t.columns:
                    _thin = _t[_t["candidates"] < 5]
                    if len(_thin):
                        _names = ", ".join(sorted(set(_thin["team"].tolist())))
                        st.warning(
                            f"**No first-TD split for some games.** "
                            f"{_names} have almost no players in this week's "
                            f"candidate pool, so the split would describe the "
                            f"roster feed rather than the football. Their "
                            f"opponents are withheld too — one number is just "
                            f"one minus the other. This clears once rosters are "
                            f"published; re-run `make ingest`.",
                            icon=":material/database_off:")
                st.caption(
                    "Not shown: the chance a team scores *any* touchdown. It is "
                    "92% for nearly every team in nearly every game, and a "
                    "column that always reads the same teaches you to skip it."
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
        render_accuracy_strip(target_type, selected_model,
                              selected_version)
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

        _stale, _stale_err = derived_staleness()
        if not _stale_err and _stale:
            _names = sorted({r["artifact"] for r in _stale})
            st.warning(
                f"**{len(_stale)} artifact(s) on this page were written before "
                f"the model now being served** — "
                + ", ".join(f"`{n}`" for n in _names[:6])
                + (f" and {len(_names) - 6} more" if len(_names) > 6 else "")
                + ". Promotion swaps the weights and nothing else, so these "
                  "still describe the previous model. Regenerate with: "
                + ", ".join(f"`{f}`" for f in sorted({r["fix"] for r in _stale})),
                icon=":material/update:")

        from src.models.registry import MISSING_OPTIONAL
        if MISSING_OPTIONAL:
            # Degraded, not dead. Before 2026-08-19 this state was a crash at
            # import: a model module one commit newer than the running image
            # took the whole UI down for a model nothing was using. Now it
            # costs only the models it names, and says which.
            st.warning(
                "Some model modules did not load, so those models are "
                "unavailable: "
                + "; ".join(f"`{m.split('.')[-1]}` ({why})"
                            for m, why in sorted(MISSING_OPTIONAL.items()))
                + ". The board is unaffected unless one of them is the served "
                  "model. If this is a container, its source is behind the "
                  "repository — rebuild it with `make docker-build`.",
                icon=":material/warning:")

        render_feature_set(target_type, selected_version)
        render_feature_lab(target_type)
        st.divider()

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
                        # One scorer, shared with the strip above and with the
                        # walk-forward artifact. This block used to rank on raw
                        # model output and skip the joint step, which made it a
                        # fourth private copy of the scoring path: on anytime TD
                        # 2025 it read Top-1 50.0% while the board showed 51.4%,
                        # same model, same season.
                        _out = scored_season(target_type, hist_model, test_season,
                                             selected_version)
                        if _out is None or not len(_out):
                            st.info("Could not score this season with the "
                                    "current artifacts.")
                            st.stop()
                        best_ranks = [int(r) for r in _out["best_rank"].dropna()]
                        n_games = int(len(_out))
                        # Games whose only scorer the candidate filter removed
                        # have no rank at all. They count against the model —
                        # dropping them is how the walk-forward flattered itself
                        # for a year — so the denominator is every played game.

                        # Summary metrics
                        top1_pct = sum(1 for r in best_ranks if r == 1) / n_games * 100 if n_games else 0
                        top3_pct = sum(1 for r in best_ranks if r <= 3) / n_games * 100 if n_games else 0
                        top5_pct = sum(1 for r in best_ranks if r <= 5) / n_games * 100 if n_games else 0
                        median_rank = float(np.median(best_ranks)) if best_ranks else 0

                        # The headline is the same measurement the board's
                        # strip shows, from the same source, so the two pages
                        # cannot disagree about how good the model is. Two
                        # numbers under similar labels — pooled folds here, one
                        # season there — read as a contradiction rather than as
                        # two views, which is exactly how this page was read.
                        # Same accessor and same renderer as the board's
                        # header, so the two cannot disagree. See
                        # tests/test_headline_parity.py.
                        _headline = headline_accuracy(target_type, hist_model,
                                                      selected_version)
                        if _headline:
                            st.markdown("#### Track record")
                            render_headline(_headline, st.container(horizontal=True))
                            st.caption(
                                f"Pooled over {_headline['games']:,} games in "
                                f"{_headline.get('span', '')}, each season "
                                f"predicted by a model retrained without it. "
                                f"This is the figure on the board's header — "
                                f"same measurement, same source."
                            )

                        st.markdown(f"#### {test_season} in detail")
                        st.caption(
                            f"The single held-out season on its own. It moves "
                            f"around more than the pooled figure above — "
                            f"{n_games} games carries roughly three points of "
                            f"standard error — so read it for *where* the model "
                            f"missed, not for how good it is."
                        )
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
                            # Weeks come from the feature matrix rather than from
                            # a second scoring pass, so this chart and the
                            # summary above it are the same numbers cut two ways.
                            _weeks = (test_df.select(["game_id", "week"]).unique()
                                      .to_pandas())
                            _byweek = _out.merge(_weeks, on="game_id", how="left")
                            week_stats = []
                            for w in sorted(_byweek["week"].dropna().unique()):
                                sub = _byweek[_byweek["week"] == w]
                                if not len(sub):
                                    continue
                                week_stats.append({
                                    "Week": int(w),
                                    "Top-1": float(sub["hit1"].mean()) * 100,
                                    "Top-3": float(sub["hit3"].mean()) * 100,
                                    "Top-5": float(sub["hit5"].mean()) * 100,
                                })

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


@st.cache_data(show_spinner=False)
def clv_headline(tt: str) -> dict | None:
    """The pooled closing-line result `clv_by_rank` decomposes, or None.

    Read from the artifact rather than recomputed, for the same reason
    walkforward.json and rank_economics.json are: it is measured over the
    walk-forward backtests and rebuilt by `make evaluate`, so recomputing it
    per page view would be several seconds of work to reproduce a file that
    already exists.

    The two are different questions and the table alone cannot answer this
    one. `by_rank` asks whether the effect fades as the group widens; this asks
    whether, across every scored player-game, the direction we disagreed with
    the opening price in is the direction the line then moved — against a
    permutation null, which is what makes the number mean anything. The market
    drifts longer overall, so a model with no skill at all still scores about
    53%.
    """
    from src.evaluation.rank_economics import load
    return load(get_path("output", tt) / "clv.json")


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
        render_accuracy_strip(target_type, selected_model,
                              selected_version)
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
            _head = clv_headline(target_type)
            if _head:
                st.markdown("##### Does the betting market drift toward our picks?")
                _beats = _head["agree_pct"] > _head["null_hi"]
                c1, c2, c3 = st.columns(3)
                c1.metric(
                    "Market moved our way", f"{_head['agree_pct']:.1%}",
                    delta=f"{_head['edge_pts']:+.1f} pts vs chance",
                    delta_color="normal" if _beats else "off",
                    help=f"Across {_head['n']:,} player-games where the price "
                         f"actually moved, this is how often the direction we "
                         f"disagreed with the opening price in is the direction "
                         f"the line then went. Measured on the walk-forward "
                         f"backtests over {', '.join(str(s) for s in _head['seasons'])}.")
                c2.metric(
                    "Chance alone would give", f"{_head['null_pct']:.1%}",
                    help="Shuffling *which* players we like, within each game, "
                         "200 times. The whole board drifts longer between the "
                         "open and kickoff, so a model with no skill still "
                         "scores well above 50% — this is the bar that matters, "
                         "not a coin flip. 95% of shuffles land between "
                         f"{_head['null_lo']:.1%} and {_head['null_hi']:.1%}.")
                c3.metric(
                    "Player-games measured", f"{_head['n']:,}",
                    help=f"From {_head['pairs']:,} paired open/close prices "
                         f"across {_head['games']:,} games. Prices that closed "
                         f"where they opened are excluded — they say nothing "
                         f"about who was right.")
                if _beats:
                    st.caption(
                        f":material/check_circle: **Clear of the null.** The "
                        f"players we rate above the opening price are the ones "
                        f"the market then shortens. This is the highest-powered "
                        f"evidence here — every priced player counts, not just "
                        f"the ones who scored, which is why it rests on "
                        f"{_head['n']:,} observations where the accuracy figures "
                        f"above rest on about 1,100 games.")
                else:
                    st.caption(
                        ":material/help: **Inside the null.** On this evidence "
                        "our disagreements with the opening price do not "
                        "anticipate where the line goes.")
                st.caption(
                    "It is a proxy, not a bank statement. Beating the close does "
                    "not put money in your pocket, and a book that will not take "
                    "the bet at the opening price makes it moot.")

            if clv:
                if not _head:
                    st.markdown("##### Does the betting market drift toward our picks?")
                st.caption(
                    "**Broken down by how highly we rate the player.** A real "
                    "effect should be strongest at the top and fade as the group "
                    "widens — that pattern is harder to produce by accident than "
                    "the single figure above, which is why both are here."
                    if _head else
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
        render_accuracy_strip(target_type, selected_model,
                              selected_version)

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
