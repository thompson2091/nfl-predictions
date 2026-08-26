#!/usr/bin/env python3
"""Run the whole Sunday chain end to end, against a scratch record.

    python scripts/44_rehearse.py
    python scripts/44_rehearse.py --week 1 --keep

Every link in the weekly flow works. Nobody has ever seen them work *in a row*,
which is a different claim: the capture writes an archive the shortlist reads,
the shortlist writes picks the score reads, the bet log joins the archive on a
normalised name that has to match one written by a different module in a
different week. A chain of five links each tested alone is not a tested chain,
and week 1 is a bad time to find the seam.

So this drives the real scripts — not the functions they call — with
`NFL_RECORDS_DIR` pointed at a scratch directory. The two files under `data/`
are the only things in the project that cannot be regenerated, and a rehearsal
that appended August prices as week 1's tracked picks would corrupt the record
the whole forward test exists to build.

The capture is the one link it cannot exercise: the API serves current markets
only and a call costs a credit. That link is checked rather than run — key
present, week derived the same way the cron job derives it, archive holding
rows for the week, and how stale they are.

Exit status is the number of failed links, so it can be a preseason cron job
later if that ever seems worth doing.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, ".")

from src.utils.config import get_config  # noqa: E402

#: How old an archived quote can be before the rehearsal calls it stale. Three
#: weeks is generous — in season the gap between captures is days — and it is
#: here to catch a cron job that has silently stopped, not to grade a price.
STALE_DAYS = 21

PY_BIN = ".venv/bin/python" if Path(".venv/bin/python").exists() else sys.executable

_results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    _results.append((name, ok, detail))
    print(f"  [{'ok ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def run(args: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([PY_BIN, *args], capture_output=True, text=True,
                          env={**os.environ, **env})


def link_capture(season: int, week: int, markets: tuple[str, ...]) -> None:
    """The link that cannot be run: check what it would need and what it left."""
    print("\nCAPTURE — checked, not run (the API serves current markets only)")
    env_file = Path(".env")
    key = os.environ.get("ODDS_API_KEY") or (
        "ODDS_API_KEY" in env_file.read_text() if env_file.exists() else False)
    check("odds api key reachable", bool(key),
          "from .env" if not os.environ.get("ODDS_API_KEY") else "from environment")

    try:
        from src.ingest.capture_window import should_capture
        cap, why = should_capture("open")
        check("kickoff guard answers", True, why)
    except Exception as e:                                   # pragma: no cover
        check("kickoff guard answers", False, repr(e))

    import polars as pl

    from src.ingest.odds_history import HISTORY_PATH
    if not Path(HISTORY_PATH).exists():
        check("archive holds this week", False, "no odds_history.parquet")
        return
    h = pl.read_parquet(HISTORY_PATH).filter(
        (pl.col("season") == season) & (pl.col("week") == week))
    for market in markets:
        m = h.filter(pl.col("market") == market)
        if m.height == 0:
            check(f"archive holds {market}", False, "no rows for this week")
            continue
        last = max(m["captured_at"].to_list())
        age = (datetime.now(timezone.utc)
               - datetime.fromisoformat(last)).days
        check(f"archive holds {market}", age <= STALE_DAYS,
              f"{m.height} quotes, newest {age}d old ({last[:10]})")


def link_shortlist(season: int, week: int, markets: tuple[str, ...],
                   env: dict, picks_path: Path) -> None:
    """Shortlist runs, records its picks, and does not double them on a re-run."""
    print("\nSHORTLIST — run for real, recording into the scratch directory")
    for market in markets:
        r = run(["scripts/39_shortlist.py", "--week", str(week),
                 "--season", str(season), "--target", market], env)
        if not check(f"39_shortlist {market} exits clean", r.returncode == 0,
                     (r.stderr.strip().splitlines() or [""])[-1][:120]):
            continue
        # Only where a rule exists to reach. First TD deliberately has none:
        # it failed the same permutation control the fade passed, so a missing
        # section there is the design working, not the chain breaking.
        from src.evaluation.tracked_rules import rules_for
        want = bool(rules_for(market))
        named = "TRACKED \u2014" in r.stdout
        check(f"{market} reaches the tracked rules", named == want,
              "no rule is defined for this market" if not want else
              ("printed" if named else "no rule section printed"))

    import polars as pl

    if not picks_path.exists():
        check("picks recorded", True,
              "no rule named anybody on this board — nothing to record, the "
              "normal answer on a four-game August slate")
        _synthetic_idempotence(picks_path, season, week)
        return
    before = pl.read_csv(picks_path, infer_schema_length=0).height
    check("picks recorded", before > 0, f"{before} rows")

    for market in markets:
        run(["scripts/39_shortlist.py", "--week", str(week),
             "--season", str(season), "--target", market], env)
    after = pl.read_csv(picks_path, infer_schema_length=0).height
    check("re-running does not double the record", after == before,
          f"{before} -> {after}")


def _synthetic_idempotence(picks_path: Path, season: int, week: int) -> None:
    """Exercise the one guard an empty board would otherwise skip.

    Recording twice in a week must not double a rule's record, or the forward
    test can be inflated by re-running a script. On most preseason boards no
    rule fires, so there is nothing to re-run — and this is the link least
    worth leaving unexercised until the week it matters. Written on a made-up
    row, into the scratch file, and said out loud so nobody reads it as a pick.
    """
    from src.evaluation.tracked_rules import record

    row = [{"rule": "rehearsal", "player": "Nobody At All", "team": "XXX",
            "game": "XXX @ XXX", "odds": 700, "ours": 0.02, "book": 0.07,
            "edge_pp": -5.0}]
    kw = dict(season=season, week=week, market="anytime_td",
              recorded_on="1970-01-01", path=picks_path)
    first = record(row, **kw)
    again = record(row, **kw)
    check("re-running does not double the record", first == 1 and again == 0,
          f"synthetic row — no picks this week to use; wrote {first}, "
          f"re-wrote {again}")


def link_betlog(season: int, week: int, env: dict, log_path: Path) -> None:
    """A paper bet on each side, logged and scored, with the signs checked.

    Both sides of the same player at the same price, because the one thing that
    can silently be wrong here is the lay convention — and a back and a lay
    written at one price must score as exact opposites. A single logged bet
    would look fine either way up.
    """
    print("\nBET LOG — a paper bet on each side, then scored against the close")
    import polars as pl

    from src.ingest.odds_history import HISTORY_PATH
    h = pl.read_parquet(HISTORY_PATH).filter(
        (pl.col("season") == season) & (pl.col("week") == week)
        & (pl.col("market") == "anytime_td") & (pl.col("snapshot") == "close"))
    if h.height == 0:
        check("a name to log", False, "nothing archived for this week")
        return
    row = h.sort("captured_at").tail(1).row(0, named=True)
    player, close = row["player_name_raw"], float(row["odds"])
    # Deliberately not the archived price: a bet logged at the closing number
    # scores zero, and zero is the one value that hides a sign error.
    took = close + 40

    for side in ("yes", "no"):
        r = run(["scripts/40_betlog.py", "--add", "--season", str(season),
                 "--week", str(week), "--target", "anytime_td",
                 "--player", player, "--side", side, "--odds", str(took),
                 "--stake", "10", "--book", "rehearsal",
                 "--note", "paper — rehearsal"], env)
        check(f"log a {side} bet", r.returncode == 0,
              (r.stderr.strip().splitlines() or [""])[-1][:120])

    check("log written", log_path.exists(),
          f"{log_path.name}" if log_path.exists() else "no file")

    r = run(["scripts/40_betlog.py"], env)
    check("40_betlog scores", r.returncode == 0 and "BET LOG" in r.stdout,
          (r.stderr.strip().splitlines() or [""])[-1][:120])

    from src.evaluation.betlog import score
    s = score(path=log_path)
    scored = {(x["player"], x["side"]): x["clv_pp"] for x in s["rows"]
              if x["clv_pp"] is not None}
    y, n = scored.get((player, "yes")), scored.get((player, "no"))
    check("the bet joins an archived close", y is not None and n is not None,
          f"{s['scored']} of {s['n']} scored, {s['unmatched']} unmatched")
    if y is None or n is None:
        return
    check("a lay scores the other way up", abs(y + n) < 1e-9,
          f"back {y:+.2f}pp, lay {n:+.2f}pp")
    check("closing-line value is non-zero", abs(y) > 1e-9,
          f"took {took:+.0f}, closed {close:+.0f}")


def main(a) -> int:
    season = a.season
    week = a.week
    markets = tuple(a.markets)
    scratch = Path(a.dir) if a.dir else Path(tempfile.mkdtemp(prefix="rehearse_"))
    scratch.mkdir(parents=True, exist_ok=True)
    env = {"NFL_RECORDS_DIR": str(scratch)}

    print(f"REHEARSAL — {season} week {week}, records under {scratch}")
    print("  Nothing here touches data/tracked_picks.csv or data/bets_placed.csv.")

    link_capture(season, week, markets)
    link_shortlist(season, week, markets, env, scratch / "tracked_picks.csv")
    link_betlog(season, week, env, scratch / "bets_placed.csv")

    bad = [n for n, ok, _ in _results if not ok]
    print(f"\n{len(_results) - len(bad)}/{len(_results)} links clean")
    if bad:
        print("  failed: " + "; ".join(bad))
    else:
        print("  The chain runs end to end. What it does not prove is that the "
              "capture\n  will return anything in September — that one is the "
              "calendar's to answer.")

    if a.keep:
        print(f"\n  Scratch kept at {scratch}")
    elif not a.dir:
        shutil.rmtree(scratch, ignore_errors=True)
    return len(bad)


if __name__ == "__main__":
    cfg = get_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=cfg["seasons"]["predict_season"])
    ap.add_argument("--week", type=int, default=1)
    ap.add_argument("--markets", nargs="+", default=["anytime_td", "first_td"])
    ap.add_argument("--dir", help="scratch directory; default a temp one")
    ap.add_argument("--keep", action="store_true", help="do not delete it")
    sys.exit(main(ap.parse_args()))
