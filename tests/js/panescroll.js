// Pressing `+` does not send you back to the top of the board.
//
// The page re-renders on every state change, which rebuilds the table from
// nothing — so the pane that was scrolled to row two hundred came back scrolled
// to row one, and the act of acknowledging a tap threw away what the tap was
// part of. Two things have to survive it: how far down the pane was, and how
// many rows had been drawn to get there. Restoring the first without the second
// scrolls to a position that no longer exists.
//
//   node tests/js/panescroll.js <payload.json> <page.js>
const { loadPage, reporter } = require('/Users/mthompson/projects/personal/nfl-predictions/tests/js/domstub.js');

const { ok, done } = reporter();
const x = loadPage(process.argv[2], process.argv[3],
  ['S', 'table', 'render', 'rowsFor', 'toggleFav', 'CHUNK_ROWS', 'restorePanes']);
const { S, table, render, rowsFor, toggleFav, CHUNK_ROWS, restorePanes } = x;

const many = [];
for (let i = 0; i < CHUNK_ROWS * 4; i++)
  many.push({ id: 'r' + i, player: 'Player ' + i, ours: i / 1000 });
const cols = [{ w: '100px', label: 'Who', mob: 'title',
                cell: (d, r) => { d.textContent = r.player; } }];
const build = () => table(cols, many, null, { id: 'probe' });

// ── A screenful, not the whole board ────────────────────────────────────
S.pane = {};
let t = build();
const first = t.children.filter(c => c.className.indexOf('row') >= 0).length;
ok('the first draw is one screenful, not ' + many.length,
   first === CHUNK_ROWS, 'drew ' + first);

// ── Scrolling asks for more, without rebuilding anything ────────────────
t.scrollHeight = 4000; t.clientHeight = 600; t.scrollTop = 3500;
t.onscroll();
const after = t.children.filter(c => c.className.indexOf('row') >= 0).length;
ok('scrolling near the bottom draws the next chunk in place',
   after === CHUNK_ROWS * 2, 'drew ' + after);
ok('and the pane remembers where it was', S.pane.probe.top === 3500);
ok('and how much it had drawn', S.pane.probe.drawn === CHUNK_ROWS * 2);

// ── Rebuilt while still working on it ───────────────────────────────────
t = build();
const redrawn = t.children.filter(c => c.className.indexOf('row') >= 0).length;
ok('a rebuild redraws as far as you had got',
   redrawn === CHUNK_ROWS * 2,
   'drew ' + redrawn + ' — a position at row ' + CHUNK_ROWS * 2
   + ' cannot be restored onto ' + redrawn + ' rows');

// ── What render does with it ────────────────────────────────────────────
// Starring a player passes `keepFocus`, so the position is kept. That is the
// tap the complaint was about: it jumped to the top of the list.
S.route = 'week';
const row = rowsFor(S.market, 'all')[0];
S.pane = { probe: { top: 3500, drawn: CHUNK_ROWS * 2 } };
toggleFav(row.id);
ok('starring a player keeps the pane where it was',
   S.pane.probe && S.pane.probe.top === 3500);

// Changing a filter gives you different rows, and a position in those means
// nothing — so that one starts at the top, on purpose.
S.pane = { probe: { top: 3500, drawn: CHUNK_ROWS * 2 } };
render();
ok('changing a filter starts at the top again',
   !S.pane.probe, 'a scroll position in a different set of rows is not a place');

// ── And `render` is what puts it back ───────────────────────────────────
// Through `render`, not by calling `restorePanes` directly: the first version
// of this called it directly, so removing the call from `render` left the
// page broken and the test green. Falsified by doing exactly that.
S.route = 'week';
S.market = 'any';
S.fw.view = 'all';
render();                                   // a clean tree with a real pane
const root = document.querySelector('#root');
const panes = root.querySelectorAll('[data-pane]');
ok('the board renders a pane render can find', panes.length > 0);
if (panes.length) {
  const board = panes[0];
  const id = board.getAttribute('data-pane');
  S.pane[id] = { top: 880, drawn: CHUNK_ROWS };
  render(true);
  const after = document.querySelector('#root').querySelectorAll('[data-pane]')[0];
  ok('and render puts the position back onto it', after.scrollTop === 880,
     'scrollTop came back ' + after.scrollTop);
}

done();
