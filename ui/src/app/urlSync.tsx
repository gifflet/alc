// urlSync.tsx — One-way binding between the tab store and the project URL.
//
// The bug this guards against is a navigation ping-pong: hydrating the store FROM
// the URL while also pushing the store TO the URL creates a feedback loop. The
// rule here is strict:
//   1. Hydration runs ONCE per project (keyed on id), reading the URL at mount.
//   2. After that the flow is store -> URL only; UrlSync never navigates until
//      hydration for the current id has completed (the `hydrated` gate), so it
//      can't fire on the empty/stale store that exists before hydration.
import { useEffect, useState } from 'react'
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

/** Reflect the active tab in the URL. No-op until hydration has run. */
export function UrlSync({ id, hydrated }: { id: string; hydrated: boolean }) {
  const { tabs, activeTabId } = useUiState()
  const navigate = useNavigate()
  const location = useLocation()
  useEffect(() => {
    if (!hydrated) return
    const active = tabs.find((t) => t.id === activeTabId)
    if (!active) return
    const path = pathForTab(id, active.target)
    if (path !== location.pathname) navigate(path, { replace: true })
  }, [hydrated, id, tabs, activeTabId, navigate, location.pathname])
  return null
}
