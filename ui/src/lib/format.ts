// format.ts — Pure display formatters shared across views.
//
// mtime / ts values from the backend are epoch SECONDS (Path.stat().st_mtime)
// or ISO-8601 strings (run event `ts`). relativeTime accepts either.

/** Coerce an epoch-seconds number or ISO string to epoch milliseconds. */
function toMillis(value: number | string): number {
  if (typeof value === 'number') return value * 1000
  return Date.parse(value)
}

/** Human "2m ago" style delta. `now` is injectable for deterministic tests. */
export function relativeTime(value: number | string, now: number = Date.now()): string {
  const deltaS = Math.max(0, Math.round((now - toMillis(value)) / 1000))
  if (deltaS < 60) return 'now'
  const mins = Math.floor(deltaS / 60)
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

/** Compact file size: bytes under 1 KB, else one-decimal KB/MB. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const kb = bytes / 1024
  if (kb < 1024) return `${kb.toFixed(1)} KB`
  return `${(kb / 1024).toFixed(1)} MB`
}

/** Currency-ish USD display for a cost float (e.g. 1.5 -> "$1.50"). */
export function formatCost(usd: number): string {
  return `$${usd.toFixed(2)}`
}

/** Thousands-grouped integer for tabular cells. */
export function formatCount(n: number): string {
  return n.toLocaleString('en-US')
}

/** "mandate_started" -> "Mandate started" for event labels. */
export function titleCase(name: string): string {
  const spaced = name.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}
