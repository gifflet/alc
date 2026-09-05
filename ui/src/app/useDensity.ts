// useDensity.ts — Bind the density rule to the document.
//
// One place decides density and writes `data-density` onto <html>; every
// component then consumes CSS custom properties (--ui-row-h, --ui-text-body, …).
// No component queries the viewport itself, so there is exactly one rule to
// change and exactly one thing to assert in a test.
import { useEffect, useSyncExternalStore } from 'react'
import { COARSE_QUERY, NARROW_QUERY, WIDE_QUERY, resolveDensity } from './density'
import type { Density } from './density'
import { uiStore, useUiState } from './uiStore'

/**
 * Subscribe to a media query.
 *
 * jsdom (and any non-browser host) may not implement matchMedia at all; there
 * the query is reported as not matching, which lands on `compact` — today's
 * desktop — so tests and SSR degrade to the current behaviour rather than
 * flipping the whole UI into touch mode.
 */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return () => {}
      const list = window.matchMedia(query)
      // Safari < 14 only has the deprecated addListener; support both.
      if (typeof list.addEventListener === 'function') {
        list.addEventListener('change', onChange)
        return () => list.removeEventListener('change', onChange)
      }
      list.addListener(onChange)
      return () => list.removeListener(onChange)
    },
    () => {
      if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
      return window.matchMedia(query).matches
    },
    () => false,
  )
}

/** True when the viewport is too narrow for the IDE grid (see NARROW_QUERY). */
export function useNarrow(): boolean {
  return useMediaQuery(NARROW_QUERY)
}

/** The active density, honouring the operator's persisted override. */
export function useDensity(): Density {
  const { density } = useUiState()
  const coarse = useMediaQuery(COARSE_QUERY)
  const narrow = useNarrow()
  const wide = useMediaQuery(WIDE_QUERY)
  return resolveDensity(density, coarse, narrow, wide)
}

/**
 * Apply the active density to <html>. Mounted once, at the app root.
 *
 * Returns the value it applied so a caller (or a test) can assert without
 * reaching into the DOM.
 */
export function useApplyDensity(): Density {
  const density = useDensity()
  // Written during render for the same reason as the theme: effects flush
  // child-first, so anything reading the resolved token values in an effect
  // must see the attribute already updated.
  if (typeof document !== 'undefined' && document.documentElement.dataset.density !== density) {
    document.documentElement.dataset.density = density
  }
  useEffect(() => {
    document.documentElement.dataset.density = density
  }, [density])
  return density
}

