"""site/v4 — the Hashmark app, built by overriding v3's four chrome builders.

**v4 DOES NOT FORK v3's RENDER LOOP, AND THAT IS THE DESIGN.**

`v3js.render` is 120 lines of scroll restoration, focus preservation, history
pushing and sticky-bar measurement, every line of it written against a bug
that shipped. Forking it to change the markup would mean reproducing all of
that against an app nobody has read yet. So v4 leaves it alone and redeclares
only what it fills:

    v3Header()   -> the Hashmark app bar, or the game screen's dark header
    v3Nav()      -> five tabs, Starred where v3 has Picks
    v3Screen()   -> the route

A duplicate `function` declaration in one script is legal and the last one
wins, which is the same mechanism `v3.py` already relies on to shadow v1's
`JS_SHELL`. The event delegation, `v3Do`, the sheet, the week picker and every
`data-v3*` key are untouched, so a tap does in v4 exactly what it does in v3.

**THE TAB KEYS STAY v3's.** `V.tab` is still `games|props|picks|angles|record`
even though the third tab now reads "Starred". Renaming it would mean
rewriting `v3Do`, `v3Weeks` and `v3Push` — and `v3Push` is what puts the tab
in the URL, so a rename would also break every link anyone has saved. The
label is what the design changed; the key is a route.

**AND THE BET SLIP IS GONE.** Asked for directly: "i dont want a bet slip
anymore". v4's shell has no `slipbarHost`, so `render` skips it without this
module having to return an empty string for it. `v3Picks` — saved parlays —
is therefore unreachable in v4, and the third tab is the starred list
instead.

Phase A covers the games column: the list and the game screen's four
sections. The other three tabs still render v3's builders, already wearing
Hashmark tokens because `v4css` keeps v3's class vocabulary.
"""
from __future__ import annotations

from src.export.v3js import js as v3_js

#: Stored under its own key, because v3 and v4 are the same origin.
#:
#: v3 is served from `/` and v4 from `/v4/`, which is one origin and one
#: `localStorage`. Sharing `picksix.v3` would mean v4 writing a `V.tab` of
#: `starred` into the store v3 reads, and v3 landing on a tab it has no
#: screen for. `v3Load` and `v3Save` are function declarations, so these
#: hoist over v3's — including over the `const V = ... v3Load()` initializer,
#: which runs after hoisting and therefore reads v4's key.
V4KEY = "picksix.v4"

OVERRIDES = r"""
// ── storage, under v4's own key ─────────────────────────────────────────
//
// Hoisted over v3's declarations. See the module docstring: one origin, two
// apps, and a tab key v3 cannot render.
function v3Load() {
  try { return JSON.parse(localStorage.getItem('__V4KEY__') || '{}'); }
  catch (e) { return {}; }
}
function v3Save() {
  try {
    localStorage.setItem('__V4KEY__', JSON.stringify({
      market: V.market, sort: V.sort, filter: V.filter,
      game: V.game, desc: V.desc, gfilter: V.gfilter, gbasis: V.gbasis,
      saved: V.saved, savedFilter: V.savedFilter,
      gsort: V.gsort, gsortdesc: V.gsortdesc,
      lodds: V.lodds, rungs: V.rungs }));
  } catch (e) { /* private window, blocked storage — the app still works */ }
}

// ── EVERYTHING IN THIS BLOCK IS A FUNCTION, AND THAT IS NOT A STYLE ─────
//
// v3's bundle ENDS WITH `render()`, at module scope. v4's block is appended
// after it, so v4's code runs for the first time BEFORE its own module body
// has been evaluated. Function declarations are hoisted and survive that;
// `const` and `let` sit in the temporal dead zone and throw.
//
// Found by `tests/js/v4app.js` on the first run: `ReferenceError: Cannot
// access 'V4ICONS' before initialization`, thrown from `v4Icon` inside the
// boot render. An uncaught throw at module scope abandons the rest of the
// script, so the page would have been blank with the tokens loaded — which
// is the one failure this version is most exposed to.
//
// The rule, asserted by `test_the_override_block_declares_only_functions`:
// a table v4 needs becomes a function that returns it. Rebuilding a small
// object literal per call costs nothing a render can measure.
//
// ── icons ───────────────────────────────────────────────────────────────
//
// Stroke paths, drawn at the size they are used at. Inline rather than a
// sprite sheet because the page is one file and a sprite would be one more
// thing that can 404; `currentColor` is what lets the tab bar light a tab by
// changing one property.
function v4Icons() {
  return {
  games: 'M4 5h16v15H4zM4 10h16M9 3v4M15 3v4',
  props: 'M12 11a3.5 3.5 0 100-7 3.5 3.5 0 000 7zM5 21c0-3.9 3.1-6 7-6s7 2.1 7 6',
  star: 'M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z',
  angles: 'M4 19h16M4 19l5-7 4 3 6-9',
  record: 'M4 4h16v16H4zM8 8h8M8 12h8M8 16h5',
  search: 'M20 20l-3.5-3.5',
  ask: 'M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-5A8 8 0 1 1 21 12z',
  person: 'M4 21c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5',
  chevdown: 'm6 9 6 6 6-6',
  chevleft: 'm15 18-6-6 6-6',
  arrow: 'M5 12h14M13 6l6 6-6 6',
  };
}

// Search and the profile glyph each need a circle the path cannot draw.
function v4Circles() {
  return {
    search: '<circle cx="11" cy="11" r="7"></circle>',
    person: '<circle cx="12" cy="8" r="4"></circle>',
  };
}

function v4Icon(key, size) {
  const d = v4Icons()[key];
  if (!d) return '';
  const extra = v4Circles()[key] || '';
  return '<svg width="' + size + '" height="' + size + '" '
    + 'viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    + 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    + extra + '<path d="' + d + '"></path></svg>';
}

// ── the five tabs ───────────────────────────────────────────────────────
//
// "Starred" over v3's "Picks": `picks` was the saved-parlay list and the slip
// it was fed from is gone. The route key is still `picks` — see the module
// docstring.
function v4Tabs() {
  return [
    ['games', 'Games', 'games'],
    ['props', 'Props', 'props'],
    ['picks', 'Starred', 'star'],
    ['angles', 'Angles', 'angles'],
    ['record', 'Record', 'record'],
  ];
}

function v3Nav() {
  return v4Tabs().map(t => {
    const on = V.tab === t[0] && !V.game;
    return '<button class="tab" data-v3tab="' + t[0] + '"'
      + (on ? ' aria-current="page"' : '') + '>'
      + v4Icon(t[2], 24) + esc(t[1]) + '</button>';
  }).join('');
}

// ── the app bar ─────────────────────────────────────────────────────────
//
// TWO HEADERS, ONE SLOT. Everywhere but inside a game this is a wordmark and
// a row of 44px targets on the ground color. Inside a game it is the dark
// header with the fixture, the Ask button and the section nav — which is
// where the design puts the game's own navigation, so it rides with the
// chrome rather than scrolling away with the content.
function v3Header() {
  return V.game ? v4GameHead(V.game) : v4AppBar();
}

function v4AppBar() {
  const weeks = v3Weeks();
  const label = V.week != null ? 'Week ' + V.week
    : 'Week ' + (DATA.week || '');
  // The picker is a native select behind the pill: a phone renders it as a
  // full-height wheel, which is a better control than anything drawn here,
  // and `data-v3week` is the key v3's change handler already listens for.
  const opts = ['<option value="">This week</option>'].concat(
    weeks.map(w => '<option value="' + w + '"'
      + (V.week === w ? ' selected' : '') + '>Week ' + w + '</option>'))
    .join('');
  const wk = weeks.length
    ? '<span class="pillbtn' + (V.week != null ? ' pillbtn--past' : '') + '">'
      + '<select data-v3week aria-label="Which week to show">' + opts
      + '</select>' + v4Icon('chevdown', 14) + '</span>'
    : '<span class="pillbtn" style="border:0;background:transparent">'
      + esc(label) + '</span>';
  return '<div class="appbar">'
    + '<span class="brand">' + esc(DATA.brand || 'Pick Six') + '</span>'
    + '<span class="bargroup">' + wk
    // Search, Ask and Settings are Phase E. They are drawn now rather than
    // later because the bar's height is what every screen below it is laid
    // out against, and adding a 44px row to it afterwards would move every
    // one of them. Disabled rather than absent: a target that does nothing
    // and says so is honest, where a bar that grows later is a redesign.
    + '<button class="iconbtn" disabled aria-label="Search — not built yet">'
    + v4Icon('search', 19) + '</button>'
    + '<button class="iconbtn" disabled aria-label="Ask — not built yet">'
    + v4Icon('ask', 19) + '</button>'
    + '<button class="iconbtn" disabled aria-label="Settings — not built yet">'
    + v4Icon('person', 19) + '</button>'
    + '</span></div>';
}

//: The game screen's four sections, and the v3 builder each one calls.
//:
//: The keys are v3's `V.gameTab` values, unchanged, so `v3Do`'s `v3gtab`
//: handler needs no edit and a link into a section still resolves.
function v4GSec() {
  return [
    ['odds', 'Odds'],
    ['players', 'Props'],
    ['edge', 'Matchup'],
    ['angles', 'Angles'],
  ];
}

function v4GameHead(gid) {
  const c = (v3GameSet().cards || []).filter(x => x.game_id === gid)[0];
  const name = c
    ? esc(c.away) + ' <i>@</i> ' + esc(c.home)
    : esc(String(gid).replace('_', ' @ '));
  const sec = V.gameTab || 'odds';
  return '<div class="ghead">'
    + '<div class="ghead__t">'
    + '<button class="iconbtn" data-v3back="1" aria-label="'
    + (V.backTab === 'angles' ? 'Back to the angles board' : 'Back to all games')
    + '">' + v4Icon('chevleft', 20) + '</button>'
    + '<span class="ghead__n">' + name + '</span>'
    // Phase E. Drawn and disabled for the same reason the app bar's are.
    + '<button class="gocta" disabled aria-label="Ask about this game — '
    + 'not built yet">Ask' + v4Icon('arrow', 14) + '</button>'
    + '</div>'
    + '<nav class="gnav" aria-label="Game sections">'
    + v4GSec().map(s => '<button data-v3gtab="' + s[0] + '"'
        + (sec === s[0] ? ' aria-current="page"' : '') + '>'
        + esc(s[1]) + '</button>').join('')
    + '</nav></div>';
}

// ── v4's own click keys ─────────────────────────────────────────────────
//
// `V3CLICKS` is a `const` in v3's bundle and v4 cannot extend it — see the
// module docstring on why nothing here is a `const` either. So v4 registers
// a SECOND document listener for its own keys. Additive, not a replacement:
// v3's walker finds no match on a `data-v4*` node and falls through to the
// body without acting, and v4's does the same for every v3 key.
function v4Clicks() {
  return ['v4gsort'];
}

function v4Do(kind, v) {
  switch (kind) {
    // WHICH COLUMN THE GAMES LIST IS ORDERED BY, and tapping the active one
    // reverses it. Tapping it a third time clears the sort and goes back to
    // kickoff order, because a reader who has sorted by Model has no other
    // way back to the one ordering that groups by day.
    case 'v4gsort':
      // An EMPTY value clears it, which is what the "Back to kickoff order"
      // button sends. Reusing the active column's own key there read as a
      // third tap and reversed the sort instead of clearing it — a button
      // doing the opposite of what it says.
      if (!v) { V.gsort = null; V.gsortdesc = true; }
      else if (V.gsort !== v) { V.gsort = v; V.gsortdesc = true; }
      else if (V.gsortdesc) { V.gsortdesc = false; }
      else { V.gsort = null; V.gsortdesc = true; }
      V.top = 'section';
      break;
    default: return;
  }
  v3Save();
  render();
}

document.addEventListener('click', ev => {
  let node = ev.target;
  const keys = v4Clicks();
  while (node && node !== document.body) {
    for (let i = 0; i < keys.length; i++) {
      const v = node.getAttribute && node.getAttribute('data-' + keys[i]);
      if (v != null) { ev.preventDefault(); v4Do(keys[i], v); return; }
    }
    node = node.parentNode;
  }
});

// ── the route ───────────────────────────────────────────────────────────
//
// Phase A owns Games and the game screen. The other three tabs still call
// v3's builders: they render in Hashmark already, because `v4css` keeps v3's
// class vocabulary and only swaps the token block under it. Each is replaced
// in its own phase, and until then the app is whole rather than half-built.
function v3Screen() {
  switch (V.tab) {
    case 'props': return v3Week();          // phase B
    case 'picks': return v4Starred();       // phase C
    case 'angles': return v3AnglesPage();   // phase C
    case 'record': return v3RecordPage();   // phase D
    default: return V.game ? v4Game(V.game) : v4Games();
  }
}

// THE SLIP IS GONE, SO THE TAB IT FED IS NOT THE SAVED-PARLAY LIST.
//
// Phase C builds the starred board properly. Until then this says what the
// tab is for rather than rendering `v3Picks`, which explains how to use a
// slip bar that no longer exists — a screen giving instructions for a
// removed feature is worse than one admitting it is unfinished.
function v4Starred() {
  const n = (rowsFor(V.market, null) || []).filter(r => isFav(r.id)).length;
  return '<div class="wrap"><h1 class="h1">Starred</h1>'
    + '<p class="lede">Tap the star on any player to keep them here. '
    + (n ? 'You have ' + n + ' starred on the '
        + esc((V3MKT.filter(m => m[0] === V.market)[0] || [])[1]
              || 'current') + ' board.'
        : 'Nothing starred yet.')
    + '</p>'
    + '<div class="card"><p class="help">This board is still being built. '
    + 'The starred list, the price each pick was starred at and the alert '
    + 'when it moves all land together.</p></div></div>';
}

// ── screen: games ───────────────────────────────────────────────────────

//: How the model's number is read against the book's, and the four filters
//: that follow from it. LIFTED FROM v3 RATHER THAN REWRITTEN: the threshold,
//: the tie-breaking and the "by more / closer game" wording were all argued
//: out there, including the bug where the tag came from the sign of
//: `model_spread` while the percentage came from `model_win_home` and the two
//: disagreed on a near-pick'em. The design draws the same four buckets.
function v4Lean(c) {
  const haveP = has(c.win_home) && has(c.model_win_home);
  if (!haveP && (!has(c.spread) || !has(c.model_spread))) return ['', 'none'];
  if (haveP) {
    const d = (c.model_win_home - c.win_home) * 100;
    if ((c.win_home >= 0.5) !== (c.model_win_home >= 0.5))
      return ['Model picks ' + (c.model_win_home >= 0.5 ? c.home : c.away),
              'flip'];
    if (Math.abs(d) < 3) return ['Model agrees', 'agree'];
    const towardFav = (c.win_home >= 0.5) ? d > 0 : d < 0;
    return [towardFav ? 'Model: by more' : 'Model: closer game', 'diff'];
  }
  const d = c.model_spread - c.spread;
  if ((c.spread < 0) !== (c.model_spread < 0))
    return ['Model picks the other side', 'flip'];
  if (Math.abs(d) < 1) return ['Model agrees', 'agree'];
  return [Math.abs(c.model_spread) < Math.abs(c.spread)
    ? 'Model: closer game' : 'Model: by more', 'diff'];
}

function v4FG() {
  return {
    all: () => true,
    flip: c => v4Lean(c)[1] === 'flip',
    diff: c => v4Lean(c)[1] !== 'agree' && v4Lean(c)[1] !== 'none',
    agree: c => v4Lean(c)[1] === 'agree',
  };
}

//: A spread, printed the way a book prints one. `PK` rather than `0.0`,
//: because a pick'em is not a half-point line and nobody writes it as one.
function v4Spread(v) {
  if (!has(v)) return '\u2014';
  if (v === 0) return 'PK';
  return (v > 0 ? '+' : '\u2212') + Math.abs(v).toFixed(1);
}

function v4Pct0(p) { return has(p) ? Math.round(p * 100) + '%' : '\u2014'; }
function v4Tot(v) { return has(v) ? Number(v).toFixed(1) : '\u2014'; }

//: What is unusual about this fixture, in the order a reader cares.
//:
//: Read off the card's own flags rather than written per game. Rest is the
//: one thing on a card that is a FACT about the week rather than a model
//: output, which is why it earns a slot beside the totals.
function v4Note(c) {
  const bits = [];
  if (c.away_is_short_week && c.home_is_short_week) bits.push('Both on a short week');
  else if (c.away_is_short_week) bits.push(esc(c.away) + ' on a short week');
  else if (c.home_is_short_week) bits.push(esc(c.home) + ' on a short week');
  if (c.away_is_off_bye) bits.push(esc(c.away) + ' off a bye');
  if (c.home_is_off_bye) bits.push(esc(c.home) + ' off a bye');
  return bits.join(' \u00b7 ');
}

//: One game, as five columns over two rows.
//:
//: EVERY ROW IS THE SAME SIDE'S NUMBER. Win chance, model, book and adjusted
//: all read "this team's chance", so the away row is `1 - home` on all three
//: and the reader never has to work out whose number a cell is. That is the
//: whole reason the design puts the team name in the first column.
function v4GameCard(c) {
  const lean = v4Lean(c);
  const adj = v3AdjWin(c);
  const mH = c.model_win_home, bH = c.win_home;
  // Which side the MODEL likes, which is the column the design emphasises.
  const aLead = has(mH) && mH < 0.5, hLead = has(mH) && mH >= 0.5;
  const side = (nm, sp, model, book, ad, lead) =>
    '<span class="gc__team">' + esc(nm) + '</span>'
    + '<span class="gc__n">' + v4Spread(sp) + '</span>'
    + '<span class="gc__n' + (lead ? ' gc__n--lead' : '') + '">'
    + v4Pct0(model) + '</span>'
    + '<span class="gc__n gc__n--mut">' + v4Pct0(book) + '</span>'
    + '<span class="gc__n">' + v4Pct0(ad) + '</span>';
  const flip = v => has(v) ? 1 - v : null;
  const bl = c.blend || {};
  const note = v4Note(c);
  return '<button class="gc" data-v3game="' + esc(c.game_id) + '">'
    // ONE WRAPPER INSIDE THE BUTTON. A `<button>` puts its children in an
    // anonymous content box that does not stretch to the button's width, so
    // every row sat at its own intrinsic width and the numbers bunched left
    // of the column header above them. v3's card is an `<a>` and the
    // design's is an `<a>`, which is why neither has this problem — and why
    // this one keeps the button: a card you open with the keyboard has to
    // answer Enter and Space, and an anchor with no href answers neither.
    + '<span class="gc__in">'
    + '<span class="gc__t">'
    + '<span class="num" style="font-size:11px;color:var(--mut)">'
    + esc(v3Kick(c)) + '</span>'
    + (lean[0]
       ? '<span class="tag' + (lean[1] === 'flip' ? ' tag--warn'
           : lean[1] === 'diff' ? ' tag--ours' : '') + '">'
         + esc(lean[0]) + '</span>'
       : '')
    + '</span>'
    + '<span class="gc__g">'
    + side(c.away, has(c.spread) ? -c.spread : null,
           flip(mH), flip(bH), flip(adj), aLead)
    + side(c.home, c.spread, mH, bH, adj, hLead)
    + '</span>'
    + '<span class="gc__f">'
    + '<span>Total \u00b7 M ' + v4Tot(c.model_total) + ' \u00b7 B '
    + v4Tot(c.total) + ' \u00b7 A ' + v4Tot(bl.total) + '</span>'
    + '<span>' + note + '</span>'
    + '</span></span></button>';
}

//: The orderings the games list offers, and the scalar each one reads.
//:
//: EVERY ONE IS THE FAVORITE'S NUMBER, NOT THE HOME SIDE'S. A card carries
//: two teams and a column holds one figure per team, so "sort by Model" has
//: to pick a scalar — and the home side's chance is the wrong one: it would
//: put every game with a strong road favorite at the bottom of a list a
//: reader asked for the strongest leans. `max(p, 1 - p)` is "how sure is
//: this number", which is the question a reader sorting by it is asking.
//:
//: Spread sorts on the absolute line for the same reason.
function v4Sorts() {
  return [
    ['spread', 'Spread', c => has(c.spread) ? Math.abs(c.spread) : null],
    ['model', 'Model', c => has(c.model_win_home)
      ? Math.max(c.model_win_home, 1 - c.model_win_home) : null],
    ['book', 'Book', c => has(c.win_home)
      ? Math.max(c.win_home, 1 - c.win_home) : null],
    ['adj', 'Adj', c => {
      const a = v3AdjWin(c);
      return has(a) ? Math.max(a, 1 - a) : null;
    }],
  ];
}

function v4Games() {
  const g = v3GameSet();
  const cards = g.cards || [];
  if (!cards.length) {
    return '<div class="wrap">' + v3PastBanner() + '<h1 class="h1">Games</h1>'
      + '<div class="card"><p class="lede">'
      + (g.absent
         ? 'No game lines were archived for week ' + V.week + '.'
         : 'No game lines have been captured for this week yet. The board is '
           + 'built from an odds archive, and until it runs there is nothing '
           + 'here to show.')
      + '</p></div></div>';
  }
  const cur = V.gfilter || 'all';
  const chips = [['all', 'All'], ['flip', 'Model picks other side'],
                 ['diff', 'Model differs'], ['agree', 'Model agrees']]
    .map(f => {
      const n = cards.filter(v4FG()[f[0]]).length;
      return '<button class="chip" data-v3gfilter="' + f[0] + '" '
        + 'aria-pressed="' + (cur === f[0]) + '"'
        + (n ? '' : ' disabled') + '>'
        + esc(f[1]) + '<i>' + n + '</i></button>';
    }).join('');
  const show = cards.filter(v4FG()[cur] || v4FG().all);

  // THE THREE ESTIMATE COLUMNS ARE THE SORT CONTROL, and the header says so
  // before it is tapped.
  const sorts = v4Sorts();
  const active = sorts.filter(s => s[0] === V.gsort)[0];
  const heads = sorts.map(s => {
    const on = V.gsort === s[0];
    return '<b class="' + (s[0] === 'model' ? 'm' : '') + '" '
      + 'data-v4gsort="' + s[0] + '" aria-pressed="' + on + '" '
      + 'aria-label="Order by ' + esc(s[1])
      + (on ? (V.gsortdesc ? ', high first' : ', low first') : '') + '">'
      + esc(s[1]) + '<i>' + (on ? (V.gsortdesc ? '\u25bc' : '\u25b2')
                                : '\u25bc') + '</i></b>';
  }).join('');

  // GROUPED BY THE DAY THE CARD ITSELF NAMES, in kickoff order — UNTIL A
  // COLUMN IS SORTED BY, and then not at all.
  //
  // `kick_day` is the card's own label and `kick_sort` is its sortable
  // timestamp, so the grouping cannot disagree with the time printed on each
  // row. Days are taken in the order they first appear rather than from a
  // fixed Thu/Sun/Mon list: an international window, a Saturday in December
  // and a Friday after Thanksgiving are all real and none of them is in that
  // list.
  //
  // A sort and the day headings cannot both be true. Ordering by Model and
  // keeping the headings would print THURSDAY over a Sunday game, or scatter
  // one day's games down the page under five headings. So a sorted list is
  // one flat list — every row still carries its own kickoff — and the bar
  // under it names the order and offers the way back.
  let order = [];
  const byDay = {};
  if (active) {
    const get = active[2];
    // `sort` puts a before b when the comparator is NEGATIVE, so descending
    // — biggest first — has to return a POSITIVE number when a is smaller.
    // Written the other way round first, and `gsortdesc` sorted ascending on
    // every column; two of the four happened to tie on the fixture and
    // passed, which is what the ordering assertion against the card's own
    // scalar is for.
    const dir = V.gsortdesc ? 1 : -1;
    byDay[''] = show.slice().sort((a, b) => {
      const x = get(a), y = get(b);
      // Nulls last in BOTH directions, the rule v3's board sort already
      // uses: a game with no line is not the biggest favorite and it is not
      // the smallest either.
      if (!has(x) && !has(y)) return 0;
      if (!has(x)) return 1;
      if (!has(y)) return -1;
      return x === y ? 0 : (x < y ? dir : -dir);
    });
    order = [''];
  } else {
    const sorted = show.slice().sort((a, b) =>
      String(a.kick_sort || '') < String(b.kick_sort || '') ? -1 : 1);
    sorted.forEach(c => {
      const d = c.kick_day || '';
      if (!byDay[d]) { byDay[d] = []; order.push(d); }
      byDay[d].push(c);
    });
  }

  return '<div class="wrap gl">' + v3PastBanner()
    + '<div style="display:flex;align-items:baseline;'
    + 'justify-content:space-between">'
    + '<h1 class="h1">Games</h1>'
    + '<span class="num" style="font-size:12px;color:var(--mut)">'
    + show.length + ' of ' + cards.length + '</span></div>'
    + '<div class="chips" style="margin-top:12px">' + chips + '</div>'
    + '<div class="gl__hd" style="margin-top:12px">'
    + '<span>Win chance</span>' + heads + '</div>'
    + '<div class="gl__games" style="display:flex;flex-direction:column;'
    + 'gap:8px;margin-top:8px">'
    + (show.length
       ? order.map(d => (d ? '<span class="gl__day">'
             + esc(d.toUpperCase()) + '</span>' : '')
           + byDay[d].map(v4GameCard).join('')).join('')
       : '<div class="empty">No game this week reads that way.</div>')
    + '</div>'
    // THE ORDER, NAMED, UNDER THE LIST. The header is outside the scrolling
    // pane, so three games down the only thing on screen is an ordering with
    // nothing saying what it is.
    + (active
       ? '<div class="gl__by"><span>Ordered by ' + esc(active[1]) + ', '
         + (V.gsortdesc ? 'highest first' : 'lowest first')
         + ' \u00b7 days not shown</span>'
         + '<button data-v4gsort="">Back to kickoff order</button></div>'
       : '')
    // THE 21+ LINE IS NOT DECORATION AND IT IS NOT A FOOTER EITHER.
    //
    // It sits at the end of the one screen everybody lands on, which is
    // where a reader who has just been handed a board of prices is most
    // likely to read it. "Information, not a sportsbook" is the accurate
    // claim: nothing here takes a bet.
    + '<div class="legal"><b>21+</b>Information, not a sportsbook \u00b7 '
    + '1-800-GAMBLER</div>'
    + '</div>';
}

// ── screen: one game ────────────────────────────────────────────────────
//
// The chrome — back, the fixture, Ask and the section nav — is in the header
// (see `v4GameHead`), so this is the section body alone. The four section
// builders are v3's, unchanged: `v3GameOdds` carries the projection table,
// the ladders and the score distribution, `v3GamePlayers` the in-game prop
// board, `v3GameMatchup` the unit-by-unit comparison and `v3Angles` the
// game's splits. Each is long and each is tested.
function v4Game(gid) {
  const c = (v3GameSet().cards || []).filter(x => x.game_id === gid)[0];
  if (!c) {
    return '<div class="wrap"><div class="card">'
      + 'That game is not on this week\u2019s board.</div></div>';
  }
  const sec = V.gameTab || 'odds';
  return '<div class="wrap">'
    + (sec === 'players' ? v3GamePlayers(gid)
     : sec === 'edge' ? v3GameMatchup(c)
     : sec === 'angles' ? v3Angles(c)
     : v3GameOdds(c, gid))
    + '</div>';
}
"""


def js() -> str:
    """v3's JavaScript, then v4's overrides. Order is the whole mechanism."""
    return v3_js() + "\n" + OVERRIDES.replace("__V4KEY__", V4KEY)
