// Every screen of the v4 app, rendered against a stub DOM.
//
// Same reason as `v3app.js`: `node --check` proves the syntax and nothing
// else, and the failure mode of a generated single-page app is a blank screen
// with one line in a console nobody has open.
//
// v4 has a second failure mode v3 does not, and it is the whole subject of
// this file. v4 is v3's bundle plus a block of DUPLICATE declarations —
// `v3Header`, `v3Nav`, `v3Screen`, `v3Load`, `v3Save` — which are legal and
// last-wins. If that mechanism ever stops working, or if v4's block is
// concatenated in the wrong order, the page still parses and still renders:
// it renders v3. A blank screen is loud; the wrong app wearing the right
// stylesheet is not.
//
//   node tests/js/v4app.js <payload.json> <page.js>
const { loadPage, reporter } = require(
  require('path').join(__dirname, 'domstub.js'));

const { ok, done } = reporter();
const x = loadPage(process.argv[2], process.argv[3],
  ['V', 'render', 'v3Screen', 'v3Header', 'v3Nav', 'v3Do', 'DATA', 'has',
   'v4Tabs', 'v4GSec', 'v4FG', 'v4Icons',
   'v4Games', 'v4Game', 'v4GameHead', 'v4AppBar', 'v4Starred',
   'v4Lean', 'v4Spread', 'v4Note', 'v4Icon', 'v4GameCard',
   'v3GameSet', 'v3Weeks', 'rowsFor', 'isFav', 'v3Load', 'v3Save',
   'v4Clicks', 'v4Do', 'v4Sorts',
   'V3TABS', 'V3MKT', 'V3CLICKS']);
const { V, render, v3Screen, v3Nav, DATA, has, v4Tabs, v4GSec, v4FG,
        v4Lean, v4Spread, v4Note, v3GameSet, V3CLICKS } = x;
const V4TABS = v4Tabs(), V4GSEC = v4GSec(), FG = v4FG();

// The whole shell. v4 writes the header into `#appbar`, the screen into
// `#app` and the tabs into `#tabbar`. There is NO `#slipbarHost`: the slip
// is gone, and `render` guards that write with an existence check.
const app = () => ['app', 'appbar', 'tabbar', 'sheet']
  .map(id => (document.getElementById(id) || {}).innerHTML || '').join('\n');
const pane = () => document.getElementById('app').innerHTML;
const bar = () => (document.getElementById('appbar') || {}).innerHTML || '';

// ── the shell ───────────────────────────────────────────────────────────
let err = null;
try { render(); } catch (e) { err = e; }
ok('the shell renders', !err, err && (err.message + '\n' + err.stack));

// THE OVERRIDES WON. Each of these is a thing only v4 emits, so finding it
// proves the duplicate declaration took effect rather than that the page
// happens to look plausible.
ok('v4’s app bar replaced v3’s header',
   bar().indexOf('class="appbar"') >= 0 && bar().indexOf('class="hd"') < 0,
   bar().slice(0, 160));
ok('and v4’s tab bar replaced v3’s nav',
   v3Nav().indexOf('class="tab"') >= 0, v3Nav().slice(0, 120));
ok('the third tab reads Starred, not Picks',
   app().indexOf('>Starred<') >= 0 && app().indexOf('>Picks<') < 0);
ok('and its route key is still v3’s, so saved links resolve',
   app().indexOf('data-v3tab="picks"') >= 0);
ok('storage is under v4’s own key, not v3’s',
   /picksix\.v4/.test(String(x.v3Save)) && !/picksix\.v3/.test(String(x.v3Save)),
   String(x.v3Save).slice(0, 90));

ok('the nav carries every destination',
   V4TABS.every(t => app().indexOf('data-v3tab="' + t[0] + '"') >= 0));
ok('the header names the brand', bar().indexOf(DATA.brand) >= 0, DATA.brand);
ok('the week picker is on the board', bar().indexOf('data-v3week') >= 0);

// NO SLIP BAR ANYWHERE. Asked for directly, and the kind of thing that comes
// back when a screen is restyled from a design that still had one.
ok('there is no slip bar',
   app().indexOf('slipbar') < 0 && app().indexOf('data-v3pick=') < 0,
   'a slip control is on screen');

// ── every tab renders ───────────────────────────────────────────────────
V4TABS.forEach(t => {
  V.tab = t[0]; V.game = null;
  let e = null;
  try { render(); } catch (ex) { e = ex; }
  ok('tab ' + t[0] + ' renders', !e, e && (e.message + '\n' + e.stack));
  ok('tab ' + t[0] + ' is not empty', pane().length > 80, String(pane().length));
});

// ── the games list ──────────────────────────────────────────────────────
V.tab = 'games'; V.game = null; V.gfilter = 'all'; render();
const cards = v3GameSet().cards || [];
ok('the games list exercised real cards', cards.length > 0, String(cards.length));
ok('every game on the board is openable',
   cards.every(c => pane().indexOf('data-v3game="' + c.game_id + '"') >= 0));
ok('the five-column header names all three estimates',
   ['Win chance', 'Spread', 'Model', 'Book', 'Adj']
     .every(h => pane().indexOf('>' + h + '<') >= 0));
// THE DAY HEADING COMES FROM THE CARD, so it cannot disagree with the time
// printed on the row under it.
ok('games are grouped under the day the card names',
   cards.every(c => !c.kick_day
     || pane().indexOf(String(c.kick_day).toUpperCase()) >= 0));
ok('the 21+ line is on the landing screen',
   pane().indexOf('1-800-GAMBLER') >= 0);

// EVERY FILTER, and the count on each chip is the count it filters to.
['all', 'flip', 'diff', 'agree'].forEach(f => {
  V.gfilter = f;
  let e = null;
  try { render(); } catch (ex) { e = ex; }
  ok('filter ' + f + ' renders', !e, e && e.message);
  // THE COUNT ON SCREEN IS THE COUNT IT FILTERED TO, on every filter and
  // not just the one that shows everything. The first version let three of
  // the four pass on `|| f !== 'all'`, which is a check that reports a pass
  // for not having looked.
  const n = cards.filter(FG[f]).length;
  ok('filter ' + f + ' shows ' + n + ' of ' + cards.length,
     pane().indexOf('>' + n + ' of ' + cards.length + '<') >= 0,
     'pane says neither');
  // And an empty filter says so rather than drawing a bare heading.
  if (!n) ok('filter ' + f + ' says it is empty',
             pane().indexOf('No game this week reads that way') >= 0);
});
V.gfilter = 'all';

// THE FOUR BUCKETS PARTITION THE BOARD. `diff` is the union of flip and the
// genuine disagreements, so flip + agree + the rest has to come back to the
// whole: a filter that drops a game silently is a board that lies about how
// often the model disagrees.
const nFlip = cards.filter(FG.flip).length;
const nAgree = cards.filter(FG.agree).length;
const nDiff = cards.filter(FG.diff).length;
const nNone = cards.filter(c => v4Lean(c)[1] === 'none').length;
ok('the lean buckets account for every game',
   nFlip + nAgree + nNone + (nDiff - nFlip) === cards.length,
   nFlip + '+' + nAgree + '+' + nNone + '+' + (nDiff - nFlip)
     + ' vs ' + cards.length);

// A PICK'EM IS NOT A HALF-POINT LINE.
ok('a pick’em prints as PK', v4Spread(0) === 'PK', v4Spread(0));
ok('a favorite keeps its minus sign',
   v4Spread(-6.5) === '−6.5', v4Spread(-6.5));
ok('an underdog keeps its plus', v4Spread(3) === '+3.0', v4Spread(3));
ok('a missing spread is a dash', v4Spread(null) === '—', v4Spread(null));

// EVERY ROW IS THE SAME SIDE'S NUMBER. The away row has to be 1 - home on
// all three estimates, or a reader cannot tell whose chance a cell is.
const withP = cards.filter(c => has(c.win_home) && has(c.model_win_home))[0];
if (withP) {
  const html = x.v4GameCard(withP);
  const pc = v => Math.round(v * 100) + '%';
  ok('the away row reads the away side’s model chance',
     html.indexOf('>' + pc(1 - withP.model_win_home) + '<') >= 0,
     pc(1 - withP.model_win_home));
  ok('and the home row reads the home side’s',
     html.indexOf('>' + pc(withP.model_win_home) + '<') >= 0,
     pc(withP.model_win_home));
  ok('and the book’s number is on the card too',
     html.indexOf('>' + pc(withP.win_home) + '<') >= 0);
} else {
  ok('a card carries both win probabilities', false, 'no card to check');
}

// ── the three estimate columns order the list ───────────────────────────
V.game = null; V.tab = 'games'; V.gfilter = 'all';
V.gsort = null; V.gsortdesc = true; render();
ok('the header offers a sort on every estimate',
   x.v4Sorts().every(s => bar().indexOf('data-v4gsort') >= 0
     || pane().indexOf('data-v4gsort="' + s[0] + '"') >= 0),
   pane().slice(pane().indexOf('gl__hd'), pane().indexOf('gl__hd') + 400));
ok('and no column is pressed before one is chosen',
   pane().indexOf('aria-pressed="true"') < 0
   || pane().indexOf('data-v4gsort') < 0
   || !/data-v4gsort="[a-z]+" aria-pressed="true"/.test(pane()));
ok('kickoff order keeps the day headings',
   pane().indexOf('class="gl__day"') >= 0);

// EVERY COLUMN, AND THE ORDER IT CLAIMS IS THE ORDER ON SCREEN.
const pos = gid2 => pane().indexOf('data-v3game="' + gid2 + '"');
x.v4Sorts().forEach(srt => {
  V.gsort = srt[0]; V.gsortdesc = true;
  let e = null;
  try { render(); } catch (ex) { e = ex; }
  ok('sorted by ' + srt[0] + ' renders', !e, e && e.message);
  ok('sorted by ' + srt[0] + ' names the order',
     pane().indexOf('Ordered by ' + srt[1] + ', highest first') >= 0);
  ok('sorted by ' + srt[0] + ' drops the day headings',
     pane().indexOf('class="gl__day"') < 0);
  ok('sorted by ' + srt[0] + ' offers the way back',
     pane().indexOf('data-v4gsort=""') >= 0);
  // The scalar is read off the card, so the order on screen is checkable
  // against it rather than against a second copy of the same sort.
  const vals = cards.filter(c => has(srt[2](c)))
    .map(c => ({ g: c.game_id, v: srt[2](c) }))
    .sort((a, b) => b.v - a.v);
  if (vals.length > 1) {
    const ok1 = pos(vals[0].g) >= 0 && pos(vals[vals.length - 1].g) >= 0
      && pos(vals[0].g) < pos(vals[vals.length - 1].g);
    ok('sorted by ' + srt[0] + ': the strongest is above the weakest', ok1,
       vals[0].g + '@' + pos(vals[0].g) + ' vs '
         + vals[vals.length - 1].g + '@' + pos(vals[vals.length - 1].g));
  }
  // And reversing it reverses the page.
  V.gsortdesc = false; render();
  ok('sorted by ' + srt[0] + ' reversed says so',
     pane().indexOf('Ordered by ' + srt[1] + ', lowest first') >= 0);
  if (vals.length > 1) {
    ok('sorted by ' + srt[0] + ' reversed puts the weakest above',
       pos(vals[vals.length - 1].g) < pos(vals[0].g));
  }
});

// A NULL IS NOT THE SMALLEST AND NOT THE BIGGEST. Both directions.
V.gsort = 'spread'; V.gsortdesc = true; render();
ok('every game is still on the board when sorted',
   cards.every(c => pos(c.game_id) >= 0));

// THE WAY BACK CLEARS THE SORT. It used to carry the active column's own
// key, which read as a third tap and reversed the order instead.
V.gsort = 'model'; V.gsortdesc = true;
x.v4Do('v4gsort', '');
ok('the way back clears the sort rather than reversing it',
   V.gsort == null && V.gsortdesc === true,
   String(V.gsort) + '/' + String(V.gsortdesc));
// And a third tap on the same column does the same thing.
x.v4Do('v4gsort', 'book');
x.v4Do('v4gsort', 'book');
ok('a second tap reverses', V.gsort === 'book' && V.gsortdesc === false);
x.v4Do('v4gsort', 'book');
ok('and a third clears', V.gsort == null);
V.gsort = null; V.gsortdesc = true; render();

// ── the card's content fills the card ───────────────────────────────────
//
// A `<button>` wraps its children in an anonymous content box that does not
// stretch, so without one wrapper of its own every row inside sat at its
// intrinsic width and the numbers bunched left of their column header.
ok('the card wraps its rows in one full-width box',
   x.v4GameCard(cards[0]).indexOf('<span class="gc__in">') >= 0,
   x.v4GameCard(cards[0]).slice(0, 120));
ok('and closes it', /<\/span><\/span><\/button>$/.test(x.v4GameCard(cards[0])),
   x.v4GameCard(cards[0]).slice(-60));

// ── one game, all four sections ─────────────────────────────────────────
const gid = (cards[0] || {}).game_id;
ok('there is a game to open', !!gid, String(gid));
V.game = gid; V.tab = 'games';
V4GSEC.forEach(sec => {
  V.gameTab = sec[0];
  let e = null;
  try { render(); } catch (ex) { e = ex; }
  ok('game section ' + sec[0] + ' renders', !e, e && (e.message + '\n' + e.stack));
  ok('game section ' + sec[0] + ' is not empty',
     pane().length > 80, String(pane().length));
  // The header carries the nav, so the section you are on is marked there.
  ok('game section ' + sec[0] + ' is marked current in the header',
     bar().indexOf('data-v3gtab="' + sec[0] + '" aria-current="page"') >= 0,
     bar().slice(0, 200));
});

// THE DARK HEADER REPLACES THE APP BAR INSIDE A GAME, and carries the way out.
V.gameTab = 'odds'; render();
ok('inside a game the header goes dark',
   bar().indexOf('class="ghead"') >= 0 && bar().indexOf('class="appbar"') < 0);
ok('and carries a way back out', bar().indexOf('data-v3back="1"') >= 0);
ok('and names the fixture',
   bar().indexOf((cards[0] || {}).away) >= 0
   && bar().indexOf((cards[0] || {}).home) >= 0);
ok('the week picker is not offered inside a game',
   bar().indexOf('data-v3week') < 0);

// ── every key the markup uses is one the delegation handles ─────────────
//
// A `data-v4*` attribute would render, look right and do nothing on tap:
// `V3CLICKS` is the list the click handler walks, and a key missing from it
// is a dead control. Checked across every screen rather than by reading the
// source, because the point is what the page emits.
V.game = null;
const seen = {};
V4TABS.forEach(t => {
  V.tab = t[0]; render();
  const html = app();
  let m;
  const re = /data-(v[0-9][a-z]+)=/g;
  while ((m = re.exec(html)) !== null) seen[m[1]] = true;
});
V.game = gid; V.tab = 'games';
V4GSEC.forEach(s => {
  V.gameTab = s[0]; render();
  let m;
  const re = /data-(v[0-9][a-z]+)=/g;
  const html = app();
  while ((m = re.exec(html)) !== null) seen[m[1]] = true;
});
// v4 adds a SECOND delegation for its own keys, because `V3CLICKS` is a
// const in v3's bundle and cannot be extended. Both lists count.
const live = V3CLICKS.concat(x.v4Clicks()).concat(['v3week']);
const dead = Object.keys(seen).filter(k => live.indexOf(k) < 0);
ok('every data key on screen is one a delegation handles',
   dead.length === 0, dead.join(', '));
ok('and v4 contributed at least one of its own',
   Object.keys(seen).some(k => x.v4Clicks().indexOf(k) >= 0),
   Object.keys(seen).join(','));

// ── the note under the totals is a fact about the week ──────────────────
ok('a short week is named on the card',
   v4Note({ away: 'TB', home: 'DAL', away_is_short_week: 1,
            home_is_short_week: 1 }) === 'Both on a short week',
   v4Note({ away: 'TB', home: 'DAL', away_is_short_week: 1,
            home_is_short_week: 1 }));
ok('and one team on a short week is named by itself',
   v4Note({ away: 'TB', home: 'DAL', away_is_short_week: 1 })
     === 'TB on a short week');
ok('a bye is carried too',
   v4Note({ away: 'TB', home: 'DAL', home_is_off_bye: 1 })
     === 'DAL off a bye');
ok('and an ordinary week says nothing',
   v4Note({ away: 'TB', home: 'DAL' }) === '');

done();
