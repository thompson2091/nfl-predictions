// Enough of a browser to render the dashboard's panes into, and no more.
//
// The page builds its DOM through `el()` — createElement, appendChild,
// textContent, innerHTML — so a node needs those and little else. Shared by
// every JS harness here so the two cannot drift into stubbing different
// browsers.
const fs = require('fs');

const store = new Map();

function mkNode(tag) {
  const n = {
    tagName: tag, children: [], _text: '', _html: '', attrs: {},
    className: '', style: {}, dataset: {}, value: '', checked: false,
    classList: {
      add(c) { n.className += (n.className ? ' ' : '') + c; },
      contains(c) { return n.className.split(/\s+/).includes(c); },
    },
    setAttribute(k, v) { n.attrs[k] = v; },
    appendChild(c) { n.children.push(c); return c; },
    get textContent() { return n._text; }, set textContent(v) { n._text = v; },
    get innerHTML() { return n._html; }, set innerHTML(v) { n._html = v; },
  };
  return n;
}

function install() {
  globalThis.localStorage = {
    getItem: k => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: k => store.delete(k),
  };
  globalThis.document = {
    createElement: mkNode,
    createTextNode: t => ({ _text: t, children: [] }),
    addEventListener() {},
    documentElement: {
      getAttribute: () => null, setAttribute() {}, removeAttribute() {},
    },
    querySelector: () => mkNode('div'),
    querySelectorAll: () => [],
    activeElement: null,
  };
  globalThis.window = globalThis;
  globalThis.scrollTo = () => {};
  globalThis.scrollX = 0; globalThis.scrollY = 0;
  globalThis.setTimeout = globalThis.setTimeout || (fn => fn());
}

/** Evaluate the page script and hand back the helpers it keeps to itself.
 *
 * `const` at a script's top level is not a global, so anything declared that
 * way is unreachable from here unless the script is asked to export it.
 */
function loadPage(payloadPath, pagePath, names) {
  install();
  globalThis.DATA = JSON.parse(fs.readFileSync(payloadPath, 'utf8'));
  const js = fs.readFileSync(pagePath, 'utf8')
    + '\nglobalThis.__x = { ' + names.join(', ') + ' };';
  (0, eval)(js);
  return globalThis.__x;
}

/** Every piece of text a rendered node tree would show. */
function textOf(n, out) {
  out = out || [];
  if (!n) return out;
  if (n._text) out.push(n._text);
  if (n._html) out.push(String(n._html).replace(/<[^>]*>/g, ''));
  (n.children || []).forEach(c => textOf(c, out));
  return out;
}

function reporter() {
  const state = { failures: 0 };
  return {
    ok(what, cond, detail) {
      if (!cond) {
        state.failures++;
        console.log('FAIL  ' + what + (detail ? '  — ' + detail : ''));
      } else console.log('ok    ' + what);
    },
    done() {
      console.log(state.failures ? '\n' + state.failures + ' failed'
                                 : '\nall passed');
      process.exit(state.failures ? 1 : 0);
    },
  };
}

module.exports = { mkNode, install, loadPage, textOf, reporter };
