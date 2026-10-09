"""The certainty measurement, checked on inputs whose answer is known.

The expensive half of `confidence` is `legs`, which rebuilds a board per
market per week; the half that can be wrong quietly is the arithmetic. So
these drive `gradient`, `paired` and `power` with synthetic rows where the
right answer is arithmetic rather than a measurement, and one end-to-end
check that the script's week parser does what its help text says.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from src.evaluation import confidence as C

REPO = Path(__file__).resolve().parents[1]


def leg(game: str, model: float, ret: float) -> dict:
    return {"game_id": game, "model": model, "ret": ret, "won": ret > 0,
            "odds": -110, "market": "receptions", "week": 1, "season": 2026,
            "player": game + str(model), "line": 3.5}


def test_certainty_is_distance_from_a_coin_flip_either_way():
    """A model at 0.05 is as sure as one at 0.95 — of the under."""
    assert C.certainty(0.95) == pytest.approx(0.95)
    assert C.certainty(0.05) == pytest.approx(0.95)
    assert C.certainty(0.50) == pytest.approx(0.50)
    # And it is never below a coin flip, which is what the bands assume.
    for p in (0.0, 0.2, 0.5, 0.7, 1.0):
        assert C.certainty(p) >= 0.5


def test_the_bands_tile_the_range_without_a_gap_or_an_overlap():
    """A gap is a bet on nobody's row; an overlap is one counted twice.

    Both read as a measured result rather than as an arithmetic slip, which
    is the same reason `test_the_spread_bands_partition_the_line` exists for
    the angles.
    """
    assert C.BANDS[0][0] == 0.50, "the first band has to start at a coin flip"
    assert C.BANDS[-1][1] > 1.0, "a model at exactly 1.0 must land somewhere"
    for (a1, b1), (a2, b2) in zip(C.BANDS, C.BANDS[1:]):
        assert b1 == a2, f"gap or overlap between {b1} and {a2}"
    # Every certainty falls in exactly one band.
    for p in (0.5, 0.5001, 0.549, 0.55, 0.62, 0.75, 0.999, 1.0):
        hit = [1 for lo, hi in C.BANDS if lo <= C.certainty(p) < hi]
        assert len(hit) == 1, f"{p} lands on {len(hit)} bands"


def test_a_band_under_the_floor_is_reported_as_unmeasurable_not_dropped():
    """A missing row reads as a band nobody looked at."""
    rows = [leg("g1", 0.52, 1.0), leg("g2", 0.52, -1.0)]
    out = C.gradient(rows, min_n=40)
    assert len(out) == len(C.BANDS), "a band vanished"
    first = out[0]
    assert first["n"] == 2 and "roi" not in first, first
    # And with the floor lowered it becomes measurable on the same input.
    assert "roi" in C.gradient(rows, min_n=2)[0]


def test_the_gradient_puts_each_bet_in_the_band_its_certainty_names():
    rows = [leg("g1", 0.51, 1.0), leg("g1", 0.58, 1.0), leg("g2", 0.62, 1.0),
            leg("g2", 0.70, 1.0), leg("g3", 0.90, 1.0), leg("g3", 0.10, 1.0)]
    out = {(b["lo"], b["hi"]): b["n"] for b in C.gradient(rows, min_n=1)}
    assert out[(0.50, 0.55)] == 1
    assert out[(0.55, 0.60)] == 1
    assert out[(0.60, 0.65)] == 1
    assert out[(0.65, 0.75)] == 1
    # 0.90 and 0.10 are both 0.90 sure, of opposite sides.
    assert out[(0.75, 1.01)] == 2


def test_the_paired_test_differences_within_a_game_not_across_them():
    """THE WHOLE POINT: a shootout lifts both groups in the same game.

    Two games, each with one confident winner and one unconfident loser. The
    within-game difference is the same in both, so the mean is that
    difference and the standard error is zero — which is the degenerate case
    worth pinning, because a naive variance divides by it.
    """
    rows = [leg("g1", 0.80, 0.909), leg("g1", 0.51, -1.0),
            leg("g2", 0.80, 0.909), leg("g2", 0.51, -1.0),
            leg("g3", 0.80, 0.909), leg("g3", 0.51, -1.0)]
    d = C.paired(rows)
    assert d is not None
    assert d["games"] == 3
    assert d["diff"] == pytest.approx(1.909, abs=1e-3)
    assert d["se"] == 0.0 and d["p"] == 1.0, d


def test_a_game_with_only_one_group_contributes_nothing_to_the_paired_test():
    """Which is why its game count is smaller than the season's, and has to
    be reported rather than assumed equal."""
    rows = [leg("both", 0.80, 1.0), leg("both", 0.51, -1.0),
            leg("hi only", 0.80, 1.0), leg("hi only", 0.85, 1.0),
            leg("lo only", 0.51, -1.0)]
    d = C.paired(rows)
    assert d is None or d["games"] == 1, d


def test_too_few_paired_games_says_so_rather_than_inventing_an_interval():
    rows = [leg("g1", 0.80, 1.0), leg("g1", 0.51, -1.0)]
    assert C.paired(rows) is None


def test_power_reports_what_the_reading_could_have_found():
    """A flat gradient from a test that can only see twenty points is not a
    flat gradient, and the sensitivity is printed before the result for
    exactly that reason.

    BETWEEN-GAME VARIATION IS THE WHOLE INPUT. A fixture where every game
    sums to the same thing has no between-game variance and CR0 correctly
    reports a standard error of zero — which is the clustering working, not
    a bug, and is why these games differ from each other rather than only
    within themselves.
    """
    rows = []
    for i in range(40):
        # Whole games win or lose together, which is the correlation
        # clustering exists to price.
        r = 1.0 if i % 2 == 0 else -1.0
        rows += [leg(f"g{i}", 0.80, r), leg(f"g{i}", 0.51, r)]
    p = C.power(rows)
    assert p["n"] == 80 and p["games"] == 40
    assert p["se"] > 0, "a fixture with between-game variation must have one"
    # 80% power is a wider bar than the interval's own half-width.
    assert p["detects"] > (p["ci_hi"] - p["roi"])
    assert C.power([])["n"] == 0


def test_clustering_widens_the_interval_when_a_game_moves_together():
    """The claim the module rests on, checked rather than asserted in prose.

    The same returns, arranged so whole games win or lose together, carry
    less information than the same count spread one to a game — and a
    cluster-robust interval has to be wider for the first than for the
    second or it is not clustering anything.
    """
    together, apart = [], []
    for i in range(30):
        r = 1.0 if i % 2 == 0 else -1.0
        together += [leg(f"g{i}", 0.70, r) for _ in range(4)]
        apart += [leg(f"g{i}-{k}", 0.70, r if k == 0 else -r)
                  for k in range(4)]
    wide = C.power(together)
    tight = C.power(apart)
    assert wide["se"] > tight["se"], (wide["se"], tight["se"])


def test_nothing_serves_off_these_cuts():
    """`HI` and `LO` are reporting cuts for a diagnostic.

    The project does not hand-tune a served threshold, and a 0.60 cut here
    is tie-break sensitive — +2.48 per $100 with the project's own `-edge`
    dedupe tie-break and +1.91 with a neutral one. So the gradient is the
    finding and no cut is published. If that ever changes it has to come
    past this test, which checks the two things that would make it false:
    the module still says so, and nothing that builds a page reads it.
    """
    src = (REPO / "src/evaluation/confidence.py").read_text()
    assert "NOTHING HERE IS FITTED AND NOTHING SERVES OFF IT" in src, (
        "the module no longer states that nothing serves off these cuts")

    readers = sorted(
        p.name for p in (REPO / "src/export").glob("*.py")
        if "evaluation.confidence" in p.read_text()
        or "evaluation import confidence" in p.read_text())
    assert not readers, (
        f"these build a page and import the diagnostic: {readers}")


@pytest.mark.parametrize("spec,want", [
    ("1-4", [1, 2, 3, 4]),
    ("3", [3]),
    ("1,3,5", [1, 3, 5]),
    ("1-3,7", [1, 2, 3, 7]),
    ("5-5", [5]),
    ("2,2,1", [1, 2]),
])
def test_the_scripts_week_parser_does_what_its_help_text_says(spec, want):
    spec_path = REPO / "scripts" / "65_confidence.py"
    s = importlib.util.spec_from_file_location("conf_cli", spec_path)
    mod = importlib.util.module_from_spec(s)
    s.loader.exec_module(mod)
    assert mod._weeks(spec) == want


def test_the_script_prints_the_record_so_far_beside_a_new_reading():
    """A number on its own invites the reading the 2026 line exists to
    prevent: the 2024-25 result must not be quoted without it."""
    spec_path = REPO / "scripts" / "65_confidence.py"
    s = importlib.util.spec_from_file_location("conf_cli2", spec_path)
    mod = importlib.util.module_from_spec(s)
    s.loader.exec_module(mod)
    labels = [r[0] for r in mod.REFERENCE]
    assert any("2026" in x for x in labels), "the flat season is missing"
    assert any("2025" in x for x in labels), "the strong season is missing"
    # The 2026 reading is the one that is near zero, and the test says so in
    # case somebody updates the table and drops the shape of the finding.
    by = {r[0]: r for r in mod.REFERENCE}
    flat = [v for k, v in by.items() if "2026" in k][0]
    assert abs(flat[1]) < 2.0 and flat[2] > 0.5, flat
