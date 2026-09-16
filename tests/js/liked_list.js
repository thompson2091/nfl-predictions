// What "Guys I like" has to get right, checked without a browser.
//
// The pane is JavaScript inside a generated HTML file, so nothing in the
// Python suite can see it. These are the behaviours that were actually wrong
// at some point while it was written:
//
//   * the two parlay builders shared their legs, because `coverPicker` and
//     `coverToggle` both reached for `S.cover` directly;
//   * a saved player the board no longer carries has to keep its row;
//   * on first TD, two players from one game cannot both score first, so those
//     combinations are impossible rather than merely correlated.
//
// Run by tests/test_liked_list.py, which supplies the payload and the script.
//   node tests/js/liked_list.js <payload.json> <page.js>
const { loadPage, textOf, reporter } = require('./domstub.js');

const { ok, done } = reporter();
const x = loadPage(process.argv[2], process.argv[3],
  ['has', 'S', 'M', 'LIKED_NS', 'LIKED_FAV_NS', 'isLiked', 'isFav',
   'likedList', 'favList']);
const { has, S, M, LIKED_NS, LIKED_FAV_NS, isLiked, isFav, likedList } = x;

// The shell's `render` repaints the whole page from the payload, which needs
// far more of it than any of this does. Counted rather than run: what matters
// here is that a toggle asks for a repaint, not what the repaint draws.
let renders = 0;
globalThis.render = () => { renders++; };

const paneText = () => textOf(paneLiked()).join(' ');

// ── The list ─────────────────────────────────────────────────────────────
const m = M();
ok('empty list points at where players are added',
   /Players/.test(paneText()) && /Shortlist/.test(paneText()));

const pool = (m.players || []).filter(p => has(p.ours) && p.priced);
const picks = [];
const seen = {};
for (const p of pool) { if (!seen[p.game]) { seen[p.game] = 1; picks.push(p.player); } if (picks.length === 3) break; }
picks.forEach(likedToggle);

ok('the list is stored per season, week and market',
   likedKey(LIKED_NS, m) === 'gil:' + m.season + ':' + m.week + ':' + m.key,
   likedKey(LIKED_NS, m));
ok('saved players survive a reload',
   JSON.parse(localStorage.getItem(likedKey(LIKED_NS, m))).length === 3);
const shown = paneText();
ok('every saved player is on the pane', picks.every(n => shown.includes(n)));
ok('adding a player repaints the page', renders >= picks.length, renders + ' repaints');

// ── Stars ────────────────────────────────────────────────────────────────
favToggle(picks[1]);
ok('a star is stored apart from the list', isFav(picks[1]) && !isFav(picks[0]));
ok('starring does not change the list', likedList(m).length === 3);

// ── A player the board no longer carries ─────────────────────────────────
likedToggle('Someone No Longer Listed');
const stale = paneText();
ok('a saved player off the board keeps a labelled row',
   stale.includes('Someone No Longer Listed') && /not on this week/.test(stale));
favToggle('Someone No Longer Listed');
likedToggle('Someone No Longer Listed');
ok('removing a player takes its star with it',
   !isLiked('Someone No Longer Listed') && !isFav('Someone No Longer Listed'));

// ── Combinations ─────────────────────────────────────────────────────────
const cand = picks.map(n => (m.players || []).find(p => p.player === n));
const subs = likedSubsets(cand, false);
ok('every combination of two legs and up is enumerated', subs.length === 4,
   subs.length + ' for 3 players, expected 3 pairs + 1 triple');
ok('a combination multiplies its legs',
   Math.abs(subs.find(s => s.legs === 3).ours
            - cand.reduce((a, p) => a * p.ours, 1)) < 1e-12);

// Two players in one game cannot both score first. Impossible, not correlated.
const byGame = {}; const pair = [];
for (const p of (m.players || []).filter(p => has(p.ours))) {
  if (byGame[p.game]) { pair.push(byGame[p.game], p); break; }
  byGame[p.game] = p;
}
if (pair.length === 2) {
  ok('same-game legs are dropped on first TD', likedSubsets(pair, true).length === 0);
  ok('same-game legs are kept, and flagged, on anytime TD',
     likedSubsets(pair, false).length === 1 && likedSubsets(pair, false)[0].same);
}

// ── The two parlay builders are separate ─────────────────────────────────
// This failed when it was written: both pickers reached for S.cover.
S.cover.picked = null; S.likedCover.picked = null;
paneCover();
paneCover({ state: S.likedCover, pool: r => isLiked(r.player) });
const before = (S.cover.picked || []).slice();
coverToggle(picks[0], S.likedCover);
ok('the Parlay tab keeps its own legs',
   JSON.stringify(before) === JSON.stringify(S.cover.picked),
   JSON.stringify(S.cover.picked));
ok('the list builder only ever offers saved players',
   (S.likedCover.picked || []).every(n => isLiked(n)));

// ── Markets do not share a list ──────────────────────────────────────────
if (DATA.markets.length > 1) {
  const firstCount = likedList(M()).length;
  S.market = 1;
  ok('a second market starts with its own empty list', likedList(M()).length === 0,
     likedKey(LIKED_NS, M()));
  const other = (M().players || []).filter(p => has(p.ours))[0];
  if (other) likedToggle(other.player);
  S.market = 0;
  ok('adding on one market leaves the other alone',
     likedList(M()).length === firstCount);
}

done();
