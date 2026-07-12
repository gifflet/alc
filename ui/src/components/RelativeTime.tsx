// RelativeTime.tsx — "2m ago" that refreshes itself on a slow interval.
import { useEffect, useState } from 'react'
import { relativeTime } from '../lib/format'

export function RelativeTime({ value }: { value: number | string }) {
  const [, tick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 30_000)
    return () => clearInterval(id)
  }, [])
  const iso = typeof value === 'number' ? new Date(value * 1000).toISOString() : value
  return (
    <time dateTime={iso} className="tabular text-muted">
      {relativeTime(value)}
    </time>
  )
}
