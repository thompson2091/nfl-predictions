# The site.html design

Seven artboards, exported from the Claude design canvas as one self-extracting
`Design.html` and unpacked here. The original is a bundle three layers deep —
base64 of gzip of a JSON manifest, whose `template` field is a JSON-encoded
string — so these are the readable form and the one to edit or diff against.

    page-01  This week      the main board, market menu, game chips, slip
    page-02  Game breakdown  one fixture, drive-level
    page-03  Shortlist       funnel, star, ours-vs-book bar, best price, slip
    page-04  Saved parlays   cards, status dots, filters, settle summary
    page-05  Ladder          the roll-it-forward calculator
    page-06  Who scores      the mobile view
    page-07  Model           accuracy by season, and what each feature is worth

Each is a `.dc.html`: markup with `{{binding}}` placeholders, `sc-for` and
`sc-if` for repetition and branching, and a `DCLogic` class at the bottom whose
`renderVals()` returns the bindings. The sample data in `renderVals` is real
Week 2 output where it could be and invented where it could not — the Saved
parlays are all invented, as are the rushing-yards rows.

## The design system, read off the artboards

Type      Schibsted Grotesk for everything, Newsreader (serif) for the brand
          and page titles. `font-variant-numeric: tabular-nums` on the body,
          which is what stops a column of percentages from jittering.
Ground    #F5F3EE page, #FFFFFF cards, #F7F5F0 inset panels
Ink       #16181D text, #5E6168 and #6B6E75 muted, #8A8D93 faintest
Lines     #E3DFD6 borders, #ECE8E0 and #F0EDE6 inside cards
Ours      #1F4FA3 — the model's bar, and every link
Good      #1C6B42 text, #E3F0E8 fill, #BFD9C8 border, #1C7A4A dot
Bad       #9E3624 text, #F6E4E0 fill, #B3402F dot
Star      #D9A21B fill on #B8860B stroke
Radii     8 nav · 10 controls · 12 menus · 14 cards · 999 pills
Frame     1440 wide, 64px header, 360px right aside, 40px page gutter
Targets   44px minimum on anything clickable, including the star and the ×

The one thing the artboards carry that a screenshot would not is the *copy*.
"Nothing survives every filter this week — that's an answer, not a gap" and
"We rate them below the price. You can't bet against them at a book, but
they're worth keeping off a parlay" are load-bearing, and they are why the
empty states here say something rather than apologising.

## What the artboards are not

`SquaresPro` is the design template's placeholder name, not a decision.

The market menu lists Rushing yards as available and Receiving/Passing yards as
Soon. Only Anytime TD, First TD and Receptions have models behind them today,
and Receptions loses to the market on every week measured — see
`src/prediction/receptions.py`. A market the menu offers and the pipeline
cannot serve is worse than one it does not list.
