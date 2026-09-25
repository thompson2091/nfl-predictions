"""Splitting a bankroll across several bets, and what actually happens if you do.

Sizing cannot rescue a negative edge — it only changes how fast you find out. So
this module assumes the question "is there an edge" has already been answered by
`src/evaluation/rank_economics.py`, and answers the next one: given several bets
worth making, how much on each, and what does the range of outcomes look like.

Two things here are usually got wrong.

**Correlation.** The intuition is that backing three players in one game is not
three independent bets, because a shootout lifts all of them. Measured over
three seasons of residuals, that intuition is wrong for this market, and in an
interesting way:

    anytime TD  teammate correlation -0.024     (very slightly NEGATIVE)
    first TD    teammate correlation -0.046

Teammates compete for the same touchdowns, and that substitution effect just
outweighs the shared game total. First TD is more negative still, and
structurally so: exactly one player scores a game's first touchdown, so two
teammates cannot both be it. Both numbers are small enough that independent
draws are an excellent approximation here, so that is what we use — not from
convenience but because the measurement says the correction would be smaller
than the simulation noise. `fit_correlation` re-derives it, so if the market or
the model changes the assumption can be rechecked rather than trusted.

An opponents figure used to be quoted here too (+0.007). Nothing computes it —
it survived in prose after the code that produced it went, which is its own
small lesson about numbers in docstrings. `fit_correlation` measures teammates
and only teammates.

First touchdown is the exception and needs no estimate: exactly one player
scores, so our selections in a game are exactly mutually exclusive and that is
modeled directly.

**Mutual exclusivity.** Dutching — sizing stakes so any single winner returns
the same — is only defined when exactly one bet can win. That is true of first
touchdown (0.99 winners per game) and false of anytime touchdown (4.01, with
94.6% of games producing two or more). Applying it to anytime TD produces a
confident table of numbers that describes nothing. `dutch` therefore refuses to
run on a multi-winner market rather than returning a plausible-looking answer.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from src.prediction.bets import american_to_decimal
from src.utils.config import get_config

#: Methods that assume exactly one selection can win.
SINGLE_WINNER_ONLY = {"dutch"}


def is_single_winner(target_type: str) -> bool:
    """First touchdown has one winner per game; anytime touchdown has ~4."""
    return target_type == "first_td"


# --------------------------------------------------------------------------
# Allocation
# --------------------------------------------------------------------------

def allocate(bets: pl.DataFrame, bankroll: float, method: str = "kelly",
             kelly_fraction: float | None = None,
             max_frac: float = 0.25,
             prob_col: str = "probability",
             target_type: str = "anytime_td") -> pl.DataFrame:
    """Stakes for each bet under one allocation rule.

    - `equal`   — the baseline every other method has to beat.
    - `kelly`   — fractional Kelly, the only method that scales with edge *and*
                  price. Full Kelly assumes your probabilities are exact; a
                  slightly overconfident model goes broke on it.
    - `ev`      — stakes proportional to expected value. Ignores variance, so it
                  overbets longshots relative to Kelly.
    - `dutch`   — equal return whichever selection wins. Single-winner only.
    """
    if bets.height == 0:
        return bets.with_columns(pl.lit(0.0).alias("stake"))

    cfg = get_config().get("betting", {})
    if kelly_fraction is None:
        kelly_fraction = float(cfg.get("kelly_fraction", 0.25))

    if method in SINGLE_WINNER_ONLY and not is_single_winner(target_type):
        raise ValueError(
            f"'{method}' assumes exactly one selection can win. {target_type} "
            f"averages several winners per game, so equal-return sizing is not "
            f"defined for it — use 'kelly' or 'equal'."
        )

    df = bets.with_columns(
        pl.when(pl.col("odds") > 0).then(1.0 + pl.col("odds") / 100.0)
        .otherwise(1.0 + 100.0 / -pl.col("odds")).alias("dec")
    )
    p = df[prob_col].to_numpy()
    dec = df["dec"].to_numpy()
    b = dec - 1.0

    if method == "equal":
        w = np.ones(len(p))
    elif method == "dutch":
        # Equal gross return: stake_i proportional to 1/decimal_odds.
        w = 1.0 / dec
    elif method == "ev":
        w = np.maximum(p * b - (1 - p), 0.0)
    elif method == "kelly":
        w = np.maximum((p * b - (1 - p)) / b, 0.0) * kelly_fraction
    else:
        raise ValueError(f"unknown allocation method: {method}")

    if method == "kelly":
        # Kelly is already a fraction of bankroll, not a weight to normalize —
        # normalizing it would silently turn a "bet 3% of bankroll" signal into
        # "bet everything", which is how a conservative rule becomes a reckless
        # one.
        stakes = np.minimum(w, max_frac) * bankroll
        if stakes.sum() > bankroll:
            stakes *= bankroll / stakes.sum()
    elif method == "dutch":
        # No per-bet cap here. Equal gross return whichever selection wins *is*
        # the method; clipping one leg breaks that property and leaves a table
        # that still looks like dutching but no longer equalises anything.
        total = w.sum()
        stakes = (w / total * bankroll) if total > 0 else np.zeros(len(w))
    else:
        total = w.sum()
        stakes = (w / total * bankroll) if total > 0 else np.zeros(len(w))
        # With few selections the cap legitimately stops the whole bankroll
        # being deployed — two bets under a 25% cap put 50% to work, not 100%.
        # That is the risk control doing its job, not a bug to normalize away.
        stakes = np.minimum(stakes, max_frac * bankroll)

    return df.with_columns(pl.Series("stake", np.round(stakes, 2)))


# --------------------------------------------------------------------------
# Simulation
# --------------------------------------------------------------------------

def simulate(bets: pl.DataFrame, n_draws: int = 20_000, seed: int = 0,
             prob_col: str = "probability",
             target_type: str = "anytime_td") -> np.ndarray:
    """Draw outcomes for every bet. Returns (n_draws, n_bets) of 0/1.

    Single-winner markets are modeled exactly — one scorer per game, our
    selections mutually exclusive, the remaining probability belonging to
    someone we did not back. Multi-winner markets are drawn independently,
    which the measured teammate correlation of -0.024 justifies (see the module
    docstring; `fit_correlation` re-derives it).
    """
    n = bets.height
    if n == 0:
        return np.zeros((0, 0), dtype=bool)
    rng = np.random.default_rng(seed)
    p = np.clip(bets[prob_col].to_numpy(), 1e-9, 1 - 1e-9)

    if is_single_winner(target_type) and "game_id" in bets.columns:
        # Exactly one scorer per game. Our selections may not cover everyone, so
        # the leftover probability is "someone we did not back", and every one of
        # our bets in that game loses together.
        out = np.zeros((n_draws, n), dtype=bool)
        games = bets["game_id"].to_numpy()
        for g in np.unique(games):
            cols = np.flatnonzero(games == g)
            probs = p[cols]
            spare = max(0.0, 1.0 - probs.sum())
            wheel = np.concatenate([probs, [spare]])
            wheel = wheel / wheel.sum()
            picks = rng.choice(len(wheel), size=n_draws, p=wheel)
            for j, col in enumerate(cols):
                out[:, col] = picks == j
        return out

    # Independent draws, which preserves every player's marginal probability
    # exactly. An earlier version regenerated outcomes from the joint model's
    # Poisson-and-share structure; that reproduces the model's dependence but
    # drifts off the published marginals (expected winners came out 1.44 where
    # the probabilities summed to 1.59) because those probabilities carry the
    # fitted binomial conversion the Poisson draw does not.
    return rng.random((n_draws, n)) < p


def outcomes(bets: pl.DataFrame, n_draws: int = 20_000, seed: int = 0,
             prob_col: str = "probability",
             target_type: str = "anytime_td") -> dict:
    """The distribution of what this portfolio returns, not just its average.

    Expected profit alone hides everything that matters about a small bankroll:
    a portfolio can have positive expectation and still lose money most weeks.
    `p_profit` is usually the number a person actually wants.
    """
    if bets.height == 0 or "stake" not in bets.columns:
        return {}

    stake = bets["stake"].to_numpy()
    dec = bets["dec"].to_numpy() if "dec" in bets.columns else np.array(
        [american_to_decimal(o) for o in bets["odds"].to_list()])
    total = float(stake.sum())
    if total <= 0:
        return {}

    won = simulate(bets, n_draws, seed, prob_col, target_type)
    # Profit per draw: winners return stake*(dec-1), everything staked is lost.
    profit = (won * (stake * (dec - 1.0))).sum(axis=1) - (~won * stake).sum(axis=1)

    # Single-winner markets are modeled exactly; multi-winner ones are drawn
    # independently, which the measured correlations justify (see module docs).
    correlated = is_single_winner(target_type)
    return {
        "staked": total,
        "n_bets": bets.height,
        "expected_profit": float(profit.mean()),
        "expected_roi": float(profit.mean() / total * 100),
        "p_profit": float((profit > 0).mean()),
        "p_lose_all": float((profit <= -total + 1e-9).mean()),
        "worst": float(profit.min()),
        "best": float(profit.max()),
        "p05": float(np.percentile(profit, 5)),
        "median": float(np.percentile(profit, 50)),
        "p95": float(np.percentile(profit, 95)),
        "expected_winners": float(won.sum(axis=1).mean()),
        "correlated": correlated,
    }


def profit_by_winner(bets: pl.DataFrame) -> pl.DataFrame:
    """What the portfolio returns if each selection is the one that wins.

    Only meaningful when the selections are mutually exclusive — with several
    winners per game the "if #2 wins" row is not a scenario, because #1 and #3
    may have won too. `outcomes()` is the multi-winner equivalent.
    """
    stake = bets["stake"].to_numpy()
    dec = bets["dec"].to_numpy()
    total = stake.sum()
    return bets.with_columns([
        pl.Series("returns", np.round(stake * dec, 2)),
        pl.Series("net_if_wins", np.round(stake * dec - total, 2)),
        # How much this selection would need for the whole book to come out ahead.
        pl.Series("min_stake_to_profit", np.round(total / dec, 2)),
    ])


def compare(bets: pl.DataFrame, bankroll: float, target_type: str,
            prob_col: str = "probability",
            methods: tuple[str, ...] = ("equal", "kelly", "ev")) -> list[dict]:
    """Every allocation rule on the same bets, so the choice is visible."""
    out = []
    for m in methods:
        if m in SINGLE_WINNER_ONLY and not is_single_winner(target_type):
            continue
        try:
            sized = allocate(bets, bankroll, m, prob_col=prob_col,
                             target_type=target_type)
        except ValueError:
            continue
        stats = outcomes(sized, prob_col=prob_col, target_type=target_type)
        if stats:
            stats["method"] = m
            out.append(stats)
    return out


def fit_correlation(target_type: str = "anytime_td",
                    model: str | None = None) -> dict | None:
    """Measure how much teammates' outcomes actually move together.

    Residual covariance between players on the same team, after removing each
    player's own probability, scaled by the mean Bernoulli variance. Run this
    before assuming independence — it is what justifies the assumption, and it
    is cheap enough to recheck whenever the model changes.

    **One model's frames, not every file that matches.** This globbed
    `backtest_*.csv`, which matches the current model's frames AND the
    unprefixed ones left by an older run — and on first TD an `ensemble` set
    besides. Concatenated, every game-team appeared two or three times with a
    different `prob_calibrated` each time, so the covariance was largely each
    player correlating with his own duplicate. It reported **+0.022** where the
    single-model answer is **-0.024**: not a small error but a sign error, and
    the sign is the whole content of the number. The cover section applies this
    to teammate pairs, so it had been inflating the chance of teammates scoring
    together where the measurement says to deflate it.

    `n_team_games` did not notice, because grouping by (game_id, team) folds the
    duplicates into one larger group rather than making more of them.
    """
    from src.utils.config import production_model
    from src.utils.paths import get_path

    who = model or production_model(target_type)
    frames = []
    for path in sorted(get_path("output", target_type)
                       .glob(f"backtest_{who}_[0-9][0-9][0-9][0-9].csv")):
        d = pl.read_parquet(path) if path.suffix == ".parquet" else pl.read_csv(path)
        if {"scored", "prob_calibrated", "game_id", "team"} <= set(d.columns):
            frames.append(d)
    if not frames:
        return None

    df = pl.concat(frames, how="diagonal_relaxed").with_columns(
        (pl.col("scored") - pl.col("prob_calibrated")).alias("_r")
    )
    covs, vars_ = [], []
    for _, grp in df.group_by(["game_id", "team"]):
        r = grp["_r"].to_numpy()
        if len(r) < 2:
            continue
        total = r.sum()
        covs.append((total * total - (r * r).sum()) / (len(r) * (len(r) - 1)))
        p = grp["prob_calibrated"].to_numpy()
        vars_.append(float((p * (1 - p)).mean()))
    if not covs:
        return None

    cov, var = float(np.mean(covs)), float(np.mean(vars_))
    rho = cov / var if var > 0 else 0.0
    return {
        "target_type": target_type,
        "teammate_covariance": cov,
        "bernoulli_variance": var,
        "teammate_rho": rho,
        "independence_reasonable": abs(rho) < 0.05,
        "n_team_games": len(covs),
    }


def backtest_allocation(target_type: str, top_n: int = 3,
                        bankroll: float = 1000.0,
                        methods: tuple[str, ...] = ("flat", "equal", "kelly", "ev"),
                        prob_col: str = "prob_calibrated") -> list[dict]:
    """Walk the whole backtest game by game, staking each method, and compare.

    A single game's allocation table is a toy — you cannot tell whether Kelly
    beats flat staking from one slate. This runs each method across every game
    we hold prices for, compounding a real bankroll, and reports what a person
    actually feels: the final balance, the worst peak-to-trough fall along the
    way, and the longest losing run.

    `flat` stakes a fixed 1% of the *starting* bankroll on every bet and never
    compounds. It is the honest baseline: any method that cannot beat it is
    adding machinery, not returns.

    Ranks on `prob_col`, our own view rather than the published blend, for the
    reason set out in `src/evaluation/rank_economics.py` — blending toward the
    price is the act of giving up the disagreement you are betting on.
    """
    from src.evaluation.rank_economics import load_bets

    df = load_bets(target_type, rank_by=prob_col)
    if df is None or df.height == 0:
        return []
    df = df.filter(pl.col("rank") <= top_n).sort(["season", "week", "game_id"])

    out = []
    for method in methods:
        bank = bankroll
        peak, max_dd = bankroll, 0.0
        losing, longest_losing = 0, 0
        staked_total = 0.0
        games = 0

        for _, game in df.group_by(["season", "week", "game_id"],
                                   maintain_order=True):
            if bank <= 0:
                break
            games += 1
            # Never risk more than 5% of the bankroll on one game, so a single
            # slate cannot end the experiment and the drawdown figure stays
            # meaningful.
            budget = min(bank * 0.05, bank)
            if method == "flat":
                stake = np.full(game.height, bankroll * 0.01)
            else:
                sized = allocate(game, budget, method, prob_col=prob_col,
                                 target_type=target_type)
                stake = sized["stake"].to_numpy()

            dec = game["dec"].to_numpy() if "dec" in game.columns else np.array(
                [american_to_decimal(o) for o in game["odds"].to_list()])
            won = game["scored"].to_numpy().astype(bool)
            pnl = float((stake * (dec - 1.0))[won].sum() - stake[~won].sum())

            bank += pnl
            staked_total += float(stake.sum())
            peak = max(peak, bank)
            max_dd = max(max_dd, (peak - bank) / peak if peak > 0 else 0.0)
            losing = losing + 1 if pnl < 0 else 0
            longest_losing = max(longest_losing, losing)

        out.append({
            "method": method,
            "games": games,
            "final_bankroll": round(bank, 2),
            "profit": round(bank - bankroll, 2),
            "growth_pct": round((bank / bankroll - 1) * 100, 1),
            "staked": round(staked_total, 2),
            "roi_on_turnover": (round((bank - bankroll) / staked_total * 100, 1)
                                if staked_total > 0 else None),
            "max_drawdown_pct": round(max_dd * 100, 1),
            "longest_losing_streak": longest_losing,
            "busted": bank <= 0,
        })
    return out
