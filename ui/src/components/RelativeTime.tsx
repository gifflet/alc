// RelativeTime.tsx — "2m ago" that refreshes on a shared, slow clock.
//
// Memoised so a parent re-render (a query refetch, a tab switch) never re-renders
// the label; it only updates when its `value` changes or the shared clock ticks.
import { memo } from 'react'
import { relativeTime } from '../lib/format'
import { useClock } from '../lib/clock'

export const RelativeTime = memo(function RelativeTime({ value }: { value: number | string }) {
  useClock()
  const iso = typeof value === 'number' ? new Date(value * 1000).toISOString() : value
  return (
    <time dateTime={iso} className="tabular text-muted">
      {relativeTime(value)}
    </time>
  )
})
