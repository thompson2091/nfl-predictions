// The over/under shortlist, rendered.
//
// The rule is fitted and graded in Python; what this checks is the half that
// can only go wrong on the page — that the view shows the lines the rule took
// rather than the lines the board leads with, that it names a side, and that
// the number on the control is the number of rows underneath it.
//
//   node tests/js/oushortlist.js <payload.json> <page.js>
const { loadPage, textOf, reporter } = require('./domstub.js');

const { ok, done } = reporter();
const x = loadPage(process.argv[2], process.argv[3],
  ['S', 'rowsFor', 'marketOf', 'oneTake', 'oneLine', 'ouShortKeys', 'ouKey',
   'pageWeek', 'el', 'has']);
const { S, rowsFor, marketOf, oneTake, oneLine, ouShortKeys, ouKey, pageWeek, has } = x;
const txt = n => textOf(n).join(' ');

// ── Rushing yards: the rule took two lines, neither of them the consensus ──
S.market = 'rush';
S.route = 'week';
const m = marketOf('rush');
const all = rowsFor('rush', 'all');
const short = rowsFor('rush', 'short');

ok('the payload carries a fitted rule', !!(m.shortlist && m.shortlist.floors));
ok('the shortlist is the lines the rule took, not the whole board',
   short.length === 2 && all.length > short.length,
   'got ' + short.length + ' of ' + all.length);
ok('every shortlisted row names the side the rule took',
   short.every(r => r.take === 'over'), JSON.stringify(short.map(r => r.take)));
ok('and carries how far we sat from the price',
   short.every(r => has(r.takeGap)));

// The bug this fixture exists for. 54.5 is the consensus line and the rule did
// not take it; 51.5 and 58.5 are what it took. Narrowed with `oneLine`, both
// are dropped and Alpha Back leaves a shortlist that still counts him.
const viaOneLine = oneLine(short, {});
ok('`oneLine` would empty this shortlist', viaOneLine.length === 0,
   'got ' + viaOneLine.length + ' — the fixture no longer tests the bug');
const shown = oneTake(short);
ok('`oneTake` keeps the player, once', shown.length === 1);
ok('and keeps his biggest disagreement', shown[0].line === 51.5,
   'kept ' + shown[0].line);

// ── The page renders, and its count is the count on screen ──────────────
S.fw.view = 'short';
S.fw.allLines = false;
let page = null, err = null;
try { page = pageWeek(); } catch (e) { err = e; }
ok('the shortlist view renders', !err, err && (err.message + '\n' + err.stack));
if (page) {
  const t = txt(page);
  ok('the board shows the player the rule picked', t.indexOf('Alpha Back') >= 0);
  ok('the control counts the LINES the rule took', t.indexOf('Shortlist · 2') >= 0,
     'the segmented control must agree with the funnel');
  ok('the funnel says both numbers', t.indexOf('2 lines on 1 players') >= 0, t.slice(0, 300));
  // The honest headline. A point estimate on its own would read as a claim the
  // measurement does not make.
  ok('the graded figure carries its interval', t.indexOf('95% interval') >= 0);
  ok('and says so when that interval spans zero', t.indexOf('spans zero') >= 0);
  ok('the rule is described by its fitted band, not a typed one',
     t.indexOf('2 to 5 points on the over') >= 0, t.slice(0, 400));
}

// ── Expanded, both lines come back ──────────────────────────────────────
S.fw.allLines = true;
const wide = txt(pageWeek());
ok('expanded, the board shows both lines the rule took',
   wide.indexOf('51.5') >= 0 && wide.indexOf('58.5') >= 0, wide.slice(0, 400));
ok('and stops saying it is hiding any',
   wide.indexOf('lines on 1 players') < 0, wide.slice(0, 400));
S.fw.allLines = false;
const narrow = txt(pageWeek());
ok('collapsed, only the biggest disagreement is on screen',
   narrow.indexOf('51.5') >= 0 && narrow.indexOf('58.5') < 0, narrow.slice(0, 400));

// ── Receptions: a market whose floors differ per side ───────────────────
S.market = 'rec';
S.fw.view = 'short';
S.fw.allLines = false;
const rec = rowsFor('rec', 'short');
ok('receptions carries its own rule', rec.length === 1 && rec[0].take === 'over');
let rp = null; err = null;
try { rp = pageWeek(); } catch (e) { err = e; }
ok('and its shortlist renders', !err, err && err.message);
if (rp) ok('naming both fitted bands',
  txt(rp).indexOf('0 to 2 points on the over') >= 0
  && txt(rp).indexOf('2 to 5 points on the under') >= 0, txt(rp).slice(0, 400));

// ── A touchdown board is untouched ──────────────────────────────────────
S.market = 'any';
S.fw.view = 'short';
let td = null; err = null;
try { td = pageWeek(); } catch (e) { err = e; }
ok('the touchdown shortlist still renders through its own path', !err,
   err && err.message);
if (td) ok('and still offers Fades, which a two-sided market has no use for',
  txt(td).indexOf('Fades') >= 0);

done();
