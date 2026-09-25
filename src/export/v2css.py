"""The v2 stylesheet: the design system, plus what the real app needs.

`v2design.css` is read off `design/v2/prototype.html` and changed as little as
possible — the same relationship `design/` has to v1. Three things were taken
out of it and they are all the prototype's own furniture rather than the
system: the Google Fonts `@import` (this page carries its own faces), the fake
`.safe` and `.homebar` device chrome (real safe-area insets replace them), and
the `.stage`/`.phone` frame the whole thing was mocked inside.

What is added here is in two parts, kept separate on purpose.

**The shell.** The prototype's phone frame is a 390px box with a fixed app bar,
one scrolling middle, and bars pinned to the bottom. That is the app-shell
layout, and applying it to the viewport rather than to a mock is what makes
this work as an installed app: the page itself never scrolls, so there is no
address bar to collapse and nothing that can slide out from under a pinned
heading. v1 spent three attempts on that problem; the shape of this design
removes it.

**The four components the prototype had no use for.** It is an anytime-TD
board with five screens; the real app has six markets, a fitted shortlist with
a graded record, saved parlays that settle, and problem banners. Each of these
is built from the system's own tokens rather than invented beside it.
"""
from __future__ import annotations

from pathlib import Path

DESIGN = (Path(__file__).with_name("v2design.css")).read_text()


#: The app shell: one scrolling region between two pinned bars.
SHELL_CSS = """
/* ---------- the shell ---------- */
/*
 * The prototype's `.phone` was a 390px box with `display:flex` down its
 * length: a bar that does not scroll, a middle that does, and bars at the
 * bottom that do not. That is the whole layout, and it belongs to the
 * viewport rather than to a mock of one.
 *
 * `100dvh` and not `100vh`: iOS reports `vh` as the window with the address
 * bar hidden, so a `vh` shell is taller than the screen it is on and the
 * bottom bars sit below the fold. `overflow:hidden` on the body is what makes
 * `.scroll` the only scroller on the page — which is the property that ends
 * the address-bar problem rather than working around it.
 */
html,body{height:100%}
body{
  margin:0;height:100dvh;display:flex;flex-direction:column;overflow:hidden;
  background:var(--bg-base);color:var(--ink);font-family:var(--font-sans);
  overscroll-behavior:none;-webkit-font-smoothing:antialiased;
}
.appbar{
  flex:none;
  /* The status bar's height on a notched phone, and zero everywhere else. */
  padding-top:env(safe-area-inset-top);
  height:auto;min-height:calc(var(--bar-h) + env(safe-area-inset-top));
  padding-left:calc(var(--space-4) + env(safe-area-inset-left));
  padding-right:calc(var(--space-4) + env(safe-area-inset-right));
}
.scroll{
  flex:1;min-height:0;
  padding-left:env(safe-area-inset-left);padding-right:env(safe-area-inset-right);
  overscroll-behavior:contain;
}
.slipbar{
  padding-left:calc(var(--space-4) + env(safe-area-inset-left));
  padding-right:calc(var(--space-4) + env(safe-area-inset-right));
}
.tabbar{
  padding-left:env(safe-area-inset-left);padding-right:env(safe-area-inset-right);
  /* The home indicator sits over the bottom of the screen in an installed
     app. Added to the bar's height rather than inside it, so the tap targets
     stay 56px rather than being squeezed into what is left. */
  height:calc(var(--tabbar-h) + env(safe-area-inset-bottom));
  padding-bottom:env(safe-area-inset-bottom);
}
/* The sheet is fixed to the window now rather than to a phone mock, so it
   needs the same treatment at its bottom edge.

   `min-height:0` is the one that matters. `.sheet` is a flex column with a
   max-height, and a flex item will not shrink below its own content unless
   told to — so a body taller than the sheet did not scroll, it overflowed,
   and the sheet's `overflow:hidden`-by-radius clipped whatever was at the
   bottom. On a player's detail that is the two buttons, cut in half.

   The padding underneath them is the home indicator's, which sits over the
   last 34px of an installed app and would otherwise take the same bite. */
.sheet{max-height:82dvh}
.sheet__body{
  flex:1;min-height:0;
  padding-bottom:calc(var(--space-5) + env(safe-area-inset-bottom));
}
"""


#: The four the prototype had no use for, each built from the system's tokens.
EXTRA_CSS = """
/* ---------- banners ---------- */
/*
 * A market whose pipeline reported a problem, and the slip's one-market
 * prompt. The system has `.badge` for a word and `.prose` for a paragraph;
 * this is the thing in between — a sentence that has to be read before the
 * board under it means anything.
 */
.banner{
  display:flex;gap:var(--space-2);align-items:flex-start;
  padding:var(--space-3) var(--space-4);border-radius:var(--radius-md);
  font-size:14px;line-height:19px;
}
.banner--warn{background:var(--warn-soft);color:var(--warn)}
.banner--bad{background:var(--bad-soft);color:var(--bad)}
.banner b{font-weight:600}

/* ---------- toast ---------- */
/*
 * A banner says something that has to be read before the screen under it means
 * anything, and stays until it stops being true. This says something that was
 * true for one moment — a slip filed — and then takes it back. A receipt, not
 * a state, which is why nothing on the page reserves room for it.
 *
 * Above the tab bar rather than over it, and clear of the home indicator,
 * because the bottom 34px of an installed app is not the app's to draw in.
 * Under the scrim's z-index so an open sheet covers it: a sheet is a question
 * being asked, and nothing may float over the answer to one.
 */
.toast{
  position:fixed;z-index:19;left:50%;
  bottom:calc(var(--tabbar-h) + env(safe-area-inset-bottom) + var(--space-4));
  max-width:min(92vw,420px);
  display:flex;align-items:center;gap:var(--space-2);
  padding:var(--space-3) var(--space-4);border-radius:var(--radius-pill);
  background:var(--good-soft);color:var(--good);
  font-size:14px;line-height:19px;font-weight:600;
  box-shadow:var(--shadow-sheet);
  opacity:0;pointer-events:none;
  /* The resting position is the traveled-to one offset downward, so the
     open state is a plain `translate(-50%,0)` and the centering survives. */
  transform:translate(-50%,6px);
  transition:opacity .18s ease,transform .18s ease;
}
.toast--open{opacity:1;transform:translate(-50%,0)}

/* ---------- saved card ---------- */
/*
 * A saved slip's header, which is the whole card until it is opened. A button
 * rather than a row with a chevron in it: the target is the line you read, not
 * the 16px arrow at the end of it, and 44px of it at that.
 */
.pcard{
  display:flex;align-items:center;gap:var(--space-3);width:100%;
  min-height:var(--tap-target);
  background:none;border:0;padding:0;margin:0;
  color:inherit;font:inherit;text-align:left;cursor:pointer;
}
.pcard__m{flex:1;min-width:0}
.pcard__m>*{display:block}
.pcard__chev{
  flex:none;display:flex;color:var(--ink-faint);
  transition:transform .18s ease;
}
.pcard__chev--open{transform:rotate(180deg)}

@media (prefers-reduced-motion:reduce){
  .toast,.pcard__chev{transition:none}
}

/* ---------- funnel ---------- */
/*
 * What the shortlist rule removed, in the order it removed it. The counts are
 * the point as much as the survivors are: a week that ends with nothing has
 * to say which measurement emptied it, or it reads as a data problem rather
 * than as the answer. Scrolls sideways like `.chiprow`, because on a phone
 * five steps do not fit and wrapping them reads as two funnels.
 */
.funnel{
  display:flex;gap:var(--space-2);align-items:center;overflow-x:auto;
  padding:var(--space-3) var(--space-4) var(--space-1);scrollbar-width:none;
}
.funnel::-webkit-scrollbar{display:none}
.step{
  flex:none;display:inline-flex;align-items:center;height:var(--control-h);
  padding:0 var(--space-3);white-space:nowrap;
  background:var(--bg-surface);border:var(--hairline) solid var(--border-soft);
  border-radius:var(--radius-pill);font-size:13px;font-weight:500;
  font-variant-numeric:tabular-nums;
}
.step--last{background:var(--ink);color:var(--bg-surface);border-color:var(--ink);font-weight:600}
.funnel .sep{flex:none;color:var(--ink-faint);display:inline-flex}

/* ---------- breakdown ---------- */
/*
 * The parlay's shape: how many legs land, how likely that is, and what it
 * pays. Three columns of figures and no header row that repeats down the
 * page — a table, but the only one in the app, which is why it is 40 lines
 * rather than the grid machinery v1 needed.
 */
.brk{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
.brk th{
  padding:0 0 var(--space-2);text-align:right;
  font-size:10px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;
  color:var(--ink-faint);
}
.brk th:first-child{text-align:left}
.brk td{
  padding:var(--space-2) 0;text-align:right;font-size:15px;font-weight:600;
  border-top:var(--hairline) solid var(--separator);
}
.brk td:first-child{text-align:left;font-weight:500;color:var(--ink-muted)}
.brk tr:first-child td{border-top:0}
.brk .pos{color:var(--good)} .brk .neg{color:var(--bad)}

/* ---------- count ---------- */
/*
 * "147 of 530 shown", under every list. It was written with no class at all
 * and inherited the body's 14px sans at full ink, which put it at the weight
 * of the rows it was counting — the one line on the screen that is furniture
 * reading like content. It is the same 10px uppercase the metric labels use,
 * because it is the same kind of thing: a label on a number.
 */
.count{
  padding:var(--space-3) var(--space-4) var(--space-2);text-align:center;
  font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink-faint);font-variant-numeric:tabular-nums;
}

/* ---------- five metrics on a phone ---------- */
/*
 * Model · Book · Adj · Edge · EV, in the 290px a row's middle has on a 390px
 * screen. Five 40px minimums and four 12px gaps is 248, which fits — until a
 * value is wider than its minimum, and "−$16.86" is. The gap comes down to
 * 10 and the minimum goes with it; the labels are 10px uppercase and were
 * never the constraint.
 */
@media (max-width:480px){
  .metrics{gap:10px}
  .metric{min-width:34px}
}
/* Under about 340px the five no longer fit on one line, and a strip that
   overflows makes the whole row wider than the screen. Wrapping costs a
   taller row on the smallest phones still in use and costs nothing anywhere
   else. */
@media (max-width:340px){
  .metrics{flex-wrap:wrap;row-gap:6px}
}

/* ---------- six destinations ---------- */
/*
 * Saved earned a tab of its own, which makes six. At 390px that is 65px each
 * and at 320px it is 53px — enough for an 11px label, but only if the label
 * cannot push the tab wider than its share. `min-width:0` is what lets a flex
 * item be smaller than its content; without it six tabs overflow the bar and
 * the last one is off the screen.
 */
/*
 * A line where the tab bar meets whatever is above it.
 *
 * Both bars carry `--shadow-bar`, which is a 10%-opacity hairline — enough to
 * lift a single bar off a scrolling list and not enough to separate two bars
 * stacked on each other. Against the slip bar, which shares its background,
 * the two read as one tall footer. This is the separator the rest of the
 * design uses between things that are genuinely different, and it replaces
 * the shadow rather than joining it: two lines a pixel apart is a seam.
 */
.tabbar{box-shadow:none;border-top:var(--hairline) solid var(--separator)}
.tab{min-width:0;padding:0 2px}
.tab span:last-child{max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
@media (max-width:360px){ .tab{font-size:10px} }

/* ---------- swipe to clear ---------- */
/*
 * The slip bar, pulled left to show what is under it. A phone pattern and
 * only a phone pattern — it is driven by touch events, which a mouse does not
 * send, and the button behind it is hidden at the widths where the slip has
 * somewhere better to live.
 *
 * The bar moves and the button does not: the button is already there, at the
 * right-hand edge, with the bar sitting on top of it. That is why the
 * movement can follow a finger rather than play an animation at the end of
 * one.
 */
.slipwrap{position:relative;flex:none;overflow:hidden}
.slipdel{
  position:absolute;right:0;top:0;bottom:0;width:112px;border:0;
  background:var(--bad);color:#fff;font-size:15px;font-weight:600;
  display:flex;align-items:center;justify-content:center;gap:6px;
  padding-right:env(safe-area-inset-right);
}
.slipwrap .slipbar{position:relative;z-index:1;transition:transform .18s ease}
.slipwrap[data-swipe=open] .slipbar{transform:translateX(-112px)}
/* While a finger is on it there is no transition, or the bar lags the thumb
   by the length of the animation and feels stuck to the glass. */
.slipwrap[data-swipe=dragging] .slipbar{transition:none}

/* ---------- graded ---------- */
/* The rule's own record, printed wherever the rule is offered. Never the
   point estimate alone: on all four line markets the interval spans zero, and
   a number without it reads as a claim the measurement does not make. */
.graded{
  padding:0 var(--space-4) var(--space-3);
  font-size:13px;line-height:18px;color:var(--ink-muted);
}
.graded b{font-weight:600}
.graded .pos{color:var(--good)} .graded .neg{color:var(--bad)}

/* ---------- archived week ---------- */
/*
 * The past-week table had NO RULES AT ALL. Its markup shipped with `.row2`
 * and `.row2__rank` and nothing ever styled them, so every cell rendered as
 * an inline span and the whole thing ran together as one paragraph of text —
 * which is what a week looked like on a phone.
 *
 * A grid, and it wraps rather than scrolls: a table narrower than the screen
 * beats a table you have to drag sideways, and the seven O/U columns do not
 * fit 375px at a readable size.
 */
.ph{
  display:grid;gap:var(--space-2);align-items:end;
  padding:var(--space-2) var(--space-4);
  font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink-faint);border-bottom:var(--hairline) solid var(--separator);
}
.ph > span:not(:first-child){text-align:right}
.ph--td{grid-template-columns:minmax(0,1fr) 46px 46px 46px 58px}
.ph--ou{grid-template-columns:minmax(0,1fr) 40px 58px 44px 44px 44px 62px}
.pr{
  display:grid;gap:var(--space-2);align-items:baseline;
  padding:var(--space-2) var(--space-4);
  font-size:14px;line-height:19px;
}
.pr + .pr{border-top:var(--hairline) solid var(--separator)}
.pr--td{grid-template-columns:minmax(0,1fr) 46px 46px 46px 58px}
.pr--ou{grid-template-columns:minmax(0,1fr) 40px 58px 44px 44px 44px 62px}
.pr > span:not(.pr__n){text-align:right}
.pr__n{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pr__t{margin-left:6px;font-size:12px;color:var(--ink-faint)}
/* The book, muted, and the served number, accented — the same pairing the
   live board uses, so the two screens read the same way. */
.pr__b{color:var(--ink-muted)}
.pr__a{color:var(--accent);font-weight:600}
.pr__j{display:flex;flex-direction:column;align-items:flex-end;gap:0}
.pr__band{font-size:11px;color:var(--ink-faint);font-variant-numeric:tabular-nums}
.pr__r{display:flex;flex-direction:column;align-items:flex-end;gap:2px}
.badge--none{background:var(--bg-inset);color:var(--ink-faint)}

/* ---------- game lines ---------- */
/* One priced outcome: what it is, the consensus, the best, the gap, and who
   is offering it. A five-column grid rather than a table because the last
   column is a book name of unpredictable length and has to be allowed to
   truncate rather than push the numbers off the right edge of a phone. */
.gmk{
  display:flex;align-items:baseline;
  padding:var(--space-3) var(--space-4) var(--space-1);
  font-size:12px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;
  color:var(--ink-faint);
}
/* Four columns and a bar, not six columns. The book name moved UNDER the
   outcome: at 375px a fifth column of "hardrockbet_oh" either truncated to
   nothing or pushed the money off the right edge. */
.bl{
  display:grid;grid-template-columns:minmax(0,1fr) 46px 84px 62px;
  gap:var(--space-2);align-items:baseline;
  padding:var(--space-2) var(--space-4) var(--space-3);
  font-size:14px;line-height:19px;
}
.bl + .bl{border-top:var(--hairline) solid var(--separator)}
.bl__o{overflow:hidden;display:flex;flex-direction:column;gap:1px}
.bl__w{
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-size:11px;color:var(--ink-faint);
}
.bl__f{text-align:right;font-weight:600}
.bl__p{text-align:right;font-weight:600}
/* The consensus, beside the best it is being beaten by. Muted and small: it
   is context for the price, not a second price. */
.bl__c{font-weight:400;font-size:12px;color:var(--ink-faint)}
.bl__e{text-align:right;font-size:13px}
.bl__e.good{color:var(--good)} .bl__e.bad{color:var(--bad)}
/* The chance, drawn. Spans every column so a ladder of alternate lines reads
   as a shape rather than as numbers four tenths of a point apart. */
.blbar{
  grid-column:1/-1;height:4px;margin-top:var(--space-1);
  background:var(--bg-inset);border-radius:var(--radius-pill);overflow:hidden;
}
.blbar__f{display:block;height:4px;background:var(--border);border-radius:var(--radius-pill)}
/* On a graded week the bar carries the outcome, so a page of lines can be
   scanned for what happened without reading a single number. */
.blbar__f--won{background:var(--good)}
.blbar__f--lost{background:var(--bad)}

/* ---------- game list ---------- */
/* Sixteen fixtures you can read at once. Two lines, not five columns: at
   375px a spread, a total, a lean and a dollar figure will not sit beside a
   matchup at a readable size, and the first thing a five-column row drops is
   the one being scanned for. */
.glh, .gl{
  display:grid;
  grid-template-columns:minmax(0,1fr) minmax(0,88px) 22px;
  grid-template-areas:"g l c" "m m c";
  gap:2px var(--space-2);align-items:baseline;
  padding:var(--space-3) var(--space-4);width:100%;text-align:left;
}
.glh{
  grid-template-areas:"g l c";
  font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink-faint);border-bottom:var(--hairline) solid var(--separator);
}
.glh > span:nth-child(3){display:none}
.glh > span:nth-child(2){grid-area:l;text-align:right}
.glh > span:nth-child(4){display:none}
.gl{background:none;border:0;color:var(--ink);border-top:var(--hairline) solid var(--separator)}
.gl:first-of-type{border-top:0}
.gl--open{background:var(--bg-inset)}
.gl__g{grid-area:g;font-size:15px;font-weight:600;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.gl__l{grid-area:l;font-size:13px;color:var(--ink-muted);text-align:right}
.gl__m{grid-area:m;font-size:12px;color:var(--ink-faint);overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.gl__e{grid-area:l;grid-row:2;font-size:13px;text-align:right;color:var(--ink-muted)}
.gl__e.good{color:var(--good)}
.gl__c{grid-area:c;align-self:center;color:var(--ink-faint);transition:transform .15s}
.gl--open .gl__c{transform:rotate(90deg)}

/* ---------- model comparison ---------- */
/* Ours beside the market's, on the same row. The number that matters is the
   gap, and two figures in separate cards cannot be subtracted by eye. */
.mtable{margin-top:var(--space-3)}
.mrow{
  display:grid;grid-template-columns:minmax(0,1fr) 64px 64px;
  gap:var(--space-2);padding:var(--space-2) 0;font-size:14px;
}
.mrow + .mrow{border-top:var(--hairline) solid var(--separator)}
.mrow > span:not(:first-child){text-align:right}
.mrow--h{
  font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink-faint);
}
.mrow__m{color:var(--ink-muted)}

/* ---------- picker ---------- */
/* One control that opens a sheet, in place of a horizontal row of pills.
   Sixteen fixtures in a scroller put most of them off-screen with no way to
   see what you were choosing between. */
.picker{
  display:flex;align-items:center;gap:var(--space-2);width:100%;
  min-height:var(--tap-target);padding:var(--space-2) var(--space-4);
  background:var(--bg-surface);border:var(--hairline) solid var(--border-soft);
  border-radius:var(--radius-md);color:var(--ink);text-align:left;
}
.picker__l{font-size:12px;color:var(--ink-faint);flex:none}
.picker__v{flex:1;font-size:15px;font-weight:600;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}

/* ---------- matchup card ---------- */
/* Blocks with rules between them and a label on each. The previous card ran a
   score, a bar and three price tables together with nothing saying which was
   which — and an unlabelled 66/34 split reads as the share of bets on each
   team, which it is not. */
.gc__head{
  display:flex;justify-content:space-between;align-items:baseline;gap:var(--space-2);
  padding:var(--space-4) var(--space-4) var(--space-3);
  border-bottom:var(--hairline) solid var(--separator);
}
.gc__teams{font-size:17px;font-weight:600}
.gc__fin{font-size:12px;color:var(--ink-muted)}
.gc__fin b{font-size:15px;color:var(--ink);margin-right:4px}
.gc__when{font-size:12px;color:var(--ink-faint)}
.gc__blk{padding:var(--space-3) var(--space-4)}
.gc__blk + .gc__blk{border-top:var(--hairline) solid var(--separator)}
.gc__lbl{
  display:flex;align-items:baseline;gap:var(--space-2);
  font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink-faint);
}
.gc__hint{
  font-weight:400;letter-spacing:0;text-transform:none;font-size:11px;
  color:var(--ink-faint);
}
.gc__hint--warn{color:var(--warn)}
.gc__score{display:flex;align-items:baseline;gap:var(--space-2);margin-top:2px}
.gc__score .num{font-size:24px;font-weight:600;letter-spacing:-.01em}
.gc__score--ours .num{color:var(--accent)}
.gc__dash{color:var(--ink-faint)}
.gc__line{margin-left:auto;font-size:12px;color:var(--ink-muted);text-align:right}
.gc__vs{margin-top:var(--space-2);font-size:12px;color:var(--ink-muted)}
/* Both sides of one question, so one bar. Two numbers side by side invite
   the reader to compare them to 50 rather than to each other. */
.split{
  display:flex;height:26px;margin-top:var(--space-2);
  border-radius:var(--radius-sm);overflow:hidden;font-size:12px;
}
.split span{
  display:flex;align-items:center;gap:4px;padding:0 var(--space-2);
  overflow:hidden;white-space:nowrap;
}
.split__a{background:var(--bg-segment);color:var(--ink-muted)}
.split__h{background:var(--accent-soft);color:var(--accent);justify-content:flex-end}
.split b{font-weight:600}
.gmk__h{margin-left:auto;font-weight:400;text-transform:none;letter-spacing:0}
/* Movement drops the book column: the mover is the market, not one book. */
.bl--mv{grid-template-columns:minmax(0,1fr) 52px 52px 68px}
.bl--mv .bl__g.good{color:var(--good)} .bl--mv .bl__g.bad{color:var(--bad)}

/* ---------- bet definitions ---------- */
/* Hit rate, the price it is measured against, and the interval drawn over
   that price. The bar straddling the marker IS the finding, so it is drawn
   rather than described — a reader who skips the verdict line still sees it. */
/* The headline result, stated once at the top. "No edge" is a finding and
   reads as one here; six red rows read as six things being broken. */
.verdict{padding:var(--space-4)}
.verdict__t{font-size:17px;font-weight:600;line-height:23px}
.verdict__b{margin-top:var(--space-2);font-size:14px;line-height:20px;color:var(--ink-muted)}
.def{padding:var(--space-3) var(--space-4)}
.def + .def{border-top:var(--hairline) solid var(--separator)}
.def__t{display:flex;gap:var(--space-2);align-items:baseline;font-size:15px;line-height:20px;font-weight:600}
.def__n{margin-left:auto;font-size:12px;color:var(--ink-faint);flex:none;font-weight:400}
/* Neutral. A measurement that came back "no" is not an error, and toning it
   red made the page read as a list of faults. */
.def__s{margin-top:2px;font-size:14px;line-height:20px;color:var(--ink-muted)}
.def__s b{font-weight:600;color:var(--ink)}
.ci{
  position:relative;height:6px;margin:var(--space-2) 0 var(--space-1);
  background:var(--bg-inset);border-radius:var(--radius-pill);
}
.ci__bar{
  position:absolute;top:0;height:6px;
  background:var(--border);border-radius:var(--radius-pill);
}
/* The price the interval has to clear. A 2px rule, full height, so it reads
   as a threshold rather than as another value on the bar. */
.ci__bar--good{background:var(--good)}
.ci__bar--bad{background:var(--bad)}
.ci__mark{position:absolute;top:-3px;width:2px;height:12px;background:var(--ink)}
"""


#: Wider screens, and only where the phone layout stops being the right shape.
DESKTOP_CSS = """
/* ---------- wider ---------- */
/*
 * Mobile first, and this is the "also works on a desktop" half.
 *
 * The column does not grow past a reading measure. A list of rows at 1440px
 * is not more readable for being 1440px wide — it is the same rows with the
 * name and the numbers pushed apart, which is the comparison the metrics
 * strip exists to make easy.
 */
@media (min-width:700px){
  .scroll>.inner,.slipwrap .slipbar{max-width:760px;margin-left:auto;margin-right:auto}
}
@media (min-width:1000px){
  .scroll>.inner,.slipwrap .slipbar{max-width:940px}
  /* The room is there, so the row stops hiding two of its numbers. Rendered
     on every row at every width and hidden below this one, rather than
     rebuilt when the window changes — a resize does not re-render. */
  .metric--wide{display:flex}
  /* And the name gets the space the extra metrics do not need. */
  .row__name{font-size:17px}
}
@media (min-width:1280px){
  .scroll>.inner,.slipwrap .slipbar{max-width:1100px}
}
/* Two of a row's six metrics are for screens with room for them. */
.metric--wide{display:none}
/* Swiping is a touch gesture; a mouse never sends one, and above this width
   the slip is a tab away rather than a bar to be dismissed. */
@media (min-width:900px){
  .slipdel{display:none}
  .slipwrap[data-swipe=open] .slipbar{transform:none}
}
/*
 * The tab bar comes up into the header. Five destinations at the bottom of a
 * 1080px window is a phone pattern being worn by something that is not a
 * phone — the thumb argument that puts it there does not apply to a mouse.
 */
/* Under 420px the seven-column O/U row stops being readable. The projection
   band and the model column go first: the band is a detail of the projection
   beside it, and the model is recoverable from the adj and the book. */
@media (max-width:420px){
  .ph--ou{grid-template-columns:minmax(0,1fr) 38px 46px 42px 42px 56px}
  .pr--ou{grid-template-columns:minmax(0,1fr) 38px 46px 42px 42px 56px}
  .ph--ou > span:nth-child(4), .pr--ou > span:nth-child(4){display:none}
  .pr__band{display:none}
}

@media (min-width:900px){
  .tabbar{
    order:-1;height:auto;padding:0;box-shadow:none;
    background:transparent;justify-content:center;gap:var(--space-1);
  }
  .tab{
    flex:none;flex-direction:row;gap:var(--space-2);height:40px;padding:0 14px;
    border-radius:var(--radius-pill);font-size:15px;
  }
  .tab[aria-current=page]{background:var(--accent-soft)}
  /* Which puts it inside the header, so the header owns the height. */
  .appbar{
    min-height:calc(var(--bar-h) + env(safe-area-inset-top));
    display:flex;align-items:center;
  }
  .shellbars{display:contents}
}
"""


def css() -> str:
    """The whole stylesheet, in cascade order."""
    return DESIGN + SHELL_CSS + EXTRA_CSS + DESKTOP_CSS
