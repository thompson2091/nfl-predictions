// Enough of a browser to render the dashboard's panes into, and no more.
//
// The page builds its DOM through `el()` — createElement, appendChild,
// textContent, innerHTML — so a node needs those and little else. Shared by
// every JS harness here so the two cannot drift into stubbing different
// browsers.
const fs = require('fs');

const store = new Map();
const nodes = {};
const docListeners = {};

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
    // GEOMETRY, only where a test installs it. Nothing here lays anything
    // out, so a node reports no box by default — but a page that measures a
    // STICKY element cannot be checked without one: a stuck bar reports the
    // pane's top edge, not its place in the document, and code that confuses
    // the two is correct at the top of a page and a no-op everywhere else.
    // A test sets `_rect` to a function of the pane's `scrollTop` and gets
    // exactly that distinction; leaving it unset keeps the old behavior.
    _rect: null,
    getBoundingClientRect() {
      return n._rect ? n._rect()
                     : { top: 0, left: 0, bottom: 0, right: 0,
                         width: 0, height: 0 };
    },
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
  for (const k of Object.keys(docListeners)) delete docListeners[k];
  // Fire what the page registered on `document`, the way a browser would.
  globalThis.fireDoc = (type, event) => {
    const fns = docListeners[type] || [];
    fns.forEach(fn => fn(event));
    return fns.length > 0;
  };
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
    // Recorded rather than swallowed. The page delegates every click to one
    // document listener, so a harness that cannot fire that listener can only
    // check that a button was DRAWN — which is how six controls shipped
    // correct, unreachable, and green.
    addEventListener(type, fn) { (docListeners[type] || (docListeners[type] = [])).push(fn); },
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
    // Same memoisation, same reason: the page addresses `#scroll` and
    // `#tabbar` as places it clears and refills, not as new divs each call.
    getElementById: id => (nodes['#' + id] || (nodes['#' + id] = mkNode('div'))),
    querySelectorAll: () => [],
    activeElement: null,
  };
  globalThis.window = globalThis;
  // Window-level listeners, recorded like the document's.
  const winListeners = {};
  globalThis.addEventListener = (type, fn) =>
    (winListeners[type] || (winListeners[type] = [])).push(fn);
  globalThis.fireWin = (type, event) =>
    (winListeners[type] || []).forEach(fn => fn(event));
  // A hash that routes when it is set, which is the only thing `go()` does
  // and the only reason the page has a router at all.
  let hash = '';
  globalThis.location = {
    get hash() { return hash; },
    set hash(v) { hash = v; globalThis.fireWin('hashchange', {}); },
  };
  // A history stack that actually stacks, so a page using `pushState` for
  // the back gesture can be exercised rather than merely not crashed.
  const stack = [];
  globalThis.history = {
    get length() { return stack.length; },
    get state() { return stack.length ? stack[stack.length - 1].state : null; },
    pushState(state, _t, url) { stack.push({ state, url }); hash = url || hash; },
    replaceState(state, _t, url) {
      if (stack.length) stack[stack.length - 1] = { state, url };
      else stack.push({ state, url });
      hash = url || hash;
    },
    back() {
      if (stack.length < 2) return;
      stack.pop();
      const top = stack[stack.length - 1];
      hash = top.url || hash;
      globalThis.fireWin('popstate', { state: top.state });
    },
  };
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
