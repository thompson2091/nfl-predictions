"""site/v4 — the Hashmark stylesheet.

**THE COMPONENT RULES ARE v3's, UNCHANGED, AND THAT IS THE WHOLE POINT.**
`v3css.COMPONENTS` is 1,400 lines of rules for a class vocabulary — `.card`,
`.row`, `.strip`, `.cell`, `.seg`, `.mkt`, `.tag`, `.num` — and every one of
those rules reads its colors, type and spacing from custom properties rather
than from literals. So a new look is a new token block, not a new stylesheet,
and v3's screen builders render in it without being touched.

What that buys: `v3GameOdds`, `v3GamePlayers`, `v3GameMatchup`, `v3Angles` and
the whole Record page keep working and come out in Hashmark. What it costs is
that anything the design draws DIFFERENTLY from v3 — the day-grouped game
cards, the dark game header, the display type — has to be said again here, at
the bottom, where it wins. That trade is the same one `v3.py` records about
v1's calculation layer, and it is made for the same reason: refactoring the
tested thing to serve the untested one is how both get broken.

The palette is read off `project/System.dc.html` on the design canvas, which
is the artboard that declares it rather than one that happens to use it:

    ink      #10140F   text, active states, summary cards
    ink-2    #4B524C   secondary text, labels
    ground   #F3F4F1   screen background
    surface  #FFFFFF   cards, lists, sheets
    line     #DEE1DC   hairlines and borders
    action   #C6F24E   main action, current selection
    star     #D9A21B   starred players and bets only
    value +  #0A4FA3   tint #E3EDFB
    value −  #A2480A   tint #FCEBDD

**NO GREEN AND NO RED.** v3 grades with #1C6B42 and #9E3624; Hashmark grades
with blue and orange. That is not a palette preference — about one man in
twelve cannot separate the first pair, and every number on this app that
carries a verdict carries it in color. Blue and orange differ in lightness as
well as hue, so they survive being printed, screenshotted and color-blind.
"""
from __future__ import annotations

from src.export.v3css import COMPONENTS

#: The Hashmark tokens, in v3's own names so v3's rules pick them up.
#:
#: Named for v3's vocabulary rather than Hashmark's because the 1,400 lines
#: below ask for `var(--ours)` and `var(--mut2)`; renaming the tokens would
#: mean rewriting every rule that reads one, which is the opposite of the
#: trade this module exists to make. The Hashmark name is in the comment.
HASHMARK: dict[str, str] = {
    # Ground and ink.
    "bg": "#F3F4F1",        # ground
    "card": "#FFFFFF",      # surface
    "inset": "#ECEEEA",
    "sunk": "#E6E8E4",
    "line": "#DEE1DC",      # line
    "line2": "#EEF0EC",
    "line3": "#F1F2EF",
    "btnline": "#C9CEC8",
    "ink": "#10140F",       # ink
    "mut": "#4B524C",       # ink-2
    "mut2": "#6B726C",
    "mut3": "#A9B0A9",
    # Meaning. `ours` is Hashmark's "value +", and `good` is the same color
    # on purpose: the app's one positive signal is "our number beats the
    # price", so a second green for "this bet won" would be a second claim
    # wearing a first-class color.
    "ours": "#0A4FA3",
    "oursbg": "#E3EDFB",
    "oursfaint": "#7FB2F5",
    "good": "#0A4FA3",
    "goodbg": "#E3EDFB",
    "goodline": "#C3D8F2",
    "gooddot": "#0A4FA3",
    "bad": "#A2480A",       # value −
    "badbg": "#FCEBDD",
    "baddot": "#C2560A",
    "warn": "#6B4A0E",
    "warnbg": "#FBEFD9",
    "star": "#D9A21B",      # star
    "starline": "#B8860B",
    "seg": "#E6E8E4",
    "navon": "#ECEEEA",
    "pend": "#A9B0A9",
    # THE ACCENT, WHICH v3 HAS NO TOKEN FOR.
    #
    # #C6F24E is the one color in this design that means "press this" and
    # nothing else. It is deliberately NOT in the meaning group: a lime
    # background behind a number would read as a verdict, and the design
    # spends it only on the primary action and the current selection.
    #
    # It fails contrast against white text by a mile and passes against ink,
    # which is why every rule below that uses it also sets `color:var(--ink)`.
    "action": "#C6F24E",
    "actionink": "#10140F",
    # Type. Three faces, each with a job: Barlow Condensed for display
    # numbers and headings, Geist for everything that is read as a sentence,
    # Geist Mono for anything a reader compares down a column.
    "sans": "'Geist',system-ui,-apple-system,BlinkMacSystemFont,sans-serif",
    "display": "'Barlow Condensed','Arial Narrow',Impact,sans-serif",
    "mono": "'Geist Mono',ui-monospace,SFMono-Regular,Menlo,monospace",
    # Kept so v3's one `var(--serif)` rule resolves to something real rather
    # than to the browser's default serif, which is not in this design.
    "serif": "'Barlow Condensed','Arial Narrow',sans-serif",
    "t-xs": "11px", "t-sm": "12px", "t-md": "13px", "t-base": "15px",
    "t-lg": "17px", "t-xl": "22px", "t-2xl": "30px", "t-3xl": "40px",
    # Space, on the design system's own scale.
    "s1": "4px", "s2": "8px", "s3": "12px", "s4": "16px",
    "s5": "24px", "s6": "32px", "s7": "48px", "s8": "56px",
    # Radius: chip, control, button, card, sheet.
    "r-sm": "6px", "r-md": "10px", "r-lg": "14px", "r-xl": "16px",
    "r-pill": "999px", "r-sheet": "22px",
    "e1": "0 1px 3px rgba(16,20,15,.10)",
    "e2": "0 6px 20px rgba(16,20,15,.18)",
    "e3": "0 12px 32px rgba(16,20,15,.14)",
    "header": "64px", "aside": "360px", "gutter": "40px",
}


def tokens_css() -> str:
    """One `:root` block. `color-scheme:light` for the same reason v1 gives.

    The design system ships a dark palette (ground #0D110E, surface #171C18,
    line #2E3530, ink #EEF1EC, lime unchanged) and nothing here reads it yet.
    It is left out rather than half-applied: a mechanical inversion would put
    the blue and the orange on a black ground, where neither carries the
    lightness difference that makes them separable, and the point of choosing
    them over green and red would be lost in the one mode nobody checked.
    """
    body = "".join(f"--{k}:{v};" for k, v in HASHMARK.items())
    return ":root{color-scheme:light;" + body + "}"


#: Everything the design draws differently from v3. Appended LAST so it wins.
CHROME = """
/* ---- type: three faces, each with a job ------------------------------
   `.num` is the lever. Every figure v3 renders already carries it — it was
   added for `font-variant-numeric` — so one rule here puts Geist Mono under
   every number in the app without touching a single screen builder. */
.num{font-family:var(--mono);font-variant-numeric:tabular-nums;
  letter-spacing:-.01em}

/* THE DISPLAY FACE IS FOR NUMBERS AND TITLES, NOT FOR PROSE.
   Barlow Condensed at 38px is the design's page title and its big figures.
   It is condensed, which is what makes a 40px number fit a phone column, and
   condensed is exactly wrong for a paragraph: `.lede` and `.help` stay in
   Geist. */
.h1{margin:14px 0 0;font-family:var(--display);font-size:38px;line-height:38px;
  font-weight:700;text-transform:uppercase;letter-spacing:.005em}
.big{font-family:var(--display);font-weight:700;letter-spacing:.005em}
.lede{margin:8px 0 0;font-size:15px;line-height:21px;color:var(--mut)}

/* ---- the app bar: a wordmark and four round targets -------------------
   The design puts the week picker, search, ask and settings in 44px circles
   on the right of a condensed wordmark. 44 is not a style choice: it is the
   smallest target a thumb hits reliably, and the row is the one piece of
   chrome present on every screen. */
.appbar{padding:calc(10px + env(safe-area-inset-top,0px)) 16px 0}
.brand{font-family:var(--display);font-size:22px;font-weight:700;
  letter-spacing:.06em;text-transform:uppercase;white-space:nowrap}
.bargroup{display:flex;align-items:center;gap:6px}
.iconbtn{width:44px;height:44px;flex:none;border-radius:22px;
  background:var(--card);border:1px solid var(--line);display:flex;
  align-items:center;justify-content:center;color:var(--ink)}
.pillbtn{height:44px;padding:0 10px 0 12px;border-radius:22px;
  background:var(--card);border:1px solid var(--line);display:flex;
  align-items:center;gap:4px;font-size:13px;font-weight:600;
  white-space:nowrap;color:var(--ink)}
/* WHEN THE PRICES WERE READ, ON EVERY SCREEN THAT SHOWS ONE.
   A board with no timestamp is a board a reader has to trust; this app's
   whole subject is numbers that move. The dot is green because it is a
   liveness indicator and not a verdict — it is the one green in the app and
   it never sits next to a result. */
.fresh{display:flex;align-items:center;gap:6px;padding:6px 16px 0;
  font-size:11px;color:var(--mut)}
.fresh i{width:7px;height:7px;border-radius:4px;background:#3E9B3A;
  flex:none;font-style:normal}
.fresh--stale i{background:var(--baddot)}

/* ---- the tab bar: five tabs, lit by ink rather than by color ---------
   v3's tab bar tints the active tab's background. Hashmark darkens its icon
   and its label instead and leaves the ground alone, so the bar reads as one
   surface and the lime stays reserved for things you press to DO something
   rather than to go somewhere. */
.tabbar{height:84px;flex:none;background:var(--card);
  border-top:1px solid var(--line);display:grid;
  grid-template-columns:repeat(5,minmax(0,1fr));
  padding:4px 4px calc(0px + env(safe-area-inset-bottom,0px));
  box-sizing:border-box}
.tab{height:50px;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:3px;font-size:11px;font-weight:500;
  color:var(--mut2);background:none;border:0}
.tab[aria-current="page"]{font-weight:600;color:var(--ink)}
.tab svg{stroke-width:1.7}
.tab[aria-current="page"] svg{stroke-width:2.1}

/* ---- the games list --------------------------------------------------
   FIVE COLUMNS, AND THE HEADER IS THE SAME GRID AS THE ROWS.
   Win chance, spread, model, book, adjusted. The header lives outside the
   scrolling pane and the rows inside it, so the two grids are declared once
   as a custom property rather than twice as a pair of literals that drift. */
.gl{--gcols:minmax(0,1fr) 52px 44px 44px 44px}
.gl__hd{display:grid;grid-template-columns:var(--gcols);gap:6px;
  padding:0 14px;font-size:11px;font-weight:600;letter-spacing:.04em;
  text-transform:uppercase;color:var(--mut)}
.gl__hd b{font-weight:600;text-align:right}
.gl__hd b.m{color:var(--ours)}
.gl__day{padding:6px 2px 0;font-family:var(--mono);font-size:11px;
  font-weight:500;letter-spacing:.08em;color:var(--mut)}
.gc{display:flex;flex-direction:column;gap:8px;background:var(--card);
  border:1px solid var(--line);border-radius:var(--r-lg);padding:12px 14px;
  color:var(--ink);text-align:left;width:100%}
.gc__t{display:flex;justify-content:space-between;align-items:center;gap:8px}
.gc__g{display:grid;grid-template-columns:var(--gcols);gap:6px;row-gap:6px;
  align-items:center}
.gc__team{font-size:16px;font-weight:600}
.gc__n{text-align:right;font-family:var(--mono);font-size:14px}
.gc__n--lead{font-weight:700;color:var(--ours)}
.gc__n--mut{color:var(--mut)}
.gc__f{display:flex;justify-content:space-between;gap:10px;padding-top:8px;
  border-top:1px solid var(--line2);font-family:var(--mono);font-size:12px;
  color:var(--mut)}
.gc__f span{min-width:0;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}

/* ---- filter chips ----------------------------------------------------
   Lime for the pressed one. These SCROLL sideways on purpose: there are four
   and the longest is "Model picks other side", which does not divide a phone
   into equal parts the way the market segments do. */
.chips{display:flex;gap:8px;overflow-x:auto;scrollbar-width:none;
  margin:0 -16px;padding:0 16px}
.chips::-webkit-scrollbar{display:none}
.chips>*{flex:none}
.chip{height:44px;padding:0 12px;border-radius:18px;background:var(--card);
  border:1px solid var(--line);display:flex;align-items:center;gap:6px;
  font-size:13px;font-weight:600;white-space:nowrap;color:var(--ink)}
.chip[aria-pressed="true"]{background:var(--action);border-color:var(--action);
  color:var(--actionink)}
.chip i{font-style:normal;font-family:var(--mono);font-size:11px;
  color:var(--mut)}
.chip[aria-pressed="true"] i{color:var(--actionink);opacity:.7}

/* ---- the game screen's dark header ----------------------------------
   The one inverted surface in the app, and it marks the one place you are
   inside something rather than scanning a list. The section nav under it
   underlines in lime, which is the only place lime marks a position rather
   than an action — a tab you are on IS the current selection, which is what
   the token is for. */
.ghead{background:var(--ink);color:#FFFFFF;flex:none;
  padding:calc(10px + env(safe-area-inset-top,0px)) 12px 0;
  display:flex;flex-direction:column;gap:10px}
.ghead__t{display:flex;align-items:center;justify-content:space-between;
  gap:8px}
.ghead__n{font-family:var(--display);font-size:30px;font-weight:700;
  line-height:1;min-width:0;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.ghead__n i{font-family:var(--mono);font-size:13px;font-weight:500;
  font-style:normal;color:var(--mut3)}
.ghead .iconbtn{background:#232A24;border-color:#232A24;color:#FFFFFF}
.gocta{height:40px;padding:0 14px;flex:none;border-radius:20px;
  background:var(--action);color:var(--actionink);display:flex;
  align-items:center;gap:6px;font-size:14px;font-weight:700;border:0}
.gnav{display:flex;gap:20px;overflow-x:auto;scrollbar-width:none;padding:0 4px}
.gnav::-webkit-scrollbar{display:none}
.gnav button{height:42px;flex:none;display:flex;align-items:center;
  font-size:15px;font-weight:500;color:var(--mut3);background:none;border:0;
  border-bottom:3px solid transparent}
.gnav button[aria-current="page"]{font-weight:600;color:#FFFFFF;
  border-bottom-color:var(--action)}

/* ---- the 21+ line, which is not decoration --------------------------- */
.legal{margin-top:8px;min-height:44px;display:flex;align-items:center;
  justify-content:center;gap:8px;font-size:12px;color:var(--mut);
  text-align:center}
.legal b{height:20px;padding:0 6px;border-radius:5px;background:var(--ink);
  color:var(--action);font-size:11px;font-weight:700;display:flex;
  align-items:center;flex:none}

/* ---- tags, restated in the Hashmark palette --------------------------
   v3's `.tag--good` and `.tag--bad` resolve through the tokens already. The
   two that need saying again are the ones whose v3 rule hardcodes a tint. */
.tag--ours{background:var(--oursbg);color:var(--ours)}
.tag--warn{background:#FCEBDD;color:#8A3C08}
.tag--doubt{background:#FFF1E6;color:#A2480A}
"""


def css() -> str:
    """Tokens, then v3's components, then what the design draws differently."""
    return tokens_css() + COMPONENTS + CHROME
