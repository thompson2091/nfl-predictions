# Pick Six Mobile — the v2 design

`prototype.html` is the clickable prototype, saved from the artifact at
https://claude.ai/artifact/BEbwcaHvnG8xNsE3QHc9Jb — 897 lines, self-contained,
open it in a browser. It carries real week-2 numbers for 63 anytime-TD players
and every screen works: tap a row, build a slip, open any sheet, ladder it.

Read it as the source of truth. What follows is the index.

## This is not a reskin of site.html

`site.html` is a responsive page whose thesis is *a table stays a table* —
one grid at every width, pinned headings, pinned name, columns dropped on a
phone to shorten the journey. Four attempts at anything else failed and there
is a test holding the line (`test_one_table_layout_at_every_width`).

This design does not have a table. A player is a **row**: star, then a name
with an odds pill, the team and fixture under it, and a four-metric strip
(Model · Book · Adj · Edge). Everything else — the opening price, EV, the
read, a sentence explaining the row — is behind a tap, in a **detail sheet**.

It is also not a page. It is an app: a 52px app bar, a scroll area, a
persistent slip bar, a 56px **tab bar** (Board · Combos · Slip · Ladder ·
Model), and a home indicator. Every dropdown is a **bottom sheet**.

So adopting it is an information-architecture change, not a palette swap.

## Tokens

Colour is the same family as v1 — warm paper, the same #1f4fa3 accent — but
renamed and regrouped, and it **has a dark mode**, which v1 explicitly
refuses. Both are declared: `prefers-color-scheme` for the system setting and
`[data-theme]` for an explicit choice, so a toggle can win in both directions.

    Ground   --bg-base #f5f3ee · --bg-surface #ffffff · --bg-elevated #ffffff
             --bg-inset #f7f5f0 · --bg-segment #e9e5dc · --bg-pressed #eeebe4
             --page #e8e5de (behind the phone frame)
    Ink      --ink #16181d · --ink-muted #5e6168 · --ink-faint #6b6e75
    Accent   --accent #1f4fa3 · --on-accent #ffffff · --accent-soft #eef2fa
             --accent-line #b9c8e6
    Meaning  --good #1c6b42 / --good-soft #e3f0e8
             --bad #9e3624 / --bad-soft #f6e4e0
             --warn #7a5410 / --warn-soft #fbefd9 · --star #ad7d09
    Lines    --separator #e3dfd6 · --border #8a8d93 · --border-soft #d6d1c6
    Scrim    --scrim #16181d8c
    Shadow   --shadow-card 0 1px 2px rgba(22,24,29,.06)
             --shadow-bar  0 -1px 0 rgba(22,24,29,.10)
             --shadow-sheet 0 -8px 32px rgba(22,24,29,.18)
    Dark     --bg-base #121211 · --bg-surface #1c1c1a · --bg-elevated #262624
             --ink #f6f4ef · --accent #7fa8f0 / --on-accent #101826
             --good #4fbe85 · --bad #ff8a75 · --warn #e0b05a · --star #e8b838
             --shadow-card none

    Type     --font-sans Schibsted Grotesk · --font-serif Newsreader
             `.num` sets tabular-nums AND font-feature-settings "tnum"
    Space    --space-1..6  4 · 8 · 12 · 16 · 20 · 24
    Radius   --radius-sm 8 · md 12 · lg 16 · xl 22 · pill 999
    Metrics  --tap-target 44 · --control-h 36 · --bar-h 52
             --tabbar-h 56 · --hairline 1

Note the radii are NOT v1's (8/10/12/14/999 becomes 8/12/16/22/999), and the
serif is used only for the brand mark and page titles, at 600.

## Components, and the sizes that matter

    .appbar     52px. Brand (serif 19/22, 600), screen name (15, 600, muted),
                market pill pushed right — a pill, not a menu button.
    .seg        The pool switch. 2px padding, radius-md, 34px buttons, the
                selected one on --bg-surface with --shadow-card.
    .search     44px, --bg-inset, radius-md. The input is 16px, which is the
                size iOS will not zoom into on focus.
    .chiprow    Horizontally scrollable, scrollbar hidden. Chips are 36px
                pills; pressed is --accent-soft with an --accent border.
    .sortbar    Sticky inside the card. "Sorted by" + a sheet trigger in
                accent + a direction pill on the right.
    .row        Star (44) · main · add (44). Name 16/21 600, meta 13/18 muted,
                odds a 22px pill. `.metric__l` is 10px 600 uppercase with
                .07em tracking; `.metric__v` 14/19 600 tabular.
    .badge      22px, radius-sm, 12px 600, with a 6px currentColor dot.
    .btn        44px min, radius-md, 16px 600. --sm is 36px/radius-sm.
    .sheet      Bottom, max-height 82%, radius-xl top corners, a 36×5 grab
                handle, head with a "Done" button, body scrolls.
                Transform translateY with cubic-bezier(.32,.72,0,1) over .28s.
    .slipbar    Above the tab bar: count badge, price 16/21 700, leg surnames
                truncated, an "Open" button.
    .tabbar     56px, five tabs, 11px labels, accent when current, a 17px
                badge on Slip.
    .empty      Centred, 16px title, 15/20 body capped at 30ch, one button.

## What the prototype does not cover

It is anytime TD only. There is no receptions or yardage board, no shortlist
funnel or graded record, no saved parlays, no game breakdown, no "every posted
line" control, and the market sheet lists 2+ TDs as Soon. Those screens exist
in site.html and need a home in this architecture rather than a translation.
