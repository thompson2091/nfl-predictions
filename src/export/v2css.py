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
   needs the same treatment at its bottom edge. */
.sheet{max-height:82dvh}
.sheet__body{padding-bottom:calc(var(--space-5) + env(safe-area-inset-bottom))}
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
  .scroll>.inner{max-width:680px;margin:0 auto}
  .appbar{max-width:none}
  .appbar__inner,.slipbar__inner{max-width:680px;margin:0 auto;width:100%;
    display:flex;align-items:center;gap:var(--space-3)}
}
/*
 * The tab bar comes up into the header. Five destinations at the bottom of a
 * 1080px window is a phone pattern being worn by something that is not a
 * phone — the thumb argument that puts it there does not apply to a mouse.
 */
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
