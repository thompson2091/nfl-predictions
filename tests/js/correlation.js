// The page's same-game correction, run on inputs the Python side also runs.
//
// Two implementations of one number is this project's cardinal sin. The JS
// has to exist — the slip recomputes as legs are added — so the guard is that
// both are fed the same card and the same legs and must agree.
//
//   node tests/js/correlation.js <payload.json> <page.js> <legs.json>
const fs = require('fs');
const path = require('path');
const { loadPage } = require(path.join(__dirname, 'domstub.js'));

const x = loadPage(process.argv[2], process.argv[3],
  ['V', 'DATA', 'v3Correlation', 'v3JointOne', 'v3Cond', 'V3BANDS', 'V3FLIP',
   'betProb', 'v3Key', 'v3Same', 'v3GameSet']);
const spec = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'));
x.V.week = null;
const r = x.v3JointOne(spec.gid, spec.legs);
process.stdout.write(JSON.stringify(r === null ? { lift: null } : r));
