// pwa.ts — Install the service worker that makes the control room an app.
//
// The worker caches ONLY the built shell (hashed, immutable assets). It must
// never cache /api: the backend already marks those `Cache-Control: no-store`
// because a stale response would let the control room misreport project state —
// the one thing it can never do.
export function registerServiceWorker(): void {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return
  // Registration is best-effort: a failure must not keep the UI from loading.
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {})
  })
}

