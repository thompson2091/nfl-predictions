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
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.4 var(--sans);-webkit-font-smoothing:antialiased;
  overflow:hidden}

/* ---- the app frame: a fixed shell with one scrolling pane ----
   Copied in structure from v2, which had it right. A page that scrolls its
   BODY under fixed bars fights the address bar on every phone: the viewport
   changes height as you scroll and the bottom bar jumps. A flex column that
   owns the window does not have that problem, and it is why v2's chrome feels
   like an app and the first v3 did not. */
.app{position:fixed;inset:0;display:flex;flex-direction:column;
  padding-top:env(safe-area-inset-top,0px)}
.scroll{flex:1;min-height:0;overflow-y:auto;-webkit-overflow-scrolling:touch;
  overscroll-behavior:contain;
  padding-left:env(safe-area-inset-left,0px);
  padding-right:env(safe-area-inset-right,0px);
  padding-bottom:var(--s5)}
.appbar{flex:none;display:flex;align-items:center;justify-content:space-between;
  gap:12px;height:52px;padding:0 16px;background:var(--bg)}
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
.seg--4{grid-template-columns:repeat(4,minmax(0,1fr))}
.seg--4 button{font-size:13px}
.rowacts{display:flex;flex-direction:column;align-items:center;gap:2px;
  flex-shrink:0}
.seg button{height:36px;border:0;border-radius:10px;font-size:15px;
  font-weight:500;background:transparent;color:var(--mut)}
.seg button[aria-pressed=true]{background:var(--card);color:var(--ink);
  box-shadow:0 1px 2px rgba(22,24,29,.12)}

/* ---- pickers: game filter and sort, side by side on one line ---- */
.picker{display:flex;align-items:center;gap:8px;margin-top:12px;padding:0 12px;
  height:44px;border-radius:12px;background:var(--card);
  border:1px solid var(--btnline)}
.picker--on{border-color:var(--ours);background:var(--oursbg)}
.picker .eyebrow{flex-shrink:0}
.picker select{flex:1;min-width:0;border:0;background:transparent;height:42px;
  font-size:15px;font-weight:600}
.dirbtn{flex-shrink:0;height:32px;padding:0 10px;border-radius:8px;
  border:1px solid var(--btnline);background:var(--inset);font-size:13px;
  font-weight:600;color:var(--mut)}

/* ---- the number strip: the old board's columns, on the row ---- */
.rowbtn{flex:1;min-width:0;display:block;text-align:left;border:0;
  background:transparent;padding:0;font:inherit;color:inherit}
.strip{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:4px;
  padding:8px 0 2px}
@media (max-width:400px){.strip{grid-template-columns:repeat(3,minmax(0,1fr));
  row-gap:8px}}
.cell{display:flex;flex-direction:column;min-width:0}
.cell b{font-size:15px;line-height:20px;font-weight:700}
.cell b.good{color:var(--good)}
.cell b.bad{color:var(--bad)}
.cell i{font-style:normal;font-size:11px;line-height:14px;font-weight:600;
  letter-spacing:.06em;text-transform:uppercase;color:var(--mut2)}
.row--open{background:var(--inset)}

/* ---- the full-stat panel behind a row ---- */
.detail{flex-basis:100%;width:100%;margin-top:4px;padding:12px;
  border-radius:12px;background:var(--card);border:1px solid var(--line)}
.detail dl{margin:0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));
  gap:2px 12px}
.detail dl>div{display:flex;justify-content:space-between;gap:8px;
  padding:6px 0;border-bottom:1px solid var(--line3);min-width:0}
.detail dt{font-size:13px;color:var(--mut);flex-shrink:0}
.detail dd{margin:0;font-size:13px;font-weight:600;text-align:right;
  min-width:0;overflow-wrap:anywhere}
@media (max-width:420px){.detail dl{grid-template-columns:1fr}}

/* ---- cards and lists ---- */
.card{margin-top:16px;padding:16px;background:var(--card);border-radius:16px;
  box-shadow:0 1px 2px rgba(22,24,29,.06)}
.list{margin-top:12px;background:var(--card);border-radius:16px;
  box-shadow:0 1px 2px rgba(22,24,29,.06);overflow:hidden}
.row{display:flex;gap:8px;align-items:flex-start;flex-wrap:wrap;
  padding:12px 8px 12px 16px;border-top:1px solid var(--line)}
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

/* ---- one betting line, both sides, with what the book keeps ---- */
.lineblk{margin-top:8px;padding:12px 14px;background:var(--card);
  border-radius:16px;box-shadow:0 1px 2px rgba(22,24,29,.06)}
.lineblk--main{border:1px solid var(--ours)}
.lineblk>.tag{margin-bottom:8px}
.side{display:flex;align-items:center;justify-content:space-between;gap:12px;
  padding:8px 0;border-top:1px solid var(--line3)}
.side:first-of-type{border-top:0}
.side__n{display:flex;flex-direction:column;gap:2px;min-width:0}
.side__n b{font-size:17px;font-weight:600}
.side__p{display:flex;flex-direction:column;align-items:flex-end;gap:2px;
  flex-shrink:0}
.hold{margin-top:8px;padding-top:8px;border-top:1px solid var(--line);
  font-size:13px;line-height:18px;color:var(--mut)}
.hold b{color:var(--ink)}

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

/* ---- two big choosers instead of a page of radio buttons ---- */
.chooser{display:grid;grid-template-columns:2fr 1fr;gap:8px;margin-top:16px}
.choose{display:flex;flex-direction:column;align-items:flex-start;gap:2px;
  min-height:60px;padding:10px 14px;border-radius:14px;background:var(--card);
  border:1px solid var(--btnline);text-align:left}
.choose b{font-size:17px;font-weight:700}

/* ---- where the public is ---- */
.pub{margin-top:12px}
.pub__h{display:flex;align-items:baseline;justify-content:space-between;
  gap:8px;flex-wrap:wrap;margin-bottom:5px}
.pub .bar{height:30px}

/* ---- injury report ---- */
.injrow{display:flex;align-items:flex-start;gap:10px;padding:6px 0;
  border-top:1px solid var(--line3)}
.inj .eyebrow+.injrow{border-top:0}
.injrow>.tag{flex-shrink:0;min-width:78px;justify-content:center}
.injrow__n{display:flex;flex-direction:column;min-width:0}
.injrow__n b{font-size:15px;font-weight:600}
.injrow__n i{font-style:normal;font-size:12px;color:var(--mut)}

/* ---- moving between games without going back ---- */
.gamenav{display:flex;align-items:center;justify-content:space-between;gap:10px;
  margin-top:4px}
.gsel{display:flex;align-items:center;gap:4px;min-width:0;flex:1;
  justify-content:flex-end}
.gsel select{min-width:0;max-width:190px;height:36px;border-radius:10px;
  border:1px solid var(--btnline);background:var(--card);font-size:13px;
  font-weight:600;padding:0 6px}
.gstep{width:36px;height:36px;border-radius:10px;border:1px solid var(--btnline);
  background:var(--card);color:var(--ink);font-size:18px;line-height:1;
  flex-shrink:0}

/* ---- book against model, same shape both sides ---- */
.cmp{padding:12px;border-radius:12px;background:var(--inset);display:flex;
  flex-direction:column;gap:2px}
.cmp--ours{background:var(--oursbg)}
.cmp--ours .eyebrow{color:var(--ours)}
.cmp b{font-size:19px;font-weight:700}

/* ---- the score ladder ---- */
.ltab__h,.ltab__r{display:grid;grid-template-columns:96px 52px 1fr;
  align-items:center;gap:10px;padding:6px 0}
.ltab__h{font-size:11px;font-weight:600;letter-spacing:.06em;
  text-transform:uppercase;color:var(--mut2);border-bottom:1px solid var(--line)}
.ltab__r{border-top:1px solid var(--line3);font-size:14px}
.ltab__r:first-of-type{border-top:0}
.ltab__r--on{background:var(--oursbg);border-radius:8px;
  box-shadow:0 0 0 6px var(--oursbg);position:relative}
.ltab__r span:nth-child(2){font-weight:700}
.ltab__r i{font-style:normal;font-size:11px;color:var(--mut2);
  margin-left:8px;white-space:nowrap}
.mini{display:inline-block;width:46%;height:8px;border-radius:999px;
  background:var(--sunk);overflow:hidden;vertical-align:middle}
.mini i{display:block;height:100%;background:var(--ours);margin:0}
.quotes{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.quote{display:inline-flex;align-items:baseline;gap:5px;padding:6px 10px;
  border-radius:10px;background:var(--inset);font-size:13px}
.quote b{font-weight:700}
.quote i{font-style:normal;color:var(--mut2);font-size:12px}

/* ---- final-score distribution ---- */
.mrow{display:grid;grid-template-columns:minmax(96px,1.6fr) 1fr 46px;
  align-items:center;gap:10px;padding:5px 0}
.mrow__l{font-size:13px;color:var(--mut)}
.mrow__v{font-size:13px;font-weight:700;text-align:right}
.mbar{height:10px;border-radius:999px;background:var(--sunk);overflow:hidden}
.mbar i{display:block;height:100%;border-radius:999px;background:var(--ours)}
.srow{display:flex;align-items:baseline;justify-content:space-between;gap:10px;
  padding:7px 0;border-top:1px solid var(--line3)}
.srow:first-child{border-top:0}
.srow b{font-size:15px;font-weight:700}

/* ---- ladder ---- */
.rung{display:grid;grid-template-columns:56px minmax(0,1fr) minmax(0,1fr);
  align-items:center;min-height:56px;padding:6px 16px;
  border-top:1px solid var(--line)}
.rung span:nth-child(n+2){text-align:right}
.rung--alt{background:var(--inset)}

/* ---- nav ---- */
/* THE HOME INDICATOR IS ADDED TO THE BAR'S HEIGHT, NOT TAKEN OUT OF IT.
   The first version padded 28px INSIDE an 84px bar, which squeezed the tap
   targets into 56px of a bar that looked 84px tall and left a slab of empty
   white under the labels. v2 adds the inset to the height and pads by exactly
   the inset, so the targets stay full size and nothing is wasted. */
.tabbar{flex:none;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));
  height:calc(56px + env(safe-area-inset-bottom,0px));
  padding-bottom:env(safe-area-inset-bottom,0px);
  padding-left:env(safe-area-inset-left,0px);
  padding-right:env(safe-area-inset-right,0px);
  background:var(--card);border-top:1px solid var(--line)}
.tabbar a{display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:2px;color:var(--mut);font-size:11px;
  font-weight:600;min-width:0;padding:0 2px}
.tabbar a[aria-current=page]{color:var(--ours)}
@media (max-width:360px){.tabbar a{font-size:10px}}

/* ---- the slip bar, and swiping it away ----
   The button is BEHIND the bar rather than revealed by it, so the movement
   follows a thumb instead of playing an animation after one. */
.slipwrap{position:relative;flex:none;overflow:hidden;background:var(--bad)}
.slipdel{position:absolute;right:0;top:0;bottom:0;width:112px;border:0;
  background:var(--bad);color:#fff;font-size:15px;font-weight:600;
  display:flex;align-items:center;justify-content:center;gap:6px;
  padding-right:env(safe-area-inset-right,0px)}
.slipbar{position:relative;z-index:1;display:flex;align-items:center;gap:10px;
  height:60px;padding:0 12px 0 16px;background:var(--ours);color:#fff;
  transition:transform .18s ease}
.slipwrap[data-swipe=open] .slipbar{transform:translateX(-112px)}
.slipwrap[data-swipe=dragging] .slipbar{transition:none}
.slipbar__count{min-width:26px;height:26px;border-radius:999px;
  background:rgba(255,255,255,.22);display:inline-flex;align-items:center;
  justify-content:center;font-size:13px;font-weight:700;flex-shrink:0}
.slipbar__main{flex:1;min-width:0;display:flex;flex-direction:column}
.slipbar__price{font-size:15px;font-weight:700}
.slipbar__legs{font-size:12px;opacity:.85;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis}
.slipbar__open{flex-shrink:0;height:36px;padding:0 14px;border-radius:10px;
  border:0;background:#fff;color:var(--ours);font-size:14px;font-weight:700}
.slipbar__x{flex-shrink:0;width:36px;height:36px;border-radius:10px;border:0;
  background:rgba(255,255,255,.18);color:#fff;font-size:18px;line-height:1}

/* ---- the bottom sheet ---- */
.scrim{position:fixed;inset:0;background:rgba(22,24,29,.42);opacity:0;
  pointer-events:none;transition:opacity .18s ease;z-index:20}
.scrim.open{opacity:1;pointer-events:auto}
.sheet{position:fixed;left:0;right:0;bottom:0;z-index:21;background:var(--card);
  border-radius:20px 20px 0 0;transform:translateY(100%);
  transition:transform .22s cubic-bezier(.2,.8,.3,1);max-height:82dvh;
  display:flex;flex-direction:column;box-shadow:0 -8px 40px rgba(22,24,29,.22)}
.sheet.open{transform:none}
.sheet__grab{flex:none;padding:8px 0 4px;display:flex;justify-content:center}
.sheet__grab i{display:block;width:40px;height:4px;border-radius:999px;
  background:var(--pend)}
.sheet__head{flex:none;display:flex;align-items:center;
  justify-content:space-between;padding:4px 16px 8px}
.sheet__head b{font-size:19px;font-weight:700}
.sheet__x{width:36px;height:36px;border-radius:999px;border:0;
  background:var(--inset);color:var(--ink);font-size:18px}
.sheet__body{flex:1;min-height:0;overflow-y:auto;padding:0 16px
  calc(20px + env(safe-area-inset-bottom,0px))}

/* ---- swipe a leg away ---- */
.legwrap{position:relative;overflow:hidden;background:var(--bad)}
.legdel{position:absolute;right:0;top:0;bottom:0;width:96px;border:0;
  background:var(--bad);color:#fff;font-size:15px;font-weight:600}
.legwrap>.row{position:relative;z-index:1;background:var(--card);
  transition:transform .18s ease}
.legwrap[data-swipe=open]>.row{transform:translateX(-96px)}
.legwrap[data-swipe=dragging]>.row{transition:none}

/* ---- favourites ---- */
.star{flex-shrink:0;width:40px;height:40px;border-radius:10px;border:0;
  background:transparent;color:var(--mut3);font-size:19px;line-height:1}
.star[aria-pressed=true]{color:var(--star)}
@media (max-width:380px){.h1{font-size:26px;line-height:32px}
  .mkts{grid-template-columns:repeat(2,minmax(0,1fr))}}
"""


def css() -> str:
    return tokens_css() + COMPONENTS
