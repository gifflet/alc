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

/**
 * Ask for notification permission.
 *
 * Called only from an explicit operator action (the Inbox opt-in), never on
 * load: a permission prompt the user did not ask for is denied by reflex, and a
 * denial is sticky.
 */
export async function requestNotificationPermission(): Promise<NotificationPermission> {
  if (typeof Notification === 'undefined') return 'denied'
  if (Notification.permission !== 'default') return Notification.permission
  return Notification.requestPermission()
}

/** Whether this browser will show notifications right now. */
export function canNotify(): boolean {
  return typeof Notification !== 'undefined' && Notification.permission === 'granted'
}
