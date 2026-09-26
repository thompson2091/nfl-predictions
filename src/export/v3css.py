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
idea, and the three colors that carry meaning — ours, good, bad — are never
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
/* THE BAR SIZES ITSELF TO WHAT IS IN IT.
   It was a fixed 52px holding a header that asked for 52px of its own plus
   a 12px margin and the safe-area inset — about 64px of content in a 52px
   box. `align-items:center` then bled the overflow downward, so the brand
   row and the game switcher under it nearly touched at the top of a phone.
   One box owns the spacing: this one. */
.appbar{flex:none;display:flex;align-items:center;justify-content:space-between;
  gap:12px;padding:calc(6px + env(safe-area-inset-top,0px)) 16px 6px;
  background:var(--bg)}
a{color:var(--ours);text-decoration:none}
button,input,select{font-family:inherit;font-size:inherit;color:inherit}
/* SIXTEEN PIXELS, ON EVERY CONTROL YOU CAN FOCUS.
   iOS Safari zooms the page when a form control is focused whose computed
   font-size is under 16px, and it does NOT zoom back out afterwards: tap the
   search box once and the whole board stays magnified until you pinch it
   back. The rule is on the elements rather than on each component, so a new
   control cannot reintroduce it by inheriting the 15px body size. Raising
   `body` instead would reflow every card to fix five controls. */
input,select,textarea{font-size:16px}
button{cursor:pointer}
:focus-visible{outline:2px solid var(--ours);outline-offset:2px}
.num{font-variant-numeric:tabular-nums}
.wrap{max-width:560px;margin:0 auto;padding:0 16px}

/* ---- header and the week picker, which is global on purpose ---- */
/* No height and no margin here: `.appbar` owns both, and two owners is what
   made the header overflow its own bar. */
/* The row is as tall as the tallest thing in it — the week chip, at 36px —
   and no taller. `viewport-fit=cover` means the notch inset is added ON TOP
   of this padding, so every pixel written here is a pixel of empty band
   above the brand on a phone. */
.hd{display:flex;align-items:center;justify-content:space-between;gap:12px;
  width:100%;min-height:36px}
.hd__b{font-family:var(--serif);font-size:19px;font-weight:600}
.wk{display:flex;align-items:center;gap:6px;height:36px;padding:0 10px;
  border-radius:10px;border:1px solid var(--btnline);background:var(--card);
  font-size:13px;color:var(--mut)}
.wk--past{border-color:var(--warn);background:var(--warnbg);color:var(--warn);
  font-weight:600}
.wk select{border:0;background:transparent;font-size:16px;color:inherit;
  font-weight:inherit;padding:0;margin:0}
.past{margin:12px 0 0;padding:10px 14px;border-radius:12px;
  background:var(--warnbg);color:var(--warn);font-size:13px;line-height:18px}
/* The same shape as `.past`, because it is the same kind of statement: read
   what follows with this in mind. Stacked rather than one run of text so the
   count is scannable without reading the sentence. */
.thin{margin:12px 0 0;padding:10px 14px;border-radius:12px;
  background:var(--warnbg);color:var(--warn);font-size:13px;line-height:18px;
  display:flex;flex-direction:column;gap:2px}
.thin b{font-weight:600}

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
/* The per-game count. Inside a game a market can hold nothing, and the only
   way to find out used to be to tap it and read an empty list. */
.mkt i{font-style:normal;font-size:12px;color:var(--mut);margin-left:4px}
.mkt--none{opacity:.55}
.mkt--none i{color:var(--mut)}
.help{margin:10px 2px 0;font-size:13px;line-height:18px;color:var(--mut)}
/* The game's section bar, pinned to the top of the scrolling pane.
   `#scroll` is the scroll container and the app header sits OUTSIDE it, so
   `top:0` is the top of the readable area and needs no header offset. The
   negative margins and matching padding let the background reach the full
   width of the pane, so nothing shows through beside the control. */
.gtabs{position:sticky;top:0;z-index:5;background:var(--bg);
  margin:0 -16px;padding:8px 16px}
/* Switcher and Ask share a row; the five-way control gets its own. Three
   full-width rows ran to about 140px on a phone, and a pinned bar that deep
   costs more screen than the scrolling it saves. */
.gtabs__row{display:flex;align-items:center;gap:8px}
/* Unbordered on purpose: everything else in this row is a bordered control
   that changes what you are looking at, and this one leaves. */
.gback{width:28px;height:36px;flex-shrink:0;border:0;background:transparent;
  color:var(--ours);font-size:24px;line-height:1;padding:0;margin-right:-4px}
/* Pinned, the selector IS the row, so it takes the space rather than the
   190px cap it needed when it shared a line with other things. */
.gtabs .gsel{flex:1;min-width:0;justify-content:stretch}
.gtabs .gsel select{flex:1;min-width:0;max-width:none;text-align:center;
  text-align-last:center}
/* The control's 16px top margin is the gap it needs IN THE FLOW. Inside the
   bar the wrapper's padding already gives it, and both together made the bar
   taller than the heading underneath. */
.gtabs .seg{margin-top:8px}
/* The matchup's own view control, pinned UNDER the game bar. `--gtabs-h` is
   written by `render` from the measured bar; the fallback only matters for
   the first paint. A lower `z-index` than `.gtabs` so that if the two ever
   meet, the game bar is the one that stays readable. */
.mxbar{position:sticky;top:var(--gtabs-h,0px);z-index:4;background:var(--bg);
  margin:0 -16px;padding:8px 16px}
.mxbar .seg{margin-top:0}
/* One row that scrolls sideways rather than a block that wraps to three.
   These sit under a bar that is already pinned, and a filter which pushes the
   thing it filters off the screen is not a filter. */
.mxpills{flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none;
  -webkit-overflow-scrolling:touch;margin:12px -16px 0;padding:0 16px}
.mxpills::-webkit-scrollbar{display:none}
.mxpills .cat{flex-shrink:0}

/* ---- the props filters, pinned ----
   Stacked at full size these ran about 250px before the first player: six
   44px market buttons in a 3x2 grid, a sentence, a 4-way filter, a search box
   and a sort row. Fine to read once, impossible to pin. Each control keeps
   one tap and loses its padding, which gets the bar to about 118px. */
.pbar{position:sticky;top:var(--gtabs-h,0px);z-index:4;background:var(--bg);
  margin:16px -16px 0;padding:8px 16px;display:flex;flex-direction:column;
  gap:6px}
/* A market that holds nobody for this game, greyed rather than counted. The
   count it replaces did not fit an even sixth of a phone; the question it
   answered — is there anyone in here — still gets an answer. */
.pbar .seg button.mkt--none{opacity:.45}
.pbar .seg{margin-top:0}
.pbar .seg button{height:32px;font-size:13px}
.pbar__row{display:flex;align-items:center;gap:6px}
.pbar .search{flex:1;min-width:0;margin-top:0}
.pbar .search input{height:34px;padding-right:34px}
.pbar .searchx{top:1px;right:2px}
.pbar .picker{flex-shrink:0;margin-top:0;height:34px;gap:4px;padding:0 6px 0 10px}
/* "SORT BY" goes: a dropdown listing sort names does not need a label saying
   it sorts, and in a pinned row that label is 60px of nothing. */
.pbar .picker .eyebrow{display:none}
/* STAYS AT 16px. Anything smaller and iOS zooms the whole page when the
   select takes focus, which on a pinned bar means the board jumps sideways
   every time you change the sort. It truncates instead. */
.pbar .picker select{height:32px;max-width:96px;flex:0 1 auto}
.pbar .dirbtn{height:26px;padding:0 8px;font-size:12px}

/* The one edge this project has measured, called out rather than set in the
   same muted grey as "pays if the player scores a touchdown" — where it read
   as another line of instructions. Green because it is the good news, and
   because the app already spends `--good` on things that went our way. */
.clv{margin:12px 0 0;padding:10px 14px;border-radius:12px;
  background:var(--goodbg);color:var(--good);font-size:13px;line-height:18px}
.clv b{font-weight:700}
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
  font-size:16px;font-weight:600}
.dirbtn{flex-shrink:0;height:32px;padding:0 10px;border-radius:8px;
  border:1px solid var(--btnline);background:var(--inset);font-size:13px;
  font-weight:600;color:var(--mut)}

/* ---- search ---- */
.search{position:relative;margin-top:12px}
.search input{width:100%;height:44px;padding:0 40px 0 14px;border-radius:12px;
  border:1px solid var(--btnline);background:var(--card);font-size:16px;
  -webkit-appearance:none;appearance:none}
.search input::-webkit-search-cancel-button{display:none}
.searchx{position:absolute;right:6px;top:6px;width:32px;height:32px;
  border-radius:8px;border:0;background:var(--inset);color:var(--mut);
  font-size:15px}

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
.three{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}

/* ---- picks: what you kept, and how it settled ----
   A leg carries a dot rather than a word, because a saved slip is read at a
   glance to see which way it is going and three colors say that faster than
   three labels. Pending is gray on purpose: an ungraded leg is not a miss. */
.legline{display:flex;align-items:center;justify-content:space-between;
  gap:10px;padding:7px 0;border-top:1px solid var(--line3);font-size:14px}
.legline > span:first-child{display:flex;align-items:center;gap:8px;
  min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dot{width:8px;height:8px;border-radius:999px;flex-shrink:0;
  background:var(--mut2)}
.dot--good{background:var(--good)}
.dot--bad{background:var(--bad)}
.dot--pend{background:var(--mut2)}
.panel{padding:10px;border-radius:12px;background:var(--inset)}
/* The row of a settled curve that actually happened. */
.out--on{background:var(--goodbg);border-radius:8px}
.out--on span:first-child{color:var(--good);font-weight:600}
.panel .eyebrow{display:block;margin-bottom:2px}
.num.good{color:var(--good)}
.num.bad{color:var(--bad)}
@media (max-width:420px){.three{grid-template-columns:1fr;gap:8px}}
.cmp--adj{background:var(--goodbg)}
.cmp--adj .eyebrow{color:var(--good)}
.seg--5{grid-template-columns:repeat(5,minmax(0,1fr))}
.seg--5 button{font-size:12px;padding:0 2px}
.box{padding:12px;border-radius:12px;background:var(--inset);
  display:flex;flex-direction:column;gap:2px}
.box--ours{background:var(--oursbg)}
/* A PLAYED GAME TURNS A CHANCE INTO AN ANSWER. Tinted, not recoloured: the
   percentage that was forecast stays readable beside what happened. */
.box--good{background:var(--goodbg)}
.box--good .eyebrow,.box--good .sub{color:var(--good)}
.box--bad{background:var(--badbg)}
.box--bad .eyebrow,.box--bad .sub{color:var(--bad)}
.mrow--on{background:var(--goodbg);border-radius:8px}
.mrow--on .mrow__l{color:var(--good);font-weight:600}
.srow--on{background:var(--goodbg);border-radius:8px}
.srow--on b{color:var(--good)}
/* Close enough to our number that we like it. Quieter than `--on`, which marks
   what actually happened on a played week — an opinion must not look like a
   result. Tint rather than a label: it can mark several rows, and a phrase
   appended to a scoreline wrapped onto two lines on a phone. */
.srow--like{background:var(--oursbg);border-radius:8px}
.srow--like b{color:var(--ours)}
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
/* No font-size here on purpose: the 16px floor above covers it, and a
   number written here is a number that can be lowered without anyone
   connecting it to the zoom. */
.ask input{flex:1;min-width:0;height:44px;padding:0 12px;border-radius:12px;
  border:1px solid var(--btnline);background:var(--inset)}
.ask button{width:44px;height:44px;border-radius:12px;border:0;
  background:var(--ours);color:#fff;display:flex;align-items:center;
  justify-content:center}
/* Asking is context, not a section: the control sits with the game's own
   numbers above the tab bar, so a question raised on any tab is one tap away
   and closes back onto the tab that raised it. */
.askbtn{display:flex;align-items:center;justify-content:space-between;
  width:100%;min-height:48px;margin-top:12px;padding:0 14px;
  border-radius:14px;background:var(--card);color:var(--ink);
  border:1px solid var(--btnline);font-size:15px;font-weight:600;
  box-shadow:0 1px 2px rgba(22,24,29,.06)}
.askbtn i{font-style:normal;color:var(--mut);font-size:17px}
/* The pinned form: content-width and the switcher's height, so the two read
   as one control rather than a button with a dropdown stuck to it. */
.askbtn--mini{width:auto;min-height:36px;height:36px;margin:0;padding:0 12px;
  flex-shrink:0;border-radius:10px;font-size:14px;gap:6px;
  justify-content:center}
.askbtn--mini i{font-size:15px}
.qs{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.q{min-height:36px;padding:6px 12px;border-radius:999px;
  border:1px solid var(--btnline);background:var(--card);text-align:left;
  font-size:15px}
.ans{margin-top:10px;padding:12px;border-radius:12px;background:var(--oursbg);
  font-size:15px;line-height:20px}
.ans--bad{background:var(--badbg);color:var(--bad)}
@keyframes v3pulse{0%,100%{opacity:.45}50%{opacity:1}}
.thinking{animation:v3pulse 1.1s ease-in-out infinite}

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

/* ---- how the line has moved ---- */
.moved{margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid var(--line)}
.moved__r{display:grid;grid-template-columns:62px 1fr auto;align-items:baseline;
  gap:10px;padding:4px 0;font-size:14px}
.moved__r b{font-weight:700}
.moved__r .sub{font-size:12px;text-align:right}

/* ---- where the public is ---- */
.pub{margin-top:12px}
.pub__h{display:flex;align-items:baseline;justify-content:space-between;
  gap:8px;flex-wrap:wrap;margin-bottom:5px}
.pub .bar{height:30px}

/* ---- matchup differentials ---- */
.mx{padding:8px 0;border-top:1px solid var(--line3)}
.mx:first-child{border-top:0}
.mx__h{display:flex;justify-content:space-between;align-items:baseline;gap:8px;
  font-size:14px}
.mx__h i{font-style:normal;color:var(--mut2)}
.mx__h b{font-weight:700}
.mx__h b.good{color:var(--good)}
.mx__h b.bad{color:var(--bad)}
.mx__b{position:relative;height:8px;border-radius:999px;background:var(--sunk);
  margin:5px 0 3px;overflow:hidden}
.mx__b::before{content:'';position:absolute;left:50%;top:0;bottom:0;width:1px;
  background:var(--mut3);z-index:1}
.mx__b i{position:absolute;top:0;bottom:0;display:block;border-radius:999px}
.mx__b i.r{left:50%;background:var(--good)}
.mx__b i.l{right:50%;background:var(--bad)}
.mx__f{font-size:12px;color:var(--mut)}
.gap{display:flex;flex-direction:column;gap:2px;padding:8px 0;
  border-top:1px solid var(--line3)}
.gap:first-of-type{border-top:0}
.gap b{font-size:14px;font-weight:600}
.gap span{font-size:13px;color:var(--mut);line-height:18px}
.seg--6{grid-template-columns:repeat(6,minmax(0,1fr))}
.seg--6 button{font-size:11px;padding:0 1px}

/* ---- injury report ---- */
.injrow{display:flex;align-items:flex-start;gap:10px;padding:6px 0;
  border-top:1px solid var(--line3)}
.inj .eyebrow+.injrow{border-top:0}
.injrow>.tag{flex-shrink:0;min-width:78px;justify-content:center}
.injrow__n{display:flex;flex-direction:column;min-width:0}
.injrow__n b{font-size:15px;font-weight:600}
.injrow__n i{font-style:normal;font-size:12px;color:var(--mut)}

/* ---- moving between games without going back ---- */
.gsel{display:flex;align-items:center;gap:4px;min-width:0;flex:1;
  justify-content:flex-end}
.gsel select{min-width:0;max-width:190px;height:36px;border-radius:10px;
  border:1px solid var(--btnline);background:var(--card);font-size:16px;
  font-weight:600;padding:0 4px}
.gstep{width:36px;height:36px;border-radius:10px;border:1px solid var(--btnline);
  background:var(--card);color:var(--ink);font-size:18px;line-height:1;
  flex-shrink:0}

/* ---- book against model, same shape both sides ---- */
.cmp{padding:12px;border-radius:12px;background:var(--inset);display:flex;
  flex-direction:column;gap:2px}
.cmp--ours{background:var(--oursbg)}
.cmp--ours .eyebrow{color:var(--ours)}
.cmp__t{font-size:17px;font-weight:700;line-height:20px}
.cmp__s{font-size:19px;font-weight:700;line-height:23px;
  white-space:nowrap}

/* ---- the score ladder ---- */
.ltab__h,.ltab__r{display:grid;grid-template-columns:96px 52px 1fr;
  align-items:center;gap:10px;padding:6px 0}
.ltab__h{font-size:11px;font-weight:600;letter-spacing:.06em;
  text-transform:uppercase;color:var(--mut2);border-bottom:1px solid var(--line)}
.ltab__r{border-top:1px solid var(--line3);font-size:14px}
/* A PLAYED WEEK HAS ANSWERS, NOT CHANCES. Tinted rather than recoloured, so
   the percentage stays readable and the row still reads as one of a ladder
   rather than as a verdict of its own. */
.ltab__r--hit{background:var(--goodbg)}
.ltab__r--miss{background:var(--badbg)}
.ltab__r--hit .num:first-child{color:var(--good);font-weight:600}
.ltab__r--miss .num:first-child{color:var(--bad);font-weight:600}
.ltab__r:first-of-type{border-top:0}
.ltab__r--on{background:var(--oursbg);border-radius:8px;
  box-shadow:0 0 0 6px var(--oursbg);position:relative}
/* Our number, when it falls on a different rung from the posted one. Quieter
   than `--on`: the posted line is the fact, ours is the opinion. */
.ltab__r--mine{background:var(--inset);border-radius:8px;position:relative}
.ltab__r--mine .num:first-child{color:var(--ours);font-weight:600}
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

/* ---- ladder inputs ---- */
.lfields{display:grid;grid-template-columns:1fr 1fr 80px;gap:8px;margin-top:16px}
.lfield{display:flex;flex-direction:column;gap:2px;padding:8px 10px;
  border-radius:12px;background:var(--card);border:1px solid var(--btnline)}
.lfield input{border:0;background:transparent;font-size:19px;font-weight:700;
  padding:0;width:100%;font-variant-numeric:tabular-nums}
.lfield i{font-style:normal;font-size:11px;color:var(--mut2)}
@media (max-width:400px){.lfields{grid-template-columns:1fr 1fr;
  grid-template-areas:'a b' 'c c'}}

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

/* ---- favorites ---- */
.star{flex-shrink:0;width:40px;height:40px;border-radius:10px;border:0;
  background:transparent;color:var(--mut3);font-size:19px;line-height:1}
.star[aria-pressed=true]{color:var(--star)}
@media (max-width:380px){.h1{font-size:26px;line-height:32px}
  .mkts{grid-template-columns:repeat(2,minmax(0,1fr))}}
"""


def css() -> str:
    return tokens_css() + COMPONENTS
