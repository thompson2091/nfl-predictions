"""site/v3 — the stylesheet for the version a casual bettor reads.

v2's CSS is 33KB of component rules for a board with seven tabs, six markets
and four filters, and it is right for what it does. This is a different
problem: four tabs, one list at a time, and a reader who has not agreed to
learn what "edge_pp" means before the page is useful.

**The tokens are v2's, unchanged.** `pwa.TOKENS` is imported rather than
copied — the design this was drawn from already uses that palette, down to
#1F4FA3 for our number and Schibsted Grotesk for the text, so there is nothing
to reconcile and a change to the token layer moves both versions at once.

What differs is the component set. v2 packs; this breathes. Every interactive
target is at least 44px because it is used with a thumb, every card is one
idea, and the three colours that carry meaning — ours, good, bad — are never
spent on decoration, so that when a row is green it is green for a reason.
"""
from __future__ import annotations

from src.export.pwa import TOKENS


def tokens_css() -> str:
    out = [":root{"]
    for group in TOKENS.values():
        for k, v in group.items():
            out.append(f"--{k}:{v};")
    out.append("}")
    return "".join(out)


#: Component rules. Grouped by screen, in the order a reader meets them.
COMPONENTS = """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.4 var(--sans);-webkit-font-smoothing:antialiased;
  padding-bottom:calc(84px + env(safe-area-inset-bottom,0px))}
a{color:var(--ours);text-decoration:none}
button,input,select{font-family:inherit;font-size:inherit;color:inherit}
button{cursor:pointer}
:focus-visible{outline:2px solid var(--ours);outline-offset:2px}
.num{font-variant-numeric:tabular-nums}
.wrap{max-width:560px;margin:0 auto;padding:0 16px}

/* ---- header and the week picker, which is global on purpose ---- */
.hd{display:flex;align-items:center;justify-content:space-between;gap:12px;
  height:52px;margin-top:calc(12px + env(safe-area-inset-top,0px))}
.hd__b{font-family:var(--serif);font-size:19px;font-weight:600}
.wk{display:flex;align-items:center;gap:6px;height:36px;padding:0 10px;
  border-radius:10px;border:1px solid var(--btnline);background:var(--card);
  font-size:13px;color:var(--mut)}
.wk--past{border-color:var(--warn);background:var(--warnbg);color:var(--warn);
  font-weight:600}
.wk select{border:0;background:transparent;font-size:13px;color:inherit;
  font-weight:inherit;padding:0;margin:0}
.past{margin:12px 0 0;padding:10px 14px;border-radius:12px;
  background:var(--warnbg);color:var(--warn);font-size:13px;line-height:18px}

/* ---- page intro ---- */
.h1{margin:16px 0 0;font-size:30px;line-height:36px;font-weight:700}
.lede{margin:8px 0 0;font-size:17px;line-height:24px;color:var(--mut)}
.eyebrow{font-size:11px;line-height:14px;font-weight:600;letter-spacing:.07em;
  text-transform:uppercase;color:var(--mut2)}

/* ---- controls ---- */
.mkts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;
  margin-top:20px}
.mkt{min-height:44px;padding:0 6px;border-radius:12px;font-size:15px;
  font-weight:500;background:var(--card);color:var(--ink);
  border:1px solid var(--btnline)}
.mkt[aria-pressed=true]{background:var(--oursbg);color:var(--ours);
  border-color:var(--ours)}
.help{margin:10px 2px 0;font-size:13px;line-height:18px;color:var(--mut)}
.seg{display:grid;gap:2px;padding:2px;background:var(--seg);border-radius:12px;
  margin-top:16px}
.seg--2{grid-template-columns:repeat(2,minmax(0,1fr))}
.seg--3{grid-template-columns:repeat(3,minmax(0,1fr))}
.seg button{height:36px;border:0;border-radius:10px;font-size:15px;
  font-weight:500;background:transparent;color:var(--mut)}
.seg button[aria-pressed=true]{background:var(--card);color:var(--ink);
  box-shadow:0 1px 2px rgba(22,24,29,.12)}

/* ---- cards and lists ---- */
.card{margin-top:16px;padding:16px;background:var(--card);border-radius:16px;
  box-shadow:0 1px 2px rgba(22,24,29,.06)}
.list{margin-top:12px;background:var(--card);border-radius:16px;
  box-shadow:0 1px 2px rgba(22,24,29,.06);overflow:hidden}
.row{display:flex;gap:8px;align-items:center;padding:12px 8px 12px 16px;
  border-top:1px solid var(--line)}
.row:first-child{border-top:0}
.row__m{display:flex;flex-direction:column;gap:8px;flex:1;min-width:0}
.row__t{display:flex;justify-content:space-between;gap:12px}
.name{font-size:17px;line-height:22px;font-weight:600}
.sub{font-size:13px;line-height:18px;color:var(--mut)}
.line{font-size:13px;line-height:18px;font-weight:600}
.chance{display:flex;flex-direction:column;align-items:flex-end;gap:2px;
  flex-shrink:0}
.chance b{font-size:20px;line-height:24px;font-weight:700}
.tags{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.pill{height:24px;padding:0 10px;display:inline-flex;align-items:center;
  border-radius:999px;border:1px solid var(--btnline);font-size:13px;
  font-weight:600}
.tag{height:24px;padding:0 8px;display:inline-flex;align-items:center;
  border-radius:8px;font-size:12px;font-weight:600;background:var(--inset);
  color:var(--mut)}
.tag--good{background:var(--goodbg);color:var(--good)}
.tag--bad{background:var(--badbg);color:var(--bad)}
.tag--warn{background:var(--warnbg);color:var(--warn)}
.tag--ours{background:var(--oursbg);color:var(--ours)}
.add{flex-shrink:0;width:44px;height:44px;border-radius:12px;display:flex;
  align-items:center;justify-content:center;background:var(--card);
  color:var(--ink);border:1px solid var(--mut3)}
.add[aria-pressed=true]{background:var(--ours);color:#fff;border-color:var(--ours)}
.more{width:100%;height:52px;border:0;border-top:1px solid var(--line);
  background:var(--card);color:var(--ours);font-size:15px;font-weight:600}
.empty{padding:24px 16px;text-align:center;color:var(--mut);font-size:15px;
  line-height:20px}

/* ---- graded past weeks. The whole point of looking back. ---- */
.row--won{background:var(--goodbg)}
.row--lost{background:var(--badbg)}
.mark{width:22px;height:22px;border-radius:999px;display:inline-flex;
  align-items:center;justify-content:center;font-size:13px;font-weight:700;
  flex-shrink:0}
.mark--won{background:var(--gooddot);color:#fff}
.mark--lost{background:var(--baddot);color:#fff}
.mark--void{background:var(--pend);color:#fff}
.score{display:flex;gap:8px;align-items:baseline}
.score b{font-size:17px;font-weight:700}

/* ---- games ---- */
.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.stat{display:flex;flex-direction:column;gap:2px}
.stat b{font-size:20px;line-height:24px;font-weight:700}
.g{display:flex;align-items:center;gap:12px;padding:12px 16px;min-height:68px;
  border-top:1px solid var(--line);color:var(--ink)}
.g:first-child{border-top:0}
.g__m{display:flex;flex-direction:column;gap:4px;flex:1;min-width:0}
.kick{font-size:12px;color:var(--mut2);font-weight:600}
.chev{flex-shrink:0;color:var(--mut)}

/* ---- game detail ---- */
.back{height:44px;display:inline-flex;align-items:center;gap:2px;
  font-size:17px;color:var(--ours)}
.vs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));
  align-items:center}
.vs b{font-size:22px;line-height:28px;font-weight:700}
.bar{display:flex;height:32px;border-radius:8px;overflow:hidden;
  font-size:13px;font-weight:600}
.bar span{display:flex;align-items:center;padding:0 10px}
.bar .a{background:var(--sunk);color:var(--ink)}
.bar .h{background:var(--ours);color:#fff;justify-content:flex-end}
.two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.box{padding:12px;border-radius:12px;background:var(--inset);
  display:flex;flex-direction:column;gap:2px}
.box--ours{background:var(--oursbg)}
.box b{font-size:17px;font-weight:600}
.cats{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.cat{min-height:36px;padding:0 14px;border-radius:999px;font-size:15px;
  font-weight:500;background:var(--card);color:var(--ink);
  border:1px solid var(--btnline)}
.cat[aria-pressed=true]{background:var(--oursbg);color:var(--ours);
  border-color:var(--ours)}
.note{margin-top:12px;padding:16px;background:var(--card);border-radius:16px;
  box-shadow:0 1px 2px rgba(22,24,29,.06);display:flex;flex-direction:column;
  gap:12px}
.note__h{display:flex;justify-content:space-between;align-items:center;gap:8px}
.note h3{margin:-6px 0 0;font-size:17px;line-height:22px;font-weight:600}
.note p{margin:0;font-size:15px;line-height:20px;color:var(--mut)}
.figs{display:flex;gap:8px;flex-wrap:wrap}
.fig{padding:8px 12px;border-radius:12px;background:var(--inset);
  display:flex;flex-direction:column}
.fig b{font-size:20px;line-height:24px;font-weight:700}
.fig span{font-size:13px;line-height:18px;color:var(--mut)}
.note__f{display:flex;align-items:center;justify-content:space-between;gap:8px;
  padding-top:12px;border-top:1px solid var(--line)}
.btn{height:44px;min-width:76px;padding:0 16px;border-radius:12px;
  font-size:15px;font-weight:600;background:var(--card);color:var(--ours);
  border:1px solid var(--ours)}
.btn[aria-pressed=true]{background:var(--goodbg);color:var(--good);
  border-color:var(--good)}
.ask{display:flex;gap:8px;margin-top:12px}
.ask input{flex:1;min-width:0;height:44px;padding:0 12px;border-radius:12px;
  border:1px solid var(--btnline);background:var(--inset)}
.ask button{width:44px;height:44px;border-radius:12px;border:0;
  background:var(--ours);color:#fff;display:flex;align-items:center;
  justify-content:center}
.qs{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.q{min-height:36px;padding:6px 12px;border-radius:999px;
  border:1px solid var(--btnline);background:var(--card);text-align:left;
  font-size:15px}
.ans{margin-top:12px;padding:12px;border-radius:12px;background:var(--oursbg);
  font-size:15px;line-height:20px}

/* ---- my picks ---- */
.opt{display:flex;gap:12px;align-items:flex-start;width:100%;padding:14px 16px;
  border-radius:16px;background:var(--card);border:1px solid transparent;
  box-shadow:0 1px 2px rgba(22,24,29,.06);margin-top:8px;text-align:left}
.opt[aria-pressed=true]{border-color:var(--ours)}
.radio{flex-shrink:0;margin-top:1px;width:22px;height:22px;border-radius:999px;
  display:flex;align-items:center;justify-content:center;
  border:1.5px solid var(--mut3)}
.opt[aria-pressed=true] .radio{border:2px solid var(--ours)}
.radio i{width:0;height:0;border-radius:999px;background:var(--ours)}
.opt[aria-pressed=true] .radio i{width:10px;height:10px}
.stakes{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;
  margin-top:8px}
.stake{height:44px;border-radius:12px;font-size:15px;font-weight:600;
  background:var(--card);color:var(--ink);border:1px solid var(--btnline)}
.stake[aria-pressed=true]{background:var(--oursbg);color:var(--ours);
  border-color:var(--ours)}
.out{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));
  align-items:center;min-height:44px;border-top:1px solid var(--line)}
.out span:nth-child(n+2){text-align:right}
.big{font-size:28px;line-height:32px;font-weight:700}
.cta{width:100%;height:52px;border-radius:12px;font-size:17px;font-weight:600;
  background:var(--ours);color:#fff;border:1px solid var(--ours);margin-top:16px}
.cta[aria-pressed=true]{background:var(--goodbg);color:var(--good);
  border-color:var(--good)}
.fab{position:fixed;left:50%;transform:translateX(-50%);width:calc(100% - 32px);
  max-width:528px;bottom:calc(96px + env(safe-area-inset-bottom,0px));
  height:56px;padding:0 16px;border-radius:12px;background:var(--ours);
  color:#fff;display:flex;align-items:center;justify-content:space-between;
  box-shadow:0 -8px 32px rgba(22,24,29,.18);z-index:5}
.fab b{min-width:24px;height:24px;border-radius:999px;background:#fff;
  color:var(--ours);display:inline-flex;align-items:center;
  justify-content:center;font-size:13px;font-weight:700}

/* ---- ladder ---- */
.rung{display:grid;grid-template-columns:56px minmax(0,1fr) minmax(0,1fr);
  align-items:center;min-height:56px;padding:6px 16px;
  border-top:1px solid var(--line)}
.rung span:nth-child(n+2){text-align:right}
.rung--alt{background:var(--inset)}

/* ---- nav ---- */
.nav{position:fixed;left:0;right:0;bottom:0;height:84px;
  padding-bottom:calc(28px + env(safe-area-inset-bottom,0px));
  background:var(--card);box-shadow:0 -1px 0 rgba(22,24,29,.10);
  display:grid;grid-template-columns:repeat(4,minmax(0,1fr));z-index:6}
.nav a{display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:2px;color:var(--mut);font-size:13px}
.nav a[aria-current=page]{color:var(--ours);font-weight:600}
@media (max-width:380px){.h1{font-size:26px;line-height:32px}
  .mkts{grid-template-columns:repeat(2,minmax(0,1fr))}}
"""


def css() -> str:
    return tokens_css() + COMPONENTS
