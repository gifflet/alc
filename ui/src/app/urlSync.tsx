// urlSync.tsx — One-way binding between the tab store and the project URL.
//
// The bug this guards against is a navigation ping-pong: hydrating the store FROM
// the URL while also pushing the store TO the URL creates a feedback loop. The
// rule here is strict:
//   1. Hydration runs ONCE per project (keyed on id), reading the URL at mount.
//   2. After that, store -> URL PUSHES a history entry per navigation, and
//      URL -> store runs ONLY on a pop (back/forward): `pendingRef` records
//      each path this component itself pushed, so the location change caused by
//      our own navigate() is swallowed and never re-hydrates the store. A
//      genuine pop reaches the store, the store then matches the URL, and the
//      push side no-ops — a fixed point, not a loop.
//
// Why PUSH and not the old `replace: true`: with replace, the app's whole life
// happened inside ONE history entry — the URL was always right, but Android's
// back gesture had nowhere to go except out of the app. Opening a run from the
// Runs list and swiping back CLOSED the page instead of returning to the list.
// With real entries, system back walks the app's own navigation — detail to
// list to the view before it — and only past the beginning does it leave, which
// is what back means everywhere else on the phone. Desktop gets meaningful
// browser back/forward from the same mechanism; the sheet/More popstate handler
// in OperatorShell still consumes a pop first, so overlays keep closing before
// the stack moves.
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { uiStore, useUiState } from './uiStore'
import { openArgFromPath, pathForTab } from './tabRoute'

/** The path segments after /projects/:id, from the live browser location. */
function splatSegments(id: string): string[] {
  const prefix = `/projects/${id}`
  const path = window.location.pathname
  const rest = path.startsWith(prefix) ? path.slice(prefix.length) : ''
  return rest.split('/').filter(Boolean)
}

/**
 * Reset + hydrate the tab store from the URL once per project. Returns whether
 * hydration for `id` has run — the gate UrlSync waits on before it navigates.
 */
export function useUrlHydration(id: string): boolean {
  const [hydratedId, setHydratedId] = useState<string | null>(null)
  useEffect(() => {
    uiStore.reset()
    uiStore.openTab(openArgFromPath(splatSegments(id)) ?? openArgFromPath([])!)
    setHydratedId(id)
  }, [id])
  return hydratedId === id
}

/** Two-way binding: store -> URL as pushed history entries, URL -> store on pop. */
export function UrlSync({ id, hydrated }: { id: string; hydrated: boolean }) {
  const { tabs, activeTabId } = useUiState()
  const navigate = useNavigate()
  const location = useLocation()
  // Paths whose location change is OURS (a navigate below), not a pop. A list,
  // not a single slot: two store updates can land before the router delivers
  // the first location change.
  const pendingRef = useRef<string[]>([])
  // The first sync after hydration may normalise the URL (an unknown path
  // hydrates to the dashboard); that correction must not mint a history entry
  // the back gesture would then step through.
  const firstSyncRef = useRef(true)

  // POP side first, then PUSH. The order matters on the popstate commit: this
  // effect updates the store synchronously, and the push effect below reads
  // the store LIVE (uiStore.getState(), not the render's captured values) — so
  // even when the router's changing `navigate` identity re-triggers the push
  // effect on that same commit, it sees the already-reconciled store and
  // no-ops instead of shoving the just-left path back onto the stack.
  useEffect(() => {
    if (!hydrated) return
    const pending = pendingRef.current.indexOf(location.pathname)
    if (pending !== -1) {
      pendingRef.current.splice(0, pending + 1)
      return // our own push arriving — not a pop
    }
    // A pop (or forward): the URL is now the source of truth. openTab dedupes
    // by target id, so revisiting a tab focuses it instead of duplicating.
    const arg = openArgFromPath(splatSegments(id))
    if (arg) uiStore.openTab(arg)
  }, [hydrated, id, location.pathname])

  useEffect(() => {
    if (!hydrated) return
    // Live store, live location: this effect's DEPENDENCIES say when to look,
    // but what it compares must be the present, not the render that scheduled
    // it.
    const state = uiStore.getState()
    const active = state.tabs.find((t) => t.id === state.activeTabId)
    if (!active) return
    const path = pathForTab(id, active.target)
    if (path !== window.location.pathname) {
      pendingRef.current.push(path)
      navigate(path, { replace: firstSyncRef.current })
    }
    firstSyncRef.current = false
  }, [hydrated, id, tabs, activeTabId, navigate])

  return null
}
