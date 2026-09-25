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
