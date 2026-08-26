// sw.js — Minimal shell cache for the installed control room.
//
// Scope is deliberately tiny: precache nothing, cache only same-origin GETs for
// built assets, and NEVER touch /api or /ws. Project state must always come from
// the server — a cached queue or scorecard would be a lie about a live system.
const CACHE = 'alc-shell-v1'

self.addEventListener('activate', (event) => {
  // Drop older shell caches so a redeploy cannot serve a stale bundle forever.
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url)
  const isShellAsset =
    event.request.method === 'GET' &&
    url.origin === self.location.origin &&
    url.pathname.startsWith('/assets/')

  if (!isShellAsset) return // /api, /ws and everything else: straight to the network

  event.respondWith(
    caches.match(event.request).then(
      (hit) =>
        hit ??
        fetch(event.request).then((response) => {
          const copy = response.clone()
          caches.open(CACHE).then((cache) => cache.put(event.request, copy))
          return response
        }),
    ),
  )
})
