"""The fade-as-under measurement, and the thing that inflates it."""
import polars as pl

from src.evaluation import fade_unders as fu


def test_scratches_are_reported_separately_and_the_baseline_proves_why():
    """A player who does not play goes under every line he was priced at.

    Kept in, the baseline sits near 52.4% and the market looks tilted. Taken
    out it falls to about 50%, which is what a fair line should be — and that
    is the number that says the rest of the measurement can be trusted. The
    module must always report both, because the difference IS the finding.
    """
    rows = fu.evaluate("receiving_yards")
    if not rows:
        return
    both = {r["played_only"] for r in rows}
    assert both == {True, False}, "both views must be reported"

    base_all = [r for r in rows if r["cut"] is None and not r["played_only"]][0]
    base_played = [r for r in rows if r["cut"] is None and r["played_only"]][0]
    assert base_all["under_rate"] > base_played["under_rate"], (
        "removing non-participants should LOWER the under rate")
    assert 0.47 < base_played["under_rate"] < 0.53, (
        f"a fair market's baseline should sit near 50%, got "
        f"{base_played['under_rate']:.3f} — if it does not, the line being "
        f"graded is probably not the line that was bettable")


def test_one_line_per_player_week():
    """Alternates are one result, not four.

    The archive holds a player at 40.5, 45.5 and 50.5 yards. Counting each as
    a bet quadruples n and correlates every outcome inside a player-week, so
    the interval comes out twice as tight as the evidence supports.
    """
    b = fu.board("receiving_yards")
    if b.is_empty():
        return
    per = b.group_by(["season", "week", "pn"]).agg(pl.len().alias("n"))
    assert per["n"].max() == 1, (
        f"a player-week appears {per['n'].max()} times; alternates are not "
        f"being collapsed")


def test_a_push_is_not_a_loss():
    b = fu.board("receptions")
    if b.is_empty():
        return
    assert (b["receptions"] == b["point"]).sum() == 0


def test_the_main_line_is_the_balanced_one_and_is_reproducible():
    """Selecting the most-quoted point picked near-randomly across 7 yards.

    94% of archived points are quoted by exactly one book, so 88.4% of
    player-weeks had every candidate tied at one book and the tie broke on
    whichever row a parallel group-by emitted first. The tied points span a
    median of seven yards, which is most of the distance between a line a
    player beats and one he does not: the same cell measured 59.0% one run
    and 55.5% the next.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "src/evaluation/fade_unders.py").read_text()
    assert 'pl.len().alias("books")' not in src, (
        "book count is not a line-selection rule on this archive")
    assert '(pl.col("implied_prob") - 0.5).abs()' in src
    # `point` last in the sort, so the 6.6% that remain tied break the same
    # way every run.
    assert '"balance", "point"' in src


def test_projected_usage_is_lagged_and_actual_usage_is_never_filtered_on():
    """The whole result turns on which of the two the selection reads.

    `targets` and `carries` are post-game. Filtering on them measures a rate
    nobody can bet — 1-2 actual carries goes under 72% of the time, which is
    a fact about being ruled out, not about the market.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "src/evaluation/fade_unders.py").read_text()
    body = src[src.index("def evaluate_projected"):src.index("def usage_gradient")]
    for post in ('pl.col("targets")', 'pl.col("carries")', 'pl.col("played")'):
        assert post not in body, (
            f"{post} is a post-game quantity and cannot gate a bettable rate")
    assert 'pl.col("proj_usage")' in body
    # And the projection must be the lagged mean, not the current week's.
    assert "_avg_3g" in src


def test_projection_carries_only_part_of_the_usage_gradient():
    """If projecting usage reproduced actual usage, the earlier number stood.

    It does not, and the size of the gap is the finding: actual usage swings
    the under rate across roughly 75 points, the projection of it across
    under 15. Usage is far less predictable than it is decisive.
    """
    from src.evaluation.fade_unders import usage_gradient

    g = [r for r in usage_gradient("rushing_yards")
         if r.get("actual_n", 0) > 100 and r.get("proj_n", 0) > 100]
    if not g:
        import pytest
        pytest.skip("no archived rushing lines to grade")
    spread = lambda k: (max(r[k] for r in g) - min(r[k] for r in g))
    assert spread("actual_under") > 0.40, (
        "actual usage should swing the under rate enormously")
    assert spread("proj_under") < 0.20, (
        "if the projection swung this much, the look-ahead version was fine")
    assert spread("actual_under") > 2 * spread("proj_under")
