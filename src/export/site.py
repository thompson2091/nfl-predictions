"""One file, five pages: the board as a product rather than a tab strip.

`src/export/dashboard.py` grew nine tabs because every question that came up
got one, and a tab strip is the cheapest place to put a thing. The cost showed
up in what opened first: a reader arriving at nine equal tabs has to know which
one answers "what should I look at this week", and the answer was spread across
four of them.

This is the same data under the design in `design/`. Five pages — This week,
Shortlist, Saved, Ladder, Model — and the nine tabs fold in rather than
disappear: Players is the board on This week, Favorites is the star on each row
and a chip that filters to them, Parlay is the slip beside the board,
Combinations sits under the board, Teams is what a game chip opens, and
Receptions is an entry in the market menu.

Still one self-contained file. Everything is inline including the two variable
fonts, because the page has always been a thing you can send to someone who
does not have the repo, and a page that needs a font server is not that.

Routing is the location hash, so the five pages are five URLs you can link to
and the back button works, without the file ever stopping being one file.

**What is saved, and for how long.** Favorites, the working slip and saved
parlays all live in localStorage under a key carrying the season and week, and
a new week starts empty. That is a deliberate narrowing: a parlay saved on
Wednesday still settles on Sunday and shows its result, so the Saved page keeps
its status dots, its Won/Lost filters and a net figure — it just does not carry
last week's into this one. Nothing is sent anywhere.
"""
from __future__ import annotations

import base64
import html
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FONT_DIR = PROJECT_ROOT / "design" / "fonts"

#: The two faces the design is drawn in, embedded as data URIs.
#:
#: Both are variable fonts, so one file covers every weight the page uses and
#: the six @font-face blocks the canvas exported collapse to two. Latin subset
#: only: the canvas carried Vietnamese and Latin-Extended as well, which is
#: 270KB for scripts no NFL roster contains.
#:
#: Absent, the page still renders — the stacks below fall back to Georgia and
#: Helvetica, which is a fair approximation and not the design.
FONT_FILES = {"Newsreader": "Newsreader.woff2",
              "Schibsted Grotesk": "SchibstedGrotesk.woff2"}


def _font_faces() -> str:
    out = []
    for family, name in FONT_FILES.items():
        p = FONT_DIR / name
        if not p.exists():
            continue
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        out.append(
            "@font-face{font-family:'%s';font-style:normal;font-weight:300 800;"
            "font-display:swap;src:url(data:font/woff2;base64,%s) format('woff2')}"
            % (family, b64))
    return "".join(out)


CSS = """
/* ── Tokens ──────────────────────────────────────────────────────────────
   Read off the artboards in design/, named for what they mean rather than
   what colour they are, so a theme change is a block of declarations and not
   a search for #1F4FA3.

   There is no dark mode. The design is a single committed look on a warm
   paper ground, and a mechanical inversion of it is not the same design —
   the greens and reds carry meaning against #F5F3EE that they lose against
   black. `color-scheme: light` stops the browser helping. */
:root{
  color-scheme: light;
  --bg:#F5F3EE; --card:#FFFFFF; --inset:#F7F5F0; --sunk:#EEEBE4;
  --line:#E3DFD6; --line2:#ECE8E0; --line3:#F0EDE6; --btnline:#D6D1C6;
  --ink:#16181D; --mut:#5E6168; --mut2:#6B6E75; --mut3:#8A8D93;
  --ours:#1F4FA3; --oursbg:#EEF2FA; --oursfaint:#B9C8E6;
  --good:#1C6B42; --goodbg:#E3F0E8; --goodline:#BFD9C8; --gooddot:#1C7A4A;
  --bad:#9E3624; --badbg:#F6E4E0; --baddot:#B3402F;
  --warn:#7A5410; --warnbg:#FBEFD9;
  --star:#D9A21B; --starline:#B8860B;
  --seg:#E9E5DC; --navon:#EFECE5; --pend:#C9C4B8;
  --sans:'Schibsted Grotesk','Helvetica Neue',-apple-system,BlinkMacSystemFont,sans-serif;
  --serif:'Newsreader',Georgia,'Times New Roman',serif;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background:var(--bg); color:var(--ink); font-family:var(--sans);
  font-size:15px; line-height:1.45;
  /* Every table on this page is a column of numbers being compared down its
     length. Proportional digits make 11.1% and 88.8% different widths, and
     the column stops being scannable. */
  font-variant-numeric:tabular-nums;
  -webkit-font-smoothing:antialiased;
}
a{color:var(--ink);text-underline-offset:2px}
a:hover{color:var(--ours)}
button,input,select{font-family:inherit;font-size:inherit;color:inherit}
h1,h2,h3{margin:0;font-weight:600}
:focus-visible{outline:2px solid var(--ours);outline-offset:2px;border-radius:6px}

/* ── Shell ───────────────────────────────────────────────────────────── */
.top{
  height:64px; padding:0 40px; display:flex; align-items:center; gap:40px;
  border-bottom:1px solid var(--line); background:var(--card);
  position:sticky; top:0; z-index:30;
}
.brand{font-family:var(--serif);font-size:22px;font-weight:600;white-space:nowrap}
.nav{display:flex;gap:8px;flex-grow:1;flex-wrap:wrap}
.nav a{
  padding:10px 14px;border-radius:8px;font-size:15px;text-decoration:none;
  color:var(--mut);white-space:nowrap;
}
.nav a:hover{background:var(--inset);color:var(--ink)}
.nav a[aria-current=page]{background:var(--navon);color:var(--ink);font-weight:600}
.when{font-size:14px;color:var(--mut);white-space:nowrap}
.wrap{display:flex;align-items:flex-start;min-height:0}
/* No max-width. The tables are the content and they are wide; a reading
   measure would only push the numbers being compared further apart. */
main{flex-grow:1;padding:28px 40px 40px;display:flex;flex-direction:column;gap:18px;min-width:0}
/* The slip is not furniture. It takes 360px of the board's width, so it is
   present only while it holds something or has been asked for, and can be put
   away again without emptying it. */
aside{
  width:360px;flex-shrink:0;border-left:1px solid var(--line);background:var(--card);
  padding:24px 24px 32px;display:flex;flex-direction:column;gap:14px;
  /* The full height of the window under the header, not just as tall as its
     contents. A panel that stops halfway down leaves a seam of page
     background beside the board and reads as something that failed to load. */
  position:sticky;top:64px;height:calc(100vh - 64px);overflow-y:auto;
}
.asidehead{display:flex;justify-content:space-between;align-items:center;gap:12px}
/* The handle that brings it back. Fixed to the viewport rather than the page,
   because the board is long and a control at the top of a 500-row table is a
   control you have to scroll to find. */
.sliptab{
  position:fixed;right:20px;bottom:20px;z-index:25;height:48px;padding:0 20px;
  border-radius:999px;border:1px solid var(--ink);background:var(--ink);color:#fff;
  font-size:15px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;
  gap:10px;box-shadow:0 6px 20px rgba(22,24,29,.22);
}
.sliptab .n{
  background:#fff;color:var(--ink);border-radius:999px;min-width:22px;height:22px;
  display:inline-flex;align-items:center;justify-content:center;font-size:13px;
}
.pagehead{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;flex-wrap:wrap}
h1{font-family:var(--serif);font-weight:500;font-size:40px;line-height:1.1}
.lede{margin:6px 0 0;font-size:15px;color:var(--mut);max-width:640px}
h2{font-size:18px}
.h2s{font-family:var(--serif);font-weight:500;font-size:28px}

/* ── Surfaces ────────────────────────────────────────────────────────── */
.card{background:var(--card);border:1px solid var(--line);border-radius:14px}
.card.pad{padding:20px 24px}
.panel{background:var(--inset);border-radius:10px;padding:12px}
.note{color:var(--mut2);font-size:13px}
.fine{color:var(--mut2);font-size:13px;margin:0}
.muted{color:var(--mut);margin:0}
.warnbox{background:var(--warnbg);color:var(--warn);border-radius:10px;padding:12px 14px;font-size:14px}
.badbox{background:var(--badbg);color:var(--bad);border-radius:10px;padding:12px 14px;font-size:14px}
.pos{color:var(--good)} .neg{color:var(--bad)}

/* ── Controls ────────────────────────────────────────────────────────── */
.chip{
  height:36px;padding:0 14px;border-radius:999px;font-size:14px;cursor:pointer;
  background:var(--card);color:var(--ink);border:1px solid var(--btnline);
  display:inline-flex;align-items:center;gap:8px;white-space:nowrap;
}
.chip:hover{border-color:var(--mut3)}
.chip[aria-pressed=true]{background:var(--ink);color:#fff;border-color:var(--ink)}
.chiprow{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.seg{display:flex;background:var(--seg);border-radius:10px;padding:3px}
.seg button{
  height:36px;padding:0 16px;border:none;border-radius:8px;font-size:14px;
  cursor:pointer;background:transparent;color:var(--mut);
}
.seg button[aria-pressed=true]{
  background:var(--card);color:var(--ink);font-weight:600;box-shadow:0 1px 2px rgba(0,0,0,.08);
}
.btn{
  height:44px;padding:0 18px;border-radius:10px;border:1px solid var(--btnline);
  background:var(--card);color:var(--ink);font-size:15px;cursor:pointer;
  display:inline-flex;align-items:center;justify-content:center;gap:8px;
}
.btn:hover{border-color:var(--mut3)}
.btn.solid{background:var(--ink);color:#fff;border-color:var(--ink);font-weight:600}
.btn.solid:hover{background:#000;border-color:#000}
/* The one primary action in the slip. Taller than a control, full width, and
   separated from the text above it so it does not read as another paragraph. */
.btn.primary{height:48px;font-size:15px;font-weight:600;border-radius:10px;width:100%}
.btn.primary[disabled]{opacity:.5;cursor:default}
.btn.done{background:var(--goodbg);color:var(--good);border-color:var(--goodline);font-weight:600}
.btn.wide{width:100%}
/* 44px is the floor for anything a finger has to find. It applies to the star
   and the × as much as to the buttons, which is why they are sized here and
   not left to whatever the glyph happens to be. */
.icon{
  width:44px;height:44px;border:none;background:transparent;cursor:pointer;
  display:flex;align-items:center;justify-content:center;padding:0;color:var(--mut2);
}
.add{
  width:44px;height:44px;border-radius:10px;cursor:pointer;font-size:18px;font-weight:600;
  background:var(--card);color:var(--ink);border:1px solid var(--btnline);
}
.add[aria-pressed=true]{background:var(--ours);color:#fff;border-color:var(--ours)}
/* label / control / hint, always in that order and always the same height, so
   a field carrying a hint does not push its neighbours out of line. The ladder
   had three inputs at three different heights for exactly this reason. */
.linkbtn{
  border:none;background:transparent;color:var(--mut);font-size:13px;cursor:pointer;
  padding:6px 8px;border-radius:8px;min-height:32px;
}
.linkbtn:hover{background:var(--badbg);color:var(--bad)}
.field{display:flex;flex-direction:column;gap:4px;min-width:0}
.field label{font-size:12px;color:var(--mut2);line-height:16px}
.field .hint{font-size:12px;color:var(--mut3);line-height:16px;min-height:16px}
.fieldrow{display:flex;gap:12px;flex-wrap:wrap;align-items:flex-start}
.fieldrow .field{flex:1 1 180px}
.fieldrow .field input,.fieldrow .field select{width:100%}
input[type=text],input[type=search],select{
  height:44px;padding:0 12px;border:1px solid var(--btnline);border-radius:10px;
  background:var(--card);
}
input[type=search]{-webkit-appearance:none}
.search{position:relative;display:flex;align-items:center;
  flex-grow:1;min-width:180px;max-width:320px}
.search svg{position:absolute;left:12px;pointer-events:none;color:var(--mut3)}
.search input{padding-left:36px;width:100%}

/* ── Menu ────────────────────────────────────────────────────────────── */
.menuwrap{position:relative;flex-shrink:0}
.menu{
  position:absolute;right:0;top:52px;z-index:20;width:280px;background:var(--card);
  border:1px solid var(--line);border-radius:12px;padding:8px;
  box-shadow:0 12px 32px rgba(22,24,29,.14);
}
.menu .grp{padding:8px 10px 4px;font-size:12px;font-weight:600;letter-spacing:.5px;
  text-transform:uppercase;color:var(--mut2)}
.menu button{
  width:100%;min-height:44px;padding:0 10px;border:none;border-radius:8px;
  display:flex;align-items:center;justify-content:space-between;font-size:15px;
  text-align:left;background:transparent;color:var(--ink);cursor:pointer;
}
.menu button:hover:not(:disabled){background:var(--inset)}
.menu button[aria-checked=true]{background:var(--oursbg);font-weight:600}
.menu button:disabled{color:var(--mut3);cursor:default}
.menu .tag{font-size:14px;color:var(--ours);font-weight:700}
.menu button:disabled .tag{font-size:12px;color:var(--mut3);font-weight:400}

/* ── Tables ──────────────────────────────────────────────────────────── */
.rows{padding:4px 20px}
.hd,.row{display:grid;grid-template-columns:var(--cols);gap:12px;align-items:center}
.hd{
  height:40px;font-size:12px;font-weight:600;letter-spacing:.5px;
  text-transform:uppercase;color:var(--mut2);border-bottom:1px solid var(--line2);
}
.hd .s{cursor:pointer;user-select:none}
.hd .s:hover{color:var(--ink)}
.row{min-height:56px;border-bottom:1px solid var(--line3)}
.row:last-child{border-bottom:none}
.r{text-align:right}
.who{min-width:0}
.who b{display:block;font-size:15px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.who span{font-size:12px;color:var(--mut2)}
.big{font-size:15px;font-weight:700}
.dim{font-size:14px;color:var(--mut2)}
/* The bar is the comparison the whole page is about: our number as a filled
   length, the book's as a tick across it. Scaled to a fixed ceiling rather
   than to the row's own max, so a bar means the same thing on every row. */
.bar{position:relative;height:8px;background:var(--sunk);border-radius:4px}
.bar i{position:absolute;left:0;top:0;bottom:0;border-radius:4px;background:var(--ours)}
.bar u{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--ink)}
.key{display:flex;gap:12px}
.key span{display:inline-flex;align-items:center;gap:6px}
.key i{width:10px;height:10px;border-radius:2px;background:var(--ours);display:inline-block}
.key u{width:2px;height:12px;background:var(--ink);display:inline-block}
.pill{padding:4px 10px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap}
.pill.p-ours{background:var(--oursbg);color:var(--ours)}
.pill.p-good{background:var(--goodbg);color:var(--good)}
.pill.p-bad{background:var(--badbg);color:var(--bad)}
.pill.p-mut{background:var(--inset);color:var(--mut)}
/* Between agreement and a strong call. Green, but the quiet one. */
.pill.p-lean{background:var(--goodbg);color:var(--mut)}
.empty{padding:48px 20px;text-align:center}
.empty b{display:block;font-size:18px}
.empty span{font-size:15px;color:var(--mut);display:block;margin-top:6px}

/* ── Funnel ──────────────────────────────────────────────────────────── */
.funnel{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:14px;color:var(--mut)}
.funnel .step{padding:6px 12px;border-radius:999px;background:var(--card);border:1px solid var(--line)}
.funnel .step.last{background:var(--ink);color:#fff;font-weight:600;border-color:var(--ink)}
.funnel .roi{margin-left:auto}

/* ── Slip ────────────────────────────────────────────────────────────── */
.leg{display:flex;align-items:center;justify-content:space-between;gap:8px;
  padding:4px 4px 4px 12px;background:var(--inset);border-radius:10px}
.leg b{display:block;font-size:14px;font-weight:600}
.leg span{font-size:12px;color:var(--mut2)}
.two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.three{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.stat{background:var(--inset);border-radius:10px;padding:12px}
.stat i{display:block;font-size:12px;color:var(--mut2);font-style:normal}
.stat b{display:block;font-size:22px;font-weight:700}
.dash{border:1px dashed var(--btnline);border-radius:12px;padding:24px 16px;
  text-align:center;color:var(--mut2);font-size:15px}
.brk{display:grid;grid-template-columns:1fr 70px 80px;gap:6px;font-size:14px}
.brk .h{font-size:12px;color:var(--mut2);text-transform:uppercase;letter-spacing:.5px}
.dot{flex-shrink:0;width:8px;height:8px;border-radius:4px;display:inline-block}
.dot.pending{background:var(--pend)} .dot.hit{background:var(--gooddot)} .dot.miss{background:var(--baddot)}

/* ── Saved ───────────────────────────────────────────────────────────── */
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:20px}
.cards article{padding:18px 20px;display:flex;flex-direction:column;gap:12px}
.cards .legline{display:flex;justify-content:space-between;align-items:center;gap:10px;
  min-height:34px;border-top:1px solid var(--line3);font-size:14px}
.cards .legline>span:first-child{display:inline-flex;align-items:center;gap:8px;min-width:0}
.cards .legline em{font-style:normal;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.summary{display:flex;gap:24px;font-size:14px;color:var(--mut)}
.summary b{display:block;font-size:22px;font-weight:700;color:var(--ink)}

/* ── Responsive ──────────────────────────────────────────────────────── */
/* The design is drawn at 1440 and the tables are the thing that has to
   survive narrowing. Columns are dropped in order of how redundant they are:
   the bar first (its information is also the two numbers beside it), then the
   graded band, then the read. Nothing that can only be read in one place is
   ever hidden. */
@media (max-width:1240px){
  main{padding:24px 24px 32px}
  .top{padding:0 24px;gap:24px}
}
@media (max-width:1100px){
  .wrap{flex-direction:column}
  h1{font-size:32px}
  /* The slip becomes a sheet.
     Stacked in the flow it lands underneath a five-hundred-row table, which
     is not "below the board" so much as unreachable — and the handle that
     opens it would scroll you there rather than show it. Fixed to the bottom
     of the viewport, it opens over the board wherever you happen to be. */
  aside{
    position:fixed;left:0;right:0;bottom:0;top:auto;z-index:40;
    width:auto;height:auto;max-height:82vh;
    border-left:none;border-top:1px solid var(--line);
    border-radius:16px 16px 0 0;
    box-shadow:0 -10px 40px rgba(22,24,29,.24);
    overflow-y:auto;
    padding:16px 20px calc(24px + env(safe-area-inset-bottom));
    -webkit-overflow-scrolling:touch;
  }
  /* A grab bar, so the sheet reads as something that came up and can go back
     down rather than as content that appeared. */
  aside::before{
    content:'';position:sticky;top:0;display:block;width:40px;height:4px;
    margin:-6px auto 10px;border-radius:2px;background:var(--btnline);
  }
  /* The board keeps scrolling under it, so the last rows are not left beneath
     the sheet with no way to reach them. */
  main{padding-bottom:180px}
}
@media (max-width:900px){
  .top{height:auto;min-height:64px;flex-wrap:wrap;gap:12px;padding:10px 20px}
  .nav{order:3;width:100%;gap:4px;overflow-x:auto;-webkit-overflow-scrolling:touch}
  .nav a{padding:8px 12px;font-size:14px}
  .when{margin-left:auto}
  main{padding:20px 16px 28px}
  h1{font-size:28px}
  .lede{font-size:14px}
  .hidemd{display:none}
  .cards{grid-template-columns:1fr}
}
@media (max-width:680px){
  .hidesm{display:none}
  main{padding:16px 12px 24px}
  .pagehead{align-items:flex-start}
  h1{font-size:24px}
  .seg{width:100%}
  .seg button{flex:1 1 0;padding:0 8px;font-size:13px}
  .chiprow{gap:6px}
  .search{max-width:none;flex:1 1 100%}
  .two,.three{grid-template-columns:1fr}
  .sliptab{right:12px;bottom:12px}
  .fieldrow .field{flex:1 1 100%}

  /* A table becomes one card per row.
     The grid columns are dropped entirely — nine of them on a 360px screen is
     four characters each — and every cell prints its own label instead, which
     is what `data-label` is for. The header has nothing left to head, so it
     goes.
     Three cells are furniture rather than data and keep their places on the
     first line: the star leads, the player names the row, and the action sits
     on the right. Everything else stacks under them as label/value pairs. */
  .rows{padding:0}
  .hd{display:none}
  .row{
    display:grid;
    grid-template-columns:44px minmax(0,1fr) auto;
    gap:2px 10px;
    padding:12px 12px 14px;
    align-items:center;
    min-height:0;
  }
  .row>div{
    grid-column:2 / -1;
    display:flex;align-items:baseline;justify-content:space-between;gap:12px;
    text-align:right;min-height:26px;
  }
  .row>div::before{
    content:attr(data-label);
    color:var(--mut2);font-size:12px;font-weight:600;
    letter-spacing:.4px;text-transform:uppercase;text-align:left;flex:0 0 auto;
  }
  .row>div:not([data-label])::before,.row>div[data-label=""]::before{content:none}
  .row>div:empty{display:none}
  .row .mob-lead{grid-column:1;grid-row:1;justify-content:center;min-height:44px}
  .row .mob-title{grid-column:2;grid-row:1;justify-content:flex-start;text-align:left}
  .row .mob-act{grid-column:3;grid-row:1;justify-content:flex-end}
  .row .mob-title .who b{white-space:normal}
  /* A row with no lead or action cell — Model, Ladder — has nothing to sit in
     the first column, so its cells use the full width. */
  .row>div:first-child:not(.mob-lead){grid-column:1 / -1}
  .brk{grid-template-columns:1fr 64px 76px}
  .cards article{padding:14px 16px}
}
@media print{
  .top,aside,.chiprow,.add,.icon{display:none}
  body{background:#fff}
  .card{break-inside:avoid}
}
"""


JS_CORE = r"""
// ── Helpers ─────────────────────────────────────────────────────────────
const $ = s => document.querySelector(s);
const has = v => v !== null && v !== undefined && !(typeof v === 'number' && isNaN(v));
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct = (v, d) => has(v) ? (v * 100).toFixed(d == null ? 0 : d) + '%' : '';
const spp = v => has(v) ? (v > 0 ? '+' : '') + v.toFixed(0) : '';
// A probability a person can read, at any scale. `toExponential` is correct
// and useless: "9.8e-1%" was on the Ladder where "0.98%" belonged, and below a
// tenth of a percent even that stops meaning anything, so it becomes odds
// against — "1 in 1,200" is a sentence, 8.3e-4% is a typo.
function chanceTxt(p) {
  if (!has(p) || p <= 0) return '—';
  if (p >= 0.995) return '~100%';
  if (p >= 0.1) return (p * 100).toFixed(0) + '%';
  if (p >= 0.01) return (p * 100).toFixed(1) + '%';
  if (p >= 0.001) return (p * 100).toFixed(2) + '%';
  return '1 in ' + Math.round(1 / p).toLocaleString();
}
const money = v => (v < 0 ? '−$' : '$') + Math.abs(v).toLocaleString(undefined,
  { maximumFractionDigits: 2 });

// American from decimal, and back. The board stores whichever the source had,
// and the two notations have to agree to the cent or a slip prices wrong.
const american = o => !has(o) ? '' : (o > 0 ? '+' + o : String(o));
const decToAm = d => d >= 2 ? Math.round((d - 1) * 100) : -Math.round(100 / (d - 1));
const amToDec = a => a > 0 ? 1 + a / 100 : 1 + 100 / -a;

function el(tag, attrs, kids) {
  const n = document.createElement(tag);
  Object.entries(attrs || {}).forEach(([k, v]) => {
    if (v === null || v === undefined || v === false) return;
    if (k === 'text') n.textContent = v;
    else if (k === 'html') n.innerHTML = v;
    else if (k === 'class') n.className = v;
    else if (k.startsWith('on')) n[k.toLowerCase()] = v;
    else n.setAttribute(k, v === true ? '' : v);
  });
  (kids || []).forEach(k => k && n.appendChild(k));
  return n;
}
const svg = (d, o) => {
  o = o || {};
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('width', o.size || 16); s.setAttribute('height', o.size || 16);
  s.setAttribute('viewBox', '0 0 24 24');
  s.setAttribute('fill', o.fill || 'none'); s.setAttribute('stroke', o.stroke || 'currentColor');
  s.setAttribute('stroke-width', o.w || 2);
  s.setAttribute('stroke-linecap', 'round'); s.setAttribute('stroke-linejoin', 'round');
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', d); s.appendChild(p);
  return s;
};
const STAR = 'M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z';
const CHEV = 'M9 18l6-6-6-6';
const DOWN = 'M6 9l6 6 6-6';
const MAG = 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-4.3-4.3';
const BIN = 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3';
const EX = 'M6 6l12 12M18 6L6 18';

// ── Markets ─────────────────────────────────────────────────────────────
//
// The menu lists only what a model actually serves. A market offered here and
// unserved by the pipeline is worse than one that is not listed: it reads as a
// page that is broken rather than a roadmap. So rushing, receiving and passing
// yards are present as "Soon" and cannot be picked, because there is no model
// behind them — see design/README.md.
//
// `kind` is what the board looks like, not what the bet is. `td` is a player
// and a probability; `ou` is a player, a posted line and a distribution, which
// needs four more columns and two buttons instead of one.
const MENU = [
  { title: 'Touchdowns', items: [['any', 'Anytime TD'], ['first', 'First TD']] },
  { title: 'Volume', items: [['rec', 'Receptions']] },
  { title: 'Yards', items: [['rush', 'Rushing yards', 1], ['recyds', 'Receiving yards', 1],
                            ['passyds', 'Passing yards', 1]] },
];
const KIND = { any: 'td', first: 'td', rec: 'ou' };

function marketOf(key) {
  if (key === 'rec') return DATA.receptions || {};
  return DATA.markets[key === 'first' ? 1 : 0] || {};
}
function marketLabel(key) {
  for (const g of MENU) for (const it of g.items) if (it[0] === key) return it[1];
  return key;
}
// Which markets this export actually carries. First TD is a second entry in
// DATA.markets and receptions a separate payload, so "served" is not the same
// question for the two and is asked separately.
function served(key) {
  if (key === 'rec') return !!(DATA.receptions && DATA.receptions.model);
  return !!DATA.markets[key === 'first' ? 1 : 0];
}

// ── Rows ────────────────────────────────────────────────────────────────
//
// One shape for both kinds, so the filters, the slip and the combinations
// search are written once. A `td` row has no line and one side; an `ou` row
// has a line and two, and carries `side` on the leg rather than the row.
function rowsFor(key, view) {
  const m = marketOf(key);
  if (KIND[key] === 'ou') {
    return (m.rows || []).map(r => ({
      key: key, kind: 'ou',
      id: key + '|' + r.player_name + '|' + r.point,
      player: r.player_name, team: r.team, game: r.game_id || '',
      line: r.point, proj: r.mu, lo: r.lo, hi: r.hi,
      ours: r.ours, book: r.fair_prob, edge: r.edge_pp,
      modelOnly: r.model_only,
      odds: r.odds, dec: has(r.odds) ? amToDec(r.odds) : null,
      // Priced means a book has quoted this player, not that the row exists.
      // Most of this board is a projection with no line against it.
      thin: !!r.thin, nBooks: r.n_books, priced: has(r.point),
    }));
  }

  const rows = (m.players || []).map(r => ({
    key: key, kind: 'td',
    id: key + '|' + r.player,
    player: r.player, team: r.team, game: r.game, gameId: r.game_id,
    ours: r.ours, modelOnly: r.model_only, book: r.book,
    // Measured on the pre-blend number, which is the basis the shortlist rule
    // was fitted and backtested on. The published probability has already been
    // pulled toward the price it is being compared against, so an edge taken
    // from it is about 62% of the real one and shrinks most exactly where the
    // disagreement is largest — see `src/prediction/bets.py`. First TD
    // publishes the model number directly and the two coincide there.
    edge: has(r.book) ? ((has(r.model_only) ? r.model_only : r.ours) - r.book) * 100 : null,
    odds: r.odds_num, dec: r.dec, priced: !!r.priced,
    best: r.best, bestBook: r.best_book, read: r.read, rank: r.rank,
    status: r.status, blocked: r.blocked, pos: r.pos,
  }));

  // The shortlist and the fades are this table with a rule applied — the same
  // rows, the same columns, the same numbers, fewer players. They used to be
  // mapped from their own payload entries, which meant their figures came from
  // a different place and could disagree with the board about the same man;
  // they did, and the Adj column showed the pre-blend number as a result.
  if (view === 'short' || view === 'fade') {
    const sl = m.shortlist || {};
    const want = new Set((((view === 'short') ? sl.rows : sl.vetoes) || [])
      .map(r => r.player));
    return rows.filter(r => want.has(r.player));
  }
  return rows;
}

// The probability a *bet* is judged on, which is not always the one we publish.
//
// On the touchdown markets it is the pre-blend model number. `bets.py` is
// explicit about why: the published probability has already been pulled toward
// the price it is being compared against, so an EV taken from it is measured
// on a different quantity than every profitability figure this project quotes,
// and the threshold would mean something on screen that it did not mean in the
// backtest.
//
// On receptions it is the served number, and for the opposite reason: there
// the blend is the thing that was measured, and it beats the book where the
// raw model does not.
function betProb(row) {
  if (row.kind === 'ou') return row.ours;
  return has(row.modelOnly) ? row.modelOnly : row.ours;
}
// Expected return on a flat $100, at that probability and the posted price.
function ev100(row) {
  const p = betProb(row);
  return (has(p) && has(row.dec)) ? 100 * (p * row.dec - 1) : null;
}

// ── Storage ─────────────────────────────────────────────────────────────
//
// Everything this page remembers is scoped to one season and week, and a new
// week starts empty. That covers favorites, the working slip and saved
// parlays alike.
//
// The narrowing is deliberate and it does cost something: the Saved page
// cannot show last week's net. What it keeps is everything that happens
// inside a week — a slip saved on Wednesday still settles on Sunday, so the
// status dots, the Won/Lost filters and a net figure all still work. What it
// avoids is a store that grows all season in a browser nobody is backing up,
// and a "net" that quietly means "since whenever I last cleared this".
//
// Every access is wrapped: localStorage throws outright in some privacy modes
// rather than returning null, and a page that will not render because it
// could not read a favourite is a worse page than one with no favourites.
const WK = () => (DATA.season || 0) + ':' + (DATA.week || 0);
const KEY = what => 'sp:' + WK() + ':' + what;
const LASTKEY = what => 'sp:' + (DATA.season || 0) + ':' + ((DATA.week || 1) - 1) + ':' + what;

// Two weeks of parlays, and exactly two.
//
// Saved parlays are the one thing that cannot live in a single week, and the
// reason is a timing trap rather than a preference. The slate holds a finished
// week until the next one's roster lands, and the rollover that builds the next
// week is the same run that extracts the finished week's touchdowns — so the
// only export that can settle week 2 is the one that has already become week 3.
// Scoped to one week, every saved parlay would read Pending forever and the
// status dots would be decoration.
//
// So last week's are read, shown as settled, and dropped the week after. That
// keeps the bound — nothing accumulates across a season — while letting a slip
// saved on Wednesday actually resolve.
function loadParlays() {
  const now = (load('parlays', []) || []).map(p => ({ ...p, last: false }));
  let prev = [];
  try {
    const raw = localStorage.getItem(LASTKEY('parlays'));
    if (raw) prev = (JSON.parse(raw) || []).map(p => ({ ...p, last: true }));
  } catch (e) { prev = []; }
  return now.concat(prev);
}
function saveParlays(all) {
  // Only this week's are written back. Last week's are read-only history and
  // are owned by the key they were written under.
  save('parlays', all.filter(p => !p.last).map(p => {
    const { last, ...rest } = p;
    return rest;
  }));
}
// Anything older than last week is dead and will never be read again. Left
// alone it is a season of orphaned keys in a store nobody is looking at.
function prune() {
  try {
    const keep = [KEY(''), LASTKEY('')];
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i);
      if (k && k.indexOf('sp:') === 0 && !keep.some(pre => k.indexOf(pre) === 0)) {
        localStorage.removeItem(k);
      }
    }
  } catch (e) { /* a store that will not enumerate cannot be tidied */ }
}
function load(what, fallback) {
  try {
    const raw = localStorage.getItem(KEY(what));
    if (raw === null) return fallback;
    const v = JSON.parse(raw);
    return v === null || v === undefined ? fallback : v;
  } catch (e) { return fallback; }
}
function save(what, value) {
  try { localStorage.setItem(KEY(what), JSON.stringify(value)); return true; }
  catch (e) { S.storageBroke = true; return false; }
}

// ── State ───────────────────────────────────────────────────────────────
const S = {
  route: 'week',
  market: 'any',
  menuOpen: false,
  storageBroke: false,
  // One slip, shared by This week and the Shortlist. Two lists that both
  // called themselves "your slip" was the prototype's one real bug: a leg
  // added on one page was missing on the other, and nothing said so.
  //
  // `market` is on the slip rather than derived from the legs, so an empty
  // slip still knows which market it belongs to and the conflict prompt can
  // name both sides.
  slip: { market: 'any', legs: [], size: 0, stake: 10, stakeRaw: '10' },
  // The slip takes 360px off the board, so it is shown only while it holds
  // something or has been asked for. Adding a leg opens it; closing it puts
  // it away without emptying it, and the handle says how many are in there.
  slipOpen: false,
  conflict: null,
  // Per-table sort, keyed by the table's id. Lives on S rather than in
  // the table, because the table is rebuilt on every render.
  sort: {},
  favs: [],
  parlays: [],
  saved: {},
  // Filters are per page: the Shortlist is already filtered to 36 players and
  // wants a name box, where This week is the whole slate and wants the lot.
  // `view` is which rule is applied to the board: everything, the fitted
  // shortlist, or the players we rate below the price. Favorites is a
  // separate toggle because it is orthogonal — you can want your starred
  // players within the shortlist.
  fw: { view: 'all', q: '', game: '', pos: '', priced: 'all', favOnly: false,
        sort: '', dir: -1 },
  fs: { q: '', game: '', pos: '', sort: '', dir: -1 },
  savedFilter: 'all',
  // Combinations has its own filters rather than inheriting This week's.
  // Inheriting would make a control on one page silently change the
  // results on another, which is the kind of coupling nobody can see.
  // `pool` is the one control that matters: which players are even
  // eligible to be combined.
  cb: { pool: 'short', q: '', game: '', pos: '', legs: 3, show: 25,
        rank: 'likely', sameGame: true },
  ladder: { start: 100, startRaw: '100', bets: 10, betsRaw: '10',
            dec: 1 + 100 / 170, oddsRaw: '−170' },
};

function boot() {
  prune();
  S.favs = load('favs', []);
  S.parlays = loadParlays();
  const sl = load('slip', null);
  if (sl && sl.legs) S.slip = Object.assign(S.slip, sl);
  if (!served(S.slip.market)) S.slip = { market: 'any', legs: [], size: 0, stake: 10, stakeRaw: '10' };
  S.market = S.slip.market;
  route();
  window.addEventListener('hashchange', route);
  document.addEventListener('click', e => {
    if (S.menuOpen && !e.target.closest('.menuwrap')) { S.menuOpen = false; render(); }
  });
}

// ── Routing ─────────────────────────────────────────────────────────────
//
// The hash, so the five pages are five linkable URLs and the back button
// works, while the export stays one file that opens from a filesystem.
// Four, not five. The Shortlist was a page in the design and is a view here:
// it is the same players as the board with a fitted rule over them, and two
// pages showing one population with different columns is the duplication that
// made the old nine-tab dashboard hard to open. What the page carried that a
// filter does not — the funnel and the graded return — appears as a strip
// above the board whenever that view is on, which is the only place it means
// anything anyway.
// Combinations is a page and the Shortlist is not, and the difference is the
// unit. The shortlist is the same players as the board with a rule over them,
// so it is a view of one table. Combinations returns *slips* — a different
// thing, with its own pool, its own ranking and its own save — and burying a
// search tool under a board it does not resemble was the wrong call the first
// time.
const PAGES = [
  ['week', 'This week'], ['combos', 'Combinations'], ['saved', 'Saved'],
  ['ladder', 'Ladder'], ['model', 'Model'],
];
function route() {
  const h = (location.hash || '').replace(/^#\/?/, '').split('?')[0];
  S.route = PAGES.some(p => p[0] === h) ? h : 'week';
  render();
  window.scrollTo(0, 0);
}
function go(page) { location.hash = '#' + page; }

// ── Favorites ───────────────────────────────────────────────────────────
const isFav = id => S.favs.indexOf(id) >= 0;
function toggleFav(id) {
  S.favs = isFav(id) ? S.favs.filter(x => x !== id) : S.favs.concat([id]);
  save('favs', S.favs);
  render(true);
}
function starBtn(row) {
  const on = isFav(row.id);
  const b = el('button', {
    class: 'icon', 'aria-pressed': on ? 'true' : 'false',
    'aria-label': (on ? 'Remove ' : 'Mark ') + row.player + (on ? ' from favorites' : ' as a favorite'),
    onclick: () => toggleFav(row.id),
  });
  b.appendChild(svg(STAR, { size: 20, w: 1.8,
    fill: on ? 'var(--star)' : 'none', stroke: on ? 'var(--starline)' : 'var(--mut3)' }));
  return b;
}
"""


JS_SHARED = r"""
// ── Filters ─────────────────────────────────────────────────────────────
//
// Four controls, and each answers a question someone actually asks of a board
// this size: "where is this player", "what is in this game", "show me the
// running backs", "what can I actually bet".
//
// The search matches player, team and fixture together rather than offering
// three boxes. Typing "BUF" should find the Bills game and every Bill on it,
// which is one intent, and splitting it into fields makes the reader decide
// which field their intent lives in before they can type.
function matches(row, q) {
  if (!q) return true;
  const hay = (row.player + ' ' + (row.team || '') + ' ' + (row.game || '')).toLowerCase();
  // Every whitespace-separated term must appear somewhere. "det gibbs" finds
  // one row; as a single substring it finds none.
  return q.toLowerCase().split(/\s+/).filter(Boolean).every(t => hay.indexOf(t) >= 0);
}
function applyFilters(rows, f) {
  let out = rows.filter(r => matches(r, f.q));
  if (f.game) out = out.filter(r => (r.game || '') === f.game);
  if (f.pos) out = out.filter(r => (r.pos || '') === f.pos);
  if (f.favOnly) out = out.filter(r => isFav(r.id));
  if (f.priced === 'priced') out = out.filter(r => r.priced);
  else if (f.priced === 'unpriced') out = out.filter(r => !r.priced);
  // Sorting is deliberately not done here. `table` owns it, so a column
  // header and the row order cannot disagree, and every table gets it whether
  // or not the page has filter state to hang it on.
  return out;
}

function searchBox(f, placeholder) {
  const i = el('input', { type: 'search', value: f.q, placeholder: placeholder || 'Player, team or game',
    'aria-label': 'Search' });
  let t;
  i.oninput = () => { clearTimeout(t); t = setTimeout(() => { f.q = i.value; render(true); }, 110); };
  const w = el('div', { class: 'search' });
  w.appendChild(svg(MAG, { size: 16, stroke: 'currentColor' }));
  w.appendChild(i);
  return w;
}
function pickerFor(label, value, options, onpick) {
  const s = el('select', { 'aria-label': label });
  options.forEach(o => {
    const [v, t] = Array.isArray(o) ? o : [o, o];
    const opt = el('option', { value: v, text: t });
    if (String(v) === String(value)) opt.selected = true;
    s.appendChild(opt);
  });
  s.onchange = () => { onpick(s.value); render(); };
  return s;
}
function favChip(f, rows) {
  const n = rows.filter(r => isFav(r.id)).length;
  const b = el('button', { class: 'chip', 'aria-pressed': f.favOnly ? 'true' : 'false',
    onclick: () => { f.favOnly = !f.favOnly; render(); } });
  b.appendChild(svg(STAR, { size: 16, w: 1.8, fill: f.favOnly ? 'currentColor' : 'none' }));
  b.appendChild(document.createTextNode(' Favorites · ' + n));
  return b;
}
// A count under the filters, always, even when nothing is filtered. "36 of 36"
// is not noise: it is the only thing that distinguishes a board showing
// everything from a board whose filter silently matched everything.
function countLine(shown, total, noun) {
  return el('p', { class: 'fine',
    text: shown === total ? total + ' ' + noun
                          : shown + ' of ' + total + ' ' + noun + ' shown' });
}

// ── Tables ──────────────────────────────────────────────────────────────
//
// `cols` is [{k, label, w, cell, r, sort, title}]. Sorting is on the raw
// value through the filter state, never on the rendered string: "9%" sorts
// after "10%" as text and the column becomes a lie.
function table(cols, rows, f, opts) {
  opts = opts || {};
  // Every table sorts, on every column that has a value to sort by.
  //
  // Sorting used to hang off the page's filter state, so the two board tables
  // sorted and the four on Model, Ladder and Combinations did not — a
  // difference nobody could see until they clicked a heading and nothing
  // happened. A table without its own filter state gets one here, keyed by
  // `opts.id`, and the state lives on S so it survives a re-render.
  const st = (f && 'sort' in f) ? f
    : (S.sort[opts.id || 'x'] = S.sort[opts.id || 'x'] || { sort: '', dir: -1 });
  const sortable = c => !c.nosort && (c.sort || c.sortVal);
  const keyOf = c => c.sort || c.label;
  const valOf = (c, r) => c.sortVal ? c.sortVal(r) : r[c.sort];

  if (st.sort) {
    const c = cols.find(c => sortable(c) && keyOf(c) === st.sort);
    if (c) rows = rows.slice().sort((a, b) => {
      const x = valOf(c, a), y = valOf(c, b);
      if (!has(x) && !has(y)) return 0;
      // Missing always sorts last, whichever way the column is pointing. A
      // blank that floats to the top on one click is a row you have to
      // re-sort past to read the answer.
      if (!has(x)) return 1;
      if (!has(y)) return -1;
      return typeof x === 'string' ? st.dir * String(x).localeCompare(String(y))
                                   : st.dir * (x - y);
    });
  }

  const tpl = cols.map(c => c.w).join(' ');
  const wrap = el('div', { class: 'card rows' });
  // `--cols`, not `grid-template-columns`.
  //
  // An inline declaration beats every rule in the stylesheet including one
  // inside a media query, so writing the nine-column track inline made the
  // narrow layout unreachable — it was in the sheet, it was correct, and it
  // never applied. A custom property carries the same value while leaving the
  // property itself to the cascade, where a breakpoint can have it.
  const hd = el('div', { class: 'hd', style: '--cols:' + tpl });
  cols.forEach(c => {
    const on = sortable(c);
    const d = el('div', { class: (c.r ? 'r ' : '') + (c.hide ? 'hidesm ' : '') + (on ? 's' : ''),
      title: c.title || null, role: on ? 'button' : null, tabindex: on ? '0' : null });
    if (c.head) c.head(d); else d.textContent = c.label || '';
    if (on) {
      const k = keyOf(c);
      const flip = () => {
        st.dir = st.sort === k ? -st.dir : -1;
        st.sort = k;
        render();
      };
      d.onclick = flip;
      d.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); flip(); } };
      if (st.sort === k) {
        d.setAttribute('aria-sort', st.dir > 0 ? 'ascending' : 'descending');
        d.appendChild(document.createTextNode(st.dir > 0 ? ' \u2191' : ' \u2193'));
      }
    }
    hd.appendChild(d);
  });
  wrap.appendChild(hd);
  rows.forEach(r => {
    const tr = el('div', { class: 'row', style: '--cols:' + tpl });
    cols.forEach(c => {
      // `data-label` is what the narrow layout prints beside the value. The
      // header is gone below 680px, so without it a stacked row is a column of
      // unlabelled numbers — which is what the first mobile attempt was.
      const d = el('div', {
        class: (c.r ? 'r ' : '') + (c.hide ? 'hidesm ' : '') + (c.mob ? 'mob-' + c.mob : ''),
        'data-label': c.label || null,
      });
      c.cell(d, r);
      tr.appendChild(d);
    });
    wrap.appendChild(tr);
  });
  if (!rows.length) {
    wrap.appendChild(el('div', { class: 'empty' }, [
      el('b', { text: opts.emptyTitle || 'Nothing matches' }),
      el('span', { text: opts.emptyBody || 'Clear a filter, or search for something else.' }),
    ]));
  }
  return wrap;
}
// The comparison, as one cell: our probability filled, the book's as a tick.
// Both scaled to the same ceiling on every row, so a longer bar always means a
// higher number rather than a higher number *for this row*.
function barCell(d, r, ceiling, key) {
  const c = ceiling || 0.75;
  const v = r[key || 'ours'];
  const b = el('div', { class: 'bar' });
  if (has(v)) b.appendChild(el('i', { style: 'width:' + Math.min(100, v / c * 100).toFixed(1) + '%' }));
  if (has(r.book)) b.appendChild(el('u', { style: 'left:' + Math.min(100, r.book / c * 100).toFixed(1) + '%' }));
  d.appendChild(b);
}
function keyHead(d, ours, book) {
  const k = el('div', { class: 'key' });
  k.appendChild(el('span', {}, [el('i'), el('span', { text: ours || 'Adj' })]));
  k.appendChild(el('span', {}, [el('u'), el('span', { text: book || 'Book' })]));
  d.appendChild(k);
}

// ── The slip ────────────────────────────────────────────────────────────
//
// One slip for the whole page. A leg is {id, key, side, label, sub, p, dec}
// — enough to re-price it without going back to the board, because the Saved
// page has to show a parlay whose player may no longer be on this week's
// board at all.
//
// One market per slip, enforced rather than warned about: a two-leg parlay
// mixing an anytime TD with a receptions over is not a thing a book will
// price, and showing a combined number for it would be inventing a market.
const legIn = id => S.slip.legs.some(l => l.id === id);
function toggleLeg(row, side) {
  const id = row.id + (side ? '|' + side : '');
  if (legIn(id)) {
    S.slip.legs = S.slip.legs.filter(l => l.id !== id);
    persistSlip();
    return render(true);
  }
  if (S.slip.legs.length && S.slip.market !== row.key) {
    // Do not silently drop what is there. Name both markets and let the
    // reader choose which slip they meant.
    S.conflict = { row: row, side: side };
    return render();
  }
  S.slip.market = row.key;
  S.slip.legs = S.slip.legs.concat([legOf(row, side)]);
  S.slipOpen = true;
  persistSlip();
  render(true);
}
function legOf(row, side) {
  const over = side !== 'under';
  // Taking the under flips every probability on the row, not just the one we
  // price with — otherwise the leg would show the book's chance of the over
  // beside our chance of the under and invite the comparison.
  const flip = v => !has(v) ? null : (row.kind === 'ou' && !over ? 1 - v : v);
  const p = flip(row.ours), pm = flip(row.modelOnly), pb = flip(row.book);
  return {
    id: row.id + (side ? '|' + side : ''),
    key: row.key, player: row.player, side: side || null, team: row.team,
    label: row.kind === 'ou'
      ? row.player + ' ' + (over ? 'over ' : 'under ') + row.line
      : row.player,
    // All three numbers on the leg, because the slip is where you decide and
    // the decision turns on which of them you believe. Showing the served
    // figure alone hid whether we and the book agreed on our own or because
    // we were pulled there.
    sub: legSub(pm, pb, p, row.odds),
    p: p, pm: pm, pb: pb, dec: row.dec, odds: row.odds, game: row.game,
  };
}
function legSub(model, book, adj, odds) {
  const bits = [];
  if (has(model)) bits.push('M ' + pct(model));
  if (has(book)) bits.push('B ' + pct(book));
  if (has(adj)) bits.push('A ' + pct(adj));
  if (!bits.length) bits.push('no number');
  if (has(odds)) bits.push(american(odds));
  return bits.join(' · ');
}
function persistSlip() {
  S.saved = {};                     // any edit unsaves; see saveSlip
  save('slip', S.slip);
}
function clearSlip() {
  S.slip = { market: S.slip.market, legs: [], size: 0,
             stake: S.slip.stake, stakeRaw: S.slip.stakeRaw };
  S.conflict = null;
  // An emptied slip has nothing to show, so it gets out of the board's way
  // rather than sitting there as a dashed rectangle taking 360px.
  S.slipOpen = false;
  persistSlip();
  render();
}

// The round robin, priced exactly.
//
// A slip is always the full cover here — every combination of the legs, which
// is what a book sells as a round robin and what the old Parlay pane showed.
// There is no "how to back it" control: the breakdown below covers every size
// at once, so choosing one in advance only hid the rest.
//
// The arithmetic is an enumeration over all 2^n outcome patterns rather than a
// shortcut, because the shortcut is wrong. Each slip pays the product of *its
// own* legs' prices, and those differ: over three legs the three doubles are
// three different numbers. Averaging the decimal across slips — which is what
// this did before — reports a single payout that no individual slip pays, and
// it is out by more the further apart the prices are.
//
// Ported from `paneCover` in the previous dashboard, which had it right.
const COVER_MAX_LEGS = 12;

function portfolio(legs, stake, rho) {
  const n = legs.length, N = 1 << n;
  const p = legs.map(l => has(l.p) ? l.p : 0);
  const dec = legs.map(l => has(l.dec) ? l.dec : null);
  const allPriced = dec.every(has);

  // Every pattern of who scores, and what it is worth.
  const bits = [], prob = new Array(N);
  for (let m = 0; m < N; m++) {
    const b = [];
    let q = 1;
    for (let i = 0; i < n; i++) { const on = (m >> i) & 1; b.push(on); q *= on ? p[i] : 1 - p[i]; }
    bits.push(b); prob[m] = q;
  }
  // Teammates only. The measured correlation is a team-game effect — one
  // offence stalls and neither of its players scores — and applying it across
  // fixtures would inflate the tail for legs that have nothing to do with
  // each other.
  if (rho) {
    let tot = 0;
    for (let m = 0; m < N; m++) {
      const z = bits[m].map((on, i) => (on - p[i]) / Math.sqrt(Math.max(p[i] * (1 - p[i]), 1e-9)));
      let pair = 0;
      for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++)
        if (legs[i].team && legs[i].team === legs[j].team) pair += z[i] * z[j];
      prob[m] *= Math.exp(rho * pair); tot += prob[m];
    }
    for (let m = 0; m < N; m++) prob[m] /= tot;
  }

  const ret = new Array(N).fill(0), wins = new Array(N).fill(0);
  let slips = 0;
  for (let mask = 1; mask < N; mask++) {
    slips++;
    let payout = stake, priced = true;
    for (let i = 0; i < n; i++) if ((mask >> i) & 1) {
      if (dec[i] === null) priced = false; else payout *= dec[i];
    }
    if (!priced) payout = 0;
    for (let m = 0; m < N; m++) if ((m & mask) === mask) { ret[m] += payout; wins[m]++; }
  }
  const staked = stake * slips;

  const kOf = m => bits[m].reduce((a, b) => a + b, 0);
  const rows = [];
  for (let k = n; k >= 0; k--) {
    let w = 0, r = 0, lo = Infinity, hi = -Infinity, nb = 0;
    for (let m = 0; m < N; m++) if (kOf(m) === k) {
      w += prob[m]; r += ret[m] * prob[m];
      lo = Math.min(lo, ret[m]); hi = Math.max(hi, ret[m]); nb = wins[m];
    }
    const avg = w > 0 ? r / w : lo;
    // `lo` and `hi` are not decoration. With k of n scoring, *which* k they
    // were decides what came back, and on spread-out prices those two numbers
    // are far apart — an average alone would read as a certainty.
    rows.push({ hit: k, slipsWon: nb, chance: w, net: avg - staked,
                netLo: lo - staked, netHi: hi - staked });
  }
  let ev = 0;
  for (let m = 0; m < N; m++) ev += (ret[m] - staked) * prob[m];

  return { n: n, slips: slips, stake: stake, outlay: staked, rows: rows,
           ev: ev, roi: staked ? ev / staked : 0, priced: allPriced,
           all: prob[N - 1] };
}

function slipMath() {
  const legs = S.slip.legs.slice(0, COVER_MAX_LEGS);
  const stake = S.slip.stake || 0;
  const rho = ((M0() || {}).cover || {}).rho || 0;
  if (!legs.length) {
    return { legs: legs, slips: 0, outlay: 0, rows: [], ev: 0, all: 1,
             priced: true, over: 0 };
  }
  const f = portfolio(legs, stake, rho);
  f.legs = legs;
  f.over = S.slip.legs.length - legs.length;
  return f;
}
// The market payload carrying `cover`, whichever market the slip belongs to.
function M0() {
  return S.slip.market === 'rec' ? {} : marketOf(S.slip.market);
}

// Every k-subset of n, as index lists. Used by the Combinations page, which
// enumerates slips rather than pricing one; the slip's own maths enumerates
// outcome patterns instead and does not go through this.
function combosOf(n, k) {
  const out = [];
  (function walk(start, acc) {
    if (acc.length === k) return out.push(acc.slice());
    for (let i = start; i < n; i++) { acc.push(i); walk(i + 1, acc); acc.pop(); }
  })(0, []);
  return out;
}

function choose(n, k) {
  if (k > n || k < 0) return 0;
  let r = 1;
  for (let i = 1; i <= k; i++) r = r * (n - k + i) / i;
  return Math.round(r);
}

"""


JS_SLIPVIEW = r"""
// ── Slip panel ──────────────────────────────────────────────────────────
//
// The same slip on both pages, drawn two ways. This week gets the round robin
// and the per-outcome breakdown, because that is the page you go to when you
// are deciding how to back something. The Shortlist gets legs, chance, price
// and a save button, and a link to the other page for the rest — the feedback
// on the prototype was that a second full builder there was noise.
function slipPanel() {
  const full = true;
  const a = el('aside');
  const m = slipMath();

  // Two different actions that both look like "get rid of this", kept
  // visually apart because they are not undoable in the same way. Collapsing
  // keeps every leg; clearing throws them away. The chevron collapses, the
  // word says what it does, and only one of them is destructive.
  const close = el('button', { class: 'icon', 'aria-label': 'Collapse the slip',
    title: 'Collapse — the legs stay where they are',
    onclick: () => { S.slipOpen = false; render(); } });
  close.appendChild(svg(CHEV, { size: 18 }));
  const head = el('div', { style: 'display:flex;align-items:center;gap:4px' });
  head.appendChild(el('span', { class: 'note',
    text: m.legs.length === 1 ? '1 leg' : m.legs.length + ' legs' }));
  if (m.legs.length) head.appendChild(el('button', { class: 'linkbtn',
    text: 'Clear', 'aria-label': 'Remove all ' + m.legs.length + ' legs from the slip',
    title: 'Remove every leg', onclick: () => clearSlip() }));
  head.appendChild(close);
  a.appendChild(el('div', { class: 'asidehead' }, [
    el('h2', { class: 'h2s', text: 'Your slip' }), head,
  ]));

  if (S.conflict) {
    const other = marketLabel(S.conflict.row.key);
    a.appendChild(el('div', { class: 'warnbox' }, [
      el('div', { html: 'Your slip is <b>' + esc(marketLabel(S.slip.market)) + '</b>. '
        + 'Legs from different markets cannot be priced together.' }),
      el('div', { style: 'display:flex;gap:8px;margin-top:10px;flex-wrap:wrap' }, [
        el('button', { class: 'btn solid', text: 'Start a ' + other + ' slip',
          onclick: () => {
            const c = S.conflict; S.conflict = null;
            S.slip.market = c.row.key; S.slip.legs = [legOf(c.row, c.side)];
            persistSlip(); render();
          } }),
        el('button', { class: 'btn', text: 'Keep this one',
          onclick: () => { S.conflict = null; render(); } }),
      ]),
    ]));
  }

  if (!m.legs.length) {
    a.appendChild(el('div', { class: 'dash',
      text: 'Add players from the list to price them together.' }));
    return a;
  }

  a.appendChild(el('div', { class: 'note',
    title: 'M is the model on its own, B is the de-vigged book price, A is what '
         + 'we serve — the model after the market blend.',
    text: marketLabel(S.slip.market) + ' · M model · B book · A adj' }));
  const list = el('div', { style: 'display:flex;flex-direction:column;gap:6px' });
  m.legs.forEach(l => {
    const x = el('button', { class: 'icon', 'aria-label': 'Remove ' + l.player,
      onclick: () => { S.slip.legs = S.slip.legs.filter(o => o.id !== l.id); persistSlip(); render(true); } });
    x.appendChild(svg(EX, { size: 16 }));
    list.appendChild(el('div', { class: 'leg' }, [
      el('div', {}, [el('b', { text: l.label }), el('span', { text: l.sub })]), x,
    ]));
  });
  a.appendChild(list);

  a.appendChild(el('div', { class: 'two' }, [
    el('div', { class: 'stat' }, [el('i', { text: 'All hit' }),
      el('b', { text: chanceTxt(m.all) })]),
    el('div', { class: 'stat' }, [el('i', { text: 'Slips' }),
      el('b', { text: String(m.slips) })]),
  ]));
  if (m.over) a.appendChild(el('div', { class: 'warnbox', text:
    m.over + ' leg' + (m.over === 1 ? ' is' : 's are') + ' not priced below: a full '
    + 'cover of more than ' + COVER_MAX_LEGS + ' legs is ' + (Math.pow(2, COVER_MAX_LEGS) - 1)
    + ' slips, which is past the point of being a thing anyone places.' }));

  if (full) {
    // No "how to back it" control. The slip is the full cover — every
    // combination of the legs, which is how a book sells a round robin — and
    // the table below breaks out every size at once. Choosing one in advance
    // only hid the rest of the answer.
    const si = el('input', { type: 'text', inputmode: 'decimal', value: S.slip.stakeRaw,
      'aria-label': 'Stake per slip' });
    si.oninput = () => {
      S.slip.stakeRaw = si.value;
      const x = parseFloat(si.value.replace(/[^0-9.]/g, ''));
      if (isFinite(x) && x > 0) { S.slip.stake = x; persistSlip(); render(true); }
    };
    a.appendChild(el('div', { class: 'field' }, [el('label', { text: 'Stake per slip ($)' }), si]));
    a.appendChild(el('p', { class: 'fine',
      text: m.slips + (m.slips === 1 ? ' slip · ' : ' slips · ') + money(m.outlay)
          + ' at risk · every combination of ' + m.legs.length
          + (m.legs.length === 1 ? ' leg' : ' legs') }));

    if (m.priced) {
      const brk = el('div', { class: 'brk' });
      ['Legs in', 'Chance', 'Net'].forEach((h, i) =>
        brk.appendChild(el('div', { class: 'h' + (i ? ' r' : ''), text: h })));
      m.rows.forEach(r => {
        brk.appendChild(el('div', {
          title: r.slipsWon ? r.slipsWon + ' of ' + m.slips + ' slips pay' : 'no slip pays',
          text: r.hit + ' of ' + m.legs.length
              + (r.slipsWon ? ' · ' + r.slipsWon + '/' + m.slips : '') }));
        brk.appendChild(el('div', { class: 'r', text: chanceTxt(r.chance) }));
        // A range where there is one. With k of n scoring, *which* k they were
        // decides what came back, and on spread-out prices the best and worst
        // cases are far apart — an average alone would read as a certainty.
        const spread = Math.abs(r.netHi - r.netLo) > 0.005;
        brk.appendChild(el('div', {
          class: 'r ' + (r.net >= 0 ? 'pos' : 'neg'),
          title: spread ? 'between ' + money(r.netLo) + ' and ' + money(r.netHi)
                        + ', depending which legs landed' : null,
          text: money(r.net) + (spread ? '*' : '') }));
      });
      a.appendChild(el('div', { class: 'panel' }, [brk]));
      const anySpread = m.rows.some(r => Math.abs(r.netHi - r.netLo) > 0.005);
      a.appendChild(el('p', { class: 'fine', html:
        'Expected <b class="' + (m.ev >= 0 ? 'pos' : 'neg') + '">' + esc(money(m.ev)) + '</b> per run ('
        + (m.roi >= 0 ? '+' : '') + (m.roi * 100).toFixed(1) + '% on ' + esc(money(m.outlay))
        + '), at our numbers and each leg\u2019s own price.'
        + (anySpread ? ' A starred net is an average: which legs landed changes what came back.' : '')
        + ' Teammates are treated as correlated \u2014 one offence stalling takes '
        + 'its players down together \u2014 and legs in different games as independent.' }));
    } else {
      a.appendChild(el('p', { class: 'fine',
        text: 'One of these legs has no posted price, so there is nothing to multiply. '
            + 'The chances above still hold; the payout does not exist yet.' }));
    }
  }

  a.appendChild(el('div', { style: 'margin-top:4px' }, [saveButton()]));
  const graded = gradedNote(S.slip.market);
  if (graded) a.appendChild(el('p', { class: 'fine', html: '<b>Graded:</b> ' + esc(graded) }));
  return a;
}

// What actually goes beside the board.
//
// Three states, and the middle one is the point: a slip with legs that has
// been put away is not an empty slip. It comes back with everything in it, and
// until it does the board has the full width of the window.
// One component, everywhere. The Combinations page used to get a cut-down
// version without the round robin or the breakdown, on the reasoning that a
// second full builder there was noise — but it is the same slip, and a control
// that exists on one page and not another for the same object is a control you
// have to remember the location of.
function slipSlot() {
  // A conflict has to be answered, so it opens the panel whatever else is
  // true. Otherwise: nothing in it, nothing to show. An empty slip used to
  // render a dashed rectangle saying "add players from the list", which is an
  // instruction taking 360px away from the list it refers to.
  if (S.conflict) return slipPanel();
  if (!S.slipOpen || !S.slip.legs.length) return null;
  return slipPanel();
}
function slipHandle() {
  const n = S.slip.legs.length;
  if (S.slipOpen || !n) return null;
  const b = el('button', { class: 'sliptab', 'aria-label': 'Open your slip, ' + n
    + (n === 1 ? ' leg' : ' legs'), onclick: () => { S.slipOpen = true; render(); } });
  b.appendChild(el('span', { text: 'Your slip' }));
  b.appendChild(el('span', { class: 'n', text: String(n) }));
  return b;
}

// Saving is a snapshot, not a pointer: the legs, the round robin and the
// stake, so loading it back reproduces the same breakdown even if the board
// has moved underneath it. Editing anything unsaves, which is what makes the
// green state trustworthy.
function slipSignature() {
  return JSON.stringify([S.slip.market, S.slip.stake,
                         S.slip.legs.map(l => l.id).sort()]);
}
function saveButton() {
  const sig = slipSignature();
  const on = S.saved.sig === sig;
  const b = el('button', { class: 'btn primary ' + (on ? 'done' : 'solid'),
    text: on ? '✓ Saved to parlays' : 'Save this parlay',
    onclick: () => { saveSlip(); } });
  if (!on) return b;
  const w = el('div', { style: 'display:flex;flex-direction:column;gap:8px' }, [b]);
  w.appendChild(el('a', { href: '#saved', text: 'View saved parlays',
    style: 'font-size:14px;color:var(--ours);min-height:44px;display:inline-flex;align-items:center' }));
  return w;
}
function saveSlip() {
  const m = slipMath();
  if (!m.legs.length) return;
  const p = {
    id: 'p' + Date.now().toString(36),
    name: m.legs.length + '-leg ' + marketLabel(S.slip.market),
    market: S.slip.market, marketLabel: marketLabel(S.slip.market),
    week: DATA.week, season: DATA.season,
    size: 0, stake: S.slip.stake,
    slips: m.slips, outlay: m.outlay,
    chance: m.all, priced: m.priced,
    // The whole payout curve, so a saved slip reproduces its breakdown rather
    // than being re-derived from a single averaged price that no slip pays.
    rows: m.rows.map(r => ({ hit: r.hit, slipsWon: r.slipsWon,
                             chance: r.chance, net: r.net })),
    ev: m.ev,
    legs: m.legs.map(l => ({ id: l.id, key: l.key, player: l.player, side: l.side,
                             label: l.label, odds: l.odds, dec: l.dec, p: l.p, game: l.game })),
    savedAt: new Date().toISOString(),
  };
  S.parlays = S.parlays.concat([p]);
  saveParlays(S.parlays);
  S.saved = { sig: slipSignature(), id: p.id };
  render();
}
function gradedNote(key) {
  if (key === 'rec') {
    const f = (DATA.receptions || {}).forward;
    if (!f) return 'receptions has not been graded against a close yet.';
    if (f.raw_beats_market) return 'the raw receptions model is ahead of the market, '
      + 'which has meant a leak every previous time. See the Model page.';
    return 'receptions is served as 17% our number and 83% the book\u2019s, which beats '
      + 'the book by ' + (f.pooled.market_log_loss - f.pooled.model_log_loss).toFixed(4)
      + ' of log loss over ' + f.pooled.n.toLocaleString() + ' settled lines. Real, '
      + 'small, and not a betting edge.';
  }
  const rec = ((marketOf(key).shortlist || {}).record || {});
  const arm = armOf(rec, 'shortlist') || armOf(rec, 'we rate higher');
  if (!arm || !has(arm.roi)) return null;
  return 'backing every player we rate above the price returned '
    + roiTxt(arm.roi) + ' a bet over ' + (rec.seasons || []).join('–') + '.';
}
// The graded record is a list of arms — "all priced", "we rate higher",
// "shortlist" — because the rule is a funnel and each stage has its own
// number. Read by name rather than by index: the list gains arms.
function armOf(rec, name) {
  return ((rec || {}).arms || []).find(a => a.arm === name) || null;
}
const roiTxt = v => (v > 0 ? '+' : '−') + Math.abs(v).toFixed(1) + '%';
"""


JS_WEEK = r"""
// ── Page: This week ─────────────────────────────────────────────────────
//
// The whole slate, and the page the export opens on. Four of the old
// dashboard's tabs live here: the board is Players, the star and its chip are
// Favorites, the panel on the right is Parlay, and a game chip opens what
// Teams used to answer.
//
// The market menu is the only place the three markets are switched, so the
// board, the slip and the graded note can never disagree about which one is
// being looked at — which they could when the market was a segmented control
// on one tab and a different control on another.
function pageWeek() {
  const f = S.fw, key = S.market, kind = KIND[key] || 'td';
  const m = marketOf(key);
  // A count market has no fitted shortlist rule, so its views are different:
  // everything, or the rows a book has actually quoted. See `viewSeg`.
  const view = kind === 'ou' ? (f.view === 'priced' ? 'priced' : 'all') : f.view;
  let rows = rowsFor(key, view === 'priced' ? 'all' : view);
  if (view === 'priced') rows = rows.filter(r => r.priced);
  const out = el('div', { class: 'wrap' });
  const main = el('main');

  const HEAD = {
    all: ['Who scores', 'Every player on the slate, with our number beside the book’s.'],
    short: ['Shortlist', 'Players we rate at least ' + floorTxt(m)
            + ' above the price, in the range where the market has tended to move our way.'],
    fade: ['Leave these out', 'We rate them below the price. You cannot bet against them at a '
           + 'book, but they are worth keeping off a parlay.'],
  };
  const head = kind === 'ou'
    ? (view === 'priced'
        ? [marketLabel(key), 'The lines a book has actually posted, against what '
           + 'the count model projects.']
        : [marketLabel(key), 'Every player on the slate with a projection, whether '
           + 'or not a book has drawn a line on him yet.'])
    : HEAD[view];
  main.appendChild(el('div', { class: 'pagehead' }, [
    el('div', {}, [el('h1', { text: head[0] }), el('p', { class: 'lede', text: head[1] })]),
    marketMenu(),
  ]));

  main.appendChild(viewSeg(f, m, kind, rowsFor(key, 'all')));
  if (view === 'short') main.appendChild(funnelStrip(m, key, rows.length));

  (m.problems || []).forEach(p => main.appendChild(el('div', { class: 'badbox', text: String(p) })));

  // ── Filters ──────────────────────────────────────────────────────────
  const games = Array.from(new Set(rows.map(r => r.game).filter(Boolean))).sort();
  const poss = Array.from(new Set(rows.map(r => r.pos).filter(Boolean))).sort();
  const bar = el('div', { class: 'chiprow' });
  bar.appendChild(searchBox(f));
  bar.appendChild(favChip(f, rows));
  if (poss.length) bar.appendChild(pickerFor('Position', f.pos,
    [['', 'Any position']].concat(poss.map(p => [p, p])), v => { f.pos = v; }));
  if (kind === 'td') bar.appendChild(pickerFor('Priced', f.priced,
    [['all', 'Priced and not'], ['priced', 'Priced only'], ['unpriced', 'No price only']],
    v => { f.priced = v; }));
  if (games.length) bar.appendChild(pickerFor('Game', f.game,
    [['', 'All ' + games.length + ' games']].concat(games.map(g => [g, g])), v => { f.game = v; }));
  if (f.q || f.game || f.pos || f.favOnly || f.priced !== 'all')
    bar.appendChild(el('button', { class: 'chip', text: 'Clear filters', onclick: () => {
      S.fw = Object.assign(S.fw, { q: '', game: '', pos: '', priced: 'all', favOnly: false });
      render();
    } }));
  main.appendChild(bar);

  if (f.game) main.appendChild(gameCard(f.game, rows));

  const shown = applyFilters(rows, f);
  main.appendChild(kind === 'ou' ? ouTable(shown, f) : tdTable(shown, f, view));
  main.appendChild(countLine(shown.length, rows.length, kind === 'ou' ? 'lines' : 'players'));
  if (view !== 'fade') main.appendChild(el('p', { class: 'fine' }, [
    document.createTextNode('Looking for the best slips among these players rather than the '
      + 'players themselves? '),
    el('a', { href: '#combos', text: 'Combinations' }),
    document.createTextNode(' searches every subset of a pool you choose.'),
  ]));

  out.appendChild(main);
  const slip = slipSlot();
  if (slip) out.appendChild(slip);
  return out;
}

// Three views of one board. A segmented control rather than chips, because
// they are mutually exclusive readings of the same rows and chips read as
// additive.
function viewSeg(f, m, kind, allRows) {
  const g = el('div', { class: 'seg', role: 'group', 'aria-label': 'View' });
  let opts;
  if (kind === 'ou') {
    // No Shortlist here, and that is a statement rather than an omission.
    // The touchdown shortlist is a rule with a floor fitted on the seasons the
    // market moved our way and a graded return beside it. Nothing equivalent
    // exists for receptions: what we serve is 83% the book, the disagreements
    // that remain are one or two points, and they do not survive the vig. A
    // control called Shortlist would imply a bet list that has not been
    // measured. Priced is the narrowing that is actually useful — most of this
    // board has no line on it until close to kickoff.
    const priced = allRows.filter(r => r.priced).length;
    opts = [['all', 'Everyone', allRows.length], ['priced', 'Priced', priced]];
  } else {
    const sl = m.shortlist || {};
    opts = [['all', 'Everyone', (m.players || []).length],
            ['short', 'Shortlist', (sl.rows || []).length],
            ['fade', 'Fades', (sl.vetoes || []).length]];
  }
  const cur = opts.some(o => o[0] === f.view) ? f.view : 'all';
  opts.forEach(([k, label, n]) => {
    g.appendChild(el('button', { type: 'button', 'aria-pressed': cur === k ? 'true' : 'false',
      text: label + ' · ' + n,
      onclick: () => { f.view = k; f.sort = ''; render(); } }));
  });
  return el('div', { class: 'chiprow' }, [g]);
}

// The funnel, and the number that keeps it honest beside it. Both belong to
// the shortlist view and to nothing else: "36 shortlisted" means nothing
// without the 399 it came from, and neither means anything without the fact
// that backing all of them lost money over two graded seasons.
function funnelStrip(m, key, n) {
  const sl = m.shortlist || {}, dropped = sl.dropped || [];
  const priced = (m.players || []).filter(p => p.priced).length;
  const strip = el('div', { class: 'funnel' });
  const step = (text, last) => el('span', { class: 'step' + (last ? ' last' : ''), text: text });
  const arrow = () => { const w = el('span'); w.appendChild(svg(CHEV, { size: 14, stroke: 'var(--mut3)' })); return w; };

  strip.appendChild(step(priced + ' priced'));
  dropped.forEach((d, i) => {
    strip.appendChild(arrow());
    strip.appendChild(step(d.left + (i === dropped.length - 1 ? ' shortlisted' : ' we rate higher'),
      i === dropped.length - 1));
  });
  if (!dropped.length) { strip.appendChild(arrow()); strip.appendChild(step(n + ' shortlisted', true)); }

  const arm = armOf(sl.record || {}, 'shortlist') || armOf(sl.record || {}, 'we rate higher');
  if (arm && has(arm.roi)) {
    strip.appendChild(el('span', { class: 'roi', html:
      'Graded ' + esc((sl.record.seasons || []).join('–')) + ': <b class="'
      + (arm.roi >= 0 ? 'pos' : 'neg') + '">' + esc(roiTxt(arm.roi))
      + '</b> a bet on this rule' }));
  }
  return strip;
}
// The rule's own threshold, fitted rather than typed, so the copy above the
// board quotes what was actually applied.
function floorTxt(m) {
  const fl = (m.shortlist || {}).floor || {};
  return has(fl.lo) ? fl.lo.toFixed(0) + ' points' : 'the fitted floor';
}

function marketMenu() {
  const w = el('div', { class: 'menuwrap' });
  const b = el('button', { class: 'btn', 'aria-expanded': S.menuOpen ? 'true' : 'false',
    'aria-haspopup': 'menu', onclick: e => { e.stopPropagation(); S.menuOpen = !S.menuOpen; render(); } });
  b.appendChild(el('span', { class: 'note', text: 'Market' }));
  b.appendChild(el('span', { style: 'font-weight:600', text: marketLabel(S.market) }));
  b.appendChild(svg(DOWN, { size: 16 }));
  w.appendChild(b);
  if (!S.menuOpen) return w;

  const menu = el('div', { class: 'menu', role: 'menu' });
  MENU.forEach(g => {
    menu.appendChild(el('div', { class: 'grp', text: g.title }));
    g.items.forEach(([k, label, soon]) => {
      // "Soon" is not a promise, it is an absence stated plainly. A market
      // listed as pickable that the pipeline cannot serve reads as breakage.
      const off = !!soon || !served(k);
      const on = k === S.market;
      const it = el('button', { role: 'menuitemradio', 'aria-checked': on ? 'true' : 'false',
        disabled: off || null,
        onclick: off ? null : () => { S.market = k; S.menuOpen = false; S.fw.game = ''; render(); } }, [
        el('span', { text: label }),
        el('span', { class: 'tag', text: off ? 'Soon' : (on ? '✓' : '') }),
      ]);
      menu.appendChild(it);
    });
  });
  w.appendChild(menu);
  return w;
}

// What Teams used to answer, scoped to the fixture you picked: who the model
// likes on each side, and how much scoring it expects in total.
function gameCard(game, rows) {
  const inGame = rows.filter(r => r.game === game);
  const teams = Array.from(new Set(inGame.map(r => r.team).filter(Boolean)));
  const byTeam = teams.map(t => ({
    team: t,
    sum: inGame.filter(r => r.team === t).reduce((a, r) => a + (has(r.ours) ? r.ours : 0), 0),
    top: inGame.filter(r => r.team === t).sort((a, b) => (b.ours || 0) - (a.ours || 0))[0],
  })).sort((a, b) => b.sum - a.sum);
  const total = byTeam.reduce((a, t) => a + t.sum, 0) || 1;

  const c = el('div', { class: 'card pad', style: 'display:flex;align-items:center;gap:28px;flex-wrap:wrap' });
  c.appendChild(el('div', { style: 'width:150px;flex-shrink:0' }, [
    el('div', { class: 'note', style: 'text-transform:uppercase;letter-spacing:.5px;font-weight:600',
      text: 'Expected scorers' }),
    el('div', { style: 'font-size:18px;font-weight:700', text: game }),
  ]));
  const mid = el('div', { style: 'flex-grow:1;min-width:220px;display:flex;flex-direction:column;gap:6px' });
  mid.appendChild(el('div', { style: 'display:flex;justify-content:space-between;font-size:14px' }, [
    el('span', { html: '<b>' + (byTeam[0] ? byTeam[0].sum.toFixed(1) : '—') + '</b> ' + esc(byTeam[0] ? byTeam[0].team : '') }),
    el('span', { html: esc(byTeam[1] ? byTeam[1].team : '') + ' <b>' + (byTeam[1] ? byTeam[1].sum.toFixed(1) : '—') + '</b>' }),
  ]));
  const track = el('div', { style: 'height:10px;border-radius:5px;overflow:hidden;background:var(--oursfaint)' });
  track.appendChild(el('div', { style: 'height:100%;background:var(--ours);width:'
    + ((byTeam[0] ? byTeam[0].sum : 0) / total * 100).toFixed(1) + '%' }));
  mid.appendChild(track);
  mid.appendChild(el('div', { class: 'fine', text:
    'Our numbers add to ' + total.toFixed(1) + ' scorers in this game. '
    + (byTeam[0] && byTeam[0].top ? byTeam[0].team + '’s best is ' + byTeam[0].top.player
       + ' at ' + pct(byTeam[0].top.ours) + '.' : '') }));
  c.appendChild(mid);
  return c;
}

// ── The two board shapes ─────────────────────────────────────────────────
function tdTable(rows, f, view) {
  const cols = [
    { w: '44px', label: '', nosort: 1, mob: 'lead',
      title: 'Star a player to keep him in view. Favorites are held in this '
           + 'browser for this week only.',
      cell: (d, r) => d.appendChild(starBtn(r)) },
    { w: 'minmax(0,1fr)', label: 'Player', sort: 'player', mob: 'title',
      title: 'Who, his team, and the fixture. Click the fixture to filter the '
           + 'board to that game.',
      cell: (d, r) => {
        const w = el('div', { class: 'who' });
        w.appendChild(el('b', { text: r.player }));
        const sub = el('span');
        sub.appendChild(document.createTextNode((r.team || '') + ' · '));
        sub.appendChild(el('a', { href: '#week', text: r.game || '',
          style: 'color:var(--mut2)',
          onclick: e => { e.preventDefault(); f.game = r.game; render(); } }));
        if (r.status) sub.appendChild(document.createTextNode(' · ' + r.status));
        w.appendChild(sub);
        d.appendChild(w);
      } },
    { w: '150px', hide: 1, nosort: 1,
      title: 'Our number as a filled bar against the book\u2019s as a tick, both on '
           + 'the same scale for every row \u2014 so a longer bar always means a '
           + 'higher number, not a higher number for that row.',
      head: d => keyHead(d, view === 'all' ? 'Adj' : 'Model', 'Book'),
      // On the shortlist and the fades the bar draws the number the rule acts
      // on, which is the pre-blend one. Drawing the published number beside an
      // edge computed from a different one would be two answers to the same
      // question in the same row.
      cell: (d, r) => barCell(d, r, null, view === 'all' ? 'ours' : 'modelOnly') },
    // Three numbers, in the order they are made. `Model` is what the fitted
    // model said on its own; `Book` is the de-vigged market price; `Adj` is
    // ours after the market blend and the joint step, and is the one every
    // other column is computed from. Showing only the last of those made the
    // blend invisible — a row where we agree with the book because we were
    // pulled there looked identical to one where we agreed on our own.
    // Odds first: it is the thing being compared against, so the three
    // probabilities read left to right as an answer to it rather than as
    // figures you have to carry across the row.
    //
    // No "best price" line under it. It named a book per player on a page that
    // is not a bet card, and the shopping figure it came from is a
    // week-level number — `line_shopping` reports it on its own terms.
    { w: '80px', label: 'Odds', r: 1, sort: 'odds',
      title: 'The consensus price across books, de-vigged into Book beside it. '
           + '\u201cNo price\u201d means nobody has quoted him yet, which is common '
           + 'early in the week.',
      cell: (d, r) => d.appendChild(el('span', {
        class: r.priced ? '' : 'dim', text: r.priced ? american(r.odds) : 'no price' })) },
    { w: '56px', label: 'Model', r: 1, sort: 'modelOnly', hide: 1,
      title: 'The fitted model alone, before any market information.',
      cell: (d, r) => d.appendChild(el('span', { class: 'dim',
        text: has(r.modelOnly) ? pct(r.modelOnly) : '—' })) },
    { w: '56px', label: 'Book', r: 1, sort: 'book',
      title: 'The market\u2019s own probability with its margin removed \u2014 what the '
           + 'book actually thinks, rather than what it charges.',
      cell: (d, r) =>
        d.appendChild(el('span', { class: 'dim', text: r.priced ? pct(r.book) : '—' })) },
    { w: '56px', label: 'Adj', r: 1, sort: 'ours',
      title: 'What we serve: the model after the market blend and the joint step.',
      cell: (d, r) => d.appendChild(el('span', { class: 'big', text: pct(r.ours) })) },
    { w: '64px', label: 'Edge', r: 1, sort: 'edge',
      title: 'Model minus the book’s, in probability points — measured before '
           + 'the market blend, which is the basis the shortlist rule was '
           + 'backtested on.',
      cell: (d, r) => d.appendChild(el('span', {
        class: has(r.edge) ? (r.edge > 0 ? 'pos' : 'neg') : '', text: has(r.edge) ? spp(r.edge) : '' })) },

    { w: '86px', label: 'EV $100', r: 1, sortVal: r => ev100(r),
      title: 'What a flat $100 returns on average, at our number and the posted '
           + 'price. Negative is the usual answer. It is not a forecast of this '
           + 'bet — backing every player we rate above the price returned '
           + '\u221219.6% a bet over 2024\u201325, which is the figure to weigh a '
           + 'positive number here against.',
      cell: (d, r) => {
        const v = ev100(r);
        d.appendChild(el('span', { class: has(v) ? (v >= 0 ? 'pos' : 'neg') : 'dim',
          text: has(v) ? money(v) : '\u2014' }));
      } },
    { w: '92px', label: 'Read', sort: 'read',
      title: 'The verdict in one word. Strong call and Leans are above the price, '
           + 'Matches book is agreement, Veto is below it.',
      cell: (d, r) => r.read && d.appendChild(
        el('span', { class: 'pill ' + readClass(r.read), text: r.read })) },
    { w: '44px', label: '', nosort: 1, mob: 'act',
      title: 'Add him to your slip, where the whole set is priced together.',
      cell: (d, r) => d.appendChild(addBtn(r)) },
  ];
  const empty = view === 'short'
    ? { emptyTitle: 'Nothing survives every filter this week',
        emptyBody: 'That is an answer, not a gap: no disagreement here has held '
                 + 'up against the closing line.' }
    : { emptyTitle: 'No players match',
        emptyBody: 'Clear a filter, or search for a different name.' };
  return table(cols, rows, f, Object.assign({ id: 'td' }, empty));
}

function ouTable(rows, f) {
  const cols = [
    { w: '44px', label: '', nosort: 1, mob: 'lead',
      title: 'Star a player to keep him in view. Favorites are held in this '
           + 'browser for this week only.',
      cell: (d, r) => d.appendChild(starBtn(r)) },
    { w: 'minmax(0,1fr)', label: 'Player', sort: 'player', mob: 'title',
      title: 'Who and his team. A book count appears where fewer than three '
           + 'stood behind the line.',
      cell: (d, r) => {
        d.appendChild(el('div', { class: 'who' }, [
          el('b', { text: r.player }),
          el('span', { text: (r.team || '') + (r.thin ? ' · ' + r.nBooks + ' book' + (r.nBooks === 1 ? '' : 's') : '') }),
        ]));
      } },
    { w: '120px', hide: 1, nosort: 1,
      title: 'The projection as a filled bar against the posted line as a tick '
           + '\u2014 how far clear of the number we have him.',
      head: d => keyHead(d, 'Proj', 'Line'), cell: (d, r) => {
        // Projection against the line, both scaled to the same ceiling, so the
        // bar says "how far clear of the number do we have him".
        const top = Math.max(10, r.line * 1.6);
        const b = el('div', { class: 'bar' });
        b.appendChild(el('i', { style: 'width:' + Math.min(100, r.proj / top * 100).toFixed(1) + '%' }));
        b.appendChild(el('u', { style: 'left:' + Math.min(100, r.line / top * 100).toFixed(1) + '%' }));
        d.appendChild(b);
      } },
    { w: '52px', label: 'Line', r: 1, sort: 'line',
      title: 'The number a book posted. Blank means nobody has drawn one yet '
           + '\u2014 most of this board, until close to kickoff.',
      cell: (d, r) =>
        d.appendChild(el('span', { text: has(r.line) ? r.line.toFixed(1) : '' })) },
    { w: '56px', label: 'Proj', r: 1, sort: 'proj',
      title: 'Expected receptions \u2014 the count model\u2019s mean. Read it with the '
           + 'floor and ceiling beside it; a mean alone cannot be read.',
      cell: (d, r) =>
        d.appendChild(el('span', { class: 'big', text: has(r.proj) ? r.proj.toFixed(1) : '' })) },
    // Floor and ceiling as two columns rather than one range, so each can be
    // sorted on its own: "who has the highest floor" and "who has the biggest
    // ceiling" are different questions and a combined cell answers neither.
    //
    // Both are read off the same fitted distribution as every probability on
    // the row — the 15th and 85th percentiles, so the count sits between them
    // about seven games in ten. Two players can project the same mean and be
    // completely different bets; this is where that shows.
    { w: '58px', label: 'Floor', r: 1, sort: 'lo',
      title: 'He catches at least this many about 85% of the time — the 15th '
           + 'percentile of the fitted distribution.',
      cell: (d, r) => d.appendChild(el('span', { class: 'dim',
        text: has(r.lo) ? String(r.lo) : '' })) },
    { w: '68px', label: 'Ceiling', r: 1, sort: 'hi',
      title: 'He stays under this about 85% of the time — the 85th percentile '
           + 'of the fitted distribution.',
      cell: (d, r) => d.appendChild(el('span', { class: 'dim',
        text: has(r.hi) ? String(r.hi) : '' })) },
    { w: '56px', label: 'Model', r: 1, sort: 'modelOnly', hide: 1,
      title: 'The count model\u2019s own chance of the over, before it is shrunk '
           + 'toward the book.',
      cell: (d, r) => d.appendChild(el('span', { class: 'dim',
        text: has(r.modelOnly) ? pct(r.modelOnly) : '\u2014' })) },
    { w: '56px', label: 'Book', r: 1, sort: 'book',
      title: 'The market\u2019s own chance of the over, with its margin removed.',
      cell: (d, r) => d.appendChild(el('span', { class: 'dim',
        text: has(r.book) ? pct(r.book) : '\u2014' })) },
    { w: '56px', label: 'Adj', r: 1, sort: 'ours',
      title: 'What we serve: 17% the model, 83% the book. Where no line is '
           + 'posted there is nothing to shrink toward, so it is the model alone.',
      cell: (d, r) => d.appendChild(el('span', { class: 'big',
        text: has(r.ours) ? pct(r.ours) : '\u2014' })) },
    { w: '72px', label: 'Gap', r: 1, sort: 'edge',
      title: 'Ours minus the book’s. A disagreement, not an edge — on this market the book has been the better estimate.',
      cell: (d, r) => d.appendChild(el('span', {
        class: has(r.edge) ? (r.edge > 0 ? 'pos' : 'neg') : '', text: has(r.edge) ? spp(r.edge) : '' })) },
    { w: '86px', label: 'EV $100', r: 1, sortVal: r => ev100(r),
      title: 'What a flat $100 on the over returns on average, at what we serve '
           + 'and the posted price. On this market we serve 83% the book, so '
           + 'these are small by construction and mostly negative \u2014 the hold '
           + 'is about 7%.',
      cell: (d, r) => {
        const v = ev100(r);
        d.appendChild(el('span', { class: has(v) ? (v >= 0 ? 'pos' : 'neg') : 'dim',
          text: has(v) ? money(v) : '\u2014' }));
      } },
    { w: '132px', label: 'Bet', nosort: 1, mob: 'act',
      title: 'Add the over or the under to your slip. A count market has two '
           + 'sides, unlike a touchdown.',
      cell: (d, r) => {
        const g = el('div', { style: 'display:flex;gap:6px' });
        ['over', 'under'].forEach(side => {
          const on = legIn(r.id + '|' + side);
          g.appendChild(el('button', { class: 'chip', 'aria-pressed': on ? 'true' : 'false',
            'aria-label': (on ? 'Remove ' : 'Add ') + r.player + ' ' + side + ' ' + r.line,
            style: 'height:36px;padding:0 10px',
            text: side === 'over' ? 'O' : 'U', onclick: () => toggleLeg(r, side) }));
        });
        d.appendChild(g);
      } },
  ];
  return table(cols, rows, f, { id: 'ou',
    emptyTitle: 'No lines posted yet',
    emptyBody: 'Books post these much closer to kickoff than touchdown props.' });
}

// The four verdicts the board actually produces, each with its own colour.
// Substring matching got this wrong in a way nobody would notice: "Strong
// call" contains none of the words it looked for, so the strongest reading on
// the page rendered in the same grey as "Matches book".
const READ_CLASS = {
  'strong call': 'p-good',      // we rate him well above the price
  'leans': 'p-lean',            // above it, but not by much
  'matches book': 'p-mut',      // we and the market agree
  'veto': 'p-bad',              // we rate him below the price
};
function readClass(read) {
  return READ_CLASS[String(read).toLowerCase()] || 'p-mut';
}
function addBtn(row) {
  const on = legIn(row.id);
  return el('button', { class: 'add', 'aria-pressed': on ? 'true' : 'false',
    'aria-label': (on ? 'Remove ' : 'Add ') + row.player + (on ? ' from slip' : ' to slip'),
    text: on ? '✓' : '+', onclick: () => toggleLeg(row) });
}

"""


JS_COMBOS = r"""
// ── Page: Combinations ──────────────────────────────────────────────────
//
// The only page whose rows are not players. It takes a pool, enumerates every
// subset of a given size, and ranks them — so the unit here is a slip, which
// is why it is a page rather than a view of the board.
//
// `pool` is the control that matters and it defaults to the shortlist. Over
// the whole slate the top combinations are simply the four highest
// probabilities on the board, which is a list you already have; over a pool
// you chose, the question becomes the one worth asking — given these players,
// what goes together.
//
// Two honesty problems are on the page rather than in a footnote. Ranking by
// likelihood alone always returns the shortest-priced favourites, so price and
// expected value are ranking options beside it. And every number here assumes
// the legs are independent, which they are not: two players in the same game
// move together, so a same-game slip is further from its stated chance in both
// directions. Those slips are marked, and can be excluded outright.
const COMBO_POOL_MAX = 24;
const COMBO_SETS_MAX = 20000;

function pageCombos() {
  const c = S.cb, key = S.market, kind = KIND[key] || 'td';
  const m = marketOf(key);
  const out = el('div', { class: 'wrap' });
  const main = el('main');

  main.appendChild(el('div', { class: 'pagehead' }, [
    el('div', {}, [
      el('h1', { text: 'Combinations' }),
      el('p', { class: 'lede', text: 'Every slip you could build from a pool you choose, '
        + 'ranked. Save one straight to your parlays, or load it to price a round robin.' }),
    ]),
    marketMenu(),
  ]));

  // ── Pool ─────────────────────────────────────────────────────────────
  const sl = m.shortlist || {};
  // Only a row that can actually be backed belongs in a pool.
  //
  // On a count market most of the board is a projection with no line against
  // it, and a projection has no side and no price — there is nothing to
  // combine. Counting those in made the control say "Everyone · 531" while 7
  // rows were eligible, so any filter at all emptied the table and the label
  // was the thing that was wrong.
  const eligible = r => kind === 'ou' ? r.priced : has(r.ours);
  const board = rowsFor(key, 'all').filter(eligible);
  const pools = kind === 'ou'
    ? { all: { label: 'Priced', rows: board },
        fav: { label: 'Favorites', rows: board.filter(r => isFav(r.id)) } }
    : { short: { label: 'Shortlist', rows: rowsFor(key, 'short').filter(eligible) },
        fav: { label: 'Favorites', rows: board.filter(r => isFav(r.id)) },
        all: { label: 'Everyone', rows: board } };
  // Fall back before the control is drawn, or the pool in use is not the one
  // showing as pressed — which is how a count market rendered with nothing
  // selected at all.
  if (!pools[c.pool]) c.pool = 'all';
  const seg = el('div', { class: 'seg', role: 'group', 'aria-label': 'Pool' });
  Object.keys(pools).forEach(k => {
    seg.appendChild(el('button', { type: 'button', 'aria-pressed': c.pool === k ? 'true' : 'false',
      text: pools[k].label + ' · ' + pools[k].rows.length,
      onclick: () => { c.pool = k; render(); } }));
  });

  const bar = el('div', { class: 'chiprow' });
  bar.appendChild(seg);
  bar.appendChild(searchBox(c, 'Narrow the pool'));
  const base = pools[c.pool].rows;
  const games = Array.from(new Set(base.map(r => r.game).filter(Boolean))).sort();
  const poss = Array.from(new Set(base.map(r => r.pos).filter(Boolean))).sort();
  if (poss.length) bar.appendChild(pickerFor('Position', c.pos,
    [['', 'Any position']].concat(poss.map(x => [x, x])), v => { c.pos = v; }));
  if (games.length) bar.appendChild(pickerFor('Game', c.game,
    [['', 'All ' + games.length + ' games']].concat(games.map(g => [g, g])), v => { c.game = v; }));
  main.appendChild(bar);

  const ctl = el('div', { class: 'chiprow' });
  ctl.appendChild(el('div', { class: 'field' }, [el('label', { text: 'Legs' }),
    pickerFor('Legs per slip', c.legs, [2, 3, 4, 5, 6], v => { c.legs = +v; })]));
  ctl.appendChild(el('div', { class: 'field' }, [el('label', { text: 'Rank by' }),
    pickerFor('Rank by', c.rank, [
      ['likely', 'Most likely'], ['price', 'Longest price'], ['ev', 'Expected value'],
    ], v => { c.rank = v; })]));
  ctl.appendChild(el('div', { class: 'field' }, [el('label', { text: 'Show' }),
    pickerFor('How many', c.show, [10, 25, 50, 100], v => { c.show = +v; })]));
  ctl.appendChild(el('button', { class: 'chip', 'aria-pressed': c.sameGame ? 'true' : 'false',
    text: 'Allow same-game slips',
    onclick: () => { c.sameGame = !c.sameGame; render(); } }));
  main.appendChild(ctl);

  // ── The pool, after filtering ────────────────────────────────────────
  //
  // Capped, and the cap is stated. Every subset of 24 players taken 6 at a
  // time is 134,596 slips, which the browser will enumerate and no one will
  // read; past that the answer stops depending on the tail anyway because the
  // pool is already sorted by our own number.
  let pool = applyFilters(base, { q: c.q, game: c.game, pos: c.pos, priced: 'all' })
    .sort((a, b) => b.ours - a.ours);
  const poolFull = pool.length;
  pool = pool.slice(0, COMBO_POOL_MAX);

  const k = Math.min(c.legs, pool.length);
  const sets = pool.length >= 2 && choose(pool.length, k) <= COMBO_SETS_MAX
    ? combosOf(pool.length, k) : [];

  const stake = S.slip.stake || 10;
  let slips = sets.map(ix => {
    let p = 1, d = 1, priced = true;
    const gs = {};
    ix.forEach(i => {
      // `betProb`, not the published number, so a slip's EV here is measured
      // on the same quantity as the EV beside each player on the board.
      p *= betProb(pool[i]);
      if (has(pool[i].dec)) d *= pool[i].dec; else priced = false;
      gs[pool[i].game] = 1;
    });
    const sameGame = Object.keys(gs).length < ix.length;
    // Expected value of one stake on the whole slip, at our probability and
    // the posted price. Negative is the normal case and is not hidden.
    const ev = priced ? p * (stake * d - stake) - (1 - p) * stake : null;
    return { ix: ix, p: p, dec: priced ? d : null, ev: ev, sameGame: sameGame };
  });
  if (!c.sameGame) slips = slips.filter(s => !s.sameGame);

  const rank = { likely: (a, b) => b.p - a.p,
                 price: (a, b) => (b.dec || 0) - (a.dec || 0),
                 ev: (a, b) => (b.ev === null ? -Infinity : b.ev) - (a.ev === null ? -Infinity : a.ev) };
  const total = slips.length;
  slips = slips.sort(rank[c.rank] || rank.likely).slice(0, c.show);

  // ── Results ──────────────────────────────────────────────────────────
  const cols = [
    { w: 'minmax(0,2fr)', label: 'Slip', mob: 'title',
      title: 'The players in this combination, and their teams. Slips whose '
           + 'legs share a fixture are marked \u2014 those legs move together.',
      sortVal: s => s.ix.map(i => pool[i].player).join(' '),
      cell: (d, s) => {
        const names = s.ix.map(i => pool[i].player);
        const w = el('div', { class: 'who' });
        w.appendChild(el('b', { text: names.join(' · ') }));
        const sub = el('span');
        sub.appendChild(document.createTextNode(
          s.ix.map(i => pool[i].team).join(', ')));
        if (s.sameGame) {
          sub.appendChild(document.createTextNode(' · '));
          sub.appendChild(el('span', { class: 'pill p-bad', style: 'font-size:11px',
            text: 'same game' }));
        }
        w.appendChild(sub);
        d.appendChild(w);
      } },
    { w: '90px', label: 'All hit', r: 1, sortVal: s => s.p,
      title: 'The chance every leg lands, treating them as independent.',
      cell: (d, s) => d.appendChild(el('span', { class: 'big',
        text: chanceTxt(s.p) })) },
    { w: '96px', label: 'Pays', r: 1, sortVal: s => s.dec,
      title: 'What this slip returns if every leg lands, at each leg\u2019s own '
           + 'posted price. Blank where one of them has no price.',
      cell: (d, s) => d.appendChild(el('span', {
        text: s.dec ? american(decToAm(s.dec)) : '—' })) },
    { w: '100px', label: 'EV on $' + Math.round(stake), r: 1, sortVal: s => s.ev,
      title: 'What this slip returns on average per stake, at our numbers and '
           + 'each leg\u2019s own price. Measured on the same basis as the EV beside '
           + 'each player on This week. Negative is the usual answer.',
      cell: (d, s) => d.appendChild(el('span', {
        class: s.ev === null ? 'note' : (s.ev >= 0 ? 'pos' : 'neg'),
        text: s.ev === null ? 'unpriced' : money(s.ev) })) },
    { w: '150px', label: '', nosort: 1, mob: 'act',
      title: 'Load puts the combination in your slip to price as a round robin. '
           + 'Save keeps it as it stands, on the Saved page.',
      cell: (d, s) => {
        const g = el('div', { style: 'display:flex;gap:6px;justify-content:flex-end' });
        g.appendChild(el('button', { class: 'chip', text: 'Load',
          'aria-label': 'Load ' + s.ix.map(i => pool[i].player).join(', ') + ' into the slip',
          onclick: () => {
            // Stay put. The slip is beside this table, so navigating away to
            // show what just landed in it takes the reader off the page they
            // were working on to prove something they can already see.
            S.slip.market = key;
            S.slip.legs = s.ix.map(i => legOf(pool[i]));
            S.slip.size = 0;
            persistSlip();
            S.slipOpen = true;
            render();
          } }));
        const savedAlready = comboSaved(key, s, pool);
        g.appendChild(el('button', { class: 'chip', 'aria-pressed': savedAlready ? 'true' : 'false',
          text: savedAlready ? '✓ Saved' : 'Save',
          'aria-label': (savedAlready ? 'Already saved: ' : 'Save ')
            + s.ix.map(i => pool[i].player).join(', '),
          onclick: savedAlready ? null : () => saveCombo(key, s, pool) }));
        d.appendChild(g);
      } },
  ];
  main.appendChild(table(cols, slips, null, { id: 'combos',
    emptyTitle: pool.length < 2 ? 'Not enough players in this pool'
                                : 'No slip survives these settings',
    emptyBody: pool.length < 2
      ? (kind === 'ou'
          ? 'Only players a book has quoted can be combined — a projection with '
            + 'no line has no side to back. Books post these close to kickoff.'
          : 'Widen the pool, or clear a filter.')
      : 'Allow same-game slips, or ask for fewer legs.' }));

  main.appendChild(el('p', { class: 'fine', text:
    total.toLocaleString() + ' slip' + (total === 1 ? '' : 's') + ' of ' + k + ' from '
    + pool.length + ' player' + (pool.length === 1 ? '' : 's')
    + (poolFull > pool.length
       ? ' (the ' + COMBO_POOL_MAX + ' we rate highest, of ' + poolFull + ')' : '')
    + (total > slips.length ? ' · showing the top ' + slips.length : '') + '.' }));
  main.appendChild(el('p', { class: 'fine', style: 'max-width:680px', text:
    'Every figure treats the legs as independent, which they are not. Two '
    + 'players in one game share a script — if the offence stalls neither '
    + 'scores — so a same-game slip lands together or not at all more often '
    + 'than this says. That cuts both ways: it is likelier than the number '
    + 'above and also likelier to lose outright.' }));

  out.appendChild(main);
  const slip = slipSlot();
  if (slip) out.appendChild(slip);
  return out;
}

// Saving a combination without going through the slip.
//
// It is the same record `saveSlip` writes, built from a slip that was never
// loaded — so a parlay saved here loads back, settles and prices exactly like
// one built by hand. The stake and round robin come from the working slip, so
// the two controls a reader has already set are the ones that apply.
function comboKey(key, s, pool) {
  return key + '::' + s.ix.map(i => pool[i].id).sort().join('+');
}
function comboSaved(key, s, pool) {
  const want = comboKey(key, s, pool);
  return S.parlays.some(p => p.market === key
    && (p.legs || []).map(l => l.id).sort().join('+') === want.split('::')[1]);
}
function saveCombo(key, s, pool) {
  const legs = s.ix.map(i => legOf(pool[i]));
  const stake = S.slip.stake || 10;
  const p = {
    id: 'p' + Date.now().toString(36),
    name: legs.length + '-leg ' + marketLabel(key),
    market: key, marketLabel: marketLabel(key),
    week: DATA.week, season: DATA.season,
    size: 0, stake: stake, slips: 1, outlay: stake,
    chance: s.p, dec: s.dec || 1, priced: !!s.dec,
    // One slip, not a cover: you picked this combination, so it pays only
    // when every leg lands. Stored as the same curve shape as anything else
    // in the list, so the Saved page settles one kind of card rather than two.
    rows: legs.map((_, i) => i).concat([legs.length]).reverse().map(hit => ({
      hit: hit, slipsWon: hit === legs.length ? 1 : 0,
      chance: hit === legs.length ? s.p : null,
      net: hit === legs.length ? (s.dec ? stake * s.dec - stake : 0) : -stake,
    })),
    legs: legs.map(l => ({ id: l.id, key: l.key, player: l.player, side: l.side,
                           label: l.label, odds: l.odds, dec: l.dec, p: l.p, game: l.game })),
    savedAt: new Date().toISOString(),
    from: 'combinations',
  };
  S.parlays = S.parlays.concat([p]);
  saveParlays(S.parlays);
  S.notice = 'Saved ' + p.name + ' to your parlays.';
  render();
}
"""


JS_SAVED = r"""
// ── Page: Saved ─────────────────────────────────────────────────────────
//
// Slips kept from the board, and how they turned out. Scoped to this week like
// everything else the page remembers, which is a real narrowing — there is no
// season-long ledger here. What it keeps is the whole arc inside a week: save
// on Wednesday, watch the dots turn on Sunday, read the net on Monday.
//
// A saved parlay stores its structure, not a pointer at the board: the legs,
// the round robin and the stake, so loading it back reproduces the same
// breakdown even after the prices move underneath it.
function pageSaved() {
  const out = el('div', { class: 'wrap' });
  const main = el('main');
  const all = S.parlays.map(settle);

  const settled = all.filter(p => p.status !== 'Pending');
  const won = settled.filter(p => p.status === 'Won');
  const net = settled.reduce((a, p) => a + p.net, 0);

  main.appendChild(el('div', { class: 'pagehead' }, [
    el('div', {}, [
      el('h1', { text: 'Saved parlays' }),
      el('p', { class: 'lede', text: 'Slips you have kept. They settle on their own as games '
        + 'finish, and last week’s drop off once this one is over.' }),
    ]),
    el('div', { class: 'summary' }, [
      el('div', {}, [el('div', { text: 'Settled' }), el('b', { text: String(settled.length) })]),
      el('div', {}, [el('div', { text: 'Won' }), el('b', { text: String(won.length) })]),
      el('div', {}, [el('div', { text: 'Net' }),
        el('b', { class: net >= 0 ? 'pos' : 'neg', text: money(net) })]),
    ]),
  ]));

  const counts = { all: all.length, pending: all.length - settled.length,
                   won: won.length, lost: settled.length - won.length };
  const chips = el('div', { class: 'chiprow' });
  [['all', 'All'], ['pending', 'Pending'], ['won', 'Won'], ['lost', 'Lost']].forEach(([k, label]) => {
    chips.appendChild(el('button', { class: 'chip', 'aria-pressed': S.savedFilter === k ? 'true' : 'false',
      text: label + ' · ' + counts[k], onclick: () => { S.savedFilter = k; render(); } }));
  });
  main.appendChild(chips);

  const keep = p => S.savedFilter === 'all'
    || (S.savedFilter === 'pending' && p.status === 'Pending')
    || (S.savedFilter === 'won' && p.status === 'Won')
    || (S.savedFilter === 'lost' && p.status === 'Lost');
  const shown = all.filter(keep);

  if (!all.length) {
    main.appendChild(el('div', { class: 'card pad', style: 'text-align:center;padding:48px' }, [
      el('p', { class: 'muted', text: 'Nothing saved yet. Build a slip on This week and press '
        + '“Save this parlay”.' }),
      el('p', { style: 'margin-top:12px' }, [el('a', { href: '#week', text: 'Go to this week' })]),
    ]));
  } else if (!shown.length) {
    main.appendChild(el('div', { class: 'card pad', style: 'text-align:center;padding:48px' }, [
      el('p', { class: 'muted', text: 'No saved parlay is ' + S.savedFilter + '.' }),
    ]));
  } else {
    const grid = el('div', { class: 'cards' });
    shown.forEach(p => grid.appendChild(parlayCard(p)));
    main.appendChild(grid);
  }
  out.appendChild(main);
  return out;
}

// Settlement, per leg and then per slip.
//
// `DATA.results` maps a leg id to 'hit' or 'miss' and carries only the weeks
// that have been graded, so before kickoff every leg is simply absent from it
// and the parlay is Pending. A leg the map does not know about keeps the whole
// slip pending rather than being assumed missed — a parlay that reads Lost
// because a name failed to match is worse than one that reads Pending for an
// hour longer.
function settle(p) {
  const res = DATA.results || {};
  // Keyed by week as well as market and player: `any|Derrick Henry` is a
  // different bet in week 2 than in week 3, and a shared key would settle a
  // live parlay from a result it never had.
  const legs = p.legs.map(l => ({ ...l, state: res[p.week + '|' + l.id] || 'pending' }));
  const pending = legs.some(l => l.state === 'pending');
  const hits = legs.filter(l => l.state === 'hit').length;
  let status = 'Pending', net = 0;
  if (!pending) {
    // Read the payout curve the slip was saved with, rather than re-deriving
    // it from a single price. A full cover pays every sub-slip whose legs all
    // landed, and those slips have different prices — there is no one number
    // to multiply, which is why the curve is stored.
    const row = (p.rows || []).find(r => r.hit === hits);
    if (row) {
      net = row.net;
      status = row.slipsWon > 0 ? 'Won' : 'Lost';
    } else {
      // A parlay saved before the curve existed. Treated as the single slip
      // it was: every leg or nothing.
      const won = hits === legs.length;
      const ret = p.priced && won ? p.stake * (p.dec || 1) : 0;
      net = ret - (p.outlay || p.stake * (p.slips || 1));
      status = won ? 'Won' : 'Lost';
    }
  }
  return { ...p, legs: legs, status: status, net: net, hits: hits };
}

function parlayCard(p) {
  const pend = p.status === 'Pending';
  const cls = pend ? 'p-ours' : p.status === 'Won' ? 'p-good' : 'p-bad';
  const a = el('article', { class: 'card' });

  a.appendChild(el('div', { style: 'display:flex;justify-content:space-between;align-items:flex-start;gap:12px' }, [
    el('div', { style: 'min-width:0' }, [
      el('h2', { text: p.name }),
      el('div', { class: 'note', text: p.marketLabel + ' · Week ' + p.week + ' · '
        + money(p.stake) + (p.size ? ' each · by ' + p.size + 's' : ' · every leg')
        + (p.last ? ' · last week' : '') }),
    ]),
    el('span', { class: 'pill ' + cls, text: p.status }),
  ]));

  const legs = el('div');
  p.legs.forEach(l => {
    legs.appendChild(el('div', { class: 'legline' }, [
      el('span', {}, [el('span', { class: 'dot ' + l.state }), el('em', { text: l.label })]),
      el('span', { class: 'note', text: has(l.odds) ? american(l.odds) : '—' }),
    ]));
  });
  a.appendChild(legs);

  a.appendChild(el('div', { class: 'three panel' }, [
    el('div', {}, [el('i', { class: 'note', style: 'font-style:normal;display:block;font-size:12px', text: 'Pays' }),
      el('b', { style: 'font-size:16px', text: p.priced ? american(decToAm(p.dec)) : '—' })]),
    el('div', {}, [el('i', { class: 'note', style: 'font-style:normal;display:block;font-size:12px', text: 'All hit' }),
      el('b', { style: 'font-size:16px', text: chanceTxt(p.chance) })]),
    el('div', {}, [el('i', { class: 'note', style: 'font-style:normal;display:block;font-size:12px',
        text: pend ? 'Legs in' : 'Result' }),
      el('b', { class: pend ? '' : (p.net >= 0 ? 'pos' : 'neg'), style: 'font-size:16px',
        text: pend ? p.hits + ' of ' + p.legs.length : money(p.net) })]),
  ]));

  const act = el('div', { style: 'display:flex;gap:8px;align-items:center' });
  act.appendChild(el('button', { class: 'btn solid', style: 'flex-grow:1',
    text: pend ? 'Load into slip' : 'Rebuild for this week',
    onclick: () => loadParlay(p) }));
  // Last week's cards are history and are owned by the key they were written
  // under, so there is no delete on them — a button that appeared to work and
  // silently did not would be worse than its absence. They go on their own
  // when the week turns over again.
  if (!p.last) {
    const del = el('button', { class: 'btn', style: 'width:44px;padding:0',
      'aria-label': 'Delete ' + p.name, onclick: () => {
        S.parlays = S.parlays.filter(x => x.id !== p.id);
        saveParlays(S.parlays);
        render();
      } });
    del.appendChild(svg(BIN, { size: 18 }));
    act.appendChild(del);
  }
  a.appendChild(act);
  return a;
}

// Loading a saved slip back.
//
// A leg whose player has no line on this week's board is kept and flagged
// rather than dropped. Dropping it silently would change the slip into a
// different, shorter one wearing the same name — and the reader would have no
// way to see that it had happened.
function loadParlay(p) {
  const live = rowsFor(p.market, 'all');
  const byId = {};
  live.forEach(r => { byId[r.id] = r; });
  S.slip.market = p.market;
  S.slip.size = p.size || 0;
  S.slip.stake = p.stake;
  S.slip.stakeRaw = String(p.stake);
  S.slip.legs = p.legs.map(l => {
    const base = l.id.split('|').slice(0, 2).join('|');
    const now = byId[base];
    if (!now) return { ...l, stale: true, sub: l.sub || 'no line this week' };
    const side = l.side;
    return { ...legOf(now, side), stale: false };
  });
  const stale = S.slip.legs.filter(l => l.stale).length;
  persistSlip();
  S.notice = stale
    ? stale + ' leg' + (stale === 1 ? '' : 's') + ' from that slip has no line on this '
      + 'week’s board. They are still on the slip, marked, so you can see what is missing.'
    : null;
  go('week');
}
"""


JS_LADDER = r"""
// ── Page: Ladder ────────────────────────────────────────────────────────
//
// Roll the whole balance into the next bet and see the path. The arithmetic is
// not in question: at decimal price d the balance is start × d^n if every bet
// wins. What the table cannot show is the other branch, which is one row tall
// and says zero — so the chance of the whole run sits beside the payout at the
// same size, because a payout without it is a number with no scale.
//
// That chance is read off the posted price and is therefore generous. A price
// implies 1/d including the book's margin, so it sits above what the book
// itself thinks will happen. Taken at face value the ladder is worth exactly
// its stake — p × d = 1 at every rung — and the margin is what pushes it below.
const LADDER_MAX = 50;

function pageLadder() {
  const L = S.ladder, out = el('div', { class: 'wrap' });
  const main = el('main');
  main.appendChild(el('div', { class: 'pagehead' }, [el('div', {}, [
    el('h1', { text: 'Ladder' }),
    el('p', { class: 'lede', text: 'Roll the balance into the next bet, and see what the run '
      + 'is worth against how likely it is to survive.' }),
  ])]));

  const money2 = v => '$' + Math.round(v).toLocaleString();
  // label / input / hint, every field the same three rows whether or not it
  // has a hint. The hint used to be optional, so the field carrying one was
  // taller than its neighbours and the row sat at three different heights.
  const num = (label, raw, onset, hint) => {
    const i = el('input', { type: 'text', inputmode: 'decimal', value: raw, 'aria-label': label });
    i.oninput = () => { onset(i.value); render(true); };
    return el('div', { class: 'field' },
      [el('label', { text: label }), i, el('span', { class: 'hint', text: hint || '' })]);
  };
  const bar = el('div', { class: 'fieldrow', style: 'max-width:640px' });
  bar.appendChild(num('Starting bankroll', L.startRaw, v => {
    L.startRaw = v; const x = parseFloat(v.replace(/[^0-9.]/g, ''));
    if (isFinite(x) && x > 0) L.start = x;
  }, 'Dollars'));
  bar.appendChild(num('Price each rung', L.oddsRaw, v => {
    L.oddsRaw = v;
    const t = v.replace(/[−–]/g, '-').trim();
    const a = parseFloat(t);
    if (isFinite(a) && Math.abs(a) >= 100) L.dec = amToDec(a);
    else if (isFinite(a) && a > 1 && a < 100) L.dec = a;
  }, 'American (−170) or decimal (1.59)'));
  bar.appendChild(num('Rungs', L.betsRaw, v => {
    L.betsRaw = v; const n = parseInt(v.replace(/[^0-9]/g, ''), 10);
    if (isFinite(n) && n > 0) L.bets = Math.min(LADDER_MAX, n);
  }, 'Up to ' + LADDER_MAX));
  main.appendChild(bar);

  const rows = [];
  let bal = L.start, p = 1;
  for (let i = 1; i <= Math.min(L.bets, LADDER_MAX); i++) {
    bal *= L.dec; p /= L.dec;
    rows.push({ rung: i, bal: bal, p: p, won: bal - L.start });
  }
  const last = rows[rows.length - 1];

  main.appendChild(el('div', { class: 'three', style: 'max-width:640px' }, [
    el('div', { class: 'stat' }, [el('i', { text: 'If every rung wins' }),
      el('b', { text: last ? money2(last.bal) : '—' })]),
    el('div', { class: 'stat' }, [el('i', { text: 'Chance of the run' }),
      el('b', { text: last ? chanceTxt(last.p) : '—' })]),
    el('div', { class: 'stat' }, [el('i', { text: 'At risk' }),
      el('b', { text: money2(L.start) })]),
  ]));

  const cols = [
    { w: '70px', label: 'Rung', sort: 'rung',
      title: 'Which bet in the run this is. Every rung assumes the one above it '
           + 'won.',
      cell: (d, r) => d.appendChild(el('span', { text: String(r.rung) })) },
    { w: 'minmax(0,1fr)', label: 'Balance', r: 1, sort: 'bal',
      title: 'What the whole bankroll is worth after this rung, with everything '
           + 'rolled into the next bet.',
      cell: (d, r) =>
        d.appendChild(el('span', { class: 'big', text: money2(r.bal) })) },
    { w: 'minmax(0,1fr)', label: 'Profit so far', r: 1, sort: 'won',
      title: 'Balance less what you started with \u2014 the winnings, if you stopped '
           + 'here.',
      cell: (d, r) =>
        d.appendChild(el('span', { class: 'pos', text: money2(r.won) })) },
    { w: 'minmax(0,1fr)', label: 'Chance of getting here', r: 1, sort: 'p',
      title: 'The chance every rung up to this one won. Read off the posted '
           + 'price, so it includes the book\u2019s margin and is kinder than the truth.',
      cell: (d, r) =>
        d.appendChild(el('span', { text: chanceTxt(r.p) })) },
  ];
  main.appendChild(table(cols, rows, null, { id: 'ladder' }));
  main.appendChild(el('p', { class: 'fine', style: 'max-width:640px', text:
    'Every row assumes the one above it won. The branch where it did not is a '
    + 'single row saying zero, and it is the likelier branch from about the '
    + 'third rung on. The chance column is read off the price, so it includes '
    + 'the book’s margin and is therefore kinder than the truth.' }));
  out.appendChild(main);
  return out;
}
"""


JS_MODEL = r"""
// ── Page: Model ─────────────────────────────────────────────────────────
//
// Provenance and record, for all three markets at once rather than for
// whichever one happened to be selected. What is scoring the board, how it did
// on seasons it never trained on, what it is built from, and — for receptions
// — the standing admission that the book is better at it than we are.
//
// Everything here is read off artifacts. Nothing is recomputed for display: a
// page that recalculates its own provenance can agree with itself while
// disagreeing with what is being served.
function pageModel() {
  const out = el('div', { class: 'wrap' });
  const main = el('main');
  main.appendChild(el('div', { class: 'pagehead' }, [el('div', {}, [
    el('h1', { text: 'How good is the model?' }),
    el('p', { class: 'lede', text: 'What is scoring this week’s board, how it did on seasons it '
      + 'never saw, and where the numbers came from.' }),
  ])]));

  DATA.markets.forEach(m => main.appendChild(marketCard(m)));
  const rec = DATA.receptions;
  if (rec && rec.forward) main.appendChild(receptionsCard(rec));

  out.appendChild(main);
  return out;
}

function marketCard(m) {
  const w = m.served || {}, r = m.recipe;
  const c = el('div', { class: 'card pad', style: 'display:flex;flex-direction:column;gap:14px' });
  c.appendChild(el('h2', { class: 'h2s', text: m.label }));

  c.appendChild(el('div', { class: 'three' }, [
    stat('Model', (w.model || '—').toUpperCase(), 'chosen per market, not globally'),
    stat('Version', w.version || '—', w.created ? w.created.slice(0, 10) + ' promoted' : ' '),
    stat('Features', r ? r.n_features.toLocaleString() : '—',
         r ? r.n_families + ' families' : ' '),
  ]));

  if (w.dirty) c.appendChild(el('div', { class: 'warnbox', html:
    '<b>This version was locked from a tree with uncommitted changes.</b> The '
    + 'artifacts scoring the board are the promoted ones and are fine; what is '
    + 'incomplete is their provenance. Cleaning the tree now does not change '
    + 'this — locking a new version from a clean one does.' }));
  (w.problems || []).forEach(p => c.appendChild(el('div', { class: 'badbox', text: String(p) })));
  if (w.note) c.appendChild(el('p', { class: 'muted', text: w.note }));

  // How the top pick did, per season it never trained on.
  if (r && r.seasons && r.seasons.length) {
    const cols = [
      { w: 'minmax(0,1fr)', label: 'Test season', sort: 'season',
        title: 'A season the model never trained on. Everything in this row is '
             + 'measured on games it had not seen.',
        cell: (d, s) =>
          d.appendChild(el('span', { text: String(s.season) })) },
      { w: '80px', label: 'Games', r: 1, sort: 'games',
        title: 'How many fixtures the row is measured over.',
        cell: (d, s) =>
          d.appendChild(el('span', { text: String(s.games) })) },
      { w: '110px', label: 'Top 1', r: 1, sort: 'top1',
        title: 'How often the player we rank first in a game scored.',
        cell: (d, s) => d.appendChild(el('span', { class: 'big', text: pct(s.top1, 1) })) },
      { w: '90px', label: 'Top 3', r: 1, sort: 'top3',
        title: 'How often at least one of our top three in a game scored.',
        cell: (d, s) =>
          d.appendChild(el('span', { class: 'dim', text: pct(s.top3, 1) })) },
      { w: '90px', label: 'Top 5', r: 1, sort: 'top5',
        title: 'How often at least one of our top five in a game scored.',
        cell: (d, s) =>
          d.appendChild(el('span', { class: 'dim', text: pct(s.top5, 1) })) },
    ];
    c.appendChild(table(cols, r.seasons, null, { id: 'seasons:' + m.key }));
  }

  // What the model is built from, and what each part is worth. `worth_top1` is
  // an ablation: retrain without the family and see what the top pick loses.
  // Families with a measured cost are listed first because that is the only
  // part of this a reader can act on.
  if (r && r.families && r.families.length) {
    const fam = r.families.slice().sort((a, b) =>
      (has(b.worth_top1) ? Math.abs(b.worth_top1) : -1) - (has(a.worth_top1) ? Math.abs(a.worth_top1) : -1));
    const cols = [
      { w: 'minmax(0,1fr)', label: 'Family', sort: 'name',
        title: 'A group of related feature columns \u2014 usage, matchup, pace \u2014 '
             + 'and how many columns are in it.',
        cell: (d, f) => d.appendChild(el('div', { class: 'who' }, [
          el('b', { text: f.name }), el('span', { text: f.n + ' columns' })])) },
      { w: '120px', label: 'Worth', r: 1, sort: 'worth_top1',
        title: 'Top-1 lost when this family is removed and the model refitted.',
        cell: (d, f) => d.appendChild(el('span', {
          class: has(f.worth_top1) ? (f.worth_top1 > 0 ? 'pos' : 'neg') : 'note',
          text: has(f.worth_top1) ? spp(f.worth_top1 * 100) + ' pp' : 'not measured' })) },
      { w: '110px', label: 'p', r: 1, sort: 'p_value',
        title: 'How likely a drop this size is if the family were worth nothing. '
             + 'Small means the loss is unlikely to be noise.',
        cell: (d, f) => d.appendChild(el('span', {
          class: 'dim', text: has(f.p_value) ? f.p_value.toFixed(3) : '' })) },
    ];
    c.appendChild(el('h3', { style: 'margin-top:4px', text: 'What it uses, and what each part is worth' }));
    c.appendChild(table(cols, fam, null, { id: 'families:' + m.key }));
    if (r.unattributed && r.unattributed.length) c.appendChild(el('p', { class: 'fine',
      text: r.unattributed.length + ' columns belong to no family and are not ablated: '
          + r.unattributed.slice(0, 8).join(', ')
          + (r.unattributed.length > 8 ? ' …' : '') }));
  }
  return c;
}

function receptionsCard(rec) {
  const f = rec.forward, p = f.pooled;
  const c = el('div', { class: 'card pad', style: 'display:flex;flex-direction:column;gap:14px' });
  c.appendChild(el('h2', { class: 'h2s', text: 'Receptions' }));
  c.appendChild(el('div', { class: f.beats_market ? 'badbox' : 'warnbox', html: f.beats_market
    ? '<b>This model is currently ahead of the market, which on this market has '
      + 'meant a bug every previous time.</b> The first version of it beat receptions '
      + 'by +17–22% ROI and that was the NGS existence leak — the model could see '
      + 'whether a player had a tracking record, which only exists for players who '
      + 'played. Treat this as something to investigate, not something to bet.'
    : '<b>The book prices this market better than we do.</b> Over '
      + p.n.toLocaleString() + ' settled lines its de-vigged price has a log loss of '
      + p.market_log_loss.toFixed(4) + ' against our ' + p.model_log_loss.toFixed(4)
      + '. That is what a market holding around 7% looks like when you bring a model '
      + 'to it. This market is on the page to be measured in public, not to be bet.' }));
  const cols = [
    { w: 'minmax(0,1fr)', label: 'Week', sort: 'week',
      title: 'A played week of this season, graded against the last price on '
           + 'offer before kickoff.',
      cell: (d, w) => d.appendChild(el('span', { text: 'Week ' + w.week })) },
    { w: '80px', label: 'Lines', r: 1, sort: 'n',
      title: 'Settled lines in the week. Whole-number pushes are excluded \u2014 '
           + 'neither side called those wrong.',
      cell: (d, w) => d.appendChild(el('span', { text: String(w.n) })) },
    { w: '100px', label: 'Went over', r: 1, sort: 'over_rate',
      title: 'How often the count actually beat the line. Near 50% is what a '
           + 'well-set market looks like.',
      cell: (d, w) =>
        d.appendChild(el('span', { class: 'dim', text: pct(w.over_rate, 1) })) },
    { w: '90px', label: 'Us', r: 1, sort: 'model_log_loss',
      title: 'Log loss of what we serve. Lower is better; green means we beat '
           + 'the market that week.',
      cell: (d, w) =>
        d.appendChild(el('span', {
          class: w.model_log_loss < w.market_log_loss ? 'pos' : 'neg',
          text: w.model_log_loss.toFixed(4) })) },
    { w: '90px', label: 'Market', r: 1, sort: 'market_log_loss',
      title: 'Log loss of the de-vigged book price over the same lines.',
      cell: (d, w) =>
        d.appendChild(el('span', { class: 'dim', text: w.market_log_loss.toFixed(4) })) },
  ];
  c.appendChild(table(cols, f.weeks, null, { id: 'recweeks' }));
  c.appendChild(el('p', { class: 'fine', text: f.note + ' In-play quotes are excluded: a book '
    + 'still quoting in the fourth quarter is quoting on a game it can already see.' }));
  return c;
}

function stat(k, v, d) {
  return el('div', { class: 'stat' }, [
    el('i', { text: k }), el('b', { style: 'font-size:18px', text: v }),
    el('i', { class: 'note', text: d || ' ' }),
  ]);
}
"""


JS_SHELL = r"""
// ── Shell ───────────────────────────────────────────────────────────────
const VIEWS = { week: pageWeek, combos: pageCombos, saved: pageSaved,
                ladder: pageLadder, model: pageModel };

function render(keepFocus) {
  const active = keepFocus ? document.activeElement : null;
  const label = active && active.getAttribute ? active.getAttribute('aria-label') : null;
  const sel = active && active.selectionStart;

  $('#top').innerHTML = '';
  $('#top').appendChild(el('div', { class: 'brand', text: DATA.brand || 'Pick Six' }));
  const nav = el('nav', { class: 'nav' });
  PAGES.forEach(([id, text]) => nav.appendChild(el('a', {
    href: '#' + id, text: text, 'aria-current': S.route === id ? 'page' : null })));
  $('#top').appendChild(nav);
  $('#top').appendChild(el('div', { class: 'when',
    text: (DATA.season || '') + ' · Week ' + (DATA.week || '') }));

  const root = $('#root');
  root.innerHTML = '';
  if (S.notice) {
    root.appendChild(el('div', { class: 'warnbox', style: 'margin:16px 40px 0', text: S.notice }));
    S.notice = null;
  }
  if (S.storageBroke) root.appendChild(el('div', { class: 'badbox', style: 'margin:16px 40px 0',
    text: 'This browser will not let the page save anything, so favorites, the slip and '
        + 'saved parlays will not survive a reload. Private browsing usually does this.' }));
  root.appendChild((VIEWS[S.route] || pageWeek)());
  const handle = slipHandle();
  if (handle) root.appendChild(handle);

  if (label) {
    const again = root.querySelector('[aria-label="' + label.replace(/"/g, '\\"') + '"]');
    if (again && again.focus) {
      again.focus();
      if (sel != null && again.setSelectionRange) { try { again.setSelectionRange(sel, sel); } catch (e) {} }
    }
  }
}
document.addEventListener('DOMContentLoaded', boot);
"""


SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ctext y='26' font-size='26'%3E%F0%9F%8F%88%3C/text%3E%3C/svg%3E">
<style>__FONTS____CSS__</style>
</head>
<body>
<header class="top" id="top"></header>
<noscript>
  <div style="max-width:640px;margin:48px auto;padding:0 24px;font:16px/1.5 Georgia,serif">
    <h1 style="font-family:Georgia,serif;font-weight:500">This page needs JavaScript</h1>
    <p style="color:#5E6168">Every number here is computed in your browser — the board,
    the parlay maths and the combinations search — so there is nothing to show without it.
    Nothing is sent anywhere; that is the same reason it works with no network.</p>
  </div>
</noscript>
<div id="root"></div>
<footer style="padding:24px 40px 40px;color:var(--mut2);font-size:13px;max-width:900px">
__FOOTER__
</footer>
<script id="payload" type="application/json">__DATA__</script>
<script>const DATA = JSON.parse(document.getElementById('payload').textContent);</script>
<script>__JS__</script>
</body>
</html>
"""

FOOTER = """<p>Built __BUILT__ from the model each market's registry says it is serving.
Every probability is the model's; every price is an archived consensus across books,
de-vigged. Favorites, the working slip and saved parlays are held in this browser
only, scoped to this season and week, and clear when the week rolls over.</p>
<p>Nothing here is advice. The graded figures on the shortlist are what the rule
actually returned over the seasons named beside them, and they are negative.</p>
"""


def render(payload: dict) -> str:
    """The whole page, as one string."""
    js = "\n".join([JS_CORE, JS_SHARED, JS_SLIPVIEW, JS_WEEK, JS_COMBOS,
                    JS_SAVED, JS_LADDER, JS_MODEL, JS_SHELL])
    # `</` inside the JSON would close the script tag early and render the rest
    # of the payload as text. Escaping is cheaper than trusting that no player
    # is ever named in a way that produces one.
    data = (json.dumps(payload, separators=(",", ":"), allow_nan=False)
            .replace("</", "<\\/"))
    brand = payload.get("brand") or "Pick Six"
    return (SHELL
            .replace("__TITLE__", html.escape(
                f"{brand} — {payload.get('season', '')} week {payload.get('week', '')}"))
            .replace("__FONTS__", _font_faces())
            .replace("__CSS__", CSS)
            .replace("__FOOTER__", FOOTER.replace(
                "__BUILT__", html.escape(str(payload.get("built", "")))))
            .replace("__JS__", js)
            .replace("__DATA__", data))
