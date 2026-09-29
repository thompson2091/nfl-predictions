"""Does a recent-seasons model beat an all-seasons one? IT DOES NOT.

    python scripts/63_recency_window.py [half_life_seasons]

Walk-forward from 2019, same features, same hyperparameters, out-of-sample on
1,918 games. Three windows:

  all     every prior season, unweighted        (what ships today)
  last2   the two most recent prior seasons only
  decay   every prior season, exponentially decayed by age

**THE ANSWER, 2026-09-29.** Paired per game against `all`, positive is worse:

  window          margin MAE   total MAE   paired margin      paired total
  all                 10.702      10.788               -                 -
  last2               10.968      11.343  +0.266 (t=+2.63)  +0.555 (t=+5.33)
  decay hl=1.5        10.789      10.763  +0.087 (t=+1.22)  -0.025 (t=-0.35)
  decay hl=3          10.752      10.808  +0.050 (t=+0.81)  +0.020 (t=+0.30)
  decay hl=6          10.712      10.787  +0.010 (t=+0.17)  -0.001 (t=-0.02)

Monotone in the wrong direction: the harder old seasons are discounted, the
worse it gets. `last2` is decisively worse on both quantities. Every decay
setting is indistinguishable from `all`, and converges to it as the half-life
lengthens — which is the shape of a knob that does nothing.

PAIRED, on the same games, because season-to-season noise dwarfs the gap: the
unpaired MAEs differ by less than a third of a point and the paired test is
what makes `last2` significant and the decays not.

So the training window stays every prior season, unweighted, and
`test_the_training_window_is_every_prior_season` holds it there. Re-run this
before changing it.
"""
import sys
import numpy as np
import polars as pl

sys.path.insert(0, ".")
import lightgbm as lgb
from src.models.game_model import (feature_columns, leaky_columns, team_games)

HALF_LIFE = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
FIRST = 2019

d = team_games()
feats = feature_columns(d)
feats = [c for c in feats if c not in set(leaky_columns(d, feats))]
print(f"{d.height} team-games, {len(feats)} features, "
      f"seasons {d['season'].min()}-{d['season'].max()}")

def fit_predict(tr, te, w=None):
    m = lgb.LGBMRegressor(n_estimators=400, learning_rate=0.05,
                          num_leaves=31, min_child_samples=40,
                          subsample=0.8, colsample_bytree=0.6,
                          random_state=0, verbose=-1)
    m.fit(tr.select(feats).to_numpy(), tr["points"].to_numpy(),
          sample_weight=w)
    return m.predict(te.select(feats).to_numpy())

def game_level(te, pred):
    te = te.with_columns(pl.Series("pred", pred))
    home, away = pl.col("home") == 1, pl.col("home") == 0
    return te.group_by("game_id").agg([
        pl.col("season").first().alias("season"),
        (pl.col("pred").filter(home).first()
         - pl.col("pred").filter(away).first()).alias("m_hat"),
        pl.col("pred").sum().alias("t_hat"),
        (pl.col("points").filter(home).first()
         - pl.col("points").filter(away).first()).alias("m_act"),
        pl.col("points").sum().alias("t_act"),
    ])

WINDOWS = ["all", "last2", "decay"]
out = {w: [] for w in WINDOWS}
for season in sorted(s for s in d["season"].unique() if s >= FIRST):
    prior = d.filter(pl.col("season") < season)
    te = d.filter(pl.col("season") == season)
    if te.is_empty() or prior.height < 500:
        continue
    for w in WINDOWS:
        if w == "all":
            tr, sw = prior, None
        elif w == "last2":
            tr = prior.filter(pl.col("season") >= season - 2)
            sw = None
            if tr.height < 500:
                continue
        else:
            tr = prior
            age = (season - tr["season"].to_numpy()).astype(float)
            sw = 0.5 ** (age / HALF_LIFE)
        out[w].append(game_level(te, fit_predict(tr, te, sw)))

print(f"\nhalf-life {HALF_LIFE} seasons\n")
hdr = f"{'window':<8}{'games':>7}{'margin MAE':>12}{'margin RMSE':>13}" \
      f"{'total MAE':>11}{'total RMSE':>12}"
print(hdr); print("-" * len(hdr))
res = {}
for w in WINDOWS:
    if not out[w]:
        continue
    g = pl.concat(out[w])
    me = (g["m_hat"] - g["m_act"]).to_numpy()
    tv = (g["t_hat"] - g["t_act"]).to_numpy()
    res[w] = (g, me, tv)
    print(f"{w:<8}{g.height:>7}{np.abs(me).mean():>12.3f}"
          f"{np.sqrt((me**2).mean()):>13.3f}"
          f"{np.abs(tv).mean():>11.3f}{np.sqrt((tv**2).mean()):>12.3f}")

# PAIRED, on the same games, because season-to-season noise dwarfs the gap.
base_g, base_m, base_t = res["all"]
print("\npaired against 'all', per game (negative = better):")
for w in WINDOWS[1:]:
    if w not in res:
        continue
    g, me, tv = res[w]
    j = base_g.select(["game_id", "m_hat", "t_hat"]).join(
        g.select(["game_id", "m_hat", "t_hat"]), on="game_id", suffix="_b")
    j = j.join(base_g.select(["game_id", "m_act", "t_act"]), on="game_id")
    dm = (np.abs(j["m_hat_b"] - j["m_act"]).to_numpy()
          - np.abs(j["m_hat"] - j["m_act"]).to_numpy())
    dt = (np.abs(j["t_hat_b"] - j["t_act"]).to_numpy()
          - np.abs(j["t_hat"] - j["t_act"]).to_numpy())
    for name, v in (("margin", dm), ("total", dt)):
        n = len(v)
        se = v.std(ddof=1) / np.sqrt(n)
        t = v.mean() / se if se else 0.0
        print(f"  {w:<6} {name:<7} {v.mean():+.4f} MAE  (t={t:+.2f}, n={n})")
