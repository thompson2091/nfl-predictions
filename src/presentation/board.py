"""What the board says about a row, and how money is phrased.

Pure functions over the fitted artifacts and the board frame. No Streamlit, no
file reads — hand them a `rank_economics` dict and a DataFrame and they return
labels, tables and prose. That is the whole point of the module: the tier
thresholds decide what the app is allowed to claim, and a claim about money
should be testable without standing up a browser.
"""
from __future__ import annotations

import pandas as pd

#: How each tier reads on the board. Two levels and a blank — no letter grade,
#: because a letter beside a player's name reads as a promise about that player
#: and roughly half of even the strongest tier loses.
TIER_LABEL = {"strong": "Strong", "standard": "Standard", "fade": "Fade"}

#: The statistician's verdict, said out loud. "Indistinguishable from zero" is
#: precise and means nothing to most readers; "too close to call" means the same
#: thing and survives being read quickly.
VERDICT_PLAIN = {
    "positive": "Made money",
    "negative": "Lost money",
    "indistinguishable from zero": "Too close to call",
    "no bets": "—",
}


# ── Money and odds ─────────────────────────────────────────────────────────
#
# Two formatters, two jobs, and they used to share the name `_money`. The
# second definition silently replaced the first at import; the file was correct
# only because every caller of one happened to sit above the other definition
# in a script that executes top to bottom. Reordering anything turned
# "+$12.00" into "$112 back on every $100" with no error. Hence two names.


def american(o) -> str:
    """A price as a signed American number, or an em dash if there isn't one."""
    try:
        return f"{int(o):+d}"
    except (TypeError, ValueError):
        return "—"


def signed_money(x: float, places: int = 2, escape: bool = True) -> str:
    """A signed dollar amount, sign outside the symbol: `+$12.00`.

    `escape` because Streamlit reads a matched pair of dollar signs in markdown
    as LaTeX — but a metric value is plain text, where the escape would print.
    """
    sym = "\\$" if escape else "$"
    return f"{'+' if x >= 0 else '-'}{sym}{abs(x):,.{places}f}"


def roi_money(roi_pct: float | None) -> str:
    """A return, phrased the way someone who does not bet would think about it.

    "+12.0% ROI" is a unit of measurement most people have never used. "$112
    back on every $100" is the same fact and needs no translation.

    Dollar signs are escaped because Streamlit's markdown treats a matched pair
    of them as inline LaTeX, which silently turns "$112 back on every $100" into
    typeset mathematics.
    """
    if roi_pct is None:
        return "—"
    return f"\\${100 + roi_pct:,.0f} back on every \\$100 staked"


# ── Row-level verdicts ─────────────────────────────────────────────────────


def confidence(edge_pp: float, lo: float, hi: float) -> str:
    """Label what the model is doing, not how sure it is.

    These read as verdicts, so the wording matters. Calling a large gap "Low
    confidence" said the opposite of what the data shows — on those players our
    estimate has been 12-24% closer to reality than the bookmaker's.
    """
    d = abs(edge_pp) / 100.0
    if d <= lo:
        return "Matches book"
    if d <= hi:
        return "Leans"
    return "Strong call"


def preblend_columns_differ(frame) -> bool:
    """Do Bet # / Bet edge say anything the # / Difference columns do not?

    False for a market that is not blended: there the published number *is* the
    model's, so the two pairs are identical and showing both reads as a
    distinction the market does not have. The renderer and the caption that
    describes it both ask this, so the prose cannot end up describing columns
    that were not drawn — which is exactly what it did on the First TD board.
    """
    needed = {"bet_rank", "model_edge_pp", "game_rank", "edge_pp"}
    if not needed <= set(frame.columns):
        return False
    return bool(not frame["bet_rank"].equals(frame["game_rank"])
                or (frame["model_edge_pp"] - frame["edge_pp"]).abs().max() > 0.05)


def highlight_tier(frame, rule: dict):
    """Label each row with the measured tier it falls into, or blank.

    Every threshold comes from `fit_highlight_tiers`, so a re-run on new seasons
    moves the marks rather than leaving them describing a model that no longer
    exists. A tier that stops clearing its bar simply disappears from the file
    and stops being marked here.
    """
    h = rule.get("tiers")
    if not h or not (h.get("tiers") or h.get("fade")):
        return ""

    names = {t["tier"] for t in h.get("tiers") or []}
    edge = frame["model_edge_pp"]
    eligible = ((frame["bet_rank"] <= h["max_rank"])
                & (edge >= h["edge_cut"] * 100))
    floor = h.get("exclude_below_odds")
    if floor is not None:
        eligible &= frame["odds"] >= floor

    big = edge >= h["big_edge"] * 100
    out = pd.Series("", index=frame.index, dtype="object")
    if "standard" in names:
        out[eligible & ~big] = TIER_LABEL["standard"]
    if "strong" in names:
        out[eligible & big] = TIER_LABEL["strong"]

    # Fade carries no rank or price filter, unlike the backing tiers. The point
    # of it is a player the book rates and we do not, and those are often well
    # down our own list — a rank filter would discard the clearest cases.
    fade = h.get("fade")
    if fade:
        out[edge <= fade["edge_at_most"] * 100] = TIER_LABEL["fade"]
    return out


# ── The tier legend and its prose ──────────────────────────────────────────


def ex_top10(tier: dict) -> str:
    """What a tier returned with its ten largest wins removed.

    The honest companion to the headline. A tier can read +21.7% and be almost
    entirely ten lucky afternoons — first TD's strong tier drops to +1.2% this
    way — and no confidence interval conveys that, because the interval is wide
    for the same reason the number is high.
    """
    v = tier.get("roi_ex_top10")
    if v is None:
        return "—"
    return f"${100 + v:,.0f} per $100"


def tier_legend(rule: dict | None) -> pd.DataFrame | None:
    """Every value the Worth backing column can take, and what earns it.

    Built from the fitted tiers rather than written out, so the legend cannot
    drift from the rule it describes. The blank row is included deliberately:
    it covers four quite different situations, and reading a blank as "we don't
    like him" is wrong for three of them.
    """
    h = (rule or {}).get("tiers") or {}
    if not (h.get("tiers") or h.get("fade")):
        return None

    by = {t["tier"]: t for t in h.get("tiers") or []}
    floor = h.get("exclude_below_odds")
    qualifier = (f", priced +{floor} or longer" if floor else "")
    rows = []

    if "strong" in by:
        t = by["strong"]
        rows.append({
            "Label": "Strong",
            "What earns it": (f"Bet edge of {h['big_edge'] * 100:.0f} points or "
                              f"more, Bet # {h['max_rank']} or better{qualifier}"),
            "What it means": "We disagree with the book by a lot, in the direction you can back",
            "Historically": f"${100 + t['roi']:,.0f} per $100 staked",
            "Without the 10 biggest wins": ex_top10(t),
            "About": f"{t['bets_per_week']:.0f} a week",
        })
    if "standard" in by:
        t = by["standard"]
        rows.append({
            "Label": "Standard",
            "What earns it": (f"Bet edge between {h['edge_cut'] * 100:.0f} and "
                              f"{h['big_edge'] * 100:.0f} points, Bet # "
                              f"{h['max_rank']} or better{qualifier}"),
            "What it means": "A real but modest disagreement — the same idea as Strong, weaker",
            "Historically": f"${100 + t['roi']:,.0f} per $100 staked",
            "Without the 10 biggest wins": ex_top10(t),
            "About": f"{t['bets_per_week']:.0f} a week",
        })
    if h.get("fade"):
        f = h["fade"]
        rows.append({
            "Label": "Fade",
            "What earns it": (f"Bet edge of {abs(f['edge_at_most']) * 100:.0f} "
                              f"points or more *below* the book, any rank or price"),
            "What it means": "The book rates this player and we strongly do not. Not a bet — a warning",
            "Historically": (f"book prices them ~{f['implied_pct']:.0f}%, "
                             f"~{f['actual_pct']:.0f}% actually score"),
            "Without the 10 biggest wins": "—",
            "About": f"{f['bets_per_week']:.0f} a week",
        })
    rows.append({
        "Label": "(blank)",
        "What earns it": "Everything else",
        "What it means": ("Not a view — it covers four different things: we rate "
                          "them slightly lower, the edge is too small, they are "
                          "outside the top few, or the price is too short"),
        "Historically": "—",
        "Without the 10 biggest wins": "—",
        "About": "most of the board",
    })
    return pd.DataFrame(rows)


def tier_summary(rule: dict | None) -> str:
    """One sentence naming each tier and what it returned, for the board caption."""
    h = (rule or {}).get("tiers") or {}
    by = {t["tier"]: t for t in h.get("tiers", [])}
    if not by:
        return "."
    bits = []
    if "strong" in by:
        bits.append(f"**Strong** (\\${100 + by['strong']['roi']:,.0f} per "
                    f"\\$100, ~{by['strong']['bets_per_week']:.0f}/week)")
    if "standard" in by:
        bits.append(f"**Standard** (\\${100 + by['standard']['roi']:,.0f} per "
                    f"\\$100, ~{by['standard']['bets_per_week']:.0f}/week)")
    if h.get("fade"):
        f = h["fade"]
        bits.append(f"**Fade** — a warning, not a bet (book prices them "
                    f"~{f['implied_pct']:.0f}%, ~{f['actual_pct']:.0f}% score)")
    if not bits:
        return "."
    return ": " + ", ".join(bits[:-1]) + (" and " if len(bits) > 1 else "") + bits[-1] + "."


def tier_help(region: dict | None) -> str:
    """The tooltip for the highlight column, written from the measured tiers."""
    h = (region or {}).get("tiers") or {}
    if not (h.get("tiers") or h.get("fade")):
        return "Measured profitability. Nothing is marked on this market."

    by = {t["tier"]: t for t in h.get("tiers") or []}
    lines = [
        f"Marked from a rule fitted to {region['games']:,} games in "
        f"{region['span']} — thresholds measured, not chosen by hand. The "
        f"backing tiers need **Bet #** {h['max_rank']} or better and a positive "
        f"**Bet edge**"
        + (f", at a price of +{h['exclude_below_odds']} or longer"
           if h.get("exclude_below_odds") else "") + ".\n",
    ]
    if "strong" in by:
        t = by["strong"]
        lines.append(
            f"**Strong** — bet edge of {h['big_edge'] * 100:.0f} points or "
            f"more. Returned \\${100 + t['roi']:,.0f} per \\$100 staked, about "
            f"{t['bets_per_week']:.0f} a week."
        )
    if "standard" in by:
        t = by["standard"]
        lines.append(
            f"**Standard** — a smaller disagreement. Returned "
            f"\\${100 + t['roi']:,.0f} per \\$100, about "
            f"{t['bets_per_week']:.0f} a week."
        )
    fade = h.get("fade")
    if fade:
        lines.append(
            f"**Fade** — we rate them at least "
            f"{abs(fade['edge_at_most']) * 100:.0f} points *below* the book. "
            f"The book prices this group around "
            f"{fade['implied_pct']:.0f}% and about "
            f"{fade['actual_pct']:.0f}% of them actually score, in every "
            f"season measured. **This is a warning, not a bet** — these "
            f"markets only sell the Yes side, so there is nothing to back. It "
            f"means: whatever else you do this week, not this one."
        )

    # "Fading" is not a picked slope any more. The question it is really asking
    # is whether the most recent season sits below what the pooled estimate
    # says to expect, and the bootstrap interval already answers that. The
    # picked version (-5 points a year) fired on a decline that turned out to be
    # in-sample contamination rather than a fading edge — a warning built on a
    # threshold nobody measured, describing an artifact.
    for t in h.get("tiers") or []:
        per = t.get("per_season") or []
        if len(per) < 2 or t.get("lo") is None:
            continue
        latest = per[-1]
        if (latest.get("roi") or 0) < t["lo"]:
            lines.append(
                f"\n:material/warning: **The most recent season is below the "
                f"range.** The {t['tier']} group returned "
                f"{latest['roi']:+.0f}% in {latest['season']}, under the "
                f"{t['lo']:+.0f}% floor of its own interval. One season is not "
                f"a trend, but it is the first thing that would show if this "
                f"stopped working."
            )
            break
    if by:
        hit = by.get("strong", by.get("standard", {})).get("hit_pct", 0)
        lines.append(
            f"\n**A fact about the group, not the player.** About "
            f"{100 - hit:.0f}% of even the marked bets lose. This is not a "
            f"recommendation to bet."
        )
    return "\n\n".join(lines)


# ── Whole-slate arithmetic ─────────────────────────────────────────────────


def slate_expectation(frame, rule: dict | None) -> str | None:
    """Flat $100 a bet across everything we'd back this week, added up.

    A per-row EV column cannot show this, and row-by-row is exactly where the
    reading goes wrong. Ten bets we rate 40-50% win four or five of themselves,
    which reads like a good afternoon — and still lose money whenever the
    winners are priced short and the losers long. One favourite at -185 we rate
    43% costs about a third of its stake, more than several modest longshots
    make back. Expected winners and expected profit move independently, and the
    only way to see that is to add the payouts up rather than leaving it as an
    exercise for the reader.

    Deliberately computed over the whole week's marked plays, not the filtered
    view, so narrowing the board to one game does not quietly re-scope the
    slate. Returns None where no rule was fitted — a market with no measured
    edge has no plays to total up.
    """
    if not rule or "ev_model_pct" not in frame.columns:
        return None
    tiers = highlight_tier(frame, rule)
    if not isinstance(tiers, pd.Series):
        return None

    marked = frame[tiers.isin([TIER_LABEL["strong"], TIER_LABEL["standard"]])]
    # A player who is Out is not a bad bet, it is a settled loss, and including
    # one in a total of expected money overstates it by the whole stake.
    dropped = 0
    if "is_blocked" in marked.columns:
        out = marked["is_blocked"].fillna(False).astype(bool)
        dropped, marked = int(out.sum()), marked[~out]

    n = len(marked)
    if n == 0:
        return ("**Nothing on this week's board clears the bar.** That is the "
                "position the measured rule takes most weeks — no play is a "
                "result, not a gap.")

    staked = n * 100
    winners = float(marked["prob_bet"].sum()) if "prob_bet" in marked.columns else None
    profit = float(marked["ev_model_pct"].sum())

    parts = [
        f"**A flat \\$100 on each of the {n} marked "
        f"{'play' if n == 1 else 'plays'}** — \\${staked:,} staked, "
        f"expected return **{signed_money(profit)}** "
        f"(\\${staked + profit:,.2f} back, {profit / staked * 100:+.1f}% on "
        f"turnover) if our numbers are right."
    ]
    if winners is not None:
        parts.append(
            f"We expect **{winners:.1f} of the {n}** to score"
            + (f" — and the two numbers move independently. A slate can win "
               f"half its bets and still lose money, when the winners are "
               f"priced short and the losers long."
               if profit < 0 and winners / n >= 0.35 else ".")
        )
    if dropped:
        parts.append(
            f"Excludes {dropped} marked "
            f"{'player' if dropped == 1 else 'players'} ruled out by the "
            f"injury report."
        )
    parts.append(
        "Priced at the consensus in **Odds** and measured on our pre-blend "
        "number, the same basis as **Expected on \\$100**. What sets like this "
        "have *actually* returned is in **Betting reality**."
    )
    return " ".join(parts)


# ── Profitability tables ───────────────────────────────────────────────────


def roi_rows(rows: list[dict], key: str, label: str) -> pd.DataFrame:
    """One ROI table, however it was sliced — by rank, by season, by price."""
    return pd.DataFrame([{
        label: r.get(key),
        "Bets": r["n"],
        "Hit": r["hit_pct"] / 100,
        "Break-even": r["breakeven_pct"] / 100,
        "Odds": r["median_odds"],
        "ROI": r["roi"] / 100 if r["roi"] is not None else None,
        "95% interval": (f"{r['lo']:+.1f}% to {r['hi']:+.1f}%"
                         if r["lo"] is not None else "—"),
        "Verdict": ("Too few bets to say" if r.get("thin")
                    else VERDICT_PLAIN.get(r["verdict"], r["verdict"])),
    } for r in rows])


def bet_guidance(econ: dict, n: int) -> tuple[list[str], list[str]]:
    """Plain do / do-not advice, derived from the tables rather than typed out.

    Every line here quotes a number the page also shows, so the advice cannot
    drift away from the evidence when the backtest is re-run on new seasons.
    """
    h = econ["headline"]
    proven = bool(h and h["verdict"] == "positive")
    ranks = econ.get("by_rank") or []
    buckets = econ.get("by_odds_bucket") or []
    seasons = econ.get("by_season") or []

    deepest = max((r["rank"] for r in ranks if r["verdict"] == "positive"),
                  default=0)
    worst_band = min(buckets, key=lambda r: r["roi"]) if buckets else None
    good_seasons = sum(1 for r in seasons if r["verdict"] == "positive")

    comparison = {(r["ranked_by"], r["top_n"]): r
                  for r in econ.get("blend_comparison") or []}
    model_row = comparison.get(("model only (pre-blend)", n))
    blend_row = comparison.get(("blended (published)", n))

    do: list[str] = []
    dont: list[str] = []

    if proven:
        depth_phrase = (
            "Only the top-rated player in a game held up on their own"
            if deepest == 1 else
            f"Ranks 1 to {deepest} each held up on their own"
            if deepest > 1 else
            "No individual rank held up on its own, which is worth knowing"
        )
        do.append(
            f"**Stick to the top of each game.** Backing our top {n} returned "
            f"{roi_money(h['roi'])}. {depth_phrase}; past that the advantage fades."
        )
        # What "profitable in N of M seasons" means depends entirely on N. The
        # copy used to call any N "the reason to take it seriously", which read
        # as an endorsement of a model that had worked once in three years.
        if good_seasons == len(seasons):
            do.append(
                f"**Treat it as {len(seasons)} seasons of evidence, not a "
                f"promise.** It was profitable in every season separately, "
                f"which is the reason to take it seriously — and still only "
                f"{econ['games']:,} games."
            )
        else:
            season = "season" if good_seasons == 1 else "seasons"
            do.append(
                f"**Be sceptical of the headline.** The pooled figure is "
                f"positive, but it was only profitable in {good_seasons} "
                f"{season} out of {len(seasons)}. A strategy that works in one "
                f"year and not the next is usually one year of luck, not an "
                f"edge — the season-by-season table below is the honest view."
            )
        if model_row and blend_row:
            gap = model_row["roi"] - blend_row["roi"]
            do.append(
                f"**Use the model's own number, not the one on the board.** The "
                f"board blends our estimate with the bookmaker's to be more "
                f"accurate. For betting that costs about {gap:.0f} points of "
                f"return, because agreeing with the price is the opposite of "
                f"having a reason to bet."
            )
        do.append(
            "**Stake small and stake the same each time.** No staking scheme "
            "turns a bad bet good. Sizing only changes how quickly you find out."
        )
    else:
        do.append(
            "**Do not bet this market yet.** Follow it on paper for a season "
            "and see whether the pattern survives. Nothing is lost by waiting."
        )
        do.append(
            "**Look at the other market instead.** The two are measured the "
            "same way and only one of them currently clears its prices."
        )

    if worst_band:
        dont.append(
            f"**Do not chase the big prices.** Every price band loses money "
            f"backed blindly; the longest ones are the worst, at "
            f"{roi_money(worst_band['roi'])} in the {worst_band['bucket']} band. "
            f"We sort those players well — that is not the same as them being "
            f"good bets."
        )
    dont.append(
        "**Do not bet more because a week went badly.** Long runs of losing "
        "games are normal and mean nothing on their own — the staking section "
        "below shows how long they actually got."
    )
    dont.append(
        "**Do not treat this as income.** It is a small advantage measured at "
        "prices that had already closed. Money you would mind losing does not "
        "belong here."
    )
    return do, dont
