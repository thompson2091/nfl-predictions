"""How a book settles an over/under player prop, which is not how the card did.

Two defects, both in the direction of flattering the record, both measured on
the scorecard's own rows for 2026 weeks 1-4 on 2026-10-06:

**AN UNDER WAS PAID AT THE OVER'S PRICE.** `odds_history` carries one price per
(player, market, point) and it is the over — see `fade_unders` for the proof.
`week_history.ou_week` picks a side and hands back that one price either way,
so every under the model chose was settled at a number nobody offered for it.
`odds_books` has had BOTH sides, per book, since 2023, so the under's own price
exists and is used here. On catches, weeks 3-4, the break-even rate moves from
52.2% to 59.8% and the row's +$7.59 per $100 becomes -$8: the model takes
unders where the under is the juiced side, and the over's price hid it.

**A PLAYER WHO PLAYED AND RECORDED NOTHING WAS DROPPED.** Grading looks the
player up in `weekly_stats`, which only has a row for a player who did
something. A receiver who ran routes and drew no target has no row, so his
bet — usually a winning under — vanished from the record. A book settles it:
he played. 174 such rows over weeks 1-4, almost all on catches and receiving
yards.

**AND A PLAYER WHO DID NOT PLAY IS VOID**, as a book voids him. Participation is
read from `snap_counts` (any offensive snap). That is post-game information,
which is correct here: this is settlement, not prediction, and a book settles
on exactly that fact. A player missing from snap counts is void even if the
miss is a name mismatch — a wrong void is visible as a smaller n, a wrong
grade is not.

Both fixes are applied per row, before any collapse to one bet per
player-game, so every week range the card offers inherits them.
"""
from __future__ import annotations

import polars as pl

#: The over/under markets this settles. Touchdown props have no line and no
#: participation question of this shape.
OU_MARKETS = ("receptions", "receiving_yards", "rushing_yards", "passing_yards")

_PRICES: dict = {}
_SNAPS: dict = {}


def _norm(names: list[str]) -> list[str]:
    from src.prediction.predict import _norm_name_expr

    if not names:
        return []
    return (pl.DataFrame({"p": names}, schema={"p": pl.Utf8})
            .with_columns(_norm_name_expr("p").alias("n"))["n"].to_list())


def side_prices(season: int, snapshot: str = "close") -> pl.DataFrame:
    """Median price across books for each side of every over/under line.

    One row per (game_id, player_name_norm, market, point, side), `side`
    being the archive's `yes` (over) or `no` (under). In-play quotes are
    dropped BEFORE the per-book recency dedupe, because every dedupe in this
    repo otherwise prefers them (pipeline trap 8). The median rather than the
    best price, because the over side the card already uses is the
    consensus — the two sides have to be priced the same way or the
    comparison between them is a comparison of methods.
    """
    key = (season, snapshot)
    if key in _PRICES:
        return _PRICES[key]
    from src.ingest.odds_history import BOOKS_PATH as path
    from src.ingest.odds_history import drop_in_play, resolve_game_ids

    try:
        b = (pl.scan_parquet(path)
             .filter((pl.col("season") == season)
                     & (pl.col("snapshot") == snapshot)
                     & pl.col("market").is_in(list(OU_MARKETS)))
             .collect())
    except Exception:                                            # noqa: BLE001
        return pl.DataFrame()
    if b.is_empty():
        _PRICES[key] = b
        return b
    b = drop_in_play(resolve_game_ids(b))
    b = (b.sort("captured_at")
          .unique(subset=["game_id", "bookmaker", "player_name_norm",
                          "market", "point", "side"], keep="last"))
    # The median is taken in PROBABILITY, not in American odds. American odds
    # are discontinuous at even money — -105 and +105 are neighbours and
    # their median is 0, a price that pays infinity — so a line split across
    # books at evens produced a zero and a division by it.
    imp = (pl.when(pl.col("odds") > 0).then(100.0 / (pl.col("odds") + 100.0))
             .otherwise(-pl.col("odds") / (-pl.col("odds") + 100.0)))
    out = (b.with_columns(imp.alias("_p"))
            .group_by(["game_id", "player_name_norm", "market", "point", "side"])
            .agg(pl.col("_p").median().alias("_p"), pl.len().alias("n_books")))
    p = pl.col("_p")
    out = out.with_columns(
        pl.when(p >= 0.5).then(-100.0 * p / (1.0 - p))
          .otherwise(100.0 * (1.0 - p) / p).round(0).alias("odds")).drop("_p")
    _PRICES[key] = out
    return out


def participation(season: int) -> dict:
    """(game_id, normalized name) -> offensive snaps, for players who took one."""
    if season in _SNAPS:
        return _SNAPS[season]
    from src.prediction.predict import _norm_name_expr
    from src.utils.paths import get_path

    try:
        s = (pl.scan_parquet(get_path("raw") / "snap_counts.parquet")
             .filter(pl.col("season") == season)
             .select(["game_id", "player", "offense_snaps"]).collect())
    except Exception:                                            # noqa: BLE001
        return {}
    s = (s.with_columns(_norm_name_expr("player").alias("n"))
          .group_by(["game_id", "n"]).agg(pl.col("offense_snaps").max()))
    got = {(r["game_id"], r["n"]): r["offense_snaps"]
           for r in s.iter_rows(named=True)
           if (r["offense_snaps"] or 0) > 0}
    _SNAPS[season] = got
    return got


def settle_rows(season: int, market: str, rows: list[dict],
                prices: pl.DataFrame | None = None,
                played: dict | None = None) -> list[dict]:
    """Re-settle `week_history.ou_week` rows the way a book would.

    Returns new dicts; the input is not modified. For each row with a side:

    - `odds` becomes the price of the side taken. An under with no archived
      under price gets `odds=None` and drops out of any priced record rather
      than borrowing the over's number. `odds_over` keeps the old value.
    - a player with no snap and no stat line is `void=True`, `won=None`.
    - a player who played and has no stat line is graded at zero.

    Rows the market does not cover are passed through unchanged.
    """
    if market not in OU_MARKETS:
        return [dict(r) for r in rows]
    prices = side_prices(season) if prices is None else prices
    played = participation(season) if played is None else played
    under: dict = {}
    if prices is not None and not prices.is_empty():
        u = prices.filter((pl.col("market") == market) & (pl.col("side") == "no"))
        under = {(r["game_id"], r["player_name_norm"], float(r["point"])): r["odds"]
                 for r in u.iter_rows(named=True) if r["point"] is not None}
    names = _norm([r.get("player_name") or "" for r in rows])
    out = []
    for r, n in zip(rows, names):
        r = dict(r)
        side, line = r.get("side"), r.get("line")
        if side is None or line is None:
            out.append(r)
            continue
        r["odds_over"] = r.get("odds")
        if side == "under":
            r["odds"] = under.get((r.get("game_id"), n, float(line)))
        # A stat line is proof of playing on its own; snap counts are keyed by
        # a different source's spelling of the name and can miss a man who
        # plainly played.
        snapped = (r.get("game_id"), n) in played or r.get("actual") is not None
        r["void"] = not snapped
        if not snapped:
            r["won"] = None
        elif r.get("actual") is None:
            r["actual"] = 0.0
            r["won"] = (None if float(line) == 0.0
                        else (0.0 > float(line)) == (side == "over"))
        out.append(r)
    return out


def stat_lookup(season: int, week: int, stat: str):
    """A function from a board row's player to his `stat` that week, or None.

    **BY PLAYER ID, THEN BY THE BOARD'S OWN NAME, THEN BY THE BOX SCORE'S.**
    Every grader used to look the result up by `player_display_name`, which
    is the box score's spelling, while a board row carries the feature
    matrix's. They differ: "Kenny Gainwell" against "Kenneth Gainwell", and
    in 2026 "Jalen Cropper" against "Jalen Moreno-Cropper". A miss there is
    not a missing result — the snap counts, keyed by the board's spelling,
    say he played, so `settle_rows` and `forward_record` grade him at ZERO.
    That is a winning under that never happened.

    So the id comes first: from the row when it carries one, else from that
    week's feature matrix, which is where the board's names come from. The
    display name is the last resort, so nothing that matched before stops
    matching. A name two players share is never used for either step.
    """
    from src.utils.paths import get_path

    try:
        ws = (pl.scan_parquet(get_path("raw") / "weekly_stats.parquet")
              .filter((pl.col("season") == season) & (pl.col("week") == week))
              .select(["player_id", "player_display_name", stat]).collect())
    except Exception:                                            # noqa: BLE001
        return lambda name, player_id=None: None
    by_id = {i: v for i, v in zip(ws["player_id"].to_list(), ws[stat].to_list())
             if i is not None}
    shown = ws["player_display_name"].to_list()
    by_shown = {n: v for n, v in zip(shown, ws[stat].to_list())
                if n and shown.count(n) == 1}

    name_to_id: dict = {}
    try:
        f = (pl.scan_parquet(get_path("processed", "anytime_td") / "features.parquet")
             .filter((pl.col("season") == season) & (pl.col("week") == week))
             .select(["player_name", "player_id"]).unique().collect())
        ids = f.group_by("player_name").agg(pl.col("player_id").n_unique().alias("n"),
                                             pl.col("player_id").first())
        name_to_id = {r["player_name"]: r["player_id"]
                      for r in ids.filter(pl.col("n") == 1).iter_rows(named=True)}
    except Exception:                                            # noqa: BLE001
        pass

    # A SNAP WITH NO STAT IS A ZERO, as a book settles it. nflverse writes no
    # weekly row for a player who played and recorded nothing, so these legs
    # stayed pending forever: 163 of 2,504 frozen rows in weeks 2-6 (audit
    # 2026-10-19). `safe_legs.game_logs` is the snap-backed log, keyed by id,
    # that already reads them as zero; it is the last resort, by id only.
    played: dict = {}
    try:
        from src.evaluation.safe_legs import game_logs

        g = game_logs().filter((pl.col("season") == season)
                               & (pl.col("week") == week))
        if stat in g.columns:
            played = dict(zip(g["player_id"].to_list(), g[stat].to_list()))
    except Exception:                                            # noqa: BLE001
        pass

    def get(name, player_id=None):
        # A weekly row can exist with this stat NULL (a receiver's passing
        # yards); that is the same "played, recorded none" and falls through.
        pid = player_id or name_to_id.get(name)
        got = by_id.get(pid) if pid is not None else None
        if got is None:
            got = by_shown.get(name)
        if got is None and pid is not None:
            got = played.get(pid)
        return got
    return get
