// uiStore.ts — Central UI state (open tabs + panel layout).
//
// A tiny external store consumed via useSyncExternalStore — no redux/zustand.
// State is immutable-replaced on every action so React re-renders reliably.
// Panel sizing/collapse persists to localStorage; open tabs are session-only.
import { useSyncExternalStore } from 'react'
import type { CollectionName } from '../api/types'

export type PrimaryView = 'dashboard' | 'queue' | 'runs' | 'loops'

/** A config file that can be opened as a read-only source viewer. */
export type SourceResource = 'manifest' | CollectionName | 'prompts'

export type TabTarget =
  | { type: 'view'; view: PrimaryView }
  | { type: 'run'; stem: string }
  | { type: 'loop'; name: string }
  | { type: 'source'; resource: SourceResource; name: string }

export interface Tab {
  id: string
  title: string
  target: TabTarget
  closable: boolean
}

export interface UiState {
  tabs: Tab[]
  activeTabId: string | null
  leftWidth: number
  leftCollapsed: boolean
  bottomHeight: number
  bottomCollapsed: boolean
  bottomTab: 'console' | 'problems'
}

const LEFT_MIN = 160
const LEFT_MAX = 600
const BOTTOM_MIN = 100
const BOTTOM_MAX = 500
const PANELS_KEY = 'alc-ui:panels'

/** Stable, unique id for a tab target. */
export function tabId(target: TabTarget): string {
  switch (target.type) {
    case 'view':
      return `view:${target.view}`
    case 'run':
      return `run:${target.stem}`
    case 'loop':
      return `loop:${target.name}`
    case 'source':
      return `source:${target.resource}:${target.name}`
  }
}

interface PersistedPanels {
  leftWidth: number
  leftCollapsed: boolean
  bottomHeight: number
  bottomCollapsed: boolean
  bottomTab: 'console' | 'problems'
}

function loadPanels(): PersistedPanels {
  const fallback: PersistedPanels = {
    leftWidth: 240,
    leftCollapsed: false,
    bottomHeight: 200,
    bottomCollapsed: true,
    bottomTab: 'console',
  }
  try {
    const raw = localStorage.getItem(PANELS_KEY)
    if (!raw) return fallback
    return { ...fallback, ...(JSON.parse(raw) as Partial<PersistedPanels>) }
  } catch {
    return fallback
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function createStore() {
  const listeners = new Set<() => void>()
  let state: UiState = initial()

  function initial(): UiState {
    const panels = loadPanels()
    return { tabs: [], activeTabId: null, ...panels }
  }

  function persistPanels(s: UiState): void {
    try {
      const panels: PersistedPanels = {
        leftWidth: s.leftWidth,
        leftCollapsed: s.leftCollapsed,
        bottomHeight: s.bottomHeight,
        bottomCollapsed: s.bottomCollapsed,
        bottomTab: s.bottomTab,
      }
      localStorage.setItem(PANELS_KEY, JSON.stringify(panels))
    } catch {
      // Storage unavailable (private mode / SSR) — degrade silently.
    }
  }

  function set(next: UiState, persist = false): void {
    state = next
    if (persist) persistPanels(state)
    listeners.forEach((l) => l())
  }

  return {
    getState: (): UiState => state,
    subscribe(listener: () => void): () => void {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    reset(): void {
      set(initial())
    },
    openTab(tab: { target: TabTarget; title: string; closable?: boolean }): void {
      const id = tabId(tab.target)
      const exists = state.tabs.some((t) => t.id === id)
      const tabs = exists
        ? state.tabs
        : [...state.tabs, { id, title: tab.title, target: tab.target, closable: tab.closable ?? true }]
      set({ ...state, tabs, activeTabId: id })
    },
    closeTab(id: string): void {
      const idx = state.tabs.findIndex((t) => t.id === id)
      if (idx === -1) return
      const tabs = state.tabs.filter((t) => t.id !== id)
      let activeTabId = state.activeTabId
      if (activeTabId === id) {
        const neighbour = tabs[idx] ?? tabs[idx - 1] ?? null
        activeTabId = neighbour ? neighbour.id : null
      }
      set({ ...state, tabs, activeTabId })
    },
    setActiveTab(id: string): void {
      set({ ...state, activeTabId: id })
    },
    setLeftWidth(width: number): void {
      set({ ...state, leftWidth: clamp(width, LEFT_MIN, LEFT_MAX) }, true)
    },
    toggleLeft(): void {
      set({ ...state, leftCollapsed: !state.leftCollapsed }, true)
    },
    setBottomHeight(height: number): void {
      set({ ...state, bottomHeight: clamp(height, BOTTOM_MIN, BOTTOM_MAX) }, true)
    },
    toggleBottom(): void {
      set({ ...state, bottomCollapsed: !state.bottomCollapsed }, true)
    },
    setBottomTab(tab: 'console' | 'problems'): void {
      set({ ...state, bottomTab: tab, bottomCollapsed: false }, true)
    },
  }
}

export const uiStore = createStore()

/** Subscribe a component to the whole UI state. */
export function useUiState(): UiState {
  return useSyncExternalStore(uiStore.subscribe, uiStore.getState)
}
