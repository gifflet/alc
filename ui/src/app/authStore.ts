// authStore.ts — Whether the server has rejected this browser's token.
//
// A control plane must never misreport project state. Without this, a 401 makes
// every query fail empty and the views render their "nothing here" state — the
// UI would calmly say "Nothing running" while units are in flight. That is the
// one thing it can never do, so an auth failure is surfaced as itself.
import { useSyncExternalStore } from 'react'

let unauthorized = false
const listeners = new Set<() => void>()

function emit(): void {
  listeners.forEach((l) => l())
}

export const authStore = {
  getState: (): boolean => unauthorized,
  subscribe(listener: () => void): () => void {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },
  /** Called from the global query error handler on any 401. */
  setUnauthorized(value: boolean): void {
    if (unauthorized === value) return
    unauthorized = value
    emit()
  },
}

export function useUnauthorized(): boolean {
  return useSyncExternalStore(authStore.subscribe, authStore.getState, () => false)
}
