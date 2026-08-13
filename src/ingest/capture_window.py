"""Is a kickoff near enough that an odds snapshot is worth an API credit?

The capture schedule fires 15 close slots a week, derived from the season's
kickoff waves (`scripts/25_odds_schedule.py`). Most weeks only some of them have
a game behind them: the league flexes games between windows all season, and
Thanksgiving, Christmas and the Wednesday openers exist in some seasons and not
others. Regenerating the schedule weekly would make the plists correct and the
job fragile, so instead every slot fires and this decides.

The asymmetry that shapes the logic: skipping a capture loses a price that
cannot be bought back at any cost, while capturing needlessly costs one API
credit. So every failure mode here resolves toward capturing — an unreadable
schedule, an unparseable kickoff, a clock in the wrong timezone.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl

from src.utils.config import get_config
from src.utils.paths import get_path


def window_for(snapshot: str, cfg: dict | None = None) -> timedelta:
    """How far ahead a kickoff may be and still justify this snapshot."""
    cfg = cfg if cfg is not None else get_config().get("odds_capture", {})
    if snapshot == "open":
        return timedelta(days=float(cfg.get("open_window_days", 7)))
    return timedelta(hours=float(cfg.get("close_window_hours", 4)))


def kickoffs(schedule: pl.DataFrame | None = None) -> list[datetime]:
    """Every kickoff in the schedule, as naive local datetimes.

    Kickoff times are US Eastern and launchd fires in local time. Treating both
    as naive local is exact on an Eastern machine and off by the offset
    elsewhere — which the 30-minute lead absorbs for anywhere within a few hours
    of Eastern, and which would need a real timezone if this ever ran in CI.
    """
    if schedule is None:
        schedule = pl.read_parquet(get_path("raw") / "schedules.parquet")
    if "gameday" not in schedule.columns or "gametime" not in schedule.columns:
        raise ValueError("schedule has no gameday/gametime columns")
    s = schedule.filter(pl.col("gameday").is_not_null()
                        & pl.col("gametime").is_not_null())
    out = []
    for day, time in zip(s["gameday"].cast(str).str.slice(0, 10), s["gametime"]):
        try:
            out.append(datetime.fromisoformat(f"{day}T{str(time)[:5]}:00"))
        except ValueError:
            # One malformed row must not decide the whole week. Dropping it is
            # safe because the *next* kickoff governs, and a real kickoff will
            # still be found if one is near.
            continue
    return sorted(out)


def should_capture(snapshot: str, now: datetime | None = None,
                   schedule: pl.DataFrame | None = None,
                   cfg: dict | None = None) -> tuple[bool, str]:
    """(capture?, one line saying why) — the line is logged either way."""
    now = now or datetime.now()
    window = window_for(snapshot, cfg)
    try:
        ahead = [k for k in kickoffs(schedule) if k >= now]
    except Exception as e:  # unreadable schedule: capture rather than lose a week
        return True, f"could not read the schedule ({e}) — capturing anyway"

    if not ahead:
        return False, f"no kickoffs ahead of {now:%F %H:%M} — nothing to capture"

    delta = ahead[0] - now
    when = f"{ahead[0]:%a %F %H:%M}"
    if delta > window:
        return False, (f"next kickoff {when} is {_short(delta)} away, outside "
                       f"the {_short(window)} {snapshot} window — skipping, "
                       "no credits spent")
    return True, f"next kickoff {when}, {_short(delta)} away — capturing"


def _short(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d{hours}h"
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"
