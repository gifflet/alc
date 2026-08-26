// useTheme.ts — Bind the theme to the document.
//
// Same shape as useDensity: one place decides, writes `data-theme` onto <html>,
// and every component keeps consuming semantic tokens. Nothing branches on the
// theme at the component level, which is why light was a values-only change.
import { useEffect } from 'react'
import { useMediaQuery } from './useDensity'
import { uiStore, useUiState } from './uiStore'

export type Theme = 'dark' | 'light'

export const LIGHT_QUERY = '(prefers-color-scheme: light)'

/**
 * The theme to apply: the operator's explicit choice, else the OS preference.
 *
 * Dark is the fallback — it is what the app has always been, and what a host
 * with no matchMedia (jsdom, SSR) should keep rendering.
 */
export function resolveTheme(override: Theme | null, prefersLight: boolean): Theme {
  if (override) return override
  return prefersLight ? 'light' : 'dark'
}

export function useTheme(): Theme {
  const { theme } = useUiState()
  return resolveTheme(theme, useMediaQuery(LIGHT_QUERY))
}

/** Apply the theme to <html>; mounted once, at the app root.
 *
 * The attribute is written during RENDER, not in an effect. React flushes
 * effects child-first, so a descendant that reads the resolved token values
 * (CodeEditor builds Monaco's theme from them) would run BEFORE the root effect
 * and read the previous theme's colours — the editor stayed light on a dark
 * page. Writing it here means every child renders with the attribute already
 * correct. The effect stays as a belt-and-braces for hydration.
 */
export function useApplyTheme(): Theme {
  const theme = useTheme()
  if (typeof document !== 'undefined' && document.documentElement.dataset.theme !== theme) {
    document.documentElement.dataset.theme = theme
  }
  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])
  return theme
}

/** Flip the theme; null returns to following the OS. */
export function setTheme(theme: Theme | null): void {
  uiStore.setTheme(theme)
}
