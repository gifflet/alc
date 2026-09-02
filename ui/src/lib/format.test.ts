import { describe, expect, it } from 'vitest'
import { relativeTime, formatCost } from './format'

describe('relativeTime', () => {
  // mtime values from the backend are epoch SECONDS (Path.stat().st_mtime).
  const now = 1_700_000_000_000 // ms

  it('renders "now" for sub-minute deltas', () => {
    expect(relativeTime(now / 1000 - 5, now)).toBe('now')
  })

  it('renders minutes', () => {
    expect(relativeTime(now / 1000 - 120, now)).toBe('2m ago')
  })

  it('renders hours', () => {
    expect(relativeTime(now / 1000 - 3 * 3600, now)).toBe('3h ago')
  })

  it('renders days', () => {
    expect(relativeTime(now / 1000 - 2 * 86400, now)).toBe('2d ago')
  })

  it('accepts an ISO string', () => {
    const iso = new Date(now - 60_000).toISOString()
    expect(relativeTime(iso, now)).toBe('1m ago')
  })
})

describe('formatCost', () => {
  it('renders a USD cost with two decimals', () => {
    expect(formatCost(1.5)).toBe('$1.50')
  })
  it('rounds to two decimals', () => {
    expect(formatCost(0.999)).toBe('$1.00')
  })
  it('renders a zero cost plainly', () => {
    expect(formatCost(0)).toBe('$0.00')
  })
})
