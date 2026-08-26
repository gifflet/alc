// token.ts — Hold the API token this browser was handed.
//
// `alc ui --token T` prints a one-time URL (…/?t=T). The SPA takes the token out
// of the query string, stores it, and IMMEDIATELY rewrites the address bar so
// the secret does not sit in browser history, in a bookmark, or in whatever the
// operator pastes into a chat when asking for help.
//
// With no token configured server-side nothing here ever runs: reads return null
// and the client simply sends no header, which is the unauthenticated default.

const STORAGE_KEY = 'alc-ui:token'
/** The query parameter `alc ui` prints in its one-time URL. */
export const TOKEN_PARAM = 't'

function storage(): Storage | null {
  try {
    return window.localStorage
  } catch {
    return null // private mode / blocked storage — degrade to in-memory only
  }
}

let memoryToken: string | null = null

/** The token to present, or null when this browser has none. */
export function getToken(): string | null {
  if (memoryToken) return memoryToken
  try {
    return storage()?.getItem(STORAGE_KEY) ?? null
  } catch {
    return null
  }
}

export function setToken(token: string | null): void {
  memoryToken = token
  try {
    if (token) storage()?.setItem(STORAGE_KEY, token)
    else storage()?.removeItem(STORAGE_KEY)
  } catch {
    // Storage unavailable: the in-memory copy still serves this session.
  }
}

export function clearToken(): void {
  setToken(null)
}

/**
 * Extract `?t=…` from a URL, returning the token and the URL with it removed.
 *
 * Pure so the stripping is unit-tested without touching window.history — the
 * property that matters (the secret leaves the address bar) is asserted on the
 * returned string.
 */
export function extractToken(href: string): { token: string | null; cleaned: string } {
  let url: URL
  try {
    url = new URL(href)
  } catch {
    return { token: null, cleaned: href }
  }
  const token = url.searchParams.get(TOKEN_PARAM)
  if (!token) return { token: null, cleaned: href }
  url.searchParams.delete(TOKEN_PARAM)
  // Drop a now-empty '?' so the cleaned URL is what the operator would type.
  const cleaned = url.pathname + (url.searchParams.toString() ? `?${url.searchParams}` : '') + url.hash
  return { token, cleaned }
}

/**
 * Consume a token handed in the current URL, then scrub it from the address bar.
 *
 * Called once at startup, before the first render, so the token is available to
 * the very first request and never renders into a shareable URL.
 */
export function adoptTokenFromUrl(): void {
  const { token, cleaned } = extractToken(window.location.href)
  if (!token) return
  setToken(token)
  window.history.replaceState(null, '', cleaned)
}
