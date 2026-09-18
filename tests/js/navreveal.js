// The nav gets out of the way going down, and comes back coming up.
//
// Two pinned bars cost about 150px of a 700px phone before the browser takes
// its own share, and when it does it is the topmost layer that loses — an
// address bar at the top of the window sits exactly where a pinned nav is. So
// only the filter bar is pinned and the header slides.
//
//   node tests/js/navreveal.js <payload.json> <page.js>
const { loadPage, reporter } = require('/Users/mthompson/projects/personal/nfl-predictions/tests/js/domstub.js');

const { ok, done } = reporter();
const x = loadPage(process.argv[2], process.argv[3],
  ['S', 'navScrolled', 'render', 'NAV_AFTER', 'NAV_STEP']);
const { S, navScrolled, render, NAV_AFTER, NAV_STEP } = x;

const state = () => document.documentElement.getAttribute('data-nav');

// ── Down the board ──────────────────────────────────────────────────────
navScrolled('board', 0);
ok('at the top, the nav is there', state() !== 'away');
navScrolled('board', 40);
ok('a little way down it is still there',
   state() !== 'away', 'hiding at 40px makes the nav flicker on every nudge');
navScrolled('board', NAV_AFTER + 200);
ok('well down the board it is out of the way', state() === 'away');

// ── And back ────────────────────────────────────────────────────────────
navScrolled('board', NAV_AFTER + 100);
ok('any upward movement brings it back', state() === 'here');
navScrolled('board', NAV_AFTER + 300);
ok('going down again puts it away', state() === 'away');
navScrolled('board', 0);
ok('and the top always shows it', state() === 'here');

// ── A thumb resting on glass is not a scroll ────────────────────────────
navScrolled('board', 400);
ok('setup: away', state() === 'away');
navScrolled('board', 400 - (NAV_STEP - 1));
ok('a sub-threshold twitch does not flap it', state() === 'away',
   'a header that reappears on every pixel of jitter is worse than one that '
   + 'never moves');

// ── Two scrollers do not read each other's positions ────────────────────
// The distinguishing case needs the OTHER scroller to be further down than
// the one moving. The first version of this had the pane at 900 and the
// window at 0, which both arrangements answer the same way — it passed
// against a single shared previous-position, which is the bug it names.
//
// So: the window is well down the page, and a pane starts scrolling from the
// top. Compared with where the PANE was, that is a move down past the
// threshold and the nav goes. Compared with where the WINDOW was, it is a
// four-hundred-pixel move up, and the nav comes back.
navScrolled('window', 0);
navScrolled('window', 500);
ok('setup: the window is well down', state() === 'away');
navScrolled('freshpane', 100);
ok('each scroller is compared with where IT was', state() === 'away',
   'one shared previous-position reads this as a jump upward and reveals');

// ── Changing what you are looking at starts over ────────────────────────
// Further down than the pane already was: 900 after 950 is an upward move and
// would reveal the nav, which is the code being right and the setup being
// wrong. It caught me once.
navScrolled('board', 1400);
ok('setup: away', state() === 'away');
S.route = 'week';
render();
ok('a filter or market change shows the nav again', state() === 'here',
   'you are at the top of something new');

done();
