// Enough of a browser to render the dashboard's panes into, and no more.
//
// The page builds its DOM through `el()` — createElement, appendChild,
// textContent, innerHTML — so a node needs those and little else. Shared by
// every JS harness here so the two cannot drift into stubbing different
// browsers.
const fs = require('fs');

const store = new Map();
const nodes = {};

function mkNode(tag) {
  const n = {
    tagName: tag, children: [], _text: '', _html: '', attrs: {},
    className: '', style: {}, dataset: {}, value: '', checked: false,
    classList: {
      add(c) { n.className += (n.className ? ' ' : '') + c; },
      contains(c) { return n.className.split(/\s+/).includes(c); },
    },
    setAttribute(k, v) { n.attrs[k] = v; },
    getAttribute(k) { return k in n.attrs ? n.attrs[k] : null; },
    // A scroll pane's position, which the page both reads and writes. A plain
    // number is enough: nothing here lays anything out, so the only question
    // a harness can ask is whether the page put back what it took.
    scrollTop: 0, scrollHeight: 0, clientHeight: 0,
    // Only the attribute form, and only over this node's own subtree. Enough
    // for `[data-pane]`, which is what the page looks for; anything more
    // would be stubbing a selector engine.
    querySelectorAll(sel) {
      const m = /^\[([a-z-]+)\]$/.exec(sel);
      if (!m) return [];
      const out = [];
      (function walk(x) {
        if (!x) return;
        if (x.attrs && x.attrs[m[1]] != null) out.push(x);
        (x.children || []).forEach(walk);
      })(n);
      return out;
    },
    appendChild(c) { n.children.push(c); return c; },
    get textContent() { return n._text; }, set textContent(v) { n._text = v; },
    get innerHTML() { return n._html; },
    // Clearing a node's HTML clears its children, which is the whole reason
    // the page does it. A stub that kept them made `#root` accumulate every
    // render on top of the last one.
    set innerHTML(v) { n._html = v; if (!v) n.children = []; },
  };
  return n;
}

function install() {
  for (const k of Object.keys(nodes)) delete nodes[k];
  globalThis.localStorage = {
    getItem: k => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: k => store.delete(k),
  };
  globalThis.document = {
    createElement: mkNode,
    // SVG nodes go through a namespaced constructor and are otherwise the
    // same shape as anything else here. Without this an icon throws and takes
    // the whole pane down, which is a stub gap reported as a page bug.
    createElementNS: (ns, tag) => mkNode(tag),
    createTextNode: t => ({ _text: t, children: [] }),
    addEventListener() {},
    // Attributes that are actually kept. They used to be discarded, which
    // made every `data-` flag the page sets on the root — the slip state, the
    // nav state — unobservable, so a harness could not tell a page that set
    // them from one that did not.
    documentElement: (() => {
      const a = {};
      return {
        attrs: a,
        style: { props: {}, setProperty(k, v) { this.props[k] = v; },
                 getPropertyValue(k) { return this.props[k] || ''; } },
        getAttribute: k => (k in a ? a[k] : null),
        setAttribute(k, v) { a[k] = String(v); },
        removeAttribute(k) { delete a[k]; },
      };
    })(),
    // The same node for the same selector, because the page believes it is
    // addressing the same element every time — `$('#root')` is a place it
    // clears and refills, not a new div each call. Handing back a fresh one
    // hid a whole class of bug: a test could not see what `render` had built,
    // so an assertion about the rendered tree passed against a `render` that
    // built nothing.
    querySelector: sel => (nodes[sel] || (nodes[sel] = mkNode('div'))),
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
