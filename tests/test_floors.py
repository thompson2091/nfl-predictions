"""90% floors: the line, the backtest's selection, the freeze, and the page."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from src.evaluation import floors as F
from src.export import prediction_freeze as PF

REPO = Path(__file__).resolve().parents[1]

KICKS = {"2026_07_A_B": datetime(2026, 10, 18, 13, 0),
         "2026_07_C_D": datetime(2026, 10, 19, 20, 15)}
BEFORE = datetime(2026, 10, 18, 9, 0)
BETWEEN = datetime(2026, 10, 18, 18, 0)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Never touch the real archive or the real backtest files."""
    monkeypatch.setattr(PF, "ROOT", tmp_path / "predictions")
    monkeypatch.setattr("src.evaluation.tracked_rules.kickoffs",
                        lambda season, week: dict(KICKS))
    monkeypatch.setattr("src.export.run_manifest.served_version",
                        lambda market: "v-test")
    monkeypatch.setattr(F, "target", lambda: 0.90)
    PF._CACHE.clear()
    PF._DIRTY.clear()
    yield
    PF._CACHE.clear()
    PF._DIRTY.clear()


# ── The floor itself ───────────────────────────────────────────────────────

def test_the_floor_is_the_highest_line_at_or_above_target():
    lines = np.array([0.5, 1.5, 2.5, 3.5])
    p = np.array([[0.99, 0.95, 0.90, 0.60],     # 0.90 exactly counts
                  [0.97, 0.89, 0.50, 0.10],
                  [0.85, 0.40, 0.10, 0.01]])    # nothing clears: no floor
    line, chance = F.floors(p, lines, 0.90)
    assert line[0] == 2.5 and chance[0] == pytest.approx(0.90)
    assert line[1] == 0.5 and chance[1] == pytest.approx(0.97)
    assert np.isnan(line[2]) and np.isnan(chance[2])


def test_catches_floor_matches_a_brute_force_negative_binomial():
    from scipy import stats

    mu, r = np.array([1.2, 3.5, 7.0]), 6.0
    lines = F.grid("receptions")
    raw = F.raw_over_grid("receptions", mu, lines, dispersion=r)
    line, _ = F.floors(raw, lines, 0.90)
    for i, m in enumerate(mu):
        dist = stats.nbinom(r, r / (r + m))
        ok = [L for L in lines if 1 - dist.cdf(np.floor(L)) >= 0.90]
        want = max(ok) if ok else np.nan
        assert (np.isnan(want) and np.isnan(line[i])) or line[i] == want


def test_yardage_floor_reads_the_quantile_curve():
    """A curve whose 10th percentile is 40: P(over 39.5) is just above 0.90
    and P(over 40.5) just below, so the floor is 39.5."""
    from src.models.yards import QUANTILE_LEVELS

    lv = np.array(QUANTILE_LEVELS)
    q = (lv * 400.0)[None, :]                    # q(a) = 400a, q(0.10) = 40
    lines = F.grid("receiving_yards")
    raw = F.raw_over_grid("receiving_yards", q, lines, QUANTILE_LEVELS)
    assert np.all(np.diff(raw[0]) <= 1e-12), "P(over) must not rise with the line"
    line, chance = F.floors(raw, lines, 0.90)
    assert line[0] == 39.5 and chance[0] >= 0.90


def test_calibration_is_monotone_and_moves_the_floor_the_right_way():
    lines = F.grid("rushing_yards")[:6]
    raw = np.array([[0.99, 0.97, 0.95, 0.92, 0.91, 0.80]])
    assert F.floors(F.calibrate(raw, None), lines, 0.9)[0][0] == lines[4]
    # A flattening map (slope < 1) pulls 0.91 and 0.92 under target.
    flat = {"a": 0.0, "b": 0.6}
    cal = F.calibrate(raw, flat)
    assert np.all(np.diff(cal[0]) <= 0)
    assert F.floors(cal, lines, 0.9)[0][0] < lines[4]


def test_fit_rows_take_one_line_per_level_and_grade_the_result():
    lines = np.array([0.5, 1.5, 2.5])
    raw = np.array([[0.99, 0.92, 0.55]])
    x, y = F.fit_rows(raw, lines, np.array([2.0]), levels=(0.5, 0.9, 0.95, 0.98))
    # 0.5 -> 2.5 (missed: 2 < 2.5); 0.9 -> 1.5 (hit); 0.95 and 0.98 -> 0.5,
    # which counts once.
    assert list(x) == [0.55, 0.92, 0.99]
    assert list(y) == [0.0, 1.0, 1.0]


# ── The backtest's selection ──────────────────────────────────────────────

def test_backtest_drops_void_grades_zero_and_keeps_only_its_season(monkeypatch):
    """Every priced player-game, settled like a book: no snap and no stat is
    void (absent from the log), a snap with no stat is a zero (in the log)."""
    ids = pl.DataFrame({"season": [2025] * 3, "week": [1] * 3,
                        "game_id": ["G1", "G1", "G2"],
                        "player_id": ["played", "zero", "void"],
                        "player_name": ["P", "Z", "V"], "team": ["A", "A", "C"]})
    dist = np.array([5.0, 4.0, 3.0])
    monkeypatch.setattr(F, "week_dists", lambda m, s, w, arts=None:
                        (ids, dist, {"dispersion": 6.0}))
    logs = pl.DataFrame({"season": [2025, 2025, 2024], "week": [1, 1, 1],
                         "game_id": ["G1", "G1", "G1"],
                         "player_id": ["played", "zero", "void"],
                         "receptions": [6.0, 0.0, 9.0]})
    got, d, _ = F.settled_dists("receptions", 2025, logs)
    assert sorted(got["player_id"].to_list()) == ["played", "zero"]
    by = dict(zip(got["player_id"].to_list(), got["actual"].to_list()))
    assert by == {"played": 6.0, "zero": 0.0}
    # The distribution travels with its row through the join.
    assert sorted(d.tolist()) == [4.0, 5.0]
    assert F.grade(np.array([0.5, 0.5]), np.array([0.0, 1.0])).tolist() == [0.0, 1.0]


def test_hit_rate_interval_is_clustered_by_game():
    hit = np.array([1, 1, 1, 0, 1, 1, 0, 0])
    games = np.array(["a", "a", "a", "a", "b", "b", "b", "b"])
    r = F.cluster_rate(hit, games)
    assert r["n"] == 8 and r["games"] == 2 and r["hit"] == pytest.approx(0.625)
    assert r["lo"] <= r["hit"] <= r["hi"]
    assert F.cluster_rate(np.array([]), np.array([]))["n"] == 0


def test_a_market_ships_when_its_interval_reaches_the_target():
    assert F.passes({"n": 10, "hi": 0.905}, 0.90)
    assert F.passes({"n": 10, "hi": 0.97, "lo": 0.93}, 0.90)
    assert not F.passes({"n": 10, "hi": 0.88}, 0.90)
    assert not F.passes({"n": 0, "hi": None}, 0.90)


# ── The live payload ──────────────────────────────────────────────────────

def _bt():
    ok = {"n": 1800, "games": 285, "hit": 0.908, "lo": 0.895, "hi": 0.921}
    bad = {"n": 600, "games": 285, "hit": 0.82, "lo": 0.79, "hi": 0.85}
    return {"test_season": 2025, "fit_season": 2024,
            "money": {"per_100": -4.05, "season": 2025},
            "markets": {
                "receptions": {"test": ok, "median_gap": 3.0, "strata": []},
                "receiving_yards": {"test": ok, "median_gap": 33.0, "strata": [
                    {"n": 500, "hit": 0.86, "lo": 0.83, "hi": 0.89,
                     "from": None, "to": 30.0},
                    {"n": 600, "hit": 0.93, "lo": 0.91, "hi": 0.95,
                     "from": 30.0, "to": None}]},
                "rushing_yards": {"test": ok, "strata": []},
                "passing_yards": {"test": bad, "strata": []}}}


def _week_floors(market, season, week, cal, tgt, arts=None):
    return pl.DataFrame({
        "player_name": ["Alpha", "Bravo", "Bench"],
        "player_id": ["a", "b", "x"], "team": ["A", "C", "A"],
        "game_id": ["2026_07_A_B", "2026_07_C_D", "2026_07_A_B"],
        "floor": [24.5, 10.5, 0.5], "p_floor": [0.91, 0.93, 0.95],
        "proj": [60.0, 25.0, 3.0]})


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(F, "load_backtest", lambda out_dir=None: _bt())
    monkeypatch.setattr(F, "load_calibration", lambda out_dir=None: {
        m: {"a": 0.0, "b": 1.0} for m in F.MARKETS})
    monkeypatch.setattr(F, "week_floors", _week_floors)
    monkeypatch.setattr(F, "book_prices", lambda s, w: {
        ("2026_07_A_B", "a", "receiving_yards", 24.5): {"odds": -900, "n_books": 3}})
    return F.payload(2026, 7, eligible={"Alpha", "Bravo"})


def test_payload_keeps_the_board_population_and_matches_the_exact_rung(live):
    rec = {m["market"]: m for m in live["markets"]}["receiving_yards"]
    assert [r["player_name"] for r in rec["rows"]] == ["Alpha", "Bravo"]
    assert rec["rows"][0]["book_odds"] == -900
    assert rec["rows"][1]["book_odds"] is None       # no rung at 10.5
    assert live["loss_per_100"] == pytest.approx(-4.05)
    assert rec["ok"] is True and [w["to"] for w in rec["weak"]] == [30.0]


def test_a_market_that_misses_target_is_shown_not_hidden(live):
    pas = {m["market"]: m for m in live["markets"]}["passing_yards"]
    assert pas["ok"] is False
    assert pas["rows"], "a failing market is shown with a warning, not removed"


def test_a_market_with_no_calibration_shows_no_floors(monkeypatch):
    # Raw passing floors held 0.82 on 2025: a missing file is not a 90% claim.
    monkeypatch.setattr(F, "load_backtest", lambda out_dir=None: _bt())
    monkeypatch.setattr(F, "load_calibration", lambda out_dir=None: {})
    monkeypatch.setattr(F, "week_floors", _week_floors)
    monkeypatch.setattr(F, "book_prices", lambda s, w: {})
    got = F.payload(2026, 7, eligible={"Alpha", "Bravo"})
    for m in got["markets"]:
        assert m["rows"] == [] and "no fitted calibration" in m["problem"]


# ── The freeze and the forward record ─────────────────────────────────────

def test_floors_freeze_per_game_before_kickoff_only(live):
    assert F.freeze(live, 2026, 7, now=BETWEEN) == 4   # C_D in 4 markets
    kept = PF.frozen(2026, 7, "receiving_yards_floor")
    assert list(kept) == ["2026_07_C_D"]
    row = kept["2026_07_C_D"][0]
    assert set(row) <= set(PF.FLOOR_FIELDS)
    assert row["floor"] == 10.5 and row["target"] == 0.90
    assert row["version"] == "v-test"


def test_a_started_game_serves_the_floor_it_kicked_off_with(live):
    F.freeze(live, 2026, 7, now=BEFORE)
    later = json.loads(json.dumps(live))
    for m in later["markets"]:
        for r in m["rows"]:
            r["floor"] = 99.5
    F.serve_frozen(later, 2026, 7, now=BETWEEN)
    rec = {m["market"]: m for m in later["markets"]}["receiving_yards"]
    by = {r["player_name"]: r for r in rec["rows"]}
    assert by["Alpha"]["floor"] == 24.5 and by["Alpha"]["frozen"]
    assert by["Bravo"]["floor"] == 99.5                # not started: live


def test_forward_grades_final_games_and_counts_pending_once():
    frozen = {"7": {
        "receiving_yards_floor": {
            "2026_07_A_B": [
                {"player_name": "Alpha", "player_id": "a", "floor": 24.5},
                {"player_name": "Zero", "player_id": "z", "floor": 0.5},
                {"player_name": "Gone", "player_id": "g", "floor": 4.5}],
            "2026_07_C_D": [
                {"player_name": "Bravo", "player_id": "b", "floor": 10.5}]},
        # A board market beside it is not a floor and is not read.
        "receiving_yards": {"2026_07_A_B": [{"player_name": "Alpha", "point": 60.5}]}}}
    acts = {"a": 30.0}
    got = F.forward(2026, frozen=frozen,
                    unfinished=lambda s, w: ({"2026_07_C_D"}, {"C @ D"}),
                    actuals=lambda s, w, m: (lambda name, pid=None: acts.get(pid)),
                    played={("2026_07_A_B", "zero"): 12})
    rec = {m["market"]: m for m in got["markets"]}["receiving_yards"]
    # Alpha over 24.5 (hit); Zero played and recorded nothing (miss at 0.5);
    # Gone neither played nor recorded (void); Bravo's game is not final.
    assert rec["n"] == 2 and rec["hit"] == pytest.approx(0.5)
    assert rec["pending"] == 1 and got["pending"] == 1
    assert got["weeks"] == [7]
    other = {m["market"]: m for m in got["markets"]}["receptions"]
    assert other["n"] == 0 and other["pending"] == 0


def test_floor_keys_do_not_leak_into_the_over_under_forward_record():
    """`forward_record` reads the same freeze; a floor row has no `point`
    and must never become a pick there."""
    from src.evaluation import forward_record as FR

    PF.load(2026)["7"] = {"receptions_floor": {"2026_07_A_B": [
        {"player_name": "Alpha", "player_id": "a", "floor": 2.5}]}}
    assert FR._picks_from_boards(2026) == []


# ── The page ───────────────────────────────────────────────────────────────

@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_floors_view_and_its_record_render(live, tmp_path):
    import tests.test_v3_export as V3T
    from src.export import site as v1
    from src.export import v3js

    p = V3T.payload_v3.__wrapped__()
    p["floors"] = live
    S = p.setdefault("scorecard", {})
    S["floors"] = {"target": 0.9, "weeks": [6], "pending": 3, "markets": [
        {"market": "receptions", "label": "Catches", "n": 40, "games": 9,
         "hit": 0.925, "lo": 0.87, "hi": 0.98, "pending": 3},
        {"market": "passing_yards", "label": "Passing yards", "n": 20,
         "games": 9, "hit": 0.70, "lo": 0.55, "hi": 0.85, "pending": 0}]}
    js = tmp_path / "app.js"
    js.write_text("\n".join([v1.JS_CORE, v1.JS_SHARED, v1.JS_SLIPVIEW, v1.JS_WEEK,
                             v1.JS_COMBOS, v1.JS_SAVED, v1.JS_LADDER, v1.JS_MODEL,
                             v3js.js()]))
    pl_ = tmp_path / "payload.json"
    pl_.write_text(json.dumps(p))
    r = subprocess.run(["node", str(REPO / "tests" / "js" / "floors.js"),
                        str(pl_), str(js)],
                       capture_output=True, text=True, cwd=str(REPO))
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    for check in ("the floors filter is on the bar",
                  "it says these are not bets",
                  "it quotes the measured loss from the payload",
                  "a passing market shows its held-out record",
                  "the floor and the book price are on the row",
                  "a missing rung leaves the price blank",
                  "a weak band marks its rows",
                  "a market below target carries a warning and its rows",
                  "a touchdown market explains floors are over/under only",
                  "a past week points to the record",
                  "the record grades floors per market against the target",
                  "pending floors are counted once and apart",
                  "a market holding below target is named"):
        assert check in r.stdout, f"not exercised: {check}\n{r.stdout}"
