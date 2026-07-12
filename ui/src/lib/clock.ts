// clock.ts — One shared, lazy interval that drives every relative-time label.
//
// Rendering N rows used to spawn N setInterval timers, each re-rendering its own
// cell on its own schedule. A single module-level clock ticks all subscribers in
// lockstep and only runs while something is mounted — fewer timers, and the tick
// is isolated to the components that read it (their parents never re-render).
import { useSyncExternalStore } from 'react'

const TICK_MS = 30_000

const listeners = new Set<() => void>()
let tick = 0
let timer: ReturnType<typeof setInterval> | null = null

function start(): void {
  if (timer !== null) return
  timer = setInterval(() => {
    tick += 1
    listeners.forEach((l) => l())
  }, TICK_MS)
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  start()
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0 && timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }
}

/** Re-render on a slow shared cadence (every 30s) without a per-instance timer. */
export function useClock(): number {
  return useSyncExternalStore(subscribe, () => tick)
}
