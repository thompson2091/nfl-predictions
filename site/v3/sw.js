// Pick Six — offline shell. Generated; do not edit.
const CACHE = 'picksix-v3-20260925T213234+0000';
const SHELL = ['./', './index.html', './manifest.webmanifest'];

self.addEventListener('install', e => {
  // `skipWaiting`, so a new week's upload takes over on the next load rather
  // than waiting for every tab to close. The page is a document, not a
  // running session; there is no state to lose.
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  // Same origin only. A cross-origin request from this page would be a bug —
  // the page carries its own fonts and reaches for nothing — and caching one
  // would hide it.
  if (new URL(req.url).origin !== self.location.origin) return;

  e.respondWith((async () => {
    try {
      const fresh = await fetch(req);
      // Only a real answer is worth keeping. A 404 cached under the page's
      // own URL is an app that is broken until someone clears their browser.
      if (fresh && fresh.ok) {
        const c = await caches.open(CACHE);
        c.put(req, fresh.clone());
      }
      return fresh;
    } catch (err) {
      const hit = await caches.match(req);
      if (hit) return hit;
      // A navigation with nothing cached: hand back the shell rather than the
      // browser's offline page, which is how an installed app is supposed to
      // behave when it has never been opened online.
      if (req.mode === 'navigate') {
        const shell = await caches.match('./index.html');
        if (shell) return shell;
      }
      throw err;
    }
  })());
});
